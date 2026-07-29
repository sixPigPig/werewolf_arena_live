from __future__ import annotations

import re

from app.werewolf.debate_realism import (
    contradictory_role_targets,
    dialogue_quality_warnings,
)


_SEER_SELF_CLAIM_RE = re.compile(
    r"(?:我(?:是|跳|拿的(?:是)?|这张牌是)一?张?预言家(?:牌)?|"
    r"(?:^|[。！？；\n])\s*(?:\d{1,2}号(?:玩家)?[，,:：]?\s*)?预言家(?:牌)?(?:[，。,:：]|$))"
)
_NON_SEER_SELF_CLAIM_RE = re.compile(
    r"(?:我(?:是|跳|拿的(?:是)?|这张牌是|身份是?)一?张?"
    r"(?:村民|平民|女巫|猎人|白痴|守卫|狼人)(?:牌)?|"
    r"(?:^|[。！？；\n])\s*(?:\d{1,2}号(?:玩家)?[，,:：]?\s*)"
    r"(?:身份(?:是)?[，,:：]?\s*)?"
    r"(?:村民|平民|女巫|猎人|白痴|守卫|狼人)(?:牌)?(?:[，。,:：]|$))"
)
_FUTURE_INVESTIGATION_RE = re.compile(
    r"(?:先|再|今晚|今夜|明晚|下一晚|优先|暂定|计划|准备|会|要)"
    r"[^。！？；\n]{0,10}(?:查验|验(?:警上|警下|(?:玩家)?\d{1,2}号))"
)
_OTHER_BADGE_FLOW_OWNER_RE = re.compile(
    r"(?:\d{1,2}号(?:玩家)?|你|他|她)(?:自己)?(?:刚才|提出|说)?的?$"
)
_SHERIFF_ELECTION_SPEECH_ACTIONS = frozenset(
    {"sheriff_speech", "sheriff_pk_speech"}
)
_FUTURE_HUNTER_SHOT_RE = re.compile(
    r"(?:今晚|今夜|明晚|下一晚|下一夜|下个夜晚|明天晚上)"
    r"[^。！？；\n]{0,16}(?:开枪|带走|崩|枪)"
)
_FUTURE_STAGE_RE = re.compile(r"明天|下一轮|下一夜|下一晚|明晚|下个夜晚")
_NEGATED_FUTURE_STAGE_RE = re.compile(
    r"(?:没有|不存在|不会有|不再有|不一定有)(?:明天|下一轮|下一夜|下一晚|明晚|下个夜晚)"
)
_FUTURE_ACTION_RE = re.compile(
    r"(?:明天|下一轮|下一夜|下一晚|明晚|下个夜晚)"
    r"[^。！？；\n]{0,20}(?:投|票|查验|验人|开枪|带走|用药|毒|救|发言|解释|守护|保护)"
)
DETERMINISTIC_HARD_RULE_CODES = frozenset(
    {
        "hunter_claims_voluntary_future_shot",
        "claims_future_round_after_terminal",
        "claims_illegal_post_death_action",
    }
)


def _has_self_investigation_plan(text: str) -> bool:
    normalized = text.replace(" ", "")
    if re.search(
        r"我(?:今晚|今夜|明晚|下一晚|先|再|准备|计划|会|要|优先)"
        r"[^。！？；\n]{0,12}(?:查验|验(?:警上|警下|(?:玩家)?\d{1,2}号))",
        normalized,
    ):
        return True
    for segment in re.split(r"[。！？；\n]", normalized):
        if "警徽流" not in segment or not _FUTURE_INVESTIGATION_RE.search(segment):
            continue
        owner_prefix = segment.split("警徽流", 1)[0][-16:]
        if "我的" not in owner_prefix and _OTHER_BADGE_FLOW_OWNER_RE.search(owner_prefix):
            continue
        return True
    return False


def action_quality_warnings(
    *,
    action: str,
    text: str,
    actor: str | None = None,
    endgame: bool = False,
    prior_texts: list[str] | tuple[str, ...] = (),
    eligibility: dict[str, object] | None = None,
    role: str = "",
    hard_state: dict[str, object] | None = None,
) -> list[str]:
    warnings: list[str] = []
    normalized = text.replace(" ", "")

    if action == "sheriff_speech" and "退水" in normalized:
        warnings.append("sheriff_speech_mentions_withdraw")

    if action == "sheriff_speech":
        recognizes_other = "认" in normalized and "真预" in normalized
        asks_badge_for_self = "警徽投给我" in normalized or "把警徽投给我" in normalized
        if recognizes_other and asks_badge_for_self:
            warnings.append("sheriff_speech_conflicting_badge_goal")

        if _has_self_investigation_plan(text):
            claims_seer = _SEER_SELF_CLAIM_RE.search(text) is not None
            claims_non_seer = _NON_SEER_SELF_CLAIM_RE.search(text) is not None
            if claims_non_seer or (role != "预言家" and not claims_seer):
                warnings.append("sheriff_speech_investigation_plan_without_seer_claim")

    if eligibility is not None and action in _SHERIFF_ELECTION_SPEECH_ACTIONS:
        original_voters = eligibility.get("original_voters")
        no_sheriff_voters = isinstance(original_voters, list) and not original_voters
        appeals_for_sheriff_vote = "警下" in normalized and any(
            phrase in normalized for phrase in ("投票", "上票", "票投", "给我票")
        )
        if no_sheriff_voters and appeals_for_sheriff_vote:
            warnings.append("appeals_to_missing_sheriff_voters")

        promises_own_vote = any(
            phrase in normalized for phrase in ("我会投", "我投给", "我的票", "我这一票")
        )
        if eligibility.get("actor_can_sheriff_vote") is False and promises_own_vote:
            warnings.append("promises_ineligible_sheriff_vote")

    if endgame and action == "debate":
        mentions_tomorrow = any(
            phrase in normalized for phrase in ("明天", "下一轮", "下一夜")
        )
        mentions_pressure = (
            "不能出错" in normalized
            or "直接输" in normalized
            or "直接结束" in normalized
            or "可能结束" in normalized
            or "没有明天" in normalized
            or "不一定有明天" in normalized
            or "终局" in normalized
            or "生死局" in normalized
        )
        if mentions_tomorrow and not mentions_pressure:
            warnings.append("endgame_tomorrow_without_pressure")
            warnings.append("assumes_future_round_in_endgame")
            warnings.append("ignores_terminal_risk")

    if contradictory_role_targets(text):
        warnings.append("role_term_contradiction")

    hard_state = hard_state if isinstance(hard_state, dict) else {}
    if (
        role == "猎人"
        and hard_state.get("hunter_death_trigger_active") is not True
        and _FUTURE_HUNTER_SHOT_RE.search(normalized) is not None
    ):
        warnings.append("hunter_claims_voluntary_future_shot")

    if (
        hard_state.get("terminal_after_current_action") is True
        and _claims_future_action(normalized)
    ):
        warnings.append("claims_future_round_after_terminal")

    if (
        hard_state.get("actor_alive") is False
        and action != "hunter_shoot"
        and _claims_future_action(normalized)
    ):
        warnings.append("claims_illegal_post_death_action")

    if actor:
        actor_number = actor.replace("玩家", "")
        aliases = [actor_number]
        bare_number = actor_number.replace("号", "")
        if bare_number != actor_number:
            aliases.append(bare_number)
        group_patterns = [
            pattern
            for alias in aliases
            for pattern in (f"{alias}、", f"、{alias}", f"{alias}和")
        ]
        if any(pattern in normalized for pattern in group_patterns) and (
            "后置位" in normalized or "他们" in normalized or "范围" in normalized
        ):
            warnings.append("self_reference_as_group")

    if action == "debate":
        for warning in dialogue_quality_warnings(
            text=text,
            prior_texts=prior_texts,
        ):
            if warning not in warnings:
                warnings.append(warning)

    return warnings


def _claims_future_action(text: str) -> bool:
    without_negated_markers = _NEGATED_FUTURE_STAGE_RE.sub("", text)
    return (
        _FUTURE_STAGE_RE.search(without_negated_markers) is not None
        and _FUTURE_ACTION_RE.search(without_negated_markers) is not None
    )
