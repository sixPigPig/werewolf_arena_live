from __future__ import annotations

from typing import Any

DEFAULT_GAME_RULES = """你正在进行一局数字版狼人杀。

游戏规则：
- 共 8 名玩家：2 名狼人、1 名预言家、1 名守卫、4 名村民。
- 每轮包含夜晚和白天两个阶段。
- 夜晚：狼人选择一名玩家出局；预言家查验一名玩家身份；守卫保护一名玩家。如果狼人目标被守卫保护，则无人出局。
- 白天：所有存活玩家讨论，并投票放逐一名玩家。
- 胜利条件：好人阵营放逐全部狼人即获胜；狼人数量大于或等于其他存活玩家数量时狼人获胜。
"""

SCHEMAS: dict[str, dict[str, Any]] = {
    "bid": {
        "type": "object",
        "properties": {"reasoning": {"type": "string"}, "bid": {"type": "string"}},
        "required": ["reasoning", "bid"],
    },
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
    "bid": "bid",
    "debate": "say",
    "vote": "vote",
    "sheriff_run": "run",
    "sheriff_speech": "say",
    "sheriff_withdraw": "withdraw",
    "sheriff_vote": "sheriff_vote",
    "sheriff_pk_speech": "say",
    "sheriff_runoff_vote": "sheriff_vote",
    "speech_order": "speech_order",
    "sheriff_badge": "badge",
    "investigate": "investigate",
    "remove": "remove",
    "protect": "protect",
    "witch_save": "save",
    "witch_poison": "poison",
    "hunter_shoot": "shoot",
    "summarize": "summary",
}

FIELD_LABELS = {
    "reasoning": "推理",
    "bid": "发言意愿",
    "say": "发言内容",
    "vote": "投票对象",
    "run": "竞选选择",
    "withdraw": "退水选择",
    "sheriff_vote": "警长投票对象",
    "speech_order": "发言方向",
    "badge": "警徽处理",
    "investigate": "查验对象",
    "remove": "袭击对象",
    "protect": "保护对象",
    "save": "解药选择",
    "poison": "毒药选择",
    "shoot": "开枪目标",
    "summary": "回合总结",
}


def build_prompt(action: str, world_state: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    if action not in SCHEMAS:
        raise ValueError(f"Unsupported action: {action}")

    sections = [
        _render_base(world_state),
        _render_observations(world_state),
        _render_sheriff_election(world_state),
        _render_debate(world_state),
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


def _render_sheriff_election(world_state: dict[str, Any]) -> str:
    election = world_state.get("sheriff_election") or []
    if not election:
        return ""
    return "警长竞选公开信息：\n" + "\n".join(f"- {line}" for line in election)


def _render_debate(world_state: dict[str, Any]) -> str:
    debate = world_state.get("debate") or []
    if not debate:
        return "本轮发言记录：讨论尚未开始。"
    return "本轮发言记录：\n" + "\n".join(f"- {line}" for line in debate)


def _render_instruction(action: str, world_state: dict[str, Any]) -> str:
    role = world_state["role"]
    options = world_state.get("options", "")
    if action == "bid":
        return (
            "行动：发言竞价。\n"
            "你需要决定自己有多想成为下一个发言者。0 表示先观察，4 表示必须立刻回应。\n"
            f"你本轮还剩 {world_state['debate_turns_left']} 次潜在发言机会。\n"
            f"请以{role}的目标思考，输出字段 reasoning 和 bid。"
        )
    if action == "debate":
        return (
            "行动：白天公开发言。\n"
            f"你的发言动机：{world_state.get('bidding_rationale') or '暂无'}。\n"
            "如果你是狼人，要误导局势、转移怀疑、保护队友；如果你是好人，要寻找矛盾、提出怀疑并推动团队协作。\n"
            "发言必须是中文，简洁、有策略、像真实玩家。输出字段 reasoning 和 say。"
        )
    if action == "vote":
        return (
            "行动：投票放逐。\n"
            "你必须从候选人中选择一名玩家投票。结合发言、行为矛盾和阵营目标做判断。\n"
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
        return (
            "行动：警上竞选发言。\n"
            "你已经上警，需要公开说明竞选警长的理由、警徽流思路和当前判断。\n"
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
        return (
            "行动：警长投票。\n"
            "警长拥有 1.5 票并决定白天发言方向。你必须从警长候选人中选择一名玩家投票。\n"
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
    if action == "investigate":
        return (
            "行动：预言家夜晚查验。\n"
            f"候选人：{options}。\n"
            "你必须选择一名最值得查验的玩家。\n"
            "输出字段 reasoning 和 investigate。"
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
        return (
            "行动：女巫夜晚毒药。\n"
            f"候选人：{options}。\n"
            "你可以选择一名玩家使用毒药，或选择不使用毒药。"
            "被毒死的猎人不能开枪。输出字段 reasoning 和 poison。"
        )
    if action == "hunter_shoot":
        return (
            "行动：猎人死亡开枪。\n"
            f"候选人：{options}。\n"
            "你可以选择一名存活玩家带走，或选择不发动技能。"
            "结合发言、投票和阵营目标做判断。输出字段 reasoning 和 shoot。"
        )
    if action == "summarize":
        return (
            "行动：回合总结。\n"
            "总结你这一轮得到的信息、怀疑对象、可信对象和下一步策略。使用第一人称中文。\n"
            "输出字段 reasoning 和 summary。"
        )
    raise ValueError(f"Unsupported action: {action}")


def _render_json_example(action: str) -> str:
    key = RESULT_FIELD_BY_ACTION[action]
    field_mapping = f"reasoning={FIELD_LABELS['reasoning']}，{key}={FIELD_LABELS[key]}"
    return (
        f"JSON 示例（字段含义：{field_mapping}）："
        f'{{"reasoning":"用中文说明你的推理","{key}":"你的选择或发言"}}'
    )
