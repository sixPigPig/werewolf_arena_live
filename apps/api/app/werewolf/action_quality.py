from __future__ import annotations

from app.werewolf.debate_realism import dialogue_quality_warnings


def action_quality_warnings(
    *,
    action: str,
    text: str,
    actor: str | None = None,
    endgame: bool = False,
    prior_texts: list[str] | tuple[str, ...] = (),
    personality: str = "",
    eligibility: dict[str, object] | None = None,
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

    if eligibility is not None:
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

    if ("查杀" in normalized and "好人" in normalized) or (
        "金水" in normalized and "狼人" in normalized
    ):
        warnings.append("role_term_contradiction")

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
            personality=personality,
        ):
            if warning not in warnings:
                warnings.append(warning)

    return warnings
