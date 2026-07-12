from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request
from sqlalchemy.exc import OperationalError, ProgrammingError
from sqlalchemy.orm import Session

from app.api.admin.errors import request_id_for
from app.core.config import settings
from app.db.session import get_db
from app.models.public import PublicSession
from app.models.user import User
from app.public.session import (
    find_public_session,
    public_csrf_token_matches,
    public_session_is_expired,
)


@dataclass(frozen=True)
class PublicPrincipal:
    user: User
    session: PublicSession


def get_current_public_principal(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
) -> PublicPrincipal:
    session_token = request.cookies.get(settings.public_session_cookie_name)
    if not session_token:
        raise public_problem(
            request,
            status_code=401,
            code="public_session_required",
            detail="A valid public session is required.",
        )
    try:
        session = find_public_session(db, session_token)
    except (OperationalError, ProgrammingError) as exc:
        raise public_problem(
            request,
            status_code=503,
            code="public_session_database_unavailable",
            detail="Public session data is temporarily unavailable.",
        ) from exc
    if session is None or session.revoked_at is not None or public_session_is_expired(session):
        raise public_problem(
            request,
            status_code=401,
            code="public_session_required",
            detail="A valid public session is required.",
        )
    try:
        user = db.get(User, session.user_id)
    except (OperationalError, ProgrammingError) as exc:
        raise public_problem(
            request,
            status_code=503,
            code="public_session_database_unavailable",
            detail="Public session data is temporarily unavailable.",
        ) from exc
    if user is None or not user.is_active or user.auth_provider != "guest":
        raise public_problem(
            request,
            status_code=401,
            code="public_session_required",
            detail="A valid public session is required.",
        )
    return PublicPrincipal(user=user, session=session)


def require_public_csrf(
    request: Request,
    principal: Annotated[PublicPrincipal, Depends(get_current_public_principal)],
    csrf_token: Annotated[str | None, Header(alias="X-CSRF-Token")] = None,
) -> PublicPrincipal:
    validate_public_origin(request)
    if not public_csrf_token_matches(principal.session, csrf_token):
        raise public_problem(
            request,
            status_code=403,
            code="public_csrf_invalid",
            detail="A valid CSRF token is required for this operation.",
        )
    return principal


def public_problem(
    request: Request,
    *,
    status_code: int,
    code: str,
    detail: str,
    extensions: Mapping[str, object] | None = None,
) -> HTTPException:
    request_id = request_id_for(request)
    problem_detail = dict(extensions or {})
    problem_detail.update({"code": code, "message": detail, "request_id": request_id})
    return HTTPException(
        status_code=status_code,
        detail=problem_detail,
        headers={
            "Cache-Control": "private, no-store",
            "Pragma": "no-cache",
            "X-Request-ID": request_id,
        },
    )


def validate_public_origin(request: Request) -> None:
    origin = request.headers.get("origin")
    if not origin:
        return
    allowed_origins = {value.rstrip("/") for value in settings.public_cors_origins}
    if origin.rstrip("/") not in allowed_origins:
        raise public_problem(
            request,
            status_code=403,
            code="public_origin_invalid",
            detail="This origin is not allowed to perform public writes.",
        )
