from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Body, Depends, Request, Response
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.admin.audit import record_audit_event
from app.admin.rbac import permissions_for_role
from app.admin.session import as_utc, create_admin_session, rotate_admin_csrf_token, utc_now
from app.api.admin.dependencies import AdminPrincipal, get_current_admin, require_admin_csrf
from app.api.admin.errors import AdminAPIProblem, request_id_for
from app.core.config import settings
from app.db.session import get_db
from app.models.user import User

router = APIRouter()


class EmptyDevLoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AdminMeUser(BaseModel):
    id: str
    email: str
    display_name: str
    role: str


class AdminMeResponse(BaseModel):
    user: AdminMeUser
    permissions: list[str]
    csrf_token: str
    session_expires_at: datetime


@router.get("/me", response_model=AdminMeResponse)
def read_admin_me(
    request: Request,
    response: Response,
    db: Annotated[Session, Depends(get_db)],
    principal: Annotated[AdminPrincipal, Depends(get_current_admin)],
) -> AdminMeResponse:
    csrf_token = principal.csrf_token
    if csrf_token is None:
        csrf_token = rotate_admin_csrf_token(principal.session)
        db.commit()
        _set_csrf_cookie(response, csrf_token, expires_at=principal.session.expires_at)

    _set_private_response_headers(request, response)
    return _serialize_admin_me(principal, csrf_token)


@router.post("/dev-login", response_model=AdminMeResponse)
def dev_login(
    request: Request,
    response: Response,
    db: Annotated[Session, Depends(get_db)],
    _body: Annotated[EmptyDevLoginRequest | None, Body()] = None,
) -> AdminMeResponse:
    if not _dev_login_is_available():
        raise AdminAPIProblem(
            status_code=404,
            code="admin_dev_login_disabled",
            title="Development login unavailable",
            detail="Development admin login is not enabled in this environment.",
        )

    configured_email = settings.admin_dev_auth_email.strip().lower()
    user = db.scalar(select(User).where(func.lower(User.email) == configured_email))
    if user is None:
        user = User(
            email=configured_email,
            display_name=settings.admin_dev_auth_display_name.strip(),
            admin_role=settings.admin_dev_auth_role,
            is_active=True,
        )
        db.add(user)
        db.flush()
    else:
        user.display_name = settings.admin_dev_auth_display_name.strip()
        user.admin_role = settings.admin_dev_auth_role
        user.is_active = True
        db.flush()

    issued = create_admin_session(
        db,
        user_id=user.id,
        ttl_seconds=settings.admin_session_ttl_seconds,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    record_audit_event(
        db,
        request=request,
        actor_user_id=user.id,
        action="admin.session.dev_login",
        resource_type="user",
        resource_id=str(user.id),
        result="success",
        after={"admin_role": user.admin_role},
    )
    db.commit()

    _set_session_cookie(response, issued.session_token, expires_at=issued.record.expires_at)
    _set_csrf_cookie(response, issued.csrf_token, expires_at=issued.record.expires_at)
    _set_private_response_headers(request, response)
    principal = AdminPrincipal(
        user=user,
        session=issued.record,
        permissions=permissions_for_role(user.admin_role),
        csrf_token=issued.csrf_token,
    )
    return _serialize_admin_me(principal, issued.csrf_token)


@router.post("/logout", status_code=204)
def logout(
    request: Request,
    response: Response,
    db: Annotated[Session, Depends(get_db)],
    principal: Annotated[AdminPrincipal, Depends(require_admin_csrf)],
) -> None:
    principal.session.revoked_at = utc_now()
    record_audit_event(
        db,
        request=request,
        actor_user_id=principal.user.id,
        action="admin.session.logout",
        resource_type="admin_session",
        resource_id=principal.session.id,
        result="success",
    )
    db.commit()
    _delete_auth_cookies(response)
    _set_private_response_headers(request, response)


def _serialize_admin_me(principal: AdminPrincipal, csrf_token: str) -> AdminMeResponse:
    return AdminMeResponse(
        user=AdminMeUser(
            id=str(principal.user.id),
            email=principal.user.email,
            display_name=principal.user.display_name,
            role=principal.user.admin_role or "",
        ),
        permissions=sorted(permission.value for permission in principal.permissions),
        csrf_token=csrf_token,
        session_expires_at=as_utc(principal.session.expires_at),
    )


def _dev_login_is_available() -> bool:
    return settings.admin_dev_auth_enabled and settings.app_environment in {
        "development",
        "test",
    }


def _set_session_cookie(response: Response, token: str, *, expires_at: datetime) -> None:
    response.set_cookie(
        key=settings.admin_session_cookie_name,
        value=token,
        max_age=settings.admin_session_ttl_seconds,
        expires=as_utc(expires_at),
        path=_admin_cookie_path(),
        secure=settings.admin_session_cookie_secure,
        httponly=True,
        samesite="lax",
    )


def _set_csrf_cookie(response: Response, token: str, *, expires_at: datetime) -> None:
    response.set_cookie(
        key=f"{settings.admin_session_cookie_name}_csrf",
        value=token,
        max_age=settings.admin_session_ttl_seconds,
        expires=as_utc(expires_at),
        path=_admin_cookie_path(),
        secure=settings.admin_session_cookie_secure,
        httponly=True,
        samesite="lax",
    )


def _delete_auth_cookies(response: Response) -> None:
    for cookie_name in (
        settings.admin_session_cookie_name,
        f"{settings.admin_session_cookie_name}_csrf",
    ):
        response.delete_cookie(
            key=cookie_name,
            path=_admin_cookie_path(),
            secure=settings.admin_session_cookie_secure,
            httponly=True,
            samesite="lax",
        )


def _set_private_response_headers(request: Request, response: Response) -> None:
    request_id = request_id_for(request)
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    response.headers["X-Request-ID"] = request_id


def _admin_cookie_path() -> str:
    return f"{settings.api_v1_prefix.rstrip('/')}/admin"
