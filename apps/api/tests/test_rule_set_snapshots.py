from __future__ import annotations

import copy
import hashlib
import json
import math
import re
from collections.abc import Callable

import pytest

from app.rule_sets import RuleSetConfig, normalize_rule_set_config
from app.rule_sets.snapshots import (
    canonical_rule_set_config,
    compile_rule_set_config,
    resolve_rule_set_snapshot,
    rule_set_config_from_snapshot,
    rule_set_content_hash,
)
from app.shared.rules import validate_frozen_rule_contract_snapshot


def valid_config(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "name": "经典 8 人局",
        "description": "包含狼人、预言家、守卫与村民的官方标准局。",
        "complexity": "标准",
        "estimated_duration": "中",
        "rule_tags": ["无警长", "顺序发言", "标准"],
        "role_counts": {
            "werewolf": 2,
            "villager": 4,
            "seer": 1,
            "guard": 1,
            "witch": 0,
            "hunter": 0,
            "idiot": 0,
        },
        "win_condition": "wolves_gte_others",
        "sheriff_enabled": False,
        "sheriff_vote_weight": 1,
        "speech_policy": "sequential",
        "werewolf_self_explosion_enabled": False,
        "first_night_last_words_enabled": False,
        "sheriff_badge_bomb_policy": "none",
    }
    value.update(overrides)
    return value


OFFICIAL_CONFIG_GOLDENS: dict[str, dict[str, object]] = {
    "classic_8": {
        "name": "经典 8 人局",
        "description": "包含狼人、预言家、守卫与村民的官方标准局。",
        "complexity": "标准",
        "estimated_duration": "中",
        "rule_tags": ["无警长", "顺序发言", "标准"],
        "role_counts": {
            "werewolf": 2,
            "villager": 4,
            "seer": 1,
            "guard": 1,
            "witch": 0,
            "hunter": 0,
            "idiot": 0,
        },
        "win_condition": "wolves_gte_others",
        "sheriff_enabled": False,
        "sheriff_vote_weight": 1.0,
        "speech_policy": "sequential",
        "werewolf_self_explosion_enabled": False,
        "first_night_last_words_enabled": False,
        "sheriff_badge_bomb_policy": "none",
    },
    "starter_6": {
        "name": "新手 6 人快局",
        "description": "更短的官方入门局,适合快速观察模型策略。",
        "complexity": "入门",
        "estimated_duration": "短",
        "rule_tags": ["无警长", "顺序发言", "新手"],
        "role_counts": {
            "werewolf": 1,
            "villager": 3,
            "seer": 1,
            "guard": 1,
            "witch": 0,
            "hunter": 0,
            "idiot": 0,
        },
        "win_condition": "wolves_gte_others",
        "sheriff_enabled": False,
        "sheriff_vote_weight": 1.0,
        "speech_policy": "sequential",
        "werewolf_self_explosion_enabled": False,
        "first_night_last_words_enabled": False,
        "sheriff_badge_bomb_policy": "none",
    },
    "social_8": {
        "name": "社交 8 人局",
        "description": "仅保留狼人夜晚行动的官方心理博弈局。",
        "complexity": "心理",
        "estimated_duration": "中",
        "rule_tags": ["无警长", "顺序发言", "心理"],
        "role_counts": {
            "werewolf": 2,
            "villager": 6,
            "seer": 0,
            "guard": 0,
            "witch": 0,
            "hunter": 0,
            "idiot": 0,
        },
        "win_condition": "wolves_gte_others",
        "sheriff_enabled": False,
        "sheriff_vote_weight": 1.0,
        "speech_policy": "sequential",
        "werewolf_self_explosion_enabled": False,
        "first_night_last_words_enabled": False,
        "sheriff_badge_bomb_policy": "none",
    },
    "classic_12_seer_witch_hunter_idiot": {
        "name": "12 人预女猎白局",
        "description": "4 狼、预言家、女巫、猎人、白痴与 4 民的标准屠边局。",
        "complexity": "进阶",
        "estimated_duration": "长",
        "rule_tags": ["有警长", "警徽 1.5 票", "屠边", "预女猎白"],
        "role_counts": {
            "werewolf": 4,
            "villager": 4,
            "seer": 1,
            "guard": 0,
            "witch": 1,
            "hunter": 1,
            "idiot": 1,
        },
        "win_condition": "slaughter_side",
        "sheriff_enabled": True,
        "sheriff_vote_weight": 1.5,
        "speech_policy": "sheriff_directed",
        "werewolf_self_explosion_enabled": True,
        "first_night_last_words_enabled": True,
        "sheriff_badge_bomb_policy": "double",
    },
}

OFFICIAL_RUNTIME_GOLDENS: dict[str, dict[str, object]] = {
    "classic_8": {
        "id": "classic_8",
        "version": "2026.04",
        "name": "经典 8 人局",
        "description": "包含狼人、预言家、守卫与村民的官方标准局。",
        "player_count": 8,
        "roles": [
            {
                "role": "狼人",
                "count": 2,
                "team": "werewolves",
                "model_group": "werewolf",
                "category": "werewolf",
            },
            {
                "role": "预言家",
                "count": 1,
                "team": "villagers",
                "model_group": "villager",
                "category": "god",
            },
            {
                "role": "守卫",
                "count": 1,
                "team": "villagers",
                "model_group": "villager",
                "category": "god",
            },
            {
                "role": "村民",
                "count": 4,
                "team": "villagers",
                "model_group": "villager",
                "category": "civilian",
            },
        ],
        "night_actions": ["remove", "protect", "investigate"],
        "day_actions": ["debate", "vote", "summarize"],
        "win_condition": "wolves_gte_others",
        "reveal_policy": "hidden",
        "complexity": "标准",
        "estimated_duration": "中",
        "sheriff_enabled": False,
        "sheriff_vote_weight": 1.0,
        "werewolf_self_explosion_enabled": False,
        "first_night_last_words_enabled": False,
        "sheriff_badge_bomb_policy": "none",
        "speech_policy": "sequential",
        "speech_rounds": 1,
        "rule_tags": ["无警长", "顺序发言", "标准"],
    },
    "starter_6": {
        "id": "starter_6",
        "version": "2026.04",
        "name": "新手 6 人快局",
        "description": "更短的官方入门局,适合快速观察模型策略。",
        "player_count": 6,
        "roles": [
            {
                "role": "狼人",
                "count": 1,
                "team": "werewolves",
                "model_group": "werewolf",
                "category": "werewolf",
            },
            {
                "role": "预言家",
                "count": 1,
                "team": "villagers",
                "model_group": "villager",
                "category": "god",
            },
            {
                "role": "守卫",
                "count": 1,
                "team": "villagers",
                "model_group": "villager",
                "category": "god",
            },
            {
                "role": "村民",
                "count": 3,
                "team": "villagers",
                "model_group": "villager",
                "category": "civilian",
            },
        ],
        "night_actions": ["remove", "protect", "investigate"],
        "day_actions": ["debate", "vote", "summarize"],
        "win_condition": "wolves_gte_others",
        "reveal_policy": "hidden",
        "complexity": "入门",
        "estimated_duration": "短",
        "sheriff_enabled": False,
        "sheriff_vote_weight": 1.0,
        "werewolf_self_explosion_enabled": False,
        "first_night_last_words_enabled": False,
        "sheriff_badge_bomb_policy": "none",
        "speech_policy": "sequential",
        "speech_rounds": 1,
        "rule_tags": ["无警长", "顺序发言", "新手"],
    },
    "social_8": {
        "id": "social_8",
        "version": "2026.04",
        "name": "社交 8 人局",
        "description": "仅保留狼人夜晚行动的官方心理博弈局。",
        "player_count": 8,
        "roles": [
            {
                "role": "狼人",
                "count": 2,
                "team": "werewolves",
                "model_group": "werewolf",
                "category": "werewolf",
            },
            {
                "role": "村民",
                "count": 6,
                "team": "villagers",
                "model_group": "villager",
                "category": "civilian",
            },
        ],
        "night_actions": ["remove"],
        "day_actions": ["debate", "vote", "summarize"],
        "win_condition": "wolves_gte_others",
        "reveal_policy": "hidden",
        "complexity": "心理",
        "estimated_duration": "中",
        "sheriff_enabled": False,
        "sheriff_vote_weight": 1.0,
        "werewolf_self_explosion_enabled": False,
        "first_night_last_words_enabled": False,
        "sheriff_badge_bomb_policy": "none",
        "speech_policy": "sequential",
        "speech_rounds": 1,
        "rule_tags": ["无警长", "顺序发言", "心理"],
    },
    "classic_12_seer_witch_hunter_idiot": {
        "id": "classic_12_seer_witch_hunter_idiot",
        "version": "2026.04",
        "name": "12 人预女猎白局",
        "description": "4 狼、预言家、女巫、猎人、白痴与 4 民的标准屠边局。",
        "player_count": 12,
        "roles": [
            {
                "role": "狼人",
                "count": 4,
                "team": "werewolves",
                "model_group": "werewolf",
                "category": "werewolf",
            },
            {
                "role": "预言家",
                "count": 1,
                "team": "villagers",
                "model_group": "villager",
                "category": "god",
            },
            {
                "role": "女巫",
                "count": 1,
                "team": "villagers",
                "model_group": "villager",
                "category": "god",
            },
            {
                "role": "猎人",
                "count": 1,
                "team": "villagers",
                "model_group": "villager",
                "category": "god",
            },
            {
                "role": "白痴",
                "count": 1,
                "team": "villagers",
                "model_group": "villager",
                "category": "god",
            },
            {
                "role": "村民",
                "count": 4,
                "team": "villagers",
                "model_group": "villager",
                "category": "civilian",
            },
        ],
        "night_actions": ["remove", "investigate", "witch_save", "witch_poison"],
        "day_actions": [
            "sheriff_run",
            "sheriff_speech",
            "sheriff_withdraw",
            "sheriff_vote",
            "sheriff_pk_speech",
            "sheriff_runoff_vote",
            "werewolf_self_explosion",
            "speech_order",
            "debate",
            "vote",
            "hunter_shoot",
            "summarize",
        ],
        "win_condition": "slaughter_side",
        "reveal_policy": "hidden",
        "complexity": "进阶",
        "estimated_duration": "长",
        "sheriff_enabled": True,
        "sheriff_vote_weight": 1.5,
        "werewolf_self_explosion_enabled": True,
        "first_night_last_words_enabled": True,
        "sheriff_badge_bomb_policy": "double",
        "speech_policy": "sheriff_directed",
        "speech_rounds": 1,
        "rule_tags": ["有警长", "警徽 1.5 票", "屠边", "预女猎白"],
    },
}

OFFICIAL_CONFIG_HASHES = {
    "classic_8": "104d9818faac73536d50d57ca93eb623ca2dc044a4e334c6b72fcdbb0c2f5cef",
    "starter_6": "d0e67f0238dbb448afa86fd1b5b02ba303861572962b3054d8a3ea0ad913700f",
    "social_8": "25c6780c9e94df7729becf64a01a65e879236ae43c7efb0de03ac87312d1a21b",
    "classic_12_seer_witch_hunter_idiot": (
        "b81db40986fb3be46e377d68dc3870a0137fe78779c5f0997a5eeeb42a5e396a"
    ),
}

STARTER_6_LEGACY_SNAPSHOT_HASH = (
    "18d0abc90bba675b6442dd8eecc7ccb8ca2066ab5c28b85baba98f82d7ad1ea9"
)


def managed_snapshot() -> dict[str, object]:
    compiled = compile_rule_set_config(
        "classic_8",
        normalize_rule_set_config(valid_config()),
        revision_id="revision-1",
        revision_no=1,
    )
    return copy.deepcopy(compiled.snapshot)


def _compile_boundary(config: RuleSetConfig) -> object:
    return compile_rule_set_config(
        "classic_8",
        config,
        revision_id="revision-1",
        revision_no=1,
    )


def _set_boolean_role_count(config: RuleSetConfig) -> None:
    config.role_counts["werewolf"] = True


def _add_unsupported_role(config: RuleSetConfig) -> None:
    config.role_counts.update(cupid=0)


def _remove_supported_role(config: RuleSetConfig) -> None:
    del config.role_counts["guard"]


def _set_boolean_vote_weight(config: RuleSetConfig) -> None:
    object.__setattr__(config, "sheriff_vote_weight", True)


def _set_unrepresentable_vote_weight(config: RuleSetConfig) -> None:
    object.__setattr__(config, "sheriff_vote_weight", 10**1_000)


CONFIG_BOUNDARIES: tuple[Callable[[RuleSetConfig], object], ...] = (
    _compile_boundary,
    canonical_rule_set_config,
    rule_set_content_hash,
)

CONFIG_MUTATIONS: tuple[Callable[[RuleSetConfig], None], ...] = (
    _set_boolean_role_count,
    _add_unsupported_role,
    _remove_supported_role,
    _set_boolean_vote_weight,
    _set_unrepresentable_vote_weight,
)


def _full_snapshot_hash(snapshot: dict[str, object]) -> str:
    encoded = json.dumps(
        snapshot,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@pytest.mark.parametrize("rule_set_id", tuple(OFFICIAL_CONFIG_GOLDENS))
def test_all_official_configs_match_literal_runtime_and_hash_goldens(
    rule_set_id: str,
) -> None:
    raw_config = copy.deepcopy(OFFICIAL_CONFIG_GOLDENS[rule_set_id])
    config = normalize_rule_set_config(raw_config)
    compiled = compile_rule_set_config(
        rule_set_id,
        config,
        revision_id="revision-1",
        revision_no=1,
    )
    expected = copy.deepcopy(OFFICIAL_RUNTIME_GOLDENS[rule_set_id])
    expected["version"] = "1"
    day_actions = expected["day_actions"]
    assert isinstance(day_actions, list)
    day_actions.insert(day_actions.index("vote") + 1, "exile_last_words")
    expected["exile_last_words_enabled"] = True
    expected.update(
        {
            "revision_id": "revision-1",
            "revision_no": 1,
            "schema_version": 1,
            "content_hash": OFFICIAL_CONFIG_HASHES[rule_set_id],
        }
    )

    assert canonical_rule_set_config(config) == raw_config
    frozen_rule_text = compiled.snapshot["rule_text"]
    frozen_contract = compiled.snapshot["rule_contract"]
    actual_runtime = {
        key: value
        for key, value in compiled.snapshot.items()
        if key not in {"rule_text", "rule_contract"}
    }
    assert actual_runtime == expected
    assert isinstance(frozen_rule_text, str) and frozen_rule_text
    assert isinstance(frozen_contract, dict)
    validate_frozen_rule_contract_snapshot(compiled.snapshot, compiled.rule_set)
    assert compiled.content_hash == OFFICIAL_CONFIG_HASHES[rule_set_id]


def test_managed_snapshot_round_trips_without_catalog_access() -> None:
    compiled = compile_rule_set_config(
        "classic_8",
        normalize_rule_set_config(valid_config()),
        revision_id="revision-1",
        revision_no=1,
    )

    restored = resolve_rule_set_snapshot(compiled.snapshot)

    assert restored.rule_set == compiled.rule_set
    assert restored.snapshot == compiled.snapshot
    assert restored.revision_id == "revision-1"
    assert restored.revision_no == 1
    assert restored.schema_version == 1
    assert restored.content_hash == compiled.content_hash


def test_v1_frozen_snapshot_round_trips_after_contract_writer_advances(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    compiled = compile_rule_set_config(
        "classic_8",
        normalize_rule_set_config(valid_config()),
        revision_id="revision-1",
        revision_no=1,
    )
    frozen_v1_snapshot = copy.deepcopy(compiled.snapshot)

    monkeypatch.setattr("app.shared.rules.RULE_CONTRACT_SCHEMA_VERSION", 2)

    restored = resolve_rule_set_snapshot(frozen_v1_snapshot)
    assert restored.snapshot == frozen_v1_snapshot
    assert restored.snapshot["rule_contract"]["schema_version"] == 1


@pytest.mark.parametrize("target", ["contract", "clause"])
def test_snapshot_parser_fails_closed_for_unknown_frozen_schema(target: str) -> None:
    snapshot = managed_snapshot()
    contract = snapshot["rule_contract"]
    assert isinstance(contract, dict)
    if target == "contract":
        contract["schema_version"] = 999
    else:
        clauses = contract["clauses"]
        assert isinstance(clauses, list) and isinstance(clauses[0], dict)
        clauses[0]["schema_version"] = 999

    with pytest.raises(ValueError, match="frozen rule contract is invalid"):
        resolve_rule_set_snapshot(snapshot)


@pytest.mark.parametrize("rule_set_id", tuple(OFFICIAL_RUNTIME_GOLDENS))
def test_legacy_snapshot_round_trips_exactly(rule_set_id: str) -> None:
    snapshot = copy.deepcopy(OFFICIAL_RUNTIME_GOLDENS[rule_set_id])

    restored = resolve_rule_set_snapshot(snapshot)

    assert restored.snapshot == snapshot
    assert restored.rule_set.id == rule_set_id
    assert restored.revision_id is None
    assert restored.revision_no is None
    assert restored.rule_set.version == "2026.04"


def test_current_ascii_comma_starter_legacy_snapshot_resolves_exactly() -> None:
    snapshot = copy.deepcopy(OFFICIAL_RUNTIME_GOLDENS["starter_6"])

    restored = resolve_rule_set_snapshot(snapshot)

    assert _full_snapshot_hash(snapshot) == STARTER_6_LEGACY_SNAPSHOT_HASH
    assert restored.snapshot == snapshot
    assert restored.rule_set.description == "更短的官方入门局,适合快速观察模型策略。"


def test_obsolete_fullwidth_comma_starter_legacy_snapshot_is_rejected() -> None:
    snapshot = copy.deepcopy(OFFICIAL_RUNTIME_GOLDENS["starter_6"])
    snapshot["description"] = "更短的官方入门局，适合快速观察模型策略。"

    with pytest.raises(ValueError, match="snapshot field description does not match"):
        resolve_rule_set_snapshot(snapshot)


def test_snapshot_parser_restores_the_normalized_management_config() -> None:
    expected = normalize_rule_set_config(valid_config())

    assert rule_set_config_from_snapshot(managed_snapshot()) == expected
    assert (
        rule_set_config_from_snapshot(
            copy.deepcopy(OFFICIAL_RUNTIME_GOLDENS["classic_8"])
        )
        == expected
    )


def test_canonical_config_has_only_normalized_management_fields() -> None:
    canonical = canonical_rule_set_config(normalize_rule_set_config(valid_config()))

    assert canonical == {
        "name": "经典 8 人局",
        "description": "包含狼人、预言家、守卫与村民的官方标准局。",
        "complexity": "标准",
        "estimated_duration": "中",
        "rule_tags": ["无警长", "顺序发言", "标准"],
        "role_counts": {
            "werewolf": 2,
            "villager": 4,
            "seer": 1,
            "guard": 1,
            "witch": 0,
            "hunter": 0,
            "idiot": 0,
        },
        "win_condition": "wolves_gte_others",
        "sheriff_enabled": False,
        "sheriff_vote_weight": 1.0,
        "speech_policy": "sequential",
        "werewolf_self_explosion_enabled": False,
        "first_night_last_words_enabled": False,
        "sheriff_badge_bomb_policy": "none",
    }
    assert set(canonical).isdisjoint(
        {
            "id",
            "revision_id",
            "revision_no",
            "version",
            "schema_version",
            "content_hash",
            "display_order",
            "is_default",
            "player_count",
            "roles",
            "night_actions",
            "day_actions",
            "reveal_policy",
            "speech_rounds",
        }
    )


def test_werewolf_attack_policy_is_frozen_but_legacy_config_hash_shape_is_preserved() -> None:
    legacy = normalize_rule_set_config(valid_config())
    explicit = normalize_rule_set_config(
        valid_config(
            werewolf_attack_policy={
                "resolution": "plurality_rotating_tiebreak",
                "allow_no_attack": True,
                "allow_wolf_target": True,
            }
        )
    )

    assert legacy.werewolf_attack_resolution is None
    assert "werewolf_attack_policy" not in canonical_rule_set_config(legacy)
    legacy_compiled = compile_rule_set_config(
        "legacy_rule",
        legacy,
        revision_id="legacy-revision",
        revision_no=1,
    )
    assert "werewolf_attack_policy" not in legacy_compiled.snapshot
    assert legacy_compiled.rule_set.werewolf_attack_resolution == "unanimous_no_attack"

    assert canonical_rule_set_config(explicit)["werewolf_attack_policy"] == {
        "resolution": "plurality_rotating_tiebreak",
        "allow_no_attack": True,
        "allow_wolf_target": True,
    }
    explicit_compiled = compile_rule_set_config(
        "explicit_rule",
        explicit,
        revision_id="explicit-revision",
        revision_no=1,
    )
    assert explicit_compiled.snapshot["werewolf_attack_policy"] == {
        "resolution": "plurality_rotating_tiebreak",
        "allow_no_attack": True,
        "allow_wolf_target": True,
    }
    assert "平票时由本夜轮值狼人归票" in explicit_compiled.snapshot["rule_text"]
    assert "主动选择空刀" in explicit_compiled.snapshot["rule_text"]
    assert "存活狼人选为夜间袭击目标" in explicit_compiled.snapshot["rule_text"]


def test_content_hash_excludes_stable_id_and_revision_metadata() -> None:
    config = normalize_rule_set_config(valid_config())
    first = compile_rule_set_config(
        "classic_8", config, revision_id="revision-1", revision_no=1
    )
    second = compile_rule_set_config(
        "renamed-stable-id", config, revision_id="revision-99", revision_no=99
    )

    assert first.content_hash == second.content_hash == rule_set_content_hash(config)


@pytest.mark.parametrize(
    "boundary", CONFIG_BOUNDARIES, ids=("compile", "canonical", "hash")
)
@pytest.mark.parametrize(
    "mutate",
    CONFIG_MUTATIONS,
    ids=(
        "boolean_role_count",
        "extra_role",
        "missing_role",
        "boolean_vote_weight",
        "unrepresentable_vote_weight",
    ),
)
def test_config_boundaries_reject_mutated_normalized_configs_with_value_error(
    boundary: Callable[[RuleSetConfig], object],
    mutate: Callable[[RuleSetConfig], None],
) -> None:
    config = normalize_rule_set_config(valid_config())
    mutate(config)

    with pytest.raises(ValueError):
        boundary(config)


def test_compiler_detaches_output_from_caller_owned_role_counts() -> None:
    config = normalize_rule_set_config(valid_config())
    compiled = compile_rule_set_config(
        "classic_8",
        config,
        revision_id="revision-1",
        revision_no=1,
    )
    expected_snapshot = copy.deepcopy(compiled.snapshot)

    config.role_counts["werewolf"] = 0
    config.role_counts["villager"] = 8

    assert compiled.snapshot == expected_snapshot
    assert [role.count for role in compiled.rule_set.roles] == [2, 1, 1, 4]


def test_compiler_rejects_a_configuration_that_fails_validation() -> None:
    invalid = normalize_rule_set_config(
        valid_config(
            role_counts={
                "werewolf": 0,
                "villager": 6,
                "seer": 0,
                "guard": 0,
                "witch": 0,
                "hunter": 0,
                "idiot": 0,
            }
        )
    )

    with pytest.raises(ValueError, match="werewolf_required"):
        compile_rule_set_config(
            "invalid", invalid, revision_id="revision-1", revision_no=1
        )


@pytest.mark.parametrize(
    "field",
    [
        "id",
        "version",
        "name",
        "description",
        "player_count",
        "roles",
        "night_actions",
        "day_actions",
        "win_condition",
        "reveal_policy",
        "complexity",
        "estimated_duration",
        "sheriff_enabled",
        "sheriff_vote_weight",
        "werewolf_self_explosion_enabled",
        "first_night_last_words_enabled",
        "sheriff_badge_bomb_policy",
        "speech_policy",
        "speech_rounds",
        "rule_tags",
    ],
)
def test_snapshot_parser_rejects_every_missing_runtime_field(field: str) -> None:
    snapshot = managed_snapshot()
    del snapshot[field]

    with pytest.raises(ValueError, match="fields"):
        resolve_rule_set_snapshot(snapshot)


def test_snapshot_parser_rejects_unknown_fields() -> None:
    snapshot = managed_snapshot()
    snapshot["display_order"] = 10

    with pytest.raises(ValueError, match="Unsupported snapshot fields: display_order"):
        resolve_rule_set_snapshot(snapshot)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("player_count", True),
        ("speech_rounds", True),
        ("sheriff_vote_weight", True),
        ("revision_no", True),
        ("schema_version", True),
    ],
)
def test_snapshot_parser_rejects_booleans_as_numbers(field: str, value: object) -> None:
    snapshot = managed_snapshot()
    snapshot[field] = value

    with pytest.raises(ValueError):
        resolve_rule_set_snapshot(snapshot)


def test_snapshot_parser_rejects_boolean_role_counts() -> None:
    snapshot = managed_snapshot()
    roles = snapshot["roles"]
    assert isinstance(roles, list)
    roles[0]["count"] = True

    with pytest.raises(ValueError, match="count"):
        resolve_rule_set_snapshot(snapshot)


@pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf])
def test_snapshot_parser_rejects_non_finite_vote_weights(value: float) -> None:
    snapshot = managed_snapshot()
    snapshot["sheriff_vote_weight"] = value

    with pytest.raises(ValueError, match="finite"):
        resolve_rule_set_snapshot(snapshot)


def test_snapshot_parser_rejects_unrepresentable_integer_vote_weight() -> None:
    snapshot = managed_snapshot()
    snapshot["sheriff_vote_weight"] = 10**1_000

    with pytest.raises(ValueError, match="must be a float"):
        resolve_rule_set_snapshot(snapshot)


@pytest.mark.parametrize("field", ["night_actions", "day_actions"])
def test_snapshot_parser_rejects_derived_action_mismatches(field: str) -> None:
    snapshot = managed_snapshot()
    actions = snapshot[field]
    assert isinstance(actions, list)
    actions.append("unexpected_action")

    with pytest.raises(ValueError, match=re.escape(f"snapshot field {field} does not match")):
        resolve_rule_set_snapshot(snapshot)


@pytest.mark.parametrize(
    ("field", "value"),
    [("reveal_policy", "public"), ("speech_rounds", 2), ("player_count", 7)],
)
def test_snapshot_parser_rejects_other_derived_field_mismatches(
    field: str, value: object
) -> None:
    snapshot = managed_snapshot()
    snapshot[field] = value

    with pytest.raises(ValueError, match=re.escape(f"snapshot field {field} does not match")):
        resolve_rule_set_snapshot(snapshot)


@pytest.mark.parametrize("role_field", ["role", "team", "model_group", "category"])
def test_snapshot_parser_requires_exact_role_metadata(role_field: str) -> None:
    snapshot = managed_snapshot()
    roles = snapshot["roles"]
    assert isinstance(roles, list)
    roles[0][role_field] = "changed"

    with pytest.raises(ValueError, match="role"):
        resolve_rule_set_snapshot(snapshot)


@pytest.mark.parametrize(
    ("role_field", "value"),
    [
        ("role", []),
        ("team", {}),
        ("model_group", ["villager"]),
        ("category", {"name": "god"}),
    ],
)
def test_snapshot_parser_rejects_non_string_role_metadata_with_value_error(
    role_field: str, value: object
) -> None:
    snapshot = managed_snapshot()
    roles = snapshot["roles"]
    assert isinstance(roles, list)
    roles[0][role_field] = value

    with pytest.raises(ValueError, match="role metadata must be text"):
        resolve_rule_set_snapshot(snapshot)


def test_snapshot_parser_rejects_role_order_mismatches() -> None:
    snapshot = managed_snapshot()
    roles = snapshot["roles"]
    assert isinstance(roles, list)
    roles[0], roles[1] = roles[1], roles[0]

    with pytest.raises(ValueError, match="snapshot field roles does not match"):
        resolve_rule_set_snapshot(snapshot)


def test_managed_snapshot_rejects_a_hash_mismatch() -> None:
    snapshot = managed_snapshot()
    snapshot["content_hash"] = "0" * 64

    with pytest.raises(ValueError, match="content_hash does not match"):
        resolve_rule_set_snapshot(snapshot)


@pytest.mark.parametrize(
    "missing_field", ["revision_id", "revision_no", "schema_version", "content_hash"]
)
def test_managed_snapshot_rejects_partial_metadata(missing_field: str) -> None:
    snapshot = managed_snapshot()
    del snapshot[missing_field]

    with pytest.raises(ValueError, match="revision metadata must be all present or all absent"):
        resolve_rule_set_snapshot(snapshot)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("revision_id", "", "revision_id"),
        ("revision_id", True, "revision_id"),
        ("revision_no", 0, "revision_no"),
        ("revision_no", 1.0, "revision_no"),
        ("schema_version", 2, "schema_version"),
        ("content_hash", "A" * 64, "content_hash"),
        ("version", "2", "version must equal revision_no"),
    ],
)
def test_managed_snapshot_rejects_invalid_or_mismatched_metadata(
    field: str, value: object, message: str
) -> None:
    snapshot = managed_snapshot()
    snapshot[field] = value

    with pytest.raises(ValueError, match=message):
        resolve_rule_set_snapshot(snapshot)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("revision_id", "revision-1"),
        ("revision_no", 1),
        ("schema_version", 1),
        ("content_hash", "0" * 64),
    ],
)
def test_legacy_snapshot_rejects_mixed_revision_metadata(field: str, value: object) -> None:
    snapshot = copy.deepcopy(OFFICIAL_RUNTIME_GOLDENS["starter_6"])
    snapshot[field] = value

    with pytest.raises(ValueError, match="revision metadata must be all present or all absent"):
        resolve_rule_set_snapshot(snapshot)


def test_legacy_snapshot_requires_the_current_compatibility_version() -> None:
    snapshot = copy.deepcopy(OFFICIAL_RUNTIME_GOLDENS["starter_6"])
    snapshot["version"] = "old-version"

    with pytest.raises(ValueError, match="legacy snapshot version"):
        resolve_rule_set_snapshot(snapshot)
