from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Any

from sqlalchemy import case, select
from sqlalchemy.orm import Session

from app.models.game_session import GameReplayPayload, GameSessionRecord
from app.models.live import LiveEventRecord, LiveRunRecord, VoiceUtteranceRecord
from app.models.quality_evaluation import GameQualityEvaluationRecord
from app.werewolf.evaluation_bundle import (
    QualityEvaluationBundleV1,
    build_quality_evaluation_bundle,
)
from app.werewolf.quality_evaluation import DEFAULT_EVALUATOR_VERSION


class QualityEvaluationSourceUnavailable(RuntimeError):
    pass


def build_database_quality_bundle(
    db: Session,
    *,
    session_id: str,
    run_id: str | None = None,
) -> QualityEvaluationBundleV1:
    payload = db.get(GameReplayPayload, session_id)
    if payload is None or not isinstance(payload.state, dict) or not isinstance(payload.logs, list):
        raise QualityEvaluationSourceUnavailable("quality evaluation replay is unavailable")
    run_record = (
        db.get(LiveRunRecord, run_id)
        if run_id
        else db.scalar(
            select(LiveRunRecord)
            .where(LiveRunRecord.session_id == session_id)
            .order_by(LiveRunRecord.completed_at.desc(), LiveRunRecord.created_at.desc())
            .limit(1)
        )
    )
    if run_record is not None and run_record.session_id != session_id:
        raise QualityEvaluationSourceUnavailable("quality evaluation run does not match session")
    effective_run_id = run_record.run_id if run_record is not None else None
    events: list[dict[str, Any]] = []
    voices: list[dict[str, Any]] = []
    if effective_run_id:
        event_records = list(
            db.scalars(
                select(LiveEventRecord)
                .where(LiveEventRecord.run_id == effective_run_id)
                .order_by(LiveEventRecord.event_id.asc())
            )
        )
        events = [_event_dict(record) for record in event_records]
        voice_records = list(
            db.scalars(
                select(VoiceUtteranceRecord)
                .where(VoiceUtteranceRecord.run_id == effective_run_id)
                .order_by(
                    VoiceUtteranceRecord.source_event_id.asc(),
                    VoiceUtteranceRecord.utterance_id.asc(),
                )
            )
        )
        voices = [_voice_dict(record) for record in voice_records]
    return build_quality_evaluation_bundle(
        state=payload.state,
        logs=[item for item in payload.logs if isinstance(item, dict)],
        live_events=events,
        voice_utterances=voices,
        run_id=str(effective_run_id) if effective_run_id else None,
        started_at=(
            _format_datetime(run_record.started_at) if run_record is not None else None
        ),
        completed_at=(
            _format_datetime(run_record.completed_at) if run_record is not None else None
        ),
    )


def enqueue_quality_evaluation(
    db: Session,
    *,
    session_id: str,
    run_id: str | None = None,
    evaluator_version: str = DEFAULT_EVALUATOR_VERSION,
) -> GameQualityEvaluationRecord:
    bundle = build_database_quality_bundle(db, session_id=session_id, run_id=run_id)
    existing = db.scalar(
        select(GameQualityEvaluationRecord).where(
            GameQualityEvaluationRecord.session_id == session_id,
            GameQualityEvaluationRecord.evaluator_version == evaluator_version,
            GameQualityEvaluationRecord.source_revision == bundle.source_revision,
        )
    )
    if existing is not None:
        return existing
    record = GameQualityEvaluationRecord(
        id=_quality_evaluation_id(session_id, evaluator_version, bundle.source_revision),
        session_id=session_id,
        run_id=bundle.run_id,
        evaluator_version=evaluator_version,
        source_revision=bundle.source_revision,
        status="pending",
        data_status="collecting",
        verdict="unavailable",
        safe_summary={},
        max_event_id=bundle.source_coverage.max_event_id,
        max_voice_source_event_id=bundle.source_coverage.max_voice_source_event_id,
    )
    db.add(record)
    db.flush()
    return record


def enqueue_recent_missing_evaluations(
    db: Session,
    *,
    evaluator_version: str,
    session_id: str | None = None,
    since: datetime | None = None,
    limit: int = 100,
    dry_run: bool = True,
) -> dict[str, int]:
    bounded_limit = min(1000, max(1, limit))
    query = select(GameSessionRecord.session_id).where(GameSessionRecord.status == "complete")
    if session_id:
        query = query.where(GameSessionRecord.session_id == session_id)
    if since:
        query = query.where(GameSessionRecord.updated_at >= since)
    candidates = list(
        db.scalars(
            query.order_by(GameSessionRecord.updated_at.desc()).limit(bounded_limit)
        )
    )
    matched = 0
    enqueued = 0
    skipped = 0
    for candidate in candidates:
        matched += 1
        try:
            bundle = build_database_quality_bundle(db, session_id=candidate)
        except QualityEvaluationSourceUnavailable:
            skipped += 1
            continue
        existing = db.scalar(
            select(GameQualityEvaluationRecord.id).where(
                GameQualityEvaluationRecord.session_id == candidate,
                GameQualityEvaluationRecord.evaluator_version == evaluator_version,
                GameQualityEvaluationRecord.source_revision == bundle.source_revision,
            )
        )
        if existing:
            skipped += 1
            continue
        enqueued += 1
        if not dry_run:
            enqueue_quality_evaluation(
                db,
                session_id=candidate,
                run_id=bundle.run_id,
                evaluator_version=evaluator_version,
            )
    return {"matched": matched, "enqueued": enqueued, "skipped": skipped}


def latest_quality_evaluation(
    db: Session,
    *,
    session_id: str,
) -> GameQualityEvaluationRecord | None:
    return db.scalar(
        select(GameQualityEvaluationRecord)
        .where(GameQualityEvaluationRecord.session_id == session_id)
        .order_by(
            case(
                (
                    GameQualityEvaluationRecord.status.in_(("pending", "processing")),
                    0,
                ),
                else_=1,
            ),
            GameQualityEvaluationRecord.created_at.desc(),
            GameQualityEvaluationRecord.id.desc(),
        )
        .limit(1)
    )


def _quality_evaluation_id(session_id: str, version: str, revision: str) -> str:
    digest = hashlib.sha256(f"{session_id}:{version}:{revision}".encode()).hexdigest()[:24]
    return f"quality_{digest}"


def _event_dict(record: LiveEventRecord) -> dict[str, Any]:
    return {
        "id": record.event_id,
        "type": record.type,
        "run_id": record.run_id,
        "session_id": record.session_id,
        "created_at": _format_datetime(record.created_at),
        "round": record.round,
        "phase": record.phase,
        "actor": record.actor,
        "action": record.action,
        "payload": record.payload if isinstance(record.payload, dict) else {},
    }


def _voice_dict(record: VoiceUtteranceRecord) -> dict[str, Any]:
    return {
        "utterance_id": record.utterance_id,
        "run_id": record.run_id,
        "session_id": record.session_id,
        "source_event_id": record.source_event_id,
        "last_source_event_id": record.last_source_event_id,
        "speaker_kind": record.speaker_kind,
        "action": record.action,
        "status": record.status,
        "text": record.text,
        "subtitle_timings": (
            record.subtitle_timings if isinstance(record.subtitle_timings, list) else []
        ),
    }


def _format_datetime(value: datetime | None) -> str:
    return value.isoformat() if value is not None else ""
