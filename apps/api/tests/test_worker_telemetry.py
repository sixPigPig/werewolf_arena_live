from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.models.runtime_worker import RuntimeWorkerRecord
from app.shared.worker_telemetry import (
    JUDGE_VOICE_WORKER_TYPE,
    RuntimeWorkerTelemetry,
    runtime_worker_is_alive,
)


def _session_factory() -> sessionmaker[Session]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)


def test_worker_telemetry_records_heartbeat_counters_errors_and_shutdown() -> None:
    session_factory = _session_factory()
    telemetry = RuntimeWorkerTelemetry(
        session_factory,
        worker_id="worker-voice-test",
        heartbeat_seconds=60,
    )

    telemetry.start()
    telemetry.record_scan()
    telemetry.record_error("scan_failed")

    with session_factory() as db:
        record = db.get(RuntimeWorkerRecord, "worker-voice-test")
        assert record is not None
        assert record.worker_type == JUDGE_VOICE_WORKER_TYPE
        assert record.status == "degraded"
        assert record.scans_total == 1
        assert record.errors_total == 1
        assert record.last_error_code == "scan_failed"
        assert runtime_worker_is_alive(
            db,
            worker_type=JUDGE_VOICE_WORKER_TYPE,
            max_age_seconds=45,
        ) is True

    telemetry.record_scan()
    telemetry.stop()

    with session_factory() as db:
        record = db.get(RuntimeWorkerRecord, "worker-voice-test")
        assert record is not None
        assert record.status == "stopped"
        assert record.stopped_at is not None
        assert record.scans_total == 2
        assert runtime_worker_is_alive(
            db,
            worker_type=JUDGE_VOICE_WORKER_TYPE,
            max_age_seconds=45,
        ) is False


def test_probe_rejects_an_expired_heartbeat() -> None:
    session_factory = _session_factory()
    old = datetime.now(tz=UTC) - timedelta(minutes=5)
    with session_factory() as db:
        db.add(
            RuntimeWorkerRecord(
                worker_id="worker-old",
                worker_type=JUDGE_VOICE_WORKER_TYPE,
                status="running",
                started_at=old,
                heartbeat_at=old,
            )
        )
        db.commit()
        assert runtime_worker_is_alive(
            db,
            worker_type=JUDGE_VOICE_WORKER_TYPE,
            max_age_seconds=45,
        ) is False


def test_runtime_worker_probe_is_scoped_to_the_requested_worker_type() -> None:
    session_factory = _session_factory()
    telemetry = RuntimeWorkerTelemetry(
        session_factory,
        worker_id="worker-voice-test",
        worker_type=JUDGE_VOICE_WORKER_TYPE,
        heartbeat_seconds=60,
    )

    telemetry.start()
    try:
        with session_factory() as db:
            record = db.get(RuntimeWorkerRecord, "worker-voice-test")
            assert record is not None
            assert record.worker_type == JUDGE_VOICE_WORKER_TYPE
            assert (
                runtime_worker_is_alive(
                    db,
                    worker_type=JUDGE_VOICE_WORKER_TYPE,
                    max_age_seconds=45,
                )
                is True
            )
            assert (
                runtime_worker_is_alive(
                    db,
                    worker_type="other_worker",
                    max_age_seconds=45,
                )
                is False
            )
    finally:
        telemetry.stop()
