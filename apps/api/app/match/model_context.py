from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field as dataclass_field
import json
from typing import Any

from app.match.ability_runtime import normalize_role_key, normalize_team_key
from app.match.discourse_ledger import build_public_discourse_ledger
from app.match.discourse_model_view import build_discourse_model_view
from app.match.model_context_compaction import (
    KNOWN_EVENTS_CANONICAL_SCHEMA_VERSION,
    ModelContextCompactionError,
    build_known_events_v7_compaction_metadata,
    encode_known_events_v7,
    expand_known_events_v7,
)
from app.match.model_context_contract import (
    DISCOURSE_LEDGER_SCHEMA_VERSION,
    KNOWN_EVENTS_SCHEMA_VERSION,
    MODEL_CONTEXT_SCHEMA_VERSION,
    MODEL_VIEW_SELECTOR_VERSION,
    PROMPT_TEMPLATE_VERSION,
    PUBLIC_TIMELINE_SCHEMA_VERSION,
    is_supported_model_context_contract,
)
from app.match.model_context_selector import select_known_events_v13
from app.match.win_conditions import (
    build_public_win_condition_contract,
)


_PERSONA_TEXT_LIMIT = 600

_DIRECT_ACTION_ABILITY_IDS = {
    "guard_protect": "guard.protect",
    "seer_investigate": "seer.investigate",
    "witch_heal": "witch.heal",
    "witch_poison": "witch.poison",
    "hunter_death_shot": "hunter.death_shot",
}


@dataclass(frozen=True)
class ModelPlayerReference:
    player_id: str
    seat: int
    display_name: str

    @property
    def ref(self) -> str:
        return f"seat_{self.seat}"

    @property
    def label(self) -> str:
        return f"{self.seat}号"


@dataclass(frozen=True)
class ProjectedModelContext:
    context: dict[str, Any]
    projection_metadata: dict[str, Any]
    observation_context: dict[str, Any] = dataclass_field(default_factory=dict)


class ModelContextProjectionInvariantError(ValueError):
    def __init__(self, invariant_code: str) -> None:
        super().__init__("model_context_projection_invariant_failed")
        self.invariant_code = invariant_code


def project_model_action_context(
    context: dict[str, Any],
    *,
    players: tuple[ModelPlayerReference, ...],
    model_context_contract: dict[str, Any] | None = None,
    action_record_seq: int | None = None,
    projection_at_seq: int | None = None,
) -> dict[str, Any]:
    return project_model_action_context_with_metadata(
        context,
        players=players,
        model_context_contract=model_context_contract,
        action_record_seq=action_record_seq,
        projection_at_seq=projection_at_seq,
    ).context


def project_model_action_context_with_metadata(
    context: dict[str, Any],
    *,
    players: tuple[ModelPlayerReference, ...],
    model_context_contract: dict[str, Any] | None = None,
    action_record_seq: int | None = None,
    projection_at_seq: int | None = None,
) -> ProjectedModelContext:
    resolved_projection_at_seq = _resolved_projection_at_seq(
        action_record_seq=action_record_seq,
        projection_at_seq=projection_at_seq,
    )
    contract = model_context_contract
    if not is_supported_model_context_contract(contract):
        raise ValueError("unsupported_model_context_contract")
    return _project_v13_model_action_context_with_metadata(
        context,
        players=players,
        projection_at_seq=resolved_projection_at_seq,
        prompt_template_version=int(contract["prompt_template_version"]),
        known_events_schema_version=int(contract["known_events_schema_version"]),
        ledger_schema_version=int(contract["ledger_schema_version"]),
        model_view_schema_version=int(contract["model_view_schema_version"]),
    )


def _project_v13_model_action_context_with_metadata(
    context: dict[str, Any],
    *,
    players: tuple[ModelPlayerReference, ...],
    projection_at_seq: int | None,
    prompt_template_version: int,
    known_events_schema_version: int,
    ledger_schema_version: int,
    model_view_schema_version: int,
) -> ProjectedModelContext:
    if not players:
        raise ModelContextProjectionInvariantError("players_required")

    source = _project_value(context, players=players)
    private_facts = source.pop("private_authoritative_facts", None)
    private_facts = private_facts if isinstance(private_facts, list) else []
    public_history = context.get("public_history")
    if isinstance(public_history, (list, tuple)):
        statements, _vote_snapshots, public_events = _project_public_history(
            public_history,
            players=players,
            include_technical_speech_skips=True,
        )
    else:
        statements = []
        public_events = []

    identity = source.get("self_identity")
    identity = identity if isinstance(identity, dict) else {}
    actor_ref = identity.get("player_id")
    actor_ref = actor_ref if isinstance(actor_ref, str) else None
    hard_rules = _model_hard_rules(
        source.get("public_rule_contract"),
        include_win_condition_contract=True,
    )
    task_at_seq = _action_at_seq(
        projection_at_seq,
        source=source,
        public_events=public_events,
        private_facts=private_facts,
    )
    visible_statements = _statements_visible_at_seq(statements, task_at_seq=task_at_seq)
    current_round_no = _current_round_no(source, statements=visible_statements)
    task = _model_task_v11(source, at_seq=task_at_seq, actor_ref=actor_ref)
    task["round_no"] = current_round_no
    candidates = source.get("candidates")
    candidates = candidates if isinstance(candidates, list) else []
    candidate_refs = [
        str(candidate["player_id"])
        for candidate in candidates
        if isinstance(candidate, dict) and isinstance(candidate.get("player_id"), str)
    ]
    ledger = build_public_discourse_ledger(
        visible_statements,
        current_round_no=current_round_no,
        actor_ref=actor_ref,
        ledger_schema_version=ledger_schema_version,
        role_keys={
            item.get("role_key")
            for item in hard_rules.get("roles", [])
            if isinstance(item, dict) and isinstance(item.get("role_key"), str)
        },
        team_keys={
            item.get("team")
            for item in hard_rules.get("roles", [])
            if isinstance(item, dict) and isinstance(item.get("team"), str)
        },
        player_refs={player.ref for player in players},
        current_night_no=_positive_int(source.get("night_no")) or current_round_no,
    )
    model_view, model_view_metadata = build_discourse_model_view(
        ledger,
        actor_ref=actor_ref,
        task=task,
        candidate_refs=candidate_refs,
        latest_vote_result_ref=None,
        model_view_schema_version=model_view_schema_version,
    )

    teammate_refs = _current_living_werewolf_teammates(
        source,
        private_facts=private_facts,
        self_ref=actor_ref,
    )
    teammate_facts_removed = [
        fact
        for fact in private_facts
        if not isinstance(fact, dict)
        or fact.get("fact_type") not in {"werewolf_teammates", "living_werewolf_teammates"}
    ]
    future_filtered_events: list[dict[str, Any]] = []
    visible_events = _known_events(
        public_events=public_events,
        statements=visible_statements,
        private_facts=teammate_facts_removed,
        task_at_seq=task_at_seq,
        current_round_no=current_round_no,
        schema_version=KNOWN_EVENTS_CANONICAL_SCHEMA_VERSION,
        future_events_out=future_filtered_events,
    )
    is_werewolf = identity.get("role_key") == "werewolf"
    configured_werewolf_count = hard_rules.get("werewolf_count")
    if is_werewolf and isinstance(configured_werewolf_count, int) and configured_werewolf_count > 1:
        visible_events.append(
            _canonical_living_werewolf_teammates_event(
                teammate_refs=teammate_refs,
                task_at_seq=task_at_seq,
                source=source,
                current_round_no=current_round_no,
                owner_ref=actor_ref,
            )
        )
        visible_events.sort(key=_known_event_sort_key)

    _attach_v11_first_party_claim_annotations(
        visible_events,
        model_view=model_view,
    )
    latest_actor_memory_cutoffs = [
        cutoff
        for fact in teammate_facts_removed
        for payload in (fact.get("payload"),)
        if isinstance(fact, dict)
        and fact.get("fact_type") == "private_round_memory"
        and isinstance(payload, dict)
        for cutoff in (_positive_int(payload.get("source_cutoff_record_seq")),)
        if cutoff is not None
    ]
    rolling_memory_cutoff_seq = max(latest_actor_memory_cutoffs, default=None)
    if source.get("unarchived_memory_source_cutoff_record_seq") == 0:
        # Runtime explicitly marks a missing first snapshot. This is distinct
        # from historical/diagnostic payloads that merely predate actor memory.
        rolling_memory_cutoff_seq = 0
    if source.get("action_type") == "private_round_memory":
        # The first snapshot has no predecessor. A zero cutoff intentionally
        # makes every visible durable event part of that initial memory input.
        rolling_memory_cutoff_seq = (
            _positive_int(source.get("previous_memory_source_cutoff_record_seq")) or 0
        )
    selection = select_known_events_v13(
        visible_events,
        actor_ref=actor_ref,
        current_round_no=current_round_no,
        candidate_refs=candidate_refs,
        model_view=model_view,
        rolling_memory_cutoff_seq=rolling_memory_cutoff_seq,
        future_filtered=future_filtered_events,
    )
    selected_events = selection.events
    questions, relations = _v11_discourse_projection(
        model_view,
        selected_events=selected_events,
        current_round_no=current_round_no,
        include_reply_opportunity=_is_scheduled_speech_action(task),
    )
    canonical_known_events = {
        "schema_version": KNOWN_EVENTS_CANONICAL_SCHEMA_VERSION,
        "events": selected_events,
        "questions": questions,
        "relations": relations,
    }
    state = _model_public_state(source)
    state.update(
        _v11_temporal_state(
            source,
            selected_events=selected_events,
            current_round_no=current_round_no,
        )
    )
    if task_at_seq is not None:
        state["as_of_seq"] = task_at_seq
    living_werewolf_count = (
        1 + len(teammate_refs)
        if is_werewolf and isinstance(configured_werewolf_count, int)
        else None
    )
    projected_context = {
        "model_context_schema_version": MODEL_CONTEXT_SCHEMA_VERSION,
        "prompt_template_version": prompt_template_version,
        "task": task,
        "self": _model_self_v11(source, hard_rules=hard_rules),
        "rules": _model_action_rules_v11(
            source,
            hard_rules=hard_rules,
            living_werewolf_count=living_werewolf_count,
        ),
        "state": state,
        "known_events": canonical_known_events,
        "persona": _compact_persona(
            source.get("actor_profile"),
            include_delivery=_response_allows_speech(source.get("output_contract")),
        ),
        "candidates": candidates,
        "response": _model_response_v11(source.get("output_contract")),
        "player_reference_format": "seat_N",
    }
    validate_projected_model_context(
        projected_context,
        internal_contract=(
            source.get("output_contract") if isinstance(source.get("output_contract"), dict) else {}
        ),
        _canonical_known_events=canonical_known_events,
    )
    try:
        compact_known_events = encode_known_events_v7(canonical_known_events)
    except ModelContextCompactionError as exc:
        raise ModelContextProjectionInvariantError(exc.code) from exc
    if compact_known_events.get("schema_version") != known_events_schema_version:
        raise ModelContextProjectionInvariantError("known_events_schema_version")
    projected_context["known_events"] = compact_known_events
    validate_projected_model_context(
        projected_context,
        internal_contract=(
            source.get("output_contract") if isinstance(source.get("output_contract"), dict) else {}
        ),
    )
    projection_metadata = _v13_projection_metadata(
        ledger=ledger,
        model_view_metadata=model_view_metadata,
        projected_context=projected_context,
        selected_events=selected_events,
        selector_audit=selection.audit,
        questions=questions,
        relations=relations,
        current_round_no=current_round_no,
        model_view_schema_version=model_view_schema_version,
        canonical_known_events=canonical_known_events,
        compact_known_events=compact_known_events,
    )

    observation_task = _model_task(source)
    observation_speech_progress = _model_speech_progress(
        observation_task,
        actor_ref=actor_ref,
    )
    if observation_speech_progress is not None:
        observation_task["speech_progress"] = observation_speech_progress
    observation_history, _observation_metadata = build_discourse_model_view(
        ledger,
        actor_ref=actor_ref,
        task=observation_task,
        candidate_refs=candidate_refs,
        latest_vote_result_ref=None,
        model_view_schema_version=model_view_schema_version,
    )
    return ProjectedModelContext(
        context=projected_context,
        projection_metadata=projection_metadata,
        observation_context={
            "task": observation_task,
            "hard_rules": hard_rules,
            "public_timeline": _model_public_timeline(public_events),
            "history": observation_history,
            "known_events": canonical_known_events,
        },
    )


def validate_projected_model_context(
    context: dict[str, Any],
    internal_contract: dict[str, Any],
    *,
    _canonical_known_events: dict[str, Any] | None = None,
) -> None:
    def fail(code: str) -> None:
        raise ModelContextProjectionInvariantError(code)

    if context.get("model_context_schema_version") != MODEL_CONTEXT_SCHEMA_VERSION:
        fail("model_context_schema_version")
    if context.get("prompt_template_version") != PROMPT_TEMPLATE_VERSION:
        fail("prompt_template_version")
    if _canonical_known_events is not None:
        known_events = _canonical_known_events
        if known_events.get("schema_version") != KNOWN_EVENTS_CANONICAL_SCHEMA_VERSION:
            fail("known_events_schema_version")
    else:
        compact_known_events = context.get("known_events")
        if (
            not isinstance(compact_known_events, dict)
            or compact_known_events.get("schema_version") != KNOWN_EVENTS_SCHEMA_VERSION
        ):
            fail("known_events_schema_version")
        try:
            known_events = expand_known_events_v7(compact_known_events)
        except ModelContextCompactionError as exc:
            fail(exc.code)

    task = context.get("task")
    state = context.get("state")
    if not isinstance(task, dict) or not isinstance(state, dict):
        fail("task_state_shape")
    task_at_seq = _positive_int(task.get("at_seq"))
    if task_at_seq is None or task_at_seq != _positive_int(state.get("as_of_seq")):
        fail("task_state_clock")
    task_round_no = _positive_int(task.get("round_no"))
    if task_round_no is None or task_round_no != _positive_int(state.get("current_round_no")):
        fail("task_state_round")

    response = context.get("response")
    response = response if isinstance(response, dict) else {}
    internal_kind = internal_contract.get("kind")
    if internal_kind not in {"speech", "target", "boolean"}:
        fail("internal_response_kind")
    if response.get("kind") != internal_kind:
        fail("response_kind")
    response_speech = response.get("speech")
    internal_speech = internal_contract.get("speech")
    if not isinstance(response_speech, dict) or not isinstance(internal_speech, dict):
        fail("response_speech_shape")
    if response_speech.get("mode") != internal_speech.get("mode"):
        fail("response_speech_mode")

    candidates = context.get("candidates")
    candidates = candidates if isinstance(candidates, list) else []
    candidate_ids = [
        item.get("player_id")
        for item in candidates
        if isinstance(item, dict) and isinstance(item.get("player_id"), str)
    ]
    if len(candidate_ids) != len(candidates) or len(candidate_ids) != len(set(candidate_ids)):
        fail("candidate_shape")
    if internal_kind == "target":
        internal_target_policy = internal_contract.get("target_policy")
        internal_target_policy = (
            internal_target_policy if isinstance(internal_target_policy, dict) else {}
        )
        allowed_target_ids = internal_target_policy.get("allowed_target_ids")
        if not isinstance(allowed_target_ids, list) or any(
            not isinstance(item, str) for item in allowed_target_ids
        ):
            fail("internal_allowed_targets")
        if set(candidate_ids) != set(allowed_target_ids):
            fail("candidate_allowed_target_mismatch")
        response_target_policy = response.get("target_policy")
        if (
            not isinstance(response_target_policy, dict)
            or response_target_policy.get("mode") != internal_target_policy.get("mode")
            or response_target_policy.get("candidate_source") != "candidates"
        ):
            fail("response_target_policy")
    elif "target_policy" in response:
        fail("response_target_policy_unexpected")
    if internal_kind == "boolean" and response.get("field") != internal_contract.get("field"):
        fail("response_boolean_field")

    self_context = context.get("self")
    self_context = self_context if isinstance(self_context, dict) else {}
    identity = self_context.get("identity")
    identity = identity if isinstance(identity, dict) else {}
    actor_ref = identity.get("player_id")
    office = self_context.get("public_office_capabilities")
    office = office if isinstance(office, dict) else {}
    sheriff_ref = state.get("sheriff_player_id")
    sheriff_badge_state = state.get("sheriff_badge_state")
    expected_is_sheriff = (
        isinstance(actor_ref, str) and actor_ref == sheriff_ref and sheriff_badge_state == "held"
    )
    if office.get("is_current_sheriff") is not expected_is_sheriff:
        fail("sheriff_holder_mismatch")
    if sheriff_ref is not None and sheriff_badge_state != "held":
        fail("sheriff_badge_state_mismatch")
    if "sheriff_badge_state" in office:
        fail("duplicate_sheriff_badge_state")

    events = known_events.get("events")
    questions = known_events.get("questions")
    relations = known_events.get("relations")
    if (
        not isinstance(events, list)
        or not isinstance(questions, list)
        or not isinstance(relations, list)
    ):
        fail("known_events_shape")
    event_by_ref: dict[str, dict[str, Any]] = {}
    for event in events:
        if not isinstance(event, dict):
            fail("event_shape")
        event_ref = event.get("event_ref")
        if not isinstance(event_ref, str) or not event_ref or event_ref in event_by_ref:
            fail("event_ref")
        if event.get("visibility") not in {"public", "actor_private"}:
            fail("event_visibility")
        known_at_seq = _positive_int(event.get("known_at_seq"))
        if known_at_seq is None:
            fail("event_sequence_missing")
        if known_at_seq > task_at_seq:
            fail("event_after_task")
        record_seq = event.get("record_seq")
        if record_seq is not None and (
            _positive_int(record_seq) is None or int(record_seq) > task_at_seq
        ):
            fail("event_after_task")
        if event.get("visibility") == "actor_private":
            if (
                event.get("owner_scope") != "player"
                or not isinstance(actor_ref, str)
                or event.get("owner_ref") != actor_ref
            ):
                fail("actor_private_owner")
        elif "owner_scope" in event or "owner_ref" in event:
            fail("public_event_owner")
        if "source_event_id" in event:
            fail("duplicate_source_event_id")
        if "timeline_index" in event:
            fail("timeline_index")
        event_by_ref[event_ref] = event

    rules = context.get("rules")
    rules = rules if isinstance(rules, dict) else {}
    role_summary = rules.get("role_summary")
    role_summary = role_summary if isinstance(role_summary, list) else []
    role_keys = {
        item.get("role_key")
        for item in role_summary
        if isinstance(item, dict) and isinstance(item.get("role_key"), str)
    }
    team_keys = {
        item.get("team")
        for item in role_summary
        if isinstance(item, dict) and isinstance(item.get("team"), str)
    }
    player_refs = {
        ref
        for key in ("alive_player_ids", "eliminated_player_ids")
        for raw_refs in (state.get(key),)
        if isinstance(raw_refs, list)
        for ref in raw_refs
        if isinstance(ref, str)
    }
    if isinstance(actor_ref, str):
        player_refs.add(actor_ref)
    for event in events:
        raw_annotations = event.get("annotations")
        if raw_annotations is None:
            continue
        if not isinstance(raw_annotations, list):
            fail("claim_shape")
        for claim in raw_annotations:
            _validate_v11_claim(
                claim,
                role_keys=role_keys,
                team_keys=team_keys,
                player_refs=player_refs,
                fail=fail,
            )

    question_by_id: dict[str, dict[str, Any]] = {}
    for question in questions:
        if not isinstance(question, dict):
            fail("question_shape")
        question_id = question.get("question_id")
        source_ref = question.get("source_event_ref")
        source_event = event_by_ref.get(source_ref) if isinstance(source_ref, str) else None
        if (
            not isinstance(question_id, str)
            or not question_id
            or question_id in question_by_id
            or source_event is None
        ):
            fail("question_reference")
        if question.get("source_authority") != source_event.get("authority"):
            fail("question_authority")
        asked_at_seq = _positive_int(question.get("asked_at_seq"))
        if asked_at_seq is None or asked_at_seq > task_at_seq:
            fail("question_after_task")
        if not _is_complete_derivation(question.get("derivation")):
            fail("question_derivation")
        if question.get("response_status") not in {"none_detected", "response_detected"}:
            fail("question_response_status")
        address_resolution = question.get("address_resolution")
        addressed_to = question.get("addressed_to")
        if address_resolution == "resolved" and not isinstance(addressed_to, str):
            fail("question_address")
        if address_resolution == "unresolved" and addressed_to is not None:
            fail("question_address")
        if address_resolution not in {"resolved", "unresolved"}:
            fail("question_address")
        requested_fields = question.get("requested_fields")
        if isinstance(requested_fields, list) and any(
            field not in {"target_ref", "claimed_result"} for field in requested_fields
        ):
            fail("question_requested_fields")
        question_by_id[question_id] = question

    response_relation_counts = {question_id: 0 for question_id in question_by_id}
    for relation in relations:
        if not isinstance(relation, dict) or relation.get("type") != "response_to_question":
            fail("relation_shape")
        from_ref = relation.get("from_event_ref")
        question_id = relation.get("to_question_id")
        response_event = event_by_ref.get(from_ref) if isinstance(from_ref, str) else None
        question = question_by_id.get(question_id) if isinstance(question_id, str) else None
        if response_event is None or question is None:
            fail("relation_reference")
        if relation.get("temporal_order_valid") is not True:
            fail("relation_temporal_flag")
        if not _is_complete_derivation(relation.get("derivation")):
            fail("relation_derivation")
        response_seq = _positive_int(response_event.get("known_at_seq")) or _positive_int(
            response_event.get("record_seq")
        )
        if response_seq is None or response_seq <= int(question["asked_at_seq"]):
            fail("relation_temporal_order")
        addressed_to = question.get("addressed_to")
        if isinstance(addressed_to, str) and response_event.get("speaker_ref") != addressed_to:
            fail("relation_responder")
        response_relation_counts[str(question_id)] += 1
    for question_id, question in question_by_id.items():
        detected = response_relation_counts[question_id] > 0
        if detected != (question.get("response_status") == "response_detected"):
            fail("question_relation_status")


def _validate_v11_claim(
    claim: Any,
    *,
    role_keys: set[Any],
    team_keys: set[Any],
    player_refs: set[str],
    fail: Any,
) -> None:
    if not isinstance(claim, dict) or not _is_complete_derivation(claim.get("derivation")):
        fail("claim_derivation")
    if claim.get("authority") != "player_claim_unverified":
        fail("claim_authority")
    claim_type = claim.get("claim_type")
    if claim_type == "role_claim":
        if claim.get("claimed_role") not in role_keys:
            fail("claim_role")
    elif claim_type == "team_claim":
        if claim.get("claimed_team") not in team_keys:
            fail("claim_team")
    elif claim_type == "investigation_claim":
        action_in = claim.get("claimed_action_in")
        if (
            not isinstance(action_in, dict)
            or action_in.get("period") != "night"
            or _positive_int(action_in.get("round_no")) is None
            or claim.get("target_ref") not in player_refs
            or claim.get("claimed_result") not in {"werewolves", "villagers"}
        ):
            fail("claim_investigation")
    elif claim_type == "future_investigation_plan":
        if claim.get("target_ref") not in player_refs or claim.get("specificity") not in {
            "specific_target",
            "direction_only",
        }:
            fail("claim_future_investigation")
    else:
        fail("claim_type")


def _model_task_v11(
    source: dict[str, Any],
    *,
    at_seq: int | None,
    actor_ref: str | None,
) -> dict[str, Any]:
    base = _model_task(source)
    task: dict[str, Any] = {
        "type": base.pop("action_type", None),
        "goal": base.pop("objective", None),
        "at_seq": at_seq,
        **base,
    }
    speech_progress = _model_speech_progress(task, actor_ref=actor_ref)
    if speech_progress is not None:
        speech_progress.pop("instruction", None)
        task["speech_progress"] = speech_progress
    extension = source.get("v11_action_extension")
    extension = extension if isinstance(extension, dict) else {}
    mechanical_effect = extension.get("mechanical_effect")
    if isinstance(mechanical_effect, dict):
        task["mechanical_effect"] = _without_explanations(mechanical_effect)
    return {key: value for key, value in task.items() if value is not None}


def _model_self_v11(
    source: dict[str, Any],
    *,
    hard_rules: dict[str, Any],
) -> dict[str, Any]:
    projected = _model_self(source, private_facts=[], hard_rules=hard_rules)
    projected.pop("private_judge_facts", None)
    office = projected.get("public_office_capabilities")
    if isinstance(office, dict):
        office.pop("sheriff_badge_state", None)
    restrictions = projected.get("state_restrictions")
    if isinstance(restrictions, dict):
        restrictions.pop("sheriff_badge_state", None)
    identity = source.get("self_identity")
    identity = identity if isinstance(identity, dict) else {}
    if identity.get("role_key") == "werewolf":
        projected["werewolf_coordination"] = (
            {"mode": "solo"} if hard_rules.get("werewolf_count") == 1 else {"mode": "team"}
        )
    compacted = _drop_empty_collections(projected)
    return compacted if isinstance(compacted, dict) else {}


def _model_action_rules(
    source: dict[str, Any],
    *,
    hard_rules: dict[str, Any],
) -> dict[str, Any]:
    action_type = str(source.get("action_type") or "")
    ability_id = source.get("ability_id")
    ability_id = ability_id if isinstance(ability_id, str) else None
    if ability_id is None:
        ability_id = _DIRECT_ACTION_ABILITY_IDS.get(action_type)
    all_ability_rules = hard_rules.get("ability_rules")
    all_ability_rules = all_ability_rules if isinstance(all_ability_rules, dict) else {}
    result: dict[str, Any] = {
        "rule_id": hard_rules.get("rule_id"),
        "rule_version": hard_rules.get("rule_version"),
        "player_count": hard_rules.get("player_count"),
        "role_summary": hard_rules.get("roles"),
        "werewolf_count": hard_rules.get("werewolf_count"),
        "win_condition": hard_rules.get("win_condition"),
        "win_condition_contract": hard_rules.get("win_condition_contract"),
        "reveal_policy": hard_rules.get("reveal_policy"),
        "role_reveal_rule": hard_rules.get("role_reveal_rule"),
        "ability_lifecycle": hard_rules.get("ability_lifecycle"),
        "sheriff": hard_rules.get("sheriff"),
    }
    ability_rule = all_ability_rules.get(ability_id) if ability_id is not None else None
    if ability_rule is None and ability_id is not None:
        ability_rule = all_ability_rules.get(ability_id.replace(".", "_"))
    if ability_id is not None and isinstance(ability_rule, dict):
        result["current_ability"] = {
            "ability_id": ability_id,
            **dict(ability_rule),
        }
    if action_type == "werewolf_self_explosion":
        result["werewolf_self_explosion_enabled"] = hard_rules.get(
            "werewolf_self_explosion_enabled"
        )
    return {
        key: value
        for key, value in result.items()
        if value is not None and value != {} and value != []
    }


def _model_action_rules_v11(
    source: dict[str, Any],
    *,
    hard_rules: dict[str, Any],
    living_werewolf_count: int | None,
) -> dict[str, Any]:
    result = _model_action_rules(source, hard_rules=hard_rules)
    current_ability = result.get("current_ability")
    if (
        not isinstance(current_ability, dict)
        or current_ability.get("ability_id") != "werewolf.attack"
    ):
        return result

    current_ability = dict(current_ability)
    raw_team_resolution = current_ability.get("team_resolution")
    raw_team_resolution = raw_team_resolution if isinstance(raw_team_resolution, dict) else {}
    allow_no_attack = (
        raw_team_resolution.get("allow_no_attack") is True
        or current_ability.get("each_actor_must_choose_target") is False
    )
    allow_wolf_target = (
        raw_team_resolution.get("allow_wolf_target") is True
        or current_ability.get("can_target_self") is True
        or current_ability.get("can_target_werewolf_teammates") is True
    )
    resolution = raw_team_resolution.get("resolution")
    if living_werewolf_count == 1:
        team_resolution = {
            "strategy": "single_actor_direct",
            "on_tie": "not_applicable",
        }
    elif resolution == "unanimous_no_attack":
        team_resolution = {
            "strategy": "unanimity_required",
            "on_disagreement": "no_attack",
        }
    elif resolution == "plurality_rotating_tiebreak":
        team_resolution = {
            "strategy": "plurality",
            "on_unique_highest": "unique_highest",
            "on_tie": "explicit_rotating_werewolf_decision",
        }
    elif resolution == "plurality_seeded_random":
        team_resolution = {
            "strategy": "plurality",
            "on_unique_highest": "unique_highest",
            "on_tie": "deterministic_seeded_choice",
        }
    else:
        team_resolution = dict(raw_team_resolution)

    current_ability["team_resolution"] = team_resolution
    current_ability["individual_ballot"] = {
        "target_mode": "optional" if allow_no_attack else "required",
        "allow_no_attack": allow_no_attack,
        "allow_wolf_target": allow_wolf_target,
    }
    result["current_ability"] = current_ability
    return result


def _resolved_projection_at_seq(
    *,
    action_record_seq: int | None,
    projection_at_seq: int | None,
) -> int | None:
    if projection_at_seq is None:
        return action_record_seq
    if (
        not isinstance(projection_at_seq, int)
        or isinstance(projection_at_seq, bool)
        or projection_at_seq <= 0
    ):
        raise ValueError("projection_at_seq must be a positive integer")
    if (
        not isinstance(action_record_seq, int)
        or isinstance(action_record_seq, bool)
        or action_record_seq <= 0
    ):
        raise ValueError("projection_at_seq requires a positive action_record_seq")
    if projection_at_seq > action_record_seq:
        raise ValueError("projection_at_seq cannot be later than action_record_seq")
    return projection_at_seq


def _action_at_seq(
    explicit: int | None,
    *,
    source: dict[str, Any],
    public_events: list[dict[str, Any]],
    private_facts: list[Any],
) -> int | None:
    for candidate in (explicit, source.get("action_record_seq")):
        if isinstance(candidate, int) and not isinstance(candidate, bool) and candidate > 0:
            return candidate
    known_sequences = [
        value
        for item in [*public_events, *private_facts]
        if isinstance(item, dict)
        for value in (item.get("known_at_seq"), item.get("record_seq"))
        if isinstance(value, int) and not isinstance(value, bool) and value > 0
    ]
    return max(known_sequences, default=0) + 1


def _known_events(
    *,
    public_events: list[dict[str, Any]],
    statements: list[dict[str, Any]],
    private_facts: list[Any],
    task_at_seq: int | None,
    current_round_no: int,
    schema_version: int,
    future_events_out: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    speech_by_ref = {
        str(item.get("source_event_id")): item.get("speech")
        for item in statements
        if isinstance(item.get("source_event_id"), str)
    }
    events: list[dict[str, Any]] = []
    for index, source_event in enumerate(public_events, start=1):
        record_seq = _positive_int(source_event.get("record_seq"))
        if task_at_seq is not None and record_seq is not None and record_seq > task_at_seq:
            if future_events_out is not None:
                future_events_out.append(
                    {
                        "event_ref": str(
                            source_event.get("source_event_id") or f"public_event_{index}"
                        ),
                        "kind": str(source_event.get("kind") or "unknown"),
                    }
                )
            continue
        item = dict(source_event)
        statement_ref = item.pop("statement_ref", None)
        if isinstance(statement_ref, str):
            item["speech"] = speech_by_ref.get(statement_ref)
        item.update(
            {
                "event_ref": str(item.get("source_event_id") or f"public_event_{index}"),
                "visibility": "public",
                "known_at_seq": record_seq,
            }
        )
        if schema_version != 5:
            raise ValueError("unsupported_known_events_schema_version")
        item.pop("source_event_id", None)
        item.pop("timeline_index", None)
        if record_seq is None:
            item["sequence_status"] = "unknown"
        events.append(_drop_none_values(item))

    for index, fact in enumerate(private_facts, start=1):
        if not isinstance(fact, dict):
            continue
        fact_id = fact.get("knowledge_fact_id")
        known_at_seq = _positive_int(fact.get("known_at_seq"))
        record_seq = _positive_int(fact.get("record_seq"))
        historical = isinstance(fact_id, str) or isinstance(fact.get("source_activation_id"), str)
        if known_at_seq is None and not historical:
            known_at_seq = task_at_seq
        if task_at_seq is not None and known_at_seq is not None and known_at_seq > task_at_seq:
            if future_events_out is not None:
                future_events_out.append(
                    {
                        "event_ref": (
                            fact_id if isinstance(fact_id, str) else f"current_private_fact_{index}"
                        ),
                        "kind": str(fact.get("fact_type") or "private_judge_fact"),
                    }
                )
            continue
        payload = fact.get("payload")
        payload = dict(payload) if isinstance(payload, dict) else payload
        occurred_in = fact.get("occurred_in")
        if not isinstance(occurred_in, dict):
            occurred_in = _private_fact_occurrence(payload, current_round_no=current_round_no)
        item = {
            "event_ref": (fact_id if isinstance(fact_id, str) else f"current_private_fact_{index}"),
            "kind": fact.get("fact_type") or "private_judge_fact",
            "authority": fact.get("authority") or "judge_fact",
            "visibility": "actor_private",
            "owner_scope": fact.get("owner_scope"),
            "owner_ref": fact.get("owner_id"),
            "source_activation_id": fact.get("source_activation_id"),
            "record_seq": record_seq,
            "known_at_seq": known_at_seq,
            "occurred_in": occurred_in,
            "data": payload,
        }
        if known_at_seq is None:
            item["sequence_status"] = "unknown"
        events.append(_drop_none_values(item))
    return sorted(events, key=_known_event_sort_key)


def _statements_visible_at_seq(
    statements: list[dict[str, Any]],
    *,
    task_at_seq: int | None,
) -> list[dict[str, Any]]:
    if task_at_seq is None:
        return statements
    return [
        statement
        for statement in statements
        if not isinstance(statement.get("uttered_record_seq"), int)
        or isinstance(statement.get("uttered_record_seq"), bool)
        or int(statement["uttered_record_seq"]) <= task_at_seq
    ]


def _current_living_werewolf_teammates(
    source: dict[str, Any],
    *,
    private_facts: list[Any],
    self_ref: str | None,
) -> list[str]:
    all_teammate_refs: list[str] = []
    for fact in private_facts:
        if not isinstance(fact, dict) or fact.get("fact_type") not in {
            "werewolf_teammates",
            "living_werewolf_teammates",
        }:
            continue
        payload = fact.get("payload")
        if isinstance(payload, dict):
            payload = payload.get("teammate_refs")
        if not isinstance(payload, list):
            continue
        all_teammate_refs.extend(item for item in payload if isinstance(item, str))

    public_state = source.get("public_match_state")
    public_state = public_state if isinstance(public_state, dict) else {}
    raw_alive_refs = public_state.get("alive_player_ids")
    alive_refs = (
        {item for item in raw_alive_refs if isinstance(item, str)}
        if isinstance(raw_alive_refs, list)
        else None
    )
    return sorted(
        {
            item
            for item in all_teammate_refs
            if item != self_ref and (alive_refs is None or item in alive_refs)
        },
        key=_seat_ref_sort_key,
    )


def _canonical_living_werewolf_teammates_event(
    *,
    teammate_refs: list[str],
    task_at_seq: int | None,
    source: dict[str, Any],
    current_round_no: int,
    owner_ref: str | None,
) -> dict[str, Any]:
    return {
        "event_ref": "current_living_werewolf_teammates",
        "kind": "living_werewolf_teammates",
        "authority": "judge_fact",
        "visibility": "actor_private",
        "owner_scope": "player",
        "owner_ref": owner_ref,
        "known_at_seq": task_at_seq,
        "occurred_in": _v11_current_action_occurrence(
            source,
            current_round_no=current_round_no,
        ),
        "data": {"teammate_refs": list(teammate_refs)},
    }


def _v11_current_action_occurrence(
    source: dict[str, Any],
    *,
    current_round_no: int,
) -> dict[str, Any]:
    phase_id = source.get("phase_id")
    night_no = _positive_int(source.get("night_no"))
    if isinstance(phase_id, str) and phase_id.startswith("day_"):
        return {"period": "day", "round_no": current_round_no}
    if isinstance(phase_id, str) and phase_id.startswith("night_"):
        return {"period": "night", "round_no": night_no or current_round_no}
    if night_no is not None:
        return {"period": "night", "round_no": night_no}
    return {"period": "day", "round_no": current_round_no}


def _attach_v11_first_party_claim_annotations(
    selected_events: list[dict[str, Any]],
    *,
    model_view: dict[str, Any],
) -> None:
    annotations_by_source: dict[str, list[dict[str, Any]]] = {}
    timeline = model_view.get("timeline")
    timeline = timeline if isinstance(timeline, list) else []
    for statement in timeline:
        if not isinstance(statement, dict):
            continue
        source_event_ref = statement.get("source_event_id")
        raw_annotations = statement.get("annotations")
        if not isinstance(source_event_ref, str) or not isinstance(raw_annotations, list):
            continue
        compact = [
            projected
            for annotation in raw_annotations
            if isinstance(annotation, dict)
            and (projected := _v11_first_party_claim_annotation(annotation)) is not None
        ]
        if compact:
            annotations_by_source[source_event_ref] = compact

    for event in selected_events:
        event_ref = event.get("event_ref")
        if event.get("kind") != "player_statement" or not isinstance(event_ref, str):
            continue
        annotations = annotations_by_source.get(event_ref)
        if annotations:
            event["annotations"] = annotations


def _v11_first_party_claim_annotation(
    annotation: dict[str, Any],
) -> dict[str, Any] | None:
    claim_type = annotation.get("claim_type")
    if claim_type not in {
        "role_claim",
        "team_claim",
        "investigation_claim",
        "future_investigation_plan",
    }:
        return None
    derivation = annotation.get("derivation")
    if not _is_complete_derivation(derivation):
        return None
    result = {
        "claim_id": annotation.get("claim_id"),
        "claim_type": claim_type,
        "authority": "player_claim_unverified",
        "sentence_index": annotation.get("sentence_index"),
        "derivation": derivation,
    }
    for key in (
        "claimed_role",
        "claimed_team",
        "claimed_action_in",
        "target_ref",
        "claimed_result",
        "specificity",
    ):
        if key in annotation:
            result[key] = annotation[key]
    return _drop_none_values(result)


def _is_complete_derivation(value: Any) -> bool:
    return (
        isinstance(value, dict)
        and value.get("kind") == "deterministic_heuristic"
        and _positive_int(value.get("validator_version")) is not None
        and value.get("validation_status") == "complete"
    )


def _v11_temporal_state(
    source: dict[str, Any],
    *,
    selected_events: list[dict[str, Any]],
    current_round_no: int,
) -> dict[str, Any]:
    current_period = _v11_current_action_occurrence(
        source,
        current_round_no=current_round_no,
    )["period"]
    publicly_announced_nights = [
        round_no
        for event in selected_events
        if event.get("visibility") == "public" and event.get("kind") == "night_result"
        for occurred_in in (event.get("occurred_in"),)
        if isinstance(occurred_in, dict)
        for round_no in (_positive_int(occurred_in.get("round_no")),)
        if round_no is not None
    ]
    latest_publicly_announced_night_no = max(publicly_announced_nights, default=0)
    if current_period == "night":
        latest_completed_night_no = max(
            latest_publicly_announced_night_no,
            current_round_no - 1,
        )
    else:
        # Player-facing day actions, including the pre-dawn sheriff election,
        # only begin after the current round's night actions have resolved.
        latest_completed_night_no = max(
            latest_publicly_announced_night_no,
            current_round_no,
        )
    return {
        "current_period": current_period,
        "current_round_no": current_round_no,
        "latest_completed_night_no": latest_completed_night_no,
        "next_night_no": latest_completed_night_no + 1,
    }


def _v11_discourse_projection(
    model_view: dict[str, Any],
    *,
    selected_events: list[dict[str, Any]],
    current_round_no: int,
    include_reply_opportunity: bool,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    event_by_ref = {
        str(event["event_ref"]): event
        for event in selected_events
        if isinstance(event, dict) and isinstance(event.get("event_ref"), str)
    }
    raw_questions = model_view.get("questions")
    raw_questions = raw_questions if isinstance(raw_questions, list) else []
    questions: list[dict[str, Any]] = []
    for raw_question in raw_questions:
        if not isinstance(raw_question, dict):
            continue
        asked_in = raw_question.get("asked_in")
        if not isinstance(asked_in, dict) or asked_in.get("round_no") != current_round_no:
            continue
        question_id = raw_question.get("question_id")
        source_event_ref = raw_question.get("source_event_ref")
        response_status = raw_question.get("response_status")
        address_resolution = raw_question.get("address_resolution")
        derivation = raw_question.get("derivation")
        if (
            not isinstance(question_id, str)
            or not isinstance(source_event_ref, str)
            or source_event_ref not in event_by_ref
            or response_status not in {"none_detected", "response_detected"}
            or address_resolution not in {"resolved", "unresolved"}
            or not _is_complete_derivation(derivation)
        ):
            continue
        source_event = event_by_ref[source_event_ref]
        asked_at_seq = _positive_int(raw_question.get("asked_at_seq"))
        if asked_at_seq is None:
            asked_at_seq = _positive_int(source_event.get("known_at_seq"))
        item: dict[str, Any] = {
            "question_id": question_id,
            "source_event_ref": source_event_ref,
            "source_authority": raw_question.get("source_authority"),
            "asked_by": raw_question.get("asked_by"),
            "addressed_to": raw_question.get("addressed_to"),
            "address_resolution": address_resolution,
            "asked_at_seq": asked_at_seq,
            "topic": raw_question.get("topic"),
            "response_status": response_status,
            "derivation": derivation,
        }
        requested_fields = raw_question.get("requested_fields")
        if isinstance(requested_fields, list):
            retained_requested_fields = [
                field for field in requested_fields if field in {"target_ref", "claimed_result"}
            ]
            if retained_requested_fields:
                item["requested_fields"] = retained_requested_fields
        referenced_night_no = _positive_int(raw_question.get("referenced_night_no"))
        if referenced_night_no is not None:
            item["referenced_night_no"] = referenced_night_no
        reply_opportunity = raw_question.get("reply_opportunity")
        if include_reply_opportunity and reply_opportunity in {
            "awaiting_scheduled_turn",
            "current_speaker_turn",
            "scheduled_turn_passed",
            "not_in_current_speech_order",
        }:
            item["reply_opportunity"] = reply_opportunity
        retained_refs: list[str] = []
        prior_refs = raw_question.get("prior_relevant_statement_refs")
        if isinstance(prior_refs, list):
            retained_refs = [
                ref for ref in prior_refs if isinstance(ref, str) and ref in event_by_ref
            ]
            if retained_refs:
                item["prior_relevant_event_refs"] = retained_refs
        if retained_refs and raw_question.get("prior_coverage") == "already_publicly_reported":
            item["prior_coverage"] = "already_publicly_reported"
        questions.append(_drop_none_values(item))

    question_by_id = {
        question["question_id"]: question
        for question in questions
        if isinstance(question.get("question_id"), str)
    }
    raw_relations = model_view.get("relations")
    raw_relations = raw_relations if isinstance(raw_relations, list) else []
    relations: list[dict[str, Any]] = []
    for raw_relation in raw_relations:
        if not isinstance(raw_relation, dict):
            continue
        question_id = raw_relation.get("to_question_id")
        from_event_ref = raw_relation.get("from_event_ref")
        derivation = raw_relation.get("derivation")
        question = question_by_id.get(question_id) if isinstance(question_id, str) else None
        if (
            question is None
            or not isinstance(from_event_ref, str)
            or from_event_ref not in event_by_ref
            or question["source_event_ref"] not in event_by_ref
            or raw_relation.get("temporal_order_valid") is not True
            or raw_relation.get("type") != "response_to_question"
            or not _is_complete_derivation(derivation)
        ):
            continue
        relations.append(
            {
                "relation_id": raw_relation.get("relation_id"),
                "type": "response_to_question",
                "from_event_ref": from_event_ref,
                "to_question_id": question_id,
                "temporal_order_valid": True,
                "derivation": derivation,
            }
        )
    return questions, relations


def _is_scheduled_speech_action(task: dict[str, Any]) -> bool:
    action_type = task.get("type")
    return (
        isinstance(action_type, str)
        and ("speech" in action_type or action_type.endswith("last_words"))
        and isinstance(task.get("speech_order"), list)
    )


def _seat_ref_sort_key(value: str) -> tuple[int, str]:
    if value.startswith("seat_") and value[5:].isdigit():
        return int(value[5:]), value
    return 10_000, value


def _private_fact_occurrence(payload: Any, *, current_round_no: int) -> dict[str, Any]:
    if isinstance(payload, dict):
        night_no = _positive_int(payload.get("night_no"))
        if night_no is not None:
            return {"period": "night", "round_no": night_no}
        round_no = _positive_int(payload.get("round_no"))
        if round_no is not None:
            return {"period": "day", "round_no": round_no}
    return {"period": "current_action", "round_no": current_round_no}


def _v13_projection_metadata(
    *,
    ledger: dict[str, Any],
    model_view_metadata: dict[str, Any],
    projected_context: dict[str, Any],
    selected_events: list[dict[str, Any]],
    selector_audit: dict[str, Any],
    questions: list[dict[str, Any]],
    relations: list[dict[str, Any]],
    current_round_no: int,
    model_view_schema_version: int,
    canonical_known_events: dict[str, Any],
    compact_known_events: dict[str, Any],
) -> dict[str, Any]:
    statements = ledger.get("statements")
    statements = statements if isinstance(statements, list) else []
    ledger_claims = ledger.get("claims")
    ledger_claims = ledger_claims if isinstance(ledger_claims, list) else []
    ledger_questions = ledger.get("questions")
    ledger_questions = ledger_questions if isinstance(ledger_questions, list) else []
    ledger_relations = ledger.get("relations")
    ledger_relations = ledger_relations if isinstance(ledger_relations, list) else []
    annotations = [
        annotation
        for event in selected_events
        if isinstance(event.get("annotations"), list)
        for annotation in event["annotations"]
        if isinstance(annotation, dict)
    ]
    selected_sequences = [
        sequence
        for event in selected_events
        for sequence in (_positive_int(event.get("known_at_seq")),)
        if sequence is not None
    ]
    current_round_statements = [
        statement
        for statement in statements
        if isinstance(statement, dict)
        and isinstance(statement.get("occurred_in"), dict)
        and statement["occurred_in"].get("round_no") == current_round_no
    ]

    def count(name: str, fallback: int) -> int:
        value = model_view_metadata.get(name)
        return (
            value
            if isinstance(value, int) and not isinstance(value, bool) and value >= 0
            else fallback
        )

    source_claim_count = count("source_claim_candidate_count", len(ledger_claims))
    validated_claim_count = count("emitted_claim_count", len(annotations))
    emitted_claim_count = len(annotations)
    source_question_count = count("source_question_count", len(ledger_questions))
    out_of_scope_question_count = count("out_of_scope_question_count", 0)
    emitted_question_count = count("emitted_question_count", len(questions))
    current_scope_question_count = count(
        "current_scope_question_count",
        max(0, source_question_count - out_of_scope_question_count),
    )
    source_relation_count = count("source_relation_count", len(ledger_relations))
    emitted_relation_count = count("emitted_relation_count", len(relations))
    derivation_rejections = model_view_metadata.get("derivation_rejections")
    derivation_rejections = (
        [dict(item) for item in derivation_rejections if isinstance(item, dict)]
        if isinstance(derivation_rejections, list)
        else []
    )
    metadata = {
        "prompt_schema_version": MODEL_CONTEXT_SCHEMA_VERSION,
        "model_context_schema_version": MODEL_CONTEXT_SCHEMA_VERSION,
        "prompt_template_version": projected_context["prompt_template_version"],
        "known_events_schema_version": projected_context["known_events"]["schema_version"],
        "ledger_schema_version": (
            _positive_int(ledger.get("ledger_schema_version")) or DISCOURSE_LEDGER_SCHEMA_VERSION
        ),
        "model_view_schema_version": model_view_schema_version,
        "model_view_selector_version": MODEL_VIEW_SELECTOR_VERSION,
        "serialized_char_count": _serialized_chars(projected_context),
        "section_char_counts": {
            key: _serialized_chars(value)
            for key, value in projected_context.items()
            if key not in {"model_context_schema_version", "prompt_template_version"}
        },
        "ledger_statement_count": len(statements),
        "ledger_statement_char_count": sum(
            len(str(item.get("speech") or "")) for item in statements if isinstance(item, dict)
        ),
        "ledger_claim_count": len(ledger_claims),
        "ledger_question_count": len(ledger_questions),
        "ledger_relation_count": len(ledger_relations),
        "source_event_count": selector_audit["source_count"],
        "emitted_event_count": len(selected_events),
        "future_filtered_event_count": selector_audit["future_filtered_count"],
        "selector_omitted_event_count": selector_audit["omitted_count"],
        "budget_dropped_event_count": 0,
        "selector": selector_audit,
        "known_event_record_seq_min": min(selected_sequences, default=None),
        "known_event_record_seq_max": max(selected_sequences, default=None),
        "source_claim_candidate_count": source_claim_count,
        "emitted_claim_count": emitted_claim_count,
        "out_of_scope_claim_count": max(0, validated_claim_count - emitted_claim_count),
        "rejected_claim_count": count(
            "rejected_claim_count",
            max(0, source_claim_count - validated_claim_count),
        ),
        "source_question_count": source_question_count,
        "current_scope_question_count": current_scope_question_count,
        "emitted_question_count": emitted_question_count,
        "out_of_scope_question_count": out_of_scope_question_count,
        "invalid_question_count": count(
            "invalid_question_count",
            max(0, current_scope_question_count - emitted_question_count),
        ),
        "source_relation_count": source_relation_count,
        "emitted_relation_count": emitted_relation_count,
        "invalid_relation_count": count(
            "invalid_relation_count",
            max(0, source_relation_count - emitted_relation_count),
        ),
        "none_detected_question_count": sum(
            question.get("response_status") == "none_detected" for question in questions
        ),
        "response_detected_question_count": sum(
            question.get("response_status") == "response_detected" for question in questions
        ),
        "awaiting_scheduled_turn_question_count": sum(
            question.get("reply_opportunity") == "awaiting_scheduled_turn" for question in questions
        ),
        "current_round_statement_count": len(current_round_statements),
        "current_round_statement_char_count": sum(
            len(str(item.get("speech") or ""))
            for item in current_round_statements
            if isinstance(item, dict)
        ),
        "derivation_rejections": derivation_rejections,
    }
    metadata.update(
        build_known_events_v7_compaction_metadata(
            canonical_known_events,
            compact_known_events,
        )
    )
    return metadata


def _known_event_sort_key(event: dict[str, Any]) -> tuple[int, int, int, str]:
    known_at_seq = _positive_int(event.get("known_at_seq"))
    record_seq = _positive_int(event.get("record_seq"))
    sequence = known_at_seq if known_at_seq is not None else record_seq
    timeline_index = _positive_int(event.get("timeline_index"))
    return (
        1 if sequence is None else 0,
        sequence or 0,
        timeline_index or 0,
        str(event.get("event_ref") or ""),
    )


def _positive_int(value: Any) -> int | None:
    if isinstance(value, int) and not isinstance(value, bool) and value > 0:
        return value
    return None


def _drop_none_values(value: dict[str, Any]) -> dict[str, Any]:
    return {key: item for key, item in value.items() if item is not None}


def _drop_empty_collections(value: Any) -> Any:
    if isinstance(value, dict):
        compacted = {key: _drop_empty_collections(item) for key, item in value.items()}
        return {key: item for key, item in compacted.items() if item not in (None, "", [], {})}
    if isinstance(value, list):
        compacted_items = [_drop_empty_collections(item) for item in value]
        return [item for item in compacted_items if item not in (None, "", [], {})]
    return value


def _serialized_chars(value: Any) -> int:
    return len(json.dumps(value, ensure_ascii=False, separators=(",", ":")))


def model_prompt_metadata(
    context: dict[str, Any],
    *,
    projection_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if (
        context.get("model_context_schema_version") != MODEL_CONTEXT_SCHEMA_VERSION
        or context.get("prompt_template_version") != PROMPT_TEMPLATE_VERSION
    ):
        raise ValueError("unsupported_model_prompt_contract")
    compact_known_events = context.get("known_events")
    compact_known_events = compact_known_events if isinstance(compact_known_events, dict) else {}
    if compact_known_events.get("schema_version") != KNOWN_EVENTS_SCHEMA_VERSION:
        raise ValueError("unsupported_known_events_schema_version")
    try:
        known_events = expand_known_events_v7(compact_known_events)
    except ModelContextCompactionError as exc:
        raise ValueError("unsupported_known_events_schema_version") from exc
    events = known_events.get("events")
    questions = known_events.get("questions")
    relations = known_events.get("relations")
    events = events if isinstance(events, list) else []
    questions = questions if isinstance(questions, list) else []
    relations = relations if isinstance(relations, list) else []
    annotations = [
        annotation
        for event in events
        if isinstance(event, dict) and isinstance(event.get("annotations"), list)
        for annotation in event["annotations"]
        if isinstance(annotation, dict)
    ]
    record_seqs = [
        sequence
        for event in events
        if isinstance(event, dict)
        for sequence in (_positive_int(event.get("record_seq")),)
        if sequence is not None
    ]
    metadata: dict[str, Any] = {
        "prompt_schema_version": MODEL_CONTEXT_SCHEMA_VERSION,
        "model_context_schema_version": MODEL_CONTEXT_SCHEMA_VERSION,
        "prompt_template_version": context["prompt_template_version"],
        "known_events_schema_version": KNOWN_EVENTS_SCHEMA_VERSION,
        "serialized_char_count": _serialized_chars(context),
        "known_event_count": len(events),
        "known_event_record_seq_min": min(record_seqs, default=None),
        "known_event_record_seq_max": max(record_seqs, default=None),
        "known_event_kind_counts": {
            kind: sum(isinstance(event, dict) and event.get("kind") == kind for event in events)
            for kind in sorted(
                {
                    event.get("kind")
                    for event in events
                    if isinstance(event, dict) and isinstance(event.get("kind"), str)
                }
            )
        },
        "structured_claim_count": len(annotations),
        "question_count": len(questions),
        "none_detected_question_count": sum(
            isinstance(question, dict) and question.get("response_status") == "none_detected"
            for question in questions
        ),
        "response_detected_question_count": sum(
            isinstance(question, dict) and question.get("response_status") == "response_detected"
            for question in questions
        ),
        "relation_count": len(relations),
    }
    if projection_metadata:
        metadata.update(projection_metadata)
    return metadata


def _current_round_no(
    source: dict[str, Any],
    *,
    statements: list[dict[str, Any]],
) -> int:
    value = source.get("round_no")
    if isinstance(value, int) and not isinstance(value, bool) and value > 0:
        return value
    public_state = source.get("public_match_state")
    if isinstance(public_state, dict):
        value = public_state.get("round_no")
        if isinstance(value, int) and not isinstance(value, bool) and value > 0:
            return value
    statement_rounds = [
        occurred_in["round_no"]
        for statement in statements
        if isinstance((occurred_in := statement.get("occurred_in")), dict)
        and isinstance(occurred_in.get("round_no"), int)
        and not isinstance(occurred_in.get("round_no"), bool)
        and occurred_in["round_no"] > 0
    ]
    return max(statement_rounds, default=1)


def _model_task(source: dict[str, Any]) -> dict[str, Any]:
    task: dict[str, Any] = {
        "action_type": source.get("action_type"),
        "objective": source.get("objective"),
        "phase_id": source.get("phase_id"),
        "round_no": source.get("round_no"),
    }
    for field in (
        "night_no",
        "speech_round",
        "speech_order",
        "vote_round",
        "pk_candidate_ids",
        "original_candidate_ids",
        "original_off_sheriff_voter_ids",
        "public_stage",
        "ability_id",
        "decision_rules",
    ):
        if field in source:
            task[field] = source[field]
    current_action_effect = source.get("current_action_effect")
    if not isinstance(current_action_effect, dict):
        current_action_effect = _default_current_action_effect(source)
    task["mechanical_effect"] = _without_explanations(current_action_effect)
    return {key: value for key, value in task.items() if value is not None}


def _model_speech_progress(
    task: dict[str, Any],
    *,
    actor_ref: str | None,
) -> dict[str, Any] | None:
    raw_order = task.get("speech_order")
    if (
        not isinstance(raw_order, list)
        or not raw_order
        or actor_ref is None
        or actor_ref not in raw_order
        or any(not isinstance(item, str) for item in raw_order)
    ):
        return None
    current_index = raw_order.index(actor_ref)
    return {
        "current_speaker_ref": actor_ref,
        "current_position": current_index + 1,
        "total_speakers": len(raw_order),
        "scheduled_before_refs": raw_order[:current_index],
        "remaining_speaker_refs": raw_order[current_index + 1 :],
        "instruction": (
            "remaining_speaker_refs 中的玩家本轮尚未轮到发言；"
            "不得因此描述成拒绝回应、故意沉默或轮到后仍不解释"
        ),
    }


def _model_hard_rules(
    value: Any,
    *,
    include_win_condition_contract: bool = False,
) -> dict[str, Any]:
    contract = value if isinstance(value, dict) else {}
    roles = contract.get("roles")
    roles = roles if isinstance(roles, list) else []
    configured_werewolf_count = contract.get("werewolf_count")
    if isinstance(configured_werewolf_count, int) and not isinstance(
        configured_werewolf_count,
        bool,
    ):
        werewolf_count: int | None = configured_werewolf_count
    elif roles:
        werewolf_count = sum(
            int(item.get("count") or 0)
            for item in roles
            if isinstance(item, dict) and item.get("role_key") == "werewolf"
        )
    else:
        werewolf_count = None
    night_rules = contract.get("night_action_rules")
    night_rules = night_rules if isinstance(night_rules, dict) else {}
    ability_rules: dict[str, Any] = {}
    for ability_id, raw_rule in night_rules.items():
        if not isinstance(ability_id, str) or not isinstance(raw_rule, dict):
            continue
        rule = _without_explanations(raw_rule)
        if ability_id == "werewolf_attack":
            rule.pop("actor_scope", None)
            rule.pop("single_werewolf_resolution", None)
            if werewolf_count == 1:
                rule["coordination"] = "solo"
                rule.pop("team_resolution", None)
                rule.pop("can_target_werewolf_teammates", None)
            elif isinstance(werewolf_count, int) and werewolf_count > 1:
                rule["coordination"] = "team"
        ability_rules[ability_id] = rule
    result = {
        "rule_id": contract.get("rule_id"),
        "rule_version": contract.get("rule_version"),
        "player_count": contract.get("player_count"),
        "roles": [
            {
                key: item.get(key)
                for key in ("role_key", "role_label", "count", "team")
                if item.get(key) is not None
            }
            for item in roles
            if isinstance(item, dict)
        ],
        "werewolf_count": werewolf_count,
        "max_rounds": contract.get("max_rounds"),
        "win_condition": contract.get("win_condition"),
        "win_condition_contract": (
            build_public_win_condition_contract(
                contract.get("win_condition"),
                frozen_role_keys=tuple(
                    str(item.get("role_key"))
                    for item in roles
                    if isinstance(item, dict) and isinstance(item.get("role_key"), str)
                ),
            )
            if include_win_condition_contract
            else None
        ),
        "reveal_policy": contract.get("reveal_policy"),
        "role_reveal_rule": contract.get("role_reveal_rule"),
        "ability_lifecycle": _without_explanations(contract.get("ability_lifecycle")),
        "sheriff": {
            "enabled": bool(contract.get("sheriff_enabled")),
            "vote_weight": contract.get("sheriff_vote_weight"),
        },
        "speech": {
            "policy": contract.get("speech_policy"),
            "rounds": contract.get("speech_rounds"),
            "exile_last_words_enabled": bool(contract.get("exile_last_words_enabled")),
            "first_night_last_words_enabled": bool(contract.get("first_night_last_words_enabled")),
        },
        "werewolf_self_explosion_enabled": bool(contract.get("werewolf_self_explosion_enabled")),
        "ability_rules": ability_rules,
    }
    return {key: item for key, item in result.items() if item is not None}


def _model_self(
    source: dict[str, Any],
    *,
    private_facts: list[Any],
    hard_rules: dict[str, Any],
) -> dict[str, Any]:
    identity = source.get("self_identity")
    identity = identity if isinstance(identity, dict) else {}
    role_key = identity.get("role_key")
    self_ref = identity.get("player_id")
    visible_private_facts = (
        [
            fact
            for fact in private_facts
            if not isinstance(fact, dict)
            or fact.get("fact_type") not in {"werewolf_teammates", "living_werewolf_teammates"}
        ]
        if role_key == "werewolf"
        else private_facts
    )
    result: dict[str, Any] = {
        "identity": {
            key: identity.get(key)
            for key in ("player_id", "seat", "role_key", "team")
            if identity.get(key) is not None
        },
        "private_judge_facts": visible_private_facts,
        "role_capabilities": _without_explanations(source.get("role_capabilities")),
        "ability_runtime_state": _without_explanations(source.get("ability_runtime_state")),
        "public_office_capabilities": _without_explanations(
            source.get("public_office_capabilities")
        ),
        "state_restrictions": _without_explanations(source.get("current_state_restrictions")),
    }
    if role_key == "werewolf":
        living_teammates = _living_werewolf_teammates(
            private_facts,
            self_ref=self_ref if isinstance(self_ref, str) else None,
            werewolf_count=hard_rules.get("werewolf_count"),
        )
        result["werewolf_coordination"] = (
            {"mode": "solo"}
            if hard_rules.get("werewolf_count") == 1
            else {
                "mode": "team",
                "living_teammate_refs": living_teammates or [],
            }
        )
    return result


def _living_werewolf_teammates(
    private_facts: list[Any],
    *,
    self_ref: str | None,
    werewolf_count: Any,
) -> list[str] | None:
    if werewolf_count == 1:
        return []
    for fact in reversed(private_facts):
        if not isinstance(fact, dict):
            continue
        if fact.get("fact_type") not in {
            "werewolf_teammates",
            "living_werewolf_teammates",
        }:
            continue
        payload = fact.get("payload")
        if not isinstance(payload, list):
            continue
        return [item for item in payload if isinstance(item, str) and item != self_ref]
    return None


def _model_public_state(source: dict[str, Any]) -> dict[str, Any]:
    public_match_state = source.get("public_match_state")
    public_match_state = dict(public_match_state) if isinstance(public_match_state, dict) else {}
    sheriff_player_id = source.get("sheriff_player_id")
    if sheriff_player_id is not None:
        public_match_state["sheriff_player_id"] = sheriff_player_id
    office = source.get("public_office_capabilities")
    if isinstance(office, dict):
        badge_state = office.get("sheriff_badge_state")
        if badge_state is not None:
            public_match_state["sheriff_badge_state"] = badge_state
    return public_match_state


def _model_public_timeline(events: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "schema_version": PUBLIC_TIMELINE_SCHEMA_VERSION,
        "source_rules": {
            "record_seq_clock": (
                "record_seq 是全部公开事件唯一可比较的时间顺序；数值更小的事件先发生"
            ),
            "authority_rule": (
                "authority=judge_fact 是法官确认的公开事实；"
                "authority=player_claim_unverified 是玩家原话，不是法官确认"
            ),
            "statement_reference_rule": (
                "kind=player_statement 的 statement_ref 对应 "
                "history.timeline 中相同 source_event_id 的完整原话"
            ),
            "causality_rule": (
                "后发生的任何公开事件只能用于事后评价，不得被描述为更早行动当时"
                "已经存在的理由、信息、回答或反应"
            ),
            "missing_record_seq_rule": (
                "缺少 record_seq 的事件只能沿用输入位置，不得与其他事件推断精确先后"
            ),
            "duplicate_record_seq_rule": (
                "若输入出现相同 record_seq，则沿用输入顺序展示，"
                "但不得推断这些同序事件之间的精确因果先后"
            ),
        },
        "events": events,
    }


def _response_allows_speech(value: Any) -> bool:
    contract = value if isinstance(value, dict) else {}
    speech = contract.get("speech")
    speech = speech if isinstance(speech, dict) else {}
    return speech.get("mode") in {"required", "optional", "required_if_true"}


def _model_response_v11(value: Any) -> dict[str, Any]:
    contract = value if isinstance(value, dict) else {}
    kind = contract.get("kind")
    speech = contract.get("speech")
    speech = speech if isinstance(speech, dict) else {}
    projected_speech = {
        key: speech.get(key)
        for key in ("mode", "max_chars", "max_sentences", "condition")
        if speech.get(key) is not None
    }
    result: dict[str, Any] = {
        "kind": kind,
        "presentation_kind": contract.get("presentation_kind"),
        "language": contract.get("language"),
        "speech": projected_speech,
    }
    decision_note = contract.get("decision_note")
    if isinstance(decision_note, dict):
        result["decision_note"] = {
            key: decision_note.get(key)
            for key in ("mode", "max_chars")
            if decision_note.get(key) is not None
        }
    if kind == "target":
        target_policy = contract.get("target_policy")
        target_policy = target_policy if isinstance(target_policy, dict) else {}
        result["target_policy"] = {
            "mode": target_policy.get("mode"),
            "candidate_source": "candidates",
        }
    elif kind == "boolean":
        result["field"] = contract.get("field")
        boolean_contract = contract.get("boolean")
        if isinstance(boolean_contract, dict):
            result["boolean"] = {
                key: boolean_contract.get(key)
                for key in ("true_means", "false_means")
                if boolean_contract.get(key) is not None
            }
    compacted = _drop_empty_collections(result)
    return compacted if isinstance(compacted, dict) else {}


def _compact_persona(value: Any, *, include_delivery: bool = True) -> dict[str, Any]:
    profile = value if isinstance(value, dict) else {}
    personality = profile.get("personality")
    if isinstance(personality, str) and len(personality) > _PERSONA_TEXT_LIMIT:
        personality = personality[:_PERSONA_TEXT_LIMIT].rstrip() + "…"
    delivery = (
        {
            "delivery_mood": profile.get("base_delivery_mood"),
            "delivery_intensity": profile.get("base_delivery_intensity"),
            "delivery_pace": profile.get("base_delivery_pace"),
            "delivery_instruction": profile.get("base_delivery_instruction"),
        }
        if include_delivery
        else {}
    )
    return {
        key: item
        for key, item in {
            "personality": personality,
            "strategy_profile": profile.get("strategy_profile"),
            **delivery,
        }.items()
        if item not in (None, [], "")
    }


def _without_explanations(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _without_explanations(item)
            for key, item in value.items()
            if key not in {"source", "instruction"}
        }
    if isinstance(value, list):
        return [_without_explanations(item) for item in value]
    return value


def sanitize_model_speech(
    speech: str,
    *,
    players: tuple[ModelPlayerReference, ...],
) -> str:
    return _project_text(speech, players=players)


def resolve_model_target(
    target: str | None,
    *,
    players: tuple[ModelPlayerReference, ...],
) -> str | None:
    if target is None:
        return None
    return {player.ref: player.player_id for player in players}.get(target)


def _default_current_action_effect(context: dict[str, Any]) -> dict[str, Any]:
    output_contract = context.get("output_contract")
    output_contract = output_contract if isinstance(output_contract, dict) else {}
    target_policy = output_contract.get("target_policy")
    target_policy = target_policy if isinstance(target_policy, dict) else {}
    return {
        "action_type": context.get("action_type"),
        "source": "current_action_contract",
        "target_mode": target_policy.get("mode", "none"),
        "speech_has_gameplay_effect": False,
        "instruction": (
            "该字段只描述本次动作契约已经确定的机械边界；speech 可以表达策略、"
            "判断或伪装，但不会自行产生死亡、技能、投票或其他游戏效果。"
        ),
    }


def build_public_rule_contract(
    *,
    rule: dict[str, Any],
    max_rounds: int,
) -> dict[str, Any]:
    raw_roles = rule.get("roles")
    roles: list[dict[str, Any]] = []
    if isinstance(raw_roles, list):
        for raw_role in raw_roles:
            if not isinstance(raw_role, dict):
                continue
            role_label = raw_role.get("role")
            count = raw_role.get("count")
            if (
                not isinstance(role_label, str)
                or not role_label.strip()
                or not isinstance(count, int)
                or isinstance(count, bool)
                or count < 1
            ):
                continue
            role_key = normalize_role_key(role_label)
            roles.append(
                {
                    "role_key": role_key,
                    "role_label": role_label.strip(),
                    "count": count,
                    "team": normalize_team_key(raw_role.get("team"), role_key=role_key),
                }
            )

    player_count = rule.get("player_count")
    if not isinstance(player_count, int) or isinstance(player_count, bool):
        player_count = sum(item["count"] for item in roles)
    werewolf_count = sum(item["count"] for item in roles if item["role_key"] == "werewolf")
    sheriff_enabled = bool(rule.get("sheriff_enabled"))
    role_composition = "、".join(f"{item['count']}名{item['role_label']}" for item in roles)
    role_keys = {item["role_key"] for item in roles}
    night_action_rules = _night_action_rules(
        role_keys=role_keys,
        werewolf_count=werewolf_count,
        ability_policies=rule.get("ability_policies"),
    )
    reveal_policy = str(rule.get("reveal_policy") or "hidden")
    return {
        "schema_version": 1,
        "source": "frozen_rule_snapshot",
        "rule_id": rule.get("id"),
        "rule_name": rule.get("name"),
        "rule_version": rule.get("version"),
        "player_count": player_count,
        "roles": roles,
        "role_composition": (
            f"本局共有{player_count}名玩家：{role_composition}。"
            if role_composition
            else f"本局共有{player_count}名玩家。"
        ),
        "werewolf_count": werewolf_count,
        "night_action_rules": night_action_rules,
        "max_rounds": max_rounds,
        "win_condition": rule.get("win_condition") or "wolves_gte_others",
        "reveal_policy": reveal_policy,
        "role_reveal_rule": (
            "玩家死亡或被放逐后，法官不会公开其身份或阵营；"
            "出局方式、发言和投票结果均不能作为法官已证实其身份的依据。"
            if reveal_policy == "hidden"
            else "玩家死亡或被放逐后，法官会按照本局公开身份规则播报其身份。"
        ),
        "ability_lifecycle": {
            "active_abilities_require_alive": True,
            "eliminated_players_can_act_in_later_windows": False,
            "death_triggered_exceptions": (["hunter.death_shot"] if "hunter" in role_keys else []),
        },
        "sheriff_enabled": sheriff_enabled,
        "sheriff_vote_weight": (
            float(rule.get("sheriff_vote_weight") or 1) if sheriff_enabled else None
        ),
        "sheriff_rule": (
            "本局启用警长系统。"
            if sheriff_enabled
            else "本局不启用警长系统，不存在上警、警徽或警徽流机制。"
        ),
        "speech_policy": rule.get("speech_policy") or "sequential",
        "speech_rounds": int(rule.get("speech_rounds") or 1),
        "werewolf_self_explosion_enabled": bool(rule.get("werewolf_self_explosion_enabled")),
        "exile_last_words_enabled": bool(rule.get("exile_last_words_enabled")),
        "first_night_last_words_enabled": bool(rule.get("first_night_last_words_enabled")),
    }


def build_public_match_state(
    *,
    round_no: int,
    players: Iterable[Any],
) -> dict[str, Any]:
    player_list = tuple(players)
    alive_player_ids = [str(player.player_id) for player in player_list if bool(player.alive)]
    eliminated_player_ids = [
        str(player.player_id) for player in player_list if not bool(player.alive)
    ]
    return {
        "round_no": round_no,
        "alive_player_count": len(alive_player_ids),
        "alive_player_ids": alive_player_ids,
        "eliminated_player_count": len(eliminated_player_ids),
        "eliminated_player_ids": eliminated_player_ids,
        "identity_information_included": False,
    }


def build_private_round_memory_action_context(
    *,
    game_id: str,
    action_id: str,
    phase_id: str,
    round_no: int,
    batch_id: str,
    source_cutoff_record_seq: int,
    player_id: str,
    seat: int,
    role_key: str,
    team: str,
    persona: dict[str, Any],
    alive: bool,
    sheriff_player_id: str | None,
    sheriff_badge_state: str,
    rule: dict[str, Any],
    max_rounds: int,
    player_state: dict[str, Any] | None,
    players: Iterable[Any],
    private_facts: Iterable[dict[str, Any]],
    public_history: Iterable[dict[str, Any]],
    previous_memory_snapshot: dict[str, Any] | None,
    previous_memory_fact_id: str | None,
    previous_memory_source_cutoff_record_seq: int | None,
    memory_source_refs: Iterable[str],
    memory_source_refs_sha256: str,
) -> dict[str, Any]:
    """Build the exact durable context for one rolling private-memory action."""

    objective = private_round_memory_objective(round_no)
    return {
        "schema_version": 1,
        "action_id": action_id,
        "action_type": "private_round_memory",
        "game_id": game_id,
        "phase_id": phase_id,
        "actor": {"kind": "player", "id": player_id},
        "objective": objective,
        "output_contract": private_round_memory_output_contract(),
        "influence": {
            "schema_version": 1,
            "status": "disabled",
            "captured_at": None,
            "strength": 0,
            "signals": [],
        },
        **build_private_round_memory_source_context(
            round_no=round_no,
            batch_id=batch_id,
            source_cutoff_record_seq=source_cutoff_record_seq,
            player_id=player_id,
            seat=seat,
            role_key=role_key,
            team=team,
            persona=persona,
            alive=alive,
            sheriff_player_id=sheriff_player_id,
            sheriff_badge_state=sheriff_badge_state,
            rule=rule,
            max_rounds=max_rounds,
            player_state=player_state,
            players=players,
            private_facts=private_facts,
            public_history=public_history,
            previous_memory_snapshot=previous_memory_snapshot,
            previous_memory_fact_id=previous_memory_fact_id,
            previous_memory_source_cutoff_record_seq=(
                previous_memory_source_cutoff_record_seq
            ),
            memory_source_refs=memory_source_refs,
            memory_source_refs_sha256=memory_source_refs_sha256,
        ),
    }


def build_private_round_memory_source_context(
    *,
    round_no: int,
    batch_id: str,
    source_cutoff_record_seq: int,
    player_id: str,
    seat: int,
    role_key: str,
    team: str,
    persona: dict[str, Any],
    alive: bool,
    sheriff_player_id: str | None,
    sheriff_badge_state: str,
    rule: dict[str, Any],
    max_rounds: int,
    player_state: dict[str, Any] | None,
    players: Iterable[Any],
    private_facts: Iterable[dict[str, Any]],
    public_history: Iterable[dict[str, Any]],
    previous_memory_snapshot: dict[str, Any] | None,
    previous_memory_fact_id: str | None,
    previous_memory_source_cutoff_record_seq: int | None,
    memory_source_refs: Iterable[str],
    memory_source_refs_sha256: str,
) -> dict[str, Any]:
    facts = [dict(item) for item in private_facts]
    player_list = tuple(players)
    if normalize_role_key(role_key) == "werewolf":
        facts.append(
            {
                "fact_type": "living_werewolf_teammates",
                "payload": [
                    str(player.player_id)
                    for player in player_list
                    if bool(player.alive)
                    and normalize_role_key(player.role_key) == "werewolf"
                    and str(player.player_id) != player_id
                ],
            }
        )
    return {
        "round_no": round_no,
        **build_actor_information(
            player_id=player_id,
            seat=seat,
            role_key=role_key,
            team=team,
            persona=persona,
            alive=alive,
            sheriff_player_id=sheriff_player_id,
            sheriff_badge_state=sheriff_badge_state,
            rule=rule,
            player_state=player_state,
            private_facts=facts,
            current_action_type="private_round_memory",
        ),
        "private_authoritative_facts": private_authoritative_facts(
            facts,
            owner_scope="player",
            owner_id=player_id,
        ),
        "public_match_state": build_public_match_state(
            round_no=round_no,
            players=player_list,
        ),
        "candidates": [],
        "public_history": [dict(item) for item in public_history],
        "sheriff_player_id": sheriff_player_id,
        "public_rule_contract": build_public_rule_contract(
            rule=rule,
            max_rounds=max_rounds,
        ),
        "private_memory_batch_id": batch_id,
        "public_cutoff_record_seq": source_cutoff_record_seq,
        "memory_round_no": round_no,
        "memory_visibility": "actor_only",
        "rolling_memory_schema_version": 2,
        "previous_memory_snapshot": (
            dict(previous_memory_snapshot)
            if isinstance(previous_memory_snapshot, dict)
            else None
        ),
        "previous_memory_fact_id": previous_memory_fact_id,
        "previous_memory_source_cutoff_record_seq": (
            previous_memory_source_cutoff_record_seq
        ),
        "memory_source_refs": list(memory_source_refs),
        "memory_source_refs_sha256": memory_source_refs_sha256,
        "batch_id": batch_id,
        "projection_at_seq": source_cutoff_record_seq,
    }


def private_round_memory_objective(round_no: int) -> str:
    return (
        f"生成仅供你本人后续决策使用的第{round_no}轮滚动私有记忆快照。"
        "用上一份主观记忆、本轮新增事件和当前硬事实更新整份记忆；"
        "输出会完整替换运行时上一快照，不要只总结本轮。"
        "保留仍重要的主要判断和下一轮待验证事项，删除已过时内容；"
        "不得编造未知身份或结果，使用第一人称并保持精简。"
    )


def private_round_memory_output_contract() -> dict[str, Any]:
    return {
        "kind": "speech",
        "presentation_kind": "private_round_memory",
        "language": "zh-CN",
        "speech": {
            "type": "string",
            "mode": "required",
            "min_length": 1,
            "max_chars": 400,
            "max_sentences": 4,
        },
        "required_fields": ["speech"],
    }


def build_actor_information(
    *,
    player_id: str,
    seat: int,
    role_key: str,
    team: str,
    persona: dict[str, Any],
    alive: bool,
    sheriff_player_id: str | None,
    sheriff_badge_state: str,
    rule: dict[str, Any],
    player_state: dict[str, Any] | None = None,
    private_facts: Iterable[dict[str, Any]] | None = None,
    current_action_type: str | None = None,
    current_action_knowledge: dict[str, Any] | None = None,
) -> dict[str, Any]:
    normalized_role = normalize_role_key(role_key)
    state = player_state if isinstance(player_state, dict) else {}
    role_capabilities = _role_capabilities(
        role_key=normalized_role,
        rule=rule,
    )
    is_sheriff = (
        bool(rule.get("sheriff_enabled"))
        and sheriff_badge_state == "held"
        and sheriff_player_id == player_id
    )
    return {
        "self_identity": {
            "player_id": player_id,
            "seat": seat,
            "role_key": normalized_role,
            "team": normalize_team_key(team, role_key=normalized_role),
            "source": "private_role_assignment",
            "authoritative": True,
        },
        "role_capabilities": role_capabilities,
        "ability_runtime_state": _ability_runtime_state(
            abilities=role_capabilities["abilities"],
            alive=alive,
            player_state=state,
            private_facts=private_facts,
            current_action_type=current_action_type,
            current_action_knowledge=current_action_knowledge,
        ),
        "public_office_capabilities": _public_office_capabilities(
            is_sheriff=is_sheriff,
            sheriff_badge_state=sheriff_badge_state,
            rule=rule,
        ),
        "current_state_restrictions": {
            "alive": alive,
            "can_vote": bool(state.get("can_vote", True)) if alive else False,
            "idiot_revealed": bool(state.get("idiot_revealed")),
            "sheriff_badge_state": sheriff_badge_state,
            "instruction": (
                "角色能力与公开职位职权相加后，再受当前状态和本次动作候选范围限制；"
                "公开伪装或谎报身份不受此字段禁止。"
            ),
        },
        "actor_profile": persona,
    }


def _role_capabilities(
    *,
    role_key: str,
    rule: dict[str, Any],
) -> dict[str, Any]:
    werewolf_count = _werewolf_count_from_rule(rule)
    policies = rule.get("ability_policies")
    attack_policy = policies.get("werewolf_attack") if isinstance(policies, dict) else None
    allow_wolf_target = (
        isinstance(attack_policy, dict) and attack_policy.get("allow_wolf_target") is True
    )
    allow_no_attack = (
        isinstance(attack_policy, dict) and attack_policy.get("allow_no_attack") is True
    )
    target_description = (
        "一名存活玩家（可以选择狼人或自己）" if allow_wolf_target else "一名存活的非狼人玩家"
    )
    optional_description = "，也可以主动空刀" if allow_no_attack else ""
    capabilities: dict[str, list[dict[str, Any]]] = {
        "villager": [],
        "werewolf": [
            {
                "ability_id": "werewolf.attack",
                "timing": "night",
                "description": (
                    f"你是本局唯一狼人，独自选择{target_description}作为袭击目标"
                    f"{optional_description}。"
                    if werewolf_count == 1
                    else (
                        f"与存活狼人队友共同选择{target_description}作为袭击目标"
                        f"{optional_description}。"
                        if werewolf_count > 1
                        else f"选择{target_description}作为袭击目标{optional_description}。"
                    )
                ),
            }
        ],
        "seer": [
            {
                "ability_id": "seer.investigate",
                "timing": "night",
                "description": "选择一名其他存活玩家，法官私下返回其狼人或好人阵营结果。",
            }
        ],
        "guard": [
            {
                "ability_id": "guard.protect",
                "timing": "night",
                "description": "按照本局守卫规则选择一名存活玩家守护。",
            }
        ],
        "witch": [
            {
                "ability_id": "witch.heal",
                "timing": "night",
                "description": "在解药仍可用且符合本局规则时决定是否救治狼人袭击目标。",
            },
            {
                "ability_id": "witch.poison",
                "timing": "night",
                "description": "在毒药仍可用且符合本局规则时决定是否毒杀合法目标。",
            },
        ],
        "hunter": [
            {
                "ability_id": "hunter.death_shot",
                "timing": "death_reaction",
                "description": "死亡且符合本局猎人规则时，可以选择一名存活玩家开枪或放弃。",
            }
        ],
        "idiot": [
            {
                "ability_id": "idiot.exile_immunity",
                "timing": "first_exile",
                "description": "第一次被投票放逐时公开白痴身份并免于出局，之后失去投票权。",
            }
        ],
    }
    abilities = list(capabilities.get(role_key, []))
    if role_key == "werewolf" and bool(rule.get("werewolf_self_explosion_enabled")):
        abilities.append(
            {
                "ability_id": "werewolf.self_explosion",
                "timing": "eligible_day_windows",
                "description": (
                    "在本局允许的白天窗口决定是否自爆；执行后只有本人立即出局并公开确认"
                    "狼人身份，不会选择、杀死或带走其他玩家。"
                ),
            }
        )
    return {
        "source": "private_role_assignment_and_frozen_rules",
        "role_key": role_key,
        "abilities": abilities,
        "no_exclusive_active_ability": not abilities,
        "instruction": "这些是真实角色能力；获得或失去警长职位都不会改变此列表。",
    }


def _werewolf_count_from_rule(rule: dict[str, Any]) -> int:
    roles = rule.get("roles")
    if not isinstance(roles, list):
        return 0
    return sum(
        int(item.get("count") or 0)
        for item in roles
        if isinstance(item, dict) and normalize_role_key(item.get("role")) == "werewolf"
    )


def _ability_runtime_state(
    *,
    abilities: Iterable[dict[str, Any]],
    alive: bool,
    player_state: dict[str, Any],
    private_facts: Iterable[dict[str, Any]] | None,
    current_action_type: str | None,
    current_action_knowledge: dict[str, Any] | None,
) -> dict[str, Any]:
    facts = tuple(private_facts or ())
    knowledge = current_action_knowledge if isinstance(current_action_knowledge, dict) else {}
    current_ability_id = _ability_id_for_action(current_action_type)
    latest_commits: dict[str, dict[str, Any]] = {}
    for fact in facts:
        if not isinstance(fact, dict):
            continue
        if fact.get("fact_type") != "private_ability_action_committed":
            continue
        payload = fact.get("payload")
        if not isinstance(payload, dict):
            continue
        ability_id = payload.get("ability_id")
        if isinstance(ability_id, str):
            latest_commits[ability_id] = payload

    limited_uses = {
        "witch.heal": ("heal_remaining", "heal_used"),
        "witch.poison": ("poison_remaining", "poison_used"),
        "hunter.death_shot": (None, "shot_used"),
        "idiot.exile_immunity": (None, None),
    }
    runtime_abilities: list[dict[str, Any]] = []
    for ability in abilities:
        if not isinstance(ability, dict):
            continue
        ability_id = ability.get("ability_id")
        if not isinstance(ability_id, str):
            continue
        last_commit = latest_commits.get(ability_id)
        remaining_uses: int | None = None
        resource_status = "not_limited"
        limited = limited_uses.get(ability_id)
        if limited is not None:
            remaining_key, result_key = limited
            remaining_uses = 1
            if ability_id == "idiot.exile_immunity" and bool(player_state.get("idiot_revealed")):
                remaining_uses = 0
            elif (
                isinstance(last_commit, dict)
                and isinstance(last_commit.get("result"), dict)
                and result_key is not None
                and last_commit["result"].get(result_key) is True
            ):
                remaining_uses = 0
            explicit_remaining = (
                knowledge.get(remaining_key) if isinstance(remaining_key, str) else None
            )
            if isinstance(explicit_remaining, int) and not isinstance(explicit_remaining, bool):
                remaining_uses = max(0, explicit_remaining)
            resource_status = "consumed" if remaining_uses == 0 else "available"

        in_current_action_window = current_ability_id == ability_id
        death_reaction_window = (
            ability.get("timing") == "death_reaction" and in_current_action_window
        )
        actor_state_allows_execution = alive or death_reaction_window
        can_execute_now = (
            actor_state_allows_execution
            and in_current_action_window
            and resource_status != "consumed"
        )
        unavailable_now_reason: str | None = None
        if not actor_state_allows_execution:
            unavailable_now_reason = "actor_not_alive"
        elif resource_status == "consumed":
            unavailable_now_reason = "resource_consumed"
        elif not in_current_action_window:
            unavailable_now_reason = "not_current_action_window"

        runtime_ability: dict[str, Any] = {
            "ability_id": ability_id,
            "owned": True,
            "resource_status": resource_status,
            "remaining_uses": remaining_uses,
            "in_current_action_window": in_current_action_window,
            "can_execute_now": can_execute_now,
            "unavailable_now_reason": unavailable_now_reason,
        }
        runtime_abilities.append(runtime_ability)

    return {
        "source": "private_role_assignment_resource_history_and_current_window",
        "current_action_ability_id": current_ability_id,
        "abilities": runtime_abilities,
        "instruction": (
            "owned 只表示真实角色拥有该能力；是否已消耗以及本次动作能否执行，"
            "必须以 resource_status、remaining_uses 和 can_execute_now 为准。"
        ),
    }


def _ability_id_for_action(action_type: str | None) -> str | None:
    if not isinstance(action_type, str):
        return None
    if action_type.startswith("ability_") and action_type.endswith("_decision"):
        return action_type[len("ability_") : -len("_decision")]
    if action_type == "werewolf_self_explosion":
        return "werewolf.self_explosion"
    return _DIRECT_ACTION_ABILITY_IDS.get(action_type)


def _public_office_capabilities(
    *,
    is_sheriff: bool,
    sheriff_badge_state: str,
    rule: dict[str, Any],
) -> dict[str, Any]:
    sheriff_enabled = bool(rule.get("sheriff_enabled"))
    abilities: list[dict[str, Any]] = []
    if is_sheriff:
        abilities.append(
            {
                "authority_id": "sheriff.weighted_exile_vote",
                "timing": "weighted_exile_vote",
                "vote_weight": float(rule.get("sheriff_vote_weight") or 1),
            }
        )
        if str(rule.get("speech_policy") or "sequential") == "sheriff_directed":
            abilities.append(
                {
                    "authority_id": "sheriff.choose_speech_order",
                    "timing": "day_discussion_opening",
                }
            )
        abilities.append(
            {
                "authority_id": "sheriff.resolve_badge_after_death",
                "timing": "death_reaction",
                "choices": ["transfer_to_alive_player", "destroy_badge"],
            }
        )
    return {
        "source": "public_match_state_and_frozen_rules",
        "sheriff_system_enabled": sheriff_enabled,
        "is_current_sheriff": is_sheriff,
        "sheriff_badge_state": sheriff_badge_state,
        "abilities": abilities,
        "instruction": ("警长职权只与职位有关，不会授予验人、用药、守护、开枪或其他角色能力。"),
    }


def _night_action_rules(
    *,
    role_keys: set[str],
    werewolf_count: int,
    ability_policies: Any,
) -> dict[str, Any]:
    policies = ability_policies if isinstance(ability_policies, dict) else {}
    attack_policy = policies.get("werewolf_attack")
    if not isinstance(attack_policy, dict):
        attack_policy = {
            "resolution": "unanimous_no_attack",
            "allow_no_attack": False,
            "allow_wolf_target": False,
        }
    allow_no_attack = attack_policy.get("allow_no_attack") is True
    allow_wolf_target = attack_policy.get("allow_wolf_target") is True
    result: dict[str, Any] = {
        "werewolf_attack": {
            "enabled": werewolf_count > 0,
            "actor_scope": "所有存活狼人",
            "target_scope": (
                "一名存活玩家，可以选择狼人或自己" if allow_wolf_target else "一名存活的非狼人玩家"
            ),
            "each_actor_must_choose_target": not allow_no_attack,
            "can_target_self": allow_wolf_target,
            "can_target_werewolf_teammates": allow_wolf_target,
            "team_resolution": dict(attack_policy),
            "single_werewolf_resolution": (
                "本局只有1名狼人时，由该狼人直接作出最终选择，不会发生团队平票。"
                if werewolf_count == 1
                else None
            ),
        }
    }
    if "guard" in role_keys:
        guard_policy = policies.get("guard")
        result["guard_protect"] = {
            "enabled": True,
            "target_scope": "一名存活玩家，可以选择自己",
            "target_required": True,
            "first_night_self_protect": bool(
                isinstance(guard_policy, dict) and guard_policy.get("first_night_self_protect")
            ),
            "can_repeat_previous_night_target": bool(
                isinstance(guard_policy, dict) and guard_policy.get("consecutive_same_target")
            ),
            "successful_protection_effect": (
                "若守护目标当夜受到狼人攻击，该目标不会因这次攻击出局。"
            ),
        }
    if "seer" in role_keys:
        result["seer_investigate"] = {
            "enabled": True,
            "target_scope": "一名其他存活玩家",
            "target_required": True,
            "result_scope": "法官只向预言家确认目标属于狼人阵营或好人阵营",
        }
    if "witch" in role_keys:
        witch_policy = policies.get("witch")
        witch_policy = witch_policy if isinstance(witch_policy, dict) else {}
        result["witch"] = {
            "enabled": True,
            "first_night_self_heal": bool(witch_policy.get("first_night_self_heal")),
            "heal_poison_mutually_exclusive": bool(
                witch_policy.get("heal_poison_mutually_exclusive")
            ),
            "poison_excludes_self": bool(witch_policy.get("poison_excludes_self")),
            "poison_excludes_attacked_target": bool(
                witch_policy.get("poison_excludes_attacked_target")
            ),
        }
    if "hunter" in role_keys:
        hunter_policy = policies.get("hunter")
        hunter_policy = hunter_policy if isinstance(hunter_policy, dict) else {}
        result["hunter_death_shot"] = {
            "enabled": True,
            "poison_disables_shot": bool(hunter_policy.get("poison_disables_shot")),
        }
    return result


def private_authoritative_facts(
    knowledge: Any,
    *,
    owner_scope: str | None = None,
    owner_id: str | None = None,
) -> list[dict[str, Any]]:
    if (owner_scope is None) != (owner_id is None):
        raise ValueError("private_fact_owner_incomplete")
    if isinstance(knowledge, list):
        facts = [dict(item) for item in knowledge if isinstance(item, dict)]
    elif isinstance(knowledge, dict):
        facts = []
        for fact_type, payload in knowledge.items():
            if fact_type == "known_investigations" and isinstance(payload, list):
                facts.extend(dict(item) for item in payload if isinstance(item, dict))
                continue
            facts.append({"fact_type": fact_type, "payload": payload})
    else:
        return []
    if owner_scope is not None and owner_id is not None:
        for fact in facts:
            fact.setdefault("owner_scope", owner_scope)
            fact.setdefault("owner_id", owner_id)
    return facts


_INTERNAL_MODEL_FAILURE_AUDIT_KEYS = frozenset(
    {
        "failure_episode_id",
        "source_failure_episode_ids",
        "failed_failure_episode_ids",
        "canceled_failure_episode_ids",
        "technical_outcome_record_seq",
        "failure_episode_disposition",
        "model_generation_policy_contract_status",
        "model_generation_policy_schema_version",
        "model_generation_policy_classification_version",
        "model_generation_policy_enforcement",
        "model_generation_policy_profile",
        "model_generation_policy_profile_source",
        "model_generation_policy_reasoning_parameter_mode",
        "reasoning_only_timeout_ms",
        "timeout_max_attempts",
        "reasoning_only_elapsed_ms",
        "shadow_would_timeout",
    }
)


def _without_internal_model_failure_audit(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _without_internal_model_failure_audit(item)
            for key, item in value.items()
            if key not in _INTERNAL_MODEL_FAILURE_AUDIT_KEYS
        }
    if isinstance(value, list):
        return [_without_internal_model_failure_audit(item) for item in value]
    if isinstance(value, tuple):
        return [_without_internal_model_failure_audit(item) for item in value]
    return value


def _project_public_history(
    history: Iterable[Any],
    *,
    players: tuple[ModelPlayerReference, ...],
    include_technical_speech_skips: bool = False,
) -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
]:
    statements: list[dict[str, Any]] = []
    vote_snapshots: list[dict[str, Any]] = []
    public_events: list[dict[str, Any]] = []
    has_presented_player_speech = any(
        isinstance(item, dict) and item.get("event_type") == "public_player_speech_presented"
        for item in history
    )
    latest_round = 1
    for history_index, raw_item in enumerate(history, start=1):
        if not isinstance(raw_item, dict):
            continue
        event_type = raw_item.get("event_type")
        payload = _without_internal_model_failure_audit(raw_item.get("payload"))
        if not isinstance(event_type, str) or not isinstance(payload, dict):
            continue
        source_event_id = _source_id(raw_item.get("source_event_id"))
        if source_event_id is None:
            source_event_id = f"history_{history_index}"
        record_seq = raw_item.get("record_seq")
        sequenced_source = {
            "source_event_id": source_event_id,
            **(
                {"record_seq": record_seq}
                if isinstance(record_seq, int) and not isinstance(record_seq, bool)
                else {}
            ),
        }
        statement_source = {
            "source_kind": "speaker_statement",
            **(
                {"uttered_record_seq": record_seq}
                if isinstance(record_seq, int) and not isinstance(record_seq, bool)
                else {}
            ),
        }
        round_no = payload.get("round_no")
        if isinstance(round_no, int) and round_no > 0:
            latest_round = round_no
        projected_payload = _project_value(payload, players=players)
        if event_type == "action_skipped_technical":
            if not include_technical_speech_skips:
                continue
            public_events.append(
                {
                    "kind": "speech_turn_skipped_technical",
                    "authority": "judge_fact",
                    **sequenced_source,
                    "occurred_in": {"period": "day", "round_no": latest_round},
                    "speaker_ref": projected_payload.get("actor_id"),
                    "action_type": projected_payload.get("action_type"),
                    "stage": projected_payload.get("action_type"),
                    "reason": "technical_failure",
                }
            )
            continue
        if event_type == "public_player_speech_presented":
            statement = {
                "kind": "player_statement",
                "source_event_id": source_event_id,
                "occurred_in": {"period": "day", "round_no": latest_round},
                "stage": projected_payload.get("stage"),
                "speaker_ref": projected_payload.get("player_id"),
                "speech": projected_payload.get("speech"),
                **statement_source,
            }
            statements.append(statement)
            public_events.append(
                {
                    "kind": "player_statement",
                    "authority": "player_claim_unverified",
                    **sequenced_source,
                    "occurred_in": statement["occurred_in"],
                    "stage": statement["stage"],
                    "speaker_ref": statement["speaker_ref"],
                    "statement_ref": source_event_id,
                }
            )
            continue
        if event_type == "day_speech_committed":
            if not has_presented_player_speech:
                statement = {
                    "kind": "player_statement",
                    "source_event_id": source_event_id,
                    "occurred_in": {"period": "day", "round_no": latest_round},
                    "stage": projected_payload.get("stage"),
                    "speaker_ref": projected_payload.get("player_id"),
                    "speech": projected_payload.get("speech"),
                    **statement_source,
                }
                statements.append(statement)
                public_events.append(
                    {
                        "kind": "player_statement",
                        "authority": "player_claim_unverified",
                        **sequenced_source,
                        "occurred_in": statement["occurred_in"],
                        "stage": statement["stage"],
                        "speaker_ref": statement["speaker_ref"],
                        "statement_ref": source_event_id,
                    }
                )
            continue
        if event_type == "day_vote_committed":
            fact = {
                "kind": "day_vote",
                "authority": "judge_fact",
                **sequenced_source,
                "occurred_in": {"period": "day", "round_no": latest_round},
                "action_type": projected_payload.get("action_type"),
                "voter_ref": projected_payload.get("voter_player_id"),
                "target_ref": projected_payload.get("target_player_id"),
                "weight": projected_payload.get("weight"),
            }
            if projected_payload.get("technical_status") is not None:
                fact.update(
                    {
                        "technical_status": projected_payload.get("technical_status"),
                        "technical_reason": projected_payload.get("technical_reason"),
                    }
                )
            public_events.append(dict(fact))
            continue
        if event_type == "day_vote_resolved":
            vote_snapshot = {
                "kind": "vote_result",
                "authority": "judge_fact",
                **sequenced_source,
                "occurred_in": {"period": "day", "round_no": latest_round},
                "action_type": projected_payload.get("action_type"),
                "eligible_voter_refs": projected_payload.get("eligible_voter_ids", []),
                "ineligible_voter_refs": projected_payload.get("ineligible_voter_ids", []),
                "candidate_refs": projected_payload.get("candidate_player_ids", []),
                "weighted": projected_payload.get("weighted"),
                "sheriff_ref": projected_payload.get("sheriff_player_id"),
                "sheriff_vote_weight": projected_payload.get("sheriff_vote_weight"),
                "voter_weights": projected_payload.get("voter_weights", {}),
                "totals": projected_payload.get("totals", {}),
                "leader_refs": projected_payload.get("leaders", []),
                "identity_reveal": "none",
            }
            if "technical_abstentions" in projected_payload:
                vote_snapshot["technical_abstentions"] = projected_payload["technical_abstentions"]
            vote_snapshots.append(vote_snapshot)
            public_events.append(dict(vote_snapshot))
            continue
        if event_type == "dawn_public_result":
            eliminated = projected_payload.get("dead_player_ids")
            eliminated_refs = eliminated if isinstance(eliminated, list) else []
            fact = {
                "kind": "night_result",
                "authority": "judge_fact",
                **sequenced_source,
                "occurred_in": {"period": "night", "round_no": latest_round},
                "announced_in": {"period": "dawn", "round_no": latest_round},
                "outcome": "deaths" if eliminated_refs else "peaceful",
                "eliminated_player_refs": eliminated_refs,
                "role_revealed": False,
                "known_role": None,
                "identity_reveal": "none",
            }
            public_events.append(dict(fact))
            continue
        if event_type == "player_exiled":
            fact = {
                "kind": "player_eliminated",
                "authority": "judge_fact",
                **sequenced_source,
                "occurred_in": {"period": "day", "round_no": latest_round},
                "public_reason": "exile",
                "player_ref": projected_payload.get("player_id"),
                "role_revealed": False,
                "known_role": None,
                "identity_reveal": "none",
            }
            public_events.append(dict(fact))
            continue
        if event_type == "idiot_revealed":
            fact = {
                "kind": "role_revealed",
                "authority": "judge_fact",
                **sequenced_source,
                "occurred_in": {"period": "day", "round_no": latest_round},
                "player_ref": projected_payload.get("player_id"),
                "role_revealed": True,
                "known_role": "idiot",
                "survived": bool(projected_payload.get("survived")),
            }
            public_events.append(dict(fact))
            continue
        if event_type == "werewolf_self_exploded":
            fact = {
                "kind": "player_eliminated",
                "authority": "judge_fact",
                **sequenced_source,
                "occurred_in": {"period": "day", "round_no": latest_round},
                "public_reason": "self_explosion",
                "player_ref": projected_payload.get("player_id"),
                "stage": projected_payload.get("stage"),
                "role_revealed": True,
                "known_role": "werewolf",
                "identity_reveal": "werewolf_confirmed",
            }
            public_events.append(dict(fact))
            continue
        if event_type == "hunter_response_resolved":
            hunter_ref = projected_payload.get("hunter_player_id")
            target_ref = projected_payload.get("target_player_id")
            fact = {
                "kind": "hunter_response",
                "authority": "judge_fact",
                **sequenced_source,
                "occurred_in": {
                    "period": projected_payload.get("period") or "day",
                    "round_no": latest_round,
                },
                "hunter_ref": hunter_ref,
                "target_ref": target_ref,
                "hunter_role_revealed": target_ref is not None,
                "target_role_revealed": False,
                "target_known_role": None,
            }
            public_events.append(dict(fact))
            continue
        fact = {
            "kind": event_type,
            "authority": "judge_fact",
            **sequenced_source,
            "occurred_in": {
                "period": _public_event_period(event_type),
                "round_no": latest_round,
            },
            "payload": projected_payload,
        }
        public_events.append(dict(fact))

    if public_events and all(
        isinstance(item.get("record_seq"), int) and not isinstance(item.get("record_seq"), bool)
        for item in public_events
    ):
        public_events.sort(key=lambda item: int(item["record_seq"]))
    for timeline_index, event in enumerate(public_events, start=1):
        event["timeline_index"] = timeline_index
    return statements, vote_snapshots, public_events


def _source_id(value: Any) -> str | None:
    if isinstance(value, str) and value:
        return value
    if isinstance(value, int) and not isinstance(value, bool):
        return str(value)
    return None


def _public_event_period(event_type: str) -> str:
    return "dawn" if event_type == "dawn_public_result" else "day"


def _project_value(
    value: Any,
    *,
    players: tuple[ModelPlayerReference, ...],
) -> Any:
    if isinstance(value, dict):
        return {
            (_project_text(key, players=players) if isinstance(key, str) else key): _project_value(
                item, players=players
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_project_value(item, players=players) for item in value]
    if isinstance(value, tuple):
        return [_project_value(item, players=players) for item in value]
    if isinstance(value, str):
        return _project_text(value, players=players)
    return value


def _project_text(
    value: str,
    *,
    players: tuple[ModelPlayerReference, ...],
) -> str:
    projected = value
    for player in sorted(players, key=lambda item: len(item.player_id), reverse=True):
        projected = projected.replace(player.player_id, player.ref)
    for player in sorted(players, key=lambda item: len(item.display_name), reverse=True):
        if player.display_name:
            projected = projected.replace(player.display_name, player.label)
    return projected
