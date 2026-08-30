from __future__ import annotations

from typing import Any


AUDIENCE_CONTRACT_VERSION = 1
V2_EVENT_AUDIENCES = frozenset(
    {
        "all",
        "public",
        "god_view",
        "director",
        "player_private",
    }
)


def model_event_audience(*, action_audience: str, actor_kind: str) -> str:
    """Return the narrow canonical audience for raw model lifecycle events."""
    if action_audience not in V2_EVENT_AUDIENCES:
        raise ValueError(f"unsupported V2 record event audience: {action_audience!r}")
    if action_audience not in {"all", "public"}:
        return action_audience
    return "player_private" if actor_kind == "player" else "director"


def canonical_event_payload(
    payload: dict[str, Any],
    *,
    audience: str,
) -> dict[str, Any]:
    """Attach the explicit transport audience contract to a new record event."""
    normalized_audience = audience.strip() if isinstance(audience, str) else ""
    if normalized_audience not in V2_EVENT_AUDIENCES:
        raise ValueError(f"unsupported V2 record event audience: {audience!r}")
    if normalized_audience != audience:
        raise ValueError("V2 record event audience must already be canonical")
    if "audience" in payload or "audience_contract_version" in payload:
        raise ValueError("V2 record event audience metadata must be supplied separately")
    return {
        **payload,
        "audience": normalized_audience,
        "audience_contract_version": AUDIENCE_CONTRACT_VERSION,
    }
