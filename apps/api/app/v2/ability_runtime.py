from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
import hashlib
import json
from typing import Any, Literal


class V2AbilityConfigurationError(RuntimeError):
    pass


OwnerScope = Literal["player", "team"]


@dataclass(frozen=True)
class V2AbilityDefinition:
    ability_id: str
    ability_version: int
    action_name: str
    owner_role_key: str
    owner_scope: OwnerScope
    activation_group: str
    window_type: str
    trigger: str
    order: int
    dependencies: tuple[str, ...]
    decision_contract_id: str
    target_policy_id: str
    effect_type: str
    presentation_policy_id: str
    blocking: bool = True


@dataclass(frozen=True)
class V2NightResolution:
    deaths: tuple[dict[str, str], ...]
    peaceful: bool
    attack_prevented_by: str | None


_ROLE_KEYS = {
    "werewolf": "werewolf",
    "狼人": "werewolf",
    "villager": "villager",
    "村民": "villager",
    "seer": "seer",
    "预言家": "seer",
    "guard": "guard",
    "守卫": "guard",
    "witch": "witch",
    "女巫": "witch",
    "hunter": "hunter",
    "猎人": "hunter",
    "idiot": "idiot",
    "白痴": "idiot",
}

_TEAM_KEYS = {
    "werewolves": "werewolves",
    "werewolf": "werewolves",
    "狼队": "werewolves",
    "villagers": "villagers",
    "village": "villagers",
    "good": "villagers",
    "好人": "villagers",
}

ABILITY_REGISTRY: dict[str, V2AbilityDefinition] = {
    "werewolf.attack": V2AbilityDefinition(
        ability_id="werewolf.attack",
        ability_version=1,
        action_name="remove",
        owner_role_key="werewolf",
        owner_scope="team",
        activation_group="werewolves",
        window_type="night",
        trigger="window_opened",
        order=10,
        dependencies=(),
        decision_contract_id="werewolf_consensus_target.v1",
        target_policy_id="alive_non_werewolf.v1",
        effect_type="attack",
        presentation_policy_id="private_team_turn.v1",
    ),
    "guard.protect": V2AbilityDefinition(
        ability_id="guard.protect",
        ability_version=1,
        action_name="protect",
        owner_role_key="guard",
        owner_scope="player",
        activation_group="guard",
        window_type="night",
        trigger="window_opened",
        order=20,
        dependencies=(),
        decision_contract_id="choose_one_alive.v1",
        target_policy_id="alive_guard_self_allowed_no_repeat.v1",
        effect_type="protect",
        presentation_policy_id="private_role_turn.v1",
    ),
    "seer.investigate": V2AbilityDefinition(
        ability_id="seer.investigate",
        ability_version=1,
        action_name="investigate",
        owner_role_key="seer",
        owner_scope="player",
        activation_group="seer",
        window_type="night",
        trigger="window_opened",
        order=30,
        dependencies=(),
        decision_contract_id="choose_one_alive.v1",
        target_policy_id="alive_non_self.v1",
        effect_type="investigate",
        presentation_policy_id="private_role_turn_with_result.v1",
    ),
    "witch.heal": V2AbilityDefinition(
        ability_id="witch.heal",
        ability_version=1,
        action_name="witch_save",
        owner_role_key="witch",
        owner_scope="player",
        activation_group="witch",
        window_type="night",
        trigger="provisional_attack_available",
        order=40,
        dependencies=("werewolf.attack",),
        decision_contract_id="optional_attacked_target.v1",
        target_policy_id="current_attack_target_first_night_self_allowed.v1",
        effect_type="heal",
        presentation_policy_id="private_role_turn.v1",
    ),
    "witch.poison": V2AbilityDefinition(
        ability_id="witch.poison",
        ability_version=1,
        action_name="witch_poison",
        owner_role_key="witch",
        owner_scope="player",
        activation_group="witch",
        window_type="night",
        trigger="witch_heal_declined_or_unavailable",
        order=41,
        dependencies=("werewolf.attack", "witch.heal"),
        decision_contract_id="optional_one_alive.v1",
        target_policy_id="alive_non_self_non_attacked.v1",
        effect_type="poison",
        presentation_policy_id="private_role_turn.v1",
    ),
    "hunter.death_shot": V2AbilityDefinition(
        ability_id="hunter.death_shot",
        ability_version=1,
        action_name="hunter_shoot",
        owner_role_key="hunter",
        owner_scope="player",
        activation_group="hunter_death_reaction",
        window_type="dawn_reaction",
        trigger="owner_died_not_by_poison",
        order=90,
        dependencies=(),
        decision_contract_id="optional_one_alive.v1",
        target_policy_id="alive_non_self.v1",
        effect_type="shoot",
        presentation_policy_id="public_death_reaction.v1",
    ),
}

_ACTION_TO_ABILITY = {
    definition.action_name: definition.ability_id for definition in ABILITY_REGISTRY.values()
}
_NIGHT_ACTIONS = frozenset(
    {"remove", "protect", "investigate", "witch_save", "witch_poison"}
)


def normalize_role_key(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise V2AbilityConfigurationError("role key is missing")
    role_key = _ROLE_KEYS.get(value.strip())
    if role_key is None:
        raise V2AbilityConfigurationError(f"unsupported role {value.strip()}")
    return role_key


def normalize_team_key(value: object, *, role_key: str) -> str:
    if isinstance(value, str) and value.strip():
        team_key = _TEAM_KEYS.get(value.strip())
        if team_key is not None:
            return team_key
    return "werewolves" if role_key == "werewolf" else "villagers"


def compile_ability_runtime_snapshot(
    *,
    game_id: str,
    rule_snapshot: dict[str, Any],
    assignments: Sequence[Any],
) -> dict[str, Any]:
    rule_set = rule_snapshot.get("rule_set")
    if not isinstance(rule_set, dict):
        raise V2AbilityConfigurationError("rule snapshot has no rule set")
    normalized_assignments = [_assignment(item) for item in assignments]
    if not normalized_assignments:
        raise V2AbilityConfigurationError("ability runtime requires role assignments")
    role_counts: dict[str, int] = {}
    for item in normalized_assignments:
        role_counts[item["role_key"]] = role_counts.get(item["role_key"], 0) + 1

    raw_night_actions = rule_set.get("night_actions")
    if raw_night_actions is None:
        night_actions = _derived_night_actions(role_counts)
        action_source = "derived_from_frozen_roles"
    else:
        if not isinstance(raw_night_actions, list) or any(
            not isinstance(item, str) or not item.strip() for item in raw_night_actions
        ):
            raise V2AbilityConfigurationError("night actions are invalid")
        night_actions = tuple(item.strip() for item in raw_night_actions)
        action_source = "frozen_rule_snapshot"
    if len(night_actions) != len(set(night_actions)):
        raise V2AbilityConfigurationError("night actions contain duplicates")
    unknown_actions = set(night_actions) - _NIGHT_ACTIONS
    if unknown_actions:
        raise V2AbilityConfigurationError(
            f"unknown night actions: {', '.join(sorted(unknown_actions))}"
        )
    expected_actions = set(_derived_night_actions(role_counts))
    if set(night_actions) != expected_actions:
        raise V2AbilityConfigurationError("night actions do not match assigned roles")

    instances: list[dict[str, Any]] = []
    for action_name in night_actions:
        definition = ABILITY_REGISTRY[_ACTION_TO_ABILITY[action_name]]
        owners = _owners(definition, normalized_assignments)
        if not owners:
            raise V2AbilityConfigurationError(
                f"ability {definition.ability_id} has no eligible owner"
            )
        for owner_id in owners:
            instances.append(_instance(game_id, definition, owner_id))

    if role_counts.get("hunter"):
        definition = ABILITY_REGISTRY["hunter.death_shot"]
        for owner_id in _owners(definition, normalized_assignments):
            instances.append(_instance(game_id, definition, owner_id))

    instances.sort(key=lambda item: (item["order"], item["ability_instance_id"]))
    canonical = {
        "schema_version": 1,
        "registry_version": 1,
        "action_source": action_source,
        "execution_enabled": 6 <= len(normalized_assignments) <= 12,
        "rule_id": _required_text(rule_set.get("id"), "rule id"),
        "rule_version": _required_text(rule_set.get("version"), "rule version"),
        "win_condition": str(rule_set.get("win_condition") or "wolves_gte_others"),
        "sheriff_enabled": bool(rule_set.get("sheriff_enabled")),
        "day_actions": list(
            rule_set.get("day_actions") or _derived_day_actions(rule_set, role_counts)
        ),
        "day_policies": {
            "sheriff_vote_weight": float(rule_set.get("sheriff_vote_weight") or 1),
            "speech_policy": str(rule_set.get("speech_policy") or "sequential"),
            "speech_rounds": int(rule_set.get("speech_rounds") or 1),
            "werewolf_self_explosion_enabled": bool(
                rule_set.get("werewolf_self_explosion_enabled")
            ),
            "exile_last_words_enabled": bool(rule_set.get("exile_last_words_enabled")),
            "sheriff_badge_bomb_policy": str(
                rule_set.get("sheriff_badge_bomb_policy") or "none"
            ),
        },
        "policies": {
            "werewolf_consensus": {
                "rounds": 2,
                "agreement": "unanimous",
                "unresolved": "no_attack",
            },
            "guard": {
                "first_night_self_protect": True,
                "consecutive_same_target": False,
            },
            "witch": {
                "first_night_self_heal": True,
                "heal_poison_mutually_exclusive": True,
                "poison_excludes_self": True,
                "poison_excludes_attacked_target": True,
            },
            "hunter": {"poison_disables_shot": True},
        },
        "next_windows": {
            "normal": (
                "sheriff_election_ready"
                if bool(rule_set.get("sheriff_enabled"))
                else "public_day_ready"
            ),
            "terminal": "game_completed",
        },
        "assignments": normalized_assignments,
        "instances": instances,
    }
    digest = hashlib.sha256(_canonical(canonical)).hexdigest()
    return {**canonical, "snapshot_hash": digest}


def ability_snapshot_hash(snapshot: dict[str, Any]) -> str:
    digest = snapshot.get("snapshot_hash")
    if not isinstance(digest, str) or len(digest) != 64:
        raise V2AbilityConfigurationError("ability snapshot hash is missing")
    canonical = {key: value for key, value in snapshot.items() if key != "snapshot_hash"}
    if hashlib.sha256(_canonical(canonical)).hexdigest() != digest:
        raise V2AbilityConfigurationError("ability snapshot hash mismatch")
    return digest


def resolve_first_night(
    *,
    attack_target: str | None,
    protected_target: str | None,
    healed_target: str | None,
    poisoned_target: str | None,
) -> V2NightResolution:
    deaths: list[dict[str, str]] = []
    prevented_by: str | None = None
    if attack_target is not None:
        if protected_target == attack_target:
            prevented_by = "protect"
        elif healed_target == attack_target:
            prevented_by = "heal"
        else:
            deaths.append({"player_id": attack_target, "cause": "werewolf_attack"})
    if poisoned_target is not None:
        deaths.append({"player_id": poisoned_target, "cause": "witch_poison"})
    if len({item["player_id"] for item in deaths}) != len(deaths):
        raise V2AbilityConfigurationError("night resolution produced duplicate death")
    return V2NightResolution(
        deaths=tuple(deaths),
        peaceful=not deaths,
        attack_prevented_by=prevented_by,
    )


def _derived_night_actions(role_counts: dict[str, int]) -> tuple[str, ...]:
    actions = ["remove"]
    if role_counts.get("guard"):
        actions.append("protect")
    if role_counts.get("seer"):
        actions.append("investigate")
    if role_counts.get("witch"):
        actions.extend(("witch_save", "witch_poison"))
    return tuple(actions)


def _derived_day_actions(
    rule_set: dict[str, Any],
    role_counts: dict[str, int],
) -> tuple[str, ...]:
    actions: list[str] = []
    if bool(rule_set.get("sheriff_enabled")):
        actions.extend(
            (
                "sheriff_run",
                "sheriff_speech",
                "sheriff_withdraw",
                "sheriff_vote",
                "sheriff_pk_speech",
                "sheriff_runoff_vote",
                "speech_order",
            )
        )
    if bool(rule_set.get("werewolf_self_explosion_enabled")):
        actions.append("werewolf_self_explosion")
    actions.extend(("debate", "vote"))
    if bool(rule_set.get("exile_last_words_enabled", True)):
        actions.append("exile_last_words")
    if role_counts.get("hunter"):
        actions.append("hunter_shoot")
    actions.append("summarize")
    return tuple(actions)


def _assignment(value: Any) -> dict[str, Any]:
    role = getattr(value, "role", None)
    player_id = getattr(value, "player_id", None)
    seat = getattr(value, "seat", None)
    team = getattr(value, "team", None)
    if not isinstance(player_id, str) or not player_id.strip():
        raise V2AbilityConfigurationError("assignment player id is invalid")
    if not isinstance(seat, int) or isinstance(seat, bool) or not 1 <= seat <= 24:
        raise V2AbilityConfigurationError("assignment seat is invalid")
    role_key = normalize_role_key(role)
    return {
        "seat": seat,
        "player_id": player_id.strip(),
        "role_key": role_key,
        "team_key": normalize_team_key(team, role_key=role_key),
    }


def _owners(
    definition: V2AbilityDefinition,
    assignments: list[dict[str, Any]],
) -> tuple[str, ...]:
    matching = [item for item in assignments if item["role_key"] == definition.owner_role_key]
    if definition.owner_scope == "team":
        return ("werewolves",) if matching else ()
    return tuple(item["player_id"] for item in matching)


def _instance(
    game_id: str,
    definition: V2AbilityDefinition,
    owner_id: str,
) -> dict[str, Any]:
    identity = hashlib.sha256(
        f"{game_id}:{definition.ability_id}:{definition.ability_version}:{owner_id}".encode()
    ).hexdigest()[:16]
    return {
        "ability_instance_id": f"v2_ability_{identity}",
        "ability_id": definition.ability_id,
        "ability_version": definition.ability_version,
        "action_name": definition.action_name,
        "owner_role_key": definition.owner_role_key,
        "owner_scope": definition.owner_scope,
        "owner_id": owner_id,
        "activation_group": definition.activation_group,
        "window_type": definition.window_type,
        "trigger": definition.trigger,
        "order": definition.order,
        "dependencies": list(definition.dependencies),
        "decision_contract_id": definition.decision_contract_id,
        "target_policy_id": definition.target_policy_id,
        "effect_type": definition.effect_type,
        "presentation_policy_id": definition.presentation_policy_id,
        "blocking": definition.blocking,
        "max_activations_per_window": 48 if definition.owner_scope == "team" else 1,
    }


def _required_text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise V2AbilityConfigurationError(f"{label} is missing")
    return value.strip()


def _canonical(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()


__all__ = [
    "ABILITY_REGISTRY",
    "V2AbilityConfigurationError",
    "V2AbilityDefinition",
    "V2NightResolution",
    "ability_snapshot_hash",
    "compile_ability_runtime_snapshot",
    "normalize_role_key",
    "normalize_team_key",
    "resolve_first_night",
]
