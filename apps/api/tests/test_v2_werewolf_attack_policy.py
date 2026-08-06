from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

from app.v2.first_night_engine import (
    V2NightEngine,
    _WorkingNight,
    _resolve_werewolf_attack,
)
from app.v2.model_client import V2ModelDecision
from app.v2.model_context import (
    V2ModelPlayerReference,
    build_public_rule_contract,
    project_model_action_context,
)
from app.v2.model_context_contract import v9_model_context_contract
from app.v2.night_repository import (
    V2ActivationRef,
    V2NightPlayer,
    V2NightRuntimeState,
)


def _player(player_id: str, seat: int, role_key: str) -> V2NightPlayer:
    return V2NightPlayer(
        player_id=player_id,
        seat=seat,
        display_name=f"{seat}号",
        role_key=role_key,
        team="werewolves" if role_key == "werewolf" else "villagers",
        alive=True,
        tts_speaker=None,
        tts_dialect=None,
        model_provider="agent_plan",
        model_id="test-model",
        model_parameters={},
        persona={},
    )


def _decision(
    target_player_id: str | None,
    speech: str | None,
    *,
    decision_note: str | None = None,
) -> V2ModelDecision:
    return V2ModelDecision(
        target_player_id=target_player_id,
        speech=speech,
        provider_request_id="request",
        first_token_ms=1,
        completed_ms=2,
        decision_note=decision_note,
    )


def _state(
    *,
    players: tuple[V2NightPlayer, ...],
    policy: dict[str, Any],
    round_no: int = 1,
) -> V2NightRuntimeState:
    return V2NightRuntimeState(
        game_id="v2_game_test",
        run_id="v2_run_test",
        window_id="v2_window_test",
        window_seq=round_no,
        phase_id=f"night_{round_no}",
        round_no=round_no,
        snapshot={"policies": {"werewolf_attack": policy}, "instances": []},
        rule={
            "id": "test_rule",
            "name": "测试规则",
            "version": "1",
            "player_count": len(players),
            "roles": [],
            "win_condition": "wolves_gte_others",
            "reveal_policy": "hidden",
            "sheriff_enabled": False,
            "speech_policy": "sequential",
            "speech_rounds": 1,
            "ability_policies": {"werewolf_attack": policy},
        },
        max_rounds=8,
        sheriff_player_id=None,
        sheriff_badge_state="unassigned",
        players=players,
    )


def _v9_werewolf_attack_ability(
    policy: dict[str, Any],
    *,
    living_teammates: list[str] | None = None,
) -> dict[str, Any]:
    teammate_ids = living_teammates if living_teammates is not None else ["wolf-2"]
    players = (
        V2ModelPlayerReference("wolf-1", 1, "1号"),
        V2ModelPlayerReference("wolf-2", 2, "2号"),
        V2ModelPlayerReference("good-3", 3, "3号"),
        V2ModelPlayerReference("good-4", 4, "4号"),
    )
    rule_contract = build_public_rule_contract(
        rule={
            "id": "wolf-policy-v9",
            "version": "1",
            "player_count": 4,
            "roles": [
                {"role": "狼人", "count": 2, "team": "werewolves"},
                {"role": "村民", "count": 2, "team": "villagers"},
            ],
            "ability_policies": {"werewolf_attack": policy},
        },
        max_rounds=8,
    )
    projected = project_model_action_context(
        {
            "round_no": 2,
            "night_no": 2,
            "action_type": "ability_werewolf.attack_decision",
            "ability_id": "werewolf.attack",
            "self_identity": {
                "player_id": "wolf-1",
                "seat": 1,
                "role_key": "werewolf",
                "team": "werewolves",
            },
            "private_authoritative_facts": [
                {
                    "fact_type": "living_werewolf_teammates",
                    "payload": teammate_ids,
                }
            ],
            "public_match_state": {
                "round_no": 2,
                "alive_player_ids": ["wolf-1", *teammate_ids, "good-3", "good-4"],
            },
            "public_rule_contract": rule_contract,
            "public_history": [],
            "output_contract": {
                "kind": "target",
                "target_policy": {"mode": "optional" if policy["allow_no_attack"] else "required"},
                "speech": {"mode": "forbidden"},
            },
        },
        players=players,
        model_context_contract=v9_model_context_contract(),
        action_record_seq=50,
    )
    return projected["rules"]["current_ability"]


def test_v9_derives_unambiguous_semantics_for_all_werewolf_attack_strategies() -> None:
    expected = {
        "unanimous_no_attack": {
            "strategy": "unanimity_required",
            "on_disagreement": "no_attack",
        },
        "plurality_rotating_tiebreak": {
            "strategy": "plurality",
            "on_unique_highest": "unique_highest",
            "on_tie": "explicit_rotating_werewolf_decision",
        },
        "plurality_seeded_random": {
            "strategy": "plurality",
            "on_unique_highest": "unique_highest",
            "on_tie": "deterministic_seeded_choice",
        },
    }
    for resolution, team_resolution in expected.items():
        ability = _v9_werewolf_attack_ability(
            {
                "resolution": resolution,
                "allow_no_attack": False,
                "allow_wolf_target": False,
            }
        )
        assert ability["team_resolution"] == team_resolution
        assert ability["individual_ballot"] == {
            "target_mode": "required",
            "allow_no_attack": False,
            "allow_wolf_target": False,
        }


def test_v9_werewolf_attack_single_living_actor_and_optional_ballot_are_explicit() -> None:
    ability = _v9_werewolf_attack_ability(
        {
            "resolution": "plurality_seeded_random",
            "allow_no_attack": True,
            "allow_wolf_target": True,
        },
        living_teammates=[],
    )

    assert ability["team_resolution"] == {
        "strategy": "single_actor_direct",
        "on_tie": "not_applicable",
    }
    assert ability["individual_ballot"] == {
        "target_mode": "optional",
        "allow_no_attack": True,
        "allow_wolf_target": True,
    }


def test_second_round_receives_first_round_and_prior_second_round_speech() -> None:
    players = (
        _player("wolf-1", 1, "werewolf"),
        _player("wolf-2", 2, "werewolf"),
        _player("good-3", 3, "villager"),
        _player("good-4", 4, "villager"),
        _player("good-5", 5, "villager"),
        _player("good-6", 6, "villager"),
    )
    policy = {
        "resolution": "plurality_rotating_tiebreak",
        "allow_no_attack": False,
        "allow_wolf_target": False,
    }
    state = V2NightRuntimeState(
        game_id="v2_game_test",
        run_id="v2_run_test",
        window_id="v2_window_test",
        window_seq=1,
        phase_id="night_1",
        round_no=1,
        snapshot={"policies": {"werewolf_attack": policy}, "instances": []},
        rule={
            "id": "test_rule",
            "name": "测试规则",
            "version": "1",
            "player_count": 6,
            "roles": [
                {"role": "狼人", "count": 2, "team": "werewolves"},
                {"role": "村民", "count": 4, "team": "villagers"},
            ],
            "win_condition": "wolves_gte_others",
            "reveal_policy": "hidden",
            "sheriff_enabled": False,
            "speech_policy": "sequential",
            "speech_rounds": 1,
            "ability_policies": {"werewolf_attack": policy},
        },
        max_rounds=8,
        sheriff_player_id=None,
        sheriff_badge_state="unassigned",
        players=players,
    )
    repository = _FakeRepository()
    actions = _FakeActions(
        [
            _decision("good-3", None, decision_note="3号发言最稳，可能藏身份。"),
            _decision("good-4", None, decision_note="4号神职风险更高。"),
            _decision("good-3", "看完队友意见，我最终投3号。"),
            _decision("good-3", "综合讨论，我也归票3号。"),
        ]
    )
    engine = V2NightEngine(
        repository=repository,
        action_engine=actions,
        day_engine=SimpleNamespace(),
    )
    working = _WorkingNight()

    asyncio.run(engine._run_werewolves(state, _FakeBroadcaster(), working))

    assert working.attack_target == "good-3"
    blind_specs = actions.specs[:2]
    discussion_specs = actions.specs[2:]
    assert all(
        spec.output_kind == "private_decision"
        and spec.decision_contract.speech_mode == "forbidden"
        and spec.decision_contract.decision_note_mode == "optional"
        and spec.decision_contract.decision_note_max_chars == 80
        for spec in blind_specs
    )
    assert all(
        spec.output_kind == "decision_and_speech"
        and spec.decision_contract.speech_mode == "required"
        and spec.decision_contract.speech_max_sentences == 1
        and spec.decision_contract.decision_note_mode == "none"
        for spec in discussion_specs
    )
    assert {spec.objective for spec in actions.specs} == {
        "独立盲选本夜初步袭击目标，并用 decision_note 记录一句简短理由。",
        (
            "刀口出现分歧；查看全体狼人的盲选刀口和你自己的盲选理由，"
            "重新选择刀口，并在狼人私聊中用一句话说明理由。"
        ),
    }
    assert all("一句话" not in spec.objective for spec in blind_specs)
    assert all("一句话" in spec.objective for spec in discussion_specs)
    assert actions.specs[0].defer_presentation is True
    assert actions.specs[1].defer_presentation is True
    assert actions.specs[0].batch_id == actions.specs[1].batch_id
    assert "werewolf_first_round" not in repository.knowledge[0]
    assert "werewolf_first_round" not in repository.knowledge[1]
    first_final = repository.knowledge[2]
    second_final = repository.knowledge[3]
    assert (
        first_final["werewolf_first_round"]
        == second_final["werewolf_first_round"]
        == [
            {
                "player_id": "wolf-1",
                "target_player_id": "good-3",
                "status": "completed",
            },
            {
                "player_id": "wolf-2",
                "target_player_id": "good-4",
                "status": "completed",
            },
        ]
    )
    assert first_final["blind_choice_reason_visibility"] == "own_declared_reason_only"
    assert second_final["blind_choice_reason_visibility"] == "own_declared_reason_only"
    assert first_final["werewolf_second_round_so_far"] == []
    assert second_final["werewolf_second_round_so_far"] == [
        {
            "player_id": "wolf-1",
            "target_player_id": "good-3",
            "speech": "看完队友意见，我最终投3号。",
            "speaking_position": 1,
        }
    ]
    assert actions.presented == []
    blind_completions = [
        item
        for item in repository.completions
        if item["decision"]["decision_stage"] == "preference_probe"
    ]
    assert [item["decision"]["decision_note"] for item in blind_completions] == [
        "3号发言最稳，可能藏身份。",
        "4号神职风险更高。",
    ]
    assert all("speech" not in item["decision"] for item in blind_completions)
    final_completions = [
        item
        for item in repository.completions
        if item["decision"]["decision_stage"] == "sequential_final_vote"
    ]
    assert len(final_completions) == 2
    assert {item["result"]["resolution_reason"] for item in final_completions} == {"unique_highest"}
    assert all(item.get("effect_type") is None for item in final_completions)
    team_resolution = next(
        item
        for item in repository.completions
        if item["decision"]["decision_stage"] == "team_resolution"
    )
    assert team_resolution["effect_type"] == "attack"
    assert team_resolution["target_player_id"] == "good-3"


def test_parallel_unanimous_preference_skips_second_round_and_forms_attack() -> None:
    players = (
        _player("wolf-1", 1, "werewolf"),
        _player("wolf-2", 2, "werewolf"),
        _player("good-3", 3, "villager"),
        _player("good-4", 4, "villager"),
        _player("good-5", 5, "villager"),
        _player("good-6", 6, "villager"),
    )
    policy = {
        "resolution": "plurality_rotating_tiebreak",
        "allow_no_attack": False,
        "allow_wolf_target": False,
    }
    state = _state(players=players, policy=policy)
    repository = _FakeRepository()
    actions = _ConcurrentPreferenceActions(
        expected_wolves=2,
        target_player_id="good-3",
    )
    engine = V2NightEngine(
        repository=repository,
        action_engine=actions,
        day_engine=SimpleNamespace(),
    )
    working = _WorkingNight()

    asyncio.run(engine._run_werewolves(state, _FakeBroadcaster(), working))

    assert actions.max_in_flight == 2
    assert len(actions.specs) == 2
    assert all(spec.defer_presentation for spec in actions.specs)
    assert actions.presented == []
    assert working.attack_target == "good-3"
    assert not any(
        item["decision"]["decision_stage"] == "sequential_final_vote"
        for item in repository.completions
    )
    resolution = next(
        item
        for item in repository.completions
        if item["decision"]["decision_stage"] == "team_resolution"
    )
    assert resolution["result"]["resolution_reason"] == "blind_choice_unanimous"
    assert resolution["decision"]["resolution_stage"] == "blind_choice_consensus"
    assert resolution["effect_type"] == "attack"


def test_tied_second_round_requests_explicit_rotating_tiebreak() -> None:
    players = (
        _player("wolf-1", 1, "werewolf"),
        _player("wolf-2", 2, "werewolf"),
        _player("good-3", 3, "villager"),
        _player("good-4", 4, "villager"),
        _player("good-5", 5, "villager"),
        _player("good-6", 6, "villager"),
    )
    policy = {
        "resolution": "plurality_rotating_tiebreak",
        "allow_no_attack": False,
        "allow_wolf_target": False,
    }
    repository = _FakeRepository()
    actions = _FakeActions(
        [
            _decision("good-3", None, decision_note="盲选3号。"),
            _decision("good-4", None, decision_note="盲选4号。"),
            _decision("good-3", "我最终投3号。"),
            _decision("good-4", "我最终投4号。"),
            _decision("good-4", "我归票4号。"),
        ]
    )
    working = _WorkingNight()
    engine = V2NightEngine(
        repository=repository,
        action_engine=actions,
        day_engine=SimpleNamespace(),
    )

    asyncio.run(
        engine._run_werewolves(
            _state(players=players, policy=policy),
            _FakeBroadcaster(),
            working,
        )
    )

    assert working.attack_target == "good-4"
    assert actions.specs[-1].allowed_target_ids == ("good-3", "good-4")
    assert repository.knowledge[-1]["decision_stage"] == "tiebreak"
    tiebreak = next(
        item for item in repository.completions if item["decision"]["decision_stage"] == "tiebreak"
    )
    assert tiebreak["activation"].actor_player_id == "wolf-1"
    assert tiebreak["result"]["resolution_reason"] == "explicit_rotating_tiebreak"


def test_werewolf_attack_resolution_presets_are_deterministic() -> None:
    wolves = [_player(f"wolf-{index}", index, "werewolf") for index in range(1, 5)]
    state = SimpleNamespace(game_id="v2_game_test", round_no=2)

    majority = _resolve_werewolf_attack(
        state=state,
        wolves=wolves,
        votes=[
            ("wolf-1", "good-5"),
            ("wolf-2", "good-5"),
            ("wolf-3", "good-5"),
            ("wolf-4", "good-6"),
        ],
        policy={"resolution": "plurality_rotating_tiebreak"},
    )
    assert (majority.target_player_id, majority.reason) == (
        "good-5",
        "unique_highest",
    )

    rotating = _resolve_werewolf_attack(
        state=state,
        wolves=wolves[:2],
        votes=[("wolf-1", "good-5"), ("wolf-2", "good-6")],
        policy={"resolution": "plurality_rotating_tiebreak"},
    )
    assert (
        rotating.target_player_id,
        rotating.reason,
        rotating.tiebreaker_player_id,
        rotating.tied_target_player_ids,
    ) == (
        None,
        "explicit_rotating_tiebreak_required",
        "wolf-2",
        ("good-5", "good-6"),
    )

    seeded_first = _resolve_werewolf_attack(
        state=state,
        wolves=wolves[:2],
        votes=[("wolf-1", "good-5"), ("wolf-2", "good-6")],
        policy={"resolution": "plurality_seeded_random"},
    )
    seeded_second = _resolve_werewolf_attack(
        state=state,
        wolves=wolves[:2],
        votes=[("wolf-1", "good-5"), ("wolf-2", "good-6")],
        policy={"resolution": "plurality_seeded_random"},
    )
    assert seeded_first == seeded_second
    assert seeded_first.target_player_id in {"good-5", "good-6"}
    assert seeded_first.reason == "seeded_tiebreak"

    unanimous = _resolve_werewolf_attack(
        state=state,
        wolves=wolves[:2],
        votes=[("wolf-1", "good-5"), ("wolf-2", "good-6")],
        policy={"resolution": "unanimous_no_attack"},
    )
    assert (unanimous.target_player_id, unanimous.reason) == (
        None,
        "no_consensus_no_attack",
    )


def test_optional_no_attack_and_wolf_target_switches_change_decision_contract() -> None:
    wolf = _player("wolf-1", 1, "werewolf")
    good_players = tuple(_player(f"good-{seat}", seat, "villager") for seat in range(2, 7))
    policy = {
        "resolution": "plurality_rotating_tiebreak",
        "allow_no_attack": True,
        "allow_wolf_target": True,
    }
    state = V2NightRuntimeState(
        game_id="v2_game_optional",
        run_id="v2_run_optional",
        window_id="v2_window_optional",
        window_seq=1,
        phase_id="night_1",
        round_no=1,
        snapshot={"policies": {"werewolf_attack": policy}, "instances": []},
        rule={
            "id": "test_rule",
            "name": "测试规则",
            "version": "1",
            "player_count": 6,
            "roles": [
                {"role": "狼人", "count": 1, "team": "werewolves"},
                {"role": "村民", "count": 5, "team": "villagers"},
            ],
            "win_condition": "wolves_gte_others",
            "reveal_policy": "hidden",
            "sheriff_enabled": False,
            "speech_policy": "sequential",
            "speech_rounds": 1,
            "ability_policies": {"werewolf_attack": policy},
        },
        max_rounds=8,
        sheriff_player_id=None,
        sheriff_badge_state="unassigned",
        players=(wolf, *good_players),
    )
    repository = _FakeRepository()
    actions = _FakeActions([_decision(None, "本夜主动空刀。")])
    working = _WorkingNight()
    engine = V2NightEngine(
        repository=repository,
        action_engine=actions,
        day_engine=SimpleNamespace(),
    )

    asyncio.run(engine._run_werewolves(state, _FakeBroadcaster(), working))

    assert working.attack_target is None
    assert actions.specs[0].decision_contract.target_mode == "optional"
    assert actions.specs[0].allowed_target_ids == tuple(
        player.player_id for player in state.players
    )
    assert repository.completions[0]["result"]["resolution_reason"] == ("voluntary_no_attack")


class _FakeRepository:
    def __init__(self) -> None:
        self.knowledge: list[dict[str, Any]] = []
        self.completions: list[dict[str, Any]] = []
        self._occurrence = 0

    def open_activation(
        self,
        *,
        state: V2NightRuntimeState,
        ability_id: str,
        actor_player_id: str,
        occurrence: int,
        audience: str,
    ) -> V2ActivationRef:
        self._occurrence = occurrence
        return V2ActivationRef(
            activation_id=f"activation-{occurrence}",
            ability_instance_id="instance",
            ability_id=ability_id,
            actor_player_id=actor_player_id,
            occurrence=occurrence,
            audience=audience,
        )

    def register_activation_knowledge(
        self,
        *,
        state: V2NightRuntimeState,
        activation: V2ActivationRef,
        owner_player_id: str,
        allowed_knowledge: dict[str, Any],
    ) -> tuple[tuple[str, ...], str]:
        self.knowledge.append(allowed_knowledge)
        return ((f"fact-{activation.occurrence}",), "hash")

    def player_knowledge(self, *, game_id: str, player_id: str) -> list[dict[str, Any]]:
        return []

    def public_history(self, game_id: str) -> list[dict[str, Any]]:
        return []

    def complete_activation(self, **kwargs: Any) -> None:
        self.completions.append(kwargs)


class _FakeActions:
    def __init__(self, decisions: list[V2ModelDecision]) -> None:
        self._decisions = iter(decisions)
        self.specs: list[Any] = []
        self.presented: list[V2ModelDecision] = []

    async def run_judge_speech(self, **kwargs: Any) -> bool:
        return True

    async def run_player_decision(self, **kwargs: Any) -> V2ModelDecision:
        self.specs.append(kwargs["spec"])
        return next(self._decisions)

    async def present_player_decision(self, **kwargs: Any) -> bool:
        self.presented.append(kwargs["decision"])
        return True


class _ConcurrentPreferenceActions:
    def __init__(self, *, expected_wolves: int, target_player_id: str) -> None:
        self._expected_wolves = expected_wolves
        self._target_player_id = target_player_id
        self._started = 0
        self._in_flight = 0
        self._all_started = asyncio.Event()
        self.max_in_flight = 0
        self.specs: list[Any] = []
        self.presented: list[V2ModelDecision] = []

    async def run_judge_speech(self, **kwargs: Any) -> bool:
        return True

    async def run_player_decision(self, **kwargs: Any) -> V2ModelDecision:
        spec = kwargs["spec"]
        self.specs.append(spec)
        assert spec.defer_presentation is True
        self._started += 1
        self._in_flight += 1
        self.max_in_flight = max(self.max_in_flight, self._in_flight)
        if self._started == self._expected_wolves:
            self._all_started.set()
        await asyncio.wait_for(self._all_started.wait(), timeout=1)
        self._in_flight -= 1
        return _decision(
            self._target_player_id,
            None,
            decision_note=f"{spec.actor_id}盲选同一刀口。",
        )

    async def present_player_decision(self, **kwargs: Any) -> bool:
        self.presented.append(kwargs["decision"])
        return True


class _FakeBroadcaster:
    async def broadcast_json(self, payload: dict[str, Any], **kwargs: Any) -> None:
        return None
