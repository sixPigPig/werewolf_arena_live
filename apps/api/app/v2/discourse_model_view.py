from __future__ import annotations

from collections import defaultdict
import json
from typing import Any

from app.v2.discourse_ledger import speech_matches_question_topic
from app.v2.model_context_contract import DISCOURSE_MODEL_VIEW_SCHEMA_VERSION


def build_discourse_model_view(
    ledger: dict[str, Any],
    *,
    actor_ref: str | None,
    task: dict[str, Any],
    candidate_refs: list[str],
    latest_vote_result_ref: str | None,
    model_view_schema_version: int = DISCOURSE_MODEL_VIEW_SCHEMA_VERSION,
) -> tuple[dict[str, Any], dict[str, Any]]:
    statements = _dict_list(ledger.get("statements"))
    claims = _dict_list(ledger.get("claims"))
    questions = _dict_list(ledger.get("questions"))
    relations = _dict_list(ledger.get("relations"))
    ledger_schema_version = _positive_int(ledger.get("ledger_schema_version"), default=2)

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
    projected_questions = _project_questions(
        questions,
        statements=statements,
        claims=claims,
        actor_ref=actor_ref,
        task=task,
        ledger_schema_version=ledger_schema_version,
        model_view_schema_version=model_view_schema_version,
    )
    focus = _build_focus(
        statements=statements,
        questions=projected_questions,
        actor_ref=actor_ref,
        task=task,
        candidate_refs=candidate_refs,
        latest_vote_result_ref=latest_vote_result_ref,
    )
    source_rules = dict(ledger.get("source_rules") or {})
    source_rules.update(
        {
            "turn_opportunity_rule": (
                "reply_opportunity=awaiting_scheduled_turn 表示被提问者本轮尚未轮到发言；"
                "不得描述成拒绝回应、故意沉默或轮到后仍不解释"
            ),
            "prior_explanation_rule": (
                "prior_relevant_statement_refs 是问题之前同一玩家对相关主题的第一方原话；"
                "它不是对后来问题的回答，但判断其是否曾解释时优先于其他玩家的二手复述"
            ),
        }
    )
    if model_view_schema_version >= 4:
        source_rules["prior_coverage_rule"] = (
            "prior_coverage=already_publicly_reported 表示被提问者在问题之前已公开报告同一事项；"
            "此前报告不是对后来问题的回答，问题仍需按后续发言判断 status"
        )
    model_view = {
        "ledger_schema_version": ledger.get("ledger_schema_version"),
        "model_view_schema_version": model_view_schema_version,
        "source_rules": source_rules,
        "current_round_no": ledger.get("current_round_no"),
        "timeline": timeline,
        "questions": projected_questions,
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
        "model_view_schema_version": model_view_schema_version,
        "ledger_statement_count": len(statements),
        "ledger_statement_char_count": _statement_chars(statements),
        "ledger_claim_count": len(claims),
        "ledger_question_count": len(questions),
        "ledger_relation_count": len(relations),
        "model_view_statement_count": len(timeline),
        "model_view_statement_char_count": _statement_chars(timeline),
        "model_view_claim_annotation_count": sum(len(item["annotations"]) for item in timeline),
        "model_view_question_count": len(projected_questions),
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
        "awaiting_scheduled_turn_question_count": sum(
            question.get("reply_opportunity") == "awaiting_scheduled_turn"
            for question in projected_questions
        ),
        "prior_relevant_statement_question_count": sum(
            bool(question.get("prior_relevant_statement_refs")) for question in projected_questions
        ),
        "selection_profile": "full_public_history_with_reference_only_focus",
        "source_record_seq_min": min(record_seqs, default=None),
        "source_record_seq_max": max(record_seqs, default=None),
        "ledger_serialized_char_count": _serialized_chars(ledger),
        "model_view_serialized_char_count": _serialized_chars(model_view),
    }
    if model_view_schema_version >= 4:
        metadata["prior_coverage_question_count"] = sum(
            question.get("prior_coverage") == "already_publicly_reported"
            for question in projected_questions
        )
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


def _question_reference(
    question: dict[str, Any],
    *,
    model_view_schema_version: int,
) -> dict[str, Any]:
    item = {key: value for key, value in question.items() if key not in {"exact_quote"}}
    if model_view_schema_version < 4:
        item.pop("address_resolution", None)
        if item.get("status") == "open" and not isinstance(item.get("addressed_to"), str):
            item["status"] = "unresolved_target"
    return item


def _project_questions(
    questions: list[dict[str, Any]],
    *,
    statements: list[dict[str, Any]],
    claims: list[dict[str, Any]],
    actor_ref: str | None,
    task: dict[str, Any],
    ledger_schema_version: int,
    model_view_schema_version: int,
) -> list[dict[str, Any]]:
    speech_order = _string_list(task.get("speech_order"))
    current_position = (
        speech_order.index(actor_ref)
        if actor_ref is not None and actor_ref in speech_order
        else None
    )
    projected: list[dict[str, Any]] = []
    for question in questions:
        item = _question_reference(
            question,
            model_view_schema_version=model_view_schema_version,
        )
        target_ref = item.get("addressed_to")
        if item.get("status") == "open":
            item["status_semantics"] = "no_response_after_question"
            reply_opportunity = _reply_opportunity(
                target_ref,
                speech_order=speech_order,
                current_position=current_position,
            )
            if reply_opportunity is not None:
                item["reply_opportunity"] = reply_opportunity
        if isinstance(target_ref, str):
            past_investigation_v4 = (
                model_view_schema_version >= 4
                and question.get("topic") == "past_investigation_result"
            )
            raw_prior_refs = [
                str(statement["source_event_id"])
                for statement in statements
                if statement.get("speaker_ref") == target_ref
                and (past_investigation_v4 or _same_round(statement, question=question))
                and _statement_precedes_question(statement, question=question)
                and speech_matches_question_topic(
                    str(statement.get("speech") or ""),
                    topic=str(question.get("topic") or ""),
                    ledger_schema_version=ledger_schema_version,
                )
                and isinstance(statement.get("source_event_id"), str)
            ]
            prior_refs = raw_prior_refs
            matching_investigation_claims: list[dict[str, Any]] = []
            referenced_night_no = question.get("referenced_night_no")
            if past_investigation_v4 and isinstance(referenced_night_no, int):
                matching_investigation_claims = [
                    claim
                    for claim in claims
                    if _qualifying_prior_investigation_claim(
                        claim,
                        target_ref=target_ref,
                        prior_refs=raw_prior_refs,
                        referenced_night_no=referenced_night_no,
                    )
                ]
                matching_refs = {
                    str(claim["source_event_id"])
                    for claim in matching_investigation_claims
                    if isinstance(claim.get("source_event_id"), str)
                }
                prior_refs = [ref for ref in raw_prior_refs if ref in matching_refs]
            if prior_refs:
                item["prior_relevant_statement_refs"] = prior_refs
                if (
                    past_investigation_v4
                    and isinstance(referenced_night_no, int)
                    and _claims_cover_requested_fields(
                        matching_investigation_claims,
                        requested_fields=_string_list(question.get("requested_fields")),
                    )
                ):
                    item["prior_coverage"] = "already_publicly_reported"
        projected.append(item)
    return projected


def _qualifying_prior_investigation_claim(
    claim: dict[str, Any],
    *,
    target_ref: str,
    prior_refs: list[str],
    referenced_night_no: int,
) -> bool:
    claimed_action_in = claim.get("claimed_action_in")
    return (
        claim.get("claim_type") == "investigation_claim"
        and claim.get("source_kind") == "speaker_first_party_claim"
        and claim.get("speaker_ref") == target_ref
        and claim.get("source_event_id") in prior_refs
        and isinstance(claimed_action_in, dict)
        and claimed_action_in.get("period") == "night"
        and claimed_action_in.get("round_no") == referenced_night_no
        and (
            isinstance(claim.get("target_ref"), str)
            or claim.get("claimed_result") in {"werewolves", "villagers"}
        )
    )


def _claims_cover_requested_fields(
    claims: list[dict[str, Any]],
    *,
    requested_fields: list[str],
) -> bool:
    required = requested_fields or ["target_ref", "claimed_result"]
    return all(
        any(
            isinstance(claim.get("target_ref"), str)
            if field == "target_ref"
            else claim.get("claimed_result") in {"werewolves", "villagers"}
            if field == "claimed_result"
            else False
            for claim in claims
        )
        for field in required
    )


def _reply_opportunity(
    target_ref: Any,
    *,
    speech_order: list[str],
    current_position: int | None,
) -> str | None:
    if not isinstance(target_ref, str) or current_position is None:
        return None
    if target_ref not in speech_order:
        return "not_in_current_speech_order"
    target_position = speech_order.index(target_ref)
    if target_position > current_position:
        return "awaiting_scheduled_turn"
    if target_position == current_position:
        return "current_speaker_turn"
    return "scheduled_turn_passed"


def _same_round(statement: dict[str, Any], *, question: dict[str, Any]) -> bool:
    occurred_in = statement.get("occurred_in")
    asked_in = question.get("asked_in")
    return (
        isinstance(occurred_in, dict)
        and isinstance(asked_in, dict)
        and occurred_in.get("round_no") == asked_in.get("round_no")
    )


def _statement_precedes_question(
    statement: dict[str, Any],
    *,
    question: dict[str, Any],
) -> bool:
    statement_record_seq = statement.get("record_seq")
    asked_record_seq = question.get("asked_record_seq")
    if (
        isinstance(statement_record_seq, int)
        and not isinstance(statement_record_seq, bool)
        and isinstance(asked_record_seq, int)
        and not isinstance(asked_record_seq, bool)
    ):
        return statement_record_seq < asked_record_seq
    statement_turn_index = statement.get("turn_index")
    asked_turn_index = question.get("asked_turn_index")
    return (
        isinstance(statement_turn_index, int)
        and not isinstance(statement_turn_index, bool)
        and isinstance(asked_turn_index, int)
        and not isinstance(asked_turn_index, bool)
        and statement_turn_index < asked_turn_index
    )


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
        "open_question_contexts": [
            {
                key: question[key]
                for key in (
                    "question_id",
                    "asked_by",
                    "addressed_to",
                    "topic",
                    "address_resolution",
                    "requested_fields",
                    "referenced_night_no",
                    "reply_opportunity",
                    "prior_relevant_statement_refs",
                    "prior_coverage",
                )
                if key in question
            }
            for question in questions
            if question.get("status") == "open" and isinstance(question.get("addressed_to"), str)
        ],
        "first_party_relevant_statement_refs": list(
            dict.fromkeys(
                ref
                for question in questions
                for ref in _string_list(question.get("prior_relevant_statement_refs"))
            )
        ),
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


def _positive_int(value: Any, *, default: int) -> int:
    if isinstance(value, int) and not isinstance(value, bool) and value > 0:
        return value
    return default


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def _statement_chars(statements: list[dict[str, Any]]) -> int:
    return sum(len(str(item.get("speech") or "")) for item in statements)


def _serialized_chars(value: Any) -> int:
    return len(json.dumps(value, ensure_ascii=False, separators=(",", ":")))
