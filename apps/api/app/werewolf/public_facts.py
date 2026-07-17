from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any, Literal


PINNED_CATEGORIES = {
    "claim",
    "sheriff",
    "sheriff_result",
    "death",
    "vote",
    "reveal",
    "interruption",
}
ENGINE_FACT_CATEGORIES = frozenset(
    {"death", "vote", "sheriff", "sheriff_result", "reveal", "interruption"}
)
PLAYER_CLAIM_CATEGORIES = frozenset({"claim", "speech"})
PRIVATE_FACT_CATEGORIES = frozenset({"private_observation", "strategy_note"})
PUBLIC_FACT_CATEGORIES = frozenset(
    {
        "event",
        "death",
        "vote",
        "claim",
        "speech",
        "sheriff",
        "sheriff_result",
        "reveal",
        "interruption",
    }
)
PUBLIC_FACT_SCHEMA_VERSION = 3
FactRetention = Literal["critical", "important", "recent"]
FactTrustClass = Literal["engine_fact", "player_claim", "legacy_unclassified"]
FACT_RETENTION_LEVELS = frozenset({"critical", "important", "recent"})
FACT_TRUST_CLASSES = frozenset(
    {"engine_fact", "player_claim", "legacy_unclassified"}
)
PRIVATE_DETAIL_KEYS = frozenset(
    {
        "known_roles",
        "model_memory",
        "observations",
        "private_observation",
        "private_summaries",
        "prompt",
        "raw_response",
        "reasoning",
        "strategy_note",
        "strategy_notes",
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
    trust_class: FactTrustClass | None = None
    source_opportunity_id: str | None = None
    source_event_id: str | None = None
    details: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.category in PRIVATE_FACT_CATEGORIES:
            raise ValueError(f"Public fact uses private category: {self.category}")
        if self.category not in PUBLIC_FACT_CATEGORIES:
            raise ValueError(f"Unsupported public fact category: {self.category}")
        if self.retention is not None and self.retention not in FACT_RETENTION_LEVELS:
            raise ValueError(f"Unsupported public fact retention: {self.retention}")
        if self.trust_class is not None and self.trust_class not in FACT_TRUST_CLASSES:
            raise ValueError(f"Unsupported public fact trust class: {self.trust_class}")
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

    @property
    def effective_trust_class(self) -> FactTrustClass:
        if self.trust_class == "engine_fact" and self.category not in ENGINE_FACT_CATEGORIES:
            if self.category in PLAYER_CLAIM_CATEGORIES:
                return "player_claim"
            return "legacy_unclassified"
        if self.trust_class is not None:
            return self.trust_class
        if self.category in PLAYER_CLAIM_CATEGORIES:
            return "player_claim"
        if self.category in ENGINE_FACT_CATEGORIES:
            return "engine_fact"
        return "legacy_unclassified"

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
            "trust_class": self.effective_trust_class,
            "source_opportunity_id": self.source_opportunity_id,
            "source_event_id": self.source_event_id,
            "details": copy.deepcopy(self.details),
        }


def public_fact_from_dict(data: dict[str, Any]) -> PublicFact:
    raw_category = data.get("category")
    if raw_category is None or raw_category == "":
        category = "event"
    elif not isinstance(raw_category, str):
        return _redacted_public_fact()
    else:
        category = raw_category
    if category not in PUBLIC_FACT_CATEGORIES:
        return _redacted_public_fact()
    raw_retention = data.get("retention")
    retention: FactRetention | None = None
    if isinstance(raw_retention, str) and raw_retention in FACT_RETENTION_LEVELS:
        retention = raw_retention  # type: ignore[assignment]
    raw_trust_class = data.get("trust_class")
    if raw_trust_class is not None and (
        not isinstance(raw_trust_class, str)
        or raw_trust_class not in FACT_TRUST_CLASSES
    ):
        return _redacted_public_fact()
    trust_class: FactTrustClass = (  # type: ignore[assignment]
        raw_trust_class or "legacy_unclassified"
    )
    details = data.get("details")
    safe_details = copy.deepcopy(details) if isinstance(details, dict) else {}
    if _first_private_detail_key(safe_details) is not None:
        return _redacted_public_fact()
    raw_text = data.get("text")
    return PublicFact(
        round_number=_safe_int(data.get("round_number"), default=0),
        category=category,
        text=raw_text if isinstance(raw_text, str) else "",
        schema_version=_safe_int(data.get("schema_version"), default=1),
        fact_id=_safe_optional_string(data.get("fact_id")) or "",
        stage=_safe_optional_string(data.get("stage")),
        actor=_safe_optional_string(data.get("actor")),
        retention=retention,
        trust_class=trust_class,
        source_opportunity_id=_safe_optional_string(
            data.get("source_opportunity_id")
        ),
        source_event_id=_safe_optional_string(data.get("source_event_id")),
        details=safe_details,
    )


def public_fact_dicts_from_value(
    value: object,
    *,
    include_details: bool = False,
) -> list[dict[str, Any]]:
    """Project stored facts through the public whitelist, dropping unsafe rows."""
    if not isinstance(value, list):
        return []
    result: list[dict[str, Any]] = []
    for item in value:
        if isinstance(item, str):
            fact = PublicFact(
                round_number=0,
                category="event",
                text=item,
                schema_version=1,
                trust_class="legacy_unclassified",
            )
        elif isinstance(item, dict):
            fact = public_fact_from_dict(item)
        else:
            continue
        if not fact.text.strip():
            continue
        payload = fact.to_dict()
        if not include_details:
            payload["details"] = {}
        result.append(payload)
    return result


def _redacted_public_fact() -> PublicFact:
    return PublicFact(
        round_number=0,
        category="event",
        text="",
        schema_version=PUBLIC_FACT_SCHEMA_VERSION,
        trust_class="legacy_unclassified",
    )


def _safe_int(value: object, *, default: int) -> int:
    try:
        return int(value) if value is not None and not isinstance(value, bool) else default
    except (TypeError, ValueError, OverflowError):
        return default


def _safe_optional_string(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


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
    rendered_lines: list[object],
) -> dict[str, Any]:
    critical = [fact for fact in facts if fact.effective_retention == "critical"]
    rendered = {
        text
        for item in rendered_lines
        if (text := _rendered_fact_text(item)) is not None
    }
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
    return [
        _project_fact_text(fact, (budget or PublicFactBudget()).max_fact_chars)
        for fact in _select_compressed_public_facts(
            facts,
            max_lines=max_lines,
            budget=budget,
        )
    ]


def compressed_public_fact_records(
    facts: list[PublicFact],
    *,
    max_lines: int = 18,
    budget: PublicFactBudget | None = None,
) -> list[dict[str, Any]]:
    fact_budget = budget or PublicFactBudget()
    return [
        {
            "round_number": fact.round_number,
            "category": fact.category,
            "trust_class": fact.effective_trust_class,
            "text": _project_fact_text(fact, fact_budget.max_fact_chars),
            "fact_id": fact.fact_id,
            "stage": fact.stage,
            "actor": fact.actor,
            "source_opportunity_id": fact.source_opportunity_id,
            "source_event_id": fact.source_event_id,
        }
        for fact in _select_compressed_public_facts(
            facts,
            max_lines=max_lines,
            budget=fact_budget,
        )
    ]


def _select_compressed_public_facts(
    facts: list[PublicFact],
    *,
    max_lines: int,
    budget: PublicFactBudget | None,
) -> list[PublicFact]:
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
            key = (
                "legacy",
                fact.round_number,
                fact.category,
                fact.effective_trust_class,
                fact.text,
            )
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
    return [fact for _, fact in selected]


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


def _rendered_fact_text(value: object) -> str | None:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        text = value.get("text")
        return str(text) if isinstance(text, str) else None
    return None


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
