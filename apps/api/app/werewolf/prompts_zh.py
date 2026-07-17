from __future__ import annotations

from typing import Any

DEFAULT_GAME_RULES = """你正在进行一局数字版狼人杀。

游戏规则：
- 共 8 名玩家：2 名狼人、1 名预言家、1 名守卫、4 名村民。
- 每轮包含夜晚和白天两个阶段。
- 夜晚：狼人选择一名玩家出局；预言家查验一名玩家阵营；守卫保护一名玩家。如果狼人目标被守卫保护，则无人出局。
- 白天：所有存活玩家讨论，并投票放逐一名玩家。
- 胜利条件：好人阵营放逐全部狼人即获胜；狼人数量大于或等于其他存活玩家数量时狼人获胜。
"""

SCHEMAS: dict[str, dict[str, Any]] = {
    "debate": {
        "type": "object",
        "properties": {"reasoning": {"type": "string"}, "say": {"type": "string"}},
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
        "properties": {"reasoning": {"type": "string"}, "say": {"type": "string"}},
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
        "properties": {"reasoning": {"type": "string"}, "say": {"type": "string"}},
        "required": ["reasoning", "say"],
    },
    "sheriff_runoff_vote": {
        "type": "object",
        "properties": {"reasoning": {"type": "string"}, "sheriff_vote": {"type": "string"}},
        "required": ["reasoning", "sheriff_vote"],
    },
    "exile_pk_speech": {
        "type": "object",
        "properties": {"reasoning": {"type": "string"}, "say": {"type": "string"}},
        "required": ["reasoning", "say"],
    },
    "exile_runoff_vote": {
        "type": "object",
        "properties": {"reasoning": {"type": "string"}, "vote": {"type": "string"}},
        "required": ["reasoning", "vote"],
    },
    "exile_last_words": {
        "type": "object",
        "properties": {"reasoning": {"type": "string"}, "say": {"type": "string"}},
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
        },
        "required": ["reasoning", "target", "message"],
    },
    "werewolf_kill_vote": {
        "type": "object",
        "properties": {
            "reasoning": {"type": "string"},
            "target": {"type": "string"},
            "message": {"type": "string"},
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
    }:
        speech_guidance_sections.append(_render_speech_mission(world_state))
    if action == "debate":
        speech_guidance_sections.append(_render_debate_guidance(world_state))

    sections = [
        _render_base(world_state),
        _render_observations(world_state),
        _render_model_memory(world_state),
        _render_hard_state(world_state),
        _render_public_facts(world_state),
        _render_public_self_history(world_state),
        _render_stage_interruptions(world_state),
        _render_endgame_context(world_state),
        _render_sheriff_election(world_state),
        _render_public_action_eligibility(world_state),
        _render_quality_feedback(world_state),
        _render_debate(world_state),
        *speech_guidance_sections,
        _render_instruction(action, world_state),
        "请只输出合法 JSON，不要输出 Markdown，不要添加解释性前后缀。",
        _render_json_example(action),
    ]
    return "\n\n".join(section for section in sections if section.strip()), SCHEMAS[action]


def _render_base(world_state: dict[str, Any]) -> str:
    rules_text = str(world_state.get("rule_text") or DEFAULT_GAME_RULES)
    if "狼人杀" not in rules_text:
        rules_text = f"你正在进行一局数字版狼人杀。\n\n{rules_text}"
    personality = world_state.get("personality") or "无"
    werewolf_context = world_state.get("werewolf_context") or ""
    return (
        f"{rules_text}\n"
        "当前状态：\n"
        f"- 现在是第 {world_state['round']} 轮。\n"
        f"- 你是{world_state['name']}，身份是{world_state['role']}。{werewolf_context}\n"
        f"- 你的性格设定：{personality}\n"
        f"- 当前存活玩家：{world_state['remaining_players']}"
    )


def _render_observations(world_state: dict[str, Any]) -> str:
    observations = world_state.get("observations") or []
    if not observations:
        return "你的私人观察：暂无。"
    return "你的私人观察：\n" + "\n".join(f"- {observation}" for observation in observations)


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
        lines.append(f"你的出局原因：{hard_state['death_cause']}。")
    if hard_state.get("current_action"):
        lines.append(f"当前唯一合法阶段：{hard_state['current_action']}。")
    if not lines:
        return ""
    return "引擎硬状态（不可否认或改写）：\n" + "\n".join(f"- {line}" for line in lines)


def _render_public_facts(world_state: dict[str, Any]) -> str:
    facts = world_state.get("public_facts") or []
    if not facts:
        return "公开事实记录：暂无。"
    return "公开事实记录：\n" + "\n".join(f"- {fact}" for fact in facts)


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
    instruction = str(mission.get("instruction") or "").strip()
    if not kind or not instruction:
        return ""
    return f"本次发言质量任务（{kind}）：\n- {instruction}"


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
            "发言必须是中文，简洁、有策略、像真实玩家。输出字段 reasoning 和 say。"
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
            "发言必须是中文，简洁、有策略、像真实玩家。输出字段 reasoning 和 say。"
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
            "发言必须是中文，简洁、有策略、像真实玩家。输出字段 reasoning 和 say。"
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
            "发言必须是中文，简洁、有策略、像真实玩家。输出字段 reasoning 和 say。"
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
        badge_impact = str(decision_context.get("badge_impact") or "none")
        explosion_would_end_game = (
            decision_context.get("explosion_would_end_game") is True
        )
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
        benefit_examples = "阻止关键查验、保护最后隐狼或直接创造胜势"
        if (
            self_explosion_enabled
            and sheriff_enabled
            and election_open
            and not sheriff
            and badge_policy == "double"
        ):
            benefit_examples = f"吞警徽、{benefit_examples}"
        chain_guidance = "正常比较公开身份代价与阵营收益。"
        if consecutive_explosions == 1:
            chain_guidance = (
                "上一轮已经发生自爆；本次必须给出具体 benefit_type 和 primary_risk，"
                "不能只写泛化的阻止好人获取信息。"
            )
        elif consecutive_explosions >= 2:
            chain_guidance = (
                f"已经连续 {consecutive_explosions} 轮发生狼人自爆，默认选择不自爆。"
                "只有直接胜势、关键警徽收益或保护最后隐狼等高价值理由才支持继续；"
                "阻止好人形成信息不能单独作为充分理由。"
            )
        last_wolf_guidance = (
            "你是场上最后一名狼人；自爆会让狼队失去最后存活者，必须优先评估立即败北风险。"
            if actor_is_last_wolf
            else ""
        )
        terminal_guidance = (
            "按当前人数和屠边条件，自爆会立即结算对局；必须明确胜负方向。"
            if explosion_would_end_game
            else ""
        )
        return (
            "行动：狼人自爆判断。\n"
            f"当前阶段：{stage}。\n"
            f"警长产生前自爆次数：{bomb_count}。\n"
            "自爆决策上下文：\n"
            f"- 历史总自爆次数：{total_explosions}。\n"
            f"- 连续自爆轮数：{consecutive_explosions}。\n"
            f"- 当前存活狼人/玩家：{active_wolves}/{active_players}。\n"
            f"- 已完成/待发言玩家数：{completed_speakers}/{pending_speakers}。\n"
            f"- 警徽影响：{badge_impact}。\n"
            f"{feature_context}\n"
            f"{badge_context}\n"
            f"{chain_guidance}\n"
            f"{last_wolf_guidance}\n"
            f"{terminal_guidance}\n"
            "选择自爆会公开你是狼人、你立刻出局，并让当天直接结束进入夜晚。\n"
            f"候选选项：{options}。\n"
            f"已有狼人自爆时，继续自爆必须能带来明确收益，例如{benefit_examples}。"
            "收益不明确时选择不自爆，保留白天发言空间。"
            "请以狼人阵营收益判断，输出字段 reasoning、self_explode、benefit_type、"
            "expected_gain 和 primary_risk。"
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
                "message 用一句简短中文说明最终归票理由。"
                "输出字段 reasoning、target 和 message。"
            )
        return (
            "行动：狼人夜晚最终表态与狼刀投票。\n"
            f"候选人：{options}。\n"
            f"完整狼队密聊：\n{discussion_text}\n"
            "所有存活狼人会同时提交这一次最终票，不会继续进行第三轮投票。"
            "你可以坚持或修改第一轮建议；唯一最高票目标会成为刀口，最高票平票时"
            "法官才会临时触发隐藏归票机制。你不知道谁会获得归票权。"
            "message 用一句简短中文向队友说明坚持或改刀。"
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
            '{"reasoning":"当前连续自爆代价过高",'
            '"self_explode":"不自爆","benefit_type":"none",'
            '"expected_gain":"保留白天发言和抗推空间",'
            '"primary_risk":"继续自爆会损失存活狼人"}'
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
            '"message":"给狼人队友的简短说明"}'
        )
    key = RESULT_FIELD_BY_ACTION[action]
    field_mapping = f"reasoning={FIELD_LABELS['reasoning']}，{key}={FIELD_LABELS[key]}"
    return (
        f"JSON 示例（字段含义：{field_mapping}）："
        f'{{"reasoning":"用中文说明你的推理","{key}":"你的选择或发言"}}'
    )
