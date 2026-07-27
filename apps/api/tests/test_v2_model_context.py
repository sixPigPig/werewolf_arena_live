from __future__ import annotations

import json

from app.v2.model_context import (
    V2ModelPlayerReference,
    build_public_match_state,
    build_public_rule_contract,
    private_authoritative_facts,
    project_model_action_context,
    resolve_model_target,
    sanitize_model_speech,
)
from app.v2.model_client import build_model_request_payload


PLAYERS = (
    V2ModelPlayerReference("system-player-07", 1, "乔宁"),
    V2ModelPlayerReference("system-player-01", 2, "沈砚"),
    V2ModelPlayerReference("system-player-09", 4, "唐梨"),
)


def test_model_context_uses_only_seat_references_and_splits_public_facts() -> None:
    projected = project_model_action_context(
        {
            "actor": {"kind": "player", "id": "system-player-01"},
            "objective": "沈砚需要判断唐梨是否可信",
            "output_contract": {
                "target_policy": {
                    "mode": "required",
                    "allowed_target_ids": ["system-player-09"],
                }
            },
            "actor_private": {
                "player_id": "system-player-01",
                "seat": 2,
                "persona": {"name": "沈砚", "personality": "沈砚习惯先梳理事实"},
            },
            "private_authoritative_facts": [
                {
                    "fact_type": "investigation_alignment",
                    "payload": {
                        "target_player_id": "system-player-09",
                        "alignment": "werewolves",
                        "night_no": 1,
                    },
                }
            ],
            "public_match_state": {
                "round_no": 1,
                "alive_player_count": 2,
                "alive_player_ids": ["system-player-01", "system-player-09"],
                "eliminated_player_count": 1,
                "eliminated_player_ids": ["system-player-07"],
                "identity_information_included": False,
            },
            "candidates": [
                {
                    "player_id": "system-player-09",
                    "seat": 4,
                    "display_name": "唐梨",
                }
            ],
            "public_history": [
                {
                    "event_type": "dawn_public_result",
                    "payload": {
                        "round_no": 1,
                        "dead_player_ids": ["system-player-07"],
                    },
                },
                {
                    "event_type": "day_speech_committed",
                    "payload": {
                        "round_no": 1,
                        "stage": "day_debate",
                        "player_id": "system-player-01",
                        "speech": "昨晚乔宁出局，我怀疑唐梨。",
                    },
                },
                {
                    "event_type": "player_exiled",
                    "payload": {
                        "round_no": 1,
                        "player_id": "system-player-09",
                    },
                },
            ],
        },
        players=PLAYERS,
    )

    serialized = json.dumps(projected, ensure_ascii=False)
    assert "乔宁" not in serialized
    assert "沈砚" not in serialized
    assert "唐梨" not in serialized
    assert "system-player-" not in serialized
    assert projected["actor"]["id"] == "seat_2"
    assert projected["candidates"][0] == {
        "player_id": "seat_4",
        "seat": 4,
        "display_name": "4号",
    }
    assert projected["private_authoritative_facts"] == [
        {
            "fact_type": "investigation_alignment",
            "payload": {
                "target_player_id": "seat_4",
                "alignment": "werewolves",
                "night_no": 1,
            },
        }
    ]
    assert projected["public_match_state"] == {
        "round_no": 1,
        "alive_player_count": 2,
        "alive_player_ids": ["seat_2", "seat_4"],
        "eliminated_player_count": 1,
        "eliminated_player_ids": ["seat_1"],
        "identity_information_included": False,
    }
    assert "是否公开以及如何使用由玩家自主决定" in projected[
        "information_semantics"
    ]["private_authoritative_facts"]
    assert projected["authoritative_public_facts"] == [
        {
            "kind": "night_result",
            "occurred_in": {"period": "night", "round_no": 1},
            "announced_in": {"period": "dawn", "round_no": 1},
            "outcome": "deaths",
            "eliminated_player_refs": ["seat_1"],
        },
        {
            "kind": "player_eliminated",
            "occurred_in": {"period": "day", "round_no": 1},
            "public_reason": "exile",
            "player_ref": "seat_4",
        },
    ]
    assert projected["public_statements"] == [
        {
            "kind": "player_statement",
            "occurred_in": {"period": "day", "round_no": 1},
            "stage": "day_debate",
            "speaker_ref": "seat_2",
            "speech": "昨晚1号出局，我怀疑4号。",
        }
    ]


def test_model_target_and_speech_are_mapped_back_to_internal_identity() -> None:
    assert resolve_model_target("seat_4", players=PLAYERS) == "system-player-09"
    assert resolve_model_target("seat_3", players=PLAYERS) is None
    assert sanitize_model_speech(
        "我建议查验唐梨，不要把system-player-07当成7号。",
        players=PLAYERS,
    ) == "我建议查验4号，不要把seat_1当成7号。"


def test_public_rule_contract_exposes_single_wolf_and_disabled_sheriff() -> None:
    contract = build_public_rule_contract(
        rule={
            "id": "starter_6",
            "name": "新手 6 人快局",
            "version": "1",
            "player_count": 6,
            "roles": [
                {"role": "狼人", "count": 1, "team": "werewolves"},
                {"role": "预言家", "count": 1, "team": "villagers"},
                {"role": "守卫", "count": 1, "team": "villagers"},
                {"role": "村民", "count": 3, "team": "villagers"},
            ],
            "win_condition": "wolves_gte_others",
            "reveal_policy": "hidden",
            "sheriff_enabled": False,
            "sheriff_vote_weight": 1.0,
            "speech_policy": "sequential",
            "speech_rounds": 1,
            "werewolf_self_explosion_enabled": False,
            "exile_last_words_enabled": True,
            "ability_policies": {
                "werewolf_consensus": {
                    "rounds": 2,
                    "agreement": "unanimous",
                    "unresolved": "no_attack",
                },
                "guard": {
                    "first_night_self_protect": True,
                    "consecutive_same_target": False,
                },
            },
        },
        max_rounds=8,
    )

    assert contract["player_count"] == 6
    assert contract["werewolf_count"] == 1
    assert contract["reveal_policy"] == "hidden"
    assert contract["role_reveal_rule"] == (
        "玩家死亡或被放逐后，法官不会公开其身份或阵营；"
        "出局方式、发言和投票结果均不能作为法官已证实其身份的依据。"
    )
    assert contract["roles"] == [
        {
            "role_key": "werewolf",
            "role_label": "狼人",
            "count": 1,
            "team": "werewolves",
        },
        {
            "role_key": "seer",
            "role_label": "预言家",
            "count": 1,
            "team": "villagers",
        },
        {
            "role_key": "guard",
            "role_label": "守卫",
            "count": 1,
            "team": "villagers",
        },
        {
            "role_key": "villager",
            "role_label": "村民",
            "count": 3,
            "team": "villagers",
        },
    ]
    assert contract["sheriff_enabled"] is False
    assert contract["sheriff_vote_weight"] is None
    assert contract["sheriff_rule"] == (
        "本局不启用警长系统，不存在上警、警徽或警徽流机制。"
    )
    assert contract["night_action_rules"]["werewolf_attack"] == {
        "enabled": True,
        "actor_scope": "所有存活狼人",
        "target_scope": "一名存活的非狼人玩家",
        "each_actor_must_choose_target": True,
        "can_target_self": False,
        "can_target_werewolf_teammates": False,
        "team_resolution": {
            "rounds": 2,
            "agreement": "unanimous",
            "unresolved": "no_attack",
        },
        "single_werewolf_resolution": (
            "本局只有1名狼人时，该狼人每夜必须选择一名存活的非狼人玩家，"
            "不会因团队意见不一致而空刀。"
        ),
    }
    assert contract["night_action_rules"]["guard_protect"] == {
        "enabled": True,
        "target_scope": "一名存活玩家，可以选择自己",
        "target_required": True,
        "first_night_self_protect": True,
        "can_repeat_previous_night_target": False,
        "successful_protection_effect": (
            "若守护目标当夜受到狼人攻击，该目标不会因这次攻击出局。"
        ),
    }


def test_public_match_state_contains_only_public_liveness() -> None:
    class Player:
        def __init__(self, player_id: str, alive: bool) -> None:
            self.player_id = player_id
            self.alive = alive

    state = build_public_match_state(
        round_no=2,
        players=[
            Player("system-player-07", True),
            Player("system-player-01", False),
            Player("system-player-09", True),
        ],
    )

    assert state == {
        "round_no": 2,
        "alive_player_count": 2,
        "alive_player_ids": ["system-player-07", "system-player-09"],
        "eliminated_player_count": 1,
        "eliminated_player_ids": ["system-player-01"],
        "identity_information_included": False,
    }


def test_private_authoritative_facts_flattens_known_investigations() -> None:
    assert private_authoritative_facts(
        {
            "known_investigations": [
                {
                    "fact_type": "investigation_alignment",
                    "payload": {
                        "target_player_id": "seat_4",
                        "alignment": "werewolves",
                        "night_no": 1,
                    },
                }
            ],
            "night_no": 2,
        }
    ) == [
        {
            "fact_type": "investigation_alignment",
            "payload": {
                "target_player_id": "seat_4",
                "alignment": "werewolves",
                "night_no": 1,
            },
        },
        {"fact_type": "night_no", "payload": 2},
    ]


def test_player_prompt_explains_information_sources_without_forcing_strategy() -> None:
    payload = build_model_request_payload(
        {
            "public_rule_contract": {"sheriff_enabled": False},
            "private_authoritative_facts": [],
            "authoritative_public_facts": [],
            "public_statements": [],
        },
        decision=True,
        model_id="test-model",
    )
    system_text = payload["input"][0]["content"][0]["text"]

    assert "public_rule_contract 是本局冻结的公开规则" in system_text
    assert "public_match_state 是法官确认的当前公开存活状态" in system_text
    assert "private_authoritative_facts 是当前玩家被法官确认知晓的私有事实" in system_text
    assert "public_statements 只是玩家说法" in system_text
    assert "是否公开私有事实" in system_text
    assert "采用何种策略均由你自主决定" in system_text
