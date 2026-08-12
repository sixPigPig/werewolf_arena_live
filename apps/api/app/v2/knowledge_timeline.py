from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.v2.models import V2GameRecordEvent, V2KnowledgeFact, V2PreExileResult


_KNOWLEDGE_EVENT_TYPES = frozenset(
    {
        "ability_activation_completed",
        "ability_activation_technical_no_action",
        "private_knowledge_recorded",
        "pre_exile_private_fact_committed",
        "hunter_response_resolved",
    }
)


def player_private_knowledge(
    db: Session,
    *,
    game_id: str,
    player_id: str,
    at_or_before_record_seq: int | None = None,
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

    def event_for_row(row: V2KnowledgeFact) -> V2GameRecordEvent | None:
        event = event_by_fact_id.get(row.knowledge_fact_id)
        if event is None and row.source_activation_id is not None:
            event = event_by_activation_id.get(row.source_activation_id)
        return event

    if at_or_before_record_seq is not None:
        visible_rows: list[V2KnowledgeFact] = []
        for row in rows:
            event = event_for_row(row)
            if event is not None and event.record_seq <= at_or_before_record_seq:
                visible_rows.append(row)
        rows = visible_rows
        if not rows:
            return []

    # Rolling actor memories are append-only durable audit facts, but only the
    # latest snapshot visible at this read cutoff participates in runtime. This
    # ordering matters: a concurrently-created future snapshot must not hide
    # the last snapshot that was valid at the frozen action cutoff.
    latest_memory = max(
        (row for row in rows if row.fact_type == "private_round_memory"),
        key=_private_round_memory_order,
        default=None,
    )
    rows = [
        row
        for row in rows
        if row.fact_type != "private_round_memory" or row is latest_memory
    ]

    provisional_fact_ids = {
        row.knowledge_fact_id for row in rows if _is_pre_exile_provisional_fact(row)
    }
    if provisional_fact_ids:
        committed_fact_ids = set(
            db.scalars(
                select(V2PreExileResult.private_fact_id).where(
                    V2PreExileResult.private_fact_id.in_(provisional_fact_ids),
                    V2PreExileResult.result_kind == "self_explosion",
                    V2PreExileResult.state == "committed",
                )
            )
        )
        rows = [
            row
            for row in rows
            if row.knowledge_fact_id not in provisional_fact_ids
            or row.knowledge_fact_id in committed_fact_ids
        ]
        if not rows:
            return []

    projected: list[dict[str, Any]] = []
    for row in rows:
        event = event_for_row(row)
        if _is_pre_exile_provisional_fact(row) and (
            event is None or event.event_type != "pre_exile_private_fact_committed"
        ):
            continue
        payload = dict(row.payload or {})
        occurred_in = _occurred_in(row.fact_type, payload)
        projected.append(
            {
                "knowledge_fact_id": row.knowledge_fact_id,
                "source_activation_id": row.source_activation_id,
                "owner_scope": row.owner_scope,
                "owner_id": row.owner_id,
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


def _is_pre_exile_provisional_fact(row: V2KnowledgeFact) -> bool:
    payload = row.payload if isinstance(row.payload, dict) else {}
    context = payload.get("context")
    return (
        row.fact_type == "private_action_decision"
        and payload.get("action_type") == "werewolf_self_explosion"
        and isinstance(context, dict)
        and isinstance(context.get("pipeline_id"), str)
        and context.get("visibility_mode") == "pre_exile_provisional_until_atomic_arbiter"
    )


def _private_round_memory_order(row: V2KnowledgeFact) -> tuple[int, int, str]:
    payload = row.payload if isinstance(row.payload, dict) else {}
    round_no = _positive_int(payload.get("round_no")) or 0
    cutoff = _positive_int(payload.get("source_cutoff_record_seq")) or 0
    return (round_no, cutoff, row.knowledge_fact_id)


def _occurred_in(fact_type: str, payload: dict[str, Any]) -> dict[str, Any] | None:
    night_no = _positive_int(payload.get("night_no"))
    if night_no is not None:
        return {"period": "night", "round_no": night_no}
    round_no = _positive_int(payload.get("round_no"))
    if round_no is not None:
        period = (
            "day"
            if fact_type
            in {
                "private_ability_action_committed",
                "private_action_decision",
                "private_round_memory",
            }
            else "unknown"
        )
        return {"period": period, "round_no": round_no}
    return None


def _positive_int(value: Any) -> int | None:
    if isinstance(value, int) and not isinstance(value, bool) and value > 0:
        return value
    return None


__all__ = ["player_private_knowledge"]
