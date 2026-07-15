from __future__ import annotations

from datetime import UTC, datetime
import logging
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Path, Request, Response
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.admin.audit import record_audit_event
from app.admin.rbac import AdminPermission
from app.api.admin.dependencies import AdminPrincipal, require_admin_csrf, require_admin_permission
from app.api.admin.errors import AdminAPIProblem, request_id_for
from app.api.schemas.admin_models import (
    AdminModelCatalogResponse,
    AdminModelConfigurationRequest,
    AdminModelItem,
    AdminModelSource,
)
from app.db.session import get_db
from app.model_catalog.service import (
    AgentPlanCatalogClient,
    CatalogSnapshot,
    DeepSeekCatalogClient,
    ModelCatalogUnavailable,
    ModelConfigurationConflict,
    get_catalog_snapshot,
    sync_agent_plan_catalog,
    update_model_configuration,
)
from app.models.model_configuration import ModelConfigurationRecord


router = APIRouter()
logger = logging.getLogger(__name__)
ProviderPath = Literal["agent_plan", "deepseek"]


def get_agent_plan_catalog_client() -> AgentPlanCatalogClient:
    return AgentPlanCatalogClient()


def get_deepseek_catalog_client() -> DeepSeekCatalogClient:
    return DeepSeekCatalogClient()


@router.get("/models", response_model=AdminModelCatalogResponse)
def list_admin_models(
    request: Request,
    response: Response,
    db: Annotated[Session, Depends(get_db)],
    deepseek_client: Annotated[DeepSeekCatalogClient, Depends(get_deepseek_catalog_client)],
    _principal: Annotated[
        AdminPrincipal,
        Depends(require_admin_permission(AdminPermission.SETTINGS_READ)),
    ],
) -> AdminModelCatalogResponse:
    try:
        snapshot = get_catalog_snapshot(db, deepseek_client=deepseek_client)
    except SQLAlchemyError as exc:
        logger.exception("Model catalog query failed")
        raise _catalog_unavailable() from exc
    _set_private_headers(request, response)
    return _catalog_response(snapshot)


@router.post("/models/agent-plan/sync", response_model=AdminModelCatalogResponse)
def sync_admin_agent_plan_models(
    request: Request,
    response: Response,
    db: Annotated[Session, Depends(get_db)],
    client: Annotated[AgentPlanCatalogClient, Depends(get_agent_plan_catalog_client)],
    principal: Annotated[AdminPrincipal, Depends(require_admin_csrf)],
) -> AdminModelCatalogResponse:
    _require_manage(principal)
    try:
        snapshot = sync_agent_plan_catalog(db, client=client)
    except ModelCatalogUnavailable as exc:
        record_audit_event(
            db,
            request=request,
            actor_user_id=principal.user.id,
            action="admin.model_catalog.sync",
            resource_type="model_catalog",
            resource_id="agent_plan",
            result="failed",
            reason=str(exc),
        )
        db.commit()
        raise AdminAPIProblem(
            status_code=503,
            code="admin_model_catalog_sync_unavailable",
            title="Model catalog sync unavailable",
            detail=str(exc),
        ) from exc
    except SQLAlchemyError as exc:
        db.rollback()
        raise _catalog_unavailable() from exc
    record_audit_event(
        db,
        request=request,
        actor_user_id=principal.user.id,
        action="admin.model_catalog.sync",
        resource_type="model_catalog",
        resource_id="agent_plan",
        result="success",
        after={
            "model_count": len(
                [
                    item
                    for item in snapshot.models
                    if item.provider == "agent_plan" and item.available
                ]
            )
        },
    )
    db.commit()
    _set_private_headers(request, response)
    return _catalog_response(snapshot)


@router.patch("/models/{provider}/{model_id}", status_code=204)
def configure_admin_model(
    payload: AdminModelConfigurationRequest,
    provider: ProviderPath,
    model_id: Annotated[str, Path(min_length=1, max_length=160)],
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    principal: Annotated[AdminPrincipal, Depends(require_admin_csrf)],
) -> Response:
    _require_manage(principal)
    existing = db.get(ModelConfigurationRecord, (provider, model_id))
    before = _record_audit_value(existing) if existing is not None else None
    try:
        record = update_model_configuration(
            db,
            provider=provider,
            model_id=model_id,
            enabled=payload.enabled,
            is_default=payload.is_default,
            parameters=payload.parameters.model_dump(exclude_none=True),
        )
    except LookupError as exc:
        raise AdminAPIProblem(
            status_code=404,
            code="admin_model_not_found",
            title="Model not found",
            detail="The requested model is not present in the current catalog.",
        ) from exc
    except ModelConfigurationConflict as exc:
        raise AdminAPIProblem(
            status_code=409,
            code="admin_model_configuration_conflict",
            title="Model configuration conflict",
            detail=str(exc),
        ) from exc
    except ValueError as exc:
        raise AdminAPIProblem(
            status_code=422,
            code="admin_model_configuration_invalid",
            title="Invalid model configuration",
            detail=str(exc),
        ) from exc
    record_audit_event(
        db,
        request=request,
        actor_user_id=principal.user.id,
        action="admin.model_configuration.update",
        resource_type="model_configuration",
        resource_id=f"{provider}:{model_id}",
        result="success",
        before=before,
        after=_record_audit_value(record),
    )
    try:
        db.commit()
    except SQLAlchemyError as exc:
        db.rollback()
        raise _catalog_unavailable() from exc
    return Response(status_code=204, headers=_private_headers(request))


def _catalog_response(snapshot: CatalogSnapshot) -> AdminModelCatalogResponse:
    return AdminModelCatalogResponse(
        generated_at=datetime.now(tz=UTC),
        sources=[AdminModelSource(**source.__dict__) for source in snapshot.sources],
        models=[
            AdminModelItem(
                **{
                    **item.__dict__,
                    "reasoning_effort_options": list(item.reasoning_effort_options),
                }
            )
            for item in snapshot.models
        ],
    )


def _record_audit_value(record) -> dict:
    return {
        "provider": record.provider,
        "model_id": record.model_id,
        "enabled": record.enabled,
        "is_default": record.is_default,
        "parameters": dict(record.parameter_values or {}),
    }


def _require_manage(principal: AdminPrincipal) -> None:
    if AdminPermission.SETTINGS_MANAGE not in principal.permissions:
        raise AdminAPIProblem(
            status_code=403,
            code="admin_permission_denied",
            title="Permission denied",
            detail="The 'settings.manage' permission is required.",
        )


def _catalog_unavailable() -> AdminAPIProblem:
    return AdminAPIProblem(
        status_code=503,
        code="admin_model_catalog_unavailable",
        title="Model catalog unavailable",
        detail="Model catalog storage is temporarily unavailable.",
    )


def _set_private_headers(request: Request, response: Response) -> None:
    for key, value in _private_headers(request).items():
        response.headers[key] = value


def _private_headers(request: Request) -> dict[str, str]:
    return {
        "Cache-Control": "private, no-store",
        "X-Request-Id": request_id_for(request),
    }
