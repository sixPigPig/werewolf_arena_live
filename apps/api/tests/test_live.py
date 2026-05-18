from __future__ import annotations

import json

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
        "created_at",
        "started_at",
        "completed_at",
        "winner",
        "error",
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
    }


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
