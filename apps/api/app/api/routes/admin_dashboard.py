from __future__ import annotations

from datetime import UTC, datetime
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
    AdminOverviewJobs,
    AdminOverviewProfiles,
    AdminOverviewResponse,
    AdminSearchResponse,
    AdminSearchResult,
    AdminSettingsAuthentication,
    AdminSettingsCompatibility,
    AdminSettingsResponse,
    AdminSettingsWorkers,
)
from app.api.schemas.common import PaginationResponse
from app.core.config import settings
from app.db.session import get_db
from app.models.judge_voice_asset import JudgeVoiceGenerationJob
from app.models.virtual_player_profile import VirtualPlayerProfile


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
        job_counts = _group_counts(db, JudgeVoiceGenerationJob.status)
        profiles_total = sum(profile_counts.values())
        jobs_total = sum(job_counts.values())
        featured_total = _count(
            db,
            VirtualPlayerProfile,
            VirtualPlayerProfile.featured.is_(True),
        )
    except SQLAlchemyError as exc:
        raise _dashboard_unavailable() from exc

    alerts = _overview_alerts(
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
        jobs=AdminOverviewJobs(
            total=jobs_total,
            queued=job_counts.get("queued", 0),
            running=job_counts.get("running", 0),
            completed=job_counts.get("completed", 0),
            failed=job_counts.get("failed", 0),
        ),
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
            legacy_voice_generation_enabled=(
                settings.legacy_judge_voice_generation_enabled
            ),
        ),
        workers=AdminSettingsWorkers(
            judge_voice_poll_seconds=settings.judge_voice_worker_poll_seconds,
            judge_voice_heartbeat_seconds=settings.judge_voice_worker_heartbeat_seconds,
            judge_voice_probe_max_age_seconds=(
                settings.judge_voice_worker_probe_max_age_seconds
            ),
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
    q: Annotated[str, Query(min_length=1, max_length=80)],
) -> AdminSearchResponse:
    query = q.strip()
    if len(query) < 1:
        raise AdminAPIProblem(
            status_code=422,
            code="admin_search_query_too_short",
            title="Search query too short",
            detail="Search queries must contain at least one non-space character.",
        )
    starts_with = f"{_escape_like(query)}%"
    contains = f"%{_escape_like(query)}%"
    items: list[AdminSearchResult] = []
    try:
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
    failed_jobs: int,
    queued_jobs: int,
) -> list[AdminOverviewAlert]:
    alerts: list[AdminOverviewAlert] = []
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
