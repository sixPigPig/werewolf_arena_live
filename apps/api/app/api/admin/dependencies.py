from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, Callable

from fastapi import Depends, Header, Request
from sqlalchemy.orm import Session

from app.admin.rbac import AdminPermission, permissions_for_role
from app.admin.session import admin_session_is_expired, csrf_token_matches, find_admin_session
from app.api.admin.errors import AdminAPIProblem
from app.core.config import settings
from app.db.session import get_db
from app.models.admin import AdminSession
from app.models.user import User


@dataclass(frozen=True)
class AdminPrincipal:
    user: User
    session: AdminSession
    permissions: frozenset[AdminPermission]
    csrf_token: str | None


def get_current_admin(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
) -> AdminPrincipal:
    session_token = request.cookies.get(settings.admin_session_cookie_name)
    if not session_token:
        raise _authentication_required()

    session = find_admin_session(db, session_token)
    if session is None or session.revoked_at is not None or admin_session_is_expired(session):
        raise _authentication_required()

    user = db.get(User, session.user_id)
    if user is None or not user.is_active:
        raise _authentication_required()

    permissions = permissions_for_role(user.admin_role)
    if not permissions:
        raise AdminAPIProblem(
            status_code=403,
            code="admin_permission_denied",
            title="Permission denied",
            detail="This account does not have access to the admin console.",
        )

    csrf_cookie = request.cookies.get(_csrf_cookie_name())
    csrf_token = csrf_cookie if csrf_token_matches(session, csrf_cookie) else None
    return AdminPrincipal(
        user=user,
        session=session,
        permissions=permissions,
        csrf_token=csrf_token,
    )


def require_admin_permission(
    permission: AdminPermission | str,
) -> Callable[..., AdminPrincipal]:
    required_permission = AdminPermission(permission)

    def dependency(
        principal: Annotated[AdminPrincipal, Depends(get_current_admin)],
    ) -> AdminPrincipal:
        if required_permission not in principal.permissions:
            raise AdminAPIProblem(
                status_code=403,
                code="admin_permission_denied",
                title="Permission denied",
                detail=f"The '{required_permission.value}' permission is required.",
            )
        return principal

    return dependency


def require_admin_csrf(
    principal: Annotated[AdminPrincipal, Depends(get_current_admin)],
    csrf_token: Annotated[str | None, Header(alias="X-CSRF-Token")] = None,
) -> AdminPrincipal:
    if not csrf_token_matches(principal.session, csrf_token):
        raise AdminAPIProblem(
            status_code=403,
            code="admin_csrf_invalid",
            title="Invalid CSRF token",
            detail="A valid CSRF token is required for this operation.",
        )
    return principal


def _authentication_required() -> AdminAPIProblem:
    return AdminAPIProblem(
        status_code=401,
        code="admin_auth_required",
        title="Authentication required",
        detail="A valid admin session is required.",
    )


def _csrf_cookie_name() -> str:
    return f"{settings.admin_session_cookie_name}_csrf"
