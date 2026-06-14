from __future__ import annotations


def action_quality_warnings(
    *,
    action: str,
    text: str,
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

    return warnings
