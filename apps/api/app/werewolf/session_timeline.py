from __future__ import annotations

import copy
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal


TERMINAL_EVENT_TYPES = frozenset(
    {"game_completed", "game_failed", "game_canceled"}
)
RESUME_INTERNAL_EVENT_TYPES = frozenset(
    {"run_created", "run_started", "run_recovered", "run_stop_requested"}
)


@dataclass(frozen=True)
class TimelineRun:
    run_id: str
    created_at: str
    attempt_no: int
    parent_run_id: str | None = None
    resume_from_round: int | None = None


@dataclass(frozen=True)
class SessionTimelineEvent:
    id: int
    source_run_id: str
    source_event_id: int
    type: str
    session_id: str
    created_at: str
    round: int | None
    phase: str | None
    actor: str | None
    action: str | None
    payload: dict[str, Any]
    audience: str | None = None
    projection_version: int | None = None

    def to_dict(self, *, run_id: str) -> dict[str, Any]:
        return {
            "id": self.id,
            "source_run_id": self.source_run_id,
            "source_event_id": self.source_event_id,
            "type": self.type,
            "run_id": run_id,
            "session_id": self.session_id,
            "created_at": self.created_at,
            "audience": self.audience,
            "projection_version": self.projection_version,
            "timeline_version": "session-timeline-v1",
            "round": self.round,
            "phase": self.phase,
            "actor": self.actor,
            "action": self.action,
            "payload": copy.deepcopy(self.payload),
        }


@dataclass(frozen=True)
class SessionTimeline:
    session_id: str
    current_run_id: str
    current_run_start_event_id: int
    latest_event_id: int
    events: tuple[SessionTimelineEvent, ...]
    version: Literal["session-timeline-v1"] = "session-timeline-v1"

    def source_to_timeline_ids(self) -> dict[tuple[str, int], int]:
        return {
            (event.source_run_id, event.source_event_id): event.id
            for event in self.events
        }


def build_session_timeline(
    *,
    session_id: str,
    runs: Sequence[TimelineRun],
    projected_events_by_run: Mapping[str, Sequence[Mapping[str, Any]]],
) -> SessionTimeline:
    ordered_runs = sorted(
        runs,
        key=lambda run: (run.attempt_no, run.created_at, run.run_id),
    )
    if not ordered_runs:
        return SessionTimeline(
            session_id=session_id,
            current_run_id="",
            current_run_start_event_id=0,
            latest_event_id=0,
            events=(),
        )

    folded: list[dict[str, Any]] = []
    for index, run in enumerate(ordered_runs):
        source_events = sorted(
            projected_events_by_run.get(run.run_id, ()),
            key=lambda event: int(event.get("id") or 0),
        )
        resume_from_round = _resume_from_round(run, source_events) if index else None
        if resume_from_round is not None:
            folded = [
                event
                for event in folded
                if event.get("type") not in TERMINAL_EVENT_TYPES
                and not _event_is_replaced_round(event, resume_from_round)
            ]

        for source_event in source_events:
            event = copy.deepcopy(dict(source_event))
            event_type = str(event.get("type") or "")
            round_number = event.get("round")
            if index > 0:
                if event_type in RESUME_INTERNAL_EVENT_TYPES:
                    continue
                if (
                    isinstance(round_number, int)
                    and resume_from_round is not None
                    and round_number < resume_from_round
                ):
                    continue
                if event_type == "game_started":
                    event_type = "game_resumed"
                    event["type"] = event_type
                if event_type == "game_resumed":
                    payload = copy.deepcopy(event.get("payload") or {})
                    payload.update(
                        {
                            "parent_run_id": run.parent_run_id,
                            "resume_from_round": resume_from_round,
                            "attempt_no": run.attempt_no,
                        }
                    )
                    event["payload"] = payload
            folded.append(event)

    current_run_id = ordered_runs[-1].run_id
    timeline_events: list[SessionTimelineEvent] = []
    current_run_start_event_id = 0
    seen_game_started = False
    seen_resume_sources: set[str] = set()
    for event in folded:
        event_type = str(event.get("type") or "")
        source_run_id = str(event.get("run_id") or "")
        if event_type == "game_started":
            if seen_game_started:
                event_type = "game_resumed"
            seen_game_started = True
        if event_type == "game_resumed":
            if source_run_id in seen_resume_sources:
                continue
            seen_resume_sources.add(source_run_id)
        source_event_id = int(event.get("source_event_id") or event.get("id") or 0)
        timeline_event = SessionTimelineEvent(
            id=len(timeline_events) + 1,
            source_run_id=source_run_id,
            source_event_id=source_event_id,
            type=event_type,
            session_id=session_id,
            created_at=str(event.get("created_at") or ""),
            audience=(str(event["audience"]) if event.get("audience") else None),
            projection_version=(
                int(event["projection_version"])
                if isinstance(event.get("projection_version"), int)
                else None
            ),
            round=event.get("round") if isinstance(event.get("round"), int) else None,
            phase=str(event["phase"]) if event.get("phase") is not None else None,
            actor=str(event["actor"]) if event.get("actor") is not None else None,
            action=str(event["action"]) if event.get("action") is not None else None,
            payload=copy.deepcopy(event.get("payload") or {}),
        )
        timeline_events.append(timeline_event)
        if source_run_id == current_run_id and current_run_start_event_id == 0:
            current_run_start_event_id = timeline_event.id

    return SessionTimeline(
        session_id=session_id,
        current_run_id=current_run_id,
        current_run_start_event_id=current_run_start_event_id,
        latest_event_id=len(timeline_events),
        events=tuple(timeline_events),
    )


def _resume_from_round(
    run: TimelineRun,
    events: Sequence[Mapping[str, Any]],
) -> int:
    if run.resume_from_round is not None and run.resume_from_round > 0:
        return run.resume_from_round
    event_rounds = [
        round_number
        for event in events
        if isinstance((round_number := event.get("round")), int) and round_number > 0
    ]
    return min(event_rounds, default=1)


def _event_is_replaced_round(event: Mapping[str, Any], resume_from_round: int) -> bool:
    round_number = event.get("round")
    return isinstance(round_number, int) and round_number >= resume_from_round
