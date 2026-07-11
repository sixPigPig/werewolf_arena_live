from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings
from app.judge_voice_asset_import import import_judge_voice_assets
from app.models.judge_voice_asset import JudgeVoiceAssetRecord, JudgeVoiceGenerationJob
from app.werewolf.judge_voice_assets import generate_judge_voice_assets, list_judge_voice_line_definitions
from app.werewolf.volcengine_tts import VolcengineTtsConfig


def create_voice_generation_job(
    db: Session,
    *,
    actor_user_id: int,
    mode: str,
    line_ids: list[str] | None,
    idempotency_key: str,
) -> tuple[JudgeVoiceGenerationJob, bool]:
    normalized_ids = sorted(set(line_ids or [])) or None
    request_hash = hashlib.sha256(
        json.dumps({"mode": mode, "line_ids": normalized_ids}, sort_keys=True).encode()
    ).hexdigest()
    existing = db.scalar(
        select(JudgeVoiceGenerationJob).where(
            JudgeVoiceGenerationJob.actor_user_id == actor_user_id,
            JudgeVoiceGenerationJob.idempotency_key == idempotency_key,
        )
    )
    if existing is not None:
        if existing.request_hash != request_hash:
            raise ValueError("idempotency_conflict")
        return existing, False
    job = JudgeVoiceGenerationJob(
        id=str(uuid4()),
        actor_user_id=actor_user_id,
        mode=mode,
        requested_line_ids=normalized_ids,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
        status="queued",
    )
    db.add(job)
    db.flush()
    return job, True


def run_next_voice_generation_job(session_factory: sessionmaker[Session]) -> str | None:
    with session_factory() as db:
        stale_before = datetime.now(tz=UTC) - timedelta(minutes=15)
        for stale in db.scalars(
            select(JudgeVoiceGenerationJob).where(
                JudgeVoiceGenerationJob.status == "running",
                JudgeVoiceGenerationJob.updated_at < stale_before,
            )
        ):
            stale.status = "queued"
            stale.started_at = None
        job = db.scalar(
            select(JudgeVoiceGenerationJob)
            .where(JudgeVoiceGenerationJob.status == "queued")
            .order_by(JudgeVoiceGenerationJob.created_at, JudgeVoiceGenerationJob.id)
            .with_for_update(skip_locked=True)
        )
        if job is None:
            db.commit()
            return None
        job.status = "running"
        job.started_at = datetime.now(tz=UTC)
        job.updated_at = job.started_at
        job_id = job.id
        db.commit()

    _execute_job(session_factory, job_id)
    return job_id


def run_voice_generation_worker(
    session_factory: sessionmaker[Session],
    *,
    stop_event: Event,
    poll_seconds: float,
    once: bool = False,
    on_job: Callable[[str], None] | None = None,
) -> int:
    """Continuously drain queued jobs until signalled to stop."""
    processed_count = 0
    while not stop_event.is_set():
        job_id = run_next_voice_generation_job(session_factory)
        if job_id is not None:
            processed_count += 1
            if on_job is not None:
                on_job(job_id)
        if once:
            break
        if job_id is None:
            stop_event.wait(poll_seconds)
    return processed_count


def _execute_job(session_factory: sessionmaker[Session], job_id: str) -> None:
    with session_factory() as db:
        job = db.get(JudgeVoiceGenerationJob, job_id)
        if job is None:
            return
        definitions = list_judge_voice_line_definitions()
        by_id = {line.id: line for line in definitions}
        requested = job.requested_line_ids or list(by_id)
        if any(line_id not in by_id for line_id in requested):
            _fail(job, "unknown_line_id")
            db.commit()
            return
        existing_ids = set(db.scalars(select(JudgeVoiceAssetRecord.id)))
        selected = [line_id for line_id in requested if job.mode == "all" or line_id not in existing_ids]
        job.total_count = len(selected)
        if not selected:
            job.status = "completed"
            job.completed_at = datetime.now(tz=UTC)
            db.commit()
            return
        config = _judge_config()
        if not config.available:
            job.failed_count = len(selected)
            _fail(job, f"tts_{config.unavailable_reason or 'unavailable'}")
            db.commit()
            return
        try:
            with TemporaryDirectory(prefix="judge-voice-job-") as directory:
                result = asyncio.run(
                    generate_judge_voice_assets(
                        config=config,
                        asset_dir=Path(directory),
                        line_ids=selected,
                        force=True,
                    )
                )
                imported = import_judge_voice_assets(
                    asset_dir=Path(directory),
                    audio_format=config.audio_format,
                    sample_rate=config.sample_rate,
                    db=db,
                )
            job.generated_count = len(result.generated_ids)
            job.skipped_count = imported.reused_count
            job.processed_count = job.generated_count + job.skipped_count
            job.status = "completed"
            job.completed_at = datetime.now(tz=UTC)
            db.commit()
        except Exception:
            db.rollback()
            job = db.get(JudgeVoiceGenerationJob, job_id)
            if job is not None:
                job.failed_count = max(1, job.total_count - job.processed_count)
                _fail(job, "generation_failed")
                db.commit()


def _fail(job: JudgeVoiceGenerationJob, code: str) -> None:
    job.status = "failed"
    job.error_code = code
    job.completed_at = datetime.now(tz=UTC)


def _judge_config() -> VolcengineTtsConfig:
    return VolcengineTtsConfig(
        enabled=settings.ark_tts_enabled,
        api_key=settings.ark_tts_api_key,
        resource_id=settings.ark_tts_resource_id,
        ws_url=settings.ark_tts_ws_url,
        player_speaker=settings.ark_tts_player_speaker,
        judge_speaker=settings.ark_tts_judge_speaker,
        audio_format=settings.ark_tts_judge_asset_audio_format,
        sample_rate=settings.ark_tts_judge_asset_sample_rate,
    )
