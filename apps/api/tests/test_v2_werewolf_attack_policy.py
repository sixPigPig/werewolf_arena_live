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


def _decision(target_player_id: str | None, speech: str) -> V2ModelDecision:
    return V2ModelDecision(
        target_player_id=target_player_id,
        speech=speech,
        provider_request_id="request",
        first_token_ms=1,
        completed_ms=2,
    )


def test_all_wolves_receive_the_same_complete_discussion_before_final_vote() -> None:
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
            _decision("good-3", "我建议刀3号，因为他发言最稳。"),
            _decision("good-4", "我倾向刀4号，降低神职风险。"),
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
    assert "werewolf_discussion" not in repository.knowledge[0]
    assert "werewolf_discussion" not in repository.knowledge[1]
    first_final = repository.knowledge[2]["werewolf_discussion"]
    second_final = repository.knowledge[3]["werewolf_discussion"]
    assert first_final == second_final == [
        {
            "player_id": "wolf-1",
            "target_player_id": "good-3",
            "speech": "我建议刀3号，因为他发言最稳。",
        },
        {
            "player_id": "wolf-2",
            "target_player_id": "good-4",
            "speech": "我倾向刀4号，降低神职风险。",
        },
    ]
    final_completions = [
        item
        for item in repository.completions
        if item["decision"]["decision_stage"] == "final_vote"
    ]
    assert len(final_completions) == 2
    assert {item["result"]["resolution_reason"] for item in final_completions} == {
        "unique_highest"
    }
    assert sum(item["effect_type"] == "attack" for item in final_completions) == 1


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
    ) == ("good-6", "rotating_tiebreak", "wolf-2")

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
    good_players = tuple(
        _player(f"good-{seat}", seat, "villager") for seat in range(2, 7)
    )
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
    assert repository.completions[0]["result"]["resolution_reason"] == (
        "voluntary_no_attack"
    )


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
    ) -> V2ActivationRef:
        self._occurrence = occurrence
        return V2ActivationRef(
            activation_id=f"activation-{occurrence}",
            ability_instance_id="instance",
            ability_id=ability_id,
            actor_player_id=actor_player_id,
            occurrence=occurrence,
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

    async def run_judge_speech(self, **kwargs: Any) -> bool:
        return True

    async def run_player_decision(self, **kwargs: Any) -> V2ModelDecision:
        self.specs.append(kwargs["spec"])
        return next(self._decisions)


class _FakeBroadcaster:
    async def broadcast_json(self, payload: dict[str, Any], **kwargs: Any) -> None:
        return None
