from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable


TEAM_VILLAGERS = "villagers"
TEAM_WEREWOLVES = "werewolves"

MODEL_GROUP_VILLAGER = "villager"
MODEL_GROUP_WEREWOLF = "werewolf"

ACTION_REMOVE = "remove"
ACTION_PROTECT = "protect"
ACTION_INVESTIGATE = "investigate"
ACTION_BID = "bid"
ACTION_DEBATE = "debate"
ACTION_VOTE = "vote"
ACTION_SUMMARIZE = "summarize"

WIN_CONDITION_WOLVES_GTE_OTHERS = "wolves_gte_others"
REVEAL_POLICY_HIDDEN = "hidden"

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


CLASSIC_8 = RuleSet(
    id="classic_8",
    version=RULE_SET_VERSION,
    name="经典 8 人局",
    description="包含狼人、预言家、医生与村民的官方标准局。",
    player_count=8,
    roles=(
        RoleSpec("狼人", 2, TEAM_WEREWOLVES, MODEL_GROUP_WEREWOLF),
        RoleSpec("预言家", 1, TEAM_VILLAGERS, MODEL_GROUP_VILLAGER),
        RoleSpec("医生", 1, TEAM_VILLAGERS, MODEL_GROUP_VILLAGER),
        RoleSpec("村民", 4, TEAM_VILLAGERS, MODEL_GROUP_VILLAGER),
    ),
    night_actions=(ACTION_REMOVE, ACTION_PROTECT, ACTION_INVESTIGATE),
    day_actions=(ACTION_BID, ACTION_DEBATE, ACTION_VOTE, ACTION_SUMMARIZE),
    win_condition=WIN_CONDITION_WOLVES_GTE_OTHERS,
    reveal_policy=REVEAL_POLICY_HIDDEN,
    complexity="标准",
    estimated_duration="中",
)

STARTER_6 = RuleSet(
    id="starter_6",
    version=RULE_SET_VERSION,
    name="新手 6 人快局",
    description="更短的官方入门局，适合快速观察模型策略。",
    player_count=6,
    roles=(
        RoleSpec("狼人", 1, TEAM_WEREWOLVES, MODEL_GROUP_WEREWOLF),
        RoleSpec("预言家", 1, TEAM_VILLAGERS, MODEL_GROUP_VILLAGER),
        RoleSpec("医生", 1, TEAM_VILLAGERS, MODEL_GROUP_VILLAGER),
        RoleSpec("村民", 3, TEAM_VILLAGERS, MODEL_GROUP_VILLAGER),
    ),
    night_actions=(ACTION_REMOVE, ACTION_PROTECT, ACTION_INVESTIGATE),
    day_actions=(ACTION_BID, ACTION_DEBATE, ACTION_VOTE, ACTION_SUMMARIZE),
    win_condition=WIN_CONDITION_WOLVES_GTE_OTHERS,
    reveal_policy=REVEAL_POLICY_HIDDEN,
    complexity="入门",
    estimated_duration="短",
)

SOCIAL_8 = RuleSet(
    id="social_8",
    version=RULE_SET_VERSION,
    name="社交 8 人局",
    description="仅保留狼人夜晚行动的官方心理博弈局。",
    player_count=8,
    roles=(
        RoleSpec("狼人", 2, TEAM_WEREWOLVES, MODEL_GROUP_WEREWOLF),
        RoleSpec("村民", 6, TEAM_VILLAGERS, MODEL_GROUP_VILLAGER),
    ),
    night_actions=(ACTION_REMOVE,),
    day_actions=(ACTION_BID, ACTION_DEBATE, ACTION_VOTE, ACTION_SUMMARIZE),
    win_condition=WIN_CONDITION_WOLVES_GTE_OTHERS,
    reveal_policy=REVEAL_POLICY_HIDDEN,
    complexity="心理",
    estimated_duration="中",
)

OFFICIAL_RULE_SETS = (CLASSIC_8, STARTER_6, SOCIAL_8)


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
            }
            for role in rule_set.roles
        ],
        "night_actions": list(rule_set.night_actions),
        "day_actions": list(rule_set.day_actions),
        "win_condition": rule_set.win_condition,
        "reveal_policy": rule_set.reveal_policy,
        "complexity": rule_set.complexity,
        "estimated_duration": rule_set.estimated_duration,
    }


def role_summary(rule_set: RuleSet) -> str:
    return " / ".join(f"{role.count} {role.role}" for role in rule_set.roles)


def render_rule_text(rule_set: RuleSet) -> str:
    role_text = "、".join(f"{role.count} 名{role.role}" for role in rule_set.roles)
    lines = [
        f"{rule_set.name}：共 {rule_set.player_count} 名玩家：{role_text}。",
        "胜利条件：狼人数量大于或等于其他玩家时狼人胜利，否则好人阵营胜利。",
        "夜晚行动：",
    ]

    night_action_text = {
        ACTION_REMOVE: "狼人选择并移除一名玩家",
        ACTION_PROTECT: "医生保护一名玩家",
        ACTION_INVESTIGATE: "预言家查验一名玩家身份",
    }
    lines.extend(
        f"- {night_action_text[action]}"
        for action in rule_set.night_actions
        if action in night_action_text
    )
    lines.append("白天行动：竞选、发言、投票与总结。")
    lines.append("身份揭示：游戏过程中隐藏玩家真实身份。")
    return "\n".join(lines)


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
