from __future__ import annotations

from dataclasses import dataclass
import hashlib
import hmac
import json
from typing import Any

from app.v2.ability_runtime import normalize_role_key, normalize_team_key


class V2RoleAssignmentError(RuntimeError):
    pass


@dataclass(frozen=True)
class V2AssignedRole:
    seat: int
    player_id: str
    role: str
    role_key: str
    team: str | None


@dataclass(frozen=True)
class V2RoleAssignmentResult:
    assignments: tuple[V2AssignedRole, ...]
    digest: str


def assign_private_roles(
    *,
    players_snapshot: list[dict[str, Any]],
    rule_snapshot: dict[str, Any],
    seed_hex: str,
) -> V2RoleAssignmentResult:
    try:
        seed = bytes.fromhex(seed_hex)
    except ValueError as exc:
        raise V2RoleAssignmentError("invalid private role seed") from exc
    if len(seed) != 32 or seed.hex() != seed_hex:
        raise V2RoleAssignmentError("invalid private role seed")

    players = _players(players_snapshot)
    role_cards = _role_cards(rule_snapshot)
    if len(players) != len(role_cards):
        raise V2RoleAssignmentError("role count does not match player count")

    context = json.dumps(
        {
            "players": [{"seat": seat, "player_id": player_id} for seat, player_id in players],
            "roles": [
                {"role": role, "role_key": role_key, "team": team}
                for role, role_key, team in role_cards
            ],
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    shuffled = [
        card
        for _key, _index, card in sorted(
            (
                hmac.digest(seed, context + index.to_bytes(2, "big"), "sha256"),
                index,
                card,
            )
            for index, card in enumerate(role_cards)
        )
    ]
    assignments = tuple(
        V2AssignedRole(
            seat=seat,
            player_id=player_id,
            role=role,
            role_key=role_key,
            team=team,
        )
        for (seat, player_id), (role, role_key, team) in zip(players, shuffled, strict=True)
    )
    canonical = json.dumps(
        [
            {
                "player_id": item.player_id,
                "role": item.role,
                "role_key": item.role_key,
                "seat": item.seat,
                "team": item.team,
            }
            for item in assignments
        ],
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return V2RoleAssignmentResult(
        assignments=assignments,
        digest=hashlib.sha256(canonical).hexdigest(),
    )


def _players(players_snapshot: list[dict[str, Any]]) -> list[tuple[int, str]]:
    if not players_snapshot or len(players_snapshot) > 24:
        raise V2RoleAssignmentError("invalid player snapshot")
    players: list[tuple[int, str]] = []
    seats: set[int] = set()
    player_ids: set[str] = set()
    for value in players_snapshot:
        if not isinstance(value, dict):
            raise V2RoleAssignmentError("invalid player snapshot")
        seat = value.get("seat")
        player_id = value.get("profile_id")
        if not isinstance(seat, int) or isinstance(seat, bool) or not 1 <= seat <= 24:
            raise V2RoleAssignmentError("invalid player seat")
        if not isinstance(player_id, str) or not player_id.strip():
            raise V2RoleAssignmentError("invalid player id")
        normalized_player_id = player_id.strip()
        if seat in seats or normalized_player_id in player_ids:
            raise V2RoleAssignmentError("duplicate player in private assignment")
        seats.add(seat)
        player_ids.add(normalized_player_id)
        players.append((seat, normalized_player_id))
    players.sort(key=lambda item: item[0])
    if [seat for seat, _player_id in players] != list(range(1, len(players) + 1)):
        raise V2RoleAssignmentError("player seats must be contiguous")
    return players


def _role_cards(rule_snapshot: dict[str, Any]) -> list[tuple[str, str, str]]:
    rule_set = rule_snapshot.get("rule_set")
    if not isinstance(rule_set, dict):
        raise V2RoleAssignmentError("rule snapshot must contain a rule set")
    roles = rule_set.get("roles")
    if not isinstance(roles, list) or not roles or len(roles) > 24:
        raise V2RoleAssignmentError("invalid role composition")
    cards: list[tuple[str, str, str]] = []
    seen_roles: set[str] = set()
    for value in roles:
        if not isinstance(value, dict):
            raise V2RoleAssignmentError("invalid role composition")
        role = value.get("role")
        count = value.get("count")
        team = value.get("team")
        if not isinstance(role, str) or not role.strip():
            raise V2RoleAssignmentError("invalid role")
        normalized_role = role.strip()
        role_key = normalize_role_key(normalized_role)
        if normalized_role in seen_roles:
            raise V2RoleAssignmentError("duplicate role")
        if not isinstance(count, int) or isinstance(count, bool) or not 1 <= count <= 24:
            raise V2RoleAssignmentError("invalid role count")
        if team is not None and (not isinstance(team, str) or not team.strip()):
            raise V2RoleAssignmentError("invalid role team")
        seen_roles.add(normalized_role)
        normalized_team = (
            team.strip()
            if isinstance(team, str) and team.strip()
            else normalize_team_key(team, role_key=role_key)
        )
        cards.extend((normalized_role, role_key, normalized_team) for _ in range(count))
        if len(cards) > 24:
            raise V2RoleAssignmentError("too many role cards")
    return cards
