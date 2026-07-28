from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.models.virtual_player_profile import VirtualPlayerProfile
from app.werewolf.player_avatar_assets import (
    avatar_asset_url,
    avatar_content_type_for_filename,
    create_avatar_asset,
    legacy_avatar_file_path,
)


class PlayerAvatarAssetMigrationError(RuntimeError):
    pass


@dataclass(frozen=True)
class PlayerAvatarAssetMigrationResult:
    scanned_count: int
    imported_count: int
    reused_count: int
    missing_count: int
    updated_count: int


def migrate_player_avatar_assets(
    *,
    logs_dir: Path,
    db: Session,
) -> PlayerAvatarAssetMigrationResult:
    scanned_count = 0
    imported_count = 0
    reused_count = 0
    missing_count = 0
    updated_count = 0
    try:
        profiles = (
            db.query(VirtualPlayerProfile)
            .filter(VirtualPlayerProfile.avatar_asset_id.is_(None))
            .all()
        )
        for profile in profiles:
            scanned_count += 1
            legacy_path = legacy_avatar_file_path(logs_dir, profile.avatar_image_url)
            if legacy_path is None:
                continue
            if not legacy_path.is_file():
                missing_count += 1
                continue

            content_type = profile.avatar_image_mime or avatar_content_type_for_filename(
                legacy_path
            )
            asset = create_avatar_asset(
                db,
                source="migrated",
                content_type=content_type,
                data=legacy_path.read_bytes(),
            )
            is_new_asset = asset in db.new
            db.flush()
            if is_new_asset:
                imported_count += 1
            else:
                reused_count += 1

            profile.avatar_asset_id = asset.id
            profile.avatar_image_url = avatar_asset_url(asset.id)
            profile.avatar_image_mime = asset.content_type
            updated_count += 1
        db.commit()
    except (OSError, SQLAlchemyError, ValueError) as exc:
        db.rollback()
        raise PlayerAvatarAssetMigrationError("迁移玩家头像资产失败") from exc

    return PlayerAvatarAssetMigrationResult(
        scanned_count=scanned_count,
        imported_count=imported_count,
        reused_count=reused_count,
        missing_count=missing_count,
        updated_count=updated_count,
    )
