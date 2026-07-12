from __future__ import annotations

import copy
import math
import re

import pytest

from app.rule_sets import normalize_rule_set_config
from app.rule_sets.snapshots import (
    canonical_rule_set_config,
    compile_rule_set_config,
    resolve_rule_set_snapshot,
    rule_set_config_from_snapshot,
    rule_set_content_hash,
)
from app.werewolf.rules import get_rule_set, rule_set_snapshot


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
        "sheriff_badge_bomb_policy": "none",
    }
    value.update(overrides)
    return value


def official_configs() -> list[tuple[str, dict[str, object]]]:
    return [
        ("classic_8", valid_config()),
        (
            "starter_6",
            valid_config(
                name="新手 6 人快局",
                description="更短的官方入门局，适合快速观察模型策略。",
                complexity="入门",
                estimated_duration="短",
                rule_tags=["无警长", "顺序发言", "新手"],
                role_counts={
                    "werewolf": 1,
                    "villager": 3,
                    "seer": 1,
                    "guard": 1,
                    "witch": 0,
                    "hunter": 0,
                    "idiot": 0,
                },
            ),
        ),
        (
            "social_8",
            valid_config(
                name="社交 8 人局",
                description="仅保留狼人夜晚行动的官方心理博弈局。",
                complexity="心理",
                estimated_duration="中",
                rule_tags=["无警长", "顺序发言", "心理"],
                role_counts={
                    "werewolf": 2,
                    "villager": 6,
                    "seer": 0,
                    "guard": 0,
                    "witch": 0,
                    "hunter": 0,
                    "idiot": 0,
                },
            ),
        ),
        (
            "classic_12_seer_witch_hunter_idiot",
            valid_config(
                name="12 人预女猎白局",
                description="4 狼、预言家、女巫、猎人、白痴与 4 民的标准屠边局。",
                complexity="进阶",
                estimated_duration="长",
                rule_tags=["有警长", "警徽 1.5 票", "屠边", "预女猎白"],
                role_counts={
                    "werewolf": 4,
                    "villager": 4,
                    "seer": 1,
                    "guard": 0,
                    "witch": 1,
                    "hunter": 1,
                    "idiot": 1,
                },
                win_condition="slaughter_side",
                sheriff_enabled=True,
                sheriff_vote_weight=1.5,
                speech_policy="sheriff_directed",
                werewolf_self_explosion_enabled=True,
                sheriff_badge_bomb_policy="double",
            ),
        ),
    ]


def managed_snapshot() -> dict[str, object]:
    compiled = compile_rule_set_config(
        "classic_8",
        normalize_rule_set_config(valid_config()),
        revision_id="revision-1",
        revision_no=1,
    )
    return copy.deepcopy(compiled.snapshot)


def test_official_config_compiles_to_current_classic_behavior() -> None:
    compiled = compile_rule_set_config(
        "classic_8",
        normalize_rule_set_config(valid_config()),
        revision_id="e9fa678e-9b18-5079-91d2-f74835364fb6",
        revision_no=1,
    )
    expected = rule_set_snapshot(get_rule_set("classic_8"))
    expected["version"] = "1"
    expected.update(
        {
            "revision_id": compiled.revision_id,
            "revision_no": 1,
            "schema_version": 1,
            "content_hash": compiled.content_hash,
        }
    )
    assert compiled.snapshot == expected
    assert compiled.content_hash == (
        "00095728147a022c48eab88faf21a14567ad0afa13ab9418306e84ff85b10131"
    )


@pytest.mark.parametrize(("rule_set_id", "raw_config"), official_configs())
def test_all_official_configs_compile_to_current_runtime_behavior(
    rule_set_id: str, raw_config: dict[str, object]
) -> None:
    compiled = compile_rule_set_config(
        rule_set_id,
        normalize_rule_set_config(raw_config),
        revision_id="revision-1",
        revision_no=1,
    )
    expected = rule_set_snapshot(get_rule_set(rule_set_id))
    expected["version"] = "1"
    expected.update(
        {
            "revision_id": "revision-1",
            "revision_no": 1,
            "schema_version": 1,
            "content_hash": compiled.content_hash,
        }
    )

    assert compiled.snapshot == expected


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


@pytest.mark.parametrize("rule_set_id", [item[0] for item in official_configs()])
def test_legacy_snapshot_round_trips_exactly(rule_set_id: str) -> None:
    snapshot = rule_set_snapshot(get_rule_set(rule_set_id))

    restored = resolve_rule_set_snapshot(snapshot)

    assert restored.snapshot == snapshot
    assert restored.rule_set == get_rule_set(rule_set_id)
    assert restored.revision_id is None
    assert restored.revision_no is None
    assert restored.rule_set.version == "2026.04"


def test_snapshot_parser_restores_the_normalized_management_config() -> None:
    expected = normalize_rule_set_config(valid_config())

    assert rule_set_config_from_snapshot(managed_snapshot()) == expected
    assert rule_set_config_from_snapshot(rule_set_snapshot(get_rule_set("classic_8"))) == expected


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


def test_content_hash_excludes_stable_id_and_revision_metadata() -> None:
    config = normalize_rule_set_config(valid_config())
    first = compile_rule_set_config(
        "classic_8", config, revision_id="revision-1", revision_no=1
    )
    second = compile_rule_set_config(
        "renamed-stable-id", config, revision_id="revision-99", revision_no=99
    )

    assert first.content_hash == second.content_hash == rule_set_content_hash(config)


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
    snapshot = rule_set_snapshot(get_rule_set("starter_6"))
    snapshot[field] = value

    with pytest.raises(ValueError, match="revision metadata must be all present or all absent"):
        resolve_rule_set_snapshot(snapshot)


def test_legacy_snapshot_requires_the_current_compatibility_version() -> None:
    snapshot = rule_set_snapshot(get_rule_set("starter_6"))
    snapshot["version"] = "old-version"

    with pytest.raises(ValueError, match="legacy snapshot version"):
        resolve_rule_set_snapshot(snapshot)
