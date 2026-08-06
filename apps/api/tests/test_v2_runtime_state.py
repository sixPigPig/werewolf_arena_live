from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.base import Base
from app.v2.models import (
    V2GameRecord,
    V2GameRecordEvent,
    V2GameRun,
    V2MatchState,
)
from app.v2.runtime_state import project_v2_runtime_state


NOW = datetime(2026, 8, 6, 12, 0, tzinfo=UTC)


def _game(
    *,
    status: str = "ready",
    phase_state: str = "night_running",
    current_run_id: str = "v2_run_current0001",
) -> V2GameRecord:
    return V2GameRecord(
        game_id="v2_game_runtime001",
        title="runtime projection test",
        status=status,
        current_run_id=current_run_id,
        record_schema_version=1,
        last_record_seq=0,
        last_presentation_seq=0,
        phase_seq=1,
        phase_id="first_night",
        phase_state=phase_state,
        rule_snapshot={},
        players_snapshot=[],
        judge_voice_snapshot={},
        delivery_snapshot={"schema_version": 1, "mode": "text_only"},
        ability_snapshot={},
    )


def _run(
    *,
    run_id: str = "v2_run_current0001",
    status: str = "ready",
    completed_at: datetime | None = None,
    worker_id: str | None = None,
    worker_heartbeat_at: datetime | None = None,
    lease_expires_at: datetime | None = None,
    fence_token: int = 0,
) -> V2GameRun:
    return V2GameRun(
        run_id=run_id,
        game_id="v2_game_runtime001",
        attempt_no=1,
        status=status,
        completed_at=completed_at,
        worker_id=worker_id,
        worker_heartbeat_at=worker_heartbeat_at,
        lease_expires_at=lease_expires_at,
        fence_token=fence_token,
    )


def _match(
    *,
    winner: str | None = None,
    completion_reason: str | None = None,
) -> V2MatchState:
    return V2MatchState(
        game_id="v2_game_runtime001",
        round_no=1,
        sheriff_badge_state="disabled",
        pre_sheriff_explosion_count=0,
        winner=winner,
        completion_reason=completion_reason,
    )


@pytest.mark.parametrize(
    ("game", "run", "match", "completion_event_present", "expected"),
    [
        (
            _game(status="waiting_to_start", phase_state="opening_ready"),
            _run(status="waiting_to_start"),
            None,
            False,
            "waiting",
        ),
        (_game(), _run(), _match(), False, "running"),
        (
            _game(status="awaiting_observation", phase_state="game_completed"),
            _run(status="awaiting_observation", completed_at=NOW),
            _match(winner="villagers", completion_reason="deterministic_win_condition"),
            True,
            "completed",
        ),
        (
            _game(status="awaiting_observation", phase_state="game_completed"),
            _run(status="awaiting_observation", completed_at=NOW),
            _match(winner="villagers", completion_reason="deterministic_win_condition"),
            False,
            "running",
        ),
        (
            _game(status="canceled", phase_state="night_running"),
            _run(status="canceled", completed_at=NOW),
            _match(),
            False,
            "canceled",
        ),
        (
            _game(status="failed", phase_state="failed"),
            _run(status="failed", completed_at=NOW),
            _match(completion_reason="runtime_failed"),
            False,
            "failed",
        ),
    ],
)
def test_match_status_matrix(
    game: V2GameRecord,
    run: V2GameRun,
    match: V2MatchState | None,
    completion_event_present: bool,
    expected: str,
) -> None:
    projection = project_v2_runtime_state(
        game=game,
        run=run,
        match=match,
        now=NOW,
        completion_event_present=completion_event_present,
    )

    assert projection.match_status == expected


@pytest.mark.parametrize(
    ("phase_state", "winner", "completion_reason", "completed_at", "event_present"),
    [
        ("night_running", "villagers", "deterministic_win_condition", NOW, True),
        ("game_completed", None, "deterministic_win_condition", NOW, True),
        ("game_completed", "villagers", None, NOW, True),
        ("game_completed", "villagers", "deterministic_win_condition", None, True),
        ("game_completed", "villagers", "deterministic_win_condition", NOW, False),
    ],
)
def test_incomplete_terminal_evidence_remains_running(
    phase_state: str,
    winner: str | None,
    completion_reason: str | None,
    completed_at: datetime | None,
    event_present: bool,
) -> None:
    projection = project_v2_runtime_state(
        game=_game(status="awaiting_observation", phase_state=phase_state),
        run=_run(status="awaiting_observation", completed_at=completed_at),
        match=_match(winner=winner, completion_reason=completion_reason),
        now=NOW,
        completion_event_present=event_present,
    )

    assert projection.match_status == "running"


def test_completed_requires_a_game_completed_event_from_the_current_run() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(
        engine,
        tables=[
            V2GameRecord.__table__,
            V2GameRun.__table__,
            V2MatchState.__table__,
            V2GameRecordEvent.__table__,
        ],
    )
    with Session(engine) as db:
        game = _game(status="awaiting_observation", phase_state="game_completed")
        current_run = _run(status="awaiting_observation", completed_at=NOW)
        previous_run = _run(
            run_id="v2_run_previous001",
            status="awaiting_observation",
            completed_at=NOW - timedelta(days=1),
        )
        previous_run.attempt_no = 0
        match = _match(
            winner="villagers",
            completion_reason="deterministic_win_condition",
        )
        db.add_all([game, current_run, previous_run, match])
        db.flush()
        db.add(
            V2GameRecordEvent(
                game_id=game.game_id,
                event_id=1,
                record_seq=1,
                run_id=previous_run.run_id,
                event_type="game_completed",
                payload_schema_version=1,
                payload={"winner": "villagers"},
            )
        )
        db.flush()

        without_current_event = project_v2_runtime_state(
            game=game,
            run=current_run,
            match=match,
            now=NOW,
        )
        assert without_current_event.match_status == "running"

        db.add(
            V2GameRecordEvent(
                game_id=game.game_id,
                event_id=2,
                record_seq=2,
                run_id=current_run.run_id,
                event_type="game_completed",
                payload_schema_version=1,
                payload={"winner": "villagers"},
            )
        )
        db.flush()

        with_current_event = project_v2_runtime_state(
            game=game,
            run=current_run,
            match=match,
            now=NOW,
        )
        assert with_current_event.match_status == "completed"


@pytest.mark.parametrize(
    ("game_status", "worker_id", "heartbeat", "lease", "fence_token", "expected"),
    [
        ("ready", None, None, None, 0, "unowned"),
        ("awaiting_observation", None, None, None, 1, "stopped"),
        ("ready", "worker-a", NOW, NOW + timedelta(seconds=10), 1, "owned"),
        ("ready", "worker-a", NOW, NOW, 1, "stale"),
        ("ready", "worker-a", None, None, 1, "stale"),
        ("ready", None, NOW, None, 1, "stale"),
        ("ready", None, None, NOW + timedelta(seconds=10), 1, "stale"),
        ("ready", "worker-a", NOW, None, 1, "stale"),
        ("ready", "worker-a", None, NOW + timedelta(seconds=10), 1, "stale"),
        ("ready", None, NOW, NOW + timedelta(seconds=10), 1, "stale"),
        ("ready", "worker-a", NOW, NOW + timedelta(seconds=10), 0, "stale"),
    ],
)
def test_execution_state_matrix(
    game_status: str,
    worker_id: str | None,
    heartbeat: datetime | None,
    lease: datetime | None,
    fence_token: int,
    expected: str,
) -> None:
    projection = project_v2_runtime_state(
        game=_game(status=game_status),
        run=_run(
            status=game_status,
            worker_id=worker_id,
            worker_heartbeat_at=heartbeat,
            lease_expires_at=lease,
            fence_token=fence_token,
        ),
        match=_match(),
        now=NOW,
        completion_event_present=False,
    )

    assert projection.execution_state == expected
