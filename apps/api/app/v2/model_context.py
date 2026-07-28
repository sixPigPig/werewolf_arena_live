from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
import json
import re
from typing import Any

from app.v2.ability_runtime import normalize_role_key, normalize_team_key


MODEL_INFORMATION_SEMANTICS = {
    "self_identity": (
        "法官私下确认给当前行动玩家的真实身份与阵营；它不等于玩家对外公开的身份声明。"
    ),
    "role_capabilities": (
        "由当前玩家真实角色产生的能力；警长身份不会新增、替换或删除这些角色能力。"
    ),
    "ability_runtime_state": (
        "当前玩家真实角色能力的运行状态；owned 表示永久拥有，remaining_uses、"
        "resource_status 和 can_execute_now 表示资源是否已消耗以及本次动作窗口能否执行。"
    ),
    "current_action_effect": (
        "法官根据冻结规则和当前阶段给出的本次动作确定性效果；speech 本身不会改变游戏状态。"
    ),
    "public_office_capabilities": (
        "由当前公开职位产生的附加职权；只描述警长投票、发言顺序和警徽处置等职位权力，"
        "不会赋予验人、用药、守护或开枪等神职能力。"
    ),
    "current_state_restrictions": (
        "当前存活、投票资格和警徽状态等限制；实际执行仍以本次动作的候选人与输出契约为准。"
    ),
    "public_rule_contract": (
        "本局冻结的公开规则；enabled=false 表示对应机制在本局不存在。"
    ),
    "public_match_state": (
        "当前法官确认的公开存活状态；只包含座位与是否仍在场，不包含任何身份或阵营信息。"
    ),
    "private_judge_facts": (
        "法官只向当前行动玩家确认的真实私有事实；是否公开以及如何使用由玩家自主决定。"
    ),
    "public_judge_facts": "法官已经向全体玩家确认的公开事实。",
    "public_role_confirmations": (
        "法官通过公开规则动作明确确认的身份；只有这里列出的座位才属于公开坐实身份。"
    ),
    "role_information_boundaries": (
        "本局公开规则规定的角色信息可见边界；只描述某角色通常会或不会收到哪类法官私有信息，"
        "不暴露本局其他玩家的实际私有动作。"
    ),
    "canonical_public_timeline": (
        "按 source_event_id 去重后的公开法官事件时间线；同一 source_event_id "
        "在其他字段再次出现仍是同一事件，统计时只能计算一次。"
    ),
    "public_event_counters": (
        "从 canonical_public_timeline 和公开身份确认确定性计算的公开事件计数与座位集合。"
    ),
    "vote_snapshots": (
        "法官记录的公开票型快照，包含投票资格、候选范围、实际票重、总票数和领先者；"
        "票型本身不公开任何玩家身份。"
    ),
    "public_statements": (
        "玩家的公开说法，可能包含欺骗、误判或遗漏，不会改变冻结规则或法官事实。"
    ),
    "player_claims": (
        "从玩家原话逐字提取的身份、验人、站边、投票或行动说法；"
        "confirmation_status=unverified 表示未经法官确认，不能当作事实。"
    ),
    "public_statement_ledger": (
        "较早玩家发言中逐字提取的持久说法片段；每条都带 source_event_id，"
        "仍然只是玩家说法，不是法官确认的事实。"
    ),
    "history_coverage": (
        "历史投影的覆盖审计；mode=compacted 表示当前轮和相关原文完整保留，"
        "其余历史发言由带来源的说法账本覆盖；mode=full 表示本次回退为完整发言历史。"
    ),
    "peaceful_night": (
        "night_result.outcome=peaceful 只表示该夜无人出局，不表示当前玩家没有其他私有信息。"
    ),
    "decision_freedom": (
        "这些字段只描述当前玩家可知的信息；如何判断、是否公开私有事实以及采用何种策略"
        "均由玩家自主决定。"
    ),
    "current_information_summary": (
        "置于上下文末尾的确定性信息边界摘要，只重申本次输入已有事实，不评价或修复玩家推理。"
    ),
}


@dataclass(frozen=True)
class V2ModelPlayerReference:
    player_id: str
    seat: int
    display_name: str

    @property
    def ref(self) -> str:
        return f"seat_{self.seat}"

    @property
    def label(self) -> str:
        return f"{self.seat}号"


def project_model_action_context(
    context: dict[str, Any],
    *,
    players: tuple[V2ModelPlayerReference, ...],
) -> dict[str, Any]:
    if not players:
        return dict(context)
    projected = _project_value(context, players=players)
    private_facts = projected.pop("private_authoritative_facts", None)
    if private_facts is not None:
        projected["private_judge_facts"] = private_facts
    public_history = context.get("public_history")
    if isinstance(public_history, list) or isinstance(public_history, tuple):
        facts, statements, role_confirmations, vote_snapshots, canonical_timeline = (
            _project_public_history(public_history, players=players)
        )
        projected.pop("public_history", None)
        projected["public_judge_facts"] = facts
        projected["public_role_confirmations"] = role_confirmations
        projected["canonical_public_timeline"] = canonical_timeline
        projected["public_event_counters"] = _public_event_counters(
            canonical_timeline=canonical_timeline,
            role_confirmations=role_confirmations,
        )
        projected["vote_snapshots"] = vote_snapshots
        projected["player_claims"] = _player_claims(statements)
        compacted_statements, statement_ledger, coverage = _compact_public_statements(
            statements,
            context=projected,
        )
        projected["public_statements"] = compacted_statements
        projected["public_statement_ledger"] = statement_ledger
        projected["history_coverage"] = {
            **coverage,
            "source_event_count": len(public_history),
            "authoritative_fact_count": len(facts),
            "role_confirmation_count": len(role_confirmations),
            "vote_snapshot_count": len(vote_snapshots),
            "canonical_public_event_count": len(canonical_timeline),
        }
    else:
        projected.setdefault("public_judge_facts", [])
        projected.setdefault("public_role_confirmations", [])
        projected.setdefault("canonical_public_timeline", [])
        projected.setdefault(
            "public_event_counters",
            _public_event_counters(
                canonical_timeline=[],
                role_confirmations=[],
            ),
        )
        projected.setdefault("vote_snapshots", [])
        projected.setdefault("public_statements", [])
        projected.setdefault("player_claims", [])
        projected.setdefault("public_statement_ledger", [])
    projected.setdefault(
        "current_action_effect",
        _default_current_action_effect(projected),
    )
    projected.setdefault(
        "role_information_boundaries",
        _role_information_boundaries_from_context(projected),
    )
    projected["information_semantics"] = dict(MODEL_INFORMATION_SEMANTICS)
    projected["player_reference_rule"] = {
        "reference_format": "seat_N",
        "spoken_format": "N号",
        "names_available": False,
        "instruction": "只使用座位号称呼玩家，不得猜测或生成玩家姓名。",
    }
    projected["current_information_summary"] = _current_information_summary(projected)
    return projected


def sanitize_model_speech(
    speech: str,
    *,
    players: tuple[V2ModelPlayerReference, ...],
) -> str:
    return _project_text(speech, players=players)


def resolve_model_target(
    target: str | None,
    *,
    players: tuple[V2ModelPlayerReference, ...],
) -> str | None:
    if target is None:
        return None
    return {player.ref: player.player_id for player in players}.get(target)


def _default_current_action_effect(context: dict[str, Any]) -> dict[str, Any]:
    output_contract = context.get("output_contract")
    output_contract = (
        output_contract if isinstance(output_contract, dict) else {}
    )
    target_policy = output_contract.get("target_policy")
    target_policy = target_policy if isinstance(target_policy, dict) else {}
    return {
        "action_type": context.get("action_type"),
        "source": "current_action_contract",
        "target_mode": target_policy.get("mode", "none"),
        "speech_has_gameplay_effect": False,
        "instruction": (
            "该字段只描述本次动作契约已经确定的机械边界；speech 可以表达策略、"
            "判断或伪装，但不会自行产生死亡、技能、投票或其他游戏效果。"
        ),
    }


def build_public_rule_contract(
    *,
    rule: dict[str, Any],
    max_rounds: int,
) -> dict[str, Any]:
    raw_roles = rule.get("roles")
    roles: list[dict[str, Any]] = []
    if isinstance(raw_roles, list):
        for raw_role in raw_roles:
            if not isinstance(raw_role, dict):
                continue
            role_label = raw_role.get("role")
            count = raw_role.get("count")
            if (
                not isinstance(role_label, str)
                or not role_label.strip()
                or not isinstance(count, int)
                or isinstance(count, bool)
                or count < 1
            ):
                continue
            role_key = normalize_role_key(role_label)
            roles.append(
                {
                    "role_key": role_key,
                    "role_label": role_label.strip(),
                    "count": count,
                    "team": normalize_team_key(raw_role.get("team"), role_key=role_key),
                }
            )

    player_count = rule.get("player_count")
    if not isinstance(player_count, int) or isinstance(player_count, bool):
        player_count = sum(item["count"] for item in roles)
    werewolf_count = sum(
        item["count"] for item in roles if item["role_key"] == "werewolf"
    )
    sheriff_enabled = bool(rule.get("sheriff_enabled"))
    role_composition = "、".join(
        f"{item['count']}名{item['role_label']}" for item in roles
    )
    night_action_rules = _night_action_rules(
        role_keys={item["role_key"] for item in roles},
        werewolf_count=werewolf_count,
        ability_policies=rule.get("ability_policies"),
    )
    reveal_policy = str(rule.get("reveal_policy") or "hidden")
    return {
        "schema_version": 1,
        "source": "frozen_rule_snapshot",
        "rule_id": rule.get("id"),
        "rule_name": rule.get("name"),
        "rule_version": rule.get("version"),
        "player_count": player_count,
        "roles": roles,
        "role_composition": (
            f"本局共有{player_count}名玩家：{role_composition}。"
            if role_composition
            else f"本局共有{player_count}名玩家。"
        ),
        "werewolf_count": werewolf_count,
        "night_action_rules": night_action_rules,
        "max_rounds": max_rounds,
        "win_condition": rule.get("win_condition") or "wolves_gte_others",
        "reveal_policy": reveal_policy,
        "role_reveal_rule": (
            "玩家死亡或被放逐后，法官不会公开其身份或阵营；"
            "出局方式、发言和投票结果均不能作为法官已证实其身份的依据。"
            if reveal_policy == "hidden"
            else "玩家死亡或被放逐后，法官会按照本局公开身份规则播报其身份。"
        ),
        "sheriff_enabled": sheriff_enabled,
        "sheriff_vote_weight": (
            float(rule.get("sheriff_vote_weight") or 1)
            if sheriff_enabled
            else None
        ),
        "sheriff_rule": (
            "本局启用警长系统。"
            if sheriff_enabled
            else "本局不启用警长系统，不存在上警、警徽或警徽流机制。"
        ),
        "speech_policy": rule.get("speech_policy") or "sequential",
        "speech_rounds": int(rule.get("speech_rounds") or 1),
        "werewolf_self_explosion_enabled": bool(
            rule.get("werewolf_self_explosion_enabled")
        ),
        "exile_last_words_enabled": bool(rule.get("exile_last_words_enabled")),
    }


def build_public_match_state(
    *,
    round_no: int,
    players: Iterable[Any],
) -> dict[str, Any]:
    player_list = tuple(players)
    alive_player_ids = [
        str(player.player_id) for player in player_list if bool(player.alive)
    ]
    eliminated_player_ids = [
        str(player.player_id) for player in player_list if not bool(player.alive)
    ]
    return {
        "round_no": round_no,
        "alive_player_count": len(alive_player_ids),
        "alive_player_ids": alive_player_ids,
        "eliminated_player_count": len(eliminated_player_ids),
        "eliminated_player_ids": eliminated_player_ids,
        "identity_information_included": False,
    }


def _role_information_boundaries_from_context(
    context: dict[str, Any],
) -> dict[str, Any]:
    public_rule_contract = context.get("public_rule_contract")
    public_rule_contract = (
        public_rule_contract if isinstance(public_rule_contract, dict) else {}
    )
    raw_roles = public_rule_contract.get("roles")
    raw_roles = raw_roles if isinstance(raw_roles, list) else []
    role_keys = {
        item.get("role_key")
        for item in raw_roles
        if isinstance(item, dict)
        and isinstance(item.get("role_key"), str)
    }
    boundaries: dict[str, dict[str, Any]] = {
        "werewolf": {
            "private_information_received": [
                "存活狼人队友座位",
                "当前狼人袭击动作中的队友建议与团队决议",
                "自己此前已提交的狼人私有动作",
            ],
            "private_information_not_received": [
                "预言家查验结果",
                "女巫用药决定",
                "其他神职的夜间选择",
            ],
        },
        "seer": {
            "private_information_received": [
                "自己的查验目标",
                "自己的查验阵营结果",
                "自己此前已完成的查验历史",
            ],
            "private_information_not_received": [
                "狼人袭击目标",
                "女巫是否使用解药或毒药",
                "守卫守护目标",
                "其他角色的夜间决定",
            ],
        },
        "witch": {
            "private_information_received": [
                "规则允许时法官告知的狼人袭击目标",
                "自己的药物剩余状态",
                "自己此前已提交的用药历史",
            ],
            "private_information_not_received": [
                "预言家查验目标和结果",
                "狼人团队的具体投刀过程",
                "守卫守护目标",
                "其他角色的夜间决定",
            ],
        },
        "guard": {
            "private_information_received": [
                "自己的守护目标与守护历史",
            ],
            "private_information_not_received": [
                "狼人袭击目标",
                "预言家查验结果",
                "女巫用药决定",
            ],
        },
        "hunter": {
            "private_information_received": [
                "法官告知的当前死亡原因是否允许发动猎枪",
                "自己的开枪决定",
            ],
            "private_information_not_received": [
                "狼人袭击目标",
                "预言家查验结果",
                "女巫用药决定",
            ],
        },
        "idiot": {
            "private_information_received": [
                "自己的真实身份与放逐免疫是否已经触发",
            ],
            "private_information_not_received": [
                "其他角色的私有能力动作与结果",
            ],
        },
        "villager": {
            "private_information_received": [
                "自己的真实身份",
            ],
            "private_information_not_received": [
                "其他角色的私有能力动作与结果",
            ],
        },
    }
    return {
        "source": "frozen_public_rules",
        "roles": {
            role_key: boundaries[role_key]
            for role_key in sorted(role_keys)
            if role_key in boundaries
        },
        "instruction": (
            "这些是所有玩家都知道的角色信息边界，不表示本局对应角色已经公开，"
            "也不公开任何玩家本局实际执行的私有动作。"
        ),
    }


def build_actor_information(
    *,
    player_id: str,
    seat: int,
    role_key: str,
    team: str,
    persona: dict[str, Any],
    alive: bool,
    sheriff_player_id: str | None,
    sheriff_badge_state: str,
    rule: dict[str, Any],
    player_state: dict[str, Any] | None = None,
    private_facts: Iterable[dict[str, Any]] | None = None,
    current_action_type: str | None = None,
    current_action_knowledge: dict[str, Any] | None = None,
) -> dict[str, Any]:
    normalized_role = normalize_role_key(role_key)
    state = player_state if isinstance(player_state, dict) else {}
    role_capabilities = _role_capabilities(
        role_key=normalized_role,
        rule=rule,
    )
    is_sheriff = (
        bool(rule.get("sheriff_enabled"))
        and sheriff_badge_state == "held"
        and sheriff_player_id == player_id
    )
    return {
        "self_identity": {
            "player_id": player_id,
            "seat": seat,
            "role_key": normalized_role,
            "team": normalize_team_key(team, role_key=normalized_role),
            "source": "private_role_assignment",
            "authoritative": True,
        },
        "role_capabilities": role_capabilities,
        "ability_runtime_state": _ability_runtime_state(
            abilities=role_capabilities["abilities"],
            alive=alive,
            player_state=state,
            private_facts=private_facts,
            current_action_type=current_action_type,
            current_action_knowledge=current_action_knowledge,
        ),
        "public_office_capabilities": _public_office_capabilities(
            is_sheriff=is_sheriff,
            sheriff_badge_state=sheriff_badge_state,
            rule=rule,
        ),
        "current_state_restrictions": {
            "alive": alive,
            "can_vote": bool(state.get("can_vote", True)) if alive else False,
            "idiot_revealed": bool(state.get("idiot_revealed")),
            "sheriff_badge_state": sheriff_badge_state,
            "instruction": (
                "角色能力与公开职位职权相加后，再受当前状态和本次动作候选范围限制；"
                "公开伪装或谎报身份不受此字段禁止。"
            ),
        },
        "actor_profile": persona,
    }


def _role_capabilities(
    *,
    role_key: str,
    rule: dict[str, Any],
) -> dict[str, Any]:
    capabilities: dict[str, list[dict[str, Any]]] = {
        "villager": [],
        "werewolf": [
            {
                "ability_id": "werewolf.attack",
                "timing": "night",
                "description": "与存活狼人队友共同选择一名存活的非狼人玩家作为袭击目标。",
            }
        ],
        "seer": [
            {
                "ability_id": "seer.investigate",
                "timing": "night",
                "description": "选择一名其他存活玩家，法官私下返回其狼人或好人阵营结果。",
            }
        ],
        "guard": [
            {
                "ability_id": "guard.protect",
                "timing": "night",
                "description": "按照本局守卫规则选择一名存活玩家守护。",
            }
        ],
        "witch": [
            {
                "ability_id": "witch.heal",
                "timing": "night",
                "description": "在解药仍可用且符合本局规则时决定是否救治狼人袭击目标。",
            },
            {
                "ability_id": "witch.poison",
                "timing": "night",
                "description": "在毒药仍可用且符合本局规则时决定是否毒杀合法目标。",
            },
        ],
        "hunter": [
            {
                "ability_id": "hunter.death_shot",
                "timing": "death_reaction",
                "description": "死亡且符合本局猎人规则时，可以选择一名存活玩家开枪或放弃。",
            }
        ],
        "idiot": [
            {
                "ability_id": "idiot.exile_immunity",
                "timing": "first_exile",
                "description": "第一次被投票放逐时公开白痴身份并免于出局，之后失去投票权。",
            }
        ],
    }
    abilities = list(capabilities.get(role_key, []))
    if role_key == "werewolf" and bool(rule.get("werewolf_self_explosion_enabled")):
        abilities.append(
            {
                "ability_id": "werewolf.self_explosion",
                "timing": "eligible_day_windows",
                "description": (
                    "在本局允许的白天窗口决定是否自爆；执行后只有本人立即出局并公开确认"
                    "狼人身份，不会选择、杀死或带走其他玩家。"
                ),
            }
        )
    return {
        "source": "private_role_assignment_and_frozen_rules",
        "role_key": role_key,
        "abilities": abilities,
        "no_exclusive_active_ability": not abilities,
        "instruction": "这些是真实角色能力；获得或失去警长职位都不会改变此列表。",
    }


def _ability_runtime_state(
    *,
    abilities: Iterable[dict[str, Any]],
    alive: bool,
    player_state: dict[str, Any],
    private_facts: Iterable[dict[str, Any]] | None,
    current_action_type: str | None,
    current_action_knowledge: dict[str, Any] | None,
) -> dict[str, Any]:
    facts = tuple(private_facts or ())
    knowledge = (
        current_action_knowledge
        if isinstance(current_action_knowledge, dict)
        else {}
    )
    current_ability_id = _ability_id_for_action(current_action_type)
    latest_commits: dict[str, dict[str, Any]] = {}
    for fact in facts:
        if not isinstance(fact, dict):
            continue
        if fact.get("fact_type") != "private_ability_action_committed":
            continue
        payload = fact.get("payload")
        if not isinstance(payload, dict):
            continue
        ability_id = payload.get("ability_id")
        if isinstance(ability_id, str):
            latest_commits[ability_id] = payload

    limited_uses = {
        "witch.heal": ("heal_remaining", "heal_used"),
        "witch.poison": ("poison_remaining", "poison_used"),
        "hunter.death_shot": (None, "shot_used"),
        "idiot.exile_immunity": (None, None),
    }
    runtime_abilities: list[dict[str, Any]] = []
    for ability in abilities:
        if not isinstance(ability, dict):
            continue
        ability_id = ability.get("ability_id")
        if not isinstance(ability_id, str):
            continue
        last_commit = latest_commits.get(ability_id)
        remaining_uses: int | None = None
        resource_status = "not_limited"
        limited = limited_uses.get(ability_id)
        if limited is not None:
            remaining_key, result_key = limited
            remaining_uses = 1
            if ability_id == "idiot.exile_immunity" and bool(
                player_state.get("idiot_revealed")
            ):
                remaining_uses = 0
            elif (
                isinstance(last_commit, dict)
                and isinstance(last_commit.get("result"), dict)
                and result_key is not None
                and last_commit["result"].get(result_key) is True
            ):
                remaining_uses = 0
            explicit_remaining = (
                knowledge.get(remaining_key)
                if isinstance(remaining_key, str)
                else None
            )
            if isinstance(explicit_remaining, int) and not isinstance(
                explicit_remaining, bool
            ):
                remaining_uses = max(0, explicit_remaining)
            resource_status = "consumed" if remaining_uses == 0 else "available"

        in_current_action_window = current_ability_id == ability_id
        can_execute_now = (
            alive
            and in_current_action_window
            and resource_status != "consumed"
        )
        unavailable_now_reason: str | None = None
        if not alive:
            unavailable_now_reason = "actor_not_alive"
        elif resource_status == "consumed":
            unavailable_now_reason = "resource_consumed"
        elif not in_current_action_window:
            unavailable_now_reason = "not_current_action_window"

        runtime_ability: dict[str, Any] = {
            "ability_id": ability_id,
            "owned": True,
            "resource_status": resource_status,
            "remaining_uses": remaining_uses,
            "in_current_action_window": in_current_action_window,
            "can_execute_now": can_execute_now,
            "unavailable_now_reason": unavailable_now_reason,
        }
        if last_commit is not None:
            runtime_ability["last_committed_action"] = dict(last_commit)
        runtime_abilities.append(runtime_ability)

    return {
        "source": "private_role_assignment_action_history_and_current_window",
        "current_action_ability_id": current_ability_id,
        "abilities": runtime_abilities,
        "instruction": (
            "owned 只表示真实角色拥有该能力；是否已消耗以及本次动作能否执行，"
            "必须以 resource_status、remaining_uses 和 can_execute_now 为准。"
        ),
    }


def _ability_id_for_action(action_type: str | None) -> str | None:
    if not isinstance(action_type, str):
        return None
    if action_type.startswith("ability_") and action_type.endswith("_decision"):
        return action_type[len("ability_") : -len("_decision")]
    if action_type == "werewolf_self_explosion":
        return "werewolf.self_explosion"
    return None


def _public_office_capabilities(
    *,
    is_sheriff: bool,
    sheriff_badge_state: str,
    rule: dict[str, Any],
) -> dict[str, Any]:
    sheriff_enabled = bool(rule.get("sheriff_enabled"))
    abilities: list[dict[str, Any]] = []
    if is_sheriff:
        abilities.append(
            {
                "authority_id": "sheriff.weighted_exile_vote",
                "timing": "weighted_exile_vote",
                "vote_weight": float(rule.get("sheriff_vote_weight") or 1),
            }
        )
        if str(rule.get("speech_policy") or "sequential") == "sheriff_directed":
            abilities.append(
                {
                    "authority_id": "sheriff.choose_speech_order",
                    "timing": "day_discussion_opening",
                }
            )
        abilities.append(
            {
                "authority_id": "sheriff.resolve_badge_after_death",
                "timing": "death_reaction",
                "choices": ["transfer_to_alive_player", "destroy_badge"],
            }
        )
    return {
        "source": "public_match_state_and_frozen_rules",
        "sheriff_system_enabled": sheriff_enabled,
        "is_current_sheriff": is_sheriff,
        "sheriff_badge_state": sheriff_badge_state,
        "abilities": abilities,
        "instruction": (
            "警长职权只与职位有关，不会授予验人、用药、守护、开枪或其他角色能力。"
        ),
    }


def _night_action_rules(
    *,
    role_keys: set[str],
    werewolf_count: int,
    ability_policies: Any,
) -> dict[str, Any]:
    policies = ability_policies if isinstance(ability_policies, dict) else {}
    result: dict[str, Any] = {
        "werewolf_attack": {
            "enabled": werewolf_count > 0,
            "actor_scope": "所有存活狼人",
            "target_scope": "一名存活的非狼人玩家",
            "each_actor_must_choose_target": True,
            "can_target_self": False,
            "can_target_werewolf_teammates": False,
            "team_resolution": dict(policies.get("werewolf_consensus") or {}),
            "single_werewolf_resolution": (
                "本局只有1名狼人时，该狼人每夜必须选择一名存活的非狼人玩家，"
                "不会因团队意见不一致而空刀。"
                if werewolf_count == 1
                else None
            ),
        }
    }
    if "guard" in role_keys:
        guard_policy = policies.get("guard")
        result["guard_protect"] = {
            "enabled": True,
            "target_scope": "一名存活玩家，可以选择自己",
            "target_required": True,
            "first_night_self_protect": bool(
                isinstance(guard_policy, dict)
                and guard_policy.get("first_night_self_protect")
            ),
            "can_repeat_previous_night_target": bool(
                isinstance(guard_policy, dict)
                and guard_policy.get("consecutive_same_target")
            ),
            "successful_protection_effect": (
                "若守护目标当夜受到狼人攻击，该目标不会因这次攻击出局。"
            ),
        }
    if "seer" in role_keys:
        result["seer_investigate"] = {
            "enabled": True,
            "target_scope": "一名其他存活玩家",
            "target_required": True,
            "result_scope": "法官只向预言家确认目标属于狼人阵营或好人阵营",
        }
    if "witch" in role_keys:
        witch_policy = policies.get("witch")
        witch_policy = witch_policy if isinstance(witch_policy, dict) else {}
        result["witch"] = {
            "enabled": True,
            "first_night_self_heal": bool(witch_policy.get("first_night_self_heal")),
            "heal_poison_mutually_exclusive": bool(
                witch_policy.get("heal_poison_mutually_exclusive")
            ),
            "poison_excludes_self": bool(witch_policy.get("poison_excludes_self")),
            "poison_excludes_attacked_target": bool(
                witch_policy.get("poison_excludes_attacked_target")
            ),
        }
    if "hunter" in role_keys:
        hunter_policy = policies.get("hunter")
        hunter_policy = hunter_policy if isinstance(hunter_policy, dict) else {}
        result["hunter_death_shot"] = {
            "enabled": True,
            "poison_disables_shot": bool(hunter_policy.get("poison_disables_shot")),
        }
    return result


def private_authoritative_facts(knowledge: Any) -> list[dict[str, Any]]:
    if isinstance(knowledge, list):
        return [dict(item) for item in knowledge if isinstance(item, dict)]
    if not isinstance(knowledge, dict):
        return []

    facts: list[dict[str, Any]] = []
    for fact_type, payload in knowledge.items():
        if fact_type == "known_investigations" and isinstance(payload, list):
            facts.extend(dict(item) for item in payload if isinstance(item, dict))
            continue
        facts.append({"fact_type": fact_type, "payload": payload})
    return facts


def _project_public_history(
    history: Iterable[Any],
    *,
    players: tuple[V2ModelPlayerReference, ...],
) -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
]:
    facts: list[dict[str, Any]] = []
    statements: list[dict[str, Any]] = []
    role_confirmations: list[dict[str, Any]] = []
    vote_snapshots: list[dict[str, Any]] = []
    canonical_timeline: list[dict[str, Any]] = []
    canonical_source_event_ids: set[str] = set()
    has_presented_player_speech = any(
        isinstance(item, dict)
        and item.get("event_type") == "public_player_speech_presented"
        for item in history
    )
    latest_round = 1
    for history_index, raw_item in enumerate(history, start=1):
        if not isinstance(raw_item, dict):
            continue
        event_type = raw_item.get("event_type")
        payload = raw_item.get("payload")
        if not isinstance(event_type, str) or not isinstance(payload, dict):
            continue
        source_event_id = _source_id(raw_item.get("source_event_id"))
        if source_event_id is None:
            source_event_id = f"history_{history_index}"
        round_no = payload.get("round_no")
        if isinstance(round_no, int) and round_no > 0:
            latest_round = round_no
        projected_payload = _project_value(payload, players=players)
        canonical_event = _canonical_public_event(
            event_type=event_type,
            source_event_id=source_event_id,
            round_no=latest_round,
            payload=projected_payload,
        )
        if (
            canonical_event is not None
            and source_event_id not in canonical_source_event_ids
        ):
            canonical_timeline.append(canonical_event)
            canonical_source_event_ids.add(source_event_id)

        if event_type == "public_player_speech_presented":
            statements.append(
                {
                    "kind": "player_statement",
                    "source_event_id": source_event_id,
                    "occurred_in": {"period": "day", "round_no": latest_round},
                    "stage": projected_payload.get("stage"),
                    "speaker_ref": projected_payload.get("player_id"),
                    "speech": projected_payload.get("speech"),
                }
            )
            continue
        if event_type == "day_speech_committed":
            if not has_presented_player_speech:
                statements.append(
                    {
                        "kind": "player_statement",
                        "source_event_id": source_event_id,
                        "occurred_in": {"period": "day", "round_no": latest_round},
                        "stage": projected_payload.get("stage"),
                        "speaker_ref": projected_payload.get("player_id"),
                        "speech": projected_payload.get("speech"),
                    }
                )
            continue
        if event_type == "day_vote_committed":
            facts.append(
                {
                    "kind": "day_vote",
                    "source_event_id": source_event_id,
                    "occurred_in": {"period": "day", "round_no": latest_round},
                    "action_type": projected_payload.get("action_type"),
                    "voter_ref": projected_payload.get("voter_player_id"),
                    "target_ref": projected_payload.get("target_player_id"),
                    "weight": projected_payload.get("weight"),
                }
            )
            speech = projected_payload.get("speech")
            if not has_presented_player_speech and isinstance(speech, str) and speech:
                statements.append(
                    {
                        "kind": "player_statement",
                        "source_event_id": f"{source_event_id}:speech",
                        "occurred_in": {"period": "day", "round_no": latest_round},
                        "stage": projected_payload.get("action_type"),
                        "speaker_ref": projected_payload.get("voter_player_id"),
                        "speech": speech,
                    }
                )
            continue
        if event_type == "day_vote_resolved":
            vote_snapshots.append(
                {
                    "kind": "vote_result",
                    "source_event_id": source_event_id,
                    "occurred_in": {"period": "day", "round_no": latest_round},
                    "action_type": projected_payload.get("action_type"),
                    "eligible_voter_refs": projected_payload.get(
                        "eligible_voter_ids", []
                    ),
                    "ineligible_voter_refs": projected_payload.get(
                        "ineligible_voter_ids", []
                    ),
                    "candidate_refs": projected_payload.get(
                        "candidate_player_ids", []
                    ),
                    "weighted": projected_payload.get("weighted"),
                    "sheriff_ref": projected_payload.get("sheriff_player_id"),
                    "sheriff_vote_weight": projected_payload.get(
                        "sheriff_vote_weight"
                    ),
                    "voter_weights": projected_payload.get("voter_weights", {}),
                    "totals": projected_payload.get("totals", {}),
                    "leader_refs": projected_payload.get("leaders", []),
                    "identity_reveal": "none",
                }
            )
            continue
        if event_type == "dawn_public_result":
            eliminated = projected_payload.get("dead_player_ids")
            eliminated_refs = eliminated if isinstance(eliminated, list) else []
            facts.append(
                {
                    "kind": "night_result",
                    "source_event_id": source_event_id,
                    "occurred_in": {"period": "night", "round_no": latest_round},
                    "announced_in": {"period": "dawn", "round_no": latest_round},
                    "outcome": "deaths" if eliminated_refs else "peaceful",
                    "eliminated_player_refs": eliminated_refs,
                    "role_revealed": False,
                    "known_role": None,
                    "identity_reveal": "none",
                }
            )
            continue
        if event_type == "player_exiled":
            facts.append(
                {
                    "kind": "player_eliminated",
                    "source_event_id": source_event_id,
                    "occurred_in": {"period": "day", "round_no": latest_round},
                    "public_reason": "exile",
                    "player_ref": projected_payload.get("player_id"),
                    "role_revealed": False,
                    "known_role": None,
                    "identity_reveal": "none",
                }
            )
            continue
        if event_type == "idiot_revealed":
            confirmation = {
                "source_event_id": source_event_id,
                "player_ref": projected_payload.get("player_id"),
                "role_key": "idiot",
                "confirmation_reason": "idiot_exile_immunity_triggered",
                "confirmation_status": "confirmed_by_judge",
            }
            role_confirmations.append(confirmation)
            facts.append(
                {
                    "kind": "role_revealed",
                    "source_event_id": source_event_id,
                    "occurred_in": {"period": "day", "round_no": latest_round},
                    "player_ref": projected_payload.get("player_id"),
                    "role_revealed": True,
                    "known_role": "idiot",
                    "survived": bool(projected_payload.get("survived")),
                }
            )
            continue
        if event_type == "werewolf_self_exploded":
            role_confirmations.append(
                {
                    "source_event_id": source_event_id,
                    "player_ref": projected_payload.get("player_id"),
                    "role_key": "werewolf",
                    "confirmation_reason": "werewolf_self_explosion",
                    "confirmation_status": "confirmed_by_judge",
                }
            )
            facts.append(
                {
                    "kind": "player_eliminated",
                    "source_event_id": source_event_id,
                    "occurred_in": {"period": "day", "round_no": latest_round},
                    "public_reason": "self_explosion",
                    "player_ref": projected_payload.get("player_id"),
                    "stage": projected_payload.get("stage"),
                    "role_revealed": True,
                    "known_role": "werewolf",
                    "identity_reveal": "werewolf_confirmed",
                }
            )
            continue
        if event_type == "hunter_response_resolved":
            hunter_ref = projected_payload.get("hunter_player_id")
            target_ref = projected_payload.get("target_player_id")
            if target_ref is not None:
                role_confirmations.append(
                    {
                        "source_event_id": source_event_id,
                        "player_ref": hunter_ref,
                        "role_key": "hunter",
                        "confirmation_reason": "hunter_public_shot",
                        "confirmation_status": "confirmed_by_judge",
                    }
                )
            facts.append(
                {
                    "kind": "hunter_response",
                    "source_event_id": source_event_id,
                    "occurred_in": {
                        "period": projected_payload.get("period") or "day",
                        "round_no": latest_round,
                    },
                    "hunter_ref": hunter_ref,
                    "target_ref": target_ref,
                    "hunter_role_revealed": target_ref is not None,
                    "target_role_revealed": False,
                    "target_known_role": None,
                }
            )
            continue
        facts.append(
            {
                "kind": event_type,
                "source_event_id": source_event_id,
                "occurred_in": {
                    "period": _public_event_period(event_type),
                    "round_no": latest_round,
                },
                "payload": projected_payload,
            }
        )
    return (
        facts,
        statements,
        role_confirmations,
        vote_snapshots,
        canonical_timeline,
    )


def _canonical_public_event(
    *,
    event_type: str,
    source_event_id: str,
    round_no: int,
    payload: dict[str, Any],
) -> dict[str, Any] | None:
    if event_type in {
        "day_speech_committed",
        "public_player_speech_presented",
        "day_vote_committed",
    }:
        return None
    event: dict[str, Any] = {
        "source_event_id": source_event_id,
        "event_type": event_type,
        "occurred_in": {
            "period": (
                "night" if event_type == "dawn_public_result" else "day"
            ),
            "round_no": round_no,
        },
    }
    if event_type == "day_vote_committed":
        event.update(
            {
                "action_type": payload.get("action_type"),
                "voter_ref": payload.get("voter_player_id"),
                "target_ref": payload.get("target_player_id"),
                "weight": payload.get("weight"),
            }
        )
    elif event_type == "day_vote_resolved":
        event.update(
            {
                "action_type": payload.get("action_type"),
                "totals": payload.get("totals", {}),
                "leader_refs": payload.get("leaders", []),
            }
        )
    elif event_type == "dawn_public_result":
        eliminated = payload.get("dead_player_ids")
        eliminated_refs = eliminated if isinstance(eliminated, list) else []
        event.update(
            {
                "outcome": "deaths" if eliminated_refs else "peaceful",
                "eliminated_player_refs": eliminated_refs,
                "identity_reveal": "none",
            }
        )
    elif event_type == "player_exiled":
        event.update(
            {
                "player_ref": payload.get("player_id"),
                "public_effects": {
                    "player_eliminated": True,
                    "role_revealed": False,
                },
            }
        )
    elif event_type == "werewolf_self_exploded":
        event.update(
            {
                "player_ref": payload.get("player_id"),
                "stage": payload.get("stage"),
                "public_effects": {
                    "player_eliminated": True,
                    "role_confirmed": "werewolf",
                    "other_players_affected": False,
                },
            }
        )
    elif event_type == "idiot_revealed":
        event.update(
            {
                "player_ref": payload.get("player_id"),
                "public_effects": {
                    "role_confirmed": "idiot",
                    "survived": bool(payload.get("survived")),
                },
            }
        )
    elif event_type == "hunter_response_resolved":
        event.update(
            {
                "hunter_ref": payload.get("hunter_player_id"),
                "target_ref": payload.get("target_player_id"),
                "public_effects": {
                    "hunter_role_confirmed": payload.get("target_player_id")
                    is not None,
                    "target_role_revealed": False,
                },
            }
        )
    elif event_type in {
        "sheriff_elected",
        "sheriff_badge_transferred",
        "sheriff_badge_destroyed",
    }:
        event.update(
            {
                "player_ref": payload.get("player_id"),
                "from_player_ref": payload.get("from_player_id"),
                "reason": payload.get("reason"),
            }
        )
    else:
        event["public_payload"] = payload
    return event


def _public_event_counters(
    *,
    canonical_timeline: Iterable[dict[str, Any]],
    role_confirmations: Iterable[dict[str, Any]],
) -> dict[str, Any]:
    timeline = tuple(
        item for item in canonical_timeline if isinstance(item, dict)
    )
    confirmations = tuple(
        item for item in role_confirmations if isinstance(item, dict)
    )
    self_explosions = [
        item for item in timeline if item.get("event_type") == "werewolf_self_exploded"
    ]
    confirmed_wolves = {
        str(item["player_ref"]): str(item["source_event_id"])
        for item in confirmations
        if item.get("role_key") == "werewolf"
        and isinstance(item.get("player_ref"), str)
        and _source_id(item.get("source_event_id")) is not None
    }
    return {
        "counting_rule": (
            "相同 source_event_id 在不同字段中表示同一事件；统计事件、死亡或人数时只能计算一次。"
        ),
        "werewolf_self_explosion_count": len(self_explosions),
        "werewolf_self_explosion_player_refs": [
            item["player_ref"]
            for item in self_explosions
            if isinstance(item.get("player_ref"), str)
        ],
        "werewolf_self_explosion_source_event_ids": [
            item["source_event_id"]
            for item in self_explosions
            if _source_id(item.get("source_event_id")) is not None
        ],
        "confirmed_werewolf_elimination_count": len(confirmed_wolves),
        "confirmed_werewolf_refs": sorted(
            confirmed_wolves,
            key=_seat_sort_key,
        ),
        "confirmed_werewolf_source_event_ids": list(
            dict.fromkeys(confirmed_wolves.values())
        ),
    }


_DURABLE_STATEMENT_TERMS = (
    "预言家",
    "狼人",
    "狼",
    "好人",
    "金水",
    "查杀",
    "村民",
    "女巫",
    "猎人",
    "白痴",
    "守卫",
    "警长",
    "警徽",
    "上警",
    "退水",
    "对跳",
    "悍跳",
    "自爆",
    "站边",
    "怀疑",
    "认下",
    "保",
    "打",
    "出",
    "投",
    "验",
    "毒",
    "救",
    "刀",
    "归票",
    "票型",
    "身份",
    "阵营",
    "狼坑",
    "承诺",
    "明天",
    "今晚",
)
_STRUCTURED_SENTENCE_BOUNDARY = re.compile(r"(?<=[。！？!?；;])|[，,：:]|\n+")
_SEAT_REFERENCE = re.compile(r"(?<!\d)(?:seat_)?(2[0-9]|1[0-9]|[1-9])号?")
_ROLE_CLAIM = re.compile(
    r"(?:我是|我跳|我拍)(?:真)?(?:预言家|女巫|猎人|白痴|守卫|村民|好人|狼人)"
)


def _compact_public_statements(
    statements: list[dict[str, Any]],
    *,
    context: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    if not statements:
        return [], [], {
            "schema_version": 1,
            "mode": "compacted",
            "statement_count": 0,
            "exact_statement_count": 0,
            "ledger_statement_count": 0,
            "through_source_event_id": None,
        }

    current_round = _positive_int(context.get("round_no"))
    if current_round is None:
        public_match_state = context.get("public_match_state")
        if isinstance(public_match_state, dict):
            current_round = _positive_int(public_match_state.get("round_no"))
    current_round = current_round or 1
    focal_refs = _focal_player_refs(context)

    exact_ids: set[str] = set()
    latest_by_speaker: dict[str, str] = {}
    ledger: list[dict[str, Any]] = []
    ledger_ids: set[str] = set()
    coverage_failed = False

    for statement in statements:
        source_id = _source_id(statement.get("source_event_id"))
        speaker_ref = statement.get("speaker_ref")
        speech = statement.get("speech")
        occurred_in = statement.get("occurred_in")
        round_no = (
            _positive_int(occurred_in.get("round_no"))
            if isinstance(occurred_in, dict)
            else None
        )
        if source_id is None or not isinstance(speaker_ref, str) or not isinstance(
            speech, str
        ):
            coverage_failed = True
            continue

        latest_by_speaker[speaker_ref] = source_id
        mentioned_refs = _mentioned_player_refs(speech)
        claims = _durable_statement_clauses(speech)
        if round_no == current_round:
            exact_ids.add(source_id)
        if speaker_ref in focal_refs or focal_refs.intersection(mentioned_refs):
            exact_ids.add(source_id)
        if not claims:
            exact_ids.add(source_id)
        ledger.append(
            {
                "source_event_id": source_id,
                "occurred_in": occurred_in,
                "stage": statement.get("stage"),
                "speaker_ref": speaker_ref,
                "mentioned_player_refs": sorted(mentioned_refs, key=_seat_sort_key),
                "exact_claim_fragments": claims,
            }
        )
        ledger_ids.add(source_id)

    exact_ids.update(latest_by_speaker.values())
    all_ids = {
        source_id
        for statement in statements
        if (source_id := _source_id(statement.get("source_event_id"))) is not None
    }
    if coverage_failed or all_ids != ledger_ids:
        return list(statements), [], _full_history_coverage(
            statements,
            reason="statement_coverage_incomplete",
        )

    exact_statements = [
        statement
        for statement in statements
        if _source_id(statement.get("source_event_id")) in exact_ids
    ]
    older_ledger = [
        item
        for item in ledger
        if item["source_event_id"] not in exact_ids
    ]
    full_size = len(json.dumps(statements, ensure_ascii=False, separators=(",", ":")))
    compacted_size = len(
        json.dumps(
            {
                "public_statements": exact_statements,
                "public_statement_ledger": older_ledger,
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )
    )
    if compacted_size >= full_size:
        return list(statements), [], _full_history_coverage(
            statements,
            reason="compaction_not_smaller",
        )

    return exact_statements, older_ledger, {
        "schema_version": 1,
        "mode": "compacted",
        "statement_count": len(statements),
        "exact_statement_count": len(exact_statements),
        "ledger_statement_count": len(older_ledger),
        "through_source_event_id": _source_id(
            statements[-1].get("source_event_id")
        ),
    }


def _player_claims(statements: list[dict[str, Any]]) -> list[dict[str, Any]]:
    claims: list[dict[str, Any]] = []
    for statement in statements:
        speech = statement.get("speech")
        source_event_id = _source_id(statement.get("source_event_id"))
        speaker_ref = statement.get("speaker_ref")
        if (
            not isinstance(speech, str)
            or source_event_id is None
            or not isinstance(speaker_ref, str)
        ):
            continue
        fragments = _durable_statement_clauses(speech)
        if not fragments:
            continue
        claims.append(
            {
                "source_event_id": source_event_id,
                "occurred_in": statement.get("occurred_in"),
                "stage": statement.get("stage"),
                "speaker_ref": speaker_ref,
                "exact_claim_fragments": fragments,
                "confirmation_status": "unverified",
                "instruction": "这是玩家说法，不是法官事实。",
            }
        )
    return claims


def _current_information_summary(context: dict[str, Any]) -> dict[str, Any]:
    identity = context.get("self_identity")
    identity = identity if isinstance(identity, dict) else {}
    role_capabilities = context.get("role_capabilities")
    role_capabilities = (
        role_capabilities if isinstance(role_capabilities, dict) else {}
    )
    ability_runtime_state = context.get("ability_runtime_state")
    ability_runtime_state = (
        ability_runtime_state
        if isinstance(ability_runtime_state, dict)
        else {}
    )
    runtime_abilities = ability_runtime_state.get("abilities")
    runtime_abilities = (
        runtime_abilities if isinstance(runtime_abilities, list) else []
    )
    office_capabilities = context.get("public_office_capabilities")
    office_capabilities = (
        office_capabilities if isinstance(office_capabilities, dict) else {}
    )
    confirmations = context.get("public_role_confirmations")
    confirmations = confirmations if isinstance(confirmations, list) else []
    claims = context.get("player_claims")
    claims = claims if isinstance(claims, list) else []
    vote_snapshots = context.get("vote_snapshots")
    vote_snapshots = vote_snapshots if isinstance(vote_snapshots, list) else []
    action_effect = context.get("current_action_effect")
    action_effect = action_effect if isinstance(action_effect, dict) else {}
    event_counters = context.get("public_event_counters")
    event_counters = event_counters if isinstance(event_counters, dict) else {}
    return {
        "self_role": identity.get("role_key"),
        "self_team": identity.get("team"),
        "is_current_sheriff": bool(office_capabilities.get("is_current_sheriff")),
        "role_ability_ids": [
            item.get("ability_id")
            for item in role_capabilities.get("abilities", [])
            if isinstance(item, dict) and isinstance(item.get("ability_id"), str)
        ],
        "available_role_ability_ids": [
            item.get("ability_id")
            for item in runtime_abilities
            if isinstance(item, dict)
            and isinstance(item.get("ability_id"), str)
            and item.get("resource_status") != "consumed"
        ],
        "consumed_role_ability_ids": [
            item.get("ability_id")
            for item in runtime_abilities
            if isinstance(item, dict)
            and isinstance(item.get("ability_id"), str)
            and item.get("resource_status") == "consumed"
        ],
        "current_action_ability_id": ability_runtime_state.get(
            "current_action_ability_id"
        ),
        "current_action_target_mode": action_effect.get("target_mode"),
        "current_action_affects_other_players": (
            action_effect.get("if_executed", {}).get("other_players_affected")
            if isinstance(action_effect.get("if_executed"), dict)
            else None
        ),
        "public_office_authority_ids": [
            item.get("authority_id")
            for item in office_capabilities.get("abilities", [])
            if isinstance(item, dict) and isinstance(item.get("authority_id"), str)
        ],
        "publicly_confirmed_roles": confirmations,
        "confirmed_werewolf_elimination_count": event_counters.get(
            "confirmed_werewolf_elimination_count", 0
        ),
        "confirmed_werewolf_refs": event_counters.get(
            "confirmed_werewolf_refs", []
        ),
        "unverified_player_claim_count": len(claims),
        "latest_vote_snapshot": vote_snapshots[-1] if vote_snapshots else None,
        "information_boundary": (
            "self_identity、private_judge_facts、public_judge_facts、"
            "canonical_public_timeline、public_event_counters、"
            "public_role_confirmations 和 vote_snapshots 是法官信息；"
            "public_statements、player_claims 与 public_statement_ledger 都是玩家说法。"
            "相同 source_event_id 只计算一次；"
            "普通死亡或放逐不公开身份；警长职位只增加职位职权，不改变真实角色能力。"
        ),
    }


def _full_history_coverage(
    statements: list[dict[str, Any]],
    *,
    reason: str,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "mode": "full",
        "fallback_reason": reason,
        "statement_count": len(statements),
        "exact_statement_count": len(statements),
        "ledger_statement_count": 0,
        "through_source_event_id": (
            _source_id(statements[-1].get("source_event_id"))
            if statements
            else None
        ),
    }


def _focal_player_refs(context: dict[str, Any]) -> set[str]:
    refs: set[str] = set()
    actor = context.get("actor")
    if isinstance(actor, dict) and isinstance(actor.get("id"), str):
        refs.add(actor["id"])
    candidates = context.get("candidates")
    if isinstance(candidates, list) and len(candidates) <= 3:
        for candidate in candidates:
            if isinstance(candidate, dict) and isinstance(
                candidate.get("player_id"), str
            ):
                refs.add(candidate["player_id"])
    return refs


def _mentioned_player_refs(speech: str) -> set[str]:
    return {f"seat_{match.group(1)}" for match in _SEAT_REFERENCE.finditer(speech)}


def _durable_statement_clauses(speech: str) -> list[str]:
    clauses: list[str] = []
    for raw_clause in _STRUCTURED_SENTENCE_BOUNDARY.split(speech):
        clause = raw_clause.strip()
        if not clause:
            continue
        has_stance = any(term in clause for term in _DURABLE_STATEMENT_TERMS)
        if (_SEAT_REFERENCE.search(clause) and has_stance) or _ROLE_CLAIM.search(
            clause
        ):
            clauses.append(clause)
    return clauses


def _source_id(value: Any) -> str | None:
    if isinstance(value, str) and value:
        return value
    if isinstance(value, int) and not isinstance(value, bool):
        return str(value)
    return None


def _positive_int(value: Any) -> int | None:
    if isinstance(value, int) and not isinstance(value, bool) and value > 0:
        return value
    return None


def _seat_sort_key(ref: str) -> tuple[int, str]:
    if ref.startswith("seat_") and ref[5:].isdigit():
        return int(ref[5:]), ref
    return 10_000, ref


def _public_event_period(event_type: str) -> str:
    return "dawn" if event_type == "dawn_public_result" else "day"


def _project_value(
    value: Any,
    *,
    players: tuple[V2ModelPlayerReference, ...],
) -> Any:
    if isinstance(value, dict):
        return {
            (
                _project_text(key, players=players)
                if isinstance(key, str)
                else key
            ): _project_value(item, players=players)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_project_value(item, players=players) for item in value]
    if isinstance(value, tuple):
        return [_project_value(item, players=players) for item in value]
    if isinstance(value, str):
        return _project_text(value, players=players)
    return value


def _project_text(
    value: str,
    *,
    players: tuple[V2ModelPlayerReference, ...],
) -> str:
    projected = value
    for player in sorted(players, key=lambda item: len(item.player_id), reverse=True):
        projected = projected.replace(player.player_id, player.ref)
    for player in sorted(players, key=lambda item: len(item.display_name), reverse=True):
        if player.display_name:
            projected = projected.replace(player.display_name, player.label)
    return projected
