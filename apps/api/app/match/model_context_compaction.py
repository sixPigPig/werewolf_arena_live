from __future__ import annotations

from collections import Counter, defaultdict
from copy import deepcopy
import hashlib
import json
import math
import re
from typing import Any


KNOWN_EVENTS_CANONICAL_SCHEMA_VERSION = 5
KNOWN_EVENTS_COMPACT_SCHEMA_VERSION = 6
KNOWN_EVENTS_CURRENT_SCHEMA_VERSION = 7
KNOWN_EVENTS_COMPACT_ENCODING = "lossless_refs_v1"

_COMPACT_BASE_DEFAULTS = {
    "record_seq": "known_at_seq",
    "event_ref": "record_seq_string_when_equal",
}
_COMPACT_DEFAULT_KEYS = {
    *_COMPACT_BASE_DEFAULTS,
    "scope_ref_by_kind",
    "occurred_in_ref_by_kind",
}
_CANONICAL_TOP_LEVEL_KEYS = {"schema_version", "events", "questions", "relations"}
_COMPACT_TOP_LEVEL_KEYS = {
    "schema_version",
    "encoding",
    "defaults",
    "scope_catalog",
    "occurrence_catalog",
    "events",
    "annotations",
    "questions",
    "relations",
}
_COMPACT_EVENT_KEYS = {"scope_ref", "occurred_in_ref", "annotation_count"}
_READABLE_CATALOG_KEY = re.compile(r"^[a-z][a-z0-9_]{2,}$")


class ModelContextCompactionError(ValueError):
    """A stable fail-closed error raised for invalid V5/V6 known events."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def encode_known_events_v6(canonical_v5: dict[str, Any]) -> dict[str, Any]:
    """Encode a canonical Known Events V5 object without changing its semantics."""

    canonical = _validated_canonical_v5(canonical_v5)
    events = canonical["events"]
    record_seq_counts = Counter(_canonical_record_seq(event) for event in events)
    record_seq_counts.pop(None, None)

    scope_values = [_event_scope(event) for event in events]
    distinct_scopes = {_canonical_json_text(scope): scope for scope in scope_values}
    scope_base_key_counts = Counter(
        _scope_catalog_base_key(scope) for scope in distinct_scopes.values()
    )
    scope_catalog: dict[str, dict[str, Any]] = {}
    scope_ref_by_value: dict[str, str] = {}
    for scope in scope_values:
        serialized_scope = _canonical_json_text(scope)
        if serialized_scope in scope_ref_by_value:
            continue
        scope_ref = _scope_catalog_key(
            scope,
            base_key_count=scope_base_key_counts[_scope_catalog_base_key(scope)],
        )
        _insert_catalog_entry(scope_catalog, scope_ref, scope)
        scope_ref_by_value[serialized_scope] = scope_ref

    occurrence_catalog: dict[str, dict[str, Any]] = {}
    occurrence_ref_by_value: dict[str, str] = {}
    for event in events:
        occurrence = event.get("occurred_in")
        if occurrence is None:
            continue
        if not isinstance(occurrence, dict):
            _fail("known_events_v5_occurrence_shape")
        serialized_occurrence = _canonical_json_text(occurrence)
        if serialized_occurrence in occurrence_ref_by_value:
            continue
        occurrence_ref = _occurrence_catalog_key(occurrence)
        _insert_catalog_entry(occurrence_catalog, occurrence_ref, occurrence)
        occurrence_ref_by_value[serialized_occurrence] = occurrence_ref

    scope_ref_by_kind = _modal_ref_by_kind(
        (
            str(event["kind"]),
            scope_ref_by_value[_canonical_json_text(_event_scope(event))],
        )
        for event in events
    )
    occurred_in_ref_by_kind = _modal_ref_by_kind(
        (
            str(event["kind"]),
            occurrence_ref_by_value[_canonical_json_text(event["occurred_in"])],
        )
        for event in events
        if "occurred_in" in event
    )

    compact_events: list[dict[str, Any]] = []
    compact_annotations: list[dict[str, Any]] = []
    for event in events:
        event_ref = str(event["event_ref"])
        known_at_seq = int(event["known_at_seq"])
        record_seq = _canonical_record_seq(event)
        compact_event = deepcopy(event)

        for reserved_key in _COMPACT_EVENT_KEYS:
            if reserved_key in compact_event:
                _fail("known_events_v5_reserved_compact_field")

        compact_event.pop("visibility")
        compact_event.pop("authority")
        compact_event.pop("epistemic_status", None)
        compact_event.pop("owner_scope", None)
        compact_event.pop("owner_ref", None)
        scope_ref = scope_ref_by_value[_canonical_json_text(_event_scope(event))]
        if scope_ref != scope_ref_by_kind[str(event["kind"])]:
            compact_event["scope_ref"] = scope_ref

        occurrence = compact_event.pop("occurred_in", None)
        if occurrence is not None:
            occurrence_ref = occurrence_ref_by_value[_canonical_json_text(occurrence)]
            if occurrence_ref != occurred_in_ref_by_kind.get(str(event["kind"])):
                compact_event["occurred_in_ref"] = occurrence_ref
        elif str(event["kind"]) in occurred_in_ref_by_kind:
            compact_event["occurred_in_ref"] = None

        if "record_seq" not in event:
            # V5 represents an unknown source record sequence by absence. V6 must
            # make that exception to the default explicit.
            compact_event["record_seq"] = None
        elif record_seq == known_at_seq:
            compact_event.pop("record_seq")

        if (
            record_seq is not None
            and event_ref == str(record_seq)
            and record_seq_counts[record_seq] == 1
        ):
            compact_event.pop("event_ref")

        if "annotations" in event:
            annotations = event["annotations"]
            compact_event.pop("annotations")
            compact_event["annotation_count"] = len(annotations)
            for annotation_index, annotation in enumerate(annotations):
                if "source_event_ref" in annotation or "source_annotation_index" in annotation:
                    _fail("known_events_v5_annotation_reserved_field")
                compact_annotations.append(
                    {
                        "source_event_ref": event_ref,
                        "source_annotation_index": annotation_index,
                        **deepcopy(annotation),
                    }
                )

        compact_events.append(compact_event)

    compact = {
        "schema_version": KNOWN_EVENTS_COMPACT_SCHEMA_VERSION,
        "encoding": KNOWN_EVENTS_COMPACT_ENCODING,
        "defaults": {
            **_COMPACT_BASE_DEFAULTS,
            "scope_ref_by_kind": dict(sorted(scope_ref_by_kind.items())),
            "occurred_in_ref_by_kind": dict(sorted(occurred_in_ref_by_kind.items())),
        },
        "scope_catalog": dict(sorted(scope_catalog.items())),
        "occurrence_catalog": dict(sorted(occurrence_catalog.items())),
        "events": compact_events,
        "annotations": compact_annotations,
        "questions": deepcopy(canonical["questions"]),
        "relations": deepcopy(canonical["relations"]),
    }
    expanded = expand_known_events_v6(compact)
    if expanded != canonical:
        _fail("known_events_v6_round_trip_mismatch")
    if canonical_known_events_v5_sha256(expanded) != canonical_known_events_v5_sha256(canonical):
        _fail("known_events_v6_canonical_hash_mismatch")
    _validate_speech_round_trip(canonical, expanded)
    return compact


def encode_known_events_v7(canonical_v5: dict[str, Any]) -> dict[str, Any]:
    """Losslessly encode the selector-retained canonical Known Events V5 set.

    V7 deliberately does not claim that the database history was retained in
    full. Selection happens before this function and is audited separately in
    ``prompt_projection.selector``. Within that retained projection, the V7
    byte/field round-trip remains lossless.
    """

    compact = encode_known_events_v6(canonical_v5)
    compact["schema_version"] = KNOWN_EVENTS_CURRENT_SCHEMA_VERSION
    return compact


def expand_known_events_v6(compact_v6: dict[str, Any]) -> dict[str, Any]:
    """Expand a Known Events V6 object into its complete canonical V5 form."""

    compact = _validated_compact_v6_shape(compact_v6)
    defaults = compact["defaults"]
    scope_ref_by_kind = defaults["scope_ref_by_kind"]
    occurred_in_ref_by_kind = defaults["occurred_in_ref_by_kind"]
    scope_catalog = compact["scope_catalog"]
    occurrence_catalog = compact["occurrence_catalog"]
    compact_events = compact["events"]

    effective_record_seqs = [_compact_record_seq(event) for event in compact_events]
    record_seq_counts = Counter(effective_record_seqs)
    record_seq_counts.pop(None, None)

    canonical_events: list[dict[str, Any]] = []
    annotation_counts: dict[str, int | None] = {}
    event_refs: set[str] = set()
    for compact_event in compact_events:
        event = deepcopy(compact_event)
        kind = event.get("kind")
        if not isinstance(kind, str) or not kind:
            _fail("known_events_v6_kind")
        known_at_seq = _positive_int(event.get("known_at_seq"))
        if known_at_seq is None:
            _fail("known_events_v6_known_at_seq")

        record_seq = _compact_record_seq(event)
        event_ref_is_explicit = "event_ref" in event
        explicit_event_ref = event.pop("event_ref", None)
        if not event_ref_is_explicit:
            if record_seq is None or record_seq_counts[record_seq] != 1:
                _fail("known_events_v6_event_ref_ambiguous")
            event_ref = str(record_seq)
        elif not isinstance(explicit_event_ref, str) or not explicit_event_ref:
            _fail("known_events_v6_event_ref")
        else:
            event_ref = explicit_event_ref
        if event_ref in event_refs:
            _fail("duplicate_event_ref")
        event_refs.add(event_ref)

        scope_ref = event.pop("scope_ref", scope_ref_by_kind.get(kind))
        if not isinstance(scope_ref, str) or scope_ref not in scope_catalog:
            _fail("missing_scope_ref")
        scope = scope_catalog[scope_ref]
        for key, value in scope.items():
            if key in event and event[key] != value:
                _fail("compact_scope_field_conflict")
            event[key] = deepcopy(value)

        occurrence_explicit = "occurred_in_ref" in event
        occurrence_ref = event.pop(
            "occurred_in_ref",
            occurred_in_ref_by_kind.get(kind),
        )
        if occurrence_ref is not None:
            if not isinstance(occurrence_ref, str) or occurrence_ref not in occurrence_catalog:
                _fail("missing_occurrence_ref")
            if "occurred_in" in event:
                _fail("compact_occurrence_field_conflict")
            event["occurred_in"] = deepcopy(occurrence_catalog[occurrence_ref])
        elif occurrence_explicit and kind not in occurred_in_ref_by_kind:
            _fail("compact_occurrence_default_suppression_without_default")

        raw_annotation_count = event.pop("annotation_count", None)
        if raw_annotation_count is not None and (
            not isinstance(raw_annotation_count, int)
            or isinstance(raw_annotation_count, bool)
            or raw_annotation_count < 0
        ):
            _fail("compact_annotation_count")
        annotation_counts[event_ref] = raw_annotation_count

        event["event_ref"] = event_ref
        event.pop("record_seq", None)
        if record_seq is not None:
            event["record_seq"] = record_seq
        canonical_events.append(event)

    annotations_by_event: dict[str, dict[int, dict[str, Any]]] = defaultdict(dict)
    for raw_annotation in compact["annotations"]:
        if not isinstance(raw_annotation, dict):
            _fail("compact_annotation_shape")
        annotation = deepcopy(raw_annotation)
        source_event_ref = annotation.pop("source_event_ref", None)
        source_annotation_index = annotation.pop("source_annotation_index", None)
        if not isinstance(source_event_ref, str) or source_event_ref not in event_refs:
            _fail("missing_annotation_source_ref")
        if (
            not isinstance(source_annotation_index, int)
            or isinstance(source_annotation_index, bool)
            or source_annotation_index < 0
        ):
            _fail("compact_annotation_index")
        if source_annotation_index in annotations_by_event[source_event_ref]:
            _fail("compact_annotation_index_conflict")
        annotations_by_event[source_event_ref][source_annotation_index] = annotation

    for event in canonical_events:
        event_ref = str(event["event_ref"])
        indexed_annotations = annotations_by_event.get(event_ref, {})
        expected_count = annotation_counts[event_ref]
        if expected_count is None:
            if indexed_annotations:
                expected_count = len(indexed_annotations)
            else:
                continue
        if set(indexed_annotations) != set(range(expected_count)):
            _fail("compact_annotation_index_conflict")
        event["annotations"] = [indexed_annotations[index] for index in range(expected_count)]

    canonical = {
        "schema_version": KNOWN_EVENTS_CANONICAL_SCHEMA_VERSION,
        "events": canonical_events,
        "questions": deepcopy(compact["questions"]),
        "relations": deepcopy(compact["relations"]),
    }
    return _validated_canonical_v5(canonical)


def expand_known_events_v7(compact_v7: dict[str, Any]) -> dict[str, Any]:
    """Expand a V7 retained projection into canonical Known Events V5."""

    if not isinstance(compact_v7, dict):
        _fail("known_events_v7_shape")
    compact_v6 = deepcopy(compact_v7)
    if compact_v6.get("schema_version") != KNOWN_EVENTS_CURRENT_SCHEMA_VERSION:
        _fail("unsupported_known_events_compact_schema_version")
    compact_v6["schema_version"] = KNOWN_EVENTS_COMPACT_SCHEMA_VERSION
    return expand_known_events_v6(compact_v6)


def canonical_known_events_v5_sha256(canonical_v5: dict[str, Any]) -> str:
    """Hash the complete canonical V5 object with the frozen JSON algorithm."""

    canonical = _validated_canonical_v5(canonical_v5)
    return hashlib.sha256(_canonical_json_bytes(canonical)).hexdigest()


def build_known_events_v6_compaction_metadata(
    canonical_v5: dict[str, Any],
    compact_v6: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build audit-only metadata; none of it belongs in the model context."""

    canonical = _validated_canonical_v5(canonical_v5)
    compact = encode_known_events_v6(canonical) if compact_v6 is None else deepcopy(compact_v6)
    expanded = expand_known_events_v6(compact)
    if expanded != canonical:
        _fail("known_events_v6_round_trip_mismatch")
    _validate_speech_round_trip(canonical, expanded)

    canonical_text = _canonical_json_text(canonical)
    compact_text = _canonical_json_text(compact)
    canonical_char_count = len(canonical_text)
    compact_char_count = len(compact_text)
    event_refs = [str(event["event_ref"]) for event in canonical["events"]]
    speeches = [
        event["speech"] for event in canonical["events"] if isinstance(event.get("speech"), str)
    ]
    return {
        "canonical_serialized_char_count": canonical_char_count,
        "compact_serialized_char_count": compact_char_count,
        "compaction_saved_chars": canonical_char_count - compact_char_count,
        "compaction_ratio": (
            compact_char_count / canonical_char_count if canonical_char_count else 1.0
        ),
        "verbatim_speech_count": len(speeches),
        "verbatim_speech_chars": sum(len(speech) for speech in speeches),
        "retained_event_refs": event_refs,
        "dropped_event_refs": [],
        "canonical_sha256": canonical_known_events_v5_sha256(canonical),
        "round_trip_verified": True,
    }


def build_known_events_v7_compaction_metadata(
    canonical_v5: dict[str, Any],
    compact_v7: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Audit the lossless encoding of the selector-retained event projection."""

    canonical = _validated_canonical_v5(canonical_v5)
    compact = encode_known_events_v7(canonical) if compact_v7 is None else deepcopy(compact_v7)
    expanded = expand_known_events_v7(compact)
    if expanded != canonical:
        _fail("known_events_v7_round_trip_mismatch")
    _validate_speech_round_trip(canonical, expanded)

    canonical_text = _canonical_json_text(canonical)
    compact_text = _canonical_json_text(compact)
    canonical_char_count = len(canonical_text)
    compact_char_count = len(compact_text)
    event_refs = [str(event["event_ref"]) for event in canonical["events"]]
    speeches = [
        event["speech"] for event in canonical["events"] if isinstance(event.get("speech"), str)
    ]
    return {
        "canonical_serialized_char_count": canonical_char_count,
        "compact_serialized_char_count": compact_char_count,
        "compaction_saved_chars": canonical_char_count - compact_char_count,
        "compaction_ratio": (
            compact_char_count / canonical_char_count if canonical_char_count else 1.0
        ),
        "verbatim_speech_count": len(speeches),
        "verbatim_speech_chars": sum(len(speech) for speech in speeches),
        "retained_event_refs": event_refs,
        "canonical_sha256": canonical_known_events_v5_sha256(canonical),
        "round_trip_verified": True,
        "lossless_scope": "selector_retained_projection",
    }


def _validated_canonical_v5(value: Any) -> dict[str, Any]:
    _validate_json_value(value)
    if not isinstance(value, dict):
        _fail("known_events_v5_shape")
    if set(value) != _CANONICAL_TOP_LEVEL_KEYS:
        _fail("known_events_v5_top_level_keys")
    if value.get("schema_version") != KNOWN_EVENTS_CANONICAL_SCHEMA_VERSION:
        _fail("unsupported_known_events_schema_version")
    events = value.get("events")
    questions = value.get("questions")
    relations = value.get("relations")
    if (
        not isinstance(events, list)
        or not isinstance(questions, list)
        or not isinstance(relations, list)
    ):
        _fail("known_events_v5_shape")

    event_refs: set[str] = set()
    previous_sequence: int | None = None
    for event in events:
        if not isinstance(event, dict):
            _fail("known_events_v5_event_shape")
        event_ref = event.get("event_ref")
        if not isinstance(event_ref, str) or not event_ref:
            _fail("known_events_v5_event_ref")
        if event_ref in event_refs:
            _fail("duplicate_event_ref")
        event_refs.add(event_ref)
        kind = event.get("kind")
        if not isinstance(kind, str) or not kind:
            _fail("known_events_v5_kind")
        if _positive_int(event.get("known_at_seq")) is None:
            _fail("known_events_v5_known_at_seq")
        if "record_seq" in event and _positive_int(event.get("record_seq")) is None:
            _fail("known_events_v5_record_seq")
        visibility = event.get("visibility")
        if visibility not in {"public", "actor_private"}:
            _fail("known_events_v5_visibility")
        if visibility == "actor_private":
            if (
                event.get("owner_scope") != "player"
                or not isinstance(event.get("owner_ref"), str)
                or not event["owner_ref"]
            ):
                _fail("known_events_v5_private_owner")
        elif "owner_scope" in event or "owner_ref" in event:
            _fail("known_events_v5_public_owner")
        if not isinstance(event.get("authority"), str) or not event["authority"]:
            _fail("known_events_v5_authority")
        occurrence = event.get("occurred_in")
        if occurrence is not None:
            _validate_occurrence(occurrence, error_code="known_events_v5_occurrence_shape")
        annotations = event.get("annotations")
        if annotations is not None and (
            not isinstance(annotations, list)
            or any(not isinstance(annotation, dict) for annotation in annotations)
        ):
            _fail("known_events_v5_annotation_shape")
        if "speech" in event and not isinstance(event["speech"], str):
            _fail("known_events_v5_speech_shape")
        sequence = int(event["known_at_seq"])
        if previous_sequence is not None and sequence < previous_sequence:
            _fail("known_events_not_chronological")
        previous_sequence = sequence

    _validate_reference_closure(events, questions, relations, event_refs=event_refs)
    return deepcopy(value)


def _validated_compact_v6_shape(value: Any) -> dict[str, Any]:
    _validate_json_value(value)
    if not isinstance(value, dict) or set(value) != _COMPACT_TOP_LEVEL_KEYS:
        _fail("known_events_v6_shape")
    if value.get("schema_version") != KNOWN_EVENTS_COMPACT_SCHEMA_VERSION:
        _fail("unsupported_known_events_compact_schema_version")
    if value.get("encoding") != KNOWN_EVENTS_COMPACT_ENCODING:
        _fail("unsupported_known_events_compact_encoding")
    defaults = value.get("defaults")
    if not isinstance(defaults, dict) or set(defaults) != _COMPACT_DEFAULT_KEYS:
        _fail("unsupported_known_events_compact_defaults")
    if any(defaults.get(key) != expected for key, expected in _COMPACT_BASE_DEFAULTS.items()):
        _fail("unsupported_known_events_compact_defaults")
    scope_ref_by_kind = defaults.get("scope_ref_by_kind")
    occurred_in_ref_by_kind = defaults.get("occurred_in_ref_by_kind")
    if not isinstance(scope_ref_by_kind, dict) or not isinstance(occurred_in_ref_by_kind, dict):
        _fail("unsupported_known_events_compact_defaults")
    scope_catalog = value.get("scope_catalog")
    occurrence_catalog = value.get("occurrence_catalog")
    events = value.get("events")
    annotations = value.get("annotations")
    questions = value.get("questions")
    relations = value.get("relations")
    if (
        not isinstance(scope_catalog, dict)
        or not isinstance(occurrence_catalog, dict)
        or not isinstance(events, list)
        or not isinstance(annotations, list)
        or not isinstance(questions, list)
        or not isinstance(relations, list)
    ):
        _fail("known_events_v6_shape")
    for scope_ref, scope in scope_catalog.items():
        _validate_catalog_key(scope_ref)
        if not isinstance(scope, dict):
            _fail("compact_scope_shape")
        allowed_keys = {"visibility", "owner_scope", "owner_ref", "authority", "epistemic_status"}
        if not set(scope).issubset(allowed_keys):
            _fail("compact_scope_shape")
        visibility = scope.get("visibility")
        if not isinstance(scope.get("authority"), str) or not scope["authority"]:
            _fail("compact_scope_shape")
        if "epistemic_status" in scope and (
            not isinstance(scope["epistemic_status"], str) or not scope["epistemic_status"]
        ):
            _fail("compact_scope_shape")
        if visibility == "public":
            if "owner_scope" in scope or "owner_ref" in scope:
                _fail("compact_scope_shape")
        elif visibility == "actor_private":
            if (
                scope.get("owner_scope") != "player"
                or not isinstance(scope.get("owner_ref"), str)
                or not scope["owner_ref"]
            ):
                _fail("compact_scope_shape")
        else:
            _fail("compact_scope_shape")
    for occurrence_ref, occurrence in occurrence_catalog.items():
        _validate_catalog_key(occurrence_ref)
        _validate_occurrence(occurrence, error_code="compact_occurrence_shape")
    for defaults_by_kind, catalog, missing_ref_code in (
        (scope_ref_by_kind, scope_catalog, "missing_scope_ref"),
        (occurred_in_ref_by_kind, occurrence_catalog, "missing_occurrence_ref"),
    ):
        for kind, catalog_ref in defaults_by_kind.items():
            if not isinstance(kind, str) or not kind or not isinstance(catalog_ref, str):
                _fail("unsupported_known_events_compact_defaults")
            if catalog_ref not in catalog:
                _fail(missing_ref_code)
    for event in events:
        if not isinstance(event, dict):
            _fail("known_events_v6_event_shape")
        if any(
            key in event
            for key in (
                "visibility",
                "authority",
                "epistemic_status",
                "owner_scope",
                "owner_ref",
            )
        ):
            _fail("compact_scope_field_conflict")
        if "occurred_in" in event:
            _fail("compact_occurrence_field_conflict")
        if "annotations" in event:
            _fail("compact_annotation_field_conflict")
        kind = event.get("kind")
        if not isinstance(kind, str) or not kind:
            _fail("known_events_v6_kind")
    event_kinds = {str(event["kind"]) for event in events}
    if not set(scope_ref_by_kind).issubset(event_kinds) or not set(
        occurred_in_ref_by_kind
    ).issubset(event_kinds):
        _fail("unsupported_known_events_compact_defaults")
    return deepcopy(value)


def _validate_reference_closure(
    events: list[Any],
    questions: list[Any],
    relations: list[Any],
    *,
    event_refs: set[str],
) -> None:
    question_ids: set[str] = set()
    for question in questions:
        if not isinstance(question, dict):
            _fail("known_events_question_shape")
        question_id = question.get("question_id")
        if not isinstance(question_id, str) or not question_id or question_id in question_ids:
            _fail("known_events_question_id")
        question_ids.add(question_id)
        source_event_ref = question.get("source_event_ref")
        if not isinstance(source_event_ref, str) or source_event_ref not in event_refs:
            _fail("missing_question_source_ref")
        prior_refs = question.get("prior_relevant_event_refs")
        if prior_refs is not None and (
            not isinstance(prior_refs, list)
            or any(not isinstance(ref, str) or ref not in event_refs for ref in prior_refs)
        ):
            _fail("missing_question_prior_ref")

    for relation in relations:
        if not isinstance(relation, dict):
            _fail("known_events_relation_shape")
        from_event_ref = relation.get("from_event_ref")
        to_question_id = relation.get("to_question_id")
        if not isinstance(from_event_ref, str) or from_event_ref not in event_refs:
            _fail("missing_relation_event_ref")
        if not isinstance(to_question_id, str) or to_question_id not in question_ids:
            _fail("missing_relation_question_ref")


def _event_scope(event: dict[str, Any]) -> dict[str, Any]:
    scope = {
        "visibility": event["visibility"],
        "authority": event["authority"],
    }
    if "epistemic_status" in event:
        scope["epistemic_status"] = event["epistemic_status"]
    if event["visibility"] == "actor_private":
        scope["owner_scope"] = event["owner_scope"]
        scope["owner_ref"] = event["owner_ref"]
    return scope


def _modal_ref_by_kind(items: Any) -> dict[str, str]:
    counts_by_kind: dict[str, Counter[str]] = defaultdict(Counter)
    for kind, catalog_ref in items:
        counts_by_kind[kind][catalog_ref] += 1
    return {
        kind: min(counts, key=lambda ref: (-counts[ref], ref))
        for kind, counts in counts_by_kind.items()
    }


def _scope_catalog_base_key(scope: dict[str, Any]) -> str:
    parts = [
        _catalog_component(scope["visibility"]),
        _catalog_component(scope["authority"]),
    ]
    if "epistemic_status" in scope:
        parts.extend(("epistemic", _catalog_component(scope["epistemic_status"])))
    return "_".join(parts)


def _scope_catalog_key(scope: dict[str, Any], *, base_key_count: int) -> str:
    base_key = _scope_catalog_base_key(scope)
    if base_key_count == 1:
        return base_key
    if scope.get("visibility") != "actor_private":
        # The base includes every public scope dimension. A collision here can
        # only be caused by lossy catalog-key normalization.
        return base_key
    return "_".join(
        (
            base_key,
            _catalog_component(scope["owner_scope"]),
            _catalog_component(scope["owner_ref"]),
        )
    )


def _occurrence_catalog_key(occurrence: dict[str, Any]) -> str:
    period = occurrence.get("period")
    round_no = occurrence.get("round_no")
    if not isinstance(period, str) or not period or _positive_int(round_no) is None:
        _fail("known_events_v5_occurrence_shape")
    return f"{_catalog_component(period)}_{int(round_no)}"


def _catalog_component(value: Any) -> str:
    if not isinstance(value, str) or not value:
        _fail("compact_catalog_key_unreadable")
    component = re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")
    if not component:
        _fail("compact_catalog_key_unreadable")
    return component


def _insert_catalog_entry(
    catalog: dict[str, dict[str, Any]],
    key: str,
    value: dict[str, Any],
) -> None:
    _validate_catalog_key(key)
    existing = catalog.get(key)
    if existing is not None and existing != value:
        _fail("compact_catalog_key_collision")
    catalog[key] = deepcopy(value)


def _validate_catalog_key(key: Any) -> None:
    if not isinstance(key, str) or _READABLE_CATALOG_KEY.fullmatch(key) is None:
        _fail("compact_catalog_key_unreadable")


def _validate_occurrence(value: Any, *, error_code: str) -> None:
    if not isinstance(value, dict):
        _fail(error_code)
    period = value.get("period")
    round_no = value.get("round_no")
    if not isinstance(period, str) or not period or _positive_int(round_no) is None:
        _fail(error_code)


def _canonical_record_seq(event: dict[str, Any]) -> int | None:
    return int(event["record_seq"]) if "record_seq" in event else None


def _compact_record_seq(event: dict[str, Any]) -> int | None:
    known_at_seq = _positive_int(event.get("known_at_seq"))
    if known_at_seq is None:
        _fail("known_events_v6_known_at_seq")
    if "record_seq" not in event:
        return known_at_seq
    record_seq = event.get("record_seq")
    if record_seq is None:
        return None
    parsed = _positive_int(record_seq)
    if parsed is None:
        _fail("known_events_v6_record_seq")
    return parsed


def _positive_int(value: Any) -> int | None:
    if isinstance(value, int) and not isinstance(value, bool) and value > 0:
        return value
    return None


def _validate_speech_round_trip(
    canonical: dict[str, Any],
    expanded: dict[str, Any],
) -> None:
    canonical_speeches = [
        event["speech"].encode("utf-8")
        for event in canonical["events"]
        if isinstance(event.get("speech"), str)
    ]
    expanded_speeches = [
        event["speech"].encode("utf-8")
        for event in expanded["events"]
        if isinstance(event.get("speech"), str)
    ]
    if canonical_speeches != expanded_speeches:
        _fail("known_events_v6_speech_mismatch")


def _validate_json_value(value: Any) -> None:
    if value is None or isinstance(value, (str, bool, int)):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            _fail("canonical_json_non_finite_number")
        return
    if isinstance(value, list):
        for item in value:
            _validate_json_value(item)
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                _fail("canonical_json_non_string_key")
            _validate_json_value(item)
        return
    _fail("canonical_json_unsupported_type")


def _canonical_json_text(value: Any) -> str:
    _validate_json_value(value)
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    except (TypeError, ValueError, UnicodeEncodeError) as exc:
        raise ModelContextCompactionError("canonical_json_invalid") from exc


def _canonical_json_bytes(value: Any) -> bytes:
    try:
        return _canonical_json_text(value).encode("utf-8")
    except UnicodeEncodeError as exc:
        raise ModelContextCompactionError("canonical_json_invalid") from exc


def _fail(code: str) -> None:
    raise ModelContextCompactionError(code)
