from __future__ import annotations

from datetime import UTC, datetime, timedelta
import logging
from threading import Event, Thread

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session, sessionmaker

from app.models.runtime_worker import RuntimeWorkerRecord


logger = logging.getLogger(__name__)
JUDGE_VOICE_WORKER_TYPE = "judge_voice_generation"


class RuntimeWorkerTelemetry:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        *,
        worker_id: str,
        heartbeat_seconds: float,
        worker_type: str = JUDGE_VOICE_WORKER_TYPE,
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
