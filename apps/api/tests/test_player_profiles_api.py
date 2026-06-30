import base64
import json
from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.routes import player_profiles as player_profiles_routes
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models.player_avatar_asset import PlayerAvatarAsset
from app.models.user import User
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
            "catchphrases": ["我先盘票型", "这里别急着出"],
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
    assert payload["catchphrases"] == ["我先盘票型", "这里别急着出"]
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
    assert asset.data == PNG_BYTES
    assert asset.size_bytes == len(PNG_BYTES)


def test_get_avatar_asset_returns_404_for_missing_asset() -> None:
    response = client.get("/api/v1/player-profiles/avatar-assets/missing-asset")

    assert response.status_code == 404
    assert response.json()["detail"] == "Avatar asset not found"


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


@pytest.mark.parametrize(
    ("method", "path", "payload"),
    [
        ("get", "/api/v1/player-profiles", None),
        ("get", "/api/v1/player-profiles/profile-1", None),
        (
            "post",
            "/api/v1/player-profiles",
            {"display_name": "数据库玩家", "model": "deepseek-v4-flash"},
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


def test_player_profile_file_store_reads_old_payload_with_rich_defaults(
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
