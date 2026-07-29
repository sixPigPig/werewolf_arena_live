from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.v2.ability_runtime import (
    V2AbilityConfigurationError,
    ability_snapshot_hash,
    compile_ability_runtime_snapshot,
    resolve_first_night,
)


def test_rules_compile_different_ability_plans_without_role_flow_branches() -> None:
    social = _compile(
        roles=[("werewolf", "werewolves", 2), ("villager", "villagers", 6)],
        night_actions=["remove"],
    )
    classic = _compile(
        roles=[
            ("werewolf", "werewolves", 2),
            ("villager", "villagers", 4),
            ("seer", "villagers", 1),
            ("guard", "villagers", 1),
        ],
        night_actions=["remove", "protect", "investigate"],
    )
    advanced = _compile(
        roles=[
            ("werewolf", "werewolves", 4),
            ("villager", "villagers", 4),
            ("seer", "villagers", 1),
            ("witch", "villagers", 1),
            ("hunter", "villagers", 1),
            ("idiot", "villagers", 1),
        ],
        night_actions=["remove", "investigate", "witch_save", "witch_poison"],
        sheriff_enabled=True,
    )

    assert _ability_ids(social) == ["werewolf.attack"]
    assert _ability_ids(classic) == [
        "werewolf.attack",
        "guard.protect",
        "seer.investigate",
    ]
    assert _ability_ids(advanced) == [
        "werewolf.attack",
        "seer.investigate",
        "witch.heal",
        "witch.poison",
        "hunter.death_shot",
    ]
    assert classic["policies"]["werewolf_attack"] == {
        "resolution": "unanimous_no_attack",
        "allow_no_attack": False,
        "allow_wolf_target": False,
    }
    assert classic["policies"]["guard"] == {
        "first_night_self_protect": True,
        "consecutive_same_target": False,
    }
    assert advanced["next_windows"]["normal"] == "sheriff_election_ready"
    assert ability_snapshot_hash(advanced) == advanced["snapshot_hash"]


def test_missing_night_actions_are_derived_only_from_frozen_roles() -> None:
    snapshot = _compile(
        roles=[
            ("狼人", "werewolves", 2),
            ("村民", "villagers", 4),
            ("预言家", "villagers", 1),
            ("守卫", "villagers", 1),
        ],
        night_actions=None,
    )

    assert snapshot["action_source"] == "derived_from_frozen_roles"
    assert _ability_ids(snapshot) == [
        "werewolf.attack",
        "guard.protect",
        "seer.investigate",
    ]
    assert {item["role_key"] for item in snapshot["assignments"]} == {
        "werewolf",
        "villager",
        "seer",
        "guard",
    }


def test_frozen_werewolf_attack_policy_is_compiled_into_ability_snapshot() -> None:
    snapshot = _compile(
        roles=[("werewolf", "werewolves", 2), ("villager", "villagers", 6)],
        night_actions=["remove"],
        werewolf_attack_policy={
            "resolution": "plurality_seeded_random",
            "allow_no_attack": True,
            "allow_wolf_target": True,
        },
    )

    assert snapshot["policies"]["werewolf_attack"] == {
        "resolution": "plurality_seeded_random",
        "allow_no_attack": True,
        "allow_wolf_target": True,
    }


def test_unknown_or_role_mismatched_night_action_fails_closed() -> None:
    with pytest.raises(V2AbilityConfigurationError, match="unknown night actions"):
        _compile(
            roles=[("werewolf", "werewolves", 2), ("villager", "villagers", 6)],
            night_actions=["remove", "dream"],
        )

    with pytest.raises(V2AbilityConfigurationError, match="do not match assigned roles"):
        _compile(
            roles=[("werewolf", "werewolves", 2), ("villager", "villagers", 6)],
            night_actions=["remove", "protect"],
        )


@pytest.mark.parametrize(
    ("protected", "healed", "poisoned", "expected", "prevented_by"),
    [
        (None, None, None, ({"player_id": "p1", "cause": "werewolf_attack"},), None),
        ("p1", None, None, (), "protect"),
        (None, "p1", None, (), "heal"),
        (
            None,
            None,
            "p2",
            (
                {"player_id": "p1", "cause": "werewolf_attack"},
                {"player_id": "p2", "cause": "witch_poison"},
            ),
            None,
        ),
    ],
)
def test_first_night_resolution_is_deterministic(
    protected: str | None,
    healed: str | None,
    poisoned: str | None,
    expected: tuple[dict[str, str], ...],
    prevented_by: str | None,
) -> None:
    result = resolve_first_night(
        attack_target="p1",
        protected_target=protected,
        healed_target=healed,
        poisoned_target=poisoned,
    )

    assert result.deaths == expected
    assert result.peaceful is (not expected)
    assert result.attack_prevented_by == prevented_by


def _compile(
    *,
    roles: list[tuple[str, str, int]],
    night_actions: list[str] | None,
    sheriff_enabled: bool = False,
    werewolf_attack_policy: dict[str, object] | None = None,
) -> dict[str, object]:
    assignments = []
    seat = 1
    role_rows = []
    for role, team, count in roles:
        role_rows.append({"role": role, "count": count, "team": team})
        for _ in range(count):
            assignments.append(
                SimpleNamespace(
                    seat=seat,
                    player_id=f"player-{seat}",
                    role=role,
                    team=team,
                )
            )
            seat += 1
    rule_set: dict[str, object] = {
        "id": "test_rule",
        "version": "1",
        "roles": role_rows,
        "sheriff_enabled": sheriff_enabled,
        "win_condition": "wolves_gte_others",
    }
    if night_actions is not None:
        rule_set["night_actions"] = night_actions
    if werewolf_attack_policy is not None:
        rule_set["werewolf_attack_policy"] = werewolf_attack_policy
    return compile_ability_runtime_snapshot(
        game_id="v2_game_0123456789abcdef",
        rule_snapshot={"rule_set": rule_set},
        assignments=assignments,
    )


def _ability_ids(snapshot: dict[str, object]) -> list[str]:
    instances = snapshot["instances"]
    assert isinstance(instances, list)
    return [str(item["ability_id"]) for item in instances]
