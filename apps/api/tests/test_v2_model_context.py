from __future__ import annotations

import json

from app.v2.model_context import (
    V2ModelPlayerReference,
    project_model_action_context,
    resolve_model_target,
    sanitize_model_speech,
)


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
