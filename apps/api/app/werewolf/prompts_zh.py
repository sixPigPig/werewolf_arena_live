from __future__ import annotations

from typing import Any

GAME_RULES = """你正在进行一局数字版狼人杀。

游戏规则：
- 共 {{num_players}} 名玩家：2 名狼人、1 名预言家、1 名医生、{{num_villagers}} 名村民。
- 每轮包含夜晚和白天两个阶段。
- 夜晚：狼人选择一名玩家出局；预言家查验一名玩家身份；医生保护一名玩家。如果狼人目标被医生保护，则无人出局。
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
    "investigate": "investigate",
    "remove": "remove",
    "protect": "protect",
    "summarize": "summary",
}

FIELD_LABELS = {
    "reasoning": "推理",
    "bid": "发言意愿",
    "say": "发言内容",
    "vote": "投票对象",
    "investigate": "查验对象",
    "remove": "袭击对象",
    "protect": "保护对象",
    "summary": "回合总结",
}


def build_prompt(action: str, world_state: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    if action not in SCHEMAS:
        raise ValueError(f"Unsupported action: {action}")

    sections = [
        _render_base(world_state),
        _render_observations(world_state),
        _render_debate(world_state),
        _render_instruction(action, world_state),
        "请只输出合法 JSON，不要输出 Markdown，不要添加解释性前后缀。",
        _render_json_example(action),
    ]
    return "\n\n".join(section for section in sections if section.strip()), SCHEMAS[action]


def _render_base(world_state: dict[str, Any]) -> str:
    text = GAME_RULES
    for key in ("num_players", "num_villagers"):
        text = text.replace(f"{{{{{key}}}}}", str(world_state[key]))

    personality = world_state.get("personality") or "无"
    werewolf_context = world_state.get("werewolf_context") or ""
    return (
        f"{text}\n"
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
            "行动：医生夜晚保护。\n"
            f"候选人：{options}。\n"
            "你必须选择一名最需要保护的玩家。\n"
            "输出字段 reasoning 和 protect。"
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
