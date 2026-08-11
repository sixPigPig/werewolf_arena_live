from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx
import pytest

from app.v2.model_client import (
    V2ModelClient,
    V2ModelError,
    V2ModelProgress,
    V2ModelTarget,
)
from app.v2.model_context_compaction import encode_known_events_v6
from app.v2.model_context_contract import MODEL_CONTEXT_SCHEMA_VERSION, PROMPT_TEMPLATE_VERSION


def _action_context() -> dict[str, Any]:
    return {
        "model_context_schema_version": MODEL_CONTEXT_SCHEMA_VERSION,
        "prompt_template_version": PROMPT_TEMPLATE_VERSION,
        "action_type": "day_debate_speech",
        "known_events": encode_known_events_v6(
            {
                "schema_version": 5,
                "events": [],
                "questions": [],
                "relations": [],
            }
        ),
        "candidates": [],
        "response": {
            "kind": "speech",
            "speech": {"mode": "required"},
        },
    }


def _client(handler: Any, *, max_in_flight: int = 1) -> V2ModelClient:
    return V2ModelClient(
        agent_plan_api_key="agent-plan-key",
        agent_plan_base_url="https://ark.example.test/api/plan/v3",
        ark_api_key="ark-key",
        ark_base_url="https://ark.example.test/api/v3",
        deepseek_api_key="deepseek-key",
        deepseek_base_url="https://deepseek.example.test",
        first_token_seconds=1,
        stream_idle_seconds=1,
        total_seconds=2,
        agent_plan_max_in_flight=max_in_flight,
        transport=httpx.MockTransport(handler),
    )


def _target(client: V2ModelClient) -> V2ModelTarget:
    return client.resolve_model_target(
        model_provider="agent_plan",
        model_id="glm-5-2-260617",
        model_supports_thinking=True,
        model_parameters={
            "thinking": "enabled",
            "reasoning_effort": "high",
            "max_tokens_mode": "manual",
            "max_tokens": 16_384,
        },
    )


def _completed_response(speech: str) -> httpx.Response:
    event = json.dumps(
        {
            "type": "response.output_text.delta",
            "delta": json.dumps({"speech": speech}, ensure_ascii=False),
        },
        ensure_ascii=False,
    )
    return httpx.Response(200, text=f"data: {event}\n\ndata: [DONE]\n\n")


def test_idle_only_admits_immediately_when_provider_has_idle_capacity() -> None:
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return _completed_response("空闲预生成完成")

    async def scenario() -> None:
        client = _client(handler)
        progress: list[V2ModelProgress] = []
        try:
            decision = await client.generate_action_decision_with_progress(
                action_context=_action_context(),
                attempt_id="v2_model_idle_success",
                target=_target(client),
                admission_mode="idle_only",
                on_progress=progress.append,
            )
        finally:
            await client.aclose()

        assert decision.speech == "空闲预生成完成"
        assert len(requests) == 1
        assert [item.stage for item in progress[:2]] == ["queued", "admitted"]
        assert progress[1].provider_in_flight == 1
        assert progress[1].provider_concurrency_limit == 1

    asyncio.run(scenario())


def test_idle_only_fails_immediately_when_provider_is_full_without_http() -> None:
    owner_started = asyncio.Event()
    release_owner = asyncio.Event()
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        owner_started.set()
        await release_owner.wait()
        return _completed_response("占用请求完成")

    async def scenario() -> None:
        client = _client(handler)
        target = _target(client)
        owner = asyncio.create_task(
            client.generate_action_decision(
                action_context=_action_context(),
                attempt_id="v2_model_capacity_owner",
                target=target,
            )
        )
        await asyncio.wait_for(owner_started.wait(), timeout=0.5)
        progress: list[V2ModelProgress] = []
        try:
            with pytest.raises(V2ModelError) as raised:
                await asyncio.wait_for(
                    client.generate_action_decision_with_progress(
                        action_context=_action_context(),
                        attempt_id="v2_model_prefetch_rejected",
                        target=target,
                        admission_mode="idle_only",
                        on_progress=progress.append,
                    ),
                    timeout=0.1,
                )
            error = raised.value
            assert error.code == "model_prefetch_capacity_unavailable"
            assert error.retryable is False
            assert error.failure_stage == "provider_admission"
            assert error.provider_in_flight == 1
            assert error.provider_concurrency_limit == 1
            assert error.queue_wait_ms is not None and error.queue_wait_ms <= 10
            assert [item.stage for item in progress] == ["queued"]
            assert len(requests) == 1
        finally:
            release_owner.set()
            await owner
            await client.aclose()

    asyncio.run(scenario())


def test_idle_only_succeeds_after_provider_capacity_is_released() -> None:
    first_started = asyncio.Event()
    release_first = asyncio.Event()
    request_count = 0

    async def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal request_count
        request_count += 1
        if request_count == 1:
            first_started.set()
            await release_first.wait()
        return _completed_response(f"请求{request_count}完成")

    async def scenario() -> None:
        client = _client(handler)
        target = _target(client)
        owner = asyncio.create_task(
            client.generate_action_decision(
                action_context=_action_context(),
                attempt_id="v2_model_release_owner",
                target=target,
            )
        )
        await asyncio.wait_for(first_started.wait(), timeout=0.5)
        release_first.set()
        await owner
        try:
            decision = await asyncio.wait_for(
                client.generate_action_decision(
                    action_context=_action_context(),
                    attempt_id="v2_model_after_release",
                    target=target,
                    admission_mode="idle_only",
                ),
                timeout=0.5,
            )
        finally:
            await client.aclose()

        assert decision.speech == "请求2完成"
        assert request_count == 2

    asyncio.run(scenario())


def test_idle_only_never_bypasses_an_existing_normal_waiter() -> None:
    first_started = asyncio.Event()
    second_started = asyncio.Event()
    release_first = asyncio.Event()
    release_second = asyncio.Event()
    request_count = 0

    async def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal request_count
        request_count += 1
        request_no = request_count
        if request_no == 1:
            first_started.set()
            await release_first.wait()
        elif request_no == 2:
            second_started.set()
            await release_second.wait()
        return _completed_response(f"请求{request_no}完成")

    async def scenario() -> None:
        client = _client(handler)
        target = _target(client)
        owner = asyncio.create_task(
            client.generate_action_decision(
                action_context=_action_context(),
                attempt_id="v2_model_fifo_owner",
                target=target,
            )
        )
        await asyncio.wait_for(first_started.wait(), timeout=0.5)

        waiter_queued = asyncio.Event()

        def observe_waiter(progress: V2ModelProgress) -> None:
            if progress.stage == "queued":
                waiter_queued.set()

        normal_waiter = asyncio.create_task(
            client.generate_action_decision_with_progress(
                action_context=_action_context(),
                attempt_id="v2_model_fifo_waiter",
                target=target,
                on_progress=observe_waiter,
            )
        )
        await asyncio.wait_for(waiter_queued.wait(), timeout=0.5)
        await asyncio.sleep(0)

        rejected_progress: list[V2ModelProgress] = []
        with pytest.raises(V2ModelError, match="model_prefetch_capacity_unavailable"):
            await client.generate_action_decision_with_progress(
                action_context=_action_context(),
                attempt_id="v2_model_fifo_prefetch_rejected",
                target=target,
                admission_mode="idle_only",
                on_progress=rejected_progress.append,
            )
        assert [item.stage for item in rejected_progress] == ["queued"]

        release_first.set()
        await asyncio.wait_for(second_started.wait(), timeout=0.5)
        assert request_count == 2
        release_second.set()
        first, second = await asyncio.gather(owner, normal_waiter)
        try:
            prefetch = await client.generate_action_decision(
                action_context=_action_context(),
                attempt_id="v2_model_fifo_prefetch_after_waiter",
                target=target,
                admission_mode="idle_only",
            )
        finally:
            await client.aclose()

        assert first.speech == "请求1完成"
        assert second.speech == "请求2完成"
        assert prefetch.speech == "请求3完成"
        assert request_count == 3

    asyncio.run(scenario())


def test_canceled_normal_waiter_does_not_leak_capacity_or_block_idle_only() -> None:
    owner_started = asyncio.Event()
    release_owner = asyncio.Event()
    request_count = 0

    async def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal request_count
        request_count += 1
        if request_count == 1:
            owner_started.set()
            await release_owner.wait()
        return _completed_response(f"请求{request_count}完成")

    async def scenario() -> None:
        client = _client(handler)
        target = _target(client)
        owner = asyncio.create_task(
            client.generate_action_decision(
                action_context=_action_context(),
                attempt_id="v2_model_cancel_owner",
                target=target,
            )
        )
        await asyncio.wait_for(owner_started.wait(), timeout=0.5)

        waiter_queued = asyncio.Event()

        def observe_waiter(progress: V2ModelProgress) -> None:
            if progress.stage == "queued":
                waiter_queued.set()

        canceled_waiter = asyncio.create_task(
            client.generate_action_decision_with_progress(
                action_context=_action_context(),
                attempt_id="v2_model_canceled_waiter",
                target=target,
                on_progress=observe_waiter,
            )
        )
        await asyncio.wait_for(waiter_queued.wait(), timeout=0.5)
        for _ in range(10):
            if client._gates["agent_plan"]._normal_waiters == 1:
                break
            await asyncio.sleep(0)
        assert client._gates["agent_plan"]._normal_waiters == 1

        canceled_waiter.cancel()
        with pytest.raises(asyncio.CancelledError):
            await canceled_waiter
        assert client._gates["agent_plan"]._normal_waiters == 0

        release_owner.set()
        await owner
        try:
            decision = await asyncio.wait_for(
                client.generate_action_decision(
                    action_context=_action_context(),
                    attempt_id="v2_model_idle_after_cancellation",
                    target=target,
                    admission_mode="idle_only",
                ),
                timeout=0.5,
            )
        finally:
            await client.aclose()

        assert decision.speech == "请求2完成"
        assert request_count == 2

    asyncio.run(scenario())
