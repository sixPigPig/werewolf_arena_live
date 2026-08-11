from __future__ import annotations

from typing import Any

from app.v2.contracts import (
    V2PublicPlayerSeatResponse,
    V2PublicRoleAssignmentStatusResponse,
    V2PublicRoleCountResponse,
    V2PublicRuleSnapshotResponse,
)


class V2PublicProjectionError(RuntimeError):
    pass


def project_public_role_assignment_status(
    assigned_count: int | None,
) -> V2PublicRoleAssignmentStatusResponse:
    if assigned_count is None:
        return V2PublicRoleAssignmentStatusResponse(state="unavailable", assigned_count=0)
    if not isinstance(assigned_count, int) or isinstance(assigned_count, bool):
        raise V2PublicProjectionError("invalid private role assignment count")
    if not 1 <= assigned_count <= 24:
        raise V2PublicProjectionError("invalid private role assignment count")
    return V2PublicRoleAssignmentStatusResponse(
        state="sealed",
        assigned_count=assigned_count,
    )


def project_public_rule_snapshot(
    rule_snapshot: dict[str, Any],
) -> V2PublicRuleSnapshotResponse | None:
    if not rule_snapshot:
        return None
    rule_set = rule_snapshot.get("rule_set")
    if not isinstance(rule_set, dict):
        if set(rule_snapshot) <= {
            "day_speech_pipeline_contract",
            "model_context_contract",
            "model_generation_policy_contract",
        }:
            return None
        raise V2PublicProjectionError("rule snapshot must contain a rule set")

    rule_id = _required_text(rule_set.get("id"), "rule id")
    name = _required_text(rule_set.get("name"), "rule name")
    version = _required_text(rule_set.get("version"), "rule version")
    player_count = _bounded_integer(rule_set.get("player_count"), "player count", 1, 24)
    max_rounds = _bounded_integer(rule_snapshot.get("max_rounds"), "max rounds", 1, 20)
    raw_roles = rule_set.get("roles")
    if not isinstance(raw_roles, list) or not raw_roles or len(raw_roles) > 24:
        raise V2PublicProjectionError("invalid public role composition")

    roles: list[V2PublicRoleCountResponse] = []
    seen_roles: set[str] = set()
    role_count = 0
    for value in raw_roles:
        if not isinstance(value, dict):
            raise V2PublicProjectionError("public role must be an object")
        role = _required_text(value.get("role"), "role")
        if role in seen_roles:
            raise V2PublicProjectionError("duplicate public role")
        count = _bounded_integer(value.get("count"), "role count", 1, 24)
        seen_roles.add(role)
        role_count += count
        roles.append(V2PublicRoleCountResponse(role=role, count=count))
    if role_count != player_count:
        raise V2PublicProjectionError("public role count does not match player count")

    return V2PublicRuleSnapshotResponse(
        rule_id=rule_id,
        name=name,
        version=version,
        player_count=player_count,
        roles=roles,
        max_rounds=max_rounds,
        sheriff_enabled=_optional_boolean(rule_set.get("sheriff_enabled"), "sheriff flag"),
        werewolf_self_explosion_enabled=_optional_boolean(
            rule_set.get("werewolf_self_explosion_enabled"),
            "self explosion flag",
        ),
        exile_last_words_enabled=_optional_boolean(
            rule_set.get("exile_last_words_enabled"),
            "last words flag",
        ),
        first_night_last_words_enabled=_optional_boolean(
            rule_set.get("first_night_last_words_enabled"),
            "first night last words flag",
        ),
    )


def project_public_player_seats(
    players_snapshot: list[dict[str, Any]],
    *,
    player_states: dict[str, Any] | None = None,
) -> list[V2PublicPlayerSeatResponse]:
    if len(players_snapshot) > 24:
        raise V2PublicProjectionError("too many player seats")

    seats: list[V2PublicPlayerSeatResponse] = []
    seen: set[int] = set()
    seen_player_ids: set[str] = set()
    for value in players_snapshot:
        if not isinstance(value, dict):
            raise V2PublicProjectionError("player snapshot must be an object")
        seat = value.get("seat")
        player_id = value.get("profile_id")
        name = value.get("name")
        avatar_url = value.get("avatar_image_url")
        if not isinstance(seat, int) or isinstance(seat, bool) or not 1 <= seat <= 24:
            raise V2PublicProjectionError("invalid player seat")
        if seat in seen:
            raise V2PublicProjectionError("duplicate player seat")
        if not isinstance(player_id, str) or not player_id.strip():
            raise V2PublicProjectionError("invalid public player id")
        normalized_player_id = player_id.strip()
        if normalized_player_id in seen_player_ids:
            raise V2PublicProjectionError("duplicate public player id")
        if name is not None and not isinstance(name, str):
            raise V2PublicProjectionError("invalid public player name")
        if avatar_url is not None and not isinstance(avatar_url, str):
            raise V2PublicProjectionError("invalid public avatar url")

        seen.add(seat)
        seen_player_ids.add(normalized_player_id)
        display_name = name.strip() if isinstance(name, str) else ""
        seats.append(
            V2PublicPlayerSeatResponse(
                seat=seat,
                player_id=normalized_player_id,
                display_name=display_name or f"{seat}号玩家",
                avatar_url=avatar_url.strip() if avatar_url and avatar_url.strip() else None,
                alive=(
                    bool(player_states[normalized_player_id].alive)
                    if player_states is not None and normalized_player_id in player_states
                    else True
                ),
            )
        )
    return sorted(seats, key=lambda item: item.seat)


def _required_text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise V2PublicProjectionError(f"invalid {label}")
    return value.strip()


def _bounded_integer(value: object, label: str, minimum: int, maximum: int) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or not minimum <= value <= maximum:
        raise V2PublicProjectionError(f"invalid {label}")
    return value


def _optional_boolean(value: object, label: str) -> bool | None:
    if value is None:
        return None
    if not isinstance(value, bool):
        raise V2PublicProjectionError(f"invalid {label}")
    return value
