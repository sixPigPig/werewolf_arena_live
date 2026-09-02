from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Iterator

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.models.user import User  # noqa: F401 - registers referenced users table
from app.match.day_speech_pipeline_contract import freeze_day_speech_pipeline_contract
from app.match.execution import RunFence, bind_run_fence
from app.match.match_repository import (
    DayVoteCommit,
    MatchRepository,
)
from app.match.model_context_contract import freeze_model_context_contract
from app.match.model_generation_policy_contract import (
    freeze_model_generation_policy_contract,
)
from app.match.model_failure_episode import derive_failure_episodes
from app.match.models import (
    GameRecord,
    GameRecordEvent,
    GameRun,
    MatchState,
    PlayerState,
    PreExilePipeline,
    PreExileResult,
    RoleAssignment,
    RoleAssignmentBatch,
)
from app.match.pre_exile_pipeline_contract import (
    PreExilePipelineContractError,
    current_pre_exile_pipeline_contract,
    freeze_pre_exile_pipeline_contract,
    pre_exile_pipeline_contract_summary,
    pre_exile_context_sha256,
    resolve_pre_exile_pipeline_contract,
    schema_v2_pre_exile_pipeline_contract,
)
from app.match.pre_exile_pipeline_repository import (
    PreExilePipelineRepository,
    PreExilePipelineRepositoryError,
    PreExilePipelineSnapshot,
)
from app.match.repository import (
    ActionClaim,
    ActionRepository,
    PresentationIdentity,
    RepositoryError,
)


GAME_ID = "v2_game_pre_exile_repo"
RUN_ID = "v2_run_pre_exile_repo"
WORKER_ID = "v2_worker_pre_exile_repo"
PHASE_ID = "day_1"
PHASE_STATE = "public_discussion_open"
PREDECESSOR_ACTION_ID = "v2_action_pre_exile_last_speech"
PREDECESSOR_PRESENTATION_ID = "v2_pres_pre_exile_last_speech"
PLAYERS = ("wolf_1", "wolf_2", "villager_3", "villager_4")
WOLVES = ("wolf_1", "wolf_2")


@dataclass(frozen=True)
class _Harness:
    factory: sessionmaker[Session]
    actions: ActionRepository
    pipelines: PreExilePipelineRepository
    matches: MatchRepository
    fence: RunFence
    predecessor: PresentationIdentity
    pipeline: PreExilePipelineSnapshot
    public_history: tuple[dict[str, Any], ...]
    public_skip_record_seq: int | None = None

    def close_predecessor(self, *, commit_canonical_speech: bool = True) -> None:
        self.actions.complete_text_action(
            identity=self.predecessor,
            next_live_state="ready",
            next_phase_state=PHASE_STATE,
        )
        if commit_canonical_speech and self.public_skip_record_seq is None:
            with bind_run_fence(self.fence):
                self.actions.append_event(
                    game_id=GAME_ID,
                    event_type="day_speech_committed",
                    audience="all",
                    payload={
                        "round_no": 1,
                        "stage": "day_debate",
                        "player_id": "villager_4",
                        "speech": "4号完成本轮最后发言。",
                    },
                )

    @property
    def batch_id(self) -> str:
        return f"{PHASE_ID}:exile_vote:{self.pipeline.public_cutoff_record_seq}:vote"


@pytest.fixture
def harness() -> Iterator[_Harness]:
    engine, result = _build_harness()
    try:
        yield result
    finally:
        engine.dispose()


@pytest.fixture
def technical_skip_harness() -> Iterator[_Harness]:
    engine, result = _build_harness(technical_skip=True)
    try:
        yield result
    finally:
        engine.dispose()


def test_contract_is_exact_and_legacy_missing_stays_sequential() -> None:
    legacy = resolve_pre_exile_pipeline_contract({})
    assert legacy.status == "legacy_sequential"
    assert legacy.mode == "sequential"
    assert legacy.speculative_vote_capacity_recovery_mode == "disabled"
    assert legacy.self_explosion_early_empty_stream_hidden_retry_max_retries == 0

    schema_v1_contract = {
        "schema_version": 1,
        "mode": "sealed_last_speech_overlap",
        "action_types": ["werewolf_self_explosion", "exile_vote"],
        "launch_boundary": "last_public_speech_sealed",
        "accept_boundary": "last_public_speech_closed",
        "self_explosion_admission_mode": "normal",
        "speculative_vote_admission_mode": "idle_only",
        "speculative_vote_capacity_recovery_mode": "normal_batch_after_close_once",
        "wolf_vote_gate": "own_no_explosion_result",
        "vote_abort_policy": "any_explosion_discards_all_votes",
        "private_context_mode": "sealed_snapshot_plus_own_no_explosion_fact",
        "result_commit_mode": "durable_atomic_arbiter",
        "fallback_mode": "before_launch_sequential_only",
        "inflight_recovery_mode": "no_duplicate_provider",
    }
    schema_v1 = resolve_pre_exile_pipeline_contract(
        {"pre_exile_pipeline_contract": schema_v1_contract}
    )
    assert schema_v1.schema_version == 1
    assert schema_v1.self_explosion_early_empty_stream_hidden_retry_max_retries == 0

    frozen = freeze_pre_exile_pipeline_contract({"rule_set": {"id": "test"}})
    assert frozen["pre_exile_pipeline_contract"] == (current_pre_exile_pipeline_contract())
    resolved = resolve_pre_exile_pipeline_contract(frozen)
    assert resolved.status == "supported"
    assert resolved.schema_version == 3
    assert resolved.speculative_vote_capacity_recovery_mode == ("normal_batch_after_close_once")
    assert resolved.self_explosion_early_empty_stream_hidden_retry_max_retries == 1
    assert pre_exile_pipeline_contract_summary(frozen) == {
        "status": "supported",
        "schema_version": 3,
        "mode": "sealed_last_speech_overlap",
        "action_types": ["werewolf_self_explosion", "exile_vote"],
        "launch_boundary": "last_public_speech_sealed",
        "accept_boundary": "last_public_speech_sealed",
        "self_explosion_admission_mode": "normal",
        "speculative_vote_admission_mode": "normal",
        "speculative_vote_capacity_recovery_mode": "normal_batch_after_close_once",
        "wolf_vote_gate": "own_no_explosion_result",
        "vote_abort_policy": "any_explosion_discards_all_votes",
        "private_context_mode": "sealed_snapshot_plus_own_no_explosion_fact",
        "result_commit_mode": "durable_atomic_arbiter",
        "fallback_mode": "before_launch_sequential_only",
        "inflight_recovery_mode": "no_duplicate_provider",
        "self_explosion_early_empty_stream_hidden_retry_max_retries": 1,
    }

    malformed_contracts = [
        {**current_pre_exile_pipeline_contract(), "fallback_mode": "sequential"},
        {
            **current_pre_exile_pipeline_contract(),
            "self_explosion_early_empty_stream_hidden_retry_max_retries": 0,
        },
        {
            key: value
            for key, value in current_pre_exile_pipeline_contract().items()
            if key != "self_explosion_early_empty_stream_hidden_retry_max_retries"
        },
        {**schema_v1_contract, "self_explosion_early_empty_stream_hidden_retry_max_retries": 1},
    ]
    for malformed in malformed_contracts:
        with pytest.raises(
            PreExilePipelineContractError,
            match="unsupported_pre_exile_pipeline_contract",
        ):
            resolve_pre_exile_pipeline_contract({"pre_exile_pipeline_contract": malformed})


def test_normal_and_technical_skip_last_speech_lineage_is_strict(
    harness: _Harness,
    technical_skip_harness: _Harness,
) -> None:
    assert harness.pipeline.predecessor_action_id == PREDECESSOR_ACTION_ID
    assert technical_skip_harness.pipeline.predecessor_action_id == (PREDECESSOR_ACTION_ID)
    assert technical_skip_harness.public_skip_record_seq is not None

    with technical_skip_harness.factory.begin() as db:
        event = db.scalar(
            select(GameRecordEvent).where(
                GameRecordEvent.game_id == GAME_ID,
                GameRecordEvent.record_seq == technical_skip_harness.public_skip_record_seq,
            )
        )
        assert event is not None
        event.payload = {
            **event.payload,
            "actor_id": "villager_3",
        }

    with pytest.raises(
        PreExilePipelineRepositoryError,
        match="technical-skip predecessor has no public skip fact",
    ):
        _reserve_again(technical_skip_harness)


def test_pre_exile_generation_claim_allows_finalizing_with_active_predecessor(
    harness: _Harness,
) -> None:
    self_result = _record_self_result(harness, actor_id="wolf_1", explode=False)
    assert self_result.state == "ready"
    assert self_result.private_fact_record_seq is not None
    harness.pipelines.reserve_result(
        pipeline_id=harness.pipeline.pipeline_id,
        actor_player_id="wolf_1",
        result_kind="exile_vote",
        fence=harness.fence,
    )
    harness.actions.mark_finalizing(
        identity=harness.predecessor,
        tts_attempt_id="v2_tts_finalizing_pre_exile_vote",
        sample_count=24_000,
    )

    action_id = "v2_action_finalizing_pre_exile_vote"
    claim = _claim_initial(
        harness,
        actor_id="wolf_1",
        result_kind="exile_vote",
        action_id=action_id,
    )

    assert claim.action_id == action_id
    assert claim.non_blocking is True
    with harness.factory() as db:
        result = db.scalar(
            select(PreExileResult).where(
                PreExileResult.pipeline_id == harness.pipeline.pipeline_id,
                PreExileResult.actor_player_id == "wolf_1",
                PreExileResult.result_kind == "exile_vote",
            )
        )
        opened = db.scalar(
            select(GameRecordEvent).where(
                GameRecordEvent.game_id == GAME_ID,
                GameRecordEvent.event_type == "action_opened",
                GameRecordEvent.payload["action_id"].as_string() == action_id,
            )
        )
    assert result is not None and result.action_id == action_id
    assert opened is not None
    assert opened.payload["context"]["pipeline"]["result_kind"] == "exile_vote"


def test_pre_exile_generation_claim_rejects_finalizing_without_active_predecessor(
    harness: _Harness,
) -> None:
    harness.pipelines.reserve_result(
        pipeline_id=harness.pipeline.pipeline_id,
        actor_player_id="villager_3",
        result_kind="exile_vote",
        fence=harness.fence,
    )
    harness.close_predecessor()
    harness.actions.mark_finalizing(
        identity=harness.predecessor,
        tts_attempt_id="v2_tts_finalizing_without_active_predecessor",
        sample_count=24_000,
    )

    action_id = "v2_action_finalizing_without_active_predecessor"
    with pytest.raises(RepositoryError, match="pre-exile predecessor is no longer active"):
        _claim_initial(
            harness,
            actor_id="villager_3",
            result_kind="exile_vote",
            action_id=action_id,
        )

    with harness.factory() as db:
        result = db.scalar(
            select(PreExileResult).where(
                PreExileResult.pipeline_id == harness.pipeline.pipeline_id,
                PreExileResult.actor_player_id == "villager_3",
                PreExileResult.result_kind == "exile_vote",
            )
        )
        opened = db.scalar(
            select(GameRecordEvent).where(
                GameRecordEvent.game_id == GAME_ID,
                GameRecordEvent.event_type == "action_opened",
                GameRecordEvent.payload["action_id"].as_string() == action_id,
            )
        )
    assert result is not None and result.action_id is None
    assert opened is None


def test_schema_v2_self_explosion_requires_retry_metadata_and_exile_vote_forbids_it(
    harness: _Harness,
) -> None:
    harness.pipelines.reserve_result(
        pipeline_id=harness.pipeline.pipeline_id,
        actor_player_id="wolf_1",
        result_kind="self_explosion",
        fence=harness.fence,
    )
    self_action_id = "v2_action_schema_v2_self_retry"
    with (
        bind_run_fence(harness.fence),
        pytest.raises(
            RepositoryError,
            match="pre-exile pipeline generation claim is not isolated",
        ),
    ):
        harness.actions.claim_action(
            game_id=GAME_ID,
            action_id=self_action_id,
            context=_initial_context(
                harness,
                action_id=self_action_id,
                actor_id="wolf_1",
                result_kind="self_explosion",
                self_explosion_retry=False,
            ),
            expected_phase_id=PHASE_ID,
            expected_phase_state=PHASE_STATE,
            audience="god_view",
            context_audience="god_view",
            non_blocking=True,
        )
    self_claim = _claim_initial(
        harness,
        actor_id="wolf_1",
        result_kind="self_explosion",
        action_id=self_action_id,
    )
    assert self_claim.action_id == self_action_id

    _record_self_result(harness, actor_id="wolf_2", explode=False)
    harness.pipelines.reserve_result(
        pipeline_id=harness.pipeline.pipeline_id,
        actor_player_id="wolf_2",
        result_kind="exile_vote",
        fence=harness.fence,
    )
    vote_action_id = "v2_action_schema_v2_vote_no_retry"
    vote_context = _initial_context(
        harness,
        action_id=vote_action_id,
        actor_id="wolf_2",
        result_kind="exile_vote",
    )
    vote_context["pipeline"].update(
        {
            "retry_mode": "empty_stream_once_while_predecessor_active",
            "empty_stream_max_attempts": 2,
        }
    )
    with (
        bind_run_fence(harness.fence),
        pytest.raises(
            RepositoryError,
            match="pre-exile pipeline generation claim is not isolated",
        ),
    ):
        harness.actions.claim_action(
            game_id=GAME_ID,
            action_id=vote_action_id,
            context=vote_context,
            expected_phase_id=PHASE_ID,
            expected_phase_state=PHASE_STATE,
            audience="god_view",
            context_audience="god_view",
            non_blocking=True,
        )
    vote_claim = _claim_initial(
        harness,
        actor_id="wolf_2",
        result_kind="exile_vote",
        action_id=vote_action_id,
    )
    assert vote_claim.action_id == vote_action_id


def test_schema_v1_self_explosion_preserves_legacy_pipeline_context() -> None:
    engine, harness = _build_harness(pre_exile_schema_version=1)
    try:
        harness.pipelines.reserve_result(
            pipeline_id=harness.pipeline.pipeline_id,
            actor_player_id="wolf_1",
            result_kind="self_explosion",
            fence=harness.fence,
        )
        action_id = "v2_action_schema_v1_self_legacy"
        with (
            bind_run_fence(harness.fence),
            pytest.raises(
                RepositoryError,
                match="pre-exile pipeline generation claim is not isolated",
            ),
        ):
            harness.actions.claim_action(
                game_id=GAME_ID,
                action_id=action_id,
                context=_initial_context(
                    harness,
                    action_id=action_id,
                    actor_id="wolf_1",
                    result_kind="self_explosion",
                ),
                expected_phase_id=PHASE_ID,
                expected_phase_state=PHASE_STATE,
                audience="god_view",
                context_audience="god_view",
                non_blocking=True,
            )
        with bind_run_fence(harness.fence):
            claim = harness.actions.claim_action(
                game_id=GAME_ID,
                action_id=action_id,
                context=_initial_context(
                    harness,
                    action_id=action_id,
                    actor_id="wolf_1",
                    result_kind="self_explosion",
                    self_explosion_retry=False,
                ),
                expected_phase_id=PHASE_ID,
                expected_phase_state=PHASE_STATE,
                audience="god_view",
                context_audience="god_view",
                non_blocking=True,
            )
        assert claim is not None
        assert claim.action_id == action_id
    finally:
        engine.dispose()


def test_day_speech_generation_claim_remains_rejected_while_finalizing(
    harness: _Harness,
) -> None:
    harness.actions.mark_finalizing(
        identity=harness.predecessor,
        tts_attempt_id="v2_tts_finalizing_day_speech_generation",
        sample_count=24_000,
    )

    action_id = "v2_action_finalizing_day_speech_generation"
    context = {
        **_speech_context(),
        "action_id": action_id,
        "actor": {"kind": "player", "id": "villager_3"},
        "public_history_cutoff_record_seq": harness.pipeline.public_cutoff_record_seq,
        "projection_at_seq": harness.pipeline.public_cutoff_record_seq,
        "batch_id": "v2_slot_finalizing:generation",
        "pipeline": {
            "slot_id": "v2_slot_finalizing",
            "stage": "generation",
            "model_admission_mode": "idle_only",
            "retry_mode": "empty_stream_once_while_predecessor_active",
            "empty_stream_max_attempts": 2,
        },
    }
    with (
        bind_run_fence(harness.fence),
        pytest.raises(
            RepositoryError,
            match="day speech pipeline generation is not frozen and enabled",
        ),
    ):
        harness.actions.claim_action(
            game_id=GAME_ID,
            action_id=action_id,
            context=context,
            expected_phase_id=PHASE_ID,
            expected_phase_state=PHASE_STATE,
            audience="player_private",
            context_audience="player_private",
            non_blocking=True,
        )


def test_arbiter_requires_player_canonical_commit_but_not_technical_skip_commit(
    harness: _Harness,
    technical_skip_harness: _Harness,
) -> None:
    for target in (harness, technical_skip_harness):
        _record_self_result(target, actor_id="wolf_1", explode=False)
        _record_self_result(target, actor_id="wolf_2", explode=False)

    with technical_skip_harness.factory.begin() as db:
        row = db.scalar(
            select(PreExileResult).where(
                PreExileResult.pipeline_id == technical_skip_harness.pipeline.pipeline_id,
                PreExileResult.actor_player_id == "wolf_1",
                PreExileResult.result_kind == "self_explosion",
            )
        )
        assert row is not None and row.private_fact_record_seq is not None
        recorded = db.scalar(
            select(GameRecordEvent).where(
                GameRecordEvent.game_id == GAME_ID,
                GameRecordEvent.record_seq == row.private_fact_record_seq,
            )
        )
        assert recorded is not None
        recorded.event_id += 1_000

    harness.close_predecessor(commit_canonical_speech=False)
    with (
        bind_run_fence(harness.fence),
        pytest.raises(
            RepositoryError,
            match="canonical day speech is not committed",
        ),
    ):
        harness.matches.resolve_pre_exile_self_explosions(
            game_id=GAME_ID,
            pipeline_id=harness.pipeline.pipeline_id,
            expected_wolf_ids=WOLVES,
        )

    technical_skip_harness.close_predecessor()
    with bind_run_fence(technical_skip_harness.fence):
        resolved = technical_skip_harness.matches.resolve_pre_exile_self_explosions(
            game_id=GAME_ID,
            pipeline_id=technical_skip_harness.pipeline.pipeline_id,
            expected_wolf_ids=WOLVES,
        )
    assert resolved.outcome == "no_explosion"
    with technical_skip_harness.factory() as db:
        commits = list(
            db.scalars(
                select(GameRecordEvent).where(
                    GameRecordEvent.game_id == GAME_ID,
                    GameRecordEvent.event_type == "day_speech_committed",
                )
            )
        )
    assert commits == []


def test_false_path_capacity_batch_adoption_and_vote_consume_are_atomic(
    harness: _Harness,
) -> None:
    wolf_1 = _record_self_result(harness, actor_id="wolf_1", technical_false=True)
    with pytest.raises(
        PreExilePipelineRepositoryError,
        match="different durable success lineage",
    ):
        harness.pipelines.record_result(
            pipeline_id=harness.pipeline.pipeline_id,
            actor_player_id="wolf_1",
            result_kind="self_explosion",
            action_id=str(wolf_1.action_id),
            technical_outcome_record_seq=int(wolf_1.private_fact_record_seq or 0),
            fence=harness.fence,
        )
    _record_self_result(harness, actor_id="wolf_2", explode=False)
    assert harness.matches.private_knowledge(game_id=GAME_ID, player_id="wolf_1") == []
    provisional = harness.pipelines.get_provisional_self_explosion_fact(
        pipeline_id=harness.pipeline.pipeline_id,
        actor_player_id="wolf_1",
        private_fact_id=str(wolf_1.private_fact_id),
        fence=harness.fence,
    )
    assert provisional["known_at_seq"] == wolf_1.private_fact_record_seq
    assert provisional["payload"]["decision"] == {"explode": False}

    initial_rows: dict[str, Any] = {}
    for actor_id in ("villager_3", "villager_4"):
        initial_rows[actor_id] = _record_capacity_failure(harness, actor_id=actor_id)

    harness.close_predecessor()
    with bind_run_fence(harness.fence):
        resolved = harness.matches.resolve_pre_exile_self_explosions(
            game_id=GAME_ID,
            pipeline_id=harness.pipeline.pipeline_id,
            expected_wolf_ids=WOLVES,
        )
    assert resolved.outcome == "no_explosion"
    assert resolved.failed_player_ids == ("wolf_1",)

    committed_private = harness.matches.private_knowledge(
        game_id=GAME_ID,
        player_id="wolf_1",
    )
    assert len(committed_private) == 1
    assert committed_private[0]["source_event_type"] == ("pre_exile_private_fact_committed")
    assert committed_private[0]["known_at_seq"] > int(wolf_1.private_fact_record_seq or 0)

    recoveries: dict[str, ActionClaim] = {}
    for actor_id, target_id in (
        ("villager_3", "wolf_1"),
        ("villager_4", "wolf_2"),
    ):
        recoveries[actor_id] = _claim_recovery(
            harness,
            actor_id=actor_id,
            source_row=initial_rows[actor_id],
        )

    with harness.factory() as db:
        game = db.get(GameRecord, GAME_ID)
        run = db.get(GameRun, RUN_ID)
        assert game is not None and run is not None
        assert game.status == run.status == "ready"
        bound = list(
            db.scalars(
                select(PreExileResult).where(
                    PreExileResult.pipeline_id == harness.pipeline.pipeline_id,
                    PreExileResult.result_kind == "exile_vote",
                )
            )
        )
        assert all(row.recovery_action_id is not None for row in bound)
        assert all(row.recovery_terminal_record_seq is None for row in bound)

    adopted: dict[str, Any] = {}
    for actor_id, target_id in (
        ("villager_3", "wolf_1"),
        ("villager_4", "wolf_2"),
    ):
        claim = recoveries[actor_id]
        _complete_success(
            harness,
            claim=claim,
            parsed_output={"target_player_id": target_id, "decision_note": None},
        )
        adopted[actor_id] = harness.pipelines.adopt_vote_recovery_result(
            pipeline_id=harness.pipeline.pipeline_id,
            actor_player_id=actor_id,
            source_action_id=str(initial_rows[actor_id].action_id),
            recovery_action_id=claim.action_id,
            fence=harness.fence,
        )
        assert adopted[actor_id].state == "ready"
        assert set(adopted[actor_id].failure or {}) == {"initial_admission_failure"}
        assert adopted[actor_id].recovery_terminal_record_seq is not None

    votes = (
        DayVoteCommit("villager_3", "wolf_1", 1.0, None),
        DayVoteCommit("villager_4", "wolf_2", 1.0, None),
    )
    resolution = _resolution_payload(harness, votes=votes)
    self_terminal_before = {
        row.actor_player_id: row.terminal_at
        for row in harness.pipelines.list_results(harness.pipeline.pipeline_id)
        if row.result_kind == "self_explosion"
    }
    with bind_run_fence(harness.fence):
        harness.matches.finalize_day_vote_batch(
            game_id=GAME_ID,
            phase_id=PHASE_ID,
            phase_state=PHASE_STATE,
            round_no=1,
            action_type="exile_vote",
            batch_id=harness.batch_id,
            public_cutoff_record_seq=harness.pipeline.public_cutoff_record_seq,
            expected_voter_ids=("villager_3", "villager_4"),
            votes=votes,
            decision_context={
                "batch_id": harness.batch_id,
                "public_cutoff_record_seq": harness.pipeline.public_cutoff_record_seq,
            },
            resolution_payload=resolution,
            pre_exile_pipeline_id=harness.pipeline.pipeline_id,
        )
        # Same batch is a read-only idempotent retry.
        harness.matches.finalize_day_vote_batch(
            game_id=GAME_ID,
            phase_id=PHASE_ID,
            phase_state=PHASE_STATE,
            round_no=1,
            action_type="exile_vote",
            batch_id=harness.batch_id,
            public_cutoff_record_seq=harness.pipeline.public_cutoff_record_seq,
            expected_voter_ids=("villager_3", "villager_4"),
            votes=votes,
            decision_context={
                "batch_id": harness.batch_id,
                "public_cutoff_record_seq": harness.pipeline.public_cutoff_record_seq,
            },
            resolution_payload=resolution,
            pre_exile_pipeline_id=harness.pipeline.pipeline_id,
        )

    with (
        bind_run_fence(harness.fence),
        pytest.raises(
            RepositoryError,
            match="retry changed a committed private vote",
        ),
    ):
        harness.matches.finalize_day_vote_batch(
            game_id=GAME_ID,
            phase_id=PHASE_ID,
            phase_state=PHASE_STATE,
            round_no=1,
            action_type="exile_vote",
            batch_id=harness.batch_id,
            public_cutoff_record_seq=harness.pipeline.public_cutoff_record_seq,
            expected_voter_ids=("villager_3", "villager_4"),
            votes=(
                DayVoteCommit("villager_3", "wolf_1", 1.0, "tampered"),
                votes[1],
            ),
            decision_context={
                "batch_id": harness.batch_id,
                "public_cutoff_record_seq": harness.pipeline.public_cutoff_record_seq,
            },
            resolution_payload=resolution,
            pre_exile_pipeline_id=harness.pipeline.pipeline_id,
        )
    with (
        bind_run_fence(harness.fence),
        pytest.raises(
            RepositoryError,
            match="retry changed an already committed vote batch",
        ),
    ):
        harness.matches.finalize_day_vote_batch(
            game_id=GAME_ID,
            phase_id=PHASE_ID,
            phase_state=PHASE_STATE,
            round_no=1,
            action_type="exile_vote",
            batch_id=harness.batch_id,
            public_cutoff_record_seq=harness.pipeline.public_cutoff_record_seq,
            expected_voter_ids=("villager_3", "villager_4"),
            votes=votes,
            decision_context={
                "batch_id": harness.batch_id,
                "public_cutoff_record_seq": harness.pipeline.public_cutoff_record_seq,
            },
            resolution_payload={},
            pre_exile_pipeline_id=harness.pipeline.pipeline_id,
        )
    with (
        bind_run_fence(harness.fence),
        pytest.raises(
            RepositoryError,
            match="different durable output",
        ),
    ):
        harness.matches.finalize_day_vote_batch(
            game_id=GAME_ID,
            phase_id=PHASE_ID,
            phase_state=PHASE_STATE,
            round_no=1,
            action_type="exile_vote",
            batch_id=harness.batch_id,
            public_cutoff_record_seq=harness.pipeline.public_cutoff_record_seq,
            expected_voter_ids=("villager_3", "villager_4"),
            votes=votes,
            decision_context={
                "batch_id": harness.batch_id,
                "public_cutoff_record_seq": harness.pipeline.public_cutoff_record_seq,
                "tampered": True,
            },
            resolution_payload=resolution,
            pre_exile_pipeline_id=harness.pipeline.pipeline_id,
        )

    pipeline = harness.pipelines.get_pipeline(harness.pipeline.pipeline_id)
    results = harness.pipelines.list_results(harness.pipeline.pipeline_id)
    assert pipeline.state == "consumed"
    assert all(row.state == "committed" and row.terminal_at is not None for row in results)
    assert {
        row.actor_player_id: row.terminal_at
        for row in results
        if row.result_kind == "self_explosion"
    } == self_terminal_before
    with harness.factory() as db:
        events = list(
            db.scalars(
                select(GameRecordEvent)
                .where(GameRecordEvent.game_id == GAME_ID)
                .order_by(GameRecordEvent.record_seq)
            )
        )
    assert len([event for event in events if event.event_type == "day_vote_committed"]) == 2
    recovery_audits = [
        event
        for event in events
        if event.event_type == "pre_exile_result_recorded"
        and event.payload.get("recovery_action_id") is not None
    ]
    assert len(recovery_audits) == 2
    assert all(event.payload.get("recovery_terminal_record_seq") for event in recovery_audits)
    assert all("decision" not in event.payload for event in recovery_audits)


def test_true_path_atomically_kills_discards_votes_and_is_idempotent(
    harness: _Harness,
) -> None:
    _record_self_result(harness, actor_id="wolf_1", explode=True)
    _record_self_result(harness, actor_id="wolf_2", technical_false=True)
    _record_open_vote_attempt(
        harness,
        actor_id="villager_3",
    )
    harness.close_predecessor()

    with bind_run_fence(harness.fence):
        resolved = harness.matches.resolve_pre_exile_self_explosions(
            game_id=GAME_ID,
            pipeline_id=harness.pipeline.pipeline_id,
            expected_wolf_ids=WOLVES,
        )
        repeated = harness.matches.resolve_pre_exile_self_explosions(
            game_id=GAME_ID,
            pipeline_id=harness.pipeline.pipeline_id,
            expected_wolf_ids=WOLVES,
        )
    assert resolved == repeated
    assert resolved.outcome == "explosion_selected"
    assert resolved.selected_player_id == "wolf_1"
    assert resolved.failed_player_ids == ("wolf_2",)

    with harness.factory() as db:
        pipeline = db.get(PreExilePipeline, harness.pipeline.pipeline_id)
        wolf = db.get(PlayerState, (GAME_ID, "wolf_1"))
        results = list(
            db.scalars(
                select(PreExileResult).where(
                    PreExileResult.pipeline_id == harness.pipeline.pipeline_id
                )
            )
        )
        events = list(
            db.scalars(select(GameRecordEvent).where(GameRecordEvent.game_id == GAME_ID))
        )
    assert pipeline is not None and pipeline.state == "explosion_selected"
    assert wolf is not None and not wolf.alive and wolf.death_cause == "werewolf_self_explosion"
    assert all(
        result.state == "committed" for result in results if result.result_kind == "self_explosion"
    )
    assert all(
        result.state == "discarded" for result in results if result.result_kind == "exile_vote"
    )
    assert not [event for event in events if event.event_type.startswith("day_vote_")]
    assert len([event for event in events if event.event_type == "werewolf_self_exploded"]) == 1
    episodes = derive_failure_episodes(sorted(events, key=lambda event: event.record_seq))
    vote_episodes = [
        episode for episode in episodes if episode.action_id == "v2_action_open_vote_villager_3"
    ]
    assert len(vote_episodes) == 1
    assert vote_episodes[0].resolution == "isolated_action_failure"
    assert not any(episode.is_open for episode in episodes)
    for terminalizer in (
        harness.pipelines.cancel_pipeline,
        harness.pipelines.invalidate_pipeline,
    ):
        with pytest.raises(
            PreExilePipelineRepositoryError,
            match="pipeline is terminal",
        ):
            terminalizer(
                pipeline_id=harness.pipeline.pipeline_id,
                reason_code="stale_terminalizer",
                fence=harness.fence,
            )
    assert (
        harness.pipelines.get_pipeline(harness.pipeline.pipeline_id).state == "explosion_selected"
    )


def test_capacity_recovery_allows_queued_but_rejects_admitted_source(
    harness: _Harness,
) -> None:
    _record_self_result(harness, actor_id="wolf_1", explode=False)
    _record_self_result(harness, actor_id="wolf_2", explode=False)
    queued = _record_capacity_failure(
        harness,
        actor_id="villager_3",
        admission_event_type="model_request_queued",
    )
    admitted = _record_capacity_failure(
        harness,
        actor_id="villager_4",
        admission_event_type="model_request_admitted",
    )
    harness.close_predecessor()
    with bind_run_fence(harness.fence):
        harness.matches.resolve_pre_exile_self_explosions(
            game_id=GAME_ID,
            pipeline_id=harness.pipeline.pipeline_id,
            expected_wolf_ids=WOLVES,
        )

    queued_claim = _claim_recovery(
        harness,
        actor_id="villager_3",
        source_row=queued,
    )
    assert queued_claim.action_id == "v2_action_recovery_villager_3"
    _complete_success(
        harness,
        claim=queued_claim,
        parsed_output={"target_player_id": "wolf_1", "decision_note": None},
    )
    with bind_run_fence(harness.fence):
        forged_response_seq = harness.actions.append_event(
            game_id=GAME_ID,
            event_type="model_response_received",
            audience="god_view",
            payload={
                "action_id": queued_claim.action_id,
                "attempt_id": "v2_attempt_forged_after_terminal",
                "application_validation_result": "accepted",
                "parsed_output": {
                    "target_player_id": "wolf_2",
                    "decision_note": None,
                },
            },
        )
    with pytest.raises(
        PreExilePipelineRepositoryError,
        match="recovery result is invalid",
    ):
        harness.pipelines.adopt_vote_recovery_result(
            pipeline_id=harness.pipeline.pipeline_id,
            actor_player_id="villager_3",
            source_action_id=str(queued.action_id),
            recovery_action_id=queued_claim.action_id,
            response_record_seq=forged_response_seq,
            fence=harness.fence,
        )
    with pytest.raises(
        RepositoryError,
        match="reached the provider and cannot be repeated",
    ):
        _claim_recovery(
            harness,
            actor_id="villager_4",
            source_row=admitted,
        )


def test_fail_runtime_flushes_synthetic_episode_before_run_terminal(
    harness: _Harness,
) -> None:
    _record_open_vote_attempt(harness, actor_id="villager_3")
    with bind_run_fence(harness.fence):
        harness.matches.fail_runtime(
            game_id=GAME_ID,
            failure_code="pre_exile_test_runtime_failure",
        )
    with harness.factory() as db:
        events = list(
            db.scalars(
                select(GameRecordEvent)
                .where(GameRecordEvent.game_id == GAME_ID)
                .order_by(GameRecordEvent.record_seq)
            )
        )
        pipeline = db.get(PreExilePipeline, harness.pipeline.pipeline_id)
        result = db.scalar(
            select(PreExileResult).where(
                PreExileResult.pipeline_id == harness.pipeline.pipeline_id,
                PreExileResult.actor_player_id == "villager_3",
                PreExileResult.result_kind == "exile_vote",
            )
        )
    episodes = derive_failure_episodes(events)
    assert len(episodes) == 1
    assert episodes[0].resolution == "run_failure"
    failed = next(event for event in events if event.event_type == "day_runtime_failed")
    assert failed.payload["failed_failure_episode_ids"] == [episodes[0].failure_episode_id]
    assert pipeline is not None and pipeline.state == "invalidated"
    assert result is not None and result.state == "discarded"


def test_recovery_adoption_rejects_technical_fact_forged_after_terminal(
    harness: _Harness,
) -> None:
    _record_self_result(harness, actor_id="wolf_1", explode=False)
    _record_self_result(harness, actor_id="wolf_2", explode=False)
    source = _record_capacity_failure(harness, actor_id="villager_3")
    harness.close_predecessor()
    with bind_run_fence(harness.fence):
        harness.matches.resolve_pre_exile_self_explosions(
            game_id=GAME_ID,
            pipeline_id=harness.pipeline.pipeline_id,
            expected_wolf_ids=WOLVES,
        )
    claim = _claim_recovery(
        harness,
        actor_id="villager_3",
        source_row=source,
    )
    with harness.factory() as db:
        game = db.get(GameRecord, GAME_ID)
        assert game is not None
        forged_technical_seq = game.last_record_seq + 2
    with bind_run_fence(harness.fence):
        harness.actions.complete_silent_action(
            claim=claim,
            next_live_state="ready",
            next_phase_state=PHASE_STATE,
            failure_episode_id="v2_failure_forged_after_terminal",
            technical_outcome_record_seq=forged_technical_seq,
        )
        actual_technical_seq = harness.actions.append_event(
            game_id=GAME_ID,
            event_type="technical_target_outcome_applied",
            audience="god_view",
            payload={
                "action_id": claim.action_id,
                "attempt_id": "v2_attempt_forged_technical",
                "actor_id": "villager_3",
                "action_type": "exile_vote",
                "technical_outcome": "technical_abstain",
                "failure_episode_id": "v2_failure_forged_after_terminal",
                "failure_code": "model_action_wall_timeout",
                "target_exhaustion_failure_mode": "action_wall_timeout",
                "target_player_id": None,
                "model_generation_policy_schema_version": 4,
            },
        )
    assert actual_technical_seq == forged_technical_seq
    with pytest.raises(
        PreExilePipelineRepositoryError,
        match="recovery technical outcome is invalid",
    ):
        harness.pipelines.adopt_vote_recovery_result(
            pipeline_id=harness.pipeline.pipeline_id,
            actor_player_id="villager_3",
            source_action_id=str(source.action_id),
            recovery_action_id=claim.action_id,
            technical_outcome_record_seq=actual_technical_seq,
            fence=harness.fence,
        )


def test_late_wolf_vote_claim_uses_committed_false_fact_and_rejects_later_public_speech(
    harness: _Harness,
) -> None:
    wolf_1 = _record_self_result(harness, actor_id="wolf_1", explode=False)
    _record_self_result(harness, actor_id="wolf_2", explode=False)
    harness.pipelines.reserve_result(
        pipeline_id=harness.pipeline.pipeline_id,
        actor_player_id="wolf_1",
        result_kind="exile_vote",
        fence=harness.fence,
    )
    harness.pipelines.reserve_result(
        pipeline_id=harness.pipeline.pipeline_id,
        actor_player_id="wolf_2",
        result_kind="exile_vote",
        fence=harness.fence,
    )
    harness.close_predecessor()
    with bind_run_fence(harness.fence):
        harness.matches.resolve_pre_exile_self_explosions(
            game_id=GAME_ID,
            pipeline_id=harness.pipeline.pipeline_id,
            expected_wolf_ids=WOLVES,
        )
    committed = harness.pipelines.list_results(harness.pipeline.pipeline_id)
    committed_wolf_1 = next(
        row
        for row in committed
        if row.actor_player_id == "wolf_1" and row.result_kind == "self_explosion"
    )
    assert committed_wolf_1.state == "committed"
    assert committed_wolf_1.private_fact_id == wolf_1.private_fact_id

    claim = _claim_initial(
        harness,
        actor_id="wolf_1",
        result_kind="exile_vote",
        action_id="v2_action_late_wolf_vote_1",
    )
    assert claim.non_blocking

    with bind_run_fence(harness.fence):
        harness.actions.append_event(
            game_id=GAME_ID,
            event_type="speech_segment_committed",
            audience="all",
            payload={
                "action_id": "v2_action_illegal_later_speech",
                "presentation_id": "v2_pres_illegal_later_speech",
                "speech_id": "v2_speech_illegal_later_speech",
                "segment_index": 0,
                "text": "不应跨过这条公开边界。",
            },
        )
    with pytest.raises(RepositoryError, match="crossed a public boundary"):
        _claim_initial(
            harness,
            actor_id="wolf_2",
            result_kind="exile_vote",
            action_id="v2_action_late_wolf_vote_2",
        )


def test_cancelled_pipeline_hides_provisional_fact_and_non_atomic_mutators_fail(
    harness: _Harness,
) -> None:
    row = _record_self_result(harness, actor_id="wolf_1", explode=False)
    assert row.private_fact_id is not None
    assert harness.matches.private_knowledge(game_id=GAME_ID, player_id="wolf_1") == []

    canceled = harness.pipelines.cancel_pipeline(
        pipeline_id=harness.pipeline.pipeline_id,
        reason_code="test_cancel",
        fence=harness.fence,
    )
    assert canceled.state == "canceled"
    assert harness.matches.private_knowledge(game_id=GAME_ID, player_id="wolf_1") == []
    with pytest.raises(
        PreExilePipelineRepositoryError,
        match="provisional_self_explosion_fact_unavailable",
    ):
        harness.pipelines.get_provisional_self_explosion_fact(
            pipeline_id=harness.pipeline.pipeline_id,
            actor_player_id="wolf_1",
            private_fact_id=row.private_fact_id,
            fence=harness.fence,
        )
    with pytest.raises(
        PreExilePipelineRepositoryError,
        match="pre_exile_atomic_arbiter_required",
    ):
        harness.pipelines.resolve_self_explosions(
            pipeline_id=harness.pipeline.pipeline_id,
            expected_wolf_ids=WOLVES,
            fence=harness.fence,
        )
    with pytest.raises(
        PreExilePipelineRepositoryError,
        match="pre_exile_atomic_vote_commit_required",
    ):
        harness.pipelines.accept_votes(
            pipeline_id=harness.pipeline.pipeline_id,
            expected_voter_ids=("villager_3",),
            fence=harness.fence,
        )


def _build_harness(
    *,
    technical_skip: bool = False,
    pre_exile_schema_version: int = 2,
) -> tuple[Any, _Harness]:
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)
    rule_snapshot: dict[str, Any] = {
        "rule_set": {
            "id": "pre-exile-repository-test",
            "sheriff_enabled": False,
            "speech_rounds": 1,
        },
        "max_rounds": 8,
    }
    rule_snapshot = freeze_model_context_contract(rule_snapshot)
    rule_snapshot = freeze_model_generation_policy_contract(rule_snapshot)
    rule_snapshot = freeze_day_speech_pipeline_contract(rule_snapshot)
    rule_snapshot = freeze_pre_exile_pipeline_contract(rule_snapshot)
    rule_snapshot["pre_exile_pipeline_contract"] = schema_v2_pre_exile_pipeline_contract()
    if pre_exile_schema_version == 1:
        schema_v1_contract = dict(rule_snapshot["pre_exile_pipeline_contract"])
        schema_v1_contract["schema_version"] = 1
        schema_v1_contract.pop(
            "self_explosion_early_empty_stream_hidden_retry_max_retries"
        )
        rule_snapshot["pre_exile_pipeline_contract"] = schema_v1_contract
    elif pre_exile_schema_version != 2:
        raise ValueError("unsupported pre-exile test schema")
    now = datetime.now(tz=UTC)
    with factory.begin() as db:
        db.add(
            GameRecord(
                game_id=GAME_ID,
                title="pre exile repository test",
                status="ready",
                current_run_id=RUN_ID,
                last_record_seq=0,
                last_presentation_seq=0,
                phase_seq=3,
                phase_id=PHASE_ID,
                phase_state=PHASE_STATE,
                rule_snapshot=rule_snapshot,
                players_snapshot=[
                    {
                        "profile_id": player_id,
                        "name": player_id,
                        "model_provider": "agent_plan",
                        "model": "test-model",
                        "model_supports_thinking": False,
                        "model_parameters": {
                            "thinking": "disabled",
                            "reasoning_effort": None,
                            "max_tokens_mode": "manual",
                            "max_tokens": 512,
                        },
                    }
                    for player_id in PLAYERS
                ],
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
                status="ready",
                worker_id=WORKER_ID,
                worker_heartbeat_at=now,
                lease_expires_at=now + timedelta(minutes=5),
                fence_token=7,
            )
        )
        db.add(MatchState(game_id=GAME_ID, round_no=1, sheriff_badge_state="disabled"))
        db.add(
            RoleAssignmentBatch(
                assignment_id="v2_roles_pre_exile_repo",
                game_id=GAME_ID,
                seed_hex="a" * 64,
                assignment_digest="b" * 64,
                player_count=len(PLAYERS),
            )
        )
        for seat, player_id in enumerate(PLAYERS, start=1):
            is_wolf = player_id.startswith("wolf_")
            db.add(
                PlayerState(
                    game_id=GAME_ID,
                    player_id=player_id,
                    seat=seat,
                    alive=True,
                    state={"can_vote": True},
                )
            )
            db.add(
                RoleAssignment(
                    game_id=GAME_ID,
                    seat=seat,
                    assignment_id="v2_roles_pre_exile_repo",
                    player_id=player_id,
                    role="狼人" if is_wolf else "平民",
                    role_key="werewolf" if is_wolf else "villager",
                    team="wolves" if is_wolf else "village",
                )
            )
    fence = RunFence(run_id=RUN_ID, worker_id=WORKER_ID, fence_token=7)
    actions = ActionRepository(factory, enforce_execution_fence=True)
    pipelines = PreExilePipelineRepository(factory)
    matches = MatchRepository(factory, enforce_execution_fence=True)
    public_skip_record_seq: int | None = None
    with bind_run_fence(fence):
        if technical_skip:
            public_skip_record_seq = actions.append_event(
                game_id=GAME_ID,
                event_type="action_skipped_technical",
                audience="all",
                payload={
                    "action_id": "v2_action_failed_last_speech",
                    "phase_id": PHASE_ID,
                    "round_no": 1,
                    "action_type": "day_debate_speech",
                    "actor_id": "villager_4",
                    "player_seat": 4,
                    "reason": "technical_failure",
                },
            )
        claim = actions.claim_action(
            game_id=GAME_ID,
            action_id=PREDECESSOR_ACTION_ID,
            context=(
                _technical_skip_context(public_skip_record_seq)
                if public_skip_record_seq is not None
                else _speech_context()
            ),
            expected_phase_id=PHASE_ID,
            expected_phase_state=PHASE_STATE,
            audience="all",
            context_audience="all" if technical_skip else "player_private",
        )
    assert claim is not None
    predecessor = actions.open_presentation(
        claim=claim,
        presentation_id=PREDECESSOR_PRESENTATION_ID,
        speech_id="v2_speech_pre_exile_last",
        voice_asset_id=None,
        subtitle_text=(
            "4号本轮因技术原因未能完成发言，流程继续。"
            if technical_skip
            else "4号完成本轮最后发言。"
        ),
        sample_rate=24_000,
        actor_kind="judge" if technical_skip else "player",
        actor_id="judge" if technical_skip else "villager_4",
    )
    with factory() as db:
        game = db.get(GameRecord, GAME_ID)
        sealed = db.scalar(
            select(GameRecordEvent).where(
                GameRecordEvent.game_id == GAME_ID,
                GameRecordEvent.event_type == "speech_sealed",
                GameRecordEvent.payload["action_id"].as_string() == PREDECESSOR_ACTION_ID,
            )
        )
        assert game is not None and sealed is not None
        cutoff = game.last_record_seq
        sealed_seq = sealed.record_seq
    with bind_run_fence(fence):
        frozen = matches.snapshot_for_pre_exile_pipeline(
            game_id=GAME_ID,
            run_id=RUN_ID,
            phase_id=PHASE_ID,
            phase_state=PHASE_STATE,
            predecessor_presentation_id=PREDECESSOR_PRESENTATION_ID,
            predecessor_action_id=PREDECESSOR_ACTION_ID,
            predecessor_source_event_id=int(predecessor.source_event_id or 0),
            predecessor_turn_player_id=("villager_4" if technical_skip else None),
        )
    public_history = tuple(dict(item) for item in frozen.match_snapshot.public_history)
    pipeline = pipelines.reserve_pipeline(
        game_id=GAME_ID,
        phase_id=PHASE_ID,
        round_no=1,
        predecessor_action_id=PREDECESSOR_ACTION_ID,
        predecessor_presentation_id=PREDECESSOR_PRESENTATION_ID,
        predecessor_source_event_id=int(predecessor.source_event_id or 0),
        predecessor_source_record_seq=int(predecessor.source_record_seq or 0),
        predecessor_sealed_record_seq=sealed_seq,
        public_cutoff_record_seq=cutoff,
        public_history_sha256=pre_exile_context_sha256(list(public_history)),
        fence=fence,
    )
    return engine, _Harness(
        factory=factory,
        actions=actions,
        pipelines=pipelines,
        matches=matches,
        fence=fence,
        predecessor=predecessor,
        pipeline=pipeline,
        public_history=public_history,
        public_skip_record_seq=public_skip_record_seq,
    )


def _reserve_again(harness: _Harness) -> PreExilePipelineSnapshot:
    return harness.pipelines.reserve_pipeline(
        game_id=GAME_ID,
        phase_id=PHASE_ID,
        round_no=1,
        predecessor_action_id=PREDECESSOR_ACTION_ID,
        predecessor_presentation_id=PREDECESSOR_PRESENTATION_ID,
        predecessor_source_event_id=int(harness.predecessor.source_event_id or 0),
        predecessor_source_record_seq=int(harness.predecessor.source_record_seq or 0),
        predecessor_sealed_record_seq=harness.pipeline.predecessor_sealed_record_seq,
        public_cutoff_record_seq=harness.pipeline.public_cutoff_record_seq,
        public_history_sha256=harness.pipeline.public_history_sha256,
        fence=harness.fence,
    )


def _speech_context() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "action_id": PREDECESSOR_ACTION_ID,
        "action_type": "day_debate_speech",
        "game_id": GAME_ID,
        "phase_id": PHASE_ID,
        "actor": {"kind": "player", "id": "villager_4"},
        "objective": "发表本轮最后一段公开发言。",
        "output_contract": {"kind": "speech"},
        "speech_round": 1,
        "speech_order": list(PLAYERS),
    }


def _technical_skip_context(public_skip_record_seq: int) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "action_id": PREDECESSOR_ACTION_ID,
        "action_type": "judge_day_speech_technical_skip",
        "game_id": GAME_ID,
        "phase_id": PHASE_ID,
        "actor": {"kind": "judge", "id": "judge"},
        "objective": "说明4号本轮技术跳过。",
        "output_contract": {"kind": "speech"},
        "round_no": 1,
        "player_seat": 4,
        "skipped_player_id": "villager_4",
        "speech_round": 1,
        "speech_order": list(PLAYERS),
        "public_skip_record_seq": public_skip_record_seq,
    }


def _initial_context(
    harness: _Harness,
    *,
    action_id: str,
    actor_id: str,
    result_kind: str,
    self_explosion_retry: bool = True,
) -> dict[str, Any]:
    action_type = "werewolf_self_explosion" if result_kind == "self_explosion" else "exile_vote"
    return {
        "schema_version": 1,
        "action_id": action_id,
        "action_type": action_type,
        "game_id": GAME_ID,
        "phase_id": PHASE_ID,
        "actor": {"kind": "player", "id": actor_id},
        "objective": "作出私密决策。",
        "output_contract": (
            {"kind": "boolean", "field": "explode"}
            if result_kind == "self_explosion"
            else {"kind": "target", "target_policy": {"mode": "required"}}
        ),
        "candidates": [
            {"player_id": player_id, "seat": seat}
            for seat, player_id in enumerate(PLAYERS, start=1)
            if player_id != actor_id
        ],
        "batch_id": harness.batch_id,
        "public_history_cutoff_record_seq": harness.pipeline.public_cutoff_record_seq,
        "public_history": [dict(item) for item in harness.public_history],
        "private_authoritative_facts": _private_facts_for_action(
            harness,
            actor_id=actor_id,
            result_kind=result_kind,
        ),
        "pipeline": {
            "kind": "pre_exile",
            "pipeline_id": harness.pipeline.pipeline_id,
            "result_kind": result_kind,
            "stage": "generation",
            "model_admission_mode": ("normal" if result_kind == "self_explosion" else "idle_only"),
            **(
                {
                    "retry_mode": "empty_stream_once_while_predecessor_active",
                    "empty_stream_max_attempts": 2,
                }
                if result_kind == "self_explosion" and self_explosion_retry
                else {}
            ),
        },
    }


def _claim_initial(
    harness: _Harness,
    *,
    actor_id: str,
    result_kind: str,
    action_id: str,
    self_explosion_retry: bool = True,
) -> ActionClaim:
    with bind_run_fence(harness.fence):
        claim = harness.actions.claim_action(
            game_id=GAME_ID,
            action_id=action_id,
            context=_initial_context(
                harness,
                action_id=action_id,
                actor_id=actor_id,
                result_kind=result_kind,
                self_explosion_retry=self_explosion_retry,
            ),
            expected_phase_id=PHASE_ID,
            expected_phase_state=PHASE_STATE,
            audience="god_view",
            context_audience="god_view",
            non_blocking=True,
        )
    assert claim is not None
    return claim


def _complete_success(
    harness: _Harness,
    *,
    claim: ActionClaim,
    parsed_output: dict[str, Any],
) -> None:
    with bind_run_fence(harness.fence):
        harness.actions.append_event(
            game_id=GAME_ID,
            event_type="model_response_received",
            audience="god_view",
            payload={
                "action_id": claim.action_id,
                "attempt_id": f"v2_attempt_{claim.action_id[-16:]}",
                "application_validation_result": "accepted",
                "parsed_output": parsed_output,
            },
        )
        harness.actions.complete_silent_action(
            claim=claim,
            next_live_state="ready",
            next_phase_state=PHASE_STATE,
        )


def _record_self_result(
    harness: _Harness,
    *,
    actor_id: str,
    explode: bool = False,
    technical_false: bool = False,
) -> Any:
    harness.pipelines.reserve_result(
        pipeline_id=harness.pipeline.pipeline_id,
        actor_player_id=actor_id,
        result_kind="self_explosion",
        fence=harness.fence,
    )
    action_id = f"v2_action_self_{actor_id}"
    claim = _claim_initial(
        harness,
        actor_id=actor_id,
        result_kind="self_explosion",
        action_id=action_id,
    )
    if technical_false:
        with bind_run_fence(harness.fence):
            technical_seq = harness.actions.append_event(
                game_id=GAME_ID,
                event_type="technical_fallback_applied",
                audience="god_view",
                payload={
                    "action_id": action_id,
                    "attempt_id": f"v2_attempt_technical_{actor_id}",
                    "technical_outcome": "false",
                    "failure_code": "model_action_wall_timeout",
                },
            )
            harness.actions.complete_silent_action(
                claim=claim,
                next_live_state="ready",
                next_phase_state=PHASE_STATE,
                failure_episode_id=f"v2_failure_{actor_id}",
                technical_outcome_record_seq=technical_seq,
            )
        return harness.pipelines.record_result(
            pipeline_id=harness.pipeline.pipeline_id,
            actor_player_id=actor_id,
            result_kind="self_explosion",
            action_id=action_id,
            technical_outcome_record_seq=technical_seq,
            fence=harness.fence,
        )
    _complete_success(
        harness,
        claim=claim,
        parsed_output={"explode": explode, "decision_note": None},
    )
    return harness.pipelines.record_result(
        pipeline_id=harness.pipeline.pipeline_id,
        actor_player_id=actor_id,
        result_kind="self_explosion",
        action_id=action_id,
        fence=harness.fence,
    )


def _record_vote_success(
    harness: _Harness,
    *,
    actor_id: str,
    target_id: str,
) -> Any:
    harness.pipelines.reserve_result(
        pipeline_id=harness.pipeline.pipeline_id,
        actor_player_id=actor_id,
        result_kind="exile_vote",
        fence=harness.fence,
    )
    action_id = f"v2_action_vote_{actor_id}"
    claim = _claim_initial(
        harness,
        actor_id=actor_id,
        result_kind="exile_vote",
        action_id=action_id,
    )
    _complete_success(
        harness,
        claim=claim,
        parsed_output={"target_player_id": target_id, "decision_note": None},
    )
    return harness.pipelines.record_result(
        pipeline_id=harness.pipeline.pipeline_id,
        actor_player_id=actor_id,
        result_kind="exile_vote",
        action_id=action_id,
        fence=harness.fence,
    )


def _record_open_vote_attempt(
    harness: _Harness,
    *,
    actor_id: str,
) -> ActionClaim:
    harness.pipelines.reserve_result(
        pipeline_id=harness.pipeline.pipeline_id,
        actor_player_id=actor_id,
        result_kind="exile_vote",
        fence=harness.fence,
    )
    action_id = f"v2_action_open_vote_{actor_id}"
    claim = _claim_initial(
        harness,
        actor_id=actor_id,
        result_kind="exile_vote",
        action_id=action_id,
    )
    with bind_run_fence(harness.fence):
        harness.actions.append_event(
            game_id=GAME_ID,
            event_type="model_request_started",
            audience="god_view",
            payload={
                "action_id": action_id,
                "attempt_id": f"v2_attempt_open_{actor_id}",
                "attempt_no": 1,
                "cycle_attempt_no": 1,
                "retry_cycle": 1,
                "max_attempts": 1,
            },
        )
    return claim


def _record_capacity_failure(
    harness: _Harness,
    *,
    actor_id: str,
    admission_event_type: str | None = None,
) -> Any:
    harness.pipelines.reserve_result(
        pipeline_id=harness.pipeline.pipeline_id,
        actor_player_id=actor_id,
        result_kind="exile_vote",
        fence=harness.fence,
    )
    action_id = f"v2_action_capacity_{actor_id}"
    claim = _claim_initial(
        harness,
        actor_id=actor_id,
        result_kind="exile_vote",
        action_id=action_id,
    )
    with bind_run_fence(harness.fence):
        if admission_event_type is not None:
            harness.actions.append_event(
                game_id=GAME_ID,
                event_type=admission_event_type,
                audience="god_view",
                payload={
                    "action_id": action_id,
                    "attempt_id": f"v2_attempt_capacity_{actor_id}",
                },
            )
        harness.actions.append_event(
            game_id=GAME_ID,
            event_type="model_request_failed",
            audience="god_view",
            payload={
                "action_id": action_id,
                "attempt_id": f"v2_attempt_capacity_{actor_id}",
                "attempt_no": 1,
                "cycle_attempt_no": 1,
                "retry_cycle": 1,
                "max_attempts": 1,
                "failure_kind": "technical",
                "failure_code": "model_prefetch_capacity_unavailable",
                "failure_category": "admission_capacity",
                "failure_stage": "provider_admission",
                "retryable": False,
                "attempt_terminal": True,
                "action_recoverable": False,
                "run_terminal": False,
                "terminal": True,
                "automatic_retry_scheduled": False,
            },
        )
        failed_seq = harness.actions.fail_action(
            claim=claim,
            failure_kind="technical",
            failure_code="model_prefetch_capacity_unavailable",
            identity=None,
        )
    return harness.pipelines.record_failure(
        pipeline_id=harness.pipeline.pipeline_id,
        actor_player_id=actor_id,
        result_kind="exile_vote",
        action_id=action_id,
        failure_record_seq=failed_seq,
        fence=harness.fence,
    )


def _claim_recovery(
    harness: _Harness,
    *,
    actor_id: str,
    source_row: Any,
) -> ActionClaim:
    action_id = f"v2_action_recovery_{actor_id}"
    context = {
        "schema_version": 1,
        "action_id": action_id,
        "action_type": "exile_vote",
        "game_id": GAME_ID,
        "phase_id": PHASE_ID,
        "actor": {"kind": "player", "id": actor_id},
        "objective": "恢复一次容量拒绝前未触达Provider的投票。",
        "output_contract": {"kind": "target", "target_policy": {"mode": "required"}},
        "candidates": [
            {"player_id": player_id, "seat": seat}
            for seat, player_id in enumerate(PLAYERS, start=1)
            if player_id != actor_id
        ],
        "batch_id": harness.batch_id,
        "public_history_cutoff_record_seq": harness.pipeline.public_cutoff_record_seq,
        "public_history": [dict(item) for item in harness.public_history],
        "private_authoritative_facts": _private_facts_for_action(
            harness,
            actor_id=actor_id,
            result_kind="exile_vote",
        ),
        "pre_exile_recovery": {
            "pipeline_id": harness.pipeline.pipeline_id,
            "result_id": source_row.result_id,
            "source_action_id": source_row.action_id,
            "model_admission_mode": "normal",
        },
    }
    with bind_run_fence(harness.fence):
        claim = harness.actions.claim_action(
            game_id=GAME_ID,
            action_id=action_id,
            context=context,
            expected_phase_id=PHASE_ID,
            expected_phase_state=PHASE_STATE,
            audience="god_view",
            context_audience="god_view",
            non_blocking=True,
        )
    assert claim is not None and claim.non_blocking
    return claim


def _private_facts_for_action(
    harness: _Harness,
    *,
    actor_id: str,
    result_kind: str,
) -> list[dict[str, Any]]:
    facts = [
        fact
        for fact in harness.matches.private_knowledge(
            game_id=GAME_ID,
            player_id=actor_id,
        )
        if type(fact.get("known_at_seq")) is int
        and fact["known_at_seq"] <= harness.pipeline.public_cutoff_record_seq
    ]
    if actor_id.startswith("wolf_") and result_kind == "exile_vote":
        self_result = next(
            (
                row
                for row in harness.pipelines.list_results(harness.pipeline.pipeline_id)
                if row.actor_player_id == actor_id and row.result_kind == "self_explosion"
            ),
            None,
        )
        if self_result is not None and self_result.private_fact_id is not None:
            facts.append(
                harness.pipelines.get_provisional_self_explosion_fact(
                    pipeline_id=harness.pipeline.pipeline_id,
                    actor_player_id=actor_id,
                    private_fact_id=self_result.private_fact_id,
                    fence=harness.fence,
                )
            )
    if actor_id.startswith("wolf_"):
        facts.append(
            {
                "fact_type": "living_werewolf_teammates",
                "payload": [player_id for player_id in WOLVES if player_id != actor_id],
                "owner_scope": "player",
                "owner_id": actor_id,
            }
        )
    return facts


def _resolution_payload(
    harness: _Harness,
    *,
    votes: tuple[DayVoteCommit, ...],
) -> dict[str, Any]:
    totals: dict[str, float] = {}
    weights: dict[str, float] = {}
    for vote in votes:
        assert vote.target_player_id is not None
        weights[vote.voter_player_id] = vote.weight
        totals[vote.target_player_id] = totals.get(vote.target_player_id, 0.0) + vote.weight
    highest = max(totals.values())
    return {
        "round_no": 1,
        "action_type": "exile_vote",
        "batch_id": harness.batch_id,
        "public_cutoff_record_seq": harness.pipeline.public_cutoff_record_seq,
        "eligible_voter_ids": [vote.voter_player_id for vote in votes],
        "candidate_player_ids": list(PLAYERS),
        "voter_weights": weights,
        "totals": totals,
        "leaders": sorted(player_id for player_id, total in totals.items() if total == highest),
        "technical_abstentions": [],
    }
