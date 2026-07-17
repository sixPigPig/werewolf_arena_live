from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections.abc import Mapping, Sequence
from typing import Literal, TypedDict, cast


SelfExplosionBenefitType = Literal[
    "immediate_win",
    "secure_badge_denial",
    "protect_last_hidden_wolf",
    "deny_confirmed_public_information",
    "force_valuable_night",
    "none",
]
SelfExplosionExecutionStatus = Literal[
    "completed",
    "timed_out",
    "fallback",
    "canceled",
    "failed",
    "expired",
    "superseded",
]
SelfExplosionDecisionSchema = Literal["v2", "legacy"]


class SelfExplosionAuditPayload(TypedDict):
    decision_schema: SelfExplosionDecisionSchema
    window_id: str | None
    execution_status: SelfExplosionExecutionStatus | None
    duration_ms: int | None
    benefit_type: SelfExplosionBenefitType | None


CURRENT_SELF_EXPLOSION_DECISION_SCHEMA: Literal["v2"] = "v2"
SELF_EXPLOSION_BENEFIT_TYPES = frozenset(
    {
        "immediate_win",
        "secure_badge_denial",
        "protect_last_hidden_wolf",
        "deny_confirmed_public_information",
        "force_valuable_night",
        "none",
    }
)
SELF_EXPLOSION_EXECUTION_STATUSES = frozenset(
    {
        "completed",
        "timed_out",
        "fallback",
        "canceled",
        "failed",
        "expired",
        "superseded",
    }
)

_BENEFIT_ALIASES: dict[str, SelfExplosionBenefitType] = {
    "instant_win": "immediate_win",
    "win_immediately": "immediate_win",
    "direct_win": "immediate_win",
    "立即获胜": "immediate_win",
    "立即胜利": "immediate_win",
    "直接获胜": "immediate_win",
    "badge_denial": "secure_badge_denial",
    "deny_badge": "secure_badge_denial",
    "swallow_badge": "secure_badge_denial",
    "吞警徽": "secure_badge_denial",
    "吞掉警徽": "secure_badge_denial",
    "阻止警徽产生": "secure_badge_denial",
    "protect_last_wolf": "protect_last_hidden_wolf",
    "save_last_wolf": "protect_last_hidden_wolf",
    "保护最后一狼": "protect_last_hidden_wolf",
    "保护最后隐狼": "protect_last_hidden_wolf",
    "deny_public_information": "deny_confirmed_public_information",
    "block_public_information": "deny_confirmed_public_information",
    "阻断公开信息": "deny_confirmed_public_information",
    "阻止公开信息": "deny_confirmed_public_information",
    "force_night": "force_valuable_night",
    "enter_night": "force_valuable_night",
    "强制进入夜晚": "force_valuable_night",
    "直接进入夜晚": "force_valuable_night",
    "no_benefit": "none",
    "no_gain": "none",
    "无收益": "none",
    "没有收益": "none",
}
_TOKEN_SEPARATOR = re.compile(r"[\s_\-‐‑‒–—―]+")
_WINDOW_COMPONENT_UNSAFE = re.compile(r"[^a-z0-9]+")
_WINDOW_ID = re.compile(r"^r[1-9]\d*:self-explosion:[a-z0-9-]{1,32}:[a-z0-9-]{1,32}:[0-9a-f]{12}$")


def normalize_self_explosion_benefit_type(
    value: object,
) -> SelfExplosionBenefitType | None:
    """Return a bounded benefit label without echoing unknown model output."""
    token = _normalized_token(value)
    if token is None:
        return None
    if token in SELF_EXPLOSION_BENEFIT_TYPES:
        return cast(SelfExplosionBenefitType, token)
    alias = _BENEFIT_ALIASES.get(token)
    if alias is not None:
        return alias
    return _BENEFIT_ALIASES.get(token.replace("_", ""))


def build_self_explosion_window_id(
    *,
    round_number: int,
    stage: str,
    timing: str,
    ordered_actors: Sequence[str],
    completed_actors: Sequence[str],
    current_actor: str | None,
) -> str:
    """Build a reproducible window id without embedding player identities."""
    if isinstance(round_number, bool) or not isinstance(round_number, int):
        raise TypeError("round_number must be an integer")
    if round_number < 1:
        raise ValueError("round_number must be positive")
    normalized_stage = _required_normalized_text(stage, field="stage")
    normalized_timing = _required_normalized_text(timing, field="timing")
    ordered = _normalized_actor_sequence(ordered_actors, field="ordered_actors")
    completed = _normalized_actor_sequence(
        completed_actors,
        field="completed_actors",
    )
    current = _normalized_current_actor(current_actor)
    digest_source = json.dumps(
        {
            "round": round_number,
            "stage": normalized_stage,
            "timing": normalized_timing,
            "ordered": ordered,
            "completed": completed,
            "current": current,
        },
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    digest = hashlib.sha256(digest_source.encode("utf-8")).hexdigest()[:12]
    stage_component = _window_component(normalized_stage, fallback="stage")
    timing_component = _window_component(normalized_timing, fallback="timing")
    return f"r{round_number}:self-explosion:{stage_component}:{timing_component}:{digest}"


def build_self_explosion_audit_payload(
    *,
    result: Mapping[str, object] | None,
    window_id: object,
    execution_status: object,
    duration_ms: object,
) -> SelfExplosionAuditPayload:
    """Build a provenance-complete, bounded audit record or mark it legacy."""
    benefit_type = normalize_self_explosion_benefit_type(
        result.get("benefit_type") if isinstance(result, Mapping) else None
    )
    safe_window_id = (
        window_id if isinstance(window_id, str) and _WINDOW_ID.fullmatch(window_id) else None
    )
    status_token = _normalized_token(execution_status)
    safe_execution_status = (
        cast(SelfExplosionExecutionStatus, status_token)
        if status_token in SELF_EXPLOSION_EXECUTION_STATUSES
        else None
    )
    safe_duration_ms = (
        duration_ms
        if isinstance(duration_ms, int) and not isinstance(duration_ms, bool) and duration_ms >= 0
        else None
    )
    response_is_complete = isinstance(result, Mapping) and all(
        _is_non_empty_string(result.get(field)) for field in ("expected_gain", "primary_risk")
    )
    is_current = (
        benefit_type is not None
        and safe_window_id is not None
        and safe_execution_status is not None
        and safe_duration_ms is not None
        and response_is_complete
    )
    return {
        "decision_schema": (CURRENT_SELF_EXPLOSION_DECISION_SCHEMA if is_current else "legacy"),
        "window_id": safe_window_id,
        "execution_status": safe_execution_status,
        "duration_ms": safe_duration_ms,
        "benefit_type": benefit_type,
    }


def _normalized_token(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    text = unicodedata.normalize("NFKC", value).strip().casefold()
    if not text:
        return None
    return _TOKEN_SEPARATOR.sub("_", text).strip("_") or None


def _required_normalized_text(value: object, *, field: str) -> str:
    token = _normalized_token(value)
    if token is None:
        raise ValueError(f"{field} must be a non-empty string")
    return token


def _window_component(value: str, *, fallback: str) -> str:
    component = _WINDOW_COMPONENT_UNSAFE.sub("-", value).strip("-")[:32]
    return component or fallback


def _normalized_actor_sequence(
    values: Sequence[str],
    *,
    field: str,
) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)) or not isinstance(values, Sequence):
        raise TypeError(f"{field} must be a sequence of strings")
    normalized: list[str] = []
    for value in values:
        if not isinstance(value, str):
            raise TypeError(f"{field} must contain only strings")
        actor = unicodedata.normalize("NFKC", value).strip()
        if not actor:
            raise ValueError(f"{field} must not contain empty actors")
        normalized.append(actor)
    return tuple(normalized)


def _normalized_current_actor(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError("current_actor must be a string or None")
    actor = unicodedata.normalize("NFKC", value).strip()
    if not actor:
        raise ValueError("current_actor must not be empty")
    return actor


def _is_non_empty_string(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())
