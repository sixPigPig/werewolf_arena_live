from __future__ import annotations

from datetime import UTC, datetime, timedelta
import math
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy import func, or_, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.admin.rbac import AdminPermission
from app.api.admin.dependencies import AdminPrincipal, require_admin_permission
from app.api.admin.errors import AdminAPIProblem, request_id_for
from app.api.schemas.admin_dashboard import (
    AdminJobItem,
    AdminJobListResponse,
    AdminOverviewAlert,
    AdminOverviewGames,
    AdminOverviewJobs,
    AdminOverviewProfiles,
    AdminOverviewResponse,
    AdminOverviewRuns,
    AdminSearchResponse,
    AdminSearchResult,
    AdminSettingsAuthentication,
    AdminSettingsCompatibility,
    AdminSettingsLiveRuns,
    AdminSettingsResponse,
    AdminSettingsWorkers,
)
from app.api.schemas.common import PaginationResponse
from app.core.config import settings
from app.db.session import get_db
from app.models.game_session import GameSessionRecord
from app.models.judge_voice_asset import JudgeVoiceGenerationJob
from app.models.live import LiveRunRecord
from app.models.virtual_player_profile import VirtualPlayerProfile
from app.werewolf.worker_telemetry import live_run_reaper_is_alive


router = APIRouter()
JobStatus = Literal["queued", "running", "completed", "failed"]


@router.get("/overview", response_model=AdminOverviewResponse)
def get_admin_overview(
    request: Request,
    response: Response,
    db: Annotated[Session, Depends(get_db)],
    _principal: Annotated[
        AdminPrincipal,
        Depends(require_admin_permission(AdminPermission.OVERVIEW_READ)),
    ],
) -> AdminOverviewResponse:
    try:
        now = datetime.now(tz=UTC)
        profile_counts = _group_counts(db, VirtualPlayerProfile.status)
        game_counts = _group_counts(db, GameSessionRecord.status)
        run_counts = _group_counts(db, LiveRunRecord.status)
        job_counts = _group_counts(db, JudgeVoiceGenerationJob.status)
        stale_before = now - timedelta(seconds=settings.live_run_reaper_stale_grace_seconds)
        stale_filter = (
            LiveRunRecord.status.in_(("queued", "running")),
            (
                (LiveRunRecord.lease_expires_at <= stale_before)
                | (
                    LiveRunRecord.lease_expires_at.is_(None)
                    & (LiveRunRecord.created_at <= stale_before)
                )
            ),
        )
        stale_total = _count(db, LiveRunRecord, *stale_filter)
        exhausted_total = _count(
            db,
            LiveRunRecord,
            *stale_filter,
            LiveRunRecord.recovery_attempts >= settings.live_run_reaper_max_attempts,
        )
        reaper_up = live_run_reaper_is_alive(
            db,
            max_age_seconds=settings.live_run_reaper_probe_max_age_seconds,
        )
        profiles_total = sum(profile_counts.values())
        games_total = sum(game_counts.values())
        runs_total = sum(run_counts.values())
        jobs_total = sum(job_counts.values())
        failed_games = sum(
            count for status, count in game_counts.items() if status not in {"complete"}
        )
        featured_total = _count(
            db,
            VirtualPlayerProfile,
            VirtualPlayerProfile.featured.is_(True),
        )
        resumable_total = _count(
            db,
            GameSessionRecord,
            GameSessionRecord.resumable.is_(True),
        )
    except SQLAlchemyError as exc:
        raise _dashboard_unavailable() from exc

    alerts = _overview_alerts(
        reaper_up=reaper_up,
        stale_total=stale_total,
        exhausted_total=exhausted_total,
        failed_jobs=job_counts.get("failed", 0),
        queued_jobs=job_counts.get("queued", 0),
    )
    _set_private_headers(request, response)
    return AdminOverviewResponse(
        generated_at=now.isoformat(),
        environment=settings.app_environment,
        profiles=AdminOverviewProfiles(
            total=profiles_total,
            draft=profile_counts.get("draft", 0),
            published=profile_counts.get("published", 0),
            archived=profile_counts.get("archived", 0),
            featured=featured_total,
        ),
        games=AdminOverviewGames(
            total=games_total,
            complete=game_counts.get("complete", 0),
            incomplete=failed_games,
            resumable=resumable_total,
        ),
        runs=AdminOverviewRuns(
            total=runs_total,
            queued=run_counts.get("queued", 0),
            running=run_counts.get("running", 0),
            completed=run_counts.get("completed", 0),
            canceled=run_counts.get("canceled", 0),
            failed=run_counts.get("failed", 0),
            stale=stale_total,
            recovery_exhausted=exhausted_total,
        ),
        jobs=AdminOverviewJobs(
            total=jobs_total,
            queued=job_counts.get("queued", 0),
            running=job_counts.get("running", 0),
            completed=job_counts.get("completed", 0),
            failed=job_counts.get("failed", 0),
        ),
        reaper_up=reaper_up,
        alerts=alerts,
    )

@router.get("/jobs", response_model=AdminJobListResponse)
def list_admin_jobs(
    request: Request,
    response: Response,
    db: Annotated[Session, Depends(get_db)],
    _principal: Annotated[
        AdminPrincipal,
        Depends(require_admin_permission(AdminPermission.VOICE_READ)),
    ],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    status: Annotated[JobStatus | None, Query()] = None,
) -> AdminJobListResponse:
    filters = [JudgeVoiceGenerationJob.status == status] if status else []
    try:
        total = _count(db, JudgeVoiceGenerationJob, *filters)
        jobs = list(
            db.scalars(
                select(JudgeVoiceGenerationJob)
                .where(*filters)
                .order_by(
                    JudgeVoiceGenerationJob.created_at.desc(),
                    JudgeVoiceGenerationJob.id.desc(),
                )
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        )
    except SQLAlchemyError as exc:
        raise _dashboard_unavailable() from exc
    _set_private_headers(request, response)
    return AdminJobListResponse(
        items=[_job_item(job) for job in jobs],
        pagination=PaginationResponse(
            page=page,
            page_size=page_size,
            total=total,
            pages=math.ceil(total / page_size) if total else 0,
        ),
    )


@router.get("/settings", response_model=AdminSettingsResponse)
def get_admin_settings(
    request: Request,
    response: Response,
    _principal: Annotated[
        AdminPrincipal,
        Depends(require_admin_permission(AdminPermission.SETTINGS_READ)),
    ],
) -> AdminSettingsResponse:
    _set_private_headers(request, response)
    return AdminSettingsResponse(
        environment=settings.app_environment,
        api_prefix=settings.api_v1_prefix,
        tts_enabled=settings.ark_tts_enabled,
        authentication=AdminSettingsAuthentication(
            oidc_enabled=settings.admin_oidc_enabled,
            development_login_enabled=settings.admin_dev_auth_enabled,
            secure_admin_cookie=settings.admin_session_cookie_secure,
            secure_public_cookie=settings.public_session_cookie_secure,
            admin_session_ttl_seconds=settings.admin_session_ttl_seconds,
            public_session_ttl_seconds=settings.public_session_ttl_seconds,
        ),
        compatibility=AdminSettingsCompatibility(
            legacy_content_writes_enabled=(
                settings.legacy_player_profile_content_writes_enabled
            ),
            legacy_favorite_writes_enabled=(
                settings.legacy_player_profile_favorite_writes_enabled
            ),
            legacy_voice_generation_enabled=(
                settings.legacy_judge_voice_generation_enabled
            ),
        ),
        workers=AdminSettingsWorkers(
            judge_voice_poll_seconds=settings.judge_voice_worker_poll_seconds,
            reaper_poll_seconds=settings.live_run_reaper_poll_seconds,
            reaper_stale_grace_seconds=settings.live_run_reaper_stale_grace_seconds,
            reaper_max_attempts=settings.live_run_reaper_max_attempts,
            reaper_probe_max_age_seconds=settings.live_run_reaper_probe_max_age_seconds,
        ),
        live_runs=AdminSettingsLiveRuns(
            lease_seconds=settings.live_run_lease_seconds,
            heartbeat_seconds=settings.live_run_heartbeat_seconds,
            event_poll_seconds=settings.live_run_event_poll_seconds,
        ),
    )


@router.get("/search", response_model=AdminSearchResponse)
def search_admin_resources(
    request: Request,
    response: Response,
    db: Annotated[Session, Depends(get_db)],
    principal: Annotated[
        AdminPrincipal,
        Depends(require_admin_permission(AdminPermission.OVERVIEW_READ)),
    ],
    q: Annotated[str, Query(min_length=2, max_length=80)],
) -> AdminSearchResponse:
    query = q.strip()
    if len(query) < 2:
        raise AdminAPIProblem(
            status_code=422,
            code="admin_search_query_too_short",
            title="Search query too short",
            detail="Search queries must contain at least two non-space characters.",
        )
    starts_with = f"{_escape_like(query)}%"
    contains = f"%{_escape_like(query)}%"
    items: list[AdminSearchResult] = []
    try:
        if AdminPermission.RUNS_READ in principal.permissions:
            runs = db.scalars(
                select(LiveRunRecord)
                .where(
                    or_(
                        LiveRunRecord.run_id.ilike(starts_with, escape="\\"),
                        LiveRunRecord.session_id.ilike(starts_with, escape="\\"),
                    )
                )
                .order_by(LiveRunRecord.updated_at.desc())
                .limit(5)
            )
            items.extend(
                AdminSearchResult(
                    type="run",
                    id=run.run_id,
                    label=run.run_id,
                    description=f"对局 {run.session_id}",
                    status=run.status,
                    href=f"/operations/runs/{run.run_id}",
                )
                for run in runs
            )
        if AdminPermission.GAMES_READ in principal.permissions:
            games = db.scalars(
                select(GameSessionRecord)
                .where(GameSessionRecord.session_id.ilike(starts_with, escape="\\"))
                .order_by(GameSessionRecord.updated_at.desc())
                .limit(5)
            )
            items.extend(
                AdminSearchResult(
                    type="game",
                    id=game.session_id,
                    label=game.session_id,
                    description=f"{game.round_count} 轮对局",
                    status=game.status,
                    href=f"/operations/games/{game.session_id}",
                )
                for game in games
            )
        if AdminPermission.PLAYERS_READ in principal.permissions:
            profiles = db.scalars(
                select(VirtualPlayerProfile)
                .where(
                    or_(
                        VirtualPlayerProfile.id.ilike(starts_with, escape="\\"),
                        VirtualPlayerProfile.display_name.ilike(contains, escape="\\"),
                    )
                )
                .order_by(VirtualPlayerProfile.updated_at.desc())
                .limit(5)
            )
            items.extend(
                AdminSearchResult(
                    type="player",
                    id=profile.id,
                    label=profile.display_name,
                    description=f"玩家 ID {profile.id}",
                    status=profile.status,
                    href=f"/content/players/{profile.id}",
                )
                for profile in profiles
            )
        if AdminPermission.VOICE_READ in principal.permissions:
            jobs = db.scalars(
                select(JudgeVoiceGenerationJob)
                .where(JudgeVoiceGenerationJob.id.ilike(starts_with, escape="\\"))
                .order_by(JudgeVoiceGenerationJob.created_at.desc())
                .limit(5)
            )
            items.extend(
                AdminSearchResult(
                    type="job",
                    id=job.id,
                    label=f"语音任务 {job.id[:8]}",
                    description="生成缺失语音" if job.mode == "missing" else "重新生成全部",
                    status=job.status,
                    href=f"/system/jobs?job={job.id}",
                )
                for job in jobs
            )
    except SQLAlchemyError as exc:
        raise _dashboard_unavailable() from exc
    _set_private_headers(request, response)
    return AdminSearchResponse(query=query, items=items[:20])


def _overview_alerts(
    *,
    reaper_up: bool,
    stale_total: int,
    exhausted_total: int,
    failed_jobs: int,
    queued_jobs: int,
) -> list[AdminOverviewAlert]:
    alerts: list[AdminOverviewAlert] = []
    if not reaper_up:
        alerts.append(
            AdminOverviewAlert(
                code="live_run_reaper_down",
                severity="critical",
                title="自动恢复进程没有新鲜心跳",
                detail="孤儿运行不会被自动认领，请检查 live-run reaper。",
                count=1,
                href="/operations/runs",
            )
        )
    if exhausted_total:
        alerts.append(
            AdminOverviewAlert(
                code="live_run_recovery_exhausted",
                severity="critical",
                title="运行自动恢复次数已耗尽",
                detail="需要人工检查失败原因并决定是否从检查点恢复。",
                count=exhausted_total,
                href="/operations/runs?worker_state=stale",
            )
        )
    elif stale_total:
        alerts.append(
            AdminOverviewAlert(
                code="live_run_stale",
                severity="warning",
                title="存在等待自动恢复的运行",
                detail="运行租约已经过期，reaper 将按退避策略处理。",
                count=stale_total,
                href="/operations/runs?worker_state=stale",
            )
        )
    if failed_jobs:
        alerts.append(
            AdminOverviewAlert(
                code="voice_jobs_failed",
                severity="warning",
                title="存在失败的语音生成任务",
                detail="任务只显示稳定错误分类，凭据和供应商原始响应不会公开。",
                count=failed_jobs,
                href="/system/jobs?status=failed",
            )
        )
    if queued_jobs:
        alerts.append(
            AdminOverviewAlert(
                code="voice_jobs_queued",
                severity="info",
                title="语音任务正在等待处理",
                detail="持续 worker 启动后会按创建时间领取任务。",
                count=queued_jobs,
                href="/system/jobs?status=queued",
            )
        )
    return alerts


def _job_item(job: JudgeVoiceGenerationJob) -> AdminJobItem:
    return AdminJobItem(
        id=job.id,
        type="judge_voice_generation",
        mode=job.mode,
        status=job.status,
        total_count=job.total_count,
        processed_count=job.processed_count,
        generated_count=job.generated_count,
        failed_count=job.failed_count,
        error_code=job.error_code,
        created_at=job.created_at.isoformat(),
        started_at=job.started_at.isoformat() if job.started_at else None,
        completed_at=job.completed_at.isoformat() if job.completed_at else None,
    )


def _group_counts(db: Session, column) -> dict[str, int]:
    return {
        str(status): int(count)
        for status, count in db.execute(
            select(column, func.count()).group_by(column)
        )
    }


def _count(db: Session, model, *filters: object) -> int:
    return int(db.scalar(select(func.count()).select_from(model).where(*filters)) or 0)


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _set_private_headers(request: Request, response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    response.headers["X-Request-ID"] = request_id_for(request)


def _dashboard_unavailable() -> AdminAPIProblem:
    return AdminAPIProblem(
        status_code=503,
        code="admin_dashboard_unavailable",
        title="Admin dashboard unavailable",
        detail="Operational summaries are temporarily unavailable.",
    )
