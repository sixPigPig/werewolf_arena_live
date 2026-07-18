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
class ResolvedAvatarReference:
    id: str | None
    url: str
    mime: str


def avatar_asset_url(asset_id: str) -> str:
    return f"{settings.api_v1_prefix}/player-profiles/avatar-assets/{asset_id}"


def avatar_content_type_for_filename(filename_or_path: str | Path) -> str:
    suffix = Path(filename_or_path).suffix.lower()
    if suffix == ".png":
        return "image/png"
    if suffix in {".jpg", ".jpeg"}:
        return "image/jpeg"
    if suffix == ".webp":
        return "image/webp"
    return "application/octet-stream"


def avatar_asset_id_for_url(url: str | None) -> str | None:
    if not url:
        return None
    url = url.strip()
    asset_prefix = f"{settings.api_v1_prefix}/player-profiles/avatar-assets/"
    if not url.startswith(asset_prefix):
        return None
    asset_id = url.removeprefix(asset_prefix)
    if not asset_id or Path(asset_id).name != asset_id:
        return None
    return asset_id


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
        data_base64=base64.b64encode(data).decode("ascii"),
        sha256=sha256,
        size_bytes=len(data),
    )
    db.add(asset)
    return asset


def decode_avatar_asset_data(asset: PlayerAvatarAsset) -> bytes:
    try:
        data = base64.b64decode(asset.data_base64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("Invalid stored avatar image data") from exc
    if len(data) != asset.size_bytes or hashlib.sha256(data).hexdigest() != asset.sha256:
        raise ValueError("Stored avatar image data failed integrity validation")
    return data


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


def legacy_avatar_filename(avatar_image_url: str | None) -> str | None:
    if not avatar_image_url:
        return None
    avatar_image_url = avatar_image_url.strip()
    legacy_prefix = f"{settings.api_v1_prefix}/player-profiles/avatar/"
    if not avatar_image_url.startswith(legacy_prefix):
        return None
    filename = avatar_image_url.removeprefix(legacy_prefix)
    if Path(filename).name != filename:
        return None
    return filename


def legacy_avatar_file_path(logs_dir: str | Path, avatar_image_url: str | None) -> Path | None:
    filename = legacy_avatar_filename(avatar_image_url)
    if filename is None:
        return None
    return Path(logs_dir) / "player_profile_assets" / filename


def resolve_profile_avatar_reference(
    db: Session,
    *,
    avatar_asset_id: str | None,
    appearance_id: str | None,
    avatar_image_url: str | None,
    avatar_image_mime: str | None,
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

    trimmed_url = avatar_image_url.strip() if isinstance(avatar_image_url, str) else ""
    if trimmed_url:
        system_asset_id = system_avatar_asset_id_for_legacy_url(trimmed_url)
        if system_asset_id is not None:
            return ResolvedAvatarReference(
                id=system_asset_id,
                url=avatar_asset_url(system_asset_id),
                mime="image/png",
            )

        url_asset_id = avatar_asset_id_for_url(trimmed_url)
        if url_asset_id is not None:
            asset = db.get(PlayerAvatarAsset, url_asset_id)
            if asset is None:
                raise ValueError("Avatar asset not found")
            return ResolvedAvatarReference(
                id=asset.id,
                url=avatar_asset_url(asset.id),
                mime=asset.content_type,
            )

        if legacy_avatar_filename(trimmed_url) is not None:
            raise ValueError("Legacy file-backed avatar URLs are no longer supported")

        return ResolvedAvatarReference(
            id=None,
            url=trimmed_url,
            mime=avatar_image_mime or "",
        )

    system_asset_id = system_avatar_asset_id_for_appearance(appearance_id)
    if system_asset_id is not None:
        return ResolvedAvatarReference(
            id=system_asset_id,
            url=avatar_asset_url(system_asset_id),
            mime="image/png",
        )

    return ResolvedAvatarReference(
        id=None,
        url="",
        mime=avatar_image_mime or "",
    )
