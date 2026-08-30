from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.models.user import User  # noqa: F401 - registers referenced users table
from app.match.match_repository import MatchRepository
from app.match.models import (
    DaySpeechSlot,
    GameRecord,
    GameRecordEvent,
    GameRun,
    MatchState,
)
from app.match.repository import RepositoryError


GAME_ID = "v2_game_match_pipeline_terminal"
RUN_ID = "v2_run_match_pipeline_terminal"
WORKER_ID = "v2_worker_match_pipeline_terminal"
PHASE_ID = "day_1"
PHASE_STATE = "public_discussion_open"


@dataclass(frozen=True)
class _Harness:
    factory: sessionmaker[Session]
    repository: MatchRepository


@pytest.fixture
def harness() -> _Harness:
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    now = datetime.now(tz=UTC)
    with factory.begin() as db:
        db.add(
            GameRecord(
                game_id=GAME_ID,
                title="match pipeline terminal test",
                status="ready",
                current_run_id=RUN_ID,
                last_record_seq=0,
                last_presentation_seq=0,
                phase_seq=3,
                phase_id=PHASE_ID,
                phase_state=PHASE_STATE,
                rule_snapshot={
                    "rule_set": {"id": "match-pipeline-terminal"},
                    "max_rounds": 8,
                },
                players_snapshot=[],
                judge_voice_snapshot={},
                delivery_snapshot={"schema_version": 1, "mode": "tts"},
                ability_snapshot={},
            )
        )
        db.add(
            GameRun(
                run_id=RUN_ID,
                game_id=GAME_ID,
                attempt_no=1,
                status="ready",
                worker_id=WORKER_ID,
                worker_heartbeat_at=now,
                lease_expires_at=now + timedelta(minutes=5),
                fence_token=7,
            )
        )
        db.add(
            MatchState(
                game_id=GAME_ID,
                round_no=1,
                sheriff_badge_state="disabled",
            )
        )
    result = _Harness(factory=factory, repository=MatchRepository(factory))
    try:
        yield result
    finally:
        engine.dispose()


def test_finish_day_rejects_open_slots_then_fail_runtime_invalidates_all(
    harness: _Harness,
) -> None:
    seeded_states = ("reserved", "generating", "ready", "presenting")
    with harness.factory.begin() as db:
        for index, state in enumerate(seeded_states, start=2):
            db.add(_slot(index=index, state=state))

    with pytest.raises(
        RepositoryError,
        match="cannot finish day with a nonterminal day speech slot",
    ):
        harness.repository.finish_day(
            game_id=GAME_ID,
            reason="day_actions_completed",
        )

    with harness.factory() as db:
        game = db.get(GameRecord, GAME_ID)
        run = db.get(GameRun, RUN_ID)
        match = db.get(MatchState, GAME_ID)
        slots_before_failure = list(
            db.scalars(
                select(DaySpeechSlot)
                .where(DaySpeechSlot.game_id == GAME_ID)
                .order_by(DaySpeechSlot.turn_index)
            )
        )
        events_before_failure = list(
            db.scalars(select(GameRecordEvent).where(GameRecordEvent.game_id == GAME_ID))
        )
    assert game is not None
    assert (game.phase_seq, game.phase_id, game.phase_state, game.status) == (
        3,
        PHASE_ID,
        PHASE_STATE,
        "ready",
    )
    assert run is not None and run.status == "ready"
    assert match is not None and match.round_no == 1
    assert [slot.state for slot in slots_before_failure] == list(seeded_states)
    assert events_before_failure == []

    returned_run_id = harness.repository.fail_runtime(
        game_id=GAME_ID,
        failure_code="day_pipeline_terminal_test",
    )
    assert returned_run_id == RUN_ID

    with harness.factory() as db:
        game = db.get(GameRecord, GAME_ID)
        run = db.get(GameRun, RUN_ID)
        match = db.get(MatchState, GAME_ID)
        slots = list(
            db.scalars(
                select(DaySpeechSlot)
                .where(DaySpeechSlot.game_id == GAME_ID)
                .order_by(DaySpeechSlot.turn_index)
            )
        )
        events = list(
            db.scalars(
                select(GameRecordEvent)
                .where(GameRecordEvent.game_id == GAME_ID)
                .order_by(GameRecordEvent.record_seq)
            )
        )
    assert game is not None and game.status == "failed" and game.phase_state == "failed"
    assert game.phase_id == PHASE_ID and game.phase_seq == 3
    assert run is not None and run.status == "failed" and run.completed_at is not None
    assert match is not None and match.completion_reason == "day_pipeline_terminal_test"
    assert len(slots) == len(seeded_states)
    assert all(slot.state == "invalidated" for slot in slots)
    assert all(slot.terminal_at is not None for slot in slots)
    assert len({slot.terminal_at for slot in slots}) == 1
    assert all(
        slot.failure
        == {
            "kind": "runtime_failed",
            "reason_code": "day_runtime_failed",
            "failure_code": "day_pipeline_terminal_test",
        }
        for slot in slots
    )
    invalidated = [event for event in events if event.event_type == "day_speech_slot_invalidated"]
    assert len(invalidated) == len(seeded_states)
    assert [event.payload["slot_id"] for event in invalidated] == [slot.slot_id for slot in slots]
    assert all(event.payload["audience"] == "god_view" for event in invalidated)
    assert all(event.payload["state"] == "invalidated" for event in invalidated)
    assert all(event.payload["failure_kind"] == "runtime_failed" for event in invalidated)
    assert all(event.payload["reason_code"] == "day_runtime_failed" for event in invalidated)
    assert all(
        event.payload["failure_code"] == "day_pipeline_terminal_test" for event in invalidated
    )
    runtime_failed = events[-1]
    assert runtime_failed.event_type == "day_runtime_failed"
    assert runtime_failed.payload["invalidated_day_speech_slot_count"] == len(seeded_states)
    assert max(event.record_seq for event in invalidated) < runtime_failed.record_seq


def test_fail_runtime_without_slots_keeps_zero_count_semantics(harness: _Harness) -> None:
    harness.repository.fail_runtime(
        game_id=GAME_ID,
        failure_code="day_runtime_without_pipeline_slots",
    )
    with harness.factory() as db:
        runtime_failed = db.scalar(
            select(GameRecordEvent).where(
                GameRecordEvent.game_id == GAME_ID,
                GameRecordEvent.event_type == "day_runtime_failed",
            )
        )
    assert runtime_failed is not None
    assert runtime_failed.payload["failure_code"] == "day_runtime_without_pipeline_slots"
    assert runtime_failed.payload["invalidated_day_speech_slot_count"] == 0


def _slot(*, index: int, state: str) -> DaySpeechSlot:
    return DaySpeechSlot(
        slot_id=f"v2_slot_match_terminal_{index}",
        game_id=GAME_ID,
        run_id=RUN_ID,
        fence_worker_id=WORKER_ID,
        fence_token=7,
        phase_id=PHASE_ID,
        round_no=1,
        speech_round=1,
        turn_index=index,
        action_type="day_debate_speech",
        actor_player_id=f"player_{index}",
        predecessor_action_id=f"v2_action_match_predecessor_{index}",
        predecessor_presentation_id=f"v2_pres_match_predecessor_{index}",
        predecessor_source_event_id=index,
        predecessor_source_record_seq=index,
        context_cutoff_record_seq=index,
        state=state,
        generation_action_id=(
            f"v2_action_match_generation_{index}" if state in {"ready", "presenting"} else None
        ),
        generation_response_record_seq=(index if state in {"ready", "presenting"} else None),
        decision=(
            {"speech": f"prefetched speech {index}"} if state in {"ready", "presenting"} else None
        ),
        presentation_action_id=(
            f"v2_action_match_presentation_{index}" if state == "presenting" else None
        ),
        presentation_id=(f"v2_pres_match_slot_{index}" if state == "presenting" else None),
    )
