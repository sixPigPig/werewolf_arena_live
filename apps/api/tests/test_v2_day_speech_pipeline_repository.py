from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.models.user import User  # noqa: F401 - registers the referenced users table
from app.match.day_speech_pipeline_contract import (
    DaySpeechPipelineContractError,
    current_day_speech_pipeline_contract,
    freeze_day_speech_pipeline_contract,
    resolve_day_speech_pipeline_contract,
)
from app.match.day_speech_pipeline_repository import (
    DaySpeechPipelineRepository,
    DaySpeechPipelineRepositoryError,
    DaySpeechSlotSnapshot,
)
from app.match.event_contract import canonical_event_payload
from app.match.execution import RunFence, bind_run_fence
from app.match.model_context_contract import freeze_model_context_contract
from app.match.model_generation_policy_contract import (
    freeze_model_generation_policy_contract,
)
from app.match.models import (
    GameRecord,
    GameRecordEvent,
    GameRun,
    LivePresentation,
    PlayerState,
)
from app.match.repository import (
    ActionClaim,
    ActionRepository,
    ExecutionOwnershipLost,
    PresentationIdentity,
)
from app.match.service import create_waiting_game


GAME_ID = "v2_game_day_speech_slots"
RUN_ID = "v2_run_day_speech_slots"
PHASE_ID = "day_1"
PHASE_STATE = "public_discussion_open"
WORKER_ID = "v2_worker_day_speech_slots"
PREDECESSOR_ACTION_ID = "v2_action_day_predecessor"
PREDECESSOR_PRESENTATION_ID = "v2_pres_day_predecessor"
PREDECESSOR_SOURCE_EVENT_ID = 900


@dataclass(frozen=True)
class _Harness:
    session_factory: sessionmaker[Session]
    actions: ActionRepository
    slots: DaySpeechPipelineRepository
    fence: RunFence
    predecessor_claim: ActionClaim
    predecessor: PresentationIdentity
    predecessor_source_record_seq: int
    cutoff: int

    def reserve(self) -> DaySpeechSlotSnapshot:
        return self.slots.reserve_slot(
            game_id=GAME_ID,
            phase_id=PHASE_ID,
            round_no=1,
            speech_round=1,
            turn_index=2,
            actor_player_id="player_2",
            predecessor_action_id=PREDECESSOR_ACTION_ID,
            predecessor_presentation_id=PREDECESSOR_PRESENTATION_ID,
            predecessor_source_event_id=PREDECESSOR_SOURCE_EVENT_ID,
            predecessor_source_record_seq=self.predecessor_source_record_seq,
            context_cutoff_record_seq=self.cutoff,
            fence=self.fence,
        )


@pytest.fixture
def harness() -> _Harness:
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    rule_snapshot: dict[str, Any] = {
        "rule_set": {"id": "day-speech-slot-test", "sheriff_enabled": False},
        "max_rounds": 8,
    }
    rule_snapshot = freeze_model_context_contract(rule_snapshot)
    rule_snapshot = freeze_model_generation_policy_contract(rule_snapshot)
    rule_snapshot = freeze_day_speech_pipeline_contract(rule_snapshot)
    now = datetime.now(tz=UTC)
    with factory.begin() as db:
        db.add(
            GameRecord(
                game_id=GAME_ID,
                title="day speech slot test",
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
            GameRun(
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
                PlayerState(
                    game_id=GAME_ID,
                    player_id="player_1",
                    seat=1,
                    alive=True,
                    state={},
                ),
                PlayerState(
                    game_id=GAME_ID,
                    player_id="player_2",
                    seat=2,
                    alive=True,
                    state={},
                ),
            ]
        )
    fence = RunFence(run_id=RUN_ID, worker_id=WORKER_ID, fence_token=1)
    actions = ActionRepository(factory, enforce_execution_fence=True)
    with bind_run_fence(fence):
        claim = actions.claim_action(
            game_id=GAME_ID,
            action_id=PREDECESSOR_ACTION_ID,
            context=_speech_context(
                action_id=PREDECESSOR_ACTION_ID,
                actor_player_id="player_1",
            ),
            expected_phase_id=PHASE_ID,
            expected_phase_state=PHASE_STATE,
            audience="all",
            context_audience="player_private",
        )
    assert claim is not None
    predecessor = actions.open_presentation(
        claim=claim,
        presentation_id=PREDECESSOR_PRESENTATION_ID,
        speech_id="v2_speech_day_predecessor",
        voice_asset_id="v2_voice_day_predecessor",
        subtitle_text="第一位玩家的公开发言。",
        sample_rate=24_000,
        actor_kind="player",
        actor_id="player_1",
    )
    with factory.begin() as db:
        presentation = db.get(
            LivePresentation,
            (GAME_ID, predecessor.presentation_seq),
        )
        assert presentation is not None
        source = db.get(
            GameRecordEvent,
            (GAME_ID, presentation.source_event_id),
        )
        assert source is not None
        source_record_seq = source.record_seq
        source.event_id = PREDECESSOR_SOURCE_EVENT_ID
        presentation.source_event_id = PREDECESSOR_SOURCE_EVENT_ID
        game = db.get(GameRecord, GAME_ID)
        assert game is not None
        cutoff = game.last_record_seq
    result = _Harness(
        session_factory=factory,
        actions=actions,
        slots=DaySpeechPipelineRepository(factory),
        fence=fence,
        predecessor_claim=claim,
        predecessor=predecessor,
        predecessor_source_record_seq=source_record_seq,
        cutoff=cutoff,
    )
    try:
        yield result
    finally:
        engine.dispose()


def test_contract_freeze_resolve_and_new_game_summary() -> None:
    legacy = resolve_day_speech_pipeline_contract({})
    assert legacy.status == "legacy_sequential"
    assert legacy.mode == "sequential"
    assert legacy.max_lookahead == 0
    assert legacy.post_predecessor_close_grace_ms is None
    assert legacy.post_predecessor_close_wait_mode == "disabled"
    assert legacy.duplicate_foreground_fallback_forbidden_failure_categories == ()
    assert legacy.early_transport_hidden_retry_max_retries == 0
    assert legacy.prefetch_capacity_unavailable_fallback_mode == "disabled"
    assert not legacy.enables("day_debate_speech")

    schema_v1_contract = {
        "schema_version": 1,
        "mode": "one_ahead",
        "action_types": ["day_debate_speech"],
        "max_lookahead": 1,
        "context_source": "active_sealed_predecessor",
        "admission_mode": "idle_only",
        "fallback_mode": "fallback_sequential",
    }
    schema_v1 = resolve_day_speech_pipeline_contract(
        {"day_speech_pipeline_contract": schema_v1_contract}
    )
    assert schema_v1.status == "supported"
    assert schema_v1.schema_version == 1
    assert schema_v1.fallback_mode == "fallback_sequential"
    assert schema_v1.post_predecessor_close_grace_ms is None
    assert schema_v1.post_predecessor_close_wait_mode == "disabled"
    assert schema_v1.duplicate_foreground_fallback_forbidden_failure_categories == ()
    assert schema_v1.early_transport_hidden_retry_max_retries == 0
    assert schema_v1.prefetch_capacity_unavailable_fallback_mode == "fallback_sequential"

    schema_v2_contract = {
        "schema_version": 2,
        "mode": "one_ahead",
        "action_types": ["day_debate_speech"],
        "max_lookahead": 1,
        "context_source": "active_sealed_predecessor",
        "admission_mode": "idle_only",
        "fallback_mode": "fallback_sequential",
        "post_predecessor_close_grace_ms": 30_000,
        "duplicate_foreground_fallback_forbidden_failure_categories": [
            "output_budget",
            "timeout",
        ],
        "early_transport_hidden_retry_max_retries": 1,
        "prefetch_capacity_unavailable_fallback_mode": "fallback_sequential",
    }
    schema_v2 = resolve_day_speech_pipeline_contract(
        {"day_speech_pipeline_contract": schema_v2_contract}
    )
    assert schema_v2.status == "supported"
    assert schema_v2.schema_version == 2
    assert schema_v2.post_predecessor_close_grace_ms == 30_000
    assert schema_v2.post_predecessor_close_wait_mode == "deadline_then_technical_skip"
    assert schema_v2.duplicate_foreground_fallback_forbidden_failure_categories == (
        "output_budget",
        "timeout",
    )
    assert schema_v2.early_transport_hidden_retry_max_retries == 1

    frozen = freeze_day_speech_pipeline_contract({"rule_set": {"id": "test"}})
    assert frozen["day_speech_pipeline_contract"] == (current_day_speech_pipeline_contract())
    resolved = resolve_day_speech_pipeline_contract(frozen)
    assert resolved.status == "supported"
    assert resolved.schema_version == 3
    assert resolved.enables("day_debate_speech")
    assert not resolved.enables("sheriff_campaign_speech")
    assert resolved.post_predecessor_close_grace_ms is None
    assert resolved.post_predecessor_close_wait_mode == "await_same_inflight_to_terminal"
    assert resolved.duplicate_foreground_fallback_forbidden_failure_categories == (
        "output_budget",
        "timeout",
    )
    assert resolved.early_transport_hidden_retry_max_retries == 1
    assert resolved.prefetch_capacity_unavailable_fallback_mode == "fallback_sequential"

    malformed_contracts = [
        {**current_day_speech_pipeline_contract(), "max_lookahead": 2},
        {**current_day_speech_pipeline_contract(), "unexpected": True},
        {
            key: value
            for key, value in current_day_speech_pipeline_contract().items()
            if key != "post_predecessor_close_wait_mode"
        },
        {
            **current_day_speech_pipeline_contract(),
            "post_predecessor_close_wait_mode": "deadline_then_technical_skip",
        },
        {**current_day_speech_pipeline_contract(), "post_predecessor_close_grace_ms": 30_000},
        {
            key: value
            for key, value in schema_v2_contract.items()
            if key != "post_predecessor_close_grace_ms"
        },
        {**schema_v1_contract, "post_predecessor_close_grace_ms": 30_000},
    ]
    for malformed_contract in malformed_contracts:
        with pytest.raises(
            DaySpeechPipelineContractError,
            match="unsupported_day_speech_pipeline_contract",
        ):
            resolve_day_speech_pipeline_contract(
                {"day_speech_pipeline_contract": malformed_contract}
            )

    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as db:
        game, _run, _token = create_waiting_game(
            db,
            title="pipeline contract summary",
            delivery_snapshot={"schema_version": 1, "mode": "tts"},
        )
        game_id = game.game_id
    with factory() as db:
        game = db.get(GameRecord, game_id)
        created = db.scalar(
            select(GameRecordEvent).where(
                GameRecordEvent.game_id == game_id,
                GameRecordEvent.event_type == "game_created",
            )
        )
        assert game is not None and created is not None
        assert game.rule_snapshot["day_speech_pipeline_contract"] == (
            current_day_speech_pipeline_contract()
        )
        summary = created.payload["day_speech_pipeline_contract"]
        assert summary == {
            "status": "supported",
            "schema_version": 3,
            "mode": "one_ahead",
            "action_types": ["day_debate_speech"],
            "max_lookahead": 1,
            "context_source": "active_sealed_predecessor",
            "admission_mode": "idle_only",
            "fallback_mode": "fallback_sequential",
            "post_predecessor_close_grace_ms": None,
            "post_predecessor_close_wait_mode": "await_same_inflight_to_terminal",
            "duplicate_foreground_fallback_forbidden_failure_categories": [
                "output_budget",
                "timeout",
            ],
            "early_transport_hidden_retry_max_retries": 1,
            "prefetch_capacity_unavailable_fallback_mode": "fallback_sequential",
        }
    engine.dispose()


def test_slot_happy_path_is_idempotent_ordered_and_private(harness: _Harness) -> None:
    slot = harness.reserve()
    assert slot.state == "reserved"
    assert slot.predecessor_source_event_id == PREDECESSOR_SOURCE_EVENT_ID
    assert slot.predecessor_source_record_seq != slot.predecessor_source_event_id
    assert harness.reserve().slot_id == slot.slot_id

    assert harness.slots.mark_generating(slot_id=slot.slot_id, fence=harness.fence).state == (
        "generating"
    )
    assert harness.slots.predecessor_is_active(slot.slot_id) is True
    action_id = "v2_action_day_prefetch_generation"
    response_seq = _append_generation_success(
        harness,
        slot=slot,
        action_id=action_id,
        speech="第二位玩家提前生成但尚未展示的发言。",
    )
    ready = harness.slots.mark_ready(
        slot_id=slot.slot_id,
        generation_action_id=action_id,
        generation_response_record_seq=response_seq,
        fence=harness.fence,
    )
    assert ready.state == "ready"
    assert ready.generation_attempt_id == "v2_model_day_prefetch"
    assert ready.decision == {
        "target_player_ref": None,
        "target_player_id": None,
        "speech": "第二位玩家提前生成但尚未展示的发言。",
        "decision_note": None,
    }
    assert (
        harness.slots.mark_ready(
            slot_id=slot.slot_id,
            generation_action_id=action_id,
            generation_response_record_seq=response_seq,
            fence=harness.fence,
        ).state
        == "ready"
    )

    _complete_voice_action(harness, harness.predecessor)
    with bind_run_fence(harness.fence):
        next_claim = harness.actions.claim_action(
            game_id=GAME_ID,
            action_id="v2_action_day_prefetch_presentation",
            context=_speech_context(
                action_id="v2_action_day_prefetch_presentation",
                actor_player_id="player_2",
                pipeline={
                    "slot_id": slot.slot_id,
                    "stage": "presentation",
                    "model_admission_mode": "normal",
                },
            ),
            expected_phase_id=PHASE_ID,
            expected_phase_state=PHASE_STATE,
            audience="all",
            context_audience="player_private",
        )
    assert next_claim is not None
    next_presentation = harness.actions.open_presentation(
        claim=next_claim,
        presentation_id="v2_pres_day_prefetch",
        speech_id="v2_speech_day_prefetch",
        voice_asset_id="v2_voice_day_prefetch",
        subtitle_text=str(ready.decision["speech"]),
        sample_rate=24_000,
        actor_kind="player",
        actor_id="player_2",
    )
    presenting = harness.slots.mark_presenting(
        slot_id=slot.slot_id,
        presentation_action_id=next_claim.action_id,
        presentation_id=next_presentation.presentation_id,
        fence=harness.fence,
    )
    assert presenting.state == "presenting"
    _complete_voice_action(harness, next_presentation)
    consumed = harness.slots.mark_consumed(slot_id=slot.slot_id, fence=harness.fence)
    assert consumed.state == "consumed"
    assert consumed.consumed_at is not None
    assert consumed.terminal_at == consumed.consumed_at

    with harness.session_factory() as db:
        lifecycle = list(
            db.scalars(
                select(GameRecordEvent)
                .where(
                    GameRecordEvent.game_id == GAME_ID,
                    GameRecordEvent.event_type.like("day_speech_slot_%"),
                )
                .order_by(GameRecordEvent.record_seq)
            )
        )
    assert [event.event_type for event in lifecycle] == [
        "day_speech_slot_reserved",
        "day_speech_slot_generation_started",
        "day_speech_slot_ready",
        "day_speech_slot_presenting",
        "day_speech_slot_consumed",
    ]
    assert all(event.payload["audience"] == "god_view" for event in lifecycle)
    assert all("decision" not in event.payload for event in lifecycle)
    assert all("speech" not in event.payload for event in lifecycle)


def test_slot_accepts_active_technical_skip_judge_cue_as_turn_predecessor(
    harness: _Harness,
) -> None:
    _complete_voice_action(harness, harness.predecessor)
    with harness.session_factory.begin() as db:
        db.add(
            PlayerState(
                game_id=GAME_ID,
                player_id="player_3",
                seat=3,
                alive=True,
                state={},
            )
        )
    public_skip_record_seq = harness.actions.append_event(
        game_id=GAME_ID,
        event_type="action_skipped_technical",
        audience="all",
        payload={
            "action_id": "v2_action_failed_player_2",
            "phase_id": PHASE_ID,
            "round_no": 1,
            "action_type": "day_debate_speech",
            "actor_id": "player_2",
            "player_seat": 2,
            "reason": "technical_failure",
        },
        fence=harness.fence,
    )
    judge_action_id = "v2_action_judge_technical_skip"
    with bind_run_fence(harness.fence):
        claim = harness.actions.claim_action(
            game_id=GAME_ID,
            action_id=judge_action_id,
            context={
                "schema_version": 1,
                "action_id": judge_action_id,
                "action_type": "judge_day_speech_technical_skip",
                "game_id": GAME_ID,
                "phase_id": PHASE_ID,
                "actor": {"kind": "judge", "id": "judge"},
                "objective": "播报技术跳过提示",
                "output_contract": {"kind": "speech"},
                "round_no": 1,
                "skipped_player_id": "player_2",
                "speech_round": 1,
                "speech_order": ["player_1", "player_2", "player_3"],
                "public_skip_record_seq": public_skip_record_seq,
            },
            expected_phase_id=PHASE_ID,
            expected_phase_state=PHASE_STATE,
            audience="all",
            context_audience="god_view",
        )
    assert claim is not None
    judge = harness.actions.open_presentation(
        claim=claim,
        presentation_id="v2_pres_judge_technical_skip",
        speech_id="v2_speech_judge_technical_skip",
        voice_asset_id="v2_voice_judge_technical_skip",
        subtitle_text="2号本轮因技术原因未能完成发言，流程继续",
        sample_rate=24_000,
        actor_kind="judge",
        actor_id="judge",
    )
    with harness.session_factory() as db:
        source = db.get(GameRecordEvent, (GAME_ID, judge.source_event_id))
        game = db.get(GameRecord, GAME_ID)
        assert source is not None and game is not None
        source_record_seq = source.record_seq
        cutoff = game.last_record_seq

    slot = harness.slots.reserve_slot(
        game_id=GAME_ID,
        phase_id=PHASE_ID,
        round_no=1,
        speech_round=1,
        turn_index=3,
        actor_player_id="player_3",
        predecessor_action_id=judge.action_id,
        predecessor_presentation_id=judge.presentation_id,
        predecessor_source_event_id=int(judge.source_event_id),
        predecessor_source_record_seq=source_record_seq,
        context_cutoff_record_seq=cutoff,
        predecessor_turn_player_id="player_2",
        fence=harness.fence,
    )

    assert slot.state == "reserved"
    assert slot.actor_player_id == "player_3"
    assert slot.turn_index == 3

    with pytest.raises(
        DaySpeechPipelineRepositoryError,
        match="active public TTS presentation",
    ):
        harness.slots.reserve_slot(
            game_id=GAME_ID,
            phase_id=PHASE_ID,
            round_no=1,
            speech_round=1,
            turn_index=3,
            actor_player_id="player_3",
            predecessor_action_id=judge.action_id,
            predecessor_presentation_id=judge.presentation_id,
            predecessor_source_event_id=int(judge.source_event_id),
            predecessor_source_record_seq=source_record_seq,
            context_cutoff_record_seq=cutoff,
            fence=harness.fence,
        )

    harness.slots.mark_generating(slot_id=slot.slot_id, fence=harness.fence)
    generation_action_id = "v2_action_prefetch_after_technical_skip"
    response_seq = _append_generation_success(
        harness,
        slot=slot,
        action_id=generation_action_id,
        speech="第三位玩家在技术提示期间提前生成的发言。",
    )
    ready = harness.slots.mark_ready(
        slot_id=slot.slot_id,
        generation_action_id=generation_action_id,
        generation_response_record_seq=response_seq,
        fence=harness.fence,
    )
    _complete_voice_action(harness, judge)
    with bind_run_fence(harness.fence):
        player_claim = harness.actions.claim_action(
            game_id=GAME_ID,
            action_id="v2_action_present_after_technical_skip",
            context=_speech_context(
                action_id="v2_action_present_after_technical_skip",
                actor_player_id="player_3",
                pipeline={
                    "slot_id": slot.slot_id,
                    "stage": "presentation",
                    "model_admission_mode": "normal",
                },
            ),
            expected_phase_id=PHASE_ID,
            expected_phase_state=PHASE_STATE,
            audience="all",
            context_audience="player_private",
        )
    assert player_claim is not None
    player_presentation = harness.actions.open_presentation(
        claim=player_claim,
        presentation_id="v2_pres_after_technical_skip",
        speech_id="v2_speech_after_technical_skip",
        voice_asset_id="v2_voice_after_technical_skip",
        subtitle_text=str(ready.decision["speech"]),
        sample_rate=24_000,
        actor_kind="player",
        actor_id="player_3",
    )
    presenting = harness.slots.mark_presenting(
        slot_id=slot.slot_id,
        presentation_action_id=player_claim.action_id,
        presentation_id=player_presentation.presentation_id,
        fence=harness.fence,
    )
    assert presenting.state == "presenting"
    _complete_voice_action(harness, player_presentation)
    assert (
        harness.slots.mark_consumed(slot_id=slot.slot_id, fence=harness.fence).state == "consumed"
    )


def test_slot_rejects_illegal_transition_and_wrong_context_cutoff(
    harness: _Harness,
) -> None:
    slot = harness.reserve()
    with pytest.raises(
        DaySpeechPipelineRepositoryError,
        match="cannot transition from reserved",
    ):
        harness.slots.mark_ready(
            slot_id=slot.slot_id,
            generation_action_id="v2_action_too_early",
            generation_response_record_seq=harness.cutoff,
            fence=harness.fence,
        )
    harness.slots.mark_generating(slot_id=slot.slot_id, fence=harness.fence)
    action_id = "v2_action_wrong_cutoff"
    response_seq = _append_generation_success(
        harness,
        slot=slot,
        action_id=action_id,
        speech="不会被接受的错误截止发言。",
        projection_at_seq=harness.cutoff - 1,
    )
    with pytest.raises(
        DaySpeechPipelineRepositoryError,
        match="changed its frozen context cutoff",
    ):
        harness.slots.mark_ready(
            slot_id=slot.slot_id,
            generation_action_id=action_id,
            generation_response_record_seq=response_seq,
            fence=harness.fence,
        )
    assert harness.slots.get_slot(slot.slot_id).state == "generating"


def test_slot_failure_requires_durable_pipeline_action_lineage(harness: _Harness) -> None:
    slot = harness.reserve()
    harness.slots.mark_generating(slot_id=slot.slot_id, fence=harness.fence)
    action_id = "v2_action_day_prefetch_failed"
    opened_seq = _append_action_opened(
        harness,
        slot=slot,
        action_id=action_id,
        stage="generation",
    )
    request_failure_seq = _append_record_event(
        harness.session_factory,
        event_type="model_request_failed",
        audience="player_private",
        payload={
            "action_id": action_id,
            "attempt_id": "v2_model_day_prefetch_failed",
            "failure_kind": "model_error",
            "failure_code": "model_prefetch_capacity_unavailable",
            "raw_response": "must remain private",
        },
    )
    failure_seq = _append_record_event(
        harness.session_factory,
        event_type="action_failed",
        audience="all",
        payload={
            "action_id": action_id,
            "presentation_id": None,
            "failure_kind": "model_error",
            "failure_code": "model_prefetch_capacity_unavailable",
        },
    )
    assert opened_seq < request_failure_seq < failure_seq
    failed = harness.slots.mark_failed(
        slot_id=slot.slot_id,
        failure_record_seq=failure_seq,
        fence=harness.fence,
    )
    assert failed.state == "failed"
    assert failed.generation_action_id == action_id
    assert failed.generation_attempt_id == "v2_model_day_prefetch_failed"
    assert failed.failure is not None
    assert failed.failure["model_request_failed"]["raw_response"] == ("must remain private")
    with harness.session_factory() as db:
        lifecycle = db.scalar(
            select(GameRecordEvent).where(
                GameRecordEvent.game_id == GAME_ID,
                GameRecordEvent.event_type == "day_speech_slot_failed",
            )
        )
        assert lifecycle is not None
        assert lifecycle.payload["audience"] == "god_view"
        assert "raw_response" not in lifecycle.payload


def test_new_fence_invalidates_stale_slot_without_mutating_from_old_owner(
    harness: _Harness,
) -> None:
    slot = harness.reserve()
    now = datetime.now(tz=UTC)
    with harness.session_factory.begin() as db:
        run = db.get(GameRun, RUN_ID)
        assert run is not None
        run.worker_id = "v2_worker_day_speech_recovery"
        run.worker_heartbeat_at = now
        run.lease_expires_at = now + timedelta(minutes=5)
        run.fence_token = 2
    with pytest.raises(ExecutionOwnershipLost, match="v2_run_execution_lease_lost"):
        harness.slots.mark_generating(slot_id=slot.slot_id, fence=harness.fence)

    recovery_fence = RunFence(
        run_id=RUN_ID,
        worker_id="v2_worker_day_speech_recovery",
        fence_token=2,
    )
    invalidated = harness.slots.invalidate_slot(
        slot_id=slot.slot_id,
        reason_code="worker_fence_replaced",
        fence=recovery_fence,
    )
    assert invalidated.state == "invalidated"
    assert invalidated.failure == {
        "kind": "invalidated",
        "reason_code": "worker_fence_replaced",
        "invalidated_by_run_id": RUN_ID,
        "invalidated_by_worker_id": "v2_worker_day_speech_recovery",
        "invalidated_by_fence_token": 2,
    }


def _speech_context(
    *,
    action_id: str,
    actor_player_id: str,
    pipeline: dict[str, Any] | None = None,
    public_cutoff_record_seq: int | None = None,
    projection_at_seq: int | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "action_id": action_id,
        "action_type": "day_debate_speech",
        "game_id": GAME_ID,
        "phase_id": PHASE_ID,
        "actor": {"kind": "player", "id": actor_player_id},
        "objective": "发表本轮白天讨论发言。",
        "output_contract": {"kind": "speech"},
        "speech_round": 1,
        "speech_order": (
            ["player_1", "player_2", "player_3"]
            if actor_player_id == "player_3"
            else ["player_1", "player_2"]
        ),
        **({"pipeline": pipeline} if pipeline is not None else {}),
        **(
            {"public_cutoff_record_seq": public_cutoff_record_seq}
            if public_cutoff_record_seq is not None
            else {}
        ),
        **({"projection_at_seq": projection_at_seq} if projection_at_seq is not None else {}),
    }


def _append_action_opened(
    harness: _Harness,
    *,
    slot: DaySpeechSlotSnapshot,
    action_id: str,
    stage: str,
    projection_at_seq: int | None = None,
) -> int:
    cutoff = slot.context_cutoff_record_seq
    context = _speech_context(
        action_id=action_id,
        actor_player_id=slot.actor_player_id,
        pipeline={
            "slot_id": slot.slot_id,
            "stage": stage,
            "model_admission_mode": "idle_only" if stage == "generation" else "normal",
        },
        public_cutoff_record_seq=(cutoff if stage == "generation" else None),
        projection_at_seq=(projection_at_seq if projection_at_seq is not None else cutoff)
        if stage == "generation"
        else None,
    )
    context["batch_id"] = f"{slot.slot_id}:generation"
    with harness.session_factory.begin() as db:
        game = db.get(GameRecord, GAME_ID)
        assert game is not None
        record_seq = game.last_record_seq + 1
        context["run_id"] = RUN_ID
        context["action_record_seq"] = record_seq
        db.add(
            GameRecordEvent(
                game_id=GAME_ID,
                event_id=record_seq,
                record_seq=record_seq,
                run_id=RUN_ID,
                event_type="action_opened",
                payload_schema_version=1,
                payload=canonical_event_payload(
                    {"action_id": action_id, "activation_id": None, "context": context},
                    audience="player_private",
                ),
            )
        )
        game.last_record_seq = record_seq
        return record_seq


def _append_generation_success(
    harness: _Harness,
    *,
    slot: DaySpeechSlotSnapshot,
    action_id: str,
    speech: str,
    projection_at_seq: int | None = None,
) -> int:
    _append_action_opened(
        harness,
        slot=slot,
        action_id=action_id,
        stage="generation",
        projection_at_seq=projection_at_seq,
    )
    response_seq = _append_record_event(
        harness.session_factory,
        event_type="model_response_received",
        audience="player_private",
        payload={
            "action_id": action_id,
            "attempt_id": "v2_model_day_prefetch",
            "application_validation_result": "accepted",
            "parsed_output": {
                "target_player_ref": None,
                "target_player_id": None,
                "speech": speech,
                "decision_note": None,
            },
            "raw_response": '{"speech":"private model output"}',
        },
    )
    _append_record_event(
        harness.session_factory,
        event_type="action_succeeded",
        audience="all",
        payload={
            "action_id": action_id,
            "result": "decision_recorded_without_presentation",
            "phase_id": PHASE_ID,
        },
    )
    return response_seq


def _append_record_event(
    factory: sessionmaker[Session],
    *,
    event_type: str,
    audience: str,
    payload: dict[str, Any],
) -> int:
    with factory.begin() as db:
        game = db.get(GameRecord, GAME_ID)
        assert game is not None
        record_seq = game.last_record_seq + 1
        db.add(
            GameRecordEvent(
                game_id=GAME_ID,
                event_id=record_seq,
                record_seq=record_seq,
                run_id=RUN_ID,
                event_type=event_type,
                payload_schema_version=1,
                payload=canonical_event_payload(payload, audience=audience),
            )
        )
        game.last_record_seq = record_seq
        return record_seq


def _complete_voice_action(
    harness: _Harness,
    identity: PresentationIdentity,
) -> None:
    harness.actions.mark_voice_ready(
        identity=identity,
        tts_attempt_id=f"v2_tts_{identity.presentation_seq}",
        sample_count=24_000,
        duration_ms=1_000,
        pcm_sha256="a" * 64,
        size_bytes=48_000,
    )
    harness.actions.complete_action(
        identity=identity,
        tts_attempt_id=f"v2_tts_{identity.presentation_seq}",
        final_chunk_index=0,
        final_sample_cursor=24_000,
        next_live_state="ready",
        next_phase_state=PHASE_STATE,
    )
