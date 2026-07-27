from __future__ import annotations

from dataclasses import dataclass
from typing import Any


class V2JudgeTemplateError(RuntimeError):
    pass


@dataclass(frozen=True)
class V2RenderedJudgeSpeech:
    template_id: str
    template_version: int
    text: str
    variables: dict[str, Any]


def render_judge_speech(
    *,
    action_type: str,
    context: dict[str, Any],
) -> V2RenderedJudgeSpeech:
    variables: dict[str, Any]
    text: str

    if action_type == "judge_opening_speech":
        setup = _mapping(context.get("game_setup"))
        rule_name = _optional_text(setup.get("rule_name"))
        player_count = _optional_int(setup.get("player_count"))
        variables = {
            "rule_name": rule_name,
            "player_count": player_count,
        }
        if rule_name and player_count:
            text = f"欢迎来到{rule_name}。本局共{player_count}名玩家，对局现在开始。"
        elif player_count:
            text = f"欢迎来到本场实时狼人杀对局。本局共{player_count}名玩家，对局现在开始。"
        else:
            text = "欢迎来到本场实时狼人杀对局。对局现在开始。"
    elif action_type == "judge_nightfall_announcement":
        round_no = _positive_int(context.get("round_no"), "round_no")
        variables = {"round_no": round_no}
        text = (
            "首夜开始，请所有玩家闭眼。"
            if round_no == 1
            else f"第{round_no}夜开始，请所有存活玩家闭眼。"
        )
    elif action_type == "judge_dawn_announcement":
        death_seats = _positive_int_list(
            context.get("public_death_seats"),
            "public_death_seats",
        )
        variables = {"public_death_seats": death_seats}
        text = (
            "天亮了，昨夜是平安夜。"
            if not death_seats
            else "天亮了，昨夜出局的玩家是："
            f"{'、'.join(f'{seat}号' for seat in death_seats)}。"
        )
    elif action_type == "judge_sheriff_election_opening":
        round_no = _positive_int(context.get("round_no"), "round_no")
        variables = {"round_no": round_no}
        text = f"第{round_no}天警长竞选现在开始，请存活玩家决定是否参选。"
    elif action_type == "judge_public_discussion_opening":
        round_no = _positive_int(context.get("round_no"), "round_no")
        variables = {"round_no": round_no}
        text = f"第{round_no}天白天讨论现在开始，请存活玩家按照发言顺序依次发言。"
    elif action_type == "judge_exile_result":
        player_seat = _positive_int(context.get("player_seat"), "player_seat")
        outcome = _required_text(context.get("outcome"), "outcome")
        variables = {"player_seat": player_seat, "outcome": outcome}
        text = (
            f"{player_seat}号在放逐投票中翻开白痴身份，免于出局。"
            if outcome == "idiot_revealed"
            else f"{player_seat}号被投票放逐出局。"
        )
    elif action_type == "judge_hunter_shot_announcement":
        target_seat = _positive_int(
            context.get("target_player_seat"),
            "target_player_seat",
        )
        variables = {"target_player_seat": target_seat}
        text = f"猎人开枪带走了{target_seat}号。"
    elif action_type == "judge_sheriff_badge_result":
        target_seat = _optional_positive_int(context.get("target_player_seat"))
        variables = {"target_player_seat": target_seat}
        text = (
            f"警徽移交给{target_seat}号。"
            if target_seat is not None
            else "警长撕毁警徽，本局不再有警长。"
        )
    elif action_type == "judge_werewolf_self_explosion":
        player_seat = _positive_int(context.get("player_seat"), "player_seat")
        variables = {"player_seat": player_seat}
        text = f"{player_seat}号发动狼人自爆并立即出局，今天剩余流程结束。"
    elif action_type == "judge_sheriff_elected":
        player_seat = _positive_int(context.get("player_seat"), "player_seat")
        variables = {"player_seat": player_seat}
        text = f"{player_seat}号当选警长并获得警徽。"
    elif action_type == "judge_sheriff_badge_destroyed":
        variables = {}
        text = "本次警长竞选没有产生警长，警徽流失。"
    elif action_type == "judge_no_exile":
        variables = {}
        text = "本轮放逐投票没有产生唯一结果，今天无人被放逐。"
    elif action_type == "judge_day_summary":
        round_no = _positive_int(context.get("round_no"), "round_no")
        variables = {"round_no": round_no}
        text = f"第{round_no}天流程结束，即将入夜。"
    elif action_type == "judge_game_completed":
        winner = _required_text(context.get("winner"), "winner")
        winner_name = {
            "villagers": "好人阵营",
            "werewolves": "狼人阵营",
        }.get(winner)
        if winner_name is None:
            raise V2JudgeTemplateError(f"unsupported winner: {winner}")
        variables = {"winner": winner}
        text = f"本局结束，{winner_name}获胜。"
    elif action_type == "werewolf_attack_wake":
        variables = {}
        text = "狼人请睁眼，请依次商议今晚的袭击目标。"
    elif action_type == "werewolf_attack_sleep":
        variables = {}
        text = "狼人行动结束，请闭眼。"
    elif action_type == "guard_protect_wake":
        variables = {}
        text = "守卫请睁眼，请选择今晚要守护的玩家。"
    elif action_type == "guard_protect_sleep":
        variables = {}
        text = "守卫行动结束，请闭眼。"
    elif action_type == "seer_investigate_wake":
        variables = {}
        text = "预言家请睁眼，请选择今晚要查验的玩家。"
    elif action_type == "seer_investigate_result":
        target_seat = _positive_int(
            context.get("target_player_seat"),
            "target_player_seat",
        )
        alignment = _required_text(context.get("alignment"), "alignment")
        alignment_name = {
            "villagers": "好人阵营",
            "werewolves": "狼人阵营",
        }.get(alignment)
        if alignment_name is None:
            raise V2JudgeTemplateError(f"unsupported alignment: {alignment}")
        variables = {
            "target_player_seat": target_seat,
            "alignment": alignment,
        }
        text = f"你查验的{target_seat}号属于{alignment_name}。"
    elif action_type == "seer_investigate_sleep":
        variables = {}
        text = "预言家行动结束，请闭眼。"
    elif action_type == "witch_wake":
        variables = {}
        text = "女巫请睁眼。"
    elif action_type == "witch_attack_observation":
        attacked_seat = _optional_positive_int(context.get("attacked_player_seat"))
        variables = {"attacked_player_seat": attacked_seat}
        text = (
            f"今晚被狼人袭击的是{attacked_seat}号。"
            if attacked_seat is not None
            else "今晚目前没有狼人袭击目标。"
        )
    elif action_type == "witch_sleep":
        variables = {}
        text = "女巫行动结束，请闭眼。"
    else:
        raise V2JudgeTemplateError(f"missing judge template: {action_type}")

    return V2RenderedJudgeSpeech(
        template_id=action_type,
        template_version=1,
        text=text,
        variables=variables,
    )


def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _required_text(value: Any, field: str) -> str:
    text = _optional_text(value)
    if text is None:
        raise V2JudgeTemplateError(f"{field} is required")
    return text


def _optional_text(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _positive_int(value: Any, field: str) -> int:
    result = _optional_int(value)
    if result is None or result < 1:
        raise V2JudgeTemplateError(f"{field} must be a positive integer")
    return result


def _optional_int(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _positive_int_list(value: Any, field: str) -> list[int]:
    if not isinstance(value, list):
        raise V2JudgeTemplateError(f"{field} must be a list")
    return [_positive_int(item, f"{field}[]") for item in value]


def _optional_positive_int(value: Any) -> int | None:
    if value is None:
        return None
    return _positive_int(value, "seat")
