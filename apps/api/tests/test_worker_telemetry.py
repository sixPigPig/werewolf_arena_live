from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.models.live import LiveRunRecord
from app.models.runtime_worker import RuntimeWorkerRecord
from app.werewolf.orphan_reaper import OrphanRecoveryResult
from app.werewolf.worker_telemetry import (
    JUDGE_VOICE_WORKER_TYPE,
    RuntimeWorkerTelemetry,
    live_run_reaper_is_alive,
    render_live_run_metrics,
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
        worker_id="worker-reaper-test",
        heartbeat_seconds=60,
    )

    telemetry.start()
    telemetry.record_scan()
    telemetry.record_recovery(
        OrphanRecoveryResult(
            run_id="run_123456789abc",
            session_id="game_1234abcd",
            attempt=1,
            outcome="resumed",
        )
    )
    telemetry.record_error("scan_failed")

    with session_factory() as db:
        record = db.get(RuntimeWorkerRecord, "worker-reaper-test")
        assert record is not None
        assert record.status == "degraded"
        assert record.scans_total == 1
        assert record.recoveries_resumed_total == 1
        assert record.recoveries_canceled_total == 0
        assert record.errors_total == 1
        assert record.last_error_code == "scan_failed"
        assert live_run_reaper_is_alive(db, max_age_seconds=45) is True

    telemetry.record_scan()
    telemetry.stop()

    with session_factory() as db:
        record = db.get(RuntimeWorkerRecord, "worker-reaper-test")
        assert record is not None
        assert record.status == "stopped"
        assert record.stopped_at is not None
        assert record.scans_total == 2
        assert live_run_reaper_is_alive(db, max_age_seconds=45) is False


def test_metrics_are_aggregated_and_do_not_expose_runtime_identifiers() -> None:
    session_factory = _session_factory()
    now = datetime.now(tz=UTC)
    with session_factory() as db:
        db.add(
            RuntimeWorkerRecord(
                worker_id="worker-secret-id",
                worker_type="live_run_reaper",
                status="running",
                started_at=now,
                heartbeat_at=now,
                scans_total=5,
                recoveries_resumed_total=2,
                recoveries_canceled_total=1,
                recoveries_failed_total=1,
                errors_total=3,
            )
        )
        db.add_all(
            [
                _stale_run(
                    run_id="run_111111111111",
                    session_id="game_11111111",
                    now=now,
                    attempts=1,
                    not_before=now + timedelta(minutes=1),
                ),
                _stale_run(
                    run_id="run_222222222222",
                    session_id="game_22222222",
                    now=now,
                    attempts=3,
                ),
            ]
        )
        db.commit()

        metrics = render_live_run_metrics(
            db,
            reaper_max_age_seconds=45,
            stale_grace_seconds=30,
            max_attempts=3,
        )

    assert "werewolf_live_run_reaper_up 1" in metrics
    assert "werewolf_live_run_reaper_scans_total 5" in metrics
    assert 'werewolf_live_run_reaper_recoveries_total{outcome="resumed"} 2' in metrics
    assert "werewolf_live_run_reaper_errors_total 3" in metrics
    assert "werewolf_live_run_orphans_stale 2" in metrics
    assert "werewolf_live_run_orphans_backoff 1" in metrics
    assert "werewolf_live_run_recovery_exhausted 1" in metrics
    assert "worker-secret-id" not in metrics
    assert "run_111111111111" not in metrics
    assert "game_11111111" not in metrics


def test_probe_rejects_an_expired_heartbeat() -> None:
    session_factory = _session_factory()
    old = datetime.now(tz=UTC) - timedelta(minutes=5)
    with session_factory() as db:
        db.add(
            RuntimeWorkerRecord(
                worker_id="worker-old",
                worker_type="live_run_reaper",
                status="running",
                started_at=old,
                heartbeat_at=old,
            )
        )
        db.commit()
        assert live_run_reaper_is_alive(db, max_age_seconds=45) is False


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
            assert live_run_reaper_is_alive(db, max_age_seconds=45) is False
    finally:
        telemetry.stop()


def _stale_run(
    *,
    run_id: str,
    session_id: str,
    now: datetime,
    attempts: int,
    not_before: datetime | None = None,
) -> LiveRunRecord:
    return LiveRunRecord(
        run_id=run_id,
        session_id=session_id,
        status="running",
        villager_model="model",
        werewolf_model="model",
        seed=1,
        max_rounds=8,
        rule_set_id="starter_6",
        rule_set={"id": "starter_6"},
        player_configs=[],
        lineup_quality_warnings=[],
        worker_id="worker-lost",
        worker_heartbeat_at=now - timedelta(minutes=2),
        lease_expires_at=now - timedelta(minutes=1),
        recovery_attempts=attempts,
        recovery_not_before=not_before,
    )
