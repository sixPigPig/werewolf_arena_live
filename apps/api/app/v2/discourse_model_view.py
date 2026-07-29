from __future__ import annotations

from collections import defaultdict
import json
from typing import Any

from app.v2.model_context_contract import DISCOURSE_MODEL_VIEW_SCHEMA_VERSION


def build_discourse_model_view(
    ledger: dict[str, Any],
    *,
    actor_ref: str | None,
    task: dict[str, Any],
    candidate_refs: list[str],
    latest_vote_result_ref: str | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    statements = _dict_list(ledger.get("statements"))
    claims = _dict_list(ledger.get("claims"))
    questions = _dict_list(ledger.get("questions"))
    relations = _dict_list(ledger.get("relations"))

    annotations_by_source: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for claim in claims:
        source_event_id = claim.get("source_event_id")
        if isinstance(source_event_id, str):
            annotations_by_source[source_event_id].append(_claim_annotation(claim))

    timeline = [
        {
            **statement,
            "annotations": annotations_by_source.get(
                str(statement.get("source_event_id") or ""),
                [],
            ),
        }
        for statement in statements
    ]
    focus = _build_focus(
        statements=statements,
        questions=questions,
        actor_ref=actor_ref,
        task=task,
        candidate_refs=candidate_refs,
        latest_vote_result_ref=latest_vote_result_ref,
    )
    model_view = {
        "ledger_schema_version": ledger.get("ledger_schema_version"),
        "model_view_schema_version": DISCOURSE_MODEL_VIEW_SCHEMA_VERSION,
        "source_rules": ledger.get("source_rules"),
        "current_round_no": ledger.get("current_round_no"),
        "timeline": timeline,
        "questions": [_question_reference(question) for question in questions],
        "relations": relations,
        "focus": focus,
    }
    record_seqs = [
        value
        for statement in statements
        for value in (statement.get("record_seq"),)
        if isinstance(value, int) and not isinstance(value, bool)
    ]
    current_round_no = ledger.get("current_round_no")
    current_round_statements = [
        statement
        for statement in statements
        if isinstance(statement.get("occurred_in"), dict)
        and statement["occurred_in"].get("round_no") == current_round_no
    ]
    metadata = {
        "model_view_schema_version": DISCOURSE_MODEL_VIEW_SCHEMA_VERSION,
        "ledger_statement_count": len(statements),
        "ledger_statement_char_count": _statement_chars(statements),
        "ledger_claim_count": len(claims),
        "ledger_question_count": len(questions),
        "ledger_relation_count": len(relations),
        "model_view_statement_count": len(timeline),
        "model_view_statement_char_count": _statement_chars(timeline),
        "model_view_claim_annotation_count": sum(len(item["annotations"]) for item in timeline),
        "model_view_question_count": len(model_view["questions"]),
        "model_view_relation_count": len(relations),
        "dropped_statement_count": 0,
        "dropped_claim_count": 0,
        "dropped_question_count": 0,
        "dropped_relation_count": 0,
        "current_round_statement_count": len(current_round_statements),
        "current_round_statement_char_count": _statement_chars(current_round_statements),
        "secondary_paraphrase_count": sum(
            claim.get("claim_type") == "secondary_paraphrase" for claim in claims
        ),
        "unverified_reported_response_count": sum(
            claim.get("asserted_relation_type") == "reported_response"
            and claim.get("temporal_relation_status") == "unverified"
            for claim in claims
        ),
        "open_question_count": sum(question.get("status") == "open" for question in questions),
        "selection_profile": "full_public_history_with_reference_only_focus",
        "source_record_seq_min": min(record_seqs, default=None),
        "source_record_seq_max": max(record_seqs, default=None),
        "ledger_serialized_char_count": _serialized_chars(ledger),
        "model_view_serialized_char_count": _serialized_chars(model_view),
    }
    return model_view, metadata


def _claim_annotation(claim: dict[str, Any]) -> dict[str, Any]:
    redundant_fields = {
        "source_event_id",
        "speaker_ref",
        "uttered_turn_index",
        "occurred_in",
        "stage",
        "exact_quote",
        "uttered_record_seq",
    }
    return {key: value for key, value in claim.items() if key not in redundant_fields}


def _question_reference(question: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in question.items() if key not in {"exact_quote"}}


def _build_focus(
    *,
    statements: list[dict[str, Any]],
    questions: list[dict[str, Any]],
    actor_ref: str | None,
    task: dict[str, Any],
    candidate_refs: list[str],
    latest_vote_result_ref: str | None,
) -> dict[str, Any]:
    latest_by_speaker: dict[str, str] = {}
    for statement in statements:
        speaker_ref = statement.get("speaker_ref")
        source_event_id = statement.get("source_event_id")
        if isinstance(speaker_ref, str) and isinstance(source_event_id, str):
            latest_by_speaker[speaker_ref] = source_event_id

    pk_refs = _string_list(task.get("pk_candidate_ids"))
    profile = (
        "pk_speech"
        if pk_refs
        else "public_vote"
        if task.get("action_type") in {"day_vote", "sheriff_vote"}
        else "public_speech"
        if task.get("action_type") in {"day_speech", "day_debate_speech"}
        else "general"
    )
    focus: dict[str, Any] = {
        "profile": profile,
        "actor_previous_statement_ref": (
            latest_by_speaker.get(actor_ref) if actor_ref is not None else None
        ),
        "open_question_refs": [
            str(question["question_id"])
            for question in questions
            if question.get("status") == "open"
            and actor_ref is not None
            and question.get("addressed_to") == actor_ref
        ],
        "candidate_latest_statement_refs": [
            source_event_id
            for candidate_ref in candidate_refs
            if (source_event_id := latest_by_speaker.get(candidate_ref)) is not None
        ],
        "pk_opponent_latest_statement_refs": [
            source_event_id
            for candidate_ref in pk_refs
            if candidate_ref != actor_ref
            and (source_event_id := latest_by_speaker.get(candidate_ref)) is not None
        ],
        "latest_vote_result_ref": latest_vote_result_ref,
    }
    return {key: value for key, value in focus.items() if value is not None and value != []}


def _dict_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, dict)]


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def _statement_chars(statements: list[dict[str, Any]]) -> int:
    return sum(len(str(item.get("speech") or "")) for item in statements)


def _serialized_chars(value: Any) -> int:
    return len(json.dumps(value, ensure_ascii=False, separators=(",", ":")))
