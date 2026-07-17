from __future__ import annotations

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
    sheriff_badge_bomb_policy: str = "none"


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
    sheriff_badge_bomb_policy="double",
    speech_policy=SPEECH_POLICY_SHERIFF_DIRECTED,
    rule_tags=("有警长", "警徽 1.5 票", "屠边", "预女猎白"),
)

OFFICIAL_RULE_SETS = (CLASSIC_8, STARTER_6, SOCIAL_8, CLASSIC_12_SEER_WITCH_HUNTER_IDIOT)


def get_rule_set(rule_set_id: str) -> RuleSet:
    for rule_set in OFFICIAL_RULE_SETS:
        if rule_set.id == rule_set_id:
            return rule_set
    raise KeyError(rule_set_id)


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
    if any(role.role == "女巫" for role in rule_set.roles):
        lines.append("女巫拥有一瓶解药和一瓶毒药，首夜可自救，同一夜只能救或毒二选一。")
    if any(role.role == "猎人" for role in rule_set.roles):
        lines.append("猎人死亡时可以开枪带走一名玩家，但被女巫毒死时不能开枪。")
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
        self_explosion_text = "狼人白天公开阶段可以自爆，自爆后该狼人公开出局并直接结束当天。"
        if not rule_set.sheriff_enabled:
            self_explosion_text += "自爆不涉及警长或警徽处理。"
        elif rule_set.sheriff_badge_bomb_policy == "double":
            self_explosion_text += (
                "本规则采用双爆吞警徽：警长产生前第一次自爆只中断竞选，第二次自爆才会导致警徽流失。"
            )
        else:
            self_explosion_text += "警长产生前自爆会中断当次竞选，但多次自爆不会累计导致警徽流失。"
        lines.append(self_explosion_text)
    if rule_set.exile_last_words_enabled:
        lines.append(
            "被白天投票放逐且实际出局的玩家发表一次遗言；白痴翻牌免死、狼人自爆、"
            "夜间死亡和猎人带走均不触发该遗言。遗言结束后再依次结算死亡技能与警徽。"
        )
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


validate_rule_sets(OFFICIAL_RULE_SETS)
