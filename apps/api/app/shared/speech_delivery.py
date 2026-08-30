from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any


DELIVERY_SCHEMA_VERSION = 1
DELIVERY_MAPPING_VERSION = "delivery-v1"
AFFECT_DELIVERY_MAPPING_VERSION = "affect-delivery-v2"
DELIVERY_MOODS = frozenset(
    {
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
    }
)
DELIVERY_INTENSITIES = frozenset({"low", "medium", "high"})
DELIVERY_PACES = frozenset({"slow", "natural", "fast"})

_MOOD_TEXT = {
    "neutral": "自然",
    "restrained": "克制",
    "calm": "克制平静",
    "confident": "坚定自信",
    "skeptical": "带有质疑",
    "tense": "略显紧张",
    "frustrated": "带有不满",
    "urgent": "急切但清晰",
    "sad": "低落克制",
    "excited": "情绪高涨",
    "playful": "轻松灵动",
}
_INTENSITY_TEXT = {"low": "收敛", "medium": "适中", "high": "明显"}
_PACE_TEXT = {"slow": "稍慢", "natural": "自然", "fast": "稍快"}
_DIALECT_TEXT = {
    "sichuan": "四川话",
    "shaanxi": "陕西话",
    "northeast": "东北话",
}
_ALLOWED_INSTRUCTION_CUES = (
    "克制",
    "平静",
    "坚定",
    "自信",
    "质疑",
    "犹豫",
    "紧张",
    "激动",
    "悲伤",
    "低落",
    "轻松",
    "自然",
    "低沉",
    "果断",
    "不满",
    "急切",
    "急促",
    "停顿",
    "反问",
    "短句",
    "清晰",
)
_PRIVATE_OR_FACT_RE = re.compile(
    r"\d|号|玩家|狼人|好人|村民|预言家|女巫|猎人|守卫|白痴|"
    r"查验|刀口|毒药|解药|守护|身份|阵营|投票|出局|死亡|自爆|reasoning",
    re.IGNORECASE,
)


def normalize_delivery(
    value: object,
    *,
    base_mood: str = "neutral",
    base_intensity: str = "medium",
    base_pace: str = "natural",
    base_instruction: str = "",
) -> dict[str, Any]:
    """Return a bounded delivery value without copying model facts into TTS."""

    source = value if isinstance(value, Mapping) else {}
    mood = _enum_value(source.get("mood"), DELIVERY_MOODS, base_mood, "neutral")
    intensity = _enum_value(
        source.get("intensity"),
        DELIVERY_INTENSITIES,
        base_intensity,
        "medium",
    )
    pace = _enum_value(source.get("pace"), DELIVERY_PACES, base_pace, "natural")
    instruction = _safe_instruction(source.get("instruction"))
    if not instruction:
        instruction = _safe_instruction(base_instruction)
    return {
        "schema_version": DELIVERY_SCHEMA_VERSION,
        "mood": mood,
        "intensity": intensity,
        "pace": pace,
        "instruction": instruction,
    }


def compile_context_texts(
    delivery: Mapping[str, object] | None,
    *,
    dialect: str = "",
) -> list[str]:
    normalized = normalize_delivery(delivery or {})
    mood = _MOOD_TEXT[str(normalized["mood"])]
    intensity = _INTENSITY_TEXT[str(normalized["intensity"])]
    pace = _PACE_TEXT[str(normalized["pace"])]
    instruction = str(normalized.get("instruction") or "")
    extra = f"；演绎提示为{instruction}" if instruction else ""
    dialect_text = _DIALECT_TEXT.get(dialect.strip().lower(), "")
    dialect_instruction = f"；使用{dialect_text}自然表达" if dialect_text else ""
    return [
        "像真人在狼人杀现场自然接话，不要使用播音腔。"
        f"情绪{mood}；表达力度{intensity}；语速{pace}{dialect_instruction}{extra}。"
    ]


def delivery_from_result(
    result: Mapping[str, object] | None,
    *,
    base_mood: str = "neutral",
    base_intensity: str = "medium",
    base_pace: str = "natural",
    base_instruction: str = "",
) -> dict[str, Any]:
    return normalize_delivery(
        result.get("delivery") if result is not None else None,
        base_mood=base_mood,
        base_intensity=base_intensity,
        base_pace=base_pace,
        base_instruction=base_instruction,
    )


def compile_affect_delivery_v2(
    *,
    base_mood: str,
    base_intensity: str,
    base_pace: str,
    base_instruction: str,
    public_affect: Mapping[str, object] | None,
    speech_act: str | None,
    phase: str,
    previous_delivery: Mapping[str, object] | None = None,
) -> dict[str, Any]:
    """Compile bounded delivery from public affect without model-authored facts."""

    affect = public_affect if isinstance(public_affect, Mapping) else {}
    mood = _enum_value(affect.get("mood"), DELIVERY_MOODS, base_mood, "neutral")
    intensity = _enum_value(
        affect.get("intensity"),
        DELIVERY_INTENSITIES,
        base_intensity,
        "medium",
    )
    pace = _enum_value(affect.get("pace"), DELIVERY_PACES, base_pace, "natural")
    normalized_act = speech_act.strip().lower() if isinstance(speech_act, str) else ""
    if normalized_act in {"challenge", "accuse", "defend", "correct"}:
        if intensity == "low":
            intensity = "medium"
        if mood in {"neutral", "calm", "restrained"}:
            mood = "skeptical" if normalized_act in {"challenge", "correct"} else "tense"
    if phase in {"exile_last_words", "hunter_shoot"} and pace == "fast":
        pace = "natural"

    previous = normalize_delivery(previous_delivery or {}) if previous_delivery else None
    if previous is not None:
        if previous["intensity"] == "low" and intensity == "high":
            intensity = "medium"
        if previous["pace"] == "slow" and pace == "fast":
            pace = "natural"

    return normalize_delivery(
        {
            "mood": mood,
            "intensity": intensity,
            "pace": pace,
        },
        base_mood=base_mood,
        base_intensity=base_intensity,
        base_pace=base_pace,
        base_instruction=base_instruction,
    )


def _enum_value(
    value: object,
    allowed: frozenset[str],
    fallback: str,
    default: str,
) -> str:
    candidate = str(value).strip().lower() if isinstance(value, str) else ""
    if candidate in allowed:
        return candidate
    normalized_fallback = fallback.strip().lower() if isinstance(fallback, str) else ""
    return normalized_fallback if normalized_fallback in allowed else default


def _safe_instruction(value: object) -> str:
    if not isinstance(value, str):
        return ""
    compact = " ".join(value.strip().split())[:120]
    if not compact or _PRIVATE_OR_FACT_RE.search(compact):
        return ""
    cues = [cue for cue in _ALLOWED_INSTRUCTION_CUES if cue in compact]
    return "、".join(dict.fromkeys(cues))
