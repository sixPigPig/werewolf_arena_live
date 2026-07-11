from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Path, Query, Request, Response
from sqlalchemy import func, select
from sqlalchemy.exc import OperationalError, ProgrammingError
from sqlalchemy.orm import Session

from app.admin.audit import record_audit_event
from app.admin.live_runs import (
    AdminLiveRunDetailData,
    AdminLiveRunEventRow,
    AdminLiveRunRow,
    AdminVoiceCounts,
    get_admin_live_run_detail,
    list_admin_live_runs,
)
from app.admin.rbac import AdminPermission
from app.api.admin.dependencies import AdminPrincipal, require_admin_permission
from app.api.admin.errors import AdminAPIProblem, request_id_for
from app.api.schemas.admin_live_runs import (
    AdminLiveRunDebugResponse,
    AdminLiveRunDetailResponse,
    AdminLiveRunEventSummary,
    AdminLiveRunGameSummary,
    AdminLiveRunListItem,
    AdminLiveRunListResponse,
    AdminLiveRunRuleSetSummary,
    AdminLiveRunSort,
    AdminLiveRunStatus,
    AdminLiveRunVoiceCounts,
)
from app.db.session import get_db
from app.models.live import LiveRunRecord, VoiceUtteranceRecord
from app.werewolf.rules import get_rule_set


router = APIRouter()
RecoverableDatabaseError = (OperationalError, ProgrammingError)
RUN_ID_RE = r"^run_[0-9a-f]{12}$"


@router.get("/live-runs", response_model=AdminLiveRunListResponse)
def list_live_runs(
    request: Request,
    response: Response,
    db: Annotated[Session, Depends(get_db)],
    _principal: Annotated[
        AdminPrincipal,
        Depends(require_admin_permission(AdminPermission.RUNS_READ)),
    ],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    q: Annotated[str | None, Query(max_length=120)] = None,
    status: AdminLiveRunStatus | None = None,
    rule_set_id: Annotated[str | None, Query(min_length=1, max_length=80)] = None,
    created_from: datetime | None = None,
    created_to: datetime | None = None,
    sort: AdminLiveRunSort = "-updated_at",
) -> AdminLiveRunListResponse:
    normalized_from = _query_datetime(created_from, "created_from")
    normalized_to = _query_datetime(created_to, "created_to")
    if normalized_from is not None and normalized_to is not None and normalized_from > normalized_to:
        raise _invalid_filter("created_from must be earlier than or equal to created_to.")
    try:
        result = list_admin_live_runs(
            db,
            page=page,
            page_size=page_size,
            query_text=q,
            status=status,
            rule_set_id=rule_set_id,
            created_from=normalized_from,
            created_to=normalized_to,
            sort=sort,
        )
    except RecoverableDatabaseError as exc:
        raise _database_unavailable() from exc
    _set_private_headers(request, response)
    return AdminLiveRunListResponse(
        items=[
            _list_item(
                record,
                event_count=result.event_counts.get(record.run_id, 0),
                last_event_at=result.last_event_at.get(record.run_id),
                voice_counts=result.voice_counts.get(record.run_id, AdminVoiceCounts()),
            )
            for record in result.records
        ],
        pagination={
            "page": result.page,
            "page_size": result.page_size,
            "total": result.total,
            "pages": result.pages,
        },
    )


@router.get("/live-runs/{run_id}", response_model=AdminLiveRunDetailResponse)
def get_live_run(
    run_id: Annotated[str, Path(pattern=RUN_ID_RE)],
    request: Request,
    response: Response,
    db: Annotated[Session, Depends(get_db)],
    _principal: Annotated[
        AdminPrincipal,
        Depends(require_admin_permission(AdminPermission.RUNS_READ)),
    ],
) -> AdminLiveRunDetailResponse:
    try:
        detail = get_admin_live_run_detail(db, run_id)
    except RecoverableDatabaseError as exc:
        raise _database_unavailable() from exc
    if detail is None:
        raise _not_found()
    _set_private_headers(request, response)
    return _detail_response(detail)


@router.get("/live-runs/{run_id}/debug", response_model=AdminLiveRunDebugResponse)
def get_live_run_debug(
    run_id: Annotated[str, Path(pattern=RUN_ID_RE)],
    request: Request,
    response: Response,
    db: Annotated[Session, Depends(get_db)],
    principal: Annotated[
        AdminPrincipal,
        Depends(require_admin_permission(AdminPermission.RUNS_DEBUG_READ)),
    ],
) -> AdminLiveRunDebugResponse:
    try:
        run_row = db.execute(
            select(LiveRunRecord.run_id, LiveRunRecord.error).where(
                LiveRunRecord.run_id == run_id
            )
        ).one_or_none()
        if run_row is None:
            raise _not_found()
        failed_voice_filter = (
            VoiceUtteranceRecord.run_id == run_id,
            VoiceUtteranceRecord.status == "failed",
        )
        voice_error_filter = (
            *failed_voice_filter,
            VoiceUtteranceRecord.error_message.is_not(None),
            VoiceUtteranceRecord.error_message != "",
        )
        voice_error_total = int(
            db.scalar(
                select(func.count())
                .select_from(VoiceUtteranceRecord)
                .where(*failed_voice_filter)
            )
            or 0
        )
        voice_error_rows = list(
            db.execute(
                select(
                    VoiceUtteranceRecord.utterance_id,
                    VoiceUtteranceRecord.error_message,
                )
                .where(*voice_error_filter)
                .order_by(
                    VoiceUtteranceRecord.created_at.desc(),
                    VoiceUtteranceRecord.utterance_id.desc(),
                )
                .limit(20)
            )
        )
        voice_errors = [
            {"utterance_id": _safe_text(utterance_id, max_length=40), "error": summary}
            for utterance_id, error in voice_error_rows
            if (summary := _summarize_error(error)) is not None
        ]
        result = AdminLiveRunDebugResponse(
            run_id=run_id,
            run_error=_summarize_error(run_row.error),
            voice_error_total=voice_error_total,
            voice_errors=voice_errors,
            truncated=voice_error_total > len(voice_errors),
        )
        record_audit_event(
            db,
            request=request,
            actor_user_id=principal.user.id,
            action="admin.live_run.debug.read",
            resource_type="live_run",
            resource_id=run_id,
            result="success",
            after={
                "run_error_present": result.run_error is not None,
                "voice_error_total": voice_error_total,
                "voice_error_returned": len(voice_errors),
                "truncated": result.truncated,
            },
        )
        db.commit()
    except AdminAPIProblem:
        raise
    except RecoverableDatabaseError as exc:
        db.rollback()
        raise _database_unavailable() from exc
    _set_private_headers(request, response)
    return result


def _detail_response(detail: AdminLiveRunDetailData) -> AdminLiveRunDetailResponse:
    item = _list_item(
        detail.record,
        event_count=detail.event_count,
        last_event_at=detail.last_event_at,
        voice_counts=detail.voice_counts,
    )
    return AdminLiveRunDetailResponse(
        **item.model_dump(),
        recent_events=[_event_summary(event) for event in detail.recent_events],
    )


def _list_item(
    record: AdminLiveRunRow,
    *,
    event_count: int,
    last_event_at: datetime | None,
    voice_counts: AdminVoiceCounts,
) -> AdminLiveRunListItem:
    game = _game_summary(record)
    return AdminLiveRunListItem(
        run_id=_safe_text(record.run_id, max_length=32),
        session_id=_safe_text(record.session_id, max_length=32),
        status=record.status,
        winner=(
            _optional_text(record.winner, max_length=80)
            if record.can_reveal_event_identity
            else None
        ),
        villager_model=_optional_text(record.villager_model, max_length=120),
        werewolf_model=_optional_text(record.werewolf_model, max_length=120),
        max_rounds=max(0, int(record.max_rounds or 0)),
        rule_set=_rule_set_summary(record.rule_set_id),
        created_at=_as_utc(record.created_at),
        started_at=_optional_utc(record.started_at),
        completed_at=_optional_utc(record.completed_at),
        updated_at=_as_utc(record.updated_at),
        event_count=max(0, event_count),
        last_activity_at=_activity_at(record, last_event_at),
        is_stale=_is_stale(record, last_event_at),
        voice_counts=AdminLiveRunVoiceCounts(**voice_counts.__dict__),
        has_error=record.has_error,
        game=game,
    )


def _event_summary(event: AdminLiveRunEventRow) -> AdminLiveRunEventSummary:
    return AdminLiveRunEventSummary(
        event_id=max(0, int(event.event_id)),
        type=_safe_text(event.type, max_length=80),
        round=_event_round(event.round),
        phase=_optional_text(event.phase, max_length=40),
        actor=_optional_text(event.actor, max_length=120),
        action=_optional_text(event.action, max_length=80),
        created_at=_as_utc(event.created_at),
    )


def _game_summary(record: AdminLiveRunRow) -> AdminLiveRunGameSummary | None:
    if record.game_status not in {"complete", "partial"} or record.game_resumable is None:
        return None
    return AdminLiveRunGameSummary(
        status=record.game_status,
        resumable=record.game_resumable,
        terminal=record.game_is_terminal,
    )


def _rule_set_summary(rule_set_id_value: Any) -> AdminLiveRunRuleSetSummary | None:
    rule_set_id = _optional_text(rule_set_id_value, max_length=80)
    if rule_set_id is None:
        return None
    try:
        rule_set = get_rule_set(rule_set_id)
    except KeyError:
        return AdminLiveRunRuleSetSummary(
            id=rule_set_id,
            name=rule_set_id,
            player_count=None,
        )
    return AdminLiveRunRuleSetSummary(
        id=rule_set.id,
        name=rule_set.name,
        player_count=rule_set.player_count,
    )


def _activity_at(record: AdminLiveRunRow, last_event_at: datetime | None) -> datetime:
    return _optional_utc(last_event_at) or _as_utc(record.created_at)


def _is_stale(record: AdminLiveRunRow, last_event_at: datetime | None) -> bool:
    if record.status not in {"queued", "running"}:
        return False
    activity_at = _activity_at(record, last_event_at)
    return (_utc_now() - activity_at).total_seconds() > 60


def _utc_now() -> datetime:
    return datetime.now(tz=UTC)


def _summarize_error(value: Any) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    lowered = value.casefold()
    if "maximum rounds" in lowered:
        return "Maximum rounds exceeded"
    if "timeout" in lowered or "timed out" in lowered:
        return "Upstream request timed out"
    if "rate limit" in lowered or "too many requests" in lowered or " 429" in lowered:
        return "Upstream rate limit exceeded"
    if "401" in lowered or "403" in lowered or "unauthorized" in lowered:
        return "Upstream authentication or authorization failed"
    if "connection" in lowered or "network" in lowered or "dns" in lowered:
        return "Upstream connection failed"
    if "json" in lowered or "parse" in lowered or "schema" in lowered:
        return "Model response validation failed"
    if "tts" in lowered or "voice" in lowered or "audio" in lowered:
        return "Voice synthesis failed"
    return "Runtime failure (details withheld)"


def _safe_text(value: Any, *, max_length: int) -> str:
    if not isinstance(value, str):
        return ""
    return value.replace("\x00", "").strip()[:max_length]


def _event_round(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value if 0 <= value <= 1000 else None


def _optional_text(value: Any, *, max_length: int) -> str | None:
    text = _safe_text(value, max_length=max_length)
    return text or None


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _optional_utc(value: datetime | None) -> datetime | None:
    return _as_utc(value) if value is not None else None


def _query_datetime(value: datetime | None, field: str) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        raise _invalid_filter(f"{field} must include a timezone offset.")
    return value.astimezone(UTC)


def _set_private_headers(request: Request, response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    response.headers["X-Request-ID"] = request_id_for(request)


def _not_found() -> AdminAPIProblem:
    return AdminAPIProblem(
        status_code=404,
        code="admin_live_run_not_found",
        title="Live run not found",
        detail="The requested live run does not exist.",
    )


def _invalid_filter(detail: str) -> AdminAPIProblem:
    return AdminAPIProblem(
        status_code=422,
        code="admin_live_run_filter_invalid",
        title="Invalid live run filter",
        detail=detail,
    )


def _database_unavailable() -> AdminAPIProblem:
    return AdminAPIProblem(
        status_code=503,
        code="admin_live_run_database_unavailable",
        title="Live run database unavailable",
        detail="Live run data is temporarily unavailable.",
    )
