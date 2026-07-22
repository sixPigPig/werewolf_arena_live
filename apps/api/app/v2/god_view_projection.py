from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from app.v2.contracts import V2GodViewPlayerIdentityResponse
from app.v2.models import V2RoleAssignment
from app.v2.public_projection import project_public_player_seats


class V2GodViewProjectionError(RuntimeError):
    pass


def project_god_view_player_identities(
    *,
    players_snapshot: list[dict[str, Any]],
    assignments: Sequence[V2RoleAssignment],
    player_states: dict[str, Any],
) -> list[V2GodViewPlayerIdentityResponse]:
    public_seats = project_public_player_seats(
        players_snapshot,
        player_states=player_states,
    )
    assignments_by_seat = {item.seat: item for item in assignments}
    if len(assignments_by_seat) != len(assignments):
        raise V2GodViewProjectionError("duplicate private assignment seat")
    if len(public_seats) != len(assignments_by_seat):
        raise V2GodViewProjectionError("private assignments do not cover every public seat")

    projected: list[V2GodViewPlayerIdentityResponse] = []
    for player in public_seats:
        assignment = assignments_by_seat.get(player.seat)
        if assignment is None or assignment.player_id != player.player_id:
            raise V2GodViewProjectionError("private assignment does not match public seat")
        player_state = player_states.get(player.player_id)
        if player_state is None:
            raise V2GodViewProjectionError("private player state is incomplete")
        projected.append(
            V2GodViewPlayerIdentityResponse(
                seat=player.seat,
                player_id=player.player_id,
                display_name=player.display_name,
                avatar_url=player.avatar_url,
                role=assignment.role,
                team=assignment.team,
                alive=player_state.alive,
                death_cause=player_state.death_cause,
            )
        )
    return projected
