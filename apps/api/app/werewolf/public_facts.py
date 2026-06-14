from __future__ import annotations

from dataclasses import dataclass
from typing import Any


PINNED_CATEGORIES = {"claim", "sheriff", "death", "vote", "reveal"}


@dataclass(frozen=True)
class PublicFact:
    round_number: int
    category: str
    text: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "round_number": self.round_number,
            "category": self.category,
            "text": self.text,
        }


def public_fact_from_dict(data: dict[str, Any]) -> PublicFact:
    return PublicFact(
        round_number=int(data.get("round_number") or 0),
        category=str(data.get("category") or "event"),
        text=str(data.get("text") or ""),
    )


def compressed_public_facts(
    facts: list[PublicFact],
    *,
    max_lines: int = 18,
) -> list[str]:
    if max_lines <= 0:
        return []

    pinned = [fact for fact in facts if fact.category in PINNED_CATEGORIES]
    recent = facts[-max_lines:]
    merged: list[PublicFact] = []
    seen: set[tuple[int, str, str]] = set()
    for fact in [*pinned, *recent]:
        key = (fact.round_number, fact.category, fact.text)
        if key in seen or not fact.text:
            continue
        seen.add(key)
        merged.append(fact)
    return [fact.text for fact in merged[-max_lines:]]
