from __future__ import annotations

from app.werewolf.player_presets import default_strategy_text


def compose_player_profile_prompt(profile: object, base_personality: str) -> str:
    sections = [base_personality.strip()]

    short_description = _profile_string(profile, "short_description")
    if short_description:
        sections.append(f"角色简介: {short_description}")

    background_story = _profile_string(profile, "background_story")
    if background_story:
        sections.append(f"背景设定: {background_story}")

    speaking_style = _profile_string(profile, "speaking_style")
    if speaking_style:
        sections.append(f"发言风格: {speaking_style}")

    strategy_profile = _profile_string(profile, "strategy_profile") or "balanced"
    try:
        strategy_text = default_strategy_text(strategy_profile)
    except KeyError:
        strategy_text = default_strategy_text("balanced")
    sections.append(f"狼人杀策略: {strategy_text}")

    for label, field_name in (
        ("冒险倾向", "risk_tolerance"),
        ("伪装倾向", "bluffing_tendency"),
        ("信任倾向", "trust_tendency"),
        ("领导倾向", "leadership_tendency"),
        ("发言活跃", "talkativeness"),
    ):
        sections.append(f"{label}: {_profile_int(profile, field_name)}/5")

    example_messages = _profile_list(profile, "example_messages")
    if example_messages:
        sections.append(f"示例发言: {'；'.join(example_messages)}")

    return "\n".join(section for section in sections if section)


def _profile_string(profile: object, field_name: str) -> str:
    value = getattr(profile, field_name, "")
    return str(value).strip() if value is not None else ""


def _profile_int(profile: object, field_name: str) -> int:
    value = getattr(profile, field_name, 3)
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return 3
    return min(5, max(1, parsed))


def _profile_list(profile: object, field_name: str) -> list[str]:
    value = getattr(profile, field_name, [])
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]
