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
    _require_current_schema_version(
        model_view_schema_version,
        expected=DISCOURSE_MODEL_VIEW_SCHEMA_VERSION,
        kind="model_view",
    )
    statements = _dict_list(ledger.get("statements"))
    raw_claims = _dict_list(ledger.get("claims"))
    raw_questions = _dict_list(ledger.get("questions"))
    raw_relations = _dict_list(ledger.get("relations"))
    ledger_schema_version = _positive_int(
        ledger.get("ledger_schema_version"),
        default=DISCOURSE_MODEL_VIEW_SCHEMA_VERSION,
    )
    if ledger_schema_version != DISCOURSE_MODEL_VIEW_SCHEMA_VERSION:
        raise ValueError("unsupported_discourse_ledger_schema_version")
    statement_by_ref = {
        str(statement["source_event_id"]): statement
        for statement in statements
        if isinstance(statement.get("source_event_id"), str)
    }
    derivation_rejections = _dict_list(ledger.get("derivation_rejections"))

    claims: list[dict[str, Any]] = []
    invalid_claim_count = 0
    for claim in raw_claims:
        source_event_ref = claim.get("source_event_ref")
        if (
            not isinstance(source_event_ref, str)
            or source_event_ref not in statement_by_ref
            or not _has_complete_derivation(claim)
            or not _valid_claim_shape(claim)
        ):
            invalid_claim_count += 1
            derivation_rejections.append(
                _view_rejection(claim, kind="claim", reason="invalid_source_or_derivation")
            )
            continue
        claims.append(claim)

    current_round_no = ledger.get("current_round_no")
    scoped_questions: list[dict[str, Any]] = []
    current_scope_question_count = 0
    out_of_scope_question_count = 0
    invalid_question_count = 0
    out_of_scope_question_ids: set[str] = set()
    for question in raw_questions:
        asked_in = question.get("asked_in")
        if not isinstance(asked_in, dict) or asked_in.get("round_no") != current_round_no:
            out_of_scope_question_count += 1
            if isinstance(question.get("question_id"), str):
                out_of_scope_question_ids.add(str(question["question_id"]))
            continue
        current_scope_question_count += 1
        source_event_ref = question.get("source_event_ref")
        if (
            not isinstance(source_event_ref, str)
            or source_event_ref not in statement_by_ref
            or question.get("address_resolution") not in {"resolved", "unresolved"}
            or question.get("response_status") not in {"none_detected", "response_detected"}
            or not _has_complete_derivation(question)
            or not _valid_question_shape(
                question,
                source_statement=statement_by_ref.get(str(source_event_ref)),
            )
        ):
            invalid_question_count += 1
            derivation_rejections.append(
                _view_rejection(question, kind="question", reason="invalid_source_or_derivation")
            )
            continue
        scoped_questions.append(question)

    annotations_by_source: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for claim in claims:
        source_event_ref = claim.get("source_event_ref")
        if isinstance(source_event_ref, str):
            annotations_by_source[source_event_ref].append(_claim_annotation(claim))

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
        scoped_questions,
        statements=statements,
        claims=claims,
        actor_ref=actor_ref,
        task=task,
    )
    (
        projected_relations,
        invalid_relation_count,
        out_of_scope_relation_count,
    ) = _project_relations(
        raw_relations,
        questions=projected_questions,
        statement_by_ref=statement_by_ref,
        out_of_scope_question_ids=out_of_scope_question_ids,
        derivation_rejections=derivation_rejections,
    )
    responded_question_ids = {
        str(relation["to_question_id"])
        for relation in projected_relations
        if isinstance(relation.get("to_question_id"), str)
    }
    for question in projected_questions:
        question["response_status"] = (
            "response_detected"
            if question.get("question_id") in responded_question_ids
            else "none_detected"
        )
        if question["response_status"] == "response_detected":
            question.pop("response_status_semantics", None)
            question.pop("reply_opportunity", None)
            continue
        question["response_status_semantics"] = "no_response_detected_after_question"
        if _is_scheduled_speech_task(task):
            speech_order = _string_list(task.get("speech_order"))
            current_position = (
                speech_order.index(actor_ref)
                if actor_ref is not None and actor_ref in speech_order
                else None
            )
            reply_opportunity = _reply_opportunity(
                question.get("addressed_to"),
                speech_order=speech_order,
                current_position=current_position,
            )
            if reply_opportunity is not None:
                question["reply_opportunity"] = reply_opportunity
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
    source_rules["prior_coverage_rule"] = (
        "prior_coverage=already_publicly_reported 表示被提问者在问题之前已公开报告同一事项；"
        "此前报告不是对后来问题的回应，response_status 只按后续发言判定"
    )
    model_view = {
        "ledger_schema_version": ledger.get("ledger_schema_version"),
        "model_view_schema_version": model_view_schema_version,
        "source_rules": source_rules,
        "current_round_no": ledger.get("current_round_no"),
        "timeline": timeline,
        "questions": projected_questions,
        "relations": projected_relations,
        "focus": focus,
    }
    record_seqs = [
        value
        for statement in statements
        for value in (statement.get("record_seq"),)
        if isinstance(value, int) and not isinstance(value, bool)
    ]
    current_round_statements = [
        statement
        for statement in statements
        if isinstance(statement.get("occurred_in"), dict)
        and statement["occurred_in"].get("round_no") == current_round_no
    ]
    ledger_derivation_metadata = (
        dict(ledger.get("derivation_metadata"))
        if isinstance(ledger.get("derivation_metadata"), dict)
        else {}
    )
    metadata = {
        "model_view_schema_version": model_view_schema_version,
        "ledger_statement_count": len(statements),
        "ledger_statement_char_count": _statement_chars(statements),
        "ledger_claim_count": len(raw_claims),
        "ledger_question_count": len(raw_questions),
        "ledger_relation_count": len(raw_relations),
        "model_view_statement_count": len(timeline),
        "model_view_statement_char_count": _statement_chars(timeline),
        "model_view_claim_annotation_count": sum(len(item["annotations"]) for item in timeline),
        "model_view_question_count": len(projected_questions),
        "model_view_relation_count": len(projected_relations),
        "source_claim_candidate_count": _nonnegative_int(
            ledger_derivation_metadata.get("source_claim_candidate_count"),
            default=len(raw_claims),
        ),
        "emitted_claim_count": len(claims),
        "rejected_claim_count": _nonnegative_int(
            ledger_derivation_metadata.get("rejected_claim_count"),
            default=0,
        )
        + invalid_claim_count,
        "source_question_count": len(raw_questions),
        "current_scope_question_count": current_scope_question_count,
        "emitted_question_count": len(projected_questions),
        "out_of_scope_question_count": out_of_scope_question_count,
        "invalid_question_count": invalid_question_count,
        "source_relation_count": len(raw_relations),
        "emitted_relation_count": len(projected_relations),
        "out_of_scope_relation_count": out_of_scope_relation_count,
        "invalid_relation_count": invalid_relation_count,
        "derivation_rejections": derivation_rejections,
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
        "none_detected_question_count": sum(
            question.get("response_status") == "none_detected" for question in projected_questions
        ),
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
    metadata["prior_coverage_question_count"] = sum(
        question.get("prior_coverage") == "already_publicly_reported"
        for question in projected_questions
    )
    return model_view, metadata


def _claim_annotation(claim: dict[str, Any]) -> dict[str, Any]:
    redundant_fields = {
        "source_event_ref",
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
) -> dict[str, Any]:
    return {key: value for key, value in question.items() if key not in {"exact_quote"}}


def _project_questions(
    questions: list[dict[str, Any]],
    *,
    statements: list[dict[str, Any]],
    claims: list[dict[str, Any]],
    actor_ref: str | None,
    task: dict[str, Any],
) -> list[dict[str, Any]]:
    speech_order = _string_list(task.get("speech_order"))
    current_position = (
        speech_order.index(actor_ref)
        if actor_ref is not None and actor_ref in speech_order
        else None
    )
    projected: list[dict[str, Any]] = []
    for question in questions:
        item = _question_reference(question)
        target_ref = item.get("addressed_to")
        if item.get("response_status") == "none_detected":
            item["response_status_semantics"] = "no_response_detected_after_question"
            reply_opportunity = (
                _reply_opportunity(
                    target_ref,
                    speech_order=speech_order,
                    current_position=current_position,
                )
                if _is_scheduled_speech_task(task)
                else None
            )
            if reply_opportunity is not None:
                item["reply_opportunity"] = reply_opportunity
        if isinstance(target_ref, str):
            past_investigation_v5 = question.get("topic") == "past_investigation_result"
            raw_prior_refs = [
                str(statement["source_event_id"])
                for statement in statements
                if statement.get("speaker_ref") == target_ref
                and (past_investigation_v5 or _same_round(statement, question=question))
                and _statement_precedes_question(statement, question=question)
                and speech_matches_question_topic(
                    str(statement.get("speech") or ""),
                    topic=str(question.get("topic") or ""),
                )
                and isinstance(statement.get("source_event_id"), str)
            ]
            prior_refs = raw_prior_refs
            matching_investigation_claims: list[dict[str, Any]] = []
            referenced_night_no = question.get("referenced_night_no")
            if past_investigation_v5 and isinstance(referenced_night_no, int):
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
                    str(claim["source_event_ref"])
                    for claim in matching_investigation_claims
                    if isinstance(claim.get("source_event_ref"), str)
                }
                prior_refs = [ref for ref in raw_prior_refs if ref in matching_refs]
            if prior_refs:
                item["prior_relevant_statement_refs"] = prior_refs
                if (
                    past_investigation_v5
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
        and claim.get("source_event_ref") in prior_refs
        and isinstance(claimed_action_in, dict)
        and claimed_action_in.get("period") == "night"
        and claimed_action_in.get("round_no") == referenced_night_no
        and isinstance(claim.get("target_ref"), str)
        and claim.get("claimed_result") in {"werewolves", "villagers"}
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


def _is_scheduled_speech_task(task: dict[str, Any]) -> bool:
    action_type = task.get("type", task.get("action_type"))
    return isinstance(action_type, str) and (
        "speech" in action_type or action_type.endswith("last_words")
    )


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
    asked_record_seq = question.get("asked_at_seq")
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


def _project_relations(
    relations: list[dict[str, Any]],
    *,
    questions: list[dict[str, Any]],
    statement_by_ref: dict[str, dict[str, Any]],
    out_of_scope_question_ids: set[str],
    derivation_rejections: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], int, int]:
    question_by_id = {
        str(question["question_id"]): question
        for question in questions
        if isinstance(question.get("question_id"), str)
    }
    projected: list[dict[str, Any]] = []
    invalid_count = 0
    out_of_scope_count = 0
    for relation in relations:
        question_id = relation.get("to_question_id")
        if isinstance(question_id, str) and question_id in out_of_scope_question_ids:
            out_of_scope_count += 1
            continue
        from_event_ref = relation.get("from_event_ref")
        question = question_by_id.get(question_id) if isinstance(question_id, str) else None
        response_statement = (
            statement_by_ref.get(from_event_ref) if isinstance(from_event_ref, str) else None
        )
        if (
            relation.get("type") != "response_to_question"
            or question is None
            or response_statement is None
            or relation.get("temporal_order_valid") is not True
            or not _has_complete_derivation(relation)
            or response_statement.get("speaker_ref") != question.get("addressed_to")
            or not _response_follows_question(response_statement, question=question)
        ):
            invalid_count += 1
            derivation_rejections.append(
                _view_rejection(
                    relation,
                    kind="relation",
                    reason="invalid_reference_or_semantics",
                )
            )
            continue
        projected.append(
            {
                "relation_id": relation.get("relation_id"),
                "type": "response_to_question",
                "from_event_ref": from_event_ref,
                "to_question_id": question_id,
                "temporal_order_valid": True,
                "derivation": dict(relation["derivation"]),
            }
        )
    return projected, invalid_count, out_of_scope_count


def _response_follows_question(
    statement: dict[str, Any],
    *,
    question: dict[str, Any],
) -> bool:
    response_occurrence = statement.get("occurred_in")
    asked_in = question.get("asked_in")
    if (
        not isinstance(response_occurrence, dict)
        or not isinstance(asked_in, dict)
        or response_occurrence.get("round_no") != asked_in.get("round_no")
    ):
        return False
    response_seq = statement.get("record_seq")
    asked_at_seq = question.get("asked_at_seq")
    if (
        isinstance(response_seq, int)
        and not isinstance(response_seq, bool)
        and isinstance(asked_at_seq, int)
        and not isinstance(asked_at_seq, bool)
    ):
        return response_seq > asked_at_seq
    response_turn = statement.get("turn_index")
    asked_turn = question.get("asked_turn_index")
    return (
        isinstance(response_turn, int)
        and not isinstance(response_turn, bool)
        and isinstance(asked_turn, int)
        and not isinstance(asked_turn, bool)
        and response_turn > asked_turn
    )


def _valid_claim_shape(claim: dict[str, Any]) -> bool:
    if claim.get("authority") != "player_claim_unverified":
        return False
    claim_type = claim.get("claim_type")
    if claim_type == "role_claim":
        return isinstance(claim.get("claimed_role"), str)
    if claim_type == "team_claim":
        return claim.get("claimed_team") in {"villagers", "werewolves"}
    if claim_type == "investigation_claim":
        claimed_action_in = claim.get("claimed_action_in")
        return (
            isinstance(claimed_action_in, dict)
            and claimed_action_in.get("period") == "night"
            and isinstance(claimed_action_in.get("round_no"), int)
            and not isinstance(claimed_action_in.get("round_no"), bool)
            and claimed_action_in["round_no"] > 0
            and isinstance(claim.get("target_ref"), str)
            and claim.get("claimed_result") in {"werewolves", "villagers"}
        )
    if claim_type == "future_investigation_plan":
        return isinstance(claim.get("target_ref"), str) and claim.get("specificity") in {
            "specific_target",
            "direction_only",
        }
    if claim_type == "vote_stance":
        return isinstance(claim.get("target_ref"), str)
    if claim_type == "player_assessment":
        refs = claim.get("subject_refs")
        return isinstance(refs, list) and bool(refs) and all(isinstance(ref, str) for ref in refs)
    if claim_type == "secondary_paraphrase":
        return isinstance(claim.get("reported_speaker_ref"), str)
    return False


def _valid_question_shape(
    question: dict[str, Any],
    *,
    source_statement: dict[str, Any] | None,
) -> bool:
    if (
        source_statement is None
        or question.get("source_authority") != "player_claim_unverified"
        or question.get("asked_by") != source_statement.get("speaker_ref")
        or not isinstance(question.get("question_id"), str)
        or not isinstance(question.get("topic"), str)
    ):
        return False
    address_resolution = question.get("address_resolution")
    addressed_to = question.get("addressed_to")
    if address_resolution == "resolved" and not isinstance(addressed_to, str):
        return False
    if address_resolution == "unresolved" and addressed_to is not None:
        return False
    requested_fields = question.get("requested_fields")
    if requested_fields is not None and (
        not isinstance(requested_fields, list)
        or not requested_fields
        or any(field not in {"target_ref", "claimed_result"} for field in requested_fields)
    ):
        return False
    referenced_night_no = question.get("referenced_night_no")
    return referenced_night_no is None or (
        isinstance(referenced_night_no, int)
        and not isinstance(referenced_night_no, bool)
        and referenced_night_no > 0
    )


def _has_complete_derivation(item: dict[str, Any]) -> bool:
    derivation = item.get("derivation")
    return (
        isinstance(derivation, dict)
        and derivation.get("kind") == "deterministic_heuristic"
        and derivation.get("validator_version") == 1
        and derivation.get("validation_status") == "complete"
    )


def _view_rejection(
    item: dict[str, Any],
    *,
    kind: str,
    reason: str,
) -> dict[str, Any]:
    source_event_ref = item.get("source_event_ref")
    if not isinstance(source_event_ref, str):
        source_event_ref = item.get("from_event_ref")
    rejection = {
        "source_event_ref": source_event_ref,
        "kind": kind,
        "reason": reason,
    }
    return {key: value for key, value in rejection.items() if value is not None}


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
        "unresponded_question_refs": [
            str(question["question_id"])
            for question in questions
            if question.get("response_status") == "none_detected"
            and actor_ref is not None
            and question.get("addressed_to") == actor_ref
        ],
        "unresponded_question_contexts": [
            {
                key: question[key]
                for key in (
                    "question_id",
                    "asked_by",
                    "addressed_to",
                    "topic",
                    "address_resolution",
                    "response_status",
                    "requested_fields",
                    "referenced_night_no",
                    "reply_opportunity",
                    "prior_relevant_statement_refs",
                    "prior_coverage",
                )
                if key in question
            }
            for question in questions
            if question.get("response_status") == "none_detected"
            and isinstance(question.get("addressed_to"), str)
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


def _nonnegative_int(value: Any, *, default: int) -> int:
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return value
    return default


def _require_current_schema_version(value: int, *, expected: int, kind: str) -> None:
    if value != expected:
        raise ValueError(f"unsupported_discourse_{kind}_schema_version")


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def _statement_chars(statements: list[dict[str, Any]]) -> int:
    return sum(len(str(item.get("speech") or "")) for item in statements)


def _serialized_chars(value: Any) -> int:
    return len(json.dumps(value, ensure_ascii=False, separators=(",", ":")))
