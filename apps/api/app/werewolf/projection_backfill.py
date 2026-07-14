from __future__ import annotations

import argparse
import copy
import json
from dataclasses import dataclass
from typing import Any

from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.models.live import (
    GodViewLiveEventRecord,
    LiveEventRecord,
    PublicLiveEventRecord,
)
from app.werewolf.live import LiveEvent, ProjectedLiveEvent
from app.werewolf.live_store import format_live_datetime, parse_live_datetime
from app.werewolf.privacy_projection import ProjectionAudience, project_live_event


@dataclass
class ProjectionRebuildCounts:
    scanned: int = 0
    created: int = 0
    updated: int = 0
    unchanged: int = 0
    omitted: int = 0

    def to_dict(self) -> dict[str, int]:
        return {
            "scanned": self.scanned,
            "created": self.created,
            "updated": self.updated,
            "unchanged": self.unchanged,
            "omitted": self.omitted,
        }


def rebuild_live_event_projections(
    db: Session,
    *,
    apply: bool,
    run_id: str | None = None,
    session_id: str | None = None,
    limit: int = 1000,
) -> dict[str, dict[str, int]]:
    bounded_limit = min(10_000, max(1, limit))
    query: Select[tuple[LiveEventRecord]] = select(LiveEventRecord)
    if run_id:
        query = query.where(LiveEventRecord.run_id == run_id)
    if session_id:
        query = query.where(LiveEventRecord.session_id == session_id)
    records = list(
        db.scalars(
            query.order_by(
                LiveEventRecord.created_at.asc(),
                LiveEventRecord.run_id.asc(),
                LiveEventRecord.event_id.asc(),
            ).limit(bounded_limit)
        )
    )
    counts = {
        "player_public": ProjectionRebuildCounts(),
        "spectator_god_view": ProjectionRebuildCounts(),
    }
    for record in records:
        event = _live_event(record)
        for audience in ("player_public", "spectator_god_view"):
            audience_counts = counts[audience]
            audience_counts.scanned += 1
            projected = project_live_event(event, audience)
            if projected is None:
                audience_counts.omitted += 1
                continue
            _rebuild_one(
                db,
                event=projected,
                audience=audience,
                apply=apply,
                counts=audience_counts,
            )
    return {audience: value.to_dict() for audience, value in counts.items()}


def _rebuild_one(
    db: Session,
    *,
    event: ProjectedLiveEvent,
    audience: ProjectionAudience,
    apply: bool,
    counts: ProjectionRebuildCounts,
) -> None:
    record_type = (
        PublicLiveEventRecord
        if audience == "player_public"
        else GodViewLiveEventRecord
    )
    existing = db.get(record_type, (event.run_id, event.id))
    values = _projection_values(event)
    if existing is None:
        counts.created += 1
        if apply:
            db.add(record_type(**values))
        return
    if _record_matches(existing, values):
        counts.unchanged += 1
        return
    counts.updated += 1
    if apply:
        for key, value in values.items():
            setattr(existing, key, copy.deepcopy(value))


def _record_matches(
    record: PublicLiveEventRecord | GodViewLiveEventRecord,
    values: dict[str, Any],
) -> bool:
    for key, value in values.items():
        stored = getattr(record, key)
        if key == "created_at" and stored is not None and value is not None:
            if format_live_datetime(stored) != format_live_datetime(value):
                return False
            continue
        if stored != value:
            return False
    return True


def _projection_values(event: ProjectedLiveEvent) -> dict[str, Any]:
    return {
        "run_id": event.run_id,
        "event_id": event.id,
        "source_event_id": event.source_event_id,
        "session_id": event.session_id,
        "type": event.type,
        "round": event.round,
        "phase": event.phase,
        "actor": event.actor,
        "action": event.action,
        "payload": event.payload,
        "projection_version": event.projection_version,
        "created_at": parse_live_datetime(event.created_at),
    }


def _live_event(record: LiveEventRecord) -> LiveEvent:
    return LiveEvent(
        id=record.event_id,
        type=record.type,
        run_id=record.run_id,
        session_id=record.session_id,
        created_at=format_live_datetime(record.created_at),
        round=record.round,
        phase=record.phase,
        actor=record.actor,
        action=record.action,
        payload=record.payload if isinstance(record.payload, dict) else {},
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Rebuild audience-scoped live event projections without printing payloads."
    )
    parser.add_argument("--apply", action="store_true", help="write changes; default is dry-run")
    parser.add_argument("--run-id")
    parser.add_argument("--session-id")
    parser.add_argument("--limit", type=int, default=1000)
    args = parser.parse_args()
    with SessionLocal() as db:
        counts = rebuild_live_event_projections(
            db,
            apply=args.apply,
            run_id=args.run_id,
            session_id=args.session_id,
            limit=args.limit,
        )
        if args.apply:
            db.commit()
        else:
            db.rollback()
    print(json.dumps({"mode": "apply" if args.apply else "dry-run", "counts": counts}))


if __name__ == "__main__":
    main()
