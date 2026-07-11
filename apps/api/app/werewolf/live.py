from __future__ import annotations

import json
import logging
import queue
import threading
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal, Protocol

from app.werewolf.player_configs import PlayerConfig
from app.werewolf.rules import DEFAULT_RULE_SET_ID, get_rule_set, rule_set_snapshot

RunStatus = Literal["queued", "running", "completed", "failed", "canceled"]
logger = logging.getLogger(__name__)


class GameRunCanceled(RuntimeError):
    """Raised by a live event sink when an operator requested a safe stop."""


def utc_now() -> str:
    return datetime.now(tz=UTC).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True, init=False)
class LiveEvent:
    id: int
    type: str
    run_id: str
    session_id: str
    created_at: str
    round: int | None = None
    phase: str | None = None
    actor: str | None = None
    action: str | None = None
    _payload: dict[str, Any] = field(default_factory=dict, repr=False)

    def __init__(
        self,
        *,
        id: int,
        type: str,
        run_id: str,
        session_id: str,
        created_at: str,
        round: int | None = None,
        phase: str | None = None,
        actor: str | None = None,
        action: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> None:
        object.__setattr__(self, "id", id)
        object.__setattr__(self, "type", type)
        object.__setattr__(self, "run_id", run_id)
        object.__setattr__(self, "session_id", session_id)
        object.__setattr__(self, "created_at", created_at)
        object.__setattr__(self, "round", round)
        object.__setattr__(self, "phase", phase)
        object.__setattr__(self, "actor", actor)
        object.__setattr__(self, "action", action)
        object.__setattr__(self, "_payload", _copy_json_payload(payload or {}))

    @property
    def payload(self) -> dict[str, Any]:
        return _copy_json_payload(self._payload)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "type": self.type,
            "run_id": self.run_id,
            "session_id": self.session_id,
            "created_at": self.created_at,
            "round": self.round,
            "phase": self.phase,
            "actor": self.actor,
            "action": self.action,
            "payload": self.payload,
        }


@dataclass
class LiveGameRun:
    run_id: str
    session_id: str
    villager_model: str
    werewolf_model: str
    seed: int | None
    max_rounds: int
    rule_set_id: str = DEFAULT_RULE_SET_ID
    rule_set: dict[str, Any] = field(
        default_factory=lambda: rule_set_snapshot(get_rule_set(DEFAULT_RULE_SET_ID))
    )
    player_configs: list[dict[str, Any]] = field(default_factory=list)
    lineup_quality_warnings: list[dict[str, str]] = field(default_factory=list)
    status: RunStatus = "queued"
    created_at: str = field(default_factory=utc_now)
    started_at: str | None = None
    completed_at: str | None = None
    winner: str | None = None
    error: str | None = None
    stop_requested_at: str | None = None
    events: list[LiveEvent] = field(default_factory=list)
    subscribers: list[queue.Queue[LiveEvent]] = field(default_factory=list)
    next_event_id: int = 1

    @property
    def event_count(self) -> int:
        return len(self.events)

    def to_summary(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "session_id": self.session_id,
            "villager_model": self.villager_model,
            "werewolf_model": self.werewolf_model,
            "seed": self.seed,
            "max_rounds": self.max_rounds,
            "rule_set_id": self.rule_set_id,
            "rule_set": _copy_json_payload(self.rule_set),
            "player_configs": _copy_json_payload(self.player_configs),
            "lineup_quality_warnings": _copy_json_payload(self.lineup_quality_warnings),
            "status": self.status,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "winner": self.winner,
            "error": self.error,
            "stop_requested_at": self.stop_requested_at,
            "event_count": self.event_count,
        }


class LiveStore(Protocol):
    def save_run(self, run: LiveGameRun) -> None:
        ...

    def append_event(self, event: LiveEvent) -> None:
        ...


class LiveRunRegistry:
    def __init__(self, live_store: LiveStore | None = None) -> None:
        self._runs: dict[str, LiveGameRun] = {}
        self._lock = threading.RLock()
        self._live_store = live_store

    def create_run(
        self,
        *,
        session_id: str,
        villager_model: str,
        werewolf_model: str,
        seed: int | None,
        max_rounds: int,
        rule_set_id: str = DEFAULT_RULE_SET_ID,
        rule_set: dict[str, Any] | None = None,
        player_configs: list[PlayerConfig] | None = None,
        lineup_quality_warnings: list[dict[str, str]] | None = None,
    ) -> LiveGameRun:
        rule_set_data = (
            _copy_json_payload(rule_set)
            if rule_set is not None
            else rule_set_snapshot(get_rule_set(rule_set_id))
        )
        player_config_data = [config.to_dict() for config in player_configs or []]
        lineup_warning_data = _copy_json_payload(lineup_quality_warnings or [])
        with self._lock:
            run = LiveGameRun(
                run_id=f"run_{uuid.uuid4().hex[:12]}",
                session_id=session_id,
                villager_model=villager_model,
                werewolf_model=werewolf_model,
                seed=seed,
                max_rounds=max_rounds,
                rule_set_id=rule_set_id,
                rule_set=rule_set_data,
                player_configs=player_config_data,
                lineup_quality_warnings=lineup_warning_data,
            )
            self._runs[run.run_id] = run
            self._persist_run_locked(run)
            self._publish_locked(
                run,
                "run_created",
                payload={
                    "session_id": session_id,
                    "villager_model": villager_model,
                    "werewolf_model": werewolf_model,
                    "seed": seed,
                    "max_rounds": max_rounds,
                    "rule_set_id": rule_set_id,
                    "rule_set": rule_set_data,
                    "player_configs": player_config_data,
                    "lineup_quality_warnings": lineup_warning_data,
                },
            )
            return run

    def try_get_active_run_for_session(self, session_id: str) -> LiveGameRun | None:
        with self._lock:
            return self._active_run_for_session_locked(session_id)

    def get_or_create_active_run(
        self,
        *,
        session_id: str,
        villager_model: str,
        werewolf_model: str,
        seed: int | None,
        max_rounds: int,
        rule_set_id: str = DEFAULT_RULE_SET_ID,
        rule_set: dict[str, Any] | None = None,
        player_configs: list[PlayerConfig] | None = None,
    ) -> tuple[LiveGameRun, bool]:
        with self._lock:
            active_run = self._active_run_for_session_locked(session_id)
            if active_run is not None:
                return active_run, False
            return (
                self.create_run(
                    session_id=session_id,
                    villager_model=villager_model,
                    werewolf_model=werewolf_model,
                    seed=seed,
                    max_rounds=max_rounds,
                    rule_set_id=rule_set_id,
                    rule_set=rule_set,
                    player_configs=player_configs,
                ),
                True,
            )

    def get_run(self, run_id: str) -> LiveGameRun:
        with self._lock:
            return self._runs[run_id]

    def try_get_run(self, run_id: str) -> LiveGameRun | None:
        with self._lock:
            return self._runs.get(run_id)

    def set_live_store(self, live_store: LiveStore | None) -> None:
        with self._lock:
            self._live_store = live_store

    def _active_run_for_session_locked(self, session_id: str) -> LiveGameRun | None:
        return next(
            (
                run
                for run in reversed(tuple(self._runs.values()))
                if run.session_id == session_id and run.status in {"queued", "running"}
            ),
            None,
        )

    def mark_running(self, run_id: str) -> LiveEvent:
        with self._lock:
            run = self._runs[run_id]
            self._raise_if_stop_requested_locked(run)
            run.status = "running"
            run.started_at = utc_now()
            self._persist_run_locked(run)
            return self._publish_locked(run, "run_started")

    def mark_completed(self, run_id: str, *, winner: str) -> LiveEvent:
        with self._lock:
            run = self._runs[run_id]
            run.status = "completed"
            run.winner = winner
            run.completed_at = utc_now()
            self._persist_run_locked(run)
            return self._publish_locked(
                run,
                "game_completed",
                payload={"winner": winner},
            )

    def mark_failed(self, run_id: str, *, error: str) -> LiveEvent:
        with self._lock:
            run = self._runs[run_id]
            run.status = "failed"
            run.error = error
            run.completed_at = utc_now()
            self._persist_run_locked(run)
            return self._publish_locked(
                run,
                "game_failed",
                payload={"error": error},
            )

    def request_stop(self, run_id: str) -> LiveEvent:
        with self._lock:
            run = self._runs[run_id]
            if run.status not in {"queued", "running"}:
                raise ValueError(f"Run {run_id} is not active")
            if run.stop_requested_at is not None:
                raise ValueError(f"Run {run_id} already has a stop request")
            run.stop_requested_at = utc_now()
            self._persist_run_locked(run)
            return self._publish_locked(
                run,
                "run_stop_requested",
                payload={"requested_at": run.stop_requested_at},
            )

    def stop_requested(self, run_id: str) -> bool:
        with self._lock:
            run = self._runs[run_id]
            return run.stop_requested_at is not None

    def raise_if_stop_requested(self, run_id: str) -> None:
        with self._lock:
            self._raise_if_stop_requested_locked(self._runs[run_id])

    def mark_canceled(self, run_id: str) -> LiveEvent:
        with self._lock:
            run = self._runs[run_id]
            run.status = "canceled"
            run.error = None
            run.completed_at = utc_now()
            self._persist_run_locked(run)
            return self._publish_locked(run, "game_canceled")

    @staticmethod
    def _raise_if_stop_requested_locked(run: LiveGameRun) -> None:
        if run.stop_requested_at is not None:
            raise GameRunCanceled("Game run was canceled by an administrator")

    def publish(
        self,
        run_id: str,
        event_type: str,
        *,
        round_number: int | None = None,
        phase: str | None = None,
        actor: str | None = None,
        action: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> LiveEvent:
        with self._lock:
            run = self._runs[run_id]
            return self._publish_locked(
                run,
                event_type,
                round_number=round_number,
                phase=phase,
                actor=actor,
                action=action,
                payload=payload,
            )

    def events_after(self, run_id: str, *, after_id: int | None = None) -> list[LiveEvent]:
        with self._lock:
            run = self._runs[run_id]
            if after_id is None:
                return list(run.events)
            return [event for event in run.events if event.id > after_id]

    def subscribe(
        self,
        run_id: str,
        *,
        after_id: int | None = None,
    ) -> queue.Queue[LiveEvent]:
        with self._lock:
            run = self._runs[run_id]
            subscriber: queue.Queue[LiveEvent] = queue.Queue()
            for event in self.events_after(run_id, after_id=after_id):
                subscriber.put(event)
            run.subscribers.append(subscriber)
            return subscriber

    def unsubscribe(
        self,
        run_id: str,
        subscriber: queue.Queue[LiveEvent],
    ) -> None:
        with self._lock:
            run = self._runs[run_id]
            if subscriber in run.subscribers:
                run.subscribers.remove(subscriber)

    def _publish_locked(
        self,
        run: LiveGameRun,
        event_type: str,
        *,
        round_number: int | None = None,
        phase: str | None = None,
        actor: str | None = None,
        action: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> LiveEvent:
        event = LiveEvent(
            id=run.next_event_id,
            type=event_type,
            run_id=run.run_id,
            session_id=run.session_id,
            created_at=utc_now(),
            round=round_number,
            phase=phase,
            actor=actor,
            action=action,
            payload=payload,
        )
        run.next_event_id += 1
        run.events.append(event)
        self._persist_event_locked(event)
        for subscriber in run.subscribers:
            subscriber.put(event)
        return event

    def _persist_run_locked(self, run: LiveGameRun) -> None:
        if self._live_store is not None:
            try:
                self._live_store.save_run(run)
            except Exception:
                logger.exception("Failed to persist live run %s", run.run_id)

    def _persist_event_locked(self, event: LiveEvent) -> None:
        if self._live_store is not None:
            try:
                self._live_store.append_event(event)
            except Exception:
                logger.exception(
                    "Failed to persist live event %s for run %s",
                    event.id,
                    event.run_id,
                )


class EventSink:
    def __init__(self, registry: LiveRunRegistry, run_id: str) -> None:
        self.registry = registry
        self.run_id = run_id

    def publish(
        self,
        event_type: str,
        *,
        round_number: int | None = None,
        phase: str | None = None,
        actor: str | None = None,
        action: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> LiveEvent:
        self.registry.raise_if_stop_requested(self.run_id)
        return self.registry.publish(
            self.run_id,
            event_type,
            round_number=round_number,
            phase=phase,
            actor=actor,
            action=action,
            payload=payload,
        )


class NullEventSink:
    def publish(
        self,
        event_type: str,
        *,
        round_number: int | None = None,
        phase: str | None = None,
        actor: str | None = None,
        action: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> None:
        return None


def format_sse(event: LiveEvent) -> str:
    data = json.dumps(event.to_dict(), ensure_ascii=False)
    return f"id: {event.id}\nevent: {event.type}\ndata: {data}\n\n"


def _copy_json_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return json.loads(json.dumps(payload, ensure_ascii=False))
