from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx
import pytest

from app.v2.model_client import V2ModelClient, V2ModelError


def _client(
    handler,
    *,
    agent_plan_api_key: str = "ark-key",
    deepseek_api_key: str = "deepseek-key",
) -> V2ModelClient:
    return V2ModelClient(
        agent_plan_api_key=agent_plan_api_key,
        agent_plan_base_url="https://ark.example.test/api/plan/v3",
        deepseek_api_key=deepseek_api_key,
        deepseek_base_url="https://api.deepseek.example.test",
        first_token_seconds=2,
        total_seconds=5,
        transport=httpx.MockTransport(handler),
    )


def _action_context() -> dict[str, Any]:
    return {
        "action_type": "day_speech",
        "candidates": [],
        "output_contract": {
            "kind": "public_speech",
            "target_policy": "none",
        },
    }


def test_agent_plan_target_uses_ark_responses_endpoint_and_credentials() -> None:
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            headers={"x-request-id": "ark-request-id"},
            text=(
                'data: {"type":"response.output_text.delta",'
                '"delta":"{\\"target_player_id\\":null,'
                '\\"speech\\":\\"火山响应\\"}"}\n\n'
                "data: [DONE]\n\n"
            ),
        )

    client = _client(handler)
    target = client.resolve_model_target(
        model_provider="agent_plan",
        model_id="deepseek-v4-flash",
        model_parameters={
            "thinking": "disabled",
            "max_tokens": 512,
            "temperature": 0.2,
            "frequency_penalty": 0.4,
            "presence_penalty": 0.5,
        },
    )
    decision = asyncio.run(
        client.generate_action_decision(
            action_context=_action_context(),
            attempt_id="v2_model_test_ark",
            target=target,
        )
    )

    assert decision.speech == "火山响应"
    assert decision.provider_request_id == "ark-request-id"
    assert len(requests) == 1
    request = requests[0]
    assert str(request.url) == "https://ark.example.test/api/plan/v3/responses"
    assert request.headers["authorization"] == "Bearer ark-key"
    payload = json.loads(request.content)
    assert payload["model"] == "deepseek-v4-flash"
    assert "input" in payload
    assert "messages" not in payload
    assert payload["thinking"] == {"type": "disabled"}
    assert payload["max_output_tokens"] == 512
    assert payload["temperature"] == 0.2
    assert "frequency_penalty" not in payload
    assert "presence_penalty" not in payload


def test_deepseek_target_uses_official_chat_completions_endpoint_and_credentials() -> None:
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            headers={"x-request-id": "deepseek-request-id"},
            text=(
                'data: {"id":"chatcmpl-deepseek","choices":[{"delta":'
                '{"content":"{\\"target_player_id\\":null,'
                '\\"speech\\":\\"官方响应\\"}"}}]}\n\n'
                "data: [DONE]\n\n"
            ),
        )

    client = _client(handler)
    target = client.resolve_model_target(
        model_provider="deepseek",
        model_id="deepseek-v4-flash",
        model_parameters={
            "thinking": "enabled",
            "max_tokens": 2048,
            "temperature": 0.9,
        },
    )
    decision = asyncio.run(
        client.generate_action_decision(
            action_context=_action_context(),
            attempt_id="v2_model_test_deepseek",
            target=target,
        )
    )

    assert decision.speech == "官方响应"
    assert decision.provider_request_id == "chatcmpl-deepseek"
    assert len(requests) == 1
    request = requests[0]
    assert str(request.url) == "https://api.deepseek.example.test/chat/completions"
    assert request.headers["authorization"] == "Bearer deepseek-key"
    payload = json.loads(request.content)
    assert payload["model"] == "deepseek-v4-flash"
    assert "messages" in payload
    assert "input" not in payload
    assert payload["thinking"] == {"type": "enabled"}
    assert payload["max_tokens"] == 2048
    assert "temperature" not in payload


def test_provider_credentials_are_required_without_cross_provider_fallback() -> None:
    async def handler(_request: httpx.Request) -> httpx.Response:
        raise AssertionError("request must not be attempted")

    client = _client(handler, deepseek_api_key="")

    with pytest.raises(V2ModelError, match="model_provider_credentials_missing"):
        client.resolve_model_target(
            model_provider="deepseek",
            model_id="deepseek-v4-flash",
            model_parameters={},
        )

    with pytest.raises(V2ModelError, match="model_provider_not_configured"):
        client.resolve_model_target(
            model_provider="unknown",
            model_id="deepseek-v4-flash",
            model_parameters={},
        )


def test_deepseek_reasoning_only_length_stop_reports_output_budget_exhausted() -> None:
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            text=(
                'data: {"id":"chatcmpl-budget","choices":[{"delta":'
                '{"reasoning_content":"先分析场上发言。"},"finish_reason":null}]}\n\n'
                'data: {"id":"chatcmpl-budget","choices":[{"delta":{},'
                '"finish_reason":"length"}]}\n\n'
                "data: [DONE]\n\n"
            ),
        )

    client = _client(handler)
    target = client.resolve_model_target(
        model_provider="deepseek",
        model_id="deepseek-v4-flash",
        model_parameters={"thinking": "enabled", "max_tokens": 2048},
    )

    with pytest.raises(V2ModelError, match="model_output_budget_exhausted"):
        asyncio.run(
            client.generate_action_decision(
                action_context=_action_context(),
                attempt_id="v2_model_test_budget",
                target=target,
            )
        )
