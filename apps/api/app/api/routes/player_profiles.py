from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy.exc import OperationalError, ProgrammingError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import get_db
from app.models.virtual_player_profile import VirtualPlayerProfile
from app.werewolf.player_profile_store import (
    PlayerProfileFileStore,
    player_profile_store_for_logs_dir,
)
from app.werewolf.player_presets import (
    default_personality_text,
    is_valid_appearance,
    is_valid_personality,
)


router = APIRouter()

RecoverableDatabaseError = (OperationalError, ProgrammingError)


def _trim_string(value: str) -> str:
    return value.strip()


def _normalize_tags(tags: list[str]) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for tag in tags:
        trimmed = tag.strip()
        if not trimmed or trimmed in seen:
            continue
        if len(trimmed) > 20:
            raise ValueError("Tags must be 20 characters or fewer")
        normalized.append(trimmed)
        seen.add(trimmed)
    if len(normalized) > 8:
        raise ValueError("At most 8 tags are allowed")
    return normalized


def _validate_presets(personality_id: str, appearance_id: str) -> None:
    if not is_valid_personality(personality_id):
        raise HTTPException(status_code=422, detail=f"Unknown personality_id: {personality_id}")
    if not is_valid_appearance(appearance_id):
        raise HTTPException(status_code=422, detail=f"Unknown appearance_id: {appearance_id}")


class PlayerProfileBase(BaseModel):
    display_name: str = Field(min_length=1, max_length=80)
    model: str = Field(min_length=1, max_length=120)
    personality_id: str = Field(default="balanced", min_length=1, max_length=40)
    personality_text: str = ""
    appearance_id: str = Field(default="default", min_length=1, max_length=40)
    avatar_prompt: str = Field(default="", max_length=1000)
    tags: list[str] = Field(default_factory=list)

    @field_validator(
        "display_name",
        "model",
        "personality_id",
        "personality_text",
        "appearance_id",
        "avatar_prompt",
        mode="before",
    )
    @classmethod
    def trim_strings(cls, value: str) -> str:
        if isinstance(value, str):
            return _trim_string(value)
        return value

    @field_validator("tags")
    @classmethod
    def normalize_tags(cls, value: list[str]) -> list[str]:
        return _normalize_tags(value)


class CreatePlayerProfileRequest(PlayerProfileBase):
    pass


class UpdatePlayerProfileRequest(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=80)
    model: str | None = Field(default=None, min_length=1, max_length=120)
    personality_id: str | None = Field(default=None, min_length=1, max_length=40)
    personality_text: str | None = None
    appearance_id: str | None = Field(default=None, min_length=1, max_length=40)
    avatar_prompt: str | None = Field(default=None, max_length=1000)
    tags: list[str] | None = None

    @model_validator(mode="before")
    @classmethod
    def reject_null_non_nullable_fields(cls, data: object) -> object:
        if not isinstance(data, dict):
            return data
        null_fields = [
            field_name
            for field_name in (
                "display_name",
                "model",
                "personality_id",
                "personality_text",
                "appearance_id",
                "avatar_prompt",
                "tags",
            )
            if field_name in data and data[field_name] is None
        ]
        if null_fields:
            raise ValueError(f"Fields may not be null: {', '.join(null_fields)}")
        return data

    @field_validator(
        "display_name",
        "model",
        "personality_id",
        "personality_text",
        "appearance_id",
        "avatar_prompt",
        mode="before",
    )
    @classmethod
    def trim_strings(cls, value: str | None) -> str | None:
        if isinstance(value, str):
            return _trim_string(value)
        return value

    @field_validator("tags")
    @classmethod
    def normalize_tags(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        return _normalize_tags(value)


class PlayerProfileResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    owner_user_id: int | None
    display_name: str
    model: str
    personality_id: str
    personality_text: str
    appearance_id: str
    avatar_prompt: str
    tags: list[str]
    created_at: datetime
    updated_at: datetime


class PlayerProfileListResponse(BaseModel):
    profiles: list[PlayerProfileResponse]


def get_player_profile_store() -> PlayerProfileFileStore:
    return player_profile_store_for_logs_dir(settings.werewolf_logs_dir)


@router.get("", response_model=PlayerProfileListResponse)
def list_player_profiles(
    db: Annotated[Session, Depends(get_db)],
    store: Annotated[PlayerProfileFileStore, Depends(get_player_profile_store)],
) -> PlayerProfileListResponse:
    try:
        profiles = (
            db.query(VirtualPlayerProfile)
            .order_by(VirtualPlayerProfile.updated_at.desc(), VirtualPlayerProfile.id.desc())
            .all()
        )
    except RecoverableDatabaseError:
        profiles = store.list_profiles()
    return PlayerProfileListResponse(profiles=profiles)


@router.post("", response_model=PlayerProfileResponse, status_code=201)
def create_player_profile(
    request: CreatePlayerProfileRequest,
    db: Annotated[Session, Depends(get_db)],
    store: Annotated[PlayerProfileFileStore, Depends(get_player_profile_store)],
) -> VirtualPlayerProfile:
    _validate_presets(request.personality_id, request.appearance_id)
    personality_text = request.personality_text or default_personality_text(request.personality_id)
    profile = VirtualPlayerProfile(
        id=str(uuid.uuid4()),
        owner_user_id=None,
        display_name=request.display_name,
        model=request.model,
        personality_id=request.personality_id,
        personality_text=personality_text,
        appearance_id=request.appearance_id,
        avatar_prompt=request.avatar_prompt,
        tags=request.tags,
    )
    try:
        db.add(profile)
        db.commit()
        db.refresh(profile)
        return profile
    except RecoverableDatabaseError:
        db.rollback()
        return store.create_profile(
            display_name=request.display_name,
            model=request.model,
            personality_id=request.personality_id,
            personality_text=personality_text,
            appearance_id=request.appearance_id,
            avatar_prompt=request.avatar_prompt,
            tags=request.tags,
        )


@router.get("/{profile_id}", response_model=PlayerProfileResponse)
def get_player_profile(
    profile_id: str,
    db: Annotated[Session, Depends(get_db)],
    store: Annotated[PlayerProfileFileStore, Depends(get_player_profile_store)],
) -> VirtualPlayerProfile:
    return _get_profile_or_404(profile_id, db, store)


@router.patch("/{profile_id}", response_model=PlayerProfileResponse)
def update_player_profile(
    profile_id: str,
    request: UpdatePlayerProfileRequest,
    db: Annotated[Session, Depends(get_db)],
    store: Annotated[PlayerProfileFileStore, Depends(get_player_profile_store)],
) -> VirtualPlayerProfile:
    profile = _get_profile_or_404(profile_id, db, store)
    updates = request.model_dump(exclude_unset=True)

    personality_changed = (
        "personality_id" in updates and updates["personality_id"] != profile.personality_id
    )
    personality_id = updates.get("personality_id", profile.personality_id)
    appearance_id = updates.get("appearance_id", profile.appearance_id)
    _validate_presets(personality_id, appearance_id)

    if not isinstance(profile, VirtualPlayerProfile):
        if personality_changed and "personality_text" not in updates:
            updates["personality_text"] = default_personality_text(personality_id)
        elif "personality_text" in updates and not updates["personality_text"]:
            updates["personality_text"] = default_personality_text(personality_id)
        updated_profile = store.update_profile(profile_id, updates)
        if updated_profile is None:
            raise HTTPException(status_code=404, detail="Player profile not found")
        return updated_profile

    try:
        for field_name, value in updates.items():
            setattr(profile, field_name, value)

        if personality_changed and "personality_text" not in updates:
            profile.personality_text = default_personality_text(personality_id)
        elif "personality_text" in updates and not profile.personality_text:
            profile.personality_text = default_personality_text(profile.personality_id)

        profile.updated_at = datetime.now(UTC)
        db.commit()
        db.refresh(profile)
        return profile
    except RecoverableDatabaseError:
        db.rollback()
        fallback_updates = request.model_dump(exclude_unset=True)
        if personality_changed and "personality_text" not in fallback_updates:
            fallback_updates["personality_text"] = default_personality_text(personality_id)
        elif "personality_text" in fallback_updates and not fallback_updates["personality_text"]:
            fallback_updates["personality_text"] = default_personality_text(personality_id)
        updated_profile = store.update_profile(profile_id, fallback_updates)
        if updated_profile is None:
            raise HTTPException(status_code=404, detail="Player profile not found")
        return updated_profile


@router.delete("/{profile_id}", status_code=204)
def delete_player_profile(
    profile_id: str,
    db: Annotated[Session, Depends(get_db)],
    store: Annotated[PlayerProfileFileStore, Depends(get_player_profile_store)],
) -> Response:
    profile = _get_profile_or_404(profile_id, db, store)
    if not isinstance(profile, VirtualPlayerProfile):
        store.delete_profile(profile_id)
        return Response(status_code=204)
    try:
        db.delete(profile)
        db.commit()
    except RecoverableDatabaseError:
        db.rollback()
        if not store.delete_profile(profile_id):
            raise HTTPException(status_code=404, detail="Player profile not found") from None
    return Response(status_code=204)


def _get_profile_or_404(
    profile_id: str,
    db: Session,
    store: PlayerProfileFileStore,
) -> object:
    try:
        profile = db.get(VirtualPlayerProfile, profile_id)
    except RecoverableDatabaseError:
        profile = store.get_profile(profile_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="Player profile not found")
    return profile
