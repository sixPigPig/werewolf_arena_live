from __future__ import annotations

import json
import logging
import math
import queue
import re
import threading
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Iterator, Literal, Protocol

from app.rule_sets.types import CompiledRuleSet
from app.werewolf.player_configs import PlayerConfig
from app.werewolf.rules import DEFAULT_RULE_SET_ID, get_rule_set, rule_set_snapshot

RunStatus = Literal["queued", "running", "completed", "failed", "canceled"]
logger = logging.getLogger(__name__)
_RULE_SET_REVISION_FIELDS = frozenset(
    {"revision_id", "revision_no", "schema_version", "content_hash"}
)
_CONTENT_HASH_PATTERN = re.compile(r"[0-9a-f]{64}")
_STRICT_JSON_MAX_DEPTH = 128
ACTIVATION_ACK_RUN_FIELD_NAMES = frozenset(
    {
        "run_id",
        "session_id",
        "status",
        "villager_model",
        "werewolf_model",
        "seed",
        "max_rounds",
        "parent_run_id",
        "resume_from_round",
        "attempt_no",
        "rule_set_id",
        "rule_set_revision_id",
        "rule_set_revision_no",
        "rule_set_content_hash",
        "rule_set",
        "player_configs",
        "lineup_quality_warnings",
        "lineup_quality_report",
        "p2_diagnostics",
        "winner",
        "error",
        "worker_id",
        "control_version",
        "fence_token",
        "recovery_attempts",
        "recovery_last_error",
    }
)
ACTIVATION_ACK_RUN_TIMESTAMP_NAMES = frozenset(
    {
        "created_at",
        "started_at",
        "completed_at",
        "stop_requested_at",
        "worker_heartbeat_at",
        "lease_expires_at",
        "recovery_last_attempt_at",
        "recovery_not_before",
    }
)


class GameRunCanceled(RuntimeError):
    """Raised by a live event sink when an operator requested a safe stop."""


class RunLeaseUnavailable(RuntimeError):
    """Raised when another API worker owns the live run lease."""


class RunRuleSetMismatch(RunLeaseUnavailable):
    """Raised when a locked live run no longer matches its rule expectation."""


@dataclass(frozen=True)
class RunLeaseState:
    worker_id: str | None
    worker_heartbeat_at: str | None
    lease_expires_at: str | None
    stop_requested_at: str | None
    status: RunStatus
    control_version: int
    fence_token: int
    recovery_attempts: int
    recovery_last_attempt_at: str | None
    recovery_not_before: str | None
    recovery_last_error: str | None


@dataclass(frozen=True)
class RunRecoveryCandidate:
    run_id: str
    session_id: str
    recovery_attempts: int


@dataclass(frozen=True)
class RunRuleSetExpectedState:
    rule_set_id: str
    rule_set_revision_id: str | None
    rule_set_revision_no: int | None
    rule_set_content_hash: str | None
    rule_set: dict[str, object]
    rule_set_was_sql_null: bool = False


def utc_now() -> str:
    return datetime.now(tz=UTC).isoformat().replace("+00:00", "Z")


def _format_datetime(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def validate_rule_set_revision_metadata(
    *,
    rule_set_revision_id: object | None,
    rule_set_revision_no: object | None,
    rule_set_content_hash: object | None,
    rule_set: object,
) -> None:
    scalar_values = (
        rule_set_revision_id,
        rule_set_revision_no,
        rule_set_content_hash,
    )
    scalar_fields_present = tuple(value is not None for value in scalar_values)
    legacy_hash_only = scalar_fields_present == (False, False, True)
    if any(scalar_fields_present) and not all(scalar_fields_present) and not legacy_hash_only:
        raise ValueError("rule set revision metadata must be all present or all absent")
    scalars_are_managed = all(scalar_fields_present)
    if scalars_are_managed:
        _validate_managed_rule_metadata_values(
            rule_set_revision_id,
            rule_set_revision_no,
            rule_set_content_hash,
        )

    if not isinstance(rule_set, dict):
        raise ValueError("rule_set must be a dictionary")
    present_snapshot_fields = set(rule_set) & _RULE_SET_REVISION_FIELDS
    if present_snapshot_fields and present_snapshot_fields != _RULE_SET_REVISION_FIELDS:
        raise ValueError("snapshot revision metadata must be all present or all absent")
    if not present_snapshot_fields:
        if legacy_hash_only:
            from app.rule_sets.snapshots import resolve_rule_set_snapshot

            if (
                not isinstance(rule_set_content_hash, str)
                or _CONTENT_HASH_PATTERN.fullmatch(rule_set_content_hash) is None
            ):
                raise ValueError(
                    "rule set content_hash must be 64 lowercase hexadecimal characters"
                )
            try:
                compiled = resolve_rule_set_snapshot(rule_set)
            except (AttributeError, KeyError, OverflowError, TypeError, ValueError):
                raise ValueError("legacy hash-only snapshot must be complete") from None
            if (
                compiled.revision_id is not None
                or compiled.revision_no is not None
                or compiled.content_hash != rule_set_content_hash
            ):
                raise ValueError("legacy hash-only metadata must match its snapshot")
        return
    if not scalars_are_managed:
        raise ValueError("managed rule set snapshots require pinned revision metadata")

    snapshot_revision_id = rule_set["revision_id"]
    snapshot_revision_no = rule_set["revision_no"]
    snapshot_content_hash = rule_set["content_hash"]
    _validate_managed_rule_metadata_values(
        snapshot_revision_id,
        snapshot_revision_no,
        snapshot_content_hash,
    )
    schema_version = rule_set["schema_version"]
    if isinstance(schema_version, bool) or not isinstance(schema_version, int):
        raise ValueError("rule set schema_version must be an integer")
    if schema_version != 1:
        raise ValueError("rule set schema_version must be 1")
    if (
        snapshot_revision_id != rule_set_revision_id
        or snapshot_revision_no != rule_set_revision_no
        or snapshot_content_hash != rule_set_content_hash
    ):
        raise ValueError("pinned revision metadata must match the rule set snapshot")


def _validate_managed_rule_metadata_values(
    revision_id: object,
    revision_no: object,
    content_hash: object,
) -> None:
    if not isinstance(revision_id, str) or not revision_id or revision_id.strip() != revision_id:
        raise ValueError("rule set revision_id must be non-empty untrimmed text")
    if isinstance(revision_no, bool) or not isinstance(revision_no, int) or revision_no <= 0:
        raise ValueError("rule set revision_no must be a positive integer")
    if not isinstance(content_hash, str) or _CONTENT_HASH_PATTERN.fullmatch(content_hash) is None:
        raise ValueError("rule set content_hash must be 64 lowercase hexadecimal characters")


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


LiveEventAudience = Literal[
    "internal",
    "actor_private",
    "team_private",
    "player_public",
    "spectator_god_view",
    "terminal_reveal",
]


@dataclass(frozen=True, init=False)
class ProjectedLiveEvent:
    """An audience-scoped event that is safe to serialize outside the engine."""

    id: int
    source_event_id: int
    type: str
    run_id: str
    session_id: str
    created_at: str
    audience: LiveEventAudience
    projection_version: int
    round: int | None = None
    phase: str | None = None
    actor: str | None = None
    action: str | None = None
    _payload: dict[str, Any] = field(default_factory=dict, repr=False)

    def __init__(
        self,
        *,
        id: int,
        source_event_id: int,
        type: str,
        run_id: str,
        session_id: str,
        created_at: str,
        audience: LiveEventAudience,
        projection_version: int,
        round: int | None = None,
        phase: str | None = None,
        actor: str | None = None,
        action: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> None:
        object.__setattr__(self, "id", id)
        object.__setattr__(self, "source_event_id", source_event_id)
        object.__setattr__(self, "type", type)
        object.__setattr__(self, "run_id", run_id)
        object.__setattr__(self, "session_id", session_id)
        object.__setattr__(self, "created_at", created_at)
        object.__setattr__(self, "audience", audience)
        object.__setattr__(self, "projection_version", projection_version)
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
            "source_event_id": self.source_event_id,
            "type": self.type,
            "run_id": self.run_id,
            "session_id": self.session_id,
            "created_at": self.created_at,
            "audience": self.audience,
            "projection_version": self.projection_version,
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
    parent_run_id: str | None = None
    resume_from_round: int | None = None
    attempt_no: int = 1
    rule_set_id: str = DEFAULT_RULE_SET_ID
    rule_set_revision_id: str | None = None
    rule_set_revision_no: int | None = None
    rule_set_content_hash: str | None = None
    rule_set: dict[str, Any] = field(
        default_factory=lambda: rule_set_snapshot(get_rule_set(DEFAULT_RULE_SET_ID))
    )
    rule_set_was_sql_null: bool = field(default=False, repr=False)
    player_configs: list[dict[str, Any]] = field(default_factory=list)
    lineup_quality_warnings: list[dict[str, str]] = field(default_factory=list)
    lineup_quality_report: dict[str, Any] = field(default_factory=dict)
    p2_diagnostics: dict[str, Any] = field(default_factory=dict, repr=False)
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
    fence_token: int = 0
    recovery_attempts: int = 0
    recovery_last_attempt_at: str | None = None
    recovery_not_before: str | None = None
    recovery_last_error: str | None = None
    lease_lost: bool = field(default=False, repr=False)
    persisted_event_count: int = field(default=0, repr=False)
    events: list[LiveEvent] = field(default_factory=list)
    subscribers: list[queue.Queue[LiveEvent]] = field(default_factory=list)
    next_event_id: int = 1

    def __post_init__(self) -> None:
        validate_rule_set_revision_metadata(
            rule_set_revision_id=self.rule_set_revision_id,
            rule_set_revision_no=self.rule_set_revision_no,
            rule_set_content_hash=self.rule_set_content_hash,
            rule_set=self.rule_set,
        )

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
            "parent_run_id": self.parent_run_id,
            "resume_from_round": self.resume_from_round,
            "attempt_no": self.attempt_no,
            "rule_set_id": self.rule_set_id,
            "rule_set_revision_id": self.rule_set_revision_id,
            "rule_set_revision_no": self.rule_set_revision_no,
            "rule_set_content_hash": self.rule_set_content_hash,
            "rule_set": _copy_json_payload(self.rule_set),
            "player_configs": _copy_json_payload(self.player_configs),
            "lineup_quality_warnings": _copy_json_payload(self.lineup_quality_warnings),
            "lineup_quality_report": _copy_json_payload(self.lineup_quality_report),
            "status": self.status,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "winner": self.winner,
            "error": self.error,
            "stop_requested_at": self.stop_requested_at,
            "event_count": self.event_count,
        }


def live_run_matches_compiled_rule_set(
    run: LiveGameRun,
    compiled: CompiledRuleSet,
) -> bool:
    return (
        type(run.rule_set_id) is str
        and run.rule_set_id == compiled.rule_set.id
        and type(run.rule_set_revision_id) is type(compiled.revision_id)
        and run.rule_set_revision_id == compiled.revision_id
        and type(run.rule_set_revision_no) is type(compiled.revision_no)
        and run.rule_set_revision_no == compiled.revision_no
        and type(run.rule_set_content_hash) is str
        and run.rule_set_content_hash == compiled.content_hash
        and strict_json_equal(run.rule_set, compiled.snapshot)
    )


@dataclass(frozen=True)
class RunActivationExpectedEvent:
    id: int
    type: str
    run_id: str
    session_id: str
    created_at: str
    round: int | None
    phase: str | None
    actor: str | None
    action: str | None
    payload: dict[str, object]


@dataclass(frozen=True)
class RunActivationSourceState:
    run_id: str
    session_id: str
    status: str
    worker_id: str | None
    fence_token: int
    lease_lost: bool
    stop_requested_at: str | None
    started_at: str | None
    worker_heartbeat_at: str | None
    lease_expires_at: str | None
    next_event_id: int
    persisted_event_count: int
    rule_set_was_sql_null: bool
    fields: dict[str, object]
    timestamps: dict[str, str | None]
    events: tuple[RunActivationExpectedEvent, ...]
    events_container: list[LiveEvent]
    subscribers: tuple[queue.Queue[LiveEvent], ...]
    subscribers_container: list[queue.Queue[LiveEvent]]


@dataclass(frozen=True)
class RunActivationExpectedState:
    run_id: str
    fields: dict[str, object]
    timestamps: dict[str, str | None]
    events: tuple[RunActivationExpectedEvent, ...]
    event_count: int
    next_event_id: int
    rule_set_was_sql_null: bool = False


class LiveStore(Protocol):
    def save_new_run(self, run: LiveGameRun) -> None: ...

    def save_run(self, run: LiveGameRun) -> None: ...

    def activate_run(
        self,
        run_id: str,
        *,
        expected_events: tuple[LiveEvent | RunActivationExpectedEvent, ...],
        expected_rule_set: RunRuleSetExpectedState,
        expected_status: str,
        expected_started_at: str | None,
        activation: LiveEvent,
        worker_id: str,
        fence_token: int,
        started_at: str,
    ) -> None: ...

    def activation_was_committed(
        self,
        expected_state: RunActivationExpectedState,
    ) -> bool: ...

    def fail_run(
        self,
        run_id: str,
        *,
        expected_events: tuple[LiveEvent | RunActivationExpectedEvent, ...],
        expected_rule_set: RunRuleSetExpectedState,
        expected_status: str,
        failure: LiveEvent,
        worker_id: str,
        fence_token: int,
        completed_at: str,
        error: str,
    ) -> None: ...

    def failure_was_committed(
        self,
        expected_state: RunActivationExpectedState,
    ) -> bool: ...

    def append_event(
        self,
        event: LiveEvent,
        *,
        worker_id: str,
        fence_token: int,
    ) -> None: ...

    def events_after(self, run_id: str, *, after_id: int | None = None) -> list[LiveEvent]: ...

    def projected_events_after(
        self,
        run_id: str,
        *,
        audience: Literal["player_public", "spectator_god_view"],
        after_id: int | None = None,
    ) -> list[ProjectedLiveEvent]: ...

    def load_run(self, run_id: str) -> LiveGameRun | None: ...

    def active_run_for_session(self, session_id: str) -> LiveGameRun | None: ...

    def latest_run_for_session(self, session_id: str) -> LiveGameRun | None: ...

    def acquire_lease(
        self,
        run_id: str,
        *,
        expected_events: tuple[LiveEvent | RunActivationExpectedEvent, ...],
        expected_rule_set: RunRuleSetExpectedState,
        worker_id: str,
        heartbeat_at: str,
        lease_expires_at: str,
    ) -> RunLeaseState | None: ...

    def heartbeat_lease(
        self,
        run_id: str,
        *,
        worker_id: str,
        heartbeat_at: str,
        lease_expires_at: str,
        fence_token: int,
    ) -> RunLeaseState | None: ...

    def recovery_candidates(
        self,
        *,
        stale_before: str,
        now: str,
        max_attempts: int,
        limit: int,
    ) -> list[RunRecoveryCandidate]: ...

    def acquire_recovery_lease(
        self,
        run_id: str,
        *,
        expected_events: tuple[LiveEvent, ...],
        expected_rule_set: RunRuleSetExpectedState,
        worker_id: str,
        expected_attempts: int,
        max_attempts: int,
        stale_before: str,
        heartbeat_at: str,
        lease_expires_at: str,
        recovery_not_before: str,
    ) -> RunLeaseState | None: ...


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
        self._activation_events: dict[tuple[str, int], LiveEvent] = {}

    def create_run(
        self,
        *,
        session_id: str,
        villager_model: str,
        werewolf_model: str,
        seed: int | None,
        max_rounds: int,
        parent_run_id: str | None = None,
        resume_from_round: int | None = None,
        attempt_no: int = 1,
        rule_set_id: str = DEFAULT_RULE_SET_ID,
        rule_set_revision_id: str | None = None,
        rule_set_revision_no: int | None = None,
        rule_set_content_hash: str | None = None,
        rule_set: dict[str, Any] | None = None,
        player_configs: list[PlayerConfig] | None = None,
        lineup_quality_warnings: list[dict[str, str]] | None = None,
        lineup_quality_report: dict[str, object] | None = None,
    ) -> LiveGameRun:
        run = self.prepare_run(
            session_id=session_id,
            villager_model=villager_model,
            werewolf_model=werewolf_model,
            seed=seed,
            max_rounds=max_rounds,
            parent_run_id=parent_run_id,
            resume_from_round=resume_from_round,
            attempt_no=attempt_no,
            rule_set_id=rule_set_id,
            rule_set_revision_id=rule_set_revision_id,
            rule_set_revision_no=rule_set_revision_no,
            rule_set_content_hash=rule_set_content_hash,
            rule_set=rule_set,
            player_configs=player_configs,
            lineup_quality_warnings=lineup_quality_warnings,
            lineup_quality_report=lineup_quality_report,
        )
        try:
            return self._persist_and_attach_prepared_run(run)
        except Exception:
            recovery_status, recovered_run = self._recover_committed_prepared_run(run)
            if recovery_status == "recovered" and recovered_run is not None:
                return recovered_run
            raise

    def prepare_run(
        self,
        *,
        session_id: str,
        villager_model: str,
        werewolf_model: str,
        seed: int | None,
        max_rounds: int,
        parent_run_id: str | None = None,
        resume_from_round: int | None = None,
        attempt_no: int = 1,
        rule_set_id: str = DEFAULT_RULE_SET_ID,
        rule_set_revision_id: str | None = None,
        rule_set_revision_no: int | None = None,
        rule_set_content_hash: str | None = None,
        rule_set: dict[str, Any] | None = None,
        player_configs: list[PlayerConfig] | None = None,
        lineup_quality_warnings: list[dict[str, str]] | None = None,
        lineup_quality_report: dict[str, object] | None = None,
    ) -> LiveGameRun:
        rule_set_data = (
            _copy_json_payload(rule_set)
            if rule_set is not None
            else rule_set_snapshot(get_rule_set(rule_set_id))
        )
        validate_rule_set_revision_metadata(
            rule_set_revision_id=rule_set_revision_id,
            rule_set_revision_no=rule_set_revision_no,
            rule_set_content_hash=rule_set_content_hash,
            rule_set=rule_set_data,
        )
        player_config_data = [config.to_dict() for config in player_configs or []]
        lineup_warning_data = _copy_json_payload(lineup_quality_warnings or [])
        lineup_report_data = _copy_json_payload(lineup_quality_report or {})
        run = LiveGameRun(
            run_id=f"run_{uuid.uuid4().hex[:12]}",
            session_id=session_id,
            villager_model=villager_model,
            werewolf_model=werewolf_model,
            seed=seed,
            max_rounds=max_rounds,
            parent_run_id=parent_run_id,
            resume_from_round=resume_from_round,
            attempt_no=attempt_no,
            rule_set_id=rule_set_id,
            rule_set_revision_id=rule_set_revision_id,
            rule_set_revision_no=rule_set_revision_no,
            rule_set_content_hash=rule_set_content_hash,
            rule_set=rule_set_data,
            player_configs=player_config_data,
            lineup_quality_warnings=lineup_warning_data,
            lineup_quality_report=lineup_report_data,
            worker_id=self.worker_id,
        )
        run.events.append(
            LiveEvent(
                id=1,
                type="run_created",
                run_id=run.run_id,
                session_id=run.session_id,
                created_at=utc_now(),
                payload={
                    "session_id": session_id,
                    "villager_model": villager_model,
                    "werewolf_model": werewolf_model,
                    "seed": seed,
                    "max_rounds": max_rounds,
                    "parent_run_id": parent_run_id,
                    "resume_from_round": resume_from_round,
                    "attempt_no": attempt_no,
                    "rule_set_id": rule_set_id,
                    "rule_set_revision_id": rule_set_revision_id,
                    "rule_set_revision_no": rule_set_revision_no,
                    "rule_set_content_hash": rule_set_content_hash,
                    "rule_set": rule_set_data,
                    "player_configs": player_config_data,
                    "lineup_quality_warnings": lineup_warning_data,
                    "lineup_quality_report": lineup_report_data,
                },
            )
        )
        run.next_event_id = 2
        return run

    def _persist_and_attach_prepared_run(self, run: LiveGameRun) -> LiveGameRun:
        with self._lock:
            self._raise_if_prepared_run_conflicts_locked(run)
            self._persist_new_run_locked(run)
            self.attach_prepared_run(run)
        return run

    def attach_prepared_run(self, run: LiveGameRun) -> None:
        validate_prepared_run(run)
        with self._lock:
            self._raise_if_prepared_run_conflicts_locked(run)
            self._runs[run.run_id] = run

    def detach_prepared_run(self, run: LiveGameRun) -> bool:
        with self._lock:
            if self._runs.get(run.run_id) is not run:
                return False
            self._runs.pop(run.run_id)
            return True

    def _raise_if_prepared_run_conflicts_locked(self, run: LiveGameRun) -> None:
        if run.run_id in self._runs:
            raise ValueError(f"Run {run.run_id} is already attached")
        active_run = self._active_run_for_session_locked(run.session_id)
        if active_run is not None:
            raise ValueError(
                f"Session {run.session_id} already has an active run {active_run.run_id}"
            )

    def try_get_active_run_for_session(self, session_id: str) -> LiveGameRun | None:
        with self._lock:
            local_run = self._complete_local_active_run_locked(session_id)
        if local_run is not None:
            return local_run
        return self._load_complete_persisted_active_run(session_id)

    def latest_run_for_session(self, session_id: str) -> LiveGameRun | None:
        with self._lock:
            local_runs = [run for run in self._runs.values() if run.session_id == session_id]
            local_run = max(
                local_runs,
                key=lambda run: (run.attempt_no, run.created_at, run.run_id),
                default=None,
            )
        loader = getattr(self._live_store, "latest_run_for_session", None)
        persisted_run = loader(session_id) if callable(loader) else None
        candidates = [run for run in (local_run, persisted_run) if run is not None]
        return max(
            candidates,
            key=lambda run: (run.attempt_no, run.created_at, run.run_id),
            default=None,
        )

    def get_or_create_active_run(
        self,
        *,
        session_id: str,
        villager_model: str,
        werewolf_model: str,
        seed: int | None,
        max_rounds: int,
        parent_run_id: str | None = None,
        resume_from_round: int | None = None,
        attempt_no: int = 1,
        rule_set_id: str = DEFAULT_RULE_SET_ID,
        rule_set_revision_id: str | None = None,
        rule_set_revision_no: int | None = None,
        rule_set_content_hash: str | None = None,
        rule_set: dict[str, Any] | None = None,
        player_configs: list[PlayerConfig] | None = None,
    ) -> tuple[LiveGameRun, bool]:
        validate_rule_set_revision_metadata(
            rule_set_revision_id=rule_set_revision_id,
            rule_set_revision_no=rule_set_revision_no,
            rule_set_content_hash=rule_set_content_hash,
            rule_set=rule_set if rule_set is not None else {},
        )
        active_run = self.try_get_active_run_for_session(session_id)
        if active_run is not None:
            return active_run, False
        candidate = self.prepare_run(
            session_id=session_id,
            villager_model=villager_model,
            werewolf_model=werewolf_model,
            seed=seed,
            max_rounds=max_rounds,
            parent_run_id=parent_run_id,
            resume_from_round=resume_from_round,
            attempt_no=attempt_no,
            rule_set_id=rule_set_id,
            rule_set_revision_id=rule_set_revision_id,
            rule_set_revision_no=rule_set_revision_no,
            rule_set_content_hash=rule_set_content_hash,
            rule_set=rule_set,
            player_configs=player_configs,
        )
        try:
            return self._persist_and_attach_prepared_run(candidate), True
        except Exception:
            recovery_status, recovered_run = self._recover_committed_prepared_run(candidate)
            if recovery_status == "recovered" and recovered_run is not None:
                return recovered_run, True
            if recovery_status != "absent":
                raise
            with self._lock:
                local_raced_run = self._complete_local_active_run_locked(session_id)
            if local_raced_run is not None and local_raced_run.run_id != candidate.run_id:
                return local_raced_run, False
            try:
                raced_run = self.try_get_active_run_for_session(session_id)
            except Exception:
                raced_run = None
            if raced_run is not None and raced_run.run_id != candidate.run_id:
                return raced_run, False
            raise

    def get_run(self, run_id: str) -> LiveGameRun:
        with self._lock:
            return self._runs[run_id]

    def try_get_run(self, run_id: str) -> LiveGameRun | None:
        with self._lock:
            local_run = self._complete_local_run_locked(
                self._runs.get(run_id),
                require_active=False,
            )
        if local_run is not None:
            return local_run
        return self._load_complete_persisted_run(run_id, require_active=False)

    def try_claim_stale_run(self, run_id: str) -> LiveGameRun | None:
        """Atomically attach an active run whose worker lease has expired."""
        with self._lock:
            initial_local_run = self._runs.get(run_id)
            initial_fence_token = (
                initial_local_run.fence_token if initial_local_run is not None else None
            )
        persisted = self._load_complete_persisted_run(run_id)
        if persisted is None or not _lease_is_expired(persisted.lease_expires_at):
            return None
        with self._lock:
            run = self._runs.get(run_id)
            if initial_local_run is None:
                if run is not None:
                    return None
            elif run is not initial_local_run or run.fence_token != initial_fence_token:
                return None
            if run is not None:
                run = self._complete_local_run_locked(run, require_active=True)
                if run is None:
                    return None
            expected_run = run if run is not None else persisted
            expected_rule_set = _capture_rule_set_expected_state(expected_run)
            lease_state = self._acquire_lease(
                run_id,
                expected_events=tuple(expected_run.events),
                expected_rule_set=expected_rule_set,
                worker_id=self.worker_id,
            )
            if lease_state is None:
                return None
            if run is None:
                run = persisted
                self._runs[run_id] = persisted
            self._apply_lease_state_locked(run, lease_state)
            return run

    def recovery_candidates(
        self,
        *,
        stale_before: str,
        now: str,
        max_attempts: int,
        limit: int = 20,
    ) -> list[RunRecoveryCandidate]:
        loader = getattr(self._live_store, "recovery_candidates", None)
        if not callable(loader):
            return []
        return loader(
            stale_before=stale_before,
            now=now,
            max_attempts=max_attempts,
            limit=limit,
        )

    def try_claim_orphan(
        self,
        candidate: RunRecoveryCandidate,
        *,
        stale_before: str,
        recovery_not_before: str,
        max_attempts: int,
    ) -> LiveGameRun | None:
        acquire = getattr(self._live_store, "acquire_recovery_lease", None)
        if not callable(acquire):
            return None
        with self._lock:
            initial_local_run = self._runs.get(candidate.run_id)
            initial_fence_token = (
                initial_local_run.fence_token if initial_local_run is not None else None
            )
        persisted = self._load_complete_persisted_run(candidate.run_id)
        if persisted is None:
            return None
        heartbeat_at, lease_expires_at = self._lease_window()
        with self._lock:
            local_run = self._runs.get(candidate.run_id)
            if initial_local_run is None:
                if local_run is not None:
                    return None
            elif local_run is not initial_local_run or local_run.fence_token != initial_fence_token:
                return None
            if local_run is not None:
                local_run = self._complete_local_run_locked(
                    local_run,
                    require_active=True,
                )
                if local_run is None:
                    return None
            expected_run = local_run if local_run is not None else persisted
            expected_rule_set = _capture_rule_set_expected_state(expected_run)
            try:
                state = acquire(
                    candidate.run_id,
                    expected_events=tuple(expected_run.events),
                    expected_rule_set=expected_rule_set,
                    worker_id=self.worker_id,
                    expected_attempts=candidate.recovery_attempts,
                    max_attempts=max_attempts,
                    stale_before=stale_before,
                    heartbeat_at=heartbeat_at,
                    lease_expires_at=lease_expires_at,
                    recovery_not_before=recovery_not_before,
                )
            except RunRuleSetMismatch:
                return None
            if state is None:
                return None
            if local_run is None:
                local_run = persisted
                self._runs[candidate.run_id] = local_run
            self._apply_lease_state_locked(local_run, state)
            return local_run

    def write_fence(self, run_id: str) -> tuple[str, int]:
        with self._lock:
            run = self._runs[run_id]
            if run.worker_id != self.worker_id or run.fence_token <= 0:
                raise RunLeaseUnavailable(f"Run {run_id} has no writable worker lease")
            return self.worker_id, run.fence_token

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
        _require_exact_str(run_id)
        with self._lock:
            _require_exact_str(self.worker_id)
            registry_worker_id = self.worker_id
            run = dict.__getitem__(self._runs, run_id)
            source = _capture_activation_source_state(run)
            if source.run_id != run_id:
                _raise_invalid_exact_json_value()
            _raise_if_activation_source_not_startable(source)
            has_live_store = self._live_store is not None
            if has_live_store:
                supports_activation = self._supports_store_method("activate_run")
                _require_unchanged_registry_worker_id(
                    self.worker_id,
                    captured=registry_worker_id,
                )
                if not supports_activation:
                    raise RuntimeError(
                        "Persistent live store does not support atomic activation persistence"
                    )
                supports_lease = self._supports_store_method("acquire_lease")
                _require_unchanged_registry_worker_id(
                    self.worker_id,
                    captured=registry_worker_id,
                )
                if not supports_lease:
                    raise RuntimeError(
                        "Persistent live store does not support activation lease acquisition"
                    )
                supports_ack_verification = self._supports_store_method("activation_was_committed")
                _require_unchanged_registry_worker_id(
                    self.worker_id,
                    captured=registry_worker_id,
                )
                if not supports_ack_verification:
                    raise RuntimeError(
                        "Persistent live store does not support atomic activation "
                        "acknowledgement verification"
                    )
            else:
                supports_lease = self._supports_store_method("acquire_lease")
                _require_unchanged_registry_worker_id(
                    self.worker_id,
                    captured=registry_worker_id,
                )
            has_claimed_lease = _activation_source_has_current_lease(
                source,
                registry_worker_id=registry_worker_id,
                has_live_store=has_live_store,
            )
            activation_key = (source.run_id, source.fence_token)
            existing_activation = _validated_cached_activation(
                self._activation_events.get(activation_key)
            )
            if (
                source.status == "running"
                and existing_activation is not None
                and (has_claimed_lease or not has_live_store)
            ):
                return existing_activation
            lease_state = (
                None
                if has_claimed_lease
                else self._acquire_lease(
                    source.run_id,
                    expected_events=source.events,
                    expected_rule_set=_rule_set_expected_state_from_source(source),
                    worker_id=registry_worker_id,
                )
            )
            _require_unchanged_registry_worker_id(
                self.worker_id,
                captured=registry_worker_id,
            )
            if lease_state is None and not has_claimed_lease and supports_lease:
                raise RunLeaseUnavailable(f"Run {source.run_id} is owned by another worker")
            if lease_state is not None:
                trusted_lease_state = _validated_activation_lease_state(
                    lease_state,
                    registry_worker_id=registry_worker_id,
                    expected_status=source.status,
                    previous_fence_token=source.fence_token,
                )
                self._apply_lease_state_locked(run, trusted_lease_state)
            source = _capture_activation_source_state(run)
            if source.run_id != run_id:
                _raise_invalid_exact_json_value()
            _raise_if_activation_source_not_startable(source)
            if has_live_store and not _activation_source_has_current_lease(
                source,
                registry_worker_id=registry_worker_id,
                has_live_store=True,
            ):
                raise RunLeaseUnavailable(f"Run {source.run_id} is owned by another worker")
            activation_key = (source.run_id, source.fence_token)
            existing_activation = _validated_cached_activation(
                self._activation_events.get(activation_key)
            )
            if source.status == "running" and existing_activation is not None:
                return existing_activation
            expected_rule_set = _rule_set_expected_state_from_source(source)
            expected_status = source.status
            expected_started_at = source.started_at
            started_at = utc_now() if expected_started_at is None else expected_started_at
            _require_exact_timestamp(started_at)
            activation_created_at = utc_now()
            _require_exact_timestamp(activation_created_at)
            activation_transport = LiveEvent(
                id=source.next_event_id,
                type="run_recovered" if expected_started_at is not None else "run_started",
                run_id=source.run_id,
                session_id=source.session_id,
                created_at=activation_created_at,
                payload=(
                    {"fence_token": source.fence_token} if expected_started_at is not None else None
                ),
            )
            expected_state = _activation_expected_state(
                source,
                activation=activation_transport,
                started_at=started_at,
            )
            local_activation_carrier = _clone_activation_expected_event(
                tuple.__getitem__(expected_state.events, -1)
            )
            runs_container = self._runs
            activation_events_container = self._activation_events
            if (
                type(runs_container) is not dict
                or dict.get(runs_container, source.run_id) is not run
                or type(activation_events_container) is not dict
            ):
                _raise_invalid_exact_json_value()
            runs_snapshot = dict.copy(runs_container)
            activation_events_snapshot = dict.copy(activation_events_container)
            activation_cache_event_indexes = _capture_activation_cache_event_indexes(
                activation_events_snapshot,
                run_id=source.run_id,
                events_container=source.events_container,
                expected_events=tuple(expected_state.events[:-1]),
            )
            try:
                self._persist_activation_locked(
                    run,
                    source=source,
                    registry_worker_id=registry_worker_id,
                    expected_rule_set=expected_rule_set,
                    expected_status=expected_status,
                    expected_started_at=expected_started_at,
                    activation=activation_transport,
                    started_at=started_at,
                )
            except Exception as activation_error:
                if not self._activation_was_committed_locked(
                    expected_state,
                    registry_worker_id=registry_worker_id,
                ):
                    try:
                        _restore_rejected_activation_state(
                            run,
                            source=source,
                            expected_state=expected_state,
                        )
                        if isinstance(activation_error, RunLeaseUnavailable) and not isinstance(
                            activation_error,
                            RunRuleSetMismatch,
                        ):
                            object.__setattr__(run, "lease_lost", True)
                        object.__setattr__(self, "_runs", runs_container)
                        dict.clear(runs_container)
                        dict.update(runs_container, runs_snapshot)
                        object.__setattr__(self, "_activation_events", activation_events_container)
                        _restore_activation_cache_snapshot(
                            activation_events_container,
                            snapshot=activation_events_snapshot,
                            event_indexes=activation_cache_event_indexes,
                            events_container=source.events_container,
                        )
                    except Exception:
                        pass
                    raise
            local_activation = _live_event_from_expected_event(local_activation_carrier)
            try:
                registry_continuity_preserved = (
                    self._runs is runs_container
                    and dict.get(runs_container, source.run_id) is run
                    and self._activation_events is activation_events_container
                )
            except Exception:
                registry_continuity_preserved = False
            if registry_continuity_preserved and _activation_source_continuity_preserved(
                run,
                source=source,
                expected_state=expected_state,
            ):
                object.__setattr__(run, "status", "running")
                object.__setattr__(run, "started_at", started_at)
                object.__setattr__(run, "lease_lost", False)
                object.__setattr__(
                    run,
                    "rule_set_was_sql_null",
                    expected_state.rule_set_was_sql_null,
                )
                object.__setattr__(run, "next_event_id", expected_state.next_event_id)
                list.append(source.events_container, local_activation)
            else:
                _restore_committed_activation_state(
                    run,
                    source=source,
                    expected_state=expected_state,
                    local_activation=local_activation,
                )
            object.__setattr__(self, "_runs", runs_container)
            dict.clear(runs_container)
            dict.update(runs_container, runs_snapshot)
            dict.__setitem__(runs_container, source.run_id, run)
            object.__setattr__(self, "_activation_events", activation_events_container)
            _restore_activation_cache_snapshot(
                activation_events_container,
                snapshot=activation_events_snapshot,
                event_indexes=activation_cache_event_indexes,
                events_container=source.events_container,
            )
            dict.__setitem__(activation_events_container, activation_key, local_activation)
            for subscriber in source.subscribers:
                subscriber.put(local_activation)
            return local_activation

    def mark_completed(
        self,
        run_id: str,
        *,
        winner: str,
        p2_diagnostics: dict[str, Any] | None = None,
        terminal_keep_from_event_id: int | None = None,
    ) -> LiveEvent:
        with self._lock:
            run = self._runs[run_id]
            existing_completion = next(
                (event for event in reversed(run.events) if event.type == "game_completed"),
                None,
            )
            if existing_completion is not None:
                existing_payload = existing_completion.payload
                if existing_payload.get("winner") != winner:
                    raise ValueError("game_completed winner cannot change")
                existing_keep = existing_payload.get("terminal_keep_from_event_id")
                if (
                    terminal_keep_from_event_id is not None
                    and existing_keep != terminal_keep_from_event_id
                ):
                    raise ValueError("game_completed terminal boundary cannot change")
                run.status = "completed"
                run.winner = winner
                if p2_diagnostics is not None:
                    run.p2_diagnostics = _copy_json_payload(p2_diagnostics)
                run.completed_at = run.completed_at or existing_completion.created_at
                run.lease_expires_at = None
                run.recovery_last_error = None
                self._persist_run_locked(run, raise_on_error=True)
                return existing_completion
            if terminal_keep_from_event_id is not None:
                _require_exact_int(terminal_keep_from_event_id)
                if not 1 <= terminal_keep_from_event_id <= run.next_event_id:
                    raise ValueError(
                        "terminal_keep_from_event_id must identify an event no later "
                        "than game_completed"
                    )
            previous_terminal_state = (
                run.status,
                run.winner,
                _copy_json_payload(run.p2_diagnostics),
                run.completed_at,
                run.lease_expires_at,
                run.recovery_last_error,
            )
            run.status = "completed"
            run.winner = winner
            if p2_diagnostics is not None:
                run.p2_diagnostics = _copy_json_payload(p2_diagnostics)
            run.completed_at = utc_now()
            run.lease_expires_at = None
            run.recovery_last_error = None
            try:
                completion = self._publish_locked(
                    run,
                    "game_completed",
                    payload={
                        "winner": winner,
                        **(
                            {
                                "terminal_keep_from_event_id": terminal_keep_from_event_id,
                            }
                            if terminal_keep_from_event_id is not None
                            else {}
                        ),
                    },
                    raise_on_persist_error=True,
                )
            except Exception:
                (
                    run.status,
                    run.winner,
                    run.p2_diagnostics,
                    run.completed_at,
                    run.lease_expires_at,
                    run.recovery_last_error,
                ) = previous_terminal_state
                raise
            self._persist_run_locked(run, raise_on_error=True)
            return completion

    def mark_failed(self, run_id: str, *, error: str) -> LiveEvent:
        with self._lock:
            run = self._runs[run_id]
            run.status = "failed"
            run.error = error
            run.completed_at = utc_now()
            run.lease_expires_at = None
            if run.recovery_attempts > 0:
                run.recovery_last_error = error
            self._persist_run_locked(run)
            if run.status != "failed":
                return self._publish_terminal_state_locked(run)
            return self._publish_locked(
                run,
                "game_failed",
                payload={"error": error},
            )

    def mark_failed_durably(self, run_id: str, *, error: str) -> LiveEvent:
        _require_exact_str(run_id)
        _require_exact_str(error)
        with self._lock:
            registry_worker_id = self.worker_id
            _require_exact_str(registry_worker_id)
            run = dict.__getitem__(self._runs, run_id)
            source = _capture_activation_source_state(run)
            if (
                source.run_id != run_id
                or source.status not in {"queued", "running"}
                or source.worker_id != registry_worker_id
                or source.fence_token <= 0
                or source.stop_requested_at is not None
                or not _activation_source_has_current_lease(
                    source,
                    registry_worker_id=registry_worker_id,
                    has_live_store=True,
                )
            ):
                raise RunLeaseUnavailable(f"Run {run_id} durable failure was rejected by its lease")
            failer = getattr(self._live_store, "fail_run", None)
            verifier = getattr(self._live_store, "failure_was_committed", None)
            if not callable(failer) or not callable(verifier):
                raise RuntimeError(
                    "Persistent live store does not support atomic durable failure persistence"
                )
            completed_at = utc_now()
            failure_transport = LiveEvent(
                id=source.next_event_id,
                type="game_failed",
                run_id=source.run_id,
                session_id=source.session_id,
                created_at=completed_at,
                payload={"error": error},
            )
            expected_state = _failure_expected_state(
                source,
                failure=failure_transport,
                completed_at=completed_at,
                error=error,
            )
            failure_carrier = _clone_activation_expected_event(expected_state.events[-1])
            expected_rule_set = _rule_set_expected_state_from_source(source)
            runs_container = self._runs
            activation_events_container = self._activation_events
            if (
                type(runs_container) is not dict
                or dict.get(runs_container, source.run_id) is not run
                or type(activation_events_container) is not dict
            ):
                _raise_invalid_exact_json_value()
            runs_snapshot = dict.copy(runs_container)
            activation_events_snapshot = dict.copy(activation_events_container)
            activation_cache_event_indexes = _capture_activation_cache_event_indexes(
                activation_events_snapshot,
                run_id=source.run_id,
                events_container=source.events_container,
                expected_events=source.events,
            )
            try:
                failer(
                    source.run_id,
                    expected_events=source.events,
                    expected_rule_set=clone_rule_set_expected_state(expected_rule_set),
                    expected_status=source.status,
                    failure=_live_event_from_expected_event(failure_carrier),
                    worker_id=registry_worker_id,
                    fence_token=source.fence_token,
                    completed_at=completed_at,
                    error=error,
                )
            except Exception:
                if not self._failure_was_committed_locked(
                    expected_state,
                    registry_worker_id=registry_worker_id,
                ):
                    try:
                        _restore_rejected_activation_state(
                            run,
                            source=source,
                            expected_state=expected_state,
                        )
                        object.__setattr__(self, "_runs", runs_container)
                        dict.clear(runs_container)
                        dict.update(runs_container, runs_snapshot)
                        object.__setattr__(
                            self,
                            "_activation_events",
                            activation_events_container,
                        )
                        _restore_activation_cache_snapshot(
                            activation_events_container,
                            snapshot=activation_events_snapshot,
                            event_indexes=activation_cache_event_indexes,
                            events_container=source.events_container,
                        )
                    except Exception:
                        pass
                    raise
            local_failure = _live_event_from_expected_event(failure_carrier)
            _restore_committed_activation_state(
                run,
                source=source,
                expected_state=expected_state,
                local_activation=local_failure,
                rule_set_was_sql_null=source.rule_set_was_sql_null,
            )
            object.__setattr__(self, "_runs", runs_container)
            dict.clear(runs_container)
            dict.update(runs_container, runs_snapshot)
            dict.__setitem__(runs_container, source.run_id, run)
            object.__setattr__(self, "_activation_events", activation_events_container)
            _restore_activation_cache_snapshot(
                activation_events_container,
                snapshot=activation_events_snapshot,
                event_indexes=activation_cache_event_indexes,
                events_container=source.events_container,
            )
            for subscriber in source.subscribers:
                subscriber.put(local_failure)
            return local_failure

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

    def raise_if_stop_requested(
        self,
        run_id: str,
        *,
        expected_fence_token: int | None = None,
    ) -> None:
        with self._lock:
            run = self._runs[run_id]
            self._raise_if_fence_changed_locked(run, expected_fence_token)
            self._raise_if_stop_requested_locked(run)

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

    @staticmethod
    def _raise_if_not_startable_locked(run: LiveGameRun) -> None:
        if run.status not in {"queued", "running"}:
            raise ValueError(f"Run {run.run_id} is not active")

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
            event_count = len(run.events)
            next_event_id = run.next_event_id
            try:
                self._publish_locked(
                    run,
                    "run_stop_requested",
                    payload={"requested_at": requested_at},
                )
            except RunLeaseUnavailable:
                del run.events[event_count:]
                run.next_event_id = next_event_id
                return True
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
        expected_fence_token: int | None = None,
    ) -> LiveEvent:
        with self._lock:
            run = self._runs[run_id]
            if run.status in {"completed", "failed", "canceled"}:
                raise RunLeaseUnavailable(f"Run {run_id} is terminal and cannot publish events")
            self._raise_if_fence_changed_locked(run, expected_fence_token)
            return self._publish_locked(
                run,
                event_type,
                round_number=round_number,
                phase=phase,
                actor=actor,
                action=action,
                payload=payload,
            )

    def publish_lifecycle(
        self,
        run_id: str,
        event_type: str,
        *,
        round_number: int,
        phase: str,
        actor: str | None = None,
        action: str | None = None,
        payload: dict[str, Any],
        expected_fence_token: int | None = None,
    ) -> LiveEvent:
        if event_type not in {"phase_started", "phase_completed"}:
            raise ValueError("Lifecycle publication requires a lifecycle event type")
        phase_instance_id = payload.get("phase_instance_id")
        if not isinstance(phase_instance_id, str) or not phase_instance_id:
            raise ValueError("Lifecycle publication requires a phase instance id")
        with self._lock:
            run = self._runs[run_id]
            if run.status in {"completed", "failed", "canceled"}:
                raise RunLeaseUnavailable(
                    f"Run {run_id} is terminal and cannot publish events"
                )
            self._raise_if_fence_changed_locked(run, expected_fence_token)
            matches = [
                event
                for event in run.events
                if event.type == event_type
                and event.payload.get("phase_instance_id") == phase_instance_id
            ]
            if len(matches) > 1:
                raise ValueError("Lifecycle event identity is not unique")
            if matches:
                existing = matches[0]
                if (
                    existing.round != round_number
                    or existing.phase != phase
                    or existing.actor != actor
                    or existing.action != action
                    or not strict_json_equal(existing.payload, payload)
                ):
                    raise ValueError("Lifecycle event identity conflicts with persisted data")
                return existing
            if event_type == "phase_completed":
                matching_start = [
                    event
                    for event in run.events
                    if event.type == "phase_started"
                    and event.payload.get("phase_instance_id") == phase_instance_id
                ]
                if len(matching_start) != 1:
                    raise ValueError("Lifecycle completion has no unique start event")
                if payload.get("source_event_id") != matching_start[0].id:
                    raise ValueError("Lifecycle completion source event does not match")
            return self._publish_locked(
                run,
                event_type,
                round_number=round_number,
                phase=phase,
                actor=actor,
                action=action,
                payload=payload,
                raise_on_persist_error=True,
            )

    @staticmethod
    def _raise_if_fence_changed_locked(
        run: LiveGameRun,
        expected_fence_token: int | None,
    ) -> None:
        if expected_fence_token is not None and run.fence_token != expected_fence_token:
            raise RunLeaseUnavailable("Live run fencing token was superseded")

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

    def projected_events_after(
        self,
        run_id: str,
        *,
        audience: Literal["player_public", "spectator_god_view"],
        after_id: int | None = None,
    ) -> list[ProjectedLiveEvent]:
        from app.werewolf.privacy_projection import project_live_event

        with self._lock:
            run = self._runs.get(run_id)
            if run is not None:
                events = (
                    list(run.events)
                    if after_id is None
                    else [event for event in run.events if event.id > after_id]
                )
                return [
                    projected
                    for event in events
                    if (projected := project_live_event(event, audience)) is not None
                ]
        loader = getattr(self._live_store, "projected_events_after", None)
        if not callable(loader):
            raise KeyError(run_id)
        return loader(run_id, audience=audience, after_id=after_id)

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
        raise_on_persist_error: bool = False,
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
        try:
            self._persist_event_locked(
                run,
                event,
                raise_on_error=raise_on_persist_error,
            )
        except Exception:
            if run.events and run.events[-1] is event:
                run.events.pop()
                run.next_event_id -= 1
            raise
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
            except RunLeaseUnavailable:
                run.lease_lost = True
                raise
            except Exception:
                logger.exception("Failed to persist live run %s", run.run_id)
                if raise_on_error:
                    raise

    def _persist_new_run_locked(self, run: LiveGameRun) -> None:
        if self._live_store is None:
            return
        saver = getattr(self._live_store, "save_new_run", None)
        if not callable(saver):
            raise RuntimeError("Persistent live store does not support atomic new-run persistence")
        try:
            saver(run)
        except Exception:
            logger.error(
                "live_run_initial_persistence_failed run_id=%s",
                run.run_id,
                extra={
                    "event_code": "live_run_initial_persistence_failed",
                    "run_id": run.run_id,
                },
            )
            raise

    def _persist_activation_locked(
        self,
        run: LiveGameRun,
        *,
        source: RunActivationSourceState,
        registry_worker_id: str,
        expected_rule_set: RunRuleSetExpectedState,
        expected_status: str,
        expected_started_at: str | None,
        activation: LiveEvent,
        started_at: str,
    ) -> None:
        if self._live_store is None:
            return
        activator = getattr(self._live_store, "activate_run", None)
        _require_unchanged_registry_worker_id(
            self.worker_id,
            captured=registry_worker_id,
        )
        if not callable(activator):
            raise RuntimeError(
                "Persistent live store does not support atomic activation persistence"
            )
        _require_unchanged_registry_worker_id(
            self.worker_id,
            captured=registry_worker_id,
        )
        try:
            activator(
                source.run_id,
                expected_events=source.events,
                expected_rule_set=expected_rule_set,
                expected_status=expected_status,
                expected_started_at=expected_started_at,
                activation=activation,
                worker_id=registry_worker_id,
                fence_token=source.fence_token,
                started_at=started_at,
            )
        except RunRuleSetMismatch:
            raise
        except RunLeaseUnavailable:
            run.lease_lost = True
            raise
        except Exception:
            try:
                _require_unchanged_registry_worker_id(
                    self.worker_id,
                    captured=registry_worker_id,
                )
            except Exception:
                pass
            raise
        _require_unchanged_registry_worker_id(
            self.worker_id,
            captured=registry_worker_id,
        )

    def _activation_was_committed_locked(
        self,
        expected_state: RunActivationExpectedState,
        *,
        registry_worker_id: str,
    ) -> bool:
        try:
            verifier = getattr(self._live_store, "activation_was_committed", None)
            _require_unchanged_registry_worker_id(
                self.worker_id,
                captured=registry_worker_id,
            )
            if not callable(verifier):
                return False
            committed = verifier(clone_run_expected_state(expected_state)) is True
            _require_unchanged_registry_worker_id(
                self.worker_id,
                captured=registry_worker_id,
            )
            return committed
        except Exception:
            return False

    def _failure_was_committed_locked(
        self,
        expected_state: RunActivationExpectedState,
        *,
        registry_worker_id: str,
    ) -> bool:
        try:
            verifier = getattr(self._live_store, "failure_was_committed", None)
            _require_unchanged_registry_worker_id(
                self.worker_id,
                captured=registry_worker_id,
            )
            if not callable(verifier):
                return False
            committed = verifier(clone_run_expected_state(expected_state)) is True
            _require_unchanged_registry_worker_id(
                self.worker_id,
                captured=registry_worker_id,
            )
            return committed
        except Exception:
            return False

    def _persist_event_locked(
        self,
        run: LiveGameRun,
        event: LiveEvent,
        *,
        raise_on_error: bool = False,
    ) -> None:
        if self._live_store is not None:
            try:
                self._live_store.append_event(
                    event,
                    worker_id=run.worker_id or self.worker_id,
                    fence_token=run.fence_token,
                )
            except RunLeaseUnavailable:
                run.lease_lost = True
                raise
            except Exception:
                logger.exception(
                    "Failed to persist live event %s for run %s",
                    event.id,
                    event.run_id,
                )
                if raise_on_error:
                    raise

    def _supports_store_method(self, method_name: str) -> bool:
        return callable(getattr(self._live_store, method_name, None))

    def _load_persisted_run(self, run_id: str) -> LiveGameRun | None:
        loader = getattr(self._live_store, "load_run", None)
        return loader(run_id) if callable(loader) else None

    def _load_persisted_active_run(self, session_id: str) -> LiveGameRun | None:
        loader = getattr(self._live_store, "active_run_for_session", None)
        return loader(session_id) if callable(loader) else None

    def _load_complete_persisted_run(
        self,
        run_id: str,
        *,
        require_active: bool = True,
    ) -> LiveGameRun | None:
        return self._hydrate_complete_persisted_run(
            self._load_persisted_run(run_id),
            require_active=require_active,
        )

    def _load_complete_persisted_active_run(self, session_id: str) -> LiveGameRun | None:
        return self._hydrate_complete_persisted_run(self._load_persisted_active_run(session_id))

    def _recover_committed_prepared_run(
        self,
        candidate: LiveGameRun,
    ) -> tuple[Literal["absent", "recovered", "unsafe"], LiveGameRun | None]:
        try:
            persisted = self._load_persisted_run(candidate.run_id)
        except Exception:
            return "unsafe", None
        if persisted is None:
            return "absent", None
        persisted = self._hydrate_complete_persisted_run(
            persisted,
            require_prepared=True,
        )
        if persisted is None or not _prepared_runs_match(persisted, candidate):
            return "unsafe", None
        try:
            self.attach_prepared_run(persisted)
        except Exception:
            return "unsafe", None
        return "recovered", persisted

    def _complete_local_active_run_locked(self, session_id: str) -> LiveGameRun | None:
        return self._complete_local_run_locked(
            self._active_run_for_session_locked(session_id),
            require_active=True,
        )

    def _complete_local_run_locked(
        self,
        run: LiveGameRun | None,
        *,
        require_active: bool,
    ) -> LiveGameRun | None:
        if run is None:
            return None
        if require_active and run.status not in {"queued", "running"}:
            return None
        if run.events:
            return run
        return self._hydrate_complete_persisted_run(
            run,
            require_active=require_active,
        )

    def _hydrate_complete_persisted_run(
        self,
        run: LiveGameRun | None,
        *,
        require_prepared: bool = False,
        require_active: bool = True,
    ) -> LiveGameRun | None:
        if run is None:
            return None
        try:
            events = run.events
            if not events:
                loader = getattr(self._live_store, "events_after", None)
                if not callable(loader):
                    return None
                events = list(loader(run.run_id))
                run.events = events
            if (
                not events
                or run.event_count != len(events)
                or [event.id for event in events] != list(range(1, len(events) + 1))
                or any(
                    event.run_id != run.run_id or event.session_id != run.session_id
                    for event in events
                )
                or events[0].type != "run_created"
                or run.next_event_id != events[-1].id + 1
            ):
                return None
            if require_prepared:
                validate_prepared_run(run)
            elif require_active and run.status not in {"queued", "running"}:
                return None
        except Exception:
            return None
        return run

    def _lease_window(self) -> tuple[str, str]:
        heartbeat_at = datetime.now(tz=UTC)
        lease_expires_at = heartbeat_at + timedelta(seconds=self.lease_seconds)
        return _format_datetime(heartbeat_at), _format_datetime(lease_expires_at)

    def _acquire_lease(
        self,
        run_id: str,
        *,
        expected_events: tuple[LiveEvent | RunActivationExpectedEvent, ...],
        expected_rule_set: RunRuleSetExpectedState,
        worker_id: str,
    ) -> RunLeaseState | None:
        _require_exact_str(worker_id)
        acquire = getattr(self._live_store, "acquire_lease", None)
        _require_unchanged_registry_worker_id(
            self.worker_id,
            captured=worker_id,
        )
        if not callable(acquire):
            return None
        heartbeat_at, lease_expires_at = self._lease_window()
        state = acquire(
            run_id,
            expected_events=expected_events,
            expected_rule_set=clone_rule_set_expected_state(expected_rule_set),
            worker_id=worker_id,
            heartbeat_at=heartbeat_at,
            lease_expires_at=lease_expires_at,
        )
        _require_unchanged_registry_worker_id(
            self.worker_id,
            captured=worker_id,
        )
        return state

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
        with self._lock:
            fence_token = self._runs[run_id].fence_token
        state = heartbeat(
            run_id,
            worker_id=self.worker_id,
            heartbeat_at=heartbeat_at,
            lease_expires_at=lease_expires_at,
            fence_token=fence_token,
        )
        with self._lock:
            run = self._runs.get(run_id)
            if run is None:
                return state
            if state is None:
                run.lease_lost = True
                return None
            if state.status in {"queued", "running"} and state.worker_id != self.worker_id:
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
        run.fence_token = state.fence_token
        run.recovery_attempts = state.recovery_attempts
        run.recovery_last_attempt_at = state.recovery_last_attempt_at
        run.recovery_not_before = state.recovery_not_before
        run.recovery_last_error = state.recovery_last_error
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
                                    {"winner": run.winner} if run.status == "completed" else {}
                                ),
                            )
                        )
                        return
        finally:
            with self._lock:
                self._persistent_subscriptions.pop(id(subscriber), None)


def _activation_expected_state(
    source: RunActivationSourceState,
    *,
    activation: LiveEvent,
    started_at: str,
) -> RunActivationExpectedState:
    fields = _strict_json_snapshot(source.fields)
    timestamps = _strict_json_snapshot(source.timestamps)
    if type(fields) is not dict or type(timestamps) is not dict:
        _raise_invalid_exact_json_value()
    dict.__setitem__(fields, "status", "running")
    dict.__setitem__(timestamps, "started_at", started_at)
    events = tuple(_clone_activation_expected_event(event) for event in source.events) + (
        _activation_expected_event(activation),
    )
    if (
        fields.keys() != ACTIVATION_ACK_RUN_FIELD_NAMES
        or timestamps.keys() != ACTIVATION_ACK_RUN_TIMESTAMP_NAMES
    ):
        raise RuntimeError("Activation acknowledgement state inventory is incomplete")
    return RunActivationExpectedState(
        run_id=source.run_id,
        fields=fields,
        timestamps=timestamps,
        events=events,
        event_count=len(events),
        next_event_id=source.next_event_id + 1,
        rule_set_was_sql_null=False,
    )


def _failure_expected_state(
    source: RunActivationSourceState,
    *,
    failure: LiveEvent,
    completed_at: str,
    error: str,
) -> RunActivationExpectedState:
    fields = _strict_json_snapshot(source.fields)
    timestamps = _strict_json_snapshot(source.timestamps)
    if type(fields) is not dict or type(timestamps) is not dict:
        _raise_invalid_exact_json_value()
    dict.__setitem__(fields, "status", "failed")
    dict.__setitem__(fields, "error", error)
    dict.__setitem__(fields, "worker_id", None)
    dict.__setitem__(fields, "fence_token", source.fence_token + 1)
    dict.__setitem__(fields, "recovery_last_error", error)
    dict.__setitem__(timestamps, "completed_at", completed_at)
    dict.__setitem__(timestamps, "worker_heartbeat_at", None)
    dict.__setitem__(timestamps, "lease_expires_at", None)
    events = tuple(_clone_activation_expected_event(event) for event in source.events) + (
        _activation_expected_event(failure),
    )
    if (
        fields.keys() != ACTIVATION_ACK_RUN_FIELD_NAMES
        or timestamps.keys() != ACTIVATION_ACK_RUN_TIMESTAMP_NAMES
    ):
        raise RuntimeError("Failure acknowledgement state inventory is incomplete")
    return RunActivationExpectedState(
        run_id=source.run_id,
        fields=fields,
        timestamps=timestamps,
        events=events,
        event_count=len(events),
        next_event_id=source.next_event_id + 1,
        rule_set_was_sql_null=source.rule_set_was_sql_null,
    )


def clone_run_expected_state(value: object) -> RunActivationExpectedState:
    if type(value) is not RunActivationExpectedState:
        _raise_invalid_exact_json_value()
    _require_exact_str(value.run_id)
    _require_exact_int(value.event_count)
    _require_exact_int(value.next_event_id)
    if type(value.rule_set_was_sql_null) is not bool:
        _raise_invalid_exact_json_value()
    if type(value.fields) is not dict or type(value.timestamps) is not dict:
        _raise_invalid_exact_json_value()
    if type(value.events) is not tuple:
        _raise_invalid_exact_json_value()
    fields = _strict_json_snapshot(value.fields)
    timestamps = _strict_json_snapshot(value.timestamps)
    if type(fields) is not dict or type(timestamps) is not dict:
        _raise_invalid_exact_json_value()
    events = tuple(_clone_activation_expected_event(event) for event in value.events)
    if (
        fields.keys() != ACTIVATION_ACK_RUN_FIELD_NAMES
        or timestamps.keys() != ACTIVATION_ACK_RUN_TIMESTAMP_NAMES
        or value.event_count != len(events)
        or value.next_event_id != value.event_count + 1
    ):
        _raise_invalid_exact_json_value()
    return RunActivationExpectedState(
        run_id=value.run_id,
        fields=fields,
        timestamps=timestamps,
        events=events,
        event_count=value.event_count,
        next_event_id=value.next_event_id,
        rule_set_was_sql_null=value.rule_set_was_sql_null,
    )


def _capture_activation_source_state(run: object) -> RunActivationSourceState:
    if type(run) is not LiveGameRun:
        _raise_invalid_exact_json_value()
    _require_exact_str(run.run_id)
    _require_exact_str(run.session_id)
    _require_exact_str(run.status)
    _require_exact_str(run.villager_model)
    _require_exact_str(run.werewolf_model)
    _require_exact_optional_int(run.seed)
    _require_exact_int(run.max_rounds)
    _require_exact_optional_str(run.parent_run_id)
    _require_exact_optional_int(run.resume_from_round)
    _require_exact_int(run.attempt_no)
    if run.attempt_no <= 0 or (
        run.attempt_no == 1
        and (run.parent_run_id is not None or run.resume_from_round is not None)
    ):
        _raise_invalid_exact_json_value()
    if run.attempt_no > 1 and (
        run.parent_run_id is None
        or run.resume_from_round is None
        or run.resume_from_round <= 0
    ):
        _raise_invalid_exact_json_value()
    _require_exact_str(run.rule_set_id)
    _require_exact_optional_str(run.rule_set_revision_id)
    _require_exact_optional_int(run.rule_set_revision_no)
    _require_exact_optional_str(run.rule_set_content_hash)
    _require_exact_optional_str(run.winner)
    _require_exact_optional_str(run.error)
    _require_exact_optional_str(run.worker_id)
    _require_exact_int(run.control_version)
    _require_exact_int(run.fence_token)
    if run.fence_token < 0:
        _raise_invalid_exact_json_value()
    _require_exact_int(run.recovery_attempts)
    _require_exact_optional_str(run.recovery_last_error)
    _require_exact_int(run.next_event_id)
    _require_exact_int(run.persisted_event_count)
    if run.persisted_event_count < 0:
        _raise_invalid_exact_json_value()
    if type(run.lease_lost) is not bool:
        _raise_invalid_exact_json_value()
    if type(run.rule_set_was_sql_null) is not bool:
        _raise_invalid_exact_json_value()
    if type(run.rule_set) is not dict:
        _raise_invalid_exact_json_value()
    if type(run.player_configs) is not list:
        _raise_invalid_exact_json_value()
    if type(run.lineup_quality_warnings) is not list:
        _raise_invalid_exact_json_value()
    if type(run.lineup_quality_report) is not dict:
        _raise_invalid_exact_json_value()
    if type(run.p2_diagnostics) is not dict:
        _raise_invalid_exact_json_value()
    if type(run.events) is not list or type(run.subscribers) is not list:
        _raise_invalid_exact_json_value()

    raw_fields = {
        "run_id": run.run_id,
        "session_id": run.session_id,
        "status": run.status,
        "villager_model": run.villager_model,
        "werewolf_model": run.werewolf_model,
        "seed": run.seed,
        "max_rounds": run.max_rounds,
        "parent_run_id": run.parent_run_id,
        "resume_from_round": run.resume_from_round,
        "attempt_no": run.attempt_no,
        "rule_set_id": run.rule_set_id,
        "rule_set_revision_id": run.rule_set_revision_id,
        "rule_set_revision_no": run.rule_set_revision_no,
        "rule_set_content_hash": run.rule_set_content_hash,
        "rule_set": run.rule_set,
        "player_configs": run.player_configs,
        "lineup_quality_warnings": run.lineup_quality_warnings,
        "lineup_quality_report": run.lineup_quality_report,
        "p2_diagnostics": run.p2_diagnostics,
        "winner": run.winner,
        "error": run.error,
        "worker_id": run.worker_id,
        "control_version": run.control_version,
        "fence_token": run.fence_token,
        "recovery_attempts": run.recovery_attempts,
        "recovery_last_error": run.recovery_last_error,
    }
    fields = _strict_json_snapshot(raw_fields)
    if type(fields) is not dict:
        _raise_invalid_exact_json_value()

    timestamps = {
        "created_at": run.created_at,
        "started_at": run.started_at,
        "completed_at": run.completed_at,
        "stop_requested_at": run.stop_requested_at,
        "worker_heartbeat_at": run.worker_heartbeat_at,
        "lease_expires_at": run.lease_expires_at,
        "recovery_last_attempt_at": run.recovery_last_attempt_at,
        "recovery_not_before": run.recovery_not_before,
    }
    for name, value in dict.items(timestamps):
        if name == "created_at":
            _require_exact_timestamp(value)
        else:
            _require_exact_optional_timestamp(value)
    events = tuple(
        _activation_expected_event(list.__getitem__(run.events, index))
        for index in range(list.__len__(run.events))
    )
    subscribers: list[queue.Queue[LiveEvent]] = []
    for index in range(list.__len__(run.subscribers)):
        subscriber = list.__getitem__(run.subscribers, index)
        if type(subscriber) is not queue.Queue:
            _raise_invalid_exact_json_value()
        list.append(subscribers, subscriber)
    if (
        fields.keys() != ACTIVATION_ACK_RUN_FIELD_NAMES
        or timestamps.keys() != ACTIVATION_ACK_RUN_TIMESTAMP_NAMES
    ):
        raise RuntimeError("Activation acknowledgement state inventory is incomplete")
    return RunActivationSourceState(
        run_id=run.run_id,
        session_id=run.session_id,
        status=run.status,
        worker_id=run.worker_id,
        fence_token=run.fence_token,
        lease_lost=run.lease_lost,
        stop_requested_at=run.stop_requested_at,
        started_at=run.started_at,
        worker_heartbeat_at=run.worker_heartbeat_at,
        lease_expires_at=run.lease_expires_at,
        next_event_id=run.next_event_id,
        persisted_event_count=run.persisted_event_count,
        rule_set_was_sql_null=run.rule_set_was_sql_null,
        fields=fields,
        timestamps=timestamps,
        events=events,
        events_container=run.events,
        subscribers=tuple(subscribers),
        subscribers_container=run.subscribers,
    )


def _activation_source_continuity_preserved(
    run: object,
    *,
    source: RunActivationSourceState,
    expected_state: RunActivationExpectedState,
) -> bool:
    try:
        if (
            type(run) is not LiveGameRun
            or run.events is not source.events_container
            or run.subscribers is not source.subscribers_container
        ):
            return False
        current = _capture_activation_source_state(run)
        expected_events = tuple(expected_state.events[:-1])
        return bool(
            strict_json_equal(current.fields, source.fields)
            and strict_json_equal(current.timestamps, source.timestamps)
            and current.lease_lost is source.lease_lost
            and current.next_event_id == source.next_event_id
            and current.persisted_event_count == source.persisted_event_count
            and current.rule_set_was_sql_null is source.rule_set_was_sql_null
            and _activation_expected_events_equal(current.events, expected_events)
            and _subscriber_sequences_identical(current.subscribers, source.subscribers)
        )
    except Exception:
        return False


def _restore_committed_activation_state(
    run: object,
    *,
    source: RunActivationSourceState,
    expected_state: RunActivationExpectedState,
    local_activation: LiveEvent,
    rule_set_was_sql_null: bool = False,
) -> None:
    if type(run) is not LiveGameRun or type(local_activation) is not LiveEvent:
        _raise_invalid_exact_json_value()
    trusted = clone_run_expected_state(expected_state)
    fields = trusted.fields
    timestamps = trusted.timestamps
    for name, value in dict.items(fields):
        object.__setattr__(run, name, value)
    for name, value in dict.items(timestamps):
        object.__setattr__(run, name, value)

    expected_prefix = tuple(trusted.events[:-1])
    if _live_event_prefix_matches(source.events_container, expected_prefix):
        local_events = [
            list.__getitem__(source.events_container, index)
            for index in range(list.__len__(source.events_container))
        ]
    else:
        local_events = [_live_event_from_expected_event(event) for event in expected_prefix]
    list.append(local_events, local_activation)
    list.clear(source.events_container)
    list.extend(source.events_container, local_events)
    list.clear(source.subscribers_container)
    list.extend(source.subscribers_container, source.subscribers)

    object.__setattr__(run, "lease_lost", False)
    object.__setattr__(run, "persisted_event_count", source.persisted_event_count)
    object.__setattr__(run, "rule_set_was_sql_null", rule_set_was_sql_null)
    object.__setattr__(run, "events", source.events_container)
    object.__setattr__(run, "subscribers", source.subscribers_container)
    object.__setattr__(run, "next_event_id", trusted.next_event_id)


def _restore_rejected_activation_state(
    run: object,
    *,
    source: RunActivationSourceState,
    expected_state: RunActivationExpectedState,
) -> None:
    if type(run) is not LiveGameRun:
        _raise_invalid_exact_json_value()
    trusted = clone_run_expected_state(expected_state)
    fields = _strict_json_snapshot(source.fields)
    timestamps = _strict_json_snapshot(source.timestamps)
    if type(fields) is not dict or type(timestamps) is not dict:
        _raise_invalid_exact_json_value()
    for name, value in dict.items(fields):
        object.__setattr__(run, name, value)
    for name, value in dict.items(timestamps):
        object.__setattr__(run, name, value)

    expected_events = tuple(trusted.events[:-1])
    if _live_event_prefix_matches(source.events_container, expected_events):
        local_events = [
            list.__getitem__(source.events_container, index)
            for index in range(list.__len__(source.events_container))
        ]
    else:
        local_events = [_live_event_from_expected_event(event) for event in expected_events]
    list.clear(source.events_container)
    list.extend(source.events_container, local_events)
    list.clear(source.subscribers_container)
    list.extend(source.subscribers_container, source.subscribers)

    object.__setattr__(run, "lease_lost", source.lease_lost)
    object.__setattr__(run, "persisted_event_count", source.persisted_event_count)
    object.__setattr__(
        run,
        "rule_set_was_sql_null",
        source.rule_set_was_sql_null,
    )
    object.__setattr__(run, "events", source.events_container)
    object.__setattr__(run, "subscribers", source.subscribers_container)
    object.__setattr__(run, "next_event_id", source.next_event_id)


def _capture_activation_cache_event_indexes(
    snapshot: object,
    *,
    run_id: str,
    events_container: object,
    expected_events: object,
) -> dict[tuple[str, int], int]:
    if (
        type(snapshot) is not dict
        or type(events_container) is not list
        or type(expected_events) is not tuple
    ):
        _raise_invalid_exact_json_value()
    indexes: dict[tuple[str, int], int] = {}
    for key, value in dict.items(snapshot):
        if type(key) is not tuple or tuple.__len__(key) != 2:
            _raise_invalid_exact_json_value()
        cached_run_id = tuple.__getitem__(key, 0)
        cached_fence_token = tuple.__getitem__(key, 1)
        _require_exact_str(cached_run_id)
        _require_exact_int(cached_fence_token)
        if cached_fence_token < 0:
            _raise_invalid_exact_json_value()
        if cached_run_id != run_id:
            continue
        if type(value) is not LiveEvent:
            _raise_invalid_exact_json_value()
        event_index = next(
            (
                index
                for index in range(list.__len__(events_container))
                if list.__getitem__(events_container, index) is value
            ),
            None,
        )
        if event_index is None or event_index >= tuple.__len__(expected_events):
            _raise_invalid_exact_json_value()
        actual = _activation_expected_event(value)
        expected = tuple.__getitem__(expected_events, event_index)
        if not _activation_expected_events_equal((actual,), (expected,)):
            _raise_invalid_exact_json_value()
        dict.__setitem__(indexes, key, event_index)
    return indexes


def _restore_activation_cache_snapshot(
    container: object,
    *,
    snapshot: object,
    event_indexes: object,
    events_container: object,
) -> None:
    if (
        type(container) is not dict
        or type(snapshot) is not dict
        or type(event_indexes) is not dict
        or type(events_container) is not list
    ):
        _raise_invalid_exact_json_value()
    dict.clear(container)
    for key, value in dict.items(snapshot):
        if not dict.__contains__(event_indexes, key):
            dict.__setitem__(container, key, value)
    for key, event_index in dict.items(event_indexes):
        _require_exact_int(event_index)
        if event_index < 0 or event_index >= list.__len__(events_container):
            _raise_invalid_exact_json_value()
        event = list.__getitem__(events_container, event_index)
        if type(event) is not LiveEvent:
            _raise_invalid_exact_json_value()
        dict.__setitem__(container, key, event)


def _live_event_prefix_matches(
    events: object,
    expected: tuple[RunActivationExpectedEvent, ...],
) -> bool:
    try:
        if type(events) is not list or list.__len__(events) != tuple.__len__(expected):
            return False
        actual = tuple(
            _activation_expected_event(list.__getitem__(events, index))
            for index in range(list.__len__(events))
        )
        return _activation_expected_events_equal(actual, expected)
    except Exception:
        return False


def _activation_expected_events_equal(
    left: object,
    right: object,
) -> bool:
    if type(left) is not tuple or type(right) is not tuple:
        return False
    if tuple.__len__(left) != tuple.__len__(right):
        return False
    for index in range(tuple.__len__(left)):
        left_event = tuple.__getitem__(left, index)
        right_event = tuple.__getitem__(right, index)
        if (
            type(left_event) is not RunActivationExpectedEvent
            or type(right_event) is not RunActivationExpectedEvent
            or left_event.id != right_event.id
            or left_event.type != right_event.type
            or left_event.run_id != right_event.run_id
            or left_event.session_id != right_event.session_id
            or left_event.created_at != right_event.created_at
            or left_event.round != right_event.round
            or left_event.phase != right_event.phase
            or left_event.actor != right_event.actor
            or left_event.action != right_event.action
            or not strict_json_equal(left_event.payload, right_event.payload)
        ):
            return False
    return True


def _subscriber_sequences_identical(left: object, right: object) -> bool:
    if type(left) is not tuple or type(right) is not tuple:
        return False
    if tuple.__len__(left) != tuple.__len__(right):
        return False
    return all(
        tuple.__getitem__(left, index) is tuple.__getitem__(right, index)
        for index in range(tuple.__len__(left))
    )


def _raise_if_activation_source_not_startable(source: RunActivationSourceState) -> None:
    if source.lease_lost:
        raise RunLeaseUnavailable("Live run worker lease was lost")
    if source.stop_requested_at is not None:
        raise GameRunCanceled("Game run was canceled by an administrator")
    if source.status not in {"queued", "running"}:
        raise ValueError(f"Run {source.run_id} is not active")


def _activation_source_has_current_lease(
    source: RunActivationSourceState,
    *,
    registry_worker_id: str,
    has_live_store: bool,
) -> bool:
    return bool(
        source.worker_id == registry_worker_id
        and source.fence_token > 0
        and not source.lease_lost
        and (not has_live_store or not _lease_is_expired(source.lease_expires_at))
    )


def _validated_cached_activation(value: object | None) -> LiveEvent | None:
    if value is None:
        return None
    _activation_expected_event(value)
    return value


def _validated_activation_lease_state(
    value: object,
    *,
    registry_worker_id: str,
    expected_status: str,
    previous_fence_token: int,
) -> RunLeaseState:
    if type(value) is not RunLeaseState:
        _raise_invalid_exact_json_value()
    _require_exact_optional_str(value.worker_id)
    _require_exact_optional_timestamp(value.worker_heartbeat_at)
    _require_exact_optional_timestamp(value.lease_expires_at)
    _require_exact_optional_timestamp(value.stop_requested_at)
    _require_exact_str(value.status)
    _require_exact_int(value.control_version)
    _require_exact_int(value.fence_token)
    _require_exact_int(value.recovery_attempts)
    _require_exact_optional_timestamp(value.recovery_last_attempt_at)
    _require_exact_optional_timestamp(value.recovery_not_before)
    _require_exact_optional_str(value.recovery_last_error)
    if (
        value.worker_id != registry_worker_id
        or value.worker_heartbeat_at is None
        or value.lease_expires_at is None
        or value.status != expected_status
        or value.status not in {"queued", "running"}
        or value.control_version < 0
        or value.fence_token <= 0
        or value.fence_token <= previous_fence_token
        or value.recovery_attempts < 0
        or _lease_is_expired(value.lease_expires_at)
    ):
        _raise_invalid_exact_json_value()
    return RunLeaseState(
        worker_id=value.worker_id,
        worker_heartbeat_at=value.worker_heartbeat_at,
        lease_expires_at=value.lease_expires_at,
        stop_requested_at=value.stop_requested_at,
        status=value.status,
        control_version=value.control_version,
        fence_token=value.fence_token,
        recovery_attempts=value.recovery_attempts,
        recovery_last_attempt_at=value.recovery_last_attempt_at,
        recovery_not_before=value.recovery_not_before,
        recovery_last_error=value.recovery_last_error,
    )


def _activation_expected_event(event: object) -> RunActivationExpectedEvent:
    if type(event) is not LiveEvent:
        _raise_invalid_exact_json_value()
    _require_exact_int(event.id)
    if event.id <= 0:
        _raise_invalid_exact_json_value()
    _require_exact_str(event.type)
    _require_exact_str(event.run_id)
    _require_exact_str(event.session_id)
    _require_exact_str(event.created_at)
    _require_exact_optional_int(event.round)
    _require_exact_optional_str(event.phase)
    _require_exact_optional_str(event.actor)
    _require_exact_optional_str(event.action)
    if type(event._payload) is not dict:
        _raise_invalid_exact_json_value()
    try:
        _normalized_live_timestamp(event.created_at)
    except Exception:
        _raise_invalid_exact_json_value()
    payload = _strict_json_snapshot(event._payload)
    if type(payload) is not dict:
        _raise_invalid_exact_json_value()
    return RunActivationExpectedEvent(
        id=event.id,
        type=event.type,
        run_id=event.run_id,
        session_id=event.session_id,
        created_at=event.created_at,
        round=event.round,
        phase=event.phase,
        actor=event.actor,
        action=event.action,
        payload=payload,
    )


def _clone_activation_expected_event(event: object) -> RunActivationExpectedEvent:
    if type(event) is not RunActivationExpectedEvent:
        _raise_invalid_exact_json_value()
    _require_exact_int(event.id)
    if event.id <= 0:
        _raise_invalid_exact_json_value()
    _require_exact_str(event.type)
    _require_exact_str(event.run_id)
    _require_exact_str(event.session_id)
    _require_exact_timestamp(event.created_at)
    _require_exact_optional_int(event.round)
    _require_exact_optional_str(event.phase)
    _require_exact_optional_str(event.actor)
    _require_exact_optional_str(event.action)
    if type(event.payload) is not dict:
        _raise_invalid_exact_json_value()
    payload = _strict_json_snapshot(event.payload)
    if type(payload) is not dict:
        _raise_invalid_exact_json_value()
    return RunActivationExpectedEvent(
        id=event.id,
        type=event.type,
        run_id=event.run_id,
        session_id=event.session_id,
        created_at=event.created_at,
        round=event.round,
        phase=event.phase,
        actor=event.actor,
        action=event.action,
        payload=payload,
    )


def _live_event_from_expected_event(event: object) -> LiveEvent:
    cloned = _clone_activation_expected_event(event)
    local = object.__new__(LiveEvent)
    object.__setattr__(local, "id", cloned.id)
    object.__setattr__(local, "type", cloned.type)
    object.__setattr__(local, "run_id", cloned.run_id)
    object.__setattr__(local, "session_id", cloned.session_id)
    object.__setattr__(local, "created_at", cloned.created_at)
    object.__setattr__(local, "round", cloned.round)
    object.__setattr__(local, "phase", cloned.phase)
    object.__setattr__(local, "actor", cloned.actor)
    object.__setattr__(local, "action", cloned.action)
    object.__setattr__(local, "_payload", cloned.payload)
    return local


def clone_live_event(event: object) -> LiveEvent:
    return _live_event_from_expected_event(_activation_expected_event(event))


def clone_run_expected_events(
    events: object,
) -> tuple[RunActivationExpectedEvent, ...]:
    if type(events) is not tuple:
        _raise_invalid_exact_json_value()
    return tuple(
        _clone_activation_expected_event(tuple.__getitem__(events, index))
        for index in range(tuple.__len__(events))
    )


def _capture_rule_set_expected_state(run: object) -> RunRuleSetExpectedState:
    if type(run) is not LiveGameRun:
        _raise_invalid_exact_json_value()
    _require_exact_str(run.rule_set_id)
    _require_exact_optional_str(run.rule_set_revision_id)
    _require_exact_optional_int(run.rule_set_revision_no)
    _require_exact_optional_str(run.rule_set_content_hash)
    if type(run.rule_set) is not dict or type(run.rule_set_was_sql_null) is not bool:
        _raise_invalid_exact_json_value()
    snapshot = _strict_json_snapshot(run.rule_set)
    if type(snapshot) is not dict:
        _raise_invalid_exact_json_value()
    return RunRuleSetExpectedState(
        rule_set_id=run.rule_set_id,
        rule_set_revision_id=run.rule_set_revision_id,
        rule_set_revision_no=run.rule_set_revision_no,
        rule_set_content_hash=run.rule_set_content_hash,
        rule_set=snapshot,
        rule_set_was_sql_null=run.rule_set_was_sql_null,
    )


def _rule_set_expected_state_from_source(
    source: RunActivationSourceState,
) -> RunRuleSetExpectedState:
    if type(source) is not RunActivationSourceState:
        _raise_invalid_exact_json_value()
    fields = source.fields
    if type(fields) is not dict:
        _raise_invalid_exact_json_value()
    snapshot = dict.__getitem__(fields, "rule_set")
    if type(snapshot) is not dict:
        _raise_invalid_exact_json_value()
    return clone_rule_set_expected_state(
        RunRuleSetExpectedState(
            rule_set_id=dict.__getitem__(fields, "rule_set_id"),
            rule_set_revision_id=dict.__getitem__(fields, "rule_set_revision_id"),
            rule_set_revision_no=dict.__getitem__(fields, "rule_set_revision_no"),
            rule_set_content_hash=dict.__getitem__(fields, "rule_set_content_hash"),
            rule_set=snapshot,
            rule_set_was_sql_null=source.rule_set_was_sql_null,
        )
    )


def clone_rule_set_expected_state(value: object) -> RunRuleSetExpectedState:
    if type(value) is not RunRuleSetExpectedState:
        _raise_invalid_exact_json_value()
    _require_exact_str(value.rule_set_id)
    _require_exact_optional_str(value.rule_set_revision_id)
    _require_exact_optional_int(value.rule_set_revision_no)
    _require_exact_optional_str(value.rule_set_content_hash)
    if type(value.rule_set_was_sql_null) is not bool or type(value.rule_set) is not dict:
        _raise_invalid_exact_json_value()
    snapshot = _strict_json_snapshot(value.rule_set)
    if type(snapshot) is not dict:
        _raise_invalid_exact_json_value()
    return RunRuleSetExpectedState(
        rule_set_id=value.rule_set_id,
        rule_set_revision_id=value.rule_set_revision_id,
        rule_set_revision_no=value.rule_set_revision_no,
        rule_set_content_hash=value.rule_set_content_hash,
        rule_set=snapshot,
        rule_set_was_sql_null=value.rule_set_was_sql_null,
    )


def _require_exact_str(value: object) -> None:
    if type(value) is not str:
        _raise_invalid_exact_json_value()


def _require_unchanged_registry_worker_id(value: object, *, captured: str) -> None:
    _require_exact_str(value)
    if value != captured:
        _raise_invalid_exact_json_value()


def _require_exact_optional_str(value: object) -> None:
    if value is not None and type(value) is not str:
        _raise_invalid_exact_json_value()


def _require_exact_int(value: object) -> None:
    if type(value) is not int:
        _raise_invalid_exact_json_value()


def _require_exact_optional_int(value: object) -> None:
    if value is not None and type(value) is not int:
        _raise_invalid_exact_json_value()


def _require_exact_timestamp(value: object) -> None:
    _require_exact_str(value)
    try:
        _normalized_live_timestamp(value)
    except Exception:
        _raise_invalid_exact_json_value()


def _require_exact_optional_timestamp(value: object) -> None:
    if value is None:
        return
    _require_exact_timestamp(value)


def _strict_json_snapshot(value: object) -> object:
    memo: dict[int, tuple[object, int]] = {}
    active: set[int] = set()

    def walk(current: object, depth: int) -> tuple[object, int]:
        if depth > _STRICT_JSON_MAX_DEPTH:
            _raise_invalid_exact_json_value()
        value_type = type(current)
        if current is None:
            return None, 0
        if value_type is str or value_type is bool or value_type is int:
            return current, 0
        if value_type is float:
            if not math.isfinite(current):
                _raise_invalid_exact_json_value()
            return current, 0
        if value_type is not list and value_type is not dict:
            _raise_invalid_exact_json_value()

        identity = id(current)
        if identity in active:
            _raise_invalid_exact_json_value()
        memoized = memo.get(identity)
        if memoized is not None:
            clone, height = memoized
            if depth + height > _STRICT_JSON_MAX_DEPTH:
                _raise_invalid_exact_json_value()
            return clone, height

        active.add(identity)
        try:
            if value_type is list:
                clone_list: list[object] = []
                height = 0
                for index in range(list.__len__(current)):
                    child, child_height = walk(list.__getitem__(current, index), depth + 1)
                    list.append(clone_list, child)
                    height = max(height, child_height + 1)
                clone: object = clone_list
            else:
                clone_dict: dict[str, object] = {}
                height = 0
                for key, child_value in dict.items(current):
                    if type(key) is not str:
                        _raise_invalid_exact_json_value()
                    child, child_height = walk(child_value, depth + 1)
                    dict.__setitem__(clone_dict, key, child)
                    height = max(height, child_height + 1)
                clone = clone_dict
        finally:
            active.remove(identity)
        memo[identity] = (clone, height)
        return clone, height

    try:
        snapshot, _ = walk(value, 0)
        return snapshot
    except Exception:
        _raise_invalid_exact_json_value()


def _raise_invalid_exact_json_value() -> None:
    raise ValueError("invalid exact JSON value") from None


def _prepared_runs_match(persisted: LiveGameRun, candidate: LiveGameRun) -> bool:
    try:
        validate_prepared_run(candidate)
        return strict_json_equal(
            _raw_prepared_run_state(persisted),
            _raw_prepared_run_state(candidate),
        ) and _live_events_match(persisted.events[0], candidate.events[0])
    except Exception:
        return False


def _raw_prepared_run_state(run: LiveGameRun) -> dict[str, object]:
    return {
        "run_id": run.run_id,
        "session_id": run.session_id,
        "villager_model": run.villager_model,
        "werewolf_model": run.werewolf_model,
        "seed": run.seed,
        "max_rounds": run.max_rounds,
        "parent_run_id": run.parent_run_id,
        "resume_from_round": run.resume_from_round,
        "attempt_no": run.attempt_no,
        "rule_set_id": run.rule_set_id,
        "rule_set_revision_id": run.rule_set_revision_id,
        "rule_set_revision_no": run.rule_set_revision_no,
        "rule_set_content_hash": run.rule_set_content_hash,
        "rule_set": run.rule_set,
        "player_configs": run.player_configs,
        "lineup_quality_warnings": run.lineup_quality_warnings,
        "lineup_quality_report": run.lineup_quality_report,
        "p2_diagnostics": run.p2_diagnostics,
        "status": run.status,
        "created_at": run.created_at,
        "started_at": run.started_at,
        "completed_at": run.completed_at,
        "winner": run.winner,
        "error": run.error,
        "stop_requested_at": run.stop_requested_at,
        "event_count": run.event_count,
        "worker_id": run.worker_id,
        "worker_heartbeat_at": run.worker_heartbeat_at,
        "lease_expires_at": run.lease_expires_at,
        "control_version": run.control_version,
        "fence_token": run.fence_token,
        "recovery_attempts": run.recovery_attempts,
        "recovery_last_attempt_at": run.recovery_last_attempt_at,
        "recovery_not_before": run.recovery_not_before,
        "recovery_last_error": run.recovery_last_error,
        "lease_lost": run.lease_lost,
        "next_event_id": run.next_event_id,
    }


def _live_events_match(persisted: LiveEvent, candidate: LiveEvent) -> bool:
    try:
        persisted_created_at = _normalized_live_timestamp(persisted.created_at)
        candidate_created_at = _normalized_live_timestamp(candidate.created_at)
    except (AttributeError, TypeError, ValueError):
        return False
    persisted_fields = {
        "id": persisted.id,
        "type": persisted.type,
        "run_id": persisted.run_id,
        "session_id": persisted.session_id,
        "round": persisted.round,
        "phase": persisted.phase,
        "actor": persisted.actor,
        "action": persisted.action,
        "payload": persisted._payload,
    }
    candidate_fields = {
        "id": candidate.id,
        "type": candidate.type,
        "run_id": candidate.run_id,
        "session_id": candidate.session_id,
        "round": candidate.round,
        "phase": candidate.phase,
        "actor": candidate.actor,
        "action": candidate.action,
        "payload": candidate._payload,
    }
    return persisted_created_at == candidate_created_at and strict_json_equal(
        persisted_fields,
        candidate_fields,
    )


def _normalized_live_timestamp(value: str) -> str:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return _format_datetime(parsed)


def validate_prepared_run(run: LiveGameRun) -> None:
    if run.status != "queued" or run.started_at is not None or run.completed_at is not None:
        raise ValueError(f"Run {run.run_id} is not a fresh prepared run")
    if len(run.events) != 1 or run.next_event_id != 2:
        raise ValueError(f"Run {run.run_id} must contain exactly one initial event")
    event = run.events[0]
    if (
        event.id != 1
        or event.type != "run_created"
        or event.run_id != run.run_id
        or event.session_id != run.session_id
    ):
        raise ValueError(f"Run {run.run_id} has an invalid initial event")


class EventSink:
    def __init__(
        self,
        registry: LiveRunRegistry,
        run_id: str,
        *,
        fence_token: int | None = None,
    ) -> None:
        self.registry = registry
        self.run_id = run_id
        self.fence_token = fence_token

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
        self.registry.raise_if_stop_requested(
            self.run_id,
            expected_fence_token=self.fence_token,
        )
        return self.registry.publish(
            self.run_id,
            event_type,
            round_number=round_number,
            phase=phase,
            actor=actor,
            action=action,
            payload=payload,
            expected_fence_token=self.fence_token,
        )

    def publish_lifecycle(
        self,
        event_type: str,
        *,
        round_number: int,
        phase: str,
        actor: str | None = None,
        action: str | None = None,
        payload: dict[str, Any],
    ) -> LiveEvent:
        self.registry.raise_if_stop_requested(
            self.run_id,
            expected_fence_token=self.fence_token,
        )
        return self.registry.publish_lifecycle(
            self.run_id,
            event_type,
            round_number=round_number,
            phase=phase,
            actor=actor,
            action=action,
            payload=payload,
            expected_fence_token=self.fence_token,
        )

    def lifecycle_events(self) -> list[LiveEvent]:
        return [
            event
            for event in self.registry.events_after(self.run_id)
            if event.type in {"phase_started", "phase_completed"}
            and isinstance(event.payload.get("phase_instance_id"), str)
        ]


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


def format_sse(event: ProjectedLiveEvent) -> str:
    if not isinstance(event, ProjectedLiveEvent):
        raise TypeError("SSE serialization requires an audience-projected event")
    data = json.dumps(event.to_dict(), ensure_ascii=False)
    return f"id: {event.id}\nevent: {event.type}\ndata: {data}\n\n"


def _copy_json_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return json.loads(json.dumps(payload, ensure_ascii=False))


def strict_json_equal(left: object, right: object) -> bool:
    try:
        return _strict_json_equal(left, right, active_pairs=set(), depth=0)
    except Exception:
        return False


def _strict_json_equal(
    left: object,
    right: object,
    *,
    active_pairs: set[tuple[int, int]],
    depth: int,
) -> bool:
    if depth > _STRICT_JSON_MAX_DEPTH:
        return False
    if type(left) is not type(right):
        return False
    value_type = type(left)
    if left is None:
        return True
    if value_type is str or value_type is bool or value_type is int:
        return left == right
    if value_type is float:
        return math.isfinite(left) and math.isfinite(right) and left == right
    if value_type is list:
        pair = (id(left), id(right))
        if pair in active_pairs:
            return False
        active_pairs.add(pair)
        try:
            return len(left) == len(right) and all(
                _strict_json_equal(
                    left_item,
                    right_item,
                    active_pairs=active_pairs,
                    depth=depth + 1,
                )
                for left_item, right_item in zip(left, right, strict=True)
            )
        finally:
            active_pairs.remove(pair)
    if value_type is dict:
        if any(type(key) is not str for key in left) or any(type(key) is not str for key in right):
            return False
        pair = (id(left), id(right))
        if pair in active_pairs:
            return False
        active_pairs.add(pair)
        try:
            return left.keys() == right.keys() and all(
                _strict_json_equal(
                    left[key],
                    right[key],
                    active_pairs=active_pairs,
                    depth=depth + 1,
                )
                for key in left
            )
        finally:
            active_pairs.remove(pair)
    return False


def _lease_is_expired(value: str | None) -> bool:
    if value is None:
        return True
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC) <= datetime.now(tz=UTC)
