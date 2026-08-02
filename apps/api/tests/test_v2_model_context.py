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
    project_model_action_context_with_metadata,
    resolve_model_target,
    sanitize_model_speech,
)
from app.v2.model_client import build_model_request_payload
from app.v2.model_context_contract import (
    legacy_v7_model_context_contract,
    legacy_v8_prompt_v1_model_context_contract,
)


PLAYERS = (
    V2ModelPlayerReference("system-player-07", 1, "乔宁"),
    V2ModelPlayerReference("system-player-01", 2, "沈砚"),
    V2ModelPlayerReference("system-player-09", 4, "唐梨"),
)


def _history_claims(projected: dict[str, object]) -> list[dict[str, object]]:
    history = projected["history"]
    assert isinstance(history, dict)
    timeline = history["timeline"]
    assert isinstance(timeline, list)
    return [
        {
            **annotation,
            "source_event_id": statement["source_event_id"],
            "speaker_ref": statement["speaker_ref"],
            **(
                {"uttered_record_seq": statement["record_seq"]} if "record_seq" in statement else {}
            ),
        }
        for statement in timeline
        if isinstance(statement, dict)
        for annotation in statement.get("annotations", [])
        if isinstance(annotation, dict)
    ]


def test_model_context_uses_only_seat_references_and_unifies_public_events() -> None:
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
    assert projected["model_context_schema_version"] == 8
    assert projected["prompt_template_version"] == 2
    assert projected["task"]["goal"] == "2号需要判断4号是否可信"
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
    private_fact = next(
        event
        for event in projected["known_events"]["events"]
        if event["visibility"] == "actor_private"
    )
    assert private_fact == {
        "event_ref": "current_private_fact_1",
        "kind": "investigation_alignment",
        "authority": "judge_fact",
        "visibility": "actor_private",
        "record_seq": 1,
        "known_at_seq": 1,
        "occurred_in": {"period": "night", "round_no": 1},
        "data": {
            "target_player_id": "seat_4",
            "alignment": "werewolves",
            "night_no": 1,
        },
    }
    assert projected["state"] == {
        "round_no": 1,
        "alive_player_count": 2,
        "alive_player_ids": ["seat_2", "seat_4"],
        "eliminated_player_count": 1,
        "eliminated_player_ids": ["seat_1"],
        "identity_information_included": False,
        "as_of_seq": 1,
    }
    public_events = [
        event for event in projected["known_events"]["events"] if event["visibility"] == "public"
    ]
    assert [item["kind"] for item in public_events] == [
        "night_result",
        "player_statement",
        "player_eliminated",
    ]
    assert [item["timeline_index"] for item in public_events] == [1, 2, 3]
    assert public_events[0]["authority"] == "judge_fact"
    assert public_events[1]["authority"] == "player_statement"
    assert public_events[1]["speaker_ref"] == "seat_2"
    assert public_events[1]["speech"] == "昨晚1号出局，我怀疑4号。"
    assert public_events[1]["event_ref"] == "history_2"
    assert public_events[2]["public_reason"] == "exile"
    assert public_events[2]["role_revealed"] is False
    assert projected["known_events"]["schema_version"] == 1
    assert "history" not in projected
    assert "public_timeline" not in projected
    assert "source_rules" not in serialized
    assert "annotations" not in serialized
    metadata = model_prompt_metadata(projected)
    assert metadata["prompt_schema_version"] is None
    assert metadata["model_context_schema_version"] == 8
    assert metadata["prompt_template_version"] == 2
    assert metadata["serialized_char_count"] == len(
        json.dumps(projected, ensure_ascii=False, separators=(",", ":"))
    )


def test_model_context_orders_sheriff_plan_before_later_votes_on_one_clock() -> None:
    players = tuple(
        V2ModelPlayerReference(
            player_id=f"system-player-{seat:02d}",
            seat=seat,
            display_name=f"{seat}号玩家",
        )
        for seat in (2, 5, 6, 7, 8)
    )
    projected = project_model_action_context(
        {
            "round_no": 1,
            "action_type": "day_debate_speech",
            "self_identity": {
                "player_id": "system-player-08",
                "seat": 8,
                "role_key": "werewolf",
                "team": "werewolves",
            },
            "public_history": [
                {
                    "source_event_id": 448,
                    "record_seq": 448,
                    "event_type": "public_player_speech_presented",
                    "payload": {
                        "round_no": 1,
                        "stage": "sheriff_campaign_speech",
                        "player_id": "system-player-06",
                        "speech": "警徽流：今晚验2号，明晚验5号。",
                    },
                },
                {
                    "source_event_id": 562,
                    "record_seq": 562,
                    "event_type": "day_vote_committed",
                    "payload": {
                        "round_no": 1,
                        "action_type": "sheriff_vote",
                        "voter_player_id": "system-player-02",
                        "target_player_id": "system-player-07",
                        "weight": 1.0,
                    },
                },
                {
                    "source_event_id": 564,
                    "record_seq": 564,
                    "event_type": "day_vote_committed",
                    "payload": {
                        "round_no": 1,
                        "action_type": "sheriff_vote",
                        "voter_player_id": "system-player-05",
                        "target_player_id": "system-player-07",
                        "weight": 1.0,
                    },
                },
            ],
        },
        players=players,
    )

    events = projected["known_events"]["events"]
    assert [(item["record_seq"], item["kind"]) for item in events] == [
        (448, "player_statement"),
        (562, "day_vote"),
        (564, "day_vote"),
    ]
    assert events[0]["event_ref"] == "448"
    assert events[0]["speech"] == "警徽流：今晚验2号，明晚验5号。"
    assert [
        (item["voter_ref"], item["target_ref"]) for item in events if item["kind"] == "day_vote"
    ] == [
        ("seat_2", "seat_7"),
        ("seat_5", "seat_7"),
    ]
    assert "judge_facts" not in projected["state"]
    assert projected["task"]["at_seq"] == 565
    projection = project_model_action_context_with_metadata(
        {
            "round_no": 1,
            "action_type": "day_debate_speech",
            "self_identity": {
                "player_id": "system-player-08",
                "seat": 8,
                "role_key": "werewolf",
                "team": "werewolves",
            },
            "public_history": [
                {
                    "source_event_id": event["source_event_id"],
                    "record_seq": event["record_seq"],
                    "event_type": (
                        "public_player_speech_presented"
                        if event["kind"] == "player_statement"
                        else "day_vote_committed"
                    ),
                    "payload": (
                        {
                            "round_no": 1,
                            "stage": "sheriff_campaign_speech",
                            "player_id": "system-player-06",
                            "speech": "警徽流：今晚验2号，明晚验5号。",
                        }
                        if event["kind"] == "player_statement"
                        else {
                            "round_no": 1,
                            "action_type": "sheriff_vote",
                            "voter_player_id": (
                                "system-player-02"
                                if event["record_seq"] == 562
                                else "system-player-05"
                            ),
                            "target_player_id": "system-player-07",
                            "weight": 1.0,
                        }
                    ),
                }
                for event in events
            ],
        },
        players=players,
    )
    assert projection.projection_metadata["known_event_record_seq_min"] == 448
    assert projection.projection_metadata["known_event_record_seq_max"] == 564
    assert projection.projection_metadata["known_event_count"] == 3


def test_model_context_projects_current_speech_position_and_remaining_speakers() -> None:
    projected = project_model_action_context(
        {
            "round_no": 1,
            "action_type": "day_debate_speech",
            "self_identity": {
                "player_id": "system-player-01",
                "seat": 2,
                "role_key": "villager",
                "team": "villagers",
            },
            "speech_order": [
                "system-player-09",
                "system-player-01",
                "system-player-07",
            ],
        },
        players=PLAYERS,
    )

    assert projected["task"]["speech_order"] == ["seat_4", "seat_2", "seat_1"]
    assert projected["task"]["speech_progress"] == {
        "current_speaker_ref": "seat_2",
        "current_position": 2,
        "total_speakers": 3,
        "scheduled_before_refs": ["seat_4"],
        "remaining_speaker_refs": ["seat_1"],
    }


def test_public_timeline_preserves_input_order_for_legacy_duplicate_sequence() -> None:
    projected = project_model_action_context(
        {
            "self_identity": {
                "player_id": "system-player-01",
                "seat": 2,
                "role_key": "seer",
                "team": "villagers",
            },
            "public_history": [
                {
                    "source_event_id": 562,
                    "record_seq": 562,
                    "event_type": "day_vote_committed",
                    "payload": {
                        "voter_player_id": "system-player-01",
                        "target_player_id": "system-player-09",
                    },
                },
                {
                    "source_event_id": "legacy-duplicate",
                    "record_seq": 562,
                    "event_type": "day_vote_committed",
                    "payload": {
                        "voter_player_id": "system-player-09",
                        "target_player_id": "system-player-01",
                    },
                },
            ],
        },
        players=PLAYERS,
    )

    assert [
        (event["source_event_id"], event["timeline_index"])
        for event in projected["known_events"]["events"]
    ] == [("562", 1), ("legacy-duplicate", 2)]
    assert "source_rules" not in json.dumps(projected, ensure_ascii=False)


def test_v8_known_events_places_private_investigation_before_later_public_speech() -> None:
    players = tuple(
        V2ModelPlayerReference(
            player_id=f"system-player-{seat:02d}",
            seat=seat,
            display_name=f"{seat}号玩家",
        )
        for seat in (6, 8)
    )
    projected = project_model_action_context(
        {
            "round_no": 1,
            "action_type": "sheriff_campaign_speech",
            "objective": "发表警长竞选发言。",
            "self_identity": {
                "player_id": "system-player-08",
                "seat": 8,
                "role_key": "seer",
                "team": "villagers",
            },
            "private_authoritative_facts": [
                {
                    "knowledge_fact_id": "knowledge-seer-night-1",
                    "source_activation_id": "activation-seer-night-1",
                    "fact_type": "private_ability_action_committed",
                    "record_seq": 258,
                    "known_at_seq": 258,
                    "occurred_in": {"period": "night", "round_no": 1},
                    "payload": {
                        "ability_id": "seer.investigate",
                        "night_no": 1,
                        "decision": {
                            "target_player_id": "system-player-06",
                            "decision_note": "在任何警上发言前已决定查验6号。",
                        },
                        "result": {
                            "target_player_id": "system-player-06",
                            "alignment": "werewolves",
                        },
                    },
                }
            ],
            "public_history": [
                {
                    "source_event_id": 472,
                    "record_seq": 472,
                    "event_type": "public_player_speech_presented",
                    "payload": {
                        "round_no": 1,
                        "stage": "sheriff_campaign_speech",
                        "player_id": "system-player-06",
                        "speech": "6号上警，我先听后置位怎么说。",
                    },
                }
            ],
        },
        players=players,
        action_record_seq=501,
    )

    events = projected["known_events"]["events"]
    assert [(event["event_ref"], event["known_at_seq"]) for event in events] == [
        ("knowledge-seer-night-1", 258),
        ("472", 472),
    ]
    assert events[0]["visibility"] == "actor_private"
    assert events[0]["data"]["decision"] == {
        "target_player_id": "seat_6",
        "decision_note": "在任何警上发言前已决定查验6号。",
    }
    assert events[1]["speaker_ref"] == "seat_6"
    assert projected["task"]["at_seq"] == 501
    assert projected["state"]["as_of_seq"] == 501
    assert events[0]["known_at_seq"] < events[1]["known_at_seq"] < projected["task"]["at_seq"]


def test_v8_prompt_separates_event_occurrence_from_delayed_announcement() -> None:
    action_context = {
        "round_no": 1,
        "action_type": "first_night_last_words",
        "objective": "发表首夜遗言；你不知道具体死亡原因。",
        "self_identity": {
            "player_id": "system-player-07",
            "seat": 1,
            "role_key": "seer",
            "team": "villagers",
        },
        "public_history": [
            {
                "source_event_id": 608,
                "record_seq": 608,
                "event_type": "sheriff_elected",
                "payload": {
                    "round_no": 1,
                    "player_id": "system-player-07",
                    "from_player_id": None,
                    "reason": "sheriff_vote_unique_leader",
                },
            },
            {
                "source_event_id": 624,
                "record_seq": 624,
                "event_type": "dawn_public_result",
                "payload": {
                    "round_no": 1,
                    "dead_player_ids": ["system-player-07"],
                },
            },
        ],
        "output_contract": {
            "kind": "speech",
            "speech": {"mode": "required", "max_chars": 200},
        },
    }
    projected = project_model_action_context(
        action_context,
        players=PLAYERS,
        action_record_seq=639,
    )

    events = projected["known_events"]["events"]
    assert [(event["event_ref"], event["known_at_seq"]) for event in events] == [
        ("608", 608),
        ("624", 624),
    ]
    assert events[0]["kind"] == "sheriff_elected"
    assert events[0]["occurred_in"] == {"period": "day", "round_no": 1}
    assert events[1]["kind"] == "night_result"
    assert events[1]["occurred_in"] == {"period": "night", "round_no": 1}
    assert events[1]["announced_in"] == {"period": "dawn", "round_no": 1}

    request = build_model_request_payload(projected, decision=True, model_id="test-model")
    system_text = request["input"][0]["content"][0]["text"]
    assert projected["prompt_template_version"] == 2
    assert "known_at_seq/record_seq 表示信息何时被记录或获知" in system_text
    assert "occurred_in 表示事件实际发生阶段" in system_text
    assert "announced_in 只表示公布阶段，公布更晚不代表发生更晚" in system_text
    assert "带 seq 的信息按 seq 判断先后" not in system_text
    assert len(system_text) < 400

    legacy_projected = project_model_action_context(
        action_context,
        players=PLAYERS,
        model_context_contract=legacy_v8_prompt_v1_model_context_contract(),
        action_record_seq=639,
    )
    legacy_request = build_model_request_payload(
        legacy_projected,
        decision=True,
        model_id="test-model",
    )
    legacy_system_text = legacy_request["input"][0]["content"][0]["text"]
    assert legacy_projected["prompt_template_version"] == 1
    assert "带 seq 的信息按 seq 判断先后" in legacy_system_text
    assert "公布更晚不代表发生更晚" not in legacy_system_text


def test_legacy_v7_contract_keeps_legacy_projection_shape() -> None:
    projected = project_model_action_context(
        {
            "action_type": "day_debate_speech",
            "objective": "发表白天发言。",
            "self_identity": {
                "player_id": "system-player-01",
                "seat": 2,
                "role_key": "villager",
                "team": "villagers",
            },
            "public_history": [],
            "output_contract": {
                "kind": "speech",
                "speech": {"mode": "required"},
            },
        },
        players=PLAYERS,
        model_context_contract=legacy_v7_model_context_contract(),
    )

    assert projected["prompt_schema_version"] == 7
    assert projected["task"]["action_type"] == "day_debate_speech"
    assert projected["output_contract"]["kind"] == "speech"
    assert "history" in projected
    assert "public_timeline" in projected
    assert "known_events" not in projected


def test_model_context_keeps_every_round_exact_and_structured_by_reference() -> None:
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

    events = projected["known_events"]["events"]
    assert {item["source_event_id"] for item in events} == {
        "101",
        "102",
        "103",
        "104",
        "105",
    }
    assert next(item for item in events if item["source_event_id"] == "101")["speech"].endswith(
        quiet_detail
    )
    assert "annotations" not in json.dumps(projected, ensure_ascii=False)


def test_model_context_keeps_history_lossless_and_deduplicated() -> None:
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
    projection = project_model_action_context_with_metadata(
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

    projected = projection.context
    events = projected["known_events"]["events"]
    metadata = projection.projection_metadata
    assert metadata["ledger_statement_count"] == 40
    assert metadata["known_event_total_count"] == 40
    assert metadata["known_event_count"] < 40
    assert metadata["dropped_event_count"] > 0
    assert metadata["dropped_event_refs"]
    assert set(metadata["retained_event_refs"]).isdisjoint(metadata["dropped_event_refs"])
    assert all("speech_truncated" not in item for item in events)
    assert all(len(item["speech"]) > 1_800 for item in events)
    assert metadata["selection_budget_exceeded_by_required"] is True
    assert (
        model_prompt_metadata(
            projected,
            projection_metadata=metadata,
        )["serialized_char_count"]
        < 20_000
    )


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

    events = projected["known_events"]["events"]
    assert [statement["source_event_id"] for statement in events] == [
        "11",
        "20",
        "21",
    ]
    assert events[2]["speech"] == "我昨夜验了2号，2号是金水。"
    transfer = next(event for event in events if event["kind"] == "sheriff_badge_transferred")
    assert transfer["source_event_id"] == "20"
    assert transfer["authority"] == "judge_fact"
    assert transfer["payload"] == {
        "round_no": 2,
        "player_id": "seat_2",
        "from_player_id": "seat_1",
    }
    assert events[0]["speech"] == "第一天我怀疑4号。"
    assert "这条事件副本不应重复进入上下文" not in json.dumps(
        projected,
        ensure_ascii=False,
    )


def test_model_context_preserves_first_party_claim_time_before_later_paraphrases() -> None:
    players = tuple(
        V2ModelPlayerReference(
            f"system-player-{seat:02d}",
            seat,
            f"{seat}号玩家",
        )
        for seat in (6, 8, 9, 10, 11, 12)
    )
    projected = project_model_action_context(
        {
            "round_no": 1,
            "actor": {"kind": "player", "id": "system-player-12"},
            "public_history": [
                {
                    "source_event_id": 400,
                    "record_seq": 400,
                    "event_type": "public_player_speech_presented",
                    "payload": {
                        "round_no": 1,
                        "stage": "sheriff_campaign_speech",
                        "player_id": "system-player-06",
                        "speech": "6号上警，我先听后置位怎么说。",
                    },
                },
                {
                    "source_event_id": 417,
                    "record_seq": 417,
                    "event_type": "public_player_speech_presented",
                    "payload": {
                        "round_no": 1,
                        "stage": "sheriff_campaign_speech",
                        "player_id": "system-player-08",
                        "speech": (
                            "8号上警竞选，底牌预言家，昨晚验6号，查杀。"
                            "现在回头看6号刚才的发言，我认为他在带节奏。"
                        ),
                    },
                },
                {
                    "source_event_id": 597,
                    "record_seq": 597,
                    "event_type": "public_player_speech_presented",
                    "payload": {
                        "round_no": 1,
                        "stage": "day_debate_speech",
                        "player_id": "system-player-09",
                        "speech": "8号因为6号发言带节奏，所以昨晚验了6号。",
                    },
                },
                {
                    "source_event_id": 620,
                    "record_seq": 620,
                    "event_type": "public_player_speech_presented",
                    "payload": {
                        "round_no": 1,
                        "stage": "day_debate_speech",
                        "player_id": "system-player-10",
                        "speech": "9号转述说8号验6号是因为6号发言像狼。",
                    },
                },
                {
                    "source_event_id": 637,
                    "record_seq": 637,
                    "event_type": "public_player_speech_presented",
                    "payload": {
                        "round_no": 1,
                        "stage": "day_debate_speech",
                        "player_id": "system-player-11",
                        "speech": "8号警上已经说了，因为6号发言像带节奏才验6号。",
                    },
                },
            ],
        },
        players=players,
    )

    events = projected["known_events"]["events"]
    assert [(item["speaker_ref"], item["record_seq"]) for item in events] == [
        ("seat_6", 400),
        ("seat_8", 417),
        ("seat_9", 597),
        ("seat_10", 620),
        ("seat_11", 637),
    ]
    assert events[1]["speech"].startswith("8号上警竞选，底牌预言家，昨晚验6号，查杀。")
    assert events[2]["speech"] == "8号因为6号发言带节奏，所以昨晚验了6号。"
    assert all(event["authority"] == "player_statement" for event in events)
    assert "annotations" not in json.dumps(projected, ensure_ascii=False)
    assert "source_rules" not in json.dumps(projected, ensure_ascii=False)


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
            "resolution": "unanimous_no_attack",
            "allow_no_attack": False,
            "allow_wolf_target": False,
        },
        "single_werewolf_resolution": (
            "本局只有1名狼人时，由该狼人直接作出最终选择，不会发生团队平票。"
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


def test_legacy_v7_player_prompt_explains_information_sources_without_forcing_strategy() -> None:
    payload = build_model_request_payload(
        {
            "prompt_schema_version": 7,
            "hard_rules": {"werewolf_count": 1},
            "self": {"private_judge_facts": []},
            "public_state": {},
            "public_timeline": {
                "schema_version": 1,
                "source_rules": {},
                "events": [],
            },
            "history": {
                "ledger_schema_version": 2,
                "model_view_schema_version": 2,
                "source_rules": {},
                "current_round_no": 1,
                "timeline": [],
                "questions": [],
                "relations": [],
                "focus": {},
            },
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
    assert "public_state 是当前权威事实" in system_text
    assert "public_timeline.events 是全部公开事件的唯一时间轴" in system_text
    assert "后发生事件只能用于事后评价" in system_text
    assert "history 是从该时间轴派生的玩家发言与话语标注" in system_text
    assert "statement_ref 对应 history.timeline 的 source_event_id" in system_text
    assert "你可以自主判断、伪装身份和制定策略" in system_text
    assert "不得使用未提供的私密信息" in system_text
    assert "role_information_boundaries" not in system_text
    assert "current_information_summary" not in system_text
    assert len(system_text) < 500


def test_v8_player_prompt_is_short_and_leaves_strategy_to_the_model() -> None:
    payload = build_model_request_payload(
        {
            "model_context_schema_version": 8,
            "prompt_template_version": 2,
            "task": {"type": "day_debate_speech", "goal": "发表本轮白天讨论发言。"},
            "self": {"identity": {"player_id": "seat_2", "role_key": "seer"}},
            "rules": {"reveal_policy": "hidden"},
            "state": {"round_no": 1, "as_of_seq": 472},
            "known_events": {"schema_version": 1, "events": []},
            "response": {"kind": "speech", "speech": {"mode": "required"}},
        },
        decision=True,
        model_id="test-model",
    )
    system_text = payload["input"][0]["content"][0]["text"]

    assert "法官事实可信" in system_text
    assert "公布更晚不代表发生更晚" in system_text
    assert "策略、身份伪装和表达由你自主决定" in system_text
    assert "不得使用未提供的私密信息" in system_text
    assert "public_timeline" not in system_text
    assert "history" not in system_text
    assert "source_rules" not in system_text
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

    assert projected["rules"]["werewolf_count"] == 1
    assert "ability_rules" not in projected["rules"]
    assert "current_ability" not in projected["rules"]
    assert projected["self"]["werewolf_coordination"] == {"mode": "solo"}
    assert projected["known_events"]["events"] == []
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

    public_events = projected["known_events"]["events"]
    assert public_events[0]["speech"] == "我是预言家，2号是我的金水。"
    assert projected["state"]["as_of_seq"] == 1
    vote_snapshot = next(item for item in public_events if item["kind"] == "vote_result")
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
    exile_fact = next(item for item in public_events if item.get("public_reason") == "exile")
    assert exile_fact["role_revealed"] is False
    assert "known_role" not in exile_fact
    explosion = next(
        item for item in public_events if item.get("public_reason") == "self_explosion"
    )
    assert explosion["player_ref"] == "seat_1"
    assert explosion["known_role"] == "werewolf"
    assert "history" not in projected
    assert "public_timeline" not in projected
