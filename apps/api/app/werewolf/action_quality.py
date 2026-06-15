from __future__ import annotations


def action_quality_warnings(
    *,
    action: str,
    text: str,
    actor: str | None = None,
    endgame: bool = False,
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

    if endgame and action == "debate":
        mentions_tomorrow = "明天再" in normalized or "下一轮" in normalized
        mentions_pressure = (
            "不能出错" in normalized
            or "直接输" in normalized
            or "轮次" in normalized
        )
        if mentions_tomorrow and not mentions_pressure:
            warnings.append("endgame_tomorrow_without_pressure")

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

    return warnings
