from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
import hashlib
from typing import Any, Literal


FailureEpisodeResolution = Literal[
    "automatic_retry_success",
    "technical_skip",
    "technical_false_fallback",
    "operator_pause",
    "isolated_action_failure",
    "run_failure",
    "run_canceled",
    "unresolved",
    "invariant_conflict",
]


_SOURCE_EVENT_TYPES = frozenset(
    {
        "model_request_failed",
        "model_retry_scheduled",
        "model_request_started",
        "model_response_received",
    }
)
_TECHNICAL_SUPPORT_EVENT_TYPES = frozenset(
    {"action_skipped_technical", "technical_fallback_applied"}
)
_RUN_FAILURE_EVENT_TYPES = frozenset(
    {
        "day_runtime_failed",
        "ability_runtime_failed",
        "match_runtime_failed",
        "game_phase_transition_failed",
    }
)
_PRE_PROVIDER_FAILURE_CODES = frozenset(
    {
        "model_not_configured",
        "model_parameters_invalid",
        "model_context_projection_invariant_failed",
    }
)


@dataclass(frozen=True)
class FailureEpisodeEventRef:
    event_type: str
    event_id: int | str | None
    record_seq: int


@dataclass(frozen=True)
class FailureEpisode:
    failure_episode_id: str
    game_id: str | None
    run_id: str | None
    action_id: str | None
    retry_cycle: int | None
    first_failed_attempt_id: str | None
    first_failure_record_seq: int | None
    source_attempt_ids: tuple[str, ...]
    source_event_refs: tuple[FailureEpisodeEventRef, ...]
    resolution: FailureEpisodeResolution
    resolution_event_type: str | None
    resolution_event_id: int | str | None
    resolution_event_record_seq: int | None
    supporting_event_type: str | None
    supporting_event_id: int | str | None
    supporting_event_record_seq: int | None
    terminal_event_refs: tuple[FailureEpisodeEventRef, ...]
    resolution_updated_at_record_seq: int
    invariant_errors: tuple[str, ...]

    @property
    def is_open(self) -> bool:
        return self.resolution == "unresolved"


@dataclass(frozen=True)
class _Event:
    game_id: str | None
    run_id: str | None
    event_type: str
    event_id: int | str | None
    record_seq: int
    payload: dict[str, Any]

    @property
    def ref(self) -> FailureEpisodeEventRef:
        return FailureEpisodeEventRef(
            event_type=self.event_type,
            event_id=self.event_id,
            record_seq=self.record_seq,
        )


@dataclass
class _TerminalCandidate:
    resolution: FailureEpisodeResolution
    event: _Event
    supporting_event: _Event | None = None


@dataclass
class _EpisodeBuilder:
    failure_episode_id: str
    failure_events: list[_Event] = field(default_factory=list)
    source_events: list[_Event] = field(default_factory=list)
    referenced_events: list[_Event] = field(default_factory=list)
    terminals: list[_TerminalCandidate] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def error(self, code: str) -> None:
        if code not in self.errors:
            self.errors.append(code)


def stable_failure_episode_id(
    *,
    game_id: str,
    run_id: str,
    action_id: str,
    retry_cycle: int,
    first_failed_attempt_id: str,
) -> str:
    """Return the stable v1 identifier for one continuous model-failure cycle."""

    components: tuple[str, ...] = (
        game_id,
        run_id,
        action_id,
        first_failed_attempt_id,
    )
    if any(not isinstance(value, str) or not value for value in components):
        raise ValueError("failure episode identity components must be non-empty strings")
    if not isinstance(retry_cycle, int) or isinstance(retry_cycle, bool) or retry_cycle < 1:
        raise ValueError("failure episode retry_cycle must be a positive integer")
    material = "\0".join(
        ["v1", game_id, run_id, action_id, str(retry_cycle), first_failed_attempt_id]
    ).encode("utf-8")
    return "v2_mfep_" + hashlib.sha256(material).hexdigest()[:24]


def derive_failure_episodes(events: Sequence[object]) -> tuple[FailureEpisode, ...]:
    """Derive model-failure episodes from one run's complete ordered event stream.

    This function is deliberately side-effect free. Callers that need an atomic
    terminal event must load the current run events while holding the game row
    lock, call this function, and append the terminal event in that transaction.
    """

    normalized = tuple(_normalize_event(item) for item in events)
    builders: dict[str, _EpisodeBuilder] = {}
    global_order_invalid = any(
        right.record_seq <= left.record_seq
        for left, right in zip(normalized, normalized[1:], strict=False)
    )
    run_ids = {event.run_id for event in normalized if event.run_id is not None}
    mixed_runs = len(run_ids) > 1

    for event in normalized:
        episode_id = _non_empty_string(event.payload.get("failure_episode_id"))
        if episode_id is not None:
            builder = builders.setdefault(episode_id, _EpisodeBuilder(episode_id))
            builder.referenced_events.append(event)
            if event.event_type in _SOURCE_EVENT_TYPES:
                builder.source_events.append(event)
            if event.event_type == "model_request_failed":
                builder.failure_events.append(event)

        for field_name in (
            "canceled_failure_episode_ids",
            "failed_failure_episode_ids",
        ):
            raw_ids = event.payload.get(field_name)
            if not isinstance(raw_ids, list):
                continue
            for raw_id in raw_ids:
                referenced_id = _non_empty_string(raw_id)
                if referenced_id is None:
                    continue
                builders.setdefault(
                    referenced_id, _EpisodeBuilder(referenced_id)
                ).referenced_events.append(event)

    by_record_seq = {event.record_seq: event for event in normalized}
    started_by_attempt: dict[str, list[_Event]] = {}
    for event in normalized:
        if event.event_type != "model_request_started":
            continue
        attempt_id = _non_empty_string(event.payload.get("attempt_id"))
        if attempt_id is not None:
            started_by_attempt.setdefault(attempt_id, []).append(event)

    for builder in builders.values():
        if global_order_invalid:
            builder.error("record_sequence_not_strictly_increasing")
        if mixed_runs:
            builder.error("multiple_runs_supplied")
        _validate_source_lifecycle(builder, started_by_attempt=started_by_attempt)
        _collect_terminal_candidates(
            builder,
            normalized=normalized,
            by_record_seq=by_record_seq,
        )

    return tuple(
        _finish_episode(builder)
        for builder in sorted(
            builders.values(),
            key=lambda item: (
                item.failure_events[0].record_seq if item.failure_events else 2**63,
                item.failure_episode_id,
            ),
        )
    )


def open_failure_episode_ids(events: Sequence[object]) -> tuple[str, ...]:
    """Return deterministic IDs for episodes with failure but no terminal evidence."""

    return tuple(
        sorted(
            episode.failure_episode_id
            for episode in derive_failure_episodes(events)
            if episode.is_open
        )
    )


def _validate_source_lifecycle(
    builder: _EpisodeBuilder,
    *,
    started_by_attempt: dict[str, list[_Event]],
) -> None:
    if not builder.failure_events:
        builder.error("episode_has_no_source_failure")
        return

    first = builder.failure_events[0]
    game_id = first.game_id
    run_id = first.run_id
    action_id = _non_empty_string(first.payload.get("action_id"))
    retry_cycle = _positive_int(first.payload.get("retry_cycle"))
    first_attempt_id = _non_empty_string(first.payload.get("attempt_id"))
    if None in (game_id, run_id, action_id, retry_cycle, first_attempt_id):
        builder.error("first_failure_identity_incomplete")
    else:
        expected_id = stable_failure_episode_id(
            game_id=game_id,
            run_id=run_id,
            action_id=action_id,
            retry_cycle=retry_cycle,
            first_failed_attempt_id=first_attempt_id,
        )
        if expected_id != builder.failure_episode_id:
            builder.error("failure_episode_id_mismatch")

    source_audiences: set[str] = set()
    failed_attempt_ids: list[str] = []
    scheduled_next_attempts: dict[str, str] = {}
    retry_schedule_events: dict[str, _Event] = {}

    for event in builder.source_events:
        event_action_id = _non_empty_string(event.payload.get("action_id"))
        event_cycle = _positive_int(event.payload.get("retry_cycle"))
        event_audience = _non_empty_string(event.payload.get("audience"))
        if event.game_id != game_id or event.run_id != run_id:
            builder.error("source_lifecycle_cross_run_or_game")
        if event_action_id != action_id:
            builder.error("source_lifecycle_cross_action")
        if event_cycle != retry_cycle:
            builder.error("source_lifecycle_retry_cycle_mismatch")
        if event_audience is None:
            builder.error("source_lifecycle_audience_missing")
        else:
            source_audiences.add(event_audience)

        attempt_id = _non_empty_string(event.payload.get("attempt_id"))
        if (
            event.event_type
            in {
                "model_request_failed",
                "model_request_started",
                "model_response_received",
            }
            and attempt_id is None
        ):
            builder.error("source_lifecycle_attempt_id_missing")
        if event.event_type == "model_request_failed" and attempt_id is not None:
            if attempt_id in failed_attempt_ids:
                builder.error("duplicate_failed_attempt")
            failed_attempt_ids.append(attempt_id)
        if event.event_type == "model_retry_scheduled":
            next_attempt_id = _non_empty_string(event.payload.get("next_attempt_id"))
            if attempt_id is None or next_attempt_id is None:
                builder.error("retry_lineage_incomplete")
            elif attempt_id in scheduled_next_attempts:
                builder.error("duplicate_retry_schedule")
            else:
                scheduled_next_attempts[attempt_id] = next_attempt_id
                retry_schedule_events[attempt_id] = event

    if len(source_audiences) > 1:
        builder.error("source_lifecycle_audience_drift")
    scheduled_successors: set[str] = set()
    for next_attempt_id in scheduled_next_attempts.values():
        if next_attempt_id in scheduled_successors:
            builder.error("duplicate_retry_successor")
        scheduled_successors.add(next_attempt_id)

    for index, failure in enumerate(builder.failure_events):
        attempt_id = _non_empty_string(failure.payload.get("attempt_id"))
        if attempt_id is None:
            continue
        starts = [
            event
            for event in started_by_attempt.get(attempt_id, ())
            if event.record_seq < failure.record_seq
            and event.game_id == game_id
            and event.run_id == run_id
            and _non_empty_string(event.payload.get("action_id")) == action_id
            and _positive_int(event.payload.get("retry_cycle")) == retry_cycle
        ]
        failure_code = _non_empty_string(failure.payload.get("failure_code"))
        pre_provider_failure = failure.payload.get("pre_provider_failure") is True
        if (
            not starts
            and failure_code not in _PRE_PROVIDER_FAILURE_CODES
            and not pre_provider_failure
        ):
            builder.error("physical_start_missing")
        if len(starts) > 1:
            builder.error("duplicate_physical_start")
        if starts and source_audiences:
            start_audience = _non_empty_string(starts[-1].payload.get("audience"))
            if start_audience not in source_audiences:
                builder.error("source_lifecycle_audience_drift")
        if index > 0:
            previous_attempt_id = _non_empty_string(
                builder.failure_events[index - 1].payload.get("attempt_id")
            )
            if (
                previous_attempt_id is None
                or scheduled_next_attempts.get(previous_attempt_id) != attempt_id
            ):
                builder.error("retry_lineage_discontinuous")

    failed_attempt_set = set(failed_attempt_ids)
    failure_seq_by_attempt = {
        attempt_id: event.record_seq
        for event in builder.failure_events
        for attempt_id in (_non_empty_string(event.payload.get("attempt_id")),)
        if attempt_id is not None
    }
    for source in builder.source_events:
        attempt_id = _non_empty_string(source.payload.get("attempt_id"))
        if source.event_type == "model_retry_scheduled" and attempt_id is not None:
            if attempt_id not in failed_attempt_set:
                builder.error("retry_schedule_without_failure")
            elif source.record_seq <= failure_seq_by_attempt[attempt_id]:
                builder.error("retry_schedule_precedes_failure")
        if source.event_type == "model_request_started" and attempt_id is not None:
            if source.record_seq > first.record_seq:
                predecessors = [
                    failed_attempt_id
                    for failed_attempt_id, next_attempt_id in scheduled_next_attempts.items()
                    if next_attempt_id == attempt_id
                ]
                if not predecessors:
                    builder.error("physical_start_lineage_discontinuous")
                elif any(
                    retry_schedule_events[predecessor].record_seq >= source.record_seq
                    for predecessor in predecessors
                ):
                    builder.error("physical_start_precedes_retry_schedule")
                retry_of_attempt_id = _non_empty_string(source.payload.get("retry_of_attempt_id"))
                if retry_of_attempt_id not in predecessors:
                    builder.error("physical_start_retry_of_mismatch")
        if source.event_type == "model_response_received" and attempt_id is not None:
            starts = [
                event
                for event in started_by_attempt.get(attempt_id, ())
                if event.record_seq < source.record_seq
                and event.game_id == game_id
                and event.run_id == run_id
                and _non_empty_string(event.payload.get("action_id")) == action_id
                and _positive_int(event.payload.get("retry_cycle")) == retry_cycle
            ]
            if not starts:
                builder.error("response_physical_start_missing")
            if len(starts) > 1:
                builder.error("duplicate_physical_start")
            if attempt_id in failed_attempt_set:
                builder.error("response_attempt_already_failed")
            predecessors = [
                failed_attempt_id
                for failed_attempt_id, next_attempt_id in scheduled_next_attempts.items()
                if next_attempt_id == attempt_id
            ]
            if not predecessors:
                builder.error("response_lineage_discontinuous")
            elif any(
                retry_schedule_events[predecessor].record_seq >= source.record_seq
                for predecessor in predecessors
            ):
                builder.error("response_precedes_retry_schedule")
            elif starts and any(
                retry_schedule_events[predecessor].record_seq
                >= max(event.record_seq for event in starts)
                for predecessor in predecessors
            ):
                builder.error("response_start_precedes_retry_schedule")


def _collect_terminal_candidates(
    builder: _EpisodeBuilder,
    *,
    normalized: tuple[_Event, ...],
    by_record_seq: dict[int, _Event],
) -> None:
    if not builder.failure_events:
        return
    first = builder.failure_events[0]
    action_id = _non_empty_string(first.payload.get("action_id"))
    first_seq = first.record_seq

    for event in normalized:
        payload = event.payload
        singular_id = _non_empty_string(payload.get("failure_episode_id"))
        in_canceled = builder.failure_episode_id in _string_list(
            payload.get("canceled_failure_episode_ids")
        )
        in_failed = builder.failure_episode_id in _string_list(
            payload.get("failed_failure_episode_ids")
        )
        if not (singular_id == builder.failure_episode_id or in_canceled or in_failed):
            continue
        if event.record_seq <= first_seq and event is not first:
            builder.error("episode_reference_precedes_first_failure")

        if event.event_type in _SOURCE_EVENT_TYPES:
            if event.event_type == "model_response_received":
                if payload.get("application_validation_result") != "accepted":
                    builder.error("response_terminal_not_accepted")
                elif _action_event_matches(builder, event, action_id=action_id):
                    builder.terminals.append(_TerminalCandidate("automatic_retry_success", event))
            continue

        if event.event_type in _TECHNICAL_SUPPORT_EVENT_TYPES:
            if not _action_event_matches(builder, event, action_id=action_id):
                continue
            continue

        if event.event_type == "action_succeeded" and singular_id == builder.failure_episode_id:
            if not _action_event_matches(builder, event, action_id=action_id):
                continue
            supporting_seq = _positive_int(payload.get("technical_outcome_record_seq"))
            supporting = by_record_seq.get(supporting_seq) if supporting_seq is not None else None
            if (
                supporting is None
                or supporting.event_type not in _TECHNICAL_SUPPORT_EVENT_TYPES
                or supporting.record_seq <= first_seq
                or supporting.record_seq >= event.record_seq
                or _non_empty_string(supporting.payload.get("failure_episode_id"))
                != builder.failure_episode_id
                or _non_empty_string(supporting.payload.get("action_id")) != action_id
                or supporting.game_id != first.game_id
                or supporting.run_id != first.run_id
            ):
                builder.error("technical_supporting_event_invalid")
                continue
            resolution: FailureEpisodeResolution = (
                "technical_skip"
                if supporting.event_type == "action_skipped_technical"
                else "technical_false_fallback"
            )
            builder.terminals.append(_TerminalCandidate(resolution, event, supporting))
            continue

        if event.event_type == "model_action_paused" and singular_id == builder.failure_episode_id:
            if _action_event_matches(builder, event, action_id=action_id):
                builder.terminals.append(_TerminalCandidate("operator_pause", event))
            continue

        if event.event_type == "action_failed" and (
            singular_id == builder.failure_episode_id or in_failed
        ):
            disposition = payload.get("failure_episode_disposition")
            if in_failed and disposition == "run_failure":
                if event.game_id != first.game_id or event.run_id != first.run_id:
                    builder.error("terminal_evidence_cross_run_or_game")
                else:
                    builder.terminals.append(_TerminalCandidate("run_failure", event))
            elif singular_id != builder.failure_episode_id:
                builder.error("action_failure_disposition_invalid")
            elif not _action_event_matches(builder, event, action_id=action_id):
                continue
            elif disposition == "isolated_action_failure":
                builder.terminals.append(_TerminalCandidate("isolated_action_failure", event))
            elif disposition == "run_failure":
                builder.terminals.append(_TerminalCandidate("run_failure", event))
            else:
                builder.error("action_failure_disposition_invalid")
            continue

        if event.event_type == "game_canceled" and in_canceled:
            if event.game_id != first.game_id or event.run_id != first.run_id:
                builder.error("terminal_evidence_cross_run_or_game")
            else:
                builder.terminals.append(_TerminalCandidate("run_canceled", event))
            continue

        if event.event_type in _RUN_FAILURE_EVENT_TYPES and in_failed:
            if event.game_id != first.game_id or event.run_id != first.run_id:
                builder.error("terminal_evidence_cross_run_or_game")
            elif payload.get("failure_episode_disposition") != "run_failure":
                builder.error("run_failure_disposition_invalid")
            else:
                builder.terminals.append(_TerminalCandidate("run_failure", event))

    if builder.terminals:
        terminal_seq = min(candidate.event.record_seq for candidate in builder.terminals)
        if any(
            event.record_seq > terminal_seq
            for event in builder.source_events
            if event.event_type != "model_response_received"
        ):
            builder.error("source_lifecycle_after_terminal")
    if len(builder.terminals) > 1:
        builder.error("mutually_exclusive_terminal_evidence")


def _action_event_matches(
    builder: _EpisodeBuilder,
    event: _Event,
    *,
    action_id: str | None,
) -> bool:
    first = builder.failure_events[0]
    if event.game_id != first.game_id or event.run_id != first.run_id:
        builder.error("terminal_evidence_cross_run_or_game")
        return False
    if _non_empty_string(event.payload.get("action_id")) != action_id:
        builder.error("terminal_evidence_cross_action")
        return False
    if event.record_seq <= first.record_seq:
        builder.error("terminal_evidence_not_after_failure")
        return False
    return True


def _finish_episode(builder: _EpisodeBuilder) -> FailureEpisode:
    first = builder.failure_events[0] if builder.failure_events else None
    source_attempt_ids = tuple(
        dict.fromkeys(
            attempt_id
            for event in builder.source_events
            for attempt_id in (_non_empty_string(event.payload.get("attempt_id")),)
            if attempt_id is not None
        )
    )
    terminal_refs = tuple(candidate.event.ref for candidate in builder.terminals)
    if builder.errors:
        resolution: FailureEpisodeResolution = "invariant_conflict"
        primary = builder.terminals[0] if builder.terminals else None
    elif builder.terminals:
        resolution = builder.terminals[0].resolution
        primary = builder.terminals[0]
    else:
        resolution = "unresolved"
        primary = None
    supporting = primary.supporting_event if primary is not None else None
    referenced_record_seqs = [event.record_seq for event in builder.referenced_events]
    resolution_updated_at = max(
        referenced_record_seqs or ([first.record_seq] if first is not None else [0])
    )
    return FailureEpisode(
        failure_episode_id=builder.failure_episode_id,
        game_id=first.game_id if first is not None else None,
        run_id=first.run_id if first is not None else None,
        action_id=(
            _non_empty_string(first.payload.get("action_id")) if first is not None else None
        ),
        retry_cycle=(
            _positive_int(first.payload.get("retry_cycle")) if first is not None else None
        ),
        first_failed_attempt_id=(
            _non_empty_string(first.payload.get("attempt_id")) if first is not None else None
        ),
        first_failure_record_seq=first.record_seq if first is not None else None,
        source_attempt_ids=source_attempt_ids,
        source_event_refs=tuple(event.ref for event in builder.source_events),
        resolution=resolution,
        resolution_event_type=(primary.event.event_type if primary is not None else None),
        resolution_event_id=(primary.event.event_id if primary is not None else None),
        resolution_event_record_seq=(primary.event.record_seq if primary is not None else None),
        supporting_event_type=(supporting.event_type if supporting is not None else None),
        supporting_event_id=(supporting.event_id if supporting is not None else None),
        supporting_event_record_seq=(supporting.record_seq if supporting is not None else None),
        terminal_event_refs=terminal_refs,
        resolution_updated_at_record_seq=resolution_updated_at,
        invariant_errors=tuple(builder.errors),
    )


def _normalize_event(value: object) -> _Event:
    payload = _field(value, "payload")
    normalized_payload = dict(payload) if isinstance(payload, dict) else {}
    # The current durable V2 contract stores audience inside canonical payload.
    # Accept a top-level value as a read-only compatibility fallback for
    # synthetic/exported event shapes without changing persisted events.
    if "audience" not in normalized_payload:
        top_level_audience = _non_empty_string(_field(value, "audience"))
        if top_level_audience is not None:
            normalized_payload["audience"] = top_level_audience
    record_seq = _field(value, "record_seq")
    if not isinstance(record_seq, int) or isinstance(record_seq, bool):
        raise ValueError("failure episode events require integer record_seq")
    event_type = _field(value, "event_type")
    if not isinstance(event_type, str) or not event_type:
        raise ValueError("failure episode events require event_type")
    event_id = _field(value, "event_id")
    if not isinstance(event_id, (int, str)) or isinstance(event_id, bool):
        event_id = None
    return _Event(
        game_id=_non_empty_string(_field(value, "game_id")),
        run_id=_non_empty_string(_field(value, "run_id")),
        event_type=event_type,
        event_id=event_id,
        record_seq=record_seq,
        payload=normalized_payload,
    )


def _field(value: object, name: str) -> object:
    if isinstance(value, dict):
        return value.get(name)
    return getattr(value, name, None)


def _non_empty_string(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _positive_int(value: object) -> int | None:
    if isinstance(value, int) and not isinstance(value, bool) and value > 0:
        return value
    return None


def _string_list(value: object) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(item for item in value if isinstance(item, str) and item)
