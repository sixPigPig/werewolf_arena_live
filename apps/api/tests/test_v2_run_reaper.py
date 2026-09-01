from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.match.execution import RunFence
from app.match.models import (
    GameRecord,
    GameRecordEvent,
    GameRun,
    ModelActionRecovery,
)
from app.match.repository import ActionClaim, ActionRepository, RepositoryError
from app.match.service import create_waiting_game


@pytest.fixture
def session_factory() -> Iterator[sessionmaker[Session]]:
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    yield factory
    engine.dispose()


@pytest.fixture
def claimed_game(session_factory: sessionmaker[Session]) -> tuple[str, str, RunFence]:
    with session_factory() as db:
        game, _run, _token = create_waiting_game(
            db,
            title="reaper harness",
            delivery_snapshot={"schema_version": 1, "mode": "tts"},
        )
        game_id = game.game_id
    with session_factory.begin() as db:
        game = db.get(GameRecord, game_id)
        assert game is not None
        game.players_snapshot = [
            {
                "seat": 1,
                "profile_id": "reaper-player",
                "name": "收割测试玩家",
                "model_provider": "agent_plan",
                "model": "reaper-model",
                "model_supports_thinking": False,
                "model_parameters": {
                    "thinking": "disabled",
                    "reasoning_effort": None,
                    "max_tokens_mode": "auto",
                    "max_tokens": 512,
                },
            }
        ]
    actions = ActionRepository(session_factory, enforce_execution_fence=True)
    execution = actions.start_and_claim_execution(
        game_id=game_id,
        audience="player_public",
        worker_id="v2_worker_reaper",
        lease_seconds=300,
    )
    assert execution.fence is not None
    with session_factory.begin() as db:
        run = db.get(GameRun, execution.run_id)
        assert run is not None
        run.status = "finalizing"
        db.get(GameRecord, game_id).status = "finalizing"
    return game_id, execution.run_id, execution.fence


def _expire_lease(session_factory: sessionmaker[Session], run_id: str) -> None:
    with session_factory.begin() as db:
        run = db.get(GameRun, run_id)
        assert run is not None
        run.lease_expires_at = datetime.now(tz=UTC) - timedelta(minutes=10)


def _event_types(
    session_factory: sessionmaker[Session], game_id: str
) -> set[str]:
    with session_factory() as db:
        return set(
            db.scalars(
                select(GameRecordEvent.event_type).where(
                    GameRecordEvent.game_id == game_id
                )
            )
        )


def test_reap_fails_expired_active_run(
    session_factory: sessionmaker[Session], claimed_game: tuple[str, str, RunFence]
) -> None:
    game_id, run_id, fence = claimed_game
    _expire_lease(session_factory, run_id)
    actions = ActionRepository(session_factory)

    reaped = actions.reap_stale_runs(grace_seconds=30.0)

    assert [entry["run_id"] for entry in reaped] == [run_id]
    with session_factory() as db:
        run = db.get(GameRun, run_id)
        game = db.get(GameRecord, game_id)
        assert run is not None and game is not None
        assert run.status == "failed"
        assert run.completed_at is not None
        assert run.worker_id is None
        assert run.lease_expires_at is None
        assert run.fence_token == fence.fence_token + 1
        assert game.status == "failed"
        assert game.phase_state == "failed"
    events = _event_types(session_factory, game_id)
    assert "v2_run_execution_reaped" in events
    assert "game_failed" in events


def test_reap_skips_live_lease(
    session_factory: sessionmaker[Session], claimed_game: tuple[str, str, RunFence]
) -> None:
    _game_id, run_id, _fence = claimed_game
    actions = ActionRepository(session_factory)

    assert actions.reap_stale_runs(grace_seconds=30.0) == []

    with session_factory() as db:
        run = db.get(GameRun, run_id)
        assert run is not None
        assert run.status == "finalizing"
        assert run.worker_id == "v2_worker_reaper"


def test_reap_cancels_paused_recovery(
    session_factory: sessionmaker[Session], claimed_game: tuple[str, str, RunFence]
) -> None:
    game_id, run_id, _fence = claimed_game
    _expire_lease(session_factory, run_id)
    with session_factory.begin() as db:
        run = db.get(GameRun, run_id)
        game = db.get(GameRecord, game_id)
        assert run is not None and game is not None
        run.status = "paused_model_error"
        game.status = "paused_model_error"
        db.add(
            ModelActionRecovery(
                action_id="v2_action_paused_1",
                recovery_id="v2_rec_1",
                game_id=game_id,
                run_id=run_id,
                action_type="exile_vote",
                actor_id="system-player-01",
                model_provider="agent_plan",
                model_id="reaper-model",
                request_payload={},
                request_hash="hash",
                model_context={},
                action_snapshot={},
                failure_code="model_total_timeout",
                failure_category="timeout",
                attempt_no=2,
                retry_cycle=2,
                state="paused",
            )
        )
    actions = ActionRepository(session_factory)

    reaped = actions.reap_stale_runs(grace_seconds=30.0)

    assert [entry["run_id"] for entry in reaped] == [run_id]
    with session_factory() as db:
        recovery = db.get(ModelActionRecovery, "v2_action_paused_1")
        assert recovery is not None
        assert recovery.state == "canceled"
        assert recovery.resolved_at is not None
    events = _event_types(session_factory, game_id)
    assert "model_action_recovery_canceled" in events


def test_reap_skips_terminal_runs(
    session_factory: sessionmaker[Session], claimed_game: tuple[str, str, RunFence]
) -> None:
    game_id, run_id, _fence = claimed_game
    _expire_lease(session_factory, run_id)
    with session_factory.begin() as db:
        run = db.get(GameRun, run_id)
        assert run is not None
        run.status = "failed"
    actions = ActionRepository(session_factory)

    assert actions.reap_stale_runs(grace_seconds=30.0) == []

    assert "v2_run_execution_reaped" not in _event_types(session_factory, game_id)


def _paused_game(
    session_factory: sessionmaker[Session], claimed_game: tuple[str, str, RunFence]
) -> tuple[ActionClaim, str]:
    game_id, run_id, fence = claimed_game
    with session_factory.begin() as db:
        run = db.get(GameRun, run_id)
        game = db.get(GameRecord, game_id)
        assert run is not None and game is not None
        run.status = "paused_model_error"
        game.status = "paused_model_error"
        db.add(
            ModelActionRecovery(
                action_id="v2_action_paused_auto",
                recovery_id="v2_rec_auto",
                game_id=game_id,
                run_id=run_id,
                action_type="exile_vote",
                actor_id="system-player-01",
                model_provider="agent_plan",
                model_id="reaper-model",
                request_payload={},
                request_hash="hash",
                model_context={},
                action_snapshot={},
                failure_code="model_total_timeout",
                failure_category="timeout",
                attempt_no=2,
                retry_cycle=2,
                state="paused",
            )
        )
    claim = ActionClaim(
        game_id=game_id,
        run_id=run_id,
        action_id="v2_action_paused_auto",
        phase_id="day_1",
        audience="god_view",
        run_fence=fence,
    )
    return claim, game_id


def test_auto_resume_restores_generating_once(
    session_factory: sessionmaker[Session], claimed_game: tuple[str, str, RunFence]
) -> None:
    claim, game_id = _paused_game(session_factory, claimed_game)
    actions = ActionRepository(session_factory, enforce_execution_fence=True)

    assert actions.auto_resume_model_action(
        claim=claim,
        failure_code="model_total_timeout",
    )
    with session_factory() as db:
        run = db.get(GameRun, claim.run_id)
        game = db.get(GameRecord, game_id)
        recovery = db.get(ModelActionRecovery, claim.action_id)
        assert run is not None and game is not None and recovery is not None
        assert run.status == "generating"
        assert game.status == "generating"
        assert recovery.state == "running"
        assert recovery.control_request_id is None
    events = _event_types(session_factory, game_id)
    assert "model_action_auto_resumed" in events
    assert "model_action_resumed" in events

    # One auto-resume per action per run: the second pause stays for an operator.
    with session_factory.begin() as db:
        run = db.get(GameRun, claim.run_id)
        game = db.get(GameRecord, game_id)
        recovery = db.get(ModelActionRecovery, claim.action_id)
        assert run is not None and game is not None and recovery is not None
        run.status = "paused_model_error"
        game.status = "paused_model_error"
        recovery.state = "paused"
    assert not actions.auto_resume_model_action(
        claim=claim,
        failure_code="model_total_timeout",
    )


def test_auto_resume_rejects_running_game(
    session_factory: sessionmaker[Session], claimed_game: tuple[str, str, RunFence]
) -> None:
    claim, _game_id = _paused_game(session_factory, claimed_game)
    with session_factory.begin() as db:
        run = db.get(GameRun, claim.run_id)
        assert run is not None
        run.status = "generating"
    actions = ActionRepository(session_factory, enforce_execution_fence=True)

    assert not actions.auto_resume_model_action(
        claim=claim,
        failure_code="model_total_timeout",
    )


def test_abandon_model_action_pause_releases_run_and_cancels_recovery(
    session_factory: sessionmaker[Session], claimed_game: tuple[str, str, RunFence]
) -> None:
    claim, game_id = _paused_game(session_factory, claimed_game)
    actions = ActionRepository(session_factory, enforce_execution_fence=True)

    actions.abandon_model_action_pause(
        claim=claim,
        failure_code="model_total_timeout",
    )

    with session_factory() as db:
        run = db.get(GameRun, claim.run_id)
        game = db.get(GameRecord, game_id)
        recovery = db.get(ModelActionRecovery, claim.action_id)
        assert run is not None and game is not None and recovery is not None
        assert run.status == "generating"
        assert game.status == "generating"
        assert recovery.state == "canceled"
        assert recovery.resolved_at is not None
    with session_factory() as db:
        event = db.scalar(
            select(GameRecordEvent).where(
                GameRecordEvent.game_id == game_id,
                GameRecordEvent.event_type == "model_action_recovery_canceled",
            )
        )
        assert event is not None
        assert event.payload["action_id"] == claim.action_id
        assert event.payload["recovery_id"] == "v2_rec_auto"
        assert event.payload["reason_code"] == "auto_retry_exhausted"
        assert event.payload["failure_code"] == "model_total_timeout"


def test_abandon_model_action_pause_requires_active_pause(
    session_factory: sessionmaker[Session], claimed_game: tuple[str, str, RunFence]
) -> None:
    claim, _game_id = _paused_game(session_factory, claimed_game)
    with session_factory.begin() as db:
        run = db.get(GameRun, claim.run_id)
        game = db.get(GameRecord, claim.game_id)
        assert run is not None and game is not None
        run.status = "generating"
        game.status = "generating"
    actions = ActionRepository(session_factory, enforce_execution_fence=True)

    with pytest.raises(RepositoryError, match="model action pause is not active"):
        actions.abandon_model_action_pause(
            claim=claim,
            failure_code="model_total_timeout",
        )


def test_abandon_model_action_pause_requires_paused_recovery(
    session_factory: sessionmaker[Session], claimed_game: tuple[str, str, RunFence]
) -> None:
    claim, _game_id = _paused_game(session_factory, claimed_game)
    with session_factory.begin() as db:
        recovery = db.get(ModelActionRecovery, claim.action_id)
        assert recovery is not None
        recovery.state = "canceled"
    actions = ActionRepository(session_factory, enforce_execution_fence=True)

    with pytest.raises(RepositoryError, match="model action recovery is not paused"):
        actions.abandon_model_action_pause(
            claim=claim,
            failure_code="model_total_timeout",
        )
