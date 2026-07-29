from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Iterable

from app.werewolf.config import GUARD


TEAM_VILLAGERS = "villagers"
TEAM_WEREWOLVES = "werewolves"

MODEL_GROUP_VILLAGER = "villager"
MODEL_GROUP_WEREWOLF = "werewolf"

ACTION_REMOVE = "remove"
ACTION_WEREWOLF_DISCUSS = "werewolf_discuss"
ACTION_WEREWOLF_KILL_VOTE = "werewolf_kill_vote"
ACTION_PROTECT = "protect"
ACTION_INVESTIGATE = "investigate"
ACTION_WITCH_SAVE = "witch_save"
ACTION_WITCH_POISON = "witch_poison"
ACTION_HUNTER_SHOOT = "hunter_shoot"
ACTION_SHERIFF_RUN = "sheriff_run"
ACTION_SHERIFF_SPEECH = "sheriff_speech"
ACTION_SHERIFF_WITHDRAW = "sheriff_withdraw"
ACTION_SHERIFF_VOTE = "sheriff_vote"
ACTION_SHERIFF_PK_SPEECH = "sheriff_pk_speech"
ACTION_SHERIFF_RUNOFF_VOTE = "sheriff_runoff_vote"
ACTION_WEREWOLF_SELF_EXPLOSION = "werewolf_self_explosion"
ACTION_SPEECH_ORDER = "speech_order"
ACTION_SHERIFF_BADGE = "sheriff_badge"
ACTION_DEBATE = "debate"
ACTION_VOTE = "vote"
ACTION_EXILE_PK_SPEECH = "exile_pk_speech"
ACTION_EXILE_RUNOFF_VOTE = "exile_runoff_vote"
ACTION_EXILE_LAST_WORDS = "exile_last_words"
ACTION_SUMMARIZE = "summarize"

SPEECH_POLICY_SEQUENTIAL = "sequential"
SPEECH_POLICY_SHERIFF_DIRECTED = "sheriff_directed"

WIN_CONDITION_WOLVES_GTE_OTHERS = "wolves_gte_others"
WIN_CONDITION_SLAUGHTER_SIDE = "slaughter_side"
REVEAL_POLICY_HIDDEN = "hidden"

ROLE_CATEGORY_WEREWOLF = "werewolf"
ROLE_CATEGORY_GOD = "god"
ROLE_CATEGORY_CIVILIAN = "civilian"

DEFAULT_RULE_SET_ID = "classic_8"
RULE_SET_VERSION = "2026.04"

RULE_CONTRACT_SCHEMA_VERSION = 1
# Persisted contracts are decoded by an explicit reader set rather than by the
# current writer version.  A future writer bump must add its version here only
# after a compatible decoder exists; already-frozen v1 games remain readable in
# the meantime.
READABLE_RULE_CONTRACT_SCHEMA_VERSIONS = frozenset({1})
READABLE_RULE_CLAUSE_SCHEMA_VERSIONS = frozenset({1})
RULE_CONTRACT_REVISION_ID = "2026-07-18.1"
RULE_PROMPT_TEMPLATE_VERSION = "2026-07-18.1"
RULE_FALLBACK_POLICY_VERSION = "2026-07-18.1"

RULE_AUDIENCE_PLAYER_PUBLIC = "player_public"
RULE_AUDIENCE_ROLE_PRIVATE = "role_private"
RULE_AUDIENCE_INTERNAL_ONLY = "internal_only"
RULE_AUDIENCES = frozenset(
    {
        RULE_AUDIENCE_PLAYER_PUBLIC,
        RULE_AUDIENCE_ROLE_PRIVATE,
        RULE_AUDIENCE_INTERNAL_ONLY,
    }
)


class RuleConfigurationError(ValueError):
    pass


@dataclass(frozen=True)
class RoleSpec:
    role: str
    count: int
    team: str
    model_group: str
    category: str = ROLE_CATEGORY_CIVILIAN


@dataclass(frozen=True)
class RuleSet:
    id: str
    version: str
    name: str
    description: str
    player_count: int
    roles: tuple[RoleSpec, ...]
    night_actions: tuple[str, ...]
    day_actions: tuple[str, ...]
    win_condition: str
    reveal_policy: str
    complexity: str
    estimated_duration: str
    sheriff_enabled: bool = False
    sheriff_vote_weight: float = 1.0
    speech_policy: str = SPEECH_POLICY_SEQUENTIAL
    speech_rounds: int = 1
    rule_tags: tuple[str, ...] = ()
    werewolf_self_explosion_enabled: bool = False
    exile_last_words_enabled: bool = False
    first_night_last_words_enabled: bool = False
    sheriff_badge_bomb_policy: str = "none"


@dataclass(frozen=True)
class RuleClause:
    """A stable rule-to-engine contract entry.

    Clause text is code-owned rather than read from a persisted snapshot so an
    untrusted or legacy snapshot cannot inject arbitrary prompt text.  ``roles``
    and ``actions`` describe applicability; ``audience`` controls whether the
    text may enter a player prompt at all.
    """

    clause_id: str
    audience: str
    neutral_text_zh: str
    engine_constraint_ids: tuple[str, ...]
    applies_to_rule_sets: tuple[str, ...] = ("*",)
    roles: tuple[str, ...] = ()
    phases: tuple[str, ...] = ()
    actions: tuple[str, ...] = ()
    required_flags: tuple[str, ...] = ()
    prompt_slots: tuple[str, ...] = ()
    schema_version: int = RULE_CONTRACT_SCHEMA_VERSION


CLASSIC_8 = RuleSet(
    id="classic_8",
    version=RULE_SET_VERSION,
    name="经典 8 人局",
    description="包含狼人、预言家、守卫与村民的官方标准局。",
    player_count=8,
    roles=(
        RoleSpec("狼人", 2, TEAM_WEREWOLVES, MODEL_GROUP_WEREWOLF, ROLE_CATEGORY_WEREWOLF),
        RoleSpec("预言家", 1, TEAM_VILLAGERS, MODEL_GROUP_VILLAGER, ROLE_CATEGORY_GOD),
        RoleSpec(GUARD, 1, TEAM_VILLAGERS, MODEL_GROUP_VILLAGER, ROLE_CATEGORY_GOD),
        RoleSpec("村民", 4, TEAM_VILLAGERS, MODEL_GROUP_VILLAGER, ROLE_CATEGORY_CIVILIAN),
    ),
    night_actions=(ACTION_REMOVE, ACTION_PROTECT, ACTION_INVESTIGATE),
    day_actions=(
        ACTION_DEBATE,
        ACTION_VOTE,
        ACTION_EXILE_LAST_WORDS,
        ACTION_SUMMARIZE,
    ),
    win_condition=WIN_CONDITION_WOLVES_GTE_OTHERS,
    reveal_policy=REVEAL_POLICY_HIDDEN,
    complexity="标准",
    estimated_duration="中",
    rule_tags=("无警长", "顺序发言", "标准"),
    exile_last_words_enabled=True,
)

STARTER_6 = RuleSet(
    id="starter_6",
    version=RULE_SET_VERSION,
    name="新手 6 人快局",
    description="更短的官方入门局,适合快速观察模型策略。",
    player_count=6,
    roles=(
        RoleSpec("狼人", 1, TEAM_WEREWOLVES, MODEL_GROUP_WEREWOLF, ROLE_CATEGORY_WEREWOLF),
        RoleSpec("预言家", 1, TEAM_VILLAGERS, MODEL_GROUP_VILLAGER, ROLE_CATEGORY_GOD),
        RoleSpec(GUARD, 1, TEAM_VILLAGERS, MODEL_GROUP_VILLAGER, ROLE_CATEGORY_GOD),
        RoleSpec("村民", 3, TEAM_VILLAGERS, MODEL_GROUP_VILLAGER, ROLE_CATEGORY_CIVILIAN),
    ),
    night_actions=(ACTION_REMOVE, ACTION_PROTECT, ACTION_INVESTIGATE),
    day_actions=(
        ACTION_DEBATE,
        ACTION_VOTE,
        ACTION_EXILE_LAST_WORDS,
        ACTION_SUMMARIZE,
    ),
    win_condition=WIN_CONDITION_WOLVES_GTE_OTHERS,
    reveal_policy=REVEAL_POLICY_HIDDEN,
    complexity="入门",
    estimated_duration="短",
    rule_tags=("无警长", "顺序发言", "新手"),
    exile_last_words_enabled=True,
)

SOCIAL_8 = RuleSet(
    id="social_8",
    version=RULE_SET_VERSION,
    name="社交 8 人局",
    description="仅保留狼人夜晚行动的官方心理博弈局。",
    player_count=8,
    roles=(
        RoleSpec("狼人", 2, TEAM_WEREWOLVES, MODEL_GROUP_WEREWOLF, ROLE_CATEGORY_WEREWOLF),
        RoleSpec("村民", 6, TEAM_VILLAGERS, MODEL_GROUP_VILLAGER, ROLE_CATEGORY_CIVILIAN),
    ),
    night_actions=(ACTION_REMOVE,),
    day_actions=(
        ACTION_DEBATE,
        ACTION_VOTE,
        ACTION_EXILE_LAST_WORDS,
        ACTION_SUMMARIZE,
    ),
    win_condition=WIN_CONDITION_WOLVES_GTE_OTHERS,
    reveal_policy=REVEAL_POLICY_HIDDEN,
    complexity="心理",
    estimated_duration="中",
    rule_tags=("无警长", "顺序发言", "心理"),
    exile_last_words_enabled=True,
)

CLASSIC_12_SEER_WITCH_HUNTER_IDIOT = RuleSet(
    id="classic_12_seer_witch_hunter_idiot",
    version=RULE_SET_VERSION,
    name="12 人预女猎白局",
    description="4 狼、预言家、女巫、猎人、白痴与 4 民的标准屠边局。",
    player_count=12,
    roles=(
        RoleSpec("狼人", 4, TEAM_WEREWOLVES, MODEL_GROUP_WEREWOLF, ROLE_CATEGORY_WEREWOLF),
        RoleSpec("预言家", 1, TEAM_VILLAGERS, MODEL_GROUP_VILLAGER, ROLE_CATEGORY_GOD),
        RoleSpec("女巫", 1, TEAM_VILLAGERS, MODEL_GROUP_VILLAGER, ROLE_CATEGORY_GOD),
        RoleSpec("猎人", 1, TEAM_VILLAGERS, MODEL_GROUP_VILLAGER, ROLE_CATEGORY_GOD),
        RoleSpec("白痴", 1, TEAM_VILLAGERS, MODEL_GROUP_VILLAGER, ROLE_CATEGORY_GOD),
        RoleSpec("村民", 4, TEAM_VILLAGERS, MODEL_GROUP_VILLAGER, ROLE_CATEGORY_CIVILIAN),
    ),
    night_actions=(ACTION_REMOVE, ACTION_INVESTIGATE, ACTION_WITCH_SAVE, ACTION_WITCH_POISON),
    day_actions=(
        ACTION_SHERIFF_RUN,
        ACTION_SHERIFF_SPEECH,
        ACTION_SHERIFF_WITHDRAW,
        ACTION_SHERIFF_VOTE,
        ACTION_SHERIFF_PK_SPEECH,
        ACTION_SHERIFF_RUNOFF_VOTE,
        ACTION_WEREWOLF_SELF_EXPLOSION,
        ACTION_SPEECH_ORDER,
        ACTION_DEBATE,
        ACTION_VOTE,
        ACTION_EXILE_LAST_WORDS,
        ACTION_HUNTER_SHOOT,
        ACTION_SUMMARIZE,
    ),
    win_condition=WIN_CONDITION_SLAUGHTER_SIDE,
    reveal_policy=REVEAL_POLICY_HIDDEN,
    complexity="进阶",
    estimated_duration="长",
    sheriff_enabled=True,
    sheriff_vote_weight=1.5,
    werewolf_self_explosion_enabled=True,
    exile_last_words_enabled=True,
    first_night_last_words_enabled=True,
    sheriff_badge_bomb_policy="double",
    speech_policy=SPEECH_POLICY_SHERIFF_DIRECTED,
    rule_tags=("有警长", "警徽 1.5 票", "屠边", "预女猎白"),
)

OFFICIAL_RULE_SETS = (CLASSIC_8, STARTER_6, SOCIAL_8, CLASSIC_12_SEER_WITCH_HUNTER_IDIOT)


RULE_CLAUSES: tuple[RuleClause, ...] = (
    RuleClause(
        clause_id="night.werewolf_attack.non_wolf_targets.v1",
        audience=RULE_AUDIENCE_PLAYER_PUBLIC,
        neutral_text_zh="狼人夜间只能袭击非狼人玩家，不能选择自己或狼人队友。",
        engine_constraint_ids=("engine.night.werewolf_attack.candidates_non_wolves",),
        actions=(ACTION_REMOVE,),
        prompt_slots=("public_fixed_rules",),
    ),
    RuleClause(
        clause_id="night.dawn.hidden_causes.v1",
        audience=RULE_AUDIENCE_PLAYER_PUBLIC,
        neutral_text_zh=(
            "天亮只公布夜间出局名单，不公布每名玩家来自狼人袭击、女巫毒药或其他夜间效果，"
            "也不因此公开身份。"
        ),
        engine_constraint_ids=("projection.dawn.death_causes_hidden",),
        phases=("dawn",),
        prompt_slots=("public_fixed_rules",),
    ),
    RuleClause(
        clause_id="day.exile.weighted_plurality_and_runoff.v1",
        audience=RULE_AUDIENCE_PLAYER_PUBLIC,
        neutral_text_zh=(
            "白天放逐按有效票权重计算，唯一最高票玩家直接被放逐，不要求过半；"
            "最高票平票时进入 PK 发言和二轮投票，PK 候选不参加二轮投票，"
            "二轮仍平票则无人被放逐。"
        ),
        engine_constraint_ids=(
            "engine.day.exile.weighted_plurality",
            "engine.day.exile.runoff_excludes_pk_candidates",
            "engine.day.exile.runoff_tie_no_exile",
        ),
        actions=(ACTION_VOTE, ACTION_EXILE_PK_SPEECH, ACTION_EXILE_RUNOFF_VOTE),
        prompt_slots=("public_fixed_rules",),
    ),
    RuleClause(
        clause_id="day.exile.last_words_and_terminal.v1",
        audience=RULE_AUDIENCE_PLAYER_PUBLIC,
        neutral_text_zh=(
            "被白天投票放逐且实际出局的玩家通常发表一次遗言；若放逐后立即满足胜利条件，"
            "则不再发表放逐遗言，但已经触发的死亡技能仍按终局结算顺序处理。"
            "白痴翻牌免死、狼人自爆、夜间死亡和猎人带走均不触发该遗言；"
            "普通放逐的遗言结束后再依次结算已触发的死亡技能与警徽。"
        ),
        engine_constraint_ids=(
            "engine.day.exile.last_words_eligible",
            "engine.day.exile.terminal_skips_last_words",
            "engine.day.exile.aftermath_order",
        ),
        actions=(ACTION_EXILE_LAST_WORDS,),
        required_flags=("exile_last_words_enabled",),
        prompt_slots=("public_fixed_rules",),
    ),
    RuleClause(
        clause_id="day.self_explosion.interruption.v1",
        audience=RULE_AUDIENCE_PLAYER_PUBLIC,
        neutral_text_zh=(
            "狼人白天公开阶段可以自爆；仅在引擎开放的公开动作窗口生效。自爆者公开出局，"
            "当前及剩余公开动作被取消，当日不再投票，自爆者没有放逐遗言；"
            "若对局尚未结束则进入下一夜。"
        ),
        engine_constraint_ids=(
            "engine.day.self_explosion.public_windows",
            "engine.day.self_explosion.cancels_remaining_actions",
            "engine.day.self_explosion.skips_vote_and_last_words",
        ),
        actions=(ACTION_WEREWOLF_SELF_EXPLOSION,),
        required_flags=("werewolf_self_explosion_enabled",),
        prompt_slots=("public_fixed_rules",),
    ),
    RuleClause(
        clause_id="day.sheriff.eligibility_and_runoff.v1",
        audience=RULE_AUDIENCE_PLAYER_PUBLIC,
        neutral_text_zh=(
            "只有最初未上警的警下玩家拥有警长投票权；上警玩家退水后不会因此获得警长票权。"
            "首轮最高票平票时由平票候选进行 PK 并由原警下玩家二轮投票，二轮仍平票则警徽流失。"
        ),
        engine_constraint_ids=(
            "engine.day.sheriff.original_off_sheriff_voters_only",
            "engine.day.sheriff.withdrawal_does_not_grant_vote",
            "engine.day.sheriff.runoff_tie_loses_badge",
        ),
        actions=(
            ACTION_SHERIFF_RUN,
            ACTION_SHERIFF_WITHDRAW,
            ACTION_SHERIFF_VOTE,
            ACTION_SHERIFF_PK_SPEECH,
            ACTION_SHERIFF_RUNOFF_VOTE,
        ),
        required_flags=("sheriff_enabled",),
        prompt_slots=("public_fixed_rules",),
    ),
    RuleClause(
        clause_id="night.witch.resources_and_targets.v1",
        audience=RULE_AUDIENCE_PLAYER_PUBLIC,
        neutral_text_zh=(
            "女巫拥有一瓶解药和一瓶毒药，并在自己的行动阶段知道当夜狼人袭击目标；"
            "首夜可以自救，同一夜只能救或毒二选一，毒药不能选择女巫自己或当夜狼人袭击目标。"
        ),
        engine_constraint_ids=(
            "engine.night.witch.observes_attack_target",
            "engine.night.witch.save_poison_mutually_exclusive",
            "engine.night.witch.poison_excludes_self_and_attacked",
        ),
        roles=("女巫",),
        actions=(ACTION_WITCH_SAVE, ACTION_WITCH_POISON),
        prompt_slots=("public_fixed_rules",),
    ),
    RuleClause(
        clause_id="settlement.hunter.trigger_and_order.v1",
        audience=RULE_AUDIENCE_PLAYER_PUBLIC,
        neutral_text_zh=(
            "猎人死亡时可以开枪带走一名存活玩家，也可以不发动；但被女巫毒死时不能开枪；"
            "猎人技能只在死亡结算窗口触发。"
        ),
        engine_constraint_ids=(
            "engine.settlement.hunter.death_trigger_only",
            "engine.settlement.hunter.poison_disables_shot",
        ),
        roles=("猎人",),
        actions=(ACTION_HUNTER_SHOOT,),
        prompt_slots=("public_fixed_rules",),
    ),
    RuleClause(
        clause_id="private.werewolf.team_knowledge.v1",
        audience=RULE_AUDIENCE_ROLE_PRIVATE,
        neutral_text_zh="狼人知道自己的狼人队友；具体队友名单属于狼人私人信息。",
        engine_constraint_ids=("prompt.private.werewolf.teammate_knowledge",),
        roles=("狼人",),
        actions=(
            ACTION_REMOVE,
            ACTION_WEREWOLF_DISCUSS,
            ACTION_WEREWOLF_KILL_VOTE,
            ACTION_WEREWOLF_SELF_EXPLOSION,
            ACTION_DEBATE,
            ACTION_VOTE,
        ),
        prompt_slots=("role_private_rules",),
    ),
    RuleClause(
        clause_id="private.witch.attack_observation.v1",
        audience=RULE_AUDIENCE_ROLE_PRIVATE,
        neutral_text_zh=(
            "你在女巫行动阶段依法获知本夜狼人袭击目标；这项信息属于你的私人观察。"
        ),
        engine_constraint_ids=("prompt.private.witch.current_attack_target",),
        roles=("女巫",),
        actions=(ACTION_WITCH_SAVE, ACTION_WITCH_POISON),
        prompt_slots=("role_private_rules",),
    ),
    RuleClause(
        clause_id="private.seer.investigation_result.v1",
        audience=RULE_AUDIENCE_ROLE_PRIVATE,
        neutral_text_zh=(
            "你的查验结果只进入你的私人观察，除非你主动在公开发言中声明。"
        ),
        engine_constraint_ids=("prompt.private.seer.investigation_result",),
        roles=("预言家",),
        actions=(ACTION_INVESTIGATE, ACTION_DEBATE, ACTION_SHERIFF_SPEECH),
        prompt_slots=("role_private_rules",),
    ),
    RuleClause(
        clause_id="internal.werewolf.collective_fallback.v1",
        audience=RULE_AUDIENCE_INTERNAL_ONLY,
        neutral_text_zh="狼队集体无有效刀口时仅从引擎合法候选中生成确定性系统结果。",
        engine_constraint_ids=("engine.night.werewolf.collective_fallback",),
        roles=("狼人",),
        actions=(ACTION_REMOVE,),
    ),
)


ENGINE_CONSTRAINT_TO_CLAUSE_IDS: dict[str, tuple[str, ...]] = {}
for _clause in RULE_CLAUSES:
    for _constraint_id in _clause.engine_constraint_ids:
        ENGINE_CONSTRAINT_TO_CLAUSE_IDS[_constraint_id] = (
            *ENGINE_CONSTRAINT_TO_CLAUSE_IDS.get(_constraint_id, ()),
            _clause.clause_id,
        )


def get_rule_set(rule_set_id: str) -> RuleSet:
    for rule_set in OFFICIAL_RULE_SETS:
        if rule_set.id == rule_set_id:
            return rule_set
    raise KeyError(rule_set_id)


def rule_clauses_for_rule_set(
    rule_set: RuleSet,
    *,
    audiences: frozenset[str] | None = None,
    role: str | None = None,
    action: str | None = None,
    phase: str | None = None,
) -> tuple[RuleClause, ...]:
    selected_audiences = audiences or frozenset({RULE_AUDIENCE_PLAYER_PUBLIC})
    unknown_audiences = selected_audiences - RULE_AUDIENCES
    if unknown_audiences:
        raise RuleConfigurationError(
            f"Unknown rule clause audience: {', '.join(sorted(unknown_audiences))}"
        )
    return tuple(
        clause
        for clause in RULE_CLAUSES
        if clause.audience in selected_audiences
        and _rule_clause_applies(
            clause,
            rule_set_id=rule_set.id,
            role_names={item.role for item in rule_set.roles},
            configured_actions={*rule_set.night_actions, *rule_set.day_actions},
            enabled_flags={
                field
                for field in (
                    "sheriff_enabled",
                    "werewolf_self_explosion_enabled",
                    "exile_last_words_enabled",
                )
                if getattr(rule_set, field) is True
            },
            role=role,
            action=action,
            phase=phase,
        )
    )


def prompt_rule_clauses_from_snapshot(
    snapshot: Mapping[str, object] | None,
    *,
    role: str,
    action: str,
    phase: str | None = None,
) -> tuple[RuleClause, ...]:
    """Project role-private clauses from the frozen runtime contract.

    New games persist prompt-safe clause payloads so resume does not silently
    pick up a newer code registry. Legacy snapshots still resolve against the
    current code-owned registry. Malformed frozen payloads are ignored here;
    the runtime snapshot resolver rejects them at the persistence boundary.
    """

    if not isinstance(snapshot, Mapping):
        return ()
    rule_set_id = snapshot.get("id")
    raw_roles = snapshot.get("roles")
    raw_night_actions = snapshot.get("night_actions")
    raw_day_actions = snapshot.get("day_actions")
    if not isinstance(rule_set_id, str) or not isinstance(raw_roles, list):
        return ()
    if not isinstance(raw_night_actions, list) or not isinstance(raw_day_actions, list):
        return ()

    role_names = {
        item.get("role")
        for item in raw_roles
        if isinstance(item, Mapping) and isinstance(item.get("role"), str)
    }
    configured_actions = {
        item
        for item in [*raw_night_actions, *raw_day_actions]
        if isinstance(item, str)
    }
    enabled_flags = {
        field
        for field in (
            "sheriff_enabled",
            "werewolf_self_explosion_enabled",
            "exile_last_words_enabled",
        )
        if snapshot.get(field) is True
    }
    frozen_clauses = _prompt_safe_clauses_from_frozen_contract(snapshot)
    clauses = frozen_clauses if frozen_clauses is not None else RULE_CLAUSES
    return tuple(
        clause
        for clause in clauses
        if clause.audience == RULE_AUDIENCE_ROLE_PRIVATE
        and _rule_clause_applies(
            clause,
            rule_set_id=rule_set_id,
            role_names=role_names,
            configured_actions=configured_actions,
            enabled_flags=enabled_flags,
            role=role,
            action=action,
            phase=phase,
        )
    )


def rule_contract_snapshot(
    rule_set: RuleSet,
    *,
    role: str | None = None,
    action: str | None = None,
    phase: str | None = None,
) -> dict[str, object]:
    """Return JSON-safe, prompt-safe contract metadata for a frozen rule set."""

    audiences = {RULE_AUDIENCE_PLAYER_PUBLIC}
    if role is not None:
        audiences.add(RULE_AUDIENCE_ROLE_PRIVATE)
    injected = rule_clauses_for_rule_set(
        rule_set,
        audiences=frozenset(audiences),
        role=role,
        action=action,
        phase=phase,
    )
    return {
        "schema_version": RULE_CONTRACT_SCHEMA_VERSION,
        "revision_id": RULE_CONTRACT_REVISION_ID,
        "prompt_template_version": RULE_PROMPT_TEMPLATE_VERSION,
        "fallback_policy_version": RULE_FALLBACK_POLICY_VERSION,
        "canonical_hash": rule_contract_hash(rule_set),
        "injected_clause_ids": [clause.clause_id for clause in injected],
    }


def rule_contract_hash(rule_set: RuleSet) -> str:
    payload = _frozen_rule_contract_payload(rule_set)
    return _frozen_rule_contract_hash(rule_set, payload)


def freeze_rule_set_snapshot(rule_set: RuleSet) -> dict[str, Any]:
    """Build the immutable runtime rule snapshot used by new games."""

    snapshot = rule_set_snapshot(rule_set)
    contract = _frozen_rule_contract_payload(rule_set)
    contract["canonical_hash"] = _frozen_rule_contract_hash(rule_set, contract)
    snapshot["rule_text"] = contract["public_rule_text"]
    snapshot["rule_contract"] = contract
    return snapshot


def validate_frozen_rule_contract_snapshot(
    snapshot: Mapping[str, object],
    rule_set: RuleSet,
) -> None:
    """Validate a persisted contract without consulting the current registry."""

    rule_text = snapshot.get("rule_text")
    contract = snapshot.get("rule_contract")
    if not isinstance(rule_text, str) or not rule_text.strip():
        raise RuleConfigurationError("Frozen rule_text must be non-empty text")
    if not isinstance(contract, Mapping):
        raise RuleConfigurationError("Frozen rule_contract must be a mapping")
    expected_fields = {
        "schema_version",
        "revision_id",
        "prompt_template_version",
        "fallback_policy_version",
        "canonical_hash",
        "public_rule_text",
        "clauses",
    }
    if set(contract) != expected_fields:
        raise RuleConfigurationError("Frozen rule_contract fields are invalid")
    contract_schema_version = contract.get("schema_version")
    if (
        type(contract_schema_version) is not int
        or contract_schema_version not in READABLE_RULE_CONTRACT_SCHEMA_VERSIONS
    ):
        raise RuleConfigurationError("Frozen rule contract schema is unsupported")
    for field in (
        "revision_id",
        "prompt_template_version",
        "fallback_policy_version",
    ):
        value = contract.get(field)
        if not isinstance(value, str) or not value.strip() or value.strip() != value:
            raise RuleConfigurationError(f"Frozen rule contract {field} is invalid")
    if contract.get("public_rule_text") != rule_text:
        raise RuleConfigurationError("Frozen rule text does not match its contract")
    canonical_hash = contract.get("canonical_hash")
    if (
        not isinstance(canonical_hash, str)
        or len(canonical_hash) != 64
        or any(character not in "0123456789abcdef" for character in canonical_hash)
    ):
        raise RuleConfigurationError("Frozen rule contract hash is invalid")
    raw_clauses = contract.get("clauses")
    if not isinstance(raw_clauses, list):
        raise RuleConfigurationError("Frozen rule contract clauses must be a list")
    clause_ids: set[str] = set()
    for raw_clause in raw_clauses:
        clause = _rule_clause_from_frozen_payload(
            raw_clause,
            contract_schema_version=contract_schema_version,
        )
        if clause.clause_id in clause_ids:
            raise RuleConfigurationError(
                f"Duplicate frozen rule clause id: {clause.clause_id}"
            )
        clause_ids.add(clause.clause_id)
    payload_without_hash = dict(contract)
    payload_without_hash.pop("canonical_hash")
    if canonical_hash != _frozen_rule_contract_hash(rule_set, payload_without_hash):
        raise RuleConfigurationError("Frozen rule contract hash does not match payload")


def rule_text_from_snapshot(
    snapshot: Mapping[str, object] | None,
    *,
    fallback_rule_set: RuleSet,
) -> str:
    """Use a validated frozen rule text, with a legacy-code fallback."""

    if isinstance(snapshot, Mapping) and {
        "rule_text",
        "rule_contract",
    }.issubset(snapshot):
        try:
            validate_frozen_rule_contract_snapshot(snapshot, fallback_rule_set)
        except RuleConfigurationError:
            pass
        else:
            return str(snapshot["rule_text"])
    return render_rule_text(fallback_rule_set)


def _frozen_rule_contract_payload(rule_set: RuleSet) -> dict[str, object]:
    clauses = rule_clauses_for_rule_set(rule_set, audiences=RULE_AUDIENCES)
    return {
        "schema_version": RULE_CONTRACT_SCHEMA_VERSION,
        "revision_id": RULE_CONTRACT_REVISION_ID,
        "prompt_template_version": RULE_PROMPT_TEMPLATE_VERSION,
        "fallback_policy_version": RULE_FALLBACK_POLICY_VERSION,
        "public_rule_text": render_rule_text(rule_set),
        "clauses": [_frozen_rule_clause_payload(clause) for clause in clauses],
    }


def _frozen_rule_contract_hash(
    rule_set: RuleSet,
    contract: Mapping[str, object],
) -> str:
    payload = {
        "rule_set": rule_set_snapshot(rule_set),
        "contract": contract,
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _frozen_rule_clause_payload(clause: RuleClause) -> dict[str, object]:
    payload = _rule_clause_payload(clause)
    if clause.audience == RULE_AUDIENCE_INTERNAL_ONLY:
        payload["neutral_text_zh"] = None
    return payload


def _rule_clause_from_frozen_payload(
    raw_clause: object,
    *,
    contract_schema_version: int,
) -> RuleClause:
    if not isinstance(raw_clause, Mapping):
        raise RuleConfigurationError("Frozen rule clause must be a mapping")
    expected_fields = {
        "clause_id",
        "schema_version",
        "applies_to_rule_sets",
        "roles",
        "phases",
        "actions",
        "required_flags",
        "audience",
        "neutral_text_zh",
        "engine_constraint_ids",
        "prompt_slots",
    }
    if set(raw_clause) != expected_fields:
        raise RuleConfigurationError("Frozen rule clause fields are invalid")
    clause_id = raw_clause.get("clause_id")
    audience = raw_clause.get("audience")
    schema_version = raw_clause.get("schema_version")
    text = raw_clause.get("neutral_text_zh")
    if not isinstance(clause_id, str) or not clause_id.strip():
        raise RuleConfigurationError("Frozen rule clause id is invalid")
    if audience not in RULE_AUDIENCES:
        raise RuleConfigurationError("Frozen rule clause audience is invalid")
    if (
        type(schema_version) is not int
        or schema_version not in READABLE_RULE_CLAUSE_SCHEMA_VERSIONS
    ):
        raise RuleConfigurationError("Frozen rule clause schema is unsupported")
    if schema_version != contract_schema_version:
        raise RuleConfigurationError(
            "Frozen rule clause schema does not match its contract"
        )
    if audience == RULE_AUDIENCE_INTERNAL_ONLY:
        if text is not None:
            raise RuleConfigurationError("Internal frozen rule text must be omitted")
        normalized_text = ""
    else:
        if not isinstance(text, str) or not text.strip():
            raise RuleConfigurationError("Prompt-visible frozen rule text is invalid")
        normalized_text = text

    list_fields: dict[str, tuple[str, ...]] = {}
    for field in (
        "applies_to_rule_sets",
        "roles",
        "phases",
        "actions",
        "required_flags",
        "engine_constraint_ids",
        "prompt_slots",
    ):
        raw_value = raw_clause.get(field)
        if not isinstance(raw_value, list) or any(
            not isinstance(item, str) or not item for item in raw_value
        ):
            raise RuleConfigurationError(f"Frozen rule clause {field} is invalid")
        list_fields[field] = tuple(raw_value)
    if not list_fields["engine_constraint_ids"]:
        raise RuleConfigurationError("Frozen rule clause requires engine constraints")
    if audience == RULE_AUDIENCE_INTERNAL_ONLY and list_fields["prompt_slots"]:
        raise RuleConfigurationError("Internal frozen rule clause cannot have prompt slots")
    return RuleClause(
        clause_id=clause_id,
        schema_version=schema_version,
        applies_to_rule_sets=list_fields["applies_to_rule_sets"],
        roles=list_fields["roles"],
        phases=list_fields["phases"],
        actions=list_fields["actions"],
        required_flags=list_fields["required_flags"],
        audience=str(audience),
        neutral_text_zh=normalized_text,
        engine_constraint_ids=list_fields["engine_constraint_ids"],
        prompt_slots=list_fields["prompt_slots"],
    )


def _prompt_safe_clauses_from_frozen_contract(
    snapshot: Mapping[str, object],
) -> tuple[RuleClause, ...] | None:
    contract = snapshot.get("rule_contract")
    if not isinstance(contract, Mapping):
        return None
    contract_schema_version = contract.get("schema_version")
    if (
        type(contract_schema_version) is not int
        or contract_schema_version not in READABLE_RULE_CONTRACT_SCHEMA_VERSIONS
    ):
        return None
    raw_clauses = contract.get("clauses")
    if not isinstance(raw_clauses, list):
        return None
    try:
        clauses = tuple(
            _rule_clause_from_frozen_payload(
                item,
                contract_schema_version=contract_schema_version,
            )
            for item in raw_clauses
        )
    except RuleConfigurationError:
        return None
    return tuple(
        clause
        for clause in clauses
        if clause.audience in {
            RULE_AUDIENCE_PLAYER_PUBLIC,
            RULE_AUDIENCE_ROLE_PRIVATE,
        }
    )


def clause_ids_for_engine_constraint(constraint_id: str) -> tuple[str, ...]:
    return ENGINE_CONSTRAINT_TO_CLAUSE_IDS.get(constraint_id, ())


def validate_rule_clauses(clauses: Iterable[RuleClause]) -> None:
    seen_ids: set[str] = set()
    for clause in clauses:
        if clause.clause_id in seen_ids:
            raise RuleConfigurationError(f"Duplicate rule clause id: {clause.clause_id}")
        seen_ids.add(clause.clause_id)
        if clause.schema_version != RULE_CONTRACT_SCHEMA_VERSION:
            raise RuleConfigurationError(
                f"Unsupported rule clause schema version: {clause.schema_version}"
            )
        if clause.audience not in RULE_AUDIENCES:
            raise RuleConfigurationError(
                f"Unknown rule clause audience: {clause.audience}"
            )
        if not clause.neutral_text_zh.strip():
            raise RuleConfigurationError(
                f"Rule clause {clause.clause_id} requires neutral text"
            )
        if not clause.engine_constraint_ids:
            raise RuleConfigurationError(
                f"Rule clause {clause.clause_id} requires an engine constraint mapping"
            )
        if (
            clause.audience == RULE_AUDIENCE_INTERNAL_ONLY
            and clause.prompt_slots
        ):
            raise RuleConfigurationError(
                f"Internal-only rule clause {clause.clause_id} cannot have prompt slots"
            )


def _rule_clause_applies(
    clause: RuleClause,
    *,
    rule_set_id: str,
    role_names: set[str],
    configured_actions: set[str],
    enabled_flags: set[str],
    role: str | None,
    action: str | None,
    phase: str | None,
) -> bool:
    if "*" not in clause.applies_to_rule_sets and rule_set_id not in clause.applies_to_rule_sets:
        return False
    if clause.roles and not role_names.intersection(clause.roles):
        return False
    if clause.actions and not configured_actions.intersection(clause.actions):
        return False
    if clause.required_flags and not set(clause.required_flags).issubset(enabled_flags):
        return False
    if clause.audience == RULE_AUDIENCE_ROLE_PRIVATE and role is not None:
        if role not in clause.roles:
            return False
        if action is not None and clause.actions and action not in clause.actions:
            return False
        if phase is not None and clause.phases and phase not in clause.phases:
            return False
    return True


def _rule_clause_payload(clause: RuleClause) -> dict[str, object]:
    return {
        "clause_id": clause.clause_id,
        "schema_version": clause.schema_version,
        "applies_to_rule_sets": list(clause.applies_to_rule_sets),
        "roles": list(clause.roles),
        "phases": list(clause.phases),
        "actions": list(clause.actions),
        "required_flags": list(clause.required_flags),
        "audience": clause.audience,
        "neutral_text_zh": clause.neutral_text_zh,
        "engine_constraint_ids": list(clause.engine_constraint_ids),
        "prompt_slots": list(clause.prompt_slots),
    }


def list_rule_set_summaries() -> list[dict[str, Any]]:
    return [rule_set_summary(rule_set) for rule_set in OFFICIAL_RULE_SETS]


def rule_set_summary(rule_set: RuleSet) -> dict[str, Any]:
    return {
        "id": rule_set.id,
        "version": rule_set.version,
        "name": rule_set.name,
        "description": rule_set.description,
        "player_count": rule_set.player_count,
        "role_summary": role_summary(rule_set),
        "night_actions": list(rule_set.night_actions),
        "day_actions": list(rule_set.day_actions),
        "complexity": rule_set.complexity,
        "estimated_duration": rule_set.estimated_duration,
        "sheriff_enabled": rule_set.sheriff_enabled,
        "sheriff_vote_weight": rule_set.sheriff_vote_weight,
        "werewolf_self_explosion_enabled": rule_set.werewolf_self_explosion_enabled,
        "exile_last_words_enabled": rule_set.exile_last_words_enabled,
        "first_night_last_words_enabled": rule_set.first_night_last_words_enabled,
        "sheriff_badge_bomb_policy": rule_set.sheriff_badge_bomb_policy,
        "speech_policy": rule_set.speech_policy,
        "speech_rounds": rule_set.speech_rounds,
        "rule_tags": list(rule_set.rule_tags),
    }


def rule_set_snapshot(rule_set: RuleSet) -> dict[str, Any]:
    return {
        "id": rule_set.id,
        "version": rule_set.version,
        "name": rule_set.name,
        "description": rule_set.description,
        "player_count": rule_set.player_count,
        "roles": [
            {
                "role": role.role,
                "count": role.count,
                "team": role.team,
                "model_group": role.model_group,
                "category": role.category,
            }
            for role in rule_set.roles
        ],
        "night_actions": list(rule_set.night_actions),
        "day_actions": list(rule_set.day_actions),
        "win_condition": rule_set.win_condition,
        "reveal_policy": rule_set.reveal_policy,
        "complexity": rule_set.complexity,
        "estimated_duration": rule_set.estimated_duration,
        "sheriff_enabled": rule_set.sheriff_enabled,
        "sheriff_vote_weight": rule_set.sheriff_vote_weight,
        "werewolf_self_explosion_enabled": rule_set.werewolf_self_explosion_enabled,
        "exile_last_words_enabled": rule_set.exile_last_words_enabled,
        "first_night_last_words_enabled": rule_set.first_night_last_words_enabled,
        "sheriff_badge_bomb_policy": rule_set.sheriff_badge_bomb_policy,
        "speech_policy": rule_set.speech_policy,
        "speech_rounds": rule_set.speech_rounds,
        "rule_tags": list(rule_set.rule_tags),
    }


def role_summary(rule_set: RuleSet) -> str:
    return " / ".join(f"{role.count} {role.role}" for role in rule_set.roles)


def render_rule_text(rule_set: RuleSet) -> str:
    role_text = "、".join(f"{role.count} 名{role.role}" for role in rule_set.roles)
    lines = [
        f"{rule_set.name}：共 {rule_set.player_count} 名玩家：{role_text}。",
        _render_win_condition_text(rule_set),
        "夜晚行动：",
    ]

    night_action_text = {
        ACTION_REMOVE: "狼人选择并移除一名玩家",
        ACTION_PROTECT: "守卫保护一名玩家",
        ACTION_INVESTIGATE: "预言家查验一名玩家阵营",
        ACTION_WITCH_SAVE: "女巫可以使用解药救下当晚被狼人袭击的玩家",
        ACTION_WITCH_POISON: "女巫可以使用毒药淘汰一名玩家",
    }
    lines.extend(
        f"- {night_action_text[action]}"
        for action in rule_set.night_actions
        if action in night_action_text
    )
    if any(role.role == "白痴" for role in rule_set.roles):
        lines.append("白痴首次被放逐时翻牌免死，之后失去投票权但仍可发言。")
    if rule_set.sheriff_enabled:
        lines.append(
            "白天行动：首日先上警、警上发言、退水，再由警下玩家投票选出警长；"
            "平票时进入 PK 发言和二轮警下投票。"
        )
        lines.append(
            "警长在正式白天发言前决定警左或警右，所有玩家完成完整发言，随后投票放逐并进行总结。"
        )
        lines.append(
            f"警长投票计为 {rule_set.sheriff_vote_weight:g} 票，警长死亡时警徽可移交或撕毁。"
        )
    else:
        lines.append("白天行动：按座次顺序进行一轮完整发言，随后投票放逐并进行总结。")
        lines.append("本局不设警长，也没有警徽。")
    if rule_set.werewolf_self_explosion_enabled:
        if not rule_set.sheriff_enabled:
            lines.append("本局自爆不涉及警长或警徽处理。")
        elif rule_set.sheriff_badge_bomb_policy == "double":
            lines.append(
                "本规则采用双爆吞警徽：警长产生前第一次自爆只中断竞选，第二次自爆才会导致警徽流失。"
            )
        else:
            lines.append("警长产生前自爆会中断当次竞选，但多次自爆不会累计导致警徽流失。")
    contract_lines = [
        clause.neutral_text_zh
        for clause in rule_clauses_for_rule_set(rule_set)
    ]
    if contract_lines:
        lines.append("规则机制补充：")
        lines.extend(f"- {line}" for line in contract_lines)
    lines.append("身份揭示：游戏过程中隐藏玩家真实身份。")
    return "\n".join(lines)


def _render_win_condition_text(rule_set: RuleSet) -> str:
    if rule_set.win_condition == WIN_CONDITION_SLAUGHTER_SIDE:
        return "胜利条件：好人阵营需要放逐/淘汰全部狼人获胜；神职全灭或平民全灭时狼人获胜。"
    return "胜利条件：好人阵营需要放逐/淘汰全部狼人获胜；狼人数量大于或等于其他存活玩家数量时狼人获胜。"


def role_category(rule_set: RuleSet, role: str) -> str:
    return next(role_spec.category for role_spec in rule_set.roles if role_spec.role == role)


def validate_rule_sets(rule_sets: Iterable[RuleSet]) -> None:
    seen_ids: set[str] = set()
    for rule_set in rule_sets:
        if rule_set.id in seen_ids:
            raise RuleConfigurationError(f"Duplicate rule_set id: {rule_set.id}")
        seen_ids.add(rule_set.id)

        role_count = sum(role.count for role in rule_set.roles)
        if role_count != rule_set.player_count:
            raise RuleConfigurationError(
                f"Rule set {rule_set.id} defines {role_count} roles for "
                f"{rule_set.player_count} players"
            )


validate_rule_clauses(RULE_CLAUSES)
validate_rule_sets(OFFICIAL_RULE_SETS)
