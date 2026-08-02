from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx
import pytest

from app.v2.model_client import V2ModelClient, V2ModelError, V2QualityError


def _client(
    handler,
    *,
    agent_plan_api_key: str = "ark-key",
    deepseek_api_key: str = "deepseek-key",
    first_token_seconds: float = 2,
    total_seconds: float = 5,
) -> V2ModelClient:
    return V2ModelClient(
        agent_plan_api_key=agent_plan_api_key,
        agent_plan_base_url="https://ark.example.test/api/plan/v3",
        deepseek_api_key=deepseek_api_key,
        deepseek_base_url="https://api.deepseek.example.test",
        first_token_seconds=first_token_seconds,
        total_seconds=total_seconds,
        transport=httpx.MockTransport(handler),
    )


def _action_context() -> dict[str, Any]:
    return {
        "action_type": "day_speech",
        "candidates": [],
        "output_contract": {
            "kind": "speech",
            "speech": {"mode": "required"},
        },
    }


def _run_with_uvloop(coroutine: Any, uvloop: Any) -> Any:
    with asyncio.Runner(loop_factory=uvloop.new_event_loop) as runner:
        return runner.run(coroutine)


def test_model_client_disables_environment_proxy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_client_options: list[dict[str, Any]] = []
    real_async_client = httpx.AsyncClient

    def direct_async_client(*args: Any, **kwargs: Any) -> httpx.AsyncClient:
        captured_client_options.append(kwargs)
        return real_async_client(*args, **kwargs)

    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"x-request-id": "direct-request-id"},
            text=(
                'data: {"type":"response.output_text.delta",'
                '"delta":"{\\"speech\\":\\"直连响应\\"}"}\n\n'
                "data: [DONE]\n\n"
            ),
        )

    monkeypatch.setattr(
        "app.v2.model_client.httpx.AsyncClient",
        direct_async_client,
    )
    client = _client(handler)
    target = client.resolve_model_target(
        model_provider="agent_plan",
        model_id="minimax-m3",
        model_parameters={"thinking": "disabled", "max_tokens": 512},
    )

    decision = asyncio.run(
        client.generate_action_decision(
            action_context=_action_context(),
            attempt_id="v2_model_direct_transport",
            target=target,
        )
    )

    assert decision.speech == "直连响应"
    assert captured_client_options[0]["trust_env"] is False


def test_model_client_preserves_forbidden_speech_for_action_normalization() -> None:
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"x-request-id": "forbidden-speech-request"},
            text=(
                'data: {"type":"response.output_text.delta",'
                '"delta":"{\\"target_player_id\\":\\"seat_6\\",'
                '\\"speech\\":\\"违规发言只供审计\\"}"}\n\n'
                "data: [DONE]\n\n"
            ),
        )

    client = _client(handler)
    target = client.resolve_model_target(
        model_provider="agent_plan",
        model_id="minimax-m3",
        model_parameters={"thinking": "disabled", "max_tokens": 512},
    )
    context = {
        "model_context_schema_version": 8,
        "prompt_template_version": 2,
        "response": {
            "kind": "target",
            "target_policy": {"mode": "required"},
            "speech": {"mode": "forbidden"},
        },
    }

    decision = asyncio.run(
        client.generate_action_decision(
            action_context=context,
            attempt_id="v2_model_forbidden_speech",
            target=target,
        )
    )

    assert decision.target_player_id == "seat_6"
    assert decision.speech == "违规发言只供审计"


def test_model_client_parses_optional_private_decision_note() -> None:
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"x-request-id": "decision-note-request"},
            text=(
                'data: {"type":"response.output_text.delta",'
                '"delta":"{\\"target_player_id\\":\\"seat_6\\",'
                '\\"decision_note\\":\\"首夜随机覆盖中置位\\"}"}\n\n'
                "data: [DONE]\n\n"
            ),
        )

    client = _client(handler)
    target = client.resolve_model_target(
        model_provider="agent_plan",
        model_id="minimax-m3",
        model_parameters={"thinking": "disabled", "max_tokens": 512},
    )
    context = {
        "model_context_schema_version": 8,
        "prompt_template_version": 2,
        "response": {
            "kind": "target",
            "target_policy": {"mode": "required"},
            "speech": {"mode": "forbidden"},
            "decision_note": {"mode": "optional", "max_chars": 120},
        },
    }

    decision = asyncio.run(
        client.generate_action_decision(
            action_context=context,
            attempt_id="v2_model_decision_note",
            target=target,
        )
    )

    assert decision.target_player_id == "seat_6"
    assert decision.decision_note == "首夜随机覆盖中置位"


def test_model_client_does_not_timeout_immediately_under_uvloop() -> None:
    uvloop = pytest.importorskip("uvloop")

    async def handler(_request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(0.02)
        return httpx.Response(
            200,
            text=(
                'data: {"id":"chatcmpl-uvloop","choices":[{"delta":'
                '{"content":"{\\"speech\\":\\"uvloop 正常响应\\"}"}}]}\n\n'
                "data: [DONE]\n\n"
            ),
        )

    client = _client(
        handler,
        first_token_seconds=0.2,
        total_seconds=0.5,
    )
    target = client.resolve_model_target(
        model_provider="deepseek",
        model_id="deepseek-v4-flash",
        model_parameters={"thinking": "disabled", "max_tokens": 512},
    )

    decision = _run_with_uvloop(
        client.generate_action_decision(
            action_context=_action_context(),
            attempt_id="v2_model_test_uvloop_clock",
            target=target,
        ),
        uvloop,
    )

    assert decision.speech == "uvloop 正常响应"
    assert decision.first_token_ms >= 20


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


def test_sheriff_withdraw_uses_boolean_contract_without_target_player_id() -> None:
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            headers={"x-request-id": "deepseek-withdraw-request-id"},
            text=(
                'data: {"id":"chatcmpl-withdraw","choices":[{"delta":'
                '{"content":"{\\"withdraw\\":true,'
                '\\"speech\\":\\"9号选择退水。\\"}"}}]}\n\n'
                "data: [DONE]\n\n"
            ),
        )

    client = _client(handler)
    target = client.resolve_model_target(
        model_provider="deepseek",
        model_id="deepseek-v4-flash",
        model_parameters={"thinking": "disabled", "max_tokens": 512},
    )
    decision = asyncio.run(
        client.generate_action_decision(
            action_context={
                "action_type": "sheriff_withdraw",
                "candidates": [],
                "output_contract": {
                    "kind": "boolean",
                    "field": "withdraw",
                    "boolean": {
                        "true_means": "退水",
                        "false_means": "不退水",
                    },
                    "speech": {"mode": "required"},
                    "required_fields": ["withdraw", "speech"],
                },
            },
            attempt_id="v2_model_test_withdraw",
            target=target,
        )
    )

    assert decision.boolean_field == "withdraw"
    assert decision.boolean_value is True
    assert decision.target_player_id is None
    assert decision.speech == "9号选择退水。"
    payload = json.loads(requests[0].content)
    system_text = payload["messages"][0]["content"]
    assert "决定字段必须是 withdraw" in system_text
    assert "不要输出 target_player_id" in system_text


def test_sheriff_withdraw_quality_error_keeps_exact_raw_response() -> None:
    raw_response = '{"withdraw":true}'

    async def handler(_request: httpx.Request) -> httpx.Response:
        event = json.dumps(
            {
                "id": "chatcmpl-invalid-withdraw",
                "choices": [{"delta": {"content": raw_response}}],
            }
        )
        return httpx.Response(
            200,
            text=f"data: {event}\n\ndata: [DONE]\n\n",
        )

    client = _client(handler)
    target = client.resolve_model_target(
        model_provider="deepseek",
        model_id="deepseek-v4-flash",
        model_parameters={"thinking": "disabled", "max_tokens": 512},
    )

    with pytest.raises(
        V2QualityError,
        match="model_decision_invalid_speech",
    ) as caught:
        asyncio.run(
            client.generate_action_decision(
                action_context={
                    "action_type": "sheriff_withdraw",
                    "candidates": [],
                    "output_contract": {
                        "kind": "boolean",
                        "field": "withdraw",
                        "boolean": {
                            "true_means": "退水",
                            "false_means": "不退水",
                        },
                        "speech": {"mode": "required"},
                        "required_fields": ["withdraw", "speech"],
                    },
                },
                attempt_id="v2_model_test_invalid_withdraw",
                target=target,
            )
        )

    assert caught.value.raw_response == raw_response


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


def test_transport_reset_preserves_retry_diagnostics() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        try:
            raise ConnectionResetError(54, "Connection reset by peer")
        except ConnectionResetError as exc:
            raise httpx.ConnectError("proxy tunnel reset", request=request) from exc

    client = _client(handler)
    target = client.resolve_model_target(
        model_provider="deepseek",
        model_id="deepseek-v4-flash",
        model_parameters={"thinking": "enabled", "max_tokens": 2048},
    )

    with pytest.raises(V2ModelError, match="model_transport_failed") as caught:
        asyncio.run(
            client.generate_action_decision(
                action_context=_action_context(),
                attempt_id="v2_model_test_reset",
                target=target,
            )
        )

    assert caught.value.retryable is True
    assert caught.value.failure_stage == "connect"
    assert caught.value.exception_type == "builtins.ConnectionResetError"
    assert caught.value.errno == 54
    assert caught.value.first_token_seen is False
    assert caught.value.response_headers_seen is False
    assert caught.value.elapsed_ms is not None


def test_first_token_timeout_includes_response_header_wait() -> None:
    async def handler(_request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(0.05)
        return httpx.Response(200, text="data: [DONE]\n\n")

    client = _client(
        handler,
        first_token_seconds=0.01,
        total_seconds=0.1,
    )
    target = client.resolve_model_target(
        model_provider="deepseek",
        model_id="deepseek-v4-flash",
        model_parameters={"thinking": "enabled", "max_tokens": 2048},
    )

    with pytest.raises(V2ModelError, match="model_first_token_timeout") as caught:
        asyncio.run(
            client.generate_action_decision(
                action_context=_action_context(),
                attempt_id="v2_model_test_response_headers_timeout",
                target=target,
            )
        )

    assert caught.value.retryable is True
    assert caught.value.failure_stage == "response_headers"
    assert caught.value.response_headers_seen is False
    assert caught.value.first_token_seen is False


def test_total_timeout_after_first_token_is_retryable() -> None:
    class DelayedSSEStream(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield (
                b'data: {"id":"chatcmpl-timeout","choices":[{"delta":'
                b'{"reasoning_content":"thinking"}}]}\n\n'
            )
            await asyncio.sleep(0.05)
            yield b"data: [DONE]\n\n"

    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, stream=DelayedSSEStream())

    client = _client(
        handler,
        first_token_seconds=0.01,
        total_seconds=0.02,
    )
    target = client.resolve_model_target(
        model_provider="deepseek",
        model_id="deepseek-v4-flash",
        model_parameters={"thinking": "enabled", "max_tokens": 2048},
    )

    with pytest.raises(V2ModelError, match="model_total_timeout") as caught:
        asyncio.run(
            client.generate_action_decision(
                action_context=_action_context(),
                attempt_id="v2_model_test_stream_timeout",
                target=target,
            )
        )

    assert caught.value.retryable is True
    assert caught.value.failure_stage == "stream"
    assert caught.value.response_headers_seen is True
    assert caught.value.first_token_seen is True


def test_total_timeout_after_first_token_uses_uvloop_clock() -> None:
    uvloop = pytest.importorskip("uvloop")

    class DelayedSSEStream(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield (
                b'data: {"id":"chatcmpl-uvloop-timeout","choices":[{"delta":'
                b'{"reasoning_content":"thinking"}}]}\n\n'
            )
            await asyncio.sleep(0.05)
            yield b"data: [DONE]\n\n"

    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, stream=DelayedSSEStream())

    client = _client(
        handler,
        first_token_seconds=0.01,
        total_seconds=0.02,
    )
    target = client.resolve_model_target(
        model_provider="deepseek",
        model_id="deepseek-v4-flash",
        model_parameters={"thinking": "enabled", "max_tokens": 2048},
    )

    with pytest.raises(V2ModelError, match="model_total_timeout") as caught:
        _run_with_uvloop(
            client.generate_action_decision(
                action_context=_action_context(),
                attempt_id="v2_model_test_uvloop_stream_timeout",
                target=target,
            ),
            uvloop,
        )

    assert caught.value.retryable is True
    assert caught.value.failure_stage == "stream"
    assert caught.value.response_headers_seen is True
    assert caught.value.first_token_seen is True


@pytest.mark.parametrize(
    ("status_code", "retryable"),
    [(401, False), (502, True), (503, True), (504, True)],
)
def test_only_transient_http_statuses_are_retryable(
    status_code: int,
    retryable: bool,
) -> None:
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, text="provider unavailable")

    client = _client(handler)
    target = client.resolve_model_target(
        model_provider="deepseek",
        model_id="deepseek-v4-flash",
        model_parameters={"thinking": "enabled", "max_tokens": 2048},
    )

    with pytest.raises(V2ModelError, match=f"model_http_{status_code}") as caught:
        asyncio.run(
            client.generate_action_decision(
                action_context=_action_context(),
                attempt_id=f"v2_model_test_http_{status_code}",
                target=target,
            )
        )

    assert caught.value.retryable is retryable
    assert caught.value.failure_stage == "http_response"
    assert caught.value.http_status == status_code


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
