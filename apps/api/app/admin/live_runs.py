from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import Select, and_, case, func, literal, or_, select
from sqlalchemy.orm import Session

from app.models.game_session import GameSessionRecord
from app.models.live import LiveEventRecord, LiveRunRecord, VoiceUtteranceRecord
from app.models.rule_set import RuleSetRevisionRecord


@dataclass(frozen=True)
class AdminLiveRunRow:
    run_id: str
    session_id: str
    status: str
    villager_model: str | None
    werewolf_model: str | None
    max_rounds: int
    rule_set_id: str
    rule_set_revision_id: str | None
    rule_set_revision_no: int | None
    rule_set_content_hash: str | None
    rule_set_name: str | None
    rule_set_player_count: int | None
    winner: str | None
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    stop_requested_at: datetime | None
    worker_heartbeat_at: datetime | None
    lease_expires_at: datetime | None
    recovery_attempts: int
    recovery_last_attempt_at: datetime | None
    recovery_not_before: datetime | None
    updated_at: datetime
    has_error: bool
    game_status: str | None
    game_resumable: bool | None

    @property
    def run_is_terminal(self) -> bool:
        return self.status == "completed"

    @property
    def game_is_terminal(self) -> bool:
        return self.game_status == "complete" and self.game_resumable is False

    @property
    def can_reveal_event_identity(self) -> bool:
        return self.run_is_terminal and self.game_is_terminal


@dataclass(frozen=True)
class AdminLiveRunEventRow:
    event_id: int
    type: str
    round: int | None
    phase: str | None
    actor: str | None
    action: str | None
    created_at: datetime


@dataclass(frozen=True)
class AdminVoiceCounts:
    total: int = 0
    pending: int = 0
    synthesizing: int = 0
    complete: int = 0
    failed: int = 0
    canceled: int = 0
    other: int = 0


@dataclass(frozen=True)
class AdminLiveRunListResult:
    records: list[AdminLiveRunRow]
    event_counts: dict[str, int]
    last_event_at: dict[str, datetime]
    voice_counts: dict[str, AdminVoiceCounts]
    page: int
    page_size: int
    total: int
    pages: int


@dataclass(frozen=True)
class AdminLiveRunDetailData:
    record: AdminLiveRunRow
    event_count: int
    last_event_at: datetime | None
    voice_counts: AdminVoiceCounts
    recent_events: list[AdminLiveRunEventRow]
    p2_diagnostics: dict[str, Any]
    diagnostic_events: list[dict[str, Any]]


def list_admin_live_runs(
    db: Session,
    *,
    page: int,
    page_size: int,
    query_text: str | None,
    status: str | None,
    rule_set_id: str | None,
    rule_set_revision_id: str | None,
    created_from: datetime | None,
    created_to: datetime | None,
    sort: str,
) -> AdminLiveRunListResult:
    query = _base_run_query()
    filters: list[Any] = []
    normalized_query = _clean_filter(query_text)
    if normalized_query is not None:
        pattern = f"{_escape_like(normalized_query)}%"
        filters.append(
            or_(
                LiveRunRecord.run_id.ilike(pattern, escape="\\"),
                LiveRunRecord.session_id.ilike(pattern, escape="\\"),
            )
        )
    if status is not None:
        filters.append(LiveRunRecord.status == status)
    if rule_set_id is not None:
        filters.append(LiveRunRecord.rule_set_id == rule_set_id.strip())
    if rule_set_revision_id is not None:
        filters.append(LiveRunRecord.rule_set_revision_id == rule_set_revision_id.strip())
    if created_from is not None:
        filters.append(LiveRunRecord.created_at >= created_from)
    if created_to is not None:
        filters.append(LiveRunRecord.created_at <= created_to)

    query = query.where(*filters)
    total = int(db.scalar(select(func.count()).select_from(LiveRunRecord).where(*filters)) or 0)
    pages = (total + page_size - 1) // page_size if total else 0
    rows = db.execute(
        query.order_by(*_run_sort_columns(sort)).offset((page - 1) * page_size).limit(page_size)
    )
    records = [AdminLiveRunRow(*row) for row in rows]
    run_ids = [record.run_id for record in records]
    event_counts, last_event_at = _event_aggregates(db, run_ids)
    voice_counts = _voice_aggregates(db, run_ids)
    return AdminLiveRunListResult(
        records=records,
        event_counts=event_counts,
        last_event_at=last_event_at,
        voice_counts=voice_counts,
        page=page,
        page_size=page_size,
        total=total,
        pages=pages,
    )


def get_admin_live_run_detail(db: Session, run_id: str) -> AdminLiveRunDetailData | None:
    row = db.execute(_base_run_query().where(LiveRunRecord.run_id == run_id)).one_or_none()
    if row is None:
        return None
    record = AdminLiveRunRow(*row)
    event_counts, last_event_at = _event_aggregates(db, [run_id])
    voice_counts = _voice_aggregates(db, [run_id])

    identity_columns: tuple[Any, Any]
    if record.can_reveal_event_identity:
        identity_columns = (LiveEventRecord.actor, LiveEventRecord.action)
    else:
        identity_columns = (
            literal(None).label("actor"),
            literal(None).label("action"),
        )
    recent_desc = [
        AdminLiveRunEventRow(*event_row)
        for event_row in db.execute(
            select(
                LiveEventRecord.event_id,
                LiveEventRecord.type,
                LiveEventRecord.round,
                LiveEventRecord.phase,
                *identity_columns,
                LiveEventRecord.created_at,
            )
            .where(LiveEventRecord.run_id == run_id)
            .order_by(LiveEventRecord.event_id.desc())
            .limit(50)
        )
    ]
    recent_events = _safe_event_rows(
        list(reversed(recent_desc)),
        reveal_terminal_metadata=record.can_reveal_event_identity,
    )
    p2_diagnostics = db.scalar(
        select(LiveRunRecord.p2_diagnostics).where(
            LiveRunRecord.run_id == record.run_id
        )
    )
    diagnostic_events = [
        {"type": event_type, "payload": {}}
        for (event_type,) in db.execute(
            select(LiveEventRecord.type)
            .where(LiveEventRecord.run_id == run_id)
            .order_by(LiveEventRecord.event_id.asc())
            .limit(5000)
        )
    ]
    return AdminLiveRunDetailData(
        record=record,
        event_count=event_counts.get(run_id, 0),
        last_event_at=last_event_at.get(run_id),
        voice_counts=voice_counts.get(run_id, AdminVoiceCounts()),
        recent_events=recent_events,
        p2_diagnostics=(
            p2_diagnostics if isinstance(p2_diagnostics, dict) else {}
        ),
        diagnostic_events=diagnostic_events,
    )


def _base_run_query() -> Select[Any]:
    reveal_terminal_metadata = and_(
        LiveRunRecord.status == "completed",
        GameSessionRecord.status == "complete",
        GameSessionRecord.resumable.is_(False),
    )
    return (
        select(
            LiveRunRecord.run_id,
            LiveRunRecord.session_id,
            LiveRunRecord.status,
            case(
                (reveal_terminal_metadata, LiveRunRecord.villager_model),
                else_=None,
            ).label("villager_model"),
            case(
                (reveal_terminal_metadata, LiveRunRecord.werewolf_model),
                else_=None,
            ).label("werewolf_model"),
            LiveRunRecord.max_rounds,
            LiveRunRecord.rule_set_id,
            LiveRunRecord.rule_set_revision_id,
            LiveRunRecord.rule_set_revision_no,
            LiveRunRecord.rule_set_content_hash,
            RuleSetRevisionRecord.name.label("rule_set_name"),
            RuleSetRevisionRecord.player_count.label("rule_set_player_count"),
            case(
                (reveal_terminal_metadata, LiveRunRecord.winner),
                else_=None,
            ).label("winner"),
            LiveRunRecord.created_at,
            LiveRunRecord.started_at,
            LiveRunRecord.completed_at,
            LiveRunRecord.stop_requested_at,
            LiveRunRecord.worker_heartbeat_at,
            LiveRunRecord.lease_expires_at,
            LiveRunRecord.recovery_attempts,
            LiveRunRecord.recovery_last_attempt_at,
            LiveRunRecord.recovery_not_before,
            LiveRunRecord.updated_at,
            case(
                (
                    and_(LiveRunRecord.error.is_not(None), LiveRunRecord.error != ""),
                    True,
                ),
                else_=False,
            ).label("has_error"),
            GameSessionRecord.status.label("game_status"),
            GameSessionRecord.resumable.label("game_resumable"),
        )
        .outerjoin(
            GameSessionRecord,
            GameSessionRecord.session_id == LiveRunRecord.session_id,
        )
        .outerjoin(
            RuleSetRevisionRecord,
            RuleSetRevisionRecord.id == LiveRunRecord.rule_set_revision_id,
        )
    )


def _event_aggregates(
    db: Session,
    run_ids: list[str],
) -> tuple[dict[str, int], dict[str, datetime]]:
    if not run_ids:
        return {}, {}
    rows = db.execute(
        select(
            LiveEventRecord.run_id,
            func.count(),
            func.max(LiveEventRecord.created_at),
        )
        .where(LiveEventRecord.run_id.in_(run_ids))
        .group_by(LiveEventRecord.run_id)
    )
    event_counts: dict[str, int] = {}
    last_event_at: dict[str, datetime] = {}
    for run_id, event_count, latest_at in rows:
        normalized_run_id = str(run_id)
        event_counts[normalized_run_id] = int(event_count)
        if isinstance(latest_at, datetime):
            last_event_at[normalized_run_id] = latest_at
    return event_counts, last_event_at


def _voice_aggregates(
    db: Session,
    run_ids: list[str],
) -> dict[str, AdminVoiceCounts]:
    if not run_ids:
        return {}
    grouped: dict[str, dict[str, int]] = {}
    rows = db.execute(
        select(
            VoiceUtteranceRecord.run_id,
            VoiceUtteranceRecord.status,
            func.count(),
        )
        .where(VoiceUtteranceRecord.run_id.in_(run_ids))
        .group_by(VoiceUtteranceRecord.run_id, VoiceUtteranceRecord.status)
    )
    known_statuses = {"pending", "synthesizing", "complete", "failed", "canceled"}
    for run_id, status, count in rows:
        counts = grouped.setdefault(
            str(run_id),
            {
                "total": 0,
                "pending": 0,
                "synthesizing": 0,
                "complete": 0,
                "failed": 0,
                "canceled": 0,
                "other": 0,
            },
        )
        normalized_count = int(count)
        counts["total"] += normalized_count
        normalized_status = status if isinstance(status, str) else ""
        bucket = normalized_status if normalized_status in known_statuses else "other"
        counts[bucket] += normalized_count
    return {run_id: AdminVoiceCounts(**counts) for run_id, counts in grouped.items()}


def _run_sort_columns(sort: str) -> tuple[Any, Any]:
    if sort == "created_at":
        return LiveRunRecord.created_at.asc(), LiveRunRecord.run_id.asc()
    if sort == "-created_at":
        return LiveRunRecord.created_at.desc(), LiveRunRecord.run_id.desc()
    if sort == "updated_at":
        return LiveRunRecord.updated_at.asc(), LiveRunRecord.run_id.asc()
    return LiveRunRecord.updated_at.desc(), LiveRunRecord.run_id.desc()


def _clean_filter(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


_LIFECYCLE_EVENT_TYPES = {
    "run_created",
    "run_started",
    "game_started",
    "round_started",
    "phase_started",
    "game_completed",
    "game_failed",
    "run_stop_requested",
    "game_canceled",
}
_WARNING_EVENT_TYPES = {
    "model_request_failed",
    "model_retry_scheduled",
    "action_quality_warning",
}
_ACTIVITY_EVENT_TYPES = {
    "model_thinking_tick",
    "model_request_started",
    "model_response_delta",
    "model_response_received",
    "action_parsed",
    "action_requested",
    "judge_cue",
    "state_updated",
}
_KNOWN_EVENT_TYPES = _LIFECYCLE_EVENT_TYPES | _WARNING_EVENT_TYPES | _ACTIVITY_EVENT_TYPES
_SAFE_PHASES = {"night", "day", "vote", "summary"}


def _safe_event_rows(
    rows: list[AdminLiveRunEventRow],
    *,
    reveal_terminal_metadata: bool,
) -> list[AdminLiveRunEventRow]:
    safe_rows: list[AdminLiveRunEventRow] = []
    for row in rows:
        event_type = _safe_event_type(
            row.type,
            reveal_terminal_metadata=reveal_terminal_metadata,
        )
        safe_row = AdminLiveRunEventRow(
            event_id=row.event_id,
            type=event_type,
            round=_safe_event_round(row.round),
            phase=row.phase if row.phase in _SAFE_PHASES else None,
            actor=row.actor if reveal_terminal_metadata else None,
            action=row.action if reveal_terminal_metadata else None,
            created_at=row.created_at,
        )
        if (
            not reveal_terminal_metadata
            and event_type == "activity"
            and safe_rows
            and safe_rows[-1].type == "activity"
            and safe_rows[-1].round == safe_row.round
            and safe_rows[-1].phase == safe_row.phase
        ):
            safe_rows[-1] = safe_row
        else:
            safe_rows.append(safe_row)
    return safe_rows


def _safe_event_type(value: Any, *, reveal_terminal_metadata: bool) -> str:
    if not isinstance(value, str):
        return "unknown" if reveal_terminal_metadata else "activity"
    if value in _WARNING_EVENT_TYPES:
        return "runtime_warning"
    if reveal_terminal_metadata:
        return value if value in _KNOWN_EVENT_TYPES else "unknown"
    return value if value in _LIFECYCLE_EVENT_TYPES else "activity"


def _safe_event_round(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value if 0 <= value <= 1000 else None
