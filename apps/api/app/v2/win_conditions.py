from __future__ import annotations

from collections.abc import Mapping, Sequence


DEFAULT_WIN_CONDITION = "wolves_gte_others"
SLAUGHTER_SIDE_WIN_CONDITION = "slaughter_side"


def normalize_win_condition(value: object) -> str:
    return (
        SLAUGHTER_SIDE_WIN_CONDITION
        if value == SLAUGHTER_SIDE_WIN_CONDITION
        else DEFAULT_WIN_CONDITION
    )


def build_public_win_condition_contract(
    win_condition: object,
    *,
    frozen_role_keys: Sequence[str],
) -> dict[str, object]:
    mode = normalize_win_condition(win_condition)
    role_keys = tuple(
        dict.fromkeys(
            role_key.strip()
            for role_key in frozen_role_keys
            if isinstance(role_key, str) and role_key.strip()
        )
    )
    god_role_keys = [role_key for role_key in role_keys if role_key not in {"werewolf", "villager"}]
    groups: dict[str, object] = {
        "living_werewolves": {"role_keys": ["werewolf"]},
    }
    if mode == SLAUGHTER_SIDE_WIN_CONDITION:
        groups.update(
            {
                "living_villagers": {"role_keys": ["villager"]},
                "living_gods": {"role_keys": god_role_keys},
            }
        )
        werewolves_victory: dict[str, object] = {
            "operator": "any",
            "conditions": [
                {
                    "metric": "living_villagers",
                    "operator": "eq",
                    "value": 0,
                    "boundary": "slaughter_villagers",
                },
                {
                    "metric": "living_gods",
                    "operator": "eq",
                    "value": 0,
                    "boundary": "slaughter_gods",
                },
            ],
        }
    else:
        groups["living_non_werewolves"] = {
            "role_keys": [role_key for role_key in role_keys if role_key != "werewolf"],
        }
        werewolves_victory = {
            "left_metric": "living_werewolves",
            "operator": "gte",
            "right_metric": "living_non_werewolves",
            "boundary": "werewolf_parity",
        }
    return {
        "schema_version": 1,
        "mode": mode,
        "evaluation_order": ["villagers", "werewolves"],
        "post_elimination_resolution": {
            "check": "after_each_elimination_before_next_ordinary_action",
            "outcome_changing_death_triggers": "resolve_before_final_result",
        },
        "groups": groups,
        "villagers_victory": {
            "metric": "living_werewolves",
            "operator": "eq",
            "value": 0,
        },
        "werewolves_victory": werewolves_victory,
    }


def winner_from_alive_roles(
    alive_roles: Sequence[str],
    *,
    win_condition: str,
) -> str | None:
    normalized_win_condition = normalize_win_condition(win_condition)
    wolves = sum(role == "werewolf" for role in alive_roles)
    others = len(alive_roles) - wolves
    if wolves == 0:
        return "villagers"
    if normalized_win_condition == SLAUGHTER_SIDE_WIN_CONDITION:
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
