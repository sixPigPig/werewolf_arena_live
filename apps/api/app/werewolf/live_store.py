from __future__ import annotations

import copy
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.models.live import LiveEventRecord, LiveRunRecord
from app.werewolf.live import LiveEvent, LiveGameRun


def parse_live_datetime(value: str | None) -> datetime | None:
    if value is None:
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def format_live_datetime(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


class DatabaseLiveStore:
    def __init__(self, db: Session) -> None:
        self.db = db

    def save_run(self, run: LiveGameRun) -> None:
        record = self.db.get(LiveRunRecord, run.run_id)
        if record is None:
            record = LiveRunRecord(
                run_id=run.run_id,
                session_id=run.session_id,
                status=run.status,
                villager_model=run.villager_model,
                werewolf_model=run.werewolf_model,
                seed=run.seed,
                max_rounds=run.max_rounds,
                rule_set_id=run.rule_set_id,
                created_at=parse_live_datetime(run.created_at) or datetime.now(tz=UTC),
            )
            self.db.add(record)
        record.status = run.status
        record.rule_set = copy.deepcopy(run.rule_set)
        record.player_configs = copy.deepcopy(run.player_configs)
        record.lineup_quality_warnings = copy.deepcopy(run.lineup_quality_warnings)
        record.winner = run.winner
        record.error = run.error
        record.stop_requested_at = parse_live_datetime(run.stop_requested_at)
        record.started_at = parse_live_datetime(run.started_at)
        record.completed_at = parse_live_datetime(run.completed_at)
        self._commit()

    def append_event(self, event: LiveEvent) -> None:
        record = LiveEventRecord(
            run_id=event.run_id,
            event_id=event.id,
            session_id=event.session_id,
            type=event.type,
            round=event.round,
            phase=event.phase,
            actor=event.actor,
            action=event.action,
            payload=event.payload,
            created_at=parse_live_datetime(event.created_at) or datetime.now(tz=UTC),
        )
        self.db.add(record)
        self._commit()

    def events_after(self, run_id: str, *, after_id: int | None = None) -> list[LiveEvent]:
        query = self.db.query(LiveEventRecord).filter(LiveEventRecord.run_id == run_id)
        if after_id is not None:
            query = query.filter(LiveEventRecord.event_id > after_id)
        rows = query.order_by(LiveEventRecord.event_id.asc()).all()
        return [
            LiveEvent(
                id=row.event_id,
                type=row.type,
                run_id=row.run_id,
                session_id=row.session_id,
                created_at=format_live_datetime(row.created_at),
                round=row.round,
                phase=row.phase,
                actor=row.actor,
                action=row.action,
                payload=copy.deepcopy(row.payload),
            )
            for row in rows
        ]

    def playback_events_for_session(self, session_id: str) -> list[dict[str, Any]]:
        eventful_run = (
            self.db.query(LiveEventRecord.run_id)
            .join(LiveRunRecord, LiveRunRecord.run_id == LiveEventRecord.run_id)
            .filter(LiveRunRecord.session_id == session_id)
            .group_by(LiveEventRecord.run_id)
            .order_by(func.max(LiveEventRecord.created_at).desc())
            .first()
        )
        if eventful_run is None:
            return []

        eventful_run_id = eventful_run[0]
        playback_run_id = f"playback_{session_id}"
        return [
            {
                **event.to_dict(),
                "run_id": playback_run_id,
            }
            for event in self.events_after(eventful_run_id)
        ]

    def _commit(self) -> None:
        try:
            self.db.commit()
        except SQLAlchemyError:
            self.db.rollback()
            raise
