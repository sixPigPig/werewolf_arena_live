from __future__ import annotations

from datetime import UTC, datetime, timedelta
import logging
from threading import Event, Thread

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session, sessionmaker

from app.models.live import LiveRunRecord
from app.models.runtime_worker import RuntimeWorkerRecord
from app.werewolf.orphan_reaper import OrphanRecoveryResult


logger = logging.getLogger(__name__)
REAPER_WORKER_TYPE = "live_run_reaper"
JUDGE_VOICE_WORKER_TYPE = "judge_voice_generation"
QUALITY_EVALUATION_WORKER_TYPE = "quality_evaluation"


class RuntimeWorkerTelemetry:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        *,
        worker_id: str,
        heartbeat_seconds: float,
        worker_type: str = REAPER_WORKER_TYPE,
    ) -> None:
        self.session_factory = session_factory
        self.worker_id = worker_id
        self.heartbeat_seconds = heartbeat_seconds
        self.worker_type = worker_type
        self._stop_event = Event()
        self._thread: Thread | None = None

    def start(self) -> None:
        now = datetime.now(tz=UTC)
        with self.session_factory() as db:
            record = db.get(RuntimeWorkerRecord, self.worker_id)
            if record is None:
                record = RuntimeWorkerRecord(
                    worker_id=self.worker_id,
                    worker_type=self.worker_type,
                    status="running",
                    started_at=now,
                    heartbeat_at=now,
                )
                db.add(record)
            else:
                record.status = "running"
                record.started_at = now
                record.heartbeat_at = now
                record.stopped_at = None
            db.commit()
        self._thread = Thread(
            target=self._heartbeat_loop,
            daemon=True,
            name=f"runtime-worker-heartbeat-{self.worker_id}",
        )
        self._thread.start()

    def record_scan(self) -> None:
        self._update(
            scans_total=RuntimeWorkerRecord.scans_total + 1,
            status="running",
        )

    def record_recovery(self, result: OrphanRecoveryResult) -> None:
        counters = {
            "resumed": RuntimeWorkerRecord.recoveries_resumed_total,
            "canceled": RuntimeWorkerRecord.recoveries_canceled_total,
            "failed": RuntimeWorkerRecord.recoveries_failed_total,
        }
        column = counters[result.outcome]
        self._update(**{column.key: column + 1, "status": "running"})

    def record_error(self, code: str = "scan_failed") -> None:
        self._update(
            errors_total=RuntimeWorkerRecord.errors_total + 1,
            last_error_code=code[:64],
            status="degraded",
        )

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=max(1.0, self.heartbeat_seconds + 1.0))
        now = datetime.now(tz=UTC)
        try:
            with self.session_factory() as db:
                db.execute(
                    update(RuntimeWorkerRecord)
                    .where(RuntimeWorkerRecord.worker_id == self.worker_id)
                    .values(status="stopped", stopped_at=now, heartbeat_at=now)
                    .execution_options(synchronize_session=False)
                )
                db.commit()
        except Exception:
            logger.exception("Failed to persist runtime worker shutdown")

    def _heartbeat_loop(self) -> None:
        while not self._stop_event.wait(self.heartbeat_seconds):
            try:
                self._update()
            except Exception:
                logger.exception("Failed to persist runtime worker heartbeat")

    def _update(self, **values: object) -> None:
        values["heartbeat_at"] = datetime.now(tz=UTC)
        with self.session_factory() as db:
            result = db.execute(
                update(RuntimeWorkerRecord)
                .where(RuntimeWorkerRecord.worker_id == self.worker_id)
                .values(**values)
                .execution_options(synchronize_session=False)
            )
            if result.rowcount != 1:
                db.rollback()
                raise RuntimeError("runtime worker heartbeat record missing")
            db.commit()


def live_run_reaper_is_alive(
    db: Session,
    *,
    max_age_seconds: float,
) -> bool:
    return runtime_worker_is_alive(
        db,
        worker_type=REAPER_WORKER_TYPE,
        max_age_seconds=max_age_seconds,
    )


def runtime_worker_is_alive(
    db: Session,
    *,
    worker_type: str,
    max_age_seconds: float,
) -> bool:
    cutoff = datetime.now(tz=UTC) - timedelta(seconds=max_age_seconds)
    return bool(
        db.scalar(
            select(func.count())
            .select_from(RuntimeWorkerRecord)
            .where(
                RuntimeWorkerRecord.worker_type == worker_type,
                RuntimeWorkerRecord.status.in_(("running", "degraded")),
                RuntimeWorkerRecord.heartbeat_at >= cutoff,
            )
        )
    )


def render_live_run_metrics(
    db: Session,
    *,
    reaper_max_age_seconds: float,
    stale_grace_seconds: float,
    max_attempts: int,
) -> str:
    now = datetime.now(tz=UTC)
    cutoff = now - timedelta(seconds=reaper_max_age_seconds)
    stale_before = now - timedelta(seconds=stale_grace_seconds)
    workers = list(
        db.scalars(
            select(RuntimeWorkerRecord).where(
                RuntimeWorkerRecord.worker_type == REAPER_WORKER_TYPE
            )
        )
    )
    active_workers = [
        worker
        for worker in workers
        if worker.status in {"running", "degraded"}
        and _as_utc(worker.heartbeat_at) >= cutoff
    ]
    stale_filter = (
        LiveRunRecord.status.in_(("queued", "running")),
        (
            (LiveRunRecord.lease_expires_at <= stale_before)
            | (
                LiveRunRecord.lease_expires_at.is_(None)
                & (LiveRunRecord.created_at <= stale_before)
            )
        ),
    )
    stale_total = _count(db, *stale_filter)
    exhausted_total = _count(
        db,
        *stale_filter,
        LiveRunRecord.recovery_attempts >= max_attempts,
    )
    backoff_total = _count(
        db,
        *stale_filter,
        LiveRunRecord.recovery_attempts < max_attempts,
        LiveRunRecord.recovery_not_before > now,
    )
    values = {
        "up": 1 if active_workers else 0,
        "workers": len(active_workers),
        "scans": sum(worker.scans_total for worker in workers),
        "resumed": sum(worker.recoveries_resumed_total for worker in workers),
        "canceled": sum(worker.recoveries_canceled_total for worker in workers),
        "failed": sum(worker.recoveries_failed_total for worker in workers),
        "errors": sum(worker.errors_total for worker in workers),
        "stale": stale_total,
        "backoff": backoff_total,
        "exhausted": exhausted_total,
    }
    return _prometheus_text(values)


def _count(db: Session, *filters: object) -> int:
    return int(
        db.scalar(select(func.count()).select_from(LiveRunRecord).where(*filters)) or 0
    )


def _prometheus_text(values: dict[str, int]) -> str:
    return "\n".join(
        [
            "# HELP werewolf_live_run_reaper_up Whether a reaper heartbeat is fresh.",
            "# TYPE werewolf_live_run_reaper_up gauge",
            f"werewolf_live_run_reaper_up {values['up']}",
            "# HELP werewolf_live_run_reaper_workers Fresh reaper worker instances.",
            "# TYPE werewolf_live_run_reaper_workers gauge",
            f"werewolf_live_run_reaper_workers {values['workers']}",
            "# HELP werewolf_live_run_reaper_scans_total Reaper scans recorded.",
            "# TYPE werewolf_live_run_reaper_scans_total counter",
            f"werewolf_live_run_reaper_scans_total {values['scans']}",
            "# HELP werewolf_live_run_reaper_recoveries_total Recovery outcomes.",
            "# TYPE werewolf_live_run_reaper_recoveries_total counter",
            f'werewolf_live_run_reaper_recoveries_total{{outcome="resumed"}} {values["resumed"]}',
            f'werewolf_live_run_reaper_recoveries_total{{outcome="canceled"}} {values["canceled"]}',
            f'werewolf_live_run_reaper_recoveries_total{{outcome="failed"}} {values["failed"]}',
            "# HELP werewolf_live_run_reaper_errors_total Reaper scan errors.",
            "# TYPE werewolf_live_run_reaper_errors_total counter",
            f"werewolf_live_run_reaper_errors_total {values['errors']}",
            "# HELP werewolf_live_run_orphans_stale Stale active live runs.",
            "# TYPE werewolf_live_run_orphans_stale gauge",
            f"werewolf_live_run_orphans_stale {values['stale']}",
            "# HELP werewolf_live_run_orphans_backoff Stale runs waiting for retry backoff.",
            "# TYPE werewolf_live_run_orphans_backoff gauge",
            f"werewolf_live_run_orphans_backoff {values['backoff']}",
            "# HELP werewolf_live_run_recovery_exhausted Stale runs requiring manual action.",
            "# TYPE werewolf_live_run_recovery_exhausted gauge",
            f"werewolf_live_run_recovery_exhausted {values['exhausted']}",
            "",
        ]
    )


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
