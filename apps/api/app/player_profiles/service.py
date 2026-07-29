from __future__ import annotations

import math
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal, Mapping

from sqlalchemy import func, or_, text
from sqlalchemy.orm import Query, Session
from sqlalchemy.orm.exc import StaleDataError

from app.models.model_configuration import ModelConfigurationRecord
from app.models.virtual_player_profile import VirtualPlayerProfile
from app.player_profiles.errors import (
    PlayerProfileNotFound,
    PlayerProfileTransitionError,
    PlayerProfileValidationError,
    PlayerProfileVersionConflict,
)
from app.werewolf.player_avatar_assets import resolve_profile_avatar_reference
from app.werewolf.player_presets import (
    default_personality_text,
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
PlayerProfileMoveDirection = Literal["up", "down"]

_EDITABLE_PROFILE_FIELDS = frozenset(
    {
        "display_name",
        "model_provider",
        "model",
        "personality_id",
        "personality_text",
        "appearance_id",
        "avatar_asset_id",
        "avatar_image_url",
        "avatar_image_mime",
        "short_description",
        "background_story",
        "speaking_style",
        "gender",
        "tts_speaker",
        "tts_dialect",
        "base_delivery_mood",
        "base_delivery_intensity",
        "base_delivery_pace",
        "base_delivery_instruction",
        "voice_enabled",
        "strategy_profile",
        "risk_tolerance",
        "bluffing_tendency",
        "trust_tendency",
        "leadership_tendency",
        "talkativeness",
        "example_messages",
        "featured",
        "tags",
    }
)


@dataclass(frozen=True)
class PlayerProfilePage:
    items: list[VirtualPlayerProfile]
    page: int
    page_size: int
    total: int
    pages: int


def list_admin_player_profiles(
    db: Session,
    *,
    page: int,
    page_size: int,
    query_text: str | None = None,
    status: PlayerProfileStatus | None = None,
    model: str | None = None,
    personality_id: str | None = None,
    sort: PlayerProfileSort = "display_order",
) -> PlayerProfilePage:
    query = db.query(VirtualPlayerProfile)
    if query_text and query_text.strip():
        search = f"%{_escape_like(query_text.strip().lower())}%"
        query = query.filter(
            or_(
                func.lower(VirtualPlayerProfile.display_name).like(search, escape="\\"),
                func.lower(VirtualPlayerProfile.short_description).like(search, escape="\\"),
            )
        )
    if status is not None:
        query = query.filter(VirtualPlayerProfile.status == status)
    if model and model.strip():
        query = query.filter(VirtualPlayerProfile.model == model.strip())
    if personality_id and personality_id.strip():
        query = query.filter(VirtualPlayerProfile.personality_id == personality_id.strip())

    total = query.count()
    ordered = _apply_sort(query, sort)
    items = ordered.offset((page - 1) * page_size).limit(page_size).all()
    return PlayerProfilePage(
        items=list(items),
        page=page,
        page_size=page_size,
        total=total,
        pages=math.ceil(total / page_size) if total else 0,
    )


def list_published_player_profiles(db: Session) -> list[VirtualPlayerProfile]:
    return list(
        db.query(VirtualPlayerProfile)
        .filter(
            VirtualPlayerProfile.status == "published",
            VirtualPlayerProfile.deleted_at.is_(None),
        )
        .order_by(VirtualPlayerProfile.display_order.asc(), VirtualPlayerProfile.id.asc())
        .all()
    )


def list_public_player_profiles(
    db: Session,
    *,
    page: int,
    page_size: int,
) -> PlayerProfilePage:
    query = db.query(VirtualPlayerProfile).filter(
        VirtualPlayerProfile.status == "published",
        VirtualPlayerProfile.deleted_at.is_(None),
    )
    total = query.count()
    items = (
        query.order_by(
            VirtualPlayerProfile.display_order.asc(),
            VirtualPlayerProfile.id.asc(),
        )
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return PlayerProfilePage(
        items=list(items),
        page=page,
        page_size=page_size,
        total=total,
        pages=math.ceil(total / page_size) if total else 0,
    )


def get_player_profile(db: Session, profile_id: str) -> VirtualPlayerProfile:
    profile = db.get(VirtualPlayerProfile, profile_id)
    if profile is None:
        raise PlayerProfileNotFound(profile_id)
    return profile


def get_published_player_profile(db: Session, profile_id: str) -> VirtualPlayerProfile:
    profile = get_player_profile(db, profile_id)
    if profile.status != "published" or profile.deleted_at is not None:
        raise PlayerProfileNotFound(profile_id)
    return profile


def current_player_profile_version(db: Session, profile_id: str) -> int | None:
    return db.query(VirtualPlayerProfile.version).filter(
        VirtualPlayerProfile.id == profile_id
    ).scalar()


def create_player_profile(
    db: Session,
    *,
    values: Mapping[str, object],
    initial_status: Literal["draft", "published"],
    actor_user_id: int | None,
    allow_external_avatar_url: bool,
) -> VirtualPlayerProfile:
    data = dict(values)
    unknown_fields = set(data) - _EDITABLE_PROFILE_FIELDS
    if unknown_fields:
        raise PlayerProfileValidationError(
            f"Unsupported player profile fields: {', '.join(sorted(unknown_fields))}"
        )
    personality_id = str(data.get("personality_id") or "balanced")
    appearance_id = str(data.get("appearance_id") or "default")
    _validate_presets(personality_id, appearance_id, str(data.get("strategy_profile") or "balanced"))
    _ensure_model_configuration(
        db,
        provider=str(data.get("model_provider") or ""),
        model=str(data.get("model") or ""),
    )

    avatar_asset_id = _optional_string(data.get("avatar_asset_id"))
    avatar_image_url = str(data.get("avatar_image_url") or "")
    if (
        avatar_image_url
        and not allow_external_avatar_url
        and not _optional_string(avatar_asset_id)
    ):
        raise PlayerProfileValidationError("External avatar URLs are not allowed")
    try:
        resolved_avatar = resolve_profile_avatar_reference(
            db,
            avatar_asset_id=avatar_asset_id,
            appearance_id=appearance_id,
            avatar_image_url=avatar_image_url,
            avatar_image_mime=str(data.get("avatar_image_mime") or ""),
        )
    except ValueError as exc:
        raise PlayerProfileValidationError(str(exc)) from exc

    now = datetime.now(UTC)
    featured = bool(data.get("featured", False))
    if initial_status != "published" and featured:
        raise PlayerProfileValidationError("Draft player profiles cannot be featured")
    display_order: int | None = None
    if initial_status == "published":
        _lock_display_order_scope(db)
        display_order = _next_profile_display_order(db)

    profile = VirtualPlayerProfile(
        id=str(uuid.uuid4()),
        display_name=str(data["display_name"]),
        model_provider=str(data["model_provider"]),
        model=str(data["model"]),
        personality_id=personality_id,
        personality_text=str(data.get("personality_text") or "")
        or default_personality_text(personality_id),
        appearance_id=appearance_id,
        avatar_image_url=resolved_avatar.url,
        avatar_image_mime=resolved_avatar.mime,
        avatar_asset_id=resolved_avatar.id,
        short_description=str(data.get("short_description") or ""),
        background_story=str(data.get("background_story") or ""),
        speaking_style=str(data.get("speaking_style") or ""),
        gender=str(data.get("gender") or "female"),
        tts_speaker=str(data.get("tts_speaker") or ""),
        tts_dialect=str(data.get("tts_dialect") or ""),
        base_delivery_mood=str(data.get("base_delivery_mood") or "neutral"),
        base_delivery_intensity=str(data.get("base_delivery_intensity") or "medium"),
        base_delivery_pace=str(data.get("base_delivery_pace") or "natural"),
        base_delivery_instruction=str(data.get("base_delivery_instruction") or ""),
        voice_enabled=bool(data.get("voice_enabled", True)),
        voice_config_version=1,
        strategy_profile=str(data.get("strategy_profile") or "balanced"),
        risk_tolerance=int(data.get("risk_tolerance") or 3),
        bluffing_tendency=int(data.get("bluffing_tendency") or 3),
        trust_tendency=int(data.get("trust_tendency") or 3),
        leadership_tendency=int(data.get("leadership_tendency") or 3),
        talkativeness=int(data.get("talkativeness") or 3),
        example_messages=list(data.get("example_messages") or []),
        display_order=display_order,
        featured=featured,
        tags=list(data.get("tags") or []),
        status=initial_status,
        published_at=now if initial_status == "published" else None,
        published_by_user_id=actor_user_id if initial_status == "published" else None,
        updated_by_user_id=actor_user_id,
        deleted_at=None,
        created_at=now,
        updated_at=now,
    )
    db.add(profile)
    _flush_with_conflict(db, profile)
    return profile


def update_player_profile(
    db: Session,
    profile_id: str,
    *,
    updates: Mapping[str, object],
    expected_version: int | None,
    actor_user_id: int | None,
    allow_external_avatar_url: bool,
) -> VirtualPlayerProfile:
    profile = get_player_profile(db, profile_id)
    if profile.status == "archived":
        raise PlayerProfileTransitionError(
            profile_id,
            current_status=profile.status,
            target_status=profile.status,
        )
    _ensure_version(profile, expected_version)
    data = dict(updates)
    unknown_fields = set(data) - _EDITABLE_PROFILE_FIELDS
    if unknown_fields:
        raise PlayerProfileValidationError(
            f"Unsupported player profile fields: {', '.join(sorted(unknown_fields))}"
        )

    personality_changed = (
        "personality_id" in data and data["personality_id"] != profile.personality_id
    )
    personality_id = str(data.get("personality_id", profile.personality_id))
    appearance_id = str(data.get("appearance_id", profile.appearance_id))
    strategy_profile = str(data.get("strategy_profile", profile.strategy_profile))
    _validate_presets(personality_id, appearance_id, strategy_profile)
    _ensure_model_configuration(
        db,
        provider=str(data.get("model_provider", profile.model_provider)),
        model=str(data.get("model", profile.model)),
    )
    voice_fields = {
        "gender",
        "tts_speaker",
        "tts_dialect",
        "base_delivery_mood",
        "base_delivery_intensity",
        "base_delivery_pace",
        "base_delivery_instruction",
        "voice_enabled",
    }
    if "tts_speaker" in data:
        data["tts_speaker"] = str(data["tts_speaker"] or "")
    if "tts_dialect" in data:
        data["tts_dialect"] = str(data["tts_dialect"] or "")
    if "base_delivery_mood" in data:
        data["base_delivery_mood"] = str(data["base_delivery_mood"] or "neutral")
    if "base_delivery_intensity" in data:
        data["base_delivery_intensity"] = str(data["base_delivery_intensity"] or "medium")
    if "base_delivery_pace" in data:
        data["base_delivery_pace"] = str(data["base_delivery_pace"] or "natural")
    if "base_delivery_instruction" in data:
        data["base_delivery_instruction"] = str(data["base_delivery_instruction"] or "")
    voice_changed = any(
        field_name in data and data[field_name] != getattr(profile, field_name)
        for field_name in voice_fields
    )

    if "avatar_image_url" in data and data["avatar_image_url"] and not allow_external_avatar_url:
        raise PlayerProfileValidationError("External avatar URLs are not allowed")
    _apply_avatar_update(
        db,
        profile,
        data,
        appearance_id=appearance_id,
        allow_external_avatar_url=allow_external_avatar_url,
    )

    if "featured" in data and bool(data["featured"]) and profile.status != "published":
        raise PlayerProfileValidationError("Only published player profiles can be featured")

    for field_name, value in data.items():
        setattr(profile, field_name, value)

    if voice_changed:
        profile.voice_config_version += 1

    if personality_changed and "personality_text" not in data:
        profile.personality_text = default_personality_text(personality_id)
    elif "personality_text" in data and not profile.personality_text:
        profile.personality_text = default_personality_text(profile.personality_id)

    profile.updated_by_user_id = actor_user_id
    profile.updated_at = datetime.now(UTC)
    _flush_with_conflict(db, profile)
    return profile


def _ensure_model_configuration(
    db: Session,
    *,
    provider: str,
    model: str,
) -> None:
    configuration = db.get(ModelConfigurationRecord, (provider, model))
    if (
        configuration is None
        or not configuration.available
        or not configuration.enabled
    ):
        raise PlayerProfileValidationError(
            "The selected model is not configured for this deployment."
        )


def publish_player_profile(
    db: Session,
    profile_id: str,
    *,
    expected_version: int | None,
    actor_user_id: int | None,
) -> VirtualPlayerProfile:
    profile = get_player_profile(db, profile_id)
    _ensure_version(profile, expected_version)
    if profile.status != "draft":
        raise PlayerProfileTransitionError(
            profile_id,
            current_status=profile.status,
            target_status="published",
        )
    _lock_display_order_scope(db)
    now = datetime.now(UTC)
    profile.status = "published"
    profile.display_order = _next_profile_display_order(db)
    profile.published_at = now
    profile.published_by_user_id = actor_user_id
    profile.updated_by_user_id = actor_user_id
    profile.updated_at = now
    _flush_with_conflict(db, profile)
    return profile


def archive_player_profile(
    db: Session,
    profile_id: str,
    *,
    expected_version: int | None,
    actor_user_id: int | None,
) -> VirtualPlayerProfile:
    profile = get_player_profile(db, profile_id)
    _ensure_version(profile, expected_version)
    if profile.status != "published":
        raise PlayerProfileTransitionError(
            profile_id,
            current_status=profile.status,
            target_status="archived",
        )
    _lock_display_order_scope(db)
    now = datetime.now(UTC)
    profile.status = "archived"
    profile.display_order = None
    profile.featured = False
    profile.deleted_at = now
    profile.updated_by_user_id = actor_user_id
    profile.updated_at = now
    _flush_with_conflict(db, profile)
    _compact_published_display_order(db, actor_user_id=actor_user_id)
    db.refresh(profile)
    return profile


def restore_player_profile(
    db: Session,
    profile_id: str,
    *,
    expected_version: int | None,
    actor_user_id: int | None,
) -> VirtualPlayerProfile:
    profile = get_player_profile(db, profile_id)
    _ensure_version(profile, expected_version)
    if profile.status != "archived":
        raise PlayerProfileTransitionError(
            profile_id,
            current_status=profile.status,
            target_status="published",
        )
    _lock_display_order_scope(db)
    now = datetime.now(UTC)
    profile.status = "published"
    profile.display_order = _next_profile_display_order(db)
    profile.featured = False
    profile.deleted_at = None
    profile.published_at = now
    profile.published_by_user_id = actor_user_id
    profile.updated_by_user_id = actor_user_id
    profile.updated_at = now
    _flush_with_conflict(db, profile)
    return profile


def move_published_player_profile(
    db: Session,
    profile_id: str,
    *,
    direction: PlayerProfileMoveDirection,
    expected_version: int | None,
    actor_user_id: int | None,
) -> VirtualPlayerProfile:
    _lock_display_order_scope(db)
    profile = get_player_profile(db, profile_id)
    _ensure_version(profile, expected_version)
    if profile.status != "published":
        raise PlayerProfileTransitionError(
            profile_id,
            current_status=profile.status,
            target_status="published",
        )
    profiles = _published_profiles_for_update(db)
    current_index = next(
        (index for index, candidate in enumerate(profiles) if candidate.id == profile_id),
        None,
    )
    if current_index is None:
        raise PlayerProfileNotFound(profile_id)
    target_index = current_index + (-1 if direction == "up" else 1)
    if target_index < 0 or target_index >= len(profiles):
        return profile

    ordered_ids = [candidate.id for candidate in profiles]
    ordered_ids[current_index], ordered_ids[target_index] = (
        ordered_ids[target_index],
        ordered_ids[current_index],
    )
    _rewrite_published_display_order(
        db,
        ordered_ids,
        actor_user_id=actor_user_id,
    )
    return get_player_profile(db, profile_id)


def _apply_avatar_update(
    db: Session,
    profile: VirtualPlayerProfile,
    updates: dict[str, object],
    *,
    appearance_id: str,
    allow_external_avatar_url: bool,
) -> None:
    avatar_update_fields = {
        "avatar_asset_id",
        "avatar_image_url",
        "avatar_image_mime",
        "appearance_id",
    }
    if not any(field_name in updates for field_name in avatar_update_fields):
        return

    explicit_asset_clear = (
        "avatar_asset_id" in updates and updates["avatar_asset_id"] is None
    )
    explicit_avatar_url = str(updates.get("avatar_image_url") or "")
    if explicit_asset_clear and not explicit_avatar_url:
        updates["avatar_asset_id"] = None
        updates["avatar_image_url"] = ""
        updates["avatar_image_mime"] = ""
        return

    avatar_asset_id = updates.get(
        "avatar_asset_id",
        None if "avatar_image_url" in updates else profile.avatar_asset_id,
    )
    avatar_image_url = str(updates.get("avatar_image_url", profile.avatar_image_url) or "")
    if (
        avatar_image_url
        and not allow_external_avatar_url
        and not _optional_string(avatar_asset_id)
    ):
        raise PlayerProfileValidationError("External avatar URLs are not allowed")
    try:
        resolved_avatar = resolve_profile_avatar_reference(
            db,
            avatar_asset_id=_optional_string(avatar_asset_id),
            appearance_id=appearance_id,
            avatar_image_url=avatar_image_url,
            avatar_image_mime=str(
                updates.get("avatar_image_mime", profile.avatar_image_mime) or ""
            ),
        )
    except ValueError as exc:
        raise PlayerProfileValidationError(str(exc)) from exc
    updates["avatar_asset_id"] = resolved_avatar.id
    updates["avatar_image_url"] = resolved_avatar.url
    updates["avatar_image_mime"] = resolved_avatar.mime


def _validate_presets(
    personality_id: str,
    appearance_id: str,
    strategy_profile: str,
) -> None:
    if not is_valid_personality(personality_id):
        raise PlayerProfileValidationError(f"Unknown personality_id: {personality_id}")
    if not is_valid_appearance(appearance_id):
        raise PlayerProfileValidationError(f"Unknown appearance_id: {appearance_id}")
    if not is_valid_strategy(strategy_profile):
        raise PlayerProfileValidationError(f"Unknown strategy_profile: {strategy_profile}")


def _ensure_version(
    profile: VirtualPlayerProfile,
    expected_version: int | None,
) -> None:
    if expected_version is not None and profile.version != expected_version:
        raise PlayerProfileVersionConflict(
            profile.id,
            current_version=profile.version,
        )


def _flush_with_conflict(db: Session, profile: VirtualPlayerProfile) -> None:
    profile_id = profile.id
    try:
        db.flush()
    except StaleDataError as exc:
        raise PlayerProfileVersionConflict(
            profile_id,
            current_version=None,
        ) from exc


def _next_profile_display_order(db: Session) -> int:
    current_max = (
        db.query(func.max(VirtualPlayerProfile.display_order))
        .filter(VirtualPlayerProfile.status == "published")
        .scalar()
    )
    return int(current_max or 0) + 1


def _compact_published_display_order(
    db: Session,
    *,
    actor_user_id: int | None,
) -> None:
    ordered_ids = [profile.id for profile in _published_profiles_for_update(db)]
    _rewrite_published_display_order(
        db,
        ordered_ids,
        actor_user_id=actor_user_id,
    )


def _published_profiles_for_update(db: Session) -> list[VirtualPlayerProfile]:
    query = (
        db.query(VirtualPlayerProfile)
        .filter(VirtualPlayerProfile.status == "published")
        .order_by(VirtualPlayerProfile.display_order.asc(), VirtualPlayerProfile.id.asc())
    )
    if db.get_bind().dialect.name != "sqlite":
        query = query.with_for_update()
    return list(query.all())


def _rewrite_published_display_order(
    db: Session,
    ordered_ids: list[str],
    *,
    actor_user_id: int | None,
) -> None:
    if not ordered_ids:
        return
    current_max = (
        db.query(func.max(VirtualPlayerProfile.display_order))
        .filter(VirtualPlayerProfile.status == "published")
        .scalar()
    )
    temporary_offset = int(current_max or 0) + len(ordered_ids) + 1
    db.query(VirtualPlayerProfile).filter(
        VirtualPlayerProfile.status == "published"
    ).update(
        {
            VirtualPlayerProfile.display_order:
                VirtualPlayerProfile.display_order + temporary_offset
        },
        synchronize_session=False,
    )
    db.expire_all()
    now = datetime.now(UTC)
    profiles_by_id = {
        profile.id: profile
        for profile in db.query(VirtualPlayerProfile)
        .filter(VirtualPlayerProfile.id.in_(ordered_ids))
        .all()
    }
    if set(profiles_by_id) != set(ordered_ids):
        raise PlayerProfileValidationError(
            "Published player profile order changed while reordering."
        )
    for display_order, profile_id in enumerate(ordered_ids, start=1):
        profile = profiles_by_id[profile_id]
        if profile.status != "published":
            raise PlayerProfileValidationError(
                "Only published player profiles can be reordered."
            )
        profile.display_order = display_order
        profile.updated_by_user_id = actor_user_id
        profile.updated_at = now
    try:
        db.flush()
    except StaleDataError as exc:
        raise PlayerProfileVersionConflict(
            ordered_ids[0],
            current_version=current_player_profile_version(db, ordered_ids[0]),
        ) from exc


def _lock_display_order_scope(db: Session) -> None:
    if db.get_bind().dialect.name == "postgresql":
        db.execute(
            text(
                "LOCK TABLE virtual_player_profiles "
                "IN SHARE ROW EXCLUSIVE MODE"
            )
        )


def _apply_sort(query: Query, sort: PlayerProfileSort) -> Query:
    descending = sort.startswith("-")
    field_name = sort.removeprefix("-")
    column = {
        "display_order": VirtualPlayerProfile.display_order,
        "updated_at": VirtualPlayerProfile.updated_at,
        "display_name": VirtualPlayerProfile.display_name,
        "created_at": VirtualPlayerProfile.created_at,
    }[field_name]
    order = column.desc() if descending else column.asc()
    if field_name == "display_order":
        order = order.nullslast()
    return query.order_by(order, VirtualPlayerProfile.id.asc())


def _optional_string(value: object) -> str | None:
    if value is None:
        return None
    cleaned = str(value).strip()
    return cleaned or None


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
