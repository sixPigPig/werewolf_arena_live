from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import Select, and_, case, exists, func, or_, select
from sqlalchemy.orm import Session

from app.models.game_session import GameReplayPayload, GameSessionRecord
from app.models.live import LiveEventRecord, LiveRunRecord, VoiceUtteranceRecord


@dataclass(frozen=True)
class AdminGameListResult:
    records: list[GameSessionRecord]
    latest_runs: dict[str, AdminGameRunRow]
    event_counts: dict[str, int]
    page: int
    page_size: int
    total: int
    pages: int


@dataclass(frozen=True)
class AdminGameDetailData:
    record: GameSessionRecord
    state: dict[str, Any]
    runs: list[AdminGameRunRow]
    event_counts: dict[str, int]
    recent_events: list[AdminGameEventRow]
    run_count: int
    event_count: int
    failed_voice_count: int


@dataclass(frozen=True)
class AdminGameRunRow:
    run_id: str
    session_id: str
    status: str
    villager_model: str
    werewolf_model: str
    max_rounds: int
    rule_set_id: str
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    has_error: bool


@dataclass(frozen=True)
class AdminGameEventRow:
    run_id: str
    event_id: int
    type: str
    round: int | None
    phase: str | None
    actor: str | None
    action: str | None
    created_at: datetime


def list_admin_games(
    db: Session,
    *,
    page: int,
    page_size: int,
    query_text: str | None,
    status: str | None,
    winner: str | None,
    rule_set_id: str | None,
    run_status: str | None,
    created_from: datetime | None,
    created_to: datetime | None,
    sort: str,
) -> AdminGameListResult:
    query: Select[tuple[GameSessionRecord]] = select(GameSessionRecord)
    terminal_game = and_(
        GameSessionRecord.status == "complete",
        GameSessionRecord.resumable.is_(False),
    )
    normalized_query = _clean_filter(query_text)
    if normalized_query is not None:
        pattern = f"%{_escape_like(normalized_query)}%"
        matching_run = exists(
            select(LiveRunRecord.run_id).where(
                LiveRunRecord.session_id == GameSessionRecord.session_id,
                or_(
                    LiveRunRecord.run_id.ilike(pattern, escape="\\"),
                    and_(
                        terminal_game,
                        or_(
                            LiveRunRecord.villager_model.ilike(pattern, escape="\\"),
                            LiveRunRecord.werewolf_model.ilike(pattern, escape="\\"),
                        ),
                    ),
                ),
            )
        )
        query = query.where(
            or_(
                GameSessionRecord.session_id.ilike(pattern, escape="\\"),
                and_(
                    terminal_game,
                    GameSessionRecord.winner.ilike(pattern, escape="\\"),
                ),
                matching_run,
            )
        )
    if status is not None:
        query = query.where(GameSessionRecord.status == status)
    if winner is not None:
        query = query.where(
            terminal_game,
            GameSessionRecord.winner == winner.strip(),
        )
    if rule_set_id is not None:
        normalized_rule_set_id = rule_set_id.strip()
        query = query.where(
            GameSessionRecord.rule_set["id"].as_string() == normalized_rule_set_id
        )
    if run_status is not None:
        latest_run_status = (
            select(LiveRunRecord.status)
            .where(LiveRunRecord.session_id == GameSessionRecord.session_id)
            .order_by(LiveRunRecord.created_at.desc(), LiveRunRecord.run_id.desc())
            .limit(1)
            .correlate(GameSessionRecord)
            .scalar_subquery()
        )
        query = query.where(latest_run_status == run_status)
    if created_from is not None:
        query = query.where(GameSessionRecord.created_at >= created_from)
    if created_to is not None:
        query = query.where(GameSessionRecord.created_at <= created_to)

    total = int(db.scalar(select(func.count()).select_from(query.subquery())) or 0)
    pages = (total + page_size - 1) // page_size if total else 0
    query = query.order_by(*_game_sort_columns(sort)).offset((page - 1) * page_size).limit(page_size)
    records = list(db.scalars(query))

    session_ids = [record.session_id for record in records]
    latest_runs = _latest_runs_for_sessions(db, session_ids)
    runs = list(latest_runs.values())
    event_counts = _event_counts_for_runs(db, [run.run_id for run in runs])
    return AdminGameListResult(
        records=records,
        latest_runs=latest_runs,
        event_counts=event_counts,
        page=page,
        page_size=page_size,
        total=total,
        pages=pages,
    )


def get_admin_game_detail(db: Session, session_id: str) -> AdminGameDetailData | None:
    record = db.get(GameSessionRecord, session_id)
    if record is None:
        return None
    state = db.scalar(
        select(GameReplayPayload.state).where(GameReplayPayload.session_id == session_id)
    )
    if not isinstance(state, dict):
        state = {}
    run_count = int(
        db.scalar(
            select(func.count())
            .select_from(LiveRunRecord)
            .where(LiveRunRecord.session_id == session_id)
        )
        or 0
    )
    runs = [
        _run_row(row)
        for row in db.execute(
            select(LiveRunRecord)
            .with_only_columns(*_run_summary_columns())
            .where(LiveRunRecord.session_id == session_id)
            .order_by(LiveRunRecord.created_at.desc(), LiveRunRecord.run_id.desc())
            .limit(100)
        )
    ]
    event_counts = _event_counts_for_runs(db, [run.run_id for run in runs])
    reveal_terminal_metadata = record.status == "complete" and not record.resumable
    recent_desc: list[AdminGameEventRow] = []
    if reveal_terminal_metadata:
        recent_desc = [
            AdminGameEventRow(*row)
            for row in db.execute(
                select(LiveEventRecord)
                .with_only_columns(
                    LiveEventRecord.run_id,
                    LiveEventRecord.event_id,
                    LiveEventRecord.type,
                    LiveEventRecord.round,
                    LiveEventRecord.phase,
                    LiveEventRecord.actor,
                    LiveEventRecord.action,
                    LiveEventRecord.created_at,
                )
                .where(LiveEventRecord.session_id == session_id)
                .order_by(
                    LiveEventRecord.created_at.desc(),
                    LiveEventRecord.run_id.desc(),
                    LiveEventRecord.event_id.desc(),
                )
                .limit(50)
            )
        ]
    event_count = int(
        db.scalar(
            select(func.count())
            .select_from(LiveEventRecord)
            .where(LiveEventRecord.session_id == session_id)
        )
        or 0
    )
    failed_voice_count = int(
        db.scalar(
            select(func.count())
            .select_from(VoiceUtteranceRecord)
            .where(
                VoiceUtteranceRecord.session_id == session_id,
                VoiceUtteranceRecord.status == "failed",
            )
        )
        or 0
    )
    return AdminGameDetailData(
        record=record,
        state=state,
        runs=runs,
        event_counts=event_counts,
        recent_events=list(reversed(recent_desc)),
        run_count=run_count,
        event_count=event_count,
        failed_voice_count=failed_voice_count,
    )


def _latest_runs_for_sessions(
    db: Session,
    session_ids: list[str],
) -> dict[str, AdminGameRunRow]:
    if not session_ids:
        return {}
    ranked_runs = (
        select(
            LiveRunRecord.run_id.label("run_id"),
            func.row_number()
            .over(
                partition_by=LiveRunRecord.session_id,
                order_by=(LiveRunRecord.created_at.desc(), LiveRunRecord.run_id.desc()),
            )
            .label("run_rank"),
        )
        .where(LiveRunRecord.session_id.in_(session_ids))
        .subquery()
    )
    runs = [
        _run_row(row)
        for row in db.execute(
            select(*_run_summary_columns())
            .join(ranked_runs, ranked_runs.c.run_id == LiveRunRecord.run_id)
            .where(ranked_runs.c.run_rank == 1)
            .order_by(LiveRunRecord.session_id.asc())
        )
    ]
    return {run.session_id: run for run in runs}


def _run_summary_columns() -> tuple[Any, ...]:
    return (
        LiveRunRecord.run_id,
        LiveRunRecord.session_id,
        LiveRunRecord.status,
        LiveRunRecord.villager_model,
        LiveRunRecord.werewolf_model,
        LiveRunRecord.max_rounds,
        LiveRunRecord.rule_set_id,
        LiveRunRecord.created_at,
        LiveRunRecord.started_at,
        LiveRunRecord.completed_at,
        case(
            (
                and_(LiveRunRecord.error.is_not(None), LiveRunRecord.error != ""),
                True,
            ),
            else_=False,
        ).label("has_error"),
    )


def _run_row(row: Any) -> AdminGameRunRow:
    return AdminGameRunRow(
        run_id=row.run_id,
        session_id=row.session_id,
        status=row.status,
        villager_model=row.villager_model,
        werewolf_model=row.werewolf_model,
        max_rounds=row.max_rounds,
        rule_set_id=row.rule_set_id,
        created_at=row.created_at,
        started_at=row.started_at,
        completed_at=row.completed_at,
        has_error=bool(row.has_error),
    )


def _event_counts_for_runs(db: Session, run_ids: list[str]) -> dict[str, int]:
    if not run_ids:
        return {}
    rows = db.execute(
        select(LiveEventRecord.run_id, func.count())
        .where(LiveEventRecord.run_id.in_(run_ids))
        .group_by(LiveEventRecord.run_id)
    )
    return {str(run_id): int(count) for run_id, count in rows}


def _game_sort_columns(sort: str) -> tuple[Any, Any]:
    if sort == "created_at":
        return GameSessionRecord.created_at.asc(), GameSessionRecord.session_id.asc()
    if sort == "updated_at":
        return GameSessionRecord.updated_at.asc(), GameSessionRecord.session_id.asc()
    if sort == "-updated_at":
        return GameSessionRecord.updated_at.desc(), GameSessionRecord.session_id.desc()
    return GameSessionRecord.created_at.desc(), GameSessionRecord.session_id.desc()


def _clean_filter(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
