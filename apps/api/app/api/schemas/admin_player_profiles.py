from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.api.schemas.common import PaginationResponse

from app.werewolf.player_presets import (
    is_valid_appearance,
    is_valid_personality,
    is_valid_strategy,
)

PlayerProfileStatus = Literal["draft", "published", "archived"]
PlayerProfileSort = Literal[
    "display_order",
    "-display_order",
    "updated_at",
    "-updated_at",
    "display_name",
    "-display_name",
    "created_at",
    "-created_at",
]


def normalize_tags(tags: list[str]) -> list[str]:
    return normalize_limited_strings(tags, max_items=8, max_length=20, label="Tags")


def normalize_limited_strings(
    value: list[str],
    *,
    max_items: int,
    max_length: int,
    label: str = "Items",
) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, str):
            raise ValueError(f"{label} must be strings")
        trimmed = item.strip()
        if not trimmed or trimmed in seen:
            continue
        if len(trimmed) > max_length:
            raise ValueError(f"{label} must be {max_length} characters or fewer")
        normalized.append(trimmed)
        seen.add(trimmed)
    if len(normalized) > max_items:
        raise ValueError(f"At most {max_items} {label.lower()} are allowed")
    return normalized


class AdminRequestModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AdminPlayerProfileContent(AdminRequestModel):
    display_name: str = Field(min_length=1, max_length=80)
    model: str = Field(min_length=1, max_length=120)
    personality_id: str = Field(default="balanced", min_length=1, max_length=40)
    personality_text: str = ""
    appearance_id: str = Field(default="default", min_length=1, max_length=40)
    avatar_asset_id: str | None = Field(default=None, max_length=80)
    short_description: str = Field(default="", max_length=160)
    background_story: str = Field(default="", max_length=1200)
    speaking_style: str = Field(default="", max_length=800)
    catchphrases: list[str] = Field(default_factory=list)
    strategy_profile: str = Field(default="balanced", min_length=1, max_length=40)
    risk_tolerance: int = Field(default=3, ge=1, le=5)
    bluffing_tendency: int = Field(default=3, ge=1, le=5)
    trust_tendency: int = Field(default=3, ge=1, le=5)
    leadership_tendency: int = Field(default=3, ge=1, le=5)
    talkativeness: int = Field(default=3, ge=1, le=5)
    example_messages: list[str] = Field(default_factory=list)
    featured: bool = False
    tags: list[str] = Field(default_factory=list)

    @field_validator(
        "display_name",
        "model",
        "personality_id",
        "personality_text",
        "appearance_id",
        "avatar_asset_id",
        "short_description",
        "background_story",
        "speaking_style",
        "strategy_profile",
        mode="before",
    )
    @classmethod
    def trim_strings(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @field_validator("personality_id")
    @classmethod
    def validate_personality(cls, value: str) -> str:
        if not is_valid_personality(value):
            raise ValueError(f"Unknown personality_id: {value}")
        return value

    @field_validator("appearance_id")
    @classmethod
    def validate_appearance(cls, value: str) -> str:
        if not is_valid_appearance(value):
            raise ValueError(f"Unknown appearance_id: {value}")
        return value

    @field_validator("strategy_profile")
    @classmethod
    def validate_strategy(cls, value: str) -> str:
        if not is_valid_strategy(value):
            raise ValueError(f"Unknown strategy_profile: {value}")
        return value

    @field_validator("catchphrases", mode="before")
    @classmethod
    def validate_catchphrases(cls, value: object) -> object:
        if isinstance(value, list):
            return normalize_limited_strings(
                value,
                max_items=6,
                max_length=40,
                label="Catchphrases",
            )
        return value

    @field_validator("example_messages", mode="before")
    @classmethod
    def validate_example_messages(cls, value: object) -> object:
        if isinstance(value, list):
            return normalize_limited_strings(
                value,
                max_items=5,
                max_length=240,
                label="Example messages",
            )
        return value

    @field_validator("tags", mode="before")
    @classmethod
    def validate_tags(cls, value: object) -> object:
        return normalize_tags(value) if isinstance(value, list) else value


class AdminPlayerProfileCreate(AdminPlayerProfileContent):
    @model_validator(mode="after")
    def reject_featured_draft(self) -> "AdminPlayerProfileCreate":
        if self.featured:
            raise ValueError("Draft player profiles cannot be featured")
        return self


class AdminPlayerProfileUpdate(AdminRequestModel):
    expected_version: int = Field(ge=1)
    display_name: str | None = Field(default=None, min_length=1, max_length=80)
    model: str | None = Field(default=None, min_length=1, max_length=120)
    personality_id: str | None = Field(default=None, min_length=1, max_length=40)
    personality_text: str | None = None
    appearance_id: str | None = Field(default=None, min_length=1, max_length=40)
    avatar_asset_id: str | None = Field(default=None, max_length=80)
    short_description: str | None = Field(default=None, max_length=160)
    background_story: str | None = Field(default=None, max_length=1200)
    speaking_style: str | None = Field(default=None, max_length=800)
    catchphrases: list[str] | None = None
    strategy_profile: str | None = Field(default=None, min_length=1, max_length=40)
    risk_tolerance: int | None = Field(default=None, ge=1, le=5)
    bluffing_tendency: int | None = Field(default=None, ge=1, le=5)
    trust_tendency: int | None = Field(default=None, ge=1, le=5)
    leadership_tendency: int | None = Field(default=None, ge=1, le=5)
    talkativeness: int | None = Field(default=None, ge=1, le=5)
    example_messages: list[str] | None = None
    featured: bool | None = None
    tags: list[str] | None = None

    @model_validator(mode="before")
    @classmethod
    def reject_null_non_nullable_fields(cls, data: object) -> object:
        if not isinstance(data, dict):
            return data
        nullable_fields = {"avatar_asset_id"}
        null_fields = [
            field_name
            for field_name, value in data.items()
            if field_name not in nullable_fields
            and field_name != "expected_version"
            and value is None
        ]
        if null_fields:
            raise ValueError(f"Fields may not be null: {', '.join(sorted(null_fields))}")
        return data

    @model_validator(mode="after")
    def require_update_field(self) -> "AdminPlayerProfileUpdate":
        if not (self.model_fields_set - {"expected_version"}):
            raise ValueError("At least one player profile field must be updated")
        return self

    @field_validator(
        "display_name",
        "model",
        "personality_id",
        "personality_text",
        "appearance_id",
        "avatar_asset_id",
        "short_description",
        "background_story",
        "speaking_style",
        "strategy_profile",
        mode="before",
    )
    @classmethod
    def trim_strings(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @field_validator("personality_id")
    @classmethod
    def validate_personality(cls, value: str | None) -> str | None:
        if value is not None and not is_valid_personality(value):
            raise ValueError(f"Unknown personality_id: {value}")
        return value

    @field_validator("appearance_id")
    @classmethod
    def validate_appearance(cls, value: str | None) -> str | None:
        if value is not None and not is_valid_appearance(value):
            raise ValueError(f"Unknown appearance_id: {value}")
        return value

    @field_validator("strategy_profile")
    @classmethod
    def validate_strategy(cls, value: str | None) -> str | None:
        if value is not None and not is_valid_strategy(value):
            raise ValueError(f"Unknown strategy_profile: {value}")
        return value

    @field_validator("catchphrases", mode="before")
    @classmethod
    def validate_catchphrases(cls, value: object) -> object:
        if isinstance(value, list):
            return normalize_limited_strings(
                value,
                max_items=6,
                max_length=40,
                label="Catchphrases",
            )
        return value

    @field_validator("example_messages", mode="before")
    @classmethod
    def validate_example_messages(cls, value: object) -> object:
        if isinstance(value, list):
            return normalize_limited_strings(
                value,
                max_items=5,
                max_length=240,
                label="Example messages",
            )
        return value

    @field_validator("tags", mode="before")
    @classmethod
    def validate_tags(cls, value: object) -> object:
        return normalize_tags(value) if isinstance(value, list) else value


class AdminPlayerProfileTransition(AdminRequestModel):
    expected_version: int = Field(ge=1)
    reason: str = Field(min_length=3, max_length=500)

    @field_validator("reason", mode="before")
    @classmethod
    def trim_reason(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class AdminPlayerProfileResponse(BaseModel):
    id: str
    display_name: str
    model: str
    personality_id: str
    personality_text: str
    appearance_id: str
    avatar_asset_id: str | None
    avatar_image_url: str
    avatar_image_mime: str
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
    status: PlayerProfileStatus
    version: int
    created_at: datetime
    updated_at: datetime
    published_at: datetime | None
    deleted_at: datetime | None
    published_by: str | None
    updated_by: str | None


class AdminPlayerProfileListResponse(BaseModel):
    items: list[AdminPlayerProfileResponse]
    pagination: PaginationResponse


class PlayerProfileOption(BaseModel):
    id: str
    label: str
    description: str = ""


class PlayerAppearanceOption(PlayerProfileOption):
    avatar_asset_id: str | None
    avatar_image_url: str = ""


class PlayerProfileConstraints(BaseModel):
    tags_max_items: int
    tag_max_length: int
    catchphrases_max_items: int
    catchphrase_max_length: int
    example_messages_max_items: int
    example_message_max_length: int


class AdminPlayerProfileOptionsResponse(BaseModel):
    models: list[PlayerProfileOption]
    personalities: list[PlayerProfileOption]
    appearances: list[PlayerAppearanceOption]
    strategies: list[PlayerProfileOption]
    constraints: PlayerProfileConstraints


class AdminPlayerProfileAiDraftRequest(AdminRequestModel):
    mode: Literal["name", "template"] = "template"


class AdminPlayerProfileAiDraftResponse(BaseModel):
    display_name: str = Field(default="", max_length=80)
    personality_id: str = Field(default="balanced", max_length=40)
    personality_text: str
    short_description: str = Field(default="", max_length=160)
    background_story: str = Field(default="", max_length=1200)
    speaking_style: str = Field(default="", max_length=800)
    catchphrases: list[str]
    strategy_profile: str = Field(default="balanced", max_length=40)
    risk_tolerance: int = Field(ge=1, le=5)
    bluffing_tendency: int = Field(ge=1, le=5)
    trust_tendency: int = Field(ge=1, le=5)
    leadership_tendency: int = Field(ge=1, le=5)
    talkativeness: int = Field(ge=1, le=5)
    example_messages: list[str]
    tags: list[str]
