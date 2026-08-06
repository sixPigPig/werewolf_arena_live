from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.v2.execution import V2RunFence, bind_v2_run_fence
from app.v2.match_repository import V2MatchRepository
from app.v2.models import (
    V2AbilityActivation,
    V2AbilityInstance,
    V2ActionWindow,
    V2EffectIntent,
    V2GameRecord,
    V2GameRecordEvent,
    V2GameRun,
    V2KnowledgeFact,
    V2LivePresentation,
    V2MatchState,
    V2ModelActionRecovery,
    V2PlayerState,
    V2VoiceAsset,
)
from app.v2.night_repository import V2NightRepository, V2NightRuntimeState
from app.v2.repository import (
    V2ActionClaim,
    V2ActionRepository,
    V2ExecutionOwnershipLost,
    V2PresentationIdentity,
)
from app.v2.service import create_waiting_game


@dataclass(frozen=True)
class _FenceHarness:
    session_factory: sessionmaker[Session]
    game_id: str
    run_id: str
    stale_fence: V2RunFence
    actions: V2ActionRepository
    nights: V2NightRepository
    matches: V2MatchRepository

    def rotate_owner(self) -> None:
        now = datetime.now(tz=UTC)
        with self.session_factory.begin() as db:
            run = db.get(V2GameRun, self.run_id)
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

    actions = V2ActionRepository(factory, enforce_execution_fence=True)
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
        nights=V2NightRepository(factory, enforce_execution_fence=True),
        matches=V2MatchRepository(factory, enforce_execution_fence=True),
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

    with bind_v2_run_fence(harness.stale_fence):
        with pytest.raises(
            V2ExecutionOwnershipLost,
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
        game = db.get(V2GameRecord, harness.game_id)
        run = db.get(V2GameRun, harness.run_id)
        assert game is not None and run is not None
        assert game.status == run.status == "ready"
        assert game.last_record_seq == before_seq
        assert not _events_for_action(db, harness.game_id, "v2_action_stale_claim")


def test_stale_fence_rejects_presentation_creation_without_rows(
    fence_harness: _FenceHarness,
) -> None:
    harness = fence_harness
    claim = _claim_action(harness, action_id="v2_action_stale_presentation")
    before_seq = _last_record_seq(harness)
    harness.rotate_owner()

    with pytest.raises(
        V2ExecutionOwnershipLost,
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
        game = db.get(V2GameRecord, harness.game_id)
        run = db.get(V2GameRun, harness.run_id)
        assert game is not None and run is not None
        assert game.status == run.status == "generating"
        assert game.last_record_seq == before_seq
        assert db.get(V2VoiceAsset, "v2_voice_stale_create") is None
        assert (
            db.scalar(
                select(func.count())
                .select_from(V2LivePresentation)
                .where(V2LivePresentation.game_id == harness.game_id)
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
        V2ExecutionOwnershipLost,
        match="v2_run_execution_lease_lost",
    ):
        harness.actions.mark_finalizing(
            identity=identity,
            tts_attempt_id="v2_tts_stale",
            sample_count=480,
        )
    with pytest.raises(
        V2ExecutionOwnershipLost,
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
        game = db.get(V2GameRecord, harness.game_id)
        run = db.get(V2GameRun, harness.run_id)
        presentation = db.get(
            V2LivePresentation,
            (harness.game_id, identity.presentation_seq),
        )
        voice = db.get(V2VoiceAsset, identity.voice_asset_id)
        assert game is not None and run is not None
        assert presentation is not None and voice is not None
        assert game.status == run.status == "broadcasting"
        assert game.last_record_seq == before_seq
        assert presentation.state == "active"
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
        V2ExecutionOwnershipLost,
        match="v2_run_execution_lease_lost",
    ):
        harness.actions.pause_model_action(
            claim=claim,
            attempt_id="v2_model_stale_recovery",
            failure_code="model_transport_failed",
            recovery=_recovery_payload(),
        )

    with harness.session_factory() as db:
        game = db.get(V2GameRecord, harness.game_id)
        run = db.get(V2GameRun, harness.run_id)
        assert game is not None and run is not None
        assert game.status == run.status == "generating"
        assert game.last_record_seq == before_seq
        assert db.get(V2ModelActionRecovery, claim.action_id) is None


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
        V2ExecutionOwnershipLost,
        match="v2_run_execution_lease_lost",
    ):
        harness.actions.resolve_model_action_recovery(
            claim=claim,
            attempt_id="v2_model_stale_resolution",
            attempt_no=2,
            retry_cycle=2,
        )

    with harness.session_factory() as db:
        game = db.get(V2GameRecord, harness.game_id)
        run = db.get(V2GameRun, harness.run_id)
        recovery = db.get(V2ModelActionRecovery, claim.action_id)
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
    with bind_v2_run_fence(harness.stale_fence):
        activation = harness.nights.open_activation(
            state=state,
            ability_id="ability_guard.protect",
            actor_player_id="seat_1",
            occurrence=1,
            audience="god_view",
        )
    before_seq = _last_record_seq(harness)
    harness.rotate_owner()

    with bind_v2_run_fence(harness.stale_fence):
        with pytest.raises(
            V2ExecutionOwnershipLost,
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
        game = db.get(V2GameRecord, harness.game_id)
        row = db.get(V2AbilityActivation, activation.activation_id)
        instance = db.get(V2AbilityInstance, activation.ability_instance_id)
        assert game is not None and row is not None and instance is not None
        assert game.last_record_seq == before_seq
        assert row.status == "open"
        assert row.decision == {}
        assert row.result == {}
        assert row.closed_at is None
        assert instance.state == {}
        assert _row_count(db, V2EffectIntent, harness.game_id) == 0
        assert _row_count(db, V2KnowledgeFact, harness.game_id) == 0


def test_stale_fence_rejects_skip_without_leaving_open_activation(
    fence_harness: _FenceHarness,
) -> None:
    harness = fence_harness
    state = _prepare_night_state(harness)
    before_seq = _last_record_seq(harness)
    harness.rotate_owner()

    with bind_v2_run_fence(harness.stale_fence):
        with pytest.raises(
            V2ExecutionOwnershipLost,
            match="v2_run_execution_lease_lost",
        ):
            harness.nights.skip_activation(
                state=state,
                ability_id="ability_guard.protect",
                reason="no_eligible_actor_or_target",
                audience="god_view",
            )

    with harness.session_factory() as db:
        game = db.get(V2GameRecord, harness.game_id)
        assert game is not None
        assert game.last_record_seq == before_seq
        assert _row_count(db, V2AbilityActivation, harness.game_id) == 0
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
    original = V2NightRepository._open_activation_locked

    def open_then_lose_ownership(repository: V2NightRepository, **values: object):
        original(repository, **values)
        raise V2ExecutionOwnershipLost("v2_run_execution_lease_lost")

    monkeypatch.setattr(
        V2NightRepository,
        "_open_activation_locked",
        open_then_lose_ownership,
    )

    with bind_v2_run_fence(harness.stale_fence):
        with pytest.raises(
            V2ExecutionOwnershipLost,
            match="v2_run_execution_lease_lost",
        ):
            harness.nights.skip_activation(
                state=state,
                ability_id="ability_guard.protect",
                reason="no_eligible_actor_or_target",
                audience="god_view",
            )

    with harness.session_factory() as db:
        game = db.get(V2GameRecord, harness.game_id)
        assert game is not None
        assert game.last_record_seq == before_seq
        assert _row_count(db, V2AbilityActivation, harness.game_id) == 0
        assert not {
            "ability_activation_opened",
            "ability_activation_skipped",
        }.intersection(_event_types(db, harness.game_id))


def test_stale_fence_rejects_pending_night_effect_resolution(
    fence_harness: _FenceHarness,
) -> None:
    harness = fence_harness
    state = _prepare_night_state(harness)
    with bind_v2_run_fence(harness.stale_fence):
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

    with bind_v2_run_fence(harness.stale_fence):
        with pytest.raises(
            V2ExecutionOwnershipLost,
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
        game = db.get(V2GameRecord, harness.game_id)
        window = db.get(V2ActionWindow, state.window_id)
        player = db.get(V2PlayerState, (harness.game_id, "seat_1"))
        effect = db.scalar(
            select(V2EffectIntent).where(V2EffectIntent.game_id == harness.game_id)
        )
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


def test_stale_fence_rejects_match_state_mutation(
    fence_harness: _FenceHarness,
) -> None:
    harness = fence_harness
    with harness.session_factory.begin() as db:
        game = db.get(V2GameRecord, harness.game_id)
        assert game is not None
        game.phase_id = "day_1"
        game.phase_state = "day_debate"
        db.add(
            V2MatchState(
                game_id=harness.game_id,
                round_no=1,
                sheriff_badge_state="pending",
            )
        )
        db.add(
            V2PlayerState(
                game_id=harness.game_id,
                player_id="seat_1",
                seat=1,
                alive=True,
                state={},
            )
        )
    before_seq = _last_record_seq(harness)
    harness.rotate_owner()

    with bind_v2_run_fence(harness.stale_fence):
        with pytest.raises(
            V2ExecutionOwnershipLost,
            match="v2_run_execution_lease_lost",
        ):
            harness.matches.set_sheriff(
                game_id=harness.game_id,
                player_id="seat_1",
                reason="elected",
            )

    with harness.session_factory() as db:
        game = db.get(V2GameRecord, harness.game_id)
        match = db.get(V2MatchState, harness.game_id)
        player = db.get(V2PlayerState, (harness.game_id, "seat_1"))
        assert game is not None and match is not None and player is not None
        assert game.last_record_seq == before_seq
        assert match.sheriff_player_id is None
        assert match.sheriff_badge_state == "pending"
        assert player.alive is True


def _claim_action(harness: _FenceHarness, *, action_id: str) -> V2ActionClaim:
    with bind_v2_run_fence(harness.stale_fence):
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
    claim: V2ActionClaim,
) -> V2PresentationIdentity:
    return harness.actions.open_presentation(
        claim=claim,
        presentation_id="v2_pres_stale_tts",
        speech_id="v2_speech_stale_tts",
        voice_asset_id="v2_voice_stale_tts",
        subtitle_text="这是有效 owner 建立的语音展示。",
        sample_rate=24000,
    )


def _prepare_night_state(harness: _FenceHarness) -> V2NightRuntimeState:
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
        game = db.get(V2GameRecord, harness.game_id)
        run = db.get(V2GameRun, harness.run_id)
        assert game is not None and run is not None
        game.status = "ready"
        game.phase_id = "first_night"
        game.phase_state = "night_running"
        run.status = "ready"
        db.add(
            V2MatchState(
                game_id=harness.game_id,
                round_no=1,
                sheriff_badge_state="disabled",
            )
        )
        db.add(
            V2PlayerState(
                game_id=harness.game_id,
                player_id="seat_1",
                seat=1,
                alive=True,
                state={},
            )
        )
        db.add(
            V2ActionWindow(
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
            V2AbilityInstance(
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
    return V2NightRuntimeState(
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
        game = db.get(V2GameRecord, harness.game_id)
        assert game is not None
        return game.last_record_seq


def _events_for_action(db: Session, game_id: str, action_id: str) -> list[V2GameRecordEvent]:
    return [
        event
        for event in db.scalars(
            select(V2GameRecordEvent).where(V2GameRecordEvent.game_id == game_id)
        )
        if (event.payload or {}).get("action_id") == action_id
    ]


def _event_types(db: Session, game_id: str) -> set[str]:
    return set(
        db.scalars(
            select(V2GameRecordEvent.event_type).where(
                V2GameRecordEvent.game_id == game_id
            )
        )
    )


def _row_count(db: Session, model: type[object], game_id: str) -> int:
    return int(
        db.scalar(
            select(func.count()).select_from(model).where(model.game_id == game_id)
        )
        or 0
    )
