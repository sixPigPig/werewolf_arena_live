from __future__ import annotations

import base64
import binascii
import uuid
from dataclasses import dataclass
from pathlib import Path


MAX_AVATAR_IMAGE_BYTES = 2 * 1024 * 1024
AVATAR_IMAGE_TYPES = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/webp": ".webp",
}


@dataclass(frozen=True)
class PlayerAvatarAsset:
    filename: str
    path: Path
    content_type: str


class PlayerAvatarAssetStore:
    def __init__(self, root: Path) -> None:
        self.root = root

    def save(self, *, content_type: str, data_base64: str) -> PlayerAvatarAsset:
        normalized_type = content_type.lower().strip()
        extension = AVATAR_IMAGE_TYPES.get(normalized_type)
        if extension is None:
            raise ValueError("Unsupported avatar image type")

        try:
            image_bytes = base64.b64decode(data_base64, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ValueError("Invalid avatar image data") from exc

        if len(image_bytes) > MAX_AVATAR_IMAGE_BYTES:
            raise ValueError("Avatar image must be 2MB or smaller")

        self.root.mkdir(parents=True, exist_ok=True)
        filename = f"{uuid.uuid4().hex}{extension}"
        path = self.root / filename
        path.write_bytes(image_bytes)
        return PlayerAvatarAsset(
            filename=filename,
            path=path,
            content_type="image/jpeg" if normalized_type == "image/jpg" else normalized_type,
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
