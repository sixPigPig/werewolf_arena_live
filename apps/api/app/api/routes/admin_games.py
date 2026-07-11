from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Path, Query, Request, Response
from sqlalchemy import select
from sqlalchemy.exc import OperationalError, ProgrammingError
from sqlalchemy.orm import Session

from app.admin.audit import record_audit_event
from app.admin.games import (
    AdminGameDetailData,
    AdminGameEventRow,
    AdminGameRunRow,
    get_admin_game_detail,
    list_admin_games,
)
from app.admin.rbac import AdminPermission
from app.api.admin.dependencies import AdminPrincipal, require_admin_permission
from app.api.admin.errors import AdminAPIProblem, request_id_for
from app.api.schemas.admin_games import (
    AdminGameDebugResponse,
    AdminGameDetailResponse,
    AdminGameEventSummary,
    AdminGameListItem,
    AdminGameListResponse,
    AdminGameRunSummary,
    AdminGameRunStatus,
    AdminGameSort,
    AdminGameStatus,
)
from app.db.session import get_db
from app.models.game_session import GameReplayPayload, GameSessionRecord
from app.models.live import LiveRunRecord
from app.werewolf.replay import SESSION_ID_RE


router = APIRouter()
RecoverableDatabaseError = (OperationalError, ProgrammingError)


@router.get("/games", response_model=AdminGameListResponse)
def list_games(
    request: Request,
    response: Response,
    db: Annotated[Session, Depends(get_db)],
    _principal: Annotated[
        AdminPrincipal,
        Depends(require_admin_permission(AdminPermission.GAMES_READ)),
    ],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    q: Annotated[str | None, Query(max_length=120)] = None,
    status: AdminGameStatus | None = None,
    winner: Annotated[str | None, Query(min_length=1, max_length=80)] = None,
    rule_set_id: Annotated[str | None, Query(min_length=1, max_length=80)] = None,
    run_status: AdminGameRunStatus | None = None,
    created_from: datetime | None = None,
    created_to: datetime | None = None,
    sort: AdminGameSort = "-created_at",
) -> AdminGameListResponse:
    normalized_from = _query_datetime(created_from, "created_from")
    normalized_to = _query_datetime(created_to, "created_to")
    if normalized_from is not None and normalized_to is not None and normalized_from > normalized_to:
        raise _invalid_filter("created_from must be earlier than or equal to created_to.")
    try:
        result = list_admin_games(
            db,
            page=page,
            page_size=page_size,
            query_text=q,
            status=status,
            winner=winner,
            rule_set_id=rule_set_id,
            run_status=run_status,
            created_from=normalized_from,
            created_to=normalized_to,
            sort=sort,
        )
    except RecoverableDatabaseError as exc:
        raise _database_unavailable() from exc
    _set_private_headers(request, response)
    return AdminGameListResponse(
        items=[
            _list_item(
                record,
                latest_run=result.latest_runs.get(record.session_id),
                event_counts=result.event_counts,
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


@router.get("/games/{session_id}", response_model=AdminGameDetailResponse)
def get_game(
    session_id: Annotated[str, Path(pattern=SESSION_ID_RE)],
    request: Request,
    response: Response,
    db: Annotated[Session, Depends(get_db)],
    _principal: Annotated[
        AdminPrincipal,
        Depends(require_admin_permission(AdminPermission.GAMES_READ)),
    ],
) -> AdminGameDetailResponse:
    try:
        detail = get_admin_game_detail(db, session_id)
    except RecoverableDatabaseError as exc:
        raise _database_unavailable() from exc
    if detail is None:
        raise _not_found()
    _set_private_headers(request, response)
    return _detail_response(detail)


@router.get("/games/{session_id}/debug", response_model=AdminGameDebugResponse)
def get_game_debug(
    session_id: Annotated[str, Path(pattern=SESSION_ID_RE)],
    request: Request,
    response: Response,
    db: Annotated[Session, Depends(get_db)],
    principal: Annotated[
        AdminPrincipal,
        Depends(require_admin_permission(AdminPermission.GAMES_DEBUG_READ)),
    ],
) -> AdminGameDebugResponse:
    try:
        record = db.get(GameSessionRecord, session_id)
        if record is None:
            raise _not_found()
        state = db.scalar(
            select(GameReplayPayload.state).where(GameReplayPayload.session_id == session_id)
        )
        run_error_rows = list(
            db.execute(
                select(LiveRunRecord.run_id, LiveRunRecord.error)
                .where(
                    LiveRunRecord.session_id == session_id,
                    LiveRunRecord.error.is_not(None),
                    LiveRunRecord.error != "",
                )
                .order_by(LiveRunRecord.created_at.desc(), LiveRunRecord.run_id.desc())
                .limit(20)
            )
        )
        game_error = _summarize_error(
            state.get("error_message") if isinstance(state, dict) else None
        )
        run_errors = [
            {"run_id": run_id, "error": summary}
            for run_id, error in run_error_rows
            if (summary := _summarize_error(error)) is not None
        ][:20]
        result = AdminGameDebugResponse(
            session_id=session_id,
            game_error=game_error,
            run_errors=run_errors,
        )
        record_audit_event(
            db,
            request=request,
            actor_user_id=principal.user.id,
            action="admin.game.debug.read",
            resource_type="game_session",
            resource_id=session_id,
            result="success",
            after={
                "game_error_present": game_error is not None,
                "run_error_count": len(run_errors),
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


def _detail_response(detail: AdminGameDetailData) -> AdminGameDetailResponse:
    state = detail.state
    reveal_terminal_metadata = _is_terminal_game(detail.record)
    latest_run = detail.runs[0] if detail.runs else None
    item = _list_item(
        detail.record,
        latest_run=latest_run,
        event_counts=detail.event_counts,
    )
    recent_events = (
        [_event_summary(event) for event in detail.recent_events]
        if reveal_terminal_metadata
        else []
    )
    return AdminGameDetailResponse(
        **item.model_dump(),
        players=_player_summaries(
            state,
            reveal_terminal_metadata=reveal_terminal_metadata,
        ),
        rounds=_round_summaries(
            state,
            reveal_terminal_metadata=reveal_terminal_metadata,
        ),
        runs=[
            _run_summary(
                run,
                detail.event_counts,
                reveal_models=reveal_terminal_metadata,
            )
            for run in detail.runs
        ],
        recent_events=recent_events,
        diagnostics={
            "run_count": detail.run_count,
            "event_count": detail.event_count,
            "failed_voice_count": detail.failed_voice_count,
            "last_event": recent_events[-1] if recent_events else None,
        },
    )


def _list_item(
    record: GameSessionRecord,
    *,
    latest_run: AdminGameRunRow | None,
    event_counts: dict[str, int],
) -> AdminGameListItem:
    rule_set = _rule_set_summary(record.rule_set)
    if rule_set is None and latest_run is not None:
        rule_set = _rule_set_summary(
            {"id": latest_run.rule_set_id, "name": latest_run.rule_set_id}
        )
    return AdminGameListItem(
        session_id=record.session_id,
        status=_safe_text(record.status, max_length=20),
        winner=(
            _optional_text(record.winner, max_length=80)
            if _is_terminal_game(record)
            else None
        ),
        round_count=max(0, int(record.round_count or 0)),
        resumable=bool(record.resumable),
        rule_set=rule_set,
        created_at=_as_utc(record.created_at),
        updated_at=_as_utc(record.updated_at),
        latest_run=(
            _run_summary(
                latest_run,
                event_counts,
                reveal_models=_is_terminal_game(record),
            )
            if latest_run is not None
            else None
        ),
    )


def _is_terminal_game(record: GameSessionRecord) -> bool:
    return record.status == "complete" and not record.resumable


def _run_summary(
    run: AdminGameRunRow,
    event_counts: dict[str, int],
    *,
    reveal_models: bool = True,
) -> AdminGameRunSummary:
    return AdminGameRunSummary(
        run_id=run.run_id,
        status=_safe_text(run.status, max_length=20),
        villager_model=(
            _optional_text(run.villager_model, max_length=120) if reveal_models else None
        ),
        werewolf_model=(
            _optional_text(run.werewolf_model, max_length=120) if reveal_models else None
        ),
        max_rounds=max(0, int(run.max_rounds or 0)),
        created_at=_as_utc(run.created_at),
        started_at=_optional_utc(run.started_at),
        completed_at=_optional_utc(run.completed_at),
        event_count=event_counts.get(run.run_id, 0),
        has_error=run.has_error,
    )


def _event_summary(event: AdminGameEventRow) -> AdminGameEventSummary:
    return AdminGameEventSummary(
        run_id=event.run_id,
        event_id=max(0, int(event.event_id)),
        type=_safe_text(event.type, max_length=80),
        round=max(0, int(event.round)) if event.round is not None else None,
        phase=_optional_text(event.phase, max_length=40),
        actor=_optional_text(event.actor, max_length=120),
        action=_optional_text(event.action, max_length=80),
        created_at=_as_utc(event.created_at),
    )


def _player_summaries(
    state: dict[str, Any],
    *,
    reveal_terminal_metadata: bool,
) -> list[dict[str, Any]]:
    value = state.get("players")
    if not isinstance(value, list):
        return []
    players: list[dict[str, Any]] = []
    for seat, item in enumerate(value[:24], start=1):
        if not isinstance(item, dict):
            continue
        players.append(
            {
                "seat": seat,
                "name": _safe_text(item.get("name"), max_length=120),
                "profile_id": _optional_text(item.get("profile_id"), max_length=36),
                "model": (
                    _optional_text(item.get("model"), max_length=120)
                    if reveal_terminal_metadata
                    else None
                ),
                "role": (
                    _optional_text(item.get("role"), max_length=80)
                    if reveal_terminal_metadata
                    else None
                ),
                "personality_id": _safe_text(item.get("personality_id"), max_length=40),
                "appearance_id": _safe_text(item.get("appearance_id"), max_length=40),
                "avatar_image_url": _safe_avatar_url(item.get("avatar_image_url")),
                "tags": _string_list(item.get("tags"), max_items=8, max_length=20),
            }
        )
    return players


def _round_summaries(
    state: dict[str, Any],
    *,
    reveal_terminal_metadata: bool,
) -> list[dict[str, Any]]:
    value = state.get("rounds")
    if not isinstance(value, list):
        return []
    rounds: list[dict[str, Any]] = []
    for item in value[:100]:
        if (
            not isinstance(item, dict)
            or not isinstance(item.get("number"), int)
            or isinstance(item.get("number"), bool)
        ):
            continue
        if not reveal_terminal_metadata and item.get("success") is not True:
            continue
        rounds.append(
            {
                "number": max(0, item["number"]),
                "success": bool(item.get("success")),
                "players": _string_list(item.get("players"), max_items=24, max_length=120),
                "public_summary": _safe_text(item.get("public_summary"), max_length=2000),
                "night_deaths": _death_summaries(
                    item.get("night_deaths"),
                    reveal_causes=reveal_terminal_metadata,
                ),
                "day_deaths": _death_summaries(
                    item.get("day_deaths"),
                    reveal_causes=reveal_terminal_metadata,
                ),
                "exiled": _optional_text(item.get("exiled"), max_length=120),
                "hunter_shot": _optional_text(item.get("hunter_shot"), max_length=120),
                "idiot_revealed": _optional_text(item.get("idiot_revealed"), max_length=120),
                "sheriff": _optional_text(item.get("sheriff"), max_length=120),
                "votes": _votes_summary(item.get("votes")),
                "sheriff_elected": _optional_text(item.get("sheriff_elected"), max_length=120),
                "werewolf_self_exploded": _optional_text(
                    item.get("werewolf_self_exploded"),
                    max_length=120,
                ),
            }
        )
    return rounds


def _death_summaries(
    value: Any,
    *,
    reveal_causes: bool,
) -> list[dict[str, str | None]]:
    if not isinstance(value, list):
        return []
    result: list[dict[str, str | None]] = []
    for item in value[:24]:
        if (
            not isinstance(item, dict)
            or not isinstance(item.get("player"), str)
        ):
            continue
        result.append(
            {
                "player": _safe_text(item.get("player"), max_length=120),
                "cause": (
                    _optional_text(item.get("cause"), max_length=80)
                    if reveal_causes
                    else None
                ),
                "source": (
                    _optional_text(item.get("source"), max_length=120)
                    if reveal_causes
                    else None
                ),
            }
        )
    return result


def _votes_summary(value: Any) -> dict[str, str]:
    latest: Any = value
    if isinstance(value, list):
        latest = next((item for item in reversed(value) if isinstance(item, dict)), {})
    if not isinstance(latest, dict):
        return {}
    return {
        _safe_text(voter, max_length=120): _safe_text(target, max_length=120)
        for voter, target in list(latest.items())[:50]
        if isinstance(voter, str) and isinstance(target, str)
    }


def _rule_set_summary(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    rule_set_id = _optional_text(value.get("id"), max_length=80)
    name = _optional_text(value.get("name"), max_length=120)
    if rule_set_id is None and name is None:
        return None
    player_count = value.get("player_count")
    return {
        "id": rule_set_id or "",
        "name": name or rule_set_id or "",
        "player_count": (
            max(0, player_count)
            if isinstance(player_count, int) and not isinstance(player_count, bool)
            else None
        ),
    }


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
    return "Runtime failure (details withheld)"


def _safe_avatar_url(value: Any) -> str:
    text = _safe_text(value, max_length=500)
    if text.startswith("/api/v1/player-profiles/avatar-assets/"):
        return text
    return ""


def _string_list(value: Any, *, max_items: int, max_length: int) -> list[str]:
    if not isinstance(value, list):
        return []
    return [
        _safe_text(item, max_length=max_length)
        for item in value[:max_items]
        if isinstance(item, str)
    ]


def _safe_text(value: Any, *, max_length: int) -> str:
    if not isinstance(value, str):
        return ""
    return value.replace("\x00", "").strip()[:max_length]


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
        code="admin_game_not_found",
        title="Game not found",
        detail="The requested game session does not exist.",
    )


def _invalid_filter(detail: str) -> AdminAPIProblem:
    return AdminAPIProblem(
        status_code=422,
        code="admin_game_filter_invalid",
        title="Invalid game filter",
        detail=detail,
    )


def _database_unavailable() -> AdminAPIProblem:
    return AdminAPIProblem(
        status_code=503,
        code="admin_game_database_unavailable",
        title="Game database unavailable",
        detail="Game data is temporarily unavailable.",
    )
