from __future__ import annotations

from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, Path as PathParameter, Query, Request, Response
from sqlalchemy.orm import Session

from app.admin.rbac import AdminPermission
from app.admin.voice_assets import (
    get_admin_judge_voice_audio,
    list_admin_judge_voice_assets,
)
from app.api.admin.dependencies import AdminPrincipal, require_admin_permission
from app.api.admin.errors import AdminAPIProblem, request_id_for
from app.api.schemas.admin_voice_assets import (
    AdminJudgeVoiceAvailability,
    AdminJudgeVoiceCategorySummary,
    AdminJudgeVoiceCoverage,
    AdminJudgeVoiceLineItem,
    AdminJudgeVoiceLineListResponse,
    AdminJudgeVoicePagination,
    AdminJudgeVoiceSort,
)
from app.core.config import settings
from app.db.session import get_db
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


def _line_item(asset) -> AdminJudgeVoiceLineItem:
    return AdminJudgeVoiceLineItem(
        id=asset.id,
        text=asset.text,
        category=asset.category,
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
