from __future__ import annotations

import json
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Path, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator
from sqlalchemy.exc import OperationalError, ProgrammingError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import get_db
from app.models.player_avatar_asset import PlayerAvatarAsset
from app.models.virtual_player_profile import VirtualPlayerProfile
from app.player_profiles.errors import (
    PlayerProfileNotFound,
    PlayerProfileTransitionError,
    PlayerProfileValidationError,
    PlayerProfileVersionConflict,
)
from app.player_profiles.service import (
    archive_player_profile as archive_profile_service,
    create_player_profile as create_profile_service,
    get_published_player_profile as get_published_profile_service,
    list_published_player_profiles,
    update_player_profile as update_profile_service,
)
from app.werewolf.player_avatar_assets import (
    PlayerAvatarAssetStore,
    avatar_asset_url,
    player_avatar_asset_store_for_logs_dir,
    save_uploaded_avatar_asset,
)
from app.werewolf.player_presets import (
    is_valid_personality,
    is_valid_strategy,
)
from app.werewolf.providers import create_model_provider


router = APIRouter()

RecoverableDatabaseError = (OperationalError, ProgrammingError)
PLAYER_PROFILE_DATABASE_UNAVAILABLE = "Player profile database unavailable"
AI_PLAYER_DRAFT_MODEL = "deepseek-v4-flash"


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


def _normalize_limited_strings(value: list[str], *, max_items: int, max_length: int) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, str):
            raise ValueError("Items must be strings")
        trimmed = item.strip()
        if not trimmed or trimmed in seen:
            continue
        if len(trimmed) > max_length:
            raise ValueError(f"Items must be {max_length} characters or fewer")
        normalized.append(trimmed)
        seen.add(trimmed)
    if len(normalized) > max_items:
        raise ValueError(f"At most {max_items} items are allowed")
    return normalized


class PlayerProfileBase(BaseModel):
    display_name: str = Field(min_length=1, max_length=80)
    model: str = Field(min_length=1, max_length=120)
    personality_id: str = Field(default="balanced", min_length=1, max_length=40)
    personality_text: str = ""
    appearance_id: str = Field(default="default", min_length=1, max_length=40)
    avatar_prompt: str = Field(default="", max_length=1000)
    avatar_asset_id: str | None = Field(default=None, max_length=80)
    avatar_image_url: str = Field(default="", max_length=1000)
    avatar_image_mime: str = Field(default="", max_length=80)
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
    favorite: bool = False
    tags: list[str] = Field(default_factory=list)

    @field_validator(
        "display_name",
        "model",
        "personality_id",
        "personality_text",
        "appearance_id",
        "avatar_prompt",
        "avatar_asset_id",
        "avatar_image_url",
        "avatar_image_mime",
        "short_description",
        "background_story",
        "speaking_style",
        "strategy_profile",
        mode="before",
    )
    @classmethod
    def trim_strings(cls, value: str) -> str:
        if isinstance(value, str):
            return _trim_string(value)
        return value

    @field_validator("strategy_profile")
    @classmethod
    def validate_strategy_profile(cls, value: str) -> str:
        if not is_valid_strategy(value):
            raise ValueError(f"Unknown strategy_profile: {value}")
        return value

    @field_validator("catchphrases", mode="before")
    @classmethod
    def normalize_catchphrases(cls, value: object) -> object:
        if isinstance(value, list):
            return _normalize_limited_strings(value, max_items=6, max_length=40)
        return value

    @field_validator("example_messages", mode="before")
    @classmethod
    def normalize_example_messages(cls, value: object) -> object:
        if isinstance(value, list):
            return _normalize_limited_strings(value, max_items=5, max_length=240)
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
    avatar_asset_id: str | None = Field(default=None, max_length=80)
    avatar_image_url: str | None = Field(default=None, max_length=1000)
    avatar_image_mime: str | None = Field(default=None, max_length=80)
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
    favorite: bool | None = None
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
                "avatar_image_url",
                "avatar_image_mime",
                "short_description",
                "background_story",
                "speaking_style",
                "catchphrases",
                "strategy_profile",
                "risk_tolerance",
                "bluffing_tendency",
                "trust_tendency",
                "leadership_tendency",
                "talkativeness",
                "example_messages",
                "favorite",
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
        "avatar_asset_id",
        "avatar_image_url",
        "avatar_image_mime",
        "short_description",
        "background_story",
        "speaking_style",
        "strategy_profile",
        mode="before",
    )
    @classmethod
    def trim_strings(cls, value: str | None) -> str | None:
        if isinstance(value, str):
            return _trim_string(value)
        return value

    @field_validator("strategy_profile")
    @classmethod
    def validate_strategy_profile(cls, value: str | None) -> str | None:
        if value is not None and not is_valid_strategy(value):
            raise ValueError(f"Unknown strategy_profile: {value}")
        return value

    @field_validator("catchphrases", mode="before")
    @classmethod
    def normalize_catchphrases(cls, value: object) -> object:
        if isinstance(value, list):
            return _normalize_limited_strings(value, max_items=6, max_length=40)
        return value

    @field_validator("example_messages", mode="before")
    @classmethod
    def normalize_example_messages(cls, value: object) -> object:
        if isinstance(value, list):
            return _normalize_limited_strings(value, max_items=5, max_length=240)
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
    favorite: bool
    tags: list[str]
    created_at: datetime
    updated_at: datetime


class PlayerProfileListResponse(BaseModel):
    profiles: list[PlayerProfileResponse]


class AvatarUploadRequest(BaseModel):
    filename: str = Field(min_length=1, max_length=180)
    content_type: str = Field(min_length=1, max_length=80)
    data_base64: str = Field(min_length=1)


class AvatarUploadResponse(BaseModel):
    avatar_asset_id: str
    avatar_image_url: str
    avatar_image_mime: str


class PlayerProfileAiDraftRequest(BaseModel):
    mode: Literal["name", "template"] = "template"
    existing_names: list[str] = Field(default_factory=list, max_length=200)

    @field_validator("existing_names")
    @classmethod
    def normalize_existing_names(cls, value: list[str]) -> list[str]:
        normalized: list[str] = []
        for name in value:
            if not isinstance(name, str):
                continue
            trimmed = name.strip()
            if trimmed:
                normalized.append(trimmed)
        return normalized


class PlayerProfileAiDraftResponse(BaseModel):
    display_name: str = Field(default="", max_length=80)
    personality_id: str = Field(default="balanced", min_length=1, max_length=40)
    personality_text: str = ""
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
    tags: list[str] = Field(default_factory=list)

    @field_validator(
        "display_name",
        "personality_id",
        "personality_text",
        "short_description",
        "background_story",
        "speaking_style",
        "strategy_profile",
        mode="before",
    )
    @classmethod
    def trim_generated_strings(cls, value: object) -> str:
        if value is None:
            return ""
        if isinstance(value, str):
            return _trim_string(value)
        return _trim_string(str(value))

    @field_validator("personality_id")
    @classmethod
    def normalize_generated_personality(cls, value: str) -> str:
        return value if is_valid_personality(value) else "balanced"

    @field_validator("strategy_profile")
    @classmethod
    def normalize_generated_strategy(cls, value: str) -> str:
        return value if is_valid_strategy(value) else "balanced"

    @field_validator(
        "risk_tolerance",
        "bluffing_tendency",
        "trust_tendency",
        "leadership_tendency",
        "talkativeness",
        mode="before",
    )
    @classmethod
    def normalize_generated_tendency(cls, value: object) -> int:
        try:
            parsed = int(round(float(value)))
        except (TypeError, ValueError):
            return 3
        return min(5, max(1, parsed))

    @field_validator("catchphrases", mode="before")
    @classmethod
    def normalize_generated_catchphrases(cls, value: object) -> object:
        if isinstance(value, list):
            return _normalize_limited_strings(value, max_items=6, max_length=40)
        return []

    @field_validator("example_messages", mode="before")
    @classmethod
    def normalize_generated_example_messages(cls, value: object) -> object:
        if isinstance(value, list):
            return _normalize_limited_strings(value, max_items=5, max_length=240)
        return []

    @field_validator("tags", mode="before")
    @classmethod
    def normalize_generated_tags(cls, value: object) -> object:
        if isinstance(value, list):
            return _normalize_tags(value)
        return []


def get_player_avatar_asset_store() -> PlayerAvatarAssetStore:
    return player_avatar_asset_store_for_logs_dir(settings.werewolf_logs_dir)


def get_player_profile_ai_provider():
    return create_model_provider()


def _profile_response(profile: VirtualPlayerProfile) -> PlayerProfileResponse:
    payload = PlayerProfileResponse.model_validate(profile)
    if profile.avatar_asset_id:
        payload.avatar_image_url = avatar_asset_url(profile.avatar_asset_id)
    return payload


@router.post("/avatar", response_model=AvatarUploadResponse, status_code=201)
def upload_player_avatar(
    request: AvatarUploadRequest,
    db: Annotated[Session, Depends(get_db)],
) -> AvatarUploadResponse:
    _require_legacy_content_writes_enabled()
    try:
        asset = save_uploaded_avatar_asset(
            db,
            content_type=request.content_type,
            data_base64=request.data_base64,
        )
        asset_id = asset.id
        asset_content_type = asset.content_type
        db.commit()
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RecoverableDatabaseError as exc:
        db.rollback()
        raise _profile_database_unavailable() from exc

    return AvatarUploadResponse(
        avatar_asset_id=asset_id,
        avatar_image_url=avatar_asset_url(asset_id),
        avatar_image_mime=asset_content_type,
    )


@router.get("/avatar-assets/{asset_id}")
def get_player_avatar_asset(
    asset_id: str,
    db: Annotated[Session, Depends(get_db)],
) -> Response:
    try:
        asset = db.get(PlayerAvatarAsset, asset_id)
    except RecoverableDatabaseError as exc:
        raise _profile_database_unavailable() from exc
    if asset is None:
        raise HTTPException(status_code=404, detail="Avatar asset not found")
    return Response(
        content=asset.data,
        media_type=asset.content_type,
        headers={"Cache-Control": "public, max-age=31536000, immutable"},
    )


@router.get("/avatar/{filename}")
def get_player_avatar(
    filename: str,
    store: Annotated[PlayerAvatarAssetStore, Depends(get_player_avatar_asset_store)],
) -> FileResponse:
    path = store.path_for(filename)
    if path is None:
        raise HTTPException(status_code=404, detail="Avatar image not found")
    return FileResponse(path, media_type=store.content_type_for(filename))


@router.get("", response_model=PlayerProfileListResponse)
def list_player_profiles(
    db: Annotated[Session, Depends(get_db)],
) -> PlayerProfileListResponse:
    try:
        profiles = list_published_player_profiles(db)
    except RecoverableDatabaseError as exc:
        raise _profile_database_unavailable() from exc
    return PlayerProfileListResponse(
        profiles=[_profile_response(profile) for profile in profiles]
    )


@router.post("", response_model=PlayerProfileResponse, status_code=201)
def create_player_profile(
    request: CreatePlayerProfileRequest,
    db: Annotated[Session, Depends(get_db)],
) -> PlayerProfileResponse:
    _require_legacy_content_writes_enabled()
    try:
        profile = create_profile_service(
            db,
            values=request.model_dump(),
            initial_status="published",
            actor_user_id=None,
            allow_external_avatar_url=True,
        )
        db.commit()
        db.refresh(profile)
        return _profile_response(profile)
    except PlayerProfileValidationError as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RecoverableDatabaseError as exc:
        db.rollback()
        raise _profile_database_unavailable() from exc


@router.post("/ai-draft", response_model=PlayerProfileAiDraftResponse)
def generate_player_profile_ai_draft(
    request: PlayerProfileAiDraftRequest,
    provider: Annotated[object, Depends(get_player_profile_ai_provider)],
) -> PlayerProfileAiDraftResponse:
    _require_legacy_content_writes_enabled()
    prompt = _build_ai_player_draft_prompt(request)
    try:
        raw_response = provider.complete_json(
            model=AI_PLAYER_DRAFT_MODEL,
            prompt=prompt,
            temperature=0.8 if request.mode == "template" else 0.65,
        )
    except Exception as exc:
        raise HTTPException(status_code=503, detail="AI player draft generation unavailable") from exc

    try:
        payload = _parse_ai_player_draft_payload(raw_response)
        draft = PlayerProfileAiDraftResponse.model_validate(payload)
    except (ValueError, ValidationError) as exc:
        raise HTTPException(status_code=502, detail="AI player draft generation failed") from exc

    draft.display_name = _next_available_generated_name(
        draft.display_name or "新玩家",
        request.existing_names,
    )
    return draft


@router.get("/{profile_id}", response_model=PlayerProfileResponse)
def get_player_profile(
    profile_id: Annotated[str, Path(min_length=1, max_length=36)],
    db: Annotated[Session, Depends(get_db)],
) -> PlayerProfileResponse:
    try:
        return _profile_response(get_published_profile_service(db, profile_id))
    except PlayerProfileNotFound as exc:
        raise HTTPException(status_code=404, detail="Player profile not found") from exc
    except RecoverableDatabaseError as exc:
        raise _profile_database_unavailable() from exc


@router.patch("/{profile_id}", response_model=PlayerProfileResponse)
def update_player_profile(
    profile_id: Annotated[str, Path(min_length=1, max_length=36)],
    request: UpdatePlayerProfileRequest,
    db: Annotated[Session, Depends(get_db)],
) -> PlayerProfileResponse:
    updates = request.model_dump(exclude_unset=True)
    if set(updates) == {"favorite"}:
        if not settings.legacy_player_profile_favorite_writes_enabled:
            _raise_legacy_favorite_writes_disabled()
    elif not settings.legacy_player_profile_content_writes_enabled:
        _raise_legacy_content_writes_disabled()

    try:
        get_published_profile_service(db, profile_id)
        profile = update_profile_service(
            db,
            profile_id,
            updates=updates,
            expected_version=None,
            actor_user_id=None,
            allow_external_avatar_url=True,
        )
        db.commit()
        db.refresh(profile)
        return _profile_response(profile)
    except PlayerProfileNotFound as exc:
        db.rollback()
        raise HTTPException(status_code=404, detail="Player profile not found") from exc
    except (PlayerProfileValidationError, PlayerProfileTransitionError) as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except PlayerProfileVersionConflict as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Player profile changed; retry") from exc
    except RecoverableDatabaseError as exc:
        db.rollback()
        raise _profile_database_unavailable() from exc


@router.delete("/{profile_id}", status_code=204)
def delete_player_profile(
    profile_id: Annotated[str, Path(min_length=1, max_length=36)],
    db: Annotated[Session, Depends(get_db)],
) -> Response:
    _require_legacy_content_writes_enabled()
    try:
        get_published_profile_service(db, profile_id)
        archive_profile_service(
            db,
            profile_id,
            expected_version=None,
            actor_user_id=None,
        )
        db.commit()
    except PlayerProfileNotFound as exc:
        db.rollback()
        raise HTTPException(status_code=404, detail="Player profile not found") from exc
    except PlayerProfileVersionConflict as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Player profile changed; retry") from exc
    except RecoverableDatabaseError as exc:
        db.rollback()
        raise _profile_database_unavailable() from exc
    return Response(status_code=204)


def _profile_database_unavailable() -> HTTPException:
    return HTTPException(status_code=503, detail=PLAYER_PROFILE_DATABASE_UNAVAILABLE)


def _require_legacy_content_writes_enabled() -> None:
    if not settings.legacy_player_profile_content_writes_enabled:
        _raise_legacy_content_writes_disabled()


def _raise_legacy_content_writes_disabled() -> None:
    raise HTTPException(
        status_code=403,
        detail="Legacy player profile content writes are disabled",
    )


def _raise_legacy_favorite_writes_disabled() -> None:
    raise HTTPException(
        status_code=403,
        detail="Legacy player profile favorite writes are disabled",
    )


def _build_ai_player_draft_prompt(request: PlayerProfileAiDraftRequest) -> str:
    existing_names = "、".join(request.existing_names[:40]) or "无"
    if request.mode == "name":
        return (
            "为狼人杀竞技场生成一个中文虚拟玩家昵称。"
            "要求：2 到 6 个汉字，围绕夜晚、狼影、警徽、票型、查验或守护等狼人杀主题，"
            "冷峻、有辨识度，不使用编号，不和已有昵称重复。"
            f"已有昵称：{existing_names}。"
            '只输出 JSON：{"display_name":"昵称"}。'
        )

    return (
        "为狼人杀竞技场生成一套中文虚拟玩家创作模板。"
        "只生成一个全新的虚拟玩家，不要为已有昵称逐个生成模板。"
        "要求角色鲜明但适合狼人杀推理发言，字段短而具体。"
        f"已有昵称：{existing_names}。"
        "personality_id 只能是 balanced、aggressive、cautious、deceptive、analytical 之一。"
        "strategy_profile 只能是 balanced、logic_leader、shadow_wolf、social_reader、"
        "pressure_attacker、cautious_observer 之一。"
        "risk_tolerance、bluffing_tendency、trust_tendency、leadership_tendency、"
        "talkativeness 都是 1 到 5 的整数。"
        "catchphrases 最多 3 条，tags 最多 4 个，example_messages 最多 2 条。"
        "只输出 JSON，包含 display_name、personality_id、personality_text、"
        "short_description、background_story、speaking_style、catchphrases、"
        "strategy_profile、risk_tolerance、bluffing_tendency、trust_tendency、"
        "leadership_tendency、talkativeness、example_messages、tags。"
    )


def _parse_ai_player_draft_payload(raw_response: str) -> dict:
    parsed = _parse_ai_json_value(raw_response)
    known_fields = set(PlayerProfileAiDraftResponse.model_fields)
    payload = _extract_ai_player_draft_payload(parsed, known_fields)
    if payload is None:
        raise ValueError("AI player draft JSON did not contain a draft object.")
    return payload


def _parse_ai_json_value(raw_response: str) -> object:
    content = raw_response.strip()
    if content.startswith("```"):
        content = content.strip("`")
        if content.startswith("json"):
            content = content[4:]
        content = content.strip()

    decoder = json.JSONDecoder()
    try:
        parsed, _index = decoder.raw_decode(content)
    except json.JSONDecodeError as exc:
        raise ValueError("Model response was not valid JSON.") from exc
    return parsed


def _extract_ai_player_draft_payload(value: object, known_fields: set[str]) -> dict | None:
    if isinstance(value, dict):
        if any(field in value for field in known_fields):
            return value

        for nested_value in value.values():
            nested_payload = _extract_ai_player_draft_payload(nested_value, known_fields)
            if nested_payload is not None:
                return nested_payload

    if isinstance(value, list):
        for item in value:
            nested_payload = _extract_ai_player_draft_payload(item, known_fields)
            if nested_payload is not None:
                return nested_payload

    return None


def _next_available_generated_name(base_name: str, existing_names: list[str]) -> str:
    trimmed_base_name = base_name.strip() or "新玩家"
    used_names = {_normalize_generated_name(name) for name in existing_names}
    normalized_base_name = _normalize_generated_name(trimmed_base_name)
    if normalized_base_name not in used_names:
        return trimmed_base_name

    suffix = 2
    while _normalize_generated_name(f"{trimmed_base_name} {suffix}") in used_names:
        suffix += 1
    return f"{trimmed_base_name} {suffix}"


def _normalize_generated_name(value: str) -> str:
    return value.strip().replace("\u3000", " ").replace("  ", " ").lower()
