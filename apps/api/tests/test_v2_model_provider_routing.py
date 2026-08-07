from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx
import pytest

from app.v2.model_client import (
    V2ModelClient,
    V2ModelDecision,
    V2ModelError,
    V2ModelProgress,
    V2QualityError,
)


def _client(
    handler,
    *,
    agent_plan_api_key: str = "ark-key",
    deepseek_api_key: str = "deepseek-key",
    first_token_seconds: float = 2,
    stream_idle_seconds: float | None = None,
    total_seconds: float = 5,
    agent_plan_max_in_flight: int = 3,
    ark_max_in_flight: int = 3,
    deepseek_max_in_flight: int = 32,
) -> V2ModelClient:
    return V2ModelClient(
        agent_plan_api_key=agent_plan_api_key,
        agent_plan_base_url="https://ark.example.test/api/plan/v3",
        ark_api_key="ark-standard-key",
        ark_base_url="https://ark.example.test/api/v3",
        deepseek_api_key=deepseek_api_key,
        deepseek_base_url="https://api.deepseek.example.test",
        first_token_seconds=first_token_seconds,
        stream_idle_seconds=stream_idle_seconds or total_seconds,
        total_seconds=total_seconds,
        agent_plan_max_in_flight=agent_plan_max_in_flight,
        ark_max_in_flight=ark_max_in_flight,
        deepseek_max_in_flight=deepseek_max_in_flight,
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

    async def run_twice() -> tuple[V2ModelDecision, V2ModelDecision]:
        first = await client.generate_action_decision(
            action_context=_action_context(),
            attempt_id="v2_model_direct_transport",
            target=target,
        )
        second = await client.generate_action_decision(
            action_context=_action_context(),
            attempt_id="v2_model_direct_transport_again",
            target=target,
        )
        await client.aclose()
        return first, second

    decision, repeated_decision = asyncio.run(run_twice())

    assert decision.speech == "直连响应"
    assert repeated_decision.speech == "直连响应"
    assert len(captured_client_options) == 1
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


def test_model_client_repairs_identical_duplicate_json_once_and_preserves_raw() -> None:
    raw_response = (
        '{"target_player_id":"seat_6","decision_note":"首夜随机覆盖中置位"}'
        "\n\n```json\n"
        "{\n"
        '  "decision_note": "首夜随机覆盖中置位",\n'
        '  "target_player_id": "seat_6"\n'
        "}\n```"
    )
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        event = json.dumps(
            {
                "type": "response.output_text.delta",
                "delta": raw_response,
            },
            ensure_ascii=False,
        )
        return httpx.Response(200, text=f"data: {event}\n\ndata: [DONE]\n\n")

    client = _client(handler)
    target = client.resolve_model_target(
        model_provider="agent_plan",
        model_id="minimax-m3",
        model_parameters={"thinking": "disabled", "max_tokens": 512},
    )
    context = {
        "model_context_schema_version": 8,
        "prompt_template_version": 3,
        "response": {
            "kind": "target",
            "target_policy": {
                "mode": "required",
                "allowed_target_ids": ["seat_6"],
            },
            "speech": {"mode": "forbidden"},
            "decision_note": {"mode": "optional", "max_chars": 120},
        },
    }

    decision = asyncio.run(
        client.generate_action_decision(
            action_context=context,
            attempt_id="v2_model_duplicate_json",
            target=target,
        )
    )

    assert len(requests) == 1
    assert decision.target_player_id == "seat_6"
    assert decision.speech is None
    assert decision.decision_note == "首夜随机覆盖中置位"
    assert decision.repair_kind == "duplicate_identical_json_ignored"
    assert decision.raw_response == raw_response


def test_model_client_ambiguous_duplicate_json_keeps_exact_raw_response() -> None:
    raw_response = '{"target_player_id":"seat_6"}\n```json\n{"target_player_id":"seat_5"}\n```'

    async def handler(_request: httpx.Request) -> httpx.Response:
        event = json.dumps(
            {
                "type": "response.output_text.delta",
                "delta": raw_response,
            }
        )
        return httpx.Response(200, text=f"data: {event}\n\ndata: [DONE]\n\n")

    client = _client(handler)
    target = client.resolve_model_target(
        model_provider="agent_plan",
        model_id="minimax-m3",
        model_parameters={"thinking": "disabled", "max_tokens": 512},
    )

    with pytest.raises(
        V2QualityError,
        match="model_decision_ambiguous_multiple_objects",
    ) as caught:
        asyncio.run(
            client.generate_action_decision(
                action_context={
                    "model_context_schema_version": 8,
                    "prompt_template_version": 3,
                    "response": {
                        "kind": "target",
                        "target_policy": {
                            "mode": "required",
                            "allowed_target_ids": ["seat_5", "seat_6"],
                        },
                        "speech": {"mode": "forbidden"},
                    },
                },
                attempt_id="v2_model_ambiguous_duplicate_json",
                target=target,
            )
        )

    assert caught.value.raw_response == raw_response


def test_model_client_rejects_non_string_target_in_duplicate_json() -> None:
    raw_response = '{"target_player_id":1}\n{"target_player_id":null}'

    async def handler(_request: httpx.Request) -> httpx.Response:
        event = json.dumps(
            {
                "type": "response.output_text.delta",
                "delta": raw_response,
            }
        )
        return httpx.Response(200, text=f"data: {event}\n\ndata: [DONE]\n\n")

    client = _client(handler)
    target = client.resolve_model_target(
        model_provider="agent_plan",
        model_id="minimax-m3",
        model_parameters={"thinking": "disabled", "max_tokens": 512},
    )

    with pytest.raises(V2QualityError, match="model_decision_invalid_target") as caught:
        asyncio.run(
            client.generate_action_decision(
                action_context={
                    "model_context_schema_version": 8,
                    "prompt_template_version": 3,
                    "response": {
                        "kind": "target",
                        "target_policy": {"mode": "required"},
                        "speech": {"mode": "forbidden"},
                    },
                },
                attempt_id="v2_model_duplicate_invalid_target",
                target=target,
            )
        )

    assert caught.value.raw_response == raw_response


def test_model_client_treats_different_extra_payload_fields_as_ambiguous() -> None:
    raw_response = (
        '{"target_player_id":"seat_6","provider_trace":{"choice":1}}\n'
        '{"target_player_id":"seat_6","provider_trace":{"choice":2}}'
    )

    async def handler(_request: httpx.Request) -> httpx.Response:
        event = json.dumps(
            {
                "type": "response.output_text.delta",
                "delta": raw_response,
            }
        )
        return httpx.Response(200, text=f"data: {event}\n\ndata: [DONE]\n\n")

    client = _client(handler)
    target = client.resolve_model_target(
        model_provider="agent_plan",
        model_id="minimax-m3",
        model_parameters={"thinking": "disabled", "max_tokens": 512},
    )

    with pytest.raises(
        V2QualityError,
        match="model_decision_ambiguous_multiple_objects",
    ) as caught:
        asyncio.run(
            client.generate_action_decision(
                action_context={
                    "model_context_schema_version": 8,
                    "prompt_template_version": 3,
                    "response": {
                        "kind": "target",
                        "target_policy": {"mode": "required"},
                        "speech": {"mode": "forbidden"},
                    },
                },
                attempt_id="v2_model_duplicate_extra_fields",
                target=target,
            )
        )

    assert caught.value.raw_response == raw_response


def test_model_client_rejects_truncated_second_speech_object_without_fragment_fallback() -> None:
    raw_response = '{"speech":"第一句"}{"speech":"第二句"'

    async def handler(_request: httpx.Request) -> httpx.Response:
        event = json.dumps(
            {
                "type": "response.output_text.delta",
                "delta": raw_response,
            },
            ensure_ascii=False,
        )
        return httpx.Response(200, text=f"data: {event}\n\ndata: [DONE]\n\n")

    client = _client(handler)
    target = client.resolve_model_target(
        model_provider="agent_plan",
        model_id="minimax-m3",
        model_parameters={"thinking": "disabled", "max_tokens": 512},
    )

    with pytest.raises(
        V2QualityError,
        match="model_decision_invalid_json_document",
    ) as caught:
        asyncio.run(
            client.generate_action_decision(
                action_context={
                    "model_context_schema_version": 8,
                    "prompt_template_version": 3,
                    "response": {
                        "kind": "speech",
                        "speech": {"mode": "required"},
                    },
                },
                attempt_id="v2_model_truncated_second_object",
                target=target,
            )
        )

    assert caught.value.raw_response == raw_response


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


def test_ark_target_uses_standard_responses_endpoint_and_credentials() -> None:
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            headers={"x-request-id": "ark-standard-request-id"},
            text=(
                'data: {"type":"response.output_text.delta",'
                '"delta":"{\\"speech\\":\\"标准方舟响应\\"}"}\n\n'
                "data: [DONE]\n\n"
            ),
        )

    client = _client(handler)
    target = client.resolve_model_target(
        model_provider="ark",
        model_id="ep-glm-5-2",
        model_parameters={"thinking": "enabled", "max_tokens": 16_384},
    )

    decision = asyncio.run(
        client.generate_action_decision(
            action_context=_action_context(),
            attempt_id="v2_model_test_ark_standard",
            target=target,
        )
    )

    assert decision.speech == "标准方舟响应"
    assert len(requests) == 1
    request = requests[0]
    assert str(request.url) == "https://ark.example.test/api/v3/responses"
    assert request.headers["authorization"] == "Bearer ark-standard-key"
    payload = json.loads(request.content)
    assert payload["model"] == "ep-glm-5-2"
    assert payload["thinking"] == {"type": "enabled"}


def test_provider_concurrency_is_bounded_without_serializing_other_providers() -> None:
    active = {"ark.example.test": 0, "api.deepseek.example.test": 0}
    maximum = {"ark.example.test": 0, "api.deepseek.example.test": 0}
    overlap_seen = False

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal overlap_seen
        host = request.url.host
        assert host in active
        active[host] += 1
        maximum[host] = max(maximum[host], active[host])
        overlap_seen = overlap_seen or all(count > 0 for count in active.values())
        try:
            await asyncio.sleep(0.03)
            if host == "ark.example.test":
                body = (
                    'data: {"type":"response.output_text.delta",'
                    '"delta":"{\\"speech\\":\\"方舟完成\\"}"}\n\n'
                    "data: [DONE]\n\n"
                )
            else:
                body = (
                    'data: {"id":"chatcmpl-bounded","choices":[{"delta":'
                    '{"content":"{\\"speech\\":\\"DeepSeek完成\\"}"}}]}\n\n'
                    "data: [DONE]\n\n"
                )
            return httpx.Response(200, text=body)
        finally:
            active[host] -= 1

    async def run_requests() -> list:
        client = _client(
            handler,
            agent_plan_max_in_flight=2,
            deepseek_max_in_flight=2,
        )
        agent_target = client.resolve_model_target(
            model_provider="agent_plan",
            model_id="glm-5-2-260617",
            model_parameters={"thinking": "enabled", "max_tokens": 16_384},
        )
        deepseek_target = client.resolve_model_target(
            model_provider="deepseek",
            model_id="deepseek-v4-flash",
            model_parameters={"thinking": "enabled", "max_tokens": 16_384},
        )
        return await asyncio.gather(
            *[
                client.generate_action_decision(
                    action_context=_action_context(),
                    attempt_id=f"v2_model_agent_{index}",
                    target=agent_target,
                )
                for index in range(5)
            ],
            client.generate_action_decision(
                action_context=_action_context(),
                attempt_id="v2_model_deepseek_parallel",
                target=deepseek_target,
            ),
        )

    decisions = asyncio.run(run_requests())

    assert maximum["ark.example.test"] == 2
    assert maximum["api.deepseek.example.test"] == 1
    assert overlap_seen is True
    assert any(decision.queue_wait_ms > 0 for decision in decisions[:5])
    assert all(decision.provider_concurrency_limit == 2 for decision in decisions)


def test_provider_queue_wait_does_not_consume_first_token_or_hard_timeout() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(0.03)
        return httpx.Response(
            200,
            text=(
                'data: {"type":"response.output_text.delta",'
                '"delta":"{\\"speech\\":\\"排队后完成\\"}"}\n\n'
                "data: [DONE]\n\n"
            ),
        )

    async def run_requests() -> list:
        client = _client(
            handler,
            first_token_seconds=0.05,
            stream_idle_seconds=0.05,
            total_seconds=0.05,
            agent_plan_max_in_flight=1,
        )
        target = client.resolve_model_target(
            model_provider="agent_plan",
            model_id="glm-5-2-260617",
            model_parameters={"thinking": "enabled", "max_tokens": 16_384},
        )
        return await asyncio.gather(
            *[
                client.generate_action_decision(
                    action_context=_action_context(),
                    attempt_id=f"v2_model_queued_{index}",
                    target=target,
                )
                for index in range(2)
            ]
        )

    decisions = asyncio.run(run_requests())

    assert [decision.speech for decision in decisions] == ["排队后完成", "排队后完成"]
    assert decisions[1].queue_wait_ms >= 20
    assert decisions[1].completed_ms < 50


def test_canceled_provider_queue_wait_returns_the_permit() -> None:
    first_request_started = asyncio.Event()
    release_first_request = asyncio.Event()
    request_count = 0

    async def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal request_count
        request_count += 1
        if request_count == 1:
            first_request_started.set()
            await release_first_request.wait()
        return httpx.Response(
            200,
            text=(
                'data: {"type":"response.output_text.delta",'
                '"delta":"{\\"speech\\":\\"取消后完成\\"}"}\n\n'
                "data: [DONE]\n\n"
            ),
        )

    async def run_requests() -> tuple[V2ModelDecision, V2ModelDecision]:
        client = _client(handler, agent_plan_max_in_flight=1)
        target = client.resolve_model_target(
            model_provider="agent_plan",
            model_id="glm-5-2-260617",
            model_parameters={"thinking": "enabled", "max_tokens": 16_384},
        )
        first_task = asyncio.create_task(
            client.generate_action_decision(
                action_context=_action_context(),
                attempt_id="v2_model_gate_owner",
                target=target,
            )
        )
        await first_request_started.wait()

        cancellation_checks = 0

        def cancel_queued_request() -> None:
            nonlocal cancellation_checks
            cancellation_checks += 1
            if cancellation_checks >= 2:
                raise RuntimeError("scripted queue cancellation")

        with pytest.raises(RuntimeError, match="scripted queue cancellation"):
            await client.generate_action_decision(
                action_context=_action_context(),
                attempt_id="v2_model_gate_canceled",
                target=target,
                check_cancellation=cancel_queued_request,
            )

        release_first_request.set()
        first = await first_task
        third = await asyncio.wait_for(
            client.generate_action_decision(
                action_context=_action_context(),
                attempt_id="v2_model_gate_after_cancellation",
                target=target,
            ),
            timeout=0.2,
        )
        await client.aclose()
        return first, third

    first, third = asyncio.run(run_requests())

    assert first.speech == third.speech == "取消后完成"
    assert request_count == 2


def test_reasoning_progress_resets_stream_idle_timeout() -> None:
    class ProgressingSSEStream(httpx.AsyncByteStream):
        async def __aiter__(self):
            for index in range(3):
                yield (
                    'data: {"id":"chatcmpl-progressing","choices":[{"delta":'
                    f'{{"reasoning_content":"step-{index}"}}}}]}}\n\n'
                ).encode()
                await asyncio.sleep(0.015)
            yield (
                'data: {"id":"chatcmpl-progressing","choices":[{"delta":'
                '{"content":"{\\"speech\\":\\"持续推理完成\\"}"}}]}\n\n'
            ).encode()
            yield b"data: [DONE]\n\n"

    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, stream=ProgressingSSEStream())

    client = _client(
        handler,
        first_token_seconds=0.03,
        stream_idle_seconds=0.025,
        total_seconds=0.2,
    )
    target = client.resolve_model_target(
        model_provider="deepseek",
        model_id="deepseek-v4-flash",
        model_parameters={"thinking": "enabled", "max_tokens": 16_384},
    )

    decision = asyncio.run(
        client.generate_action_decision(
            action_context=_action_context(),
            attempt_id="v2_model_progressing_reasoning",
            target=target,
        )
    )

    assert decision.speech == "持续推理完成"
    assert decision.reasoning_delta_count == 3
    assert decision.text_delta_count == 1
    assert decision.max_inter_delta_ms is not None
    assert decision.max_inter_delta_ms < 25


def test_stream_idle_timeout_distinguishes_stall_from_hard_timeout() -> None:
    class StalledSSEStream(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield (
                b'data: {"id":"chatcmpl-stalled","choices":[{"delta":'
                b'{"reasoning_content":"started"}}]}\n\n'
            )
            await asyncio.sleep(0.06)
            yield b"data: [DONE]\n\n"

    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, stream=StalledSSEStream())

    client = _client(
        handler,
        first_token_seconds=0.03,
        stream_idle_seconds=0.02,
        total_seconds=0.2,
    )
    target = client.resolve_model_target(
        model_provider="deepseek",
        model_id="deepseek-v4-flash",
        model_parameters={"thinking": "enabled", "max_tokens": 16_384},
    )

    with pytest.raises(V2ModelError, match="model_stream_idle_timeout") as caught:
        asyncio.run(
            client.generate_action_decision(
                action_context=_action_context(),
                attempt_id="v2_model_stalled_reasoning",
                target=target,
            )
        )

    assert caught.value.timeout_scope == "stream_idle"
    assert caught.value.reasoning_delta_count == 1
    assert caught.value.first_token_seen is True


def test_attempt_hard_timeout_caps_continuously_progressing_reasoning() -> None:
    class NeverEndingReasoningStream(httpx.AsyncByteStream):
        async def __aiter__(self):
            for index in range(20):
                yield (
                    'data: {"id":"chatcmpl-hard-cap","choices":[{"delta":'
                    f'{{"reasoning_content":"step-{index}"}}}}]}}\n\n'
                ).encode()
                await asyncio.sleep(0.01)

    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, stream=NeverEndingReasoningStream())

    client = _client(
        handler,
        first_token_seconds=0.03,
        stream_idle_seconds=0.03,
        total_seconds=0.045,
    )
    target = client.resolve_model_target(
        model_provider="deepseek",
        model_id="deepseek-v4-flash",
        model_parameters={"thinking": "enabled", "max_tokens": 16_384},
    )

    with pytest.raises(V2ModelError, match="model_attempt_hard_timeout") as caught:
        asyncio.run(
            client.generate_action_decision(
                action_context=_action_context(),
                attempt_id="v2_model_continuous_reasoning_hard_cap",
                target=target,
            )
        )

    assert caught.value.timeout_scope == "attempt_hard"
    assert caught.value.reasoning_delta_count >= 3
    assert caught.value.text_delta_count == 0
    assert caught.value.first_token_seen is True


def test_model_progress_reports_headers_reasoning_token_and_first_visible_text() -> None:
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={
                "x-request-id": "header-request-id",
                "ratelimit-remaining": "23",
                "x-ratelimit-remaining-requests": "17",
                "authorization": "Bearer must-not-persist",
                "cookie": "provider-session=must-not-persist",
                "set-cookie": "provider-session=must-not-persist",
                "www-authenticate": "Bearer must-not-persist",
                "x-api-key": "must-not-persist",
                "x-trace-api-key": "must-not-persist",
                "x-trace-user-email": "must-not-persist@example.test",
                "x-ratelimit-api-key": "must-not-persist",
                "ratelimit-custom-secret": "must-not-persist",
                "x-unlisted-provider-metadata": "must-not-persist",
            },
            text=(
                'data: {"id":"chatcmpl-progress","choices":[{"delta":'
                '{"reasoning_content":"thinking"}}]}\n\n'
                'data: {"id":"chatcmpl-progress","choices":[{"delta":'
                '{"content":"{\\"speech\\":\\"进度响应\\"}"}}]}\n\n'
                "data: [DONE]\n\n"
            ),
        )

    client = _client(handler)
    target = client.resolve_model_target(
        model_provider="deepseek",
        model_id="deepseek-v4-flash",
        model_parameters={"thinking": "enabled", "max_tokens": 2048},
    )
    progress: list[V2ModelProgress] = []

    decision = asyncio.run(
        client.generate_action_decision_with_progress(
            action_context=_action_context(),
            attempt_id="v2_model_test_progress",
            target=target,
            on_progress=progress.append,
        )
    )

    assert decision.speech == "进度响应"
    assert [item.stage for item in progress] == [
        "queued",
        "admitted",
        "response_headers",
        "first_token",
        "first_text",
    ]
    headers = progress[2].response_headers
    assert headers is not None
    assert headers["x-request-id"] == "header-request-id"
    assert headers["ratelimit-remaining"] == "23"
    assert headers["x-ratelimit-remaining-requests"] == "17"
    assert {
        "authorization",
        "cookie",
        "set-cookie",
        "www-authenticate",
        "x-api-key",
        "x-trace-api-key",
        "x-trace-user-email",
        "x-ratelimit-api-key",
        "ratelimit-custom-secret",
        "x-unlisted-provider-metadata",
    }.isdisjoint(headers)
    assert progress[3].provider_request_id == "chatcmpl-progress"
    assert progress[3].token_kind == "reasoning"
    assert progress[4].provider_request_id == "chatcmpl-progress"
    assert progress[4].token_kind == "text"
    assert progress[2].elapsed_ms <= progress[3].elapsed_ms <= progress[4].elapsed_ms


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


def test_attempt_hard_timeout_also_caps_response_header_wait() -> None:
    async def handler(_request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(0.05)
        return httpx.Response(200, text="data: [DONE]\n\n")

    client = _client(
        handler,
        first_token_seconds=0.1,
        total_seconds=0.02,
    )
    target = client.resolve_model_target(
        model_provider="deepseek",
        model_id="deepseek-v4-flash",
        model_parameters={"thinking": "enabled", "max_tokens": 2048},
    )

    with pytest.raises(V2ModelError, match="model_attempt_hard_timeout") as caught:
        asyncio.run(
            client.generate_action_decision(
                action_context=_action_context(),
                attempt_id="v2_model_header_hard_cap",
                target=target,
            )
        )

    assert caught.value.timeout_scope == "attempt_hard"
    assert caught.value.failure_stage == "response_headers"
    assert caught.value.response_headers_seen is False


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

    with pytest.raises(V2ModelError, match="model_attempt_hard_timeout") as caught:
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
    assert caught.value.timeout_scope == "attempt_hard"


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

    with pytest.raises(V2ModelError, match="model_attempt_hard_timeout") as caught:
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
    assert caught.value.timeout_scope == "attempt_hard"


@pytest.mark.parametrize(
    ("status_code", "retryable"),
    [(401, False), (429, True), (502, True), (503, True), (504, True)],
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


def test_rate_limit_preserves_retry_after_delay() -> None:
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            429,
            text="rate limited",
            headers={"Retry-After": "1.5"},
        )

    client = _client(handler)
    target = client.resolve_model_target(
        model_provider="deepseek",
        model_id="deepseek-v4-flash",
        model_parameters={"thinking": "enabled", "max_tokens": 2048},
    )

    with pytest.raises(V2ModelError, match="model_http_429") as caught:
        asyncio.run(
            client.generate_action_decision(
                action_context=_action_context(),
                attempt_id="v2_model_test_http_429_retry_after",
                target=target,
            )
        )

    assert caught.value.retryable is True
    assert caught.value.retry_after_seconds == 1.5


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
