from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.models.virtual_player_profile import VirtualPlayerProfile
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
        for profile in profiles:
            if profile.id in seen_ids or db.get(VirtualPlayerProfile, profile.id) is not None:
                skipped_count += 1
                continue
            seen_ids.add(profile.id)
            db.add(_database_profile(profile))
            imported_count += 1
        db.commit()
    except SQLAlchemyError as exc:
        db.rollback()
        raise PlayerProfileImportError("导入玩家档案失败") from exc

    return PlayerProfileImportResult(
        read_count=len(profiles),
        imported_count=imported_count,
        skipped_count=skipped_count,
    )


def _database_profile(profile: StoredPlayerProfile) -> VirtualPlayerProfile:
    return VirtualPlayerProfile(
        id=profile.id,
        owner_user_id=profile.owner_user_id,
        display_name=profile.display_name,
        model=profile.model,
        personality_id=profile.personality_id,
        personality_text=profile.personality_text,
        appearance_id=profile.appearance_id,
        avatar_prompt=profile.avatar_prompt,
        avatar_image_url=profile.avatar_image_url,
        avatar_image_path=profile.avatar_image_path,
        avatar_image_mime=profile.avatar_image_mime,
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
        favorite=profile.favorite,
        tags=profile.tags,
        created_at=profile.created_at,
        updated_at=profile.updated_at,
    )
