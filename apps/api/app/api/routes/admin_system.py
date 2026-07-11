from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import json
import math
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, Header, Path, Query, Request, Response, status
from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.exc import IntegrityError, OperationalError, ProgrammingError
from sqlalchemy.orm import Session, aliased

from app.admin.audit import record_audit_event
from app.admin.rbac import AdminPermission
from app.admin.session import as_utc, utc_now
from app.api.admin.dependencies import (
    AdminPrincipal,
    require_admin_csrf,
    require_admin_permission,
)
from app.api.admin.errors import AdminAPIProblem, request_id_for
from app.api.schemas.admin_system import (
    AdminAuditActor,
    AdminAuditEventItem,
    AdminAuditEventListResponse,
    AdminAuditSort,
    AdminIdentityStatus,
    AdminRoleValue,
    AdminSessionRevokeRequest,
    AdminSessionRevokeResponse,
    AdminUserCreate,
    AdminUserListItem,
    AdminUserListResponse,
    AdminUserSort,
    AdminUserUpdate,
)
from app.db.session import get_db
from app.models.admin import (
    AdminSession,
    AdminUserProvisioningRequest,
    AuditEvent,
)
from app.models.user import User

router = APIRouter()
RecoverableDatabaseError = (OperationalError, ProgrammingError)


@router.get("/users", response_model=AdminUserListResponse)
def list_admin_users(
    request: Request,
    response: Response,
    db: Annotated[Session, Depends(get_db)],
    _principal: Annotated[
        AdminPrincipal,
        Depends(require_admin_permission(AdminPermission.USERS_MANAGE)),
    ],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    q: Annotated[str | None, Query(max_length=120)] = None,
    role: AdminRoleValue | None = None,
    is_active: bool | None = None,
    identity_status: AdminIdentityStatus | None = None,
    sort: AdminUserSort = "-updated_at",
) -> AdminUserListResponse:
    filters = _user_filters(q, role, is_active, identity_status)
    active_sessions = (
        select(func.count())
        .select_from(AdminSession)
        .where(
            AdminSession.user_id == User.id,
            AdminSession.revoked_at.is_(None),
            AdminSession.expires_at > utc_now(),
        )
        .correlate(User)
        .scalar_subquery()
    )
    last_session_at = (
        select(func.max(AdminSession.created_at))
        .where(AdminSession.user_id == User.id)
        .correlate(User)
        .scalar_subquery()
    )
    try:
        total = int(
            db.scalar(select(func.count()).select_from(User).where(*filters)) or 0
        )
        rows = list(
            db.execute(
                select(
                    User,
                    active_sessions.label("active_session_count"),
                    last_session_at.label("last_session_at"),
                )
                .where(*filters)
                .order_by(*_user_order(sort))
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        )
    except RecoverableDatabaseError as exc:
        raise _database_unavailable() from exc
    _set_private_headers(request, response)
    return AdminUserListResponse(
        items=[
            _serialize_user(
                user,
                active_session_count=int(active_session_count or 0),
                last_session_at=last_login,
            )
            for user, active_session_count, last_login in rows
        ],
        pagination={
            "page": page,
            "page_size": page_size,
            "total": total,
            "pages": math.ceil(total / page_size) if total else 0,
        },
    )


@router.post(
    "/users",
    response_model=AdminUserListItem,
    status_code=status.HTTP_201_CREATED,
)
def create_admin_user(
    request_body: AdminUserCreate,
    request: Request,
    response: Response,
    db: Annotated[Session, Depends(get_db)],
    principal: Annotated[AdminPrincipal, Depends(require_admin_csrf)],
    idempotency_key: Annotated[
        str,
        Header(alias="Idempotency-Key", min_length=8, max_length=160),
    ],
) -> AdminUserListItem:
    _require_permission(principal, AdminPermission.USERS_MANAGE)
    _require_permission(principal, AdminPermission.ROLES_MANAGE)
    request_hash = hashlib.sha256(
        json.dumps(request_body.model_dump(), sort_keys=True).encode("utf-8")
    ).hexdigest()
    try:
        existing_request = db.scalar(
            select(AdminUserProvisioningRequest).where(
                AdminUserProvisioningRequest.actor_user_id == principal.user.id,
                AdminUserProvisioningRequest.idempotency_key == idempotency_key,
            )
        )
        if existing_request is not None:
            if existing_request.request_hash != request_hash:
                _audited_rejection(
                    db,
                    request=request,
                    principal=principal,
                    action="admin.user.create",
                    resource_id=str(existing_request.user_id),
                    code="admin_idempotency_conflict",
                    detail="This idempotency key was already used for another request.",
                )
            existing_user = db.get(User, existing_request.user_id)
            if existing_user is None:
                raise _database_unavailable()
            result = _serialize_user_with_sessions(db, existing_user)
            _set_private_headers(request, response)
            return result

        duplicate = db.scalar(
            select(User).where(func.lower(User.email) == request_body.email).with_for_update()
        )
        if duplicate is not None:
            _audited_rejection(
                db,
                request=request,
                principal=principal,
                action="admin.user.create",
                resource_id=str(duplicate.id),
                code="admin_user_email_conflict",
                detail="An account with this email address already exists.",
            )

        user = User(
            email=request_body.email,
            display_name=request_body.display_name,
            admin_role=request_body.role,
            admin_version=1,
            is_active=True,
        )
        db.add(user)
        db.flush()
        db.add(
            AdminUserProvisioningRequest(
                id=str(uuid4()),
                actor_user_id=principal.user.id,
                idempotency_key=idempotency_key,
                request_hash=request_hash,
                user_id=user.id,
            )
        )
        record_audit_event(
            db,
            request=request,
            actor_user_id=principal.user.id,
            action="admin.user.create",
            resource_type="user",
            resource_id=str(user.id),
            result="success",
            reason=request_body.reason,
            after=_audit_user(user),
        )
        db.commit()
        result = _serialize_user_with_sessions(db, user)
    except AdminAPIProblem:
        raise
    except IntegrityError as exc:
        db.rollback()
        raise AdminAPIProblem(
            status_code=409,
            code="admin_user_create_conflict",
            title="Account creation conflict",
            detail="The account or idempotency key was created by another request.",
        ) from exc
    except RecoverableDatabaseError as exc:
        db.rollback()
        raise _database_unavailable() from exc
    _set_private_headers(request, response)
    return result


@router.patch("/users/{user_id}", response_model=AdminUserListItem)
def update_admin_user(
    user_id: Annotated[int, Path(ge=1)],
    request_body: AdminUserUpdate,
    request: Request,
    response: Response,
    db: Annotated[Session, Depends(get_db)],
    principal: Annotated[AdminPrincipal, Depends(require_admin_csrf)],
) -> AdminUserListItem:
    _require_permission(principal, AdminPermission.USERS_MANAGE)
    if "role" in request_body.model_fields_set:
        _require_permission(principal, AdminPermission.ROLES_MANAGE)
    try:
        user = db.scalar(select(User).where(User.id == user_id).with_for_update())
        if user is None or user.admin_role is None:
            raise _user_not_found()
        if user.admin_version != request_body.expected_version:
            current = _serialize_user_with_sessions(db, user)
            _audited_rejection(
                db,
                request=request,
                principal=principal,
                action="admin.user.update",
                resource_id=str(user.id),
                code="admin_user_version_conflict",
                detail="The account was changed by another administrator.",
                extensions={"current": current.model_dump(mode="json")},
            )
        next_role = request_body.role if "role" in request_body.model_fields_set else user.admin_role
        next_active = (
            request_body.is_active
            if "is_active" in request_body.model_fields_set
            else user.is_active
        )
        if user.id == principal.user.id and (
            next_role != user.admin_role or not next_active
        ):
            _audited_rejection(
                db,
                request=request,
                principal=principal,
                action="admin.user.update",
                resource_id=str(user.id),
                code="admin_user_self_protection",
                detail="You cannot disable or change the role of your own account.",
            )
        if user.admin_role == "super_admin" and (
            next_role != "super_admin" or not next_active
        ):
            other_super_admins = int(
                db.scalar(
                    select(func.count())
                    .select_from(User)
                    .where(
                        User.admin_role == "super_admin",
                        User.is_active.is_(True),
                        User.id != user.id,
                    )
                )
                or 0
            )
            if other_super_admins == 0:
                _audited_rejection(
                    db,
                    request=request,
                    principal=principal,
                    action="admin.user.update",
                    resource_id=str(user.id),
                    code="admin_last_super_admin",
                    detail="At least one active super administrator must remain.",
                )

        before = _audit_user(user)
        changed_fields: list[str] = []
        if "display_name" in request_body.model_fields_set and request_body.display_name != user.display_name:
            user.display_name = request_body.display_name or user.display_name
            changed_fields.append("display_name")
        if "role" in request_body.model_fields_set and request_body.role != user.admin_role:
            user.admin_role = request_body.role
            changed_fields.append("role")
        if "is_active" in request_body.model_fields_set and request_body.is_active != user.is_active:
            user.is_active = bool(request_body.is_active)
            changed_fields.append("is_active")
        revoked_count = 0
        if changed_fields:
            user.admin_version += 1
            user.updated_at = utc_now()
            if not user.is_active:
                revoked_count = _revoke_user_sessions(db, user.id)
        record_audit_event(
            db,
            request=request,
            actor_user_id=principal.user.id,
            action="admin.user.update",
            resource_type="user",
            resource_id=str(user.id),
            result="success",
            reason=request_body.reason,
            before=before,
            after={**_audit_user(user), "changed_fields": changed_fields, "revoked_sessions": revoked_count},
        )
        db.commit()
        result = _serialize_user_with_sessions(db, user)
    except AdminAPIProblem:
        raise
    except RecoverableDatabaseError as exc:
        db.rollback()
        raise _database_unavailable() from exc
    _set_private_headers(request, response)
    return result


@router.post(
    "/users/{user_id}/revoke-sessions",
    response_model=AdminSessionRevokeResponse,
)
def revoke_admin_user_sessions(
    user_id: Annotated[int, Path(ge=1)],
    request_body: AdminSessionRevokeRequest,
    request: Request,
    response: Response,
    db: Annotated[Session, Depends(get_db)],
    principal: Annotated[AdminPrincipal, Depends(require_admin_csrf)],
) -> AdminSessionRevokeResponse:
    _require_permission(principal, AdminPermission.USERS_MANAGE)
    try:
        user = db.get(User, user_id)
        if user is None or user.admin_role is None:
            raise _user_not_found()
        revoked_count = _revoke_user_sessions(db, user.id)
        record_audit_event(
            db,
            request=request,
            actor_user_id=principal.user.id,
            action="admin.user.sessions.revoke",
            resource_type="user",
            resource_id=str(user.id),
            result="success",
            reason=request_body.reason,
            after={"revoked_count": revoked_count},
        )
        db.commit()
    except AdminAPIProblem:
        raise
    except RecoverableDatabaseError as exc:
        db.rollback()
        raise _database_unavailable() from exc
    _set_private_headers(request, response)
    return AdminSessionRevokeResponse(user_id=str(user.id), revoked_count=revoked_count)


@router.get("/audit-events", response_model=AdminAuditEventListResponse)
def list_admin_audit_events(
    request: Request,
    response: Response,
    db: Annotated[Session, Depends(get_db)],
    _principal: Annotated[
        AdminPrincipal,
        Depends(require_admin_permission(AdminPermission.AUDIT_READ)),
    ],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    q: Annotated[str | None, Query(max_length=120)] = None,
    action: Annotated[str | None, Query(max_length=120)] = None,
    result: Annotated[str | None, Query(max_length=20)] = None,
    resource_type: Annotated[str | None, Query(max_length=80)] = None,
    created_from: datetime | None = None,
    created_to: datetime | None = None,
    sort: AdminAuditSort = "-created_at",
) -> AdminAuditEventListResponse:
    normalized_from = _query_datetime(created_from)
    normalized_to = _query_datetime(created_to)
    if normalized_from and normalized_to and normalized_from > normalized_to:
        raise AdminAPIProblem(
            status_code=422,
            code="admin_audit_filter_invalid",
            title="Invalid audit filter",
            detail="created_from must be earlier than or equal to created_to.",
        )
    actor = aliased(User)
    filters = []
    if q and (term := q.strip()):
        pattern = f"%{_escape_like(term)}%"
        filters.append(
            or_(
                AuditEvent.action.ilike(pattern, escape="\\"),
                AuditEvent.resource_id.ilike(pattern, escape="\\"),
                AuditEvent.request_id.ilike(pattern, escape="\\"),
                actor.email.ilike(pattern, escape="\\"),
                actor.display_name.ilike(pattern, escape="\\"),
            )
        )
    if action:
        filters.append(AuditEvent.action == action.strip())
    if result:
        filters.append(AuditEvent.result == result.strip())
    if resource_type:
        filters.append(AuditEvent.resource_type == resource_type.strip())
    if normalized_from:
        filters.append(AuditEvent.created_at >= normalized_from)
    if normalized_to:
        filters.append(AuditEvent.created_at <= normalized_to)
    try:
        base = select(AuditEvent).outerjoin(actor, actor.id == AuditEvent.actor_user_id)
        total = int(
            db.scalar(
                select(func.count())
                .select_from(AuditEvent)
                .outerjoin(actor, actor.id == AuditEvent.actor_user_id)
                .where(*filters)
            )
            or 0
        )
        rows = list(
            db.execute(
                base.add_columns(actor.id, actor.email, actor.display_name)
                .where(*filters)
                .order_by(
                    AuditEvent.created_at.desc() if sort == "-created_at" else AuditEvent.created_at,
                    AuditEvent.id.desc() if sort == "-created_at" else AuditEvent.id,
                )
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        )
    except RecoverableDatabaseError as exc:
        raise _database_unavailable() from exc
    _set_private_headers(request, response)
    return AdminAuditEventListResponse(
        items=[
            AdminAuditEventItem(
                id=event.id,
                actor=(
                    AdminAuditActor(
                        id=str(actor_id),
                        email=actor_email,
                        display_name=actor_display_name,
                    )
                    if actor_id is not None
                    else None
                ),
                action=event.action,
                resource_type=event.resource_type,
                resource_id=event.resource_id,
                result=event.result,
                reason=event.reason,
                request_id=event.request_id,
                created_at=as_utc(event.created_at),
            )
            for event, actor_id, actor_email, actor_display_name in rows
        ],
        pagination={
            "page": page,
            "page_size": page_size,
            "total": total,
            "pages": math.ceil(total / page_size) if total else 0,
        },
    )


def _user_filters(
    query_text: str | None,
    role: AdminRoleValue | None,
    is_active: bool | None,
    identity_status: AdminIdentityStatus | None,
) -> list:
    filters = [User.admin_role.is_not(None)]
    if query_text and (term := query_text.strip()):
        pattern = f"%{_escape_like(term)}%"
        filters.append(
            or_(
                User.email.ilike(pattern, escape="\\"),
                User.display_name.ilike(pattern, escape="\\"),
            )
        )
    if role:
        filters.append(User.admin_role == role)
    if is_active is not None:
        filters.append(User.is_active.is_(is_active))
    if identity_status == "bound":
        filters.append(and_(User.auth_provider.is_not(None), User.auth_subject.is_not(None)))
    if identity_status == "unbound":
        filters.append(and_(User.auth_provider.is_(None), User.auth_subject.is_(None)))
    return filters


def _user_order(sort: AdminUserSort) -> tuple:
    descending = sort.startswith("-")
    field = sort.removeprefix("-")
    column = {
        "display_name": User.display_name,
        "email": User.email,
        "updated_at": User.updated_at,
        "created_at": User.created_at,
    }[field]
    direction = column.desc() if descending else column.asc()
    tie_breaker = User.id.desc() if descending else User.id.asc()
    return direction, tie_breaker


def _serialize_user_with_sessions(db: Session, user: User) -> AdminUserListItem:
    active_count = int(
        db.scalar(
            select(func.count())
            .select_from(AdminSession)
            .where(
                AdminSession.user_id == user.id,
                AdminSession.revoked_at.is_(None),
                AdminSession.expires_at > utc_now(),
            )
        )
        or 0
    )
    last_session_at = db.scalar(
        select(func.max(AdminSession.created_at)).where(AdminSession.user_id == user.id)
    )
    return _serialize_user(
        user,
        active_session_count=active_count,
        last_session_at=last_session_at,
    )


def _serialize_user(
    user: User,
    *,
    active_session_count: int,
    last_session_at: datetime | None,
) -> AdminUserListItem:
    return AdminUserListItem(
        id=str(user.id),
        email=user.email,
        display_name=user.display_name,
        role=user.admin_role or "viewer",
        is_active=user.is_active,
        identity_status=(
            "bound"
            if user.auth_provider is not None and user.auth_subject is not None
            else "unbound"
        ),
        active_session_count=max(0, active_session_count),
        last_session_at=as_utc(last_session_at) if last_session_at else None,
        created_at=as_utc(user.created_at),
        updated_at=as_utc(user.updated_at),
        version=max(1, user.admin_version),
    )


def _revoke_user_sessions(db: Session, user_id: int) -> int:
    result = db.execute(
        update(AdminSession)
        .where(
            AdminSession.user_id == user_id,
            AdminSession.revoked_at.is_(None),
            AdminSession.expires_at > utc_now(),
        )
        .values(revoked_at=utc_now())
    )
    return max(0, int(result.rowcount or 0))


def _audit_user(user: User) -> dict[str, object]:
    return {
        "email": user.email,
        "display_name": user.display_name,
        "role": user.admin_role,
        "is_active": user.is_active,
        "identity_bound": user.auth_provider is not None,
        "version": user.admin_version,
    }


def _audited_rejection(
    db: Session,
    *,
    request: Request,
    principal: AdminPrincipal,
    action: str,
    resource_id: str | None,
    code: str,
    detail: str,
    extensions: dict | None = None,
) -> None:
    record_audit_event(
        db,
        request=request,
        actor_user_id=principal.user.id,
        action=action,
        resource_type="user",
        resource_id=resource_id,
        result="failure",
        reason=code,
    )
    db.commit()
    raise AdminAPIProblem(
        status_code=409,
        code=code,
        title="Admin account conflict",
        detail=detail,
        extensions=extensions or {},
    )


def _require_permission(principal: AdminPrincipal, permission: AdminPermission) -> None:
    if permission not in principal.permissions:
        raise AdminAPIProblem(
            status_code=403,
            code="admin_permission_denied",
            title="Permission denied",
            detail=f"The '{permission.value}' permission is required.",
        )


def _user_not_found() -> AdminAPIProblem:
    return AdminAPIProblem(
        status_code=404,
        code="admin_user_not_found",
        title="Admin account not found",
        detail="The requested admin account does not exist.",
    )


def _database_unavailable() -> AdminAPIProblem:
    return AdminAPIProblem(
        status_code=503,
        code="admin_system_unavailable",
        title="Admin system unavailable",
        detail="Admin account data is temporarily unavailable.",
    )


def _set_private_headers(request: Request, response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    response.headers["X-Request-ID"] = request_id_for(request)


def _query_datetime(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
