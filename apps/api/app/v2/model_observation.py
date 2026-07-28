from __future__ import annotations

import re
from typing import Any


_NEGATION_OR_REJECTION = re.compile(
    r"(?:没有|不存在|不是|并非|不可能|不能|不该|不成立|不符合|错误|矛盾|别盘|不能盘)"
)
_DOUBLE_WOLF_MARKER = re.compile(r"(?:双狼|两狼|两匹狼|两头狼|两张狼牌|两张狼人牌)")
_WOLF_TEAMMATE_MARKER = re.compile(r"狼队友")
_EXPLICIT_WOLF_PAIR = re.compile(
    r"(?:狼(?:就)?是\s*)"
    r"(?P<first>[1-9]|1[0-9]|2[0-4])号?"
    r"\s*(?:、|和|与|跟)\s*"
    r"(?P<second>[1-9]|1[0-9]|2[0-4])号?"
)


def observe_model_speech(
    speech: str | None,
    *,
    hard_rules: dict[str, Any],
) -> list[dict[str, Any]]:
    """Return passive diagnostics without changing or rejecting model output."""

    if not isinstance(speech, str) or not speech.strip():
        return []
    werewolf_count = hard_rules.get("werewolf_count")
    if werewolf_count != 1:
        return []

    signals: list[dict[str, Any]] = []
    for signal, confidence, pattern in (
        ("double_wolf_marker", "high", _DOUBLE_WOLF_MARKER),
        ("wolf_teammate_marker", "medium", _WOLF_TEAMMATE_MARKER),
        ("explicit_wolf_pair", "high", _EXPLICIT_WOLF_PAIR),
    ):
        for match in pattern.finditer(speech):
            if _is_rejected_claim(speech, start=match.start(), end=match.end()):
                continue
            signals.append(
                {
                    "signal": signal,
                    "confidence": confidence,
                    "evidence": _evidence(speech, start=match.start(), end=match.end()),
                }
            )
            break

    if not signals:
        return []
    confidence = "high" if any(item["confidence"] == "high" for item in signals) else "medium"
    return [
        {
            "code": "wolf_cardinality_contradiction",
            "severity": "warning",
            "confidence": confidence,
            "detector_version": 1,
            "configured_werewolf_count": 1,
            "signals": signals,
            "effect": "observed_only",
        }
    ]


def _is_rejected_claim(speech: str, *, start: int, end: int) -> bool:
    before = speech[max(0, start - 8) : start]
    after = speech[end : min(len(speech), end + 18)]
    return (
        _NEGATION_OR_REJECTION.search(before) is not None
        or _NEGATION_OR_REJECTION.search(after) is not None
    )


def _evidence(speech: str, *, start: int, end: int) -> str:
    return speech[max(0, start - 24) : min(len(speech), end + 24)].strip()


__all__ = ["observe_model_speech"]
