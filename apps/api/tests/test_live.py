from __future__ import annotations

import copy
import json
import logging
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy.exc import IntegrityError

from app.werewolf import live as live_module
from app.werewolf.live import (
    GameRunCanceled,
    LiveEvent,
    LiveGameRun,
    LiveRunRegistry,
    RunLeaseState,
    RunLeaseUnavailable,
    format_sse,
    strict_json_equal,
)
from app.werewolf.player_configs import PlayerConfig


def classic_rule_kwargs() -> dict:
    return {
        "rule_set_id": "classic_8",
        "rule_set": {
            "id": "classic_8",
            "version": "2026.04",
            "name": "经典 8 人局",
            "player_count": 8,
            "roles": [],
        },
    }


def managed_rule_kwargs() -> dict:
    kwargs = classic_rule_kwargs()
    kwargs["rule_set"].update(
        {
            "revision_id": "revision-2",
            "revision_no": 2,
            "schema_version": 1,
            "content_hash": "a" * 64,
        }
    )
    kwargs.update(
        {
            "rule_set_revision_id": "revision-2",
            "rule_set_revision_no": 2,
            "rule_set_content_hash": "a" * 64,
        }
    )
    return kwargs


def test_strict_json_equal_accepts_valid_type_exact_nested_json() -> None:
    value = {
        "none": None,
        "boolean": True,
        "integer": 1,
        "float": 1.0,
        "string": "value",
        "nested": [{"enabled": False, "weights": [1, 2.5]}],
    }

    assert strict_json_equal(value, copy.deepcopy(value)) is True


def test_strict_json_equal_rejects_non_json_and_non_finite_values() -> None:
    non_json = object()
    cycle: list[object] = []
    cycle.append(cycle)
    deeply_nested: object = "leaf"
    for _ in range(2_000):
        deeply_nested = [deeply_nested]

    assert strict_json_equal(float("nan"), float("nan")) is False
    assert strict_json_equal(float("inf"), float("inf")) is False
    assert strict_json_equal(float("-inf"), float("-inf")) is False
    assert strict_json_equal((1,), (1,)) is False
    assert strict_json_equal({1: "value"}, {1: "value"}) is False
    assert strict_json_equal(non_json, non_json) is False
    assert strict_json_equal(cycle, cycle) is False
    assert strict_json_equal(deeply_nested, deeply_nested) is False


def test_prepared_run_matching_does_not_normalize_raw_fields_or_event_payloads() -> None:
    candidate = LiveRunRegistry(worker_id="worker-candidate").prepare_run(
        session_id="game_raw_match",
        villager_model="deepseek-chat",
        werewolf_model="deepseek-chat",
        seed=7,
        max_rounds=8,
        rule_set={
            "id": "classic_8",
            "list_marker": [1],
            "key_marker": {"1": "value"},
        },
    )
    tuple_run = copy.deepcopy(candidate)
    tuple_run.rule_set["list_marker"] = (1,)
    numeric_key_run = copy.deepcopy(candidate)
    numeric_key_run.rule_set["key_marker"] = {1: "value"}
    raw_event_run = copy.deepcopy(candidate)
    raw_event_run.events[0]._payload["rule_set"]["list_marker"] = (1,)

    assert live_module._prepared_runs_match(tuple_run, candidate) is False
    assert live_module._prepared_runs_match(numeric_key_run, candidate) is False
    assert live_module._prepared_runs_match(raw_event_run, candidate) is False


class RecordingLiveStore:
    def __init__(self) -> None:
        self.saved_runs = []
        self.events = []
        self.fence_token = 0

    def save_run(self, run) -> None:
        self.saved_runs.append((run.run_id, run.status, run.winner, run.error))

    def save_new_run(self, run) -> None:
        self.saved_runs.append((run.run_id, run.status, run.winner, run.error))
        event = run.events[0]
        self.events.append((event.run_id, event.id, event.type))

    def append_event(self, event, **_fence) -> None:
        self.events.append((event.run_id, event.id, event.type))

    def activate_run(self, _run_id, *, activation, **_expected) -> None:
        self.saved_runs.append((activation.run_id, "running", None, None))
        self.events.append((activation.run_id, activation.id, activation.type))

    def acquire_lease(
        self,
        _run_id,
        *,
        worker_id,
        heartbeat_at,
        lease_expires_at,
        **_expected,
    ):
        self.fence_token += 1
        return RunLeaseState(
            worker_id=worker_id,
            worker_heartbeat_at=heartbeat_at,
            lease_expires_at=lease_expires_at,
            stop_requested_at=None,
            status="queued",
            control_version=0,
            fence_token=self.fence_token,
            recovery_attempts=0,
            recovery_last_attempt_at=None,
            recovery_not_before=None,
            recovery_last_error=None,
        )


class FailingLiveStore:
    def save_new_run(self, run) -> None:
        raise RuntimeError(f"cannot save {run.run_id}")

    def save_run(self, run) -> None:
        raise RuntimeError(f"cannot save {run.run_id}")

    def append_event(self, event, **_fence) -> None:
        raise RuntimeError(f"cannot append {event.id}")

    def activate_run(self, run_id, **_activation) -> None:
        raise RuntimeError(f"cannot activate {run_id}")

    def acquire_lease(
        self,
        _run_id,
        *,
        worker_id,
        heartbeat_at,
        lease_expires_at,
        **_expected,
    ):
        return RunLeaseState(
            worker_id=worker_id,
            worker_heartbeat_at=heartbeat_at,
            lease_expires_at=lease_expires_at,
            stop_requested_at=None,
            status="queued",
            control_version=0,
            fence_token=1,
            recovery_attempts=0,
            recovery_last_attempt_at=None,
            recovery_not_before=None,
            recovery_last_error=None,
        )


class EventFailingLiveStore(RecordingLiveStore):
    def __init__(self) -> None:
        super().__init__()
        self.active_run = None

    def save_new_run(self, run) -> None:
        raise RuntimeError(f"cannot append {run.events[0].id}")

    def save_run(self, run) -> None:
        super().save_run(run)
        self.active_run = copy.deepcopy(run)
        self.active_run.events = []
        self.active_run.persisted_event_count = 0
        self.active_run.next_event_id = 1

    def append_event(self, event, **_fence) -> None:
        raise RuntimeError(f"cannot append {event.id}")

    def active_run_for_session(self, session_id):
        if self.active_run is not None and self.active_run.session_id == session_id:
            return self.active_run
        return None


class LegacyTwoPhaseLiveStore:
    def __init__(self) -> None:
        self.saved_runs = []
        self.events = []

    def save_run(self, run) -> None:
        self.saved_runs.append(run.run_id)

    def append_event(self, event, **_fence) -> None:
        self.events.append((event.run_id, event.id))


class RacingActiveRunStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._initial_reads = threading.Barrier(2)
        self.active_run = None

    def active_run_for_session(self, _session_id):
        with self._lock:
            observed = self.active_run
        if observed is None:
            self._initial_reads.wait(timeout=1)
        return observed

    def load_run(self, run_id):
        with self._lock:
            return (
                self.active_run
                if self.active_run is not None and self.active_run.run_id == run_id
                else None
            )

    def save_new_run(self, run) -> None:
        with self._lock:
            if self.active_run is not None:
                raise RuntimeError("unique active session conflict")
            self.active_run = copy.deepcopy(run)

    def save_run(self, run) -> None:
        with self._lock:
            if self.active_run is not None:
                raise RuntimeError("unique active session conflict")
            self.active_run = copy.deepcopy(run)

    def append_event(self, _event, **_fence) -> None:
        return None


class PersistenceFailureStore:
    def __init__(self, failure: Exception) -> None:
        self.failure = failure
        self.attempted_run_id = None

    def active_run_for_session(self, _session_id):
        return None

    def load_run(self, _run_id):
        return None

    def save_new_run(self, run) -> None:
        self.attempted_run_id = run.run_id
        raise self.failure


class AckLostLiveStore:
    def __init__(self, failure: Exception) -> None:
        self.failure = failure
        self.committed_run = None

    def save_new_run(self, run) -> None:
        self.committed_run = copy.deepcopy(run)
        raise self.failure

    def load_run(self, run_id):
        if self.committed_run is None or self.committed_run.run_id != run_id:
            return None
        loaded = copy.deepcopy(self.committed_run)
        loaded.events = []
        loaded.persisted_event_count = 1
        loaded.next_event_id = 2
        return loaded

    def active_run_for_session(self, session_id):
        if self.committed_run is None or self.committed_run.session_id != session_id:
            return None
        return self.load_run(self.committed_run.run_id)

    def events_after(self, run_id, *, after_id=None):
        if self.committed_run is None or self.committed_run.run_id != run_id:
            return []
        return [
            copy.deepcopy(event)
            for event in self.committed_run.events
            if after_id is None or event.id > after_id
        ]


class UniqueConflictWinnerStore:
    def __init__(self, winner: LiveGameRun, failure: Exception) -> None:
        self.winner = copy.deepcopy(winner)
        self.failure = failure
        self.attempted_run_id = None

    def _loaded_winner(self):
        loaded = copy.deepcopy(self.winner)
        loaded.events = []
        loaded.persisted_event_count = len(self.winner.events)
        loaded.next_event_id = len(self.winner.events) + 1
        return loaded

    def active_run_for_session(self, session_id):
        if self.attempted_run_id is None or self.winner.session_id != session_id:
            return None
        return self._loaded_winner()

    def load_run(self, run_id):
        if run_id == self.winner.run_id:
            return self._loaded_winner()
        return None

    def events_after(self, run_id, *, after_id=None):
        if run_id != self.winner.run_id:
            return []
        return [
            copy.deepcopy(event)
            for event in self.winner.events
            if after_id is None or event.id > after_id
        ]

    def save_new_run(self, run) -> None:
        self.attempted_run_id = run.run_id
        raise self.failure


def sensitive_player_config() -> PlayerConfig:
    return PlayerConfig(
        seat=1,
        profile_id="profile-secret",
        name="player-name-secret",
        model="player-model-secret",
        personality_id="secret",
        personality="personality-secret",
        appearance_id="secret",
        avatar_prompt="avatar-secret",
        tags=("tag-secret",),
    )


def assert_safe_initial_persistence_log(
    caplog: pytest.LogCaptureFixture,
    *,
    run_id: str,
    sensitive_values: tuple[str, ...],
) -> None:
    records = [
        record
        for record in caplog.records
        if getattr(record, "event_code", None) == "live_run_initial_persistence_failed"
    ]
    assert len(records) == 1
    record = records[0]
    assert getattr(record, "run_id", None) == run_id
    assert record.exc_info is None
    assert record.exc_text is None
    assert record.stack_info is None
    rendered = f"{caplog.text}\n{record.__dict__!r}"
    assert "live_run_initial_persistence_failed" in rendered
    assert run_id in rendered
    assert "Traceback" not in rendered
    for sensitive in sensitive_values:
        assert sensitive not in rendered


def test_registry_creates_run_with_initial_event() -> None:
    registry = LiveRunRegistry()

    run = registry.create_run(
        session_id="game_1200abcd",
        villager_model="deepseek-chat",
        werewolf_model="deepseek-chat",
        seed=21,
        max_rounds=8,
        **classic_rule_kwargs(),
    )

    assert run.run_id.startswith("run_")
    assert run.session_id == "game_1200abcd"
    assert run.status == "queued"
    assert run.event_count == 1
    assert run.events[0].type == "run_created"
    assert run.to_summary()["rule_set_revision_id"] is None
    assert run.to_summary()["rule_set_revision_no"] is None
    assert run.to_summary()["rule_set_content_hash"] is None
    assert run.events[0].payload["rule_set_revision_id"] is None
    assert run.events[0].payload["rule_set_revision_no"] is None
    assert run.events[0].payload["rule_set_content_hash"] is None


def test_prepare_run_builds_initial_event_without_store_write_or_registry_attach() -> None:
    store = RecordingLiveStore()
    registry = LiveRunRegistry(live_store=store)

    run = registry.prepare_run(
        session_id="game_1200abcd",
        villager_model="deepseek-chat",
        werewolf_model="deepseek-chat",
        seed=21,
        max_rounds=8,
        **managed_rule_kwargs(),
    )

    assert store.saved_runs == []
    assert store.events == []
    assert registry._runs == {}
    assert run.events[0].type == "run_created"
    assert run.events[0].id == 1
    assert run.events[0].run_id == run.run_id
    assert run.events[0].session_id == run.session_id
    assert run.events[0].payload["rule_set"] == run.rule_set
    assert run.next_event_id == 2
    assert run.event_count == 1


def test_attach_prepared_run_writes_only_the_local_registry() -> None:
    store = RecordingLiveStore()
    registry = LiveRunRegistry(live_store=store)
    run = registry.prepare_run(
        session_id="game_1200abcd",
        villager_model="deepseek-chat",
        werewolf_model="deepseek-chat",
        seed=21,
        max_rounds=8,
    )

    registry.attach_prepared_run(run)

    assert registry.get_run(run.run_id) is run
    assert store.saved_runs == []
    assert store.events == []


def test_attach_prepared_run_rejects_duplicate_run_and_active_session_conflicts() -> None:
    registry = LiveRunRegistry()
    first = registry.prepare_run(
        session_id="game_1200abcd",
        villager_model="deepseek-chat",
        werewolf_model="deepseek-chat",
        seed=21,
        max_rounds=8,
    )
    registry.attach_prepared_run(first)
    conflicting_session = registry.prepare_run(
        session_id=first.session_id,
        villager_model="deepseek-chat",
        werewolf_model="deepseek-chat",
        seed=22,
        max_rounds=8,
    )

    with pytest.raises(ValueError, match="already attached"):
        registry.attach_prepared_run(first)
    with pytest.raises(ValueError, match="active run"):
        registry.attach_prepared_run(conflicting_session)

    assert registry.get_run(first.run_id) is first
    assert conflicting_session.run_id not in registry._runs


def test_create_run_compatibility_wrapper_does_not_attach_when_initial_event_save_fails() -> None:
    store = EventFailingLiveStore()
    registry = LiveRunRegistry(live_store=store)

    with pytest.raises(RuntimeError, match="cannot append"):
        registry.create_run(
            session_id="game_1200abcd",
            villager_model="deepseek-chat",
            werewolf_model="deepseek-chat",
            seed=21,
            max_rounds=8,
        )

    assert registry._runs == {}
    assert store.active_run is None
    assert store.saved_runs == []


def test_get_or_create_does_not_return_a_half_persisted_run_after_initial_event_failure() -> None:
    store = EventFailingLiveStore()
    registry = LiveRunRegistry(live_store=store)

    with pytest.raises(RuntimeError, match="cannot append"):
        registry.get_or_create_active_run(
            session_id="game_1200abcd",
            villager_model="deepseek-chat",
            werewolf_model="deepseek-chat",
            seed=21,
            max_rounds=8,
        )

    assert registry._runs == {}
    assert store.active_run is None
    assert store.saved_runs == []


def test_persistent_create_rejects_a_store_without_atomic_new_run_support_before_writing() -> None:
    store = LegacyTwoPhaseLiveStore()
    registry = LiveRunRegistry(live_store=store)

    with pytest.raises(RuntimeError, match="atomic new-run persistence"):
        registry.create_run(
            session_id="game_1200abcd",
            villager_model="deepseek-chat",
            werewolf_model="deepseek-chat",
            seed=21,
            max_rounds=8,
        )

    assert store.saved_runs == []
    assert store.events == []
    assert registry._runs == {}


def test_persistent_activation_rejects_a_store_without_atomic_support_before_writing() -> None:
    store = LegacyTwoPhaseLiveStore()
    registry = LiveRunRegistry(live_store=store)
    run = registry.prepare_run(
        session_id="game_missing_atomic_activation",
        villager_model="deepseek-chat",
        werewolf_model="deepseek-chat",
        seed=21,
        max_rounds=8,
    )
    registry.attach_prepared_run(run)

    with pytest.raises(RuntimeError, match="atomic activation persistence"):
        registry.mark_running(run.run_id)

    assert run.status == "queued"
    assert run.started_at is None
    assert run.next_event_id == 2
    assert [(event.id, event.type) for event in run.events] == [(1, "run_created")]
    assert store.saved_runs == []
    assert store.events == []


def test_registry_summary_and_initial_event_use_public_run_fields() -> None:
    registry = LiveRunRegistry()

    run = registry.create_run(
        session_id="game_1200abcd",
        villager_model="deepseek-chat",
        werewolf_model="deepseek-chat",
        seed=21,
        max_rounds=8,
        **managed_rule_kwargs(),
    )

    summary = run.to_summary()

    assert set(summary) == {
        "run_id",
        "session_id",
        "status",
        "villager_model",
        "werewolf_model",
        "seed",
        "max_rounds",
        "rule_set_id",
        "rule_set_revision_id",
        "rule_set_revision_no",
        "rule_set_content_hash",
        "rule_set",
        "player_configs",
        "lineup_quality_warnings",
        "created_at",
        "started_at",
        "completed_at",
        "winner",
        "error",
        "stop_requested_at",
        "event_count",
    }
    assert set(run.events[0].payload) == {
        "session_id",
        "villager_model",
        "werewolf_model",
        "seed",
        "max_rounds",
        "rule_set_id",
        "rule_set_revision_id",
        "rule_set_revision_no",
        "rule_set_content_hash",
        "rule_set",
        "player_configs",
        "lineup_quality_warnings",
    }
    assert summary["lineup_quality_warnings"] == []
    assert run.events[0].payload["lineup_quality_warnings"] == []
    assert summary["rule_set_revision_id"] == "revision-2"
    assert summary["rule_set_revision_no"] == 2
    assert summary["rule_set_content_hash"] == "a" * 64
    assert run.events[0].payload["rule_set_revision_id"] == "revision-2"
    assert run.events[0].payload["rule_set_revision_no"] == 2
    assert run.events[0].payload["rule_set_content_hash"] == "a" * 64


def test_registry_get_or_create_forwards_pinned_rule_metadata() -> None:
    registry = LiveRunRegistry()

    run, created = registry.get_or_create_active_run(
        session_id="game_1200abcd",
        villager_model="deepseek-chat",
        werewolf_model="deepseek-chat",
        seed=21,
        max_rounds=8,
        **managed_rule_kwargs(),
    )

    assert created is True
    assert run.rule_set_revision_id == "revision-2"
    assert run.rule_set_revision_no == 2
    assert run.rule_set_content_hash == "a" * 64


def test_live_game_run_rejects_partial_pinned_rule_metadata() -> None:
    with pytest.raises(ValueError, match="all present or all absent"):
        LiveGameRun(
            run_id="run_123456789abc",
            session_id="game_1200abcd",
            villager_model="deepseek-chat",
            werewolf_model="deepseek-chat",
            seed=21,
            max_rounds=8,
            rule_set_revision_id="revision-2",
        )


def test_registry_accepts_backfilled_pinned_scalars_with_a_legacy_snapshot() -> None:
    registry = LiveRunRegistry()

    run = registry.create_run(
        session_id="game_1200abcd",
        villager_model="deepseek-chat",
        werewolf_model="deepseek-chat",
        seed=21,
        max_rounds=8,
        **classic_rule_kwargs(),
        rule_set_revision_id="revision-2",
        rule_set_revision_no=2,
        rule_set_content_hash="a" * 64,
    )

    assert run.rule_set_revision_id == "revision-2"
    assert run.rule_set_revision_no == 2
    assert run.rule_set_content_hash == "a" * 64
    assert "revision_id" not in run.rule_set


@pytest.mark.parametrize(
    "changes",
    [
        {
            "rule_set_revision_id": None,
            "rule_set_revision_no": None,
            "rule_set_content_hash": None,
        },
        {"rule_set_revision_id": "revision-other"},
        {"rule_set_revision_no": 3},
        {"rule_set_content_hash": "b" * 64},
        {"rule_set": {"schema_version": True}},
        {"rule_set": {"schema_version": 2}},
    ],
    ids=(
        "missing-scalars",
        "revision-id-mismatch",
        "revision-no-mismatch",
        "content-hash-mismatch",
        "boolean-schema-version",
        "wrong-schema-version",
    ),
)
def test_registry_rejects_managed_snapshot_without_matching_pinned_scalars(
    changes: dict[str, object],
) -> None:
    kwargs = managed_rule_kwargs()
    snapshot_changes = changes.get("rule_set")
    if isinstance(snapshot_changes, dict):
        kwargs["rule_set"].update(snapshot_changes)
    else:
        kwargs.update(changes)

    with pytest.raises(ValueError):
        LiveRunRegistry().create_run(
            session_id="game_1200abcd",
            villager_model="deepseek-chat",
            werewolf_model="deepseek-chat",
            seed=21,
            max_rounds=8,
            **kwargs,
        )


@pytest.mark.parametrize(
    "metadata",
    [
        {
            "rule_set_revision_id": "revision-2",
            "rule_set_revision_no": None,
            "rule_set_content_hash": None,
        },
        {
            "rule_set_revision_id": " revision-2",
            "rule_set_revision_no": 2,
            "rule_set_content_hash": "a" * 64,
        },
        {
            "rule_set_revision_id": "revision-2",
            "rule_set_revision_no": True,
            "rule_set_content_hash": "a" * 64,
        },
        {
            "rule_set_revision_id": "revision-2",
            "rule_set_revision_no": 2,
            "rule_set_content_hash": "A" * 64,
        },
    ],
    ids=("partial", "untrimmed-id", "boolean-revision", "uppercase-hash"),
)
def test_registry_rejects_invalid_pinned_rule_metadata(metadata: dict[str, object]) -> None:
    registry = LiveRunRegistry()

    with pytest.raises(ValueError):
        registry.create_run(
            session_id="game_1200abcd",
            villager_model="deepseek-chat",
            werewolf_model="deepseek-chat",
            seed=21,
            max_rounds=8,
            **metadata,
        )


@pytest.mark.parametrize(
    "metadata",
    [
        {"rule_set_revision_id": "revision-2"},
        {
            "rule_set_revision_id": "revision-2",
            "rule_set_revision_no": True,
            "rule_set_content_hash": "a" * 64,
        },
        {
            "rule_set_revision_id": "revision-2",
            "rule_set_revision_no": 2,
            "rule_set_content_hash": "A" * 64,
        },
    ],
    ids=("partial", "boolean-revision", "uppercase-hash"),
)
def test_get_or_create_validates_pinned_metadata_before_returning_an_active_run(
    metadata: dict[str, object],
) -> None:
    registry = LiveRunRegistry()
    registry.create_run(
        session_id="game_1200abcd",
        villager_model="deepseek-chat",
        werewolf_model="deepseek-chat",
        seed=21,
        max_rounds=8,
    )

    with pytest.raises(ValueError):
        registry.get_or_create_active_run(
            session_id="game_1200abcd",
            villager_model="deepseek-chat",
            werewolf_model="deepseek-chat",
            seed=21,
            max_rounds=8,
            **metadata,
        )


def test_registry_appends_ordered_events_and_replays_after_id() -> None:
    registry = LiveRunRegistry()
    run = registry.create_run(
        session_id="game_1200abcd",
        villager_model="deepseek-chat",
        werewolf_model="deepseek-chat",
        seed=None,
        max_rounds=8,
        **classic_rule_kwargs(),
    )

    registry.publish(
        run.run_id,
        "game_started",
        payload={"players": ["张三", "李四"]},
    )
    registry.publish(
        run.run_id,
        "round_started",
        round_number=1,
        payload={"round": 1},
    )

    replayed = registry.events_after(run.run_id, after_id=1)

    assert [event.id for event in replayed] == [2, 3]
    assert [event.type for event in replayed] == ["game_started", "round_started"]
    assert replayed[1].round == 1


def test_registry_marks_completed_and_failed() -> None:
    registry = LiveRunRegistry()
    completed = registry.create_run(
        session_id="game_1200abcd",
        villager_model="deepseek-chat",
        werewolf_model="deepseek-chat",
        seed=None,
        max_rounds=8,
        **classic_rule_kwargs(),
    )
    failed = registry.create_run(
        session_id="game_1201cd34",
        villager_model="deepseek-chat",
        werewolf_model="deepseek-chat",
        seed=None,
        max_rounds=8,
        **classic_rule_kwargs(),
    )

    registry.mark_running(completed.run_id)
    assert registry.get_run(completed.run_id).status == "running"
    assert registry.get_run(completed.run_id).events[-1].type == "run_started"

    registry.mark_completed(completed.run_id, winner="狼人阵营")
    registry.mark_failed(failed.run_id, error="Maximum rounds exceeded")

    assert registry.get_run(completed.run_id).status == "completed"
    assert registry.get_run(completed.run_id).completed_at is not None
    assert registry.get_run(completed.run_id).events[-1].type == "game_completed"
    assert registry.get_run(failed.run_id).status == "failed"
    assert registry.get_run(failed.run_id).error == "Maximum rounds exceeded"
    assert registry.get_run(failed.run_id).completed_at is not None
    assert registry.get_run(failed.run_id).events[-1].type == "game_failed"


def test_registry_get_or_create_active_run_is_atomic_per_session() -> None:
    registry = LiveRunRegistry()

    def get_or_create() -> tuple[str, bool]:
        run, created = registry.get_or_create_active_run(
            session_id="game_1200abcd",
            villager_model="deepseek-chat",
            werewolf_model="deepseek-chat",
            seed=21,
            max_rounds=8,
            **classic_rule_kwargs(),
        )
        return run.run_id, created

    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(lambda _index: get_or_create(), range(8)))

    run_ids = {run_id for run_id, _created in results}
    assert len(run_ids) == 1
    assert sum(created for _run_id, created in results) == 1

    first_run_id = results[0][0]
    registry.mark_failed(first_run_id, error="temporary failure")

    replacement, created = registry.get_or_create_active_run(
        session_id="game_1200abcd",
        villager_model="deepseek-chat",
        werewolf_model="deepseek-chat",
        seed=21,
        max_rounds=8,
        **classic_rule_kwargs(),
    )

    assert created is True
    assert replacement.run_id != first_run_id


def test_get_or_create_fast_path_does_not_copy_or_replace_local_active_events() -> None:
    registry = LiveRunRegistry()
    run = registry.create_run(
        session_id="game_1200abcd",
        villager_model="deepseek-chat",
        werewolf_model="deepseek-chat",
        seed=21,
        max_rounds=8,
    )

    class IterationCountingEvents(list):
        def __init__(self, events) -> None:
            super().__init__(events)
            self.iterations = 0

        def __iter__(self):
            self.iterations += 1
            return super().__iter__()

    events = IterationCountingEvents(run.events)
    run.events = events

    active, created = registry.get_or_create_active_run(
        session_id=run.session_id,
        villager_model="deepseek-chat",
        werewolf_model="deepseek-chat",
        seed=21,
        max_rounds=8,
    )

    assert active is run
    assert created is False
    assert run.events is events
    assert events.iterations == 0


def test_get_or_create_rechecks_local_winner_after_create_race(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = LiveRunRegistry()
    winner = registry.create_run(
        session_id="game_1200abcd",
        villager_model="deepseek-chat",
        werewolf_model="deepseek-chat",
        seed=21,
        max_rounds=8,
    )
    monkeypatch.setattr(
        registry,
        "try_get_active_run_for_session",
        lambda _session_id: None,
    )

    run, created = registry.get_or_create_active_run(
        session_id=winner.session_id,
        villager_model="deepseek-chat",
        werewolf_model="deepseek-chat",
        seed=21,
        max_rounds=8,
    )

    assert run is winner
    assert created is False


def test_format_sse_preserves_unicode_and_payload_history_is_stable() -> None:
    registry = LiveRunRegistry()
    run = registry.create_run(
        session_id="game_1200abcd",
        villager_model="deepseek-chat",
        werewolf_model="deepseek-chat",
        seed=None,
        max_rounds=8,
        **classic_rule_kwargs(),
    )
    payload = {"players": ["张三", "李四"], "meta": {"phase": "夜晚"}}

    event = registry.publish(run.run_id, "players_announced", payload=payload)
    event_dict = event.to_dict()
    payload["players"].append("王五")
    payload["meta"]["phase"] = "白天"
    event_dict["payload"]["players"].append("赵六")
    event.payload["players"].append("钱七")
    event.payload["meta"]["phase"] = "黄昏"

    replayed_event = registry.events_after(run.run_id, after_id=1)[0]
    sse = format_sse(replayed_event)
    lines = sse.splitlines()
    data = json.loads(lines[2].removeprefix("data: "))

    assert lines[0] == f"id: {replayed_event.id}"
    assert lines[1] == "event: players_announced"
    assert lines[2].startswith("data: ")
    assert "张三" in lines[2]
    assert data["payload"] == {"players": ["张三", "李四"], "meta": {"phase": "夜晚"}}
    assert replayed_event.payload == {
        "players": ["张三", "李四"],
        "meta": {"phase": "夜晚"},
    }
    assert replayed_event.to_dict()["payload"] == {
        "players": ["张三", "李四"],
        "meta": {"phase": "夜晚"},
    }


def test_live_registry_persists_created_run_and_events() -> None:
    store = RecordingLiveStore()
    registry = LiveRunRegistry(live_store=store)

    run = registry.create_run(
        session_id="game_1200abcd",
        villager_model="deepseek-chat",
        werewolf_model="deepseek-chat",
        seed=7,
        max_rounds=8,
    )
    registry.mark_running(run.run_id)
    registry.mark_completed(run.run_id, winner="好人阵营")

    assert [item[1] for item in store.saved_runs] == ["queued", "running", "completed"]
    assert [item[2] for item in store.events] == [
        "run_created",
        "run_started",
        "game_completed",
    ]


def test_live_registry_rejects_created_run_when_initial_persistence_fails(caplog) -> None:
    registry = LiveRunRegistry(live_store=FailingLiveStore())

    with caplog.at_level(logging.ERROR, logger="app.werewolf.live"):
        with pytest.raises(RuntimeError, match="cannot save"):
            registry.create_run(
                session_id="game_1200abcd",
                villager_model="deepseek-chat",
                werewolf_model="deepseek-chat",
                seed=7,
                max_rounds=8,
            )

    assert registry.try_get_active_run_for_session("game_1200abcd") is None
    assert any(
        getattr(record, "event_code", None) == "live_run_initial_persistence_failed"
        for record in caplog.records
    )


def test_generic_initial_persistence_failure_logs_only_safe_metadata_and_reraises_same_error(
    caplog: pytest.LogCaptureFixture,
) -> None:
    failure = RuntimeError(
        "generic-write-secret INSERT INTO live_runs model-secret snapshot-secret "
        "player-name-secret personality-secret player_configs"
    )
    store = PersistenceFailureStore(failure)
    registry = LiveRunRegistry(live_store=store)

    with caplog.at_level(logging.ERROR, logger="app.werewolf.live"):
        with pytest.raises(RuntimeError) as raised:
            registry.get_or_create_active_run(
                session_id="game_1200abcd",
                villager_model="model-secret",
                werewolf_model="other-model-secret",
                seed=7,
                max_rounds=8,
                rule_set_id="classic_8",
                rule_set={
                    **classic_rule_kwargs()["rule_set"],
                    "storage_marker": "snapshot-secret",
                },
                player_configs=[sensitive_player_config()],
            )

    assert raised.value is failure
    assert store.attempted_run_id is not None
    assert registry._runs == {}
    assert_safe_initial_persistence_log(
        caplog,
        run_id=store.attempted_run_id,
        sensitive_values=(
            "generic-write-secret",
            "INSERT INTO live_runs",
            "model-secret",
            "snapshot-secret",
            "player-name-secret",
            "personality-secret",
            "player_configs",
        ),
    )


def test_unique_conflict_logs_only_safe_metadata_and_returns_the_other_complete_winner(
    caplog: pytest.LogCaptureFixture,
) -> None:
    winner = LiveRunRegistry(worker_id="worker-winner").prepare_run(
        session_id="game_1200abcd",
        villager_model="winner-model",
        werewolf_model="winner-model",
        seed=8,
        max_rounds=8,
    )
    failure = IntegrityError(
        "INSERT INTO live_runs (villager_model, rule_set, player_configs) "
        "VALUES (%(model)s, %(snapshot)s, %(players)s)",
        {
            "model": "model-secret",
            "snapshot": {"storage_marker": "snapshot-secret"},
            "players": [
                {
                    "name": "player-name-secret",
                    "personality": "personality-secret",
                }
            ],
        },
        RuntimeError("unique-conflict-secret"),
    )
    store = UniqueConflictWinnerStore(winner, failure)
    registry = LiveRunRegistry(live_store=store, worker_id="worker-loser")

    with caplog.at_level(logging.ERROR, logger="app.werewolf.live"):
        run, created = registry.get_or_create_active_run(
            session_id=winner.session_id,
            villager_model="model-secret",
            werewolf_model="other-model-secret",
            seed=7,
            max_rounds=8,
            rule_set_id="classic_8",
            rule_set={
                **classic_rule_kwargs()["rule_set"],
                "storage_marker": "snapshot-secret",
            },
            player_configs=[sensitive_player_config()],
        )

    assert run.run_id == winner.run_id
    assert created is False
    assert store.attempted_run_id is not None
    assert_safe_initial_persistence_log(
        caplog,
        run_id=store.attempted_run_id,
        sensitive_values=(
            "unique-conflict-secret",
            "INSERT INTO live_runs",
            "model-secret",
            "snapshot-secret",
            "player-name-secret",
            "personality-secret",
            "player_configs",
        ),
    )


def test_concurrent_same_registry_stale_claims_advance_the_fence_once() -> None:
    durable = LiveRunRegistry(worker_id="worker-old").prepare_run(
        session_id="game_stale_claim_race",
        villager_model="deepseek-chat",
        werewolf_model="deepseek-chat",
        seed=7,
        max_rounds=8,
    )
    durable.status = "running"
    durable.started_at = "2026-07-12T10:00:00Z"
    durable.worker_id = "worker-old"
    durable.worker_heartbeat_at = "2026-07-12T10:00:00Z"
    durable.lease_expires_at = "2026-07-12T10:00:01Z"
    durable.fence_token = 1

    class RacingStaleClaimStore:
        def __init__(self) -> None:
            self.prevalidation_barrier = threading.Barrier(2)
            self.state_lock = threading.Lock()
            self.acquire_calls = 0
            self.fence_token = 1

        def load_run(self, run_id):
            if run_id != durable.run_id:
                return None
            loaded = copy.deepcopy(durable)
            loaded.events = []
            loaded.persisted_event_count = 1
            loaded.next_event_id = 2
            return loaded

        def events_after(self, run_id, *, after_id=None):
            assert run_id == durable.run_id
            self.prevalidation_barrier.wait(timeout=5)
            return [
                copy.deepcopy(event)
                for event in durable.events
                if after_id is None or event.id > after_id
            ]

        def acquire_lease(
            self,
            run_id,
            *,
            worker_id,
            heartbeat_at,
            lease_expires_at,
            **_expected,
        ):
            assert run_id == durable.run_id
            with self.state_lock:
                self.acquire_calls += 1
                self.fence_token += 1
                return RunLeaseState(
                    worker_id=worker_id,
                    worker_heartbeat_at=heartbeat_at,
                    lease_expires_at=lease_expires_at,
                    stop_requested_at=None,
                    status="running",
                    control_version=0,
                    fence_token=self.fence_token,
                    recovery_attempts=0,
                    recovery_last_attempt_at=None,
                    recovery_not_before=None,
                    recovery_last_error=None,
                )

    store = RacingStaleClaimStore()
    registry = LiveRunRegistry(live_store=store, worker_id="worker-claimant")

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(registry.try_claim_stale_run, [durable.run_id] * 2))

    assert sum(result is not None for result in results) == 1
    assert store.acquire_calls == 1
    assert registry.get_run(durable.run_id).fence_token == 2


def test_concurrent_fresh_mark_running_claims_once_and_returns_one_activation() -> None:
    class BlockingStartStore:
        def __init__(self) -> None:
            self.state_lock = threading.Lock()
            self.first_acquire_entered = threading.Event()
            self.second_acquire_entered = threading.Event()
            self.release_first_acquire = threading.Event()
            self.acquire_calls = 0
            self.fence_token = 0

        def save_run(self, _run) -> None:
            return None

        def append_event(self, _event, **_fence) -> None:
            return None

        def activate_run(self, _run_id, **_activation) -> None:
            return None

        def acquire_lease(
            self,
            _run_id,
            *,
            worker_id,
            heartbeat_at,
            lease_expires_at,
            **_expected,
        ):
            with self.state_lock:
                self.acquire_calls += 1
                call_number = self.acquire_calls
                self.fence_token += 1
                fence_token = self.fence_token
            if call_number == 1:
                self.first_acquire_entered.set()
                assert self.release_first_acquire.wait(timeout=5)
            else:
                self.second_acquire_entered.set()
            return RunLeaseState(
                worker_id=worker_id,
                worker_heartbeat_at=heartbeat_at,
                lease_expires_at=lease_expires_at,
                stop_requested_at=None,
                status="queued",
                control_version=0,
                fence_token=fence_token,
                recovery_attempts=0,
                recovery_last_attempt_at=None,
                recovery_not_before=None,
                recovery_last_error=None,
            )

    store = BlockingStartStore()
    registry = LiveRunRegistry(live_store=store, worker_id="worker-start")
    run = registry.prepare_run(
        session_id="game_start_race",
        villager_model="deepseek-chat",
        werewolf_model="deepseek-chat",
        seed=7,
        max_rounds=8,
    )
    registry.attach_prepared_run(run)
    results: list[LiveEvent] = []

    first = threading.Thread(target=lambda: results.append(registry.mark_running(run.run_id)))
    second = threading.Thread(target=lambda: results.append(registry.mark_running(run.run_id)))
    first.start()
    assert store.first_acquire_entered.wait(timeout=5)
    second.start()
    store.second_acquire_entered.wait(timeout=0.2)
    store.release_first_acquire.set()
    first.join(timeout=5)
    second.join(timeout=5)

    assert not first.is_alive()
    assert not second.is_alive()
    assert store.acquire_calls == 1
    assert run.fence_token == 1
    assert [event.type for event in run.events] == ["run_created", "run_started"]
    assert [event.id for event in run.events] == [1, 2]
    assert len(results) == 2
    assert results[0] is results[1] is run.events[1]


def test_preclaimed_recovery_mark_running_is_idempotent_for_the_current_fence() -> None:
    registry = LiveRunRegistry(worker_id="worker-recovery")
    run = registry.prepare_run(
        session_id="game_recovery_activation",
        villager_model="deepseek-chat",
        werewolf_model="deepseek-chat",
        seed=7,
        max_rounds=8,
    )
    registry.attach_prepared_run(run)
    run.status = "running"
    run.started_at = "2026-07-12T10:00:00Z"
    run.worker_id = registry.worker_id
    run.worker_heartbeat_at = "2026-07-12T10:05:00Z"
    run.lease_expires_at = "2099-07-12T10:05:15Z"
    run.fence_token = 2
    run.events.append(
        LiveEvent(
            id=2,
            type="run_started",
            run_id=run.run_id,
            session_id=run.session_id,
            created_at=run.started_at,
        )
    )
    run.next_event_id = 3

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(registry.mark_running, [run.run_id] * 2))
    repeated = registry.mark_running(run.run_id)

    assert [event.type for event in run.events] == [
        "run_created",
        "run_started",
        "run_recovered",
    ]
    assert [event.id for event in run.events] == [1, 2, 3]
    assert run.events[2].payload == {"fence_token": 2}
    assert results[0] is results[1] is repeated is run.events[2]


def test_cached_mark_running_rechecks_stop_request_before_returning_activation() -> None:
    registry = LiveRunRegistry()
    run = registry.create_run(
        session_id="game_cached_stop_guard",
        villager_model="deepseek-chat",
        werewolf_model="deepseek-chat",
        seed=7,
        max_rounds=8,
    )
    activation = registry.mark_running(run.run_id)
    registry.request_stop(run.run_id)
    before = (run.status, run.fence_token, run.next_event_id, tuple(run.events))

    with pytest.raises(GameRunCanceled):
        registry.mark_running(run.run_id)

    assert (run.status, run.fence_token, run.next_event_id, tuple(run.events)) == before
    assert run.events[1] is activation


def test_cached_mark_running_rechecks_lease_loss_before_returning_activation() -> None:
    registry = LiveRunRegistry()
    run = registry.create_run(
        session_id="game_cached_lease_guard",
        villager_model="deepseek-chat",
        werewolf_model="deepseek-chat",
        seed=7,
        max_rounds=8,
    )
    activation = registry.mark_running(run.run_id)
    run.lease_lost = True
    before = (run.status, run.fence_token, run.next_event_id, tuple(run.events))

    with pytest.raises(RunLeaseUnavailable):
        registry.mark_running(run.run_id)

    assert (run.status, run.fence_token, run.next_event_id, tuple(run.events)) == before
    assert run.events[1] is activation


def test_cached_mark_running_rechecks_worker_fence_before_returning_activation() -> None:
    class FencedActivationStore:
        def __init__(self) -> None:
            self.acquire_calls = 0

        def save_run(self, _run) -> None:
            return None

        def append_event(self, _event, **_fence) -> None:
            return None

        def activate_run(self, _run_id, **_activation) -> None:
            return None

        def acquire_lease(
            self,
            _run_id,
            *,
            worker_id,
            heartbeat_at,
            lease_expires_at,
            **_expected,
        ):
            self.acquire_calls += 1
            if self.acquire_calls > 1:
                return None
            return RunLeaseState(
                worker_id=worker_id,
                worker_heartbeat_at=heartbeat_at,
                lease_expires_at=lease_expires_at,
                stop_requested_at=None,
                status="queued",
                control_version=0,
                fence_token=1,
                recovery_attempts=0,
                recovery_last_attempt_at=None,
                recovery_not_before=None,
                recovery_last_error=None,
            )

    store = FencedActivationStore()
    registry = LiveRunRegistry(live_store=store, worker_id="worker-owner")
    run = registry.prepare_run(
        session_id="game_cached_fence_guard",
        villager_model="deepseek-chat",
        werewolf_model="deepseek-chat",
        seed=7,
        max_rounds=8,
    )
    registry.attach_prepared_run(run)
    activation = registry.mark_running(run.run_id)
    run.worker_id = "worker-new-owner"
    before = (run.status, run.fence_token, run.next_event_id, tuple(run.events))

    with pytest.raises(RunLeaseUnavailable):
        registry.mark_running(run.run_id)

    assert store.acquire_calls == 2
    assert (run.status, run.fence_token, run.next_event_id, tuple(run.events)) == before
    assert run.events[1] is activation


def test_cached_mark_running_reacquires_an_expired_same_worker_lease() -> None:
    store = RecordingLiveStore()
    registry = LiveRunRegistry(live_store=store, worker_id="worker-expired-cache")
    run = registry.create_run(
        session_id="game_cached_expired_lease",
        villager_model="deepseek-chat",
        werewolf_model="deepseek-chat",
        seed=7,
        max_rounds=8,
    )
    first_activation = registry.mark_running(run.run_id)
    run.lease_expires_at = "2000-01-01T00:00:00Z"

    recovered = registry.mark_running(run.run_id)
    repeated = registry.mark_running(run.run_id)

    assert store.fence_token == 2
    assert run.fence_token == 2
    assert recovered is repeated is run.events[2]
    assert recovered is not first_activation
    assert recovered.type == "run_recovered"
    assert recovered.payload == {"fence_token": 2}
    assert [(event.id, event.type) for event in run.events] == [
        (1, "run_created"),
        (2, "run_started"),
        (3, "run_recovered"),
    ]


@pytest.mark.parametrize("terminal_status", ["completed", "failed", "canceled"])
def test_mark_running_never_reactivates_a_terminal_run(terminal_status: str) -> None:
    store = RecordingLiveStore()
    registry = LiveRunRegistry(live_store=store)
    run = registry.create_run(
        session_id=f"game_terminal_{terminal_status}",
        villager_model="deepseek-chat",
        werewolf_model="deepseek-chat",
        seed=7,
        max_rounds=8,
    )
    registry.mark_running(run.run_id)
    if terminal_status == "completed":
        registry.mark_completed(run.run_id, winner="好人阵营")
    elif terminal_status == "failed":
        registry.mark_failed(run.run_id, error="terminal failure")
    else:
        registry.mark_canceled(run.run_id)
    before = (
        run.status,
        run.fence_token,
        run.next_event_id,
        tuple(run.events),
        tuple(store.saved_runs),
        tuple(store.events),
        store.fence_token,
    )

    with pytest.raises(ValueError, match="not active"):
        registry.mark_running(run.run_id)

    assert (
        run.status,
        run.fence_token,
        run.next_event_id,
        tuple(run.events),
        tuple(store.saved_runs),
        tuple(store.events),
        store.fence_token,
    ) == before


def test_unique_conflict_returns_the_other_complete_winner_after_it_starts_running() -> None:
    winner_registry = LiveRunRegistry(worker_id="worker-winner")
    winner = winner_registry.create_run(
        session_id="game_1200abcd",
        villager_model="winner-model",
        werewolf_model="winner-model",
        seed=8,
        max_rounds=8,
    )
    winner_registry.mark_running(winner.run_id)
    failure = RuntimeError("unique active session conflict")
    store = UniqueConflictWinnerStore(winner, failure)
    registry = LiveRunRegistry(live_store=store, worker_id="worker-loser")

    run, created = registry.get_or_create_active_run(
        session_id=winner.session_id,
        villager_model="loser-model",
        werewolf_model="loser-model",
        seed=7,
        max_rounds=8,
    )

    assert created is False
    assert run.run_id == winner.run_id
    assert run.status == "running"
    assert run.next_event_id == 3
    assert [event.type for event in run.events] == ["run_created", "run_started"]


def test_get_or_create_attaches_its_exact_complete_candidate_after_commit_ack_loss() -> None:
    failure = RuntimeError("commit acknowledgement lost")
    store = AckLostLiveStore(failure)
    registry = LiveRunRegistry(live_store=store, worker_id="worker-candidate")

    run, created = registry.get_or_create_active_run(
        session_id="game_1200abcd",
        villager_model="deepseek-chat",
        werewolf_model="deepseek-chat",
        seed=7,
        max_rounds=8,
    )

    assert created is True
    assert store.committed_run is not None
    assert run.run_id == store.committed_run.run_id
    assert registry.get_run(run.run_id) is run
    assert run.event_count == 1
    assert run.next_event_id == 2
    assert [event.type for event in run.events] == ["run_created"]


def test_get_or_create_normalizes_the_exact_candidate_event_timestamp_after_ack_loss() -> None:
    failure = RuntimeError("commit acknowledgement lost")

    class NormalizedTimestampAckLostLiveStore(AckLostLiveStore):
        def events_after(self, run_id, *, after_id=None):
            events = super().events_after(run_id, after_id=after_id)
            assert len(events) == 1
            event = events[0]
            return [
                LiveEvent(
                    id=event.id,
                    type=event.type,
                    run_id=event.run_id,
                    session_id=event.session_id,
                    created_at=event.created_at.replace("Z", "+00:00"),
                    round=event.round,
                    phase=event.phase,
                    actor=event.actor,
                    action=event.action,
                    payload=event.payload,
                )
            ]

    store = NormalizedTimestampAckLostLiveStore(failure)
    registry = LiveRunRegistry(live_store=store, worker_id="worker-candidate")

    run, created = registry.get_or_create_active_run(
        session_id="game_1200abcd",
        villager_model="deepseek-chat",
        werewolf_model="deepseek-chat",
        seed=7,
        max_rounds=8,
    )

    assert created is True
    assert registry.get_run(run.run_id) is run


@pytest.mark.parametrize(
    ("expected_value", "persisted_value"),
    [(False, 0), (True, 1), (1, 1.0)],
    ids=["false-to-zero", "true-to-one", "int-to-float"],
)
def test_get_or_create_rejects_type_coercive_ack_candidate_changes(
    expected_value: object,
    persisted_value: object,
) -> None:
    failure = RuntimeError("commit acknowledgement lost")

    class TypeCoerciveAckLostLiveStore(AckLostLiveStore):
        def save_new_run(self, run) -> None:
            self.committed_run = copy.deepcopy(run)
            self.committed_run.rule_set["strict_comparison_marker"]["value"] = persisted_value
            event = self.committed_run.events[0]
            payload = event.payload
            payload["rule_set"]["strict_comparison_marker"]["value"] = persisted_value
            self.committed_run.events[0] = LiveEvent(
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
            raise self.failure

    store = TypeCoerciveAckLostLiveStore(failure)
    registry = LiveRunRegistry(live_store=store, worker_id="worker-candidate")

    with pytest.raises(RuntimeError) as raised:
        registry.get_or_create_active_run(
            session_id="game_1200abcd",
            villager_model="deepseek-chat",
            werewolf_model="deepseek-chat",
            seed=7,
            max_rounds=8,
            rule_set={
                "id": "classic_8",
                "strict_comparison_marker": {"value": expected_value},
            },
        )

    assert raised.value is failure
    assert registry._runs == {}


@pytest.mark.parametrize(
    "malformation",
    ["tuple", "numeric-key", "object", "cycle", "deep"],
)
def test_get_or_create_rethrows_ack_error_for_raw_malformed_persisted_state(
    malformation: str,
) -> None:
    failure = RuntimeError("commit acknowledgement lost")

    class RawMalformedAckLostStore(AckLostLiveStore):
        def save_new_run(self, run) -> None:
            self.committed_run = copy.deepcopy(run)
            if malformation == "tuple":
                self.committed_run.rule_set["raw_marker"] = [1]
                self.committed_run.rule_set["raw_marker"] = (1,)
            elif malformation == "numeric-key":
                self.committed_run.rule_set["raw_marker"] = {1: "value"}
            elif malformation == "object":
                self.committed_run.rule_set["raw_marker"] = object()
            elif malformation == "cycle":
                cycle: list[object] = []
                cycle.append(cycle)
                self.committed_run.rule_set["raw_marker"] = cycle
            else:
                deeply_nested: object = "leaf"
                for _ in range(2_000):
                    deeply_nested = [deeply_nested]
                self.committed_run.rule_set["raw_marker"] = deeply_nested
            raise self.failure

        def load_run(self, run_id):
            if self.committed_run is None or self.committed_run.run_id != run_id:
                return None
            loaded = copy.copy(self.committed_run)
            loaded.events = []
            loaded.persisted_event_count = 1
            loaded.next_event_id = 2
            return loaded

        def events_after(self, run_id, *, after_id=None):
            if self.committed_run is None or self.committed_run.run_id != run_id:
                return []
            return [
                event
                for event in self.committed_run.events
                if after_id is None or event.id > after_id
            ]

    candidate_marker: object
    if malformation == "tuple":
        candidate_marker = [1]
    elif malformation == "numeric-key":
        candidate_marker = {"1": "value"}
    else:
        candidate_marker = "candidate"
    store = RawMalformedAckLostStore(failure)
    registry = LiveRunRegistry(live_store=store, worker_id="worker-candidate")

    with pytest.raises(RuntimeError) as raised:
        registry.get_or_create_active_run(
            session_id="game_1200abcd",
            villager_model="deepseek-chat",
            werewolf_model="deepseek-chat",
            seed=7,
            max_rounds=8,
            rule_set={"id": "classic_8", "raw_marker": candidate_marker},
        )

    assert raised.value is failure
    assert registry._runs == {}


def test_get_or_create_does_not_downgrade_a_mismatched_exact_candidate_to_other_winner() -> None:
    failure = RuntimeError("commit acknowledgement lost")

    class MismatchedAckLostLiveStore(AckLostLiveStore):
        def save_new_run(self, run) -> None:
            self.committed_run = copy.deepcopy(run)
            self.committed_run.villager_model = "externally-mutated-model"
            raise self.failure

    store = MismatchedAckLostLiveStore(failure)
    registry = LiveRunRegistry(live_store=store, worker_id="worker-candidate")

    with pytest.raises(RuntimeError) as raised:
        registry.get_or_create_active_run(
            session_id="game_1200abcd",
            villager_model="deepseek-chat",
            werewolf_model="deepseek-chat",
            seed=7,
            max_rounds=8,
        )

    assert raised.value is failure
    assert registry._runs == {}


def test_get_or_create_does_not_return_a_preexisting_zero_event_active_row() -> None:
    half_run = LiveRunRegistry(worker_id="worker-legacy").prepare_run(
        session_id="game_1200abcd",
        villager_model="legacy-model",
        werewolf_model="legacy-model",
        seed=6,
        max_rounds=8,
    )
    half_run.events = []
    half_run.persisted_event_count = 0
    half_run.next_event_id = 1
    failure = RuntimeError("unique active session conflict")

    class PreexistingHalfRunStore:
        def __init__(self) -> None:
            self.save_attempts = 0

        def active_run_for_session(self, session_id):
            if session_id == half_run.session_id:
                return copy.deepcopy(half_run)
            return None

        def load_run(self, _run_id):
            return None

        def events_after(self, _run_id, *, after_id=None):
            return []

        def save_new_run(self, _run) -> None:
            self.save_attempts += 1
            raise failure

    store = PreexistingHalfRunStore()
    registry = LiveRunRegistry(live_store=store, worker_id="worker-candidate")

    with pytest.raises(RuntimeError) as raised:
        registry.get_or_create_active_run(
            session_id=half_run.session_id,
            villager_model="candidate-model",
            werewolf_model="candidate-model",
            seed=7,
            max_rounds=8,
        )

    assert raised.value is failure
    assert store.save_attempts == 1
    assert registry._runs == {}


def test_live_registry_publishes_to_subscriber_when_event_persistence_fails() -> None:
    registry = LiveRunRegistry()
    run = registry.create_run(
        session_id="game_1200abcd",
        villager_model="deepseek-chat",
        werewolf_model="deepseek-chat",
        seed=7,
        max_rounds=8,
    )
    subscriber = registry.subscribe(run.run_id, after_id=run.events[-1].id)
    registry.set_live_store(FailingLiveStore())

    event = registry.publish(run.run_id, "phase_started", phase="night")

    assert [item.type for item in run.events] == ["run_created", "phase_started"]
    assert subscriber.get_nowait() is event


def test_two_registries_converge_on_one_active_run_during_create_race() -> None:
    store = RacingActiveRunStore()
    registries = [
        LiveRunRegistry(live_store=store, worker_id="worker-a"),
        LiveRunRegistry(live_store=store, worker_id="worker-b"),
    ]

    def create_or_get(registry: LiveRunRegistry):
        return registry.get_or_create_active_run(
            session_id="game_1200abcd",
            villager_model="deepseek-chat",
            werewolf_model="deepseek-chat",
            seed=7,
            max_rounds=8,
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(create_or_get, registries))

    assert len({run.run_id for run, _created in results}) == 1
    assert sorted(created for _run, created in results) == [False, True]
    assert store.active_run is not None
    assert store.active_run.event_count == 1
    assert store.active_run.next_event_id == 2
    assert [event.type for event in store.active_run.events] == ["run_created"]


def test_live_registry_marks_completed_when_persistence_fails() -> None:
    registry = LiveRunRegistry()
    run = registry.create_run(
        session_id="game_1200abcd",
        villager_model="deepseek-chat",
        werewolf_model="deepseek-chat",
        seed=7,
        max_rounds=8,
    )
    registry.set_live_store(FailingLiveStore())

    event = registry.mark_completed(run.run_id, winner="好人阵营")

    assert run.status == "completed"
    assert event.type == "game_completed"
    assert run.events[-1] is event
