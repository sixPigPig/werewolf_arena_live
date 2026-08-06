from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.v2.models import V2GameRecordEvent, V2KnowledgeFact


_KNOWLEDGE_EVENT_TYPES = frozenset(
    {
        "ability_activation_completed",
        "private_knowledge_recorded",
        "hunter_response_resolved",
    }
)


def player_private_knowledge(
    db: Session,
    *,
    game_id: str,
    player_id: str,
) -> list[dict[str, Any]]:
    rows = list(
        db.scalars(
            select(V2KnowledgeFact)
            .where(
                V2KnowledgeFact.game_id == game_id,
                V2KnowledgeFact.owner_scope == "player",
                V2KnowledgeFact.owner_id == player_id,
                V2KnowledgeFact.fact_type != "action_context_projection",
            )
            .order_by(V2KnowledgeFact.created_at, V2KnowledgeFact.knowledge_fact_id)
        )
    )
    if not rows:
        return []

    events = list(
        db.scalars(
            select(V2GameRecordEvent)
            .where(
                V2GameRecordEvent.game_id == game_id,
                V2GameRecordEvent.event_type.in_(_KNOWLEDGE_EVENT_TYPES),
            )
            .order_by(V2GameRecordEvent.record_seq)
        )
    )
    event_by_fact_id: dict[str, V2GameRecordEvent] = {}
    event_by_activation_id: dict[str, V2GameRecordEvent] = {}
    for event in events:
        payload = event.payload if isinstance(event.payload, dict) else {}
        activation_id = payload.get("activation_id")
        if isinstance(activation_id, str):
            event_by_activation_id[activation_id] = event
        fact_ids = payload.get("knowledge_fact_ids")
        if isinstance(fact_ids, list):
            for fact_id in fact_ids:
                if isinstance(fact_id, str):
                    event_by_fact_id[fact_id] = event
        fact_id = payload.get("knowledge_fact_id")
        if isinstance(fact_id, str):
            event_by_fact_id[fact_id] = event

    projected: list[dict[str, Any]] = []
    for row in rows:
        event = event_by_fact_id.get(row.knowledge_fact_id)
        if event is None and row.source_activation_id is not None:
            event = event_by_activation_id.get(row.source_activation_id)
        payload = dict(row.payload or {})
        occurred_in = _occurred_in(row.fact_type, payload)
        projected.append(
            {
                "knowledge_fact_id": row.knowledge_fact_id,
                "source_activation_id": row.source_activation_id,
                "fact_type": row.fact_type,
                "payload": payload,
                **(
                    {"authority": "actor_memory"} if row.fact_type == "private_round_memory" else {}
                ),
                **(
                    {
                        "source_event_id": event.event_id,
                        "source_event_type": event.event_type,
                        "record_seq": event.record_seq,
                        "known_at_seq": event.record_seq,
                    }
                    if event is not None
                    else {}
                ),
                **({"occurred_in": occurred_in} if occurred_in is not None else {}),
            }
        )
    return projected


def _occurred_in(fact_type: str, payload: dict[str, Any]) -> dict[str, Any] | None:
    night_no = _positive_int(payload.get("night_no"))
    if night_no is not None:
        return {"period": "night", "round_no": night_no}
    round_no = _positive_int(payload.get("round_no"))
    if round_no is not None:
        period = (
            "day"
            if fact_type in {"private_ability_action_committed", "private_round_memory"}
            else "unknown"
        )
        return {"period": period, "round_no": round_no}
    return None


def _positive_int(value: Any) -> int | None:
    if isinstance(value, int) and not isinstance(value, bool) and value > 0:
        return value
    return None


__all__ = ["player_private_knowledge"]
