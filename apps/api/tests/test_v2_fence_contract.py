from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.match.execution import RunFence, bind_run_fence
from app.match.match_repository import DayVoteCommit, MatchRepository
from app.match.models import (
    AbilityActivation,
    AbilityInstance,
    ActionWindow,
    EffectIntent,
    GameRecord,
    GameRecordEvent,
    GameRun,
    KnowledgeFact,
    LivePresentation,
    MatchState,
    ModelActionRecovery,
    PlayerState,
    VoiceAsset,
)
from app.match.night_repository import NightRepository, NightRuntimeState
from app.match.repository import (
    ActionClaim,
    ActionRepository,
    ExecutionOwnershipLost,
    PresentationIdentity,
    RepositoryError,
)
from app.match.service import create_waiting_game


@dataclass(frozen=True)
class _FenceHarness:
    session_factory: sessionmaker[Session]
    game_id: str
    run_id: str
    stale_fence: RunFence
    actions: ActionRepository
    nights: NightRepository
    matches: MatchRepository

    def rotate_owner(self) -> None:
        now = datetime.now(tz=UTC)
        with self.session_factory.begin() as db:
            run = db.get(GameRun, self.run_id)
            assert run is not None
            run.worker_id = "v2_worker_replacement"
            run.worker_heartbeat_at = now
            run.lease_expires_at = now + timedelta(minutes=5)
            run.fence_token += 1


@pytest.fixture
def fence_harness() -> Iterator[_FenceHarness]:
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    with factory() as db:
        game, run, _token = create_waiting_game(
            db,
            title="stale fence mutation contract",
            delivery_snapshot={"schema_version": 1, "mode": "tts"},
        )
        game_id = game.game_id
        run_id = run.run_id
    with factory.begin() as db:
        game = db.get(GameRecord, game_id)
        assert game is not None
        game.players_snapshot = [
            {
                "seat": 1,
                "profile_id": "fence-player",
                "name": "围栏测试玩家",
                "model_provider": "agent_plan",
                "model": "fence-model",
                "model_supports_thinking": False,
                "model_parameters": {
                    "thinking": "disabled",
                    "reasoning_effort": None,
                    "max_tokens_mode": "auto",
                    "max_tokens": 512,
                },
            }
        ]

    actions = ActionRepository(factory, enforce_execution_fence=True)
    execution = actions.start_and_claim_execution(
        game_id=game_id,
        audience="player_public",
        worker_id="v2_worker_original",
        lease_seconds=300,
    )
    assert execution.fence is not None
    harness = _FenceHarness(
        session_factory=factory,
        game_id=game_id,
        run_id=run_id,
        stale_fence=execution.fence,
        actions=actions,
        nights=NightRepository(factory, enforce_execution_fence=True),
        matches=MatchRepository(factory, enforce_execution_fence=True),
    )
    try:
        yield harness
    finally:
        engine.dispose()


def test_stale_fence_rejects_action_claim_without_opening_action(
    fence_harness: _FenceHarness,
) -> None:
    harness = fence_harness
    before_seq = _last_record_seq(harness)
    harness.rotate_owner()

    with bind_run_fence(harness.stale_fence):
        with pytest.raises(
            ExecutionOwnershipLost,
            match="v2_run_execution_lease_lost",
        ):
            harness.actions.claim_action(
                game_id=harness.game_id,
                action_id="v2_action_stale_claim",
                context={"action_type": "fence_contract_action"},
                expected_phase_id="opening",
                expected_phase_state="opening_ready",
                audience="all",
                context_audience="all",
            )

    with harness.session_factory() as db:
        game = db.get(GameRecord, harness.game_id)
        run = db.get(GameRun, harness.run_id)
        assert game is not None and run is not None
        assert game.status == run.status == "ready"
        assert game.last_record_seq == before_seq
        assert not _events_for_action(db, harness.game_id, "v2_action_stale_claim")


@pytest.mark.parametrize(
    ("clear_owner", "expected_status"),
    [(False, "already_owned"), (True, "not_startable")],
)
def test_active_run_cannot_be_reclaimed_through_start_after_lease_stales(
    fence_harness: _FenceHarness,
    clear_owner: bool,
    expected_status: str,
) -> None:
    harness = fence_harness
    expired_at = datetime.now(tz=UTC) - timedelta(seconds=1)
    with harness.session_factory.begin() as db:
        run = db.get(GameRun, harness.run_id)
        assert run is not None
        run.lease_expires_at = None if clear_owner else expired_at
        if clear_owner:
            run.worker_id = None
            run.worker_heartbeat_at = None
    before_seq = _last_record_seq(harness)

    result = harness.actions.start_and_claim_execution(
        game_id=harness.game_id,
        audience="player_public",
        worker_id="v2_worker_replacement",
        lease_seconds=300,
    )

    assert result.status == expected_status
    assert result.fence is None
    assert result.current_state == "ready"
    assert result.owner_hint == (None if clear_owner else "v2_worker_original")
    with harness.session_factory() as db:
        game = db.get(GameRecord, harness.game_id)
        run = db.get(GameRun, harness.run_id)
        claim_events = list(
            db.scalars(
                select(GameRecordEvent).where(
                    GameRecordEvent.game_id == harness.game_id,
                    GameRecordEvent.event_type == "v2_run_execution_claimed",
                )
            )
        )
    assert game is not None and game.status == "ready"
    assert run is not None and run.status == "ready"
    assert run.worker_id == (None if clear_owner else "v2_worker_original")
    if clear_owner:
        assert run.lease_expires_at is None
    else:
        assert run.lease_expires_at is not None
        assert run.lease_expires_at.replace(tzinfo=UTC) == expired_at
    assert game.last_record_seq == before_seq
    assert len(claim_events) == 1


def test_stale_fence_rejects_presentation_creation_without_rows(
    fence_harness: _FenceHarness,
) -> None:
    harness = fence_harness
    claim = _claim_action(harness, action_id="v2_action_stale_presentation")
    before_seq = _last_record_seq(harness)
    harness.rotate_owner()

    with pytest.raises(
        ExecutionOwnershipLost,
        match="v2_run_execution_lease_lost",
    ):
        harness.actions.open_presentation(
            claim=claim,
            presentation_id="v2_pres_stale_create",
            speech_id="v2_speech_stale_create",
            voice_asset_id="v2_voice_stale_create",
            subtitle_text="过期 owner 不得创建展示。",
            sample_rate=24000,
        )

    with harness.session_factory() as db:
        game = db.get(GameRecord, harness.game_id)
        run = db.get(GameRun, harness.run_id)
        assert game is not None and run is not None
        assert game.status == run.status == "generating"
        assert game.last_record_seq == before_seq
        assert db.get(VoiceAsset, "v2_voice_stale_create") is None
        assert (
            db.scalar(
                select(func.count())
                .select_from(LivePresentation)
                .where(LivePresentation.game_id == harness.game_id)
            )
            == 0
        )


def test_stale_fence_rejects_tts_finalization_and_voice_ready_mutations(
    fence_harness: _FenceHarness,
) -> None:
    harness = fence_harness
    claim = _claim_action(harness, action_id="v2_action_stale_tts")
    identity = _open_voice_presentation(harness, claim)
    before_seq = _last_record_seq(harness)
    harness.rotate_owner()

    with pytest.raises(
        ExecutionOwnershipLost,
        match="v2_run_execution_lease_lost",
    ):
        harness.actions.mark_finalizing(
            identity=identity,
            tts_attempt_id="v2_tts_stale",
            sample_count=480,
        )
    with pytest.raises(
        ExecutionOwnershipLost,
        match="v2_run_execution_lease_lost",
    ):
        harness.actions.mark_voice_ready(
            identity=identity,
            tts_attempt_id="v2_tts_stale",
            sample_count=480,
            duration_ms=20,
            pcm_sha256="a" * 64,
            size_bytes=960,
        )

    with harness.session_factory() as db:
        game = db.get(GameRecord, harness.game_id)
        run = db.get(GameRun, harness.run_id)
        presentation = db.get(
            LivePresentation,
            (harness.game_id, identity.presentation_seq),
        )
        voice = db.get(VoiceAsset, identity.voice_asset_id)
        assert game is not None and run is not None
        assert presentation is not None and voice is not None
        assert game.status == run.status == "generating"
        assert game.last_record_seq == before_seq
        assert presentation.state == "queued"
        assert presentation.audio_asset_id is None
        assert presentation.audio_duration_ms is None
        assert voice.state == "writing"
        assert voice.sample_count is None
        assert voice.completed_at is None


def test_stale_fence_rejects_model_recovery_creation(
    fence_harness: _FenceHarness,
) -> None:
    harness = fence_harness
    claim = _claim_action(harness, action_id="v2_action_stale_recovery")
    before_seq = _last_record_seq(harness)
    harness.rotate_owner()

    with pytest.raises(
        ExecutionOwnershipLost,
        match="v2_run_execution_lease_lost",
    ):
        harness.actions.pause_model_action(
            claim=claim,
            attempt_id="v2_model_stale_recovery",
            failure_code="model_transport_failed",
            recovery=_recovery_payload(),
        )

    with harness.session_factory() as db:
        game = db.get(GameRecord, harness.game_id)
        run = db.get(GameRun, harness.run_id)
        assert game is not None and run is not None
        assert game.status == run.status == "generating"
        assert game.last_record_seq == before_seq
        assert db.get(ModelActionRecovery, claim.action_id) is None


def test_stale_fence_rolls_back_precheck_model_recovery_resolution(
    fence_harness: _FenceHarness,
) -> None:
    harness = fence_harness
    claim = _claim_action(harness, action_id="v2_action_stale_resolve_recovery")
    harness.actions.pause_model_action(
        claim=claim,
        attempt_id="v2_model_initial_failure",
        failure_code="model_transport_failed",
        recovery=_recovery_payload(),
    )
    before_seq = _last_record_seq(harness)
    harness.rotate_owner()

    with pytest.raises(
        ExecutionOwnershipLost,
        match="v2_run_execution_lease_lost",
    ):
        harness.actions.resolve_model_action_recovery(
            claim=claim,
            attempt_id="v2_model_stale_resolution",
            attempt_no=2,
            retry_cycle=2,
        )

    with harness.session_factory() as db:
        game = db.get(GameRecord, harness.game_id)
        run = db.get(GameRun, harness.run_id)
        recovery = db.get(ModelActionRecovery, claim.action_id)
        assert game is not None and run is not None and recovery is not None
        assert game.status == run.status == "paused_model_error"
        assert game.last_record_seq == before_seq
        assert recovery.state == "paused"
        assert recovery.attempt_no == 1
        assert recovery.retry_cycle == 1
        assert recovery.resolved_attempt_id is None
        assert recovery.resolved_at is None
        assert not any(
            event.event_type == "model_action_recovery_resolved"
            for event in _events_for_action(db, harness.game_id, claim.action_id)
        )


def test_stale_fence_rejects_night_ability_and_effect_creation(
    fence_harness: _FenceHarness,
) -> None:
    harness = fence_harness
    state = _prepare_night_state(harness)
    with bind_run_fence(harness.stale_fence):
        activation = harness.nights.open_activation(
            state=state,
            ability_id="ability_guard.protect",
            actor_player_id="seat_1",
            occurrence=1,
            audience="god_view",
        )
    before_seq = _last_record_seq(harness)
    harness.rotate_owner()

    with bind_run_fence(harness.stale_fence):
        with pytest.raises(
            ExecutionOwnershipLost,
            match="v2_run_execution_lease_lost",
        ):
            harness.nights.complete_activation(
                state=state,
                activation=activation,
                decision={
                    "target_player_id": "seat_1",
                    "decision_note": "保护自己",
                },
                result={"accepted": True},
                effect_type="protect",
                target_player_id="seat_1",
                ability_state_patch={"last_target_player_id": "seat_1"},
            )

    with harness.session_factory() as db:
        game = db.get(GameRecord, harness.game_id)
        row = db.get(AbilityActivation, activation.activation_id)
        instance = db.get(AbilityInstance, activation.ability_instance_id)
        assert game is not None and row is not None and instance is not None
        assert game.last_record_seq == before_seq
        assert row.status == "open"
        assert row.decision == {}
        assert row.result == {}
        assert row.closed_at is None
        assert instance.state == {}
        assert _row_count(db, EffectIntent, harness.game_id) == 0
        assert _row_count(db, KnowledgeFact, harness.game_id) == 0


def test_stale_fence_rejects_skip_without_leaving_open_activation(
    fence_harness: _FenceHarness,
) -> None:
    harness = fence_harness
    state = _prepare_night_state(harness)
    before_seq = _last_record_seq(harness)
    harness.rotate_owner()

    with bind_run_fence(harness.stale_fence):
        with pytest.raises(
            ExecutionOwnershipLost,
            match="v2_run_execution_lease_lost",
        ):
            harness.nights.skip_activation(
                state=state,
                ability_id="ability_guard.protect",
                reason="no_eligible_actor_or_target",
                audience="god_view",
            )

    with harness.session_factory() as db:
        game = db.get(GameRecord, harness.game_id)
        assert game is not None
        assert game.last_record_seq == before_seq
        assert _row_count(db, AbilityActivation, harness.game_id) == 0
        assert not {
            "ability_activation_opened",
            "ability_activation_skipped",
        }.intersection(_event_types(db, harness.game_id))


def test_skip_activation_rolls_back_open_when_ownership_is_lost_mid_operation(
    fence_harness: _FenceHarness,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = fence_harness
    state = _prepare_night_state(harness)
    before_seq = _last_record_seq(harness)
    original = NightRepository._open_activation_locked

    def open_then_lose_ownership(repository: NightRepository, **values: object):
        original(repository, **values)
        raise ExecutionOwnershipLost("v2_run_execution_lease_lost")

    monkeypatch.setattr(
        NightRepository,
        "_open_activation_locked",
        open_then_lose_ownership,
    )

    with bind_run_fence(harness.stale_fence):
        with pytest.raises(
            ExecutionOwnershipLost,
            match="v2_run_execution_lease_lost",
        ):
            harness.nights.skip_activation(
                state=state,
                ability_id="ability_guard.protect",
                reason="no_eligible_actor_or_target",
                audience="god_view",
            )

    with harness.session_factory() as db:
        game = db.get(GameRecord, harness.game_id)
        assert game is not None
        assert game.last_record_seq == before_seq
        assert _row_count(db, AbilityActivation, harness.game_id) == 0
        assert not {
            "ability_activation_opened",
            "ability_activation_skipped",
        }.intersection(_event_types(db, harness.game_id))


def test_stale_fence_rejects_pending_night_effect_resolution(
    fence_harness: _FenceHarness,
) -> None:
    harness = fence_harness
    state = _prepare_night_state(harness)
    with bind_run_fence(harness.stale_fence):
        activation = harness.nights.open_activation(
            state=state,
            ability_id="ability_guard.protect",
            actor_player_id="seat_1",
            occurrence=1,
            audience="god_view",
        )
        harness.nights.complete_activation(
            state=state,
            activation=activation,
            decision={"target_player_id": "seat_1"},
            result={"accepted": True},
            effect_type="attack",
            target_player_id="seat_1",
        )
    before_seq = _last_record_seq(harness)
    harness.rotate_owner()

    with bind_run_fence(harness.stale_fence):
        with pytest.raises(
            ExecutionOwnershipLost,
            match="v2_run_execution_lease_lost",
        ):
            harness.nights.resolve_night(
                state=state,
                attack_target="seat_1",
                protected_target=None,
                healed_target=None,
                poisoned_target=None,
            )

    with harness.session_factory() as db:
        game = db.get(GameRecord, harness.game_id)
        window = db.get(ActionWindow, state.window_id)
        player = db.get(PlayerState, (harness.game_id, "seat_1"))
        effect = db.scalar(select(EffectIntent).where(EffectIntent.game_id == harness.game_id))
        assert game is not None and window is not None and player is not None
        assert effect is not None
        assert game.last_record_seq == before_seq
        assert game.phase_state == "night_running"
        assert window.state == "open"
        assert player.alive is True
        assert player.death_cause is None
        assert effect.state == "pending"
        assert effect.resolved_at is None
        assert "outcome" not in effect.payload


def test_hunter_shot_atomically_resolves_its_effect_intent(
    fence_harness: _FenceHarness,
) -> None:
    harness = fence_harness
    state = _prepare_night_state(harness)
    _add_alive_players(harness, "seat_2")
    _add_hunter_ability(harness, state)
    with bind_run_fence(harness.stale_fence):
        activation = harness.nights.open_activation(
            state=state,
            ability_id="hunter.death_shot",
            actor_player_id="seat_1",
            occurrence=1,
            audience="god_view",
        )
        harness.nights.complete_activation(
            state=state,
            activation=activation,
            decision={"target_player_id": "seat_2"},
            result={"shot_used": True},
            effect_type="shoot",
            target_player_id="seat_2",
        )
        harness.nights.apply_hunter_shot(
            state=state,
            activation_id=activation.activation_id,
            hunter_player_id="seat_1",
            target_player_id="seat_2",
        )

    with harness.session_factory() as db:
        target = db.get(PlayerState, (harness.game_id, "seat_2"))
        effect = db.scalar(
            select(EffectIntent).where(EffectIntent.activation_id == activation.activation_id)
        )
        resolved = db.scalar(
            select(GameRecordEvent).where(
                GameRecordEvent.game_id == harness.game_id,
                GameRecordEvent.event_type == "effect_intent_resolved",
            )
        )
        assert target is not None and effect is not None and resolved is not None
        assert target.alive is False
        assert target.death_cause == "hunter_shot"
        assert effect.state == "resolved"
        assert effect.resolved_at is not None
        assert effect.payload["outcome"] == "killed"
        assert resolved.payload["activation_id"] == activation.activation_id
        assert resolved.payload["effect_intent_id"] == effect.effect_intent_id
        assert resolved.payload["outcome"] == "killed"


def test_hunter_shot_replay_is_idempotent_without_duplicate_resolution_events(
    fence_harness: _FenceHarness,
) -> None:
    harness = fence_harness
    state = _prepare_night_state(harness)
    _add_alive_players(harness, "seat_2")
    _add_hunter_ability(harness, state)
    with bind_run_fence(harness.stale_fence):
        activation = harness.nights.open_activation(
            state=state,
            ability_id="hunter.death_shot",
            actor_player_id="seat_1",
            occurrence=1,
            audience="god_view",
        )
        harness.nights.complete_activation(
            state=state,
            activation=activation,
            decision={"target_player_id": "seat_2"},
            result={"shot_used": True},
            effect_type="shoot",
            target_player_id="seat_2",
        )
        harness.nights.apply_hunter_shot(
            state=state,
            activation_id=activation.activation_id,
            hunter_player_id="seat_1",
            target_player_id="seat_2",
        )
        before_replay_seq = _last_record_seq(harness)
        harness.nights.apply_hunter_shot(
            state=state,
            activation_id=activation.activation_id,
            hunter_player_id="seat_1",
            target_player_id="seat_2",
        )

    with harness.session_factory() as db:
        game = db.get(GameRecord, harness.game_id)
        hunter = db.get(PlayerState, (harness.game_id, "seat_1"))
        target = db.get(PlayerState, (harness.game_id, "seat_2"))
        effect = db.scalar(
            select(EffectIntent).where(EffectIntent.activation_id == activation.activation_id)
        )
        assert game is not None and hunter is not None and target is not None
        assert effect is not None
        assert game.last_record_seq == before_replay_seq
        assert target.alive is False
        assert target.death_cause == "hunter_shot"
        assert hunter.state["hunter_response_resolved"] is True
        assert effect.state == "resolved"
        assert effect.payload["outcome"] == "killed"
        assert _event_count(db, harness.game_id, "effect_intent_resolved") == 1
        assert _event_count(db, harness.game_id, "hunter_response_resolved") == 1


@pytest.mark.parametrize(
    ("hunter_player_id", "target_player_id"),
    [("seat_9", "seat_2"), ("seat_1", "seat_3")],
)
def test_resolved_hunter_shot_rejects_mismatched_replay_without_mutation(
    fence_harness: _FenceHarness,
    hunter_player_id: str,
    target_player_id: str,
) -> None:
    harness = fence_harness
    state = _prepare_night_state(harness)
    _add_alive_players(harness, "seat_2", "seat_3")
    _add_hunter_ability(harness, state)
    with bind_run_fence(harness.stale_fence):
        activation = harness.nights.open_activation(
            state=state,
            ability_id="hunter.death_shot",
            actor_player_id="seat_1",
            occurrence=1,
            audience="god_view",
        )
        harness.nights.complete_activation(
            state=state,
            activation=activation,
            decision={"target_player_id": "seat_2"},
            result={"shot_used": True},
            effect_type="shoot",
            target_player_id="seat_2",
        )
        harness.nights.apply_hunter_shot(
            state=state,
            activation_id=activation.activation_id,
            hunter_player_id="seat_1",
            target_player_id="seat_2",
        )

    with harness.session_factory() as db:
        game = db.get(GameRecord, harness.game_id)
        effect = db.scalar(
            select(EffectIntent).where(EffectIntent.activation_id == activation.activation_id)
        )
        assert game is not None and effect is not None and effect.resolved_at is not None
        before_seq = game.last_record_seq
        before_resolved_at = effect.resolved_at
        before_payload = dict(effect.payload)
        before_effect_events = _event_count(db, harness.game_id, "effect_intent_resolved")
        before_hunter_events = _event_count(db, harness.game_id, "hunter_response_resolved")

    with bind_run_fence(harness.stale_fence):
        with pytest.raises(
            RepositoryError,
            match="hunter shoot intent does not match resolution",
        ):
            harness.nights.apply_hunter_shot(
                state=state,
                activation_id=activation.activation_id,
                hunter_player_id=hunter_player_id,
                target_player_id=target_player_id,
            )

    with harness.session_factory() as db:
        game = db.get(GameRecord, harness.game_id)
        hunter = db.get(PlayerState, (harness.game_id, "seat_1"))
        shot_target = db.get(PlayerState, (harness.game_id, "seat_2"))
        other_target = db.get(PlayerState, (harness.game_id, "seat_3"))
        effect = db.scalar(
            select(EffectIntent).where(EffectIntent.activation_id == activation.activation_id)
        )
        assert game is not None and hunter is not None
        assert shot_target is not None and other_target is not None and effect is not None
        assert game.last_record_seq == before_seq
        assert hunter.state["hunter_response_resolved"] is True
        assert shot_target.alive is False
        assert shot_target.death_cause == "hunter_shot"
        assert other_target.alive is True
        assert other_target.death_cause is None
        assert effect.state == "resolved"
        assert effect.resolved_at == before_resolved_at
        assert effect.payload == before_payload
        assert _event_count(db, harness.game_id, "effect_intent_resolved") == before_effect_events
        assert _event_count(db, harness.game_id, "hunter_response_resolved") == before_hunter_events


def test_hunter_shot_rejects_mismatched_activation_without_resolving_any_intent(
    fence_harness: _FenceHarness,
) -> None:
    harness = fence_harness
    state = _prepare_night_state(harness)
    _add_alive_players(harness, "seat_2", "seat_3")
    _add_hunter_ability(harness, state)
    with bind_run_fence(harness.stale_fence):
        first = harness.nights.open_activation(
            state=state,
            ability_id="hunter.death_shot",
            actor_player_id="seat_1",
            occurrence=1,
            audience="god_view",
        )
        harness.nights.complete_activation(
            state=state,
            activation=first,
            decision={"target_player_id": "seat_2"},
            result={"shot_used": True},
            effect_type="shoot",
            target_player_id="seat_2",
        )
        second = harness.nights.open_activation(
            state=state,
            ability_id="hunter.death_shot",
            actor_player_id="seat_1",
            occurrence=2,
            audience="god_view",
        )
        harness.nights.complete_activation(
            state=state,
            activation=second,
            decision={"target_player_id": "seat_3"},
            result={"shot_used": True},
            effect_type="shoot",
            target_player_id="seat_3",
        )
        with pytest.raises(
            RepositoryError,
            match="hunter shoot intent does not match resolution",
        ):
            harness.nights.apply_hunter_shot(
                state=state,
                activation_id=second.activation_id,
                hunter_player_id="seat_1",
                target_player_id="seat_2",
            )

    with harness.session_factory() as db:
        effects = list(
            db.scalars(
                select(EffectIntent)
                .where(EffectIntent.game_id == harness.game_id)
                .order_by(EffectIntent.activation_id)
            )
        )
        targets = [
            db.get(PlayerState, (harness.game_id, player_id))
            for player_id in ("seat_2", "seat_3")
        ]
        assert len(effects) == 2
        assert all(item.state == "pending" and item.resolved_at is None for item in effects)
        assert all(item is not None and item.alive for item in targets)
        assert "effect_intent_resolved" not in _event_types(db, harness.game_id)


def test_stale_fence_rejects_match_state_mutation(
    fence_harness: _FenceHarness,
) -> None:
    harness = fence_harness
    with harness.session_factory.begin() as db:
        game = db.get(GameRecord, harness.game_id)
        assert game is not None
        game.phase_id = "day_1"
        game.phase_state = "day_debate"
        db.add(
            MatchState(
                game_id=harness.game_id,
                round_no=1,
                sheriff_badge_state="pending",
            )
        )
        db.add(
            PlayerState(
                game_id=harness.game_id,
                player_id="seat_1",
                seat=1,
                alive=True,
                state={},
            )
        )
    before_seq = _last_record_seq(harness)
    harness.rotate_owner()

    with bind_run_fence(harness.stale_fence):
        with pytest.raises(
            ExecutionOwnershipLost,
            match="v2_run_execution_lease_lost",
        ):
            harness.matches.set_sheriff(
                game_id=harness.game_id,
                player_id="seat_1",
                reason="elected",
            )

    with harness.session_factory() as db:
        game = db.get(GameRecord, harness.game_id)
        match = db.get(MatchState, harness.game_id)
        player = db.get(PlayerState, (harness.game_id, "seat_1"))
        assert game is not None and match is not None and player is not None
        assert game.last_record_seq == before_seq
        assert match.sheriff_player_id is None
        assert match.sheriff_badge_state == "pending"
        assert player.alive is True


def test_stale_fence_rejects_atomic_day_vote_batch(
    fence_harness: _FenceHarness,
) -> None:
    harness = fence_harness
    with harness.session_factory.begin() as db:
        game = db.get(GameRecord, harness.game_id)
        assert game is not None
        game.phase_id = "day_1"
        game.phase_state = "day_vote"
        db.add(
            MatchState(
                game_id=harness.game_id,
                round_no=1,
                sheriff_badge_state="pending",
            )
        )
        for seat in (1, 2):
            db.add(
                PlayerState(
                    game_id=harness.game_id,
                    player_id=f"seat_{seat}",
                    seat=seat,
                    alive=True,
                    state={},
                )
            )
    before_seq = _last_record_seq(harness)
    batch_id = f"day_1:exile_vote:{before_seq}:vote"
    harness.rotate_owner()

    with bind_run_fence(harness.stale_fence):
        with pytest.raises(
            ExecutionOwnershipLost,
            match="v2_run_execution_lease_lost",
        ):
            harness.matches.finalize_day_vote_batch(
                game_id=harness.game_id,
                phase_id="day_1",
                phase_state="day_vote",
                round_no=1,
                action_type="exile_vote",
                batch_id=batch_id,
                public_cutoff_record_seq=before_seq,
                expected_voter_ids=("seat_1", "seat_2"),
                votes=(
                    DayVoteCommit("seat_1", "seat_2", 1.0, "投2号。"),
                    DayVoteCommit("seat_2", "seat_1", 1.0, "投1号。"),
                ),
                decision_context={
                    "vote_round": 1,
                    "batch_id": batch_id,
                    "public_cutoff_record_seq": before_seq,
                },
                resolution_payload={
                    "round_no": 1,
                    "action_type": "exile_vote",
                    "batch_id": batch_id,
                    "public_cutoff_record_seq": before_seq,
                    "eligible_voter_ids": ["seat_1", "seat_2"],
                    "ineligible_voter_ids": [],
                    "candidate_player_ids": ["seat_1", "seat_2"],
                    "weighted": False,
                    "sheriff_player_id": None,
                    "sheriff_vote_weight": None,
                    "voter_weights": {"seat_1": 1.0, "seat_2": 1.0},
                    "totals": {"seat_2": 1.0, "seat_1": 1.0},
                    "leaders": ["seat_1", "seat_2"],
                    "identity_reveal": "none",
                },
            )

    with harness.session_factory() as db:
        game = db.get(GameRecord, harness.game_id)
        assert game is not None
        assert game.last_record_seq == before_seq
        assert "day_vote_committed" not in _event_types(db, harness.game_id)
        assert "day_vote_resolved" not in _event_types(db, harness.game_id)
        assert (
            db.scalar(
                select(func.count())
                .select_from(KnowledgeFact)
                .where(
                    KnowledgeFact.game_id == harness.game_id,
                    KnowledgeFact.fact_type == "private_action_decision",
                )
            )
            == 0
        )


def _claim_action(harness: _FenceHarness, *, action_id: str) -> ActionClaim:
    with bind_run_fence(harness.stale_fence):
        claim = harness.actions.claim_action(
            game_id=harness.game_id,
            action_id=action_id,
            context={"action_type": "fence_contract_action"},
            expected_phase_id="opening",
            expected_phase_state="opening_ready",
            audience="all",
            context_audience="all",
        )
    assert claim is not None
    return claim


def _open_voice_presentation(
    harness: _FenceHarness,
    claim: ActionClaim,
) -> PresentationIdentity:
    return harness.actions.open_presentation(
        claim=claim,
        presentation_id="v2_pres_stale_tts",
        speech_id="v2_speech_stale_tts",
        voice_asset_id="v2_voice_stale_tts",
        subtitle_text="这是有效 owner 建立的语音展示。",
        sample_rate=24000,
    )


def _prepare_night_state(harness: _FenceHarness) -> NightRuntimeState:
    window_id = "v2_window_fence_contract"
    instance_id = "v2_instance_fence_contract"
    snapshot = {
        "instances": [
            {
                "ability_instance_id": instance_id,
                "ability_id": "ability_guard.protect",
            }
        ]
    }
    with harness.session_factory.begin() as db:
        game = db.get(GameRecord, harness.game_id)
        run = db.get(GameRun, harness.run_id)
        assert game is not None and run is not None
        game.status = "ready"
        game.phase_id = "first_night"
        game.phase_state = "night_running"
        run.status = "ready"
        db.add(
            MatchState(
                game_id=harness.game_id,
                round_no=1,
                sheriff_badge_state="disabled",
            )
        )
        db.add(
            PlayerState(
                game_id=harness.game_id,
                player_id="seat_1",
                seat=1,
                alive=True,
                state={},
            )
        )
        db.add(
            ActionWindow(
                window_id=window_id,
                game_id=harness.game_id,
                run_id=harness.run_id,
                window_seq=1,
                window_type="night",
                state="open",
                ability_snapshot_hash="c" * 64,
                plan=[],
                result={},
            )
        )
        db.add(
            AbilityInstance(
                ability_instance_id=instance_id,
                game_id=harness.game_id,
                ability_id="ability_guard.protect",
                ability_version=1,
                owner_scope="player",
                owner_id="seat_1",
                owner_role_key="guard",
                state={},
            )
        )
    return NightRuntimeState(
        game_id=harness.game_id,
        run_id=harness.run_id,
        window_id=window_id,
        window_seq=1,
        phase_id="first_night",
        round_no=1,
        snapshot=snapshot,
        rule={},
        max_rounds=8,
        sheriff_player_id=None,
        sheriff_badge_state="disabled",
        players=(),
    )


def _add_alive_players(harness: _FenceHarness, *player_ids: str) -> None:
    with harness.session_factory.begin() as db:
        for offset, player_id in enumerate(player_ids, start=2):
            db.add(
                PlayerState(
                    game_id=harness.game_id,
                    player_id=player_id,
                    seat=offset,
                    alive=True,
                    state={},
                )
            )


def _add_hunter_ability(
    harness: _FenceHarness,
    state: NightRuntimeState,
) -> None:
    instance = {
        "ability_instance_id": "v2_instance_hunter_death_shot",
        "ability_id": "hunter.death_shot",
    }
    state.snapshot["instances"].append(instance)
    with harness.session_factory.begin() as db:
        db.add(
            AbilityInstance(
                ability_instance_id=instance["ability_instance_id"],
                game_id=harness.game_id,
                ability_id=instance["ability_id"],
                ability_version=1,
                owner_scope="player",
                owner_id="seat_1",
                owner_role_key="hunter",
                state={},
            )
        )


def _recovery_payload() -> dict[str, object]:
    return {
        "action_type": "fence_contract_action",
        "actor_id": "seat_1",
        "model_provider": "agent_plan",
        "model_id": "test-model",
        "request_payload": {},
        "request_hash": "b" * 64,
        "model_context": {},
        "action_snapshot": {"audience": "all"},
        "failure_category": "transport",
        "attempt_no": 1,
        "retry_cycle": 1,
    }


def _last_record_seq(harness: _FenceHarness) -> int:
    with harness.session_factory() as db:
        game = db.get(GameRecord, harness.game_id)
        assert game is not None
        return game.last_record_seq


def _events_for_action(db: Session, game_id: str, action_id: str) -> list[GameRecordEvent]:
    return [
        event
        for event in db.scalars(
            select(GameRecordEvent).where(GameRecordEvent.game_id == game_id)
        )
        if (event.payload or {}).get("action_id") == action_id
    ]


def _event_types(db: Session, game_id: str) -> set[str]:
    return set(
        db.scalars(select(GameRecordEvent.event_type).where(GameRecordEvent.game_id == game_id))
    )


def _event_count(db: Session, game_id: str, event_type: str) -> int:
    return int(
        db.scalar(
            select(func.count())
            .select_from(GameRecordEvent)
            .where(
                GameRecordEvent.game_id == game_id,
                GameRecordEvent.event_type == event_type,
            )
        )
        or 0
    )


def _row_count(db: Session, model: type[object], game_id: str) -> int:
    return int(
        db.scalar(select(func.count()).select_from(model).where(model.game_id == game_id)) or 0
    )
