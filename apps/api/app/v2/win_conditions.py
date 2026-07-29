from __future__ import annotations

from collections.abc import Mapping, Sequence


def winner_from_alive_roles(
    alive_roles: Sequence[str],
    *,
    win_condition: str,
) -> str | None:
    wolves = sum(role == "werewolf" for role in alive_roles)
    others = len(alive_roles) - wolves
    if wolves == 0:
        return "villagers"
    if win_condition == "slaughter_side":
        villagers = sum(role == "villager" for role in alive_roles)
        gods = sum(role not in {"werewolf", "villager"} for role in alive_roles)
        return "werewolves" if villagers == 0 or gods == 0 else None
    return "werewolves" if wolves >= others else None


def all_hunter_settlement_branches_terminal(
    *,
    living_player_ids: frozenset[str],
    pending_hunter_ids: tuple[str, ...],
    role_by_player_id: Mapping[str, str],
    win_condition: str,
) -> bool:
    def visit(
        living: frozenset[str],
        unresolved_hunters: tuple[str, ...],
    ) -> bool:
        if not unresolved_hunters:
            return (
                winner_from_alive_roles(
                    [role_by_player_id[player_id] for player_id in living],
                    win_condition=win_condition,
                )
                is not None
            )
        _hunter_id, *remaining = unresolved_hunters
        for target_id in (None, *sorted(living)):
            next_living = set(living)
            next_hunters = list(remaining)
            if target_id is not None:
                next_living.remove(target_id)
                if role_by_player_id.get(target_id) == "hunter":
                    next_hunters.append(target_id)
            if not visit(frozenset(next_living), tuple(next_hunters)):
                return False
        return True

    return visit(living_player_ids, pending_hunter_ids)


def hunter_settlement_can_change_winner(
    *,
    living_player_ids: frozenset[str],
    pending_hunter_ids: tuple[str, ...],
    role_by_player_id: Mapping[str, str],
    win_condition: str,
) -> bool:
    if not pending_hunter_ids:
        return False
    baseline = winner_from_alive_roles(
        [role_by_player_id[player_id] for player_id in living_player_ids],
        win_condition=win_condition,
    )
    if baseline is None:
        return True

    def visit(
        living: frozenset[str],
        unresolved_hunters: tuple[str, ...],
    ) -> bool:
        if not unresolved_hunters:
            return (
                winner_from_alive_roles(
                    [role_by_player_id[player_id] for player_id in living],
                    win_condition=win_condition,
                )
                != baseline
            )
        _hunter_id, *remaining = unresolved_hunters
        for target_id in (None, *sorted(living)):
            next_living = set(living)
            next_hunters = list(remaining)
            if target_id is not None:
                next_living.remove(target_id)
                if role_by_player_id.get(target_id) == "hunter":
                    next_hunters.append(target_id)
            if visit(frozenset(next_living), tuple(next_hunters)):
                return True
        return False

    return visit(living_player_ids, pending_hunter_ids)
