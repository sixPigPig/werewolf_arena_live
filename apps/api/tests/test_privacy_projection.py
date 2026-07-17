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
                "terminal_recovery": True,
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
        "terminal_recovery": True,
    }


def test_public_model_progress_keeps_opaque_action_correlation_id() -> None:
    projected = project_live_event(
        _event(
            "model_request_started",
            action="debate",
            payload={
                "action_id": "act_public_safe",
                "request_id": "req_public_safe",
                "model": "test-model",
                "prompt": "private prompt",
            },
        ),
        "player_public",
    )

    assert projected is not None
    assert projected.payload == {
        "action_id": "act_public_safe",
        "request_id": "req_public_safe",
        "model": "test-model",
    }


@pytest.mark.parametrize("audience", ["player_public", "spectator_god_view"])
def test_hunter_result_projection_preserves_public_presentation_semantics(
    audience: str,
) -> None:
    projected = project_live_event(
        _event(
            "state_updated",
            action="hunter_shot_resolved",
            payload={
                "presentation_id": "hp_0123456789abcdef01234567",
                "hunter_shot_status": "skipped",
                "hunter_shot": None,
                "deaths": [{"player": "2号玩家", "cause": "vote_exile"}],
                "active_players": ["1号玩家", "3号玩家"],
                "private_note": "drop-me",
            },
        ),
        audience,  # type: ignore[arg-type]
    )

    assert projected is not None
    assert projected.payload == {
        "presentation_id": "hp_0123456789abcdef01234567",
        "hunter_shot_status": "skipped",
        "hunter_shot": None,
        "deaths": [{"player": "2号玩家"}],
        "active_players": ["1号玩家", "3号玩家"],
    }


@pytest.mark.parametrize("audience", ["player_public", "spectator_god_view"])
def test_game_completed_keeps_terminal_playback_boundary(audience: str) -> None:
    projected = project_live_event(
        _event(
            "game_completed",
            payload={
                "winner": "好人阵营",
                "terminal_keep_from_event_id": 5,
                "private_note": "must be removed",
            },
        ),
        audience,  # type: ignore[arg-type]
    )

    assert projected is not None
    assert projected.payload == {
        "winner": "好人阵营",
        "terminal_keep_from_event_id": 5,
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


def test_werewolf_discussion_is_god_view_only_and_keeps_safe_message() -> None:
    event = _event(
        "action_parsed",
        action="werewolf_discuss",
        payload={
            "choice": "3号玩家",
            "decision_stage": "proposal",
            "message": "建议刀3号，他像预言家。",
            "result": {
                "target": "3号玩家",
                "message": "建议刀3号，他像预言家。",
                "reasoning": "private chain of thought",
            },
            "raw_response": "private",
        },
    )

    assert project_live_event(event, "player_public") is None
    projected = project_live_event(event, "spectator_god_view")

    assert projected is not None
    assert projected.payload == {
        "choice": "3号玩家",
        "decision_stage": "proposal",
        "message": "建议刀3号，他像预言家。",
        "result": {
            "target": "3号玩家",
            "message": "建议刀3号，他像预言家。",
        },
    }


def test_werewolf_tiebreak_judge_cue_is_hidden_until_god_view_projection() -> None:
    event = _event(
        "judge_cue",
        action="werewolf_tiebreak_start",
        payload={
            "schema_version": 1,
            "cue_id": "werewolf_tiebreak_start",
            "visible_text": "狼队刀口出现平票。本夜由2号玩家行使归票权。",
            "static_asset_id": None,
            "params": {
                "player": "2号玩家",
                "players": ["3号玩家", "4号玩家"],
            },
        },
    )

    assert project_live_event(event, "player_public") is None
    projected = project_live_event(event, "spectator_god_view")

    assert projected is not None
    assert projected.payload["cue_id"] == "werewolf_tiebreak_start"
    assert projected.payload["params"] == {
        "player": "2号玩家",
        "players": ["3号玩家", "4号玩家"],
    }


def test_night_resolution_preserves_public_death_without_cause_or_source() -> None:
    projected = project_live_event(
        _event(
            "state_updated",
            action="night_resolved",
            payload={
                "presentation_id": "pp_0123456789abcdef01234567",
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
        "presentation_id": "pp_0123456789abcdef01234567",
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
