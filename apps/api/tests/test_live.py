from __future__ import annotations

import json
import logging
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from app.werewolf.live import LiveRunRegistry, format_sse


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


class RecordingLiveStore:
    def __init__(self) -> None:
        self.saved_runs = []
        self.events = []

    def save_run(self, run) -> None:
        self.saved_runs.append((run.run_id, run.status, run.winner, run.error))

    def append_event(self, event) -> None:
        self.events.append((event.run_id, event.id, event.type))


class FailingLiveStore:
    def save_run(self, run) -> None:
        raise RuntimeError(f"cannot save {run.run_id}")

    def append_event(self, event) -> None:
        raise RuntimeError(f"cannot append {event.id}")


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

    def save_run(self, run) -> None:
        with self._lock:
            if self.active_run is not None:
                raise RuntimeError("unique active session conflict")
            self.active_run = run

    def append_event(self, _event) -> None:
        return None


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


def test_registry_summary_and_initial_event_use_public_run_fields() -> None:
    registry = LiveRunRegistry()

    run = registry.create_run(
        session_id="game_1200abcd",
        villager_model="deepseek-chat",
        werewolf_model="deepseek-chat",
        seed=21,
        max_rounds=8,
        **classic_rule_kwargs(),
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
        "rule_set",
        "player_configs",
        "lineup_quality_warnings",
    }
    assert summary["lineup_quality_warnings"] == []
    assert run.events[0].payload["lineup_quality_warnings"] == []


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
    assert any("Failed to persist live run" in record.message for record in caplog.records)


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
