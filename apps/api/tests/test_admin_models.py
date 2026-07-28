from __future__ import annotations

from collections.abc import Generator
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.routes.admin_models import (
    get_agent_plan_catalog_client,
    get_deepseek_catalog_client,
)
from app.core.config import settings
from app.db.base import Base
from app.db.session import get_db
from app.main import create_application
from app.model_catalog.service import DiscoveredModel
from app.models.model_configuration import ModelConfigurationRecord
from app.models.virtual_player_profile import VirtualPlayerProfile


class FakeDeepSeekCatalogClient:
    def list_models(self) -> list[DiscoveredModel]:
        return [
            DiscoveredModel(
                provider="deepseek",
                model_id="deepseek-v4-flash",
                source_model_id="deepseek-v4-flash",
                display_name="deepseek-v4-flash",
                description="Flash",
                supports_thinking=True,
                source_details={"owned_by": "deepseek"},
            ),
            DiscoveredModel(
                provider="deepseek",
                model_id="deepseek-v4-pro",
                source_model_id="deepseek-v4-pro",
                display_name="deepseek-v4-pro",
                description="Pro",
                supports_thinking=True,
                source_details={"owned_by": "deepseek"},
            ),
        ]


class FakeAgentPlanCatalogClient:
    def list_models(self) -> list[DiscoveredModel]:
        return [
            DiscoveredModel(
                provider="agent_plan",
                model_id="agent-fast",
                source_model_id="agent-fast-source",
                display_name="Agent Fast",
                description="Fast model",
                supports_thinking=True,
                source_details={"selected": True, "plan": "agent-plan"},
            ),
            DiscoveredModel(
                provider="agent_plan",
                model_id="agent-pro",
                source_model_id="agent-pro-source",
                display_name="Agent Pro",
                description="Pro model",
                supports_thinking=True,
                source_details={"selected": False, "plan": "agent-plan"},
            ),
            DiscoveredModel(
                provider="agent_plan",
                model_id="glm-5-2-260617",
                source_model_id="glm-5-2-260601",
                display_name="glm-5-2-260617",
                description="GLM-5.2 deep-thinking model",
                supports_thinking=True,
                source_details={"selected": False, "plan": "agent-plan"},
            ),
        ]


@pytest.fixture
def model_admin_client(
    monkeypatch: pytest.MonkeyPatch,
) -> Generator[tuple[TestClient, sessionmaker[Session]], None, None]:
    monkeypatch.setattr(settings, "app_environment", "test")
    monkeypatch.setattr(settings, "admin_dev_auth_enabled", True)
    monkeypatch.setattr(settings, "admin_dev_auth_email", "models@example.test")
    monkeypatch.setattr(settings, "admin_dev_auth_display_name", "Model Admin")
    monkeypatch.setattr(settings, "admin_dev_auth_role", "super_admin")
    monkeypatch.setattr(settings, "admin_session_cookie_name", "models_admin_session")
    monkeypatch.setattr(settings, "admin_session_cookie_secure", False)
    monkeypatch.setattr(settings, "public_session_cookie_secure", False)
    monkeypatch.setenv(
        "ARK_AGENT_PLAN_MODELS",
        "agent-fast,glm-5-2-260617",
    )
    monkeypatch.setenv("DEEPSEEK_MODEL", "deepseek-v4-flash")
    monkeypatch.setenv("WEREWOLF_DEFAULT_MODEL", "agent-fast")

    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    testing_session = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    def override_get_db() -> Generator[Session, None, None]:
        with testing_session() as db:
            yield db

    application = create_application()
    application.dependency_overrides[get_db] = override_get_db
    application.dependency_overrides[get_deepseek_catalog_client] = (
        FakeDeepSeekCatalogClient
    )
    application.dependency_overrides[get_agent_plan_catalog_client] = (
        FakeAgentPlanCatalogClient
    )
    with TestClient(application) as client:
        yield client, testing_session
    engine.dispose()


def _login(client: TestClient) -> str:
    response = client.post("/api/v1/admin/dev-login")
    assert response.status_code == 200, response.text
    return response.json()["csrf_token"]


def test_model_catalog_requires_admin_session(model_admin_client) -> None:
    client, _ = model_admin_client
    response = client.get("/api/v1/admin/models")
    assert response.status_code == 401


def test_environment_bootstrap_repairs_glm_thinking_capability(
    model_admin_client,
) -> None:
    client, session_factory = model_admin_client
    with session_factory() as db:
        db.add(
            ModelConfigurationRecord(
                provider="agent_plan",
                model_id="glm-5-2-260617",
                source_model_id="glm-5-2-260617",
                display_name="glm-5-2-260617",
                available=True,
                enabled=True,
                supports_thinking=False,
                parameter_values={"thinking": "default"},
                source_details={"bootstrap": "environment"},
            )
        )
        db.commit()

    _login(client)
    listed = client.get("/api/v1/admin/models")
    assert listed.status_code == 200, listed.text
    glm = next(
        item
        for item in listed.json()["models"]
        if item["provider"] == "agent_plan"
        and item["model_id"] == "glm-5-2-260617"
    )
    assert glm["supports_thinking"] is True

    with session_factory() as db:
        repaired = db.get(
            ModelConfigurationRecord,
            ("agent_plan", "glm-5-2-260617"),
        )
        assert repaired is not None
        assert repaired.supports_thinking is True


def test_model_catalog_auto_refreshes_deepseek_and_syncs_agent_plan(
    model_admin_client,
) -> None:
    client, _ = model_admin_client
    csrf_token = _login(client)

    listed = client.get("/api/v1/admin/models")
    assert listed.status_code == 200, listed.text
    listed_payload = listed.json()
    assert {item["model_id"] for item in listed_payload["models"]} >= {
        "agent-fast",
        "glm-5-2-260617",
        "deepseek-v4-flash",
        "deepseek-v4-pro",
    }
    bootstrapped_glm = next(
        item
        for item in listed_payload["models"]
        if item["provider"] == "agent_plan"
        and item["model_id"] == "glm-5-2-260617"
    )
    assert bootstrapped_glm["supports_thinking"] is True
    assert bootstrapped_glm["parameters"]["thinking"] == "enabled"
    assert bootstrapped_glm["parameters"]["max_tokens"] == 16_384
    assert bootstrapped_glm["reasoning_effort_options"] == [
        "minimal",
        "low",
        "medium",
        "high",
    ]
    assert bootstrapped_glm["max_output_tokens_limit"] == 131_072
    deepseek_source = next(
        source for source in listed_payload["sources"] if source["provider"] == "deepseek"
    )
    assert deepseek_source["refresh_mode"] == "automatic"
    assert deepseek_source["model_count"] == 2

    synced = client.post(
        "/api/v1/admin/models/agent-plan/sync",
        headers={"X-CSRF-Token": csrf_token},
    )
    assert synced.status_code == 200, synced.text
    agent_models = [
        item for item in synced.json()["models"] if item["provider"] == "agent_plan"
    ]
    assert [item["model_id"] for item in agent_models] == [
        "agent-fast",
        "agent-pro",
        "glm-5-2-260617",
    ]
    assert next(item for item in agent_models if item["model_id"] == "agent-fast")[
        "enabled"
    ]
    agent_pro = next(item for item in agent_models if item["model_id"] == "agent-pro")
    assert not agent_pro["enabled"]
    assert agent_pro["parameters"]["thinking"] == "enabled"
    assert agent_pro["parameters"]["max_tokens"] == 16_384


def test_glm_5_2_accepts_documented_reasoning_and_output_limit(
    model_admin_client,
) -> None:
    client, _ = model_admin_client
    csrf_token = _login(client)
    client.get("/api/v1/admin/models")

    accepted = client.patch(
        "/api/v1/admin/models/agent_plan/glm-5-2-260617",
        headers={"X-CSRF-Token": csrf_token},
        json={
            "enabled": True,
            "parameters": {
                "thinking": "enabled",
                "reasoning_effort": "minimal",
                "max_tokens": 131_072,
            },
        },
    )
    assert accepted.status_code == 204, accepted.text

    rejected = client.patch(
        "/api/v1/admin/models/agent_plan/glm-5-2-260617",
        headers={"X-CSRF-Token": csrf_token},
        json={
            "enabled": True,
            "parameters": {
                "thinking": "enabled",
                "max_tokens": 131_073,
            },
        },
    )
    assert rejected.status_code == 422
    assert "max_tokens must be between 1 and 131072" in rejected.text


def test_model_configuration_updates_default_and_provider_parameters(
    model_admin_client,
) -> None:
    client, _ = model_admin_client
    csrf_token = _login(client)
    client.get("/api/v1/admin/models")
    client.post(
        "/api/v1/admin/models/agent-plan/sync",
        headers={"X-CSRF-Token": csrf_token},
    )

    response = client.patch(
        "/api/v1/admin/models/agent_plan/agent-pro",
        headers={"X-CSRF-Token": csrf_token},
        json={
            "enabled": True,
            "is_default": True,
            "parameters": {
                "thinking": "enabled",
                "reasoning_effort": "medium",
                "temperature": 0.35,
                "top_p": 0.8,
                "max_tokens": 2048,
                "frequency_penalty": 0.1,
                "presence_penalty": 0.2,
            },
        },
    )
    assert response.status_code == 204, response.text

    refreshed = client.get("/api/v1/admin/models")
    configured = next(
        item for item in refreshed.json()["models"] if item["model_id"] == "agent-pro"
    )
    assert configured["enabled"] is True
    assert configured["is_default"] is True
    assert configured["parameters"] == {
        "thinking": "enabled",
        "reasoning_effort": "medium",
        "temperature": 0.35,
        "top_p": 0.8,
        "max_tokens": 2048,
        "frequency_penalty": 0.1,
        "presence_penalty": 0.2,
    }


def test_deepseek_rejects_sampling_parameters_while_thinking_is_enabled(
    model_admin_client,
) -> None:
    client, _ = model_admin_client
    csrf_token = _login(client)
    client.get("/api/v1/admin/models")

    response = client.patch(
        "/api/v1/admin/models/deepseek/deepseek-v4-flash",
        headers={"X-CSRF-Token": csrf_token},
        json={
            "enabled": True,
            "parameters": {
                "thinking": "enabled",
                "temperature": 0.4,
                "max_tokens": 2048,
            },
        },
    )
    assert response.status_code == 422
    assert response.json()["code"] == "admin_model_configuration_invalid"


def test_model_configuration_save_rejects_reasoning_effort_when_thinking_is_disabled(
    model_admin_client,
) -> None:
    client, _ = model_admin_client
    csrf_token = _login(client)
    client.get("/api/v1/admin/models")
    client.post(
        "/api/v1/admin/models/agent-plan/sync",
        headers={"X-CSRF-Token": csrf_token},
    )

    response = client.patch(
        "/api/v1/admin/models/agent_plan/agent-pro",
        headers={"X-CSRF-Token": csrf_token},
        json={
            "enabled": True,
            "parameters": {
                "thinking": "disabled",
                "reasoning_effort": "medium",
                "max_tokens": 512,
            },
        },
    )

    assert response.status_code == 422
    assert response.json()["code"] == "admin_model_configuration_invalid"
    assert "reasoning_effort must be empty" in response.text


def test_disabling_a_model_used_by_active_profiles_is_rejected(model_admin_client) -> None:
    client, session_factory = model_admin_client
    csrf_token = _login(client)
    client.get("/api/v1/admin/models")
    with session_factory() as db:
        db.add(
            VirtualPlayerProfile(
                id="profile-agent-fast",
                display_name="Agent Fast Player",
                model_provider="agent_plan",
                model="agent-fast",
                status="published",
                published_at=datetime.now(UTC),
                display_order=1,
            )
        )
        db.commit()

    response = client.patch(
        "/api/v1/admin/models/agent_plan/agent-fast",
        headers={"X-CSRF-Token": csrf_token},
        json={
            "enabled": False,
            "parameters": {"thinking": "default", "max_tokens": 2048},
        },
    )
    assert response.status_code == 409
    assert response.json()["code"] == "admin_model_configuration_conflict"


def test_model_configuration_requires_max_tokens(model_admin_client) -> None:
    client, _ = model_admin_client
    csrf_token = _login(client)
    client.get("/api/v1/admin/models")

    response = client.patch(
        "/api/v1/admin/models/deepseek/deepseek-v4-flash",
        headers={"X-CSRF-Token": csrf_token},
        json={
            "enabled": True,
            "parameters": {"thinking": "enabled"},
        },
    )

    assert response.status_code == 422
    assert response.json()["code"] == "admin_request_invalid"


def test_catalog_uses_explicit_thinking_defaults(
    model_admin_client,
) -> None:
    client, _ = model_admin_client
    _login(client)

    response = client.get("/api/v1/admin/models")

    assert response.status_code == 200
    parameters = {
        (item["provider"], item["model_id"]): item["parameters"]
        for item in response.json()["models"]
    }
    assert parameters[("agent_plan", "agent-fast")]["max_tokens"] == 512
    assert parameters[("deepseek", "deepseek-v4-flash")]["thinking"] == "enabled"
    assert parameters[("deepseek", "deepseek-v4-flash")]["max_tokens"] == 16_384
