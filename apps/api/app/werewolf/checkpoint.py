from __future__ import annotations

import copy
import json
import random
import re
import threading
from collections.abc import Mapping
from typing import Any, Literal

from app.rule_sets.telemetry import record_rule_checkpoint_failure
from app.rule_sets.types import CompiledRuleSet
from app.werewolf.actor_mind import ActorMindV1
from app.werewolf.lm import (
    LmLog,
    ModelProvider,
    parse_json_object,
    safe_attempt_outcomes,
)
from app.werewolf.models import (
    ActionLog,
    DebateEntry,
    DeathEvent,
    GameState,
    GameView,
    Player,
    PublicOutcomeEventV1,
    RoundLog,
    RoundState,
    SheriffBadgeResolution,
    SheriffElectionResolution,
    StageInterruption,
)
from app.werewolf.public_facts import public_fact_dicts_from_value
from app.werewolf.public_outcomes import (
    conservative_legacy_outcomes,
    public_outcome_event_from_dict,
)

RESUME_CHECKPOINT_FILE = "resume_checkpoint.json"
CHECKPOINT_SCHEMA_VERSION = 3
SUPPORTED_CHECKPOINT_SCHEMA_VERSIONS = frozenset({1, 2, 3})
LIFECYCLE_LEDGER_SCHEMA_VERSION = 1
LIFECYCLE_EVENT_KINDS = frozenset({"phase_started", "phase_completed"})
TERMINAL_SETTLEMENT_SCHEMA_VERSION = "settlement_v1"
TERMINAL_SETTLEMENT_STAGES = frozenset(
    {
        "outcome_applied",
        "hunter_choice_accepted",
        "candidate_cleared",
        "winner_committed",
    }
)
TERMINAL_SETTLEMENT_STATUSES = frozenset(
    {"pending", "choice_accepted", "applied"}
)
TERMINAL_HUNTER_PRESENTATION_KIND = "hunter_shot_result"
TERMINAL_HUNTER_PRESENTATION_STATUSES = frozenset({"shot", "skipped"})
NO_HUNTER_SHOT_CHOICE = "不发动技能"
_TERMINAL_HUNTER_PRESENTATION_ID_PATTERN = re.compile(r"hp_[0-9a-f]{24}")
_TERMINAL_PRIMARY_PRESENTATION_ID_PATTERN = re.compile(r"pp_[0-9a-f]{24}")
_PHASE_INSTANCE_ID_PATTERN = re.compile(
    r"phase:r(?P<round>[1-9][0-9]*):(?P<phase>[a-z][a-z0-9_]*):(?P<occurrence>[1-9][0-9]*)"
)
TERMINAL_PRIMARY_PRESENTATION_KINDS = frozenset(
    {"exile_result", "night_result", "self_explosion_result"}
)
TERMINAL_CONTINUATION_KINDS = frozenset(
    {"day_exile_aftermath", "night_death_aftermath", "none"}
)
_CONTENT_HASH_PATTERN = re.compile(r"[0-9a-f]{64}")
_EXECUTION_RUN_PARAM_NAMES = (
    "villager_model",
    "werewolf_model",
    "seed",
    "max_rounds",
    "player_configs",
)
_OPTIONAL_LIVENESS_RUN_PARAM_NAMES = (
    "liveness_experience_snapshot",
)
_DUPLICATE_RULE_PARAM_NAMES = (
    "revision_id",
    "revision_no",
    "content_hash",
    "rule_set_snapshot",
)
_CHECKPOINT_ERROR_MESSAGES = {
    "missing": "Resume checkpoint is missing",
    "unsupported_schema": "Resume checkpoint schema is unsupported",
    "invalid_structure": "Resume checkpoint structure is invalid",
    "invalid_rule_snapshot": "Resume checkpoint rule snapshot is invalid",
    "rule_snapshot_mismatch": "Resume checkpoint rule snapshots disagree",
    "rule_metadata_mismatch": "Resume checkpoint rule metadata disagrees",
}


class ResumeCheckpointError(Exception):
    """Raised when a resume checkpoint cannot be read."""

    def __init__(self, reason: str = "invalid_structure") -> None:
        bounded_reason = reason if reason in _CHECKPOINT_ERROR_MESSAGES else "invalid_structure"
        super().__init__(_CHECKPOINT_ERROR_MESSAGES[bounded_reason])
        self.reason = bounded_reason
        self._telemetry_recorded = False


def report_resume_checkpoint_error(error: ResumeCheckpointError) -> None:
    """Record a checkpoint error once when it crosses a real failure boundary."""
    if error._telemetry_recorded:
        return
    error._telemetry_recorded = True
    record_rule_checkpoint_failure(error.reason)


def resolved_rule_set_from_checkpoint(
    checkpoint: Mapping[str, object],
) -> CompiledRuleSet:
    try:
        return _resolved_rule_set_from_checkpoint(checkpoint)
    except ResumeCheckpointError as error:
        report_resume_checkpoint_error(error)
        raise


def _resolved_rule_set_from_checkpoint(
    checkpoint: Mapping[str, object],
) -> CompiledRuleSet:
    if not isinstance(checkpoint, Mapping):
        raise ResumeCheckpointError("invalid_structure")
    if "schema_version" not in checkpoint:
        raise ResumeCheckpointError("invalid_structure")
    schema_version = checkpoint.get("schema_version")
    if type(schema_version) is not int:
        raise ResumeCheckpointError("invalid_structure")
    if schema_version not in SUPPORTED_CHECKPOINT_SCHEMA_VERSIONS:
        raise ResumeCheckpointError("unsupported_schema")
    state = checkpoint.get("state_at_round_start")
    run_params = checkpoint.get("run_params")
    if not isinstance(state, Mapping) or not isinstance(run_params, Mapping):
        raise ResumeCheckpointError("invalid_structure")
    state_snapshot = state.get("rule_set")
    if not isinstance(state_snapshot, Mapping):
        raise ResumeCheckpointError("invalid_structure")
    state_compiled = _resolve_checkpoint_rule_snapshot(state_snapshot)

    rule_set_id = run_params.get("rule_set_id")
    if type(rule_set_id) is not str or not rule_set_id or rule_set_id.strip() != rule_set_id:
        raise ResumeCheckpointError("rule_metadata_mismatch")

    present_duplicate_fields = {name for name in _DUPLICATE_RULE_PARAM_NAMES if name in run_params}
    if schema_version == 1:
        if present_duplicate_fields and present_duplicate_fields != set(
            _DUPLICATE_RULE_PARAM_NAMES
        ):
            raise ResumeCheckpointError("rule_metadata_mismatch")
        compiled = state_compiled
        if present_duplicate_fields:
            run_compiled = _resolve_checkpoint_rule_snapshot(
                _mapping_value(run_params, "rule_set_snapshot")
            )
            if run_compiled.snapshot != state_compiled.snapshot:
                raise ResumeCheckpointError("rule_snapshot_mismatch")
            _require_checkpoint_rule_metadata(run_params, state_compiled)
    else:
        if present_duplicate_fields != set(_DUPLICATE_RULE_PARAM_NAMES):
            raise ResumeCheckpointError("rule_metadata_mismatch")
        compiled = _resolve_checkpoint_rule_snapshot(
            _mapping_value(run_params, "rule_set_snapshot")
        )
        if compiled.snapshot != state_compiled.snapshot:
            raise ResumeCheckpointError("rule_snapshot_mismatch")
        _require_checkpoint_rule_metadata(run_params, compiled)

    if rule_set_id != compiled.rule_set.id:
        raise ResumeCheckpointError("rule_metadata_mismatch")
    return compiled


def _mapping_value(mapping: Mapping[str, object], name: str) -> Mapping[str, object]:
    value = mapping.get(name)
    if not isinstance(value, Mapping):
        raise ResumeCheckpointError("invalid_rule_snapshot")
    return value


def _resolve_checkpoint_rule_snapshot(
    snapshot: Mapping[str, object],
) -> CompiledRuleSet:
    from app.rule_sets.snapshots import resolve_rule_set_snapshot

    try:
        compiled = resolve_rule_set_snapshot(snapshot)
    except ResumeCheckpointError:
        raise
    except Exception:
        raise ResumeCheckpointError("invalid_rule_snapshot") from None
    if compiled.revision_id is not None and compiled.revision_id.strip() != compiled.revision_id:
        raise ResumeCheckpointError("rule_metadata_mismatch")
    return compiled


def _require_checkpoint_rule_metadata(
    run_params: Mapping[str, object],
    compiled: CompiledRuleSet,
) -> None:
    revision_id = run_params.get("revision_id")
    revision_no = run_params.get("revision_no")
    content_hash = run_params.get("content_hash")
    if (
        type(content_hash) is not str
        or _CONTENT_HASH_PATTERN.fullmatch(content_hash) is None
        or content_hash != compiled.content_hash
    ):
        raise ResumeCheckpointError("rule_metadata_mismatch")
    if compiled.revision_id is None and compiled.revision_no is None:
        if revision_id is not None or revision_no is not None:
            raise ResumeCheckpointError("rule_metadata_mismatch")
        return
    if (
        type(revision_id) is not str
        or not revision_id
        or revision_id.strip() != revision_id
        or revision_id != compiled.revision_id
        or type(revision_no) is not int
        or revision_no <= 0
        or revision_no != compiled.revision_no
    ):
        raise ResumeCheckpointError("rule_metadata_mismatch")


class ReplayThenLiveProvider:
    def __init__(
        self,
        *,
        cached_model_responses: list[dict[str, Any]],
        delegate: ModelProvider,
    ) -> None:
        self._cached_model_responses = valid_cached_model_responses(
            cached_model_responses
        )
        self._delegate = delegate
        self._lock = threading.Lock()

    def complete_json(self, *, model: str, prompt: str, temperature: float) -> str:
        with self._lock:
            prompt_match_index = self._find_prompt_match(model=model, prompt=prompt)
            if prompt_match_index is not None:
                response = self._cached_model_responses.pop(prompt_match_index)
                return str(response["raw_response"])

            legacy_match_index = self._find_legacy_match()
            if legacy_match_index is not None:
                response = self._cached_model_responses.pop(legacy_match_index)
                return str(response["raw_response"])
        return self._delegate.complete_json(model=model, prompt=prompt, temperature=temperature)

    def _find_prompt_match(self, *, model: str, prompt: str) -> int | None:
        for index, response in enumerate(self._cached_model_responses):
            if response.get("model") == model and response.get("prompt") == prompt:
                return index
        return None

    def _find_legacy_match(self) -> int | None:
        for index, response in enumerate(self._cached_model_responses):
            if "prompt" not in response:
                return index
        return None


def _cached_model_response_is_structurally_valid(response: object) -> bool:
    if not isinstance(response, dict):
        return False
    raw_response = response.get("raw_response")
    if not isinstance(raw_response, str):
        return False
    try:
        parse_json_object(raw_response)
    except ValueError:
        return False
    return True


def valid_cached_model_responses(
    responses: object,
) -> list[dict[str, Any]]:
    if not isinstance(responses, list):
        return []
    return [
        copy.deepcopy(response)
        for response in responses
        if _cached_model_response_is_structurally_valid(response)
    ]


def terminal_settlement_from_checkpoint(
    checkpoint: Mapping[str, object],
) -> dict[str, Any] | None:
    """Return a validated mid-settlement snapshot, when one is present.

    The field is optional so schema-v1/v2 round-start checkpoints remain fully
    backward compatible.  A present but malformed snapshot is rejected instead
    of silently replaying the whole round and duplicating a decisive outcome.
    """

    raw = checkpoint.get("terminal_settlement")
    if raw is None:
        return None
    if not isinstance(raw, Mapping):
        raise ResumeCheckpointError("invalid_structure")
    if raw.get("settlement_schema_version") != TERMINAL_SETTLEMENT_SCHEMA_VERSION:
        raise ResumeCheckpointError("invalid_structure")
    if raw.get("stage") not in TERMINAL_SETTLEMENT_STAGES:
        raise ResumeCheckpointError("invalid_structure")
    primary_action_id = raw.get("primary_outcome_action_id")
    cursor = raw.get("settlement_cursor")
    settlements = raw.get("settlements")
    canceled_action_ids = raw.get("canceled_action_ids")
    state = raw.get("state")
    logs = raw.get("logs")
    active_players = raw.get("active_players")
    if (
        not isinstance(primary_action_id, str)
        or not primary_action_id
        or type(cursor) is not int
        or cursor < 0
        or not isinstance(settlements, list)
        or not isinstance(canceled_action_ids, list)
        or not isinstance(state, Mapping)
        or not isinstance(logs, list)
        or not isinstance(active_players, list)
        or not all(isinstance(item, str) and item for item in canceled_action_ids)
        or not all(isinstance(item, str) and item for item in active_players)
    ):
        raise ResumeCheckpointError("invalid_structure")
    if cursor > len(settlements):
        raise ResumeCheckpointError("invalid_structure")
    primary_presentation = raw.get("primary_presentation")
    _validate_terminal_primary_presentation(primary_presentation)
    _validate_terminal_primary_presentation_payload(
        raw.get("primary_presentation_payload"),
        presentation=primary_presentation,
    )
    _validate_terminal_continuation(
        raw.get("continuation"),
        stage=raw.get("stage"),
    )
    settlement_ids: set[str] = set()
    for item in settlements:
        if not isinstance(item, Mapping):
            raise ResumeCheckpointError("invalid_structure")
        settlement_id = item.get("settlement_id")
        kind = item.get("kind")
        actor = item.get("actor")
        status = item.get("status")
        if (
            not isinstance(settlement_id, str)
            or not settlement_id
            or settlement_id in settlement_ids
            or kind not in {"death_batch", "hunter_shot"}
            or (actor is not None and (not isinstance(actor, str) or not actor))
            or status not in TERMINAL_SETTLEMENT_STATUSES
        ):
            raise ResumeCheckpointError("invalid_structure")
        settlement_ids.add(settlement_id)
        if status == "choice_accepted" and "accepted_choice" not in item:
            raise ResumeCheckpointError("invalid_structure")
        presentation = item.get("presentation")
        if presentation is not None:
            _validate_terminal_hunter_presentation(
                item=item,
                kind=kind,
                status=status,
                presentation=presentation,
            )
    return copy.deepcopy(dict(raw))


def _validate_terminal_primary_presentation(presentation: object) -> None:
    if presentation is None:
        return
    if (
        not isinstance(presentation, Mapping)
        or set(presentation) != {"presentation_id", "kind"}
        or presentation.get("kind") not in TERMINAL_PRIMARY_PRESENTATION_KINDS
    ):
        raise ResumeCheckpointError("invalid_structure")
    presentation_id = presentation.get("presentation_id")
    if (
        not isinstance(presentation_id, str)
        or _TERMINAL_PRIMARY_PRESENTATION_ID_PATTERN.fullmatch(presentation_id) is None
    ):
        raise ResumeCheckpointError("invalid_structure")


def _validate_terminal_primary_presentation_payload(
    payload: object,
    *,
    presentation: object,
) -> None:
    if payload is None:
        return
    if not isinstance(payload, Mapping) or not isinstance(presentation, Mapping):
        raise ResumeCheckpointError("invalid_structure")
    kind = presentation.get("kind")
    common_keys = {
        "active_players",
        "public_outcome_events",
        "public_outcome_next_sequence",
    }
    kind_keys = {
        "exile_result": {"exiled", "day_deaths"},
        "night_result": {"night_deaths"},
        "self_explosion_result": {
            "werewolf_self_exploded",
            "day_ended_by_self_explosion",
            "day_deaths",
        },
    }.get(kind)
    active_players = payload.get("active_players")
    public_outcomes = payload.get("public_outcome_events")
    next_sequence = payload.get("public_outcome_next_sequence")
    if (
        kind_keys is None
        or set(payload) != common_keys | kind_keys
        or not isinstance(active_players, list)
        or not all(isinstance(item, str) and item for item in active_players)
        or not isinstance(public_outcomes, list)
        or not all(_valid_frozen_public_outcome(item) for item in public_outcomes)
        or type(next_sequence) is not int
        or next_sequence < 1
    ):
        raise ResumeCheckpointError("invalid_structure")
    deaths_key = "night_deaths" if kind == "night_result" else "day_deaths"
    if not _valid_frozen_primary_deaths(payload.get(deaths_key)):
        raise ResumeCheckpointError("invalid_structure")
    if kind == "exile_result" and not isinstance(payload.get("exiled"), str):
        raise ResumeCheckpointError("invalid_structure")
    if kind == "self_explosion_result" and (
        not isinstance(payload.get("werewolf_self_exploded"), str)
        or type(payload.get("day_ended_by_self_explosion")) is not bool
    ):
        raise ResumeCheckpointError("invalid_structure")


def _valid_frozen_primary_deaths(value: object) -> bool:
    return isinstance(value, list) and all(
        isinstance(item, Mapping)
        and set(item) == {"player", "cause", "source"}
        and isinstance(item.get("player"), str)
        and bool(item.get("player"))
        and isinstance(item.get("cause"), str)
        and bool(item.get("cause"))
        and item.get("cause") != "hunter_shot"
        and (item.get("source") is None or isinstance(item.get("source"), str))
        for item in value
    )


def _valid_frozen_public_outcome(value: object) -> bool:
    if not isinstance(value, Mapping):
        return False
    required = {
        "schema_version",
        "event_id",
        "sequence",
        "kind",
        "actor_player_id",
        "target_player_id",
        "outcome",
        "caused_by_event_id",
        "occurred_phase",
    }
    return (
        set(value) == required
        and value.get("schema_version") == 1
        and isinstance(value.get("event_id"), str)
        and bool(value.get("event_id"))
        and type(value.get("sequence")) is int
        and value.get("sequence", 0) > 0
        and value.get("kind") != "hunter_shot"
        and isinstance(value.get("outcome"), str)
        and isinstance(value.get("occurred_phase"), str)
    )


def _validate_terminal_continuation(
    continuation: object,
    *,
    stage: object,
) -> None:
    if continuation is None:
        if stage == "candidate_cleared":
            raise ResumeCheckpointError("invalid_structure")
        return
    if (
        not isinstance(continuation, Mapping)
        or set(continuation)
        != {
            "kind",
            "status",
            "skip_exile_last_words",
            "transfer_sheriff_badge",
        }
        or continuation.get("kind") not in TERMINAL_CONTINUATION_KINDS
        or continuation.get("status") not in {"pending", "applied"}
        or type(continuation.get("skip_exile_last_words")) is not bool
        or type(continuation.get("transfer_sheriff_badge")) is not bool
        or (
            stage == "candidate_cleared"
            and continuation.get("status") != "applied"
        )
    ):
        raise ResumeCheckpointError("invalid_structure")


def _validate_terminal_hunter_presentation(
    *,
    item: Mapping[str, object],
    kind: object,
    status: object,
    presentation: object,
) -> None:
    """Strictly validate the optional, recoverable public result envelope.

    Older settlement_v1 checkpoints predate this field and remain readable.
    Once the field is present, however, its stable identity and semantic result
    must agree with the accepted hunter choice so recovery cannot publish an
    invented or contradictory result.
    """

    if (
        kind != "hunter_shot"
        or status not in {"choice_accepted", "applied"}
        or not isinstance(presentation, Mapping)
        or set(presentation) != {
            "presentation_id",
            "kind",
            "hunter_shot_status",
            "hunter_shot",
        }
    ):
        raise ResumeCheckpointError("invalid_structure")
    presentation_id = presentation.get("presentation_id")
    presentation_kind = presentation.get("kind")
    shot_status = presentation.get("hunter_shot_status")
    shot_target = presentation.get("hunter_shot")
    accepted_choice = item.get("accepted_choice")
    if (
        not isinstance(presentation_id, str)
        or _TERMINAL_HUNTER_PRESENTATION_ID_PATTERN.fullmatch(presentation_id) is None
        or presentation_kind != TERMINAL_HUNTER_PRESENTATION_KIND
        or shot_status not in TERMINAL_HUNTER_PRESENTATION_STATUSES
    ):
        raise ResumeCheckpointError("invalid_structure")
    if shot_status == "skipped":
        if shot_target is not None or accepted_choice != NO_HUNTER_SHOT_CHOICE:
            raise ResumeCheckpointError("invalid_structure")
        return
    if (
        not isinstance(shot_target, str)
        or not shot_target
        or shot_target == NO_HUNTER_SHOT_CHOICE
        or accepted_choice != shot_target
    ):
        raise ResumeCheckpointError("invalid_structure")


def lifecycle_ledger_from_checkpoint(
    checkpoint: Mapping[str, object],
) -> dict[str, object]:
    """Return a validated, detached lifecycle ledger.

    The ledger is additive to checkpoint schema v1/v2.  Its absence means an
    old checkpoint, not an invalid checkpoint; persisted live events can
    repopulate it during recovery.
    """

    raw = checkpoint.get("lifecycle_ledger")
    if raw is None:
        return {
            "schema_version": LIFECYCLE_LEDGER_SCHEMA_VERSION,
            "events": [],
        }
    if not isinstance(raw, Mapping):
        raise ResumeCheckpointError("invalid_structure")
    if raw.get("schema_version") != LIFECYCLE_LEDGER_SCHEMA_VERSION:
        raise ResumeCheckpointError("invalid_structure")
    raw_events = raw.get("events")
    if not isinstance(raw_events, list):
        raise ResumeCheckpointError("invalid_structure")
    events = [_validated_lifecycle_event_entry(item) for item in raw_events]
    return _validated_lifecycle_ledger(events)


def lifecycle_event_entry(
    *,
    lifecycle_kind: str,
    phase_instance_id: str,
    round_number: int,
    phase: str,
    event_id: int,
    payload: Mapping[str, object],
    stream_id: str | None = None,
) -> dict[str, object]:
    return _validated_lifecycle_event_entry(
        {
            "lifecycle_kind": lifecycle_kind,
            "phase_instance_id": phase_instance_id,
            "round_number": round_number,
            "phase": phase,
            "event_id": event_id,
            "payload": copy.deepcopy(dict(payload)),
            "stream_id": stream_id,
        }
    )


def merge_lifecycle_event_entries(
    current: list[Mapping[str, object]],
    additions: list[Mapping[str, object]],
) -> dict[str, object]:
    merged: dict[tuple[str, str], dict[str, object]] = {}
    for raw in [*current, *additions]:
        entry = _validated_lifecycle_event_entry(raw)
        key = (
            str(entry["phase_instance_id"]),
            str(entry["lifecycle_kind"]),
        )
        existing = merged.get(key)
        if existing is not None and existing != entry:
            existing_without_stream = {
                name: value for name, value in existing.items() if name != "stream_id"
            }
            entry_without_stream = {
                name: value for name, value in entry.items() if name != "stream_id"
            }
            if existing_without_stream != entry_without_stream or (
                existing.get("stream_id") is not None
                and entry.get("stream_id") is not None
            ):
                raise ResumeCheckpointError("invalid_structure")
            if existing.get("stream_id") is not None:
                entry = existing
        merged[key] = entry
    return _validated_lifecycle_ledger(list(merged.values()))


def _validated_lifecycle_event_entry(
    raw: object,
) -> dict[str, object]:
    if not isinstance(raw, Mapping):
        raise ResumeCheckpointError("invalid_structure")
    lifecycle_kind = raw.get("lifecycle_kind")
    phase_instance_id = raw.get("phase_instance_id")
    round_number = raw.get("round_number")
    phase = raw.get("phase")
    event_id = raw.get("event_id")
    payload = raw.get("payload")
    stream_id = raw.get("stream_id")
    if (
        lifecycle_kind not in LIFECYCLE_EVENT_KINDS
        or type(phase_instance_id) is not str
        or type(round_number) is not int
        or round_number <= 0
        or type(phase) is not str
        or not phase
        or phase.strip() != phase
        or type(event_id) is not int
        or event_id <= 0
        or not isinstance(payload, Mapping)
        or stream_id is not None
        and (
            type(stream_id) is not str
            or not stream_id
            or stream_id.strip() != stream_id
        )
    ):
        raise ResumeCheckpointError("invalid_structure")
    match = _PHASE_INSTANCE_ID_PATTERN.fullmatch(phase_instance_id)
    if (
        match is None
        or int(match.group("round")) != round_number
        or match.group("phase") != phase
        or payload.get("phase_instance_id") != phase_instance_id
    ):
        raise ResumeCheckpointError("invalid_structure")
    if lifecycle_kind == "phase_completed":
        if (
            payload.get("completion_status")
            not in {"completed", "skipped", "canceled", "terminal"}
            or type(payload.get("completion_reason")) is not str
            or not payload.get("completion_reason")
            or payload.get("next_phase") is not None
            and type(payload.get("next_phase")) is not str
            or type(payload.get("terminal")) is not bool
            or type(payload.get("source_event_id")) is not int
            or int(payload["source_event_id"]) <= 0
        ):
            raise ResumeCheckpointError("invalid_structure")
    return {
        "lifecycle_kind": lifecycle_kind,
        "phase_instance_id": phase_instance_id,
        "round_number": round_number,
        "phase": phase,
        "event_id": event_id,
        "payload": copy.deepcopy(dict(payload)),
        "stream_id": stream_id,
    }


def _validated_lifecycle_ledger(
    events: list[dict[str, object]],
) -> dict[str, object]:
    events.sort(key=lambda item: int(item["event_id"]))
    event_ids: set[tuple[str | None, int]] = set()
    by_instance: dict[str, dict[str, dict[str, object]]] = {}
    for event in events:
        event_id = int(event["event_id"])
        scoped_event_id = (event.get("stream_id"), event_id)
        if scoped_event_id in event_ids:
            raise ResumeCheckpointError("invalid_structure")
        event_ids.add(scoped_event_id)
        phase_instance_id = str(event["phase_instance_id"])
        lifecycle_kind = str(event["lifecycle_kind"])
        instance = by_instance.setdefault(phase_instance_id, {})
        if lifecycle_kind in instance:
            raise ResumeCheckpointError("invalid_structure")
        instance[lifecycle_kind] = event

    for instance in by_instance.values():
        started = instance.get("phase_started")
        completed = instance.get("phase_completed")
        if completed is None:
            continue
        if started is None or int(started["event_id"]) >= int(completed["event_id"]):
            raise ResumeCheckpointError("invalid_structure")
        if (
            started["round_number"] != completed["round_number"]
            or started["phase"] != completed["phase"]
            or started.get("stream_id") != completed.get("stream_id")
            or completed["payload"].get("source_event_id") != started["event_id"]
        ):
            raise ResumeCheckpointError("invalid_structure")
    return {
        "schema_version": LIFECYCLE_LEDGER_SCHEMA_VERSION,
        "events": copy.deepcopy(events),
    }


class ResumeCheckpointManager:
    def __init__(
        self,
        *,
        record_store: object,
        session_id: str,
        compiled_rule_set: CompiledRuleSet,
        run_params: dict[str, Any],
        logs_prefix: list[RoundLog] | None = None,
        initial_checkpoint: Mapping[str, object] | None = None,
    ) -> None:
        self.record_store = record_store
        self.session_id = session_id
        raw_stream_id = getattr(record_store, "run_id", None)
        self.lifecycle_stream_id = (
            raw_stream_id if isinstance(raw_stream_id, str) and raw_stream_id else None
        )
        self.rule_set_snapshot = copy.deepcopy(compiled_rule_set.snapshot)
        self.run_params = {
            name: copy.deepcopy(run_params.get(name)) for name in _EXECUTION_RUN_PARAM_NAMES
        }
        self.run_params.update(
            {
                name: copy.deepcopy(run_params[name])
                for name in _OPTIONAL_LIVENESS_RUN_PARAM_NAMES
                if name in run_params
            }
        )
        self.run_params.update(
            {
                "rule_set_id": compiled_rule_set.rule_set.id,
                "revision_id": compiled_rule_set.revision_id,
                "revision_no": compiled_rule_set.revision_no,
                "content_hash": compiled_rule_set.content_hash,
                "rule_set_snapshot": copy.deepcopy(self.rule_set_snapshot),
            }
        )
        self._logs_prefix = tuple(copy.deepcopy(logs_prefix or []))
        self._checkpoint = (
            copy.deepcopy(dict(initial_checkpoint))
            if initial_checkpoint is not None
            else None
        )
        self._lifecycle_ledger = lifecycle_ledger_from_checkpoint(
            initial_checkpoint or {}
        )
        self._terminal_recovery_active = bool(
            initial_checkpoint is not None
            and isinstance(initial_checkpoint.get("terminal_settlement"), Mapping)
        )
        self._terminal_recovery_logs_source: list[RoundLog] | None = None

    def start_round(
        self,
        *,
        state: GameState,
        logs: list[RoundLog],
        round_number: int,
        active_players: list[str],
        rng_state: object,
    ) -> None:
        if self._terminal_recovery_active:
            # During terminal-settlement recovery, ``logs`` is the complete
            # restored history rather than the post-resume delta used by a
            # normal round. Keep its live objects until recovery reaches the
            # next round so aftermath updates (for example sheriff badge and
            # summaries) become the durable prefix without duplicating it.
            if self._terminal_recovery_logs_source is not None:
                self._logs_prefix = tuple(
                    copy.deepcopy(self._terminal_recovery_logs_source)
                )
            self._terminal_recovery_active = False
            self._terminal_recovery_logs_source = None
        state_payload = state.to_dict()
        state_payload["rule_set"] = copy.deepcopy(self.rule_set_snapshot)
        self._checkpoint = {
            "schema_version": CHECKPOINT_SCHEMA_VERSION,
            "session_id": self.session_id,
            "run_params": copy.deepcopy(self.run_params),
            "round_number": round_number,
            "active_players": active_players.copy(),
            "rng_state": _json_safe_rng_state(rng_state),
            "state_at_round_start": state_payload,
            "logs_before_round": [
                log.to_dict() for log in (*self._logs_prefix, *logs)
            ],
            "cached_model_responses": [],
            "failed_request": None,
            "last_error": None,
            "lifecycle_ledger": copy.deepcopy(self._lifecycle_ledger),
            "private_runtime": {
                "actor_minds_at_round_start": {},
                "actor_minds": {},
            },
            "generation_runtime": {"speech_turn_receipts": {}},
        }
        self._save()

    def actor_minds(self) -> dict[str, ActorMindV1]:
        if self._checkpoint is None:
            return {}
        runtime = self._checkpoint.get("private_runtime")
        if not isinstance(runtime, Mapping):
            return {}
        payload = runtime.get("actor_minds")
        if not isinstance(payload, Mapping):
            return {}
        result: dict[str, ActorMindV1] = {}
        for actor, value in payload.items():
            if not isinstance(actor, str) or not actor:
                raise ResumeCheckpointError("invalid_structure")
            try:
                result[actor] = ActorMindV1.from_dict(value, actor=actor)
            except ValueError as exc:
                raise ResumeCheckpointError("invalid_structure") from exc
        return result

    def record_actor_minds(
        self,
        minds: Mapping[str, ActorMindV1],
        *,
        at_round_start: bool = False,
    ) -> None:
        if self._checkpoint is None:
            return
        runtime = self._checkpoint.setdefault("private_runtime", {})
        if not isinstance(runtime, dict):
            raise ResumeCheckpointError("invalid_structure")
        payload = {
            actor: mind.to_dict()
            for actor, mind in sorted(minds.items())
            if actor == mind.actor
        }
        runtime["actor_minds"] = copy.deepcopy(payload)
        if at_round_start:
            runtime["actor_minds_at_round_start"] = copy.deepcopy(payload)
        self._save()

    def speech_turn_receipt(self, action_id: str) -> dict[str, Any] | None:
        if self._checkpoint is None:
            return None
        runtime = self._checkpoint.get("generation_runtime")
        if not isinstance(runtime, Mapping):
            return None
        receipts = runtime.get("speech_turn_receipts")
        if not isinstance(receipts, Mapping):
            return None
        value = receipts.get(action_id)
        return copy.deepcopy(dict(value)) if isinstance(value, Mapping) else None

    def record_speech_turn_receipt(
        self,
        action_id: str,
        receipt: Mapping[str, object],
    ) -> None:
        if self._checkpoint is None:
            return
        if not action_id or receipt.get("speech_id") is None:
            raise ResumeCheckpointError("invalid_structure")
        runtime = self._checkpoint.setdefault("generation_runtime", {})
        if not isinstance(runtime, dict):
            raise ResumeCheckpointError("invalid_structure")
        receipts = runtime.setdefault("speech_turn_receipts", {})
        if not isinstance(receipts, dict):
            raise ResumeCheckpointError("invalid_structure")
        receipts[action_id] = copy.deepcopy(dict(receipt))
        self._save()

    def lifecycle_events(self) -> list[dict[str, object]]:
        events = self._lifecycle_ledger.get("events", [])
        if not isinstance(events, list):
            raise ResumeCheckpointError("invalid_structure")
        return copy.deepcopy(events)

    def reconcile_lifecycle_events(
        self,
        events: list[Mapping[str, object]],
    ) -> None:
        current = self.lifecycle_events()
        merged = merge_lifecycle_event_entries(current, events)
        if merged == self._lifecycle_ledger:
            return
        self._lifecycle_ledger = merged
        if self._checkpoint is not None:
            self._checkpoint["lifecycle_ledger"] = copy.deepcopy(merged)
            self._save()

    def record_lifecycle_event(
        self,
        *,
        lifecycle_kind: str,
        phase_instance_id: str,
        round_number: int,
        phase: str,
        event_id: int,
        payload: Mapping[str, object],
        stream_id: str | None = None,
    ) -> None:
        entry = lifecycle_event_entry(
            lifecycle_kind=lifecycle_kind,
            phase_instance_id=phase_instance_id,
            round_number=round_number,
            phase=phase,
            event_id=event_id,
            payload=payload,
            stream_id=(stream_id if stream_id is not None else self.lifecycle_stream_id),
        )
        self.reconcile_lifecycle_events([entry])

    def record_success(
        self,
        *,
        actor: str,
        action: str,
        phase: str,
        model: str,
        raw_response: str,
        prompt: str | None = None,
        actor_minds: Mapping[str, ActorMindV1] | None = None,
        logical_action_id: str | None = None,
        speech_turn_receipt: Mapping[str, object] | None = None,
    ) -> None:
        if self._checkpoint is None:
            return
        cached_response = {
            "actor": actor,
            "action": action,
            "phase": phase,
            "model": model,
            "raw_response": raw_response,
        }
        if prompt is not None:
            cached_response["prompt"] = prompt
        if actor_minds is not None:
            runtime = self._checkpoint.setdefault("private_runtime", {})
            if not isinstance(runtime, dict):
                raise ResumeCheckpointError("invalid_structure")
            runtime["actor_minds"] = {
                actor_name: mind.to_dict()
                for actor_name, mind in sorted(actor_minds.items())
                if actor_name == mind.actor
            }
        if speech_turn_receipt is not None:
            if not logical_action_id or speech_turn_receipt.get("speech_id") is None:
                raise ResumeCheckpointError("invalid_structure")
            generation_runtime = self._checkpoint.setdefault(
                "generation_runtime",
                {},
            )
            if not isinstance(generation_runtime, dict):
                raise ResumeCheckpointError("invalid_structure")
            receipts = generation_runtime.setdefault("speech_turn_receipts", {})
            if not isinstance(receipts, dict):
                raise ResumeCheckpointError("invalid_structure")
            receipts[logical_action_id] = copy.deepcopy(dict(speech_turn_receipt))
        self._checkpoint["cached_model_responses"].append(cached_response)
        self._checkpoint["failed_request"] = None
        self._checkpoint["last_error"] = None
        self._save()

    def cached_model_response_exists(
        self,
        *,
        actor: str,
        action: str,
        phase: str,
        model: str,
        prompt: str,
    ) -> bool:
        if self._checkpoint is None:
            return False
        responses = self._checkpoint.get("cached_model_responses")
        if not isinstance(responses, list):
            return False
        return any(
            isinstance(response, Mapping)
            and response.get("actor") == actor
            and response.get("action") == action
            and response.get("phase") == phase
            and response.get("model") == model
            and (
                response.get("prompt") == prompt
                or "prompt" not in response
            )
            for response in responses
        )

    def record_failure(
        self,
        *,
        actor: str,
        action: str,
        phase: str,
        model: str,
        error: str,
    ) -> None:
        if self._checkpoint is None:
            return
        failed_request = {
            "actor": actor,
            "action": action,
            "phase": phase,
            "model": model,
            "error": error,
        }
        self._checkpoint["failed_request"] = failed_request
        self._checkpoint["last_error"] = error
        self._save()

    def record_terminal_settlement(
        self,
        *,
        state: GameState,
        logs: list[RoundLog],
        active_players: list[str],
        terminal_settlement: Mapping[str, object],
    ) -> None:
        if self._checkpoint is None:
            return
        state_payload = state.to_dict()
        state_payload["rule_set"] = copy.deepcopy(self.rule_set_snapshot)
        snapshot = copy.deepcopy(dict(terminal_settlement))
        snapshot["state"] = state_payload
        if self._terminal_recovery_active:
            # The engine temporarily points ``self.logs`` at the restored
            # complete history while settling the interrupted outcome.
            # Remember that list by reference until ``start_round`` so later
            # recovery-aftermath mutations are also carried forward.
            self._terminal_recovery_logs_source = logs
            checkpoint_logs = logs
        else:
            checkpoint_logs = [*self._logs_prefix, *logs]
        snapshot["logs"] = [log.to_dict() for log in checkpoint_logs]
        snapshot["active_players"] = active_players.copy()
        validated = terminal_settlement_from_checkpoint(
            {"terminal_settlement": snapshot}
        )
        if validated is None:
            raise ResumeCheckpointError("invalid_structure")
        self._checkpoint["terminal_settlement"] = validated
        self._checkpoint["active_players"] = active_players.copy()
        self._checkpoint["failed_request"] = None
        self._checkpoint["last_error"] = None
        self._save()

    def _save(self) -> None:
        if self._checkpoint is None:
            return
        self.record_store.save_resume_checkpoint(self.session_id, self._checkpoint)


def game_state_from_dict(data: dict[str, Any]) -> GameState:
    return GameState(
        session_id=str(data["session_id"]),
        players=[player_from_dict(player) for player in data.get("players", [])],
        rule_set=copy.deepcopy(data.get("rule_set") or {}),
        rounds=[round_state_from_dict(round_state) for round_state in data.get("rounds", [])],
        winner=str(data.get("winner") or ""),
        error_message=str(data.get("error_message") or ""),
        sheriff=data.get("sheriff"),
        sheriff_badge_lost=bool(data.get("sheriff_badge_lost", False)),
        sheriff_pre_election_bomb_count=int(data.get("sheriff_pre_election_bomb_count", 0)),
        sheriff_election_pending=bool(data.get("sheriff_election_pending", False)),
        public_facts=public_fact_dicts_from_value(
            data.get("public_facts"),
            include_details=True,
        ),
        public_fact_opportunities=copy.deepcopy(
            data.get("public_fact_opportunities", [])
        ),
        public_fact_propositions=copy.deepcopy(
            data.get("public_fact_propositions", [])
        ),
    )


def round_logs_from_dict(data: list[Any]) -> list[RoundLog]:
    return [round_log_from_dict(log) for log in data if isinstance(log, dict)]


def rng_from_json_state(data: object) -> random.Random:
    rng = random.Random()
    if data is not None:
        rng.setstate(_tupleize_rng_state(data))
    return rng


def player_from_dict(data: dict[str, Any]) -> Player:
    return Player(
        name=str(data["name"]),
        role=str(data["role"]),
        model=str(data["model"]),
        personality_id=str(data.get("personality_id") or "balanced"),
        personality=str(data.get("personality") or ""),
        appearance_id=str(data.get("appearance_id") or "default"),
        avatar_prompt=str(data.get("avatar_prompt") or ""),
        avatar_image_url=str(data.get("avatar_image_url") or ""),
        profile_id=str(data["profile_id"]) if data.get("profile_id") is not None else None,
        tts_speaker=str(data.get("tts_speaker") or ""),
        tts_dialect=str(data.get("tts_dialect") or ""),
        base_delivery_mood=str(data.get("base_delivery_mood") or "neutral"),
        base_delivery_intensity=str(
            data.get("base_delivery_intensity") or "medium"
        ),
        base_delivery_pace=str(data.get("base_delivery_pace") or "natural"),
        base_delivery_instruction=str(data.get("base_delivery_instruction") or ""),
        voice_enabled=bool(data.get("voice_enabled", True)),
        voice_config_version=max(1, int(data.get("voice_config_version") or 1)),
        tags=[str(item) for item in data.get("tags", [])],
        observations=[str(item) for item in data.get("observations", [])],
        bidding_rationale=str(data.get("bidding_rationale") or ""),
        gamestate=game_view_from_dict(data["gamestate"]) if data.get("gamestate") else None,
        known_roles={str(key): str(value) for key, value in data.get("known_roles", {}).items()},
        can_vote=bool(data.get("can_vote", True)),
        revealed_role=bool(data.get("revealed_role", False)),
        witch_antidote_available=bool(data.get("witch_antidote_available", False)),
        witch_poison_available=bool(data.get("witch_poison_available", False)),
        hunter_can_shoot=bool(data.get("hunter_can_shoot", False)),
        is_sheriff=bool(data.get("is_sheriff", False)),
    )


def game_view_from_dict(data: dict[str, Any]) -> GameView:
    return GameView(
        round_number=int(data.get("round_number", 0)),
        current_players=[str(player) for player in data.get("current_players", [])],
        debate=[debate_entry_from_dict(entry) for entry in data.get("debate", [])],
        other_wolf=data.get("other_wolf"),
        wolf_teammates=[str(player) for player in data.get("wolf_teammates", [])],
    )


def round_state_from_dict(data: dict[str, Any]) -> RoundState:
    public_outcome_events = _public_outcomes_from_round_dict(data)
    return RoundState(
        number=int(data["number"]),
        players=[str(player) for player in data.get("players", [])],
        attacked=data.get("attacked"),
        eliminated=data.get("eliminated"),
        protected=data.get("protected"),
        investigated=data.get("investigated"),
        exiled=data.get("exiled"),
        night_deaths=[death_event_from_dict(item) for item in data.get("night_deaths", [])],
        day_deaths=[death_event_from_dict(item) for item in data.get("day_deaths", [])],
        saved_by_witch=data.get("saved_by_witch"),
        poisoned=data.get("poisoned"),
        hunter_shot=data.get("hunter_shot"),
        idiot_revealed=data.get("idiot_revealed"),
        debate=[debate_entry_from_dict(entry) for entry in data.get("debate", [])],
        bids=copy.deepcopy(data.get("bids", [])),
        votes=copy.deepcopy(data.get("votes", [])),
        vote_origins=copy.deepcopy(data.get("vote_origins", {})),
        exile_pk_candidates=[str(item) for item in data.get("exile_pk_candidates", [])],
        exile_pk_speeches=copy.deepcopy(data.get("exile_pk_speeches", [])),
        exile_runoff_votes={
            str(key): str(value)
            for key, value in data.get("exile_runoff_votes", {}).items()
        },
        exile_runoff_vote_origins=copy.deepcopy(
            data.get("exile_runoff_vote_origins", {})
        ),
        exile_resolution_reason=(
            str(data["exile_resolution_reason"])
            if data.get("exile_resolution_reason") is not None
            else None
        ),
        exile_last_words=(
            {
                str(key): str(value)
                for key, value in data["exile_last_words"].items()
                if isinstance(key, str) and isinstance(value, str)
            }
            if isinstance(data.get("exile_last_words"), dict)
            else None
        ),
        summaries=copy.deepcopy(data.get("summaries", {})),
        private_summaries=copy.deepcopy(data.get("private_summaries", {})),
        public_summary=str(data.get("public_summary") or ""),
        sheriff=data.get("sheriff"),
        sheriff_candidates=[str(item) for item in data.get("sheriff_candidates", [])],
        sheriff_speech_order=[str(item) for item in data.get("sheriff_speech_order", [])],
        sheriff_speech_direction=data.get("sheriff_speech_direction"),
        sheriff_speeches=copy.deepcopy(data.get("sheriff_speeches", [])),
        sheriff_withdrawn=[str(item) for item in data.get("sheriff_withdrawn", [])],
        sheriff_final_candidates=[str(item) for item in data.get("sheriff_final_candidates", [])],
        sheriff_voters=[str(item) for item in data.get("sheriff_voters", [])],
        sheriff_votes=copy.deepcopy(data.get("sheriff_votes", {})),
        sheriff_vote_origins=copy.deepcopy(data.get("sheriff_vote_origins", {})),
        sheriff_pk_candidates=[str(item) for item in data.get("sheriff_pk_candidates", [])],
        sheriff_pk_speeches=copy.deepcopy(data.get("sheriff_pk_speeches", [])),
        sheriff_runoff_votes=copy.deepcopy(data.get("sheriff_runoff_votes", {})),
        sheriff_runoff_vote_origins=copy.deepcopy(
            data.get("sheriff_runoff_vote_origins", {})
        ),
        sheriff_elected=data.get("sheriff_elected"),
        speech_order=[str(item) for item in data.get("speech_order", [])],
        speech_order_choice=data.get("speech_order_choice"),
        vote_weights=copy.deepcopy(data.get("vote_weights", {})),
        werewolf_discussion=copy.deepcopy(data.get("werewolf_discussion", [])),
        werewolf_vote_rounds=copy.deepcopy(data.get("werewolf_vote_rounds", [])),
        sheriff_badge_target=data.get("sheriff_badge_target"),
        sheriff_badge_lost=bool(data.get("sheriff_badge_lost", False)),
        werewolf_self_exploded=data.get("werewolf_self_exploded"),
        day_ended_by_self_explosion=bool(data.get("day_ended_by_self_explosion", False)),
        interruption=stage_interruption_from_dict(data.get("interruption")),
        sheriff_pre_election_bomb_count=int(data.get("sheriff_pre_election_bomb_count", 0)),
        sheriff_election_pending=bool(data.get("sheriff_election_pending", False)),
        sheriff_badge_lost_reason=data.get("sheriff_badge_lost_reason"),
        sheriff_election_resolution=sheriff_election_resolution_from_dict(
            data.get("sheriff_election_resolution")
        ),
        sheriff_badge_resolution=sheriff_badge_resolution_from_dict(
            data.get("sheriff_badge_resolution")
        ),
        public_outcome_events=public_outcome_events,
        public_outcome_next_sequence=max(
            int(data.get("public_outcome_next_sequence") or 1),
            max(
                (event.sequence for event in public_outcome_events),
                default=0,
            )
            + 1,
        ),
        success=bool(data.get("success", False)),
    )


def _public_outcomes_from_round_dict(
    data: dict[str, Any],
) -> list[PublicOutcomeEventV1]:
    raw_events = data.get("public_outcome_events")
    if isinstance(raw_events, list):
        return [
            public_outcome_event_from_dict(item)
            for item in raw_events
            if isinstance(item, dict)
        ]
    return conservative_legacy_outcomes(data)


def sheriff_election_resolution_from_dict(
    data: object,
) -> SheriffElectionResolution | None:
    if not isinstance(data, dict):
        return None
    return SheriffElectionResolution(
        schema_version=int(data.get("schema_version", 1)),
        outcome=str(data.get("outcome") or "badge_lost"),  # type: ignore[arg-type]
        reason_code=str(data.get("reason_code") or "no_candidates"),  # type: ignore[arg-type]
        reason_text=str(data.get("reason_text") or ""),
        sheriff=str(data["sheriff"]) if data.get("sheriff") is not None else None,
        candidates=[str(item) for item in data.get("candidates", [])],
        withdrawn=[str(item) for item in data.get("withdrawn", [])],
        final_candidates=[str(item) for item in data.get("final_candidates", [])],
        voters=[str(item) for item in data.get("voters", [])],
        votes={str(key): str(value) for key, value in data.get("votes", {}).items()},
        pk_candidates=[str(item) for item in data.get("pk_candidates", [])],
        runoff_votes={
            str(key): str(value) for key, value in data.get("runoff_votes", {}).items()
        },
        badge_lost=bool(data.get("badge_lost", False)),
        election_pending=bool(data.get("election_pending", False)),
    )


def sheriff_badge_resolution_from_dict(data: object) -> SheriffBadgeResolution | None:
    if not isinstance(data, dict):
        return None
    return SheriffBadgeResolution(
        schema_version=int(data.get("schema_version", 1)),
        outcome=str(data.get("outcome") or "destroyed"),  # type: ignore[arg-type]
        from_player=str(data.get("from_player") or ""),
        to_player=str(data["to_player"]) if data.get("to_player") is not None else None,
        reason_code=str(data.get("reason_code") or "destroyed"),
    )


def stage_interruption_from_dict(data: object) -> StageInterruption | None:
    if not isinstance(data, dict):
        return None
    timing = str(data.get("timing") or "before_stage")
    if timing not in {"before_stage", "before_actor", "after_actor"}:
        timing = "before_stage"
    return StageInterruption(
        stage=str(data.get("stage") or ""),
        interrupted_by=str(data.get("interrupted_by") or ""),
        actor=str(data.get("actor") or ""),
        timing=timing,  # type: ignore[arg-type]
        last_completed_speaker=(
            str(data["last_completed_speaker"])
            if data.get("last_completed_speaker") is not None
            else None
        ),
        completed_actors=[str(item) for item in data.get("completed_actors", [])],
        pending_actors=[str(item) for item in data.get("pending_actors", [])],
    )


def round_log_from_dict(data: dict[str, Any]) -> RoundLog:
    return RoundLog(
        number=int(data["number"]),
        eliminate=optional_action_log_from_dict(data.get("eliminate")),
        protect=optional_action_log_from_dict(data.get("protect")),
        investigate=optional_action_log_from_dict(data.get("investigate")),
        witch_save=optional_action_log_from_dict(data.get("witch_save")),
        witch_poison=optional_action_log_from_dict(data.get("witch_poison")),
        hunter_shoot=optional_action_log_from_dict(data.get("hunter_shoot")),
        bid=action_log_groups_from_dict(data.get("bid", [])),
        debate=action_logs_from_dict(data.get("debate", [])),
        votes=action_log_groups_from_dict(data.get("votes", [])),
        exile_pk_speech=action_logs_from_dict(data.get("exile_pk_speech", [])),
        exile_runoff_votes=action_logs_from_dict(data.get("exile_runoff_votes", [])),
        exile_last_words=optional_action_log_from_dict(data.get("exile_last_words")),
        summaries=action_logs_from_dict(data.get("summaries", [])),
        sheriff_run=action_logs_from_dict(data.get("sheriff_run", [])),
        sheriff_speech=action_logs_from_dict(data.get("sheriff_speech", [])),
        sheriff_withdraw=action_logs_from_dict(data.get("sheriff_withdraw", [])),
        sheriff_pk_speech=action_logs_from_dict(data.get("sheriff_pk_speech", [])),
        sheriff_runoff_votes=action_logs_from_dict(data.get("sheriff_runoff_votes", [])),
        sheriff_votes=action_logs_from_dict(data.get("sheriff_votes", [])),
        speech_order=optional_action_log_from_dict(data.get("speech_order")),
        sheriff_badge=optional_action_log_from_dict(data.get("sheriff_badge")),
        werewolf_self_explosion=optional_action_log_from_dict(data.get("werewolf_self_explosion")),
        werewolf_self_explosion_decisions=action_logs_from_dict(
            data.get("werewolf_self_explosion_decisions", [])
        ),
        canceled_actions=action_logs_from_dict(data.get("canceled_actions", [])),
        werewolf_discussion=action_logs_from_dict(data.get("werewolf_discussion", [])),
        werewolf_votes=action_log_groups_from_dict(data.get("werewolf_votes", [])),
    )


def optional_action_log_from_dict(data: object) -> ActionLog | None:
    return action_log_from_dict(data) if isinstance(data, dict) else None


def action_logs_from_dict(data: object) -> list[ActionLog]:
    if not isinstance(data, list):
        return []
    return [action_log_from_dict(item) for item in data if isinstance(item, dict)]


def action_log_groups_from_dict(data: object) -> list[list[ActionLog]]:
    if not isinstance(data, list):
        return []
    return [action_logs_from_dict(group) for group in data if isinstance(group, list)]


def action_log_from_dict(data: dict[str, Any]) -> ActionLog:
    lm_log_data = data.get("lm_log", {})
    if not isinstance(lm_log_data, dict):
        lm_log_data = {}
    action = str(data.get("action") or "")
    decision_schema = (
        str(data["decision_schema"])
        if data.get("decision_schema") is not None
        else ("legacy" if action == "werewolf_self_explosion" else None)
    )
    return ActionLog(
        actor=str(data.get("actor") or ""),
        action=action,
        options=[str(item) for item in data.get("options", [])],
        choice=data.get("choice"),
        lm_log=LmLog(
            prompt=str(lm_log_data.get("prompt") or ""),
            raw_response=str(lm_log_data.get("raw_response") or ""),
            result=lm_log_data.get("result", lm_log_data.get("parsed")),
            action_id=lm_log_data.get("action_id"),
            request_id=lm_log_data.get("request_id"),
            attempt_outcomes=safe_attempt_outcomes(
                lm_log_data.get("attempt_outcomes")
            ),
            invalid_attempts=copy.deepcopy(lm_log_data.get("invalid_attempts", [])),
            raw_choice=lm_log_data.get("raw_choice"),
            choice_normalization_kind=lm_log_data.get("choice_normalization_kind"),
            liveness_timing=(
                {
                    str(key): int(value)
                    for key, value in lm_log_data.get("liveness_timing", {}).items()
                    if isinstance(key, str) and type(value) is int
                }
                if isinstance(lm_log_data.get("liveness_timing"), dict)
                else {}
            ),
            committed_speech_segments=[
                str(item)
                for item in lm_log_data.get("committed_speech_segments", [])
                if isinstance(item, str) and item
            ],
            speech_id=(
                str(lm_log_data["speech_id"])
                if isinstance(lm_log_data.get("speech_id"), str)
                and lm_log_data.get("speech_id")
                else None
            ),
            speech_turn_receipt=(
                copy.deepcopy(lm_log_data["speech_turn_receipt"])
                if isinstance(lm_log_data.get("speech_turn_receipt"), dict)
                else None
            ),
        ),
        invalid_value=data.get("invalid_value"),
        fallback_choice=data.get("fallback_choice"),
        fallback_reason=data.get("fallback_reason"),
        reason_code=(
            str(data["reason_code"]) if data.get("reason_code") is not None else None
        ),
        effective_origin=(
            str(data["effective_result"].get("origin"))
            if isinstance(data.get("effective_result"), dict)
            and data["effective_result"].get("origin")
            in {"model", "system_fallback", "state_machine", "none"}
            else None
        ),
        attempt_count=int(data.get("attempt_count") or 1),
        decision_schema=decision_schema,
        decision_audit=(
            copy.deepcopy(data["decision_audit"])
            if isinstance(data.get("decision_audit"), dict)
            else None
        ),
        raw_choice=data.get("raw_choice"),
        choice_normalization_kind=data.get("choice_normalization_kind"),
        speech_mission=copy.deepcopy(data.get("speech_mission")),
        speech_quality_report=copy.deepcopy(data.get("speech_quality_report")),
        speech_quality_attempt_count=int(data.get("speech_quality_attempt_count") or 0),
        speech_quality_retry_exhausted=bool(
            data.get("speech_quality_retry_exhausted", False)
        ),
        speech_quality_initial_codes=[
            str(item) for item in data.get("speech_quality_initial_codes", [])
        ],
        speech_quality_retry_duration_ms=max(
            0,
            int(data.get("speech_quality_retry_duration_ms") or 0),
        ),
        execution_status=_execution_status_from_dict(data),
        duration_ms=max(0, int(data.get("duration_ms") or 0)),
        budget_ms=(
            max(0, int(data["budget_ms"]))
            if data.get("budget_ms") is not None
            else None
        ),
        first_token_ms=(
            max(0, int(data["first_token_ms"]))
            if data.get("first_token_ms") is not None
            else None
        ),
        fact_prompt_coverage=(
            copy.deepcopy(data["fact_prompt_coverage"])
            if isinstance(data.get("fact_prompt_coverage"), dict)
            else None
        ),
        effective_delivery=(
            copy.deepcopy(data["effective_delivery"])
            if isinstance(data.get("effective_delivery"), dict)
            else None
        ),
        effective_context_texts=[
            str(item) for item in data.get("effective_context_texts", [])
        ],
        voice_config_version=(
            max(1, int(data["voice_config_version"]))
            if data.get("voice_config_version") is not None
            else None
        ),
        delivery_mapping_version=(
            str(data["delivery_mapping_version"])
            if data.get("delivery_mapping_version") is not None
            else None
        ),
        liveness_experience_revision=(
            str(data["liveness_experience_revision"])
            if data.get("liveness_experience_revision") is not None
            else None
        ),
        prompt_chars=(
            max(0, int(data["prompt_chars"]))
            if data.get("prompt_chars") is not None
            else None
        ),
        scene_packet_chars=(
            max(0, int(data["scene_packet_chars"]))
            if data.get("scene_packet_chars") is not None
            else None
        ),
        liveness_timing=(
            {
                str(key): int(value)
                for key, value in data.get("liveness_timing", {}).items()
                if isinstance(key, str) and type(value) is int
            }
            if isinstance(data.get("liveness_timing"), dict)
            else {}
        ),
        speech_turn_receipt=(
            copy.deepcopy(data["speech_turn_receipt"])
            if isinstance(data.get("speech_turn_receipt"), dict)
            else None
        ),
    )


def _execution_status_from_dict(
    data: dict[str, Any],
) -> Literal["completed", "timed_out", "fallback", "canceled", "failed"]:
    value = str(data.get("execution_status") or "completed")
    if value in {"completed", "timed_out", "fallback", "canceled", "failed"}:
        return value  # type: ignore[return-value]
    return "completed"


def death_event_from_dict(data: dict[str, Any]) -> DeathEvent:
    return DeathEvent(
        player=str(data.get("player") or ""),
        cause=str(data.get("cause") or ""),
        source=data.get("source"),
    )


def debate_entry_from_dict(data: dict[str, Any]) -> DebateEntry:
    return DebateEntry(
        speaker=str(data.get("speaker") or ""),
        message=str(data.get("message") or ""),
    )


def _json_safe_rng_state(state: object) -> object:
    return json.loads(json.dumps(state))


def _tupleize_rng_state(data: object) -> Any:
    if isinstance(data, list):
        return tuple(_tupleize_rng_state(item) for item in data)
    return data
