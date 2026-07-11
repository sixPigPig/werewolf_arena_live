from __future__ import annotations

from collections.abc import Generator
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.routes.admin_voice_assets import get_admin_judge_voice_asset_dir
from app.core.config import settings
from app.db.base import Base
from app.db.session import get_db
from app.main import create_application


@pytest.fixture
def voice_client(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> Generator[tuple[TestClient, Path], None, None]:
    monkeypatch.setattr(settings, "app_environment", "test")
    monkeypatch.setattr(settings, "api_v1_prefix", "/api/v1")
    monkeypatch.setattr(settings, "admin_dev_auth_enabled", True)
    monkeypatch.setattr(settings, "admin_dev_auth_email", "voice-admin@example.test")
    monkeypatch.setattr(settings, "admin_dev_auth_display_name", "Voice Admin")
    monkeypatch.setattr(settings, "admin_dev_auth_role", "viewer")
    monkeypatch.setattr(settings, "admin_session_cookie_name", "voice_admin_session")
    monkeypatch.setattr(settings, "admin_session_cookie_secure", False)
    monkeypatch.setattr(settings, "admin_session_ttl_seconds", 3600)
    monkeypatch.setattr(settings, "ark_tts_judge_asset_audio_format", "mp3")
    monkeypatch.setattr(settings, "ark_tts_judge_asset_sample_rate", 24000)

    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    testing_session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    asset_dir = tmp_path / "judge-voice"
    asset_dir.mkdir()

    def override_get_db() -> Generator[Session, None, None]:
        with testing_session() as db:
            yield db

    application = create_application()
    application.dependency_overrides[get_db] = override_get_db
    application.dependency_overrides[get_admin_judge_voice_asset_dir] = lambda: asset_dir
    with TestClient(application) as client:
        yield client, asset_dir
    engine.dispose()


def _login(client: TestClient) -> None:
    response = client.post("/api/v1/admin/dev-login")
    assert response.status_code == 200, response.text


def test_admin_voice_assets_require_authenticated_voice_read(
    voice_client: tuple[TestClient, Path],
) -> None:
    client, _asset_dir = voice_client
    response = client.get("/api/v1/admin/judge-voice-lines")
    assert response.status_code == 401
    assert response.json()["code"] == "admin_auth_required"

    _login(client)
    response = client.get("/api/v1/admin/judge-voice-lines")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-request-id"]


def test_admin_voice_assets_return_safe_inventory_and_coverage(
    voice_client: tuple[TestClient, Path],
) -> None:
    client, asset_dir = voice_client
    (asset_dir / "game_intro.mp3").write_bytes(b"intro-audio")
    (asset_dir / "night_start.mp3").write_bytes(b"night-audio")
    (asset_dir / "manifest.json").write_text(
        json.dumps(
            {
                "lines": [
                    {
                        "id": "game_intro",
                        "subtitle_timings": [
                            {"text": "本局", "start_ms": 0, "end_ms": 300}
                        ],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    _login(client)

    response = client.get(
        "/api/v1/admin/judge-voice-lines",
        params={"q": "game_intro", "category": "开局", "page_size": 10},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["audio_format"] == "mp3"
    assert body["sample_rate"] == 24000
    assert body["storage_mode"] == "legacy_static_directory"
    assert body["coverage"]["available"] == 2
    assert body["coverage"]["missing"] == body["coverage"]["total"] - 2
    assert body["coverage"]["byte_total"] == len(b"intro-audio") + len(b"night-audio")
    assert body["pagination"] == {
        "page": 1,
        "page_size": 10,
        "total": 1,
        "pages": 1,
    }
    assert body["items"] == [
        {
            "id": "game_intro",
            "text": "本局游戏开始，请所有玩家确认自己的身份牌。",
            "category": "开局",
            "available": True,
            "byte_size": len(b"intro-audio"),
            "template_id": None,
            "seat_number": None,
            "subtitle_cue_count": 1,
            "audio_url": "/api/v1/admin/judge-voice-lines/game_intro/audio",
        }
    ]
    serialized = response.text
    for forbidden in (
        "filename",
        "public_url",
        "template_text",
        "subtitle_timings",
        "manifest_path",
    ):
        assert forbidden not in serialized


def test_admin_voice_assets_filter_missing_and_paginate(
    voice_client: tuple[TestClient, Path],
) -> None:
    client, asset_dir = voice_client
    (asset_dir / "game_intro.mp3").write_bytes(b"audio")
    _login(client)

    response = client.get(
        "/api/v1/admin/judge-voice-lines",
        params={
            "availability": "missing",
            "sort": "id",
            "page": 2,
            "page_size": 10,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["pagination"]["page"] == 2
    assert body["pagination"]["page_size"] == 10
    assert body["pagination"]["total"] == body["coverage"]["total"] - 1
    assert len(body["items"]) == 10
    assert all(item["available"] is False for item in body["items"])
    assert all(item["audio_url"] is None for item in body["items"])


def test_admin_voice_asset_audio_is_authenticated_and_does_not_leak_path(
    voice_client: tuple[TestClient, Path],
) -> None:
    client, asset_dir = voice_client
    audio = b"safe-admin-audio"
    (asset_dir / "night_start.mp3").write_bytes(audio)

    anonymous = client.get("/api/v1/admin/judge-voice-lines/night_start/audio")
    assert anonymous.status_code == 401

    _login(client)
    response = client.get("/api/v1/admin/judge-voice-lines/night_start/audio")
    assert response.status_code == 200
    assert response.content == audio
    assert response.headers["content-type"] == "audio/mpeg"
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert str(asset_dir) not in str(response.headers)


@pytest.mark.parametrize("line_id", ["night_start", "missing_line"])
def test_admin_voice_asset_audio_returns_structured_404(
    voice_client: tuple[TestClient, Path],
    line_id: str,
) -> None:
    client, _asset_dir = voice_client
    _login(client)
    response = client.get(f"/api/v1/admin/judge-voice-lines/{line_id}/audio")
    assert response.status_code == 404
    assert response.json()["code"] == "admin_voice_asset_not_found"


def test_admin_voice_asset_filters_are_validated(
    voice_client: tuple[TestClient, Path],
) -> None:
    client, _asset_dir = voice_client
    _login(client)
    response = client.get(
        "/api/v1/admin/judge-voice-lines",
        params={"availability": "unknown", "page_size": 101},
    )
    assert response.status_code == 422
    assert response.json()["code"] == "admin_request_invalid"
