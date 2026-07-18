from __future__ import annotations

import logging
from typing import Any

from app.werewolf.public_facts import public_fact_from_dict
from app.werewolf.rules import prompt_rule_clauses_from_snapshot


logger = logging.getLogger(__name__)

DEATH_CAUSE_PROMPT_LABELS = {
    "vote_exile": "被白天投票放逐",
    "werewolf_attack": "被狼人夜间袭击",
    "witch_poison": "被女巫使用毒药",
    "hunter_shot": "被猎人开枪带走",
    "werewolf_self_explosion": "因狼人自爆出局",
}
ACTION_PROMPT_LABELS = {
    "debate": "白天公开发言",
    "vote": "白天放逐投票",
    "sheriff_run": "警长竞选报名",
    "sheriff_speech": "警上竞选发言",
    "sheriff_withdraw": "警长竞选退水",
    "sheriff_vote": "警长投票",
    "sheriff_pk_speech": "警长竞选 PK 发言",
    "sheriff_runoff_vote": "二轮警长投票",
    "exile_pk_speech": "白天放逐 PK 发言",
    "exile_runoff_vote": "白天放逐二轮投票",
    "exile_last_words": "驱逐遗言",
    "speech_order": "警长决定发言方向",
    "sheriff_badge": "警徽处理",
    "werewolf_self_explosion": "狼人自爆判断",
    "hunter_shoot": "猎人死亡技能结算",
}
PHASE_PROMPT_LABELS = {
    "night": "夜晚",
    "day": "白天",
    "sheriff_election": "警长竞选",
    "last_words": "驱逐遗言",
    "game_over": "对局已经结束",
}
STATUS_PROMPT_LABELS = {
    "pending": "待处理",
    "completed": "已完成",
    "canceled": "已取消",
    "failed": "失败",
}
REASON_PROMPT_LABELS = {
    **DEATH_CAUSE_PROMPT_LABELS,
    "terminal_committed": "对局胜方已经确定",
    "terminal_candidate_non_settlement_action": "当前动作不是允许继续的强制结算",
    "stale_action_after_terminal": "这是终局后失效的旧动作",
}
SELF_EXPLOSION_BENEFIT_TYPE_PROMPT_LABELS = {
    "immediate_win": "立即取得对局胜利",
    "secure_badge_denial": "确保对方无法获得或保留警徽收益",
    "protect_last_hidden_wolf": "保护最后一名仍隐藏身份的狼人",
    "deny_confirmed_public_information": "阻止好人获得即将公开的确定信息",
    "force_valuable_night": "强制进入对狼人有明确价值的夜晚",
    "none": "没有足以支持自爆的明确收益",
}
SPEECH_MISSION_PROMPT_CONTENT = {
    "fact_checker": (
        "公开事实核验",
        "纠正或确认一条已经公开发生的事实，并说明它如何影响当前判断。",
    ),
    "vote_analyst": (
        "票型分析",
        "解释一处已有票型、警徽或站边变化，并给出你的票口。",
    ),
    "contradiction_hunter": (
        "矛盾追问",
        "指出一名玩家前后表述中的具体矛盾或需要回答的问题。",
    ),
    "devil_advocate": (
        "反方审视",
        "对当前多数结论提出最强反例或尚未排除的风险。",
    ),
    "risk_controller": (
        "风险控制",
        "说明判断失败的成本、轮次资源或终局风险，并给出稳妥方案。",
    ),
    "consolidator": (
        "信息归纳",
        "合并已有公开信息，形成一个明确且下一步可验证的结论。",
    ),
}
SELF_EXPLOSION_BADGE_IMPACT_PROMPT_LABELS = {
    "none": "不影响警徽",
    "owner_must_transfer_or_destroy": "自爆者持有警徽，出局后必须移交或撕毁",
    "badge_will_be_lost": "本次自爆将导致警徽流失",
    "election_postponed": "本次警长竞选被中断并顺延，警徽暂不产生",
    "election_interrupted": "本次警长竞选被中断",
}

DEFAULT_GAME_RULES = """你正在进行一局数字版狼人杀。

游戏规则：
- 共 8 名玩家：2 名狼人、1 名预言家、1 名守卫、4 名村民。
- 每轮包含夜晚和白天两个阶段。
- 夜晚：狼人选择一名玩家出局；预言家查验一名玩家阵营；守卫保护一名玩家。如果狼人目标被守卫保护，则无人出局。
- 白天：所有存活玩家讨论，并投票放逐一名玩家。
- 胜利条件：好人阵营放逐全部狼人即获胜；狼人数量大于或等于其他存活玩家数量时狼人获胜。
"""

DELIVERY_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "mood": {
            "type": "string",
            "enum": [
                "neutral",
                "restrained",
                "calm",
                "confident",
                "skeptical",
                "tense",
                "frustrated",
                "urgent",
                "sad",
                "excited",
                "playful",
            ],
        },
        "intensity": {"type": "string", "enum": ["low", "medium", "high"]},
        "pace": {"type": "string", "enum": ["slow", "natural", "fast"]},
        "instruction": {"type": "string"},
    },
    "required": ["mood", "intensity", "pace"],
}


def _speech_properties() -> dict[str, Any]:
    return {
        "reasoning": {"type": "string"},
        "say": {"type": "string"},
        "delivery": DELIVERY_SCHEMA,
    }

SCHEMAS: dict[str, dict[str, Any]] = {
    "debate": {
        "type": "object",
        "properties": _speech_properties(),
        "required": ["reasoning", "say"],
    },
    "vote": {
        "type": "object",
        "properties": {"reasoning": {"type": "string"}, "vote": {"type": "string"}},
        "required": ["reasoning", "vote"],
    },
    "sheriff_run": {
        "type": "object",
        "properties": {"reasoning": {"type": "string"}, "run": {"type": "string"}},
        "required": ["reasoning", "run"],
    },
    "sheriff_speech": {
        "type": "object",
        "properties": _speech_properties(),
        "required": ["reasoning", "say"],
    },
    "sheriff_withdraw": {
        "type": "object",
        "properties": {"reasoning": {"type": "string"}, "withdraw": {"type": "string"}},
        "required": ["reasoning", "withdraw"],
    },
    "sheriff_vote": {
        "type": "object",
        "properties": {"reasoning": {"type": "string"}, "sheriff_vote": {"type": "string"}},
        "required": ["reasoning", "sheriff_vote"],
    },
    "sheriff_pk_speech": {
        "type": "object",
        "properties": _speech_properties(),
        "required": ["reasoning", "say"],
    },
    "sheriff_runoff_vote": {
        "type": "object",
        "properties": {"reasoning": {"type": "string"}, "sheriff_vote": {"type": "string"}},
        "required": ["reasoning", "sheriff_vote"],
    },
    "exile_pk_speech": {
        "type": "object",
        "properties": _speech_properties(),
        "required": ["reasoning", "say"],
    },
    "exile_runoff_vote": {
        "type": "object",
        "properties": {"reasoning": {"type": "string"}, "vote": {"type": "string"}},
        "required": ["reasoning", "vote"],
    },
    "exile_last_words": {
        "type": "object",
        "properties": _speech_properties(),
        "required": ["reasoning", "say"],
    },
    "speech_order": {
        "type": "object",
        "properties": {"reasoning": {"type": "string"}, "speech_order": {"type": "string"}},
        "required": ["reasoning", "speech_order"],
    },
    "sheriff_badge": {
        "type": "object",
        "properties": {"reasoning": {"type": "string"}, "badge": {"type": "string"}},
        "required": ["reasoning", "badge"],
    },
    "werewolf_self_explosion": {
        "type": "object",
        "properties": {
            "reasoning": {"type": "string"},
            "self_explode": {"type": "string"},
            "benefit_type": {
                "type": "string",
                "enum": [
                    "immediate_win",
                    "secure_badge_denial",
                    "protect_last_hidden_wolf",
                    "deny_confirmed_public_information",
                    "force_valuable_night",
                    "none",
                ],
            },
            "expected_gain": {"type": "string"},
            "primary_risk": {"type": "string"},
        },
        "required": [
            "reasoning",
            "self_explode",
            "benefit_type",
            "expected_gain",
            "primary_risk",
        ],
    },
    "investigate": {
        "type": "object",
        "properties": {"reasoning": {"type": "string"}, "investigate": {"type": "string"}},
        "required": ["reasoning", "investigate"],
    },
    "remove": {
        "type": "object",
        "properties": {"reasoning": {"type": "string"}, "remove": {"type": "string"}},
        "required": ["reasoning", "remove"],
    },
    "werewolf_discuss": {
        "type": "object",
        "properties": {
            "reasoning": {"type": "string"},
            "target": {"type": "string"},
            "message": {"type": "string"},
            "delivery": DELIVERY_SCHEMA,
        },
        "required": ["reasoning", "target", "message"],
    },
    "werewolf_kill_vote": {
        "type": "object",
        "properties": {
            "reasoning": {"type": "string"},
            "target": {"type": "string"},
            "message": {"type": "string"},
            "delivery": DELIVERY_SCHEMA,
        },
        "required": ["reasoning", "target", "message"],
    },
    "protect": {
        "type": "object",
        "properties": {"reasoning": {"type": "string"}, "protect": {"type": "string"}},
        "required": ["reasoning", "protect"],
    },
    "witch_save": {
        "type": "object",
        "properties": {"reasoning": {"type": "string"}, "save": {"type": "string"}},
        "required": ["reasoning", "save"],
    },
    "witch_poison": {
        "type": "object",
        "properties": {"reasoning": {"type": "string"}, "poison": {"type": "string"}},
        "required": ["reasoning", "poison"],
    },
    "hunter_shoot": {
        "type": "object",
        "properties": {"reasoning": {"type": "string"}, "shoot": {"type": "string"}},
        "required": ["reasoning", "shoot"],
    },
    "summarize": {
        "type": "object",
        "properties": {"reasoning": {"type": "string"}, "summary": {"type": "string"}},
        "required": ["reasoning", "summary"],
    },
}

RESULT_FIELD_BY_ACTION = {
    "debate": "say",
    "vote": "vote",
    "sheriff_run": "run",
    "sheriff_speech": "say",
    "sheriff_withdraw": "withdraw",
    "sheriff_vote": "sheriff_vote",
    "sheriff_pk_speech": "say",
    "sheriff_runoff_vote": "sheriff_vote",
    "exile_pk_speech": "say",
    "exile_runoff_vote": "vote",
    "exile_last_words": "say",
    "speech_order": "speech_order",
    "sheriff_badge": "badge",
    "werewolf_self_explosion": "self_explode",
    "investigate": "investigate",
    "remove": "remove",
    "werewolf_discuss": "target",
    "werewolf_kill_vote": "target",
    "protect": "protect",
    "witch_save": "save",
    "witch_poison": "poison",
    "hunter_shoot": "shoot",
    "summarize": "summary",
}

FIELD_LABELS = {
    "reasoning": "推理",
    "say": "发言内容",
    "vote": "投票对象",
    "run": "竞选选择",
    "withdraw": "退水选择",
    "sheriff_vote": "警长投票对象",
    "speech_order": "发言方向",
    "badge": "警徽处理",
    "self_explode": "自爆选择",
    "investigate": "查验对象",
    "remove": "袭击对象",
    "target": "袭击目标",
    "message": "队友沟通",
    "protect": "保护对象",
    "save": "解药选择",
    "poison": "毒药选择",
    "shoot": "开枪目标",
    "summary": "回合总结",
}


def build_prompt(action: str, world_state: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    if action not in SCHEMAS:
        raise ValueError(f"Unsupported action: {action}")

    speech_guidance_sections = []
    if action in {
        "debate",
        "sheriff_speech",
        "sheriff_pk_speech",
        "exile_pk_speech",
        "exile_last_words",
        "werewolf_discuss",
        "werewolf_kill_vote",
    }:
        speech_guidance_sections.append(_render_speech_mission(world_state))
    if action == "debate":
        speech_guidance_sections.append(_render_debate_guidance(world_state))

    sections = [
        _render_public_rules(world_state),
        _render_role_private_rules(action, world_state),
        _render_private_identity(world_state),
        _render_public_state(world_state),
        _render_public_facts(world_state),
        _render_public_self_history(world_state),
        _render_stage_interruptions(world_state),
        _render_endgame_context(world_state),
        _render_sheriff_election(world_state),
        _render_public_action_eligibility(world_state),
        _render_observations(world_state),
        _render_model_memory(world_state),
        _render_hard_state(world_state),
        _render_quality_feedback(world_state),
        _render_debate(world_state),
        *speech_guidance_sections,
        _render_action_contract(action, world_state),
        "请只输出合法 JSON，不要输出 Markdown，不要添加解释性前后缀。",
        _render_json_example(action),
    ]
    return "\n\n".join(section for section in sections if section.strip()), SCHEMAS[action]


def _render_public_rules(world_state: dict[str, Any]) -> str:
    rules_text = str(world_state.get("rule_text") or DEFAULT_GAME_RULES)
    if "狼人杀" not in rules_text:
        rules_text = f"你正在进行一局数字版狼人杀。\n\n{rules_text}"
    return f"公共固定规则：\n{rules_text}"


def _render_role_private_rules(action: str, world_state: dict[str, Any]) -> str:
    snapshot = world_state.get("rule_set_snapshot")
    clauses = prompt_rule_clauses_from_snapshot(
        snapshot if isinstance(snapshot, dict) else None,
        role=str(world_state.get("role") or ""),
        action=action,
        phase=str(world_state.get("phase") or "") or None,
    )
    if not clauses:
        return ""
    return "角色私有规则：\n" + "\n".join(
        f"- {clause.neutral_text_zh}" for clause in clauses
    )


def _render_public_state(world_state: dict[str, Any]) -> str:
    return (
        "当前公开状态：\n"
        f"- 现在是第 {world_state['round']} 轮。\n"
        f"- 当前存活玩家：{world_state['remaining_players']}"
    )


def _render_private_identity(world_state: dict[str, Any]) -> str:
    personality = world_state.get("personality") or "无"
    werewolf_context = world_state.get("werewolf_context") or ""
    return (
        "当前私人身份与设定：\n"
        f"- 你是{world_state['name']}，身份是{world_state['role']}。{werewolf_context}\n"
        f"- 你的性格设定：{personality}"
    )


def _render_observations(world_state: dict[str, Any]) -> str:
    observations = world_state.get("observations") or []
    if not observations:
        return "你的私人观察（当前）：暂无。"
    return "你的私人观察（当前）：\n" + "\n".join(
        f"- {observation}" for observation in observations
    )


def _render_action_contract(action: str, world_state: dict[str, Any]) -> str:
    instruction = _render_instruction(action, world_state)
    if action in {
        "debate",
        "sheriff_speech",
        "sheriff_pk_speech",
        "exile_pk_speech",
        "exile_last_words",
        "werewolf_discuss",
        "werewolf_kill_vote",
    }:
        instruction += (
            "\n同时可输出 delivery，使用受控的 mood、intensity、pace 描述本轮演绎；"
            "instruction 只能写情绪、停顿、反问等演绎方式，不得写身份、座位、票型或行动事实。"
            "delivery 缺失不会影响有效 say 或 message。"
        )
    return "本次合法动作与候选：\n" + instruction


def _render_model_memory(world_state: dict[str, Any]) -> str:
    memories = world_state.get("model_memory") or []
    if not memories:
        return ""
    return (
        "你的模型策略笔记（可能包含误判，不属于客观事实）：\n"
        + "\n".join(f"- {memory}" for memory in memories)
    )


def _render_hard_state(world_state: dict[str, Any]) -> str:
    hard_state = world_state.get("hard_state")
    if not isinstance(hard_state, dict):
        return ""
    lines: list[str] = []
    if hard_state.get("actor_alive") is False:
        lines.append("你已经出局，不在当前存活玩家名单中。")
    if hard_state.get("death_cause"):
        death_cause = _prompt_state_label(
            hard_state["death_cause"],
            field="death_cause",
            labels=DEATH_CAUSE_PROMPT_LABELS,
            fallback="因未识别的规则原因出局",
        )
        lines.append(f"你的出局原因：{death_cause}。")
    if hard_state.get("current_action"):
        current_action = _prompt_state_label(
            hard_state["current_action"],
            field="current_action",
            labels=ACTION_PROMPT_LABELS,
            fallback="未识别的规则阶段",
        )
        lines.append(f"当前唯一合法阶段：{current_action}。")
    if hard_state.get("phase"):
        phase = _prompt_state_label(
            hard_state["phase"],
            field="phase",
            labels=PHASE_PROMPT_LABELS,
            fallback="未识别的规则阶段",
        )
        lines.append(f"当前流程阶段：{phase}。")
    if hard_state.get("status"):
        status = _prompt_state_label(
            hard_state["status"],
            field="status",
            labels=STATUS_PROMPT_LABELS,
            fallback="未识别的流程状态",
        )
        lines.append(f"当前流程状态：{status}。")
    if hard_state.get("reason"):
        reason = _prompt_state_label(
            hard_state["reason"],
            field="reason",
            labels=REASON_PROMPT_LABELS,
            fallback="未识别的规则原因",
        )
        lines.append(f"当前规则原因：{reason}。")
    if hard_state.get("hunter_death_trigger_active") is True:
        lines.append("引擎已经合法触发本次猎人死亡技能，你只能在本次结算中决定是否开枪。")
    elif hard_state.get("hunter_death_trigger_active") is False:
        lines.append("当前没有猎人死亡技能触发；猎人存活状态下不能主动开枪。")
    if not lines:
        return ""
    return "引擎硬状态（不可否认或改写）：\n" + "\n".join(f"- {line}" for line in lines)


def _render_public_facts(world_state: dict[str, Any]) -> str:
    facts = world_state.get("public_facts") or []
    if not facts:
        return "公开信息：暂无。"

    grouped: dict[str, list[str]] = {
        "engine_fact": [],
        "player_claim": [],
        "legacy_unclassified": [],
    }
    for fact in facts:
        if isinstance(fact, str):
            text = fact.strip()
            trust_class = "legacy_unclassified"
        elif isinstance(fact, dict):
            public_fact = public_fact_from_dict(fact)
            text = public_fact.text.strip()
            trust_class = public_fact.effective_trust_class
            if not text and fact.get("text"):
                logger.warning("unsafe_public_fact_rejected_from_prompt")
        else:
            continue
        if not text:
            continue
        grouped[trust_class].append(text)

    sections: list[str] = []
    headings = {
        "engine_fact": "引擎确认事实",
        "player_claim": "玩家声明（可能撒谎）",
        "legacy_unclassified": "未分类公开记录（非引擎确认）",
    }
    for trust_class in ("engine_fact", "player_claim", "legacy_unclassified"):
        entries = grouped[trust_class]
        if entries:
            sections.append(
                f"{headings[trust_class]}：\n"
                + "\n".join(f"- {entry}" for entry in entries)
            )
    return "\n\n".join(sections) if sections else "公开信息：暂无。"


def _prompt_state_label(
    value: object,
    *,
    field: str,
    labels: dict[str, str],
    fallback: str,
) -> str:
    normalized = str(value or "").strip()
    if normalized in labels:
        return labels[normalized]
    if not _is_explicit_chinese_plaintext(normalized):
        logger.warning("unknown_prompt_state_code field=%s", field)
        return fallback
    return normalized or fallback


def _is_explicit_chinese_plaintext(value: str) -> bool:
    """Allow custom human labels, while failing closed on machine-like values."""

    has_chinese = any(
        "\u3400" <= character <= "\u4dbf"
        or "\u4e00" <= character <= "\u9fff"
        for character in value
    )
    has_ascii_letters = any(
        character.isascii() and character.isalpha() for character in value
    )
    return has_chinese and not has_ascii_letters


def _render_public_self_history(world_state: dict[str, Any]) -> str:
    history = world_state.get("public_self_history") or []
    if not history:
        return ""
    return "你的公开发言历史：\n" + "\n".join(f"- {line}" for line in history)


def _render_stage_interruptions(world_state: dict[str, Any]) -> str:
    interruptions = world_state.get("stage_interruptions") or []
    if not interruptions:
        return ""
    return "公开流程中断记录：\n" + "\n".join(
        f"- {line}" for line in interruptions
    )


def _render_endgame_context(world_state: dict[str, Any]) -> str:
    lines = world_state.get("endgame_context") or []
    if not lines:
        return ""
    return "残局压力：\n" + "\n".join(f"- {line}" for line in lines)


def _render_sheriff_election(world_state: dict[str, Any]) -> str:
    election = world_state.get("sheriff_election") or []
    if not election:
        return ""
    context_note = (
        "（前置位内容仅供判断，不要复用其措辞、标题或段落格式）"
        if world_state.get("compact_sheriff_speech_context") is True
        else ""
    )
    return f"警长竞选公开信息{context_note}：\n" + "\n".join(
        f"- {line}" for line in election
    )


def _render_public_action_eligibility(world_state: dict[str, Any]) -> str:
    eligibility = world_state.get("public_action_eligibility")
    if not isinstance(eligibility, dict):
        return ""
    candidates = [str(item) for item in eligibility.get("original_candidates", [])]
    voters = [str(item) for item in eligibility.get("original_voters", [])]
    final_candidates = [str(item) for item in eligibility.get("final_candidates", [])]
    reason = str(eligibility.get("sheriff_vote_reason") or "")
    lines = [
        f"原始上警玩家：{'、'.join(candidates) or '无'}。",
        f"原始警下投票者：{'、'.join(voters) or '无'}。",
        f"当前最终候选：{'、'.join(final_candidates) or '无'}。",
    ]
    if candidates and not voters:
        lines.append("本轮没有警下投票者；任何上警或退水玩家都不能进行警长投票。")
    if eligibility.get("actor_can_sheriff_vote") is True:
        lines.append("你是原始警下玩家，拥有本轮警长投票权。")
    elif reason == "withdrew_candidate_not_original_voter":
        lines.append("你已退水，但你不是原始警下玩家，因此没有本轮警长投票权。")
    elif reason == "candidate_not_eligible":
        lines.append("你是上警玩家，不属于原始警下玩家，因此没有本轮警长投票权。")
    elif reason == "no_off_sheriff_voters":
        lines.append("本轮不存在合法警长投票者。")
    elif reason == "sheriff_disabled":
        lines.append("本局未启用警长规则。")
    elif eligibility.get("sheriff_election_active") is not True:
        lines.append("警长竞选已经结算。")
    lines.append(
        "你可以参与白天放逐投票。"
        if eligibility.get("actor_can_exile_vote") is True
        else "你当前不能参与白天放逐投票。"
    )
    return "警长竞选资格：\n" + "\n".join(f"- {line}" for line in lines)


def _render_debate(world_state: dict[str, Any]) -> str:
    debate = world_state.get("debate") or []
    if not debate:
        return "本轮发言记录：讨论尚未开始。"
    return "本轮发言记录：\n" + "\n".join(f"- {line}" for line in debate)


def _render_debate_guidance(world_state: dict[str, Any]) -> str:
    guidance = world_state.get("debate_guidance") or []
    if not guidance:
        return ""
    return "本轮发言任务：\n" + "\n".join(f"- {line}" for line in guidance)


def _render_speech_mission(world_state: dict[str, Any]) -> str:
    mission = world_state.get("speech_mission")
    if not isinstance(mission, dict):
        return ""
    kind = str(mission.get("kind") or "").strip()
    content = SPEECH_MISSION_PROMPT_CONTENT.get(kind)
    if content is None:
        if kind:
            logger.warning("unknown_prompt_state_code field=speech_mission_kind")
        return (
            "本次发言质量任务（未识别的发言任务）：\n"
            "- 请仅依据已经公开的信息给出清晰、可核验的判断。"
        )
    label, instruction = content
    if not instruction:
        return ""
    return f"本次发言质量任务（{label}）：\n- {instruction}"


def _render_quality_feedback(world_state: dict[str, Any]) -> str:
    feedback = str(world_state.get("quality_feedback") or "").strip()
    if not feedback:
        return ""
    return f"质量反馈：\n- {feedback}"


def _prompt_rule_settings(
    world_state: dict[str, Any],
) -> tuple[bool, float, str, bool]:
    snapshot = world_state.get("rule_set_snapshot")
    if not isinstance(snapshot, dict):
        return False, 1.0, "none", False

    sheriff_enabled = snapshot.get("sheriff_enabled") is True
    raw_weight = snapshot.get("sheriff_vote_weight")
    sheriff_vote_weight = 1.0
    if type(raw_weight) in {int, float}:
        try:
            normalized_weight = float(raw_weight)
        except (OverflowError, ValueError):
            normalized_weight = 1.0
        if normalized_weight in {1.0, 1.5, 2.0}:
            sheriff_vote_weight = normalized_weight
    raw_badge_policy = snapshot.get("sheriff_badge_bomb_policy")
    badge_policy = (
        raw_badge_policy
        if isinstance(raw_badge_policy, str) and raw_badge_policy in {"none", "double"}
        else "none"
    )
    self_explosion_enabled = snapshot.get("werewolf_self_explosion_enabled") is True
    return sheriff_enabled, sheriff_vote_weight, badge_policy, self_explosion_enabled


def _render_instruction(action: str, world_state: dict[str, Any]) -> str:
    role = world_state["role"]
    options = world_state.get("options", "")
    if action == "debate":
        return (
            "行动：白天公开发言。\n"
            "如果你是狼人，要误导局势、转移怀疑、保护队友；如果你是好人，要寻找矛盾、提出怀疑并推动团队协作。\n"
            "发言必须引用至少一条公开事实、票型或前置位发言，不要只复述别人结论。\n"
            "发言必须是中文，简洁、有策略、像真实玩家，不超过 220 个汉字。"
            "输出字段 reasoning 和 say。"
        )
    if action == "vote":
        return (
            "行动：投票放逐。\n"
            "你必须从候选人中选择一名玩家投票。结合发言、行为矛盾和阵营目标做判断。\n"
            "唯一最高票玩家将被放逐，不要求过半；最高票平票时会进入 PK 发言和二轮投票。\n"
            f"候选人：{options}。\n"
            "输出字段 reasoning 和 vote。"
        )
    if action == "sheriff_run":
        return (
            "行动：警长竞选报名。\n"
            "你需要决定是否参与警长竞选，选择上警或不上警。\n"
            f"候选选项：{options}。\n"
            f"请以{role}的目标思考，输出字段 reasoning 和 run。"
        )
    if action == "sheriff_speech":
        role_guidance = (
            "如果你选择公开声称预言家，需要说明已公开的查验结果，并给出后续查验计划；"
            "这种查验计划才叫警徽流。若不公开预言家身份，就不要编造查验能力。"
            if role == "预言家"
            else (
                "警徽流专指预言家的后续查验计划。你并非预言家，不要把警长使用方案写成警徽流，"
                "也不要承诺“先验、再验、今晚验”某位玩家。只有当你的阵营策略明确要求你公开跳预言家时，"
                "才可以给出警徽流，并且必须明确声称预言家、保持身份声明与查验计划一致。"
            )
        )
        return (
            "行动：警上竞选发言。\n"
            "你已经上警，需要公开说明竞选警长的理由、当前判断，以及如果当选将如何使用警长权限，"
            "包括发言方向、归票和警徽移交原则。\n"
            f"{role_guidance}\n"
            "发言必须是中文，简洁、有策略、像真实玩家，不超过 180 个汉字。"
            "输出字段 reasoning 和 say。"
        )
    if action == "sheriff_withdraw":
        return (
            "行动：退水选择。\n"
            "你刚完成警上竞选发言，需要决定是否退水。退水后不再是警长候选，也不会获得警长投票权。\n"
            f"候选选项：{options}。\n"
            "输出字段 reasoning 和 withdraw。"
        )
    if action == "sheriff_vote":
        _, sheriff_vote_weight, _, _ = _prompt_rule_settings(world_state)
        return (
            "行动：警长投票。\n"
            f"当选警长在白天放逐投票中计为 {sheriff_vote_weight:g} 票，并决定白天发言方向。"
            "你必须从警长候选人中选择一名玩家投票。\n"
            f"候选人：{options}。\n"
            "输出字段 reasoning 和 sheriff_vote。"
        )
    if action == "sheriff_pk_speech":
        return (
            "行动：警长竞选 PK 发言。\n"
            "首轮警下投票出现最高票平票，你作为 PK 候选需要再次发言争取警下二轮票。\n"
            "发言必须是中文，简洁、有策略、像真实玩家，不超过 180 个汉字。"
            "输出字段 reasoning 和 say。"
        )
    if action == "sheriff_runoff_vote":
        return (
            "行动：二轮警下投票。\n"
            "你是警下玩家，只能从 PK 候选中选择一名玩家投票。\n"
            f"候选人：{options}。\n"
            "输出字段 reasoning 和 sheriff_vote。"
        )
    if action == "exile_pk_speech":
        return (
            "行动：白天放逐 PK 发言。\n"
            "首轮放逐投票出现最高票平票，你是 PK 候选，需要根据公开发言和首轮票型再次发言。\n"
            "发言必须是中文，简洁、有策略、像真实玩家，不超过 180 个汉字。"
            "输出字段 reasoning 和 say。"
        )
    if action == "exile_runoff_vote":
        return (
            "行动：白天放逐二轮投票。\n"
            "你不在 PK 台上，只能从 PK 候选中选择一名玩家投票。\n"
            f"候选人：{options}。\n"
            "输出字段 reasoning 和 vote。"
        )
    if action == "exile_last_words":
        return (
            "行动：被放逐后的公开遗言。\n"
            "你已经被白天投票放逐并实际出局，不在存活玩家名单中。"
            "这是遗言阶段，不是普通白天发言，也不能在遗言中直接发动角色技能。\n"
            "请结合已经发生的公开事实、发言和票型留下最后判断；可以欺骗或表达主观判断，"
            "但不要把玩家声明写成法官确认事实。发言不超过 150 个汉字。\n"
            "输出字段 reasoning 和 say。"
        )
    if action == "speech_order":
        return (
            "行动：警长决定发言方向。\n"
            "你需要在警左或警右中选择白天发言方向，警长最后归票发言。\n"
            f"候选选项：{options}。\n"
            "输出字段 reasoning 和 speech_order。"
        )
    if action == "sheriff_badge":
        return (
            "行动：移交警徽。\n"
            "你可以选择把警徽交给存活玩家，或选择撕毁警徽。\n"
            f"候选人：{options}。\n"
            "输出字段 reasoning 和 badge。"
        )
    if action == "werewolf_self_explosion":
        stage = world_state.get("self_explosion_stage") or "白天公开阶段"
        decision_context = world_state.get("self_explosion_decision_context")
        if not isinstance(decision_context, dict):
            decision_context = {}
        total_explosions = int(decision_context.get("total_self_explosions") or 0)
        consecutive_explosions = int(
            decision_context.get("consecutive_self_explosion_rounds") or 0
        )
        active_wolves = int(decision_context.get("active_wolves_before") or 0)
        actor_is_last_wolf = decision_context.get("actor_is_last_wolf") is True
        active_players = int(decision_context.get("active_players_before") or 0)
        completed_speakers = int(decision_context.get("completed_public_speakers") or 0)
        pending_speakers = int(decision_context.get("pending_public_speakers") or 0)
        raw_badge_impact = str(decision_context.get("badge_impact") or "none").strip()
        badge_impact = SELF_EXPLOSION_BADGE_IMPACT_PROMPT_LABELS.get(raw_badge_impact)
        if badge_impact is None:
            logger.warning(
                "unknown_prompt_state_code field=self_explosion_badge_impact"
            )
            badge_impact = "未识别警徽影响，按没有额外警徽收益处理"
        sheriff = world_state.get("sheriff")
        election_open = world_state.get("sheriff_election_open") is True
        bomb_count = int(world_state.get("sheriff_pre_election_bomb_count") or 0)
        sheriff_enabled, _, badge_policy, self_explosion_enabled = _prompt_rule_settings(
            world_state
        )
        if not self_explosion_enabled:
            badge_context = (
                "本局不设警长，也没有警徽；锁定规则未启用自爆。"
                if not sheriff_enabled
                else "锁定规则未启用自爆，因此不应用警徽自爆策略。"
            )
        elif not sheriff_enabled:
            badge_context = "本局不设警长，也没有警徽；自爆不涉及警徽处理。"
        elif sheriff:
            badge_context = (
                f"当前警长是{sheriff}，此时自爆不会直接造成警徽流失；"
                "若你是警长，则按死亡警长规则处理警徽。"
            )
        elif election_open and badge_policy == "double":
            badge_context = (
                "当前还没有警长，采用双爆吞警徽规则：第一次警长产生前自爆只会中断警长竞选，"
                "第二次警长产生前自爆会导致警徽流失。"
            )
        elif election_open:
            badge_context = (
                "当前还没有警长；警长产生前自爆会中断当次竞选，但多次自爆不会累计造成警徽流失。"
            )
        else:
            badge_context = "警长竞选已经结束，当前没有可用警徽；自爆不会造成警徽流失。"
        feature_context = (
            "锁定规则已启用狼人自爆。"
            if self_explosion_enabled
            else "锁定规则未确认启用狼人自爆；仅在引擎明确开放该动作时选择。"
        )
        benefit_type_legend = "；".join(
            f"{value}={label}"
            for value, label in SELF_EXPLOSION_BENEFIT_TYPE_PROMPT_LABELS.items()
        )
        last_wolf_fact = (
            "你是场上最后一名狼人。"
            if actor_is_last_wolf
            else "你不是场上最后一名狼人。"
        )
        return (
            "行动：狼人自爆判断。\n"
            f"当前阶段：{stage}。\n"
            f"警长产生前自爆次数：{bomb_count}。\n"
            "自爆决策上下文：\n"
            f"- 历史总自爆次数：{total_explosions}。\n"
            f"- 连续自爆轮数：{consecutive_explosions}。\n"
            f"- 当前存活狼人/玩家：{active_wolves}/{active_players}。\n"
            f"- {last_wolf_fact}\n"
            f"- 已完成/待发言玩家数：{completed_speakers}/{pending_speakers}。\n"
            f"- 警徽影响：{badge_impact}。\n"
            f"{feature_context}\n"
            f"{badge_context}\n"
            "选择自爆会公开你是狼人、你立刻出局并结束当天；若对局尚未结束则进入下一夜。\n"
            f"候选选项：{options}。\n"
            "请依据已提供的规则、公开事实、私人信息和阵营目标自行判断，"
            "输出字段 reasoning、self_explode、benefit_type、"
            "expected_gain 和 primary_risk。"
            f"benefit_type 取值说明：{benefit_type_legend}。"
        )
    if action == "investigate":
        return (
            "行动：预言家夜晚查验。\n"
            f"候选人：{options}。\n"
            "你必须选择一名最值得查验的玩家。\n"
            "输出字段 reasoning 和 investigate。"
        )
    if action == "werewolf_discuss":
        return (
            "行动：狼人夜晚第一轮私密表态。\n"
            f"候选人：{options}。\n"
            "所有存活狼人会同时、独立生成第一轮意见，你暂时看不到队友本轮的内容。\n"
            "你必须从候选人中建议一名袭击目标，并用 message 给队友简短说明理由。"
            "message 控制在 30 至 60 个汉字，不要透露 reasoning 内容。"
            "这是仅狼人队友可见的信息。避免伤害性措辞，用游戏术语表达。"
            "输出字段 reasoning、target 和 message。"
        )
    if action == "werewolf_kill_vote":
        stage = str(world_state.get("werewolf_kill_vote_stage") or "final")
        discussion = world_state.get("werewolf_discussion") or []
        discussion_text = "\n".join(f"- {line}" for line in discussion) if discussion else "暂无。"
        final_vote_context = world_state.get("werewolf_final_vote_context") or "暂无。"
        if stage == "tiebreak":
            return (
                "行动：狼人夜晚平票归票。\n"
                f"完整狼队密聊：\n{discussion_text}\n"
                f"最终票型：{final_vote_context}\n"
                f"最高票平票候选人：{options}。\n"
                "法官已临时要求你行使本夜归票权。你只能从这些平票候选人中"
                "确认一个最终刀口，不能改刀其他玩家。"
                "message 用一句不超过 60 个汉字的简短中文说明最终归票理由。"
                "输出字段 reasoning、target 和 message。"
            )
        return (
            "行动：狼人夜晚最终表态与狼刀投票。\n"
            f"候选人：{options}。\n"
            f"完整狼队密聊：\n{discussion_text}\n"
            "所有存活狼人会同时提交这一次最终票，不会继续进行第三轮投票。"
            "你可以坚持或修改第一轮建议；唯一最高票目标会成为刀口，最高票平票时"
            "法官才会临时触发隐藏归票机制。你不知道谁会获得归票权。"
            "message 用一句不超过 60 个汉字的简短中文向队友说明坚持或改刀。"
            "输出字段 reasoning、target 和 message。"
        )
    if action == "remove":
        return (
            "行动：狼人夜晚袭击。\n"
            f"候选人：{options}。\n"
            "你必须选择一名对狼人最有威胁的玩家。\n"
            "避免伤害性措辞，用游戏术语表达。输出字段 reasoning 和 remove。"
        )
    if action == "protect":
        return (
            "行动：守卫夜晚保护。\n"
            f"候选人：{options}。\n"
            "你必须选择一名最需要保护的玩家。\n"
            "输出字段 reasoning 和 protect。"
        )
    if action == "witch_save":
        return (
            "行动：女巫夜晚解药。\n"
            f"候选人：{options}。\n"
            "你知道今晚被狼人袭击的玩家，可以选择使用解药救人，或选择不使用解药。"
            "本规则允许首夜自救，但同一夜使用解药后不能再使用毒药。"
            "输出字段 reasoning 和 save。"
        )
    if action == "witch_poison":
        attacked = str(world_state.get("attacked") or "")
        attacked_note = (
            f"今晚被狼人袭击的目标是{attacked}；{attacked}不在毒药候选中，不能同时作为毒药目标。"
            if attacked
            else ""
        )
        return (
            "行动：女巫夜晚毒药。\n"
            f"候选人：{options}。\n"
            f"{attacked_note}"
            "你可以选择一名候选玩家使用毒药，或选择不使用毒药。"
            "如果你最怀疑的人不在候选中，请在剩余候选中重新排序，或选择不使用毒药。"
            "如果不使用毒药，必须说明保留毒药仍有收益，不能只说信息不足。"
            "poison 必须完全等于候选人中的一个值。"
            "结合公开事实、票型和警徽流判断。被毒死的猎人不能开枪。"
            "输出字段 reasoning 和 poison。"
        )
    if action == "hunter_shoot":
        return (
            "行动：猎人死亡开枪。\n"
            "引擎已经确认你死亡并出局；你不在存活玩家名单中。当前是在结算死亡技能，"
            "不得以‘自己仍存活’或‘尚未死亡’为理由放弃判断。\n"
            f"候选人：{options}。\n"
            "你可以选择一名存活玩家带走，或选择不发动技能。"
            "必须给出候选嫌疑对比；不能只因为信息不足就随机开枪。"
            "结合公开事实、发言、投票和阵营目标做判断。输出字段 reasoning 和 shoot。"
        )
    if action == "summarize":
        return (
            "行动：回合总结。\n"
            "总结你这一轮得到的信息、怀疑对象、可信对象和下一步策略。使用第一人称中文。\n"
            "输出字段 reasoning 和 summary。"
        )
    raise ValueError(f"Unsupported action: {action}")


def _render_json_example(action: str) -> str:
    if action == "werewolf_self_explosion":
        return (
            "JSON 示例（自爆收益审计）："
            '{"reasoning":"依据当前可见规则和事实自行判断",'
            '"self_explode":"不自爆","benefit_type":"none",'
            '"expected_gain":"说明预期收益",'
            '"primary_risk":"说明主要风险"}'
        )
    if action in {"werewolf_discuss", "werewolf_kill_vote"}:
        field_mapping = (
            f"reasoning={FIELD_LABELS['reasoning']}，"
            f"target={FIELD_LABELS['target']}，"
            f"message={FIELD_LABELS['message']}"
        )
        return (
            f"JSON 示例（字段含义：{field_mapping}）："
            '{"reasoning":"用中文说明你的推理","target":"你的选择或发言",'
            '"message":"给狼人队友的简短说明",'
            '"delivery":{"mood":"tense","intensity":"low","pace":"natural"}}'
        )
    key = RESULT_FIELD_BY_ACTION[action]
    field_mapping = f"reasoning={FIELD_LABELS['reasoning']}，{key}={FIELD_LABELS[key]}"
    if key == "say":
        return (
            f"JSON 示例（字段含义：{field_mapping}）："
            f'{{"reasoning":"用中文说明你的推理","{key}":"你的发言",'
            '"delivery":{"mood":"skeptical","intensity":"medium",'
            '"pace":"natural","instruction":"克制、反问"}}'
        )
    return (
        f"JSON 示例（字段含义：{field_mapping}）："
        f'{{"reasoning":"用中文说明你的推理","{key}":"你的选择或发言"}}'
    )
