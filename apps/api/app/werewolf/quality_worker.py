from __future__ import annotations

import logging
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from threading import Event

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session, sessionmaker

from app.models.quality_evaluation import GameQualityEvaluationRecord
from app.werewolf.quality_evaluation import evaluate_quality_bundle
from app.werewolf.quality_store import (
    build_database_quality_bundle,
    enqueue_quality_evaluation,
)


logger = logging.getLogger(__name__)


class QualityEvaluationWorker:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        *,
        hmac_key: str,
        lease_seconds: float = 120.0,
        max_attempts: int = 5,
        backoff_seconds: float = 5.0,
    ) -> None:
        if not hmac_key:
            raise ValueError("quality evaluation HMAC key is required")
        self.session_factory = session_factory
        self.hmac_key = hmac_key
        self.lease_seconds = lease_seconds
        self.max_attempts = max_attempts
        self.backoff_seconds = backoff_seconds

    def claim_next_job(
        self,
        *,
        worker_id: str,
        now: datetime | None = None,
    ) -> str | None:
        claimed_at = now or datetime.now(tz=UTC)
        with self.session_factory() as db:
            while True:
                record = db.scalar(
                    select(GameQualityEvaluationRecord)
                    .where(
                        or_(
                            and_(
                                GameQualityEvaluationRecord.status == "pending",
                                GameQualityEvaluationRecord.not_before <= claimed_at,
                            ),
                            and_(
                                GameQualityEvaluationRecord.status == "processing",
                                GameQualityEvaluationRecord.lease_expires_at.is_not(None),
                                GameQualityEvaluationRecord.lease_expires_at <= claimed_at,
                            ),
                        )
                    )
                    .order_by(
                        GameQualityEvaluationRecord.not_before.asc(),
                        GameQualityEvaluationRecord.created_at.asc(),
                        GameQualityEvaluationRecord.id.asc(),
                    )
                    .with_for_update(skip_locked=True)
                    .limit(1)
                )
                if record is None:
                    return None
                if record.attempt_count >= self.max_attempts:
                    _fail_exhausted_job(record, completed_at=claimed_at)
                    db.commit()
                    continue
                break
            record.status = "processing"
            if record.started_at is None:
                record.started_at = claimed_at
            record.worker_id = worker_id
            record.lease_expires_at = claimed_at + timedelta(seconds=self.lease_seconds)
            record.attempt_count += 1
            record.last_error_code = None
            db.commit()
            return record.id

    def renew_lease(
        self,
        evaluation_id: str,
        *,
        worker_id: str,
        now: datetime | None = None,
    ) -> bool:
        renewed_at = now or datetime.now(tz=UTC)
        with self.session_factory() as db:
            record = _owned_processing_job(
                db,
                evaluation_id=evaluation_id,
                worker_id=worker_id,
                at=renewed_at,
                lock=True,
                require_live_lease=True,
            )
            if record is None:
                return False
            record.lease_expires_at = renewed_at + timedelta(seconds=self.lease_seconds)
            db.commit()
            return True

    def process_claimed_job(self, evaluation_id: str, *, worker_id: str) -> bool:
        started_at = time.monotonic()
        try:
            self._evaluate(evaluation_id, worker_id=worker_id, started_at=started_at)
        except Exception as exc:
            logger.warning(
                "Quality evaluation failed",
                extra={"evaluation_id": evaluation_id, "error_type": type(exc).__name__},
            )
            self._release_failed_job(
                evaluation_id,
                worker_id=worker_id,
                error_code=_error_code(exc),
            )
            return False
        return True

    def _evaluate(
        self,
        evaluation_id: str,
        *,
        worker_id: str,
        started_at: float,
    ) -> None:
        observed_at = datetime.now(tz=UTC)
        with self.session_factory() as db:
            record = _owned_processing_job(
                db,
                evaluation_id=evaluation_id,
                worker_id=worker_id,
                at=observed_at,
                lock=False,
                require_live_lease=True,
            )
            if record is None:
                raise RuntimeError("quality evaluation ownership was lost")
            bundle = build_database_quality_bundle(
                db,
                session_id=record.session_id,
                run_id=record.run_id,
            )
            guarded_at = datetime.now(tz=UTC)
            record = _owned_processing_job(
                db,
                evaluation_id=evaluation_id,
                worker_id=worker_id,
                at=guarded_at,
                lock=True,
                require_live_lease=True,
            )
            if record is None:
                raise RuntimeError("quality evaluation ownership was lost")
            if bundle.source_revision != record.source_revision:
                record.status = "superseded"
                record.data_status = "unavailable"
                record.verdict = "unavailable"
                record.worker_id = None
                record.lease_expires_at = None
                record.completed_at = guarded_at
                enqueue_quality_evaluation(
                    db,
                    session_id=record.session_id,
                    run_id=bundle.run_id,
                    evaluator_version=record.evaluator_version,
                )
                db.commit()
                return
            evaluator_version = record.evaluator_version
            record.lease_expires_at = guarded_at + timedelta(seconds=self.lease_seconds)
            db.commit()

        report = evaluate_quality_bundle(
            bundle,
            hmac_key=self.hmac_key,
            evaluator_version=evaluator_version,
            evaluated_at=guarded_at,
        )
        completed_at = datetime.now(tz=UTC)
        with self.session_factory() as db:
            record = _owned_processing_job(
                db,
                evaluation_id=evaluation_id,
                worker_id=worker_id,
                at=completed_at,
                lock=True,
                require_live_lease=True,
            )
            if record is None:
                raise RuntimeError("quality evaluation ownership was lost")
            record.status = "completed"
            record.data_status = report.data_status
            record.verdict = report.verdict
            record.safe_summary = report.to_dict()
            record.max_event_id = bundle.source_coverage.max_event_id
            record.max_voice_source_event_id = (
                bundle.source_coverage.max_voice_source_event_id
            )
            record.worker_id = None
            record.lease_expires_at = None
            record.last_error_code = None
            record.duration_ms = max(0, round((time.monotonic() - started_at) * 1000))
            record.completed_at = completed_at
            db.commit()

    def _release_failed_job(
        self,
        evaluation_id: str,
        *,
        worker_id: str,
        error_code: str,
    ) -> None:
        now = datetime.now(tz=UTC)
        with self.session_factory() as db:
            record = _owned_processing_job(
                db,
                evaluation_id=evaluation_id,
                worker_id=worker_id,
                at=now,
                lock=True,
                require_live_lease=False,
            )
            if record is None:
                return
            terminal = record.attempt_count >= self.max_attempts
            record.status = "failed" if terminal else "pending"
            record.data_status = "unavailable" if terminal else "collecting"
            record.verdict = "unavailable"
            record.worker_id = None
            record.lease_expires_at = None
            record.last_error_code = error_code[:64]
            record.completed_at = now if terminal else None
            record.not_before = now + timedelta(
                seconds=self.backoff_seconds * (2 ** max(0, record.attempt_count - 1))
            )
            db.commit()


def run_quality_evaluation_worker(
    session_factory: sessionmaker[Session],
    *,
    hmac_key: str,
    worker_id: str,
    stop_event: Event,
    poll_seconds: float,
    once: bool,
    lease_seconds: float = 120.0,
    max_attempts: int = 5,
    backoff_seconds: float = 5.0,
    on_job: Callable[[str], None] | None = None,
) -> int:
    worker = QualityEvaluationWorker(
        session_factory,
        hmac_key=hmac_key,
        lease_seconds=lease_seconds,
        max_attempts=max_attempts,
        backoff_seconds=backoff_seconds,
    )
    processed_count = 0
    while not stop_event.is_set():
        evaluation_id = worker.claim_next_job(worker_id=worker_id)
        if evaluation_id is None:
            if once:
                break
            stop_event.wait(poll_seconds)
            continue
        if on_job is not None:
            on_job(evaluation_id)
        worker.process_claimed_job(evaluation_id, worker_id=worker_id)
        processed_count += 1
        if once:
            break
    return processed_count


def _error_code(exc: Exception) -> str:
    known = {
        "QualityEvaluationSourceUnavailable": "source_unavailable",
        "ValueError": "invalid_evaluation_input",
        "RuntimeError": "worker_state_error",
    }
    return known.get(type(exc).__name__, "evaluation_failed")


def _fail_exhausted_job(
    record: GameQualityEvaluationRecord,
    *,
    completed_at: datetime,
) -> None:
    """Terminalize a crashed/retryable job without erasing success lineage."""

    record.status = "failed"
    record.data_status = "unavailable"
    record.verdict = "unavailable"
    record.worker_id = None
    record.lease_expires_at = None
    record.last_error_code = "lease_expired_max_attempts"
    record.completed_at = completed_at


def _owned_processing_job(
    db: Session,
    *,
    evaluation_id: str,
    worker_id: str,
    at: datetime,
    lock: bool,
    require_live_lease: bool,
) -> GameQualityEvaluationRecord | None:
    conditions = [
        GameQualityEvaluationRecord.id == evaluation_id,
        GameQualityEvaluationRecord.status == "processing",
        GameQualityEvaluationRecord.worker_id == worker_id,
    ]
    if require_live_lease:
        conditions.append(GameQualityEvaluationRecord.lease_expires_at > at)
    statement = (
        select(GameQualityEvaluationRecord)
        .where(*conditions)
        .execution_options(populate_existing=True)
    )
    if lock:
        statement = statement.with_for_update()
    return db.scalar(statement)
