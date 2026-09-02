from __future__ import annotations

import subprocess
from collections.abc import Generator
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.routes.admin_models import (
    get_agent_plan_catalog_client,
    get_arkcli_auth_client,
    get_deepseek_catalog_client,
)
from app.core.config import settings
from app.db.base import Base
from app.db.session import get_db
from app.main import create_application
from app.model_catalog.defaults import (
    default_parameter_values,
    normalize_model_parameters,
    reasoning_policy_for_model,
)
from app.model_catalog.service import (
    AgentPlanCatalogClient,
    ArkcliAuthClient,
    DeepSeekCatalogClient,
    DiscoveredModel,
    ModelCatalogAuthRequired,
    ModelCatalogUnavailable,
    VolcLoginChallenge,
    validate_parameter_values,
)
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
                model_id="auto",
                source_model_id="auto",
                display_name="Auto",
                description="Unsupported automatic model",
                supports_thinking=False,
                source_details={"selected": False, "plan": "agent-plan"},
            ),
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


class FakeArkcliAuthClient:
    def __init__(self) -> None:
        self.completed_codes: list[str] = []
        self.already_authenticated = False
        self.fail_start = False
        self.fail_complete = False

    def start_volc_login(self) -> VolcLoginChallenge:
        if self.fail_start:
            raise ModelCatalogAuthRequired(
                "Agent Plan sync requires an authenticated arkcli Volc SSO session."
            )
        if self.already_authenticated:
            return VolcLoginChallenge(
                authorize_url=None,
                expires_in_sec=None,
                already_authenticated=True,
            )
        return VolcLoginChallenge(
            authorize_url="https://signin.volcengine.com/authorize/oauth/authorize?x=1",
            expires_in_sec=600,
            already_authenticated=False,
        )

    def complete_volc_login(self, authorization_code: str) -> None:
        if self.fail_complete:
            raise ModelCatalogUnavailable("Volcengine login failed.")
        self.completed_codes.append(authorization_code)


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
    monkeypatch.setattr(
        settings,
        "live_v2_ark_models",
        "ep-glm-5-2-production",
    )

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
    application.dependency_overrides[get_arkcli_auth_client] = FakeArkcliAuthClient
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
                parameter_values={
                    "thinking": "disabled",
                    "reasoning_effort": None,
                    "max_tokens_mode": "auto",
                    "max_tokens": 512,
                },
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
    assert glm["parameters"] == {
        "thinking": "disabled",
        "reasoning_effort": None,
        "temperature": None,
        "top_p": None,
        "max_tokens_mode": "auto",
        "max_tokens": 512,
        "frequency_penalty": None,
        "presence_penalty": None,
    }

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
        "ep-glm-5-2-production",
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
    assert bootstrapped_glm["parameters"]["reasoning_effort"] == "high"
    assert bootstrapped_glm["parameters"]["max_tokens_mode"] == "auto"
    assert bootstrapped_glm["parameters"]["max_tokens"] == 8_192
    assert bootstrapped_glm["reasoning_policy"] == {
        "thinking_options": ["enabled", "disabled"],
        "default_thinking": "enabled",
        "thinking_locked": False,
        "reasoning_effort_options": ["high", "max"],
        "default_reasoning_effort": "high",
        "max_tokens_by_effort": {"high": 8_192, "max": 16_384},
        "default_max_tokens": 8_192,
        "disabled_max_tokens": 512,
        "sampling_parameters_allowed_when_thinking": True,
    }
    assert bootstrapped_glm["max_output_tokens_limit"] == 131_072
    standard_ark = next(
        item
        for item in listed_payload["models"]
        if item["provider"] == "ark" and item["model_id"] == "ep-glm-5-2-production"
    )
    assert standard_ark["supports_thinking"] is True
    assert standard_ark["parameters"]["thinking"] == "enabled"
    assert standard_ark["parameters"]["reasoning_effort"] == "high"
    assert standard_ark["parameters"]["max_tokens"] == 8_192
    assert standard_ark["max_output_tokens_limit"] == 131_072
    ark_source = next(source for source in listed_payload["sources"] if source["provider"] == "ark")
    assert ark_source["model_count"] == 1
    deepseek_source = next(
        source for source in listed_payload["sources"] if source["provider"] == "deepseek"
    )
    assert deepseek_source["refresh_mode"] == "automatic"
    assert deepseek_source["model_count"] == 2
    deepseek_model = next(
        item
        for item in listed_payload["models"]
        if item["provider"] == "deepseek"
        and item["model_id"] == "deepseek-v4-flash"
    )
    assert (
        deepseek_model["reasoning_policy"][
            "sampling_parameters_allowed_when_thinking"
        ]
        is False
    )

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
    assert agent_pro["supports_thinking"] is True
    assert agent_pro["reasoning_policy"] == {
        "thinking_options": ["enabled", "disabled"],
        "default_thinking": "enabled",
        "thinking_locked": False,
        "reasoning_effort_options": ["high", "max"],
        "default_reasoning_effort": "high",
        "max_tokens_by_effort": {"high": 8_192, "max": 16_384},
        "default_max_tokens": 8_192,
        "disabled_max_tokens": 512,
        "sampling_parameters_allowed_when_thinking": True,
    }
    assert agent_pro["parameters"] == {
        "thinking": "enabled",
        "reasoning_effort": "high",
        "temperature": None,
        "top_p": None,
        "max_tokens_mode": "auto",
        "max_tokens": 8_192,
        "frequency_penalty": None,
        "presence_penalty": None,
    }


def test_model_catalog_deletes_and_ignores_unsupported_auto(
    model_admin_client,
) -> None:
    client, session_factory = model_admin_client
    with session_factory() as db:
        db.add(
            ModelConfigurationRecord(
                provider="agent_plan",
                model_id="auto",
                source_model_id="auto",
                display_name="Auto",
                available=True,
                enabled=False,
                is_default=False,
                supports_thinking=False,
                parameter_values={
                    "thinking": "disabled",
                    "reasoning_effort": None,
                    "max_tokens_mode": "auto",
                    "max_tokens": 512,
                },
                source_details={"selected": False, "plan": "agent-plan"},
            )
        )
        db.commit()

    csrf_token = _login(client)
    listed = client.get("/api/v1/admin/models")
    assert listed.status_code == 200, listed.text
    assert all(item["model_id"] != "auto" for item in listed.json()["models"])

    synced = client.post(
        "/api/v1/admin/models/agent-plan/sync",
        headers={"X-CSRF-Token": csrf_token},
    )
    assert synced.status_code == 200, synced.text
    assert all(item["model_id"] != "auto" for item in synced.json()["models"])

    with session_factory() as db:
        assert db.get(ModelConfigurationRecord, ("agent_plan", "auto")) is None


def test_deepseek_catalog_uses_direct_transport(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests: list[dict[str, object]] = []

    class FakeResponse:
        def __enter__(self) -> FakeResponse:
            return self

        def __exit__(self, exc_type, exc, traceback) -> None:
            del exc_type, exc, traceback

        def read(self) -> bytes:
            return b'{"data":[{"id":"deepseek-v4-flash","owned_by":"deepseek"}]}'

    def fake_open_url_direct(request, *, timeout: float) -> FakeResponse:
        requests.append({"request": request, "timeout": timeout})
        return FakeResponse()

    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    monkeypatch.setattr(
        "app.model_catalog.service.open_url_direct",
        fake_open_url_direct,
    )

    models = DeepSeekCatalogClient().list_models()

    assert [model.model_id for model in models] == ["deepseek-v4-flash"]
    assert requests[0]["timeout"] == settings.model_catalog_deepseek_timeout_seconds


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
                "reasoning_effort": "max",
                "max_tokens_mode": "manual",
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
                "reasoning_effort": "max",
                "max_tokens_mode": "manual",
                "max_tokens": 131_073,
            },
        },
    )
    assert rejected.status_code == 422
    assert "max_tokens must be between 1 and 131072" in rejected.text

    invalid_effort = client.patch(
        "/api/v1/admin/models/agent_plan/glm-5-2-260617",
        headers={"X-CSRF-Token": csrf_token},
        json={
            "enabled": True,
            "parameters": {
                "thinking": "enabled",
                "reasoning_effort": "minimal",
                "max_tokens_mode": "auto",
                "max_tokens": 8_192,
            },
        },
    )
    assert invalid_effort.status_code == 422
    assert "reasoning_effort must be one of: high, max" in invalid_effort.text


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
        "/api/v1/admin/models/agent_plan/glm-5-2-260617",
        headers={"X-CSRF-Token": csrf_token},
        json={
            "enabled": True,
            "is_default": True,
            "parameters": {
                "thinking": "enabled",
                "reasoning_effort": "high",
                "temperature": 0.35,
                "top_p": 0.8,
                "max_tokens_mode": "manual",
                "max_tokens": 2048,
                "frequency_penalty": 0.1,
                "presence_penalty": 0.2,
            },
        },
    )
    assert response.status_code == 204, response.text

    refreshed = client.get("/api/v1/admin/models")
    configured = next(
        item
        for item in refreshed.json()["models"]
        if item["model_id"] == "glm-5-2-260617"
    )
    assert configured["enabled"] is True
    assert configured["is_default"] is True
    assert configured["parameters"] == {
        "thinking": "enabled",
        "reasoning_effort": "high",
        "temperature": 0.35,
        "top_p": 0.8,
        "max_tokens_mode": "manual",
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
                "reasoning_effort": "high",
                "temperature": 0.4,
                "max_tokens_mode": "auto",
                "max_tokens": 2048,
            },
        },
    )
    assert response.status_code == 422
    assert response.json()["code"] == "admin_model_configuration_invalid"


def test_agent_plan_deepseek_rejects_sampling_by_model_policy() -> None:
    with pytest.raises(
        ValueError,
        match="this model ignores sampling and penalty parameters",
    ):
        validate_parameter_values(
            provider="agent_plan",
            model_id="deepseek-v4-flash-260425",
            supports_thinking=True,
            values={
                "thinking": "enabled",
                "reasoning_effort": "high",
                "max_tokens_mode": "auto",
                "max_tokens": 8_192,
                "temperature": 0.4,
            },
        )


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
        "/api/v1/admin/models/agent_plan/glm-5-2-260617",
        headers={"X-CSRF-Token": csrf_token},
        json={
            "enabled": True,
            "parameters": {
                "thinking": "disabled",
                "reasoning_effort": "medium",
                "max_tokens_mode": "auto",
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
            "parameters": {
                "thinking": "disabled",
                "reasoning_effort": None,
                "max_tokens_mode": "auto",
                "max_tokens": 512,
            },
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
            "parameters": {
                "thinking": "enabled",
                "reasoning_effort": "high",
            },
        },
    )

    assert response.status_code == 422
    assert response.json()["code"] == "admin_request_invalid"


def test_model_configuration_rejects_unknown_request_fields(model_admin_client) -> None:
    client, _ = model_admin_client
    csrf_token = _login(client)
    client.get("/api/v1/admin/models")

    response = client.patch(
        "/api/v1/admin/models/deepseek/deepseek-v4-flash",
        headers={"X-CSRF-Token": csrf_token},
        json={
            "enabled": True,
            "legacy_mode": True,
            "parameters": {
                "thinking": "enabled",
                "reasoning_effort": "high",
                "max_tokens_mode": "auto",
                "max_tokens": 8_192,
                "legacy_budget": 123,
            },
        },
    )

    assert response.status_code == 422
    assert response.json()["code"] == "admin_request_invalid"


@pytest.mark.parametrize("invalid_max_tokens", [True, "12"])
def test_model_configuration_rejects_coerced_max_tokens(
    model_admin_client,
    invalid_max_tokens: object,
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
                "reasoning_effort": "high",
                "max_tokens_mode": "auto",
                "max_tokens": invalid_max_tokens,
            },
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
    assert parameters[("agent_plan", "agent-fast")] == {
        "thinking": "enabled",
        "reasoning_effort": "high",
        "temperature": None,
        "top_p": None,
        "max_tokens_mode": "auto",
        "max_tokens": 8_192,
        "frequency_penalty": None,
        "presence_penalty": None,
    }
    agent_fast = next(
        item
        for item in response.json()["models"]
        if item["provider"] == "agent_plan" and item["model_id"] == "agent-fast"
    )
    assert agent_fast["supports_thinking"] is True
    assert agent_fast["reasoning_policy"]["thinking_options"] == [
        "enabled",
        "disabled",
    ]
    assert agent_fast["reasoning_policy"]["thinking_locked"] is False
    assert agent_fast["reasoning_policy"]["reasoning_effort_options"] == [
        "high",
        "max",
    ]
    assert agent_fast["reasoning_policy"]["default_reasoning_effort"] == "high"
    assert parameters[("deepseek", "deepseek-v4-flash")]["thinking"] == "enabled"
    assert parameters[("deepseek", "deepseek-v4-flash")]["reasoning_effort"] == "high"
    assert parameters[("deepseek", "deepseek-v4-flash")]["max_tokens_mode"] == "auto"
    assert parameters[("deepseek", "deepseek-v4-flash")]["max_tokens"] == 8_192


def test_unverified_model_follows_glm_effort_contract(model_admin_client) -> None:
    client, _ = model_admin_client
    csrf_token = _login(client)
    client.get("/api/v1/admin/models")

    rejected = client.patch(
        "/api/v1/admin/models/agent_plan/agent-fast",
        headers={"X-CSRF-Token": csrf_token},
        json={
            "enabled": True,
            "is_default": True,
            "parameters": {
                "thinking": "enabled",
                "reasoning_effort": None,
                "max_tokens_mode": "auto",
                "max_tokens": 512,
            },
        },
    )
    assert rejected.status_code == 422
    assert "reasoning_effort is required" in rejected.text

    response = client.patch(
        "/api/v1/admin/models/agent_plan/agent-fast",
        headers={"X-CSRF-Token": csrf_token},
        json={
            "enabled": True,
            "is_default": True,
            "parameters": {
                "thinking": "enabled",
                "reasoning_effort": "max",
                "max_tokens_mode": "auto",
                "max_tokens": 16_384,
            },
        },
    )

    assert response.status_code == 204, response.text
    listed = client.get("/api/v1/admin/models")
    agent_fast = next(
        item
        for item in listed.json()["models"]
        if item["provider"] == "agent_plan" and item["model_id"] == "agent-fast"
    )
    assert agent_fast["parameters"]["thinking"] == "enabled"
    assert agent_fast["parameters"]["reasoning_effort"] == "max"
    assert agent_fast["parameters"]["max_tokens"] == 16_384


@pytest.mark.parametrize(
    (
        "provider",
        "model_id",
        "expected_efforts",
        "expected_budgets",
        "expected_default_effort",
        "expected_default_max_tokens",
        "expected_locked",
    ),
    [
        (
            "agent_plan",
            "doubao-seed-2-0-lite-260215",
            ("low", "medium", "high"),
            {"low": 4_096, "medium": 8_192, "high": 16_384},
            "low",
            4_096,
            False,
        ),
        (
            "agent_plan",
            "glm-5-2-260617",
            ("high", "max"),
            {"high": 8_192, "max": 16_384},
            "high",
            8_192,
            False,
        ),
        (
            "agent_plan",
            "glm-5-3-flash",
            ("low", "high", "max"),
            {"low": 4_096, "high": 8_192, "max": 16_384},
            "low",
            4_096,
            True,
        ),
        (
            "deepseek",
            "deepseek-v4-flash",
            ("high", "max"),
            {"high": 8_192, "max": 16_384},
            "high",
            8_192,
            False,
        ),
        (
            "agent_plan",
            "kimi-k3",
            ("low", "high", "max"),
            {"low": 4_096, "high": 8_192, "max": 16_384},
            "low",
            4_096,
            True,
        ),
        (
            "agent_plan",
            "minimax-m3",
            (),
            {},
            None,
            8_192,
            False,
        ),
    ],
)
def test_reasoning_policy_is_model_specific(
    provider: str,
    model_id: str,
    expected_efforts: tuple[str, ...],
    expected_budgets: dict[str, int],
    expected_default_effort: str | None,
    expected_default_max_tokens: int,
    expected_locked: bool,
) -> None:
    policy = reasoning_policy_for_model(
        provider,
        model_id,
        supports_thinking=True,
    )
    parameters = default_parameter_values(
        provider,
        model_id,
        supports_thinking=True,
        limit=384_000,
    )

    assert policy.reasoning_effort_options == expected_efforts
    assert policy.max_tokens_by_effort == expected_budgets
    assert policy.default_reasoning_effort == expected_default_effort
    assert policy.default_max_tokens == expected_default_max_tokens
    assert policy.thinking_locked is expected_locked
    assert parameters["thinking"] == "enabled"
    assert parameters["max_tokens_mode"] == "auto"
    assert parameters["max_tokens"] == expected_default_max_tokens
    assert parameters["reasoning_effort"] == expected_default_effort


def test_catalog_repairs_unverified_enabled_thinking_without_effort(
    model_admin_client,
) -> None:
    client, session_factory = model_admin_client
    with session_factory() as db:
        db.add(
            ModelConfigurationRecord(
                provider="agent_plan",
                model_id="agent-fast",
                source_model_id="agent-fast",
                display_name="agent-fast",
                available=True,
                enabled=True,
                is_default=True,
                supports_thinking=True,
                parameter_values={
                    "thinking": "enabled",
                    "reasoning_effort": None,
                    "max_tokens_mode": "auto",
                    "max_tokens": 512,
                },
                source_details={"bootstrap": "environment"},
            )
        )
        db.commit()

    _login(client)
    listed = client.get("/api/v1/admin/models")
    assert listed.status_code == 200, listed.text
    agent_fast = next(
        item
        for item in listed.json()["models"]
        if item["provider"] == "agent_plan" and item["model_id"] == "agent-fast"
    )
    assert agent_fast["parameters"]["thinking"] == "enabled"
    assert agent_fast["parameters"]["reasoning_effort"] == "high"
    assert agent_fast["parameters"]["max_tokens"] == 8_192


def test_unverified_legacy_model_uses_glm_reasoning_contract() -> None:
    policy = reasoning_policy_for_model(
        "agent_plan",
        "kimi-k2.6",
        supports_thinking=True,
    )
    glm_policy = reasoning_policy_for_model(
        "agent_plan",
        "glm-5-2-260617",
        supports_thinking=True,
    )

    assert policy == glm_policy
    assert policy.thinking_options == ("enabled", "disabled")
    assert policy.thinking_locked is False
    assert policy.default_thinking == "enabled"
    assert policy.reasoning_effort_options == ("high", "max")
    assert policy.default_reasoning_effort == "high"
    assert policy.max_tokens_by_effort == {"high": 8_192, "max": 16_384}


def test_unverified_legacy_model_stays_non_thinking_when_capability_is_absent() -> None:
    policy = reasoning_policy_for_model(
        "agent_plan",
        "kimi-k2.6",
        supports_thinking=False,
    )

    assert policy.thinking_options == ("disabled",)
    assert policy.thinking_locked is True
    assert policy.reasoning_effort_options == ()


def test_code_preview_remains_non_thinking_when_discovery_misreports_support() -> None:
    policy = reasoning_policy_for_model(
        "agent_plan",
        "doubao-seed-2-0-code-preview-260215",
        supports_thinking=True,
    )

    assert policy.thinking_options == ("disabled",)
    assert policy.reasoning_effort_options == ()


def test_core_contract_rejects_missing_reasoning_effort_key() -> None:
    with pytest.raises(ValueError, match="missing required parameters: reasoning_effort"):
        normalize_model_parameters(
            "agent_plan",
            "glm-5-2-260617",
            {
                "thinking": "enabled",
                "max_tokens_mode": "auto",
                "max_tokens": 8_192,
            },
            supports_thinking=True,
            limit=131_072,
        )


def test_glm_5_3_flash_rejects_disabled_and_accepts_effort_floors() -> None:
    policy = reasoning_policy_for_model(
        "agent_plan",
        "glm-5-3-flash",
        supports_thinking=True,
    )
    assert policy.thinking_options == ("enabled",)
    assert policy.thinking_locked is True
    assert policy.disabled_max_tokens is None
    assert policy.reasoning_effort_options == ("low", "high", "max")

    with pytest.raises(ValueError, match="thinking must be one of: enabled"):
        normalize_model_parameters(
            "agent_plan",
            "glm-5-3-flash",
            {
                "thinking": "disabled",
                "reasoning_effort": None,
                "max_tokens_mode": "auto",
                "max_tokens": 512,
            },
            supports_thinking=True,
            limit=384_000,
        )

    for effort, tokens in (("low", 4_096), ("high", 8_192), ("max", 16_384)):
        normalized = normalize_model_parameters(
            "agent_plan",
            "glm-5-3-flash",
            {
                "thinking": "enabled",
                "reasoning_effort": effort,
                "max_tokens_mode": "auto",
                "max_tokens": tokens,
            },
            supports_thinking=True,
            limit=384_000,
        )
        assert normalized["thinking"] == "enabled"
        assert normalized["reasoning_effort"] == effort
        assert normalized["max_tokens"] == tokens


def test_verified_model_family_rejects_forged_non_thinking_capability() -> None:
    policy = reasoning_policy_for_model(
        "agent_plan",
        "kimi-k3",
        supports_thinking=False,
    )
    assert policy.thinking_options == ("enabled",)
    assert policy.thinking_locked is True

    with pytest.raises(
        ValueError,
        match="supports_thinking does not match the model reasoning policy",
    ):
        normalize_model_parameters(
            "agent_plan",
            "kimi-k3",
            {
                "thinking": "disabled",
                "reasoning_effort": None,
                "max_tokens_mode": "auto",
                "max_tokens": 512,
            },
            supports_thinking=False,
            limit=384_000,
        )


def test_auto_max_tokens_is_relinked_by_backend(model_admin_client) -> None:
    client, _ = model_admin_client
    csrf_token = _login(client)
    client.get("/api/v1/admin/models")

    response = client.patch(
        "/api/v1/admin/models/agent_plan/glm-5-2-260617",
        headers={"X-CSRF-Token": csrf_token},
        json={
            "enabled": True,
            "parameters": {
                "thinking": "enabled",
                "reasoning_effort": "max",
                "max_tokens_mode": "auto",
                "max_tokens": 1,
            },
        },
    )
    assert response.status_code == 204, response.text

    refreshed = client.get("/api/v1/admin/models")
    configured = next(
        item
        for item in refreshed.json()["models"]
        if item["provider"] == "agent_plan"
        and item["model_id"] == "glm-5-2-260617"
    )
    assert configured["parameters"]["max_tokens"] == 16_384


def test_reasoning_change_forces_auto_even_when_request_submits_manual(
    model_admin_client,
) -> None:
    client, _ = model_admin_client
    csrf_token = _login(client)
    client.get("/api/v1/admin/models")

    response = client.patch(
        "/api/v1/admin/models/agent_plan/glm-5-2-260617",
        headers={"X-CSRF-Token": csrf_token},
        json={
            "enabled": True,
            "parameters": {
                "thinking": "enabled",
                "reasoning_effort": "max",
                "max_tokens_mode": "manual",
                "max_tokens": 123,
            },
        },
    )
    assert response.status_code == 204, response.text

    refreshed = client.get("/api/v1/admin/models")
    configured = next(
        item
        for item in refreshed.json()["models"]
        if item["provider"] == "agent_plan"
        and item["model_id"] == "glm-5-2-260617"
    )
    assert configured["parameters"]["max_tokens_mode"] == "auto"
    assert configured["parameters"]["max_tokens"] == 16_384


def test_disabling_thinking_forces_auto_512_budget(model_admin_client) -> None:
    client, _ = model_admin_client
    csrf_token = _login(client)
    client.get("/api/v1/admin/models")

    response = client.patch(
        "/api/v1/admin/models/agent_plan/glm-5-2-260617",
        headers={"X-CSRF-Token": csrf_token},
        json={
            "enabled": True,
            "parameters": {
                "thinking": "disabled",
                "reasoning_effort": None,
                "max_tokens_mode": "manual",
                "max_tokens": 999,
            },
        },
    )
    assert response.status_code == 204, response.text

    configured = next(
        item
        for item in client.get("/api/v1/admin/models").json()["models"]
        if item["provider"] == "agent_plan"
        and item["model_id"] == "glm-5-2-260617"
    )
    assert configured["parameters"]["max_tokens_mode"] == "auto"
    assert configured["parameters"]["max_tokens"] == 512


def test_enabled_thinking_requires_reasoning_effort(model_admin_client) -> None:
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
                "reasoning_effort": None,
                "max_tokens_mode": "auto",
                "max_tokens": 8_192,
            },
        },
    )

    assert response.status_code == 422
    assert "reasoning_effort is required" in response.text


def test_agent_plan_sync_reports_volc_sso_required(model_admin_client) -> None:
    client, _ = model_admin_client
    csrf_token = _login(client)

    class AuthRequiredClient:
        def list_models(self) -> list[DiscoveredModel]:
            raise ModelCatalogAuthRequired(
                "Agent Plan sync requires an authenticated arkcli Volc SSO session."
            )

    client.app.dependency_overrides[get_agent_plan_catalog_client] = (
        lambda: AuthRequiredClient()
    )
    response = client.post(
        "/api/v1/admin/models/agent-plan/sync",
        headers={"X-CSRF-Token": csrf_token},
    )

    assert response.status_code == 503
    assert response.json()["code"] == "admin_model_catalog_sync_auth_required"
    assert "Volc SSO" in response.json()["detail"]


def test_agent_plan_volc_login_start_and_complete(model_admin_client) -> None:
    client, _ = model_admin_client
    csrf_token = _login(client)
    auth_client = FakeArkcliAuthClient()
    client.app.dependency_overrides[get_arkcli_auth_client] = lambda: auth_client

    started = client.post(
        "/api/v1/admin/models/agent-plan/login",
        headers={"X-CSRF-Token": csrf_token},
    )
    assert started.status_code == 200, started.text
    assert started.json() == {
        "authorize_url": "https://signin.volcengine.com/authorize/oauth/authorize?x=1",
        "expires_in_sec": 600,
        "already_authenticated": False,
    }

    completed = client.post(
        "/api/v1/admin/models/agent-plan/login/complete",
        headers={"X-CSRF-Token": csrf_token},
        json={"authorization_code": "  demo-code  "},
    )
    assert completed.status_code == 200, completed.text
    assert completed.json() == {"authenticated": True}
    assert auth_client.completed_codes == ["  demo-code  "]


def test_agent_plan_volc_login_start_reports_already_authenticated(
    model_admin_client,
) -> None:
    client, _ = model_admin_client
    csrf_token = _login(client)
    auth_client = FakeArkcliAuthClient()
    auth_client.already_authenticated = True
    client.app.dependency_overrides[get_arkcli_auth_client] = lambda: auth_client

    started = client.post(
        "/api/v1/admin/models/agent-plan/login",
        headers={"X-CSRF-Token": csrf_token},
    )

    assert started.status_code == 200, started.text
    assert started.json() == {
        "authorize_url": None,
        "expires_in_sec": None,
        "already_authenticated": True,
    }


def test_agent_plan_client_raises_auth_required_for_volc_sso(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_run(*args, **kwargs):
        del args, kwargs
        return subprocess.CompletedProcess(
            args=["arkcli"],
            returncode=1,
            stdout="",
            stderr="control plane requires Volc SSO STS; run arkcli auth login volc-sso",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)

    with pytest.raises(ModelCatalogAuthRequired, match="Volc SSO"):
        AgentPlanCatalogClient().list_models()


def test_arkcli_auth_client_parses_no_browser_challenge(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    commands: list[list[str]] = []

    def fake_run(command, **kwargs):
        del kwargs
        commands.append(list(command))
        return subprocess.CompletedProcess(
            args=command,
            returncode=0,
            stdout=(
                '{"stage":"authorize_pending","authorize_url":'
                '"https://signin.volcengine.com/authorize/oauth/authorize?x=1",'
                '"expires_in_sec":600}'
            ),
            stderr="",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)

    challenge = ArkcliAuthClient().start_volc_login()

    assert commands == [["arkcli", "auth", "login", "--no-browser"]]
    assert challenge.authorize_url == (
        "https://signin.volcengine.com/authorize/oauth/authorize?x=1"
    )
    assert challenge.expires_in_sec == 600
    assert challenge.already_authenticated is False


def test_arkcli_auth_client_completes_no_browser_login(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    commands: list[list[str]] = []

    def fake_run(command, **kwargs):
        del kwargs
        commands.append(list(command))
        return subprocess.CompletedProcess(
            args=command,
            returncode=0,
            stdout='{"auth_method":"sso_no_browser"}',
            stderr="",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)

    ArkcliAuthClient().complete_volc_login("  encoded-code  ")

    assert commands == [
        ["arkcli", "auth", "login", "--no-browser", "--code", "encoded-code"]
    ]
