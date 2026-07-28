from __future__ import annotations

import copy
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, or_, select, update
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.models.live import (
    GodViewLiveEventRecord,
    LiveEventRecord,
    LiveRunRecord,
    PublicLiveEventRecord,
    VoiceMaterializationJobRecord,
)
from app.werewolf.live import (
    ACTIVATION_ACK_RUN_FIELD_NAMES,
    ACTIVATION_ACK_RUN_TIMESTAMP_NAMES,
    GameRunCanceled,
    LiveEvent,
    LiveGameRun,
    ProjectedLiveEvent,
    RunActivationExpectedEvent,
    RunActivationExpectedState,
    RunLeaseState,
    RunLeaseUnavailable,
    RunRecoveryCandidate,
    RunRuleSetExpectedState,
    RunRuleSetMismatch,
    clone_live_event,
    clone_run_expected_events,
    clone_run_expected_state,
    clone_rule_set_expected_state,
    strict_json_equal,
    validate_prepared_run,
    validate_rule_set_revision_metadata,
)
from app.werewolf.liveness_store import LivenessRuntimeStore
from app.werewolf.privacy_projection import ProjectionAudience, project_live_event
from app.werewolf.session_timeline import (
    SessionTimeline,
    TimelineRun,
    build_session_timeline,
)
from app.werewolf.voice import voice_job_candidate


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
            parent_run_id=run.parent_run_id,
            resume_from_round=run.resume_from_round,
            attempt_no=run.attempt_no,
            rule_set_id=run.rule_set_id,
            rule_set_revision_id=run.rule_set_revision_id,
            rule_set_revision_no=run.rule_set_revision_no,
            rule_set_content_hash=run.rule_set_content_hash,
            rule_set=copy.deepcopy(run.rule_set),
            player_configs=copy.deepcopy(run.player_configs),
            lineup_quality_warnings=copy.deepcopy(run.lineup_quality_warnings),
            lineup_quality_report=copy.deepcopy(run.lineup_quality_report),
            p2_diagnostics=copy.deepcopy(run.p2_diagnostics),
            liveness_experience_revision=run.liveness_experience_revision,
            liveness_experience_snapshot=copy.deepcopy(
                run.liveness_experience_snapshot
            ),
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
        self._stage_event_with_voice_job(event)
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
                parent_run_id=run.parent_run_id,
                resume_from_round=run.resume_from_round,
                attempt_no=run.attempt_no,
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
                    LiveRunRecord.worker_id.is_not(None),
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
        record.parent_run_id = run.parent_run_id
        record.resume_from_round = run.resume_from_round
        record.attempt_no = run.attempt_no
        record.rule_set_revision_no = run.rule_set_revision_no
        record.rule_set_content_hash = run.rule_set_content_hash
        record.rule_set = copy.deepcopy(run.rule_set)
        record.player_configs = copy.deepcopy(run.player_configs)
        record.lineup_quality_warnings = copy.deepcopy(run.lineup_quality_warnings)
        record.lineup_quality_report = copy.deepcopy(run.lineup_quality_report)
        record.p2_diagnostics = copy.deepcopy(run.p2_diagnostics)
        record.liveness_experience_revision = run.liveness_experience_revision
        record.liveness_experience_snapshot = copy.deepcopy(
            run.liveness_experience_snapshot
        )
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
        expected_events: tuple[LiveEvent | RunActivationExpectedEvent, ...],
        expected_rule_set: RunRuleSetExpectedState,
        expected_status: str,
        expected_started_at: str | None,
        activation: LiveEvent,
        worker_id: str,
        fence_token: int,
        started_at: str,
    ) -> None:
        expected_rule_set = clone_rule_set_expected_state(expected_rule_set)
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
            events_match = self._lock_and_validate_complete_event_stream(record, expected_events)
            if not self._locked_rule_set_matches(record, expected_rule_set):
                raise RunRuleSetMismatch(f"Run {run_id} activation rule set changed")
            if not events_match:
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
            if expected_rule_set.rule_set_was_sql_null:
                record.rule_set = {}
            record.status = "running"
            record.started_at = parsed_started_at
            self.db.flush([record])
            event_record = self._stage_event_with_voice_job(activation)
            self.db.flush([event_record])
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise

    def activation_was_committed(
        self,
        expected_state: RunActivationExpectedState,
    ) -> bool:
        matches = False
        try:
            with self.db.no_autoflush:
                inventory_is_complete = activation_ack_schema_inventory_complete()
                expectation_is_complete = (
                    expected_state.fields.keys() == ACTIVATION_ACK_RUN_FIELD_NAMES
                    and expected_state.timestamps.keys() == ACTIVATION_ACK_RUN_TIMESTAMP_NAMES
                )
                if inventory_is_complete and expectation_is_complete:
                    record = self.db.scalar(
                        select(LiveRunRecord)
                        .where(LiveRunRecord.run_id == expected_state.run_id)
                        .with_for_update()
                        .execution_options(populate_existing=True)
                    )
                    if record is not None:
                        events = tuple(
                            self.db.scalars(
                                select(LiveEventRecord)
                                .where(LiveEventRecord.run_id == expected_state.run_id)
                                .order_by(LiveEventRecord.event_id.asc())
                                .with_for_update()
                                .execution_options(populate_existing=True)
                            )
                        )
                        matches = _stored_activation_state_matches(
                            record,
                            events,
                            expected_state,
                        )
        except Exception:
            matches = False
        try:
            self.db.rollback()
        except Exception:
            return False
        return matches

    def fail_run(
        self,
        run_id: str,
        *,
        expected_events: tuple[LiveEvent | RunActivationExpectedEvent, ...],
        expected_rule_set: RunRuleSetExpectedState,
        expected_status: str,
        failure: LiveEvent,
        worker_id: str,
        fence_token: int,
        completed_at: str,
        error: str,
    ) -> None:
        expected_events_snapshot = clone_run_expected_events(expected_events)
        expected_rule_set = clone_rule_set_expected_state(expected_rule_set)
        failure = clone_live_event(failure)
        if (
            type(run_id) is not str
            or type(expected_status) is not str
            or expected_status not in {"queued", "running"}
            or type(worker_id) is not str
            or type(fence_token) is not int
            or fence_token <= 0
            or type(completed_at) is not str
            or type(error) is not str
            or failure.id != len(expected_events_snapshot) + 1
            or failure.type != "game_failed"
            or failure.run_id != run_id
            or failure.round is not None
            or failure.phase is not None
            or failure.actor is not None
            or failure.action is not None
            or not strict_json_equal(failure._payload, {"error": error})
        ):
            raise ValueError(f"Run {run_id} has an invalid durable failure transition")
        parsed_completed_at = parse_live_datetime(completed_at)
        if (
            parsed_completed_at is None
            or parse_live_datetime(failure.created_at) != parsed_completed_at
        ):
            raise ValueError(f"Run {run_id} has an invalid durable failure timestamp")
        try:
            record = self.db.scalar(
                select(LiveRunRecord)
                .where(LiveRunRecord.run_id == run_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            if record is None:
                raise RunLeaseUnavailable(f"Run {run_id} no longer exists")
            lease_expires_at = (
                parse_live_datetime(format_live_datetime(record.lease_expires_at))
                if record.lease_expires_at is not None
                else None
            )
            if (
                record.status != expected_status
                or record.status not in {"queued", "running"}
                or record.worker_id != worker_id
                or record.fence_token != fence_token
                or record.stop_requested_at is not None
                or lease_expires_at is None
                or lease_expires_at <= datetime.now(tz=UTC)
            ):
                raise RunLeaseUnavailable(f"Run {run_id} durable failure was rejected by its lease")
            events_match = self._lock_and_validate_complete_event_stream(
                record,
                expected_events_snapshot,
            )
            if not self._locked_rule_set_matches(record, expected_rule_set):
                raise RunRuleSetMismatch(f"Run {run_id} durable failure rule set changed")
            lease_expires_at = (
                parse_live_datetime(format_live_datetime(record.lease_expires_at))
                if record.lease_expires_at is not None
                else None
            )
            if (
                not events_match
                or lease_expires_at is None
                or lease_expires_at <= datetime.now(tz=UTC)
            ):
                raise RunLeaseUnavailable(
                    f"Run {run_id} durable failure event stream or lease changed"
                )
            if failure.session_id != record.session_id:
                raise ValueError(f"Run {run_id} has an invalid durable failure session")
            record.status = "failed"
            record.error = error
            record.completed_at = parsed_completed_at
            record.worker_id = None
            record.worker_heartbeat_at = None
            record.lease_expires_at = None
            record.fence_token += 1
            record.recovery_last_error = error
            self.db.flush([record])
            event_record = self._stage_event_with_voice_job(failure)
            self.db.flush([event_record])
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise

    def failure_was_committed(
        self,
        expected_state: RunActivationExpectedState,
    ) -> bool:
        expected_state = clone_run_expected_state(expected_state)
        matches = False
        try:
            with self.db.no_autoflush:
                inventory_is_complete = activation_ack_schema_inventory_complete()
                expectation_is_complete = (
                    expected_state.fields.keys() == ACTIVATION_ACK_RUN_FIELD_NAMES
                    and expected_state.timestamps.keys() == ACTIVATION_ACK_RUN_TIMESTAMP_NAMES
                )
                if inventory_is_complete and expectation_is_complete:
                    record = self.db.scalar(
                        select(LiveRunRecord)
                        .where(LiveRunRecord.run_id == expected_state.run_id)
                        .with_for_update()
                        .execution_options(populate_existing=True)
                    )
                    if record is not None:
                        events = tuple(
                            self.db.scalars(
                                select(LiveEventRecord)
                                .where(LiveEventRecord.run_id == expected_state.run_id)
                                .order_by(LiveEventRecord.event_id.asc())
                                .with_for_update()
                                .execution_options(populate_existing=True)
                            )
                        )
                        matches = _stored_failure_state_matches(
                            record,
                            events,
                            expected_state,
                            rule_set_is_sql_null=(
                                record.rule_set is None
                                and self._rule_set_is_sql_null(record.run_id)
                            ),
                        )
        except Exception:
            matches = False
        try:
            self.db.rollback()
        except Exception:
            return False
        return matches

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

    def latest_run_for_session(self, session_id: str) -> LiveGameRun | None:
        record = self.db.scalar(
            select(LiveRunRecord)
            .where(LiveRunRecord.session_id == session_id)
            .order_by(
                LiveRunRecord.attempt_no.desc(),
                LiveRunRecord.created_at.desc(),
                LiveRunRecord.run_id.desc(),
            )
            .limit(1)
        )
        return self._run_from_record(record) if record is not None else None

    def acquire_lease(
        self,
        run_id: str,
        *,
        expected_events: tuple[LiveEvent | RunActivationExpectedEvent, ...],
        expected_rule_set: RunRuleSetExpectedState,
        worker_id: str,
        heartbeat_at: str,
        lease_expires_at: str,
    ) -> RunLeaseState | None:
        expected_rule_set = clone_rule_set_expected_state(expected_rule_set)
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
            if record is None:
                self.db.rollback()
                return None
            events_match = self._lock_and_validate_complete_event_stream(record, expected_events)
            if not self._locked_rule_set_matches(record, expected_rule_set):
                raise RunRuleSetMismatch(f"Run {run_id} activation rule set changed")
            if not events_match:
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
        expected_rule_set: RunRuleSetExpectedState,
        worker_id: str,
        expected_attempts: int,
        max_attempts: int,
        stale_before: str,
        heartbeat_at: str,
        lease_expires_at: str,
        recovery_not_before: str,
    ) -> RunLeaseState | None:
        expected_rule_set = clone_rule_set_expected_state(expected_rule_set)
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
            if record is None:
                self.db.rollback()
                return None
            events_match = self._lock_and_validate_complete_event_stream(record, expected_events)
            if not self._locked_rule_set_matches(record, expected_rule_set):
                raise RunRuleSetMismatch(f"Run {run_id} activation rule set changed")
            if not events_match:
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
        expected_events: tuple[LiveEvent | RunActivationExpectedEvent, ...],
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

    def _locked_rule_set_matches(
        self,
        record: LiveRunRecord,
        expected: RunRuleSetExpectedState,
    ) -> bool:
        if type(expected) is not RunRuleSetExpectedState:
            return False
        if expected.rule_set_was_sql_null:
            if record.rule_set is not None:
                return False
            stored_rule_set: object = {}
            stored_rule_set_was_sql_null = self._rule_set_is_sql_null(record.run_id)
        else:
            if record.rule_set is None:
                return False
            stored_rule_set = record.rule_set
            stored_rule_set_was_sql_null = False
        stored = {
            "rule_set_id": record.rule_set_id,
            "rule_set_revision_id": record.rule_set_revision_id,
            "rule_set_revision_no": record.rule_set_revision_no,
            "rule_set_content_hash": record.rule_set_content_hash,
            "rule_set": stored_rule_set,
            "rule_set_was_sql_null": stored_rule_set_was_sql_null,
        }
        wanted = {
            "rule_set_id": expected.rule_set_id,
            "rule_set_revision_id": expected.rule_set_revision_id,
            "rule_set_revision_no": expected.rule_set_revision_no,
            "rule_set_content_hash": expected.rule_set_content_hash,
            "rule_set": expected.rule_set,
            "rule_set_was_sql_null": expected.rule_set_was_sql_null,
        }
        return strict_json_equal(stored, wanted)

    def _run_from_record(self, record: LiveRunRecord) -> LiveGameRun:
        event_count = int(
            self.db.scalar(
                select(func.count())
                .select_from(LiveEventRecord)
                .where(LiveEventRecord.run_id == record.run_id)
            )
            or 0
        )
        rule_set_was_sql_null = False
        if record.rule_set is None:
            if not self._rule_set_is_sql_null(record.run_id):
                raise ValueError(f"Run {record.run_id} has an invalid JSON null rule set")
            rule_set: dict[str, Any] = {}
            rule_set_was_sql_null = True
        else:
            rule_set = copy.deepcopy(record.rule_set)
        return LiveGameRun(
            run_id=record.run_id,
            session_id=record.session_id,
            villager_model=record.villager_model,
            werewolf_model=record.werewolf_model,
            seed=record.seed,
            max_rounds=record.max_rounds,
            parent_run_id=record.parent_run_id,
            resume_from_round=record.resume_from_round,
            attempt_no=record.attempt_no,
            rule_set_id=record.rule_set_id,
            rule_set_revision_id=record.rule_set_revision_id,
            rule_set_revision_no=record.rule_set_revision_no,
            rule_set_content_hash=record.rule_set_content_hash,
            rule_set=rule_set,
            rule_set_was_sql_null=rule_set_was_sql_null,
            player_configs=copy.deepcopy(record.player_configs or []),
            lineup_quality_warnings=copy.deepcopy(record.lineup_quality_warnings or []),
            lineup_quality_report=copy.deepcopy(record.lineup_quality_report or {}),
            p2_diagnostics=copy.deepcopy(record.p2_diagnostics or {}),
            liveness_experience_revision=record.liveness_experience_revision,
            liveness_experience_snapshot=copy.deepcopy(
                record.liveness_experience_snapshot
            ),
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

    def _rule_set_is_sql_null(self, run_id: str) -> bool:
        return (
            self.db.scalar(
                select(LiveRunRecord.rule_set.is_(None)).where(LiveRunRecord.run_id == run_id)
            )
            is True
        )

    def append_event(
        self,
        event: LiveEvent,
        *,
        worker_id: str,
        fence_token: int,
    ) -> None:
        if type(worker_id) is not str or type(fence_token) is not int:
            raise RunLeaseUnavailable(f"Run {event.run_id} event has invalid write authority")
        now = datetime.now(tz=UTC)
        guard = self.db.execute(
            update(LiveRunRecord)
            .where(
                LiveRunRecord.run_id == event.run_id,
                LiveRunRecord.worker_id.is_not(None),
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
        try:
            self._stage_event_with_voice_job(event)
        except Exception:
            self.db.rollback()
            raise
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

    def playback_events_for_session(
        self,
        session_id: str,
        *,
        audience: ProjectionAudience = "player_public",
    ) -> list[dict[str, Any]]:
        timeline = self.session_timeline_for_session(session_id, audience=audience)
        playback_run_id = f"playback_{session_id}"
        return [
            event.to_dict(run_id=playback_run_id)
            for event in timeline.events
        ]

    def session_timeline_for_run(
        self,
        run_id: str,
        *,
        audience: ProjectionAudience = "player_public",
    ) -> SessionTimeline | None:
        run = self.db.get(LiveRunRecord, run_id)
        if run is None:
            return None
        return self.session_timeline_for_session(run.session_id, audience=audience)

    def session_timeline_for_session(
        self,
        session_id: str,
        *,
        audience: ProjectionAudience = "player_public",
    ) -> SessionTimeline:
        records = (
            self.db.query(LiveRunRecord)
            .filter(LiveRunRecord.session_id == session_id)
            .order_by(
                LiveRunRecord.attempt_no.asc(),
                LiveRunRecord.created_at.asc(),
                LiveRunRecord.run_id.asc(),
            )
            .all()
        )
        runs = [
            TimelineRun(
                run_id=record.run_id,
                created_at=format_live_datetime(record.created_at),
                attempt_no=record.attempt_no,
                parent_run_id=record.parent_run_id,
                resume_from_round=record.resume_from_round,
            )
            for record in records
        ]
        events_by_run = {
            record.run_id: [
                event.to_dict()
                for event in self.projected_events_after(
                    record.run_id,
                    audience=audience,
                )
            ]
            for record in records
        }
        return build_session_timeline(
            session_id=session_id,
            runs=runs,
            projected_events_by_run=events_by_run,
        )

    def projected_events_after(
        self,
        run_id: str,
        *,
        audience: ProjectionAudience,
        after_id: int | None = None,
    ) -> list[ProjectedLiveEvent]:
        record_type = (
            PublicLiveEventRecord
            if audience == "player_public"
            else GodViewLiveEventRecord
        )
        query = self.db.query(record_type).filter(record_type.run_id == run_id)
        if after_id is not None:
            query = query.filter(record_type.event_id > after_id)
        rows = query.order_by(record_type.event_id.asc()).all()
        if rows:
            return [
                _projected_event_from_record(row, audience=audience)
                for row in rows
            ]

        # Safe compatibility path for runs created before projection tables existed.
        return [
            projected
            for event in self.events_after(run_id, after_id=after_id)
            if (projected := project_live_event(event, audience)) is not None
        ]

    def _commit(self) -> None:
        try:
            self.db.commit()
        except SQLAlchemyError:
            self.db.rollback()
            raise

    def _stage_event_with_voice_job(self, event: LiveEvent) -> LiveEventRecord:
        event_record = _event_record(event)
        self.db.add(event_record)
        self.db.flush([event_record])
        liveness_store = LivenessRuntimeStore(self.db)
        liveness_store.stage_committed_segment(event)
        liveness_store.finalize_speech_turn(event)

        public_event = project_live_event(event, "player_public")
        god_view_event = project_live_event(event, "spectator_god_view")
        if public_event is not None:
            self.db.add(_public_projection_record(public_event))
        if god_view_event is not None:
            self.db.add(_god_view_projection_record(god_view_event))

        voice_jobs: list[tuple[str, str]] = []
        public_speaker_kind: str | None = None
        if public_event is not None:
            public_speaker_kind = voice_job_candidate(public_event)
            if public_speaker_kind is not None:
                voice_jobs.append((public_speaker_kind, "player_public"))
        if god_view_event is not None:
            god_view_speaker_kind = voice_job_candidate(
                god_view_event,
                audience="spectator_god_view",
            )
            if (
                god_view_speaker_kind is not None
                and god_view_speaker_kind != public_speaker_kind
            ):
                voice_jobs.append((god_view_speaker_kind, "spectator_god_view"))

        dialect_name = self.db.get_bind().dialect.name
        for speaker_kind, audience in voice_jobs:
            voice_snapshot = (
                event.payload.get("voice_snapshot")
                if speaker_kind == "player"
                and isinstance(event.payload.get("voice_snapshot"), dict)
                else None
            )
            if voice_snapshot is not None and voice_snapshot.get("enabled") is False:
                continue
            values = {
                "run_id": event.run_id,
                "source_event_id": event.id,
                "speaker_kind": speaker_kind,
                "session_id": event.session_id,
                "audience": audience,
                "status": "pending",
                "attempt_count": 0,
                "not_before": datetime.now(tz=UTC),
                "speaker": (
                    str(voice_snapshot.get("speaker") or "") or None
                    if voice_snapshot is not None
                    else None
                ),
                "effective_delivery": (
                    voice_snapshot.get("effective_delivery")
                    if voice_snapshot is not None
                    and isinstance(voice_snapshot.get("effective_delivery"), dict)
                    else None
                ),
                "effective_context_texts": (
                    [
                        str(item)
                        for item in voice_snapshot.get("effective_context_texts", [])
                        if isinstance(item, str)
                    ]
                    if voice_snapshot is not None
                    and isinstance(voice_snapshot.get("effective_context_texts"), list)
                    else None
                ),
                "tts_dialect": (
                    str(voice_snapshot.get("tts_dialect") or "") or None
                    if voice_snapshot is not None
                    else None
                ),
                "voice_config_version": (
                    voice_snapshot.get("voice_config_version")
                    if voice_snapshot is not None
                    and type(voice_snapshot.get("voice_config_version")) is int
                    else None
                ),
                "delivery_mapping_version": (
                    str(voice_snapshot.get("delivery_mapping_version") or "") or None
                    if voice_snapshot is not None
                    else None
                ),
                "tts_request_source": (
                    "committed_speech_segment"
                    if speaker_kind == "player"
                    and event.type == "model_response_delta"
                    and event.payload.get("commit_state") == "accepted_segment"
                    else "accepted_player_action"
                    if speaker_kind == "player"
                    else "judge_event"
                ),
            }
            if dialect_name == "postgresql":
                statement = postgresql_insert(VoiceMaterializationJobRecord).values(**values)
                statement = statement.on_conflict_do_nothing(
                    index_elements=("run_id", "source_event_id", "speaker_kind")
                )
                self.db.execute(statement)
            elif dialect_name == "sqlite":
                statement = sqlite_insert(VoiceMaterializationJobRecord).values(**values)
                statement = statement.on_conflict_do_nothing(
                    index_elements=("run_id", "source_event_id", "speaker_kind")
                )
                self.db.execute(statement)
            elif self.db.get(
                VoiceMaterializationJobRecord,
                (event.run_id, event.id, speaker_kind),
            ) is None:
                self.db.add(VoiceMaterializationJobRecord(**values))
        return event_record


def _format_optional_datetime(value: datetime | None) -> str | None:
    return format_live_datetime(value) if value is not None else None


_ACTIVATION_ACK_SERVER_MANAGED_COLUMNS = frozenset({"updated_at"})


def activation_ack_schema_inventory_complete() -> bool:
    compared_columns = ACTIVATION_ACK_RUN_FIELD_NAMES | ACTIVATION_ACK_RUN_TIMESTAMP_NAMES
    table_columns = frozenset(column.name for column in LiveRunRecord.__table__.columns)
    return (
        compared_columns.isdisjoint(_ACTIVATION_ACK_SERVER_MANAGED_COLUMNS)
        and compared_columns | _ACTIVATION_ACK_SERVER_MANAGED_COLUMNS == table_columns
    )


def _stored_activation_state_matches(
    record: LiveRunRecord,
    events: tuple[LiveEventRecord, ...],
    expected: RunActivationExpectedState,
) -> bool:
    lease_expires_at = (
        parse_live_datetime(format_live_datetime(record.lease_expires_at))
        if record.lease_expires_at is not None
        else None
    )
    return bool(
        _stored_expected_state_matches(
            record,
            events,
            expected,
            rule_set_is_sql_null=False,
        )
        and record.status == "running"
        and record.stop_requested_at is None
        and record.worker_id is not None
        and record.fence_token > 0
        and lease_expires_at is not None
        and lease_expires_at > datetime.now(tz=UTC)
    )


def _stored_failure_state_matches(
    record: LiveRunRecord,
    events: tuple[LiveEventRecord, ...],
    expected: RunActivationExpectedState,
    *,
    rule_set_is_sql_null: bool,
) -> bool:
    return bool(
        _stored_expected_state_matches(
            record,
            events,
            expected,
            rule_set_is_sql_null=rule_set_is_sql_null,
        )
        and record.status == "failed"
        and record.error is not None
        and record.error == record.recovery_last_error
        and record.completed_at is not None
        and record.lease_expires_at is None
        and events[-1].type == "game_failed"
        and strict_json_equal(events[-1].payload, {"error": record.error})
    )


def _stored_expected_state_matches(
    record: LiveRunRecord,
    events: tuple[LiveEventRecord, ...],
    expected: RunActivationExpectedState,
    *,
    rule_set_is_sql_null: bool,
) -> bool:
    try:
        if type(rule_set_is_sql_null) is not bool:
            return False
        stored_rule_set = {} if rule_set_is_sql_null else record.rule_set
        stored_fields = {
            "run_id": record.run_id,
            "session_id": record.session_id,
            "status": record.status,
            "villager_model": record.villager_model,
            "werewolf_model": record.werewolf_model,
            "seed": record.seed,
            "max_rounds": record.max_rounds,
            "parent_run_id": record.parent_run_id,
            "resume_from_round": record.resume_from_round,
            "attempt_no": record.attempt_no,
            "rule_set_id": record.rule_set_id,
            "rule_set_revision_id": record.rule_set_revision_id,
            "rule_set_revision_no": record.rule_set_revision_no,
            "rule_set_content_hash": record.rule_set_content_hash,
            "rule_set": stored_rule_set,
            "player_configs": record.player_configs,
            "lineup_quality_warnings": record.lineup_quality_warnings,
            "lineup_quality_report": record.lineup_quality_report,
            "p2_diagnostics": record.p2_diagnostics,
            "liveness_experience_revision": record.liveness_experience_revision,
            "liveness_experience_snapshot": record.liveness_experience_snapshot,
            "winner": record.winner,
            "error": record.error,
            "worker_id": record.worker_id,
            "control_version": record.control_version,
            "fence_token": record.fence_token,
            "recovery_attempts": record.recovery_attempts,
            "recovery_last_error": record.recovery_last_error,
        }
        stored_timestamps = {
            "created_at": record.created_at,
            "started_at": record.started_at,
            "completed_at": record.completed_at,
            "stop_requested_at": record.stop_requested_at,
            "worker_heartbeat_at": record.worker_heartbeat_at,
            "lease_expires_at": record.lease_expires_at,
            "recovery_last_attempt_at": record.recovery_last_attempt_at,
            "recovery_not_before": record.recovery_not_before,
        }
        return bool(
            stored_fields.keys() == ACTIVATION_ACK_RUN_FIELD_NAMES
            and stored_timestamps.keys() == ACTIVATION_ACK_RUN_TIMESTAMP_NAMES
            and strict_json_equal(stored_fields, expected.fields)
            and all(
                _stored_timestamp_matches(stored_timestamps[name], expected.timestamps[name])
                for name in ACTIVATION_ACK_RUN_TIMESTAMP_NAMES
            )
            and expected.rule_set_was_sql_null is rule_set_is_sql_null
            and expected.event_count == len(expected.events)
            and expected.next_event_id == expected.event_count + 1
            and len(events) == expected.event_count
            and [event.event_id for event in events] == list(range(1, len(events) + 1))
            and events[0].type == "run_created"
            and all(
                event.run_id == record.run_id and event.session_id == record.session_id
                for event in events
            )
            and all(
                _stored_activation_event_matches(stored, expected_event)
                for stored, expected_event in zip(events, expected.events, strict=True)
            )
        )
    except Exception:
        return False


def _stored_timestamp_matches(
    stored: datetime | None,
    expected: str | None,
) -> bool:
    if stored is None or expected is None:
        return stored is None and expected is None
    parsed_expected = parse_live_datetime(expected)
    return parsed_expected is not None and format_live_datetime(stored) == format_live_datetime(
        parsed_expected
    )


def stored_event_matches(
    record: LiveEventRecord,
    expected: LiveEvent | RunActivationExpectedEvent,
) -> bool:
    if type(expected) is RunActivationExpectedEvent:
        return _stored_activation_event_matches(record, expected)
    if type(expected) is not LiveEvent:
        return False
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


def _stored_activation_event_matches(
    record: LiveEventRecord,
    expected: RunActivationExpectedEvent,
) -> bool:
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
            "payload": expected.payload,
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


def _public_projection_record(event: ProjectedLiveEvent) -> PublicLiveEventRecord:
    return PublicLiveEventRecord(**_projection_record_values(event))


def _god_view_projection_record(event: ProjectedLiveEvent) -> GodViewLiveEventRecord:
    return GodViewLiveEventRecord(**_projection_record_values(event))


def _projection_record_values(event: ProjectedLiveEvent) -> dict[str, Any]:
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
        "created_at": parse_live_datetime(event.created_at) or datetime.now(tz=UTC),
    }


def _projected_event_from_record(
    record: PublicLiveEventRecord | GodViewLiveEventRecord,
    *,
    audience: ProjectionAudience,
) -> ProjectedLiveEvent:
    return ProjectedLiveEvent(
        id=record.event_id,
        source_event_id=record.source_event_id,
        type=record.type,
        run_id=record.run_id,
        session_id=record.session_id,
        created_at=format_live_datetime(record.created_at),
        audience=audience,
        projection_version=record.projection_version,
        round=record.round,
        phase=record.phase,
        actor=record.actor,
        action=record.action,
        payload=copy.deepcopy(record.payload),
    )
