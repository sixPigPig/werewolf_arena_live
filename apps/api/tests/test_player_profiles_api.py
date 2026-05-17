import base64
from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.routes.player_profiles import get_player_avatar_asset_store, get_player_profile_store
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models.user import User
from app.werewolf.player_avatar_assets import PlayerAvatarAssetStore
from app.models.virtual_player_profile import VirtualPlayerProfile
from app.werewolf.player_profile_store import PlayerProfileFileStore
from app.werewolf.player_presets import default_personality_text


engine = create_engine(
    "sqlite+pysqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base.metadata.create_all(engine)


def override_get_db() -> Generator[Session, None, None]:
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture(autouse=True)
def isolated_db() -> Generator[None, None, None]:
    app.dependency_overrides[get_db] = override_get_db
    with TestingSessionLocal() as session:
        session.query(VirtualPlayerProfile).delete()
        session.query(User).delete()
        session.commit()
    yield
    app.dependency_overrides.clear()
    with TestingSessionLocal() as session:
        session.query(VirtualPlayerProfile).delete()
        session.query(User).delete()
        session.commit()


client = TestClient(app)
PNG_BYTES = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGA"
    "WjR9awAAAABJRU5ErkJggg=="
)


class BrokenSession:
    def query(self, *_args: object) -> None:
        raise OperationalError("select", {}, Exception("database unavailable"))

    def add(self, _value: object) -> None:
        pass

    def commit(self) -> None:
        raise OperationalError("commit", {}, Exception("database unavailable"))

    def refresh(self, _value: object) -> None:
        pass

    def rollback(self) -> None:
        pass

    def get(self, *_args: object) -> None:
        raise OperationalError("select", {}, Exception("database unavailable"))

    def close(self) -> None:
        pass


def override_broken_db() -> Generator[BrokenSession, None, None]:
    yield BrokenSession()


def test_create_profile_normalizes_and_fills_defaults() -> None:
    response = client.post(
        "/api/v1/player-profiles",
        json={
            "display_name": "  控场位  ",
            "model": "  gpt-4.1-mini  ",
            "personality_id": "cautious",
            "appearance_id": "moonlit",
            "personality_text": "   ",
            "avatar_prompt": "  silver moon portrait  ",
            "tags": [" 控场 ", "夜晚", "控场", "", " 夜晚 "],
        },
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["display_name"] == "控场位"
    assert payload["model"] == "gpt-4.1-mini"
    assert payload["personality_id"] == "cautious"
    assert payload["personality_text"] == default_personality_text("cautious")
    assert payload["appearance_id"] == "moonlit"
    assert payload["avatar_prompt"] == "silver moon portrait"
    assert payload["tags"] == ["控场", "夜晚"]
    assert payload["owner_user_id"] is None

    with TestingSessionLocal() as session:
        profiles = session.query(VirtualPlayerProfile).all()

    assert len(profiles) == 1
    assert profiles[0].display_name == "控场位"


def test_upload_avatar_image_returns_served_asset_url(tmp_path) -> None:
    app.dependency_overrides[get_player_avatar_asset_store] = lambda: PlayerAvatarAssetStore(
        tmp_path / "player_profile_assets"
    )
    try:
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
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 201
    assert payload["avatar_image_url"].startswith("/api/v1/player-profiles/avatar/")
    assert payload["avatar_image_mime"] == "image/png"
    assert served_response.status_code == 200
    assert served_response.headers["content-type"] == "image/png"
    assert served_response.content == PNG_BYTES


def test_upload_avatar_image_rejects_unsupported_type(tmp_path) -> None:
    app.dependency_overrides[get_player_avatar_asset_store] = lambda: PlayerAvatarAssetStore(
        tmp_path / "player_profile_assets"
    )
    try:
        response = client.post(
            "/api/v1/player-profiles/avatar",
            json={
                "filename": "portrait.txt",
                "content_type": "text/plain",
                "data_base64": base64.b64encode(b"not an image").decode("ascii"),
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 422
    assert response.json()["detail"] == "Unsupported avatar image type"


def test_create_profile_persists_avatar_image_metadata() -> None:
    response = client.post(
        "/api/v1/player-profiles",
        json={
            "display_name": "带图玩家",
            "model": "gpt-4.1-mini",
            "avatar_image_url": "/api/v1/player-profiles/avatar/profile.png",
            "avatar_image_mime": "image/png",
        },
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["avatar_image_url"] == "/api/v1/player-profiles/avatar/profile.png"
    assert payload["avatar_image_mime"] == "image/png"

    with TestingSessionLocal() as session:
        profile = session.get(VirtualPlayerProfile, payload["id"])

    assert profile is not None
    assert profile.avatar_image_url == "/api/v1/player-profiles/avatar/profile.png"
    assert profile.avatar_image_mime == "image/png"


def test_create_profile_accepts_system_avatar_appearance_id() -> None:
    response = client.post(
        "/api/v1/player-profiles",
        json={
            "display_name": "内设形象玩家",
            "model": "gpt-4.1-mini",
            "appearance_id": "gothic-female-2",
            "avatar_image_url": "/player-avatars/gothic-female-2.png",
            "avatar_image_mime": "image/png",
        },
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["appearance_id"] == "gothic-female-2"
    assert payload["avatar_image_url"] == "/player-avatars/gothic-female-2.png"


def test_list_profiles_returns_most_recently_updated_first() -> None:
    created_a = client.post(
        "/api/v1/player-profiles",
        json={"display_name": "A", "model": "model-a"},
    ).json()
    created_b = client.post(
        "/api/v1/player-profiles",
        json={"display_name": "B", "model": "model-b"},
    ).json()

    updated_a = client.patch(
        f"/api/v1/player-profiles/{created_a['id']}",
        json={"display_name": "A updated"},
    ).json()

    response = client.get("/api/v1/player-profiles")

    assert response.status_code == 200
    profiles = response.json()["profiles"]
    assert [profile["id"] for profile in profiles] == [created_a["id"], created_b["id"]]
    assert profiles[0]["display_name"] == updated_a["display_name"]


def test_get_patch_delete_profile() -> None:
    created = client.post(
        "/api/v1/player-profiles",
        json={
            "display_name": "Scout",
            "model": "gpt-4.1-mini",
            "personality_id": "balanced",
            "personality_text": "custom text",
            "appearance_id": "default",
            "tags": ["old"],
        },
    ).json()

    get_response = client.get(f"/api/v1/player-profiles/{created['id']}")
    assert get_response.status_code == 200
    assert get_response.json()["id"] == created["id"]

    patch_response = client.patch(
        f"/api/v1/player-profiles/{created['id']}",
        json={
            "display_name": "  Pressure Lead  ",
            "personality_id": "aggressive",
            "appearance_id": "crimson",
            "tags": [" lead ", "push", "lead"],
        },
    )

    assert patch_response.status_code == 200
    patched = patch_response.json()
    assert patched["display_name"] == "Pressure Lead"
    assert patched["personality_id"] == "aggressive"
    assert patched["personality_text"] == default_personality_text("aggressive")
    assert patched["appearance_id"] == "crimson"
    assert patched["tags"] == ["lead", "push"]

    delete_response = client.delete(f"/api/v1/player-profiles/{created['id']}")
    assert delete_response.status_code == 204
    assert delete_response.content == b""

    missing_response = client.get(f"/api/v1/player-profiles/{created['id']}")
    assert missing_response.status_code == 404
    assert missing_response.json()["detail"] == "Player profile not found"


@pytest.mark.parametrize("field_name", ["display_name", "model", "avatar_prompt", "tags"])
def test_patch_profile_rejects_null_non_nullable_fields(field_name: str) -> None:
    created = client.post(
        "/api/v1/player-profiles",
        json={
            "display_name": "Scout",
            "model": "gpt-4.1-mini",
            "personality_id": "balanced",
            "personality_text": "custom text",
            "appearance_id": "default",
            "avatar_prompt": "moonlit portrait",
            "tags": ["old"],
        },
    ).json()
    original = client.get(f"/api/v1/player-profiles/{created['id']}").json()

    response = client.patch(
        f"/api/v1/player-profiles/{created['id']}",
        json={field_name: None},
    )

    assert response.status_code == 422
    persisted = client.get(f"/api/v1/player-profiles/{created['id']}").json()
    assert persisted == original


@pytest.mark.parametrize(
    ("payload", "expected_detail"),
    [
        ({"display_name": "   ", "model": "gpt-4.1-mini"}, None),
        ({"display_name": "Valid", "model": "   "}, None),
        (
            {"display_name": "Valid", "model": "gpt-4.1-mini", "personality_id": "mystery"},
            "Unknown personality_id: mystery",
        ),
        (
            {"display_name": "Valid", "model": "gpt-4.1-mini", "appearance_id": "neon"},
            "Unknown appearance_id: neon",
        ),
        (
            {
                "display_name": "Valid",
                "model": "gpt-4.1-mini",
                "avatar_prompt": "x" * 1001,
            },
            None,
        ),
        (
            {
                "display_name": "Valid",
                "model": "gpt-4.1-mini",
                "tags": ["a", "b", "c", "d", "e", "f", "g", "h", "i"],
            },
            None,
        ),
    ],
)
def test_create_profile_validation_errors(payload: dict, expected_detail: str | None) -> None:
    response = client.post("/api/v1/player-profiles", json=payload)

    assert response.status_code == 422
    if expected_detail is not None:
        assert response.json()["detail"] == expected_detail


def test_profiles_fall_back_to_local_file_when_database_is_unavailable(
    tmp_path,
) -> None:
    app.dependency_overrides[get_db] = override_broken_db
    app.dependency_overrides[get_player_profile_store] = lambda: PlayerProfileFileStore(
        tmp_path / "player_profiles.json"
    )
    try:
        create_response = client.post(
            "/api/v1/player-profiles",
            json={
                "display_name": "  本地玩家  ",
                "model": "deepseek-v4-flash",
                "personality_id": "cautious",
                "appearance_id": "moonlit",
                "tags": [" 本地 ", "本地"],
            },
        )
        list_response = client.get("/api/v1/player-profiles")
    finally:
        app.dependency_overrides.clear()

    assert create_response.status_code == 201
    created = create_response.json()
    assert created["display_name"] == "本地玩家"
    assert created["personality_text"] == default_personality_text("cautious")
    assert created["appearance_id"] == "moonlit"
    assert created["tags"] == ["本地"]

    assert list_response.status_code == 200
    assert list_response.json()["profiles"][0]["id"] == created["id"]


def test_create_profile_persists_rich_character_settings() -> None:
    response = client.post(
        "/api/v1/player-profiles",
        json={
            "display_name": "夜谈控场",
            "model": "deepseek-v4-flash",
            "short_description": "沉稳控场，喜欢先盘逻辑再给站边。",
            "background_story": "长期观察圆桌局的复盘型玩家。",
            "speaking_style": "短句推进，先列证据，再给结论。",
            "catchphrases": ["我先盘票型", "这里不急着站死"],
            "strategy_profile": "logic_leader",
            "risk_tolerance": 2,
            "bluffing_tendency": 2,
            "trust_tendency": 3,
            "leadership_tendency": 5,
            "talkativeness": 4,
            "example_messages": ["我认为 3 号这一轮的视角不完整，先听后置位补充。"],
            "favorite": True,
        },
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["short_description"] == "沉稳控场，喜欢先盘逻辑再给站边。"
    assert payload["catchphrases"] == ["我先盘票型", "这里不急着站死"]
    assert payload["strategy_profile"] == "logic_leader"
    assert payload["risk_tolerance"] == 2
    assert payload["leadership_tendency"] == 5
    assert payload["example_messages"] == ["我认为 3 号这一轮的视角不完整，先听后置位补充。"]
    assert payload["favorite"] is True


def test_create_profile_rejects_invalid_strategy_slider_values() -> None:
    response = client.post(
        "/api/v1/player-profiles",
        json={
            "display_name": "越界玩家",
            "model": "deepseek-v4-flash",
            "strategy_profile": "unknown",
            "risk_tolerance": 6,
        },
    )

    assert response.status_code == 422


def test_create_profile_rejects_catchphrase_longer_than_40_characters() -> None:
    long_catchphrase = "啊" * 41
    response = client.post(
        "/api/v1/player-profiles",
        json={
            "display_name": "长口头禅玩家",
            "model": "deepseek-v4-flash",
            "catchphrases": [long_catchphrase],
        },
    )

    assert response.status_code == 422


def test_update_profile_rejects_catchphrase_longer_than_40_characters() -> None:
    long_catchphrase = "啊" * 41
    created = client.post(
        "/api/v1/player-profiles",
        json={
            "display_name": "长口头禅更新玩家",
            "model": "deepseek-v4-flash",
        },
    ).json()

    response = client.patch(
        f"/api/v1/player-profiles/{created['id']}",
        json={"catchphrases": [long_catchphrase]},
    )

    assert response.status_code == 422
