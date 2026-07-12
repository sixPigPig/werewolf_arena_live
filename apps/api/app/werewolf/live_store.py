from __future__ import annotations

import copy
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, or_, select, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.models.live import LiveEventRecord, LiveRunRecord
from app.werewolf.live import (
    GameRunCanceled,
    LiveEvent,
    LiveGameRun,
    RunLeaseState,
    RunLeaseUnavailable,
    RunRecoveryCandidate,
    strict_json_equal,
    validate_prepared_run,
    validate_rule_set_revision_metadata,
)


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

    def stage_new_run(self, run: LiveGameRun) -> None:
        validate_prepared_run(run)
        validate_rule_set_revision_metadata(
            rule_set_revision_id=run.rule_set_revision_id,
            rule_set_revision_no=run.rule_set_revision_no,
            rule_set_content_hash=run.rule_set_content_hash,
            rule_set=run.rule_set,
        )
        if self.db.get(LiveRunRecord, run.run_id) is not None:
            raise ValueError(f"Run {run.run_id} already exists")
        event = run.events[0]

        record = LiveRunRecord(
            run_id=run.run_id,
            session_id=run.session_id,
            status=run.status,
            villager_model=run.villager_model,
            werewolf_model=run.werewolf_model,
            seed=run.seed,
            max_rounds=run.max_rounds,
            rule_set_id=run.rule_set_id,
            rule_set_revision_id=run.rule_set_revision_id,
            rule_set_revision_no=run.rule_set_revision_no,
            rule_set_content_hash=run.rule_set_content_hash,
            rule_set=copy.deepcopy(run.rule_set),
            player_configs=copy.deepcopy(run.player_configs),
            lineup_quality_warnings=copy.deepcopy(run.lineup_quality_warnings),
            winner=run.winner,
            error=run.error,
            created_at=parse_live_datetime(run.created_at) or datetime.now(tz=UTC),
            started_at=parse_live_datetime(run.started_at),
            completed_at=parse_live_datetime(run.completed_at),
            stop_requested_at=parse_live_datetime(run.stop_requested_at),
            worker_id=run.worker_id,
            worker_heartbeat_at=parse_live_datetime(run.worker_heartbeat_at),
            lease_expires_at=parse_live_datetime(run.lease_expires_at),
            control_version=run.control_version,
            fence_token=run.fence_token,
            recovery_attempts=run.recovery_attempts,
            recovery_last_attempt_at=parse_live_datetime(run.recovery_last_attempt_at),
            recovery_not_before=parse_live_datetime(run.recovery_not_before),
            recovery_last_error=run.recovery_last_error,
        )
        self.db.add(record)
        self.db.flush()
        self.db.add(_event_record(event))
        self.db.flush()

    def save_new_run(self, run: LiveGameRun) -> None:
        try:
            self.stage_new_run(run)
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise

    def save_run(self, run: LiveGameRun) -> None:
        validate_rule_set_revision_metadata(
            rule_set_revision_id=run.rule_set_revision_id,
            rule_set_revision_no=run.rule_set_revision_no,
            rule_set_content_hash=run.rule_set_content_hash,
            rule_set=run.rule_set,
        )
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
        elif record.fence_token > 0:
            now = datetime.now(tz=UTC)
            guard = self.db.execute(
                update(LiveRunRecord)
                .where(
                    LiveRunRecord.run_id == run.run_id,
                    LiveRunRecord.worker_id == run.worker_id,
                    LiveRunRecord.fence_token == run.fence_token,
                    or_(
                        LiveRunRecord.status.in_(("completed", "failed", "canceled")),
                        LiveRunRecord.lease_expires_at > now,
                    ),
                )
                .values(fence_token=LiveRunRecord.fence_token)
                .execution_options(synchronize_session=False)
            )
            if guard.rowcount != 1:
                self.db.rollback()
                raise RunLeaseUnavailable(
                    f"Run {run.run_id} write was rejected by its fencing token"
                )
        terminal_statuses = {"completed", "failed", "canceled"}
        fenced_by_terminal_state = (
            not is_new and record.status in terminal_statuses and record.status != run.status
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
        record.rule_set_revision_id = run.rule_set_revision_id
        record.rule_set_revision_no = run.rule_set_revision_no
        record.rule_set_content_hash = run.rule_set_content_hash
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
        record.fence_token = run.fence_token
        record.recovery_attempts = run.recovery_attempts
        record.recovery_last_attempt_at = parse_live_datetime(run.recovery_last_attempt_at)
        record.recovery_not_before = parse_live_datetime(run.recovery_not_before)
        record.recovery_last_error = run.recovery_last_error
        record.worker_heartbeat_at = parse_live_datetime(run.worker_heartbeat_at)
        if not fenced_by_terminal_state:
            record.lease_expires_at = parse_live_datetime(run.lease_expires_at)
        record.started_at = parse_live_datetime(run.started_at)
        self._commit()

    def activate_run(
        self,
        run_id: str,
        *,
        expected_events: tuple[LiveEvent, ...],
        expected_status: str,
        expected_started_at: str | None,
        activation: LiveEvent,
        worker_id: str,
        fence_token: int,
        started_at: str,
    ) -> None:
        parsed_started_at = parse_live_datetime(started_at)
        parsed_expected_started_at = parse_live_datetime(expected_started_at)
        expected_type = "run_recovered" if expected_started_at is not None else "run_started"
        expected_payload = {"fence_token": fence_token} if expected_started_at is not None else {}
        status_and_start_are_canonical = (
            expected_status == "queued" and expected_started_at is None
        ) or (expected_status == "running" and expected_started_at is not None)
        recovery_start_is_unchanged = parsed_started_at is not None and (
            parsed_expected_started_at is None
            or format_live_datetime(parsed_started_at)
            == format_live_datetime(parsed_expected_started_at)
        )
        if (
            not status_and_start_are_canonical
            or not recovery_start_is_unchanged
            or activation.id != len(expected_events) + 1
            or activation.type != expected_type
            or activation.run_id != run_id
            or activation.round is not None
            or activation.phase is not None
            or activation.actor is not None
            or activation.action is not None
            or parse_live_datetime(activation.created_at) is None
            or not strict_json_equal(activation._payload, expected_payload)
        ):
            raise ValueError(f"Run {run_id} has an invalid activation transition")
        try:
            record = self.db.scalar(
                select(LiveRunRecord)
                .where(LiveRunRecord.run_id == run_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            if record is None:
                raise RunLeaseUnavailable(f"Run {run_id} no longer exists")
            if record.stop_requested_at is not None:
                raise GameRunCanceled("Game run was canceled by an administrator")
            lease_expires_at = (
                parse_live_datetime(format_live_datetime(record.lease_expires_at))
                if record.lease_expires_at is not None
                else None
            )
            lease_is_live = lease_expires_at is not None and lease_expires_at > datetime.now(tz=UTC)
            stored_started_at = _format_optional_datetime(record.started_at)
            normalized_expected_started_at = (
                format_live_datetime(parsed_expected_started_at)
                if parsed_expected_started_at is not None
                else None
            )
            if (
                record.status != expected_status
                or stored_started_at != normalized_expected_started_at
                or record.worker_id != worker_id
                or record.fence_token != fence_token
                or fence_token <= 0
                or not lease_is_live
            ):
                raise RunLeaseUnavailable(f"Run {run_id} activation was rejected by its lease")
            if not self._lock_and_validate_complete_event_stream(record, expected_events):
                raise RunLeaseUnavailable(f"Run {run_id} activation event stream changed")
            lease_expires_at = (
                parse_live_datetime(format_live_datetime(record.lease_expires_at))
                if record.lease_expires_at is not None
                else None
            )
            if lease_expires_at is None or lease_expires_at <= datetime.now(tz=UTC):
                raise RunLeaseUnavailable(f"Run {run_id} activation lease expired")
            if activation.session_id != record.session_id:
                raise ValueError(f"Run {run_id} has an invalid activation session")
            record.status = "running"
            record.started_at = parsed_started_at
            self.db.flush([record])
            event_record = _event_record(activation)
            self.db.add(event_record)
            self.db.flush([event_record])
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise

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
        expected_events: tuple[LiveEvent, ...],
        worker_id: str,
        heartbeat_at: str,
        lease_expires_at: str,
    ) -> RunLeaseState | None:
        heartbeat = parse_live_datetime(heartbeat_at)
        expires = parse_live_datetime(lease_expires_at)
        try:
            record = self.db.scalar(
                select(LiveRunRecord)
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
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            if record is None or not self._lock_and_validate_complete_event_stream(
                record,
                expected_events,
            ):
                self.db.rollback()
                return None
            record.worker_id = worker_id
            record.worker_heartbeat_at = heartbeat
            record.lease_expires_at = expires
            record.fence_token += 1
            state = self._lease_state_from_record(record)
            self.db.commit()
            return state
        except Exception:
            self.db.rollback()
            raise

    def heartbeat_lease(
        self,
        run_id: str,
        *,
        worker_id: str,
        heartbeat_at: str,
        lease_expires_at: str,
        fence_token: int,
    ) -> RunLeaseState | None:
        result = self.db.execute(
            update(LiveRunRecord)
            .where(
                LiveRunRecord.run_id == run_id,
                LiveRunRecord.worker_id == worker_id,
                LiveRunRecord.fence_token == fence_token,
                LiveRunRecord.status.in_(("queued", "running")),
            )
            .values(
                worker_heartbeat_at=parse_live_datetime(heartbeat_at),
                lease_expires_at=parse_live_datetime(lease_expires_at),
            )
            .execution_options(synchronize_session=False)
        )
        self._commit()
        if result.rowcount != 1:
            return self._lease_state(run_id)
        return self._lease_state(run_id)

    def _lease_state(self, run_id: str) -> RunLeaseState | None:
        record = self.db.get(LiveRunRecord, run_id)
        if record is None:
            return None
        return self._lease_state_from_record(record)

    def _lease_state_from_record(self, record: LiveRunRecord) -> RunLeaseState:
        return RunLeaseState(
            worker_id=record.worker_id,
            worker_heartbeat_at=_format_optional_datetime(record.worker_heartbeat_at),
            lease_expires_at=_format_optional_datetime(record.lease_expires_at),
            stop_requested_at=_format_optional_datetime(record.stop_requested_at),
            status=record.status,
            control_version=record.control_version,
            fence_token=record.fence_token,
            recovery_attempts=record.recovery_attempts,
            recovery_last_attempt_at=_format_optional_datetime(record.recovery_last_attempt_at),
            recovery_not_before=_format_optional_datetime(record.recovery_not_before),
            recovery_last_error=record.recovery_last_error,
        )

    def recovery_candidates(
        self,
        *,
        stale_before: str,
        now: str,
        max_attempts: int,
        limit: int,
    ) -> list[RunRecoveryCandidate]:
        stale = parse_live_datetime(stale_before)
        current = parse_live_datetime(now)
        event_count = (
            select(func.count(LiveEventRecord.event_id))
            .where(LiveEventRecord.run_id == LiveRunRecord.run_id)
            .correlate(LiveRunRecord)
            .scalar_subquery()
        )
        matching_session_event_count = (
            select(func.count(LiveEventRecord.event_id))
            .where(
                LiveEventRecord.run_id == LiveRunRecord.run_id,
                LiveEventRecord.session_id == LiveRunRecord.session_id,
            )
            .correlate(LiveRunRecord)
            .scalar_subquery()
        )
        distinct_event_id_count = (
            select(func.count(func.distinct(LiveEventRecord.event_id)))
            .where(LiveEventRecord.run_id == LiveRunRecord.run_id)
            .correlate(LiveRunRecord)
            .scalar_subquery()
        )
        minimum_event_id = (
            select(func.min(LiveEventRecord.event_id))
            .where(LiveEventRecord.run_id == LiveRunRecord.run_id)
            .correlate(LiveRunRecord)
            .scalar_subquery()
        )
        maximum_event_id = (
            select(func.max(LiveEventRecord.event_id))
            .where(LiveEventRecord.run_id == LiveRunRecord.run_id)
            .correlate(LiveRunRecord)
            .scalar_subquery()
        )
        has_initial_event = (
            select(LiveEventRecord.event_id)
            .where(
                LiveEventRecord.run_id == LiveRunRecord.run_id,
                LiveEventRecord.session_id == LiveRunRecord.session_id,
                LiveEventRecord.event_id == 1,
                LiveEventRecord.type == "run_created",
            )
            .correlate(LiveRunRecord)
            .exists()
        )
        rows = self.db.execute(
            select(
                LiveRunRecord.run_id,
                LiveRunRecord.session_id,
                LiveRunRecord.recovery_attempts,
            )
            .where(
                LiveRunRecord.status.in_(("queued", "running")),
                LiveRunRecord.recovery_attempts < max_attempts,
                event_count > 0,
                matching_session_event_count == event_count,
                distinct_event_id_count == event_count,
                minimum_event_id == 1,
                maximum_event_id == event_count,
                has_initial_event,
                or_(
                    LiveRunRecord.recovery_not_before.is_(None),
                    LiveRunRecord.recovery_not_before <= current,
                ),
                or_(
                    LiveRunRecord.lease_expires_at <= stale,
                    (
                        LiveRunRecord.lease_expires_at.is_(None)
                        & (LiveRunRecord.created_at <= stale)
                    ),
                ),
            )
            .order_by(LiveRunRecord.created_at, LiveRunRecord.run_id)
            .limit(limit)
        )
        return [
            RunRecoveryCandidate(
                run_id=run_id,
                session_id=session_id,
                recovery_attempts=recovery_attempts,
            )
            for run_id, session_id, recovery_attempts in rows
        ]

    def acquire_recovery_lease(
        self,
        run_id: str,
        *,
        expected_events: tuple[LiveEvent, ...],
        worker_id: str,
        expected_attempts: int,
        max_attempts: int,
        stale_before: str,
        heartbeat_at: str,
        lease_expires_at: str,
        recovery_not_before: str,
    ) -> RunLeaseState | None:
        stale = parse_live_datetime(stale_before)
        heartbeat = parse_live_datetime(heartbeat_at)
        try:
            record = self.db.scalar(
                select(LiveRunRecord)
                .where(
                    LiveRunRecord.run_id == run_id,
                    LiveRunRecord.status.in_(("queued", "running")),
                    LiveRunRecord.recovery_attempts == expected_attempts,
                    LiveRunRecord.recovery_attempts < max_attempts,
                    or_(
                        LiveRunRecord.recovery_not_before.is_(None),
                        LiveRunRecord.recovery_not_before <= heartbeat,
                    ),
                    or_(
                        LiveRunRecord.lease_expires_at <= stale,
                        (
                            LiveRunRecord.lease_expires_at.is_(None)
                            & (LiveRunRecord.created_at <= stale)
                        ),
                    ),
                )
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            if record is None or not self._lock_and_validate_complete_event_stream(
                record,
                expected_events,
            ):
                self.db.rollback()
                return None
            record.worker_id = worker_id
            record.worker_heartbeat_at = heartbeat
            record.lease_expires_at = parse_live_datetime(lease_expires_at)
            record.fence_token += 1
            record.recovery_attempts += 1
            record.recovery_last_attempt_at = heartbeat
            record.recovery_not_before = parse_live_datetime(recovery_not_before)
            record.recovery_last_error = None
            state = self._lease_state_from_record(record)
            self.db.commit()
            return state
        except Exception:
            self.db.rollback()
            raise

    def _lock_and_validate_complete_event_stream(
        self,
        record: LiveRunRecord,
        expected_events: tuple[LiveEvent, ...],
    ) -> bool:
        events = tuple(
            self.db.scalars(
                select(LiveEventRecord)
                .where(LiveEventRecord.run_id == record.run_id)
                .order_by(LiveEventRecord.event_id.asc())
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        )
        return bool(
            events
            and [event.event_id for event in events] == list(range(1, len(events) + 1))
            and events[0].type == "run_created"
            and all(
                event.run_id == record.run_id and event.session_id == record.session_id
                for event in events
            )
            and len(events) == len(expected_events)
            and all(
                stored_event_matches(recorded, expected)
                for recorded, expected in zip(events, expected_events, strict=True)
            )
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
            rule_set_revision_id=record.rule_set_revision_id,
            rule_set_revision_no=record.rule_set_revision_no,
            rule_set_content_hash=record.rule_set_content_hash,
            rule_set=copy.deepcopy({} if record.rule_set is None else record.rule_set),
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
            fence_token=record.fence_token,
            recovery_attempts=record.recovery_attempts,
            recovery_last_attempt_at=_format_optional_datetime(record.recovery_last_attempt_at),
            recovery_not_before=_format_optional_datetime(record.recovery_not_before),
            recovery_last_error=record.recovery_last_error,
            persisted_event_count=event_count,
            next_event_id=event_count + 1,
        )

    def append_event(
        self,
        event: LiveEvent,
        *,
        worker_id: str,
        fence_token: int,
    ) -> None:
        now = datetime.now(tz=UTC)
        guard = self.db.execute(
            update(LiveRunRecord)
            .where(
                LiveRunRecord.run_id == event.run_id,
                LiveRunRecord.worker_id == worker_id,
                LiveRunRecord.fence_token == fence_token,
                or_(
                    LiveRunRecord.fence_token == 0,
                    LiveRunRecord.status.in_(("completed", "failed", "canceled")),
                    LiveRunRecord.lease_expires_at > now,
                ),
            )
            .values(fence_token=LiveRunRecord.fence_token)
            .execution_options(synchronize_session=False)
        )
        if guard.rowcount != 1:
            self.db.rollback()
            raise RunLeaseUnavailable(f"Run {event.run_id} event was rejected by its fencing token")
        self.db.add(_event_record(event))
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


def stored_event_matches(record: LiveEventRecord, expected: LiveEvent) -> bool:
    try:
        expected_created_at = parse_live_datetime(expected.created_at)
        if expected_created_at is None:
            return False
        stored_fields = {
            "run_id": record.run_id,
            "session_id": record.session_id,
            "event_id": record.event_id,
            "type": record.type,
            "round": record.round,
            "phase": record.phase,
            "actor": record.actor,
            "action": record.action,
            "payload": record.payload,
        }
        expected_fields = {
            "run_id": expected.run_id,
            "session_id": expected.session_id,
            "event_id": expected.id,
            "type": expected.type,
            "round": expected.round,
            "phase": expected.phase,
            "actor": expected.actor,
            "action": expected.action,
            "payload": expected._payload,
        }
        return strict_json_equal(stored_fields, expected_fields) and format_live_datetime(
            record.created_at
        ) == format_live_datetime(expected_created_at)
    except Exception:
        return False


def _event_record(event: LiveEvent) -> LiveEventRecord:
    return LiveEventRecord(
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
