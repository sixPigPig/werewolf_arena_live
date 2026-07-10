from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request, Response
from sqlalchemy.exc import OperationalError, ProgrammingError
from sqlalchemy.orm import Session

from app.api.schemas.public_player_profiles import (
    PublicPlayerProfileListResponse,
    PublicPlayerProfileResponse,
)
from app.db.session import get_db
from app.api.admin.errors import request_id_for
from app.player_profiles.errors import PlayerProfileNotFound
from app.player_profiles.service import (
    get_published_player_profile,
    list_public_player_profiles,
)
from app.player_profiles.snapshots import public_player_profile_snapshot

router = APIRouter()
RecoverableDatabaseError = (OperationalError, ProgrammingError)


@router.get("", response_model=PublicPlayerProfileListResponse)
def list_public_profiles(
    request: Request,
    response: Response,
    db: Annotated[Session, Depends(get_db)],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> PublicPlayerProfileListResponse:
    try:
        result = list_public_player_profiles(db, page=page, page_size=page_size)
    except RecoverableDatabaseError as exc:
        raise HTTPException(status_code=503, detail="Player profile database unavailable") from exc
    _set_public_cache_headers(request, response)
    return PublicPlayerProfileListResponse(
        items=[public_player_profile_snapshot(profile) for profile in result.items],
        pagination={
            "page": result.page,
            "page_size": result.page_size,
            "total": result.total,
            "pages": result.pages,
        },
    )


@router.get("/{profile_id}", response_model=PublicPlayerProfileResponse)
def get_public_profile(
    profile_id: Annotated[str, Path(min_length=1, max_length=36)],
    request: Request,
    response: Response,
    db: Annotated[Session, Depends(get_db)],
) -> PublicPlayerProfileResponse:
    try:
        profile = get_published_player_profile(db, profile_id)
    except PlayerProfileNotFound as exc:
        raise HTTPException(status_code=404, detail="Player profile not found") from exc
    except RecoverableDatabaseError as exc:
        raise HTTPException(status_code=503, detail="Player profile database unavailable") from exc
    _set_public_cache_headers(request, response)
    return PublicPlayerProfileResponse.model_validate(public_player_profile_snapshot(profile))


def _set_public_cache_headers(request: Request, response: Response) -> None:
    response.headers["Cache-Control"] = "public, max-age=60"
    response.headers["X-Request-ID"] = request_id_for(request)
