from __future__ import annotations

import pytest

from app.werewolf.live import LiveEvent, format_sse
from app.werewolf.privacy_projection import project_live_event


def _event(
    event_type: str,
    *,
    action: str | None = None,
    payload: dict | None = None,
) -> LiveEvent:
    return LiveEvent(
        id=7,
        type=event_type,
        run_id="run_privacy",
        session_id="game_privacy",
        created_at="2026-07-15T00:00:00Z",
        round=1,
        phase="night",
        actor="1号玩家",
        action=action,
        payload=payload or {},
    )


def test_public_game_started_excludes_role_and_private_player_state() -> None:
    projected = project_live_event(
        _event(
            "game_started",
            payload={
                "players": [
                    {
                        "name": "1号玩家",
                        "model": "test-model",
                        "personality": "谨慎",
                        "role": "狼人",
                        "known_roles": {"2号玩家": "狼人"},
                        "observations": ["private"],
                        "gamestate": {"wolf_teammates": ["2号玩家"]},
                        "resources": {"antidote": 1},
                    }
                ],
                "active_players": ["1号玩家"],
                "rule_set": {
                    "roles": [{"role": "狼人", "team": "werewolf", "count": 2}]
                },
            },
        ),
        "player_public",
    )

    assert projected is not None
    assert projected.audience == "player_public"
    assert projected.source_event_id == 7
    assert projected.payload["players"] == [
        {"name": "1号玩家", "model": "test-model", "personality": "谨慎"}
    ]
    assert projected.payload["rule_set"]["roles"] == [
        {"role": "狼人", "team": "werewolf", "count": 2}
    ]


def test_god_view_game_started_includes_role_but_not_private_memory() -> None:
    projected = project_live_event(
        _event(
            "game_started",
            payload={
                "players": [
                    {
                        "name": "1号玩家",
                        "role": "狼人",
                        "known_roles": {"2号玩家": "狼人"},
                        "observations": ["private"],
                    }
                ]
            },
        ),
        "spectator_god_view",
    )

    assert projected is not None
    assert projected.payload["players"] == [{"name": "1号玩家", "role": "狼人"}]


def test_public_game_resumed_keeps_only_resume_boundary_metadata() -> None:
    projected = project_live_event(
        _event(
            "game_resumed",
            payload={
                "active_players": ["1号玩家"],
                "parent_run_id": "run_parent",
                "resume_from_round": 4,
                "attempt_no": 3,
                "private_error": "secret",
            },
        ),
        "player_public",
    )

    assert projected is not None
    assert projected.payload == {
        "active_players": ["1号玩家"],
        "parent_run_id": "run_parent",
        "resume_from_round": 4,
        "attempt_no": 3,
    }


def test_public_projection_drops_private_night_actions() -> None:
    assert (
        project_live_event(
            _event(
                "action_parsed",
                action="werewolf_kill_vote",
                payload={"choice": "3号玩家"},
            ),
            "player_public",
        )
        is None
    )


def test_god_view_gets_structured_night_result_without_raw_reasoning() -> None:
    projected = project_live_event(
        _event(
            "action_parsed",
            action="werewolf_kill_vote",
            payload={
                "choice": "3号玩家",
                "result": {"target": "3号玩家", "reasoning": "private"},
                "raw_response": "private",
            },
        ),
        "spectator_god_view",
    )

    assert projected is not None
    assert projected.payload == {
        "choice": "3号玩家",
        "result": {"target": "3号玩家"},
    }


def test_night_resolution_preserves_public_death_without_cause_or_source() -> None:
    projected = project_live_event(
        _event(
            "state_updated",
            action="night_resolved",
            payload={
                "attacked": "3号玩家",
                "protected": "4号玩家",
                "night_deaths": [
                    {"player": "3号玩家", "cause": "wolf_kill", "source": "1号玩家"}
                ],
                "active_players": ["1号玩家", "2号玩家"],
            },
        ),
        "player_public",
    )

    assert projected is not None
    assert projected.payload == {
        "night_deaths": [{"player": "3号玩家"}],
        "active_players": ["1号玩家", "2号玩家"],
        "peaceful_night": False,
    }


def test_public_speech_delta_remains_visible() -> None:
    projected = project_live_event(
        _event(
            "model_response_delta",
            action="debate",
            payload={"delta": "我认为2号可疑", "is_public": True},
        ),
        "player_public",
    )

    assert projected is not None
    assert projected.payload["delta"] == "我认为2号可疑"


def test_failed_run_never_receives_terminal_role_reveal() -> None:
    projected = project_live_event(
        _event(
            "game_failed",
            payload={
                "error": "raw provider error private",
                "message": "中断",
                "roles": {"1号玩家": "狼人"},
            },
        ),
        "player_public",
    )

    assert projected is not None
    assert projected.payload == {"message": "对局异常中断。"}


def test_unknown_event_and_action_fail_closed() -> None:
    assert project_live_event(_event("debug_dump"), "player_public") is None
    assert (
        project_live_event(
            _event("action_parsed", action="new_secret_action"),
            "spectator_god_view",
        )
        is None
    )


def test_nested_camel_case_forbidden_fields_are_removed() -> None:
    projected = project_live_event(
        _event(
            "action_parsed",
            action="debate",
            payload={
                "visible_result": {"say": "公开发言"},
                "metadata": {
                    "rawResponse": "private",
                    "system-prompt": "private",
                    "knownRoles": {"2号玩家": "狼人"},
                },
            },
        ),
        "player_public",
    )

    assert projected is not None
    assert projected.payload == {
        "visible_result": {"say": "公开发言"},
    }


def test_raw_live_event_cannot_be_serialized_as_sse() -> None:
    with pytest.raises(TypeError, match="audience-projected"):
        format_sse(_event("game_started"))  # type: ignore[arg-type]
