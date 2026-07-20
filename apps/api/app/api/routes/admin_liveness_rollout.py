from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.admin.audit import record_audit_event
from app.admin.rbac import AdminPermission
from app.api.admin.dependencies import AdminPrincipal, require_admin_csrf, require_admin_permission
from app.api.admin.errors import AdminAPIProblem, request_id_for
from app.api.schemas.admin_liveness_rollout import (
    AdminLivenessExperienceOption,
    AdminLivenessRolloutResponse,
    AdminLivenessRolloutUpdateRequest,
)
from app.core.config import settings
from app.db.session import get_db
from app.werewolf.liveness_rollout import (
    AVAILABLE_LIVENESS_EXPERIENCES,
    LivenessRolloutConfig,
    LivenessRolloutConflict,
    get_liveness_rollout_config,
    update_liveness_rollout_config,
)


router = APIRouter()


@router.get("/liveness-rollout", response_model=AdminLivenessRolloutResponse)
def get_admin_liveness_rollout(
    request: Request,
    response: Response,
    db: Annotated[Session, Depends(get_db)],
    _principal: Annotated[
        AdminPrincipal,
        Depends(require_admin_permission(AdminPermission.SETTINGS_READ)),
    ],
) -> AdminLivenessRolloutResponse:
    try:
        config = _get_config(db)
    except (SQLAlchemyError, ValueError) as exc:
        raise _rollout_unavailable() from exc
    _set_private_headers(request, response)
    return _response(config)


@router.put("/liveness-rollout", response_model=AdminLivenessRolloutResponse)
def update_admin_liveness_rollout(
    payload: AdminLivenessRolloutUpdateRequest,
    request: Request,
    response: Response,
    db: Annotated[Session, Depends(get_db)],
    principal: Annotated[AdminPrincipal, Depends(require_admin_csrf)],
) -> AdminLivenessRolloutResponse:
    _require_manage(principal)
    try:
        before = _get_config(db)
        config = update_liveness_rollout_config(
            db,
            expected_revision=payload.expected_revision,
            experience_revision=payload.experience_revision,
            experiment_id=payload.experiment_id,
            treatment_percent=payload.treatment_percent,
            updated_by_user_id=principal.user.id,
        )
    except LivenessRolloutConflict as exc:
        db.rollback()
        raise AdminAPIProblem(
            status_code=409,
            code="admin_liveness_rollout_conflict",
            title="Rollout configuration changed",
            detail="灰度配置已被其他管理员更新，请刷新页面后再保存。",
            extensions={"current_revision": exc.current_revision},
        ) from exc
    except ValueError as exc:
        db.rollback()
        raise AdminAPIProblem(
            status_code=422,
            code="admin_liveness_rollout_invalid",
            title="Invalid rollout configuration",
            detail=str(exc),
        ) from exc
    except SQLAlchemyError as exc:
        db.rollback()
        raise _rollout_unavailable() from exc

    record_audit_event(
        db,
        request=request,
        actor_user_id=principal.user.id,
        action="admin.liveness_rollout.update",
        resource_type="liveness_rollout",
        resource_id="default",
        result="success",
        reason=payload.change_reason,
        before=_audit_value(before),
        after=_audit_value(config),
    )
    try:
        db.commit()
    except SQLAlchemyError as exc:
        db.rollback()
        raise _rollout_unavailable() from exc
    _set_private_headers(request, response)
    return _response(config)


def _get_config(db: Session) -> LivenessRolloutConfig:
    return get_liveness_rollout_config(
        db,
        fallback_experiment_id=settings.werewolf_liveness_experiment_id,
        fallback_treatment_percent=settings.werewolf_liveness_rollout_percent,
    )


def _response(config: LivenessRolloutConfig) -> AdminLivenessRolloutResponse:
    return AdminLivenessRolloutResponse(
        revision=config.revision,
        experience_revision=config.experience_revision,
        experiment_id=config.experiment_id,
        treatment_percent=config.treatment_percent,
        control_percent=100 - config.treatment_percent,
        source=config.source,
        effective_scope="new_sessions_only",
        updated_at=config.updated_at,
        available_experiences=[
            AdminLivenessExperienceOption(**option.__dict__)
            for option in AVAILABLE_LIVENESS_EXPERIENCES
        ],
    )


def _audit_value(config: LivenessRolloutConfig) -> dict[str, object]:
    return {
        "revision": config.revision,
        "experience_revision": config.experience_revision,
        "experiment_id": config.experiment_id,
        "treatment_percent": config.treatment_percent,
        "source": config.source,
    }


def _require_manage(principal: AdminPrincipal) -> None:
    if AdminPermission.SETTINGS_MANAGE not in principal.permissions:
        raise AdminAPIProblem(
            status_code=403,
            code="admin_permission_denied",
            title="Permission denied",
            detail="The 'settings.manage' permission is required.",
        )


def _rollout_unavailable() -> AdminAPIProblem:
    return AdminAPIProblem(
        status_code=503,
        code="admin_liveness_rollout_unavailable",
        title="Rollout configuration unavailable",
        detail="灰度配置存储暂时不可用。",
    )


def _set_private_headers(request: Request, response: Response) -> None:
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["X-Request-Id"] = request_id_for(request)
