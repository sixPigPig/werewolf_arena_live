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
        "classic_12_seer_witch_hunter_idiot",
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
    assert [role.role for role in rule.roles] == ["狼人", "预言家", "守卫", "村民"]


def test_get_rule_set_rejects_unknown_id() -> None:
    with pytest.raises(KeyError, match="unknown_rule"):
        get_rule_set("unknown_rule")


def test_rule_set_snapshot_is_json_safe() -> None:
    snapshot = rule_set_snapshot(get_rule_set("starter_6"))

    assert snapshot == {
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
        "sheriff_badge_bomb_policy": "none",
        "speech_policy": "sequential",
        "speech_rounds": 1,
        "rule_tags": ["无警长", "顺序发言", "新手"],
    }


def test_12_player_rule_set_has_sheriff_flow_metadata() -> None:
    rule = get_rule_set("classic_12_seer_witch_hunter_idiot")
    snapshot = rule_set_snapshot(rule)

    assert rule.sheriff_enabled is True
    assert rule.sheriff_vote_weight == 1.5
    assert rule.speech_policy == "sheriff_directed"
    assert rule.speech_rounds == 1
    assert rule.rule_tags == ("有警长", "警徽 1.5 票", "屠边", "预女猎白")
    assert rule.day_actions == (
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
    )
    assert rule.werewolf_self_explosion_enabled is True
    assert rule.sheriff_badge_bomb_policy == "double"
    assert "werewolf_self_explosion" in rule.day_actions
    assert snapshot["sheriff_enabled"] is True
    assert snapshot["sheriff_vote_weight"] == 1.5
    assert snapshot["werewolf_self_explosion_enabled"] is True
    assert snapshot["sheriff_badge_bomb_policy"] == "double"
    assert snapshot["speech_policy"] == "sheriff_directed"
    assert snapshot["speech_rounds"] == 1
    assert snapshot["rule_tags"] == ["有警长", "警徽 1.5 票", "屠边", "预女猎白"]
    assert "bid" not in snapshot["day_actions"]


def test_rule_summaries_are_frontend_friendly() -> None:
    summaries = list_rule_set_summaries()

    assert summaries[0]["id"] == "classic_8"
    assert summaries[0]["role_summary"] == "2 狼人 / 1 预言家 / 1 守卫 / 4 村民"
    assert summaries[0]["werewolf_self_explosion_enabled"] is False
    assert summaries[0]["sheriff_badge_bomb_policy"] == "none"
    assert summaries[0]["rule_tags"] == ["无警长", "顺序发言", "标准"]
    assert summaries[1]["player_count"] == 6
    assert summaries[1]["rule_tags"] == ["无警长", "顺序发言", "新手"]
    assert summaries[2]["night_actions"] == ["remove"]
    assert summaries[2]["rule_tags"] == ["无警长", "顺序发言", "心理"]
    assert summaries[3]["id"] == "classic_12_seer_witch_hunter_idiot"
    assert summaries[3]["role_summary"] == "4 狼人 / 1 预言家 / 1 女巫 / 1 猎人 / 1 白痴 / 4 村民"
    assert summaries[3]["sheriff_enabled"] is True
    assert summaries[3]["sheriff_vote_weight"] == 1.5
    assert summaries[3]["werewolf_self_explosion_enabled"] is True
    assert summaries[3]["sheriff_badge_bomb_policy"] == "double"
    assert summaries[3]["speech_policy"] == "sheriff_directed"
    assert summaries[3]["rule_tags"] == ["有警长", "警徽 1.5 票", "屠边", "预女猎白"]


def test_official_rule_registry_contains_12_player_seer_witch_hunter_idiot() -> None:
    rule = get_rule_set("classic_12_seer_witch_hunter_idiot")

    assert rule.name == "12 人预女猎白局"
    assert rule.player_count == 12
    assert rule.win_condition == "slaughter_side"
    assert [role.role for role in rule.roles] == ["狼人", "预言家", "女巫", "猎人", "白痴", "村民"]
    assert [role.count for role in rule.roles] == [4, 1, 1, 1, 1, 4]


def test_12_player_rule_text_describes_confirmed_table_rules() -> None:
    text = render_rule_text(get_rule_set("classic_12_seer_witch_hunter_idiot"))

    assert "共 12 名玩家：4 名狼人、1 名预言家、1 名女巫、1 名猎人、1 名白痴、4 名村民。" in text
    assert "女巫拥有一瓶解药和一瓶毒药" in text
    assert "猎人死亡时可以开枪" in text
    assert "白痴首次被放逐时翻牌免死" in text
    assert "神职全灭或平民全灭时狼人获胜" in text
    assert "首日先上警、警上发言、退水，再由警下玩家投票选出警长" in text
    assert "平票时进入 PK 发言和二轮警下投票" in text
    assert "警长在正式白天发言前决定警左或警右" in text
    assert "所有玩家完成完整发言" in text
    assert "警长投票计为 1.5 票" in text
    assert "警徽可移交或撕毁" in text
    assert "狼人白天公开阶段可以自爆" in text
    assert "采用双爆吞警徽" in text


def test_small_rule_sets_do_not_enable_werewolf_self_explosion() -> None:
    for rule_id in ("classic_8", "starter_6", "social_8"):
        rule = get_rule_set(rule_id)

        assert rule.werewolf_self_explosion_enabled is False
        assert rule.sheriff_badge_bomb_policy == "none"
        assert "werewolf_self_explosion" not in rule.day_actions


def test_render_rule_text_matches_rule_actions() -> None:
    classic_text = render_rule_text(get_rule_set("classic_8"))
    social_text = render_rule_text(get_rule_set("social_8"))

    assert "共 8 名玩家：2 名狼人、1 名预言家、1 名守卫、4 名村民。" in classic_text
    assert "守卫保护一名玩家" in classic_text
    assert "预言家查验一名玩家阵营" in classic_text
    assert "共 8 名玩家：2 名狼人、6 名村民。" in social_text
    assert "守卫保护" not in social_text
    assert "预言家查验" not in social_text
    assert "按座次顺序进行一轮完整发言" in classic_text
    assert "随后投票放逐并进行总结" in classic_text


def test_render_rule_text_describes_engine_win_conditions() -> None:
    text = render_rule_text(get_rule_set("classic_8"))

    assert "好人阵营需要放逐/淘汰全部狼人获胜" in text
    assert "狼人数量大于或等于其他存活玩家数量时狼人获胜" in text
    assert "否则好人阵营胜利" not in text


def test_validate_rule_sets_rejects_duplicate_ids() -> None:
    duplicate = (get_rule_set("classic_8"), get_rule_set("classic_8"))

    with pytest.raises(RuleConfigurationError, match="Duplicate rule_set id"):
        validate_rule_sets(duplicate)
