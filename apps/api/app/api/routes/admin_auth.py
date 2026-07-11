from __future__ import annotations

from datetime import datetime
from typing import Annotated
from urllib.parse import urlencode

from fastapi import APIRouter, Body, Depends, Query, Request, Response
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from starlette.responses import RedirectResponse

from app.admin.audit import record_audit_event
from app.admin.oidc import (
    AdminOidcError,
    OidcProvider,
    consume_oidc_attempt,
    create_oidc_attempt,
    resolve_oidc_user,
    safe_return_to,
    validate_oidc_nonce,
)
from app.admin.rbac import permissions_for_role
from app.admin.session import as_utc, create_admin_session, rotate_admin_csrf_token, utc_now
from app.api.admin.dependencies import AdminPrincipal, get_current_admin, require_admin_csrf
from app.api.admin.errors import AdminAPIProblem, request_id_for
from app.core.config import settings
from app.db.session import get_db
from app.models.user import User

router = APIRouter()
oidc_provider = OidcProvider()


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


class AdminLoginOptionsResponse(BaseModel):
    oidc_enabled: bool
    oidc_start_path: str | None


@router.get("/login-options", response_model=AdminLoginOptionsResponse)
def read_admin_login_options(request: Request, response: Response) -> AdminLoginOptionsResponse:
    _set_private_response_headers(request, response)
    return AdminLoginOptionsResponse(
        oidc_enabled=settings.admin_oidc_enabled,
        oidc_start_path=(
            f"{settings.api_v1_prefix.rstrip('/')}/admin/oidc/start"
            if settings.admin_oidc_enabled
            else None
        ),
    )


@router.get("/oidc/start")
def start_oidc_login(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    return_to: str | None = None,
) -> RedirectResponse:
    if not settings.admin_oidc_enabled:
        raise AdminAPIProblem(
            status_code=404,
            code="admin_oidc_disabled",
            title="Enterprise login unavailable",
            detail="OIDC login is not enabled in this environment.",
        )
    attempt = create_oidc_attempt(db, return_to=safe_return_to(return_to))
    try:
        authorization_url = oidc_provider.authorization_url(
            state=attempt.state,
            nonce=attempt.oidc_nonce,
            code_verifier=attempt.record.code_verifier,
        )
    except AdminOidcError as exc:
        db.rollback()
        raise AdminAPIProblem(
            status_code=503,
            code=exc.code,
            title="Enterprise identity unavailable",
            detail="The enterprise identity provider is temporarily unavailable.",
        ) from exc
    db.commit()
    response = RedirectResponse(authorization_url, status_code=302)
    response.set_cookie(
        key=_oidc_binding_cookie_name(),
        value=attempt.browser_nonce,
        max_age=settings.admin_oidc_login_ttl_seconds,
        path=_admin_cookie_path(),
        secure=settings.admin_session_cookie_secure,
        httponly=True,
        samesite="lax",
    )
    _set_private_response_headers(request, response)
    return response


@router.get("/oidc/callback")
def finish_oidc_login(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    code: str | None = None,
    state: str | None = None,
    provider_error: Annotated[str | None, Query(alias="error")] = None,
) -> RedirectResponse:
    browser_nonce = request.cookies.get(_oidc_binding_cookie_name())
    try:
        attempt = consume_oidc_attempt(
            db,
            state=state,
            browser_nonce=browser_nonce,
        )
    except AdminOidcError as exc:
        db.rollback()
        record_audit_event(
            db,
            request=request,
            actor_user_id=None,
            action="admin.session.oidc_login",
            resource_type="admin_oidc_login_attempt",
            resource_id=None,
            result="failure",
            reason=exc.code,
        )
        db.commit()
        return _oidc_error_redirect(request, exc.code)

    return_to = attempt.return_to
    attempt_id = attempt.id
    db.commit()  # Consume state before the external token exchange.
    if provider_error:
        return _record_oidc_failure_and_redirect(
            request,
            db,
            attempt_id=attempt_id,
            return_to=return_to,
            code="admin_oidc_provider_denied",
        )

    try:
        identity = oidc_provider.exchange_code(
            code=code or "",
            code_verifier=attempt.code_verifier,
        )
        validate_oidc_nonce(attempt, identity)
        user, newly_bound = resolve_oidc_user(db, identity)
    except AdminOidcError as exc:
        db.rollback()
        return _record_oidc_failure_and_redirect(
            request,
            db,
            attempt_id=attempt_id,
            return_to=return_to,
            code=exc.code,
        )

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
        action="admin.session.oidc_login",
        resource_type="user",
        resource_id=str(user.id),
        result="success",
        after={"admin_role": user.admin_role, "identity_bound": newly_bound},
    )
    db.commit()

    response = RedirectResponse(_admin_web_url(return_to), status_code=303)
    _set_session_cookie(response, issued.session_token, expires_at=issued.record.expires_at)
    _set_csrf_cookie(response, issued.csrf_token, expires_at=issued.record.expires_at)
    _delete_oidc_binding_cookie(response)
    _set_private_response_headers(request, response)
    return response


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


def _record_oidc_failure_and_redirect(
    request: Request,
    db: Session,
    *,
    attempt_id: str,
    return_to: str,
    code: str,
) -> RedirectResponse:
    record_audit_event(
        db,
        request=request,
        actor_user_id=None,
        action="admin.session.oidc_login",
        resource_type="admin_oidc_login_attempt",
        resource_id=attempt_id,
        result="failure",
        reason=code,
    )
    db.commit()
    return _oidc_error_redirect(request, code, return_to=return_to)


def _oidc_error_redirect(
    request: Request,
    code: str,
    *,
    return_to: str = "/content/players",
) -> RedirectResponse:
    query = urlencode({"oidcError": code, "returnTo": safe_return_to(return_to)})
    response = RedirectResponse(_admin_web_url(f"/login?{query}"), status_code=303)
    _delete_oidc_binding_cookie(response)
    _set_private_response_headers(request, response)
    return response


def _admin_web_url(path: str) -> str:
    return f"{settings.admin_oidc_web_base_url.rstrip('/')}{path}"


def _oidc_binding_cookie_name() -> str:
    return f"{settings.admin_session_cookie_name}_oidc"


def _delete_oidc_binding_cookie(response: Response) -> None:
    response.delete_cookie(
        key=_oidc_binding_cookie_name(),
        path=_admin_cookie_path(),
        secure=settings.admin_session_cookie_secure,
        httponly=True,
        samesite="lax",
    )
