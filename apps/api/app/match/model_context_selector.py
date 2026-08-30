from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import re
from typing import Any


MODEL_CONTEXT_SELECTOR_VERSION = 3
_RECENT_CANDIDATE_EVIDENCE_PER_CANDIDATE = 2

_ORDINARY_OLD_KINDS = {
    "day_vote",
    "player_statement",
    "speech_turn_skipped_technical",
}


@dataclass(frozen=True)
class KnownEventsSelection:
    events: list[dict[str, Any]]
    audit: dict[str, Any]


def select_known_events_v13(
    events: list[dict[str, Any]],
    *,
    actor_ref: str | None,
    current_round_no: int,
    candidate_refs: list[str],
    model_view: dict[str, Any],
    rolling_memory_cutoff_seq: int | None = None,
    future_filtered: list[dict[str, Any]] | None = None,
) -> KnownEventsSelection:
    """Project full visible history into deterministic player working memory.

    This selector never derives alignments, wolf teams, or an action answer. It
    only chooses source events using mechanical scope, recency, participation,
    and citation-reference closure.
    """

    source_events = [dict(event) for event in events if isinstance(event, dict)]
    future_items = [dict(item) for item in (future_filtered or []) if isinstance(item, dict)]
    event_by_ref = {
        str(event["event_ref"]): event
        for event in source_events
        if isinstance(event.get("event_ref"), str)
    }
    memory_refs = [ref for ref, event in event_by_ref.items() if _is_actor_memory(event)]
    latest_memory_ref = max(
        memory_refs,
        key=lambda ref: (_event_sequence(event_by_ref[ref]), ref),
        default=None,
    )

    retained: dict[str, tuple[str, str]] = {}
    omitted: dict[str, tuple[str, str]] = {}

    for event_ref, event in event_by_ref.items():
        if _is_actor_memory(event):
            if event_ref == latest_memory_ref:
                retained[event_ref] = ("actor_memory", "latest_actor_memory")
            else:
                omitted[event_ref] = ("actor_memory", "superseded_actor_memory")
            continue
        if event.get("visibility") == "actor_private":
            retained[event_ref] = (
                "actor_private_fact",
                "actor_private_authoritative_fact",
            )
            continue
        if (
            rolling_memory_cutoff_seq is not None
            and _event_sequence(event) > rolling_memory_cutoff_seq
        ):
            retained[event_ref] = (
                "rolling_memory_increment",
                "not_yet_archived_in_actor_memory",
            )
            continue
        if _event_round_no(event) == current_round_no:
            retained[event_ref] = ("current_round", "current_round_raw_event")
            continue
        if _is_cross_round_mechanical_anchor(event):
            retained[event_ref] = (
                "mechanical_anchor",
                "cross_round_mechanical_anchor",
            )
            continue
        if _is_first_party_claim_source(event):
            retained[event_ref] = (
                "first_party_claim",
                "cross_round_first_party_role_or_alignment_claim",
            )
            continue
        if _is_last_words(event):
            retained[event_ref] = ("last_words", "cross_round_last_words")
            continue
        if isinstance(actor_ref, str) and _event_structurally_references(event, actor_ref):
            retained[event_ref] = (
                "actor_history",
                "actor_participation_or_direct_interaction",
            )

    citation_refs = _citation_closure_refs(
        model_view,
        retained_refs=set(retained),
        actor_ref=actor_ref,
    )
    for event_ref in citation_refs:
        if event_ref in event_by_ref and event_ref not in retained:
            retained[event_ref] = ("citation_closure", "referenced_source_event")
            omitted.pop(event_ref, None)

    normalized_candidates = sorted(
        {ref for ref in candidate_refs if isinstance(ref, str)},
        key=_seat_ref_sort_key,
    )
    for candidate_ref in normalized_candidates:
        evidence = [
            event
            for event in source_events
            if str(event.get("event_ref") or "") not in retained
            and not _is_actor_memory(event)
            and event.get("kind") in _ORDINARY_OLD_KINDS
            and _event_structurally_references(event, candidate_ref)
        ]
        evidence.sort(
            key=lambda event: (
                _event_sequence(event),
                str(event.get("event_ref") or ""),
            ),
            reverse=True,
        )
        for event in evidence[:_RECENT_CANDIDATE_EVIDENCE_PER_CANDIDATE]:
            event_ref = str(event["event_ref"])
            retained[event_ref] = ("candidate_evidence", "recent_candidate_evidence")
            omitted.pop(event_ref, None)

    for event_ref, event in event_by_ref.items():
        if event_ref in retained or event_ref in omitted:
            continue
        kind = event.get("kind")
        if kind == "day_vote":
            omitted[event_ref] = ("ordinary_history", "old_ordinary_vote")
        elif kind == "player_statement":
            omitted[event_ref] = (
                "ordinary_history",
                "old_non_salient_player_statement",
            )
        elif kind == "speech_turn_skipped_technical":
            omitted[event_ref] = ("ordinary_history", "old_technical_speech_skip")
        else:
            omitted[event_ref] = ("ordinary_history", "old_non_anchor_event")

    selected_events = [
        event for event in source_events if str(event.get("event_ref") or "") in retained
    ]
    retained_entries = [
        _audit_entry(event, retained[str(event["event_ref"])])
        for event in source_events
        if str(event.get("event_ref") or "") in retained
    ]
    omitted_entries = [
        _audit_entry(event, omitted[str(event["event_ref"])])
        for event in source_events
        if str(event.get("event_ref") or "") in omitted
    ]
    future_entries = [
        {
            "event_ref": str(item.get("event_ref") or "unknown"),
            "reason": "event_after_action_cutoff",
        }
        for item in future_items
    ]

    retained_type_counts = _kind_counts(selected_events)
    omitted_type_counts = _kind_counts(
        [event for event in source_events if str(event.get("event_ref") or "") in omitted]
    )
    future_type_counts = Counter(str(item.get("kind") or "unknown") for item in future_items)
    source_type_counts = Counter(retained_type_counts)
    source_type_counts.update(omitted_type_counts)
    source_type_counts.update(future_type_counts)

    latest_memory = event_by_ref.get(latest_memory_ref) if latest_memory_ref else None
    memory_cutoff, memory_hash = _actor_memory_snapshot_audit(latest_memory)
    audit = {
        "version": MODEL_CONTEXT_SELECTOR_VERSION,
        "source_count": len(source_events) + len(future_items),
        "retained_count": len(retained_entries),
        "omitted_count": len(omitted_entries),
        "future_filtered_count": len(future_entries),
        "retained": retained_entries,
        "omitted": omitted_entries,
        "future_filtered": future_entries,
        "latest_actor_memory_ref": latest_memory_ref,
        "latest_actor_memory_cutoff_seq": memory_cutoff,
        "latest_actor_memory_hash": memory_hash,
        "source_type_counts": dict(sorted(source_type_counts.items())),
        "retained_type_counts": dict(sorted(retained_type_counts.items())),
        "omitted_type_counts": dict(sorted(omitted_type_counts.items())),
    }
    if audit["source_count"] != (
        audit["retained_count"] + audit["omitted_count"] + audit["future_filtered_count"]
    ):
        raise ValueError("model_context_selector_count_mismatch")
    return KnownEventsSelection(events=selected_events, audit=audit)


def _is_actor_memory(event: dict[str, Any]) -> bool:
    return event.get("authority") == "actor_memory" or event.get("kind") == "private_round_memory"


def _is_cross_round_mechanical_anchor(event: dict[str, Any]) -> bool:
    return event.get("authority") == "judge_fact" and event.get("kind") not in _ORDINARY_OLD_KINDS


def _is_first_party_claim_source(
    event: dict[str, Any],
) -> bool:
    if event.get("kind") != "player_statement":
        return False
    annotations = event.get("annotations")
    if not isinstance(annotations, list):
        return False
    return any(
        isinstance(annotation, dict)
        and annotation.get("claim_type")
        in {
            "role_claim",
            "team_claim",
            "investigation_claim",
        }
        for annotation in annotations
    )


def _is_last_words(event: dict[str, Any]) -> bool:
    stage = event.get("stage")
    return event.get("kind") == "player_statement" and (
        stage == "last_words" or (isinstance(stage, str) and stage.endswith("last_words"))
    )


def _event_round_no(event: dict[str, Any]) -> int | None:
    occurred_in = event.get("occurred_in")
    if not isinstance(occurred_in, dict):
        return None
    round_no = occurred_in.get("round_no")
    if isinstance(round_no, int) and not isinstance(round_no, bool) and round_no > 0:
        return round_no
    return None


def _event_sequence(event: dict[str, Any] | None) -> int:
    if not isinstance(event, dict):
        return 0
    for key in ("known_at_seq", "record_seq"):
        value = event.get(key)
        if isinstance(value, int) and not isinstance(value, bool) and value > 0:
            return value
    return 0


def _event_structurally_references(event: dict[str, Any], player_ref: str) -> bool:
    def contains(value: Any, *, key: str | None = None) -> bool:
        if isinstance(value, dict):
            return any(
                contains(item, key=str(item_key))
                for item_key, item in value.items()
                if item_key not in {"speech", "memory", "text", "decision_note"}
            )
        if isinstance(value, list):
            return any(contains(item, key=key) for item in value)
        return isinstance(value, str) and value == player_ref and key != "event_ref"

    if contains(event):
        return True
    speech = event.get("speech")
    if not isinstance(speech, str) or not player_ref.startswith("seat_"):
        return False
    seat = player_ref.removeprefix("seat_")
    return bool(
        re.search(rf"(?<!\d){re.escape(seat)}号", speech)
        or re.search(
            rf"(?<![A-Za-z0-9_]){re.escape(player_ref)}(?![A-Za-z0-9_])",
            speech,
        )
    )


def _citation_closure_refs(
    model_view: dict[str, Any],
    *,
    retained_refs: set[str],
    actor_ref: str | None,
) -> set[str]:
    questions = model_view.get("questions")
    questions = questions if isinstance(questions, list) else []
    relations = model_view.get("relations")
    relations = relations if isinstance(relations, list) else []
    related_question_ids: set[str] = set()
    closure: set[str] = set()
    for question in questions:
        if not isinstance(question, dict):
            continue
        question_id = question.get("question_id")
        source_ref = question.get("source_event_ref")
        actor_involved = isinstance(actor_ref, str) and actor_ref in {
            question.get("asked_by"),
            question.get("addressed_to"),
        }
        if not isinstance(question_id, str) or not isinstance(source_ref, str):
            continue
        if source_ref not in retained_refs and not actor_involved:
            continue
        related_question_ids.add(question_id)
        closure.add(source_ref)
        prior_refs = question.get("prior_relevant_statement_refs")
        if not isinstance(prior_refs, list):
            prior_refs = question.get("prior_relevant_event_refs")
        if isinstance(prior_refs, list):
            closure.update(ref for ref in prior_refs if isinstance(ref, str))
    for relation in relations:
        if not isinstance(relation, dict):
            continue
        if relation.get("to_question_id") not in related_question_ids:
            continue
        from_ref = relation.get("from_event_ref")
        if isinstance(from_ref, str):
            closure.add(from_ref)
    return closure


def _audit_entry(
    event: dict[str, Any],
    classification: tuple[str, str],
) -> dict[str, str]:
    category, reason = classification
    return {
        "event_ref": str(event["event_ref"]),
        "category": category,
        "reason": reason,
    }


def _kind_counts(events: list[dict[str, Any]]) -> dict[str, int]:
    return dict(sorted(Counter(str(event.get("kind") or "unknown") for event in events).items()))


def _actor_memory_snapshot_audit(
    event: dict[str, Any] | None,
) -> tuple[int | None, str | None]:
    if not isinstance(event, dict):
        return None, None
    data = event.get("data")
    data = data if isinstance(data, dict) else {}
    cutoff = data.get("source_cutoff_record_seq")
    if not isinstance(cutoff, int) or isinstance(cutoff, bool) or cutoff <= 0:
        cutoff = None
    memory_hash = data.get("memory_sha256")
    if not isinstance(memory_hash, str) or len(memory_hash) != 64:
        memory_hash = None
    return cutoff, memory_hash


def _seat_ref_sort_key(value: str) -> tuple[int, str]:
    if value.startswith("seat_") and value[5:].isdigit():
        return int(value[5:]), value
    return 10_000, value
