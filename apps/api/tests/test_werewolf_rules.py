from dataclasses import replace

import pytest

from app.shared.rules import (
    CLASSIC_8,
    DEFAULT_RULE_SET_ID,
    ENGINE_CONSTRAINT_TO_CLAUSE_IDS,
    OFFICIAL_RULE_SETS,
    RULE_AUDIENCE_INTERNAL_ONLY,
    RULE_AUDIENCE_PLAYER_PUBLIC,
    RULE_CLAUSES,
    RULE_CONTRACT_SCHEMA_VERSION,
    RuleConfigurationError,
    clause_ids_for_engine_constraint,
    freeze_rule_set_snapshot,
    get_rule_set,
    list_rule_set_summaries,
    prompt_rule_clauses_from_snapshot,
    render_rule_text,
    rule_contract_hash,
    rule_contract_snapshot,
    rule_clauses_for_rule_set,
    rule_set_snapshot,
    rule_text_from_snapshot,
    validate_frozen_rule_contract_snapshot,
    validate_rule_clauses,
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
        "day_actions": ["debate", "vote", "exile_last_words", "summarize"],
        "win_condition": "wolves_gte_others",
        "reveal_policy": "hidden",
        "complexity": "入门",
        "estimated_duration": "短",
        "sheriff_enabled": False,
        "sheriff_vote_weight": 1.0,
        "werewolf_self_explosion_enabled": False,
        "exile_last_words_enabled": True,
        "first_night_last_words_enabled": False,
        "sheriff_badge_bomb_policy": "none",
        "speech_policy": "sequential",
        "speech_rounds": 1,
        "rule_tags": ["无警长", "顺序发言", "新手"],
    }


def test_rule_contract_snapshot_is_stable_prompt_safe_metadata() -> None:
    rule = get_rule_set("classic_12_seer_witch_hunter_idiot")

    snapshot = rule_contract_snapshot(
        rule,
        role="女巫",
        action="witch_save",
    )

    assert snapshot["schema_version"] == RULE_CONTRACT_SCHEMA_VERSION
    assert snapshot["canonical_hash"] == rule_contract_hash(rule)
    assert len(str(snapshot["canonical_hash"])) == 64
    assert "night.werewolf_attack.non_wolf_targets.v1" in snapshot["injected_clause_ids"]
    assert "private.witch.attack_observation.v1" in snapshot["injected_clause_ids"]
    assert "internal.werewolf.collective_fallback.v1" not in snapshot["injected_clause_ids"]


def test_frozen_runtime_contract_keeps_rule_text_and_private_clause_after_registry_change(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rule = get_rule_set("classic_12_seer_witch_hunter_idiot")
    snapshot = freeze_rule_set_snapshot(rule)
    frozen_rule_text = str(snapshot["rule_text"])
    frozen_private_text = next(
        clause.neutral_text_zh
        for clause in prompt_rule_clauses_from_snapshot(
            snapshot,
            role="女巫",
            action="witch_save",
        )
        if clause.clause_id == "private.witch.attack_observation.v1"
    )
    changed_registry = tuple(
        replace(clause, neutral_text_zh=f"新版：{clause.neutral_text_zh}")
        for clause in RULE_CLAUSES
    )
    monkeypatch.setattr("app.shared.rules.RULE_CLAUSES", changed_registry)

    assert rule_text_from_snapshot(snapshot, fallback_rule_set=rule) == frozen_rule_text
    restored_private_text = next(
        clause.neutral_text_zh
        for clause in prompt_rule_clauses_from_snapshot(
            snapshot,
            role="女巫",
            action="witch_save",
        )
        if clause.clause_id == "private.witch.attack_observation.v1"
    )
    assert restored_private_text == frozen_private_text
    assert not restored_private_text.startswith("新版：")


def test_frozen_v1_contract_remains_readable_after_writer_version_advances(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rule = get_rule_set("classic_12_seer_witch_hunter_idiot")
    snapshot = freeze_rule_set_snapshot(rule)

    monkeypatch.setattr("app.shared.rules.RULE_CONTRACT_SCHEMA_VERSION", 2)

    validate_frozen_rule_contract_snapshot(snapshot, rule)
    clauses = prompt_rule_clauses_from_snapshot(
        snapshot,
        role="女巫",
        action="witch_save",
    )
    assert clauses
    assert {clause.schema_version for clause in clauses} == {1}


@pytest.mark.parametrize("target", ["contract", "clause"])
def test_frozen_contract_rejects_unknown_reader_schema(target: str) -> None:
    rule = get_rule_set("classic_12_seer_witch_hunter_idiot")
    snapshot = freeze_rule_set_snapshot(rule)
    contract = snapshot["rule_contract"]
    assert isinstance(contract, dict)
    if target == "contract":
        contract["schema_version"] = 999
    else:
        clauses = contract["clauses"]
        assert isinstance(clauses, list) and isinstance(clauses[0], dict)
        clauses[0]["schema_version"] = 999

    with pytest.raises(RuleConfigurationError, match="schema"):
        validate_frozen_rule_contract_snapshot(snapshot, rule)


def test_rule_clause_registry_has_stable_audience_and_constraint_mapping() -> None:
    validate_rule_clauses(RULE_CLAUSES)

    clause_ids = [clause.clause_id for clause in RULE_CLAUSES]
    assert len(clause_ids) == len(set(clause_ids))
    assert clause_ids_for_engine_constraint(
        "engine.night.werewolf_attack.candidates_non_wolves"
    ) == ("night.werewolf_attack.non_wolf_targets.v1",)
    assert ENGINE_CONSTRAINT_TO_CLAUSE_IDS[
        "engine.night.werewolf.collective_fallback"
    ] == ("internal.werewolf.collective_fallback.v1",)

    public_clauses = rule_clauses_for_rule_set(
        get_rule_set("classic_12_seer_witch_hunter_idiot"),
        audiences=frozenset({RULE_AUDIENCE_PLAYER_PUBLIC}),
    )
    assert all(clause.audience == RULE_AUDIENCE_PLAYER_PUBLIC for clause in public_clauses)
    assert all(clause.audience != RULE_AUDIENCE_INTERNAL_ONLY for clause in public_clauses)


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
        "exile_last_words",
        "hunter_shoot",
        "summarize",
    )
    assert rule.werewolf_self_explosion_enabled is True
    assert rule.exile_last_words_enabled is True
    assert rule.sheriff_badge_bomb_policy == "double"
    assert "werewolf_self_explosion" in rule.day_actions
    assert snapshot["sheriff_enabled"] is True
    assert snapshot["sheriff_vote_weight"] == 1.5
    assert snapshot["werewolf_self_explosion_enabled"] is True
    assert snapshot["exile_last_words_enabled"] is True
    assert snapshot["first_night_last_words_enabled"] is True
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
    assert summaries[0]["first_night_last_words_enabled"] is False
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
    assert summaries[3]["first_night_last_words_enabled"] is True
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
    assert "狼人夜间只能袭击非狼人玩家，不能选择自己或狼人队友" in text
    assert "天亮只公布夜间出局名单" in text
    assert "不公布每名玩家来自狼人袭击、女巫毒药或其他夜间效果" in text
    assert "唯一最高票玩家直接被放逐，不要求过半" in text
    assert "PK 候选不参加二轮投票" in text
    assert "若放逐后立即满足胜利条件，则不再发表放逐遗言" in text
    assert "已经触发的死亡技能仍按终局结算顺序处理" in text
    assert "上警玩家退水后不会因此获得警长票权" in text
    assert "毒药不能选择女巫自己或当夜狼人袭击目标" in text


@pytest.mark.parametrize("weight", [1.0, 1.5, 2.0])
def test_rule_text_uses_configured_sheriff_vote_weight(weight: float) -> None:
    rule = replace(
        get_rule_set("classic_12_seer_witch_hunter_idiot"),
        sheriff_vote_weight=weight,
    )

    text = render_rule_text(rule)

    assert f"警长投票计为 {weight:g} 票" in text


def test_rule_text_describes_non_accumulating_pre_sheriff_explosions() -> None:
    rule = replace(
        get_rule_set("classic_12_seer_witch_hunter_idiot"),
        sheriff_badge_bomb_policy="none",
    )

    text = render_rule_text(rule)

    assert "警长产生前自爆会中断当次竞选" in text
    assert "不会累计导致警徽流失" in text
    assert "双爆吞警徽" not in text


def test_rule_text_describes_self_explosion_without_sheriff_or_badge() -> None:
    rule = replace(
        get_rule_set("classic_12_seer_witch_hunter_idiot"),
        sheriff_enabled=False,
        sheriff_vote_weight=1.0,
        sheriff_badge_bomb_policy="none",
    )

    text = render_rule_text(rule)

    assert "狼人白天公开阶段可以自爆" in text
    assert "本局不设警长，也没有警徽" in text
    assert "警徽流失" not in text
    assert "双爆吞警徽" not in text


def test_rule_text_omits_self_explosion_policy_when_feature_is_disabled() -> None:
    rule = replace(
        get_rule_set("classic_12_seer_witch_hunter_idiot"),
        werewolf_self_explosion_enabled=False,
        sheriff_badge_bomb_policy="none",
    )

    text = render_rule_text(rule)

    assert "狼人白天公开阶段可以自爆" not in text


def test_rule_text_omits_absent_special_roles_and_description() -> None:
    marker = "RULE_DESCRIPTION_MUST_NOT_REACH_PROMPT"
    rule = replace(get_rule_set("social_8"), description=marker)

    text = render_rule_text(rule)

    assert "女巫拥有" not in text
    assert "猎人死亡" not in text
    assert "白痴首次" not in text
    assert marker not in text


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
