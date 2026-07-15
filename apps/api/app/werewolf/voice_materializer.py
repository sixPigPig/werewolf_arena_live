from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
import logging
from threading import Event
from typing import Any

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.orm import Session, sessionmaker

from app.models.judge_voice_asset import JudgeVoiceAssetRecord
from app.models.live import (
    LiveEventRecord,
    PublicLiveEventRecord,
    VoiceAudioChunkRecord,
    VoiceMaterializationJobRecord,
    VoiceUtteranceRecord,
)
from app.werewolf.judge_voice_assets import DEFAULT_JUDGE_VOICE_ASSET_DIR
from app.werewolf.live import LiveEvent
from app.werewolf.live_store import format_live_datetime
from app.werewolf.privacy_projection import project_live_event
from app.werewolf.voice import (
    VoiceSpeakerConfig,
    VoiceUtterance,
    chunk_text_for_tts,
    deterministic_voice_utterance_id,
    event_to_voice_materialization,
)
from app.werewolf.voice_store import DatabaseVoiceStore
from app.werewolf.voice_stream import (
    StaticJudgeVoiceAsset,
    load_static_judge_voice_asset,
)
from app.werewolf.volcengine_tts import (
    TtsSubtitleTiming,
    VolcengineTtsClient,
    VolcengineTtsConfig,
    mime_type_for_format,
)


logger = logging.getLogger(__name__)
LIVE_VOICE_MATERIALIZER_WORKER_TYPE = "live_voice_materializer"


class PermanentVoiceMaterializationError(RuntimeError):
    pass


class VoiceMaterializer:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        *,
        config: VolcengineTtsConfig,
        lease_seconds: float = 120.0,
        max_attempts: int = 4,
        backoff_seconds: float = 5.0,
        client_factory: Callable[[VolcengineTtsConfig], Any] = VolcengineTtsClient,
        asset_loader: Callable[[Session, str], StaticJudgeVoiceAsset | None] | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.config = config
        self.lease_seconds = lease_seconds
        self.max_attempts = max_attempts
        self.backoff_seconds = backoff_seconds
        self.client_factory = client_factory
        self.asset_loader = asset_loader or _load_static_asset

    def claim_next_job(
        self,
        *,
        worker_id: str,
        now: datetime | None = None,
    ) -> tuple[str, int, str] | None:
        claimed_at = now or datetime.now(tz=UTC)
        with self.session_factory() as db:
            job = db.scalar(
                select(VoiceMaterializationJobRecord)
                .where(
                    or_(
                        and_(
                            VoiceMaterializationJobRecord.status == "pending",
                            VoiceMaterializationJobRecord.not_before <= claimed_at,
                        ),
                        and_(
                            VoiceMaterializationJobRecord.status == "processing",
                            VoiceMaterializationJobRecord.lease_expires_at.is_not(None),
                            VoiceMaterializationJobRecord.lease_expires_at <= claimed_at,
                        ),
                    )
                )
                .order_by(
                    VoiceMaterializationJobRecord.not_before.asc(),
                    VoiceMaterializationJobRecord.created_at.asc(),
                    VoiceMaterializationJobRecord.run_id.asc(),
                    VoiceMaterializationJobRecord.source_event_id.asc(),
                )
                .with_for_update(skip_locked=True)
                .limit(1)
            )
            if job is None:
                return None
            job.status = "processing"
            job.worker_id = worker_id
            job.lease_expires_at = claimed_at + timedelta(seconds=self.lease_seconds)
            job.attempt_count += 1
            job.last_error = None
            db.commit()
            return (job.run_id, job.source_event_id, job.speaker_kind)

    async def process_claimed_job(
        self,
        key: tuple[str, int, str],
        *,
        worker_id: str,
    ) -> bool:
        try:
            await self._materialize(key, worker_id=worker_id)
        except Exception as exc:
            logger.warning(
                "Live voice materialization failed",
                extra={
                    "run_id": key[0],
                    "source_event_id": key[1],
                    "speaker_kind": key[2],
                    "error_type": type(exc).__name__,
                },
            )
            self._release_failed_job(
                key,
                worker_id=worker_id,
                error_type=type(exc).__name__,
                permanent=isinstance(exc, PermanentVoiceMaterializationError),
            )
            return False
        self._complete_job(key, worker_id=worker_id)
        return True

    async def _materialize(
        self,
        key: tuple[str, int, str],
        *,
        worker_id: str,
    ) -> None:
        run_id, source_event_id, speaker_kind = key
        utterance_id = deterministic_voice_utterance_id(
            run_id,
            source_event_id,
            speaker_kind,  # type: ignore[arg-type]
        )
        with self.session_factory() as db:
            job = db.get(VoiceMaterializationJobRecord, key)
            if job is None or job.status != "processing" or job.worker_id != worker_id:
                raise PermanentVoiceMaterializationError("voice job ownership was lost")
            if job.audience != "player_public":
                raise PermanentVoiceMaterializationError("voice job audience is unsupported")
            if _complete_utterance_exists(db, utterance_id):
                return

            event_record = db.get(PublicLiveEventRecord, (run_id, source_event_id))
            if event_record is not None:
                event = _live_event(event_record)
            else:
                canonical_record = db.get(LiveEventRecord, (run_id, source_event_id))
                event = (
                    project_live_event(_live_event(canonical_record), "player_public")
                    if canonical_record is not None
                    else None
                )
            if event is None:
                raise PermanentVoiceMaterializationError("source event is missing")
            player_seats, previous_night_deaths, peaceful_night = _voice_context(
                db,
                event,
            )
            utterance = event_to_voice_materialization(
                event,
                VoiceSpeakerConfig(
                    player_speaker=self.config.player_speaker,
                    judge_speaker=self.config.judge_speaker,
                ),
                player_seats=player_seats,
                previous_night_deaths=previous_night_deaths,
                peaceful_night=peaceful_night,
            )
            if utterance is None or utterance.speaker_kind != speaker_kind:
                raise PermanentVoiceMaterializationError("source event is no longer narratable")
            if _equivalent_complete_voice_exists(db, utterance):
                return

            store = DatabaseVoiceStore(db, session_id=job.session_id)
            store.reset_incomplete_utterance(utterance.utterance_id)
            asset = (
                self.asset_loader(db, utterance.static_asset_id)
                if utterance.static_asset_id
                else None
            )
            if asset is not None:
                self._persist_static(store, utterance, asset)
                return
            await self._persist_dynamic(store, utterance)

    def _persist_static(
        self,
        store: DatabaseVoiceStore,
        utterance: VoiceUtterance,
        asset: StaticJudgeVoiceAsset,
    ) -> None:
        store.upsert_utterance(
            utterance,
            audio_format=asset.audio_format,
            sample_rate=asset.sample_rate,
            mime_type=asset.mime_type,
        )
        if asset.subtitle_timings:
            store.update_subtitle_timings(
                utterance.utterance_id,
                subtitle_timings=asset.subtitle_timings,
            )
        store.append_chunk(utterance.utterance_id, chunk_index=0, audio=asset.audio)
        store.complete_utterance(
            utterance.utterance_id,
            duration_ms=_asset_duration_ms(asset),
        )

    async def _persist_dynamic(
        self,
        store: DatabaseVoiceStore,
        utterance: VoiceUtterance,
    ) -> None:
        if not self.config.available:
            raise RuntimeError("TTS configuration is unavailable")
        text_chunks = chunk_text_for_tts(utterance.text)
        if not text_chunks:
            raise PermanentVoiceMaterializationError("voice text is empty")

        audio_format = self.config.audio_format
        sample_rate = self.config.sample_rate
        store.upsert_utterance(
            utterance,
            audio_format=audio_format,
            sample_rate=sample_rate,
            mime_type=mime_type_for_format(audio_format),
        )
        client = self.client_factory(self.config)
        audio_bytes = 0
        chunk_index = 0
        max_subtitle_end_ms = 0
        async for item in client.synthesize(
            speaker=utterance.speaker,
            text_chunks=text_chunks,
        ):
            if isinstance(item, TtsSubtitleTiming):
                subtitle_timings = [
                    {
                        "text": cue.text,
                        "start_ms": cue.start_ms,
                        "end_ms": cue.end_ms,
                    }
                    for cue in item.cues
                ]
                if subtitle_timings:
                    max_subtitle_end_ms = max(
                        max_subtitle_end_ms,
                        max(cue["end_ms"] for cue in subtitle_timings),
                    )
                    store.update_subtitle_timings(
                        utterance.utterance_id,
                        subtitle_timings=subtitle_timings,
                    )
                continue
            if not isinstance(item, bytes) or not item:
                continue
            store.append_chunk(
                utterance.utterance_id,
                chunk_index=chunk_index,
                audio=item,
            )
            chunk_index += 1
            audio_bytes += len(item)
        if audio_bytes == 0:
            raise RuntimeError("TTS returned no audio")
        duration_ms = max(
            max_subtitle_end_ms,
            _audio_duration_ms(
                audio_format=audio_format,
                sample_rate=sample_rate,
                audio_bytes=audio_bytes,
            ),
        )
        store.complete_utterance(utterance.utterance_id, duration_ms=duration_ms)

    def _complete_job(self, key: tuple[str, int, str], *, worker_id: str) -> None:
        now = datetime.now(tz=UTC)
        with self.session_factory() as db:
            result = db.execute(
                update(VoiceMaterializationJobRecord)
                .where(
                    VoiceMaterializationJobRecord.run_id == key[0],
                    VoiceMaterializationJobRecord.source_event_id == key[1],
                    VoiceMaterializationJobRecord.speaker_kind == key[2],
                    VoiceMaterializationJobRecord.status == "processing",
                    VoiceMaterializationJobRecord.worker_id == worker_id,
                )
                .values(
                    status="complete",
                    worker_id=None,
                    lease_expires_at=None,
                    last_error=None,
                    completed_at=now,
                    updated_at=now,
                )
                .execution_options(synchronize_session=False)
            )
            if result.rowcount != 1:
                db.rollback()
                raise RuntimeError("voice job completion lost ownership")
            db.commit()

    def _release_failed_job(
        self,
        key: tuple[str, int, str],
        *,
        worker_id: str,
        error_type: str,
        permanent: bool,
    ) -> None:
        now = datetime.now(tz=UTC)
        with self.session_factory() as db:
            job = db.get(VoiceMaterializationJobRecord, key)
            if job is None or job.status != "processing" or job.worker_id != worker_id:
                return
            terminal = permanent or job.attempt_count >= self.max_attempts
            job.status = "failed" if terminal else "pending"
            job.worker_id = None
            job.lease_expires_at = None
            job.last_error = error_type[:120]
            job.completed_at = now if terminal else None
            job.not_before = now + timedelta(
                seconds=self.backoff_seconds * (2 ** max(0, job.attempt_count - 1))
            )
            db.commit()


def run_voice_materializer_worker(
    session_factory: sessionmaker[Session],
    *,
    config: VolcengineTtsConfig,
    worker_id: str,
    stop_event: Event,
    poll_seconds: float,
    once: bool,
    lease_seconds: float = 120.0,
    max_attempts: int = 4,
    backoff_seconds: float = 5.0,
    on_job: Callable[[tuple[str, int, str]], None] | None = None,
) -> int:
    materializer = VoiceMaterializer(
        session_factory,
        config=config,
        lease_seconds=lease_seconds,
        max_attempts=max_attempts,
        backoff_seconds=backoff_seconds,
    )
    processed_count = 0
    while not stop_event.is_set():
        key = materializer.claim_next_job(worker_id=worker_id)
        if key is None:
            if once:
                break
            stop_event.wait(poll_seconds)
            continue
        if on_job is not None:
            on_job(key)
        asyncio.run(materializer.process_claimed_job(key, worker_id=worker_id))
        processed_count += 1
        if once:
            break
    return processed_count


def _load_static_asset(db: Session, asset_id: str) -> StaticJudgeVoiceAsset | None:
    record = db.get(JudgeVoiceAssetRecord, asset_id)
    if record is not None and record.data:
        return StaticJudgeVoiceAsset(
            audio=bytes(record.data),
            audio_format=record.audio_format,
            mime_type=record.mime_type,
            sample_rate=record.sample_rate,
            subtitle_timings=(
                record.subtitle_timings if isinstance(record.subtitle_timings, list) else []
            ),
        )
    return load_static_judge_voice_asset(DEFAULT_JUDGE_VOICE_ASSET_DIR, asset_id)


def _complete_utterance_exists(db: Session, utterance_id: str) -> bool:
    chunk_count = db.scalar(
        select(func.count(VoiceAudioChunkRecord.chunk_index)).where(
            VoiceAudioChunkRecord.utterance_id == utterance_id
        )
    )
    record = db.get(VoiceUtteranceRecord, utterance_id)
    return record is not None and record.status == "complete" and bool(chunk_count)


def _equivalent_complete_voice_exists(
    db: Session,
    utterance: VoiceUtterance,
) -> bool:
    query = (
        select(VoiceUtteranceRecord)
        .join(
            VoiceAudioChunkRecord,
            VoiceAudioChunkRecord.utterance_id == VoiceUtteranceRecord.utterance_id,
        )
        .where(
            VoiceUtteranceRecord.run_id == utterance.run_id,
            VoiceUtteranceRecord.speaker_kind == utterance.speaker_kind,
            VoiceUtteranceRecord.status == "complete",
        )
    )
    if utterance.request_id is not None:
        query = query.where(VoiceUtteranceRecord.request_id == utterance.request_id)
    else:
        query = query.where(
            VoiceUtteranceRecord.source_event_id <= utterance.source_event_id,
            VoiceUtteranceRecord.last_source_event_id >= utterance.source_event_id,
        )
    records = list(
        db.scalars(
            query.order_by(
                VoiceUtteranceRecord.source_event_id.asc(),
                VoiceUtteranceRecord.utterance_id.asc(),
            )
        ).unique()
    )
    return bool(records) and _normalized_voice_text(
        "".join(record.text for record in records)
    ) == _normalized_voice_text(utterance.text)


def _normalized_voice_text(text: str) -> str:
    return "".join(text.split())


def _live_event(record: LiveEventRecord | PublicLiveEventRecord) -> LiveEvent:
    return LiveEvent(
        id=record.event_id,
        type=record.type,
        run_id=record.run_id,
        session_id=record.session_id,
        created_at=format_live_datetime(record.created_at),
        round=record.round,
        phase=record.phase,
        actor=record.actor,
        action=record.action,
        payload=record.payload if isinstance(record.payload, dict) else {},
    )


def _voice_context(
    db: Session,
    event: LiveEvent,
) -> tuple[dict[str, int], tuple[str, ...], bool]:
    projected_records = list(
        db.scalars(
            select(PublicLiveEventRecord)
            .where(
                PublicLiveEventRecord.run_id == event.run_id,
                PublicLiveEventRecord.event_id <= event.id,
            )
            .order_by(PublicLiveEventRecord.event_id.asc())
        )
    )
    records: list[LiveEventRecord | PublicLiveEventRecord] = projected_records
    if not records:
        records = list(
            db.scalars(
                select(LiveEventRecord)
                .where(
                    LiveEventRecord.run_id == event.run_id,
                    LiveEventRecord.event_id <= event.id,
                )
                .order_by(LiveEventRecord.event_id.asc())
            )
        )
    player_seats: dict[str, int] = {}
    previous_night_deaths: tuple[str, ...] = ()
    peaceful_night = False
    for record in records:
        projected = (
            _live_event(record)
            if isinstance(record, PublicLiveEventRecord)
            else project_live_event(_live_event(record), "player_public")
        )
        if projected is None:
            continue
        payload = projected.payload
        if projected.type == "game_started":
            players = payload.get("players")
            if isinstance(players, list):
                player_seats = {
                    str(player["name"]): index
                    for index, player in enumerate(players, start=1)
                    if isinstance(player, dict) and isinstance(player.get("name"), str)
                }
        if projected.type == "state_updated" and projected.phase == "night":
            deaths = payload.get("night_deaths")
            if isinstance(deaths, list):
                names = [
                    str(death.get("player"))
                    for death in deaths
                    if isinstance(death, dict) and death.get("player")
                ]
                previous_night_deaths = tuple(names)
                peaceful_night = not names
    return player_seats, previous_night_deaths, peaceful_night


def _asset_duration_ms(asset: StaticJudgeVoiceAsset) -> int:
    timed_duration = max(
        (
            int(cue.get("end_ms", 0))
            for cue in asset.subtitle_timings
            if isinstance(cue, dict)
        ),
        default=0,
    )
    return max(
        timed_duration,
        _audio_duration_ms(
            audio_format=asset.audio_format,
            sample_rate=asset.sample_rate,
            audio_bytes=len(asset.audio),
        ),
    )


def _audio_duration_ms(*, audio_format: str, sample_rate: int, audio_bytes: int) -> int:
    if audio_format.lower() in {"pcm", "s16le"} and sample_rate > 0:
        return max(1, int(audio_bytes / (sample_rate * 2) * 1000))
    return 0
