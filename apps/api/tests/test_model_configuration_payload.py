from __future__ import annotations

import time

from app.model_catalog.runtime import RuntimeModelConfiguration
from app.werewolf.execution_budget import ModelCallOptions
from app.werewolf.providers import (
    ARK_AGENT_PLAN_CONFIG,
    DEEPSEEK_CONFIG,
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
                "reasoning_effort": "medium",
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
