from __future__ import annotations

import asyncio
from dataclasses import replace
from types import SimpleNamespace
from typing import Any

import pytest

from app.v2.action_engine import (
    V2ActionFailure,
    V2ActionResult,
    V2SpeechSpec,
    _action_context,
)
from app.v2.day_speech_pipeline_contract import resolve_day_speech_pipeline_contract
from app.v2.day_engine import (
    _PreExileLaunch,
    V2DayEngine,
    V2DayRuntimeError,
    _pre_exile_wolf_vote_private_facts,
    _private_fact_visible_at_public_cutoff,
)
from app.v2.match_repository import (
    V2MatchPlayer,
    V2MatchSnapshot,
    V2PreExileExplosionCommit,
    V2PreExilePrefetchSnapshot,
)
from app.v2.model_client import V2ModelDecision
from app.v2.model_context import project_model_action_context
from app.v2.model_context_compaction import expand_known_events_v6
from app.v2.model_context_contract import current_model_context_contract
from app.v2.pre_exile_pipeline_contract import (
    freeze_pre_exile_pipeline_contract,
    resolve_pre_exile_pipeline_contract,
)
from app.v2.repository import V2ExecutionOwnershipLost, V2PresentationIdentity


def _false_explosion_fact(
    *,
    fact_id: str = "v2_fact_wolf_false",
    owner_id: str = "wolf_1",
    pipeline_id: str = "v2_preex_pipeline",
    cutoff: int = 100,
    record_seq: int = 121,
) -> dict[str, Any]:
    return {
        "knowledge_fact_id": fact_id,
        "source_activation_id": None,
        "owner_scope": "player",
        "owner_id": owner_id,
        "fact_type": "private_action_decision",
        "source_event_id": record_seq,
        "source_event_type": "private_knowledge_recorded",
        "record_seq": record_seq,
        "known_at_seq": record_seq,
        "payload": {
            "schema_version": 1,
            "round_no": 1,
            "action_type": "werewolf_self_explosion",
            "decision": {"explode": False},
            "source_action_id": "v2_action_wolf_false",
            "context": {
                "pipeline_id": pipeline_id,
                "public_history_cutoff_record_seq": cutoff,
                "visibility_mode": ("pre_exile_provisional_until_atomic_arbiter"),
            },
        },
    }


@pytest.mark.parametrize(
    ("fact", "visible"),
    [
        ({"known_at_seq": 99, "record_seq": 99}, True),
        ({"known_at_seq": 100, "record_seq": 100}, True),
        ({"known_at_seq": 101, "record_seq": 101}, False),
        ({"record_seq": 99}, True),
        ({"record_seq": 101}, False),
        ({}, False),
        ({"known_at_seq": "99", "record_seq": None}, False),
        ({"known_at_seq": True, "record_seq": None}, False),
    ],
)
def test_pre_exile_private_cutoff_is_fail_closed(
    fact: dict[str, Any],
    visible: bool,
) -> None:
    assert _private_fact_visible_at_public_cutoff(fact, 100) is visible


def test_wolf_vote_private_facts_are_sealed_plus_exact_durable_false_fact() -> None:
    sealed = [
        {
            "knowledge_fact_id": "v2_fact_sealed",
            "owner_scope": "player",
            "owner_id": "wolf_1",
            "fact_type": "private_round_memory",
            "record_seq": 80,
            "known_at_seq": 80,
            "payload": {"memory": "sealed"},
        }
    ]
    post_cutoff_unrelated = {
        "knowledge_fact_id": "v2_fact_unrelated",
        "owner_scope": "player",
        "owner_id": "wolf_1",
        "fact_type": "private_action_decision",
        "record_seq": 120,
        "known_at_seq": 120,
        "payload": {
            "action_type": "exile_vote",
            "decision": {"target_player_id": "player_2"},
        },
    }
    own_false = _false_explosion_fact()

    frozen = _pre_exile_wolf_vote_private_facts(
        base=sealed,
        owner_facts=[post_cutoff_unrelated, own_false],
        owner_player_id="wolf_1",
        pipeline_id="v2_preex_pipeline",
        private_fact_id="v2_fact_wolf_false",
        private_fact_record_seq=121,
        public_cutoff_record_seq=100,
    )

    assert [fact["knowledge_fact_id"] for fact in frozen] == [
        "v2_fact_sealed",
        "v2_fact_wolf_false",
    ]
    assert all(fact["knowledge_fact_id"] != "v2_fact_unrelated" for fact in frozen)
    assert frozen[0] is not sealed[0]


@pytest.mark.parametrize(
    "mutation",
    [
        {"owner_id": "wolf_2"},
        {"source_event_type": "other"},
        {"known_at_seq": 122},
        {"record_seq": 122},
        {"fact_type": "private_round_memory"},
        {"payload.action_type": "exile_vote"},
        {"payload.decision.explode": True},
        {"payload.context.pipeline_id": "other_pipeline"},
        {"payload.context.public_history_cutoff_record_seq": 99},
        {"payload.context.visibility_mode": "committed"},
    ],
)
def test_wolf_vote_rejects_non_authoritative_false_fact(
    mutation: dict[str, Any],
) -> None:
    fact = _false_explosion_fact()
    for dotted_key, value in mutation.items():
        target: dict[str, Any] = fact
        parts = dotted_key.split(".")
        for part in parts[:-1]:
            target = target[part]
        target[parts[-1]] = value

    with pytest.raises(
        V2DayRuntimeError,
        match="pre_exile_wolf_false_private_fact_invalid",
    ):
        _pre_exile_wolf_vote_private_facts(
            base=[],
            owner_facts=[fact],
            owner_player_id="wolf_1",
            pipeline_id="v2_preex_pipeline",
            private_fact_id="v2_fact_wolf_false",
            private_fact_record_seq=121,
            public_cutoff_record_seq=100,
        )


def test_wolf_vote_rejects_false_fact_without_post_cutoff_durable_clock() -> None:
    with pytest.raises(
        V2DayRuntimeError,
        match="pre_exile_wolf_false_private_fact_missing",
    ):
        _pre_exile_wolf_vote_private_facts(
            base=[],
            owner_facts=[_false_explosion_fact(record_seq=100)],
            owner_player_id="wolf_1",
            pipeline_id="v2_preex_pipeline",
            private_fact_id="v2_fact_wolf_false",
            private_fact_record_seq=100,
            public_cutoff_record_seq=100,
        )


class _Broadcaster:
    def __init__(self) -> None:
        self.messages: list[dict[str, Any]] = []

    async def broadcast_json(
        self,
        value: dict[str, Any],
        *,
        audience: str = "all",
    ) -> None:
        self.messages.append({**value, "_audience": audience})


class _VoteRepository:
    def __init__(self, state: V2MatchSnapshot) -> None:
        self.state = state
        self.events: list[dict[str, Any]] = []
        self.finalize_calls: list[dict[str, Any]] = []

    def snapshot(self, game_id: str) -> V2MatchSnapshot:
        assert game_id == self.state.game_id
        return self.state

    def private_knowledge(
        self,
        *,
        game_id: str,
        player_id: str,
    ) -> list[dict[str, Any]]:
        assert game_id == self.state.game_id and player_id
        return []

    def append_event(self, **kwargs: Any) -> int:
        self.events.append(dict(kwargs))
        return self.state.last_record_seq + len(self.events)

    def finalize_day_vote_batch(self, **kwargs: Any) -> None:
        self.finalize_calls.append(dict(kwargs))


class _VoteActions:
    def __init__(self, expected_concurrency: int = 0) -> None:
        self.expected_concurrency = expected_concurrency
        self.active = 0
        self.max_active = 0
        self.release = asyncio.Event()
        self.specs: list[V2SpeechSpec] = []
        self._seq = 200

    def check_cancellation(self, _game_id: str) -> None:
        return

    async def run_player_decision_result(
        self,
        *,
        game_id: str,
        broadcaster: Any,
        spec: V2SpeechSpec,
        **_kwargs: Any,
    ) -> V2ActionResult:
        del game_id, broadcaster
        self.specs.append(spec)
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        if self.active >= self.expected_concurrency:
            self.release.set()
        await self.release.wait()
        await asyncio.sleep(0)
        self.active -= 1
        self._seq += 2
        assert spec.allowed_target_ids
        return V2ActionResult(
            action_id=f"v2_action_recovery_{spec.actor_id}",
            decision=_vote_decision(spec.allowed_target_ids[0]),
            model_response_record_seq=self._seq - 1,
            terminal_event_record_seq=self._seq,
        )


class _PreExileRows:
    def __init__(self, rows: list[Any]) -> None:
        self.rows = rows
        self.adopt_calls: list[dict[str, Any]] = []

    def list_results(self, pipeline_id: str) -> tuple[Any, ...]:
        assert pipeline_id == "v2_preex_pipeline"
        return tuple(self.rows)

    def adopt_vote_recovery_result(self, **kwargs: Any) -> Any:
        self.adopt_calls.append(dict(kwargs))
        return SimpleNamespace(action_id=kwargs["source_action_id"])


def _player(player_id: str, seat: int, *, role_key: str = "villager") -> V2MatchPlayer:
    return V2MatchPlayer(
        player_id=player_id,
        seat=seat,
        display_name=f"{seat}号玩家",
        role_key=role_key,
        team="werewolves" if role_key == "werewolf" else "villagers",
        alive=True,
        tts_speaker=None,
        tts_dialect=None,
        model_provider="agent_plan",
        model_id="test-model",
        model_supports_thinking=True,
        model_parameters={"thinking": {"type": "enabled"}},
        persona={},
        state={"can_vote": True},
    )


def _vote_snapshot() -> V2MatchSnapshot:
    players = tuple(_player(f"player_{seat}", seat) for seat in range(1, 4))
    return V2MatchSnapshot(
        game_id="v2_game_pre_exile",
        run_id="v2_run_pre_exile",
        last_record_seq=100,
        phase_id="day_1",
        phase_state="public_discussion_open",
        round_no=1,
        sheriff_player_id=None,
        sheriff_badge_state="disabled",
        pre_sheriff_explosion_count=0,
        rule={
            "id": "pre-exile-test",
            "speech_rounds": 1,
            "sheriff_enabled": False,
            "sheriff_vote_weight": 1,
            "werewolf_self_explosion_enabled": True,
            "day_actions": ["debate", "vote"],
            "ability_policies": {},
        },
        max_rounds=8,
        model_context_contract=current_model_context_contract(),
        model_generation_policy_contract=None,
        day_speech_pipeline_contract=resolve_day_speech_pipeline_contract({}),
        pre_exile_pipeline_contract=resolve_pre_exile_pipeline_contract(
            freeze_pre_exile_pipeline_contract({})
        ),
        audio_mode="tts",
        players=players,
        public_history=(),
    )


def _vote_decision(target_player_id: str) -> V2ModelDecision:
    return V2ModelDecision(
        target_player_id=target_player_id,
        speech=None,
        provider_request_id=f"request:{target_player_id}",
        first_token_ms=1,
        completed_ms=2,
    )


def _vote_row(
    player_id: str,
    *,
    action_id: str,
    failure: dict[str, Any] | None = None,
) -> Any:
    return SimpleNamespace(
        result_id=f"v2_prexr_{player_id}",
        actor_player_id=player_id,
        result_kind="exile_vote",
        action_id=action_id,
        failure=failure,
    )


def _capacity_failure(action_id: str) -> dict[str, Any]:
    return {
        "model_request_failed": {
            "action_id": action_id,
            "failure_code": "model_prefetch_capacity_unavailable",
            "failure_category": "admission_capacity",
            "failure_stage": "provider_admission",
        }
    }


def test_all_false_pre_exile_votes_finalize_atomically_once() -> None:
    state = _vote_snapshot()
    repository = _VoteRepository(state)
    rows = _PreExileRows(
        [
            _vote_row(player.player_id, action_id=f"v2_action_{player.player_id}")
            for player in state.players
        ]
    )
    actions = _VoteActions()
    engine = V2DayEngine(
        repository=repository,  # type: ignore[arg-type]
        action_engine=actions,  # type: ignore[arg-type]
        pre_exile_pipeline_repository=rows,  # type: ignore[arg-type]
    )
    initial = {
        "player_1": V2ActionResult(
            action_id="v2_action_player_1",
            decision=_vote_decision("player_2"),
        ),
        "player_2": V2ActionResult(
            action_id="v2_action_player_2",
            decision=_vote_decision("player_3"),
        ),
        "player_3": V2ActionResult(
            action_id="v2_action_player_3",
            decision=_vote_decision("player_1"),
        ),
    }

    totals = asyncio.run(
        engine._collect_votes(
            game_id=state.game_id,
            broadcaster=_Broadcaster(),
            action_type="exile_vote",
            voters=list(state.players),
            candidates=list(state.players),
            weighted=True,
            context={"vote_round": 1},
            pre_exile_pipeline_id="v2_preex_pipeline",
            frozen_state=state,
            frozen_private_facts_by_voter={player.player_id: [] for player in state.players},
            initial_results_by_voter=initial,
            public_history_cutoff_record_seq=100,
        )
    )

    assert totals == {"player_1": 1.0, "player_2": 1.0, "player_3": 1.0}
    assert len(repository.finalize_calls) == 1
    assert repository.finalize_calls[0]["pre_exile_pipeline_id"] == "v2_preex_pipeline"
    assert rows.adopt_calls == []
    assert actions.specs == []


def test_multiple_idle_capacity_failures_recover_concurrently_once() -> None:
    state = _vote_snapshot()
    repository = _VoteRepository(state)
    failed_ids = {"player_1", "player_2"}
    rows = _PreExileRows(
        [
            _vote_row(
                player.player_id,
                action_id=f"v2_action_idle_{player.player_id}",
                failure=(
                    _capacity_failure(f"v2_action_idle_{player.player_id}")
                    if player.player_id in failed_ids
                    else None
                ),
            )
            for player in state.players
        ]
    )
    actions = _VoteActions(expected_concurrency=2)
    engine = V2DayEngine(
        repository=repository,  # type: ignore[arg-type]
        action_engine=actions,  # type: ignore[arg-type]
        pre_exile_pipeline_repository=rows,  # type: ignore[arg-type]
    )
    initial = {
        player.player_id: (
            V2ActionResult(
                action_id=f"v2_action_idle_{player.player_id}",
                failure=V2ActionFailure(
                    code="model_prefetch_capacity_unavailable",
                    category="admission_capacity",
                    terminal_attempt_id="v2_attempt_idle_capacity",
                ),
                terminal_event_record_seq=150 + player.seat,
            )
            if player.player_id in failed_ids
            else V2ActionResult(
                action_id=f"v2_action_idle_{player.player_id}",
                decision=_vote_decision("player_1"),
            )
        )
        for player in state.players
    }

    asyncio.run(
        engine._collect_votes(
            game_id=state.game_id,
            broadcaster=_Broadcaster(),
            action_type="exile_vote",
            voters=list(state.players),
            candidates=list(state.players),
            weighted=True,
            context={"vote_round": 1},
            pre_exile_pipeline_id="v2_preex_pipeline",
            frozen_state=state,
            frozen_private_facts_by_voter={player.player_id: [] for player in state.players},
            initial_results_by_voter=initial,
            public_history_cutoff_record_seq=100,
        )
    )

    assert actions.max_active == 2
    assert len(actions.specs) == 2
    assert len(rows.adopt_calls) == 2
    assert len(repository.finalize_calls) == 1
    for spec in actions.specs:
        assert spec.model_admission_mode == "normal"
        assert spec.defer_presentation is True
        assert spec.isolated_failure is True
        assert spec.pipeline_kind is None
        assert spec.projection_at_seq is None
        assert spec.audience == "god_view"
        assert spec.context is not None
        recovery = spec.context["pre_exile_recovery"]
        assert recovery == {
            "pipeline_id": "v2_preex_pipeline",
            "result_id": f"v2_prexr_{spec.actor_id}",
            "source_action_id": f"v2_action_idle_{spec.actor_id}",
            "model_admission_mode": "normal",
        }
        assert spec.context["public_history_cutoff_record_seq"] == 100


class _GenerationRepository(_VoteRepository):
    def __init__(self, state: V2MatchSnapshot) -> None:
        super().__init__(state)
        self.private_facts: dict[str, list[dict[str, Any]]] = {}
        self.resolve_calls: list[dict[str, Any]] = []

    def private_knowledge(
        self,
        *,
        game_id: str,
        player_id: str,
    ) -> list[dict[str, Any]]:
        assert game_id == self.state.game_id
        return list(self.private_facts.get(player_id, ()))

    def resolve_pre_exile_self_explosions(
        self,
        **kwargs: Any,
    ) -> V2PreExileExplosionCommit:
        self.resolve_calls.append(dict(kwargs))
        return V2PreExileExplosionCommit(
            outcome="explosion_selected",
            selected_player_id="wolf_2",
            failed_player_ids=(),
        )


class _GenerationPipeline:
    def __init__(self, repository: _GenerationRepository) -> None:
        self.repository = repository
        self.rows: dict[tuple[str, str], Any] = {}
        self.action_results: dict[str, V2ActionResult] = {}
        self.vote_recorded_count = 0
        self.self_recorded_count = 0
        self.vote_rows_ready = asyncio.Event()
        self.self_rows_ready = asyncio.Event()

    def reserve_result(self, **kwargs: Any) -> Any:
        key = (kwargs["result_kind"], kwargs["actor_player_id"])
        row = SimpleNamespace(
            result_id=f"v2_prexr_{key[0]}_{key[1]}",
            actor_player_id=key[1],
            result_kind=key[0],
            state="reserved",
            action_id=None,
            decision=None,
            failure=None,
            private_fact_id=None,
            private_fact_record_seq=None,
        )
        self.rows[key] = row
        return row

    def record_result(self, **kwargs: Any) -> Any:
        key = (kwargs["result_kind"], kwargs["actor_player_id"])
        row = self.rows[key]
        result = self.action_results[kwargs["action_id"]]
        decision = result.decision
        assert decision is not None
        row.state = "ready"
        row.action_id = kwargs["action_id"]
        row.decision = (
            {"explode": decision.boolean_value, "decision_note": decision.decision_note}
            if key[0] == "self_explosion"
            else {
                "target_player_id": decision.target_player_id,
                "decision_note": decision.decision_note,
            }
        )
        if key[0] == "self_explosion":
            self.self_recorded_count += 1
            if decision.boolean_value is False:
                row.private_fact_id = f"v2_fact_{key[1]}_false"
                row.private_fact_record_seq = 130 + self.self_recorded_count
                self.repository.private_facts[key[1]] = [
                    _false_explosion_fact(
                        fact_id=row.private_fact_id,
                        owner_id=key[1],
                        pipeline_id="v2_preex_pipeline",
                        cutoff=100,
                        record_seq=row.private_fact_record_seq,
                    ),
                    {
                        "knowledge_fact_id": "v2_fact_post_cutoff_unrelated",
                        "owner_scope": "player",
                        "owner_id": key[1],
                        "fact_type": "private_action_decision",
                        "source_event_type": "private_knowledge_recorded",
                        "record_seq": row.private_fact_record_seq + 1,
                        "known_at_seq": row.private_fact_record_seq + 1,
                        "payload": {
                            "action_type": "exile_vote",
                            "decision": {"target_player_id": "villager_3"},
                        },
                    },
                ]
            if self.self_recorded_count == 2:
                self.self_rows_ready.set()
        else:
            self.vote_recorded_count += 1
            if self.vote_recorded_count == 3:
                self.vote_rows_ready.set()
        return row

    def get_provisional_self_explosion_fact(self, **kwargs: Any) -> dict[str, Any]:
        facts = self.repository.private_facts[kwargs["actor_player_id"]]
        return next(
            fact for fact in facts if fact.get("knowledge_fact_id") == kwargs["private_fact_id"]
        )


class _GenerationActions:
    def __init__(self, pipeline: _GenerationPipeline) -> None:
        self.pipeline = pipeline
        self.specs: list[V2SpeechSpec] = []
        self.start_order: list[tuple[str, str, str]] = []
        self._seq = 300

    def check_cancellation(self, _game_id: str) -> None:
        return

    async def run_player_decision_result(
        self,
        *,
        game_id: str,
        broadcaster: Any,
        spec: V2SpeechSpec,
        on_model_admission_pending: Any = None,
        **_kwargs: Any,
    ) -> V2ActionResult:
        del game_id, broadcaster
        self.specs.append(spec)
        self.start_order.append(
            (str(spec.pipeline_result_kind), spec.model_admission_mode, spec.actor_id)
        )
        if on_model_admission_pending is not None:
            on_model_admission_pending()
        if spec.pipeline_result_kind == "self_explosion" and spec.actor_id == "wolf_2":
            await self.pipeline.vote_rows_ready.wait()
        else:
            await asyncio.sleep(0)
        self._seq += 2
        action_id = f"v2_action_{spec.pipeline_result_kind}_{spec.actor_id}"
        if spec.pipeline_result_kind == "self_explosion":
            decision = V2ModelDecision(
                target_player_id=None,
                speech=None,
                provider_request_id=f"request:{spec.actor_id}",
                first_token_ms=1,
                completed_ms=2,
                boolean_field="explode",
                boolean_value=spec.actor_id == "wolf_2",
            )
        else:
            assert spec.allowed_target_ids
            decision = _vote_decision(spec.allowed_target_ids[0])
        result = V2ActionResult(
            action_id=action_id,
            decision=decision,
            model_response_record_seq=self._seq - 1,
            terminal_event_record_seq=self._seq,
        )
        self.pipeline.action_results[action_id] = result
        return result


def _generation_snapshot() -> V2MatchSnapshot:
    state = _vote_snapshot()
    return replace(
        state,
        players=(
            _player("wolf_1", 1, role_key="werewolf"),
            _player("wolf_2", 2, role_key="werewolf"),
            _player("villager_3", 3),
            _player("villager_4", 4),
        ),
    )


def test_votes_finishing_before_true_explosion_never_commit_and_normal_waiters_lead() -> None:
    async def scenario() -> tuple[
        Any, _GenerationRepository, _GenerationPipeline, _GenerationActions
    ]:
        state = _generation_snapshot()
        repository = _GenerationRepository(state)
        pipeline_repository = _GenerationPipeline(repository)
        actions = _GenerationActions(pipeline_repository)
        engine = V2DayEngine(
            repository=repository,  # type: ignore[arg-type]
            action_engine=actions,  # type: ignore[arg-type]
            pre_exile_pipeline_repository=pipeline_repository,  # type: ignore[arg-type]
        )
        predecessor_committed = asyncio.Event()
        launch = _PreExileLaunch(
            presentation_closed=asyncio.Event(),
            predecessor_committed=predecessor_committed,
            pipeline=SimpleNamespace(pipeline_id="v2_preex_pipeline"),
            frozen=V2PreExilePrefetchSnapshot(
                match_snapshot=state,
                public_cutoff_record_seq=100,
                predecessor_presentation_id="v2_pres_last",
                predecessor_action_id="v2_action_last_speech",
                predecessor_source_event_id=90,
                predecessor_source_record_seq=90,
                predecessor_sealed_record_seq=100,
                predecessor_actor_id="villager_4",
            ),
            run_fence=None,
        )
        task = asyncio.create_task(
            engine._generate_pre_exile_pipeline(
                launch=launch,
                sealed_private_facts={
                    player.player_id: (
                        [
                            {
                                "knowledge_fact_id": "v2_fact_sealed_wolf_1",
                                "owner_scope": "player",
                                "owner_id": "wolf_1",
                                "fact_type": "private_round_memory",
                                "record_seq": 80,
                                "known_at_seq": 80,
                                "payload": {"round_no": 1, "memory": "sealed"},
                            }
                        ]
                        if player.player_id == "wolf_1"
                        else []
                    )
                    for player in state.players
                },
                broadcaster=_Broadcaster(),
            )
        )
        await pipeline_repository.vote_rows_ready.wait()
        await pipeline_repository.self_rows_ready.wait()
        await asyncio.sleep(0)
        assert repository.resolve_calls == []
        assert repository.finalize_calls == []
        assert not task.done()
        predecessor_committed.set()
        outcome = await task
        return outcome, repository, pipeline_repository, actions

    outcome, repository, pipeline_repository, actions = asyncio.run(scenario())

    assert outcome.selected_explosion_player_id == "wolf_2"
    assert outcome.prepared_vote is None
    assert pipeline_repository.vote_recorded_count == 3
    assert len(repository.resolve_calls) == 1
    assert repository.finalize_calls == []
    first_idle_index = next(
        index
        for index, (_kind, admission, _actor) in enumerate(actions.start_order)
        if admission == "idle_only"
    )
    assert actions.start_order[:first_idle_index] == [
        ("self_explosion", "normal", "wolf_1"),
        ("self_explosion", "normal", "wolf_2"),
    ]
    wolf_vote = next(
        spec
        for spec in actions.specs
        if spec.pipeline_result_kind == "exile_vote" and spec.actor_id == "wolf_1"
    )
    assert wolf_vote.context is not None
    private_ids = {
        fact.get("knowledge_fact_id")
        for fact in wolf_vote.context["private_authoritative_facts"]
        if isinstance(fact, dict) and isinstance(fact.get("knowledge_fact_id"), str)
    }
    assert private_ids == {"v2_fact_sealed_wolf_1", "v2_fact_wolf_1_false"}
    assert "v2_fact_post_cutoff_unrelated" not in private_ids
    projected = project_model_action_context(
        _action_context(
            game_id="v2_game_pre_exile",
            action_id="v2_action_project_wolf_vote",
            spec=wolf_vote,
        ),
        players=wolf_vote.model_players,
        model_context_contract=current_model_context_contract(),
        action_record_seq=500,
        projection_at_seq=None,
    )
    known_events = expand_known_events_v6(projected["known_events"])["events"]
    assert {
        event["event_ref"] for event in known_events if event.get("visibility") == "actor_private"
    } >= {"v2_fact_sealed_seat_1", "v2_fact_seat_1_false"}
    false_event = next(
        event for event in known_events if event.get("event_ref") == "v2_fact_seat_1_false"
    )
    assert false_event["known_at_seq"] == 131
    assert false_event["data"]["decision"] == {"explode": False}
    assert "private_judge_facts" not in projected["self"]


class _DiscussionEngine(V2DayEngine):
    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.long_pre_exile_gate = asyncio.Event()

    async def _speech_order(self, **kwargs: Any) -> list[str]:
        state = kwargs["state"]
        return [player.player_id for player in state.players]

    async def _offer_all_wolves_explosion(self, **_kwargs: Any) -> bool:
        return False

    async def _player_action(self, **kwargs: Any) -> V2ModelDecision:
        player = kwargs["player"]
        opened = kwargs.get("on_presentation_opened")
        closed = kwargs.get("on_presentation_closed")
        if opened is not None:
            identity = V2PresentationIdentity(
                game_id=kwargs["game_id"],
                run_id="v2_run_pre_exile",
                action_id=f"v2_action_speech_{player.player_id}",
                phase_id="day_1",
                presentation_seq=player.seat,
                presentation_id=f"v2_pres_{player.player_id}",
                speech_id=f"v2_speech_{player.player_id}",
                segment_index=0,
                voice_asset_id=None,
                storage_key=f"speech/{player.player_id}",
                subtitle_text=f"speech:{player.player_id}",
                audience="all",
                actor_kind="player",
                actor_id=player.player_id,
                source_event_id=80 + player.seat,
                source_record_seq=80 + player.seat,
            )
            opened(identity)
            if closed is not None:
                closed(identity)
        return V2ModelDecision(
            target_player_id=None,
            speech=f"speech:{player.player_id}",
            provider_request_id=f"request:{player.player_id}",
            first_token_ms=1,
            completed_ms=2,
        )

    def _launch_pre_exile_pipeline(self, **kwargs: Any) -> None:
        launch = kwargs["launch"]
        launch.pipeline = SimpleNamespace(pipeline_id="v2_preex_pipeline")
        launch.frozen = SimpleNamespace(match_snapshot=_generation_snapshot())
        launch.task = asyncio.create_task(self.long_pre_exile_gate.wait())


class _InvalidatingPreExileRepository:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def invalidate_pipeline(self, **kwargs: Any) -> None:
        self.calls.append(dict(kwargs))


class _FailingFinalDiscussionEngine(_DiscussionEngine):
    def __init__(self, *, error_type: type[BaseException], **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.error_type = error_type
        self.last_launch: _PreExileLaunch | None = None

    async def _player_action(self, **kwargs: Any) -> V2ModelDecision:
        decision = await super()._player_action(**kwargs)
        if kwargs["player"].player_id == "villager_4":
            raise self.error_type("synthetic final presentation failure")
        return decision

    def _launch_pre_exile_pipeline(self, **kwargs: Any) -> None:
        super()._launch_pre_exile_pipeline(**kwargs)
        self.last_launch = kwargs["launch"]


def test_last_speech_commits_before_long_pre_exile_generation_finishes() -> None:
    async def scenario() -> tuple[_VoteRepository, Any]:
        state = _generation_snapshot()
        repository = _VoteRepository(state)
        engine = _DiscussionEngine(
            repository=repository,  # type: ignore[arg-type]
            action_engine=_VoteActions(),  # type: ignore[arg-type]
            pre_exile_pipeline_repository=SimpleNamespace(),  # type: ignore[arg-type]
        )
        result = await asyncio.wait_for(
            engine._run_public_discussion(
                game_id=state.game_id,
                broadcaster=_Broadcaster(),
            ),
            timeout=0.2,
        )
        launch = result.pre_exile_launch
        assert launch is not None and launch.task is not None
        assert not launch.task.done()
        launch.task.cancel()
        await asyncio.gather(launch.task, return_exceptions=True)
        return repository, result

    repository, result = asyncio.run(scenario())

    assert result.pre_exile_launch is not None
    committed = [
        event for event in repository.events if event.get("event_type") == "day_speech_committed"
    ]
    assert [event["payload"]["player_id"] for event in committed] == [
        "wolf_1",
        "wolf_2",
        "villager_3",
        "villager_4",
    ]


@pytest.mark.parametrize("error_type", [asyncio.CancelledError, RuntimeError])
def test_final_legacy_speech_failure_aborts_pre_exile_child(
    error_type: type[BaseException],
) -> None:
    async def scenario() -> tuple[
        _FailingFinalDiscussionEngine,
        _InvalidatingPreExileRepository,
    ]:
        state = _generation_snapshot()
        repository = _VoteRepository(state)
        pipeline_repository = _InvalidatingPreExileRepository()
        engine = _FailingFinalDiscussionEngine(
            error_type=error_type,
            repository=repository,  # type: ignore[arg-type]
            action_engine=_VoteActions(),  # type: ignore[arg-type]
            pre_exile_pipeline_repository=pipeline_repository,  # type: ignore[arg-type]
        )
        with pytest.raises(error_type, match="synthetic final presentation failure"):
            await engine._run_public_discussion(
                game_id=state.game_id,
                broadcaster=_Broadcaster(),
            )
        return engine, pipeline_repository

    engine, pipeline_repository = asyncio.run(scenario())

    assert engine.last_launch is not None
    assert engine.last_launch.task is not None
    assert engine.last_launch.task.cancelled()
    assert len(pipeline_repository.calls) == 1
    assert pipeline_repository.calls[0]["pipeline_id"] == "v2_preex_pipeline"
    assert pipeline_repository.calls[0]["reason_code"] == (
        "predecessor_presentation_canceled"
        if error_type is asyncio.CancelledError
        else "predecessor_presentation_failed"
    )


class _CanceledGenerationActions(_GenerationActions):
    def __init__(self, pipeline: _GenerationPipeline) -> None:
        super().__init__(pipeline)
        self.canceled_returned = False

    def check_cancellation(self, _game_id: str) -> None:
        if self.canceled_returned:
            raise V2ExecutionOwnershipLost("synthetic fence loss")

    async def run_player_decision_result(
        self,
        *,
        game_id: str,
        broadcaster: Any,
        spec: V2SpeechSpec,
        on_model_admission_pending: Any = None,
        **_kwargs: Any,
    ) -> V2ActionResult:
        del game_id, broadcaster
        self.start_order.append(
            (str(spec.pipeline_result_kind), spec.model_admission_mode, spec.actor_id)
        )
        if on_model_admission_pending is not None:
            on_model_admission_pending()
        self.canceled_returned = True
        return V2ActionResult(
            action_id=f"v2_action_canceled_{spec.actor_id}",
            failure=V2ActionFailure(
                code="pre_exile_pipeline_generation_canceled",
                category="canceled",
                terminal_attempt_id=None,
            ),
            terminal_event_record_seq=401,
        )


def test_canceled_member_does_not_become_false_or_continue_to_votes() -> None:
    async def scenario() -> tuple[_GenerationRepository, _GenerationPipeline, Any]:
        state = _generation_snapshot()
        repository = _GenerationRepository(state)
        pipeline_repository = _GenerationPipeline(repository)
        actions = _CanceledGenerationActions(pipeline_repository)
        engine = V2DayEngine(
            repository=repository,  # type: ignore[arg-type]
            action_engine=actions,  # type: ignore[arg-type]
            pre_exile_pipeline_repository=pipeline_repository,  # type: ignore[arg-type]
        )
        launch = _PreExileLaunch(
            presentation_closed=asyncio.Event(),
            predecessor_committed=asyncio.Event(),
            pipeline=SimpleNamespace(pipeline_id="v2_preex_pipeline"),
            frozen=V2PreExilePrefetchSnapshot(
                match_snapshot=state,
                public_cutoff_record_seq=100,
                predecessor_presentation_id="v2_pres_last",
                predecessor_action_id="v2_action_last_speech",
                predecessor_source_event_id=90,
                predecessor_source_record_seq=90,
                predecessor_sealed_record_seq=100,
                predecessor_actor_id="villager_4",
            ),
            run_fence=None,
        )
        with pytest.raises(V2ExecutionOwnershipLost, match="synthetic fence loss"):
            await engine._generate_pre_exile_pipeline(
                launch=launch,
                sealed_private_facts={player.player_id: [] for player in state.players},
                broadcaster=_Broadcaster(),
            )
        return repository, pipeline_repository, actions

    repository, pipeline_repository, actions = asyncio.run(scenario())

    assert repository.resolve_calls == []
    assert repository.finalize_calls == []
    assert pipeline_repository.vote_recorded_count == 0
    assert all(kind == "self_explosion" for kind, _mode, _actor in actions.start_order)
