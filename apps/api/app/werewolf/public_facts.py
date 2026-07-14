from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any, Literal


PINNED_CATEGORIES = {"claim", "sheriff", "death", "vote", "reveal", "interruption"}
PUBLIC_FACT_SCHEMA_VERSION = 3
FactRetention = Literal["critical", "important", "recent"]
FACT_RETENTION_LEVELS = frozenset({"critical", "important", "recent"})
PRIVATE_DETAIL_KEYS = frozenset(
    {
        "known_roles",
        "observations",
        "private_observation",
        "private_summaries",
        "prompt",
        "raw_response",
        "reasoning",
    }
)


@dataclass(frozen=True)
class PublicFactBudget:
    max_total_chars: int = 6000
    critical_chars: int = 3600
    important_chars: int = 1600
    recent_chars: int = 800
    max_fact_chars: int = 360


@dataclass(frozen=True)
class PublicFact:
    round_number: int
    category: str
    text: str
    schema_version: int = PUBLIC_FACT_SCHEMA_VERSION
    fact_id: str = ""
    stage: str | None = None
    actor: str | None = None
    retention: FactRetention | None = None
    source_opportunity_id: str | None = None
    details: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.retention is not None and self.retention not in FACT_RETENTION_LEVELS:
            raise ValueError(f"Unsupported public fact retention: {self.retention}")
        private_key = _first_private_detail_key(self.details)
        if private_key is not None:
            raise ValueError(f"Public fact details contain private key: {private_key}")

    @property
    def effective_retention(self) -> FactRetention:
        if self.retention is not None:
            return self.retention
        if self.category in PINNED_CATEGORIES:
            return "important"
        return "recent"

    def to_dict(self) -> dict[str, Any]:
        return {
            "round_number": self.round_number,
            "category": self.category,
            "text": self.text,
            "schema_version": self.schema_version,
            "fact_id": self.fact_id,
            "stage": self.stage,
            "actor": self.actor,
            "retention": self.effective_retention,
            "source_opportunity_id": self.source_opportunity_id,
            "details": copy.deepcopy(self.details),
        }


def public_fact_from_dict(data: dict[str, Any]) -> PublicFact:
    category = str(data.get("category") or "event")
    raw_retention = data.get("retention")
    retention: FactRetention | None = None
    if isinstance(raw_retention, str) and raw_retention in FACT_RETENTION_LEVELS:
        retention = raw_retention  # type: ignore[assignment]
    details = data.get("details")
    return PublicFact(
        round_number=int(data.get("round_number") or 0),
        category=category,
        text=str(data.get("text") or ""),
        schema_version=int(data.get("schema_version") or 1),
        fact_id=str(data.get("fact_id") or ""),
        stage=str(data["stage"]) if data.get("stage") is not None else None,
        actor=str(data["actor"]) if data.get("actor") is not None else None,
        retention=retention,
        source_opportunity_id=(
            str(data["source_opportunity_id"])
            if data.get("source_opportunity_id") is not None
            else None
        ),
        details=copy.deepcopy(details) if isinstance(details, dict) else {},
    )


@dataclass(frozen=True)
class PublicFactOpportunityV1:
    opportunity_id: str
    round_number: int
    stage: str
    category: str
    retention: FactRetention
    status: Literal["expected", "recorded", "superseded", "not_applicable"]
    fact_id: str | None = None
    reason_code: str | None = None
    schema_version: int = 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "opportunity_id": self.opportunity_id,
            "round_number": self.round_number,
            "stage": self.stage,
            "category": self.category,
            "retention": self.retention,
            "status": self.status,
            "fact_id": self.fact_id,
            "reason_code": self.reason_code,
        }


def fact_prompt_coverage(
    facts: list[PublicFact],
    rendered_lines: list[str],
) -> dict[str, Any]:
    critical = [fact for fact in facts if fact.effective_retention == "critical"]
    rendered = set(rendered_lines)
    included = [
        fact
        for fact in critical
        if _project_fact_text(fact, PublicFactBudget().max_fact_chars) in rendered
    ]
    missing = [fact for fact in critical if fact not in included]
    return {
        "schema_version": 1,
        "expected_critical_count": len(critical),
        "included_critical_count": len(included),
        "missing_critical_count": len(missing),
        "coverage_status": "available",
        "missing_reason_counts": ({"assembly_error": len(missing)} if missing else {}),
    }


def compressed_public_facts(
    facts: list[PublicFact],
    *,
    max_lines: int = 18,
    budget: PublicFactBudget | None = None,
) -> list[str]:
    if max_lines <= 0:
        return []

    fact_budget = budget or PublicFactBudget()
    unique_facts: list[tuple[int, PublicFact]] = []
    seen: set[tuple[object, ...]] = set()
    for index, fact in enumerate(facts):
        key: tuple[object, ...]
        if fact.fact_id:
            key = ("fact_id", fact.fact_id)
        else:
            key = ("legacy", fact.round_number, fact.category, fact.text)
        if key in seen or not fact.text.strip():
            continue
        seen.add(key)
        unique_facts.append((index, fact))

    critical = [item for item in unique_facts if item[1].effective_retention == "critical"]
    important = [item for item in unique_facts if item[1].effective_retention == "important"]
    recent = [item for item in unique_facts if item[1].effective_retention == "recent"]

    selected = critical.copy()
    remaining_lines = max(0, max_lines - len(selected))
    used_chars = sum(
        len(_project_fact_text(fact, fact_budget.max_fact_chars)) for _, fact in selected
    )
    selected.extend(
        _select_latest_with_budget(
            important,
            max_items=remaining_lines,
            max_chars=min(
                fact_budget.important_chars,
                max(0, fact_budget.max_total_chars - used_chars),
            ),
            max_fact_chars=fact_budget.max_fact_chars,
        )
    )
    remaining_lines = max(0, max_lines - len(selected))
    used_chars = sum(
        len(_project_fact_text(fact, fact_budget.max_fact_chars)) for _, fact in selected
    )
    selected.extend(
        _select_latest_with_budget(
            recent,
            max_items=remaining_lines,
            max_chars=min(
                fact_budget.recent_chars,
                max(0, fact_budget.max_total_chars - used_chars),
            ),
            max_fact_chars=fact_budget.max_fact_chars,
        )
    )
    selected.sort(key=lambda item: item[0])
    return [_project_fact_text(fact, fact_budget.max_fact_chars) for _, fact in selected]


def _select_latest_with_budget(
    facts: list[tuple[int, PublicFact]],
    *,
    max_items: int,
    max_chars: int,
    max_fact_chars: int,
) -> list[tuple[int, PublicFact]]:
    if max_items <= 0 or max_chars <= 0:
        return []
    selected: list[tuple[int, PublicFact]] = []
    used_chars = 0
    for item in reversed(facts):
        text_length = len(_project_fact_text(item[1], max_fact_chars))
        if selected and used_chars + text_length > max_chars:
            continue
        if not selected and text_length > max_chars:
            selected.append(item)
            break
        selected.append(item)
        used_chars += text_length
        if len(selected) >= max_items:
            break
    return selected


def _project_fact_text(fact: PublicFact, max_chars: int) -> str:
    text = fact.text.strip()
    if max_chars <= 0 or len(text) <= max_chars:
        return text
    if max_chars == 1:
        return "…"
    return text[: max_chars - 1].rstrip() + "…"


def _first_private_detail_key(value: object) -> str | None:
    if isinstance(value, dict):
        for key, nested_value in value.items():
            normalized_key = str(key).lower()
            if normalized_key in PRIVATE_DETAIL_KEYS:
                return str(key)
            nested_key = _first_private_detail_key(nested_value)
            if nested_key is not None:
                return nested_key
    elif isinstance(value, list):
        for nested_value in value:
            nested_key = _first_private_detail_key(nested_value)
            if nested_key is not None:
                return nested_key
    return None
