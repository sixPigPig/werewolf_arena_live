from __future__ import annotations

from app.werewolf.session_timeline import TimelineRun, build_session_timeline


def _event(
    run_id: str,
    event_id: int,
    event_type: str,
    *,
    round_number: int | None = None,
) -> dict[str, object]:
    return {
        "id": event_id,
        "source_event_id": event_id,
        "type": event_type,
        "run_id": run_id,
        "session_id": "game_timeline",
        "created_at": f"2026-07-15T00:00:{event_id:02d}Z",
        "audience": "player_public",
        "projection_version": 1,
        "round": round_number,
        "phase": None,
        "actor": None,
        "action": None,
        "payload": {},
    }


def test_session_timeline_replaces_retried_rounds_and_old_terminal_events() -> None:
    runs = [
        TimelineRun("run_1", "2026-07-15T00:00:00Z", 1),
        TimelineRun("run_2", "2026-07-15T00:01:00Z", 2, "run_1", 2),
        TimelineRun("run_3", "2026-07-15T00:02:00Z", 3, "run_2", 3),
        TimelineRun("run_4", "2026-07-15T00:03:00Z", 4, "run_3", 4),
    ]
    events_by_run = {
        "run_1": [
            _event("run_1", 1, "game_started"),
            _event("run_1", 2, "round_started", round_number=1),
            _event("run_1", 3, "round_started", round_number=2),
            _event("run_1", 4, "game_failed"),
        ],
        "run_2": [
            _event("run_2", 1, "game_started"),
            _event("run_2", 2, "round_started", round_number=2),
            _event("run_2", 3, "round_started", round_number=3),
            _event("run_2", 4, "game_failed"),
        ],
        "run_3": [
            _event("run_3", 1, "game_resumed"),
            _event("run_3", 2, "round_started", round_number=3),
            _event("run_3", 3, "round_started", round_number=4),
            _event("run_3", 4, "game_failed"),
        ],
        "run_4": [
            _event("run_4", 1, "game_resumed"),
            _event("run_4", 2, "round_started", round_number=4),
            _event("run_4", 3, "game_completed"),
        ],
    }

    timeline = build_session_timeline(
        session_id="game_timeline",
        runs=runs,
        projected_events_by_run=events_by_run,
    )

    assert [event.id for event in timeline.events] == list(range(1, 10))
    assert [event.type for event in timeline.events].count("game_started") == 1
    assert [event.type for event in timeline.events].count("game_resumed") == 3
    assert [event.round for event in timeline.events if event.type == "round_started"] == [
        1,
        2,
        3,
        4,
    ]
    assert [event.type for event in timeline.events if event.type.startswith("game_")][-1] == (
        "game_completed"
    )
    assert timeline.current_run_id == "run_4"
    assert timeline.current_run_start_event_id == 7


def test_session_timeline_legacy_resume_converts_duplicate_game_started() -> None:
    timeline = build_session_timeline(
        session_id="game_timeline",
        runs=[
            TimelineRun("run_1", "2026-07-15T00:00:00Z", 1),
            TimelineRun("run_2", "2026-07-15T00:01:00Z", 2, "run_1", 2),
        ],
        projected_events_by_run={
            "run_1": [_event("run_1", 1, "game_started")],
            "run_2": [_event("run_2", 1, "game_started")],
        },
    )

    assert [event.type for event in timeline.events] == ["game_started", "game_resumed"]
    assert timeline.events[1].payload == {
        "parent_run_id": "run_1",
        "resume_from_round": 2,
        "attempt_no": 2,
    }
