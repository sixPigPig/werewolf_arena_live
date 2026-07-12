import math
import re

import pytest

from app.rule_sets import normalize_rule_set_config, validate_rule_set_config


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


def test_normalization_derives_player_count_and_deduplicates_tags() -> None:
    config = normalize_rule_set_config(
        valid_config(name="  经典８人局  ", rule_tags=[" 标准 ", "标准", "新手"])
    )

    assert config.name == "经典8人局"
    assert config.rule_tags == ("标准", "新手")
    assert config.player_count == 8


@pytest.mark.parametrize(
    ("changes", "code", "path"),
    [
        (
            {
                "role_counts": {
                    "werewolf": 0,
                    "villager": 6,
                    "seer": 0,
                    "guard": 0,
                    "witch": 0,
                    "hunter": 0,
                    "idiot": 0,
                }
            },
            "werewolf_required",
            "role_counts.werewolf",
        ),
        (
            {"sheriff_enabled": False, "sheriff_vote_weight": 1.5},
            "sheriff_disabled_vote_weight",
            "sheriff_vote_weight",
        ),
        (
            {
                "werewolf_self_explosion_enabled": False,
                "sheriff_badge_bomb_policy": "double",
            },
            "badge_policy_requires_self_explosion",
            "sheriff_badge_bomb_policy",
        ),
    ],
)
def test_validation_returns_stable_codes_and_paths(
    changes: dict[str, object], code: str, path: str
) -> None:
    result = validate_rule_set_config(normalize_rule_set_config(valid_config(**changes)))

    assert result.valid is False
    assert [(item.code, item.path) for item in result.errors] == [(code, path)]


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"unsupported": True}, "Unsupported rule fields: unsupported"),
        ({"name": None}, "name must be text"),
        ({"name": ""}, "name must contain between 1 and 120 characters"),
        ({"description": "x" * 1001}, "description must contain between 0 and 1000 characters"),
        ({"complexity": "x" * 41}, "complexity must contain between 1 and 40 characters"),
        (
            {"estimated_duration": "x" * 41},
            "estimated_duration must contain between 1 and 40 characters",
        ),
        ({"name": "classic\u200b8"}, "name must not contain control characters"),
        ({"rule_tags": "标准"}, "rule_tags must be a list or tuple"),
        ({"rule_tags": ["x"] * 9}, "rule_tags must contain at most 8 items"),
        ({"rule_tags": ["x" * 21]}, "rule_tags[0] must contain between 1 and 20 characters"),
        ({"rule_tags": ["valid", "\u0000"]}, "rule_tags[1] must not contain control characters"),
        ({"win_condition": "unsupported"}, "win_condition has an unsupported value"),
        ({"sheriff_enabled": 1}, "sheriff_enabled must be a boolean"),
        ({"sheriff_vote_weight": True}, "sheriff_vote_weight must be numeric"),
        ({"sheriff_vote_weight": math.inf}, "sheriff_vote_weight must be finite"),
        ({"speech_policy": "random"}, "speech_policy has an unsupported value"),
        (
            {"werewolf_self_explosion_enabled": 0},
            "werewolf_self_explosion_enabled must be a boolean",
        ),
        (
            {"sheriff_badge_bomb_policy": "single"},
            "sheriff_badge_bomb_policy has an unsupported value",
        ),
    ],
)
def test_normalization_rejects_invalid_scalar_fields(
    changes: dict[str, object], message: str
) -> None:
    with pytest.raises(ValueError, match=re.escape(message)):
        normalize_rule_set_config(valid_config(**changes))


@pytest.mark.parametrize(
    ("role_counts", "message"),
    [
        (None, "role_counts must contain exactly the supported role ids"),
        ({}, "role_counts must contain exactly the supported role ids"),
        (
            {
                "werewolf": 2,
                "villager": 4,
                "seer": 1,
                "guard": 1,
                "witch": 0,
                "hunter": 0,
                "idiot": 0,
                "cupid": 0,
            },
            "role_counts must contain exactly the supported role ids",
        ),
        (
            {
                "werewolf": True,
                "villager": 4,
                "seer": 1,
                "guard": 1,
                "witch": 0,
                "hunter": 0,
                "idiot": 0,
            },
            "role_counts.werewolf must be a non-negative integer",
        ),
        (
            {
                "werewolf": -1,
                "villager": 4,
                "seer": 1,
                "guard": 1,
                "witch": 0,
                "hunter": 0,
                "idiot": 0,
            },
            "role_counts.werewolf must be a non-negative integer",
        ),
    ],
)
def test_normalization_requires_exact_non_negative_role_counts(
    role_counts: object, message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        normalize_rule_set_config(valid_config(role_counts=role_counts))


def test_normalization_applies_nfkc_and_trim_to_all_text_fields() -> None:
    config = normalize_rule_set_config(
        valid_config(
            name=" Ｇａｍｅ ",
            description=" 介绍 ",
            complexity=" 标准 ",
            estimated_duration=" 中 ",
            rule_tags=[" Ａ ", "A", " B "],
        )
    )

    assert config.name == "Game"
    assert config.description == "介绍"
    assert config.complexity == "标准"
    assert config.estimated_duration == "中"
    assert config.rule_tags == ("A", "B")


def test_valid_configuration_has_no_issues() -> None:
    result = validate_rule_set_config(normalize_rule_set_config(valid_config()))

    assert result.valid is True
    assert result.errors == ()
    assert result.warnings == ()


def test_validation_issues_are_returned_in_deterministic_rule_order() -> None:
    result = validate_rule_set_config(
        normalize_rule_set_config(
            valid_config(
                role_counts={
                    "werewolf": 5,
                    "villager": 0,
                    "seer": 2,
                    "guard": 0,
                    "witch": 0,
                    "hunter": 0,
                    "idiot": 0,
                },
                win_condition="slaughter_side",
                sheriff_enabled=False,
                sheriff_vote_weight=1.25,
                speech_policy="sheriff_directed",
            )
        )
    )

    assert [item.code for item in result.errors] == [
        "wolves_must_be_fewer_than_good_players",
        "special_role_count_exceeded",
        "slaughter_side_requires_villager",
        "unsupported_sheriff_vote_weight",
        "sheriff_disabled_vote_weight",
        "sheriff_disabled_speech_policy",
        "sheriff_directed_requires_sheriff",
    ]


@pytest.mark.parametrize(
    ("changes", "expected"),
    [
        (
            {
                "role_counts": {
                    "werewolf": 1,
                    "villager": 4,
                    "seer": 0,
                    "guard": 0,
                    "witch": 0,
                    "hunter": 0,
                    "idiot": 0,
                }
            },
            [("player_count_out_of_range", "role_counts")],
        ),
        (
            {
                "role_counts": {
                    "werewolf": 6,
                    "villager": 0,
                    "seer": 0,
                    "guard": 0,
                    "witch": 0,
                    "hunter": 0,
                    "idiot": 0,
                }
            },
            [
                ("good_player_required", "role_counts"),
                ("wolves_must_be_fewer_than_good_players", "role_counts.werewolf"),
            ],
        ),
        (
            {
                "role_counts": {
                    "werewolf": 2,
                    "villager": 3,
                    "seer": 2,
                    "guard": 0,
                    "witch": 0,
                    "hunter": 0,
                    "idiot": 0,
                }
            },
            [("special_role_count_exceeded", "role_counts.seer")],
        ),
        (
            {
                "win_condition": "slaughter_side",
                "role_counts": {
                    "werewolf": 2,
                    "villager": 6,
                    "seer": 0,
                    "guard": 0,
                    "witch": 0,
                    "hunter": 0,
                    "idiot": 0,
                },
            },
            [("slaughter_side_requires_god", "role_counts")],
        ),
        (
            {
                "win_condition": "slaughter_side",
                "role_counts": {
                    "werewolf": 2,
                    "villager": 0,
                    "seer": 1,
                    "guard": 1,
                    "witch": 1,
                    "hunter": 1,
                    "idiot": 0,
                },
            },
            [("slaughter_side_requires_villager", "role_counts.villager")],
        ),
        (
            {"sheriff_vote_weight": 1.25},
            [
                ("unsupported_sheriff_vote_weight", "sheriff_vote_weight"),
                ("sheriff_disabled_vote_weight", "sheriff_vote_weight"),
            ],
        ),
        ({"sheriff_enabled": True, "speech_policy": "sheriff_directed"}, []),
        (
            {
                "sheriff_enabled": True,
                "werewolf_self_explosion_enabled": True,
                "sheriff_badge_bomb_policy": "double",
            },
            [],
        ),
        (
            {
                "sheriff_enabled": False,
                "werewolf_self_explosion_enabled": True,
                "sheriff_badge_bomb_policy": "double",
            },
            [("badge_policy_requires_sheriff", "sheriff_badge_bomb_policy")],
        ),
    ],
)
def test_cross_field_validation_covers_restricted_rule_combinations(
    changes: dict[str, object], expected: list[tuple[str, str]]
) -> None:
    result = validate_rule_set_config(normalize_rule_set_config(valid_config(**changes)))

    assert [(item.code, item.path) for item in result.errors] == expected
