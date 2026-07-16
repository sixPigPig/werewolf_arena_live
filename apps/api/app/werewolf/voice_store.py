from __future__ import annotations

import base64
import hashlib
import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.models.live import (
    LiveEventRecord,
    VoiceAudioChunkRecord,
    VoiceMaterializationJobRecord,
    VoiceUtteranceRecord,
)
from app.core.config import settings
from app.werewolf.voice import VoiceUtterance, chunk_text_for_tts

TERMINAL_STATUSES = {"complete", "failed", "canceled"}
PCM_BYTES_PER_SAMPLE = 2
logger = logging.getLogger(__name__)


def text_hash_for_voice(
    *,
    speaker: str,
    audio_format: str,
    sample_rate: int,
    text: str,
) -> str:
    payload = "\0".join((speaker, audio_format, str(sample_rate), text))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class DatabaseVoiceStore:
    def __init__(self, db: Session, *, session_id: str) -> None:
        self.db = db
        self.session_id = session_id

    def upsert_utterance(
        self,
        utterance: VoiceUtterance,
        *,
        audio_format: str,
        sample_rate: int,
        mime_type: str,
        status: str = "synthesizing",
    ) -> None:
        last_source_event_id = _last_source_event_id(utterance)
        text_hash = text_hash_for_voice(
            speaker=utterance.speaker,
            audio_format=audio_format,
            sample_rate=sample_rate,
            text=utterance.text,
        )
        record = self.db.get(VoiceUtteranceRecord, utterance.utterance_id)
        if record is None:
            record = VoiceUtteranceRecord(
                utterance_id=utterance.utterance_id,
                run_id=utterance.run_id,
                session_id=self.session_id,
                audience=utterance.audience,
                source_event_id=utterance.source_event_id,
                last_source_event_id=last_source_event_id,
                request_id=utterance.request_id,
                speaker_kind=utterance.speaker_kind,
                speaker_name=utterance.speaker_name,
                speaker=utterance.speaker,
                action=utterance.action,
                text=utterance.text,
                text_hash=text_hash,
                audio_format=audio_format,
                sample_rate=sample_rate,
                mime_type=mime_type,
                status=status,
            )
            self.db.add(record)
        else:
            if last_source_event_id < record.last_source_event_id:
                return
            _raise_for_incompatible_upsert(
                record,
                utterance,
                session_id=self.session_id,
                audio_format=audio_format,
                sample_rate=sample_rate,
                mime_type=mime_type,
            )
            if record.status in TERMINAL_STATUSES:
                return
            record.last_source_event_id = max(
                record.last_source_event_id,
                last_source_event_id,
            )
            record.text = utterance.text
            record.text_hash = text_hash
            if status not in TERMINAL_STATUSES:
                record.status = status
        self._commit()

    def append_chunk(self, utterance_id: str, *, chunk_index: int, audio: bytes) -> None:
        existing = self.db.get(VoiceAudioChunkRecord, (utterance_id, chunk_index))
        if existing is not None:
            if bytes(existing.audio) != audio:
                raise ValueError(f"Voice chunk {utterance_id}:{chunk_index} has incompatible audio")
            return
        self.db.add(
            VoiceAudioChunkRecord(
                utterance_id=utterance_id,
                chunk_index=chunk_index,
                audio=audio,
                byte_length=len(audio),
            )
        )
        self._commit()

    def reset_incomplete_utterance(self, utterance_id: str) -> None:
        record = self.db.get(VoiceUtteranceRecord, utterance_id)
        if record is None or record.status == "complete":
            return
        self.db.query(VoiceAudioChunkRecord).filter(
            VoiceAudioChunkRecord.utterance_id == utterance_id
        ).delete(synchronize_session=False)
        self.db.delete(record)
        self._commit()

    def complete_utterance(
        self,
        utterance_id: str,
        *,
        duration_ms: int,
        satisfy_materialization_jobs: bool = False,
    ) -> None:
        record = self.db.get(VoiceUtteranceRecord, utterance_id)
        if record is None:
            return
        if record.status in TERMINAL_STATUSES:
            return
        completed_at = datetime.now(tz=UTC)
        record.status = "complete"
        record.duration_ms = duration_ms
        record.error_message = None
        record.completed_at = completed_at
        has_audio = (
            self.db.query(VoiceAudioChunkRecord.utterance_id)
            .filter(VoiceAudioChunkRecord.utterance_id == utterance_id)
            .first()
            is not None
        )
        if satisfy_materialization_jobs and has_audio:
            self.db.query(VoiceMaterializationJobRecord).filter(
                VoiceMaterializationJobRecord.run_id == record.run_id,
                VoiceMaterializationJobRecord.session_id == self.session_id,
                VoiceMaterializationJobRecord.audience == record.audience,
                VoiceMaterializationJobRecord.speaker_kind == record.speaker_kind,
                VoiceMaterializationJobRecord.source_event_id >= record.source_event_id,
                VoiceMaterializationJobRecord.source_event_id <= record.last_source_event_id,
                VoiceMaterializationJobRecord.status == "pending",
            ).update(
                {
                    VoiceMaterializationJobRecord.status: "complete",
                    VoiceMaterializationJobRecord.last_error: None,
                    VoiceMaterializationJobRecord.completed_at: completed_at,
                    VoiceMaterializationJobRecord.updated_at: completed_at,
                },
                synchronize_session=False,
            )
        self._commit()
        self._enqueue_quality_refresh()

    def fail_utterance(self, utterance_id: str, *, message: str) -> None:
        record = self.db.get(VoiceUtteranceRecord, utterance_id)
        if record is None:
            return
        if record.status in TERMINAL_STATUSES:
            return
        record.status = "failed"
        record.error_message = message
        record.completed_at = datetime.now(tz=UTC)
        self._commit()
        self._enqueue_quality_refresh()

    def update_subtitle_timings(
        self,
        utterance_id: str,
        *,
        subtitle_timings: list[dict[str, Any]],
    ) -> None:
        record = self.db.get(VoiceUtteranceRecord, utterance_id)
        if record is None:
            return
        if record.status in TERMINAL_STATUSES:
            return
        cues = _normalize_subtitle_timings(subtitle_timings)
        if not cues:
            return
        record.subtitle_timings = _merge_subtitle_timings(
            _normalize_subtitle_timings(record.subtitle_timings or []),
            cues,
        )
        self._commit()

    def load_utterance(self, utterance_id: str) -> dict[str, Any] | None:
        record = self.db.get(VoiceUtteranceRecord, utterance_id)
        if record is None:
            return None
        return _utterance_record_to_dict(record)

    def load_chunks(self, utterance_id: str) -> list[bytes]:
        rows = (
            self.db.query(VoiceAudioChunkRecord)
            .filter(VoiceAudioChunkRecord.utterance_id == utterance_id)
            .order_by(VoiceAudioChunkRecord.chunk_index.asc())
            .all()
        )
        return [row.audio for row in rows]

    def load_playback_voice(
        self,
        utterance_id: str,
        *,
        excluded_actions: frozenset[str] = frozenset(),
        allowed_audiences: frozenset[str] = frozenset({"player_public"}),
    ) -> dict[str, Any] | None:
        record = (
            self.db.query(VoiceUtteranceRecord)
            .filter(
                VoiceUtteranceRecord.utterance_id == utterance_id,
                VoiceUtteranceRecord.session_id == self.session_id,
                VoiceUtteranceRecord.audience.in_(allowed_audiences),
                VoiceUtteranceRecord.status == "complete",
                VoiceUtteranceRecord.speaker_kind.in_(("player", "judge")),
                VoiceUtteranceRecord.sample_rate > 0,
            )
            .first()
        )
        if record is None or record.action in excluded_actions:
            return None
        chunks = (
            self.db.query(VoiceAudioChunkRecord)
            .filter(VoiceAudioChunkRecord.utterance_id == utterance_id)
            .order_by(VoiceAudioChunkRecord.chunk_index.asc())
            .all()
        )
        if not chunks:
            return None
        return _playback_voice_from_record(record, chunks=chunks)

    def list_playback_voices(
        self,
        *,
        excluded_actions: frozenset[str] = frozenset(),
        allowed_audiences: frozenset[str] = frozenset({"player_public"}),
        include_chunks: bool = True,
    ) -> list[dict[str, Any]]:
        if not include_chunks:
            audio_lengths = (
                self.db.query(
                    VoiceAudioChunkRecord.utterance_id.label("utterance_id"),
                    func.sum(VoiceAudioChunkRecord.byte_length).label("audio_byte_length"),
                )
                .group_by(VoiceAudioChunkRecord.utterance_id)
                .subquery()
            )
            rows = (
                self.db.query(
                    VoiceUtteranceRecord,
                    audio_lengths.c.audio_byte_length,
                )
                .join(
                    audio_lengths,
                    audio_lengths.c.utterance_id == VoiceUtteranceRecord.utterance_id,
                )
                .filter(
                    VoiceUtteranceRecord.session_id == self.session_id,
                    VoiceUtteranceRecord.audience.in_(allowed_audiences),
                    VoiceUtteranceRecord.status == "complete",
                    VoiceUtteranceRecord.speaker_kind.in_(("player", "judge")),
                    VoiceUtteranceRecord.sample_rate > 0,
                )
                .order_by(
                    VoiceUtteranceRecord.source_event_id.asc(),
                    VoiceUtteranceRecord.utterance_id.asc(),
                )
                .all()
            )
            return [
                _playback_voice_from_record(
                    utterance,
                    audio_byte_length=int(audio_byte_length or 0),
                    include_chunks=False,
                )
                for utterance, audio_byte_length in rows
                if utterance.action not in excluded_actions
            ]

        rows = (
            self.db.query(VoiceUtteranceRecord, VoiceAudioChunkRecord)
            .join(
                VoiceAudioChunkRecord,
                VoiceAudioChunkRecord.utterance_id == VoiceUtteranceRecord.utterance_id,
            )
            .filter(
                VoiceUtteranceRecord.session_id == self.session_id,
                VoiceUtteranceRecord.audience.in_(allowed_audiences),
                VoiceUtteranceRecord.status == "complete",
                VoiceUtteranceRecord.speaker_kind.in_(("player", "judge")),
                VoiceUtteranceRecord.sample_rate > 0,
            )
            .order_by(
                VoiceUtteranceRecord.source_event_id.asc(),
                VoiceUtteranceRecord.utterance_id.asc(),
                VoiceAudioChunkRecord.chunk_index.asc(),
            )
            .all()
        )

        voices_by_id: dict[str, dict[str, Any]] = {}
        for utterance, chunk in rows:
            if utterance.action in excluded_actions:
                continue
            voice = voices_by_id.setdefault(
                utterance.utterance_id,
                {
                    "utterance_id": utterance.utterance_id,
                    "run_id": utterance.run_id,
                    "audience": utterance.audience,
                    "source_event_id": utterance.source_event_id,
                    "last_source_event_id": utterance.last_source_event_id,
                    "speaker_kind": utterance.speaker_kind,
                    "speaker_name": utterance.speaker_name,
                    "mime_type": utterance.mime_type,
                    "audio_format": utterance.audio_format,
                    "sample_rate": utterance.sample_rate,
                    "duration_ms": utterance.duration_ms,
                    "subtitle_timings": utterance.subtitle_timings or [],
                    "_audio_byte_length": 0,
                    "_text": utterance.text,
                    "chunks": [],
                },
            )
            voice["_audio_byte_length"] += chunk.byte_length
            voice["chunks"].append(
                {
                    "chunk_index": chunk.chunk_index,
                    "data": base64.b64encode(chunk.audio).decode("ascii"),
                }
            )
        voices = list(voices_by_id.values())
        for voice in voices:
            text = str(voice.pop("_text", "") or "")
            audio_byte_length = int(voice.pop("_audio_byte_length", 0) or 0)
            voice["subtitle_timings"] = _playback_subtitle_timings(
                subtitle_timings=voice["subtitle_timings"],
                text=text,
                audio_format=str(voice["audio_format"]),
                sample_rate=int(voice["sample_rate"]),
                audio_byte_length=audio_byte_length,
            )
        return voices

    def max_materialization_lag_ms(
        self,
        *,
        allowed_audiences: frozenset[str] = frozenset({"player_public"}),
    ) -> int | None:
        rows = self.db.execute(
            self.db.query(
                VoiceUtteranceRecord.completed_at,
                LiveEventRecord.created_at,
            )
            .join(
                LiveEventRecord,
                (LiveEventRecord.run_id == VoiceUtteranceRecord.run_id)
                & (LiveEventRecord.event_id == VoiceUtteranceRecord.source_event_id),
            )
            .filter(
                VoiceUtteranceRecord.session_id == self.session_id,
                VoiceUtteranceRecord.audience.in_(allowed_audiences),
                VoiceUtteranceRecord.status == "complete",
                VoiceUtteranceRecord.completed_at.is_not(None),
            )
            .statement
        ).all()
        lags = [
            max(0, int((_as_utc(completed_at) - _as_utc(created_at)).total_seconds() * 1000))
            for completed_at, created_at in rows
            if completed_at is not None and created_at is not None
        ]
        return max(lags) if lags else None

    def find_recent_utterance(
        self,
        *,
        run_id: str,
        current_event_id: int,
        audience: str = "player_public",
    ) -> dict[str, Any] | None:
        record = (
            self.db.query(VoiceUtteranceRecord)
            .join(
                VoiceAudioChunkRecord,
                VoiceAudioChunkRecord.utterance_id == VoiceUtteranceRecord.utterance_id,
            )
            .filter(
                VoiceUtteranceRecord.run_id == run_id,
                VoiceUtteranceRecord.audience == audience,
                VoiceUtteranceRecord.last_source_event_id <= current_event_id,
                VoiceUtteranceRecord.status == "complete",
                VoiceUtteranceRecord.speaker_kind.in_(("player", "judge")),
                VoiceUtteranceRecord.sample_rate > 0,
            )
            .order_by(VoiceUtteranceRecord.last_source_event_id.desc())
            .first()
        )
        if record is None:
            return None
        return _utterance_record_to_dict(record)

    def _commit(self) -> None:
        try:
            self.db.commit()
        except SQLAlchemyError:
            self.db.rollback()
            raise

    def _enqueue_quality_refresh(self) -> None:
        if not settings.quality_evaluation_enabled:
            return
        try:
            from app.werewolf.quality_store import enqueue_quality_evaluation

            enqueue_quality_evaluation(
                self.db,
                session_id=self.session_id,
                evaluator_version=settings.quality_evaluation_version,
            )
            self.db.commit()
        except Exception as exc:
            self.db.rollback()
            logger.warning(
                "Quality evaluation refresh enqueue failed after voice terminal state",
                extra={
                    "session_id": self.session_id,
                    "error_type": type(exc).__name__,
                },
            )


def _utterance_record_to_dict(record: VoiceUtteranceRecord) -> dict[str, Any]:
    return {
        "utterance_id": record.utterance_id,
        "run_id": record.run_id,
        "session_id": record.session_id,
        "audience": record.audience,
        "source_event_id": record.source_event_id,
        "last_source_event_id": record.last_source_event_id,
        "request_id": record.request_id,
        "speaker_kind": record.speaker_kind,
        "speaker_name": record.speaker_name,
        "speaker": record.speaker,
        "action": record.action,
        "text": record.text,
        "text_hash": record.text_hash,
        "audio_format": record.audio_format,
        "sample_rate": record.sample_rate,
        "mime_type": record.mime_type,
        "status": record.status,
        "duration_ms": record.duration_ms,
        "subtitle_timings": record.subtitle_timings or [],
        "error_message": record.error_message,
        "created_at": record.created_at,
        "updated_at": record.updated_at,
        "completed_at": record.completed_at,
    }


def _playback_voice_from_record(
    record: VoiceUtteranceRecord,
    *,
    chunks: list[VoiceAudioChunkRecord] | None = None,
    audio_byte_length: int | None = None,
    include_chunks: bool = True,
) -> dict[str, Any]:
    resolved_chunks = chunks or []
    resolved_audio_byte_length = (
        audio_byte_length
        if audio_byte_length is not None
        else sum(chunk.byte_length for chunk in resolved_chunks)
    )
    voice = {
        "utterance_id": record.utterance_id,
        "run_id": record.run_id,
        "audience": record.audience,
        "source_event_id": record.source_event_id,
        "last_source_event_id": record.last_source_event_id,
        "speaker_kind": record.speaker_kind,
        "speaker_name": record.speaker_name,
        "mime_type": record.mime_type,
        "audio_format": record.audio_format,
        "sample_rate": record.sample_rate,
        "duration_ms": record.duration_ms,
        "subtitle_timings": _playback_subtitle_timings(
            subtitle_timings=record.subtitle_timings or [],
            text=record.text,
            audio_format=record.audio_format,
            sample_rate=record.sample_rate,
            audio_byte_length=resolved_audio_byte_length,
        ),
    }
    if include_chunks:
        voice["chunks"] = [
            {
                "chunk_index": chunk.chunk_index,
                "data": base64.b64encode(chunk.audio).decode("ascii"),
            }
            for chunk in resolved_chunks
        ]
    return voice


def _last_source_event_id(utterance: VoiceUtterance) -> int:
    if utterance.last_source_event_id is None:
        return utterance.source_event_id
    return max(utterance.source_event_id, utterance.last_source_event_id)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _normalize_subtitle_timings(value: list[dict[str, Any]]) -> list[dict[str, Any]]:
    cues: list[dict[str, Any]] = []
    for cue in value:
        text = cue.get("text")
        start_ms = cue.get("start_ms")
        end_ms = cue.get("end_ms")
        if (
            isinstance(text, str)
            and isinstance(start_ms, int)
            and isinstance(end_ms, int)
            and end_ms > start_ms
        ):
            cues.append({"text": text, "start_ms": start_ms, "end_ms": end_ms})
    return cues


def _merge_subtitle_timings(
    current: list[dict[str, Any]],
    incoming: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    cues_by_key: dict[tuple[int, int, str], dict[str, Any]] = {}
    for cue in [*current, *incoming]:
        key = (cue["start_ms"], cue["end_ms"], cue["text"])
        cues_by_key[key] = cue
    return sorted(
        cues_by_key.values(),
        key=lambda cue: (cue["start_ms"], cue["end_ms"], cue["text"]),
    )


def _playback_subtitle_timings(
    *,
    subtitle_timings: list[dict[str, Any]],
    text: str,
    audio_format: str,
    sample_rate: int,
    audio_byte_length: int,
) -> list[dict[str, Any]]:
    normalized_text = _normalize_subtitle_text(text)
    if not normalized_text:
        return subtitle_timings

    normalized_timing_text = _normalize_subtitle_text(
        "".join(str(cue.get("text", "")) for cue in subtitle_timings)
    )
    if subtitle_timings and normalized_timing_text == normalized_text:
        return subtitle_timings

    duration_ms = _pcm_audio_duration_ms(
        audio_format=audio_format,
        sample_rate=sample_rate,
        audio_byte_length=audio_byte_length,
    )
    return _approximate_subtitle_timings(text, duration_ms=duration_ms)


def _normalize_subtitle_text(value: str) -> str:
    return "".join(value.split())


def _pcm_audio_duration_ms(
    *,
    audio_format: str,
    sample_rate: int,
    audio_byte_length: int,
) -> int:
    if audio_format.lower() != "pcm" or sample_rate <= 0 or audio_byte_length <= 0:
        return 0
    return max(
        1,
        round(audio_byte_length / (sample_rate * PCM_BYTES_PER_SAMPLE) * 1000),
    )


def _approximate_subtitle_timings(
    text: str,
    *,
    duration_ms: int,
) -> list[dict[str, Any]]:
    chunks = chunk_text_for_tts(text, max_chars=8)
    if not chunks:
        return []

    resolved_duration_ms = duration_ms if duration_ms > 0 else max(800, len(text) * 180)
    weights = [max(1, len(chunk)) for chunk in chunks]
    total_weight = sum(weights)
    elapsed_ms = 0
    cues: list[dict[str, Any]] = []
    for index, (chunk, weight) in enumerate(zip(chunks, weights, strict=True)):
        if index == len(chunks) - 1:
            end_ms = resolved_duration_ms
        else:
            end_ms = round(resolved_duration_ms * sum(weights[: index + 1]) / total_weight)
        if end_ms <= elapsed_ms:
            end_ms = elapsed_ms + 1
        cues.append({"text": chunk, "start_ms": elapsed_ms, "end_ms": end_ms})
        elapsed_ms = end_ms
    return cues


def _raise_for_incompatible_upsert(
    record: VoiceUtteranceRecord,
    utterance: VoiceUtterance,
    *,
    session_id: str,
    audio_format: str,
    sample_rate: int,
    mime_type: str,
) -> None:
    comparisons = (
        ("run_id", record.run_id, utterance.run_id),
        ("session_id", record.session_id, session_id),
        ("audience", record.audience, utterance.audience),
        ("request_id", record.request_id, utterance.request_id),
        ("speaker_kind", record.speaker_kind, utterance.speaker_kind),
        ("speaker_name", record.speaker_name, utterance.speaker_name),
        ("speaker", record.speaker, utterance.speaker),
        ("action", record.action, utterance.action),
        ("audio_format", record.audio_format, audio_format),
        ("sample_rate", record.sample_rate, sample_rate),
        ("mime_type", record.mime_type, mime_type),
    )
    mismatches = [name for name, existing, incoming in comparisons if existing != incoming]
    if mismatches:
        fields = ", ".join(mismatches)
        raise ValueError(
            f"Incompatible voice utterance upsert for {utterance.utterance_id}: {fields}"
        )
