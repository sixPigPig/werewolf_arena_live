from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class PublicViewerResponse(BaseModel):
    kind: Literal["guest"] = "guest"


class PublicSessionResponse(BaseModel):
    viewer: PublicViewerResponse
    csrf_token: str
    session_expires_at: datetime


class PublicPlayerProfileFavoritesResponse(BaseModel):
    profile_ids: list[str]


class PublicPlayerProfileFavoriteMutationResponse(BaseModel):
    profile_id: str
    is_favorite: bool
