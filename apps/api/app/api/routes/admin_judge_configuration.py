from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.admin.audit import record_audit_event
from app.admin.rbac import AdminPermission
from app.api.admin.dependencies import AdminPrincipal, require_admin_csrf, require_admin_permission
from app.api.admin.errors import AdminAPIProblem, request_id_for
from app.api.schemas.admin_judge_configuration import (
    AdminJudgeConfigurationRequest,
    AdminJudgeConfigurationResponse,
    AdminJudgeModelOption,
    AdminJudgeSpeakerOption,
)
from app.core.config import settings
from app.db.session import get_db
from app.judge_configuration import JUDGE_CONFIGURATION_ID, runtime_judge_configuration
from app.models.judge_configuration import JudgeConfigurationRecord
from app.models.model_configuration import ModelConfigurationRecord
from app.werewolf.tts_speaker_catalog import (
    TtsSpeakerCatalogUnavailable,
    VolcengineTtsSpeakerCatalog,
    tts_speaker_catalog,
)


router = APIRouter()
logger = logging.getLogger(__name__)


def get_judge_tts_speaker_catalog() -> VolcengineTtsSpeakerCatalog:
    return tts_speaker_catalog


@router.get(
    "/judge-configuration",
    response_model=AdminJudgeConfigurationResponse,
)
def get_admin_judge_configuration(
    request: Request,
    response: Response,
    db: Annotated[Session, Depends(get_db)],
    _principal: Annotated[
        AdminPrincipal,
        Depends(require_admin_permission(AdminPermission.SETTINGS_READ)),
    ],
    catalog: Annotated[
        VolcengineTtsSpeakerCatalog,
        Depends(get_judge_tts_speaker_catalog),
    ],
) -> AdminJudgeConfigurationResponse:
    try:
        result = _configuration_response(db, catalog=catalog)
    except SQLAlchemyError as exc:
        logger.exception("Judge configuration query failed")
        raise _configuration_unavailable() from exc
    _set_private_headers(request, response)
    return result


@router.patch(
    "/judge-configuration",
    response_model=AdminJudgeConfigurationResponse,
)
def update_admin_judge_configuration(
    payload: AdminJudgeConfigurationRequest,
    request: Request,
    response: Response,
    db: Annotated[Session, Depends(get_db)],
    principal: Annotated[AdminPrincipal, Depends(require_admin_csrf)],
    catalog: Annotated[
        VolcengineTtsSpeakerCatalog,
        Depends(get_judge_tts_speaker_catalog),
    ],
) -> AdminJudgeConfigurationResponse:
    _require_manage(principal)
    try:
        current = runtime_judge_configuration(
            db,
            default_model_id=settings.live_v2_model_id,
            default_tts_speaker=settings.live_v2_tts_judge_speaker,
        )
        existing = db.get(JudgeConfigurationRecord, JUDGE_CONFIGURATION_ID)
        _validate_model(db, payload=payload, current_model_id=current.model_id)
    except SQLAlchemyError as exc:
        raise _configuration_unavailable() from exc
    if payload.expected_version != current.version:
        raise AdminAPIProblem(
            status_code=409,
            code="admin_judge_configuration_conflict",
            title="Judge configuration conflict",
            detail="法官配置已被其他管理员更新，请刷新后重试。",
        )
    _validate_speaker(
        catalog,
        requested=payload.tts_speaker,
        current=current.tts_speaker,
    )
    before = _audit_value(current)
    try:
        if existing is None:
            existing = JudgeConfigurationRecord(
                id=JUDGE_CONFIGURATION_ID,
                model_provider=payload.model_provider,
                model_id=payload.model_id,
                tts_speaker=payload.tts_speaker,
                version=1,
            )
            db.add(existing)
        else:
            existing.model_provider = payload.model_provider
            existing.model_id = payload.model_id
            existing.tts_speaker = payload.tts_speaker
            existing.version += 1
        db.flush()
        after = {
            "model_provider": existing.model_provider,
            "model_id": existing.model_id,
            "tts_speaker": existing.tts_speaker,
            "version": existing.version,
        }
        record_audit_event(
            db,
            request=request,
            actor_user_id=principal.user.id,
            action="admin.judge_configuration.update",
            resource_type="judge_configuration",
            resource_id=JUDGE_CONFIGURATION_ID,
            result="success",
            before=before,
            after=after,
        )
        db.commit()
        db.refresh(existing)
        result = _configuration_response(db, catalog=catalog)
    except SQLAlchemyError as exc:
        db.rollback()
        raise _configuration_unavailable() from exc
    _set_private_headers(request, response)
    return result


def _configuration_response(
    db: Session,
    *,
    catalog: VolcengineTtsSpeakerCatalog,
) -> AdminJudgeConfigurationResponse:
    current = runtime_judge_configuration(
        db,
        default_model_id=settings.live_v2_model_id,
        default_tts_speaker=settings.live_v2_tts_judge_speaker,
    )
    record = db.get(JudgeConfigurationRecord, JUDGE_CONFIGURATION_ID)
    model_rows = list(
        db.scalars(
            select(ModelConfigurationRecord)
            .where(
                ModelConfigurationRecord.provider == "agent_plan",
                ModelConfigurationRecord.available.is_(True),
                ModelConfigurationRecord.enabled.is_(True),
            )
            .order_by(ModelConfigurationRecord.display_name, ModelConfigurationRecord.model_id)
        )
    )
    models = [
        AdminJudgeModelOption(
            provider="agent_plan",
            model_id=item.model_id,
            label=item.display_name or item.model_id,
        )
        for item in model_rows
    ]
    if current.model_id not in {item.model_id for item in models}:
        models.insert(
            0,
            AdminJudgeModelOption(
                provider="agent_plan",
                model_id=current.model_id,
                label=f"当前模型 · {current.model_id}",
            ),
        )
    speaker_catalog_available = True
    try:
        speaker_rows = catalog.list_supported(resource_id=settings.ark_tts_resource_id)
        speakers = [
            AdminJudgeSpeakerOption(voice_type=item.voice_type, name=item.name)
            for item in speaker_rows
        ]
    except TtsSpeakerCatalogUnavailable:
        speaker_catalog_available = False
        speakers = []
    if current.tts_speaker not in {item.voice_type for item in speakers}:
        speakers.insert(
            0,
            AdminJudgeSpeakerOption(
                voice_type=current.tts_speaker,
                name="当前音色",
            ),
        )
    return AdminJudgeConfigurationResponse(
        model_provider="agent_plan",
        model_id=current.model_id,
        tts_speaker=current.tts_speaker,
        version=current.version,
        source="database" if record is not None else "environment",
        updated_at=record.updated_at if record is not None else None,
        models=models,
        speakers=speakers,
        speaker_catalog_available=speaker_catalog_available,
        tts_resource_id=settings.ark_tts_resource_id,
    )


def _validate_model(
    db: Session,
    *,
    payload: AdminJudgeConfigurationRequest,
    current_model_id: str,
) -> None:
    record = db.get(ModelConfigurationRecord, (payload.model_provider, payload.model_id))
    if record is not None and record.available and record.enabled:
        return
    if payload.model_id == current_model_id:
        return
    raise AdminAPIProblem(
        status_code=422,
        code="admin_judge_model_unavailable",
        title="Judge model unavailable",
        detail="请选择模型管理中已启用且可用的 Agent Plan 模型。",
    )


def _validate_speaker(
    catalog: VolcengineTtsSpeakerCatalog,
    *,
    requested: str,
    current: str,
) -> None:
    try:
        supported = {
            item.voice_type
            for item in catalog.list_supported(resource_id=settings.ark_tts_resource_id)
        }
    except TtsSpeakerCatalogUnavailable as exc:
        if requested == current:
            return
        raise AdminAPIProblem(
            status_code=503,
            code="admin_judge_speakers_unavailable",
            title="Judge speakers unavailable",
            detail="音色目录暂时不可用，当前只能保留原音色。",
        ) from exc
    if requested not in supported:
        raise AdminAPIProblem(
            status_code=422,
            code="admin_judge_speaker_invalid",
            title="Judge speaker invalid",
            detail="请选择当前 TTS 资源支持的音色。",
        )


def _audit_value(value) -> dict[str, object]:
    return {
        "model_provider": value.model_provider,
        "model_id": value.model_id,
        "tts_speaker": value.tts_speaker,
        "version": value.version,
    }


def _require_manage(principal: AdminPrincipal) -> None:
    if AdminPermission.SETTINGS_MANAGE not in principal.permissions:
        raise AdminAPIProblem(
            status_code=403,
            code="admin_permission_denied",
            title="Permission denied",
            detail="The 'settings.manage' permission is required.",
        )


def _configuration_unavailable() -> AdminAPIProblem:
    return AdminAPIProblem(
        status_code=503,
        code="admin_judge_configuration_unavailable",
        title="Judge configuration unavailable",
        detail="法官配置暂时不可用。",
    )


def _set_private_headers(request: Request, response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    response.headers["X-Request-ID"] = request_id_for(request)
