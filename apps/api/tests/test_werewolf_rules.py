import pytest

from app.werewolf.rules import (
    CLASSIC_8,
    DEFAULT_RULE_SET_ID,
    OFFICIAL_RULE_SETS,
    RuleConfigurationError,
    get_rule_set,
    list_rule_set_summaries,
    render_rule_text,
    rule_set_snapshot,
    validate_rule_sets,
)


def test_official_rule_registry_contains_mvp_rules() -> None:
    assert DEFAULT_RULE_SET_ID == "classic_8"
    assert [rule.id for rule in OFFICIAL_RULE_SETS] == [
        "classic_8",
        "starter_6",
        "social_8",
    ]


def test_rule_role_counts_match_player_count() -> None:
    validate_rule_sets(OFFICIAL_RULE_SETS)

    for rule in OFFICIAL_RULE_SETS:
        assert sum(role.count for role in rule.roles) == rule.player_count


def test_get_rule_set_returns_classic_rule() -> None:
    rule = get_rule_set("classic_8")

    assert rule == CLASSIC_8
    assert rule.name == "经典 8 人局"
    assert rule.player_count == 8
    assert [role.role for role in rule.roles] == ["狼人", "预言家", "医生", "村民"]


def test_get_rule_set_rejects_unknown_id() -> None:
    with pytest.raises(KeyError, match="unknown_rule"):
        get_rule_set("unknown_rule")


def test_rule_set_snapshot_is_json_safe() -> None:
    snapshot = rule_set_snapshot(get_rule_set("starter_6"))

    assert snapshot == {
        "id": "starter_6",
        "version": "2026.04",
        "name": "新手 6 人快局",
        "description": "更短的官方入门局，适合快速观察模型策略。",
        "player_count": 6,
        "roles": [
            {"role": "狼人", "count": 1, "team": "werewolves", "model_group": "werewolf"},
            {"role": "预言家", "count": 1, "team": "villagers", "model_group": "villager"},
            {"role": "医生", "count": 1, "team": "villagers", "model_group": "villager"},
            {"role": "村民", "count": 3, "team": "villagers", "model_group": "villager"},
        ],
        "night_actions": ["remove", "protect", "investigate"],
        "day_actions": ["bid", "debate", "vote", "summarize"],
        "win_condition": "wolves_gte_others",
        "reveal_policy": "hidden",
        "complexity": "入门",
        "estimated_duration": "短",
    }


def test_rule_summaries_are_frontend_friendly() -> None:
    summaries = list_rule_set_summaries()

    assert summaries[0]["id"] == "classic_8"
    assert summaries[0]["role_summary"] == "2 狼人 / 1 预言家 / 1 医生 / 4 村民"
    assert summaries[1]["player_count"] == 6
    assert summaries[2]["night_actions"] == ["remove"]


def test_render_rule_text_matches_rule_actions() -> None:
    classic_text = render_rule_text(get_rule_set("classic_8"))
    social_text = render_rule_text(get_rule_set("social_8"))

    assert "共 8 名玩家：2 名狼人、1 名预言家、1 名医生、4 名村民。" in classic_text
    assert "医生保护一名玩家" in classic_text
    assert "预言家查验一名玩家身份" in classic_text
    assert "共 8 名玩家：2 名狼人、6 名村民。" in social_text
    assert "医生保护" not in social_text
    assert "预言家查验" not in social_text


def test_validate_rule_sets_rejects_duplicate_ids() -> None:
    duplicate = (get_rule_set("classic_8"), get_rule_set("classic_8"))

    with pytest.raises(RuleConfigurationError, match="Duplicate rule_set id"):
        validate_rule_sets(duplicate)
