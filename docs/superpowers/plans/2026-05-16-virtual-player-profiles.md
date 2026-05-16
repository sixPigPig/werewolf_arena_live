# Virtual Player Profiles Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a reusable virtual player profile library, let game creation assign saved profiles to seats, and freeze those profile values into each game run.

**Architecture:** Add a persistent `virtual_player_profiles` table and CRUD API, then keep game runtime independent by converting selected profiles into immutable `player_configs` snapshots before the game engine starts. The engine, checkpoint, live events, replay adapters, and UI all consume the frozen player fields so later profile edits never change historical games.

**Tech Stack:** FastAPI, Pydantic v2, SQLAlchemy ORM, Alembic, pytest, React 19, React Router, TanStack Query, Vitest, Testing Library, existing CSS/Tailwind utility conventions.

---

## File Structure

Backend persistence and profile API:

- Create `apps/api/app/models/virtual_player_profile.py`: SQLAlchemy model for saved profiles.
- Modify `apps/api/app/models/__init__.py`: register `VirtualPlayerProfile` with Alembic metadata.
- Create `apps/api/alembic/versions/20260516_01_create_virtual_player_profiles.py`: DB migration.
- Create `apps/api/app/werewolf/player_presets.py`: personality and appearance preset registry.
- Create `apps/api/app/api/routes/player_profiles.py`: CRUD API and request/response schemas.
- Modify `apps/api/app/api/router.py`: include `/player-profiles`.
- Modify `apps/api/tests/test_models.py`: table registration and schema assertions.
- Create `apps/api/tests/test_player_profiles_api.py`: CRUD and validation coverage.

Backend game runtime:

- Create `apps/api/app/werewolf/player_configs.py`: dataclass, request normalization, profile snapshot merge logic.
- Modify `apps/api/app/werewolf/models.py`: persist profile/personality/appearance fields on `Player`.
- Modify `apps/api/app/werewolf/checkpoint.py`: restore new player fields with defaults for legacy saves.
- Modify `apps/api/app/werewolf/engine.py`: accept `player_configs`, assign profiles by seat, include personality in `_world_state()`.
- Modify `apps/api/app/werewolf/runner.py`: pass configs into initialization and checkpoint `run_params`.
- Modify `apps/api/app/werewolf/live.py`: store and publish run-level `player_configs`.
- Modify `apps/api/app/api/routes/games.py`: accept player config payloads, resolve profile IDs through DB, pass snapshots to registry/background worker.
- Modify `apps/api/tests/test_werewolf_runner.py`: engine/runtime/checkpoint behavior.
- Modify `apps/api/tests/test_games_api.py`: create-run profile normalization and validation.

Frontend API and state:

- Modify `apps/web/src/features/games/types.ts`: add profile/config fields to API and live/replay types.
- Create `apps/web/src/features/games/playerProfileOptions.ts`: shared personality/appearance labels and CSS class mapping.
- Create `apps/web/src/features/games/api/listPlayerProfiles.ts`.
- Create `apps/web/src/features/games/api/createPlayerProfile.ts`.
- Create `apps/web/src/features/games/api/updatePlayerProfile.ts`.
- Create `apps/web/src/features/games/api/deletePlayerProfile.ts`.
- Modify `apps/web/src/features/games/api/createGameRun.ts`: type coverage only; behavior already JSON serializes full request.
- Modify `apps/web/src/features/games/api/liveRunApi.test.ts`: game run payload includes `player_configs`.
- Create `apps/web/src/features/games/api/playerProfilesApi.test.ts`: profile CRUD requests.
- Modify `apps/web/src/features/games/liveSpectator.ts`: parse new fields from `game_started`.
- Modify `apps/web/src/features/games/api/adapters.ts`: preserve replay player fields and defaults.

Frontend UI:

- Create `apps/web/src/features/games/components/VirtualPlayerLibrary.tsx`: compact saved-profile management module.
- Create `apps/web/src/features/games/components/PlayerConfigPanel.tsx`: seat-to-profile selector and per-run overrides.
- Modify `apps/web/src/features/games/components/CreateGameRunForm.tsx`: load profiles, render player config panel, submit `player_configs`.
- Modify `apps/web/src/pages/components/GamesWorkspace.tsx`: keep create form and profile library in one workspace.
- Modify `apps/web/src/features/games/components/PlayerRosterPanel.tsx`: replay profile labels and appearance skin.
- Modify `apps/web/src/features/games/components/LiveDirectorStage.tsx`: live seat appearance skin.
- Modify `apps/web/src/features/games/components/LivePlayerPanel.tsx`: focused player personality/model display.
- Modify `apps/web/src/styles/index.css`: lobby profile library, seat config panel, appearance swatches.
- Modify `apps/web/src/pages/GamesPage.test.tsx`: profile fetches, library, seat controls, submit payload.
- Modify `apps/web/src/features/games/liveSpectator.test.ts`: new live player fields.

---

### Task 1: Backend Profile Persistence And Presets

**Files:**
- Create: `apps/api/app/werewolf/player_presets.py`
- Create: `apps/api/app/models/virtual_player_profile.py`
- Create: `apps/api/alembic/versions/20260516_01_create_virtual_player_profiles.py`
- Modify: `apps/api/app/models/__init__.py`
- Modify: `apps/api/tests/test_models.py`

- [ ] **Step 1: Write the failing metadata tests**

Append these tests to `apps/api/tests/test_models.py`:

```python
from app.models.virtual_player_profile import VirtualPlayerProfile


def test_virtual_player_profile_table_is_registered_in_metadata() -> None:
    assert VirtualPlayerProfile.__table__.name == "virtual_player_profiles"
    assert "virtual_player_profiles" in Base.metadata.tables


def test_virtual_player_profile_table_matches_expected_schema() -> None:
    table = VirtualPlayerProfile.__table__
    column_names = set(table.columns.keys())

    assert column_names == {
        "id",
        "owner_user_id",
        "display_name",
        "model",
        "personality_id",
        "personality_text",
        "appearance_id",
        "avatar_prompt",
        "tags",
        "created_at",
        "updated_at",
    }
    assert table.c.id.primary_key is True
    assert table.c.owner_user_id.foreign_keys
    assert table.c.owner_user_id.index is True
    assert table.c.display_name.nullable is False
    assert table.c.model.nullable is False
    assert table.c.personality_id.nullable is False
    assert table.c.appearance_id.nullable is False
    assert table.c.tags.nullable is False
    assert table.c.created_at.server_default is not None
    assert table.c.updated_at.server_default is not None
```

- [ ] **Step 2: Run metadata tests to verify failure**

Run:

```bash
cd apps/api && uv run pytest tests/test_models.py -v
```

Expected: fail with `ModuleNotFoundError: No module named 'app.models.virtual_player_profile'`.

- [ ] **Step 3: Create preset registry**

Create `apps/api/app/werewolf/player_presets.py`:

```python
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PlayerPreset:
    id: str
    label: str
    description: str


PERSONALITY_PRESETS: dict[str, PlayerPreset] = {
    "balanced": PlayerPreset(
        id="balanced",
        label="均衡",
        description="稳健、根据证据推进，不轻易极端站边。",
    ),
    "aggressive": PlayerPreset(
        id="aggressive",
        label="进攻",
        description="进攻性强，主动施压、抓矛盾、推动投票。",
    ),
    "cautious": PlayerPreset(
        id="cautious",
        label="谨慎",
        description="谨慎保守，优先收集信息，避免过早暴露关键判断。",
    ),
    "deceptive": PlayerPreset(
        id="deceptive",
        label="欺骗",
        description="善于混淆视听，适合狼人策略，但不改变阵营目标。",
    ),
    "analytical": PlayerPreset(
        id="analytical",
        label="分析",
        description="重视票型、发言顺序和行为一致性。",
    ),
}

APPEARANCE_PRESETS: dict[str, PlayerPreset] = {
    "default": PlayerPreset(
        id="default",
        label="默认",
        description="当前按名字生成头像的兼容样式。",
    ),
    "crimson": PlayerPreset(
        id="crimson",
        label="绯红",
        description="深红阵营感形象。",
    ),
    "moonlit": PlayerPreset(
        id="moonlit",
        label="冷月",
        description="冷月银蓝形象。",
    ),
    "ember": PlayerPreset(
        id="ember",
        label="余烬",
        description="琥珀火光形象。",
    ),
    "verdant": PlayerPreset(
        id="verdant",
        label="幽林",
        description="暗绿色森林形象。",
    ),
}


def default_personality_text(personality_id: str) -> str:
    return PERSONALITY_PRESETS[personality_id].description


def is_valid_personality(personality_id: str) -> bool:
    return personality_id in PERSONALITY_PRESETS


def is_valid_appearance(appearance_id: str) -> bool:
    return appearance_id in APPEARANCE_PRESETS
```

- [ ] **Step 4: Create SQLAlchemy model**

Create `apps/api/app/models/virtual_player_profile.py`:

```python
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, JSON, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class VirtualPlayerProfile(Base):
    __tablename__ = "virtual_player_profiles"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    owner_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"),
        nullable=True,
        index=True,
    )
    display_name: Mapped[str] = mapped_column(String(80), nullable=False)
    model: Mapped[str] = mapped_column(String(120), nullable=False)
    personality_id: Mapped[str] = mapped_column(
        String(40),
        nullable=False,
        default="balanced",
    )
    personality_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    appearance_id: Mapped[str] = mapped_column(
        String(40),
        nullable=False,
        default="default",
    )
    avatar_prompt: Mapped[str] = mapped_column(Text, nullable=False, default="")
    tags: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
```

- [ ] **Step 5: Register model exports**

Replace `apps/api/app/models/__init__.py` with:

```python
from app.models.user import User
from app.models.virtual_player_profile import VirtualPlayerProfile

__all__ = ["User", "VirtualPlayerProfile"]
```

- [ ] **Step 6: Add Alembic migration**

Create `apps/api/alembic/versions/20260516_01_create_virtual_player_profiles.py`:

```python
from alembic import op
import sqlalchemy as sa


revision = "20260516_01"
down_revision = "20260422_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "virtual_player_profiles",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("owner_user_id", sa.Integer(), nullable=True),
        sa.Column("display_name", sa.String(length=80), nullable=False),
        sa.Column("model", sa.String(length=120), nullable=False),
        sa.Column(
            "personality_id",
            sa.String(length=40),
            nullable=False,
            server_default="balanced",
        ),
        sa.Column("personality_text", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "appearance_id",
            sa.String(length=40),
            nullable=False,
            server_default="default",
        ),
        sa.Column("avatar_prompt", sa.Text(), nullable=False, server_default=""),
        sa.Column("tags", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(["owner_user_id"], ["users.id"]),
    )
    op.create_index(
        "ix_virtual_player_profiles_owner_user_id",
        "virtual_player_profiles",
        ["owner_user_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_virtual_player_profiles_owner_user_id",
        table_name="virtual_player_profiles",
    )
    op.drop_table("virtual_player_profiles")
```

- [ ] **Step 7: Run metadata tests to verify pass**

Run:

```bash
cd apps/api && uv run pytest tests/test_models.py -v
```

Expected: all tests in `test_models.py` pass.

- [ ] **Step 8: Commit persistence foundation**

Run:

```bash
git add apps/api/app/werewolf/player_presets.py apps/api/app/models/virtual_player_profile.py apps/api/app/models/__init__.py apps/api/alembic/versions/20260516_01_create_virtual_player_profiles.py apps/api/tests/test_models.py
git commit -m "feat(api): add virtual player profile model"
```

---

### Task 2: Backend Virtual Player Profile CRUD API

**Files:**
- Create: `apps/api/app/api/routes/player_profiles.py`
- Modify: `apps/api/app/api/router.py`
- Create: `apps/api/tests/test_player_profiles_api.py`

- [ ] **Step 1: Write API tests with isolated SQLite DB**

Create `apps/api/tests/test_player_profiles_api.py`:

```python
from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models import User, VirtualPlayerProfile


client = TestClient(app)


@pytest.fixture
def db_session() -> Generator[Session, None, None]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(bind=engine)
    session = TestingSessionLocal()
    app.dependency_overrides[get_db] = lambda: session
    try:
        yield session
    finally:
        app.dependency_overrides.clear()
        session.close()
        Base.metadata.drop_all(bind=engine)


def test_create_profile_persists_normalized_payload(db_session: Session) -> None:
    response = client.post(
        "/api/v1/player-profiles",
        json={
            "display_name": " 冷静的阿夜 ",
            "model": " MiniMax-M2.7 ",
            "personality_id": "cautious",
            "personality_text": "",
            "appearance_id": "moonlit",
            "avatar_prompt": " 银发、冷静、观察型玩家 ",
            "tags": ["控场", "慢热", "控场"],
        },
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["id"]
    assert payload["owner_user_id"] is None
    assert payload["display_name"] == "冷静的阿夜"
    assert payload["model"] == "MiniMax-M2.7"
    assert payload["personality_id"] == "cautious"
    assert payload["personality_text"] == "谨慎保守，优先收集信息，避免过早暴露关键判断。"
    assert payload["appearance_id"] == "moonlit"
    assert payload["avatar_prompt"] == "银发、冷静、观察型玩家"
    assert payload["tags"] == ["控场", "慢热"]
    assert db_session.query(VirtualPlayerProfile).count() == 1


def test_list_profiles_returns_updated_first(db_session: Session) -> None:
    first = client.post(
        "/api/v1/player-profiles",
        json={"display_name": "A", "model": "deepseek-v4-flash"},
    ).json()
    client.post(
        "/api/v1/player-profiles",
        json={"display_name": "B", "model": "MiniMax-M2.7"},
    ).json()
    client.patch(
        f"/api/v1/player-profiles/{first['id']}",
        json={"display_name": "A updated"},
    )

    response = client.get("/api/v1/player-profiles")

    assert response.status_code == 200
    payload = response.json()
    assert payload["profiles"][0]["id"] == first["id"]
    assert payload["profiles"][0]["display_name"] == "A updated"


def test_get_update_and_delete_profile(db_session: Session) -> None:
    created = client.post(
        "/api/v1/player-profiles",
        json={"display_name": "影子", "model": "deepseek-v4-flash"},
    ).json()

    patch_response = client.patch(
        f"/api/v1/player-profiles/{created['id']}",
        json={
            "display_name": "影子二号",
            "personality_id": "aggressive",
            "appearance_id": "crimson",
            "tags": ["进攻"],
        },
    )

    assert patch_response.status_code == 200
    assert patch_response.json()["display_name"] == "影子二号"
    assert patch_response.json()["personality_text"] == "进攻性强，主动施压、抓矛盾、推动投票。"

    get_response = client.get(f"/api/v1/player-profiles/{created['id']}")
    assert get_response.status_code == 200
    assert get_response.json()["appearance_id"] == "crimson"

    delete_response = client.delete(f"/api/v1/player-profiles/{created['id']}")
    assert delete_response.status_code == 204
    assert client.get(f"/api/v1/player-profiles/{created['id']}").status_code == 404


@pytest.mark.parametrize(
    "payload, expected_fragment",
    [
        ({"display_name": "", "model": "deepseek-v4-flash"}, "display_name"),
        ({"display_name": "玩家", "model": ""}, "model"),
        ({"display_name": "玩家", "model": "deepseek-v4-flash", "personality_id": "wild"}, "Unknown personality_id"),
        ({"display_name": "玩家", "model": "deepseek-v4-flash", "appearance_id": "ghost"}, "Unknown appearance_id"),
        ({"display_name": "玩家", "model": "deepseek-v4-flash", "avatar_prompt": "x" * 501}, "avatar_prompt"),
        ({"display_name": "玩家", "model": "deepseek-v4-flash", "tags": ["x"] * 9}, "tags"),
    ],
)
def test_profile_validation_errors(
    db_session: Session,
    payload: dict[str, object],
    expected_fragment: str,
) -> None:
    response = client.post("/api/v1/player-profiles", json=payload)

    assert response.status_code == 422
    assert expected_fragment in str(response.json()["detail"])
```

- [ ] **Step 2: Run profile API tests to verify failure**

Run:

```bash
cd apps/api && uv run pytest tests/test_player_profiles_api.py -v
```

Expected: fail with `404 Not Found` for `/api/v1/player-profiles`.

- [ ] **Step 3: Create profile route**

Create `apps/api/app/api/routes/player_profiles.py`:

```python
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.virtual_player_profile import VirtualPlayerProfile
from app.werewolf.player_presets import (
    default_personality_text,
    is_valid_appearance,
    is_valid_personality,
)

router = APIRouter()


class PlayerProfileBase(BaseModel):
    display_name: str | None = None
    model: str | None = None
    personality_id: str | None = None
    personality_text: str | None = None
    appearance_id: str | None = None
    avatar_prompt: str | None = None
    tags: list[str] | None = None

    @field_validator("display_name", "model", "personality_text", "avatar_prompt", mode="before")
    @classmethod
    def trim_strings(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value

    @field_validator("tags", mode="before")
    @classmethod
    def normalize_tags(cls, value: object) -> object:
        if value is None:
            return None
        if not isinstance(value, list):
            return value
        normalized: list[str] = []
        for item in value:
            if not isinstance(item, str):
                continue
            tag = item.strip()
            if tag and tag not in normalized:
                normalized.append(tag)
        return normalized


class CreatePlayerProfileRequest(PlayerProfileBase):
    display_name: str = Field(min_length=1, max_length=80)
    model: str = Field(min_length=1, max_length=120)
    personality_id: str = "balanced"
    personality_text: str = ""
    appearance_id: str = "default"
    avatar_prompt: str = Field(default="", max_length=500)
    tags: list[str] = Field(default_factory=list, max_length=8)


class UpdatePlayerProfileRequest(PlayerProfileBase):
    display_name: str | None = Field(default=None, min_length=1, max_length=80)
    model: str | None = Field(default=None, min_length=1, max_length=120)
    avatar_prompt: str | None = Field(default=None, max_length=500)
    tags: list[str] | None = Field(default=None, max_length=8)


class PlayerProfileResponse(BaseModel):
    id: str
    owner_user_id: int | None
    display_name: str
    model: str
    personality_id: str
    personality_text: str
    appearance_id: str
    avatar_prompt: str
    tags: list[str]
    created_at: datetime
    updated_at: datetime


class PlayerProfileListResponse(BaseModel):
    profiles: list[PlayerProfileResponse]


@router.get("", response_model=PlayerProfileListResponse)
def list_player_profiles(
    db: Annotated[Session, Depends(get_db)],
) -> PlayerProfileListResponse:
    profiles = (
        db.query(VirtualPlayerProfile)
        .order_by(VirtualPlayerProfile.updated_at.desc(), VirtualPlayerProfile.id.desc())
        .all()
    )
    return PlayerProfileListResponse(profiles=[profile_to_response(profile) for profile in profiles])


@router.post("", response_model=PlayerProfileResponse, status_code=201)
def create_player_profile(
    request: CreatePlayerProfileRequest,
    db: Annotated[Session, Depends(get_db)],
) -> PlayerProfileResponse:
    validate_profile_payload(
        personality_id=request.personality_id,
        appearance_id=request.appearance_id,
        tags=request.tags,
    )
    profile = VirtualPlayerProfile(
        id=str(uuid.uuid4()),
        owner_user_id=None,
        display_name=request.display_name,
        model=request.model,
        personality_id=request.personality_id,
        personality_text=request.personality_text
        or default_personality_text(request.personality_id),
        appearance_id=request.appearance_id,
        avatar_prompt=request.avatar_prompt,
        tags=request.tags,
    )
    db.add(profile)
    db.commit()
    db.refresh(profile)
    return profile_to_response(profile)


@router.get("/{profile_id}", response_model=PlayerProfileResponse)
def get_player_profile(
    profile_id: str,
    db: Annotated[Session, Depends(get_db)],
) -> PlayerProfileResponse:
    return profile_to_response(require_profile(db, profile_id))


@router.patch("/{profile_id}", response_model=PlayerProfileResponse)
def update_player_profile(
    profile_id: str,
    request: UpdatePlayerProfileRequest,
    db: Annotated[Session, Depends(get_db)],
) -> PlayerProfileResponse:
    profile = require_profile(db, profile_id)
    updates = request.model_dump(exclude_unset=True)
    personality_id = str(updates.get("personality_id") or profile.personality_id)
    appearance_id = str(updates.get("appearance_id") or profile.appearance_id)
    tags = updates.get("tags", profile.tags)
    validate_profile_payload(
        personality_id=personality_id,
        appearance_id=appearance_id,
        tags=tags if isinstance(tags, list) else [],
    )
    for key, value in updates.items():
        setattr(profile, key, value)
    if "personality_id" in updates and not updates.get("personality_text"):
        profile.personality_text = default_personality_text(profile.personality_id)
    db.commit()
    db.refresh(profile)
    return profile_to_response(profile)


@router.delete("/{profile_id}", status_code=204)
def delete_player_profile(
    profile_id: str,
    db: Annotated[Session, Depends(get_db)],
) -> Response:
    profile = require_profile(db, profile_id)
    db.delete(profile)
    db.commit()
    return Response(status_code=204)


def require_profile(db: Session, profile_id: str) -> VirtualPlayerProfile:
    profile = db.get(VirtualPlayerProfile, profile_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="Player profile not found")
    return profile


def validate_profile_payload(
    *,
    personality_id: str,
    appearance_id: str,
    tags: list[str],
) -> None:
    if not is_valid_personality(personality_id):
        raise HTTPException(status_code=422, detail=f"Unknown personality_id: {personality_id}")
    if not is_valid_appearance(appearance_id):
        raise HTTPException(status_code=422, detail=f"Unknown appearance_id: {appearance_id}")
    if len(tags) > 8:
        raise HTTPException(status_code=422, detail="tags must contain at most 8 values")
    long_tags = [tag for tag in tags if len(tag) > 20]
    if long_tags:
        raise HTTPException(status_code=422, detail="tags must be 20 characters or fewer")


def profile_to_response(profile: VirtualPlayerProfile) -> PlayerProfileResponse:
    return PlayerProfileResponse(
        id=profile.id,
        owner_user_id=profile.owner_user_id,
        display_name=profile.display_name,
        model=profile.model,
        personality_id=profile.personality_id,
        personality_text=profile.personality_text,
        appearance_id=profile.appearance_id,
        avatar_prompt=profile.avatar_prompt,
        tags=list(profile.tags or []),
        created_at=profile.created_at,
        updated_at=profile.updated_at,
    )
```

- [ ] **Step 4: Register route**

Modify `apps/api/app/api/router.py` to:

```python
from fastapi import APIRouter

from app.api.routes.games import router as games_router
from app.api.routes.health import router as health_router
from app.api.routes.player_profiles import router as player_profiles_router


api_router = APIRouter()
api_router.include_router(games_router, prefix="/games", tags=["games"])
api_router.include_router(health_router, prefix="/health", tags=["health"])
api_router.include_router(
    player_profiles_router,
    prefix="/player-profiles",
    tags=["player-profiles"],
)
```

- [ ] **Step 5: Run profile API tests**

Run:

```bash
cd apps/api && uv run pytest tests/test_player_profiles_api.py -v
```

Expected: all profile API tests pass.

- [ ] **Step 6: Run related API tests**

Run:

```bash
cd apps/api && uv run pytest tests/test_models.py tests/test_player_profiles_api.py tests/test_games_api.py -v
```

Expected: all selected tests pass.

- [ ] **Step 7: Commit profile API**

Run:

```bash
git add apps/api/app/api/routes/player_profiles.py apps/api/app/api/router.py apps/api/tests/test_player_profiles_api.py
git commit -m "feat(api): add virtual player profile api"
```

---

### Task 3: Backend Runtime Player Config Snapshots

**Files:**
- Create: `apps/api/app/werewolf/player_configs.py`
- Modify: `apps/api/app/werewolf/models.py`
- Modify: `apps/api/app/werewolf/checkpoint.py`
- Modify: `apps/api/app/werewolf/engine.py`
- Modify: `apps/api/app/werewolf/runner.py`
- Modify: `apps/api/app/werewolf/live.py`
- Modify: `apps/api/app/api/routes/games.py`
- Modify: `apps/api/tests/test_werewolf_runner.py`
- Modify: `apps/api/tests/test_games_api.py`

- [ ] **Step 1: Write runner tests for player config assignment**

Append to `apps/api/tests/test_werewolf_runner.py`:

```python
from app.werewolf.player_configs import PlayerConfig


def test_initialize_game_state_applies_player_config_snapshot() -> None:
    rule_set = get_rule_set("starter_6")

    state = initialize_game_state(
        session_id="session_20260516_000000_profiles",
        villager_model="villager-model",
        werewolf_model="wolf-model",
        seed=12,
        rule_set=rule_set,
        player_configs=[
            PlayerConfig(
                seat=1,
                profile_id="profile-1",
                name="冷静的阿夜",
                model="MiniMax-M2.7",
                personality_id="cautious",
                personality="谨慎保守。",
                appearance_id="moonlit",
                avatar_prompt="银发观察者",
                tags=("控场",),
            )
        ],
    )

    first_player = state.players[0]
    assert first_player.name == "冷静的阿夜"
    assert first_player.model == "MiniMax-M2.7"
    assert first_player.profile_id == "profile-1"
    assert first_player.personality_id == "cautious"
    assert first_player.personality == "谨慎保守。"
    assert first_player.appearance_id == "moonlit"
    assert first_player.avatar_prompt == "银发观察者"
    assert first_player.tags == ["控场"]


def test_player_config_without_model_falls_back_to_role_model() -> None:
    rule_set = get_rule_set("starter_6")

    state = initialize_game_state(
        session_id="session_20260516_000001_profiles",
        villager_model="villager-model",
        werewolf_model="wolf-model",
        seed=12,
        rule_set=rule_set,
        player_configs=[PlayerConfig(seat=1, name="无模型玩家")],
    )

    first_player = state.players[0]
    role_spec = next(role for role in rule_set.roles if role.role == first_player.role)
    expected_model = "wolf-model" if role_spec.model_group == MODEL_GROUP_WEREWOLF else "villager-model"
    assert first_player.model == expected_model


def test_world_state_includes_player_personality() -> None:
    rule_set = get_rule_set("starter_6")
    state = initialize_game_state(
        session_id="session_20260516_000002_profiles",
        villager_model="villager-model",
        werewolf_model="wolf-model",
        seed=12,
        rule_set=rule_set,
        player_configs=[PlayerConfig(seat=1, name="分析师", personality="重视票型。")],
    )
    engine = GameEngine(
        state=state,
        provider=ScriptedChineseProvider(),
        max_rounds=1,
        rule_set=rule_set,
    )
    round_state = RoundState(number=1, players=[player.name for player in state.players])

    world_state = engine._world_state(state.players[0], [], round_state)

    assert world_state["personality"] == "重视票型。"


def test_player_from_dict_defaults_legacy_profile_fields() -> None:
    player = player_from_dict(
        {
            "name": "张三",
            "role": "狼人",
            "model": "deepseek-chat",
            "observations": [],
            "gamestate": None,
        }
    )

    assert player.personality_id == "balanced"
    assert player.personality == ""
    assert player.appearance_id == "default"
    assert player.avatar_prompt == ""
    assert player.profile_id is None
    assert player.tags == []
```

If `MODEL_GROUP_WEREWOLF` or `player_from_dict` are not imported at the top of `test_werewolf_runner.py`, add `MODEL_GROUP_WEREWOLF` from `app.werewolf.rules` and `player_from_dict` from `app.werewolf.checkpoint`.

- [ ] **Step 2: Write create-run API tests for snapshot normalization**

Append to `apps/api/tests/test_games_api.py`:

```python
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.session import get_db
from app.models import VirtualPlayerProfile


@pytest.fixture
def db_session() -> Iterator[Session]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(bind=engine)
    session = TestingSessionLocal()
    app.dependency_overrides[get_db] = lambda: session
    try:
        yield session
    finally:
        app.dependency_overrides.pop(get_db, None)
        session.close()
        Base.metadata.drop_all(bind=engine)


def test_create_game_run_resolves_profile_configs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    db_session: Session,
) -> None:
    profile = VirtualPlayerProfile(
        id="profile-1",
        display_name="冷静的阿夜",
        model="MiniMax-M2.7",
        personality_id="cautious",
        personality_text="谨慎保守。",
        appearance_id="moonlit",
        avatar_prompt="银发观察者",
        tags=["控场"],
    )
    db_session.add(profile)
    db_session.commit()
    registry = LiveRunRegistry()
    override_logs_root(tmp_path)
    override_live_registry(registry)
    captured: list[dict[str, object]] = []

    def fake_background_run(**kwargs: object) -> None:
        captured.append(kwargs)

    monkeypatch.setattr("app.api.routes.games._run_game_in_background", fake_background_run)
    monkeypatch.setattr("app.api.routes.games.threading.Thread", ImmediateThread)

    try:
        response = client.post(
            "/api/v1/games/runs",
            json={
                "rule_set_id": "starter_6",
                "seed": 21,
                "max_rounds": 1,
                "player_configs": [
                    {"seat": 1, "profile_id": "profile-1", "model": "qwen3.6-plus"}
                ],
            },
        )
    finally:
        clear_overrides()

    assert response.status_code == 201
    snapshot = response.json()["player_configs"][0]
    assert snapshot["seat"] == 1
    assert snapshot["profile_id"] == "profile-1"
    assert snapshot["name"] == "冷静的阿夜"
    assert snapshot["model"] == "qwen3.6-plus"
    assert snapshot["personality"] == "谨慎保守。"
    assert captured[0]["player_configs"][0]["profile_id"] == "profile-1"


def test_create_game_run_rejects_missing_profile(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    db_session: Session,
) -> None:
    registry = LiveRunRegistry()
    override_logs_root(tmp_path)
    override_live_registry(registry)
    monkeypatch.setattr("app.api.routes.games.threading.Thread", ImmediateThread)

    try:
        response = client.post(
            "/api/v1/games/runs",
            json={
                "rule_set_id": "starter_6",
                "player_configs": [{"seat": 1, "profile_id": "missing"}],
            },
        )
    finally:
        clear_overrides()

    assert response.status_code == 422
    assert response.json()["detail"] == "Unknown player profile: missing"
```

If `Iterator` is not already imported in `test_games_api.py`, import it from `typing`.

- [ ] **Step 3: Run runtime/API tests to verify failure**

Run:

```bash
cd apps/api && uv run pytest tests/test_werewolf_runner.py::test_initialize_game_state_applies_player_config_snapshot tests/test_games_api.py::test_create_game_run_resolves_profile_configs -v
```

Expected: fail because `PlayerConfig` and `player_configs` support do not exist yet.

- [ ] **Step 4: Create runtime player config module**

Create `apps/api/app/werewolf/player_configs.py`:

```python
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from app.models.virtual_player_profile import VirtualPlayerProfile
from app.werewolf.player_presets import default_personality_text


@dataclass(frozen=True)
class PlayerConfig:
    seat: int
    profile_id: str | None = None
    name: str | None = None
    model: str | None = None
    personality_id: str = "balanced"
    personality: str = ""
    appearance_id: str = "default"
    avatar_prompt: str = ""
    tags: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["tags"] = list(self.tags)
        return data


def player_config_from_profile(
    *,
    seat: int,
    profile: VirtualPlayerProfile | None,
    overrides: dict[str, Any],
) -> PlayerConfig:
    profile_id = str(overrides.get("profile_id") or profile.id) if profile else overrides.get("profile_id")
    personality_id = str(
        overrides.get("personality_id")
        or (profile.personality_id if profile else "balanced")
    )
    personality = str(
        overrides.get("personality")
        or overrides.get("personality_text")
        or (profile.personality_text if profile else "")
        or default_personality_text(personality_id)
    )
    tags_value = overrides.get("tags")
    if tags_value is None and profile is not None:
        tags_value = profile.tags
    tags = tuple(str(tag) for tag in tags_value or [])
    return PlayerConfig(
        seat=seat,
        profile_id=str(profile_id) if profile_id else None,
        name=clean_optional_string(
            overrides.get("name")
            or overrides.get("display_name")
            or (profile.display_name if profile else None)
        ),
        model=clean_optional_string(overrides.get("model") or (profile.model if profile else None)),
        personality_id=personality_id,
        personality=personality,
        appearance_id=str(
            overrides.get("appearance_id")
            or (profile.appearance_id if profile else "default")
        ),
        avatar_prompt=str(
            overrides.get("avatar_prompt")
            or (profile.avatar_prompt if profile else "")
        ),
        tags=tags,
    )


def clean_optional_string(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
```

- [ ] **Step 5: Extend Player serialization**

In `apps/api/app/werewolf/models.py`, add fields to `Player` after `model`:

```python
    personality_id: str = "balanced"
    personality: str = ""
    appearance_id: str = "default"
    avatar_prompt: str = ""
    profile_id: str | None = None
    tags: list[str] = field(default_factory=list)
```

In `Player.to_dict()`, add:

```python
            "personality_id": self.personality_id,
            "personality": self.personality,
            "appearance_id": self.appearance_id,
            "avatar_prompt": self.avatar_prompt,
            "profile_id": self.profile_id,
            "tags": self.tags,
```

- [ ] **Step 6: Restore new fields from checkpoint**

In `apps/api/app/werewolf/checkpoint.py`, update `player_from_dict()` with these keyword arguments:

```python
        personality_id=str(data.get("personality_id") or "balanced"),
        personality=str(data.get("personality") or ""),
        appearance_id=str(data.get("appearance_id") or "default"),
        avatar_prompt=str(data.get("avatar_prompt") or ""),
        profile_id=str(data["profile_id"]) if data.get("profile_id") else None,
        tags=[str(item) for item in data.get("tags", [])],
```

- [ ] **Step 7: Apply configs in game initialization**

In `apps/api/app/werewolf/engine.py`, import `PlayerConfig`:

```python
from app.werewolf.player_configs import PlayerConfig
```

Change `initialize_game_state()` signature to include:

```python
    player_configs: list[PlayerConfig] | None = None,
```

Before the player loop, add:

```python
    configs_by_seat = {config.seat: config for config in player_configs or []}
```

Inside the player loop, enumerate seats and apply the snapshot:

```python
    for seat_number, (player_name, role_spec) in enumerate(
        zip(player_names, role_cards, strict=True),
        start=1,
    ):
        config = configs_by_seat.get(seat_number)
        fallback_model = (
            werewolf_model
            if role_spec.model_group == MODEL_GROUP_WEREWOLF
            else villager_model
        )
        model = config.model if config and config.model else fallback_model
        name = config.name if config and config.name else player_name
        player = Player(
            name,
            role_spec.role,
            model,
            personality_id=config.personality_id if config else "balanced",
            personality=config.personality if config else "",
            appearance_id=config.appearance_id if config else "default",
            avatar_prompt=config.avatar_prompt if config else "",
            profile_id=config.profile_id if config else None,
            tags=list(config.tags) if config else [],
        )
```

In `_world_state()`, change:

```python
            "personality": "",
```

to:

```python
            "personality": player.personality,
```

- [ ] **Step 8: Thread configs through runner and live registry**

In `apps/api/app/werewolf/runner.py`, import `PlayerConfig` and add `player_configs: list[PlayerConfig] | None = None` to `run_game()`. Add this to `run_params`:

```python
        "player_configs": [
            config.to_dict() for config in player_configs or []
        ],
```

Pass `player_configs=player_configs` to `initialize_game_state()`.

In `apps/api/app/werewolf/live.py`, import `PlayerConfig`, add this field to `LiveGameRun`:

```python
    player_configs: list[dict[str, Any]] = field(default_factory=list)
```

Add `"player_configs": _copy_json_payload(self.player_configs)` to `to_summary()`. Add `player_configs: list[PlayerConfig] | None = None` to `LiveRunRegistry.create_run()`, normalize it with:

```python
        player_config_data = [
            config.to_dict() for config in player_configs or []
        ]
```

Set `player_configs=player_config_data` on `LiveGameRun` and include it in the `run_created` payload.

- [ ] **Step 9: Resolve configs in game API**

In `apps/api/app/api/routes/games.py`, add imports:

```python
from app.db.session import get_db
from app.models.virtual_player_profile import VirtualPlayerProfile
from app.werewolf.player_configs import PlayerConfig, player_config_from_profile
from app.werewolf.player_presets import is_valid_appearance, is_valid_personality
from sqlalchemy.orm import Session
```

Add Pydantic request model:

```python
class CreatePlayerConfigRequest(BaseModel):
    seat: int = Field(ge=1)
    profile_id: str | None = None
    name: str | None = Field(default=None, min_length=1, max_length=80)
    model: str | None = Field(default=None, min_length=1, max_length=120)
    personality_id: str | None = None
    personality: str | None = None
    appearance_id: str | None = None
    avatar_prompt: str | None = Field(default=None, max_length=500)
    tags: list[str] | None = Field(default=None, max_length=8)
```

Add to `CreateGameRunRequest`:

```python
    player_configs: list[CreatePlayerConfigRequest] = Field(default_factory=list)
```

Add `db: Annotated[Session, Depends(get_db)]` to `create_game_run()`. After `rule_snapshot`, normalize:

```python
    player_configs = normalize_player_config_requests(
        requests=request.player_configs,
        player_count=rule_set.player_count,
        db=db,
    )
```

Pass `player_configs=player_configs` to `registry.create_run()` and `_run_game_in_background`. Add the same parameter to `_run_game_in_background()` and pass it to `run_game()`.

Add helper in `games.py`:

```python
def normalize_player_config_requests(
    *,
    requests: list[CreatePlayerConfigRequest],
    player_count: int,
    db: Session,
) -> list[PlayerConfig]:
    if len(requests) > player_count:
        raise HTTPException(status_code=422, detail="player_configs exceeds player count")
    seen_seats: set[int] = set()
    configs: list[PlayerConfig] = []
    for item in requests:
        if item.seat > player_count:
            raise HTTPException(status_code=422, detail=f"Invalid player config seat: {item.seat}")
        if item.seat in seen_seats:
            raise HTTPException(status_code=422, detail=f"Duplicate player config seat: {item.seat}")
        seen_seats.add(item.seat)
        if item.personality_id and not is_valid_personality(item.personality_id):
            raise HTTPException(status_code=422, detail=f"Unknown personality_id: {item.personality_id}")
        if item.appearance_id and not is_valid_appearance(item.appearance_id):
            raise HTTPException(status_code=422, detail=f"Unknown appearance_id: {item.appearance_id}")
        profile = None
        if item.profile_id:
            profile = db.get(VirtualPlayerProfile, item.profile_id)
            if profile is None:
                raise HTTPException(status_code=422, detail=f"Unknown player profile: {item.profile_id}")
        configs.append(
            player_config_from_profile(
                seat=item.seat,
                profile=profile,
                overrides=item.model_dump(exclude_unset=True),
            )
        )
    return configs
```

- [ ] **Step 10: Run targeted runtime/API tests**

Run:

```bash
cd apps/api && uv run pytest tests/test_werewolf_runner.py::test_initialize_game_state_applies_player_config_snapshot tests/test_werewolf_runner.py::test_player_config_without_model_falls_back_to_role_model tests/test_werewolf_runner.py::test_world_state_includes_player_personality tests/test_werewolf_runner.py::test_player_from_dict_defaults_legacy_profile_fields tests/test_games_api.py::test_create_game_run_resolves_profile_configs tests/test_games_api.py::test_create_game_run_rejects_missing_profile -v
```

Expected: all targeted tests pass.

- [ ] **Step 11: Run wider API suite**

Run:

```bash
cd apps/api && uv run pytest -v
```

Expected: all API tests pass.

- [ ] **Step 12: Commit runtime snapshots**

Run:

```bash
git add apps/api/app/werewolf/player_configs.py apps/api/app/werewolf/models.py apps/api/app/werewolf/checkpoint.py apps/api/app/werewolf/engine.py apps/api/app/werewolf/runner.py apps/api/app/werewolf/live.py apps/api/app/api/routes/games.py apps/api/tests/test_werewolf_runner.py apps/api/tests/test_games_api.py
git commit -m "feat(api): snapshot virtual players into game runs"
```

---

### Task 4: Frontend Types And Profile API Client

**Files:**
- Modify: `apps/web/src/features/games/types.ts`
- Create: `apps/web/src/features/games/playerProfileOptions.ts`
- Create: `apps/web/src/features/games/api/listPlayerProfiles.ts`
- Create: `apps/web/src/features/games/api/createPlayerProfile.ts`
- Create: `apps/web/src/features/games/api/updatePlayerProfile.ts`
- Create: `apps/web/src/features/games/api/deletePlayerProfile.ts`
- Modify: `apps/web/src/features/games/api/liveRunApi.test.ts`
- Create: `apps/web/src/features/games/api/playerProfilesApi.test.ts`

- [ ] **Step 1: Write frontend API tests**

Create `apps/web/src/features/games/api/playerProfilesApi.test.ts`:

```ts
import { afterEach, describe, expect, it, vi } from "vitest";

import { createPlayerProfile } from "./createPlayerProfile";
import { deletePlayerProfile } from "./deletePlayerProfile";
import { listPlayerProfiles } from "./listPlayerProfiles";
import { updatePlayerProfile } from "./updatePlayerProfile";

const profilePayload = {
  id: "profile-1",
  owner_user_id: null,
  display_name: "冷静的阿夜",
  model: "MiniMax-M2.7",
  personality_id: "cautious",
  personality_text: "谨慎保守。",
  appearance_id: "moonlit",
  avatar_prompt: "银发观察者",
  tags: ["控场"],
  created_at: "2026-05-16T00:00:00Z",
  updated_at: "2026-05-16T00:00:00Z",
};

describe("player profiles api", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("lists player profiles", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ profiles: [profilePayload] }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );

    const response = await listPlayerProfiles();

    expect(fetchSpy).toHaveBeenCalledWith("/api/v1/player-profiles", undefined);
    expect(response.profiles[0].display_name).toBe("冷静的阿夜");
  });

  it("creates a player profile", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify(profilePayload), {
        status: 201,
        headers: { "Content-Type": "application/json" },
      }),
    );

    await createPlayerProfile({
      display_name: "冷静的阿夜",
      model: "MiniMax-M2.7",
      personality_id: "cautious",
      personality_text: "",
      appearance_id: "moonlit",
      avatar_prompt: "银发观察者",
      tags: ["控场"],
    });

    expect(fetchSpy).toHaveBeenCalledWith(
      "/api/v1/player-profiles",
      expect.objectContaining({
        method: "POST",
        headers: { "Content-Type": "application/json" },
      }),
    );
  });

  it("updates and deletes a player profile", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify(profilePayload), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );

    await updatePlayerProfile("profile-1", { display_name: "阿夜二号" });
    await deletePlayerProfile("profile-1");

    expect(fetchSpy.mock.calls[0][0]).toBe("/api/v1/player-profiles/profile-1");
    expect(fetchSpy.mock.calls[0][1]).toMatchObject({ method: "PATCH" });
    expect(fetchSpy.mock.calls[1][0]).toBe("/api/v1/player-profiles/profile-1");
    expect(fetchSpy.mock.calls[1][1]).toMatchObject({ method: "DELETE" });
  });
});
```

Modify `apps/web/src/features/games/api/liveRunApi.test.ts` "creates a game run" case to include:

```ts
player_configs: [
  {
    seat: 1,
    profile_id: "profile-1",
    name: "冷静的阿夜",
    model: "MiniMax-M2.7",
    personality_id: "cautious",
    personality: "谨慎保守。",
    appearance_id: "moonlit",
    avatar_prompt: "银发观察者",
    tags: ["控场"],
  },
],
```

and assert the body contains the same `player_configs`.

- [ ] **Step 2: Run API client tests to verify failure**

Run:

```bash
cd apps/web && pnpm test -- --run src/features/games/api/playerProfilesApi.test.ts src/features/games/api/liveRunApi.test.ts
```

Expected: fail because profile API modules and types do not exist.

- [ ] **Step 3: Extend shared types**

In `apps/web/src/features/games/types.ts`, add:

```ts
export type VirtualPlayerProfile = {
  id: string;
  owner_user_id: number | null;
  display_name: string;
  model: string;
  personality_id: string;
  personality_text: string;
  appearance_id: string;
  avatar_prompt: string;
  tags: string[];
  created_at: string;
  updated_at: string;
};

export type PlayerProfilesResponse = {
  profiles: VirtualPlayerProfile[];
};

export type PlayerProfileRequest = {
  display_name: string;
  model: string;
  personality_id?: string;
  personality_text?: string;
  appearance_id?: string;
  avatar_prompt?: string;
  tags?: string[];
};

export type UpdatePlayerProfileRequest = Partial<PlayerProfileRequest>;

export type PlayerConfig = {
  seat: number;
  profile_id?: string | null;
  name?: string | null;
  model?: string | null;
  personality_id?: string;
  personality?: string;
  appearance_id?: string;
  avatar_prompt?: string;
  tags?: string[];
};
```

Extend `RawPlayer` with optional fields:

```ts
  personality_id?: string;
  personality?: string;
  appearance_id?: string;
  avatar_prompt?: string;
  profile_id?: string | null;
  tags?: string[];
```

Extend `GameRun` with:

```ts
  player_configs?: PlayerConfig[];
```

Extend `CreateGameRunRequest` with:

```ts
  player_configs?: PlayerConfig[];
```

- [ ] **Step 4: Add option labels**

Create `apps/web/src/features/games/playerProfileOptions.ts`:

```ts
export const PERSONALITY_OPTIONS = [
  { id: "balanced", label: "均衡" },
  { id: "aggressive", label: "进攻" },
  { id: "cautious", label: "谨慎" },
  { id: "deceptive", label: "欺骗" },
  { id: "analytical", label: "分析" },
] as const;

export const APPEARANCE_OPTIONS = [
  { id: "default", label: "默认", className: "profile-appearance-default" },
  { id: "crimson", label: "绯红", className: "profile-appearance-crimson" },
  { id: "moonlit", label: "冷月", className: "profile-appearance-moonlit" },
  { id: "ember", label: "余烬", className: "profile-appearance-ember" },
  { id: "verdant", label: "幽林", className: "profile-appearance-verdant" },
] as const;

export function personalityLabel(id?: string) {
  return PERSONALITY_OPTIONS.find((option) => option.id === id)?.label ?? "均衡";
}

export function appearanceLabel(id?: string) {
  return APPEARANCE_OPTIONS.find((option) => option.id === id)?.label ?? "默认";
}

export function appearanceClassName(id?: string) {
  return (
    APPEARANCE_OPTIONS.find((option) => option.id === id)?.className ??
    "profile-appearance-default"
  );
}
```

- [ ] **Step 5: Add API clients**

Create `apps/web/src/features/games/api/listPlayerProfiles.ts`:

```ts
import { apiFetch } from "../../../api/client";
import type { PlayerProfilesResponse } from "../types";

export function listPlayerProfiles(): Promise<PlayerProfilesResponse> {
  return apiFetch<PlayerProfilesResponse>("/api/v1/player-profiles");
}
```

Create `apps/web/src/features/games/api/createPlayerProfile.ts`:

```ts
import { apiFetch } from "../../../api/client";
import type { PlayerProfileRequest, VirtualPlayerProfile } from "../types";

export function createPlayerProfile(
  request: PlayerProfileRequest,
): Promise<VirtualPlayerProfile> {
  return apiFetch<VirtualPlayerProfile>("/api/v1/player-profiles", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  });
}
```

Create `apps/web/src/features/games/api/updatePlayerProfile.ts`:

```ts
import { apiFetch } from "../../../api/client";
import type { UpdatePlayerProfileRequest, VirtualPlayerProfile } from "../types";

export function updatePlayerProfile(
  profileId: string,
  request: UpdatePlayerProfileRequest,
): Promise<VirtualPlayerProfile> {
  return apiFetch<VirtualPlayerProfile>(`/api/v1/player-profiles/${profileId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  });
}
```

Create `apps/web/src/features/games/api/deletePlayerProfile.ts`:

```ts
import { apiFetch } from "../../../api/client";

export function deletePlayerProfile(profileId: string): Promise<void> {
  return apiFetch<void>(`/api/v1/player-profiles/${profileId}`, {
    method: "DELETE",
  });
}
```

- [ ] **Step 6: Run frontend API tests**

Run:

```bash
cd apps/web && pnpm test -- --run src/features/games/api/playerProfilesApi.test.ts src/features/games/api/liveRunApi.test.ts
```

Expected: selected frontend API tests pass.

- [ ] **Step 7: Commit frontend API foundation**

Run:

```bash
git add apps/web/src/features/games/types.ts apps/web/src/features/games/playerProfileOptions.ts apps/web/src/features/games/api/listPlayerProfiles.ts apps/web/src/features/games/api/createPlayerProfile.ts apps/web/src/features/games/api/updatePlayerProfile.ts apps/web/src/features/games/api/deletePlayerProfile.ts apps/web/src/features/games/api/liveRunApi.test.ts apps/web/src/features/games/api/playerProfilesApi.test.ts
git commit -m "feat(web): add virtual player profile api client"
```

---

### Task 5: Frontend Profile Library UI

**Files:**
- Create: `apps/web/src/features/games/components/VirtualPlayerLibrary.tsx`
- Modify: `apps/web/src/pages/components/GamesWorkspace.tsx`
- Modify: `apps/web/src/styles/index.css`
- Modify: `apps/web/src/pages/GamesPage.test.tsx`

- [ ] **Step 1: Add GamesPage test expectations for library**

In `apps/web/src/pages/GamesPage.test.tsx`, update the fetch mock so `/api/v1/player-profiles` returns:

```ts
{
  profiles: [
    {
      id: "profile-1",
      owner_user_id: null,
      display_name: "冷静的阿夜",
      model: "MiniMax-M2.7",
      personality_id: "cautious",
      personality_text: "谨慎保守。",
      appearance_id: "moonlit",
      avatar_prompt: "银发观察者",
      tags: ["控场"],
      created_at: "2026-05-16T00:00:00Z",
      updated_at: "2026-05-16T00:00:00Z",
    },
  ],
}
```

Add assertions:

```ts
expect(await screen.findByTestId("virtual-player-library")).toBeInTheDocument();
expect(screen.getByRole("heading", { name: "虚拟玩家库" })).toBeInTheDocument();
expect(screen.getByText("冷静的阿夜")).toBeInTheDocument();
expect(screen.getByText("MiniMax-M2.7")).toBeInTheDocument();
expect(screen.getByText("谨慎")).toBeInTheDocument();
expect(screen.getByRole("button", { name: "新建虚拟玩家" })).toBeInTheDocument();
```

- [ ] **Step 2: Run page test to verify failure**

Run:

```bash
cd apps/web && pnpm test -- --run src/pages/GamesPage.test.tsx
```

Expected: fail because the library component is not rendered.

- [ ] **Step 3: Create library component**

Create `apps/web/src/features/games/components/VirtualPlayerLibrary.tsx`:

```tsx
import { Button, Container } from "../../../components/ui";
import { appearanceClassName, personalityLabel } from "../playerProfileOptions";
import type { VirtualPlayerProfile } from "../types";

type VirtualPlayerLibraryProps = {
  profiles: VirtualPlayerProfile[];
  isLoading: boolean;
  isError: boolean;
};

export function VirtualPlayerLibrary({
  profiles,
  isLoading,
  isError,
}: VirtualPlayerLibraryProps) {
  return (
    <Container
      aria-labelledby="virtual-player-library-title"
      as="section"
      className="virtual-player-library"
      contentClassName="virtual-player-library-content"
      data-testid="virtual-player-library"
      size="2"
    >
      <div className="virtual-player-library-header">
        <h2 id="virtual-player-library-title">虚拟玩家库</h2>
        <Button size="1" skin="gothic" type="button">
          新建虚拟玩家
        </Button>
      </div>
      {isLoading ? <p className="virtual-player-library-status">正在读取虚拟玩家...</p> : null}
      {isError ? <p className="virtual-player-library-error">无法读取虚拟玩家库</p> : null}
      {!isLoading && !isError && profiles.length === 0 ? (
        <p className="virtual-player-library-empty">还没有保存的虚拟玩家。</p>
      ) : null}
      {profiles.length > 0 ? (
        <ul className="virtual-player-card-grid" aria-label="虚拟玩家列表">
          {profiles.map((profile) => (
            <li className="virtual-player-card" key={profile.id}>
              <span
                aria-hidden="true"
                className={`virtual-player-avatar ${appearanceClassName(profile.appearance_id)}`}
              >
                {profile.display_name.slice(0, 1)}
              </span>
              <span className="virtual-player-card-main">
                <strong>{profile.display_name}</strong>
                <span>{profile.model}</span>
              </span>
              <span className="virtual-player-card-tags">
                <span>{personalityLabel(profile.personality_id)}</span>
                {profile.tags.slice(0, 2).map((tag) => (
                  <span key={tag}>{tag}</span>
                ))}
              </span>
            </li>
          ))}
        </ul>
      ) : null}
    </Container>
  );
}
```

- [ ] **Step 4: Wire library into workspace and accept profile props**

First modify `apps/web/src/features/games/components/CreateGameRunForm.tsx` so the component can receive profiles before seat selection is implemented:

```tsx
import type {
  EventPacingMode,
  RuleSetSummary,
  VirtualPlayerProfile,
} from "../types";

type CreateGameRunFormProps = {
  profiles?: VirtualPlayerProfile[];
};

export function CreateGameRunForm({ profiles = [] }: CreateGameRunFormProps) {
  void profiles;
```

Keep the existing form behavior unchanged in this task.

Modify `apps/web/src/pages/components/GamesWorkspace.tsx`:

```tsx
import { useQuery } from "@tanstack/react-query";
import { CreateGameRunForm } from "../../features/games/components/CreateGameRunForm";
import { VirtualPlayerLibrary } from "../../features/games/components/VirtualPlayerLibrary";
import { listPlayerProfiles } from "../../features/games/api/listPlayerProfiles";
import type { RefObject } from "react";

type GamesWorkspaceProps = {
  createFormRef: RefObject<HTMLDivElement | null>;
};

export function GamesWorkspace({ createFormRef }: GamesWorkspaceProps) {
  const profilesQuery = useQuery({
    queryKey: ["player-profiles"],
    queryFn: listPlayerProfiles,
  });
  const profiles = profilesQuery.data?.profiles ?? [];

  return (
    <main
      className="games-workspace-module lobby-page-shell mx-auto w-full max-w-none px-4 py-5 sm:px-6 lg:px-8"
      data-testid="games-workspace-module"
    >
      <VirtualPlayerLibrary
        profiles={profiles}
        isLoading={profilesQuery.isPending}
        isError={profilesQuery.isError}
      />
      <div ref={createFormRef}>
        <CreateGameRunForm profiles={profiles} />
      </div>
    </main>
  );
}
```

- [ ] **Step 5: Add CSS for library**

Append to `apps/web/src/styles/index.css`:

```css
.virtual-player-library {
  margin-bottom: 18px;
}

.virtual-player-library-content {
  display: grid;
  gap: 14px;
}

.virtual-player-library-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.virtual-player-library-header h2 {
  margin: 0;
  color: rgb(255 248 220);
  font-size: 1rem;
  font-weight: 700;
}

.virtual-player-library-status,
.virtual-player-library-empty {
  margin: 0;
  color: rgb(203 213 225);
  font-size: 0.875rem;
}

.virtual-player-library-error {
  margin: 0;
  color: rgb(254 202 202);
  font-size: 0.875rem;
}

.virtual-player-card-grid {
  display: grid;
  gap: 10px;
  grid-template-columns: repeat(auto-fit, minmax(210px, 1fr));
  list-style: none;
  margin: 0;
  padding: 0;
}

.virtual-player-card {
  display: grid;
  grid-template-columns: 42px minmax(0, 1fr);
  gap: 10px;
  align-items: center;
  border: 1px solid rgb(245 158 11 / 0.22);
  border-radius: 8px;
  background: rgb(15 23 42 / 0.62);
  padding: 10px;
}

.virtual-player-avatar {
  display: inline-flex;
  height: 42px;
  width: 42px;
  align-items: center;
  justify-content: center;
  border-radius: 999px;
  border: 2px solid rgb(251 191 36 / 0.45);
  color: rgb(255 251 235);
  font-weight: 700;
}

.profile-appearance-default {
  background: linear-gradient(135deg, rgb(51 65 85), rgb(15 23 42));
}

.profile-appearance-crimson {
  background: linear-gradient(135deg, rgb(127 29 29), rgb(30 41 59));
}

.profile-appearance-moonlit {
  background: linear-gradient(135deg, rgb(30 64 175), rgb(226 232 240));
}

.profile-appearance-ember {
  background: linear-gradient(135deg, rgb(180 83 9), rgb(127 29 29));
}

.profile-appearance-verdant {
  background: linear-gradient(135deg, rgb(20 83 45), rgb(15 23 42));
}

.virtual-player-card-main,
.virtual-player-card-tags {
  display: flex;
  min-width: 0;
}

.virtual-player-card-main {
  flex-direction: column;
  gap: 2px;
}

.virtual-player-card-main strong,
.virtual-player-card-main span {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.virtual-player-card-main strong {
  color: rgb(248 250 252);
  font-size: 0.9rem;
}

.virtual-player-card-main span {
  color: rgb(148 163 184);
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-size: 0.72rem;
}

.virtual-player-card-tags {
  grid-column: 2;
  flex-wrap: wrap;
  gap: 6px;
}

.virtual-player-card-tags span {
  border-radius: 6px;
  background: rgb(245 158 11 / 0.12);
  color: rgb(253 230 138);
  font-size: 0.72rem;
  padding: 2px 6px;
}
```

- [ ] **Step 6: Run page tests**

Run:

```bash
cd apps/web && pnpm test -- --run src/pages/GamesPage.test.tsx
```

Expected: page tests pass after updating fetch mocks for `/api/v1/player-profiles`.

- [ ] **Step 7: Commit library UI**

Run:

```bash
git add apps/web/src/features/games/components/VirtualPlayerLibrary.tsx apps/web/src/pages/components/GamesWorkspace.tsx apps/web/src/styles/index.css apps/web/src/pages/GamesPage.test.tsx
git commit -m "feat(web): show virtual player library"
```

---

### Task 6: Frontend Profile Library Management Actions

**Files:**
- Modify: `apps/web/src/features/games/components/VirtualPlayerLibrary.tsx`
- Modify: `apps/web/src/pages/components/GamesWorkspace.tsx`
- Modify: `apps/web/src/styles/index.css`
- Modify: `apps/web/src/pages/GamesPage.test.tsx`

- [ ] **Step 1: Add UI mutation tests**

In `apps/web/src/pages/GamesPage.test.tsx`, add a focused test for create, copy, edit, and delete:

```ts
it("creates, copies, edits, and deletes virtual player profiles", async () => {
  const user = userEvent.setup();
  const fetchSpy = vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
    const url = String(input);
    if (url.endsWith("/api/v1/games/rule-sets")) {
      return Promise.resolve(
        new Response(JSON.stringify(ruleSetsResponse()), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      );
    }
    if (url.endsWith("/api/v1/player-profiles") && !init) {
      return Promise.resolve(
        new Response(
          JSON.stringify({
            profiles: [
              {
                id: "profile-1",
                owner_user_id: null,
                display_name: "冷静的阿夜",
                model: "MiniMax-M2.7",
                personality_id: "cautious",
                personality_text: "谨慎保守。",
                appearance_id: "moonlit",
                avatar_prompt: "银发观察者",
                tags: ["控场"],
                created_at: "2026-05-16T00:00:00Z",
                updated_at: "2026-05-16T00:00:00Z",
              },
            ],
          }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        ),
      );
    }
    if (url.endsWith("/api/v1/player-profiles") && init?.method === "POST") {
      return Promise.resolve(
        new Response(JSON.stringify({ id: "profile-new" }), {
          status: 201,
          headers: { "Content-Type": "application/json" },
        }),
      );
    }
    if (url.endsWith("/api/v1/player-profiles/profile-1") && init?.method === "PATCH") {
      return Promise.resolve(
        new Response(JSON.stringify({ id: "profile-1" }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      );
    }
    if (url.endsWith("/api/v1/player-profiles/profile-1") && init?.method === "DELETE") {
      return Promise.resolve(new Response(null, { status: 204 }));
    }
    return Promise.resolve(new Response(JSON.stringify({ sessions: [] }), { status: 200 }));
  });

  renderWithClient(<GamesPage />, "/games");

  await user.click(await screen.findByRole("button", { name: "新建虚拟玩家" }));
  await user.type(screen.getByLabelText("虚拟玩家昵称"), "高压猎手");
  await user.type(screen.getByLabelText("默认模型"), "qwen3.6-plus");
  await user.click(screen.getByRole("button", { name: "保存虚拟玩家" }));
  await user.click(screen.getByRole("button", { name: "复制 冷静的阿夜" }));
  await user.click(screen.getByRole("button", { name: "编辑 冷静的阿夜" }));
  await user.clear(screen.getByLabelText("虚拟玩家昵称"));
  await user.type(screen.getByLabelText("虚拟玩家昵称"), "冷静的阿夜二号");
  await user.click(screen.getByRole("button", { name: "保存虚拟玩家" }));
  await user.click(screen.getByRole("button", { name: "删除 冷静的阿夜" }));

  const postCalls = fetchSpy.mock.calls.filter(
    ([input, init]) => String(input).endsWith("/api/v1/player-profiles") && init?.method === "POST",
  );
  expect(postCalls).toHaveLength(2);
  expect(JSON.parse(String(postCalls[0][1]?.body))).toMatchObject({
    display_name: "高压猎手",
    model: "qwen3.6-plus",
  });
  expect(JSON.parse(String(postCalls[1][1]?.body))).toMatchObject({
    display_name: "冷静的阿夜 副本",
    model: "MiniMax-M2.7",
  });
  expect(
    fetchSpy.mock.calls.some(
      ([input, init]) =>
        String(input).endsWith("/api/v1/player-profiles/profile-1") &&
        init?.method === "PATCH",
    ),
  ).toBe(true);
  expect(
    fetchSpy.mock.calls.some(
      ([input, init]) =>
        String(input).endsWith("/api/v1/player-profiles/profile-1") &&
        init?.method === "DELETE",
    ),
  ).toBe(true);
});
```

- [ ] **Step 2: Run page test to verify failure**

Run:

```bash
cd apps/web && pnpm test -- --run src/pages/GamesPage.test.tsx
```

Expected: fail because the profile library has no mutation callbacks or editor form.

- [ ] **Step 3: Pass mutation callbacks from workspace**

Modify `apps/web/src/pages/components/GamesWorkspace.tsx` imports:

```tsx
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { createPlayerProfile } from "../../features/games/api/createPlayerProfile";
import { deletePlayerProfile } from "../../features/games/api/deletePlayerProfile";
import { updatePlayerProfile } from "../../features/games/api/updatePlayerProfile";
import type { PlayerProfileRequest } from "../../features/games/types";
```

Inside `GamesWorkspace`, add:

```tsx
  const queryClient = useQueryClient();
  const invalidateProfiles = () =>
    queryClient.invalidateQueries({ queryKey: ["player-profiles"] });
  const createProfileMutation = useMutation({
    mutationFn: createPlayerProfile,
    onSuccess: invalidateProfiles,
  });
  const updateProfileMutation = useMutation({
    mutationFn: ({
      profileId,
      request,
    }: {
      profileId: string;
      request: Partial<PlayerProfileRequest>;
    }) => updatePlayerProfile(profileId, request),
    onSuccess: invalidateProfiles,
  });
  const deleteProfileMutation = useMutation({
    mutationFn: deletePlayerProfile,
    onSuccess: invalidateProfiles,
  });
```

Pass the callbacks:

```tsx
      <VirtualPlayerLibrary
        profiles={profiles}
        isLoading={profilesQuery.isPending}
        isError={profilesQuery.isError}
        isSaving={
          createProfileMutation.isPending ||
          updateProfileMutation.isPending ||
          deleteProfileMutation.isPending
        }
        onCreateProfile={(request) => createProfileMutation.mutate(request)}
        onUpdateProfile={(profileId, request) =>
          updateProfileMutation.mutate({ profileId, request })
        }
        onDeleteProfile={(profileId) => deleteProfileMutation.mutate(profileId)}
      />
```

- [ ] **Step 4: Add editor and actions to library**

In `apps/web/src/features/games/components/VirtualPlayerLibrary.tsx`, add imports:

```tsx
import { useState } from "react";
import { SelectField, TextField } from "../../../components/ui";
import { APPEARANCE_OPTIONS, PERSONALITY_OPTIONS } from "../playerProfileOptions";
import type { PlayerProfileRequest } from "../types";
```

Extend props:

```tsx
  isSaving: boolean;
  onCreateProfile: (request: PlayerProfileRequest) => void;
  onUpdateProfile: (profileId: string, request: Partial<PlayerProfileRequest>) => void;
  onDeleteProfile: (profileId: string) => void;
```

Add state and helpers inside the component:

```tsx
  const [editingId, setEditingId] = useState<string | null>(null);
  const editingProfile =
    profiles.find((profile) => profile.id === editingId) ?? null;
  const [draft, setDraft] = useState<PlayerProfileRequest>({
    display_name: "",
    model: "",
    personality_id: "balanced",
    personality_text: "",
    appearance_id: "default",
    avatar_prompt: "",
    tags: [],
  });

  function startCreate() {
    setEditingId(null);
    setDraft({
      display_name: "",
      model: "",
      personality_id: "balanced",
      personality_text: "",
      appearance_id: "default",
      avatar_prompt: "",
      tags: [],
    });
  }

  function startEdit(profileId: string) {
    const profile = profiles.find((item) => item.id === profileId);
    if (!profile) {
      return;
    }
    setEditingId(profile.id);
    setDraft({
      display_name: profile.display_name,
      model: profile.model,
      personality_id: profile.personality_id,
      personality_text: profile.personality_text,
      appearance_id: profile.appearance_id,
      avatar_prompt: profile.avatar_prompt,
      tags: profile.tags,
    });
  }

  function duplicateProfile(profileId: string) {
    const profile = profiles.find((item) => item.id === profileId);
    if (!profile) {
      return;
    }
    onCreateProfile({
      display_name: `${profile.display_name} 副本`,
      model: profile.model,
      personality_id: profile.personality_id,
      personality_text: profile.personality_text,
      appearance_id: profile.appearance_id,
      avatar_prompt: profile.avatar_prompt,
      tags: profile.tags,
    });
  }

  function saveDraft() {
    const request = {
      ...draft,
      tags: draft.tags ?? [],
    };
    if (editingProfile) {
      onUpdateProfile(editingProfile.id, request);
    } else {
      onCreateProfile(request);
    }
  }
```

Replace the existing new button with:

```tsx
<Button size="1" skin="gothic" type="button" onClick={startCreate}>
  新建虚拟玩家
</Button>
```

Render this form below the header:

```tsx
<div className="virtual-player-editor" data-testid="virtual-player-editor">
  <label>
    <span>昵称</span>
    <TextField.Root
      aria-label="虚拟玩家昵称"
      value={draft.display_name}
      onChange={(event) =>
        setDraft((current) => ({ ...current, display_name: event.target.value }))
      }
    />
  </label>
  <label>
    <span>模型</span>
    <TextField.Root
      aria-label="默认模型"
      value={draft.model}
      onChange={(event) =>
        setDraft((current) => ({ ...current, model: event.target.value }))
      }
    />
  </label>
  <label>
    <span>性格</span>
    <SelectField
      aria-label="性格"
      value={draft.personality_id ?? "balanced"}
      onChange={(event) =>
        setDraft((current) => ({
          ...current,
          personality_id: event.target.value,
          personality_text: "",
        }))
      }
    >
      {PERSONALITY_OPTIONS.map((option) => (
        <option key={option.id} value={option.id}>
          {option.label}
        </option>
      ))}
    </SelectField>
  </label>
  <label>
    <span>形象</span>
    <SelectField
      aria-label="人物形象"
      value={draft.appearance_id ?? "default"}
      onChange={(event) =>
        setDraft((current) => ({ ...current, appearance_id: event.target.value }))
      }
    >
      {APPEARANCE_OPTIONS.map((option) => (
        <option key={option.id} value={option.id}>
          {option.label}
        </option>
      ))}
    </SelectField>
  </label>
  <Button
    disabled={isSaving || !draft.display_name.trim() || !draft.model.trim()}
    size="1"
    skin="gothic"
    type="button"
    onClick={saveDraft}
  >
    保存虚拟玩家
  </Button>
</div>
```

Inside each profile card, add action buttons:

```tsx
<span className="virtual-player-card-actions">
  <Button size="1" type="button" onClick={() => startEdit(profile.id)}>
    编辑 {profile.display_name}
  </Button>
  <Button size="1" type="button" onClick={() => duplicateProfile(profile.id)}>
    复制 {profile.display_name}
  </Button>
  <Button size="1" type="button" onClick={() => onDeleteProfile(profile.id)}>
    删除 {profile.display_name}
  </Button>
</span>
```

- [ ] **Step 5: Add editor/action CSS**

Append to `apps/web/src/styles/index.css`:

```css
.virtual-player-editor {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 10px;
  align-items: end;
  border: 1px solid rgb(245 158 11 / 0.18);
  border-radius: 8px;
  background: rgb(2 6 23 / 0.38);
  padding: 10px;
}

.virtual-player-editor label {
  display: grid;
  gap: 5px;
}

.virtual-player-editor label span {
  color: rgb(203 213 225);
  font-size: 0.75rem;
}

.virtual-player-card-actions {
  grid-column: 1 / -1;
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.virtual-player-card-actions button {
  min-height: 30px;
}
```

- [ ] **Step 6: Run mutation UI tests**

Run:

```bash
cd apps/web && pnpm test -- --run src/pages/GamesPage.test.tsx
```

Expected: profile library tests pass, including create/copy/edit/delete API calls.

- [ ] **Step 7: Commit library management actions**

Run:

```bash
git add apps/web/src/features/games/components/VirtualPlayerLibrary.tsx apps/web/src/pages/components/GamesWorkspace.tsx apps/web/src/styles/index.css apps/web/src/pages/GamesPage.test.tsx
git commit -m "feat(web): manage virtual player profiles"
```

---

### Task 7: Frontend Seat Profile Selection And Create Run Payload

**Files:**
- Create: `apps/web/src/features/games/components/PlayerConfigPanel.tsx`
- Modify: `apps/web/src/features/games/components/CreateGameRunForm.tsx`
- Modify: `apps/web/src/styles/index.css`
- Modify: `apps/web/src/pages/GamesPage.test.tsx`

- [ ] **Step 1: Write create-form payload test**

In `apps/web/src/pages/GamesPage.test.tsx`, add a test:

```ts
it("submits selected virtual player configs when launching a game", async () => {
  const user = userEvent.setup();
  const fetchSpy = vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
    const url = String(input);
    if (url.endsWith("/api/v1/games/rule-sets")) {
      return Promise.resolve(
        new Response(JSON.stringify(ruleSetsResponse()), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      );
    }
    if (url.endsWith("/api/v1/player-profiles")) {
      return Promise.resolve(
        new Response(
          JSON.stringify({
            profiles: [
              {
                id: "profile-1",
                owner_user_id: null,
                display_name: "冷静的阿夜",
                model: "MiniMax-M2.7",
                personality_id: "cautious",
                personality_text: "谨慎保守。",
                appearance_id: "moonlit",
                avatar_prompt: "银发观察者",
                tags: ["控场"],
                created_at: "2026-05-16T00:00:00Z",
                updated_at: "2026-05-16T00:00:00Z",
              },
            ],
          }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        ),
      );
    }
    if (url.endsWith("/api/v1/games/runs")) {
      return Promise.resolve(
        new Response(
          JSON.stringify({
            run_id: "run_profiled",
            session_id: "session_20260516_000000_profiled",
            villager_model: "deepseek-v4-flash",
            werewolf_model: "deepseek-v4-flash",
            seed: null,
            max_rounds: 8,
            winner: null,
            status: "queued",
            created_at: "2026-05-16T00:00:00Z",
            started_at: null,
            completed_at: null,
            error: null,
            event_count: 1,
            event_pacing: "off",
            player_configs: [],
          }),
          { status: 201, headers: { "Content-Type": "application/json" } },
        ),
      );
    }
    return Promise.resolve(new Response(JSON.stringify({ sessions: [] }), { status: 200 }));
  });

  renderWithClient(
    <Routes>
      <Route path="/games" element={<GamesPage />} />
      <Route path="/games/live/:runId" element={<div>live page</div>} />
    </Routes>,
    "/games",
  );

  const seatOneSelect = await screen.findByLabelText("1 号座位虚拟玩家");
  await user.selectOptions(seatOneSelect, "profile-1");
  await user.click(screen.getByRole("button", { name: "发起对局" }));

  const createCall = fetchSpy.mock.calls.find(([input]) =>
    String(input).endsWith("/api/v1/games/runs"),
  );
  expect(createCall).toBeDefined();
  expect(JSON.parse(String(createCall?.[1]?.body))).toMatchObject({
    player_configs: [{ seat: 1, profile_id: "profile-1" }],
  });
});
```

- [ ] **Step 2: Run test to verify failure**

Run:

```bash
cd apps/web && pnpm test -- --run src/pages/GamesPage.test.tsx
```

Expected: fail because seat profile controls do not exist.

- [ ] **Step 3: Create seat config panel**

Create `apps/web/src/features/games/components/PlayerConfigPanel.tsx`:

```tsx
import { SelectField, TextField } from "../../../components/ui";
import { appearanceLabel, personalityLabel } from "../playerProfileOptions";
import type { PlayerConfig, VirtualPlayerProfile } from "../types";

type PlayerConfigPanelProps = {
  playerCount: number;
  profiles: VirtualPlayerProfile[];
  configs: PlayerConfig[];
  onChange: (configs: PlayerConfig[]) => void;
};

export function PlayerConfigPanel({
  playerCount,
  profiles,
  configs,
  onChange,
}: PlayerConfigPanelProps) {
  const seats = Array.from({ length: playerCount }, (_, index) => index + 1);

  function updateSeat(seat: number, patch: Partial<PlayerConfig>) {
    const existing = configs.find((config) => config.seat === seat);
    const nextConfig: PlayerConfig = { seat, ...existing, ...patch };
    const next = configs.filter((config) => config.seat !== seat);
    if (nextConfig.profile_id || nextConfig.model || nextConfig.personality_id || nextConfig.appearance_id) {
      next.push(nextConfig);
    }
    onChange(next.sort((a, b) => a.seat - b.seat));
  }

  return (
    <section className="player-config-panel" aria-labelledby="player-config-title">
      <div className="player-config-header">
        <h2 id="player-config-title">虚拟玩家</h2>
        <span>{playerCount} 个座位</span>
      </div>
      <div className="player-config-grid">
        {seats.map((seat) => {
          const config = configs.find((item) => item.seat === seat);
          const selectedProfile = profiles.find((profile) => profile.id === config?.profile_id);
          return (
            <div className="player-config-seat" key={seat}>
              <label>
                <span>{seat} 号座位</span>
                <SelectField
                  aria-label={`${seat} 号座位虚拟玩家`}
                  value={config?.profile_id ?? ""}
                  onChange={(event) =>
                    updateSeat(seat, {
                      profile_id: event.target.value || null,
                      model: null,
                      personality_id: undefined,
                      appearance_id: undefined,
                    })
                  }
                >
                  <option value="">随机玩家</option>
                  {profiles.map((profile) => (
                    <option key={profile.id} value={profile.id}>
                      {profile.display_name}
                    </option>
                  ))}
                </SelectField>
              </label>
              <label>
                <span>本局模型覆盖</span>
                <TextField.Root
                  aria-label={`${seat} 号座位模型覆盖`}
                  placeholder={selectedProfile?.model ?? "按身份默认"}
                  value={config?.model ?? ""}
                  onChange={(event) =>
                    updateSeat(seat, { model: event.target.value || null })
                  }
                />
              </label>
              {selectedProfile ? (
                <p className="player-config-summary">
                  {personalityLabel(selectedProfile.personality_id)} ·{" "}
                  {appearanceLabel(selectedProfile.appearance_id)}
                </p>
              ) : null}
            </div>
          );
        })}
      </div>
    </section>
  );
}
```

- [ ] **Step 4: Integrate seat config into create form**

Update the existing imports and remove `void profiles;` from `CreateGameRunForm`:

```tsx
import type {
  EventPacingMode,
  PlayerConfig,
  RuleSetSummary,
  VirtualPlayerProfile,
} from "../types";

type CreateGameRunFormProps = {
  profiles?: VirtualPlayerProfile[];
};

export function CreateGameRunForm({ profiles = [] }: CreateGameRunFormProps) {
```

Add state:

```tsx
  const [playerConfigs, setPlayerConfigs] = useState<PlayerConfig[]>([]);
```

Add helper before submit:

```tsx
  const normalizedPlayerConfigs = playerConfigs
    .filter((config) => config.seat <= (selectedRuleSet?.player_count ?? 0))
    .map((config) => ({
      seat: config.seat,
      ...(config.profile_id ? { profile_id: config.profile_id } : {}),
      ...(config.model ? { model: config.model } : {}),
      ...(config.personality_id ? { personality_id: config.personality_id } : {}),
      ...(config.appearance_id ? { appearance_id: config.appearance_id } : {}),
    }));
```

Include `player_configs: normalizedPlayerConfigs` in `mutation.mutate()`.

Render after selected rule details:

```tsx
            {selectedRuleSet ? (
              <PlayerConfigPanel
                playerCount={selectedRuleSet.player_count}
                profiles={profiles}
                configs={playerConfigs}
                onChange={setPlayerConfigs}
              />
            ) : null}
```

Import `PlayerConfigPanel` at the top.

- [ ] **Step 5: Add CSS for seat panel**

Append to `apps/web/src/styles/index.css`:

```css
.player-config-panel {
  display: grid;
  gap: 14px;
}

.player-config-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.player-config-header h2 {
  margin: 0;
  color: rgb(255 248 220);
  font-size: 1rem;
}

.player-config-header span {
  color: rgb(203 213 225);
  font-size: 0.8rem;
}

.player-config-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(230px, 1fr));
  gap: 10px;
}

.player-config-seat {
  display: grid;
  gap: 8px;
  border: 1px solid rgb(245 158 11 / 0.2);
  border-radius: 8px;
  background: rgb(2 6 23 / 0.45);
  padding: 10px;
}

.player-config-seat label {
  display: grid;
  gap: 5px;
}

.player-config-seat label span,
.player-config-summary {
  color: rgb(203 213 225);
  font-size: 0.75rem;
}

.player-config-summary {
  margin: 0;
}
```

- [ ] **Step 6: Run create page tests**

Run:

```bash
cd apps/web && pnpm test -- --run src/pages/GamesPage.test.tsx
```

Expected: page tests pass, including create payload with `player_configs`.

- [ ] **Step 7: Commit seat config UI**

Run:

```bash
git add apps/web/src/features/games/components/PlayerConfigPanel.tsx apps/web/src/features/games/components/CreateGameRunForm.tsx apps/web/src/styles/index.css apps/web/src/pages/GamesPage.test.tsx
git commit -m "feat(web): assign virtual players to seats"
```

---

### Task 8: Live And Replay Display New Player Fields

**Files:**
- Modify: `apps/web/src/features/games/liveSpectator.ts`
- Modify: `apps/web/src/features/games/liveSpectator.test.ts`
- Modify: `apps/web/src/features/games/api/adapters.ts`
- Modify: `apps/web/src/features/games/api/adapters.test.ts`
- Modify: `apps/web/src/features/games/components/PlayerRosterPanel.tsx`
- Modify: `apps/web/src/features/games/components/LiveDirectorStage.tsx`
- Modify: `apps/web/src/features/games/components/LivePlayerPanel.tsx`

- [ ] **Step 1: Write live spectator test**

In `apps/web/src/features/games/liveSpectator.test.ts`, add:

```ts
it("reads virtual player profile fields from game_started", () => {
  const state = deriveLiveSpectatorState([
    {
      id: 1,
      type: "game_started",
      run_id: "run_1",
      session_id: "session_1",
      created_at: "2026-05-16T00:00:00Z",
      round: null,
      phase: null,
      actor: null,
      action: null,
      payload: {
        players: [
          {
            name: "冷静的阿夜",
            role: "村民",
            model: "MiniMax-M2.7",
            personality_id: "cautious",
            personality: "谨慎保守。",
            appearance_id: "moonlit",
            avatar_prompt: "银发观察者",
            profile_id: "profile-1",
            tags: ["控场"],
          },
        ],
        active_players: ["冷静的阿夜"],
      },
    },
  ]);

  expect(state.players[0]).toMatchObject({
    personalityId: "cautious",
    personality: "谨慎保守。",
    appearanceId: "moonlit",
    profileId: "profile-1",
    tags: ["控场"],
  });
});
```

- [ ] **Step 2: Run live spectator test to verify failure**

Run:

```bash
cd apps/web && pnpm test -- --run src/features/games/liveSpectator.test.ts
```

Expected: fail because `LivePlayer` does not expose these fields.

- [ ] **Step 3: Extend live player state**

In `apps/web/src/features/games/liveSpectator.ts`, add to `LivePlayer`:

```ts
  personalityId: string;
  personality: string;
  appearanceId: string;
  avatarPrompt: string;
  profileId: string | null;
  tags: string[];
```

In `ensurePlayer()`, set defaults:

```ts
    personalityId: "balanced",
    personality: "",
    appearanceId: "default",
    avatarPrompt: "",
    profileId: null,
    tags: [],
```

In `initializePlayers()`, after model assignment:

```ts
    existing.personalityId =
      typeof player.personality_id === "string"
        ? player.personality_id
        : existing.personalityId;
    existing.personality =
      typeof player.personality === "string" ? player.personality : existing.personality;
    existing.appearanceId =
      typeof player.appearance_id === "string"
        ? player.appearance_id
        : existing.appearanceId;
    existing.avatarPrompt =
      typeof player.avatar_prompt === "string"
        ? player.avatar_prompt
        : existing.avatarPrompt;
    existing.profileId =
      typeof player.profile_id === "string" ? player.profile_id : existing.profileId;
    existing.tags = Array.isArray(player.tags)
      ? player.tags.filter((tag): tag is string => typeof tag === "string")
      : existing.tags;
```

- [ ] **Step 4: Preserve replay defaults**

In `apps/web/src/features/games/api/adapters.ts`, add helper:

```ts
function normalizePlayers(players: RawGameReplayResponse["state"]["players"]) {
  return players.map((player) => ({
    ...player,
    personality_id: player.personality_id ?? "balanced",
    personality: player.personality ?? "",
    appearance_id: player.appearance_id ?? "default",
    avatar_prompt: player.avatar_prompt ?? "",
    profile_id: player.profile_id ?? null,
    tags: player.tags ?? [],
  }));
}
```

Change `players: response.state.players` to:

```ts
    players: normalizePlayers(response.state.players),
```

Add an adapter test in `apps/web/src/features/games/api/adapters.test.ts`:

```ts
it("adds default virtual player fields for legacy replays", () => {
  const replay = normalizeGameReplay(rawReplay);

  expect(replay.players[0]).toMatchObject({
    personality_id: "balanced",
    personality: "",
    appearance_id: "default",
    avatar_prompt: "",
    profile_id: null,
    tags: [],
  });
});
```

- [ ] **Step 5: Apply appearance to display components**

In `PlayerRosterPanel.tsx`, extend `PlayerRosterItem`:

```ts
  personalityId?: string;
  appearanceId?: string;
  tags?: string[];
```

Import `appearanceClassName` and `personalityLabel`. Add `appearanceClassName(player.appearanceId)` to the avatar class. Add a small personality label near the model:

```tsx
<span className="player-roster-model mt-1 block truncate font-mono text-[11px] text-slate-500">
  {player.model}
</span>
<span className="player-roster-model mt-1 block truncate text-[11px] text-amber-200/80">
  {personalityLabel(player.personalityId)}
</span>
```

In `LiveDirectorStage.tsx`, import `appearanceClassName` and add it to the avatar class around `avatarGradient(player.name)`.

In `LivePlayerPanel.tsx`, import `personalityLabel` and show:

```tsx
<p className="text-xs text-slate-500">
  {player.model} · {personalityLabel(player.personalityId)}
</p>
```

- [ ] **Step 6: Run live/replay tests**

Run:

```bash
cd apps/web && pnpm test -- --run src/features/games/liveSpectator.test.ts src/features/games/api/adapters.test.ts
```

Expected: selected tests pass.

- [ ] **Step 7: Commit live/replay display**

Run:

```bash
git add apps/web/src/features/games/liveSpectator.ts apps/web/src/features/games/liveSpectator.test.ts apps/web/src/features/games/api/adapters.ts apps/web/src/features/games/api/adapters.test.ts apps/web/src/features/games/components/PlayerRosterPanel.tsx apps/web/src/features/games/components/LiveDirectorStage.tsx apps/web/src/features/games/components/LivePlayerPanel.tsx
git commit -m "feat(web): display virtual player snapshots"
```

---

### Task 9: Final Verification And Visual QA

**Files:**
- Modify only if verification reveals a defect in files touched by Tasks 1-8.

- [ ] **Step 1: Run full backend test suite**

Run:

```bash
cd apps/api && uv run pytest
```

Expected: all backend tests pass.

- [ ] **Step 2: Run full frontend test suite**

Run:

```bash
cd apps/web && pnpm test -- --run
```

Expected: all frontend tests pass.

- [ ] **Step 3: Run frontend production build**

Run:

```bash
cd apps/web && pnpm build
```

Expected: TypeScript and Vite build complete without errors.

- [ ] **Step 4: Start local frontend**

Run:

```bash
cd apps/web && pnpm dev -- --host 127.0.0.1
```

Expected: Vite reports a local URL, usually `http://127.0.0.1:5173/`.

- [ ] **Step 5: Browser visual QA**

Open `/games` in the in-app Browser. Verify these concrete states:

- `虚拟玩家库` appears above the create form.
- A non-empty profile list shows compact profile cards without overlapping text.
- The create form renders one virtual-player select per selected rule seat.
- Selecting a saved profile for seat 1 keeps the layout stable on desktop and mobile widths.
- Starting a game sends `player_configs` and navigates to `/games/live/:runId`.
- Live seat avatars remain visible and do not obscure role/status labels.

- [ ] **Step 6: Final git status**

Run:

```bash
git status --short
```

Expected: clean worktree after any final fix commit.

---

## Self-Review

Spec coverage:

- Persistent reusable profiles are covered by Tasks 1-2.
- `owner_user_id` is included in the model and response, with `NULL` writes in Task 2.
- Per-run frozen snapshots are covered by Task 3.
- Frontend profile CRUD actions are covered by Task 6.
- Profile selection during game creation is covered by Task 7.
- Live/replay display and legacy defaults are covered by Task 8.
- Verification commands and visual QA are covered by Task 9.
- Non-goals are preserved: no lineup templates, no image generation/upload, no model probing, no rules changes.

Placeholder scan:

- The plan contains concrete paths, test names, commands, and code snippets for each implementation step.
- There are no unresolved placeholder markers.

Type consistency:

- Backend snapshot fields use `personality_id`, `personality`, `appearance_id`, `avatar_prompt`, `profile_id`, and `tags`.
- Frontend API/replay fields keep snake_case for backend payloads.
- Frontend live state maps those fields to `personalityId`, `appearanceId`, `avatarPrompt`, and `profileId`.
