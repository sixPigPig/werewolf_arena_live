from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.v2.model_client import build_model_request_payload
from app.v2.model_context import (
    V2ModelPlayerReference,
    project_model_action_context_with_metadata,
)
from app.v2.model_context_contract import (
    legacy_v8_prompt_v1_model_context_contract,
)


_FIXTURE = Path(__file__).parent / "fixtures" / "v2_model_context_v8_eval.json"


def _cases() -> dict[str, dict[str, Any]]:
    payload = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    assert payload["schema_version"] == 1
    return {item["case_id"]: item for item in payload["cases"]}


def test_t01_private_action_and_public_speech_share_one_model_visible_clock() -> None:
    case = _cases()["T01_private_action_before_public_speech"]
    players = tuple(
        V2ModelPlayerReference(
            player_id=item["player_id"],
            seat=item["seat"],
            display_name=f"{item['seat']}号",
        )
        for item in case["players"]
    )
    projection = project_model_action_context_with_metadata(
        case["context"],
        players=players,
        model_context_contract=legacy_v8_prompt_v1_model_context_contract(),
        action_record_seq=case["action_record_seq"],
    )
    context = projection.context
    events = context["known_events"]["events"]

    assert [event["event_ref"] for event in events] == case["expect"]["event_refs"]
    assert [event["known_at_seq"] for event in events] == case["expect"]["event_sequences"]
    assert events[0]["known_at_seq"] < events[1]["known_at_seq"] < context["task"]["at_seq"]
    assert context["task"]["goal"] == "发表警长竞选发言。"
    assert (
        projection.projection_metadata["serialized_char_count"]
        <= case["expect"]["max_serialized_chars"]
    )
    assert not {
        "hard_rules",
        "history",
        "output_contract",
        "public_timeline",
    }.intersection(context)

    request = build_model_request_payload(
        context,
        decision=True,
        model_id="eval-model",
    )
    system_text = request["input"][0]["content"][0]["text"]
    assert len(system_text) < 350
    assert "public_timeline" not in system_text
    assert "history" not in system_text


def test_t02_history_is_lossless_without_a_retention_budget() -> None:
    case = _cases()["T02_lossless_history"]
    public_history = [
        {
            "source_event_id": index,
            "record_seq": index,
            "event_type": "day_speech_committed",
            "payload": {
                "round_no": index // 6 + 1,
                "stage": "day_debate",
                "player_id": "system-player-07",
                "speech": f"记录{index}。" + "长" * case["speech_chars"],
            },
        }
        for index in range(1, case["history_count"] + 1)
    ]
    projection = project_model_action_context_with_metadata(
        {
            "action_type": "day_debate_speech",
            "round_no": case["current_round_no"],
            "self_identity": {
                "player_id": "system-player-01",
                "seat": 2,
                "role_key": "villager",
                "team": "villagers",
            },
            "public_history": public_history,
            "output_contract": {
                "kind": "speech",
                "speech": {"mode": "required", "max_chars": 300},
            },
        },
        players=(
            V2ModelPlayerReference("system-player-07", 1, "1号"),
            V2ModelPlayerReference("system-player-01", 2, "2号"),
        ),
        model_context_contract=legacy_v8_prompt_v1_model_context_contract(),
        action_record_seq=100,
    )
    metadata = projection.projection_metadata

    assert metadata["known_event_total_count"] == case["history_count"]
    assert metadata["known_event_count"] == metadata["known_event_total_count"]
    assert metadata["dropped_event_count"] == 0
    assert "selection_budget_chars" not in metadata
    assert "retained_event_refs" not in metadata
    assert "dropped_event_refs" not in metadata
    assert "retention_reasons" not in metadata
    assert [event["event_ref"] for event in projection.context["known_events"]["events"]] == [
        str(index) for index in range(1, case["history_count"] + 1)
    ]
