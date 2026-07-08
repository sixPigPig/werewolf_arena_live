from __future__ import annotations

import base64
import hashlib
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.models.live import VoiceAudioChunkRecord, VoiceUtteranceRecord
from app.werewolf.voice import VoiceUtterance

TERMINAL_STATUSES = {"complete", "failed", "canceled"}


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
                source_event_id=utterance.source_event_id,
                last_source_event_id=utterance.source_event_id,
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
            if utterance.source_event_id < record.last_source_event_id:
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
                utterance.source_event_id,
            )
            record.text = utterance.text
            record.text_hash = text_hash
            if status not in TERMINAL_STATUSES:
                record.status = status
        self._commit()

    def append_chunk(self, utterance_id: str, *, chunk_index: int, audio: bytes) -> None:
        self.db.add(
            VoiceAudioChunkRecord(
                utterance_id=utterance_id,
                chunk_index=chunk_index,
                audio=audio,
                byte_length=len(audio),
            )
        )
        self._commit()

    def complete_utterance(self, utterance_id: str, *, duration_ms: int) -> None:
        record = self.db.get(VoiceUtteranceRecord, utterance_id)
        if record is None:
            return
        if record.status in TERMINAL_STATUSES:
            return
        record.status = "complete"
        record.duration_ms = duration_ms
        record.error_message = None
        record.completed_at = datetime.now(tz=UTC)
        self._commit()

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

    def list_playback_voices(self) -> list[dict[str, Any]]:
        rows = (
            self.db.query(VoiceUtteranceRecord, VoiceAudioChunkRecord)
            .join(
                VoiceAudioChunkRecord,
                VoiceAudioChunkRecord.utterance_id == VoiceUtteranceRecord.utterance_id,
            )
            .filter(
                VoiceUtteranceRecord.session_id == self.session_id,
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
            voice = voices_by_id.setdefault(
                utterance.utterance_id,
                {
                    "utterance_id": utterance.utterance_id,
                    "source_event_id": utterance.source_event_id,
                    "last_source_event_id": utterance.last_source_event_id,
                    "speaker_kind": utterance.speaker_kind,
                    "speaker_name": utterance.speaker_name,
                    "mime_type": utterance.mime_type,
                    "audio_format": utterance.audio_format,
                    "sample_rate": utterance.sample_rate,
                    "duration_ms": utterance.duration_ms,
                    "chunks": [],
                },
            )
            voice["chunks"].append(
                {
                    "chunk_index": chunk.chunk_index,
                    "data": base64.b64encode(chunk.audio).decode("ascii"),
                }
            )
        return list(voices_by_id.values())

    def find_recent_utterance(
        self,
        *,
        run_id: str,
        current_event_id: int,
    ) -> dict[str, Any] | None:
        record = (
            self.db.query(VoiceUtteranceRecord)
            .join(
                VoiceAudioChunkRecord,
                VoiceAudioChunkRecord.utterance_id == VoiceUtteranceRecord.utterance_id,
            )
            .filter(
                VoiceUtteranceRecord.run_id == run_id,
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


def _utterance_record_to_dict(record: VoiceUtteranceRecord) -> dict[str, Any]:
    return {
        "utterance_id": record.utterance_id,
        "run_id": record.run_id,
        "session_id": record.session_id,
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
        "error_message": record.error_message,
        "created_at": record.created_at,
        "updated_at": record.updated_at,
        "completed_at": record.completed_at,
    }


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
