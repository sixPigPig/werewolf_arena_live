from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import func
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.virtual_player_profile import VirtualPlayerProfile
from app.werewolf.player_avatar_assets import resolve_profile_avatar_reference
from app.werewolf.player_profile_store import PlayerProfileFileStore, StoredPlayerProfile


class PlayerProfileImportError(RuntimeError):
    pass


@dataclass(frozen=True)
class PlayerProfileImportResult:
    read_count: int
    imported_count: int
    skipped_count: int


def import_player_profiles(source: Path, db: Session) -> PlayerProfileImportResult:
    try:
        if not source.is_file():
            raise PlayerProfileImportError("无法读取玩家档案文件")
        profiles = PlayerProfileFileStore(source).list_profiles()
    except PlayerProfileImportError:
        raise
    except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
        raise PlayerProfileImportError("无法读取玩家档案文件") from exc

    if not profiles:
        raise PlayerProfileImportError("没有可导入的玩家档案")

    imported_count = 0
    skipped_count = 0
    seen_ids: set[str] = set()
    try:
        next_display_order = _next_profile_display_order(db)
        for profile in profiles:
            if profile.id in seen_ids or db.get(VirtualPlayerProfile, profile.id) is not None:
                skipped_count += 1
                continue
            seen_ids.add(profile.id)
            db.add(_database_profile(profile, db, display_order=next_display_order))
            next_display_order += 1
            imported_count += 1
        db.commit()
    except (SQLAlchemyError, ValueError) as exc:
        db.rollback()
        raise PlayerProfileImportError("导入玩家档案失败") from exc

    return PlayerProfileImportResult(
        read_count=len(profiles),
        imported_count=imported_count,
        skipped_count=skipped_count,
    )


def _database_profile(
    profile: StoredPlayerProfile,
    db: Session,
    *,
    display_order: int,
) -> VirtualPlayerProfile:
    avatar = resolve_profile_avatar_reference(
        db,
        avatar_asset_id=profile.avatar_asset_id,
        appearance_id=profile.appearance_id,
        avatar_image_url=profile.avatar_image_url,
        avatar_image_mime=profile.avatar_image_mime,
        logs_dir=settings.werewolf_logs_dir,
    )
    return VirtualPlayerProfile(
        id=profile.id,
        owner_user_id=profile.owner_user_id,
        display_name=profile.display_name,
        model=profile.model,
        personality_id=profile.personality_id,
        personality_text=profile.personality_text,
        appearance_id=profile.appearance_id,
        avatar_prompt=profile.avatar_prompt,
        avatar_image_url=avatar.url,
        avatar_image_path="",
        avatar_image_mime=avatar.mime,
        avatar_asset_id=avatar.id,
        short_description=profile.short_description,
        background_story=profile.background_story,
        speaking_style=profile.speaking_style,
        catchphrases=profile.catchphrases,
        strategy_profile=profile.strategy_profile,
        risk_tolerance=profile.risk_tolerance,
        bluffing_tendency=profile.bluffing_tendency,
        trust_tendency=profile.trust_tendency,
        leadership_tendency=profile.leadership_tendency,
        talkativeness=profile.talkativeness,
        example_messages=profile.example_messages,
        display_order=display_order,
        favorite=profile.favorite,
        featured=profile.favorite,
        tags=profile.tags,
        status="published",
        version=1,
        published_at=profile.created_at,
        published_by_user_id=None,
        updated_by_user_id=None,
        deleted_at=None,
        created_at=profile.created_at,
        updated_at=profile.updated_at,
    )


def _next_profile_display_order(db: Session) -> int:
    current_max = db.query(func.max(VirtualPlayerProfile.display_order)).scalar()
    return int(current_max or 0) + 1
