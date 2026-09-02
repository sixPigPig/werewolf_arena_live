from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.models.user import User  # noqa: F401 - registers referenced users table
from app.match.models import GameRecord, GameRecordEvent, GameRun, MatchState
from app.match.repository import ActionRepository


GAME_ID = "v2_game_reaper_test"
RUN_ID = "v2_run_reaper_test"


def _factory() -> sessionmaker[Session]:
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=True)


def _seed_run(
    factory: sessionmaker[Session],
    *,
    game_status: str,
    run_status: str,
    phase_state: str,
    lease_expires_at: datetime | None,
    worker_id: str | None,
) -> None:
    now = datetime.now(tz=UTC)
    with factory.begin() as db:
        db.add(
            GameRecord(
                game_id=GAME_ID,
                title="reaper test",
                status=game_status,
                current_run_id=RUN_ID,
                last_record_seq=0,
                last_presentation_seq=0,
                playback_cursor=0,
                phase_seq=1,
                phase_id="day_1",
                phase_state=phase_state,
                rule_snapshot={"rule_set": {"id": "reaper-test"}, "max_rounds": 8},
                players_snapshot=[],
                judge_voice_snapshot={},
                delivery_snapshot={"schema_version": 1, "mode": "text_only"},
                ability_snapshot={},
            )
        )
        db.add(
            GameRun(
                run_id=RUN_ID,
                game_id=GAME_ID,
                attempt_no=1,
                status=run_status,
                worker_id=worker_id,
                worker_heartbeat_at=now if worker_id is not None else None,
                lease_expires_at=lease_expires_at,
                fence_token=1,
            )
        )
        db.add(
            MatchState(
                game_id=GAME_ID,
                round_no=1,
                sheriff_badge_state="disabled",
                winner="villagers",
                completion_reason="deterministic_win_condition",
            )
        )


def test_reaper_skips_awaiting_observation_with_null_lease() -> None:
    factory = _factory()
    _seed_run(
        factory,
        game_status="awaiting_observation",
        run_status="awaiting_observation",
        phase_state="game_completed",
        lease_expires_at=None,
        worker_id=None,
    )
    repository = ActionRepository(factory, enforce_execution_fence=False)

    assert repository.reap_stale_runs(stale_grace_seconds=0) == []

    with factory() as db:
        game = db.get(GameRecord, GAME_ID)
        run = db.get(GameRun, RUN_ID)
        assert game is not None and run is not None
        assert game.status == "awaiting_observation"
        assert run.status == "awaiting_observation"
        assert not list(
            db.scalars(
                select(GameRecordEvent).where(
                    GameRecordEvent.event_type == "v2_run_execution_reaped"
                )
            )
        )


def test_reaper_skips_null_lease_without_worker_even_if_ready() -> None:
    factory = _factory()
    _seed_run(
        factory,
        game_status="ready",
        run_status="ready",
        phase_state="public_discussion_open",
        lease_expires_at=None,
        worker_id=None,
    )
    repository = ActionRepository(factory, enforce_execution_fence=False)

    assert repository.reap_stale_runs(stale_grace_seconds=0) == []


def test_reaper_fails_expired_ready_lease() -> None:
    factory = _factory()
    _seed_run(
        factory,
        game_status="ready",
        run_status="ready",
        phase_state="public_discussion_open",
        lease_expires_at=datetime.now(tz=UTC) - timedelta(minutes=2),
        worker_id="v2_worker_dead",
    )
    with factory.begin() as db:
        match = db.get(MatchState, GAME_ID)
        assert match is not None
        match.winner = None
        match.completion_reason = None
    repository = ActionRepository(factory, enforce_execution_fence=False)

    assert repository.reap_stale_runs(stale_grace_seconds=30) == [GAME_ID]

    with factory() as db:
        game = db.get(GameRecord, GAME_ID)
        run = db.get(GameRun, RUN_ID)
        match = db.get(MatchState, GAME_ID)
        assert game is not None and run is not None and match is not None
        assert game.status == "failed"
        assert run.status == "failed"
        assert match.completion_reason == "worker_lease_expired"
        reaped = db.scalar(
            select(GameRecordEvent).where(
                GameRecordEvent.event_type == "v2_run_execution_reaped"
            )
        )
        assert reaped is not None
        assert reaped.payload["failure_code"] == "worker_lease_expired"
