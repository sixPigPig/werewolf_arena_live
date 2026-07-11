from __future__ import annotations

import copy
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, or_, select, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.models.live import LiveEventRecord, LiveRunRecord
from app.werewolf.live import LiveEvent, LiveGameRun, RunLeaseState


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
        is_new = record is None
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
        terminal_statuses = {"completed", "failed", "canceled"}
        fenced_by_terminal_state = (
            not is_new
            and record.status in terminal_statuses
            and record.status != run.status
        )
        if fenced_by_terminal_state:
            run.status = record.status
            run.winner = record.winner
            run.error = record.error
            run.completed_at = _format_optional_datetime(record.completed_at)
            run.lease_expires_at = None
        else:
            record.status = run.status
            record.winner = run.winner
            record.error = run.error
            record.completed_at = parse_live_datetime(run.completed_at)
        record.rule_set = copy.deepcopy(run.rule_set)
        record.player_configs = copy.deepcopy(run.player_configs)
        record.lineup_quality_warnings = copy.deepcopy(run.lineup_quality_warnings)
        if is_new or run.control_version >= record.control_version:
            record.stop_requested_at = parse_live_datetime(run.stop_requested_at)
            record.control_version = run.control_version
        else:
            run.stop_requested_at = _format_optional_datetime(record.stop_requested_at)
            run.control_version = record.control_version
        record.worker_id = run.worker_id
        record.worker_heartbeat_at = parse_live_datetime(run.worker_heartbeat_at)
        if not fenced_by_terminal_state:
            record.lease_expires_at = parse_live_datetime(run.lease_expires_at)
        record.started_at = parse_live_datetime(run.started_at)
        self._commit()

    def load_run(self, run_id: str) -> LiveGameRun | None:
        record = self.db.get(LiveRunRecord, run_id)
        return self._run_from_record(record) if record is not None else None

    def active_run_for_session(self, session_id: str) -> LiveGameRun | None:
        record = self.db.scalar(
            select(LiveRunRecord)
            .where(
                LiveRunRecord.session_id == session_id,
                LiveRunRecord.status.in_(("queued", "running")),
            )
            .order_by(LiveRunRecord.created_at.desc(), LiveRunRecord.run_id.desc())
            .limit(1)
        )
        return self._run_from_record(record) if record is not None else None

    def acquire_lease(
        self,
        run_id: str,
        *,
        worker_id: str,
        heartbeat_at: str,
        lease_expires_at: str,
    ) -> RunLeaseState | None:
        heartbeat = parse_live_datetime(heartbeat_at)
        expires = parse_live_datetime(lease_expires_at)
        result = self.db.execute(
            update(LiveRunRecord)
            .where(
                LiveRunRecord.run_id == run_id,
                LiveRunRecord.status.in_(("queued", "running")),
                or_(
                    LiveRunRecord.worker_id.is_(None),
                    LiveRunRecord.worker_id == worker_id,
                    LiveRunRecord.lease_expires_at.is_(None),
                    LiveRunRecord.lease_expires_at <= heartbeat,
                ),
            )
            .values(
                worker_id=worker_id,
                worker_heartbeat_at=heartbeat,
                lease_expires_at=expires,
            )
        )
        self._commit()
        if result.rowcount != 1:
            return None
        return self._lease_state(run_id)

    def heartbeat_lease(
        self,
        run_id: str,
        *,
        worker_id: str,
        heartbeat_at: str,
        lease_expires_at: str,
    ) -> RunLeaseState | None:
        result = self.db.execute(
            update(LiveRunRecord)
            .where(
                LiveRunRecord.run_id == run_id,
                LiveRunRecord.worker_id == worker_id,
                LiveRunRecord.status.in_(("queued", "running")),
            )
            .values(
                worker_heartbeat_at=parse_live_datetime(heartbeat_at),
                lease_expires_at=parse_live_datetime(lease_expires_at),
            )
        )
        self._commit()
        if result.rowcount != 1:
            return self._lease_state(run_id)
        return self._lease_state(run_id)

    def _lease_state(self, run_id: str) -> RunLeaseState | None:
        record = self.db.get(LiveRunRecord, run_id)
        if record is None:
            return None
        return RunLeaseState(
            worker_id=record.worker_id,
            worker_heartbeat_at=_format_optional_datetime(record.worker_heartbeat_at),
            lease_expires_at=_format_optional_datetime(record.lease_expires_at),
            stop_requested_at=_format_optional_datetime(record.stop_requested_at),
            status=record.status,
            control_version=record.control_version,
        )

    def _run_from_record(self, record: LiveRunRecord) -> LiveGameRun:
        event_count = int(
            self.db.scalar(
                select(func.count())
                .select_from(LiveEventRecord)
                .where(LiveEventRecord.run_id == record.run_id)
            )
            or 0
        )
        return LiveGameRun(
            run_id=record.run_id,
            session_id=record.session_id,
            villager_model=record.villager_model,
            werewolf_model=record.werewolf_model,
            seed=record.seed,
            max_rounds=record.max_rounds,
            rule_set_id=record.rule_set_id,
            rule_set=copy.deepcopy(record.rule_set or {}),
            player_configs=copy.deepcopy(record.player_configs or []),
            lineup_quality_warnings=copy.deepcopy(record.lineup_quality_warnings or []),
            status=record.status,
            created_at=format_live_datetime(record.created_at),
            started_at=_format_optional_datetime(record.started_at),
            completed_at=_format_optional_datetime(record.completed_at),
            winner=record.winner,
            error=record.error,
            stop_requested_at=_format_optional_datetime(record.stop_requested_at),
            worker_id=record.worker_id,
            worker_heartbeat_at=_format_optional_datetime(record.worker_heartbeat_at),
            lease_expires_at=_format_optional_datetime(record.lease_expires_at),
            control_version=record.control_version,
            persisted_event_count=event_count,
        )

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


def _format_optional_datetime(value: datetime | None) -> str | None:
    return format_live_datetime(value) if value is not None else None
