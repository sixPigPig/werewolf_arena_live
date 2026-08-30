from __future__ import annotations

from collections import Counter
from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest

from app.match.model_context_compaction import (
    ModelContextCompactionError,
    build_known_events_v6_compaction_metadata,
    canonical_known_events_v5_sha256,
    encode_known_events_v6,
    encode_known_events_v7,
    expand_known_events_v6,
    expand_known_events_v7,
)


_F29_SANITIZED_FIXTURE = (
    Path(__file__).parent / "fixtures" / "v2_f29_known_events_v5_sanitized.json"
)
_F29_SANITIZED_CANONICAL_SHA256 = "5aa6f7584d8654eb8d94b1035d4213cc4b767d5da2e6b83763b2a67c2b38419a"


def test_known_events_v7_is_lossless_for_selector_retained_projection() -> None:
    canonical = _canonical_known_events_v5()

    compact = encode_known_events_v7(canonical)

    assert compact["schema_version"] == 7
    assert compact["encoding"] == "lossless_refs_v1"
    assert expand_known_events_v7(compact) == canonical


def _canonical_known_events_v5() -> dict[str, object]:
    derivation = {
        "kind": "deterministic_heuristic",
        "validator_version": 5,
        "validation_status": "complete",
    }
    return {
        "schema_version": 5,
        "events": [
            {
                "event_ref": "1",
                "kind": "player_statement",
                "authority": "player_claim_unverified",
                "visibility": "public",
                "record_seq": 1,
                "known_at_seq": 1,
                "occurred_in": {"period": "day", "round_no": 1},
                "stage": "day_debate_speech",
                "speaker_ref": "seat_1",
                "speech": "我说：昨夜风很冷。🙂\n保持原样。",
                "annotations": [
                    {
                        "claim_id": "claim_1_0",
                        "claim_type": "role_claim",
                        "authority": "player_claim_unverified",
                        "claimed_role": "seer",
                        "sentence_index": 0,
                        "derivation": derivation,
                    },
                    {
                        "claim_id": "claim_1_1",
                        "claim_type": "investigation_claim",
                        "authority": "player_claim_unverified",
                        "target_ref": "seat_4",
                        "claimed_result": "werewolves",
                        "sentence_index": 1,
                        "derivation": derivation,
                    },
                ],
            },
            {
                "event_ref": "20",
                "kind": "day_vote",
                "authority": "judge_fact",
                "visibility": "public",
                "record_seq": 20,
                "known_at_seq": 2,
                "occurred_in": {"period": "day", "round_no": 1},
                "action_type": "exile_vote",
                "voter_ref": "seat_2",
                "target_ref": "seat_4",
                "weight": 1.5,
            },
            {
                "event_ref": "legacy_vote_result",
                "kind": "vote_result",
                "authority": "judge_fact",
                "visibility": "public",
                "known_at_seq": 3,
                "sequence_status": "unknown",
                "occurred_in": {"period": "day", "round_no": 1},
                "candidate_refs": ["seat_1", "seat_4"],
                "totals": {"seat_4": 2.5},
                "leader_refs": ["seat_4"],
                "annotations": [],
            },
            {
                "event_ref": "4",
                "kind": "night_result",
                "authority": "judge_fact",
                "visibility": "public",
                "record_seq": 4,
                "known_at_seq": 4,
                "occurred_in": {"period": "night", "round_no": 1},
                "announced_in": {"period": "dawn", "round_no": 1},
                "outcome": "deaths",
                "eliminated_player_refs": ["seat_3"],
                "role_revealed": False,
                "known_role": None,
            },
            {
                "event_ref": "5",
                "kind": "player_eliminated",
                "authority": "judge_fact",
                "visibility": "public",
                "record_seq": 5,
                "known_at_seq": 5,
                "occurred_in": {"period": "day", "round_no": 1},
                "public_reason": "exile",
                "player_ref": "seat_4",
                "role_revealed": False,
            },
            {
                "event_ref": "6",
                "kind": "role_revealed",
                "authority": "judge_fact",
                "visibility": "public",
                "record_seq": 6,
                "known_at_seq": 6,
                "occurred_in": {"period": "day", "round_no": 1},
                "player_ref": "seat_6",
                "known_role": "idiot",
                "survived": True,
            },
            {
                "event_ref": "7",
                "kind": "hunter_response",
                "authority": "judge_fact",
                "visibility": "public",
                "record_seq": 7,
                "known_at_seq": 7,
                "occurred_in": {"period": "day", "round_no": 1},
                "hunter_ref": "seat_7",
                "target_ref": "seat_8",
                "hunter_role_revealed": True,
            },
            {
                "event_ref": "8",
                "kind": "speech_turn_skipped_technical",
                "authority": "judge_fact",
                "visibility": "public",
                "record_seq": 8,
                "known_at_seq": 8,
                "occurred_in": {"period": "day", "round_no": 1},
                "speaker_ref": "seat_8",
                "reason": "technical_failure",
            },
            {
                "event_ref": "9",
                "kind": "werewolf_self_exploded",
                "authority": "judge_fact",
                "visibility": "public",
                "record_seq": 9,
                "known_at_seq": 9,
                "occurred_in": {"period": "day", "round_no": 1},
                "payload": {"player_ref": "seat_9"},
            },
            {
                "event_ref": "private_investigation_1",
                "kind": "investigation_alignment",
                "authority": "judge_fact",
                "visibility": "actor_private",
                "owner_scope": "player",
                "owner_ref": "seat_2",
                "record_seq": 10,
                "known_at_seq": 10,
                "occurred_in": {"period": "night", "round_no": 1},
                "data": {"target_player_id": "seat_4", "alignment": "werewolves"},
            },
            {
                "event_ref": "private_memory_1",
                "kind": "private_round_memory",
                "authority": "actor_memory",
                "epistemic_status": "actor_subjective_memory",
                "visibility": "actor_private",
                "owner_scope": "player",
                "owner_ref": "seat_2",
                "record_seq": 11,
                "known_at_seq": 11,
                "occurred_in": {"period": "day", "round_no": 1},
                "data": {
                    "memory": "这是主观记忆，不是法官事实。",
                    "epistemic_status": "actor_subjective_memory",
                },
            },
            {
                "event_ref": "current_living_werewolf_teammates",
                "kind": "living_werewolf_teammates",
                "authority": "judge_fact",
                "visibility": "actor_private",
                "owner_scope": "player",
                "owner_ref": "seat_2",
                "record_seq": 12,
                "known_at_seq": 12,
                "occurred_in": {"period": "night", "round_no": 2},
                "data": {"teammate_refs": ["seat_5"]},
            },
        ],
        "questions": [
            {
                "question_id": "question_1",
                "source_event_ref": "1",
                "source_authority": "player_claim_unverified",
                "asked_by": "seat_1",
                "addressed_to": "seat_2",
                "address_resolution": "resolved",
                "asked_at_seq": 1,
                "topic": "past_investigation_result",
                "response_status": "response_detected",
                "prior_relevant_event_refs": ["20"],
                "derivation": derivation,
            }
        ],
        "relations": [
            {
                "relation_id": "relation_5_question_1",
                "type": "response_to_question",
                "from_event_ref": "5",
                "to_question_id": "question_1",
                "temporal_order_valid": True,
                "derivation": derivation,
            }
        ],
    }


def test_known_events_v6_round_trip_preserves_all_event_kinds_and_references() -> None:
    canonical = _canonical_known_events_v5()

    compact = encode_known_events_v6(canonical)

    assert expand_known_events_v6(compact) == canonical
    assert compact["schema_version"] == 6
    assert compact["encoding"] == "lossless_refs_v1"
    assert compact["defaults"]["record_seq"] == "known_at_seq"
    assert compact["defaults"]["event_ref"] == "record_seq_string_when_equal"
    assert compact["defaults"]["scope_ref_by_kind"]["player_statement"] == (
        "public_player_claim_unverified"
    )
    assert compact["defaults"]["occurred_in_ref_by_kind"]["player_statement"] == "day_1"
    assert list(compact["scope_catalog"]) == [
        "actor_private_actor_memory_epistemic_actor_subjective_memory",
        "actor_private_judge_fact",
        "public_judge_fact",
        "public_player_claim_unverified",
    ]
    assert compact["scope_catalog"]["actor_private_judge_fact"] == {
        "visibility": "actor_private",
        "authority": "judge_fact",
        "owner_scope": "player",
        "owner_ref": "seat_2",
    }
    assert set(compact["occurrence_catalog"]) == {"day_1", "night_1", "night_2"}
    assert [event["kind"] for event in compact["events"]] == [
        event["kind"] for event in canonical["events"]
    ]
    assert all("authority" not in event for event in compact["events"])
    assert compact["questions"] == canonical["questions"]
    assert compact["relations"] == canonical["relations"]

    first = compact["events"][0]
    assert "event_ref" not in first
    assert "record_seq" not in first
    assert "scope_ref" not in first
    assert "occurred_in_ref" not in first
    assert "annotations" not in first
    assert first["annotation_count"] == 2
    assert [annotation["source_annotation_index"] for annotation in compact["annotations"]] == [
        0,
        1,
    ]
    assert all(annotation["source_event_ref"] == "1" for annotation in compact["annotations"])

    sequence_override = compact["events"][1]
    assert sequence_override["record_seq"] == 20
    assert "event_ref" not in sequence_override
    unknown_record_seq = compact["events"][2]
    assert unknown_record_seq["record_seq"] is None
    assert unknown_record_seq["event_ref"] == "legacy_vote_result"
    assert unknown_record_seq["annotation_count"] == 0
    compact_memory = compact["events"][10]
    assert "epistemic_status" not in compact_memory
    assert compact_memory["data"]["epistemic_status"] == "actor_subjective_memory"


def test_known_events_v6_preserves_unicode_speech_byte_exactly_and_only_on_source_event() -> None:
    canonical = _canonical_known_events_v5()
    speech = canonical["events"][0]["speech"]

    compact = encode_known_events_v6(canonical)
    expanded = expand_known_events_v6(compact)
    compact_json = json.dumps(compact, ensure_ascii=False, separators=(",", ":"))

    assert expanded["events"][0]["speech"].encode("utf-8") == speech.encode("utf-8")
    assert compact_json.count(json.dumps(speech, ensure_ascii=False)) == 1
    assert all("speech" not in annotation for annotation in compact["annotations"])
    assert all("speech" not in question for question in compact["questions"])
    assert all("speech" not in relation for relation in compact["relations"])


def test_known_events_v6_encoding_hash_and_metadata_are_deterministic() -> None:
    canonical = _canonical_known_events_v5()
    expected_bytes = json.dumps(
        canonical,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")

    first = encode_known_events_v6(canonical)
    second = encode_known_events_v6(deepcopy(canonical))
    metadata = build_known_events_v6_compaction_metadata(canonical, first)

    assert first == second
    assert canonical_known_events_v5_sha256(canonical) == hashlib.sha256(expected_bytes).hexdigest()
    assert metadata["canonical_sha256"] == hashlib.sha256(expected_bytes).hexdigest()
    assert metadata["retained_event_refs"] == [event["event_ref"] for event in canonical["events"]]
    assert metadata["dropped_event_refs"] == []
    assert metadata["round_trip_verified"] is True
    assert metadata["verbatim_speech_count"] == 1
    assert metadata["verbatim_speech_chars"] == len(canonical["events"][0]["speech"])
    assert metadata["compaction_saved_chars"] == (
        metadata["canonical_serialized_char_count"] - metadata["compact_serialized_char_count"]
    )
    assert metadata["compaction_ratio"] == (
        metadata["compact_serialized_char_count"] / metadata["canonical_serialized_char_count"]
    )


def test_known_events_v6_kind_defaults_use_count_then_lexical_tie_break() -> None:
    canonical = {
        "schema_version": 5,
        "events": [
            {
                "event_ref": "1",
                "kind": "shared_kind",
                "authority": "judge_fact",
                "visibility": "public",
                "record_seq": 1,
                "known_at_seq": 1,
                "occurred_in": {"period": "day", "round_no": 2},
            },
            {
                "event_ref": "2",
                "kind": "shared_kind",
                "authority": "player_claim_unverified",
                "visibility": "public",
                "record_seq": 2,
                "known_at_seq": 2,
                "occurred_in": {"period": "day", "round_no": 1},
            },
        ],
        "questions": [],
        "relations": [],
    }

    tied = encode_known_events_v6(canonical)
    assert tied["defaults"]["scope_ref_by_kind"] == {"shared_kind": "public_judge_fact"}
    assert tied["defaults"]["occurred_in_ref_by_kind"] == {"shared_kind": "day_1"}
    assert tied["events"][0]["occurred_in_ref"] == "day_2"
    assert tied["events"][1]["scope_ref"] == "public_player_claim_unverified"

    canonical["events"].append(
        {
            "event_ref": "3",
            "kind": "shared_kind",
            "authority": "player_claim_unverified",
            "visibility": "public",
            "record_seq": 3,
            "known_at_seq": 3,
            "occurred_in": {"period": "day", "round_no": 2},
        }
    )
    counted = encode_known_events_v6(canonical)
    assert counted["defaults"]["scope_ref_by_kind"] == {
        "shared_kind": "public_player_claim_unverified"
    }
    assert counted["defaults"]["occurred_in_ref_by_kind"] == {"shared_kind": "day_2"}
    assert expand_known_events_v6(counted) == canonical


def test_known_events_v6_explicit_null_suppresses_occurrence_default() -> None:
    canonical = {
        "schema_version": 5,
        "events": [
            {
                "event_ref": "1",
                "kind": "legacy_mixed_occurrence",
                "authority": "judge_fact",
                "visibility": "public",
                "record_seq": 1,
                "known_at_seq": 1,
                "occurred_in": {"period": "day", "round_no": 1},
            },
            {
                "event_ref": "2",
                "kind": "legacy_mixed_occurrence",
                "authority": "judge_fact",
                "visibility": "public",
                "record_seq": 2,
                "known_at_seq": 2,
            },
        ],
        "questions": [],
        "relations": [],
    }

    compact = encode_known_events_v6(canonical)

    assert compact["defaults"]["occurred_in_ref_by_kind"] == {"legacy_mixed_occurrence": "day_1"}
    assert "occurred_in_ref" not in compact["events"][0]
    assert compact["events"][1]["occurred_in_ref"] is None
    assert expand_known_events_v6(compact) == canonical


def test_known_events_v6_preserves_same_sequence_reverse_lexical_event_order() -> None:
    canonical = {
        "schema_version": 5,
        "events": [
            {
                "event_ref": "z_event",
                "kind": "same_clock_fact",
                "authority": "judge_fact",
                "visibility": "public",
                "record_seq": 10,
                "known_at_seq": 10,
                "occurred_in": {"period": "day", "round_no": 1},
            },
            {
                "event_ref": "a_event",
                "kind": "same_clock_fact",
                "authority": "judge_fact",
                "visibility": "public",
                "record_seq": 10,
                "known_at_seq": 10,
                "occurred_in": {"period": "day", "round_no": 1},
            },
        ],
        "questions": [],
        "relations": [],
    }

    compact = encode_known_events_v6(canonical)

    assert [event["event_ref"] for event in compact["events"]] == ["z_event", "a_event"]
    assert expand_known_events_v6(compact) == canonical


def test_known_events_v6_rejects_explicit_null_event_ref() -> None:
    compact = encode_known_events_v6(_canonical_known_events_v5())
    compact["events"][0]["event_ref"] = None

    with pytest.raises(ModelContextCompactionError) as exc_info:
        expand_known_events_v6(compact)

    assert exc_info.value.code == "known_events_v6_event_ref"


def test_known_events_v6_missing_canonical_kind_fails_closed() -> None:
    canonical = _canonical_known_events_v5()
    canonical["events"][0].pop("kind")

    with pytest.raises(ModelContextCompactionError) as exc_info:
        encode_known_events_v6(canonical)

    assert exc_info.value.code == "known_events_v5_kind"


def test_known_events_v6_f29_sanitized_fixture_saves_at_least_twenty_percent() -> None:
    fixture = json.loads(_F29_SANITIZED_FIXTURE.read_text(encoding="utf-8"))
    provenance = fixture["provenance"]
    expected = fixture["expected"]
    canonical = fixture["known_events"]
    events = canonical["events"]
    canonical_speeches = [
        event["speech"] for event in events if isinstance(event.get("speech"), str)
    ]
    canonical_data = [event.get("data") for event in events]

    compact = encode_known_events_v6(canonical)
    expanded = expand_known_events_v6(compact)
    metadata = build_known_events_v6_compaction_metadata(canonical, compact)

    assert provenance == {
        "contains_original_speech_or_private_ids": False,
        "sanitization_contract": "same_json_shape_and_per_value_string_length_v1",
        "source_game_ref": "v2_game_f29_sanitized",
        "source_known_events_schema_version": 5,
        "source_model_context_schema_version": 11,
        "source_model_request_started_record_seq": 3004,
    }
    assert expected["event_count"] == len(events) == 131
    assert (
        expected["public_event_count"]
        == sum(event["visibility"] == "public" for event in events)
        == 96
    )
    assert (
        expected["actor_private_event_count"]
        == sum(event["visibility"] == "actor_private" for event in events)
        == 35
    )
    assert (
        expected["kind_counts"]
        == dict(sorted(Counter(event["kind"] for event in events).items()))
        == {
            "day_vote": 33,
            "hunter_response": 1,
            "living_werewolf_teammates": 1,
            "night_result": 5,
            "player_eliminated": 5,
            "player_statement": 44,
            "private_ability_action_committed": 12,
            "private_action_decision": 14,
            "private_round_memory": 3,
            "sheriff_badge_transferred": 2,
            "sheriff_elected": 1,
            "speech_turn_skipped_technical": 1,
            "vote_result": 4,
            "werewolf_attack_resolved": 5,
        }
    )
    assert expected["speech_count"] == len(canonical_speeches) == 44
    assert expected["speech_char_count"] == sum(map(len, canonical_speeches)) == 10_015
    assert expected["speech_char_lengths"] == [len(speech) for speech in canonical_speeches]
    assert all(
        char in {"文", "x", "0", ".", '"', "\\"} or char.isspace()
        for speech in canonical_speeches
        for char in speech
    )
    assert (
        expected["annotation_count"]
        == sum(
            len(event.get("annotations", []))
            for event in events
            if isinstance(event.get("annotations"), list)
        )
        == 5
    )
    assert expected["question_count"] == len(canonical["questions"]) == 1
    assert expected["relation_count"] == len(canonical["relations"]) == 0

    string_lengths: Counter[int] = Counter()

    def collect_string_lengths(value: object) -> None:
        if isinstance(value, dict):
            for item in value.values():
                collect_string_lengths(item)
        elif isinstance(value, list):
            for item in value:
                collect_string_lengths(item)
        elif isinstance(value, str):
            string_lengths[len(value)] += 1

    collect_string_lengths(canonical)
    assert expected["string_length_histogram"] == {
        str(length): count for length, count in sorted(string_lengths.items())
    }
    assert (
        canonical_known_events_v5_sha256(canonical)
        == (expected["canonical_sha256"])
        == _F29_SANITIZED_CANONICAL_SHA256
    )
    assert (
        metadata["canonical_serialized_char_count"]
        == (expected["canonical_serialized_char_count"])
        == 59_872
    )
    assert (
        metadata["compact_serialized_char_count"]
        == (expected["compact_serialized_char_count"])
        == 46_161
    )
    assert expanded == canonical
    assert [event["speech"] for event in expanded["events"] if "speech" in event] == (
        canonical_speeches
    )
    assert [event.get("data") for event in expanded["events"]] == canonical_data
    assert metadata["retained_event_refs"] == [event["event_ref"] for event in events]
    assert metadata["dropped_event_refs"] == []
    assert metadata["compaction_saved_chars"] == 13_711
    assert metadata["compaction_ratio"] <= expected["maximum_compaction_ratio"] == 0.8


@pytest.mark.parametrize(
    ("mutate", "expected_code"),
    [
        (
            lambda compact: compact["scope_catalog"].pop("public_judge_fact"),
            "missing_scope_ref",
        ),
        (
            lambda compact: compact["occurrence_catalog"].pop("day_1"),
            "missing_occurrence_ref",
        ),
        (
            lambda compact: compact["annotations"][0].update({"source_event_ref": "missing"}),
            "missing_annotation_source_ref",
        ),
        (
            lambda compact: compact["questions"][0].update({"source_event_ref": "missing"}),
            "missing_question_source_ref",
        ),
        (
            lambda compact: compact["relations"][0].update({"from_event_ref": "missing"}),
            "missing_relation_event_ref",
        ),
        (
            lambda compact: compact["annotations"].append(deepcopy(compact["annotations"][0])),
            "compact_annotation_index_conflict",
        ),
        (
            lambda compact: compact["scope_catalog"].update({"a": {"visibility": "public"}}),
            "compact_catalog_key_unreadable",
        ),
    ],
)
def test_known_events_v6_bad_references_fail_closed(mutate, expected_code: str) -> None:
    compact = encode_known_events_v6(_canonical_known_events_v5())
    mutate(compact)

    with pytest.raises(ModelContextCompactionError) as exc_info:
        expand_known_events_v6(compact)

    assert exc_info.value.code == expected_code


def test_known_events_v6_duplicate_event_ref_fails_closed() -> None:
    compact = encode_known_events_v6(_canonical_known_events_v5())
    compact["events"][0]["event_ref"] = "legacy_vote_result"

    with pytest.raises(ModelContextCompactionError) as exc_info:
        expand_known_events_v6(compact)

    assert exc_info.value.code == "duplicate_event_ref"


def test_known_events_v6_catalog_key_collision_fails_closed() -> None:
    canonical = _canonical_known_events_v5()
    private_event = deepcopy(canonical["events"][-1])
    private_event.update(
        {
            "event_ref": "private_collision",
            "owner_ref": "seat-2",
            "record_seq": 13,
            "known_at_seq": 13,
        }
    )
    canonical["events"].append(private_event)

    with pytest.raises(ModelContextCompactionError) as exc_info:
        encode_known_events_v6(canonical)

    assert exc_info.value.code == "compact_catalog_key_collision"


def test_known_events_v6_rejects_non_chronological_and_non_finite_canonical_input() -> None:
    non_chronological = _canonical_known_events_v5()
    non_chronological["events"][0], non_chronological["events"][1] = (
        non_chronological["events"][1],
        non_chronological["events"][0],
    )
    with pytest.raises(ModelContextCompactionError) as chronology_error:
        encode_known_events_v6(non_chronological)
    assert chronology_error.value.code == "known_events_not_chronological"

    non_finite = _canonical_known_events_v5()
    non_finite["events"][1]["weight"] = float("nan")
    with pytest.raises(ModelContextCompactionError) as json_error:
        canonical_known_events_v5_sha256(non_finite)
    assert json_error.value.code == "canonical_json_non_finite_number"
