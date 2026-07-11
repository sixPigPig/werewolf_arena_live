from __future__ import annotations

import json
import logging
import queue
import threading
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Iterator, Literal, Protocol

from app.werewolf.player_configs import PlayerConfig
from app.werewolf.rules import DEFAULT_RULE_SET_ID, get_rule_set, rule_set_snapshot

RunStatus = Literal["queued", "running", "completed", "failed", "canceled"]
logger = logging.getLogger(__name__)


class GameRunCanceled(RuntimeError):
    """Raised by a live event sink when an operator requested a safe stop."""


class RunLeaseUnavailable(RuntimeError):
    """Raised when another API worker owns the live run lease."""


@dataclass(frozen=True)
class RunLeaseState:
    worker_id: str | None
    worker_heartbeat_at: str | None
    lease_expires_at: str | None
    stop_requested_at: str | None
    status: RunStatus
    control_version: int


def utc_now() -> str:
    return datetime.now(tz=UTC).isoformat().replace("+00:00", "Z")


def _format_datetime(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


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
    worker_id: str | None = None
    worker_heartbeat_at: str | None = None
    lease_expires_at: str | None = None
    control_version: int = 0
    lease_lost: bool = field(default=False, repr=False)
    persisted_event_count: int = field(default=0, repr=False)
    events: list[LiveEvent] = field(default_factory=list)
    subscribers: list[queue.Queue[LiveEvent]] = field(default_factory=list)
    next_event_id: int = 1

    @property
    def event_count(self) -> int:
        return max(len(self.events), self.persisted_event_count)

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

    def events_after(self, run_id: str, *, after_id: int | None = None) -> list[LiveEvent]:
        ...

    def load_run(self, run_id: str) -> LiveGameRun | None:
        ...

    def active_run_for_session(self, session_id: str) -> LiveGameRun | None:
        ...

    def acquire_lease(
        self,
        run_id: str,
        *,
        worker_id: str,
        heartbeat_at: str,
        lease_expires_at: str,
    ) -> RunLeaseState | None:
        ...

    def heartbeat_lease(
        self,
        run_id: str,
        *,
        worker_id: str,
        heartbeat_at: str,
        lease_expires_at: str,
    ) -> RunLeaseState | None:
        ...


class LiveRunRegistry:
    def __init__(
        self,
        live_store: LiveStore | None = None,
        *,
        worker_id: str | None = None,
        lease_seconds: float = 15.0,
        heartbeat_seconds: float = 3.0,
        event_poll_seconds: float = 0.25,
    ) -> None:
        self._runs: dict[str, LiveGameRun] = {}
        self._lock = threading.RLock()
        self._live_store = live_store
        self.worker_id = worker_id or f"worker_{uuid.uuid4().hex[:20]}"
        self.lease_seconds = lease_seconds
        self.heartbeat_seconds = heartbeat_seconds
        self.event_poll_seconds = event_poll_seconds
        self._persistent_subscriptions: dict[int, threading.Event] = {}

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
                worker_id=self.worker_id,
            )
            self._runs[run.run_id] = run
            try:
                self._persist_run_locked(run, raise_on_error=True)
            except Exception:
                self._runs.pop(run.run_id, None)
                raise
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
            local_run = self._active_run_for_session_locked(session_id)
        if local_run is not None:
            return local_run
        return self._load_persisted_active_run(session_id)

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
        active_run = self.try_get_active_run_for_session(session_id)
        if active_run is not None:
            return active_run, False
        try:
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
        except Exception:
            raced_run = self._load_persisted_active_run(session_id)
            if raced_run is not None:
                return raced_run, False
            raise

    def get_run(self, run_id: str) -> LiveGameRun:
        with self._lock:
            return self._runs[run_id]

    def try_get_run(self, run_id: str) -> LiveGameRun | None:
        with self._lock:
            local_run = self._runs.get(run_id)
        if local_run is not None:
            return local_run
        return self._load_persisted_run(run_id)

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
        lease_state = self._acquire_lease(run_id)
        if lease_state is None and self._supports_store_method("acquire_lease"):
            raise RunLeaseUnavailable(f"Run {run_id} is owned by another worker")
        with self._lock:
            run = self._runs[run_id]
            if lease_state is not None:
                self._apply_lease_state_locked(run, lease_state)
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
            run.lease_expires_at = None
            self._persist_run_locked(run)
            if run.status != "completed":
                return self._publish_terminal_state_locked(run)
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
            run.lease_expires_at = None
            self._persist_run_locked(run)
            if run.status != "failed":
                return self._publish_terminal_state_locked(run)
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
            run.control_version += 1
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
            run.lease_expires_at = None
            self._persist_run_locked(run)
            if run.status != "canceled":
                return self._publish_terminal_state_locked(run)
            return self._publish_locked(run, "game_canceled")

    def _publish_terminal_state_locked(self, run: LiveGameRun) -> LiveEvent:
        if run.status == "completed":
            return self._publish_locked(
                run,
                "game_completed",
                payload={"winner": run.winner},
            )
        if run.status == "canceled":
            return self._publish_locked(run, "game_canceled")
        return self._publish_locked(
            run,
            "game_failed",
            payload={"error": run.error},
        )

    @staticmethod
    def _raise_if_stop_requested_locked(run: LiveGameRun) -> None:
        if run.lease_lost:
            raise RunLeaseUnavailable("Live run worker lease was lost")
        if run.stop_requested_at is not None:
            raise GameRunCanceled("Game run was canceled by an administrator")

    def adopt_stop_request(
        self,
        run_id: str,
        *,
        requested_at: str,
        control_version: int,
    ) -> bool:
        with self._lock:
            run = self._runs.get(run_id)
            if run is None or run.stop_requested_at is not None:
                return False
            run.stop_requested_at = requested_at
            run.control_version = max(run.control_version, control_version)
            self._publish_locked(
                run,
                "run_stop_requested",
                payload={"requested_at": requested_at},
            )
            return True

    @contextmanager
    def maintain_lease(self, run_id: str) -> Iterator[None]:
        if not self._supports_store_method("heartbeat_lease"):
            yield
            return
        stop_event = threading.Event()
        thread = threading.Thread(
            target=self._lease_heartbeat_loop,
            args=(run_id, stop_event),
            daemon=True,
            name=f"live-lease-{run_id}",
        )
        thread.start()
        try:
            yield
        finally:
            stop_event.set()
            thread.join(timeout=max(0.25, self.heartbeat_seconds + 0.25))

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
            run = self._runs.get(run_id)
            if run is not None:
                if after_id is None:
                    return list(run.events)
                return [event for event in run.events if event.id > after_id]
        loader = getattr(self._live_store, "events_after", None)
        if not callable(loader):
            raise KeyError(run_id)
        return loader(run_id, after_id=after_id)

    def subscribe(
        self,
        run_id: str,
        *,
        after_id: int | None = None,
    ) -> queue.Queue[LiveEvent]:
        with self._lock:
            run = self._runs.get(run_id)
            if run is not None:
                subscriber: queue.Queue[LiveEvent] = queue.Queue()
                events = (
                    list(run.events)
                    if after_id is None
                    else [event for event in run.events if event.id > after_id]
                )
                for event in events:
                    subscriber.put(event)
                run.subscribers.append(subscriber)
                return subscriber
        subscriber = queue.Queue()
        historical = self.events_after(run_id, after_id=after_id)
        for event in historical:
            subscriber.put(event)
        cursor = historical[-1].id if historical else after_id
        stop_event = threading.Event()
        with self._lock:
            self._persistent_subscriptions[id(subscriber)] = stop_event
        threading.Thread(
            target=self._poll_persisted_subscription,
            args=(run_id, subscriber, cursor, stop_event),
            daemon=True,
            name=f"live-events-{run_id}",
        ).start()
        return subscriber

    def unsubscribe(
        self,
        run_id: str,
        subscriber: queue.Queue[LiveEvent],
    ) -> None:
        with self._lock:
            run = self._runs.get(run_id)
            if run is not None and subscriber in run.subscribers:
                run.subscribers.remove(subscriber)
                return
            stop_event = self._persistent_subscriptions.pop(id(subscriber), None)
        if stop_event is not None:
            stop_event.set()

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

    def _persist_run_locked(
        self,
        run: LiveGameRun,
        *,
        raise_on_error: bool = False,
    ) -> None:
        if self._live_store is not None:
            try:
                self._live_store.save_run(run)
            except Exception:
                logger.exception("Failed to persist live run %s", run.run_id)
                if raise_on_error:
                    raise

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

    def _supports_store_method(self, method_name: str) -> bool:
        return callable(getattr(self._live_store, method_name, None))

    def _load_persisted_run(self, run_id: str) -> LiveGameRun | None:
        loader = getattr(self._live_store, "load_run", None)
        return loader(run_id) if callable(loader) else None

    def _load_persisted_active_run(self, session_id: str) -> LiveGameRun | None:
        loader = getattr(self._live_store, "active_run_for_session", None)
        return loader(session_id) if callable(loader) else None

    def _lease_window(self) -> tuple[str, str]:
        heartbeat_at = datetime.now(tz=UTC)
        lease_expires_at = heartbeat_at + timedelta(seconds=self.lease_seconds)
        return _format_datetime(heartbeat_at), _format_datetime(lease_expires_at)

    def _acquire_lease(self, run_id: str) -> RunLeaseState | None:
        acquire = getattr(self._live_store, "acquire_lease", None)
        if not callable(acquire):
            return None
        heartbeat_at, lease_expires_at = self._lease_window()
        return acquire(
            run_id,
            worker_id=self.worker_id,
            heartbeat_at=heartbeat_at,
            lease_expires_at=lease_expires_at,
        )

    def _lease_heartbeat_loop(
        self,
        run_id: str,
        stop_event: threading.Event,
    ) -> None:
        heartbeat = getattr(self._live_store, "heartbeat_lease", None)
        if not callable(heartbeat):
            return
        while not stop_event.wait(self.heartbeat_seconds):
            try:
                state = self.refresh_lease(run_id)
            except Exception:
                logger.exception("Failed to heartbeat live run lease %s", run_id)
                continue
            if state is None:
                return

    def refresh_lease(self, run_id: str) -> RunLeaseState | None:
        heartbeat = getattr(self._live_store, "heartbeat_lease", None)
        if not callable(heartbeat):
            return None
        heartbeat_at, lease_expires_at = self._lease_window()
        state = heartbeat(
            run_id,
            worker_id=self.worker_id,
            heartbeat_at=heartbeat_at,
            lease_expires_at=lease_expires_at,
        )
        with self._lock:
            run = self._runs.get(run_id)
            if run is None:
                return state
            if state is None:
                run.lease_lost = True
                return None
            if (
                state.status in {"queued", "running"}
                and state.worker_id != self.worker_id
            ):
                run.lease_lost = True
                return None
            if state.status in {"completed", "failed"}:
                run.lease_lost = True
                return None
            had_stop_request = run.stop_requested_at is not None
            self._apply_lease_state_locked(run, state)
            if not had_stop_request and run.stop_requested_at is not None:
                self._publish_locked(
                    run,
                    "run_stop_requested",
                    payload={"requested_at": run.stop_requested_at},
                )
        return state

    @staticmethod
    def _apply_lease_state_locked(run: LiveGameRun, state: RunLeaseState) -> None:
        run.worker_id = state.worker_id
        run.worker_heartbeat_at = state.worker_heartbeat_at
        run.lease_expires_at = state.lease_expires_at
        run.stop_requested_at = state.stop_requested_at
        run.control_version = state.control_version
        run.lease_lost = False

    def _poll_persisted_subscription(
        self,
        run_id: str,
        subscriber: queue.Queue[LiveEvent],
        after_id: int | None,
        stop_event: threading.Event,
    ) -> None:
        cursor = after_id
        try:
            while not stop_event.wait(self.event_poll_seconds):
                try:
                    events = self.events_after(run_id, after_id=cursor)
                except Exception:
                    logger.exception("Failed to poll persisted live events for %s", run_id)
                    continue
                for event in events:
                    cursor = event.id
                    subscriber.put(event)
                    if event.type in {"game_completed", "game_failed", "game_canceled"}:
                        return
                if not events:
                    run = self._load_persisted_run(run_id)
                    if run is None:
                        return
                    if run.status in {"completed", "failed", "canceled"}:
                        subscriber.put(
                            LiveEvent(
                                id=(cursor or 0) + 1,
                                type={
                                    "completed": "game_completed",
                                    "failed": "game_failed",
                                    "canceled": "game_canceled",
                                }[run.status],
                                run_id=run.run_id,
                                session_id=run.session_id,
                                created_at=run.completed_at or utc_now(),
                                payload=(
                                    {"winner": run.winner}
                                    if run.status == "completed"
                                    else {}
                                ),
                            )
                        )
                        return
        finally:
            with self._lock:
                self._persistent_subscriptions.pop(id(subscriber), None)


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
