from __future__ import annotations

from typing import Any

from app.match.contracts import DirectorSceneResponse


def project_director_scene(
    *,
    phase_id: str,
    phase_state: str,
    action_context: dict[str, Any] | None = None,
) -> DirectorSceneResponse:
    action_type = _optional_text(
        action_context.get("action_type") if action_context is not None else None
    )
    action_id = _optional_text(
        action_context.get("action_id") if action_context is not None else None
    )
    ability_id = _optional_text(
        action_context.get("ability_id") if action_context is not None else None
    )
    actor_player_id = None
    actor = action_context.get("actor") if action_context is not None else None
    if isinstance(actor, dict) and actor.get("kind") == "player":
        actor_player_id = _optional_text(actor.get("id"))
    return DirectorSceneResponse(
        scene_kind=_scene_kind(
            phase_id=phase_id,
            phase_state=phase_state,
            action_type=action_type,
        ),
        action_id=action_id,
        action_type=action_type,
        ability_id=ability_id,
        actor_player_id=actor_player_id,
    )


def _scene_kind(*, phase_id: str, phase_state: str, action_type: str | None) -> str:
    normalized = (action_type or "").lower()
    if "game_completed" in normalized or phase_state == "game_completed":
        return "terminal"
    if "dawn" in normalized:
        return "dawn"
    if phase_id == "first_night" or phase_id.startswith("night_"):
        if "werewolf" in normalized:
            return "werewolves"
        if "guard" in normalized:
            return "guard"
        if "seer" in normalized:
            return "seer"
        if "witch" in normalized:
            return "witch"
        if "hunter" in normalized:
            return "hunter"
        return "nightfall"
    if "hunter" in normalized:
        return "hunter"
    if phase_id.startswith("day_"):
        return "public_stage"
    return "opening"


def _optional_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None
