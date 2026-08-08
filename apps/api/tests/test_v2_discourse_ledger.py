from __future__ import annotations

from copy import deepcopy

import pytest

from app.v2.discourse_ledger import (
    build_public_discourse_ledger,
    validate_claim_candidate,
)
from app.v2.discourse_model_view import build_discourse_model_view
from app.v2.model_context_contract import (
    DISCOURSE_LEDGER_SCHEMA_VERSION,
    DISCOURSE_MODEL_VIEW_SCHEMA_VERSION,
)


def _statement(
    source_event_id: int,
    *,
    speaker_ref: str,
    speech: str,
    round_no: int = 3,
    stage: str = "day_debate_speech",
) -> dict[str, object]:
    return {
        "source_event_id": str(source_event_id),
        "uttered_record_seq": source_event_id,
        "occurred_in": {"period": "day", "round_no": round_no},
        "stage": stage,
        "speaker_ref": speaker_ref,
        "speech": speech,
    }


def _ledger(
    *statements: dict[str, object],
    current_round_no: int = 3,
    **kwargs: object,
) -> dict[str, object]:
    return build_public_discourse_ledger(
        statements,
        current_round_no=current_round_no,
        **kwargs,
    )


def _view(
    ledger: dict[str, object],
    *,
    actor_ref: str = "seat_12",
    task: dict[str, object] | None = None,
) -> tuple[dict[str, object], dict[str, object]]:
    return build_discourse_model_view(
        ledger,
        actor_ref=actor_ref,
        task=task or {"type": "exile_vote"},
        candidate_refs=[],
        latest_vote_result_ref=None,
    )


def test_v5_only_schema_versions_fail_closed() -> None:
    statement = _statement(100, speaker_ref="seat_1", speech="我底牌是好人。")

    with pytest.raises(ValueError, match="unsupported_discourse_ledger_schema_version"):
        build_public_discourse_ledger(
            [statement],
            current_round_no=3,
            ledger_schema_version=DISCOURSE_LEDGER_SCHEMA_VERSION - 1,
        )

    ledger = _ledger(statement)
    with pytest.raises(ValueError, match="unsupported_discourse_model_view_schema_version"):
        build_discourse_model_view(
            ledger,
            actor_ref="seat_12",
            task={"type": "exile_vote"},
            candidate_refs=[],
            latest_vote_result_ref=None,
            model_view_schema_version=DISCOURSE_MODEL_VIEW_SCHEMA_VERSION - 1,
        )


def test_conditional_topic_player_is_not_question_addressee() -> None:
    ledger = _ledger(
        _statement(
            1403,
            speaker_ref="seat_12",
            speech="如果8是狼，7号和9号在保谁？",
        )
    )

    assert ledger["questions"] == [
        {
            "question_id": "question_1403_1",
            "source_event_ref": "1403",
            "source_authority": "player_claim_unverified",
            "source_sentence_id": "sentence_1403_1",
            "sentence_index": 1,
            "asked_turn_index": 1,
            "asked_by": "seat_12",
            "asked_in": {"period": "day", "round_no": 3},
            "stage": "day_debate_speech",
            "topic": "general",
            "exact_quote": "如果8是狼，7号和9号在保谁？",
            "response_status": "none_detected",
            "address_resolution": "unresolved",
            "asked_at_seq": 1403,
            "derivation": {
                "kind": "deterministic_heuristic",
                "validator_version": 1,
                "validation_status": "complete",
            },
        }
    ]
    assert "addressed_to" not in ledger["questions"][0]


def test_leading_conditional_topic_is_not_reused_as_addressee() -> None:
    ledger = _ledger(
        _statement(
            1403,
            speaker_ref="seat_12",
            speech="8号如果是狼，7号和9号在保谁？你们怎么判断？",
        )
    )

    assert [question["address_resolution"] for question in ledger["questions"]] == [
        "unresolved",
        "unresolved",
    ]
    assert all("addressed_to" not in question for question in ledger["questions"])


def test_explicit_direct_address_resolves_only_the_grammatical_target() -> None:
    ledger = _ledger(
        _statement(
            1403,
            speaker_ref="seat_12",
            speech=("8号和9号的票型都要盘。7号你接了警徽，今天先解释昨天为什么投5不投8。"),
        )
    )

    assert len(ledger["questions"]) == 1
    question = ledger["questions"][0]
    assert question["addressed_to"] == "seat_7"
    assert question["address_resolution"] == "resolved"
    assert question["topic"] == "vote_reason"


def test_explicit_address_can_resolve_a_stable_singular_continuation() -> None:
    ledger = _ledger(
        _statement(
            1404,
            speaker_ref="seat_12",
            speech="8号先别回避。你今晚具体验谁？",
        )
    )

    assert len(ledger["questions"]) == 1
    assert ledger["questions"][0]["addressed_to"] == "seat_8"
    assert ledger["questions"][0]["address_resolution"] == "resolved"


def test_reported_question_does_not_create_address_or_relation() -> None:
    ledger = _ledger(
        _statement(
            1416,
            speaker_ref="seat_11",
            speech="8号问我为什么投5，我已经解释过。",
        ),
        _statement(
            1429,
            speaker_ref="seat_8",
            speech="我投5是因为他的复盘最差。",
        ),
    )

    assert ledger["questions"] == []
    assert ledger["relations"] == []


def test_reported_question_does_not_seed_a_later_singular_addressee() -> None:
    ledger = _ledger(
        _statement(
            1416,
            speaker_ref="seat_11",
            speech="8号问我为什么投5。你觉得这个票型怎么盘？",
        )
    )

    assert len(ledger["questions"]) == 1
    assert ledger["questions"][0]["address_resolution"] == "unresolved"
    assert "addressed_to" not in ledger["questions"][0]


def test_good_alignment_is_team_claim_not_role_claim() -> None:
    ledger = _ledger(_statement(403, speaker_ref="seat_11", speech="我底牌是好人。"))

    assert [(claim["claim_type"], claim.get("claimed_team")) for claim in ledger["claims"]] == [
        ("team_claim", "villagers")
    ]
    assert all(claim.get("claimed_role") != "good" for claim in ledger["claims"])
    assert ledger["claims"][0]["authority"] == "player_claim_unverified"
    assert ledger["claims"][0]["derivation"]["validation_status"] == "complete"


def test_concrete_role_claim_remains_role_claim() -> None:
    ledger = _ledger(_statement(404, speaker_ref="seat_6", speech="我是真预言家。"))

    assert [(claim["claim_type"], claim.get("claimed_role")) for claim in ledger["claims"]] == [
        ("role_claim", "seer")
    ]


def test_incomplete_investigation_claim_is_rejected_without_hiding_raw_speech() -> None:
    ledger = _ledger(
        _statement(
            402,
            speaker_ref="seat_10",
            speech="我是真预言家，昨晚我验了，结果稍后再说。",
            round_no=1,
        ),
        current_round_no=1,
    )

    assert [claim["claim_type"] for claim in ledger["claims"]] == ["role_claim"]
    assert ledger["statements"][0]["speech"] == "我是真预言家，昨晚我验了，结果稍后再说。"
    assert ledger["derivation_rejections"] == [
        {
            "source_event_ref": "402",
            "kind": "investigation_claim",
            "reason": "missing_required_fields",
            "missing_fields": ["target_ref", "claimed_result"],
        }
    ]
    assert ledger["derivation_metadata"] == {
        "source_claim_candidate_count": 2,
        "emitted_claim_count": 1,
        "rejected_claim_count": 1,
    }


def test_complete_investigation_claim_has_all_required_fields() -> None:
    ledger = _ledger(
        _statement(
            460,
            speaker_ref="seat_5",
            speech="我是预言家，首夜验了1号，是狼人查杀。",
            round_no=1,
        ),
        current_round_no=1,
    )

    investigation = next(
        claim for claim in ledger["claims"] if claim["claim_type"] == "investigation_claim"
    )
    assert investigation["claimed_action_in"] == {"period": "night", "round_no": 1}
    assert investigation["target_ref"] == "seat_1"
    assert investigation["claimed_result"] == "werewolves"
    assert investigation["derivation"] == {
        "kind": "deterministic_heuristic",
        "validator_version": 1,
        "validation_status": "complete",
    }


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("claimed_role", "unknown_role", "unknown_role_key"),
        ("claimed_team", "unknown_team", "unknown_team_key"),
        ("target_ref", "seat_9", "unknown_player_ref"),
    ],
)
def test_claim_validator_rejects_values_outside_frozen_enums(
    field: str,
    value: str,
    reason: str,
) -> None:
    claim_type = (
        "role_claim"
        if field == "claimed_role"
        else "team_claim"
        if field == "claimed_team"
        else "vote_stance"
    )
    candidate = {
        "claim_id": f"claim_100_1_{claim_type}",
        "claim_type": claim_type,
        "source_event_ref": "100",
        "sentence_index": 1,
        "exact_quote": "原句",
        field: value,
    }
    if claim_type == "vote_stance":
        candidate["stance"] = "support_vote"

    validated, rejection = validate_claim_candidate(
        candidate,
        source_statement={"source_event_id": "100", "speech": "原句"},
        role_keys=["seer"],
        team_keys=["villagers", "werewolves"],
        player_refs=["seat_1", "seat_2"],
        current_night_no=3,
    )

    assert validated is None
    assert rejection == {
        "source_event_ref": "100",
        "kind": claim_type,
        "reason": reason,
    }


def test_one_later_statement_can_respond_to_multiple_questions() -> None:
    ledger = _ledger(
        _statement(
            1350,
            speaker_ref="seat_3",
            speech="今天7号接警徽，我想听你怎么盘4号这一刀——狼队为什么选择刀4号？",
        ),
        _statement(
            1364,
            speaker_ref="seat_5",
            speech="7号你昨天为什么投5不投8？",
        ),
        _statement(
            1403,
            speaker_ref="seat_12",
            speech="7号请解释昨天投5的理由。",
        ),
        _statement(
            1442,
            speaker_ref="seat_7",
            speech=("刀4号的收益是拿走警徽位并制造怀疑。我昨天投5没投8，是因为5号的复盘最差。"),
        ),
    )

    assert {question["response_status"] for question in ledger["questions"]} == {
        "response_detected"
    }
    assert len(ledger["relations"]) == 3
    assert {relation["from_event_ref"] for relation in ledger["relations"]} == {"1442"}
    assert {relation["type"] for relation in ledger["relations"]} == {"response_to_question"}
    assert all(relation["temporal_order_valid"] is True for relation in ledger["relations"])


def test_one_question_can_retain_multiple_later_responses() -> None:
    ledger = _ledger(
        _statement(
            1403,
            speaker_ref="seat_12",
            speech="7号你昨天为什么投5不投8？",
        ),
        _statement(
            1420,
            speaker_ref="seat_7",
            speech="我投5是因为他复盘最差。",
        ),
        _statement(
            1442,
            speaker_ref="seat_7",
            speech="再解释一次，我投5是根据他的站边和发言判断。",
        ),
    )

    assert ledger["questions"][0]["response_status"] == "response_detected"
    assert [relation["from_event_ref"] for relation in ledger["relations"]] == [
        "1420",
        "1442",
    ]


def test_prior_statement_is_coverage_not_a_response_to_later_question() -> None:
    ledger = _ledger(
        _statement(
            460,
            speaker_ref="seat_5",
            speech="我是预言家，首夜验了1号，是狼人查杀。",
            round_no=1,
        ),
        _statement(
            732,
            speaker_ref="seat_8",
            speech="5号昨晚验了谁、什么结果？",
            round_no=1,
        ),
        current_round_no=1,
    )

    assert ledger["questions"][0]["response_status"] == "none_detected"
    assert ledger["relations"] == []
    model_view, metadata = _view(ledger, actor_ref="seat_8")
    question = model_view["questions"][0]
    assert question["prior_relevant_statement_refs"] == ["460"]
    assert question["prior_coverage"] == "already_publicly_reported"
    assert metadata["prior_coverage_question_count"] == 1


@pytest.mark.parametrize(
    ("actor_ref", "target_ref", "expected"),
    [
        ("seat_2", "seat_3", "awaiting_scheduled_turn"),
        ("seat_2", "seat_2", "current_speaker_turn"),
        ("seat_2", "seat_1", "scheduled_turn_passed"),
        ("seat_2", "seat_9", "not_in_current_speech_order"),
    ],
)
def test_reply_opportunity_is_only_mechanical_turn_position(
    actor_ref: str,
    target_ref: str,
    expected: str,
) -> None:
    target_no = target_ref.removeprefix("seat_")
    ledger = _ledger(
        _statement(
            100,
            speaker_ref="seat_12",
            speech=f"{target_no}号你为什么投5号？",
        )
    )

    model_view, _metadata = _view(
        ledger,
        actor_ref=actor_ref,
        task={
            "type": "day_debate_speech",
            "speech_order": ["seat_1", "seat_2", "seat_3"],
        },
    )

    assert model_view["questions"][0]["reply_opportunity"] == expected


def test_private_vote_does_not_project_reply_opportunity() -> None:
    ledger = _ledger(_statement(100, speaker_ref="seat_12", speech="7号你为什么投5号？"))

    model_view, _metadata = _view(
        ledger,
        task={
            "type": "exile_vote",
            "speech_order": ["seat_12", "seat_7"],
        },
    )

    assert "reply_opportunity" not in model_view["questions"][0]


def test_model_view_filters_out_of_scope_questions_and_relations_with_real_counts() -> None:
    ledger = _ledger(
        _statement(
            100,
            speaker_ref="seat_12",
            speech="7号你为什么投5号？",
            round_no=2,
        ),
        _statement(
            110,
            speaker_ref="seat_7",
            speech="我投5是因为他的复盘最差。",
            round_no=2,
        ),
        _statement(
            200,
            speaker_ref="seat_12",
            speech="7号你为什么投8号？",
            round_no=3,
        ),
        current_round_no=3,
    )

    model_view, metadata = _view(ledger)

    assert [question["source_event_ref"] for question in model_view["questions"]] == ["200"]
    assert model_view["relations"] == []
    assert metadata["source_question_count"] == 2
    assert metadata["current_scope_question_count"] == 1
    assert metadata["emitted_question_count"] == 1
    assert metadata["out_of_scope_question_count"] == 1
    assert metadata["source_relation_count"] == 1
    assert metadata["emitted_relation_count"] == 0
    assert metadata["out_of_scope_relation_count"] == 1
    assert metadata["invalid_relation_count"] == 0


def test_model_view_rejects_dangling_claim_and_relation_references() -> None:
    ledger = _ledger(_statement(100, speaker_ref="seat_12", speech="7号你为什么投5号？"))
    malformed = deepcopy(ledger)
    malformed["claims"].append(
        {
            "claim_id": "claim_missing_1_role_claim",
            "claim_type": "role_claim",
            "source_event_ref": "missing",
            "claimed_role": "seer",
            "derivation": {
                "kind": "deterministic_heuristic",
                "validator_version": 1,
                "validation_status": "complete",
            },
        }
    )
    malformed["relations"].append(
        {
            "relation_id": "relation_missing_question_100_1",
            "type": "response_to_question",
            "from_event_ref": "missing",
            "to_question_id": "question_100_1",
            "temporal_order_valid": True,
            "derivation": {
                "kind": "deterministic_heuristic",
                "validator_version": 1,
                "validation_status": "complete",
            },
        }
    )

    model_view, metadata = _view(malformed)

    assert model_view["timeline"][0]["annotations"] == []
    assert model_view["relations"] == []
    assert metadata["emitted_claim_count"] == 0
    assert metadata["rejected_claim_count"] == 1
    assert metadata["invalid_relation_count"] == 1
    assert {item["kind"] for item in metadata["derivation_rejections"]} == {
        "claim",
        "relation",
    }


def test_derivation_metadata_reports_complete_and_rejected_claims() -> None:
    ledger = _ledger(
        _statement(100, speaker_ref="seat_1", speech="我底牌是好人。"),
        _statement(
            110,
            speaker_ref="seat_5",
            speech="我是预言家，昨晚我验了，结果以后报。",
        ),
    )

    _model_view, metadata = _view(ledger)

    assert metadata["source_claim_candidate_count"] == 3
    assert metadata["emitted_claim_count"] == 2
    assert metadata["rejected_claim_count"] == 1
    assert metadata["derivation_rejections"] == [
        {
            "source_event_ref": "110",
            "kind": "investigation_claim",
            "reason": "missing_required_fields",
            "missing_fields": ["target_ref", "claimed_result"],
        }
    ]


def test_ledger_orders_statements_before_creating_temporal_relations() -> None:
    ledger = _ledger(
        _statement(
            200,
            speaker_ref="seat_7",
            speech="我投5是因为他的复盘最差。",
        ),
        _statement(
            100,
            speaker_ref="seat_12",
            speech="7号你为什么投5号？",
        ),
    )

    assert [statement["record_seq"] for statement in ledger["statements"]] == [100, 200]
    assert ledger["questions"][0]["response_status"] == "response_detected"
    assert ledger["relations"][0]["from_event_ref"] == "200"
