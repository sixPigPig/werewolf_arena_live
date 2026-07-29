import base64
import json
from collections.abc import Generator
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.routes import player_profiles as player_profiles_routes
from app.core.config import settings
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models.model_configuration import ModelConfigurationRecord
from app.models.player_avatar_asset import PlayerAvatarAsset
from app.models.user import User
from app.models.virtual_player_profile import VirtualPlayerProfile
from app.werewolf.player_avatar_assets import create_avatar_asset, decode_avatar_asset_data
from app.werewolf.player_profile_store import PlayerProfileFileStore
from app.werewolf.player_presets import default_personality_text


engine = create_engine(
    "sqlite+pysqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base.metadata.create_all(engine)
TEST_MODEL_PROVIDER = "deepseek"
TEST_MODEL_IDS = (
    "deepseek-v4-flash",
    "gpt-4.1-mini",
    "model-a",
    "model-b",
    "model-c",
)
with TestingSessionLocal.begin() as session:
    for index, model_id in enumerate(TEST_MODEL_IDS):
        session.add(
            ModelConfigurationRecord(
                provider=TEST_MODEL_PROVIDER,
                model_id=model_id,
                source_model_id=model_id,
                display_name=model_id,
                available=True,
                enabled=True,
                is_default=index == 0,
                supports_thinking=True,
                parameter_values={"thinking": "default"},
                source_details={"source": "test"},
            )
        )


def override_get_db() -> Generator[Session, None, None]:
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture(autouse=True)
def isolated_db(monkeypatch: pytest.MonkeyPatch) -> Generator[None, None, None]:
    monkeypatch.setattr(settings, "legacy_player_profile_content_writes_enabled", True)
    app.dependency_overrides[get_db] = override_get_db
    with TestingSessionLocal() as session:
        session.query(VirtualPlayerProfile).delete()
        session.query(PlayerAvatarAsset).delete()
        session.query(User).delete()
        session.commit()
    yield
    app.dependency_overrides.clear()
    with TestingSessionLocal() as session:
        session.query(VirtualPlayerProfile).delete()
        session.query(PlayerAvatarAsset).delete()
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


class FakeAiProvider:
    def __init__(self, response: object) -> None:
        self.response = response
        self.calls: list[dict[str, object]] = []

    def complete_json(self, *, model: str, prompt: str, temperature: float) -> str:
        self.calls.append({"model": model, "prompt": prompt, "temperature": temperature})
        return json.dumps(self.response, ensure_ascii=False)


def test_generate_ai_player_name_uses_deepseek_v4_flash_and_avoids_duplicates() -> None:
    provider = FakeAiProvider({"display_name": "银刃听雪"})
    app.dependency_overrides[player_profiles_routes.get_player_profile_ai_provider] = (
        lambda: provider
    )
    try:
        response = client.post(
            "/api/v1/player-profiles/ai-draft",
            json={"mode": "name", "existing_names": ["银刃听雪"]},
        )
    finally:
        app.dependency_overrides.pop(player_profiles_routes.get_player_profile_ai_provider, None)

    assert response.status_code == 200
    payload = response.json()
    assert provider.calls[0]["model"] == "deepseek-v4-flash"
    assert "狼人杀" in str(provider.calls[0]["prompt"])
    assert "票型" in str(provider.calls[0]["prompt"])
    assert payload["display_name"] == "银刃听雪 2"


def test_generate_ai_player_template_normalizes_generated_fields() -> None:
    provider = FakeAiProvider(
        {
            "display_name": "雾灯司南",
            "personality_id": "analytical",
            "personality_text": "习惯从票型和发言顺序里拆阵营。",
            "short_description": "冷静复盘，擅长拆票型。",
            "background_story": "长期在高阶圆桌局做复盘记录。",
            "speaking_style": "先列证据，再给结论。",
            "strategy_profile": "logic_leader",
            "risk_tolerance": 2,
            "bluffing_tendency": 2,
            "trust_tendency": 3,
            "leadership_tendency": 5,
            "talkativeness": 4,
            "example_messages": ["3 号这一轮补视角太晚，我会先标记。"],
            "tags": ["复盘", "控场", "复盘"],
        }
    )
    app.dependency_overrides[player_profiles_routes.get_player_profile_ai_provider] = (
        lambda: provider
    )
    try:
        response = client.post(
            "/api/v1/player-profiles/ai-draft",
            json={"mode": "template", "existing_names": []},
        )
    finally:
        app.dependency_overrides.pop(player_profiles_routes.get_player_profile_ai_provider, None)

    assert response.status_code == 200
    payload = response.json()
    assert provider.calls[0]["model"] == "deepseek-v4-flash"
    assert payload["display_name"] == "雾灯司南"
    assert payload["personality_id"] == "analytical"
    assert payload["strategy_profile"] == "logic_leader"
    assert payload["leadership_tendency"] == 5
    assert "catchphrases" not in payload
    assert payload["tags"] == ["复盘", "控场"]


def test_generate_ai_player_template_accepts_nested_model_payload() -> None:
    provider = FakeAiProvider(
        {
            "Alpha_阿夜": {
                "display_name": "Alpha 阿夜",
                "personality_id": "aggressive",
                "short_description": "高压追问，快速拆矛盾。",
                "strategy_profile": "pressure_attacker",
                "risk_tolerance": 5,
                "leadership_tendency": 4,
                "tags": ["强压", "提问"],
            },
            "Bravo_青岚": {
                "display_name": "Bravo 青岚",
                "personality_id": "analytical",
                "short_description": "冷静复盘，擅长拆票型。",
                "strategy_profile": "logic_leader",
                "risk_tolerance": 2,
                "leadership_tendency": 5,
                "tags": ["复盘", "控场"],
            },
        }
    )
    app.dependency_overrides[player_profiles_routes.get_player_profile_ai_provider] = (
        lambda: provider
    )
    try:
        response = client.post(
            "/api/v1/player-profiles/ai-draft",
            json={"mode": "template", "existing_names": ["Alpha 阿夜", "Bravo 青岚"]},
        )
    finally:
        app.dependency_overrides.pop(player_profiles_routes.get_player_profile_ai_provider, None)

    assert response.status_code == 200
    payload = response.json()
    assert payload["display_name"] == "Alpha 阿夜 2"
    assert payload["personality_id"] == "aggressive"
    assert payload["strategy_profile"] == "pressure_attacker"
    assert payload["tags"] == ["强压", "提问"]


def test_generate_ai_player_template_accepts_list_model_payload() -> None:
    provider = FakeAiProvider(
        [
            {
                "display_name": "雾灯司南",
                "personality_id": "analytical",
                "short_description": "冷静复盘，擅长拆票型。",
                "strategy_profile": "logic_leader",
                "risk_tolerance": 2,
                "leadership_tendency": 5,
                "tags": ["复盘", "控场"],
            }
        ]
    )
    app.dependency_overrides[player_profiles_routes.get_player_profile_ai_provider] = (
        lambda: provider
    )
    try:
        response = client.post(
            "/api/v1/player-profiles/ai-draft",
            json={"mode": "template", "existing_names": []},
        )
    finally:
        app.dependency_overrides.pop(player_profiles_routes.get_player_profile_ai_provider, None)

    assert response.status_code == 200
    payload = response.json()
    assert payload["display_name"] == "雾灯司南"
    assert payload["personality_id"] == "analytical"
    assert payload["strategy_profile"] == "logic_leader"


def test_create_profile_normalizes_and_fills_defaults() -> None:
    response = client.post(
        "/api/v1/player-profiles",
        json={
            "display_name": "  控场位  ",
            "model_provider": f"  {TEST_MODEL_PROVIDER}  ",
            "model": "  gpt-4.1-mini  ",
            "personality_id": "cautious",
            "appearance_id": "moonlit",
            "personality_text": "   ",
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
    assert payload["tags"] == ["控场", "夜晚"]

    with TestingSessionLocal() as session:
        profiles = session.query(VirtualPlayerProfile).all()

    assert len(profiles) == 1
    assert profiles[0].display_name == "控场位"


def test_create_profile_returns_rich_character_defaults() -> None:
    response = client.post(
        "/api/v1/player-profiles",
        json={
            "display_name": "默认玩家",
            "model_provider": TEST_MODEL_PROVIDER,
            "model": "deepseek-v4-flash",
        },
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["short_description"] == ""
    assert payload["background_story"] == ""
    assert payload["speaking_style"] == ""
    assert "catchphrases" not in payload
    assert payload["strategy_profile"] == "balanced"
    assert payload["risk_tolerance"] == 3
    assert payload["bluffing_tendency"] == 3
    assert payload["trust_tendency"] == 3
    assert payload["leadership_tendency"] == 3
    assert payload["talkativeness"] == 3
    assert payload["example_messages"] == []


@pytest.mark.parametrize(
    ("field_name", "value"),
    [
        ("favorite", True),
        ("owner_user_id", 7),
        ("avatar_prompt", "unused prompt"),
        ("avatar_image_path", "/tmp/unused.png"),
    ],
)
def test_legacy_create_rejects_removed_profile_fields(
    field_name: str,
    value: object,
) -> None:
    response = client.post(
        "/api/v1/player-profiles",
        json={
            "display_name": "旧字段测试",
            "model_provider": TEST_MODEL_PROVIDER,
            "model": "deepseek-v4-flash",
            field_name: value,
        },
    )

    assert response.status_code == 422
    with TestingSessionLocal() as session:
        assert session.query(VirtualPlayerProfile).count() == 0


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
    asset_id = payload["avatar_asset_id"]
    assert asset_id.startswith("uploaded-")
    assert payload["avatar_image_url"] == f"/api/v1/player-profiles/avatar-assets/{asset_id}"
    assert payload["avatar_image_mime"] == "image/png"
    assert served_response.status_code == 200
    assert served_response.headers["content-type"] == "image/png"
    assert (
        served_response.headers["cache-control"]
        == "public, max-age=31536000, immutable"
    )
    assert served_response.content == PNG_BYTES

    with TestingSessionLocal() as session:
        asset = session.get(PlayerAvatarAsset, asset_id)

    assert asset is not None
    assert asset.source == "uploaded"
    assert asset.content_type == "image/png"
    assert asset.data_base64 == base64.b64encode(PNG_BYTES).decode("ascii")
    assert decode_avatar_asset_data(asset) == PNG_BYTES
    assert asset.size_bytes == len(PNG_BYTES)


def test_upload_avatar_image_normalizes_jpg_alias_and_reuses_database_asset() -> None:
    first_response = client.post(
        "/api/v1/player-profiles/avatar",
        json={
            "filename": "portrait.jpg",
            "content_type": "image/jpg",
            "data_base64": base64.b64encode(PNG_BYTES).decode("ascii"),
        },
    )
    second_response = client.post(
        "/api/v1/player-profiles/avatar",
        json={
            "filename": "portrait.jpeg",
            "content_type": " image/jpeg ",
            "data_base64": base64.b64encode(PNG_BYTES).decode("ascii"),
        },
    )
    first_payload = first_response.json()
    second_payload = second_response.json()
    served_response = client.get(first_payload["avatar_image_url"])

    assert first_response.status_code == 201
    assert second_response.status_code == 201
    assert first_payload["avatar_asset_id"] == second_payload["avatar_asset_id"]
    assert first_payload["avatar_image_mime"] == "image/jpeg"
    assert second_payload["avatar_image_mime"] == "image/jpeg"
    assert served_response.status_code == 200
    assert served_response.headers["content-type"] == "image/jpeg"
    assert served_response.content == PNG_BYTES


def test_create_avatar_asset_normalizes_content_type_for_dedupe() -> None:
    with TestingSessionLocal() as session:
        first_asset = create_avatar_asset(
            session,
            content_type="image/jpg",
            data=PNG_BYTES,
            source="uploaded",
        )
        session.commit()
        first_asset_id = first_asset.id

        second_asset = create_avatar_asset(
            session,
            content_type=" image/jpeg ",
            data=PNG_BYTES,
            source="uploaded",
        )
        session.commit()

        assets = session.query(PlayerAvatarAsset).all()

    assert second_asset.id == first_asset_id
    assert len(assets) == 1
    assert assets[0].content_type == "image/jpeg"


def test_get_avatar_asset_returns_404_for_missing_asset() -> None:
    response = client.get("/api/v1/player-profiles/avatar-assets/missing-asset")

    assert response.status_code == 404
    assert response.json()["detail"] == "Avatar asset not found"


def test_get_avatar_asset_rejects_corrupted_base64_data() -> None:
    with TestingSessionLocal() as session:
        asset = create_avatar_asset(
            session,
            asset_id="corrupted-avatar",
            content_type="image/png",
            data=PNG_BYTES,
            source="uploaded",
        )
        asset.data_base64 = "not-valid-base64"
        session.commit()

    response = client.get("/api/v1/player-profiles/avatar-assets/corrupted-avatar")

    assert response.status_code == 500
    assert response.json()["detail"] == "Avatar asset data is invalid"


def test_upload_avatar_image_returns_503_when_database_is_unavailable() -> None:
    app.dependency_overrides[get_db] = override_broken_db
    try:
        response = client.post(
            "/api/v1/player-profiles/avatar",
            json={
                "filename": "portrait.png",
                "content_type": "image/png",
                "data_base64": base64.b64encode(PNG_BYTES).decode("ascii"),
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 503
    assert response.json()["detail"] == "Player profile database unavailable"


def test_get_avatar_asset_returns_503_when_database_is_unavailable() -> None:
    app.dependency_overrides[get_db] = override_broken_db
    try:
        response = client.get("/api/v1/player-profiles/avatar-assets/uploaded-missing")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 503
    assert response.json()["detail"] == "Player profile database unavailable"


def test_legacy_avatar_file_route_is_removed() -> None:
    response = client.get("/api/v1/player-profiles/avatar/legacy.png")

    assert response.status_code == 404


def test_upload_avatar_image_rejects_unsupported_type() -> None:
    response = client.post(
        "/api/v1/player-profiles/avatar",
        json={
            "filename": "portrait.txt",
            "content_type": "text/plain",
            "data_base64": base64.b64encode(b"not an image").decode("ascii"),
        },
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "Unsupported avatar image type"


def test_create_profile_binds_system_avatar_from_appearance_id() -> None:
    response = client.post(
        "/api/v1/player-profiles",
        json={
            "display_name": "内设形象玩家",
            "model_provider": TEST_MODEL_PROVIDER,
            "model": "gpt-4.1-mini",
            "appearance_id": "gothic-female-2",
        },
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["appearance_id"] == "gothic-female-2"
    assert payload["avatar_asset_id"] == "system-gothic-female-2"
    assert (
        payload["avatar_image_url"]
        == "/api/v1/player-profiles/avatar-assets/system-gothic-female-2"
    )
    assert payload["avatar_image_mime"] == "image/png"

    with TestingSessionLocal() as session:
        profile = session.get(VirtualPlayerProfile, payload["id"])

    assert profile is not None
    assert profile.avatar_asset_id == "system-gothic-female-2"
    assert (
        profile.avatar_image_url
        == "/api/v1/player-profiles/avatar-assets/system-gothic-female-2"
    )
    assert profile.avatar_image_mime == "image/png"


def test_create_profile_normalizes_legacy_system_avatar_url() -> None:
    response = client.post(
        "/api/v1/player-profiles",
        json={
            "display_name": "旧系统形象玩家",
            "model_provider": TEST_MODEL_PROVIDER,
            "model": "gpt-4.1-mini",
            "appearance_id": "default",
            "avatar_image_url": "/player-avatars/gothic-male-1.png",
            "avatar_image_mime": "image/png",
        },
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["avatar_asset_id"] == "system-gothic-male-1"
    assert (
        payload["avatar_image_url"]
        == "/api/v1/player-profiles/avatar-assets/system-gothic-male-1"
    )
    assert payload["avatar_image_mime"] == "image/png"


def test_create_profile_rejects_legacy_file_url_even_when_appearance_is_set() -> None:
    response = client.post(
        "/api/v1/player-profiles",
        json={
            "display_name": "显式旧头像玩家",
            "model_provider": TEST_MODEL_PROVIDER,
            "model": "gpt-4.1-mini",
            "appearance_id": "gothic-male-1",
            "avatar_image_url": "/api/v1/player-profiles/avatar/legacy.png",
            "avatar_image_mime": "image/png",
        },
    )

    assert response.status_code == 422
    assert (
        response.json()["detail"]
        == "Legacy file-backed avatar URLs are no longer supported"
    )


def test_create_profile_rejects_missing_legacy_uploaded_avatar_file() -> None:
    response = client.post(
        "/api/v1/player-profiles",
        json={
            "display_name": "缺失旧头像玩家",
            "model_provider": TEST_MODEL_PROVIDER,
            "model": "gpt-4.1-mini",
            "avatar_image_url": "/api/v1/player-profiles/avatar/missing.png",
            "avatar_image_mime": "image/png",
        },
    )

    assert response.status_code == 422
    assert (
        response.json()["detail"]
        == "Legacy file-backed avatar URLs are no longer supported"
    )


def test_create_profile_rejects_missing_explicit_legacy_url_before_appearance() -> None:
    response = client.post(
        "/api/v1/player-profiles",
        json={
            "display_name": "缺失显式旧头像玩家",
            "model_provider": TEST_MODEL_PROVIDER,
            "model": "gpt-4.1-mini",
            "appearance_id": "gothic-male-1",
            "avatar_image_url": "/api/v1/player-profiles/avatar/missing.png",
            "avatar_image_mime": "image/png",
        },
    )

    assert response.status_code == 422
    assert (
        response.json()["detail"]
        == "Legacy file-backed avatar URLs are no longer supported"
    )


def test_create_profile_preserves_explicit_external_avatar_url_before_appearance() -> None:
    response = client.post(
        "/api/v1/player-profiles",
        json={
            "display_name": "外部头像玩家",
            "model_provider": TEST_MODEL_PROVIDER,
            "model": "gpt-4.1-mini",
            "appearance_id": "gothic-female-2",
            "avatar_image_url": "https://example.test/avatar.png",
            "avatar_image_mime": "image/png",
        },
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["avatar_asset_id"] is None
    assert payload["avatar_image_url"] == "https://example.test/avatar.png"
    assert payload["avatar_image_mime"] == "image/png"

    with TestingSessionLocal() as session:
        profile = session.get(VirtualPlayerProfile, payload["id"])

    assert profile is not None
    assert profile.avatar_asset_id is None
    assert profile.avatar_image_url == "https://example.test/avatar.png"


def test_create_profile_binds_database_avatar_asset_from_explicit_url() -> None:
    with TestingSessionLocal() as session:
        asset = create_avatar_asset(
            session,
            asset_id="uploaded-url-only-avatar",
            content_type="image/png",
            data=PNG_BYTES,
            source="uploaded",
        )
        asset_id = asset.id
        session.commit()

    response = client.post(
        "/api/v1/player-profiles",
        json={
            "display_name": "URL 绑定头像玩家",
            "model_provider": TEST_MODEL_PROVIDER,
            "model": "gpt-4.1-mini",
            "appearance_id": "gothic-male-1",
            "avatar_image_url": "/api/v1/player-profiles/avatar-assets/uploaded-url-only-avatar",
        },
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["avatar_asset_id"] == asset_id
    assert payload["avatar_image_url"] == "/api/v1/player-profiles/avatar-assets/uploaded-url-only-avatar"
    assert payload["avatar_image_mime"] == "image/png"


def test_patch_profile_binds_database_avatar_asset_id() -> None:
    created = client.post(
        "/api/v1/player-profiles",
        json={
            "display_name": "待绑定头像玩家",
            "model_provider": TEST_MODEL_PROVIDER,
            "model": "gpt-4.1-mini",
        },
    ).json()
    upload_response = client.post(
        "/api/v1/player-profiles/avatar",
        json={
            "filename": "portrait.png",
            "content_type": "image/png",
            "data_base64": base64.b64encode(PNG_BYTES).decode("ascii"),
        },
    )
    uploaded = upload_response.json()

    patch_response = client.patch(
        f"/api/v1/player-profiles/{created['id']}",
        json={"avatar_asset_id": uploaded["avatar_asset_id"]},
    )

    assert patch_response.status_code == 200
    patched = patch_response.json()
    assert patched["avatar_asset_id"] == uploaded["avatar_asset_id"]
    assert patched["avatar_image_url"] == uploaded["avatar_image_url"]
    assert patched["avatar_image_mime"] == "image/png"

    with TestingSessionLocal() as session:
        stored = session.get(VirtualPlayerProfile, created["id"])

    assert stored is not None
    assert stored.avatar_asset_id == uploaded["avatar_asset_id"]
    assert stored.avatar_image_url == uploaded["avatar_image_url"]


def test_patch_profile_binds_database_avatar_asset_from_explicit_url() -> None:
    created = client.post(
        "/api/v1/player-profiles",
        json={
            "display_name": "待 URL 绑定头像玩家",
            "model_provider": TEST_MODEL_PROVIDER,
            "model": "gpt-4.1-mini",
        },
    ).json()
    upload_response = client.post(
        "/api/v1/player-profiles/avatar",
        json={
            "filename": "portrait.png",
            "content_type": "image/png",
            "data_base64": base64.b64encode(PNG_BYTES).decode("ascii"),
        },
    )
    uploaded = upload_response.json()

    patch_response = client.patch(
        f"/api/v1/player-profiles/{created['id']}",
        json={"avatar_image_url": uploaded["avatar_image_url"]},
    )

    assert patch_response.status_code == 200
    patched = patch_response.json()
    assert patched["avatar_asset_id"] == uploaded["avatar_asset_id"]
    assert patched["avatar_image_url"] == uploaded["avatar_image_url"]
    assert patched["avatar_image_mime"] == "image/png"

    with TestingSessionLocal() as session:
        stored = session.get(VirtualPlayerProfile, created["id"])

    assert stored is not None
    assert stored.avatar_asset_id == uploaded["avatar_asset_id"]


def test_patch_profile_clears_database_avatar_asset_when_set_to_null() -> None:
    created = client.post(
        "/api/v1/player-profiles",
        json={
            "display_name": "待清空头像玩家",
            "model_provider": TEST_MODEL_PROVIDER,
            "model": "gpt-4.1-mini",
        },
    ).json()
    uploaded = client.post(
        "/api/v1/player-profiles/avatar",
        json={
            "filename": "portrait.png",
            "content_type": "image/png",
            "data_base64": base64.b64encode(PNG_BYTES).decode("ascii"),
        },
    ).json()
    client.patch(
        f"/api/v1/player-profiles/{created['id']}",
        json={"avatar_asset_id": uploaded["avatar_asset_id"]},
    )

    patch_response = client.patch(
        f"/api/v1/player-profiles/{created['id']}",
        json={"avatar_asset_id": None},
    )

    assert patch_response.status_code == 200
    patched = patch_response.json()
    assert patched["avatar_asset_id"] is None
    assert patched["avatar_image_url"] == ""
    assert patched["avatar_image_mime"] == ""

    with TestingSessionLocal() as session:
        stored = session.get(VirtualPlayerProfile, created["id"])

    assert stored is not None
    assert stored.avatar_asset_id is None
    assert stored.avatar_image_url == ""
    assert stored.avatar_image_mime == ""


def test_patch_profile_normalizes_legacy_system_avatar_url() -> None:
    created = client.post(
        "/api/v1/player-profiles",
        json={
            "display_name": "待更新系统头像玩家",
            "model_provider": TEST_MODEL_PROVIDER,
            "model": "gpt-4.1-mini",
        },
    ).json()

    patch_response = client.patch(
        f"/api/v1/player-profiles/{created['id']}",
        json={
            "avatar_image_url": "/player-avatars/gothic-male-2.png",
            "avatar_image_mime": "image/png",
        },
    )

    assert patch_response.status_code == 200
    patched = patch_response.json()
    assert patched["avatar_asset_id"] == "system-gothic-male-2"
    assert (
        patched["avatar_image_url"]
        == "/api/v1/player-profiles/avatar-assets/system-gothic-male-2"
    )
    assert patched["avatar_image_mime"] == "image/png"


def test_patch_profile_rejects_missing_legacy_uploaded_avatar_file() -> None:
    created = client.post(
        "/api/v1/player-profiles",
        json={
            "display_name": "待更新缺失头像玩家",
            "model_provider": TEST_MODEL_PROVIDER,
            "model": "gpt-4.1-mini",
        },
    ).json()

    patch_response = client.patch(
        f"/api/v1/player-profiles/{created['id']}",
        json={
            "avatar_image_url": "/api/v1/player-profiles/avatar/missing.png",
            "avatar_image_mime": "image/png",
        },
    )

    assert patch_response.status_code == 422
    assert (
        patch_response.json()["detail"]
        == "Legacy file-backed avatar URLs are no longer supported"
    )


def test_patch_profile_rejects_legacy_file_url() -> None:
    created = client.post(
        "/api/v1/player-profiles",
        json={
            "display_name": "待迁移旧头像玩家",
            "model_provider": TEST_MODEL_PROVIDER,
            "model": "gpt-4.1-mini",
        },
    ).json()

    patch_response = client.patch(
        f"/api/v1/player-profiles/{created['id']}",
        json={
            "avatar_image_url": "/api/v1/player-profiles/avatar/legacy.png",
            "avatar_image_mime": "image/png",
        },
    )

    assert patch_response.status_code == 422
    assert (
        patch_response.json()["detail"]
        == "Legacy file-backed avatar URLs are no longer supported"
    )


def test_patch_display_name_only_preserves_unresolved_avatar_url() -> None:
    with TestingSessionLocal() as session:
        profile = VirtualPlayerProfile(
            id="profile-with-missing-legacy-avatar",
            display_name="旧头像字段玩家",
            model_provider=TEST_MODEL_PROVIDER,
            model="gpt-4.1-mini",
            personality_id="balanced",
            personality_text="custom text",
            appearance_id="default",
            avatar_image_url="/api/v1/player-profiles/avatar/missing.png",
            avatar_image_mime="image/png",
            avatar_asset_id=None,
            short_description="",
            background_story="",
            speaking_style="",
            strategy_profile="balanced",
            risk_tolerance=3,
            bluffing_tendency=3,
            trust_tendency=3,
            leadership_tendency=3,
            talkativeness=3,
            example_messages=[],
            tags=[],
            status="published",
            published_at=datetime.now(UTC),
            display_order=1,
        )
        session.add(profile)
        session.commit()

    patch_response = client.patch(
        "/api/v1/player-profiles/profile-with-missing-legacy-avatar",
        json={"display_name": "只改名字"},
    )

    assert patch_response.status_code == 200
    patched = patch_response.json()
    assert patched["display_name"] == "只改名字"
    assert patched["avatar_asset_id"] is None
    assert patched["avatar_image_url"] == "/api/v1/player-profiles/avatar/missing.png"
    assert patched["avatar_image_mime"] == "image/png"

    with TestingSessionLocal() as session:
        stored = session.get(VirtualPlayerProfile, "profile-with-missing-legacy-avatar")

    assert stored is not None
    assert stored.display_name == "只改名字"
    assert stored.avatar_asset_id is None
    assert stored.avatar_image_url == "/api/v1/player-profiles/avatar/missing.png"
    assert stored.avatar_image_mime == "image/png"


def test_patch_display_name_only_does_not_rewrite_database_avatar_fields() -> None:
    with TestingSessionLocal() as session:
        asset = create_avatar_asset(
            session,
            asset_id="uploaded-preserve-on-name-change",
            content_type="image/png",
            data=PNG_BYTES,
            source="uploaded",
        )
        profile = VirtualPlayerProfile(
            id="profile-with-db-avatar-to-preserve",
            display_name="DB 头像字段玩家",
            model_provider=TEST_MODEL_PROVIDER,
            model="gpt-4.1-mini",
            personality_id="balanced",
            personality_text="custom text",
            appearance_id="default",
            avatar_image_url="/legacy/stored-url.png",
            avatar_image_mime="image/png",
            avatar_asset_id=asset.id,
            short_description="",
            background_story="",
            speaking_style="",
            strategy_profile="balanced",
            risk_tolerance=3,
            bluffing_tendency=3,
            trust_tendency=3,
            leadership_tendency=3,
            talkativeness=3,
            example_messages=[],
            tags=[],
            status="published",
            published_at=datetime.now(UTC),
            display_order=1,
        )
        session.add(profile)
        session.commit()

    patch_response = client.patch(
        "/api/v1/player-profiles/profile-with-db-avatar-to-preserve",
        json={"display_name": "只改 DB 头像玩家名字"},
    )

    assert patch_response.status_code == 200
    patched = patch_response.json()
    assert patched["display_name"] == "只改 DB 头像玩家名字"
    assert patched["avatar_asset_id"] == "uploaded-preserve-on-name-change"
    assert (
        patched["avatar_image_url"]
        == "/api/v1/player-profiles/avatar-assets/uploaded-preserve-on-name-change"
    )

    with TestingSessionLocal() as session:
        stored = session.get(VirtualPlayerProfile, "profile-with-db-avatar-to-preserve")

    assert stored is not None
    assert stored.display_name == "只改 DB 头像玩家名字"
    assert stored.avatar_asset_id == "uploaded-preserve-on-name-change"
    assert stored.avatar_image_url == "/legacy/stored-url.png"
    assert stored.avatar_image_mime == "image/png"


def test_get_and_list_profiles_map_avatar_asset_id_to_asset_url() -> None:
    with TestingSessionLocal() as session:
        asset = create_avatar_asset(
            session,
            asset_id="uploaded-mapped-avatar",
            content_type="image/png",
            data=PNG_BYTES,
            source="uploaded",
        )
        profile = VirtualPlayerProfile(
            id="profile-with-stale-avatar-url",
            display_name="旧 URL 玩家",
            model_provider=TEST_MODEL_PROVIDER,
            model="gpt-4.1-mini",
            personality_id="balanced",
            personality_text="custom text",
            appearance_id="default",
            avatar_image_url="/api/v1/player-profiles/avatar/stale.png",
            avatar_image_mime="image/png",
            avatar_asset_id=asset.id,
            short_description="",
            background_story="",
            speaking_style="",
            strategy_profile="balanced",
            risk_tolerance=3,
            bluffing_tendency=3,
            trust_tendency=3,
            leadership_tendency=3,
            talkativeness=3,
            example_messages=[],
            tags=[],
            status="published",
            published_at=datetime.now(UTC),
            display_order=1,
        )
        session.add(profile)
        session.commit()

    get_response = client.get("/api/v1/player-profiles/profile-with-stale-avatar-url")
    list_response = client.get("/api/v1/player-profiles")

    assert get_response.status_code == 200
    get_payload = get_response.json()
    assert get_payload["avatar_asset_id"] == "uploaded-mapped-avatar"
    assert (
        get_payload["avatar_image_url"]
        == "/api/v1/player-profiles/avatar-assets/uploaded-mapped-avatar"
    )

    assert list_response.status_code == 200
    list_payload = list_response.json()["profiles"][0]
    assert list_payload["avatar_asset_id"] == "uploaded-mapped-avatar"
    assert (
        list_payload["avatar_image_url"]
        == "/api/v1/player-profiles/avatar-assets/uploaded-mapped-avatar"
    )


def test_list_profiles_keeps_default_order_after_profile_updates() -> None:
    created_a = client.post(
        "/api/v1/player-profiles",
        json={
            "display_name": "A",
            "model_provider": TEST_MODEL_PROVIDER,
            "model": "model-a",
        },
    ).json()
    created_b = client.post(
        "/api/v1/player-profiles",
        json={
            "display_name": "B",
            "model_provider": TEST_MODEL_PROVIDER,
            "model": "model-b",
        },
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
            "model_provider": TEST_MODEL_PROVIDER,
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


@pytest.mark.parametrize("field_name", ["display_name", "model", "tags"])
def test_patch_profile_rejects_null_non_nullable_fields(field_name: str) -> None:
    created = client.post(
        "/api/v1/player-profiles",
        json={
            "display_name": "Scout",
            "model_provider": TEST_MODEL_PROVIDER,
            "model": "gpt-4.1-mini",
            "personality_id": "balanced",
            "personality_text": "custom text",
            "appearance_id": "default",
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
                "tags": ["a", "b", "c", "d", "e", "f", "g", "h", "i"],
            },
            None,
        ),
    ],
)
def test_create_profile_validation_errors(payload: dict, expected_detail: str | None) -> None:
    response = client.post(
        "/api/v1/player-profiles",
        json={"model_provider": TEST_MODEL_PROVIDER, **payload},
    )

    assert response.status_code == 422
    if expected_detail is not None:
        assert response.json()["detail"] == expected_detail


@pytest.mark.parametrize(
    ("method", "path", "payload"),
    [
        ("get", "/api/v1/player-profiles", None),
        ("get", "/api/v1/player-profiles/profile-1", None),
        (
            "post",
            "/api/v1/player-profiles",
            {
                "display_name": "数据库玩家",
                "model_provider": TEST_MODEL_PROVIDER,
                "model": "deepseek-v4-flash",
            },
        ),
        (
            "patch",
            "/api/v1/player-profiles/profile-1",
            {"display_name": "更新玩家"},
        ),
        ("delete", "/api/v1/player-profiles/profile-1", None),
    ],
)
def test_profile_api_returns_503_when_database_is_unavailable(
    method: str,
    path: str,
    payload: dict[str, object] | None,
) -> None:
    app.dependency_overrides[get_db] = override_broken_db
    try:
        response = client.request(method, path, json=payload)
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 503
    assert response.json() == {"detail": "Player profile database unavailable"}


def test_player_profile_file_store_rejects_payload_without_model_provider(
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

    assert store.get_profile("legacy-profile") is None


def test_create_profile_persists_rich_character_settings() -> None:
    response = client.post(
        "/api/v1/player-profiles",
        json={
            "display_name": "夜谈控场",
            "model_provider": TEST_MODEL_PROVIDER,
            "model": "deepseek-v4-flash",
            "short_description": "沉稳控场，喜欢先盘逻辑再给站边。",
            "background_story": "长期观察圆桌局的复盘型玩家。",
            "speaking_style": "短句推进，先列证据，再给结论。",
            "strategy_profile": "logic_leader",
            "risk_tolerance": 2,
            "bluffing_tendency": 2,
            "trust_tendency": 3,
            "leadership_tendency": 5,
            "talkativeness": 4,
            "example_messages": ["我认为 3 号这一轮的视角不完整，先听后置位补充。"],
        },
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["short_description"] == "沉稳控场，喜欢先盘逻辑再给站边。"
    assert "catchphrases" not in payload
    assert payload["strategy_profile"] == "logic_leader"
    assert payload["risk_tolerance"] == 2
    assert payload["leadership_tendency"] == 5
    assert payload["example_messages"] == ["我认为 3 号这一轮的视角不完整，先听后置位补充。"]


def test_create_profile_normalizes_example_messages() -> None:
    response = client.post(
        "/api/v1/player-profiles",
        json={
            "display_name": "去重玩家",
            "model_provider": TEST_MODEL_PROVIDER,
            "model": "deepseek-v4-flash",
            "example_messages": [" 先听后置位补充。 ", "", "先听后置位补充。", " 票型先记下来。 "],
        },
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["example_messages"] == ["先听后置位补充。", "票型先记下来。"]


@pytest.mark.parametrize(
    "payload",
    [{"example_messages": [123]}],
)
def test_create_profile_rejects_non_string_rich_character_list_items(payload: dict) -> None:
    response = client.post(
        "/api/v1/player-profiles",
        json={
            "display_name": "非字符串列表玩家",
            "model_provider": TEST_MODEL_PROVIDER,
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
            "model_provider": TEST_MODEL_PROVIDER,
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
            "model_provider": TEST_MODEL_PROVIDER,
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
            "model_provider": TEST_MODEL_PROVIDER,
            "model": "deepseek-v4-flash",
            "background_story": "啊" * 1201,
        },
    )

    assert response.status_code == 422


def test_update_profile_rejects_too_long_speaking_style() -> None:
    created = client.post(
        "/api/v1/player-profiles",
        json={
            "display_name": "发言风格过长玩家",
            "model_provider": TEST_MODEL_PROVIDER,
            "model": "deepseek-v4-flash",
        },
    ).json()

    response = client.patch(
        f"/api/v1/player-profiles/{created['id']}",
        json={"speaking_style": "啊" * 801},
    )

    assert response.status_code == 422


def test_create_profile_rejects_removed_catchphrases_field() -> None:
    response = client.post(
        "/api/v1/player-profiles",
        json={
            "display_name": "旧字段玩家",
            "model_provider": TEST_MODEL_PROVIDER,
            "model": "deepseek-v4-flash",
            "catchphrases": ["旧字段不再接受"],
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
            "model_provider": TEST_MODEL_PROVIDER,
            "model": "deepseek-v4-flash",
            "example_messages": example_messages,
        },
    )

    assert response.status_code == 422


def test_update_profile_rejects_removed_catchphrases_field() -> None:
    created = client.post(
        "/api/v1/player-profiles",
        json={
            "display_name": "旧字段更新玩家",
            "model_provider": TEST_MODEL_PROVIDER,
            "model": "deepseek-v4-flash",
        },
    ).json()

    response = client.patch(
        f"/api/v1/player-profiles/{created['id']}",
        json={"catchphrases": ["旧字段不再接受"]},
    )

    assert response.status_code == 422


def test_patch_profile_persists_rich_character_settings() -> None:
    created = client.post(
        "/api/v1/player-profiles",
        json={
            "display_name": "待更新玩家",
            "model_provider": TEST_MODEL_PROVIDER,
            "model": "deepseek-v4-flash",
        },
    ).json()

    patch_response = client.patch(
        f"/api/v1/player-profiles/{created['id']}",
        json={
            "short_description": "更新后的控场简介",
            "background_story": "复盘多年圆桌局后形成的打法。",
            "speaking_style": "先拆视角，再压缩狼坑。",
            "strategy_profile": "pressure_attacker",
            "risk_tolerance": 4,
            "bluffing_tendency": 2,
            "trust_tendency": 1,
            "leadership_tendency": 5,
            "talkativeness": 4,
            "example_messages": ["这一轮我会先压 7 号解释票型。"],
        },
    )

    assert patch_response.status_code == 200
    patched = patch_response.json()
    assert patched["short_description"] == "更新后的控场简介"
    assert patched["background_story"] == "复盘多年圆桌局后形成的打法。"
    assert patched["speaking_style"] == "先拆视角，再压缩狼坑。"
    assert "catchphrases" not in patched
    assert patched["strategy_profile"] == "pressure_attacker"
    assert patched["risk_tolerance"] == 4
    assert patched["bluffing_tendency"] == 2
    assert patched["trust_tendency"] == 1
    assert patched["leadership_tendency"] == 5
    assert patched["talkativeness"] == 4
    assert patched["example_messages"] == ["这一轮我会先压 7 号解释票型。"]

    with TestingSessionLocal() as session:
        stored = session.get(VirtualPlayerProfile, created["id"])

    assert stored is not None
    assert stored.short_description == "更新后的控场简介"
    assert stored.strategy_profile == "pressure_attacker"
    assert stored.risk_tolerance == 4
    assert stored.example_messages == ["这一轮我会先压 7 号解释票型。"]
