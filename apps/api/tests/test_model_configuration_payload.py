from __future__ import annotations

import time
from types import SimpleNamespace

import pytest

from app.model_catalog.runtime import (
    RuntimeModelConfiguration,
    runtime_configuration_for_model,
)
from app.werewolf.execution_budget import ModelCallOptions
from app.werewolf.providers import (
    ARK_AGENT_PLAN_CONFIG,
    DEEPSEEK_CONFIG,
    ModelRuntimeConfigurationError,
    OpenAICompatibleProvider,
)


def test_agent_plan_runtime_configuration_is_applied_to_chat_payload(monkeypatch) -> None:
    requests = []

    def transport(url, headers, payload, **_kwargs):
        requests.append(payload)
        return {"choices": [{"message": {"content": "{}"}}]}

    monkeypatch.setattr(
        "app.werewolf.providers.runtime_configuration_for_model",
        lambda provider, model: RuntimeModelConfiguration(
            provider=provider,
            model_id=model,
            supports_thinking=True,
            parameters={
                "thinking": "enabled",
                "reasoning_effort": "high",
                "max_tokens_mode": "manual",
                "temperature": 0.25,
                "top_p": 0.9,
                "max_tokens": 4096,
                "frequency_penalty": 0.1,
                "presence_penalty": 0.2,
            },
        ),
    )
    provider = OpenAICompatibleProvider(
        config=ARK_AGENT_PLAN_CONFIG,
        api_key="test",
        transport=transport,
    )
    provider.complete_json(
        model="agent-model",
        prompt="{}",
        temperature=0.8,
        call_options=ModelCallOptions(
            deadline_at_monotonic=time.monotonic() + 10,
            request_timeout_seconds=10,
            max_output_tokens=512,
        ),
    )

    assert requests[0]["temperature"] == 0.25
    assert requests[0]["thinking"] == {"type": "enabled"}
    assert requests[0]["reasoning_effort"] == "high"
    assert requests[0]["top_p"] == 0.9
    assert requests[0]["max_completion_tokens"] == 512
    assert "max_tokens" not in requests[0]
    assert "max_tokens_mode" not in requests[0]
    assert requests[0]["frequency_penalty"] == 0.1
    assert requests[0]["presence_penalty"] == 0.2


def test_deepseek_thinking_payload_omits_ignored_sampling_parameters(monkeypatch) -> None:
    requests = []

    def transport(url, headers, payload, **_kwargs):
        requests.append(payload)
        return {"choices": [{"message": {"content": "{}"}}]}

    monkeypatch.setattr(
        "app.werewolf.providers.runtime_configuration_for_model",
        lambda provider, model: RuntimeModelConfiguration(
            provider=provider,
            model_id=model,
            supports_thinking=True,
            parameters={
                "thinking": "enabled",
                "reasoning_effort": "max",
                "max_tokens_mode": "manual",
                "max_tokens": 2048,
            },
        ),
    )
    provider = OpenAICompatibleProvider(
        config=DEEPSEEK_CONFIG,
        api_key="test",
        transport=transport,
    )
    provider.complete_json(
        model="deepseek-v4-pro",
        prompt="{}",
        temperature=0.8,
    )

    assert "temperature" not in requests[0]
    assert requests[0]["thinking"] == {"type": "enabled"}
    assert requests[0]["reasoning_effort"] == "max"
    assert requests[0]["max_tokens"] == 2048
    assert "max_tokens_mode" not in requests[0]


def test_agent_plan_deepseek_thinking_payload_uses_model_sampling_policy(
    monkeypatch,
) -> None:
    requests = []

    def transport(url, headers, payload, **_kwargs):
        requests.append(payload)
        return {"choices": [{"message": {"content": "{}"}}]}

    monkeypatch.setattr(
        "app.werewolf.providers.runtime_configuration_for_model",
        lambda provider, model: RuntimeModelConfiguration(
            provider=provider,
            model_id=model,
            supports_thinking=True,
            parameters={
                "thinking": "enabled",
                "reasoning_effort": "high",
                "max_tokens_mode": "manual",
                "max_tokens": 2048,
                "temperature": 0.8,
                "top_p": 0.9,
                "frequency_penalty": 0.1,
                "presence_penalty": 0.2,
            },
        ),
    )
    provider = OpenAICompatibleProvider(
        config=ARK_AGENT_PLAN_CONFIG,
        api_key="test",
        transport=transport,
    )

    provider.complete_json(
        model="deepseek-v4-flash",
        prompt="{}",
        temperature=0.7,
    )

    assert requests[0]["thinking"] == {"type": "enabled"}
    assert requests[0]["reasoning_effort"] == "high"
    assert requests[0]["max_completion_tokens"] == 2048
    for parameter in (
        "temperature",
        "top_p",
        "frequency_penalty",
        "presence_penalty",
    ):
        assert parameter not in requests[0]


def test_runtime_payload_omits_stored_reasoning_effort_when_thinking_is_disabled(
    monkeypatch,
) -> None:
    requests = []

    def transport(url, headers, payload, **_kwargs):
        requests.append(payload)
        return {"choices": [{"message": {"content": "{}"}}]}

    monkeypatch.setattr(
        "app.werewolf.providers.runtime_configuration_for_model",
        lambda provider, model: RuntimeModelConfiguration(
            provider=provider,
            model_id=model,
            supports_thinking=True,
            parameters={
                "thinking": "disabled",
                "reasoning_effort": None,
                "max_tokens_mode": "auto",
                "max_tokens": 512,
            },
        ),
    )
    provider = OpenAICompatibleProvider(
        config=ARK_AGENT_PLAN_CONFIG,
        api_key="test",
        transport=transport,
    )

    provider.complete_json(
        model="agent-model",
        prompt="{}",
        temperature=0.8,
    )

    assert requests[0]["thinking"] == {"type": "disabled"}
    assert "reasoning_effort" not in requests[0]
    assert "max_tokens_mode" not in requests[0]


def test_runtime_payload_omits_thinking_fields_for_model_without_capability(
    monkeypatch,
) -> None:
    requests = []

    def transport(url, headers, payload, **_kwargs):
        requests.append(payload)
        return {"choices": [{"message": {"content": "{}"}}]}

    monkeypatch.setattr(
        "app.werewolf.providers.runtime_configuration_for_model",
        lambda provider, model: RuntimeModelConfiguration(
            provider=provider,
            model_id=model,
            supports_thinking=False,
            parameters={
                "thinking": "disabled",
                "reasoning_effort": None,
                "max_tokens_mode": "auto",
                "max_tokens": 512,
            },
        ),
    )
    provider = OpenAICompatibleProvider(
        config=ARK_AGENT_PLAN_CONFIG,
        api_key="test",
        transport=transport,
    )

    provider.complete_json(
        model="non-thinking-model",
        prompt="{}",
        temperature=0.8,
    )

    assert requests[0]["max_tokens"] == 512
    assert "thinking" not in requests[0]
    assert "reasoning_effort" not in requests[0]
    assert "max_tokens_mode" not in requests[0]


def test_runtime_configuration_rejects_legacy_partial_parameter_schema(
    monkeypatch,
) -> None:
    record = SimpleNamespace(
        provider="agent_plan",
        model_id="glm-5-2-260617",
        available=True,
        enabled=True,
        supports_thinking=True,
        parameter_values={"thinking": "enabled", "max_tokens": 16_384},
    )

    class FakeSession:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def get(self, _model, _key):
            return record

    monkeypatch.setattr("app.model_catalog.runtime.SessionLocal", FakeSession)

    with pytest.raises(ValueError, match="missing required parameters"):
        runtime_configuration_for_model("agent_plan", "glm-5-2-260617")


def test_provider_fails_closed_when_runtime_configuration_is_missing(
    monkeypatch,
) -> None:
    transport_called = False

    def transport(url, headers, payload, **_kwargs):
        nonlocal transport_called
        transport_called = True
        return {"choices": [{"message": {"content": "{}"}}]}

    monkeypatch.setattr(
        "app.werewolf.providers.runtime_configuration_for_model",
        lambda _provider, _model: None,
    )
    provider = OpenAICompatibleProvider(
        config=ARK_AGENT_PLAN_CONFIG,
        api_key="test",
        transport=transport,
    )

    with pytest.raises(
        ModelRuntimeConfigurationError,
        match="model_runtime_configuration_missing",
    ):
        provider.complete_json(
            model="glm-5-2-260617",
            prompt="{}",
            temperature=0.8,
        )

    assert transport_called is False


def test_provider_fails_closed_when_runtime_configuration_is_invalid(
    monkeypatch,
) -> None:
    def invalid_runtime_configuration(_provider, _model):
        raise ValueError("stale automatic max_tokens")

    monkeypatch.setattr(
        "app.werewolf.providers.runtime_configuration_for_model",
        invalid_runtime_configuration,
    )
    provider = OpenAICompatibleProvider(
        config=ARK_AGENT_PLAN_CONFIG,
        api_key="test",
        transport=lambda *_args, **_kwargs: pytest.fail("transport must not be called"),
    )

    with pytest.raises(
        ModelRuntimeConfigurationError,
        match="model_runtime_configuration_invalid",
    ):
        provider.complete_json(
            model="glm-5-2-260617",
            prompt="{}",
            temperature=0.8,
        )
