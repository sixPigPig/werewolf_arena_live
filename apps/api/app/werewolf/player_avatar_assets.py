from __future__ import annotations

import base64
import binascii
import hashlib
import uuid
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.player_avatar_asset import PlayerAvatarAsset


MAX_AVATAR_IMAGE_BYTES = 2 * 1024 * 1024
AVATAR_IMAGE_TYPES = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/webp": ".webp",
}

SYSTEM_AVATAR_ASSET_IDS = {
    "gothic-male-1": "system-gothic-male-1",
    "gothic-male-2": "system-gothic-male-2",
    "gothic-female-1": "system-gothic-female-1",
    "gothic-female-2": "system-gothic-female-2",
}
LEGACY_SYSTEM_AVATAR_URLS = {
    f"/player-avatars/{appearance_id}.png": asset_id
    for appearance_id, asset_id in SYSTEM_AVATAR_ASSET_IDS.items()
}


@dataclass(frozen=True)
class FilePlayerAvatarAsset:
    filename: str
    path: Path
    content_type: str


@dataclass(frozen=True)
class ResolvedAvatarReference:
    id: str | None
    url: str
    mime: str


def avatar_asset_url(asset_id: str) -> str:
    return f"{settings.api_v1_prefix}/player-profiles/avatar-assets/{asset_id}"


def normalize_avatar_content_type(content_type: str) -> str:
    normalized_type = content_type.lower().strip()
    if normalized_type == "image/jpg":
        normalized_type = "image/jpeg"
    if normalized_type not in AVATAR_IMAGE_TYPES:
        raise ValueError("Unsupported avatar image type")
    return normalized_type


def decode_uploaded_avatar(*, content_type: str, data_base64: str) -> tuple[str, bytes]:
    normalized_type = normalize_avatar_content_type(content_type)
    try:
        image_bytes = base64.b64decode(data_base64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("Invalid avatar image data") from exc

    if len(image_bytes) > MAX_AVATAR_IMAGE_BYTES:
        raise ValueError("Avatar image must be 2MB or smaller")

    return normalized_type, image_bytes


def create_avatar_asset(
    db: Session,
    *,
    content_type: str,
    data: bytes,
    source: str,
    asset_id: str | None = None,
) -> PlayerAvatarAsset:
    normalized_type = normalize_avatar_content_type(content_type)
    sha256 = hashlib.sha256(data).hexdigest()
    existing = (
        db.query(PlayerAvatarAsset)
        .filter(
            PlayerAvatarAsset.sha256 == sha256,
            PlayerAvatarAsset.content_type == normalized_type,
            PlayerAvatarAsset.source == source,
        )
        .first()
    )
    if existing is not None:
        return existing

    asset = PlayerAvatarAsset(
        id=asset_id or f"{source}-{uuid.uuid4().hex}",
        source=source,
        content_type=normalized_type,
        data=data,
        sha256=sha256,
        size_bytes=len(data),
    )
    db.add(asset)
    return asset


def save_uploaded_avatar_asset(
    db: Session,
    *,
    content_type: str,
    data_base64: str,
) -> PlayerAvatarAsset:
    normalized_type, image_bytes = decode_uploaded_avatar(
        content_type=content_type,
        data_base64=data_base64,
    )
    return create_avatar_asset(
        db,
        content_type=normalized_type,
        data=image_bytes,
        source="uploaded",
    )


def system_avatar_asset_id_for_appearance(appearance_id: str | None) -> str | None:
    if not appearance_id:
        return None
    return SYSTEM_AVATAR_ASSET_IDS.get(appearance_id.strip())


def system_avatar_asset_id_for_legacy_url(avatar_image_url: str | None) -> str | None:
    if not avatar_image_url:
        return None
    return LEGACY_SYSTEM_AVATAR_URLS.get(avatar_image_url.strip())


def legacy_avatar_file_path(logs_dir: str | Path, avatar_image_url: str | None) -> Path | None:
    if not avatar_image_url:
        return None
    avatar_image_url = avatar_image_url.strip()
    legacy_prefix = f"{settings.api_v1_prefix}/player-profiles/avatar/"
    if not avatar_image_url.startswith(legacy_prefix):
        return None
    filename = avatar_image_url.removeprefix(legacy_prefix)
    if Path(filename).name != filename:
        return None
    return Path(logs_dir) / "player_profile_assets" / filename


def resolve_profile_avatar_reference(
    db: Session,
    *,
    avatar_asset_id: str | None,
    appearance_id: str | None,
    avatar_image_url: str | None,
    avatar_image_mime: str | None,
    logs_dir: str | Path,
) -> ResolvedAvatarReference:
    trimmed_asset_id = avatar_asset_id.strip() if isinstance(avatar_asset_id, str) else ""
    if trimmed_asset_id:
        asset = db.get(PlayerAvatarAsset, trimmed_asset_id)
        if asset is None:
            raise ValueError("Avatar asset not found")
        return ResolvedAvatarReference(
            id=asset.id,
            url=avatar_asset_url(asset.id),
            mime=asset.content_type,
        )

    system_asset_id = system_avatar_asset_id_for_appearance(
        appearance_id
    ) or system_avatar_asset_id_for_legacy_url(avatar_image_url)
    if system_asset_id is not None:
        return ResolvedAvatarReference(
            id=system_asset_id,
            url=avatar_asset_url(system_asset_id),
            mime="image/png",
        )

    legacy_path = legacy_avatar_file_path(logs_dir, avatar_image_url)
    if legacy_path is not None:
        if not legacy_path.is_file():
            raise ValueError("Legacy avatar image file not found")
        asset = create_avatar_asset(
            db,
            source="migrated",
            content_type=avatar_image_mime or "",
            data=legacy_path.read_bytes(),
        )
        return ResolvedAvatarReference(
            id=asset.id,
            url=avatar_asset_url(asset.id),
            mime=asset.content_type,
        )

    return ResolvedAvatarReference(
        id=None,
        url=avatar_image_url or "",
        mime=avatar_image_mime or "",
    )


class PlayerAvatarAssetStore:
    def __init__(self, root: Path) -> None:
        self.root = root

    def save(self, *, content_type: str, data_base64: str) -> FilePlayerAvatarAsset:
        normalized_type, image_bytes = decode_uploaded_avatar(
            content_type=content_type,
            data_base64=data_base64,
        )
        extension = AVATAR_IMAGE_TYPES[normalized_type]

        self.root.mkdir(parents=True, exist_ok=True)
        filename = f"{uuid.uuid4().hex}{extension}"
        path = self.root / filename
        path.write_bytes(image_bytes)
        return FilePlayerAvatarAsset(
            filename=filename,
            path=path,
            content_type=normalized_type,
        )

    def path_for(self, filename: str) -> Path | None:
        if Path(filename).name != filename:
            return None
        path = self.root / filename
        if not path.is_file():
            return None
        return path

    def content_type_for(self, filename: str) -> str:
        suffix = Path(filename).suffix.lower()
        if suffix == ".png":
            return "image/png"
        if suffix in {".jpg", ".jpeg"}:
            return "image/jpeg"
        if suffix == ".webp":
            return "image/webp"
        return "application/octet-stream"


def player_avatar_asset_store_for_logs_dir(logs_dir: str | Path) -> PlayerAvatarAssetStore:
    return PlayerAvatarAssetStore(Path(logs_dir) / "player_profile_assets")
