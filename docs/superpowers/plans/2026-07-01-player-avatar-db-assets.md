# Player Avatar Database Assets Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Store virtual player avatar image assets in PostgreSQL and serve every desktop, mobile, live, and replay avatar through stable API URLs.

**Architecture:** Add a `player_avatar_assets` table and `avatar_asset_id` on `virtual_player_profiles`. Centralize avatar asset URL generation, upload persistence, system avatar seeding, and legacy URL normalization in the API, then expose a shared frontend helper that resolves asset IDs and old URLs into API-reachable image URLs.

**Tech Stack:** FastAPI, SQLAlchemy 2, Alembic, Pydantic, pytest, Vite, React, TypeScript, Vitest, TanStack Query.

---

## File Structure

- Create `apps/api/app/models/player_avatar_asset.py`: SQLAlchemy model for avatar bytes and metadata.
- Modify `apps/api/app/models/__init__.py`: register the new model in `Base.metadata`.
- Modify `apps/api/app/models/virtual_player_profile.py`: add nullable `avatar_asset_id` FK.
- Create `apps/api/alembic/versions/20260701_01_create_player_avatar_assets.py`: create asset table, add FK, seed system assets, backfill known system avatar profiles.
- Create directory `apps/api/app/assets/player_avatars/`: stores four system PNGs as Alembic seed inputs.
- Replace `apps/api/app/werewolf/player_avatar_assets.py`: keep upload validation constants, add DB asset service, system mappings, legacy file import helpers, and public URL generation.
- Modify `apps/api/app/api/routes/player_profiles.py`: new asset read route, DB-backed upload route, profile response mapping, create/update normalization.
- Modify `apps/api/app/player_profile_import.py`: normalize imported legacy profile avatar references into asset IDs.
- Modify `apps/api/app/cli.py`: add `migrate-player-avatar-assets` command.
- Create `apps/api/app/player_avatar_asset_migration.py`: migration command logic for old file-backed uploaded avatars.
- Modify `apps/api/app/werewolf/player_configs.py`: emit generated API asset URLs for game player configs.
- Modify backend tests in `apps/api/tests/test_models.py`, `apps/api/tests/test_player_profiles_api.py`, `apps/api/tests/test_werewolf_cli.py`, and `apps/api/tests/test_games_api.py`.
- Create `packages/game-client/src/profile/avatarImageUrl.ts`: shared resolver for asset IDs and legacy paths.
- Modify `packages/game-client/src/profile/systemPlayerAvatars.ts`: replace frontend static image URLs with asset IDs.
- Modify `packages/game-client/src/profile/index.ts` and `packages/game-client/src/types.ts`: export helper and add avatar asset fields.
- Create `packages/game-client/src/profile/avatarImageUrl.test.ts`.
- Modify mobile renderers in `apps/mobile-web/src/pages/PlayersPage.tsx`, `apps/mobile-web/src/pages/GamesPage.tsx`, and `apps/mobile-web/src/pages/LivePage.tsx`.
- Modify desktop renderers and editor files under `apps/web/src/features/games/components/`.
- Update frontend tests in `packages/game-client`, `apps/mobile-web`, and `apps/web`.

---

### Task 1: Backend Models And Metadata

**Files:**
- Create: `apps/api/app/models/player_avatar_asset.py`
- Modify: `apps/api/app/models/__init__.py`
- Modify: `apps/api/app/models/virtual_player_profile.py`
- Test: `apps/api/tests/test_models.py`

- [ ] **Step 1: Write failing model tests**

Append these tests to `apps/api/tests/test_models.py`, and add `from app.models.player_avatar_asset import PlayerAvatarAsset` near the imports:

```python
def test_player_avatar_asset_table_is_registered_in_metadata() -> None:
    assert PlayerAvatarAsset.__table__.name == "player_avatar_assets"
    assert "player_avatar_assets" in Base.metadata.tables


def test_player_avatar_asset_table_matches_expected_schema() -> None:
    table = PlayerAvatarAsset.__table__
    column_names = set(table.columns.keys())

    assert column_names == {
        "id",
        "source",
        "content_type",
        "data",
        "sha256",
        "size_bytes",
        "created_at",
    }
    assert table.c.id.primary_key is True
    assert table.c.source.nullable is False
    assert table.c.content_type.nullable is False
    assert table.c.data.nullable is False
    assert table.c.sha256.nullable is False
    assert table.c.sha256.index is True
    assert table.c.size_bytes.nullable is False
    assert table.c.created_at.server_default is not None


def test_virtual_player_profile_has_avatar_asset_reference() -> None:
    table = VirtualPlayerProfile.__table__

    assert "avatar_asset_id" in table.columns
    assert table.c.avatar_asset_id.nullable is True
    assert table.c.avatar_asset_id.foreign_keys
```

Update the existing `test_virtual_player_profile_table_matches_expected_schema` expected `column_names` set to include `"avatar_asset_id"`.

- [ ] **Step 2: Run model tests and verify failure**

Run:

```bash
cd apps/api && uv run pytest tests/test_models.py -v
```

Expected: FAIL because `app.models.player_avatar_asset` does not exist and `avatar_asset_id` is missing.

- [ ] **Step 3: Create the avatar asset model**

Create `apps/api/app/models/player_avatar_asset.py`:

```python
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, LargeBinary, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class PlayerAvatarAsset(Base):
    __tablename__ = "player_avatar_assets"

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    source: Mapped[str] = mapped_column(String(20), nullable=False)
    content_type: Mapped[str] = mapped_column(String(80), nullable=False)
    data: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    size_bytes: Mapped[int] = mapped_column(nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
```

Modify `apps/api/app/models/__init__.py`:

```python
from app.models.player_avatar_asset import PlayerAvatarAsset
from app.models.user import User
from app.models.virtual_player_profile import VirtualPlayerProfile

__all__ = ["PlayerAvatarAsset", "User", "VirtualPlayerProfile"]
```

Modify `apps/api/app/models/virtual_player_profile.py` by adding this field after `avatar_image_mime`:

```python
    avatar_asset_id: Mapped[str | None] = mapped_column(
        ForeignKey("player_avatar_assets.id"),
        nullable=True,
        default=None,
    )
```

- [ ] **Step 4: Run model tests and verify pass**

Run:

```bash
cd apps/api && uv run pytest tests/test_models.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/api/app/models/player_avatar_asset.py apps/api/app/models/__init__.py apps/api/app/models/virtual_player_profile.py apps/api/tests/test_models.py
git commit -m "feat(api): add avatar asset model"
```

---

### Task 2: Alembic Migration And System Avatar Seed Assets

**Files:**
- Create: `apps/api/app/assets/player_avatars/gothic-male-1.png`
- Create: `apps/api/app/assets/player_avatars/gothic-male-2.png`
- Create: `apps/api/app/assets/player_avatars/gothic-female-1.png`
- Create: `apps/api/app/assets/player_avatars/gothic-female-2.png`
- Create: `apps/api/alembic/versions/20260701_01_create_player_avatar_assets.py`
- Verify: `apps/api/alembic/env.py`

- [ ] **Step 1: Copy system avatar seed files**

Run:

```bash
mkdir -p apps/api/app/assets/player_avatars
cp apps/web/public/player-avatars/gothic-male-1.png apps/api/app/assets/player_avatars/gothic-male-1.png
cp apps/web/public/player-avatars/gothic-male-2.png apps/api/app/assets/player_avatars/gothic-male-2.png
cp apps/web/public/player-avatars/gothic-female-1.png apps/api/app/assets/player_avatars/gothic-female-1.png
cp apps/web/public/player-avatars/gothic-female-2.png apps/api/app/assets/player_avatars/gothic-female-2.png
```

- [ ] **Step 2: Create migration**

Create `apps/api/alembic/versions/20260701_01_create_player_avatar_assets.py`:

```python
from __future__ import annotations

import hashlib
from pathlib import Path

from alembic import op
import sqlalchemy as sa

revision = "20260701_01"
down_revision = "20260517_02"
branch_labels = None
depends_on = None

SYSTEM_AVATARS = {
    "gothic-male-1": "system-gothic-male-1",
    "gothic-male-2": "system-gothic-male-2",
    "gothic-female-1": "system-gothic-female-1",
    "gothic-female-2": "system-gothic-female-2",
}


def upgrade() -> None:
    op.create_table(
        "player_avatar_assets",
        sa.Column("id", sa.String(length=80), primary_key=True),
        sa.Column("source", sa.String(length=20), nullable=False),
        sa.Column("content_type", sa.String(length=80), nullable=False),
        sa.Column("data", sa.LargeBinary(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index(
        "ix_player_avatar_assets_sha256",
        "player_avatar_assets",
        ["sha256"],
    )
    op.add_column(
        "virtual_player_profiles",
        sa.Column("avatar_asset_id", sa.String(length=80), nullable=True),
    )
    op.create_foreign_key(
        "fk_virtual_player_profiles_avatar_asset_id",
        "virtual_player_profiles",
        "player_avatar_assets",
        ["avatar_asset_id"],
        ["id"],
    )
    _seed_system_avatar_assets()
    _backfill_system_avatar_profiles()


def downgrade() -> None:
    op.drop_constraint(
        "fk_virtual_player_profiles_avatar_asset_id",
        "virtual_player_profiles",
        type_="foreignkey",
    )
    op.drop_column("virtual_player_profiles", "avatar_asset_id")
    op.drop_index("ix_player_avatar_assets_sha256", table_name="player_avatar_assets")
    op.drop_table("player_avatar_assets")


def _seed_system_avatar_assets() -> None:
    connection = op.get_bind()
    assets_dir = Path(__file__).resolve().parents[2] / "app" / "assets" / "player_avatars"
    rows = []
    for appearance_id, asset_id in SYSTEM_AVATARS.items():
        data = (assets_dir / f"{appearance_id}.png").read_bytes()
        rows.append(
            {
                "id": asset_id,
                "source": "system",
                "content_type": "image/png",
                "data": data,
                "sha256": hashlib.sha256(data).hexdigest(),
                "size_bytes": len(data),
            }
        )
    table = sa.table(
        "player_avatar_assets",
        sa.column("id", sa.String),
        sa.column("source", sa.String),
        sa.column("content_type", sa.String),
        sa.column("data", sa.LargeBinary),
        sa.column("sha256", sa.String),
        sa.column("size_bytes", sa.Integer),
    )
    connection.execute(table.insert(), rows)


def _backfill_system_avatar_profiles() -> None:
    connection = op.get_bind()
    for appearance_id, asset_id in SYSTEM_AVATARS.items():
        legacy_url = f"/player-avatars/{appearance_id}.png"
        connection.execute(
            sa.text(
                """
                UPDATE virtual_player_profiles
                SET avatar_asset_id = :asset_id,
                    avatar_image_mime = 'image/png'
                WHERE avatar_asset_id IS NULL
                  AND (appearance_id = :appearance_id OR avatar_image_url = :legacy_url)
                """
            ),
            {
                "asset_id": asset_id,
                "appearance_id": appearance_id,
                "legacy_url": legacy_url,
            },
        )
```

- [ ] **Step 3: Verify migration upgrades against local database**

Run:

```bash
cd apps/api && uv run alembic upgrade head
```

Expected: migration reaches `20260701_01` without errors.

- [ ] **Step 4: Verify migration can downgrade one revision**

Run:

```bash
cd apps/api && uv run alembic downgrade 20260517_02 && uv run alembic upgrade head
```

Expected: downgrade removes the new table and column, then upgrade recreates them and reseeds system assets.

- [ ] **Step 5: Commit**

```bash
git add apps/api/app/assets/player_avatars apps/api/alembic/versions/20260701_01_create_player_avatar_assets.py
git commit -m "feat(api): migrate avatar assets into database"
```

---

### Task 3: Avatar Asset Service And Read/Upload API

**Files:**
- Modify: `apps/api/app/werewolf/player_avatar_assets.py`
- Modify: `apps/api/app/api/routes/player_profiles.py`
- Modify: `apps/api/tests/test_player_profiles_api.py`

- [ ] **Step 1: Write failing API tests**

In `apps/api/tests/test_player_profiles_api.py`, add `from app.models.player_avatar_asset import PlayerAvatarAsset` and remove the dependency override import for `get_player_avatar_asset_store` after the implementation removes it.

Update the `isolated_db` fixture cleanup to delete profiles before assets:

```python
    with TestingSessionLocal() as session:
        session.query(VirtualPlayerProfile).delete()
        session.query(PlayerAvatarAsset).delete()
        session.query(User).delete()
        session.commit()
```

Make the same cleanup change after `yield`.

Replace `test_upload_avatar_image_returns_served_asset_url` with:

```python
def test_upload_avatar_image_returns_database_asset_url() -> None:
    response = client.post(
        "/api/v1/player-profiles/avatar",
        json={
            "filename": "portrait.png",
            "content_type": "image/png",
            "data_base64": base64.b64encode(PNG_BYTES).decode("ascii"),
        },
    )
    payload = response.json()
    served_response = client.get(payload["avatar_image_url"])

    assert response.status_code == 201
    assert payload["avatar_asset_id"].startswith("uploaded-")
    assert payload["avatar_image_url"] == (
        f"/api/v1/player-profiles/avatar-assets/{payload['avatar_asset_id']}"
    )
    assert payload["avatar_image_mime"] == "image/png"
    assert served_response.status_code == 200
    assert served_response.headers["content-type"] == "image/png"
    assert served_response.headers["cache-control"] == "public, max-age=31536000, immutable"
    assert served_response.content == PNG_BYTES

    with TestingSessionLocal() as session:
        asset = session.get(PlayerAvatarAsset, payload["avatar_asset_id"])

    assert asset is not None
    assert asset.source == "uploaded"
    assert asset.content_type == "image/png"
    assert asset.data == PNG_BYTES
    assert asset.size_bytes == len(PNG_BYTES)
```

Add:

```python
def test_get_avatar_asset_returns_404_for_missing_asset() -> None:
    response = client.get("/api/v1/player-profiles/avatar-assets/missing-asset")

    assert response.status_code == 404
    assert response.json()["detail"] == "Avatar asset not found"
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
cd apps/api && uv run pytest tests/test_player_profiles_api.py::test_upload_avatar_image_returns_database_asset_url tests/test_player_profiles_api.py::test_get_avatar_asset_returns_404_for_missing_asset -v
```

Expected: FAIL because upload still writes to the file store and `/avatar-assets/{asset_id}` does not exist.

- [ ] **Step 3: Implement DB asset service**

Replace `apps/api/app/werewolf/player_avatar_assets.py` with this focused service. Keep `PlayerAvatarAssetStore` only if a later task still needs legacy file reading; this task should introduce the DB write/read functions:

```python
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
class AvatarImageData:
    content_type: str
    data: bytes


def avatar_asset_url(asset_id: str) -> str:
    return f"{settings.api_v1_prefix}/player-profiles/avatar-assets/{asset_id}"


def normalize_avatar_content_type(content_type: str) -> str:
    normalized = content_type.lower().strip()
    if normalized == "image/jpg":
        return "image/jpeg"
    if normalized not in AVATAR_IMAGE_TYPES:
        raise ValueError("Unsupported avatar image type")
    return normalized


def decode_uploaded_avatar(*, content_type: str, data_base64: str) -> AvatarImageData:
    normalized_type = normalize_avatar_content_type(content_type)
    try:
        image_bytes = base64.b64decode(data_base64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("Invalid avatar image data") from exc
    if len(image_bytes) > MAX_AVATAR_IMAGE_BYTES:
        raise ValueError("Avatar image must be 2MB or smaller")
    return AvatarImageData(content_type=normalized_type, data=image_bytes)


def create_avatar_asset(
    db: Session,
    *,
    source: str,
    content_type: str,
    data: bytes,
    asset_id: str | None = None,
) -> PlayerAvatarAsset:
    normalized_type = normalize_avatar_content_type(content_type)
    digest = hashlib.sha256(data).hexdigest()
    existing = (
        db.query(PlayerAvatarAsset)
        .filter(
            PlayerAvatarAsset.sha256 == digest,
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
        sha256=digest,
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
    image = decode_uploaded_avatar(content_type=content_type, data_base64=data_base64)
    return create_avatar_asset(
        db,
        source="uploaded",
        content_type=image.content_type,
        data=image.data,
    )


def system_avatar_asset_id_for_appearance(appearance_id: str | None) -> str | None:
    if not appearance_id:
        return None
    return SYSTEM_AVATAR_ASSET_IDS.get(appearance_id)


def system_avatar_asset_id_for_legacy_url(url: str | None) -> str | None:
    if not url:
        return None
    return LEGACY_SYSTEM_AVATAR_URLS.get(url.strip())


def legacy_avatar_file_path(logs_dir: str | Path, avatar_image_url: str) -> Path | None:
    prefix = f"{settings.api_v1_prefix}/player-profiles/avatar/"
    if not avatar_image_url.startswith(prefix):
        return None
    filename = avatar_image_url.removeprefix(prefix)
    if Path(filename).name != filename:
        return None
    return Path(logs_dir) / "player_profile_assets" / filename
```

- [ ] **Step 4: Implement DB-backed upload and read routes**

Modify `apps/api/app/api/routes/player_profiles.py`:

```python
from fastapi import APIRouter, Depends, HTTPException, Response
```

Import the new helpers and model:

```python
from app.models.player_avatar_asset import PlayerAvatarAsset
from app.werewolf.player_avatar_assets import (
    avatar_asset_url,
    save_uploaded_avatar_asset,
)
```

Change `AvatarUploadResponse`:

```python
class AvatarUploadResponse(BaseModel):
    avatar_asset_id: str
    avatar_image_url: str
    avatar_image_mime: str
```

Replace `upload_player_avatar` and add the new read route:

```python
@router.post("/avatar", response_model=AvatarUploadResponse, status_code=201)
def upload_player_avatar(
    request: AvatarUploadRequest,
    db: Annotated[Session, Depends(get_db)],
) -> AvatarUploadResponse:
    try:
        asset = save_uploaded_avatar_asset(
            db,
            content_type=request.content_type,
            data_base64=request.data_base64,
        )
        db.commit()
        db.refresh(asset)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RecoverableDatabaseError as exc:
        db.rollback()
        raise _profile_database_unavailable() from exc

    return AvatarUploadResponse(
        avatar_asset_id=asset.id,
        avatar_image_url=avatar_asset_url(asset.id),
        avatar_image_mime=asset.content_type,
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
```

Leave the existing `GET /avatar/{filename}` route in place for old file-backed URLs until Task 5 rewires it to a legacy file helper.

- [ ] **Step 5: Run target API tests and verify pass**

Run:

```bash
cd apps/api && uv run pytest tests/test_player_profiles_api.py::test_upload_avatar_image_returns_database_asset_url tests/test_player_profiles_api.py::test_get_avatar_asset_returns_404_for_missing_asset -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add apps/api/app/werewolf/player_avatar_assets.py apps/api/app/api/routes/player_profiles.py apps/api/tests/test_player_profiles_api.py
git commit -m "feat(api): serve uploaded avatar assets from database"
```

---

### Task 4: Profile Avatar Reference Normalization

**Files:**
- Modify: `apps/api/app/werewolf/player_avatar_assets.py`
- Modify: `apps/api/app/api/routes/player_profiles.py`
- Modify: `apps/api/tests/test_player_profiles_api.py`

- [ ] **Step 1: Write failing profile normalization tests**

Replace the old `test_create_profile_persists_avatar_image_metadata` and `test_create_profile_accepts_system_avatar_appearance_id` expectations with:

```python
def test_create_profile_binds_system_avatar_from_appearance_id() -> None:
    response = client.post(
        "/api/v1/player-profiles",
        json={
            "display_name": "内设形象玩家",
            "model": "gpt-4.1-mini",
            "appearance_id": "gothic-female-2",
        },
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["appearance_id"] == "gothic-female-2"
    assert payload["avatar_asset_id"] == "system-gothic-female-2"
    assert payload["avatar_image_url"] == (
        "/api/v1/player-profiles/avatar-assets/system-gothic-female-2"
    )
    assert payload["avatar_image_mime"] == "image/png"


def test_create_profile_normalizes_legacy_system_avatar_url() -> None:
    response = client.post(
        "/api/v1/player-profiles",
        json={
            "display_name": "旧路径玩家",
            "model": "gpt-4.1-mini",
            "appearance_id": "default",
            "avatar_image_url": "/player-avatars/gothic-male-1.png",
            "avatar_image_mime": "image/png",
        },
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["avatar_asset_id"] == "system-gothic-male-1"
    assert payload["avatar_image_url"] == (
        "/api/v1/player-profiles/avatar-assets/system-gothic-male-1"
    )
```

Add:

```python
def test_create_profile_rejects_missing_legacy_uploaded_avatar_file() -> None:
    response = client.post(
        "/api/v1/player-profiles",
        json={
            "display_name": "缺图玩家",
            "model": "gpt-4.1-mini",
            "avatar_image_url": "/api/v1/player-profiles/avatar/missing.png",
            "avatar_image_mime": "image/png",
        },
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "Legacy avatar image file not found"
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
cd apps/api && uv run pytest tests/test_player_profiles_api.py::test_create_profile_binds_system_avatar_from_appearance_id tests/test_player_profiles_api.py::test_create_profile_normalizes_legacy_system_avatar_url tests/test_player_profiles_api.py::test_create_profile_rejects_missing_legacy_uploaded_avatar_file -v
```

Expected: FAIL because profile creation does not bind `avatar_asset_id`.

- [ ] **Step 3: Implement profile avatar normalization helpers**

Add to `apps/api/app/werewolf/player_avatar_assets.py`:

```python
@dataclass(frozen=True)
class ResolvedAvatarReference:
    avatar_asset_id: str | None
    avatar_image_url: str
    avatar_image_mime: str


def resolve_profile_avatar_reference(
    db: Session,
    *,
    avatar_asset_id: str | None,
    appearance_id: str,
    avatar_image_url: str,
    avatar_image_mime: str,
    logs_dir: str | Path,
) -> ResolvedAvatarReference:
    requested_asset_id = (avatar_asset_id or "").strip() or None
    if requested_asset_id is not None:
        asset = db.get(PlayerAvatarAsset, requested_asset_id)
        if asset is None:
            raise ValueError("Avatar asset not found")
        return ResolvedAvatarReference(
            avatar_asset_id=asset.id,
            avatar_image_url=avatar_asset_url(asset.id),
            avatar_image_mime=asset.content_type,
        )

    system_asset_id = (
        system_avatar_asset_id_for_appearance(appearance_id)
        or system_avatar_asset_id_for_legacy_url(avatar_image_url)
    )
    if system_asset_id is not None:
        return ResolvedAvatarReference(
            avatar_asset_id=system_asset_id,
            avatar_image_url=avatar_asset_url(system_asset_id),
            avatar_image_mime="image/png",
        )

    legacy_path = legacy_avatar_file_path(logs_dir, avatar_image_url)
    if legacy_path is not None:
        if not legacy_path.is_file():
            raise ValueError("Legacy avatar image file not found")
        data = legacy_path.read_bytes()
        asset = create_avatar_asset(
            db,
            source="migrated",
            content_type=avatar_image_mime,
            data=data,
        )
        return ResolvedAvatarReference(
            avatar_asset_id=asset.id,
            avatar_image_url=avatar_asset_url(asset.id),
            avatar_image_mime=asset.content_type,
        )

    return ResolvedAvatarReference(
        avatar_asset_id=None,
        avatar_image_url=avatar_image_url,
        avatar_image_mime=avatar_image_mime,
    )
```

- [ ] **Step 4: Wire normalization into create/update/list responses**

In `apps/api/app/api/routes/player_profiles.py`, add `avatar_asset_id` to `PlayerProfileBase`, `UpdatePlayerProfileRequest`, and `PlayerProfileResponse`:

```python
    avatar_asset_id: str | None = Field(default=None, max_length=80)
```

For `PlayerProfileResponse`, use:

```python
    avatar_asset_id: str | None
```

Add `resolve_profile_avatar_reference` to the imports.

Add this response mapper:

```python
def _profile_response(profile: VirtualPlayerProfile) -> PlayerProfileResponse:
    payload = PlayerProfileResponse.model_validate(profile)
    if profile.avatar_asset_id:
        payload.avatar_image_url = avatar_asset_url(profile.avatar_asset_id)
    return payload
```

Update list/get/create/update endpoints to return `PlayerProfileResponse` objects:

```python
return PlayerProfileListResponse(profiles=[_profile_response(profile) for profile in profiles])
```

Before creating a `VirtualPlayerProfile`, resolve the avatar:

```python
    try:
        avatar = resolve_profile_avatar_reference(
            db,
            avatar_asset_id=request.avatar_asset_id,
            appearance_id=request.appearance_id,
            avatar_image_url=request.avatar_image_url,
            avatar_image_mime=request.avatar_image_mime,
            logs_dir=settings.werewolf_logs_dir,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
```

Set the model fields:

```python
        avatar_image_url=avatar.avatar_image_url,
        avatar_image_path="",
        avatar_image_mime=avatar.avatar_image_mime,
        avatar_asset_id=avatar.avatar_asset_id,
```

In update, compute candidate values after applying request defaults but before mutating the profile:

```python
    avatar = resolve_profile_avatar_reference(
        db,
        avatar_asset_id=updates.get("avatar_asset_id", profile.avatar_asset_id),
        appearance_id=appearance_id,
        avatar_image_url=updates.get("avatar_image_url", profile.avatar_image_url),
        avatar_image_mime=updates.get("avatar_image_mime", profile.avatar_image_mime),
        logs_dir=settings.werewolf_logs_dir,
    )
```

Then set `updates["avatar_asset_id"]`, `updates["avatar_image_url"]`, `updates["avatar_image_mime"]`, and `updates["avatar_image_path"] = ""` before the existing field loop.

- [ ] **Step 5: Run target tests and verify pass**

Run:

```bash
cd apps/api && uv run pytest tests/test_player_profiles_api.py::test_create_profile_binds_system_avatar_from_appearance_id tests/test_player_profiles_api.py::test_create_profile_normalizes_legacy_system_avatar_url tests/test_player_profiles_api.py::test_create_profile_rejects_missing_legacy_uploaded_avatar_file -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add apps/api/app/werewolf/player_avatar_assets.py apps/api/app/api/routes/player_profiles.py apps/api/tests/test_player_profiles_api.py
git commit -m "feat(api): normalize profile avatar references"
```

---

### Task 5: Legacy Avatar Asset Migration CLI And JSON Import

**Files:**
- Create: `apps/api/app/player_avatar_asset_migration.py`
- Modify: `apps/api/app/player_profile_import.py`
- Modify: `apps/api/app/werewolf/player_profile_store.py`
- Modify: `apps/api/app/cli.py`
- Modify: `apps/api/tests/test_werewolf_cli.py`

- [ ] **Step 1: Write failing CLI migration tests**

Add `from app.models.player_avatar_asset import PlayerAvatarAsset` to `apps/api/tests/test_werewolf_cli.py`.

In existing test databases, call `Base.metadata.create_all(engine)` as-is after Task 1 registered `PlayerAvatarAsset`.

Add:

```python
PNG_BYTES = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
    b"\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
)


def test_migrate_player_avatar_assets_command_imports_legacy_files(
    tmp_path,
    capsys,
    monkeypatch,
) -> None:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    testing_session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    monkeypatch.setattr(cli, "SessionLocal", testing_session, raising=False)
    asset_dir = tmp_path / "player_profile_assets"
    asset_dir.mkdir()
    (asset_dir / "legacy.png").write_bytes(PNG_BYTES)
    with testing_session() as session:
        session.add(
            VirtualPlayerProfile(
                id="legacy-profile",
                owner_user_id=None,
                display_name="旧图玩家",
                model="deepseek-v4-flash",
                personality_id="balanced",
                personality_text="稳健推进。",
                appearance_id="default",
                avatar_prompt="",
                avatar_image_url="/api/v1/player-profiles/avatar/legacy.png",
                avatar_image_path="",
                avatar_image_mime="image/png",
                tags=[],
            )
        )
        session.commit()

    exit_code = main(["migrate-player-avatar-assets", "--logs-dir", str(tmp_path)])
    output = capsys.readouterr().out

    with testing_session() as session:
        profile = session.get(VirtualPlayerProfile, "legacy-profile")
        assets = session.query(PlayerAvatarAsset).all()

    assert exit_code == 0
    assert "扫描=1 导入=1 复用=0 缺失=0 回填=1" in output
    assert profile is not None
    assert profile.avatar_asset_id == assets[0].id
    assert assets[0].source == "migrated"
    assert assets[0].data == PNG_BYTES
```

Add:

```python
def test_import_player_profiles_maps_legacy_system_avatar_to_asset_id(
    tmp_path,
    capsys,
    monkeypatch,
) -> None:
    source = tmp_path / "player_profiles.json"
    source.write_text(
        json.dumps(
            {
                "version": 3,
                "profiles": [
                    {
                        "id": "legacy-system-profile",
                        "display_name": "内设旧图",
                        "model": "deepseek-v4-flash",
                        "appearance_id": "default",
                        "avatar_image_url": "/player-avatars/gothic-female-1.png",
                        "avatar_image_mime": "image/png",
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    testing_session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    monkeypatch.setattr(cli, "SessionLocal", testing_session, raising=False)

    exit_code = main(["import-player-profiles", "--source", str(source)])
    capsys.readouterr()

    with testing_session() as session:
        imported = session.get(VirtualPlayerProfile, "legacy-system-profile")

    assert exit_code == 0
    assert imported is not None
    assert imported.avatar_asset_id == "system-gothic-female-1"
    assert imported.avatar_image_url == (
        "/api/v1/player-profiles/avatar-assets/system-gothic-female-1"
    )
```

- [ ] **Step 2: Run CLI tests and verify failure**

Run:

```bash
cd apps/api && uv run pytest tests/test_werewolf_cli.py::test_migrate_player_avatar_assets_command_imports_legacy_files tests/test_werewolf_cli.py::test_import_player_profiles_maps_legacy_system_avatar_to_asset_id -v
```

Expected: FAIL because the command and import normalization do not exist.

- [ ] **Step 3: Implement migration command logic**

Create `apps/api/app/player_avatar_asset_migration.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.models.virtual_player_profile import VirtualPlayerProfile
from app.werewolf.player_avatar_assets import (
    avatar_asset_url,
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


def migrate_player_avatar_assets(*, logs_dir: Path, db: Session) -> PlayerAvatarAssetMigrationResult:
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
            asset = create_avatar_asset(
                db,
                source="migrated",
                content_type=profile.avatar_image_mime,
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
            profile.avatar_image_path = ""
            updated_count += 1
        db.commit()
    except SQLAlchemyError as exc:
        db.rollback()
        raise PlayerAvatarAssetMigrationError("迁移玩家头像资产失败") from exc
    return PlayerAvatarAssetMigrationResult(
        scanned_count=scanned_count,
        imported_count=imported_count,
        reused_count=reused_count,
        missing_count=missing_count,
        updated_count=updated_count,
    )
```

- [ ] **Step 4: Add CLI command**

Modify `apps/api/app/cli.py` imports:

```python
from app.core.config import settings
from app.player_avatar_asset_migration import (
    PlayerAvatarAssetMigrationError,
    migrate_player_avatar_assets,
)
```

Add parser:

```python
    migrate_avatar_parser = subparsers.add_parser(
        "migrate-player-avatar-assets",
        help="Import legacy file-backed player avatar images into PostgreSQL.",
    )
    migrate_avatar_parser.add_argument("--logs-dir", type=Path, default=Path(settings.werewolf_logs_dir))
    migrate_avatar_parser.set_defaults(func=_migrate_player_avatar_assets_command)
```

Add command function:

```python
def _migrate_player_avatar_assets_command(args: argparse.Namespace) -> int:
    db = SessionLocal()
    try:
        result = migrate_player_avatar_assets(logs_dir=args.logs_dir, db=db)
    except PlayerAvatarAssetMigrationError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    finally:
        db.close()

    print(
        f"扫描={result.scanned_count} "
        f"导入={result.imported_count} "
        f"复用={result.reused_count} "
        f"缺失={result.missing_count} "
        f"回填={result.updated_count}"
    )
    return 0
```

- [ ] **Step 5: Normalize JSON imports**

Modify `apps/api/app/player_profile_import.py`:

```python
from app.core.config import settings
from app.werewolf.player_avatar_assets import resolve_profile_avatar_reference
```

Change `_database_profile` to accept `db: Session`:

```python
def _database_profile(profile: StoredPlayerProfile, db: Session) -> VirtualPlayerProfile:
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
        avatar_image_url=avatar.avatar_image_url,
        avatar_image_path="",
        avatar_image_mime=avatar.avatar_image_mime,
        avatar_asset_id=avatar.avatar_asset_id,
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
```

Update call site:

```python
            db.add(_database_profile(profile, db))
```

Modify `apps/api/app/werewolf/player_profile_store.py`:

- Add `avatar_asset_id: str | None` to `StoredPlayerProfile`.
- Set `avatar_asset_id=_optional_string(payload.get("avatar_asset_id"))` in `_profile_from_payload`.

- [ ] **Step 6: Run CLI tests and verify pass**

Run:

```bash
cd apps/api && uv run pytest tests/test_werewolf_cli.py::test_migrate_player_avatar_assets_command_imports_legacy_files tests/test_werewolf_cli.py::test_import_player_profiles_maps_legacy_system_avatar_to_asset_id -v
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add apps/api/app/player_avatar_asset_migration.py apps/api/app/player_profile_import.py apps/api/app/werewolf/player_profile_store.py apps/api/app/cli.py apps/api/tests/test_werewolf_cli.py
git commit -m "feat(api): migrate legacy avatar assets"
```

---

### Task 6: Game Player Config Avatar URLs

**Files:**
- Modify: `apps/api/app/werewolf/player_configs.py`
- Modify: `apps/api/tests/test_games_api.py`

- [ ] **Step 1: Write failing game config test changes**

In `apps/api/tests/test_games_api.py`, add `from app.models.player_avatar_asset import PlayerAvatarAsset`.

Update `isolated_db` cleanup to delete `VirtualPlayerProfile` before `PlayerAvatarAsset`, then delete `PlayerAvatarAsset`.

In `test_create_game_run_resolves_profile_configs`, create a matching asset before adding the profile:

```python
            PlayerAvatarAsset(
                id="system-gothic-female-2",
                source="system",
                content_type="image/png",
                data=b"png-bytes",
                sha256="0" * 64,
                size_bytes=9,
            )
```

Change the profile avatar fields:

```python
                appearance_id="gothic-female-2",
                avatar_image_url="/player-avatars/gothic-female-2.png",
                avatar_image_mime="image/png",
                avatar_asset_id="system-gothic-female-2",
```

Change the expected snapshot URL:

```python
        "avatar_image_url": "/api/v1/player-profiles/avatar-assets/system-gothic-female-2",
```

- [ ] **Step 2: Run target game test and verify failure**

Run:

```bash
cd apps/api && uv run pytest tests/test_games_api.py::test_create_game_run_resolves_profile_configs -v
```

Expected: FAIL because `player_config_from_profile` still returns the stored legacy URL.

- [ ] **Step 3: Emit asset URLs from player configs**

Modify `apps/api/app/werewolf/player_configs.py`:

```python
from app.werewolf.player_avatar_assets import avatar_asset_url
```

Add helper:

```python
def _profile_avatar_image_url(profile: object | None) -> str | None:
    if profile is None:
        return None
    avatar_asset_id = clean_optional_string(getattr(profile, "avatar_asset_id", None))
    if avatar_asset_id is not None:
        return avatar_asset_url(avatar_asset_id)
    return _profile_string(profile, "avatar_image_url")
```

Change `avatar_image_url` assignment:

```python
        avatar_image_url=(
            _override_string(overrides, "avatar_image_url")
            or _profile_avatar_image_url(profile)
            or ""
        ),
```

- [ ] **Step 4: Run target game test and verify pass**

Run:

```bash
cd apps/api && uv run pytest tests/test_games_api.py::test_create_game_run_resolves_profile_configs -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/api/app/werewolf/player_configs.py apps/api/tests/test_games_api.py
git commit -m "feat(api): use avatar asset urls in game configs"
```

---

### Task 7: Shared Frontend Avatar URL Helper And Types

**Files:**
- Create: `packages/game-client/src/profile/avatarImageUrl.ts`
- Create: `packages/game-client/src/profile/avatarImageUrl.test.ts`
- Modify: `packages/game-client/src/profile/index.ts`
- Modify: `packages/game-client/src/profile/systemPlayerAvatars.ts`
- Modify: `packages/game-client/src/types.ts`
- Modify: `packages/game-client/src/profile/playerProfileCreation.ts`
- Modify: `packages/game-client/src/profile/playerProfileCreation.test.ts`

- [ ] **Step 1: Write failing helper tests**

Create `packages/game-client/src/profile/avatarImageUrl.test.ts`:

```ts
import { describe, expect, it } from "vitest";

import {
  avatarAssetImageUrl,
  resolveAvatarImageUrl,
  systemAvatarAssetIdForAppearance,
} from "./avatarImageUrl";

describe("avatar image URL helpers", () => {
  it("builds API asset URLs with an explicit base URL", () => {
    expect(
      avatarAssetImageUrl("system-gothic-male-1", {
        baseUrl: "https://api.example.test",
      }),
    ).toBe(
      "https://api.example.test/api/v1/player-profiles/avatar-assets/system-gothic-male-1",
    );
  });

  it("resolves avatar_asset_id before legacy URL fields", () => {
    expect(
      resolveAvatarImageUrl(
        {
          avatar_asset_id: "system-gothic-female-2",
          avatar_image_url: "/player-avatars/gothic-male-1.png",
        },
        { baseUrl: "https://api.example.test" },
      ),
    ).toBe(
      "https://api.example.test/api/v1/player-profiles/avatar-assets/system-gothic-female-2",
    );
  });

  it("resolves old system avatar URLs to API asset URLs", () => {
    expect(
      resolveAvatarImageUrl(
        { avatar_image_url: "/player-avatars/gothic-female-1.png" },
        { baseUrl: "https://api.example.test" },
      ),
    ).toBe(
      "https://api.example.test/api/v1/player-profiles/avatar-assets/system-gothic-female-1",
    );
  });

  it("prefixes API relative image URLs", () => {
    expect(
      resolveAvatarImageUrl(
        { avatar_image_url: "/api/v1/player-profiles/avatar-assets/uploaded-abc" },
        { baseUrl: "https://api.example.test" },
      ),
    ).toBe("https://api.example.test/api/v1/player-profiles/avatar-assets/uploaded-abc");
  });

  it("returns an empty string when no avatar is available", () => {
    expect(resolveAvatarImageUrl({}, { baseUrl: "https://api.example.test" })).toBe("");
  });

  it("maps appearance IDs to system avatar asset IDs", () => {
    expect(systemAvatarAssetIdForAppearance("gothic-male-2")).toBe(
      "system-gothic-male-2",
    );
    expect(systemAvatarAssetIdForAppearance("default")).toBeNull();
  });
});
```

- [ ] **Step 2: Run helper tests and verify failure**

Run:

```bash
pnpm --dir packages/game-client test -- --run src/profile/avatarImageUrl.test.ts
```

Expected: FAIL because `avatarImageUrl.ts` does not exist.

- [ ] **Step 3: Implement helper and type fields**

Create `packages/game-client/src/profile/avatarImageUrl.ts`:

```ts
export type AvatarImageValue = {
  avatar_asset_id?: string | null;
  avatar_image_url?: string | null;
};

export type AvatarImageUrlOptions = {
  baseUrl?: string;
};

const API_AVATAR_ASSET_PREFIX = "/api/v1/player-profiles/avatar-assets/";

export const SYSTEM_AVATAR_ASSET_IDS = {
  "gothic-male-1": "system-gothic-male-1",
  "gothic-male-2": "system-gothic-male-2",
  "gothic-female-1": "system-gothic-female-1",
  "gothic-female-2": "system-gothic-female-2",
} as const;

const LEGACY_SYSTEM_AVATAR_URLS: Record<string, string> = Object.fromEntries(
  Object.entries(SYSTEM_AVATAR_ASSET_IDS).map(([appearanceId, assetId]) => [
    `/player-avatars/${appearanceId}.png`,
    assetId,
  ]),
);

export function systemAvatarAssetIdForAppearance(appearanceId: string) {
  return SYSTEM_AVATAR_ASSET_IDS[
    appearanceId as keyof typeof SYSTEM_AVATAR_ASSET_IDS
  ] ?? null;
}

export function avatarAssetImageUrl(
  assetId: string,
  options: AvatarImageUrlOptions = {},
) {
  return withApiBaseUrl(`${API_AVATAR_ASSET_PREFIX}${assetId}`, options.baseUrl);
}

export function resolveAvatarImageUrl(
  value: AvatarImageValue,
  options: AvatarImageUrlOptions = {},
) {
  const assetId = value.avatar_asset_id?.trim();
  if (assetId) {
    return avatarAssetImageUrl(assetId, options);
  }

  const imageUrl = value.avatar_image_url?.trim();
  if (!imageUrl) {
    return "";
  }

  const legacyAssetId = LEGACY_SYSTEM_AVATAR_URLS[imageUrl];
  if (legacyAssetId) {
    return avatarAssetImageUrl(legacyAssetId, options);
  }

  if (imageUrl.startsWith("/api/")) {
    return withApiBaseUrl(imageUrl, options.baseUrl);
  }

  return imageUrl;
}

function withApiBaseUrl(path: string, explicitBaseUrl?: string) {
  const baseUrl = explicitBaseUrl ?? defaultApiBaseUrl();
  if (!baseUrl) {
    return path;
  }
  return `${baseUrl.replace(/\/$/, "")}${path}`;
}

function defaultApiBaseUrl() {
  const meta = import.meta as ImportMeta & {
    env?: { VITE_API_BASE_URL?: string };
  };

  return meta.env?.VITE_API_BASE_URL ?? "";
}
```

Modify `packages/game-client/src/profile/index.ts`:

```ts
export * from "./avatarImageUrl";
export * from "./playerProfileCreation";
export * from "./playerProfileOptions";
export * from "./playerStrategyOptions";
export * from "./profilePromptPreview";
export * from "./systemPlayerAvatars";
```

Modify `packages/game-client/src/types.ts`:

- Add `avatar_asset_id?: string | null;` to `RawPlayer`.
- Add `avatar_asset_id: string | null;` to `VirtualPlayerProfile`.
- Add `avatar_asset_id: string;` to `PlayerAvatarUploadResponse`.
- Add `avatar_asset_id?: string | null;` to `PlayerProfileRequest`.
- Add `avatar_asset_id: ""` to `DEFAULT_PLAYER_PROFILE_DRAFT`.

Modify `packages/game-client/src/profile/systemPlayerAvatars.ts`:

```ts
import { avatarAssetImageUrl, SYSTEM_AVATAR_ASSET_IDS } from "./avatarImageUrl";

export type SystemPlayerAvatar = {
  id: string;
  assetId: string;
  label: string;
  gender: "male" | "female";
  mime: "image/png";
};

export const SYSTEM_PLAYER_AVATARS: SystemPlayerAvatar[] = [
  {
    id: "gothic-male-1",
    assetId: SYSTEM_AVATAR_ASSET_IDS["gothic-male-1"],
    label: "夜甲行者",
    gender: "male",
    mime: "image/png",
  },
  {
    id: "gothic-male-2",
    assetId: SYSTEM_AVATAR_ASSET_IDS["gothic-male-2"],
    label: "银发贵族",
    gender: "male",
    mime: "image/png",
  },
  {
    id: "gothic-female-1",
    assetId: SYSTEM_AVATAR_ASSET_IDS["gothic-female-1"],
    label: "霜银骑士",
    gender: "female",
    mime: "image/png",
  },
  {
    id: "gothic-female-2",
    assetId: SYSTEM_AVATAR_ASSET_IDS["gothic-female-2"],
    label: "黑纱预言者",
    gender: "female",
    mime: "image/png",
  },
];

export function systemPlayerAvatarImageUrl(avatar: SystemPlayerAvatar) {
  return avatarAssetImageUrl(avatar.assetId);
}

export function randomSystemPlayerAvatar(rng = Math.random) {
  const index = Math.floor(rng() * SYSTEM_PLAYER_AVATARS.length);
  return SYSTEM_PLAYER_AVATARS[index] ?? SYSTEM_PLAYER_AVATARS[0];
}
```

Update `packages/game-client/src/profile/playerProfileCreation.ts` readiness logic so avatar presence includes asset id:

```ts
    draft.avatar_asset_id?.trim() ||
    draft.avatar_image_url?.trim() ||
    draft.appearance_id?.trim(),
```

Update `packages/game-client/src/profile/playerProfileCreation.test.ts` legacy expectations to include `avatar_asset_id` when testing system avatars.

- [ ] **Step 4: Run helper tests and typecheck**

Run:

```bash
pnpm --dir packages/game-client test -- --run src/profile/avatarImageUrl.test.ts src/profile/playerProfileCreation.test.ts
pnpm --dir packages/game-client typecheck
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add packages/game-client/src/profile/avatarImageUrl.ts packages/game-client/src/profile/avatarImageUrl.test.ts packages/game-client/src/profile/index.ts packages/game-client/src/profile/systemPlayerAvatars.ts packages/game-client/src/types.ts packages/game-client/src/profile/playerProfileCreation.ts packages/game-client/src/profile/playerProfileCreation.test.ts
git commit -m "feat(game-client): resolve avatar asset urls"
```

---

### Task 8: Mobile Web Avatar Rendering

**Files:**
- Modify: `apps/mobile-web/src/pages/PlayersPage.tsx`
- Modify: `apps/mobile-web/src/pages/GamesPage.tsx`
- Modify: `apps/mobile-web/src/pages/LivePage.tsx`
- Modify: `apps/mobile-web/src/pages/PlayersPage.test.tsx`
- Modify: `apps/mobile-web/src/pages/GamesPage.test.tsx`
- Modify: `apps/mobile-web/src/pages/LivePage.test.tsx`

- [ ] **Step 1: Write failing mobile tests**

In mobile test profile builders, add `avatar_asset_id: overrides.avatar_asset_id ?? null`.

Add to `apps/mobile-web/src/pages/PlayersPage.test.tsx`:

```tsx
it("renders player avatars through API asset URLs", async () => {
  gameClientMocks.listPlayerProfiles.mockResolvedValue({
    profiles: [
      buildProfile({
        id: "moon-hunter",
        display_name: "月下猎人",
        avatar_asset_id: "system-gothic-female-1",
        avatar_image_url: "/player-avatars/gothic-female-1.png",
        avatar_image_mime: "image/png",
      }),
    ],
  });

  renderWithQueryClient(<PlayersPage />);

  const avatar = await screen.findByRole("img", { name: "月下猎人 头像" });
  expect(avatar).toHaveAttribute(
    "src",
    "/api/v1/player-profiles/avatar-assets/system-gothic-female-1",
  );
});
```

Add to `apps/mobile-web/src/pages/GamesPage.test.tsx`:

```tsx
it("renders player card drawer avatars through resolved API asset URLs", async () => {
  const user = userEvent.setup();
  gameClientMocks.listPlayerProfiles.mockResolvedValue({
    profiles: [
      buildProfile({
        id: "profile-1",
        display_name: "阿青",
        avatar_asset_id: "system-gothic-male-1",
        avatar_image_url: "/player-avatars/gothic-male-1.png",
        avatar_image_mime: "image/png",
      }),
      buildProfile({ id: "profile-2", display_name: "白石" }),
    ],
  });
  renderGamesPage();

  await user.click(
    await screen.findByRole("button", {
      name: "选择 1 号座位，当前为 待选择",
    }),
  );

  const drawer = await screen.findByRole("dialog", { name: "玩家卡牌库" });
  const avatar = within(drawer).getAllByRole("img", { hidden: true })[0];
  expect(avatar).toHaveAttribute(
    "src",
    "/api/v1/player-profiles/avatar-assets/system-gothic-male-1",
  );
});
```

- [ ] **Step 2: Run mobile target tests and verify failure**

Run:

```bash
pnpm --dir apps/mobile-web test -- --run src/pages/PlayersPage.test.tsx src/pages/GamesPage.test.tsx
```

Expected: FAIL because components still render raw `avatar_image_url`.

- [ ] **Step 3: Use resolver in mobile pages**

Modify `apps/mobile-web/src/pages/PlayersPage.tsx` import:

```ts
import { listPlayerProfiles, resolveAvatarImageUrl } from "@werewolf-arena/game-client";
```

Inside the profile map:

```tsx
const avatarImageUrl = resolveAvatarImageUrl(profile);
```

Render:

```tsx
{avatarImageUrl ? (
  <img
    alt={`${profile.display_name} 头像`}
    className="mobile-player-avatar"
    src={avatarImageUrl}
  />
) : null}
```

Modify `apps/mobile-web/src/pages/GamesPage.tsx` import to include `resolveAvatarImageUrl`. In each profile/seat render block compute:

```tsx
const avatarImageUrl = profile ? resolveAvatarImageUrl(profile) : "";
```

Use `avatarImageUrl` for both seat avatar and drawer card avatar `src` checks.

Modify `apps/mobile-web/src/pages/LivePage.tsx` import and render:

```tsx
const avatarImageUrl = resolveAvatarImageUrl({
  avatar_image_url: player.avatarImageUrl,
});
```

Use that value for live seat avatars so old replay/live URLs are mapped.

- [ ] **Step 4: Run mobile target tests and verify pass**

Run:

```bash
pnpm --dir apps/mobile-web test -- --run src/pages/PlayersPage.test.tsx src/pages/GamesPage.test.tsx src/pages/LivePage.test.tsx
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/mobile-web/src/pages/PlayersPage.tsx apps/mobile-web/src/pages/GamesPage.tsx apps/mobile-web/src/pages/LivePage.tsx apps/mobile-web/src/pages/PlayersPage.test.tsx apps/mobile-web/src/pages/GamesPage.test.tsx apps/mobile-web/src/pages/LivePage.test.tsx
git commit -m "fix(mobile): resolve player avatar asset urls"
```

---

### Task 9: Desktop Web Editor And Avatar Rendering

**Files:**
- Modify: `apps/web/src/features/games/components/VirtualPlayerLibrary.tsx`
- Modify: `apps/web/src/features/games/components/VirtualPlayerEditor.tsx`
- Modify: `apps/web/src/features/games/components/VirtualPlayerPreview.tsx`
- Modify: `apps/web/src/features/games/components/VirtualPlayerCardGrid.tsx`
- Modify: `apps/web/src/features/games/components/ProfilePicker.tsx`
- Modify: `apps/web/src/features/games/components/SeatGrid.tsx`
- Modify: `apps/web/src/features/games/components/LiveDirectorStage.tsx`
- Modify: `apps/web/src/features/games/components/LiveNarrativeCenter.tsx`
- Modify: `apps/web/src/features/games/components/PlayerRosterPanel.tsx`
- Modify: `apps/web/src/features/games/components/VirtualPlayerLibrary.test.tsx`
- Modify other desktop tests that build `VirtualPlayerProfile`.

- [ ] **Step 1: Write failing desktop editor tests**

In `apps/web/src/features/games/components/VirtualPlayerLibrary.test.tsx`, add `avatar_asset_id: overrides.avatar_asset_id ?? null` to the `profile()` builder and include `avatar_asset_id` in upload mocks:

```ts
onUploadAvatar: vi.fn().mockResolvedValue({
  avatar_asset_id: "uploaded-dropped",
  avatar_image_url: "/api/v1/player-profiles/avatar-assets/uploaded-dropped",
  avatar_image_mime: "image/png",
}),
```

Update the existing random system avatar test expectations:

```tsx
expect(
  screen
    .getByTestId("virtual-player-avatar-dropzone")
    .querySelector("img"),
).toHaveAttribute(
  "src",
  "/api/v1/player-profiles/avatar-assets/system-gothic-male-1",
);

await waitFor(() =>
  expect(onCreateProfile).toHaveBeenCalledWith(
    expect.objectContaining({
      appearance_id: SYSTEM_PLAYER_AVATARS[0].id,
      avatar_asset_id: SYSTEM_PLAYER_AVATARS[0].assetId,
      avatar_image_mime: "image/png",
    }),
  ),
);
```

Update the explicit system avatar selection test:

```tsx
await waitFor(() =>
  expect(onCreateProfile).toHaveBeenCalledWith(
    expect.objectContaining({
      appearance_id: SYSTEM_PLAYER_AVATARS[2].id,
      avatar_asset_id: SYSTEM_PLAYER_AVATARS[2].assetId,
      avatar_image_mime: "image/png",
    }),
  ),
);
```

- [ ] **Step 2: Run desktop target test and verify failure**

Run:

```bash
pnpm --dir apps/web test -- --run src/features/games/components/VirtualPlayerLibrary.test.tsx
```

Expected: FAIL because the editor still uses `avatar.imageUrl` and saves raw URLs.

- [ ] **Step 3: Update desktop editor state and previews**

In `apps/web/src/features/games/components/VirtualPlayerLibrary.tsx`, import `resolveAvatarImageUrl` and use asset IDs:

```ts
function profileToDraft(profile: VirtualPlayerProfile): PlayerProfileRequest {
  return {
    ...defaultDraft(profile.model),
    display_name: profile.display_name,
    personality_id: profile.personality_id || "balanced",
    personality_text: profile.personality_text || "",
    short_description: profile.short_description || "",
    background_story: profile.background_story || "",
    speaking_style: profile.speaking_style || "",
    catchphrases: profile.catchphrases ?? [],
    strategy_profile: profile.strategy_profile || "balanced",
    risk_tolerance: profile.risk_tolerance ?? 3,
    bluffing_tendency: profile.bluffing_tendency ?? 3,
    trust_tendency: profile.trust_tendency ?? 3,
    leadership_tendency: profile.leadership_tendency ?? 3,
    talkativeness: profile.talkativeness ?? 3,
    example_messages: profile.example_messages ?? [],
    favorite: profile.favorite ?? false,
    appearance_id: profile.appearance_id || "default",
    avatar_prompt: profile.avatar_prompt || "",
    avatar_asset_id: profile.avatar_asset_id || "",
    avatar_image_url: profile.avatar_image_url || "",
    avatar_image_mime: profile.avatar_image_mime || "",
    tags: profile.tags ?? [],
  };
}
```

Change system avatar application:

```ts
  const applySystemAvatar = (avatar: SystemPlayerAvatar) => {
    setDraft((current) => ({
      ...current,
      appearance_id: avatar.id,
      avatar_asset_id: avatar.assetId,
      avatar_image_url: "",
      avatar_image_mime: avatar.mime,
    }));
  };
```

Change fresh draft creation:

```ts
          appearance_id: avatar.id,
          avatar_asset_id: avatar.assetId,
          avatar_image_url: "",
          avatar_image_mime: avatar.mime,
```

Change save request:

```ts
      avatar_asset_id: draft.avatar_asset_id?.trim() ?? "",
      avatar_prompt: draft.avatar_prompt?.trim() ?? "",
      avatar_image_url: draft.avatar_image_url?.trim() ?? "",
      avatar_image_mime: draft.avatar_image_mime?.trim() ?? "",
```

Change upload handler:

```ts
        avatar_asset_id: response.avatar_asset_id,
        avatar_image_url: response.avatar_image_url,
        avatar_image_mime: response.avatar_image_mime,
```

In `apps/web/src/features/games/components/VirtualPlayerEditor.tsx`, import `resolveAvatarImageUrl` and `systemPlayerAvatarImageUrl`. Use:

```tsx
const draftAvatarImageUrl = resolveAvatarImageUrl(draft);
```

Render preview from `draftAvatarImageUrl`. Use:

```tsx
const isSelected = draft.avatar_asset_id === avatar.assetId;
const avatarPreviewUrl = systemPlayerAvatarImageUrl(avatar);
```

for system avatar buttons.

In `VirtualPlayerPreview.tsx`, `VirtualPlayerCardGrid.tsx`, `ProfilePicker.tsx`, `SeatGrid.tsx`, `LiveDirectorStage.tsx`, `LiveNarrativeCenter.tsx`, and `PlayerRosterPanel.tsx`, compute a local `avatarImageUrl` with `resolveAvatarImageUrl` before rendering `<img>`.

- [ ] **Step 4: Update desktop profile builders**

For each desktop test builder that returns `VirtualPlayerProfile`, add:

```ts
avatar_asset_id: overrides.avatar_asset_id ?? null,
```

Files from the current search include:

- `apps/web/src/pages/PlayersPage.test.tsx`
- `apps/web/src/pages/GamesPage.test.tsx`
- `apps/web/src/features/games/components/VirtualPlayerLibrary.test.tsx`
- `apps/web/src/features/games/api/playerProfilesApi.test.ts`
- `apps/web/src/features/games/lineupUtils.test.ts`

- [ ] **Step 5: Run desktop target tests and verify pass**

Run:

```bash
pnpm --dir apps/web test -- --run src/features/games/components/VirtualPlayerLibrary.test.tsx src/pages/PlayersPage.test.tsx src/pages/GamesPage.test.tsx
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add apps/web/src/features/games/components apps/web/src/pages apps/web/src/features/games apps/web/src/features/games/api
git commit -m "fix(web): resolve avatar asset urls in player UI"
```

---

### Task 10: Full Verification, Documentation, And Cleanup

**Files:**
- Modify: `README.md`
- Modify: `docs/architecture.md`
- Verify: all changed backend/frontend files

- [ ] **Step 1: Update docs**

Modify `README.md` runtime data section to say avatar assets now live in PostgreSQL and add the new migration command:

```markdown
玩家头像资产现在也存储在 PostgreSQL。旧版本如果曾在 `WEREWOLF_LOGS_DIR/player_profile_assets` 写入上传头像文件，数据库迁移后执行：

```bash
cd apps/api
.venv/bin/python -m app.cli migrate-player-avatar-assets --logs-dir logs
```

该命令会把旧文件导入 `player_avatar_assets` 并回填玩家档案的 `avatar_asset_id`。
```

Modify `docs/architecture.md` runtime data ownership:

```markdown
- PostgreSQL is the runtime source for virtual player profiles and player avatar image assets.
- Legacy `player_profiles.json` files and `WEREWOLF_LOGS_DIR/player_profile_assets` files are migration inputs only.
```

- [ ] **Step 2: Run backend tests**

Run:

```bash
cd apps/api && uv run pytest
```

Expected: PASS.

- [ ] **Step 3: Run backend lint**

Run:

```bash
cd apps/api && uv run ruff check .
```

Expected: PASS.

- [ ] **Step 4: Run game-client tests and typecheck**

Run:

```bash
pnpm --dir packages/game-client test -- --run
pnpm --dir packages/game-client typecheck
```

Expected: PASS.

- [ ] **Step 5: Run mobile tests and build**

Run:

```bash
pnpm --dir apps/mobile-web test -- --run
pnpm --dir apps/mobile-web build
```

Expected: PASS.

- [ ] **Step 6: Run desktop tests and build**

Run:

```bash
pnpm --dir apps/web test -- --run
pnpm --dir apps/web build
```

Expected: PASS.

- [ ] **Step 7: Search for stale static avatar paths**

Run:

```bash
rg -n "/player-avatars|avatar\\.imageUrl|profile\\.avatar_image_url|src=\\{profile\\.avatar_image_url\\}" apps/mobile-web/src apps/web/src packages/game-client/src
```

Expected: any remaining `/player-avatars` references are inside compatibility tests or `avatarImageUrl.ts`; no UI component should render `profile.avatar_image_url` directly.

- [ ] **Step 8: Commit docs and cleanup**

```bash
git add README.md docs/architecture.md
git commit -m "docs: document database-backed avatar assets"
```
