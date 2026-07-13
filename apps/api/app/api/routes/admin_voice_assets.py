from __future__ import annotations

from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Path as PathParameter, Query, Request, Response
from sqlalchemy.orm import Session

from app.admin.rbac import AdminPermission
from app.admin.audit import record_audit_event
from app.admin.voice_jobs import create_voice_generation_job
from app.admin.voice_assets import (
    get_admin_judge_voice_audio,
    list_admin_judge_voice_assets,
)
from app.api.admin.dependencies import AdminPrincipal, require_admin_csrf, require_admin_permission
from app.api.admin.errors import AdminAPIProblem, request_id_for
from app.api.schemas.admin_voice_assets import (
    AdminJudgeVoiceAvailability,
    AdminJudgeVoiceCategorySummary,
    AdminJudgeVoiceCoverage,
    AdminJudgeVoiceLineItem,
    AdminJudgeVoiceLineListResponse,
    AdminJudgeVoicePagination,
    AdminJudgeVoiceSort,
    AdminJudgeVoiceGenerationRequest,
    AdminJudgeVoiceJobResponse,
)
from app.core.config import settings
from app.db.session import get_db
from app.models.judge_voice_asset import JudgeVoiceGenerationJob
from app.werewolf.judge_voice_assets import DEFAULT_JUDGE_VOICE_ASSET_DIR


router = APIRouter()
LINE_ID_RE = r"^[a-z0-9_]{1,80}$"


def get_admin_judge_voice_asset_dir() -> Path:
    return DEFAULT_JUDGE_VOICE_ASSET_DIR


@router.get("/judge-voice-lines", response_model=AdminJudgeVoiceLineListResponse)
def list_judge_voice_lines(
    request: Request,
    response: Response,
    db: Annotated[Session, Depends(get_db)],
    asset_dir: Annotated[Path, Depends(get_admin_judge_voice_asset_dir)],
    _principal: Annotated[
        AdminPrincipal,
        Depends(require_admin_permission(AdminPermission.VOICE_READ)),
    ],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    q: Annotated[str | None, Query(max_length=120)] = None,
    category: Annotated[str | None, Query(min_length=1, max_length=80)] = None,
    availability: AdminJudgeVoiceAvailability | None = None,
    sort: AdminJudgeVoiceSort = "category",
) -> AdminJudgeVoiceLineListResponse:
    result = list_admin_judge_voice_assets(
        db,
        asset_dir=asset_dir,
        audio_format=settings.ark_tts_judge_asset_audio_format,
        page=page,
        page_size=page_size,
        query_text=q,
        category=category,
        availability=availability,
        sort=sort,
    )
    _set_private_headers(request, response)
    return AdminJudgeVoiceLineListResponse(
        audio_format=settings.ark_tts_judge_asset_audio_format,
        sample_rate=settings.ark_tts_judge_asset_sample_rate,
        storage_mode=result.storage_mode,
        coverage=AdminJudgeVoiceCoverage(
            total=result.asset_total,
            available=result.available_total,
            missing=result.missing_total,
            byte_total=result.byte_total,
        ),
        categories=[
            AdminJudgeVoiceCategorySummary(**category_summary.__dict__)
            for category_summary in result.categories
        ],
        items=[_line_item(asset) for asset in result.records],
        pagination=AdminJudgeVoicePagination(
            page=result.page,
            page_size=result.page_size,
            total=result.total,
            pages=result.pages,
        ),
    )


@router.get("/judge-voice-lines/{line_id}/audio")
def get_judge_voice_line_audio(
    line_id: Annotated[str, PathParameter(pattern=LINE_ID_RE)],
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    asset_dir: Annotated[Path, Depends(get_admin_judge_voice_asset_dir)],
    _principal: Annotated[
        AdminPrincipal,
        Depends(require_admin_permission(AdminPermission.VOICE_READ)),
    ],
) -> Response:
    try:
        audio = get_admin_judge_voice_audio(
            db,
            asset_dir=asset_dir,
            audio_format=settings.ark_tts_judge_asset_audio_format,
            line_id=line_id,
        )
    except OSError as exc:
        raise AdminAPIProblem(
            status_code=503,
            code="admin_voice_asset_unavailable",
            title="Voice asset unavailable",
            detail="The requested voice asset cannot be read right now.",
        ) from exc
    if audio is None:
        raise _not_found()
    return Response(
        content=audio.content,
        media_type=audio.mime_type,
        headers=_private_headers(request),
    )


@router.post("/judge-voice-generation-jobs", response_model=AdminJudgeVoiceJobResponse, status_code=202)
def create_judge_voice_generation_job(
    payload: AdminJudgeVoiceGenerationRequest,
    request: Request,
    response: Response,
    db: Annotated[Session, Depends(get_db)],
    principal: Annotated[AdminPrincipal, Depends(require_admin_csrf)],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=8, max_length=80)],
) -> AdminJudgeVoiceJobResponse:
    required = (
        AdminPermission.VOICE_REGENERATE_ALL
        if payload.mode == "all"
        else AdminPermission.VOICE_GENERATE_MISSING
    )
    if required not in principal.permissions:
        raise AdminAPIProblem(
            status_code=403,
            code="admin_permission_denied",
            title="Permission denied",
            detail=f"The '{required.value}' permission is required.",
        )
    try:
        job, created = create_voice_generation_job(
            db,
            actor_user_id=principal.user.id,
            mode=payload.mode,
            line_ids=payload.line_ids,
            idempotency_key=idempotency_key,
        )
    except ValueError as exc:
        raise AdminAPIProblem(
            status_code=409,
            code="admin_idempotency_conflict",
            title="Idempotency conflict",
            detail="This idempotency key was already used for a different request.",
        ) from exc
    if created:
        record_audit_event(
            db,
            request=request,
            actor_user_id=principal.user.id,
            action="admin.judge_voice_generation.enqueue",
            resource_type="judge_voice_generation_job",
            resource_id=job.id,
            result="success",
            after={"mode": job.mode, "line_count": len(job.requested_line_ids or [])},
        )
    db.commit()
    db.refresh(job)
    if not created:
        response.status_code = 200
    _set_private_headers(request, response)
    return _job_response(job)


@router.get("/jobs/{job_id}", response_model=AdminJudgeVoiceJobResponse)
def get_judge_voice_generation_job(
    job_id: Annotated[str, PathParameter(pattern=r"^[0-9a-f-]{36}$")],
    request: Request,
    response: Response,
    db: Annotated[Session, Depends(get_db)],
    _principal: Annotated[
        AdminPrincipal,
        Depends(require_admin_permission(AdminPermission.VOICE_READ)),
    ],
) -> AdminJudgeVoiceJobResponse:
    job = db.get(JudgeVoiceGenerationJob, job_id)
    if job is None:
        raise AdminAPIProblem(
            status_code=404,
            code="admin_voice_job_not_found",
            title="Voice generation job not found",
            detail="The requested voice generation job does not exist.",
        )
    _set_private_headers(request, response)
    return _job_response(job)


def _job_response(job: JudgeVoiceGenerationJob) -> AdminJudgeVoiceJobResponse:
    return AdminJudgeVoiceJobResponse(
        id=job.id,
        mode=job.mode,
        status=job.status,
        requested_line_ids=job.requested_line_ids,
        total_count=job.total_count,
        processed_count=job.processed_count,
        generated_count=job.generated_count,
        skipped_count=job.skipped_count,
        failed_count=job.failed_count,
        error_code=job.error_code,
        created_at=job.created_at.isoformat(),
        started_at=job.started_at.isoformat() if job.started_at else None,
        completed_at=job.completed_at.isoformat() if job.completed_at else None,
    )


def _line_item(asset) -> AdminJudgeVoiceLineItem:
    return AdminJudgeVoiceLineItem(
        id=asset.id,
        text=asset.text,
        category=asset.category,
        used=asset.used,
        available=asset.exists,
        byte_size=asset.byte_size if asset.exists else None,
        template_id=asset.template_id,
        seat_number=asset.seat_number,
        subtitle_cue_count=asset.subtitle_cue_count,
        audio_url=(
            f"/api/v1/admin/judge-voice-lines/{asset.id}/audio"
            if asset.exists
            else None
        ),
    )


def _not_found() -> AdminAPIProblem:
    return AdminAPIProblem(
        status_code=404,
        code="admin_voice_asset_not_found",
        title="Voice asset not found",
        detail="The requested judge voice asset does not exist.",
    )


def _private_headers(request: Request) -> dict[str, str]:
    return {
        "Cache-Control": "no-store",
        "Pragma": "no-cache",
        "X-Content-Type-Options": "nosniff",
        "X-Request-ID": request_id_for(request),
    }


def _set_private_headers(request: Request, response: Response) -> None:
    for key, value in _private_headers(request).items():
        response.headers[key] = value
