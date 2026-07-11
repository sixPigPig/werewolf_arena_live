from __future__ import annotations

from collections.abc import Callable
from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, Request, Response
from sqlalchemy import select
from sqlalchemy.exc import OperationalError, ProgrammingError
from sqlalchemy.orm import Session

from app.admin.audit import record_audit_event
from app.admin.rbac import AdminPermission
from app.api.admin.dependencies import (
    AdminPrincipal,
    require_admin_csrf,
    require_admin_permission,
)
from app.api.admin.errors import AdminAPIProblem, request_id_for
from app.api.schemas.admin_player_profiles import (
    AdminPlayerProfileAiDraftRequest,
    AdminPlayerProfileAiDraftResponse,
    AdminPlayerProfileCreate,
    AdminPlayerProfileListResponse,
    AdminPlayerProfileOptionsResponse,
    AdminPlayerProfileResponse,
    AdminPlayerProfileTransition,
    AdminPlayerProfileUpdate,
    PlayerProfileSort,
    PlayerProfileStatus,
)
from app.api.routes.player_profiles import (
    PlayerProfileAiDraftRequest,
    PlayerProfileAiInvalidResponse,
    PlayerProfileAiProviderUnavailable,
    generate_ai_player_draft,
    get_player_profile_ai_provider,
)
from app.db.session import get_db
from app.models.virtual_player_profile import VirtualPlayerProfile
from app.player_profiles.errors import (
    PlayerProfileNotFound,
    PlayerProfileTransitionError,
    PlayerProfileValidationError,
    PlayerProfileVersionConflict,
)
from app.player_profiles.service import (
    archive_player_profile,
    create_player_profile,
    current_player_profile_version,
    get_player_profile,
    list_admin_player_profiles,
    publish_player_profile,
    restore_player_profile,
    update_player_profile,
)
from app.player_profiles.snapshots import (
    admin_player_profile_snapshot,
    audit_player_profile_snapshot,
)
from app.werewolf.player_avatar_assets import SYSTEM_AVATAR_ASSET_IDS, avatar_asset_url
from app.werewolf.player_presets import (
    APPEARANCE_PRESETS,
    PERSONALITY_PRESETS,
    STRATEGY_PRESETS,
)
from app.werewolf.providers import configured_model_options

router = APIRouter()
RecoverableDatabaseError = (OperationalError, ProgrammingError)


@router.post(
    "/player-profile-ai-drafts",
    response_model=AdminPlayerProfileAiDraftResponse,
)
def generate_admin_player_profile_ai_draft(
    request_body: AdminPlayerProfileAiDraftRequest,
    request: Request,
    response: Response,
    db: Annotated[Session, Depends(get_db)],
    principal: Annotated[
        AdminPrincipal,
        Depends(require_admin_permission(AdminPermission.PLAYERS_AI_GENERATE)),
    ],
    _csrf: Annotated[AdminPrincipal, Depends(require_admin_csrf)],
    provider: Annotated[object, Depends(get_player_profile_ai_provider)],
) -> AdminPlayerProfileAiDraftResponse:
    try:
        existing_names = list(
            db.scalars(
                select(VirtualPlayerProfile.display_name)
                .order_by(VirtualPlayerProfile.updated_at.desc())
                .limit(200)
            )
        )
        draft = generate_ai_player_draft(
            PlayerProfileAiDraftRequest(
                mode=request_body.mode,
                existing_names=existing_names,
            ),
            provider,
        )
        record_audit_event(
            db,
            request=request,
            actor_user_id=principal.user.id,
            action="admin.player_profile.ai_draft.generate",
            resource_type="player_profile_ai_draft",
            resource_id=None,
            result="success",
            after={"mode": request_body.mode, "display_name": draft.display_name},
        )
        db.commit()
    except PlayerProfileAiProviderUnavailable as exc:
        _record_ai_draft_failure(
            db,
            request=request,
            principal=principal,
            mode=request_body.mode,
            reason="provider_unavailable",
        )
        raise AdminAPIProblem(
            status_code=503,
            code="admin_player_ai_provider_unavailable",
            title="AI draft provider unavailable",
            detail="The AI draft provider is temporarily unavailable.",
        ) from exc
    except PlayerProfileAiInvalidResponse as exc:
        _record_ai_draft_failure(
            db,
            request=request,
            principal=principal,
            mode=request_body.mode,
            reason="invalid_provider_response",
        )
        raise AdminAPIProblem(
            status_code=502,
            code="admin_player_ai_response_invalid",
            title="AI draft response invalid",
            detail="The provider returned an invalid player draft.",
        ) from exc
    except RecoverableDatabaseError as exc:
        db.rollback()
        raise _database_unavailable() from exc
    _set_private_headers(request, response)
    return AdminPlayerProfileAiDraftResponse.model_validate(draft.model_dump())


@router.get("/player-profiles", response_model=AdminPlayerProfileListResponse)
def list_profiles(
    request: Request,
    response: Response,
    db: Annotated[Session, Depends(get_db)],
    _principal: Annotated[
        AdminPrincipal,
        Depends(require_admin_permission(AdminPermission.PLAYERS_READ)),
    ],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    q: Annotated[str | None, Query(max_length=120)] = None,
    status: PlayerProfileStatus | None = None,
    model: Annotated[str | None, Query(max_length=120)] = None,
    personality_id: Annotated[str | None, Query(max_length=40)] = None,
    sort: PlayerProfileSort = "display_order",
) -> AdminPlayerProfileListResponse:
    try:
        result = list_admin_player_profiles(
            db,
            page=page,
            page_size=page_size,
            query_text=q,
            status=status,
            model=model,
            personality_id=personality_id,
            sort=sort,
        )
    except RecoverableDatabaseError as exc:
        raise _database_unavailable() from exc
    _set_private_headers(request, response)
    return AdminPlayerProfileListResponse(
        items=[admin_player_profile_snapshot(profile) for profile in result.items],
        pagination={
            "page": result.page,
            "page_size": result.page_size,
            "total": result.total,
            "pages": result.pages,
        },
    )


@router.get("/player-profile-options", response_model=AdminPlayerProfileOptionsResponse)
def get_profile_options(
    request: Request,
    response: Response,
    _principal: Annotated[
        AdminPrincipal,
        Depends(require_admin_permission(AdminPermission.PLAYERS_READ)),
    ],
) -> AdminPlayerProfileOptionsResponse:
    _set_private_headers(request, response)
    return AdminPlayerProfileOptionsResponse(
        models=[
            {"id": option["id"], "label": option["label"], "description": ""}
            for option in configured_model_options()
        ],
        personalities=[
            {
                "id": preset.id,
                "label": preset.label,
                "description": preset.description,
            }
            for preset in PERSONALITY_PRESETS.values()
        ],
        appearances=[
            {
                "id": preset.id,
                "label": preset.label,
                "description": preset.description,
                "avatar_asset_id": SYSTEM_AVATAR_ASSET_IDS.get(preset.id),
                "avatar_image_url": (
                    avatar_asset_url(SYSTEM_AVATAR_ASSET_IDS[preset.id])
                    if preset.id in SYSTEM_AVATAR_ASSET_IDS
                    else ""
                ),
            }
            for preset in APPEARANCE_PRESETS.values()
        ],
        strategies=[
            {"id": strategy_id, "label": strategy_id, "description": description}
            for strategy_id, description in STRATEGY_PRESETS.items()
        ],
        constraints={
            "tags_max_items": 8,
            "tag_max_length": 20,
            "catchphrases_max_items": 6,
            "catchphrase_max_length": 40,
            "example_messages_max_items": 5,
            "example_message_max_length": 240,
        },
    )


@router.post(
    "/player-profiles",
    response_model=AdminPlayerProfileResponse,
    status_code=201,
)
def create_profile(
    request_body: AdminPlayerProfileCreate,
    request: Request,
    response: Response,
    db: Annotated[Session, Depends(get_db)],
    principal: Annotated[
        AdminPrincipal,
        Depends(require_admin_permission(AdminPermission.PLAYERS_WRITE)),
    ],
    _csrf: Annotated[AdminPrincipal, Depends(require_admin_csrf)],
) -> AdminPlayerProfileResponse:
    try:
        _ensure_configured_model(request_body.model)
        profile = create_player_profile(
            db,
            values=request_body.model_dump(),
            initial_status="draft",
            actor_user_id=principal.user.id,
            allow_external_avatar_url=False,
        )
        after = audit_player_profile_snapshot(profile)
        record_audit_event(
            db,
            request=request,
            actor_user_id=principal.user.id,
            action="admin.player_profile.create",
            resource_type="player_profile",
            resource_id=profile.id,
            result="success",
            after=after,
        )
        db.commit()
        db.refresh(profile)
    except PlayerProfileValidationError as exc:
        _record_failed_create(
            db,
            request=request,
            principal=principal,
            request_body=request_body,
            reason=str(exc),
        )
        raise _validation_problem(str(exc)) from exc
    except RecoverableDatabaseError as exc:
        db.rollback()
        raise _database_unavailable() from exc
    _set_private_headers(request, response)
    return AdminPlayerProfileResponse.model_validate(admin_player_profile_snapshot(profile))


@router.get("/player-profiles/{profile_id}", response_model=AdminPlayerProfileResponse)
def get_profile(
    profile_id: Annotated[str, Path(min_length=1, max_length=36)],
    request: Request,
    response: Response,
    db: Annotated[Session, Depends(get_db)],
    _principal: Annotated[
        AdminPrincipal,
        Depends(require_admin_permission(AdminPermission.PLAYERS_READ)),
    ],
) -> AdminPlayerProfileResponse:
    try:
        profile = get_player_profile(db, profile_id)
    except PlayerProfileNotFound as exc:
        raise _not_found() from exc
    except RecoverableDatabaseError as exc:
        raise _database_unavailable() from exc
    _set_private_headers(request, response)
    return AdminPlayerProfileResponse.model_validate(admin_player_profile_snapshot(profile))


@router.patch("/player-profiles/{profile_id}", response_model=AdminPlayerProfileResponse)
def update_profile(
    profile_id: Annotated[str, Path(min_length=1, max_length=36)],
    request_body: AdminPlayerProfileUpdate,
    request: Request,
    response: Response,
    db: Annotated[Session, Depends(get_db)],
    principal: Annotated[
        AdminPrincipal,
        Depends(require_admin_permission(AdminPermission.PLAYERS_WRITE)),
    ],
    _csrf: Annotated[AdminPrincipal, Depends(require_admin_csrf)],
) -> AdminPlayerProfileResponse:
    action = "admin.player_profile.update"
    expected_version = request_body.expected_version
    try:
        existing = get_player_profile(db, profile_id)
        updates = request_body.model_dump(exclude_unset=True)
        updates.pop("expected_version")
        if "model" in updates and updates["model"] != existing.model:
            _ensure_configured_model(str(updates["model"]))
        if existing.status == "published" or "featured" in updates:
            _require_extra_permission(principal, AdminPermission.PLAYERS_PUBLISH)
        before = audit_player_profile_snapshot(existing)
        profile = update_player_profile(
            db,
            profile_id,
            updates=updates,
            expected_version=expected_version,
            actor_user_id=principal.user.id,
            allow_external_avatar_url=False,
        )
        _commit_successful_mutation(
            db,
            request=request,
            principal=principal,
            action=action,
            profile=profile,
            before=before,
        )
    except (
        PlayerProfileNotFound,
        PlayerProfileVersionConflict,
        PlayerProfileTransitionError,
        PlayerProfileValidationError,
    ) as exc:
        _raise_profile_problem(
            db,
            request=request,
            principal=principal,
            action=action,
            profile_id=profile_id,
            exc=exc,
            expected_version=expected_version,
        )
    except RecoverableDatabaseError as exc:
        db.rollback()
        raise _database_unavailable() from exc
    _set_private_headers(request, response)
    return AdminPlayerProfileResponse.model_validate(admin_player_profile_snapshot(profile))


@router.post(
    "/player-profiles/{profile_id}/publish",
    response_model=AdminPlayerProfileResponse,
)
def publish_profile(
    profile_id: Annotated[str, Path(min_length=1, max_length=36)],
    request_body: AdminPlayerProfileTransition,
    request: Request,
    response: Response,
    db: Annotated[Session, Depends(get_db)],
    principal: Annotated[
        AdminPrincipal,
        Depends(require_admin_permission(AdminPermission.PLAYERS_PUBLISH)),
    ],
    _csrf: Annotated[AdminPrincipal, Depends(require_admin_csrf)],
) -> AdminPlayerProfileResponse:
    return _transition_profile(
        profile_id=profile_id,
        request_body=request_body,
        request=request,
        response=response,
        db=db,
        principal=principal,
        action="admin.player_profile.publish",
        transition=publish_player_profile,
    )


@router.post(
    "/player-profiles/{profile_id}/archive",
    response_model=AdminPlayerProfileResponse,
)
def archive_profile(
    profile_id: Annotated[str, Path(min_length=1, max_length=36)],
    request_body: AdminPlayerProfileTransition,
    request: Request,
    response: Response,
    db: Annotated[Session, Depends(get_db)],
    principal: Annotated[
        AdminPrincipal,
        Depends(require_admin_permission(AdminPermission.PLAYERS_ARCHIVE)),
    ],
    _csrf: Annotated[AdminPrincipal, Depends(require_admin_csrf)],
) -> AdminPlayerProfileResponse:
    return _transition_profile(
        profile_id=profile_id,
        request_body=request_body,
        request=request,
        response=response,
        db=db,
        principal=principal,
        action="admin.player_profile.archive",
        transition=archive_player_profile,
    )


@router.post(
    "/player-profiles/{profile_id}/restore",
    response_model=AdminPlayerProfileResponse,
)
def restore_profile(
    profile_id: Annotated[str, Path(min_length=1, max_length=36)],
    request_body: AdminPlayerProfileTransition,
    request: Request,
    response: Response,
    db: Annotated[Session, Depends(get_db)],
    principal: Annotated[
        AdminPrincipal,
        Depends(require_admin_permission(AdminPermission.PLAYERS_ARCHIVE)),
    ],
    _csrf: Annotated[AdminPrincipal, Depends(require_admin_csrf)],
) -> AdminPlayerProfileResponse:
    return _transition_profile(
        profile_id=profile_id,
        request_body=request_body,
        request=request,
        response=response,
        db=db,
        principal=principal,
        action="admin.player_profile.restore",
        transition=restore_player_profile,
    )


def _transition_profile(
    *,
    profile_id: str,
    request_body: AdminPlayerProfileTransition,
    request: Request,
    response: Response,
    db: Session,
    principal: AdminPrincipal,
    action: str,
    transition: Callable[..., VirtualPlayerProfile],
) -> AdminPlayerProfileResponse:
    try:
        existing = get_player_profile(db, profile_id)
        before = audit_player_profile_snapshot(existing)
        profile = transition(
            db,
            profile_id,
            expected_version=request_body.expected_version,
            actor_user_id=principal.user.id,
        )
        _commit_successful_mutation(
            db,
            request=request,
            principal=principal,
            action=action,
            profile=profile,
            before=before,
            reason=request_body.reason,
        )
    except (
        PlayerProfileNotFound,
        PlayerProfileVersionConflict,
        PlayerProfileTransitionError,
        PlayerProfileValidationError,
    ) as exc:
        _raise_profile_problem(
            db,
            request=request,
            principal=principal,
            action=action,
            profile_id=profile_id,
            exc=exc,
            reason=request_body.reason,
            expected_version=request_body.expected_version,
        )
    except RecoverableDatabaseError as exc:
        db.rollback()
        raise _database_unavailable() from exc
    _set_private_headers(request, response)
    return AdminPlayerProfileResponse.model_validate(admin_player_profile_snapshot(profile))


def _commit_successful_mutation(
    db: Session,
    *,
    request: Request,
    principal: AdminPrincipal,
    action: str,
    profile: VirtualPlayerProfile,
    before: dict[str, object] | None,
    reason: str | None = None,
) -> None:
    record_audit_event(
        db,
        request=request,
        actor_user_id=principal.user.id,
        action=action,
        resource_type="player_profile",
        resource_id=profile.id,
        result="success",
        reason=reason,
        before=before,
        after=audit_player_profile_snapshot(profile),
    )
    db.commit()
    db.refresh(profile)


def _raise_profile_problem(
    db: Session,
    *,
    request: Request,
    principal: AdminPrincipal,
    action: str,
    profile_id: str,
    exc: Exception,
    reason: str | None = None,
    expected_version: int | None = None,
) -> None:
    db.rollback()
    current_version = current_player_profile_version(db, profile_id)
    result = "conflict" if isinstance(
        exc,
        (PlayerProfileVersionConflict, PlayerProfileTransitionError),
    ) else "failure"
    record_audit_event(
        db,
        request=request,
        actor_user_id=principal.user.id,
        action=action,
        resource_type="player_profile",
        resource_id=profile_id,
        result=result,
        reason=reason or str(exc),
        after={
            "expected_version": expected_version,
            "current_version": current_version,
        },
    )
    db.commit()
    if isinstance(exc, PlayerProfileNotFound):
        raise _not_found() from exc
    if isinstance(exc, PlayerProfileVersionConflict):
        raise AdminAPIProblem(
            status_code=409,
            code="admin_player_profile_version_conflict",
            title="Player profile changed",
            detail="The player profile was changed by another user. Reload and try again.",
            extensions={"current_version": current_version},
        ) from exc
    if isinstance(exc, PlayerProfileTransitionError):
        raise AdminAPIProblem(
            status_code=409,
            code="admin_player_profile_transition_conflict",
            title="Invalid player profile transition",
            detail=(
                f"A player profile in '{exc.current_status}' status cannot transition "
                f"to '{exc.target_status}'."
            ),
            extensions={"current_version": current_version},
        ) from exc
    if isinstance(exc, PlayerProfileValidationError):
        raise _validation_problem(str(exc)) from exc
    raise exc


def _require_extra_permission(
    principal: AdminPrincipal,
    permission: AdminPermission,
) -> None:
    if permission not in principal.permissions:
        raise AdminAPIProblem(
            status_code=403,
            code="admin_permission_denied",
            title="Permission denied",
            detail=f"The '{permission.value}' permission is required.",
        )


def _ensure_configured_model(model: str) -> None:
    configured_models = {option["id"] for option in configured_model_options()}
    if model not in configured_models:
        raise PlayerProfileValidationError(
            "The selected model is not configured for this deployment."
        )


def _record_failed_create(
    db: Session,
    *,
    request: Request,
    principal: AdminPrincipal,
    request_body: AdminPlayerProfileCreate,
    reason: str,
) -> None:
    db.rollback()
    record_audit_event(
        db,
        request=request,
        actor_user_id=principal.user.id,
        action="admin.player_profile.create",
        resource_type="player_profile",
        resource_id=None,
        result="failure",
        reason=reason,
        after={
            "display_name": request_body.display_name,
            "model": request_body.model,
            "target_status": "draft",
        },
    )
    try:
        db.commit()
    except RecoverableDatabaseError as exc:
        db.rollback()
        raise _database_unavailable() from exc


def _record_ai_draft_failure(
    db: Session,
    *,
    request: Request,
    principal: AdminPrincipal,
    mode: str,
    reason: str,
) -> None:
    db.rollback()
    record_audit_event(
        db,
        request=request,
        actor_user_id=principal.user.id,
        action="admin.player_profile.ai_draft.generate",
        resource_type="player_profile_ai_draft",
        resource_id=None,
        result="failure",
        reason=reason,
        after={"mode": mode},
    )
    try:
        db.commit()
    except RecoverableDatabaseError as exc:
        db.rollback()
        raise _database_unavailable() from exc


def _set_private_headers(request: Request, response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    response.headers["X-Request-ID"] = request_id_for(request)


def _not_found() -> AdminAPIProblem:
    return AdminAPIProblem(
        status_code=404,
        code="admin_player_profile_not_found",
        title="Player profile not found",
        detail="The requested player profile does not exist.",
    )


def _validation_problem(detail: str) -> AdminAPIProblem:
    return AdminAPIProblem(
        status_code=422,
        code="admin_player_profile_invalid",
        title="Invalid player profile",
        detail=detail,
    )


def _database_unavailable() -> AdminAPIProblem:
    return AdminAPIProblem(
        status_code=503,
        code="admin_player_profile_database_unavailable",
        title="Player profile database unavailable",
        detail="Player profile data is temporarily unavailable.",
    )
