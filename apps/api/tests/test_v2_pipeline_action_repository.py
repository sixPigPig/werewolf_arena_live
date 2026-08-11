from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.models.user import User  # noqa: F401 - registers referenced users table
from app.v2.day_speech_pipeline_contract import freeze_day_speech_pipeline_contract
from app.v2.execution import V2RunFence, bind_v2_run_fence
from app.v2.model_failure_episode import (
    derive_failure_episodes,
    stable_failure_episode_id,
)
from app.v2.model_context_contract import freeze_model_context_contract
from app.v2.model_generation_policy_contract import (
    freeze_model_generation_policy_contract,
)
from app.v2.models import (
    V2DaySpeechSlot,
    V2GameRecord,
    V2GameRecordEvent,
    V2GameRun,
    V2LivePresentation,
    V2PlayerState,
)
from app.v2.repository import (
    V2ActionClaim,
    V2ActionRepository,
    V2PresentationIdentity,
    V2RepositoryError,
)
from app.v2.service import current_action_context


GAME_ID = "v2_game_pipeline_claim"
RUN_ID = "v2_run_pipeline_claim"
PHASE_ID = "day_1"
PHASE_STATE = "public_discussion_open"
WORKER_ID = "v2_worker_pipeline_claim"
PREDECESSOR_ACTION_ID = "v2_action_pipeline_predecessor"
PREDECESSOR_PRESENTATION_ID = "v2_pres_pipeline_predecessor"
SLOT_ID = "v2_slot_pipeline_claim"


@dataclass(frozen=True)
class _Harness:
    factory: sessionmaker[Session]
    repository: V2ActionRepository
    fence: V2RunFence
    predecessor_claim: V2ActionClaim
    predecessor: V2PresentationIdentity
    cutoff: int

    def generation_context(
        self,
        action_id: str,
        *,
        admission_mode: str = "idle_only",
        cutoff: int | None = None,
    ) -> dict[str, Any]:
        frozen_cutoff = self.cutoff if cutoff is None else cutoff
        return _speech_context(
            action_id=action_id,
            actor_id="player_2",
            pipeline={
                "slot_id": SLOT_ID,
                "stage": "generation",
                "model_admission_mode": admission_mode,
                "retry_mode": "empty_stream_once_while_predecessor_active",
                "empty_stream_max_attempts": 2,
            },
            public_cutoff_record_seq=frozen_cutoff,
            projection_at_seq=frozen_cutoff,
            batch_id=f"{SLOT_ID}:generation",
        )

    def claim_generation(
        self,
        action_id: str,
        *,
        context: dict[str, Any] | None = None,
        best_effort: bool = False,
        non_blocking: bool = True,
    ) -> V2ActionClaim | None:
        with bind_v2_run_fence(self.fence):
            return self.repository.claim_action(
                game_id=GAME_ID,
                action_id=action_id,
                context=context or self.generation_context(action_id),
                expected_phase_id=PHASE_ID,
                expected_phase_state=PHASE_STATE,
                audience="player_private",
                context_audience="player_private",
                best_effort=best_effort,
                non_blocking=non_blocking,
            )


@pytest.fixture
def harness() -> _Harness:
    engine, result = _build_harness()
    try:
        yield result
    finally:
        engine.dispose()


@pytest.fixture
def technical_skip_harness() -> _Harness:
    engine, result = _build_harness(technical_skip_predecessor=True)
    try:
        yield result
    finally:
        engine.dispose()


def _build_harness(
    *,
    technical_skip_predecessor: bool = False,
) -> tuple[Any, _Harness]:
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=True)
    rule_snapshot: dict[str, Any] = {
        "rule_set": {"id": "pipeline-claim-test", "sheriff_enabled": False},
        "max_rounds": 8,
    }
    rule_snapshot = freeze_day_speech_pipeline_contract(
        freeze_model_generation_policy_contract(freeze_model_context_contract(rule_snapshot))
    )
    now = datetime.now(tz=UTC)
    with factory.begin() as db:
        db.add(
            V2GameRecord(
                game_id=GAME_ID,
                title="pipeline claim test",
                status="ready",
                current_run_id=RUN_ID,
                last_record_seq=0,
                last_presentation_seq=0,
                phase_seq=1,
                phase_id=PHASE_ID,
                phase_state=PHASE_STATE,
                rule_snapshot=rule_snapshot,
                players_snapshot=[],
                judge_voice_snapshot={},
                delivery_snapshot={"schema_version": 1, "mode": "tts"},
                ability_snapshot={},
            )
        )
        db.add(
            V2GameRun(
                run_id=RUN_ID,
                game_id=GAME_ID,
                attempt_no=1,
                status="ready",
                worker_id=WORKER_ID,
                worker_heartbeat_at=now,
                lease_expires_at=now + timedelta(minutes=5),
                fence_token=1,
            )
        )
        db.add_all(
            [
                V2PlayerState(
                    game_id=GAME_ID,
                    player_id="player_1",
                    seat=1,
                    alive=True,
                    state={},
                ),
                V2PlayerState(
                    game_id=GAME_ID,
                    player_id="player_2",
                    seat=2,
                    alive=True,
                    state={},
                ),
            ]
        )
    fence = V2RunFence(run_id=RUN_ID, worker_id=WORKER_ID, fence_token=1)
    repository = V2ActionRepository(factory, enforce_execution_fence=True)
    public_skip_record_seq: int | None = None
    with bind_v2_run_fence(fence):
        if technical_skip_predecessor:
            public_skip_record_seq = repository.append_event(
                game_id=GAME_ID,
                event_type="action_skipped_technical",
                audience="all",
                payload={
                    "action_id": "v2_action_pipeline_source_failure",
                    "phase_id": PHASE_ID,
                    "round_no": 1,
                    "action_type": "day_debate_speech",
                    "actor_id": "player_1",
                    "player_seat": 1,
                    "reason": "technical_failure",
                },
            )
        predecessor_claim = repository.claim_action(
            game_id=GAME_ID,
            action_id=PREDECESSOR_ACTION_ID,
            context=(
                _technical_skip_context(
                    action_id=PREDECESSOR_ACTION_ID,
                    public_skip_record_seq=public_skip_record_seq,
                )
                if public_skip_record_seq is not None
                else _speech_context(
                    action_id=PREDECESSOR_ACTION_ID,
                    actor_id="player_1",
                )
            ),
            expected_phase_id=PHASE_ID,
            expected_phase_state=PHASE_STATE,
            audience="all",
            context_audience=("all" if technical_skip_predecessor else "player_private"),
        )
    assert predecessor_claim is not None
    predecessor = repository.open_presentation(
        claim=predecessor_claim,
        presentation_id=PREDECESSOR_PRESENTATION_ID,
        speech_id="v2_speech_pipeline_predecessor",
        voice_asset_id="v2_voice_pipeline_predecessor",
        subtitle_text=(
            "1号本轮因技术原因未能完成发言，流程继续。"
            if technical_skip_predecessor
            else "第一位玩家正在公开发言。"
        ),
        sample_rate=24_000,
        actor_kind=("judge" if technical_skip_predecessor else "player"),
        actor_id=("judge" if technical_skip_predecessor else "player_1"),
    )
    assert predecessor.source_event_id is not None
    assert predecessor.source_record_seq is not None
    with factory.begin() as db:
        game = db.get(V2GameRecord, GAME_ID)
        assert game is not None
        cutoff = game.last_record_seq
        db.add(
            V2DaySpeechSlot(
                slot_id=SLOT_ID,
                game_id=GAME_ID,
                run_id=RUN_ID,
                fence_worker_id=WORKER_ID,
                fence_token=1,
                phase_id=PHASE_ID,
                round_no=1,
                speech_round=1,
                turn_index=2,
                action_type="day_debate_speech",
                actor_player_id="player_2",
                predecessor_action_id=PREDECESSOR_ACTION_ID,
                predecessor_presentation_id=PREDECESSOR_PRESENTATION_ID,
                predecessor_source_event_id=predecessor.source_event_id,
                predecessor_source_record_seq=predecessor.source_record_seq,
                context_cutoff_record_seq=cutoff,
                state="generating",
                generation_started_at=now,
            )
        )
    result = _Harness(
        factory=factory,
        repository=repository,
        fence=fence,
        predecessor_claim=predecessor_claim,
        predecessor=predecessor,
        cutoff=cutoff,
    )
    return engine, result


def test_open_presentation_exposes_committed_event_identity(harness: _Harness) -> None:
    with harness.factory() as db:
        source = db.get(
            V2GameRecordEvent,
            (GAME_ID, harness.predecessor.source_event_id),
        )
    assert source is not None
    assert source.event_type == "speech_segment_committed"
    assert source.record_seq == harness.predecessor.source_record_seq


def test_broadcast_generation_claim_binds_slot_and_preserves_foreground_context(
    harness: _Harness,
) -> None:
    action_id = "v2_action_pipeline_generation"
    claim = harness.claim_generation(action_id)
    assert claim is not None
    assert claim.non_blocking is True
    assert claim.audience == "player_private"

    with harness.factory() as db:
        game = db.get(V2GameRecord, GAME_ID)
        run = db.get(V2GameRun, RUN_ID)
        slot = db.get(V2DaySpeechSlot, SLOT_ID)
        contexts = list(
            db.scalars(
                select(V2GameRecordEvent)
                .where(
                    V2GameRecordEvent.game_id == GAME_ID,
                    V2GameRecordEvent.event_type == "action_opened",
                )
                .order_by(V2GameRecordEvent.record_seq)
            )
        )
        foreground = current_action_context(db, GAME_ID)
    assert game is not None and game.status == "broadcasting"
    assert run is not None and run.status == "broadcasting"
    assert slot is not None and slot.generation_action_id == action_id
    assert contexts[-1].payload["context"]["pipeline"] == {
        "slot_id": SLOT_ID,
        "stage": "generation",
        "model_admission_mode": "idle_only",
        "retry_mode": "empty_stream_once_while_predecessor_active",
        "empty_stream_max_attempts": 2,
    }
    assert foreground is not None
    assert foreground["action_id"] == PREDECESSOR_ACTION_ID

    with pytest.raises(
        V2RepositoryError,
        match="already claimed generation",
    ):
        harness.claim_generation("v2_action_pipeline_generation_duplicate")


def test_broadcast_generation_claim_accepts_technical_skip_judge_predecessor(
    technical_skip_harness: _Harness,
) -> None:
    action_id = "v2_action_pipeline_generation_after_technical_skip"

    claim = technical_skip_harness.claim_generation(action_id)

    assert claim is not None
    assert claim.non_blocking is True
    with technical_skip_harness.factory() as db:
        slot = db.get(V2DaySpeechSlot, SLOT_ID)
        predecessor = db.scalar(
            select(V2LivePresentation).where(
                V2LivePresentation.game_id == GAME_ID,
                V2LivePresentation.presentation_id == PREDECESSOR_PRESENTATION_ID,
            )
        )
    assert slot is not None and slot.generation_action_id == action_id
    assert predecessor is not None
    assert predecessor.actor_kind == "judge" and predecessor.actor_id == "judge"


@pytest.mark.parametrize(
    ("case", "expected"),
    [
        ("skipped_player_changed", "technical skip predecessor context is invalid"),
        ("public_skip_actor_changed", "technical skip predecessor public fact is invalid"),
    ],
)
def test_broadcast_generation_claim_rejects_technical_skip_lineage_drift(
    technical_skip_harness: _Harness,
    case: str,
    expected: str,
) -> None:
    with technical_skip_harness.factory.begin() as db:
        if case == "skipped_player_changed":
            opened = db.scalar(
                select(V2GameRecordEvent).where(
                    V2GameRecordEvent.game_id == GAME_ID,
                    V2GameRecordEvent.event_type == "action_opened",
                    V2GameRecordEvent.payload["context"]["action_type"].as_string()
                    == "judge_day_speech_technical_skip",
                )
            )
            assert opened is not None
            payload = dict(opened.payload)
            context = dict(payload["context"])
            context["skipped_player_id"] = "player_changed"
            opened.payload = {**payload, "context": context}
        else:
            public_skip = db.scalar(
                select(V2GameRecordEvent).where(
                    V2GameRecordEvent.game_id == GAME_ID,
                    V2GameRecordEvent.event_type == "action_skipped_technical",
                )
            )
            assert public_skip is not None
            public_skip.payload = {
                **public_skip.payload,
                "actor_id": "player_changed",
            }

    with pytest.raises(V2RepositoryError, match=expected):
        technical_skip_harness.claim_generation(f"v2_action_pipeline_generation_invalid_{case}")
    with technical_skip_harness.factory() as db:
        slot = db.get(V2DaySpeechSlot, SLOT_ID)
    assert slot is not None and slot.generation_action_id is None


def test_other_broadcasting_action_remains_unclaimable(harness: _Harness) -> None:
    action_id = "v2_action_pipeline_foreground_collision"
    with bind_v2_run_fence(harness.fence):
        claim = harness.repository.claim_action(
            game_id=GAME_ID,
            action_id=action_id,
            context=_speech_context(action_id=action_id, actor_id="player_2"),
            expected_phase_id=PHASE_ID,
            expected_phase_state=PHASE_STATE,
            audience="all",
            context_audience="player_private",
        )
    assert claim is None
    with harness.factory() as db:
        slot = db.get(V2DaySpeechSlot, SLOT_ID)
        opened = list(
            db.scalars(
                select(V2GameRecordEvent).where(
                    V2GameRecordEvent.game_id == GAME_ID,
                    V2GameRecordEvent.event_type == "action_opened",
                )
            )
        )
    assert slot is not None and slot.generation_action_id is None
    assert all(event.payload.get("action_id") != action_id for event in opened)


def test_pipeline_generation_cannot_fall_through_to_ready_claim(harness: _Harness) -> None:
    action_id = "v2_action_pipeline_generation_from_ready"
    with harness.factory.begin() as db:
        game = db.get(V2GameRecord, GAME_ID)
        run = db.get(V2GameRun, RUN_ID)
        assert game is not None and run is not None
        game.status = "ready"
        run.status = "ready"

    with pytest.raises(V2RepositoryError, match="requires an active broadcast"):
        harness.claim_generation(action_id)

    with harness.factory() as db:
        slot = db.get(V2DaySpeechSlot, SLOT_ID)
        opened = list(
            db.scalars(
                select(V2GameRecordEvent).where(
                    V2GameRecordEvent.game_id == GAME_ID,
                    V2GameRecordEvent.event_type == "action_opened",
                )
            )
        )
    assert slot is not None and slot.generation_action_id is None
    assert all(event.payload.get("action_id") != action_id for event in opened)


@pytest.mark.parametrize(
    ("case", "expected"),
    [
        ("blocking", "not isolated"),
        ("best_effort", "not isolated"),
        ("normal_admission", "not isolated"),
        ("retry_policy_changed", "retry policy is not frozen"),
        ("cutoff_changed", "context lineage"),
        ("text_only", "not frozen and enabled"),
        ("inactive_predecessor", "unique active presentation"),
        ("slot_fence_changed", "fence_lost"),
    ],
)
def test_broadcast_generation_claim_fails_closed_on_contract_or_lineage_drift(
    harness: _Harness,
    case: str,
    expected: str,
) -> None:
    action_id = f"v2_action_pipeline_invalid_{case}"
    context = harness.generation_context(action_id)
    best_effort = case == "best_effort"
    non_blocking = case != "blocking"
    if case == "normal_admission":
        context["pipeline"]["model_admission_mode"] = "normal"
    elif case == "retry_policy_changed":
        context["pipeline"]["empty_stream_max_attempts"] = 1
    elif case == "cutoff_changed":
        context["projection_at_seq"] = harness.cutoff - 1
        context["public_cutoff_record_seq"] = harness.cutoff - 1
    elif case in {"text_only", "inactive_predecessor", "slot_fence_changed"}:
        with harness.factory.begin() as db:
            if case == "text_only":
                game = db.get(V2GameRecord, GAME_ID)
                assert game is not None
                game.delivery_snapshot = {"schema_version": 1, "mode": "text_only"}
            elif case == "inactive_predecessor":
                presentation = db.scalar(
                    select(V2LivePresentation).where(
                        V2LivePresentation.game_id == GAME_ID,
                        V2LivePresentation.presentation_id == PREDECESSOR_PRESENTATION_ID,
                    )
                )
                assert presentation is not None
                presentation.state = "closed"
                presentation.closed_at = datetime.now(tz=UTC)
            else:
                slot = db.get(V2DaySpeechSlot, SLOT_ID)
                assert slot is not None
                slot.fence_token += 1

    with pytest.raises(V2RepositoryError, match=expected):
        harness.claim_generation(
            action_id,
            context=context,
            best_effort=best_effort,
            non_blocking=non_blocking,
        )
    with harness.factory() as db:
        slot = db.get(V2DaySpeechSlot, SLOT_ID)
    assert slot is not None and slot.generation_action_id is None


def test_fail_action_returns_durable_failure_record_seq(harness: _Harness) -> None:
    action_id = "v2_action_pipeline_failure"
    claim = harness.claim_generation(action_id)
    assert claim is not None
    failure_seq = harness.repository.fail_action(
        claim=claim,
        failure_kind="model",
        failure_code="model_prefetch_capacity_unavailable",
        identity=None,
        failure_episode_disposition="isolated_action_failure",
    )
    assert type(failure_seq) is int and failure_seq > 0
    with harness.factory() as db:
        failure = db.scalar(
            select(V2GameRecordEvent).where(
                V2GameRecordEvent.game_id == GAME_ID,
                V2GameRecordEvent.record_seq == failure_seq,
            )
        )
        game = db.get(V2GameRecord, GAME_ID)
    assert failure is not None
    assert failure.event_type == "action_failed"
    assert failure.payload["action_id"] == action_id
    assert failure.payload["audience"] == "player_private"
    assert game is not None and game.status == "broadcasting"


@pytest.mark.parametrize("slot_state", ["generating", "presenting"])
def test_operator_cancel_terminates_nonterminal_day_speech_slot(
    harness: _Harness,
    slot_state: str,
) -> None:
    with harness.factory.begin() as db:
        run = db.get(V2GameRun, RUN_ID)
        slot = db.get(V2DaySpeechSlot, SLOT_ID)
        assert run is not None and slot is not None
        run.stop_requested_at = datetime.now(tz=UTC)
        slot.state = slot_state
        if slot_state == "presenting":
            slot.generation_action_id = "v2_action_pipeline_generated"
            slot.presentation_action_id = PREDECESSOR_ACTION_ID
            slot.presentation_id = PREDECESSOR_PRESENTATION_ID

    result = harness.repository.cancel_game(GAME_ID)
    assert result.changed is True
    assert result.status == "canceled"

    with harness.factory() as db:
        slot = db.get(V2DaySpeechSlot, SLOT_ID)
        presentation = db.scalar(
            select(V2LivePresentation).where(
                V2LivePresentation.game_id == GAME_ID,
                V2LivePresentation.presentation_id == PREDECESSOR_PRESENTATION_ID,
            )
        )
        events = list(
            db.scalars(
                select(V2GameRecordEvent)
                .where(V2GameRecordEvent.game_id == GAME_ID)
                .order_by(V2GameRecordEvent.record_seq)
            )
        )
    assert slot is not None
    assert slot.state == "canceled"
    assert slot.failure == {
        "kind": "canceled",
        "reason_code": "operator_interrupted",
    }
    assert slot.terminal_at is not None
    assert presentation is not None and presentation.state == "canceled"
    slot_canceled = [event for event in events if event.event_type == "day_speech_slot_canceled"]
    assert len(slot_canceled) == 1
    assert slot_canceled[0].payload == {
        "slot_id": SLOT_ID,
        "slot_run_id": RUN_ID,
        "phase_id": PHASE_ID,
        "round_no": 1,
        "speech_round": 1,
        "turn_index": 2,
        "actor_player_id": "player_2",
        "state": "canceled",
        "reason_code": "operator_interrupted",
        "audience": "god_view",
        "audience_contract_version": 1,
    }
    interrupted = next(event for event in events if event.event_type == "speech_interrupted")
    assert interrupted.record_seq < slot_canceled[0].record_seq
    game_canceled = next(event for event in events if event.event_type == "game_canceled")
    assert game_canceled.payload["canceled_day_speech_slot_count"] == 1


def test_operator_cancel_terminalizes_open_pipeline_attempt_and_action(
    harness: _Harness,
) -> None:
    action_id = "v2_action_pipeline_cancel_open"
    attempt_id = "v2_attempt_pipeline_cancel_open"
    claim = harness.claim_generation(action_id)
    assert claim is not None
    with bind_v2_run_fence(harness.fence):
        harness.repository.append_event(
            game_id=GAME_ID,
            event_type="model_request_started",
            audience="player_private",
            payload={
                "action_id": action_id,
                "attempt_id": attempt_id,
                "attempt_no": 1,
                "cycle_attempt_no": 1,
                "retry_cycle": 1,
                "max_attempts": 3,
                "request_payload": {"private_marker": "must-not-be-copied"},
            },
        )
    with harness.factory.begin() as db:
        run = db.get(V2GameRun, RUN_ID)
        assert run is not None
        run.stop_requested_at = datetime.now(tz=UTC)

    first = harness.repository.cancel_game(GAME_ID)
    second = harness.repository.cancel_game(GAME_ID)
    assert first.changed is True
    assert second.changed is False

    with harness.factory() as db:
        game = db.get(V2GameRecord, GAME_ID)
        run = db.get(V2GameRun, RUN_ID)
        slot = db.get(V2DaySpeechSlot, SLOT_ID)
        events = list(
            db.scalars(
                select(V2GameRecordEvent)
                .where(V2GameRecordEvent.game_id == GAME_ID)
                .order_by(V2GameRecordEvent.record_seq)
            )
        )
    attempt_failures = [
        event
        for event in events
        if event.event_type == "model_request_failed"
        and event.payload.get("attempt_id") == attempt_id
    ]
    action_failures = [
        event
        for event in events
        if event.event_type == "action_failed" and event.payload.get("action_id") == action_id
    ]
    assert len(attempt_failures) == 1
    assert len(action_failures) == 1
    attempt_failure = attempt_failures[0]
    action_failure = action_failures[0]
    assert attempt_failure.payload["audience"] == "player_private"
    assert action_failure.payload["audience"] == "player_private"
    assert attempt_failure.payload["failure_code"] == "day_speech_prefetch_canceled"
    assert attempt_failure.payload["provider_outcome_unknown"] is True
    assert attempt_failure.payload["attempt_terminal"] is True
    assert attempt_failure.payload["terminal"] is True
    assert "request_payload" not in attempt_failure.payload
    assert "private_marker" not in action_failure.payload
    assert action_failure.payload["canceled_failure_episode_ids"] == [
        attempt_failure.payload["failure_episode_id"]
    ]

    slot_canceled = next(
        event for event in events if event.event_type == "day_speech_slot_canceled"
    )
    game_canceled = next(event for event in events if event.event_type == "game_canceled")
    started = next(
        event
        for event in events
        if event.event_type == "model_request_started"
        and event.payload.get("attempt_id") == attempt_id
    )
    assert (
        started.record_seq
        < attempt_failure.record_seq
        < action_failure.record_seq
        < slot_canceled.record_seq
        < game_canceled.record_seq
    )
    assert (
        attempt_failure.payload["failure_episode_id"]
        in game_canceled.payload["canceled_failure_episode_ids"]
    )
    episodes = {episode.failure_episode_id: episode for episode in derive_failure_episodes(events)}
    episode = episodes[attempt_failure.payload["failure_episode_id"]]
    assert episode.resolution == "run_canceled"
    assert episode.invariant_errors == ()
    assert game is not None and game.status == "canceled"
    assert run is not None and run.status == "canceled"
    assert slot is not None and slot.state == "canceled"


def test_operator_cancel_does_not_duplicate_terminal_pipeline_lifecycle(
    harness: _Harness,
) -> None:
    action_id = "v2_action_pipeline_cancel_terminal"
    attempt_id = "v2_attempt_pipeline_cancel_terminal"
    claim = harness.claim_generation(action_id)
    assert claim is not None
    with bind_v2_run_fence(harness.fence):
        harness.repository.append_event(
            game_id=GAME_ID,
            event_type="model_request_started",
            audience="player_private",
            payload={
                "action_id": action_id,
                "attempt_id": attempt_id,
                "attempt_no": 1,
                "cycle_attempt_no": 1,
                "retry_cycle": 1,
                "max_attempts": 3,
            },
        )
        harness.repository.append_event(
            game_id=GAME_ID,
            event_type="model_response_received",
            audience="player_private",
            payload={
                "action_id": action_id,
                "attempt_id": attempt_id,
                "retry_cycle": 1,
                "application_validation_result": "accepted",
            },
        )
        harness.repository.complete_silent_action(
            claim=claim,
            next_live_state="ready",
            next_phase_state=PHASE_STATE,
        )
    with harness.factory.begin() as db:
        run = db.get(V2GameRun, RUN_ID)
        assert run is not None
        run.stop_requested_at = datetime.now(tz=UTC)

    harness.repository.cancel_game(GAME_ID)

    with harness.factory() as db:
        events = list(
            db.scalars(
                select(V2GameRecordEvent)
                .where(V2GameRecordEvent.game_id == GAME_ID)
                .order_by(V2GameRecordEvent.record_seq)
            )
        )
    assert not [
        event
        for event in events
        if event.event_type == "model_request_failed"
        and event.payload.get("attempt_id") == attempt_id
    ]
    assert not [
        event
        for event in events
        if event.event_type == "action_failed" and event.payload.get("action_id") == action_id
    ]
    action_successes = [
        event
        for event in events
        if event.event_type == "action_succeeded" and event.payload.get("action_id") == action_id
    ]
    responses = [
        event
        for event in events
        if event.event_type == "model_response_received"
        and event.payload.get("attempt_id") == attempt_id
    ]
    assert len(action_successes) == 1
    assert len(responses) == 1


def test_operator_cancel_closes_only_open_retry_attempt_in_same_episode(
    harness: _Harness,
) -> None:
    action_id = "v2_action_pipeline_cancel_retry"
    first_attempt_id = "v2_attempt_pipeline_cancel_retry_1"
    second_attempt_id = "v2_attempt_pipeline_cancel_retry_2"
    claim = harness.claim_generation(action_id)
    assert claim is not None
    failure_episode_id = stable_failure_episode_id(
        game_id=GAME_ID,
        run_id=RUN_ID,
        action_id=action_id,
        retry_cycle=1,
        first_failed_attempt_id=first_attempt_id,
    )
    with bind_v2_run_fence(harness.fence):
        harness.repository.append_event(
            game_id=GAME_ID,
            event_type="model_request_started",
            audience="player_private",
            payload={
                "action_id": action_id,
                "attempt_id": first_attempt_id,
                "attempt_no": 1,
                "cycle_attempt_no": 1,
                "retry_cycle": 1,
                "max_attempts": 3,
            },
        )
        harness.repository.append_event(
            game_id=GAME_ID,
            event_type="model_request_failed",
            audience="player_private",
            payload={
                "action_id": action_id,
                "attempt_id": first_attempt_id,
                "attempt_no": 1,
                "cycle_attempt_no": 1,
                "retry_cycle": 1,
                "max_attempts": 3,
                "failure_kind": "model",
                "failure_code": "model_empty_stream",
                "failure_category": "transport",
                "failure_episode_id": failure_episode_id,
                "retryable": True,
                "attempt_terminal": True,
                "action_recoverable": True,
                "run_terminal": False,
                "terminal": False,
                "automatic_retry_scheduled": True,
            },
        )
        harness.repository.append_event(
            game_id=GAME_ID,
            event_type="model_retry_scheduled",
            audience="player_private",
            payload={
                "action_id": action_id,
                "attempt_id": first_attempt_id,
                "next_attempt_id": second_attempt_id,
                "retry_cycle": 1,
                "failure_episode_id": failure_episode_id,
            },
        )
        harness.repository.append_event(
            game_id=GAME_ID,
            event_type="model_request_started",
            audience="player_private",
            payload={
                "action_id": action_id,
                "attempt_id": second_attempt_id,
                "attempt_no": 2,
                "cycle_attempt_no": 2,
                "retry_cycle": 1,
                "max_attempts": 3,
                "retry_of_attempt_id": first_attempt_id,
                "failure_episode_id": failure_episode_id,
            },
        )
    with harness.factory.begin() as db:
        run = db.get(V2GameRun, RUN_ID)
        assert run is not None
        run.stop_requested_at = datetime.now(tz=UTC)

    harness.repository.cancel_game(GAME_ID)

    with harness.factory() as db:
        events = list(
            db.scalars(
                select(V2GameRecordEvent)
                .where(V2GameRecordEvent.game_id == GAME_ID)
                .order_by(V2GameRecordEvent.record_seq)
            )
        )
    failures = [
        event
        for event in events
        if event.event_type == "model_request_failed"
        and event.payload.get("action_id") == action_id
    ]
    assert [event.payload["attempt_id"] for event in failures] == [
        first_attempt_id,
        second_attempt_id,
    ]
    assert {event.payload["failure_episode_id"] for event in failures} == {failure_episode_id}
    action_failure = next(
        event
        for event in events
        if event.event_type == "action_failed" and event.payload.get("action_id") == action_id
    )
    assert action_failure.payload["canceled_failure_episode_ids"] == [failure_episode_id]
    episodes = {episode.failure_episode_id: episode for episode in derive_failure_episodes(events)}
    assert episodes[failure_episode_id].resolution == "run_canceled"
    assert episodes[failure_episode_id].invariant_errors == ()


def _speech_context(
    *,
    action_id: str,
    actor_id: str,
    pipeline: dict[str, Any] | None = None,
    public_cutoff_record_seq: int | None = None,
    projection_at_seq: int | None = None,
    batch_id: str | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "action_id": action_id,
        "action_type": "day_debate_speech",
        "game_id": GAME_ID,
        "phase_id": PHASE_ID,
        "actor": {"kind": "player", "id": actor_id},
        "objective": "发表本轮白天讨论发言。",
        "output_contract": {"kind": "speech"},
        "speech_round": 1,
        "speech_order": ["player_1", "player_2"],
        **({"pipeline": pipeline} if pipeline is not None else {}),
        **(
            {"public_cutoff_record_seq": public_cutoff_record_seq}
            if public_cutoff_record_seq is not None
            else {}
        ),
        **({"projection_at_seq": projection_at_seq} if projection_at_seq is not None else {}),
        **({"batch_id": batch_id} if batch_id is not None else {}),
    }


def _technical_skip_context(
    *,
    action_id: str,
    public_skip_record_seq: int,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "action_id": action_id,
        "action_type": "judge_day_speech_technical_skip",
        "game_id": GAME_ID,
        "phase_id": PHASE_ID,
        "actor": {"kind": "judge", "id": "judge"},
        "objective": "说明1号本轮因技术原因未能完成发言，流程继续。",
        "output_contract": {"kind": "speech"},
        "round_no": 1,
        "player_seat": 1,
        "skipped_player_id": "player_1",
        "speech_round": 1,
        "speech_order": ["player_1", "player_2"],
        "public_skip_record_seq": public_skip_record_seq,
    }
