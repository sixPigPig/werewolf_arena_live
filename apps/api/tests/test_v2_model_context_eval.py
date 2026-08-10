from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from app.v2.model_client import build_model_request_payload
from app.v2.model_context_compaction import expand_known_events_v6
from app.v2.model_context import (
    V2ModelPlayerReference,
    project_model_action_context_with_metadata,
)
from app.v2.model_context_contract import current_model_context_contract


_FIXTURE = Path(__file__).parent / "fixtures" / "v2_model_context_v8_eval.json"


def _cases() -> dict[str, dict[str, Any]]:
    payload = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    assert payload["schema_version"] == 1
    return {item["case_id"]: item for item in payload["cases"]}


def _complete_v11_context(
    context: dict[str, Any],
    *,
    players: tuple[V2ModelPlayerReference, ...],
) -> dict[str, Any]:
    prepared = deepcopy(context)
    round_no = prepared.get("round_no") or 1
    prepared["public_match_state"] = {
        "round_no": round_no,
        "alive_player_count": len(players),
        "alive_player_ids": [player.player_id for player in players],
        "eliminated_player_count": 0,
        "eliminated_player_ids": [],
        "sheriff_badge_state": "unassigned",
    }
    prepared["public_office_capabilities"] = {"is_current_sheriff": False}
    identity = prepared.get("self_identity")
    owner_id = identity.get("player_id") if isinstance(identity, dict) else None
    private_facts = prepared.get("private_authoritative_facts")
    if isinstance(owner_id, str) and isinstance(private_facts, list):
        for fact in private_facts:
            if isinstance(fact, dict):
                fact.setdefault("owner_scope", "player")
                fact.setdefault("owner_id", owner_id)
    return prepared


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
        _complete_v11_context(case["context"], players=players),
        players=players,
        model_context_contract=current_model_context_contract(),
        action_record_seq=case["action_record_seq"],
    )
    context = projection.context
    events = expand_known_events_v6(context["known_events"])["events"]

    assert [event["event_ref"] for event in events] == case["expect"]["event_refs"]
    assert [event["known_at_seq"] for event in events] == case["expect"]["event_sequences"]
    assert events[0]["known_at_seq"] < events[1]["known_at_seq"] < context["task"]["at_seq"]
    assert events[0]["owner_scope"] == "player"
    assert events[0]["owner_ref"] == context["self"]["identity"]["player_id"]
    assert all("source_event_id" not in event for event in events)
    assert all("timeline_index" not in event for event in events)
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
        max_output_tokens=16_384,
    )
    system_text = request["input"][0]["content"][0]["text"]
    assert len(system_text) < 1_700
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
    players = (
        V2ModelPlayerReference("system-player-07", 1, "1号"),
        V2ModelPlayerReference("system-player-01", 2, "2号"),
    )
    projection = project_model_action_context_with_metadata(
        _complete_v11_context(
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
            players=players,
        ),
        players=players,
        model_context_contract=current_model_context_contract(),
        action_record_seq=100,
    )
    metadata = projection.projection_metadata

    assert metadata["source_event_count"] == case["history_count"]
    assert metadata["emitted_event_count"] == metadata["source_event_count"]
    assert metadata["future_filtered_event_count"] == 0
    assert metadata["budget_dropped_event_count"] == 0
    assert "selection_budget_chars" not in metadata
    assert metadata["retained_event_refs"] == [
        str(index) for index in range(1, case["history_count"] + 1)
    ]
    assert metadata["dropped_event_refs"] == []
    assert metadata["round_trip_verified"] is True
    assert "retention_reasons" not in metadata
    canonical_events = expand_known_events_v6(projection.context["known_events"])["events"]
    assert [event["event_ref"] for event in canonical_events] == [
        str(index) for index in range(1, case["history_count"] + 1)
    ]
    assert all(
        "source_event_id" not in event and "timeline_index" not in event
        for event in canonical_events
    )
