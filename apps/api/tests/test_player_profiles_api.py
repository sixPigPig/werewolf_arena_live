import base64
import json
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


def test_create_profile_returns_rich_character_defaults() -> None:
    response = client.post(
        "/api/v1/player-profiles",
        json={"display_name": "默认玩家", "model": "deepseek-v4-flash"},
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["short_description"] == ""
    assert payload["background_story"] == ""
    assert payload["speaking_style"] == ""
    assert payload["catchphrases"] == []
    assert payload["strategy_profile"] == "balanced"
    assert payload["risk_tolerance"] == 3
    assert payload["bluffing_tendency"] == 3
    assert payload["trust_tendency"] == 3
    assert payload["leadership_tendency"] == 3
    assert payload["talkativeness"] == 3
    assert payload["example_messages"] == []
    assert payload["favorite"] is False


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


def test_player_profile_file_store_reads_old_payload_with_rich_defaults_and_writes_v3(
    tmp_path,
) -> None:
    path = tmp_path / "player_profiles.json"
    path.write_text(
        json.dumps(
            {
                "version": 2,
                "profiles": [
                    {
                        "id": "legacy-profile",
                        "display_name": "旧档玩家",
                        "model": "deepseek-v4-flash",
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    store = PlayerProfileFileStore(path)

    legacy = store.get_profile("legacy-profile")

    assert legacy is not None
    assert legacy.short_description == ""
    assert legacy.background_story == ""
    assert legacy.speaking_style == ""
    assert legacy.catchphrases == []
    assert legacy.strategy_profile == "balanced"
    assert legacy.risk_tolerance == 3
    assert legacy.bluffing_tendency == 3
    assert legacy.trust_tendency == 3
    assert legacy.leadership_tendency == 3
    assert legacy.talkativeness == 3
    assert legacy.example_messages == []
    assert legacy.favorite is False

    store.create_profile(
        display_name="新玩家",
        model="deepseek-v4-flash",
        personality_id="balanced",
        personality_text="",
        appearance_id="default",
        avatar_prompt="",
        tags=[],
    )
    payload_after_create = json.loads(path.read_text(encoding="utf-8"))
    legacy_payload = next(
        profile
        for profile in payload_after_create["profiles"]
        if profile["id"] == "legacy-profile"
    )

    assert payload_after_create["version"] == 3
    assert legacy_payload["short_description"] == ""
    assert legacy_payload["catchphrases"] == []
    assert legacy_payload["strategy_profile"] == "balanced"
    assert legacy_payload["risk_tolerance"] == 3
    assert legacy_payload["favorite"] is False

    updated = store.update_profile(
        "legacy-profile",
        {
            "short_description": "旧档补齐简介",
            "catchphrases": ["补齐口头禅"],
            "favorite": True,
        },
    )
    payload_after_update = json.loads(path.read_text(encoding="utf-8"))

    assert updated is not None
    assert updated.short_description == "旧档补齐简介"
    assert updated.catchphrases == ["补齐口头禅"]
    assert updated.favorite is True
    assert payload_after_update["version"] == 3


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


def test_create_profile_normalizes_rich_character_lists() -> None:
    response = client.post(
        "/api/v1/player-profiles",
        json={
            "display_name": "去重玩家",
            "model": "deepseek-v4-flash",
            "catchphrases": [" 我先盘票型 ", "", "我先盘票型", " 这里不急 "],
            "example_messages": [" 先听后置位补充。 ", "", "先听后置位补充。", " 票型先记下来。 "],
        },
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["catchphrases"] == ["我先盘票型", "这里不急"]
    assert payload["example_messages"] == ["先听后置位补充。", "票型先记下来。"]


@pytest.mark.parametrize(
    "payload",
    [
        {"catchphrases": [{"x": 1}]},
        {"example_messages": [123]},
    ],
)
def test_create_profile_rejects_non_string_rich_character_list_items(payload: dict) -> None:
    response = client.post(
        "/api/v1/player-profiles",
        json={
            "display_name": "非字符串列表玩家",
            "model": "deepseek-v4-flash",
            **payload,
        },
    )

    assert response.status_code == 422


def test_create_profile_rejects_invalid_strategy_profile() -> None:
    response = client.post(
        "/api/v1/player-profiles",
        json={
            "display_name": "越界玩家",
            "model": "deepseek-v4-flash",
            "strategy_profile": "unknown",
        },
    )

    assert response.status_code == 422


def test_create_profile_rejects_invalid_numeric_slider_value() -> None:
    response = client.post(
        "/api/v1/player-profiles",
        json={
            "display_name": "滑杆越界玩家",
            "model": "deepseek-v4-flash",
            "strategy_profile": "balanced",
            "risk_tolerance": 6,
        },
    )

    assert response.status_code == 422


def test_create_profile_rejects_too_long_background_story() -> None:
    response = client.post(
        "/api/v1/player-profiles",
        json={
            "display_name": "背景过长玩家",
            "model": "deepseek-v4-flash",
            "background_story": "啊" * 1201,
        },
    )

    assert response.status_code == 422


def test_update_profile_rejects_too_long_speaking_style() -> None:
    created = client.post(
        "/api/v1/player-profiles",
        json={"display_name": "发言风格过长玩家", "model": "deepseek-v4-flash"},
    ).json()

    response = client.patch(
        f"/api/v1/player-profiles/{created['id']}",
        json={"speaking_style": "啊" * 801},
    )

    assert response.status_code == 422


def test_create_profile_rejects_more_than_6_catchphrases() -> None:
    response = client.post(
        "/api/v1/player-profiles",
        json={
            "display_name": "口头禅太多",
            "model": "deepseek-v4-flash",
            "catchphrases": [f"口头禅{index}" for index in range(7)],
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


@pytest.mark.parametrize(
    "example_messages",
    [
        [f"示例发言{index}" for index in range(6)],
        ["啊" * 241],
    ],
)
def test_create_profile_rejects_invalid_example_messages(example_messages: list[str]) -> None:
    response = client.post(
        "/api/v1/player-profiles",
        json={
            "display_name": "示例发言越界",
            "model": "deepseek-v4-flash",
            "example_messages": example_messages,
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


def test_patch_profile_persists_rich_character_settings() -> None:
    created = client.post(
        "/api/v1/player-profiles",
        json={"display_name": "待更新玩家", "model": "deepseek-v4-flash"},
    ).json()

    patch_response = client.patch(
        f"/api/v1/player-profiles/{created['id']}",
        json={
            "short_description": "更新后的控场简介",
            "background_story": "复盘多年圆桌局后形成的打法。",
            "speaking_style": "先拆视角，再压缩狼坑。",
            "catchphrases": ["先盘票型", "后置位补充"],
            "strategy_profile": "pressure_attacker",
            "risk_tolerance": 4,
            "bluffing_tendency": 2,
            "trust_tendency": 1,
            "leadership_tendency": 5,
            "talkativeness": 4,
            "example_messages": ["这一轮我会先压 7 号解释票型。"],
            "favorite": True,
        },
    )

    assert patch_response.status_code == 200
    patched = patch_response.json()
    assert patched["short_description"] == "更新后的控场简介"
    assert patched["background_story"] == "复盘多年圆桌局后形成的打法。"
    assert patched["speaking_style"] == "先拆视角，再压缩狼坑。"
    assert patched["catchphrases"] == ["先盘票型", "后置位补充"]
    assert patched["strategy_profile"] == "pressure_attacker"
    assert patched["risk_tolerance"] == 4
    assert patched["bluffing_tendency"] == 2
    assert patched["trust_tendency"] == 1
    assert patched["leadership_tendency"] == 5
    assert patched["talkativeness"] == 4
    assert patched["example_messages"] == ["这一轮我会先压 7 号解释票型。"]
    assert patched["favorite"] is True

    with TestingSessionLocal() as session:
        stored = session.get(VirtualPlayerProfile, created["id"])

    assert stored is not None
    assert stored.short_description == "更新后的控场简介"
    assert stored.catchphrases == ["先盘票型", "后置位补充"]
    assert stored.strategy_profile == "pressure_attacker"
    assert stored.risk_tolerance == 4
    assert stored.example_messages == ["这一轮我会先压 7 号解释票型。"]
    assert stored.favorite is True
