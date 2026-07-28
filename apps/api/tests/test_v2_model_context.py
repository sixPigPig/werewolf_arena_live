from __future__ import annotations

import json

from app.v2.model_context import (
    V2ModelPlayerReference,
    build_actor_information,
    build_public_match_state,
    build_public_rule_contract,
    model_prompt_metadata,
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
            "self_identity": {
                "player_id": "system-player-01",
                "seat": 2,
                "role_key": "seer",
                "team": "villagers",
            },
            "actor_profile": {
                "name": "沈砚",
                "personality": "沈砚习惯先梳理事实",
            },
            "output_contract": {
                "target_policy": {
                    "mode": "required",
                    "allowed_target_ids": ["system-player-09"],
                }
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
    assert projected["task"]["objective"] == "2号需要判断4号是否可信"
    assert projected["self"]["identity"] == {
        "player_id": "seat_2",
        "seat": 2,
        "role_key": "seer",
        "team": "villagers",
    }
    assert projected["candidates"][0] == {
        "player_id": "seat_4",
        "seat": 4,
        "display_name": "4号",
    }
    assert projected["self"]["private_judge_facts"] == [
        {
            "fact_type": "investigation_alignment",
            "payload": {
                "target_player_id": "seat_4",
                "alignment": "werewolves",
                "night_no": 1,
            },
        }
    ]
    assert projected["public_state"] == {
        "round_no": 1,
        "alive_player_count": 2,
        "alive_player_ids": ["seat_2", "seat_4"],
        "eliminated_player_count": 1,
        "eliminated_player_ids": ["seat_1"],
        "identity_information_included": False,
        "judge_facts": [
            {
                "kind": "night_result",
                "source_event_id": "history_1",
                "occurred_in": {"period": "night", "round_no": 1},
                "announced_in": {"period": "dawn", "round_no": 1},
                "outcome": "deaths",
                "eliminated_player_refs": ["seat_1"],
                "role_revealed": False,
                "known_role": None,
                "identity_reveal": "none",
            },
            {
                "kind": "player_eliminated",
                "source_event_id": "history_3",
                "occurred_in": {"period": "day", "round_no": 1},
                "public_reason": "exile",
                "player_ref": "seat_4",
                "role_revealed": False,
                "known_role": None,
                "identity_reveal": "none",
            },
        ],
    }
    assert projected["history"]["recent_statements"] == [
        {
            "kind": "player_statement",
            "source_event_id": "history_2",
            "occurred_in": {"period": "day", "round_no": 1},
            "stage": "day_debate",
            "speaker_ref": "seat_2",
            "speech": "昨晚1号出局，我怀疑4号。",
        }
    ]
    assert projected["history"]["older_claims"] == []
    assert "information_semantics" not in projected
    assert "player_claims" not in projected
    assert "current_information_summary" not in projected
    assert "role_information_boundaries" not in projected
    assert model_prompt_metadata(projected) == {
        "prompt_schema_version": 2,
        "serialized_char_count": len(
            json.dumps(projected, ensure_ascii=False, separators=(",", ":"))
        ),
        "recent_statement_count": 1,
        "older_claim_count": 0,
    }


def test_model_context_compacts_old_statements_with_source_coverage() -> None:
    quiet_detail = "这段只是当时的语气和铺垫。" * 10
    projected = project_model_action_context(
        {
            "round_no": 3,
            "actor": {"kind": "player", "id": "system-player-01"},
            "candidates": [
                {
                    "player_id": "system-player-09",
                    "seat": 4,
                    "display_name": "唐梨",
                }
            ],
            "public_history": [
                {
                    "source_event_id": 101,
                    "event_type": "day_speech_committed",
                    "payload": {
                        "round_no": 1,
                        "stage": "day_debate",
                        "player_id": "system-player-07",
                        "speech": f"我怀疑3号是狼。{quiet_detail}",
                    },
                },
                {
                    "source_event_id": 102,
                    "event_type": "day_speech_committed",
                    "payload": {
                        "round_no": 2,
                        "stage": "day_debate",
                        "player_id": "system-player-07",
                        "speech": f"我现在保3号是好人。{quiet_detail}",
                    },
                },
                {
                    "source_event_id": 103,
                    "event_type": "day_speech_committed",
                    "payload": {
                        "round_no": 3,
                        "stage": "day_debate",
                        "player_id": "system-player-09",
                        "speech": f"我今天要投2号。{quiet_detail}",
                    },
                },
                {
                    "source_event_id": 104,
                    "event_type": "day_speech_committed",
                    "payload": {
                        "round_no": 3,
                        "stage": "day_debate",
                        "player_id": "system-player-07",
                        "speech": f"我改投4号。{quiet_detail}",
                    },
                },
                {
                    "source_event_id": 105,
                    "event_type": "day_speech_committed",
                    "payload": {
                        "round_no": 3,
                        "stage": "day_debate",
                        "player_id": "system-player-09",
                        "speech": f"我认为1号可信。{quiet_detail}",
                    },
                },
            ],
        },
        players=PLAYERS,
    )

    assert {item["source_event_id"] for item in projected["history"]["recent_statements"]} == {
        "103",
        "104",
        "105",
    }
    assert projected["history"]["older_claims"] == [
        {
            "source_event_id": "101",
            "occurred_in": {"period": "day", "round_no": 1},
            "stage": "day_debate",
            "speaker_ref": "seat_1",
            "mentioned_player_refs": ["seat_3"],
            "exact_claim_fragments": ["我怀疑3号是狼。"],
            "confirmation_status": "unverified",
        },
        {
            "source_event_id": "102",
            "occurred_in": {"period": "day", "round_no": 2},
            "stage": "day_debate",
            "speaker_ref": "seat_1",
            "mentioned_player_refs": ["seat_3"],
            "exact_claim_fragments": ["我现在保3号是好人。"],
            "confirmation_status": "unverified",
        },
    ]
    recent_ids = {item["source_event_id"] for item in projected["history"]["recent_statements"]}
    older_ids = {item["source_event_id"] for item in projected["history"]["older_claims"]}
    assert recent_ids.isdisjoint(older_ids)


def test_model_context_keeps_history_bounded_and_deduplicated() -> None:
    public_history = [
        {
            "source_event_id": index,
            "event_type": "day_speech_committed",
            "payload": {
                "round_no": index // 6 + 1,
                "stage": "day_debate",
                "player_id": "system-player-07",
                "speech": f"我怀疑4号，记录{index}。" + "长发言" * 600,
            },
        }
        for index in range(1, 41)
    ]
    projected = project_model_action_context(
        {
            "action_type": "day_debate_speech",
            "public_history": public_history,
            "output_contract": {
                "kind": "speech",
                "speech": {"mode": "required"},
            },
        },
        players=PLAYERS,
    )

    recent = projected["history"]["recent_statements"]
    older = projected["history"]["older_claims"]
    recent_ids = {item["source_event_id"] for item in recent}
    older_ids = {item["source_event_id"] for item in older}
    assert len(recent) <= 3
    assert sum(len(item["speech"]) for item in recent) <= 5_000
    assert len(older) <= 18
    assert sum(len(claim) for item in older for claim in item["exact_claim_fragments"]) <= 5_000
    assert recent_ids.isdisjoint(older_ids)
    assert model_prompt_metadata(projected)["serialized_char_count"] < 15_000


def test_model_context_uses_every_presented_public_player_speech_without_duplicates() -> None:
    projected = project_model_action_context(
        {
            "round_no": 2,
            "actor": {"kind": "player", "id": "system-player-01"},
            "public_history": [
                {
                    "source_event_id": 10,
                    "event_type": "day_speech_committed",
                    "payload": {
                        "round_no": 1,
                        "stage": "day_debate",
                        "player_id": "system-player-07",
                        "speech": "这条事件副本不应重复进入上下文。",
                    },
                },
                {
                    "source_event_id": 11,
                    "event_type": "public_player_speech_presented",
                    "payload": {
                        "round_no": 1,
                        "stage": "day_debate_speech",
                        "player_id": "system-player-07",
                        "speech": "第一天我怀疑4号。",
                    },
                },
                {
                    "source_event_id": 20,
                    "event_type": "sheriff_badge_transferred",
                    "payload": {
                        "round_no": 2,
                        "player_id": "system-player-01",
                        "from_player_id": "system-player-07",
                    },
                },
                {
                    "source_event_id": 21,
                    "event_type": "public_player_speech_presented",
                    "payload": {
                        "round_no": 2,
                        "stage": "sheriff_badge_resolution",
                        "player_id": "system-player-07",
                        "speech": "我昨夜验了2号，2号是金水。",
                    },
                },
            ],
        },
        players=PLAYERS,
    )

    assert projected["history"]["recent_statements"] == [
        {
            "kind": "player_statement",
            "source_event_id": "11",
            "occurred_in": {"period": "day", "round_no": 1},
            "stage": "day_debate_speech",
            "speaker_ref": "seat_1",
            "speech": "第一天我怀疑4号。",
        },
        {
            "kind": "player_statement",
            "source_event_id": "21",
            "occurred_in": {"period": "day", "round_no": 2},
            "stage": "sheriff_badge_resolution",
            "speaker_ref": "seat_1",
            "speech": "我昨夜验了2号，2号是金水。",
        },
    ]
    assert projected["history"]["older_claims"] == []


def test_model_target_and_speech_are_mapped_back_to_internal_identity() -> None:
    assert resolve_model_target("seat_4", players=PLAYERS) == "system-player-09"
    assert resolve_model_target("seat_3", players=PLAYERS) is None
    assert (
        sanitize_model_speech(
            "我建议查验唐梨，不要把system-player-07当成7号。",
            players=PLAYERS,
        )
        == "我建议查验4号，不要把seat_1当成7号。"
    )


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
    assert contract["sheriff_rule"] == ("本局不启用警长系统，不存在上警、警徽或警徽流机制。")
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
        "successful_protection_effect": ("若守护目标当夜受到狼人攻击，该目标不会因这次攻击出局。"),
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
            "prompt_schema_version": 2,
            "hard_rules": {"werewolf_count": 1},
            "self": {"private_judge_facts": []},
            "public_state": {},
            "history": {"recent_statements": [], "older_claims": []},
            "output_contract": {
                "kind": "speech",
                "speech": {"mode": "required"},
            },
        },
        decision=True,
        model_id="test-model",
    )
    system_text = payload["input"][0]["content"][0]["text"]

    assert "hard_rules" in system_text
    assert "self 中的法官私密信息" in system_text
    assert "public_state 是权威事实" in system_text
    assert "history 只是玩家公开说法" in system_text
    assert "你可以自主判断、伪装身份和制定策略" in system_text
    assert "不得使用未提供的私密信息" in system_text
    assert "role_information_boundaries" not in system_text
    assert "current_information_summary" not in system_text
    assert len(system_text) < 350


def test_actor_information_composes_role_and_sheriff_capabilities() -> None:
    rule = {
        "sheriff_enabled": True,
        "sheriff_vote_weight": 1.5,
        "speech_policy": "sheriff_directed",
        "werewolf_self_explosion_enabled": True,
    }
    seer_sheriff = build_actor_information(
        player_id="system-player-01",
        seat=2,
        role_key="seer",
        team="villagers",
        persona={},
        alive=True,
        sheriff_player_id="system-player-01",
        sheriff_badge_state="held",
        rule=rule,
    )
    villager_sheriff = build_actor_information(
        player_id="system-player-07",
        seat=1,
        role_key="villager",
        team="villagers",
        persona={},
        alive=True,
        sheriff_player_id="system-player-07",
        sheriff_badge_state="held",
        rule=rule,
    )

    assert [item["ability_id"] for item in seer_sheriff["role_capabilities"]["abilities"]] == [
        "seer.investigate"
    ]
    assert [
        item["authority_id"] for item in seer_sheriff["public_office_capabilities"]["abilities"]
    ] == [
        "sheriff.weighted_exile_vote",
        "sheriff.choose_speech_order",
        "sheriff.resolve_badge_after_death",
    ]
    assert villager_sheriff["role_capabilities"]["abilities"] == []
    assert villager_sheriff["public_office_capabilities"]["is_current_sheriff"] is True


def test_actor_information_uses_count_aware_werewolf_capability_wording() -> None:
    base_rule = {
        "sheriff_enabled": False,
        "roles": [
            {"role": "狼人", "count": 1, "team": "werewolves"},
            {"role": "村民", "count": 5, "team": "villagers"},
        ],
    }
    single = build_actor_information(
        player_id="system-player-01",
        seat=2,
        role_key="werewolf",
        team="werewolves",
        persona={},
        alive=True,
        sheriff_player_id=None,
        sheriff_badge_state="disabled",
        rule=base_rule,
    )
    multiple = build_actor_information(
        player_id="system-player-01",
        seat=2,
        role_key="werewolf",
        team="werewolves",
        persona={},
        alive=True,
        sheriff_player_id=None,
        sheriff_badge_state="disabled",
        rule={
            **base_rule,
            "roles": [
                {"role": "狼人", "count": 2, "team": "werewolves"},
                {"role": "村民", "count": 4, "team": "villagers"},
            ],
        },
    )

    single_description = single["role_capabilities"]["abilities"][0]["description"]
    multiple_description = multiple["role_capabilities"]["abilities"][0]["description"]
    assert "本局唯一狼人，独自选择" in single_description
    assert "队友" not in single_description
    assert "存活狼人队友共同选择" in multiple_description


def test_actor_information_separates_owned_abilities_from_consumed_resources() -> None:
    rule = {
        "sheriff_enabled": True,
        "werewolf_self_explosion_enabled": True,
    }
    private_facts = [
        {
            "fact_type": "private_ability_action_committed",
            "payload": {
                "ability_id": "witch.heal",
                "night_no": 1,
                "decision": {"target_player_id": "system-player-07"},
                "result": {"heal_used": True},
            },
        }
    ]
    day_information = build_actor_information(
        player_id="system-player-01",
        seat=2,
        role_key="witch",
        team="villagers",
        persona={},
        alive=True,
        sheriff_player_id=None,
        sheriff_badge_state="held",
        rule=rule,
        private_facts=private_facts,
        current_action_type="day_debate_speech",
    )
    night_information = build_actor_information(
        player_id="system-player-01",
        seat=2,
        role_key="witch",
        team="villagers",
        persona={},
        alive=True,
        sheriff_player_id=None,
        sheriff_badge_state="held",
        rule=rule,
        private_facts=private_facts,
        current_action_type="ability_witch.poison_decision",
        current_action_knowledge={"poison_remaining": 1},
    )

    assert [item["ability_id"] for item in day_information["role_capabilities"]["abilities"]] == [
        "witch.heal",
        "witch.poison",
    ]
    day_runtime = {
        item["ability_id"]: item for item in day_information["ability_runtime_state"]["abilities"]
    }
    assert day_runtime["witch.heal"]["resource_status"] == "consumed"
    assert day_runtime["witch.heal"]["remaining_uses"] == 0
    assert day_runtime["witch.heal"]["can_execute_now"] is False
    assert day_runtime["witch.heal"]["last_committed_action"]["result"] == {"heal_used": True}
    assert day_runtime["witch.poison"]["resource_status"] == "available"
    assert day_runtime["witch.poison"]["can_execute_now"] is False

    night_runtime = {
        item["ability_id"]: item for item in night_information["ability_runtime_state"]["abilities"]
    }
    assert night_runtime["witch.heal"]["resource_status"] == "consumed"
    assert night_runtime["witch.poison"]["remaining_uses"] == 1
    assert night_runtime["witch.poison"]["in_current_action_window"] is True
    assert night_runtime["witch.poison"]["can_execute_now"] is True


def test_model_context_states_single_wolf_rule_without_generic_teammate_prompt() -> None:
    rule_contract = build_public_rule_contract(
        rule={
            "id": "role-boundaries",
            "name": "角色信息边界",
            "version": "1",
            "player_count": 3,
            "roles": [
                {"role": "狼人", "count": 1, "team": "werewolves"},
                {"role": "预言家", "count": 1, "team": "villagers"},
                {"role": "女巫", "count": 1, "team": "villagers"},
            ],
            "ability_policies": {},
        },
        max_rounds=8,
    )
    projected = project_model_action_context(
        {
            "action_type": "day_debate_speech",
            "self_identity": {
                "player_id": "system-player-01",
                "seat": 2,
                "role_key": "werewolf",
                "team": "werewolves",
            },
            "private_authoritative_facts": [
                {
                    "fact_type": "werewolf_teammates",
                    "payload": ["system-player-01"],
                }
            ],
            "output_contract": {
                "kind": "speech",
                "speech": {"mode": "required"},
            },
            "public_rule_contract": rule_contract,
            "public_history": [],
        },
        players=PLAYERS,
    )

    assert projected["hard_rules"]["werewolf_count"] == 1
    assert projected["hard_rules"]["ability_rules"]["werewolf_attack"]["coordination"] == "solo"
    assert (
        "can_target_werewolf_teammates"
        not in projected["hard_rules"]["ability_rules"]["werewolf_attack"]
    )
    assert projected["self"]["werewolf_coordination"] == {"mode": "solo"}
    assert "role_information_boundaries" not in projected
    assert "狼人队友" not in json.dumps(projected, ensure_ascii=False)


def test_model_context_separates_reveals_claims_and_vote_snapshot() -> None:
    projected = project_model_action_context(
        {
            "self_identity": {
                "player_id": "system-player-01",
                "role_key": "seer",
                "team": "villagers",
            },
            "role_capabilities": {"abilities": [{"ability_id": "seer.investigate"}]},
            "public_office_capabilities": {
                "is_current_sheriff": True,
                "abilities": [{"authority_id": "sheriff.weighted_exile_vote"}],
            },
            "public_history": [
                {
                    "source_event_id": "claim-1",
                    "event_type": "day_speech_committed",
                    "payload": {
                        "round_no": 1,
                        "stage": "day_debate",
                        "player_id": "system-player-09",
                        "speech": "我是预言家，2号是我的金水。",
                    },
                },
                {
                    "source_event_id": "vote-1",
                    "event_type": "day_vote_resolved",
                    "payload": {
                        "round_no": 1,
                        "action_type": "exile_vote",
                        "eligible_voter_ids": [
                            "system-player-01",
                            "system-player-09",
                        ],
                        "ineligible_voter_ids": ["system-player-07"],
                        "candidate_player_ids": [
                            "system-player-01",
                            "system-player-09",
                        ],
                        "weighted": True,
                        "sheriff_player_id": "system-player-01",
                        "sheriff_vote_weight": 1.5,
                        "voter_weights": {
                            "system-player-01": 1.5,
                            "system-player-09": 1.0,
                        },
                        "totals": {"system-player-09": 1.5},
                        "leaders": ["system-player-09"],
                    },
                },
                {
                    "source_event_id": "exile-1",
                    "event_type": "player_exiled",
                    "payload": {
                        "round_no": 1,
                        "player_id": "system-player-09",
                    },
                },
                {
                    "source_event_id": "bomb-1",
                    "event_type": "werewolf_self_exploded",
                    "payload": {
                        "round_no": 1,
                        "player_id": "system-player-07",
                        "stage": "day_debate",
                    },
                },
            ],
        },
        players=PLAYERS,
    )

    assert projected["history"]["recent_statements"][0]["speech"] == ("我是预言家，2号是我的金水。")
    assert projected["public_state"]["role_confirmations"] == [
        {
            "source_event_id": "bomb-1",
            "player_ref": "seat_1",
            "role_key": "werewolf",
            "confirmation_reason": "werewolf_self_explosion",
            "confirmation_status": "confirmed_by_judge",
        }
    ]
    vote_snapshot = projected["public_state"]["latest_vote_snapshot"]
    assert vote_snapshot["eligible_voter_refs"] == [
        "seat_2",
        "seat_4",
    ]
    assert vote_snapshot["ineligible_voter_refs"] == ["seat_1"]
    assert vote_snapshot["voter_weights"] == {
        "seat_2": 1.5,
        "seat_4": 1.0,
    }
    assert vote_snapshot["totals"] == {"seat_4": 1.5}
    assert "canonical_public_timeline" not in projected
    assert "public_event_counters" not in projected
    assert "current_information_summary" not in projected
    exile_fact = next(
        item
        for item in projected["public_state"]["judge_facts"]
        if item.get("public_reason") == "exile"
    )
    assert exile_fact["role_revealed"] is False
    assert exile_fact["known_role"] is None
