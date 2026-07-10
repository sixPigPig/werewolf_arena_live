from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Path, Request, Response
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.exc import OperationalError, ProgrammingError
from sqlalchemy.orm import Session

from app.api.admin.errors import request_id_for
from app.api.public.dependencies import (
    PublicPrincipal,
    get_current_public_principal,
    public_problem,
    require_public_csrf,
    validate_public_origin,
)
from app.api.schemas.public_session import (
    PublicPlayerProfileFavoriteMutationResponse,
    PublicPlayerProfileFavoritesResponse,
    PublicSessionResponse,
    PublicViewerResponse,
)
from app.core.config import settings
from app.db.session import get_db
from app.models.public import PublicSession, UserFavoritePlayerProfile
from app.models.user import User
from app.models.virtual_player_profile import VirtualPlayerProfile
from app.player_profiles.errors import PlayerProfileNotFound
from app.player_profiles.service import get_published_player_profile
from app.public.rate_limit import (
    public_favorite_write_limiter,
    public_session_creation_limiter,
)
from app.public.session import (
    as_utc,
    create_guest_public_session,
    delete_expired_public_sessions,
    find_public_session,
    public_csrf_token_matches,
    public_session_is_expired,
    refresh_public_session,
    rotate_public_csrf_token,
)

router = APIRouter()
RecoverableDatabaseError = (OperationalError, ProgrammingError)


@router.post("/session", response_model=PublicSessionResponse)
def bootstrap_public_session(
    request: Request,
    response: Response,
    db: Annotated[Session, Depends(get_db)],
) -> PublicSessionResponse:
    raw_session_token = request.cookies.get(settings.public_session_cookie_name)
    validate_public_origin(request)
    try:
        existing = (
            find_public_session(db, raw_session_token)
            if raw_session_token
            else None
        )
        user = db.get(User, existing.user_id) if existing is not None else None
        if (
            existing is not None
            and existing.revoked_at is None
            and not public_session_is_expired(existing)
            and user is not None
            and user.is_active
            and user.auth_provider == "guest"
        ):
            assert raw_session_token is not None
            csrf_token = _reuse_or_rotate_csrf_token(request, existing)
            refresh_public_session(
                existing,
                ttl_seconds=settings.public_session_ttl_seconds,
            )
            session = existing
            session_token = raw_session_token
        else:
            _enforce_session_creation_rate_limit(request)
            delete_expired_public_sessions(db)
            issued = create_guest_public_session(
                db,
                ttl_seconds=settings.public_session_ttl_seconds,
            )
            session = issued.record
            session_token = issued.session_token
            csrf_token = issued.csrf_token
        db.commit()
    except HTTPException:
        db.rollback()
        raise
    except RecoverableDatabaseError as exc:
        db.rollback()
        raise public_problem(
            request,
            status_code=503,
            code="public_session_database_unavailable",
            detail="Public session data is temporarily unavailable.",
        ) from exc

    _set_public_session_cookie(response, session_token, expires_at=session.expires_at)
    _set_public_csrf_cookie(response, csrf_token, expires_at=session.expires_at)
    _set_private_headers(request, response)
    return _session_response(session, csrf_token)


@router.get("/me", response_model=PublicSessionResponse)
def get_public_me(
    request: Request,
    response: Response,
    db: Annotated[Session, Depends(get_db)],
    principal: Annotated[PublicPrincipal, Depends(get_current_public_principal)],
) -> PublicSessionResponse:
    csrf_token = _reuse_or_rotate_csrf_token(request, principal.session)
    refresh_public_session(
        principal.session,
        ttl_seconds=settings.public_session_ttl_seconds,
    )
    try:
        db.commit()
    except RecoverableDatabaseError as exc:
        db.rollback()
        raise public_problem(
            request,
            status_code=503,
            code="public_session_database_unavailable",
            detail="Public session data is temporarily unavailable.",
        ) from exc
    raw_session_token = request.cookies.get(settings.public_session_cookie_name)
    if raw_session_token:
        _set_public_session_cookie(
            response,
            raw_session_token,
            expires_at=principal.session.expires_at,
        )
    _set_public_csrf_cookie(
        response,
        csrf_token,
        expires_at=principal.session.expires_at,
    )
    _set_private_headers(request, response)
    return _session_response(principal.session, csrf_token)


@router.get(
    "/me/favorite-player-profiles",
    response_model=PublicPlayerProfileFavoritesResponse,
)
def list_public_player_profile_favorites(
    request: Request,
    response: Response,
    db: Annotated[Session, Depends(get_db)],
    principal: Annotated[PublicPrincipal, Depends(get_current_public_principal)],
) -> PublicPlayerProfileFavoritesResponse:
    try:
        profile_ids = list(
            db.scalars(
                select(UserFavoritePlayerProfile.player_profile_id)
                .join(
                    VirtualPlayerProfile,
                    VirtualPlayerProfile.id
                    == UserFavoritePlayerProfile.player_profile_id,
                )
                .where(
                    UserFavoritePlayerProfile.user_id == principal.user.id,
                    VirtualPlayerProfile.status == "published",
                    VirtualPlayerProfile.deleted_at.is_(None),
                )
                .order_by(
                    VirtualPlayerProfile.display_order.asc(),
                    VirtualPlayerProfile.id.asc(),
                )
            )
        )
    except RecoverableDatabaseError as exc:
        raise public_problem(
            request,
            status_code=503,
            code="public_favorites_database_unavailable",
            detail="Player profile favorites are temporarily unavailable.",
        ) from exc
    _set_private_headers(request, response)
    return PublicPlayerProfileFavoritesResponse(profile_ids=profile_ids)


@router.put(
    "/me/favorite-player-profiles/{profile_id}",
    response_model=PublicPlayerProfileFavoriteMutationResponse,
)
def favorite_public_player_profile(
    profile_id: Annotated[str, Path(min_length=1, max_length=36)],
    request: Request,
    response: Response,
    db: Annotated[Session, Depends(get_db)],
    principal: Annotated[PublicPrincipal, Depends(require_public_csrf)],
) -> PublicPlayerProfileFavoriteMutationResponse:
    return _write_favorite(
        profile_id=profile_id,
        request=request,
        response=response,
        db=db,
        principal=principal,
        method="favorite",
    )


@router.delete(
    "/me/favorite-player-profiles/{profile_id}",
    response_model=PublicPlayerProfileFavoriteMutationResponse,
)
def unfavorite_public_player_profile(
    profile_id: Annotated[str, Path(min_length=1, max_length=36)],
    request: Request,
    response: Response,
    db: Annotated[Session, Depends(get_db)],
    principal: Annotated[PublicPrincipal, Depends(require_public_csrf)],
) -> PublicPlayerProfileFavoriteMutationResponse:
    return _write_favorite(
        profile_id=profile_id,
        request=request,
        response=response,
        db=db,
        principal=principal,
        method="unfavorite",
    )


def _write_favorite(
    *,
    profile_id: str,
    request: Request,
    response: Response,
    db: Session,
    principal: PublicPrincipal,
    method: Literal["favorite", "unfavorite"],
) -> PublicPlayerProfileFavoriteMutationResponse:
    _enforce_favorite_write_rate_limit(request, principal.session.id)
    try:
        get_published_player_profile(db, profile_id)
        if method == "favorite":
            _insert_favorite_if_missing(db, principal.user.id, profile_id)
            is_favorite = True
        else:
            db.query(UserFavoritePlayerProfile).filter(
                UserFavoritePlayerProfile.user_id == principal.user.id,
                UserFavoritePlayerProfile.player_profile_id == profile_id,
            ).delete(synchronize_session=False)
            is_favorite = False
        db.commit()
    except PlayerProfileNotFound as exc:
        db.rollback()
        raise public_problem(
            request,
            status_code=404,
            code="public_player_profile_not_found",
            detail="Player profile not found.",
        ) from exc
    except RecoverableDatabaseError as exc:
        db.rollback()
        raise public_problem(
            request,
            status_code=503,
            code="public_favorites_database_unavailable",
            detail="Player profile favorites are temporarily unavailable.",
        ) from exc
    _set_private_headers(request, response)
    return PublicPlayerProfileFavoriteMutationResponse(
        profile_id=profile_id,
        is_favorite=is_favorite,
    )


def _insert_favorite_if_missing(db: Session, user_id: int, profile_id: str) -> None:
    values = {
        "user_id": user_id,
        "player_profile_id": profile_id,
        "created_at": datetime.now().astimezone(),
    }
    table = UserFavoritePlayerProfile.__table__
    dialect_name = db.get_bind().dialect.name
    if dialect_name == "postgresql":
        statement = postgresql_insert(table).values(**values).on_conflict_do_nothing(
            index_elements=["user_id", "player_profile_id"]
        )
    elif dialect_name == "sqlite":
        statement = sqlite_insert(table).values(**values).on_conflict_do_nothing(
            index_elements=["user_id", "player_profile_id"]
        )
    else:
        existing = db.get(UserFavoritePlayerProfile, (user_id, profile_id))
        if existing is None:
            db.add(UserFavoritePlayerProfile(**values))
        return
    db.execute(statement)


def _session_response(
    session: PublicSession,
    csrf_token: str,
) -> PublicSessionResponse:
    return PublicSessionResponse(
        viewer=PublicViewerResponse(),
        csrf_token=csrf_token,
        session_expires_at=as_utc(session.expires_at),
    )


def _set_private_headers(request: Request, response: Response) -> None:
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["Pragma"] = "no-cache"
    response.headers["X-Request-ID"] = request_id_for(request)


def _set_public_session_cookie(
    response: Response,
    session_token: str,
    *,
    expires_at: datetime,
) -> None:
    response.set_cookie(
        key=settings.public_session_cookie_name,
        value=session_token,
        max_age=settings.public_session_ttl_seconds,
        expires=as_utc(expires_at),
        path=f"{settings.api_v1_prefix.rstrip('/')}/public",
        secure=settings.public_session_cookie_secure,
        httponly=True,
        samesite="lax",
    )


def _set_public_csrf_cookie(
    response: Response,
    csrf_token: str,
    *,
    expires_at: datetime,
) -> None:
    response.set_cookie(
        key=_public_csrf_cookie_name(),
        value=csrf_token,
        max_age=settings.public_session_ttl_seconds,
        expires=as_utc(expires_at),
        path=f"{settings.api_v1_prefix.rstrip('/')}/public",
        secure=settings.public_session_cookie_secure,
        httponly=False,
        samesite="lax",
    )


def _reuse_or_rotate_csrf_token(
    request: Request,
    session: PublicSession,
) -> str:
    candidate = request.cookies.get(_public_csrf_cookie_name())
    if public_csrf_token_matches(session, candidate):
        assert candidate is not None
        return candidate
    return rotate_public_csrf_token(session)


def _public_csrf_cookie_name() -> str:
    return f"{settings.public_session_cookie_name}_csrf"


def _enforce_session_creation_rate_limit(request: Request) -> None:
    key = f"session:{_client_ip(request) or 'unknown'}"
    if not public_session_creation_limiter.allow(
        key,
        limit=120,
        window_seconds=60,
    ):
        raise public_problem(
            request,
            status_code=429,
            code="public_session_rate_limited",
            detail="Too many public sessions were created. Try again later.",
        )


def _enforce_favorite_write_rate_limit(request: Request, session_id: str) -> None:
    key = f"favorite:{session_id}"
    if not public_favorite_write_limiter.allow(
        key,
        limit=120,
        window_seconds=60,
    ):
        raise public_problem(
            request,
            status_code=429,
            code="public_favorite_rate_limited",
            detail="Too many favorite changes were requested. Try again later.",
        )


def _client_ip(request: Request) -> str | None:
    return request.client.host[:45] if request.client else None
