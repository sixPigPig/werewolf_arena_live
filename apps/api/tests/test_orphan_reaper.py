from __future__ import annotations

from datetime import UTC, datetime, timedelta
from threading import Event

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.routes.games import SessionLiveStore
from app.db.base import Base
from app.models.live import LiveRunRecord
from app.werewolf.live import LiveRunRegistry
from app.werewolf.orphan_reaper import (
    run_live_run_reaper,
    run_next_orphan_recovery,
)
from app.werewolf.replay import DatabaseReplayStore

def _session_factory() -> sessionmaker[Session]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)


def _seed_orphan(
    session_factory: sessionmaker[Session],
    *,
    session_id: str,
    with_checkpoint: bool = True,
    stop_requested: bool = False,
) -> tuple[LiveRunRegistry, str]:
    owner = LiveRunRegistry(
        live_store=SessionLiveStore(session_factory),
        worker_id="worker-lost",
    )
    run = owner.create_run(
        session_id=session_id,
        villager_model="deepseek-chat",
        werewolf_model="deepseek-chat",
        seed=7,
        max_rounds=8,
    )
    owner.mark_running(run.run_id)
    if with_checkpoint:
        with session_factory() as db:
            DatabaseReplayStore(db).save_resume_checkpoint(
                session_id,
                _checkpoint(session_id),
            )
    with session_factory() as db:
        record = db.get(LiveRunRecord, run.run_id)
        assert record is not None
        record.worker_heartbeat_at = datetime.now(tz=UTC) - timedelta(minutes=2)
        record.lease_expires_at = datetime.now(tz=UTC) - timedelta(minutes=1)
        if stop_requested:
            record.stop_requested_at = datetime.now(tz=UTC) - timedelta(seconds=30)
            record.control_version += 1
        db.commit()
    return owner, run.run_id


def _checkpoint(session_id: str) -> dict[str, object]:
    return {
        "schema_version": 1,
        "session_id": session_id,
        "state_at_round_start": {
            "session_id": session_id,
            "players": [],
            "rounds": [],
            "winner": "",
            "error_message": "",
            "rule_set": {"id": "starter_6"},
        },
        "logs_before_round": [],
        "run_params": {
            "villager_model": "deepseek-chat",
            "werewolf_model": "deepseek-chat",
            "seed": 7,
            "max_rounds": 8,
            "rule_set_id": "starter_6",
            "player_configs": [],
        },
        "round_number": 1,
        "active_players": [],
        "cached_model_responses": [],
        "failed_request": None,
        "last_error": None,
    }


def test_reaper_claims_checkpoint_with_new_fence_and_schedules_backoff() -> None:
    session_factory = _session_factory()
    owner, run_id = _seed_orphan(
        session_factory,
        session_id="game_6100abcd",
    )
    original_fence = owner.get_run(run_id).fence_token
    reaper = LiveRunRegistry(
        live_store=SessionLiveStore(session_factory),
        worker_id="worker-reaper",
    )

    result = run_next_orphan_recovery(
        session_factory,
        reaper,
        stale_grace_seconds=0,
        backoff_seconds=30,
        max_attempts=3,
        execute_recovery=lambda run, registry: registry.mark_running(run.run_id),
    )

    assert result is not None
    assert result.run_id == run_id
    assert result.outcome == "resumed"
    assert result.attempt == 1
    with session_factory() as db:
        saved = db.get(LiveRunRecord, run_id)
        assert saved is not None
        assert saved.status == "running"
        assert saved.worker_id == "worker-reaper"
        assert saved.fence_token == original_fence + 1
        assert saved.recovery_attempts == 1
        assert saved.recovery_last_attempt_at is not None
        assert saved.recovery_not_before is not None


def test_only_one_reaper_can_claim_the_same_candidate() -> None:
    session_factory = _session_factory()
    _owner, run_id = _seed_orphan(
        session_factory,
        session_id="game_6200abcd",
    )
    first = LiveRunRegistry(
        live_store=SessionLiveStore(session_factory),
        worker_id="worker-reaper-a",
    )
    second = LiveRunRegistry(
        live_store=SessionLiveStore(session_factory),
        worker_id="worker-reaper-b",
    )
    now = datetime.now(tz=UTC)
    stale_before = (now - timedelta(seconds=1)).isoformat()
    candidates = first.recovery_candidates(
        stale_before=stale_before,
        now=now.isoformat(),
        max_attempts=3,
    )
    assert len(candidates) == 1

    claimed = first.try_claim_orphan(
        candidates[0],
        stale_before=stale_before,
        recovery_not_before=(now + timedelta(seconds=30)).isoformat(),
        max_attempts=3,
    )
    raced = second.try_claim_orphan(
        candidates[0],
        stale_before=stale_before,
        recovery_not_before=(now + timedelta(seconds=30)).isoformat(),
        max_attempts=3,
    )

    assert claimed is not None
    assert claimed.run_id == run_id
    assert raced is None


def test_reaper_fails_orphan_without_checkpoint_and_cancels_pending_stop() -> None:
    session_factory = _session_factory()
    _owner, failed_run_id = _seed_orphan(
        session_factory,
        session_id="game_6300abcd",
        with_checkpoint=False,
    )
    _owner, canceled_run_id = _seed_orphan(
        session_factory,
        session_id="game_6400abcd",
        with_checkpoint=False,
        stop_requested=True,
    )
    reaper = LiveRunRegistry(
        live_store=SessionLiveStore(session_factory),
        worker_id="worker-reaper",
    )

    first = run_next_orphan_recovery(
        session_factory,
        reaper,
        stale_grace_seconds=0,
        backoff_seconds=30,
        max_attempts=3,
    )
    second = run_next_orphan_recovery(
        session_factory,
        reaper,
        stale_grace_seconds=0,
        backoff_seconds=30,
        max_attempts=3,
    )

    assert first is not None
    assert first.run_id == failed_run_id
    assert first.outcome == "failed"
    assert second is not None
    assert second.run_id == canceled_run_id
    assert second.outcome == "canceled"
    with session_factory() as db:
        failed = db.get(LiveRunRecord, failed_run_id)
        canceled = db.get(LiveRunRecord, canceled_run_id)
        assert failed is not None
        assert failed.status == "failed"
        assert failed.recovery_last_error == (
            "Orphaned live run has no valid resume checkpoint"
        )
        assert canceled is not None
        assert canceled.status == "canceled"


def test_reaper_respects_backoff_and_max_attempts() -> None:
    session_factory = _session_factory()
    _owner, run_id = _seed_orphan(
        session_factory,
        session_id="game_6500abcd",
    )
    with session_factory() as db:
        record = db.get(LiveRunRecord, run_id)
        assert record is not None
        record.recovery_attempts = 2
        record.recovery_not_before = datetime.now(tz=UTC) + timedelta(minutes=1)
        db.commit()
    reaper = LiveRunRegistry(live_store=SessionLiveStore(session_factory))
    now = datetime.now(tz=UTC)

    assert reaper.recovery_candidates(
        stale_before=now.isoformat(),
        now=now.isoformat(),
        max_attempts=3,
    ) == []
    with session_factory() as db:
        record = db.get(LiveRunRecord, run_id)
        assert record is not None
        record.recovery_not_before = now - timedelta(seconds=1)
        record.recovery_attempts = 3
        db.commit()
    assert reaper.recovery_candidates(
        stale_before=now.isoformat(),
        now=now.isoformat(),
        max_attempts=3,
    ) == []


def test_continuous_reaper_reports_recoveries_until_stopped(monkeypatch) -> None:
    stop_event = Event()
    results = iter(
        [
            type("Result", (), {"run_id": "run-1"})(),
            type("Result", (), {"run_id": "run-2"})(),
        ]
    )

    def fake_run_next(*_args, **_kwargs):
        result = next(results)
        if result.run_id == "run-2":
            stop_event.set()
        return result

    monkeypatch.setattr(
        "app.werewolf.orphan_reaper.run_next_orphan_recovery",
        fake_run_next,
    )
    observed: list[str] = []
    processed = run_live_run_reaper(
        object(),
        object(),
        stop_event=stop_event,
        poll_seconds=1,
        stale_grace_seconds=30,
        backoff_seconds=30,
        max_attempts=3,
        on_recovery=lambda result: observed.append(result.run_id),
    )

    assert processed == 2
    assert observed == ["run-1", "run-2"]
