from __future__ import annotations

from typing import Any

from app.v2.contracts import V2PublicPlayerSeatResponse


class V2PublicProjectionError(RuntimeError):
    pass


def project_public_player_seats(
    players_snapshot: list[dict[str, Any]],
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
            )
        )
    return sorted(seats, key=lambda item: item.seat)
