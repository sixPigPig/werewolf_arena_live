from __future__ import annotations

from pydantic import BaseModel

from app.api.schemas.common import PaginationResponse


class PublicPlayerProfileResponse(BaseModel):
    id: str
    display_name: str
    model_provider: str
    model: str
    personality_id: str
    personality_text: str
    appearance_id: str
    avatar_image_url: str
    short_description: str
    background_story: str
    speaking_style: str
    catchphrases: list[str]
    strategy_profile: str
    risk_tolerance: int
    bluffing_tendency: int
    trust_tendency: int
    leadership_tendency: int
    talkativeness: int
    example_messages: list[str]
    display_order: int
    featured: bool
    tags: list[str]


class PublicPlayerProfileListResponse(BaseModel):
    items: list[PublicPlayerProfileResponse]
    pagination: PaginationResponse
