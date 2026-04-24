from __future__ import annotations

from app.werewolf.live import LiveRunRegistry


def test_registry_creates_run_with_initial_event() -> None:
    registry = LiveRunRegistry()

    run = registry.create_run(
        session_id="session_20260424_120000_ab12cd34",
        villager_model="deepseek-chat",
        werewolf_model="deepseek-chat",
        seed=21,
        max_rounds=8,
    )

    assert run.run_id.startswith("run_")
    assert run.session_id == "session_20260424_120000_ab12cd34"
    assert run.status == "queued"
    assert run.event_count == 1
    assert run.events[0].type == "run_created"


def test_registry_appends_ordered_events_and_replays_after_id() -> None:
    registry = LiveRunRegistry()
    run = registry.create_run(
        session_id="session_20260424_120000_ab12cd34",
        villager_model="deepseek-chat",
        werewolf_model="deepseek-chat",
        seed=None,
        max_rounds=8,
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
        session_id="session_20260424_120000_ab12cd34",
        villager_model="deepseek-chat",
        werewolf_model="deepseek-chat",
        seed=None,
        max_rounds=8,
    )
    failed = registry.create_run(
        session_id="session_20260424_120001_cd34ab12",
        villager_model="deepseek-chat",
        werewolf_model="deepseek-chat",
        seed=None,
        max_rounds=8,
    )

    registry.mark_running(completed.run_id)
    registry.mark_completed(completed.run_id, winner="狼人阵营")
    registry.mark_failed(failed.run_id, error="Maximum rounds exceeded")

    assert registry.get_run(completed.run_id).status == "completed"
    assert registry.get_run(completed.run_id).completed_at is not None
    assert registry.get_run(completed.run_id).events[-1].type == "game_completed"
    assert registry.get_run(failed.run_id).status == "failed"
    assert registry.get_run(failed.run_id).error == "Maximum rounds exceeded"
    assert registry.get_run(failed.run_id).events[-1].type == "game_failed"
