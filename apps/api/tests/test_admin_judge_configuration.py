from __future__ import annotations

from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.routes.admin_judge_configuration import get_judge_tts_speaker_catalog
from app.core.config import settings
from app.db.base import Base
from app.db.session import get_db
from app.main import create_application
from app.model_catalog.service import update_model_configuration
from app.models.admin import AuditEvent
from app.models.model_configuration import ModelConfigurationRecord
from app.werewolf.tts_speaker_catalog import TtsSpeakerOption


class FakeSpeakerCatalog:
    def list_supported(self, *, resource_id: str) -> tuple[TtsSpeakerOption, ...]:
        assert resource_id == "seed-tts-2.0"
        return (
            TtsSpeakerOption(
                voice_type="zh_female_vv_uranus_bigtts",
                name="Vivi 2.0",
                gender="female",
            ),
            TtsSpeakerOption(
                voice_type="zh_male_yangguangqingnian_uranus_bigtts",
                name="阳光青年 2.0",
                gender="male",
            ),
        )


@pytest.fixture
def judge_admin_client(
    monkeypatch: pytest.MonkeyPatch,
) -> Generator[tuple[TestClient, sessionmaker[Session]], None, None]:
    monkeypatch.setattr(settings, "app_environment", "test")
    monkeypatch.setattr(settings, "admin_dev_auth_enabled", True)
    monkeypatch.setattr(settings, "admin_dev_auth_email", "judge@example.test")
    monkeypatch.setattr(settings, "admin_dev_auth_display_name", "Judge Admin")
    monkeypatch.setattr(settings, "admin_dev_auth_role", "super_admin")
    monkeypatch.setattr(settings, "admin_session_cookie_name", "judge_admin_session")
    monkeypatch.setattr(settings, "admin_session_cookie_secure", False)
    monkeypatch.setattr(settings, "public_session_cookie_secure", False)
    monkeypatch.setattr(
        settings,
        "live_v2_tts_judge_speaker",
        "zh_female_vv_uranus_bigtts",
    )

    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    testing_session = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    with testing_session() as db:
        db.add(
            ModelConfigurationRecord(
                provider="agent_plan",
                model_id="judge-model-pro",
                display_name="Judge Model Pro",
                available=True,
                enabled=True,
                parameter_values={
                    "thinking": "disabled",
                    "reasoning_effort": None,
                    "max_tokens_mode": "auto",
                    "max_tokens": 512,
                },
                source_details={},
            )
        )
        db.commit()

    def override_get_db() -> Generator[Session, None, None]:
        with testing_session() as db:
            yield db

    application = create_application()
    application.dependency_overrides[get_db] = override_get_db
    application.dependency_overrides[get_judge_tts_speaker_catalog] = FakeSpeakerCatalog
    with TestClient(application) as client:
        yield client, testing_session
    engine.dispose()


def _login(client: TestClient) -> str:
    response = client.post("/api/v1/admin/dev-login")
    assert response.status_code == 200, response.text
    return response.json()["csrf_token"]


def test_judge_configuration_requires_admin_session(judge_admin_client) -> None:
    client, _ = judge_admin_client
    assert client.get("/api/v1/admin/judge-configuration").status_code == 401


def test_judge_configuration_reads_defaults_and_persists_fixed_voice(
    judge_admin_client,
) -> None:
    client, session_factory = judge_admin_client
    csrf_token = _login(client)

    initial = client.get("/api/v1/admin/judge-configuration")
    assert initial.status_code == 200, initial.text
    assert initial.json() == {
        "voice_mode": "fixed",
        "tts_speaker": "zh_female_vv_uranus_bigtts",
        "random_tts_speakers": [],
        "version": 0,
        "source": "environment",
        "updated_at": None,
        "speakers": [
            {
                "voice_type": "zh_female_vv_uranus_bigtts",
                "name": "Vivi 2.0",
            },
            {
                "voice_type": "zh_male_yangguangqingnian_uranus_bigtts",
                "name": "阳光青年 2.0",
            },
        ],
        "speaker_catalog_available": True,
        "tts_resource_id": "seed-tts-2.0",
    }

    saved = client.patch(
        "/api/v1/admin/judge-configuration",
        headers={"X-CSRF-Token": csrf_token},
        json={
            "voice_mode": "fixed",
            "tts_speaker": "zh_male_yangguangqingnian_uranus_bigtts",
            "random_tts_speakers": [],
            "expected_version": 0,
        },
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["voice_mode"] == "fixed"
    assert saved.json()["tts_speaker"] == "zh_male_yangguangqingnian_uranus_bigtts"
    assert saved.json()["version"] == 1
    assert saved.json()["source"] == "database"

    with session_factory() as db:
        audit = db.scalar(
            select(AuditEvent).where(AuditEvent.action == "admin.judge_configuration.update")
        )
        assert audit is not None
        assert audit.after["voice_mode"] == "fixed"
        update_model_configuration(
            db,
            provider="agent_plan",
            model_id="judge-model-pro",
            enabled=False,
            is_default=False,
            parameters={
                "thinking": "disabled",
                "reasoning_effort": None,
                "max_tokens_mode": "auto",
                "max_tokens": 512,
            },
        )


def test_judge_configuration_persists_random_pool_and_rejects_stale_update(
    judge_admin_client,
) -> None:
    client, session_factory = judge_admin_client
    csrf_token = _login(client)
    saved = client.patch(
        "/api/v1/admin/judge-configuration",
        headers={"X-CSRF-Token": csrf_token},
        json={
            "voice_mode": "random",
            "tts_speaker": None,
            "random_tts_speakers": [
                "zh_female_vv_uranus_bigtts",
                "zh_male_yangguangqingnian_uranus_bigtts",
            ],
            "expected_version": 0,
        },
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["voice_mode"] == "random"
    assert saved.json()["random_tts_speakers"] == [
        "zh_female_vv_uranus_bigtts",
        "zh_male_yangguangqingnian_uranus_bigtts",
    ]

    stale = client.patch(
        "/api/v1/admin/judge-configuration",
        headers={"X-CSRF-Token": csrf_token},
        json={
            "voice_mode": "fixed",
            "tts_speaker": "zh_female_vv_uranus_bigtts",
            "random_tts_speakers": [],
            "expected_version": 9,
        },
    )
    assert stale.status_code == 409
    assert stale.json()["code"] == "admin_judge_configuration_conflict"
