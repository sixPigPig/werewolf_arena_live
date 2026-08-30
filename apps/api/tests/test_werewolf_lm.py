import json
import os
import time
import urllib.error
import urllib.request

import pytest

from app.model_catalog.defaults import (
    default_parameter_values,
    max_output_tokens_limit,
    reasoning_policy_for_model,
)
from app.model_catalog.runtime import RuntimeModelConfiguration
from app.shared.execution_budget import ModelCallOptions, ModelDeadlineExceeded
from app.shared.providers import (
    ARK_AGENT_PLAN_MODELS,
    ArkAgentPlanProvider,
    DeepSeekProvider,
    ModelRuntimeConfigurationError,
    create_model_provider,
    default_model_name,
    open_url_direct,
)
from app.shared.openai_sse import extract_openai_chat_delta

@pytest.fixture(autouse=True)
def _strict_runtime_model_configuration(monkeypatch) -> None:
    def enabled_catalog_models(provider: str) -> tuple[str, ...]:
        return {
            "agent_plan": ARK_AGENT_PLAN_MODELS,
            "deepseek": ("deepseek-chat", "deepseek-v4-flash"),
        }.get(provider, ())

    def configured_model(provider: str, model_id: str) -> RuntimeModelConfiguration:
        policy = reasoning_policy_for_model(
            provider,
            model_id,
            supports_thinking=False,
        )
        supports_thinking = "enabled" in policy.thinking_options
        return RuntimeModelConfiguration(
            provider=provider,
            model_id=model_id,
            supports_thinking=supports_thinking,
            parameters=default_parameter_values(
                provider,
                model_id,
                supports_thinking=supports_thinking,
                limit=max_output_tokens_limit(provider, model_id),
            ),
        )

    monkeypatch.setattr(
        "app.shared.providers.runtime_configuration_for_model",
        configured_model,
    )
    monkeypatch.setattr(
        "app.shared.providers.catalog_model_names",
        enabled_catalog_models,
    )
    monkeypatch.setattr(
        "app.shared.providers.runtime_default_model",
        lambda: None,
    )

def test_extract_openai_chat_delta_reads_compatible_sse_chunks() -> None:
    chunk = ('data: {"choices":[{"delta":{"content":"我不是狼"}}]}\n\n').encode("utf-8")

    assert extract_openai_chat_delta(chunk) == "我不是狼"
    assert extract_openai_chat_delta(b"data: [DONE]\n\n") is None
    assert extract_openai_chat_delta(b": heartbeat\n\n") is None

def test_extract_openai_chat_delta_skips_role_only_events_in_same_chunk() -> None:
    chunk = (
        'data: {"choices":[{"delta":{"role":"assistant"}}]}\n\n'
        'data: {"choices":[{"delta":{"content":"你好"}}]}\n\n'
    ).encode("utf-8")

    assert extract_openai_chat_delta(chunk) == "你好"

def test_extract_openai_chat_delta_skips_leading_comment_in_same_chunk() -> None:
    chunk = (': heartbeat\n\ndata: {"choices":[{"delta":{"content":"继续"}}]}\n\n').encode("utf-8")

    assert extract_openai_chat_delta(chunk) == "继续"

def test_extract_openai_chat_delta_joins_multiple_content_events_in_same_chunk() -> None:
    chunk = (
        'data: {"choices":[{"delta":{"content":"你"}}]}\n\n'
        'data: {"choices":[{"delta":{"content":"好"}}]}\n\n'
    ).encode("utf-8")

    assert extract_openai_chat_delta(chunk) == "你好"

def test_extract_openai_chat_delta_preserves_content_before_done_in_same_chunk() -> None:
    chunk = ('data: {"choices":[{"delta":{"content":"结束前"}}]}\n\ndata: [DONE]\n\n').encode(
        "utf-8"
    )

    assert extract_openai_chat_delta(chunk) == "结束前"

def test_deepseek_provider_uses_env_and_json_response_format(monkeypatch) -> None:
    requests = []

    def fake_transport(url: str, headers: dict[str, str], payload: dict) -> dict:
        requests.append({"url": url, "headers": headers, "payload": payload})
        return {
            "choices": [
                {"message": {"content": json.dumps({"reasoning": "按格式返回", "vote": "老周"})}}
            ]
        }

    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    provider = DeepSeekProvider(transport=fake_transport)

    raw = provider.complete_json(
        model="deepseek-chat",
        prompt='请输出 json：{"vote":"老周"}',
        temperature=0.3,
    )

    assert json.loads(raw) == {"reasoning": "按格式返回", "vote": "老周"}
    assert requests[0]["url"] == "https://api.deepseek.com/chat/completions"
    assert requests[0]["headers"]["Authorization"] == "Bearer test-key"
    assert requests[0]["payload"]["model"] == "deepseek-chat"
    assert requests[0]["payload"]["response_format"] == {"type": "json_object"}

def test_provider_applies_remaining_budget_and_max_output_tokens(monkeypatch) -> None:
    requests = []

    def fake_transport(
        url: str,
        headers: dict[str, str],
        payload: dict,
        *,
        call_options: ModelCallOptions | None,
    ) -> dict:
        requests.append(
            {
                "url": url,
                "headers": headers,
                "payload": payload,
                "call_options": call_options,
            }
        )
        return {"choices": [{"message": {"content": '{"reasoning":"ok","vote":"1号玩家"}'}}]}

    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    provider = DeepSeekProvider(transport=fake_transport)
    options = ModelCallOptions(
        deadline_at_monotonic=time.monotonic() + 2,
        request_timeout_seconds=1.5,
        max_output_tokens=96,
    )

    provider.complete_json(
        model="deepseek-chat",
        prompt="{}",
        temperature=0.3,
        call_options=options,
    )

    applied = requests[0]["call_options"]
    assert isinstance(applied, ModelCallOptions)
    assert 0 < applied.request_timeout_seconds <= 1.5
    assert applied.deadline_at_monotonic == options.deadline_at_monotonic
    assert requests[0]["payload"]["max_tokens"] == 96

def test_provider_transport_timeout_becomes_action_deadline(monkeypatch) -> None:
    def timeout_transport(url: str, headers: dict[str, str], payload: dict) -> dict:
        del url, headers, payload
        raise TimeoutError("socket timeout with SENTINEL_PRIVATE_BODY")

    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    provider = DeepSeekProvider(transport=timeout_transport, max_retries=1)

    with pytest.raises(ModelDeadlineExceeded):
        provider.complete_json(
            model="deepseek-chat",
            prompt="{}",
            temperature=0.3,
            call_options=ModelCallOptions(
                deadline_at_monotonic=time.monotonic() + 1,
                request_timeout_seconds=1,
            ),
        )

def test_openai_compatible_provider_streams_chat_deltas(monkeypatch) -> None:
    requests = []

    def fake_stream_transport(url: str, headers: dict[str, str], payload: dict) -> list[str]:
        requests.append({"url": url, "headers": headers, "payload": payload})
        return ["我", "不是", "狼"]

    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    provider = DeepSeekProvider(stream_transport=fake_stream_transport)

    chunks = list(
        provider.stream_json(
            model="deepseek-chat",
            prompt='请输出 json：{"say":"我不是狼"}',
            temperature=0.3,
        )
    )

    assert chunks == ["我", "不是", "狼"]
    assert requests[0]["url"] == "https://api.deepseek.com/chat/completions"
    assert requests[0]["headers"]["Authorization"] == "Bearer test-key"
    assert requests[0]["payload"]["stream"] is True
    assert requests[0]["payload"]["model"] == "deepseek-chat"
    assert requests[0]["payload"]["response_format"] == {"type": "json_object"}

def test_openai_compatible_provider_stream_wraps_http_error_with_guidance(monkeypatch) -> None:
    def failing_stream_transport(url: str, headers: dict[str, str], payload: dict) -> list[str]:
        del headers, payload
        raise urllib.error.HTTPError(
            url=url,
            code=401,
            msg="Unauthorized",
            hdrs={},
            fp=None,
        )

    monkeypatch.setenv("ARK_AGENT_PLAN_API_KEY", "agent-plan-key")
    provider = ArkAgentPlanProvider(stream_transport=failing_stream_transport)

    with pytest.raises(RuntimeError, match="ARK_AGENT_PLAN_BASE_URL"):
        list(provider.stream_json(model="minimax-m3", prompt="{}", temperature=0.3))

def test_openai_compatible_provider_stream_retries_pre_yield_network_error(monkeypatch) -> None:
    attempts = []
    sleep_calls = []

    def flaky_stream_transport(url: str, headers: dict[str, str], payload: dict) -> list[str]:
        attempts.append({"url": url, "headers": headers, "payload": payload})
        if len(attempts) == 1:
            raise urllib.error.URLError(ConnectionResetError(54, "Connection reset by peer"))
        return ["重试", "成功"]

    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    provider = DeepSeekProvider(
        stream_transport=flaky_stream_transport,
        sleep=sleep_calls.append,
    )

    assert list(provider.stream_json(model="deepseek-chat", prompt="{}", temperature=0.3)) == [
        "重试",
        "成功",
    ]
    assert len(attempts) == 2
    assert sleep_calls == [0.25]

def test_openai_compatible_provider_stream_does_not_retry_after_yield(monkeypatch) -> None:
    attempts = []

    def flaky_stream_transport(url: str, headers: dict[str, str], payload: dict):
        attempts.append({"url": url, "headers": headers, "payload": payload})
        yield "已经输出"
        raise urllib.error.URLError(ConnectionResetError(54, "Connection reset by peer"))

    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    provider = DeepSeekProvider(
        stream_transport=flaky_stream_transport,
        sleep=lambda _seconds: None,
    )
    chunks = provider.stream_json(model="deepseek-chat", prompt="{}", temperature=0.3)

    assert next(chunks) == "已经输出"
    with pytest.raises(
        RuntimeError, match="DeepSeek streaming request failed after partial output"
    ):
        next(chunks)
    assert len(attempts) == 1

def test_urlopen_stream_transport_yields_sse_deltas(monkeypatch) -> None:
    requests = []

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback) -> None:
            del exc_type, exc, traceback

        def __iter__(self):
            return iter(
                [
                    'data: {"choices":[{"delta":{"content":"我"}}]}\n\n'.encode("utf-8"),
                    'data: {"choices":[{"delta":{"content":"不是狼"}}]}\n\n'.encode("utf-8"),
                    b"data: [DONE]\n\n",
                ]
            )

    def fake_urlopen(request, timeout: int):
        requests.append({"request": request, "timeout": timeout})
        return FakeResponse()

    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    monkeypatch.setattr("app.shared.providers.open_url_direct", fake_urlopen)
    provider = DeepSeekProvider()

    chunks = list(provider.stream_json(model="deepseek-chat", prompt="{}", temperature=0.3))

    assert chunks == ["我", "不是狼"]
    assert requests[0]["timeout"] == 30

def test_urlopen_stream_transport_times_out_when_stream_has_no_content(
    monkeypatch,
) -> None:
    monotonic_values = iter([0.0, 30.0, 61.0])
    requests = []

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback) -> None:
            del exc_type, exc, traceback

        def __iter__(self):
            return iter([b": heartbeat\n\n", b": heartbeat\n\n"])

    def fake_urlopen(request, timeout: int):
        requests.append(request)
        assert timeout == 30
        return FakeResponse()

    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    monkeypatch.setattr("app.shared.providers.open_url_direct", fake_urlopen)
    monkeypatch.setattr(
        "app.shared.providers.time.monotonic",
        lambda: next(monotonic_values),
    )
    provider = DeepSeekProvider(max_retries=3)

    with pytest.raises(RuntimeError, match="no content"):
        list(provider.stream_json(model="deepseek-chat", prompt="{}", temperature=0.3))
    assert len(requests) == 1

def test_open_url_direct_uses_an_empty_proxy_handler(monkeypatch) -> None:
    opened: list[dict[str, object]] = []
    response = object()

    class FakeOpener:
        def open(
            self,
            request: urllib.request.Request,
            *,
            timeout: float,
        ) -> object:
            opened.append({"request": request, "timeout": timeout})
            return response

    handlers: list[object] = []

    def fake_build_opener(*values: object) -> FakeOpener:
        handlers.extend(values)
        return FakeOpener()

    monkeypatch.setattr(urllib.request, "build_opener", fake_build_opener)
    request = urllib.request.Request("https://model.example.test/responses")

    result = open_url_direct(request, timeout=8)

    assert result is response
    assert opened == [{"request": request, "timeout": 8}]
    assert len(handlers) == 1
    assert isinstance(handlers[0], urllib.request.ProxyHandler)
    assert handlers[0].proxies == {}

def test_deepseek_provider_requires_api_key(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)

    with pytest.raises(RuntimeError, match="DEEPSEEK_API_KEY"):
        DeepSeekProvider()

def test_deepseek_provider_loads_key_from_dotenv(tmp_path, monkeypatch) -> None:
    requests = []

    def fake_transport(url: str, headers: dict[str, str], payload: dict) -> dict:
        requests.append({"url": url, "headers": headers, "payload": payload})
        return {
            "choices": [
                {"message": {"content": json.dumps({"reasoning": "按格式返回", "vote": "老周"})}}
            ]
        }

    (tmp_path / ".env").write_text(
        "APP_NAME=Python React Web API\n"
        "DEEPSEEK_API_KEY=dotenv-key\n"
        "DEEPSEEK_BASE_URL=https://example.deepseek.test\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("DEEPSEEK_BASE_URL", raising=False)

    provider = DeepSeekProvider(transport=fake_transport)
    provider.complete_json(model="deepseek-chat", prompt="{}", temperature=0.3)

    assert requests[0]["url"] == "https://example.deepseek.test/chat/completions"
    assert requests[0]["headers"]["Authorization"] == "Bearer dotenv-key"

def test_deepseek_provider_retries_connection_reset(monkeypatch) -> None:
    attempts = []

    def flaky_transport(url: str, headers: dict[str, str], payload: dict) -> dict:
        attempts.append({"url": url, "headers": headers, "payload": payload})
        if len(attempts) == 1:
            raise urllib.error.URLError(ConnectionResetError(54, "Connection reset by peer"))
        return {
            "choices": [
                {"message": {"content": json.dumps({"reasoning": "重试成功", "vote": "老周"})}}
            ]
        }

    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    provider = DeepSeekProvider(transport=flaky_transport, sleep=lambda _seconds: None)

    raw = provider.complete_json(
        model="deepseek-chat",
        prompt='请输出 json：{"vote":"老周"}',
        temperature=0.3,
    )

    assert json.loads(raw) == {"reasoning": "重试成功", "vote": "老周"}
    assert len(attempts) == 2

def test_deepseek_provider_raises_clear_error_after_network_retries(monkeypatch) -> None:
    def failing_transport(url: str, headers: dict[str, str], payload: dict) -> dict:
        del url, headers, payload
        raise urllib.error.URLError(ConnectionResetError(54, "Connection reset by peer"))

    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    provider = DeepSeekProvider(
        transport=failing_transport,
        max_retries=2,
        sleep=lambda _seconds: None,
    )

    with pytest.raises(RuntimeError, match="DeepSeek network request failed after 2 attempts"):
        provider.complete_json(
            model="deepseek-chat",
            prompt='请输出 json：{"vote":"老周"}',
            temperature=0.3,
        )

def test_ark_agent_plan_provider_uses_plan_endpoint_and_model_name(
    tmp_path,
    monkeypatch,
) -> None:
    requests = []

    def fake_transport(url: str, headers: dict[str, str], payload: dict) -> dict:
        requests.append({"url": url, "headers": headers, "payload": payload})
        return {
            "choices": [
                {"message": {"content": json.dumps({"reasoning": "按格式返回", "vote": "老周"})}}
            ]
        }

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ARK_AGENT_PLAN_API_KEY", "agent-plan-key")
    monkeypatch.delenv("ARK_API_KEY", raising=False)
    monkeypatch.delenv("ARK_AGENT_PLAN_API_HOST", raising=False)
    monkeypatch.delenv("ARK_AGENT_PLAN_BASE_URL", raising=False)
    provider = ArkAgentPlanProvider(transport=fake_transport)

    raw = provider.complete_json(
        model="minimax-m3",
        prompt='请输出 json：{"vote":"老周"}',
        temperature=0.3,
    )

    assert json.loads(raw) == {"reasoning": "按格式返回", "vote": "老周"}
    assert requests[0]["url"] == ("https://ark.cn-beijing.volces.com/api/plan/v3/chat/completions")
    assert requests[0]["headers"]["Authorization"] == "Bearer agent-plan-key"
    assert requests[0]["payload"]["model"] == "minimax-m3"
    assert "reasoning_split" not in requests[0]["payload"]
    assert "response_format" not in requests[0]["payload"]

def test_ark_agent_plan_provider_accepts_standard_ark_key_and_api_host(monkeypatch) -> None:
    requests = []

    def fake_transport(url: str, headers: dict[str, str], payload: dict) -> dict:
        requests.append({"url": url, "headers": headers, "payload": payload})
        return {
            "choices": [
                {"message": {"content": json.dumps({"reasoning": "按格式返回", "vote": "老周"})}}
            ]
        }

    monkeypatch.delenv("ARK_AGENT_PLAN_API_KEY", raising=False)
    monkeypatch.setenv("ARK_API_KEY", "agent-plan-key")
    monkeypatch.setenv("ARK_AGENT_PLAN_API_HOST", "https://ark.cn-beijing.volces.com")
    monkeypatch.delenv("ARK_AGENT_PLAN_BASE_URL", raising=False)
    provider = ArkAgentPlanProvider(transport=fake_transport)

    provider.complete_json(
        model="glm-5-2-260617",
        prompt='请输出 json：{"vote":"老周"}',
        temperature=0.3,
    )

    assert requests[0]["url"] == ("https://ark.cn-beijing.volces.com/api/plan/v3/chat/completions")

def test_ark_agent_plan_provider_explains_invalid_plan_key(monkeypatch) -> None:
    def failing_transport(url: str, headers: dict[str, str], payload: dict) -> dict:
        del url, headers, payload
        raise urllib.error.HTTPError(
            url="https://ark.cn-beijing.volces.com/api/plan/v3/chat/completions",
            code=401,
            msg="Unauthorized",
            hdrs={},
            fp=None,
        )

    monkeypatch.setenv("ARK_AGENT_PLAN_API_KEY", "agent-plan-key")
    provider = ArkAgentPlanProvider(transport=failing_transport)

    with pytest.raises(RuntimeError, match="ARK_AGENT_PLAN_BASE_URL"):
        provider.complete_json(model="minimax-m3", prompt="{}", temperature=0.3)

def test_model_provider_router_routes_all_agent_plan_models(tmp_path, monkeypatch) -> None:
    requests = []

    def fake_transport(url: str, headers: dict[str, str], payload: dict) -> dict:
        requests.append({"url": url, "headers": headers, "payload": payload})
        return {"choices": [{"message": {"content": "{}"}}]}

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ARK_AGENT_PLAN_API_KEY", "agent-plan-key")
    monkeypatch.delenv("ARK_API_KEY", raising=False)
    monkeypatch.delenv("ARK_AGENT_PLAN_MODEL", raising=False)
    monkeypatch.delenv("ARK_AGENT_PLAN_MODELS", raising=False)

    provider = create_model_provider(transport=fake_transport)
    for model in ARK_AGENT_PLAN_MODELS:
        provider.complete_json(model=model, prompt="{}", temperature=0.3)

    assert [request["payload"]["model"] for request in requests] == list(ARK_AGENT_PLAN_MODELS)
    assert {request["url"] for request in requests} == {
        "https://ark.cn-beijing.volces.com/api/plan/v3/chat/completions"
    }

def test_model_provider_router_rejects_removed_agent_plan_model(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ARK_AGENT_PLAN_API_KEY", "agent-plan-key")
    monkeypatch.delenv("ARK_API_KEY", raising=False)
    monkeypatch.delenv("ARK_AGENT_PLAN_MODELS", raising=False)

    provider = create_model_provider(transport=lambda _url, _headers, _payload: {})

    with pytest.raises(RuntimeError, match="No provider registered"):
        provider.complete_json(model="MiniMax-M2.7", prompt="{}", temperature=0.3)

def test_model_provider_router_does_not_use_prefix_when_catalog_is_empty(
    monkeypatch,
) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "deepseek-key")
    monkeypatch.setattr(
        "app.shared.providers.catalog_model_names",
        lambda _provider: (),
    )

    provider = create_model_provider(transport=lambda _url, _headers, _payload: {})

    with pytest.raises(RuntimeError, match="No provider registered for model deepseek-chat"):
        provider.complete_json(model="deepseek-chat", prompt="{}", temperature=0.3)

def test_model_provider_router_routes_deepseek_models(monkeypatch) -> None:
    requests = []

    def fake_transport(url: str, headers: dict[str, str], payload: dict) -> dict:
        requests.append({"url": url, "headers": headers, "payload": payload})
        return {
            "choices": [
                {"message": {"content": json.dumps({"reasoning": "按格式返回", "vote": "老周"})}}
            ]
        }

    monkeypatch.setenv("DEEPSEEK_API_KEY", "deepseek-key")

    provider = create_model_provider(transport=fake_transport)
    provider.complete_json(
        model="deepseek-chat",
        prompt='请输出 json：{"vote":"老周"}',
        temperature=0.3,
    )

    assert requests[0]["url"] == "https://api.deepseek.com/chat/completions"
    assert requests[0]["headers"]["Authorization"] == "Bearer deepseek-key"
    assert requests[0]["payload"]["response_format"] == {"type": "json_object"}

def test_model_provider_router_exposes_stream_json(monkeypatch) -> None:
    def fake_stream_transport(url: str, headers: dict[str, str], payload: dict) -> list[str]:
        del url, headers, payload
        return ['{"reasoning":"x","say":"你好"}']

    monkeypatch.setenv("DEEPSEEK_API_KEY", "deepseek-key")
    provider = create_model_provider(stream_transport=fake_stream_transport)

    assert list(provider.stream_json(model="deepseek-chat", prompt="{}", temperature=0.3)) == [
        '{"reasoning":"x","say":"你好"}'
    ]

def test_model_provider_router_reports_unknown_models(monkeypatch) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "deepseek-key")

    provider = create_model_provider(transport=lambda _url, _headers, _payload: {})

    with pytest.raises(RuntimeError, match="No provider registered for model unknown-model"):
        provider.complete_json(model="unknown-model", prompt="{}", temperature=0.3)

def test_model_provider_router_stream_reports_unknown_models(monkeypatch) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "deepseek-key")

    provider = create_model_provider(stream_transport=lambda _url, _headers, _payload: [])

    with pytest.raises(RuntimeError, match="No provider registered for model unknown-model"):
        provider.stream_json(model="unknown-model", prompt="{}", temperature=0.3)

def test_default_model_name_uses_agent_plan_lite_when_plan_key_is_configured(
    tmp_path,
    monkeypatch,
) -> None:
    (tmp_path / ".env").write_text(
        "#DEEPSEEK_API_KEY=\n"
        "DEEPSEEK_MODEL=deepseek-v4-flash\n"
        "ARK_AGENT_PLAN_API_KEY=agent-plan-key\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("WEREWOLF_DEFAULT_MODEL", raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("ARK_AGENT_PLAN_API_KEY", raising=False)
    monkeypatch.delenv("ARK_API_KEY", raising=False)

    assert default_model_name() == "doubao-seed-2-0-lite-260215"

def test_default_model_name_ignores_unregistered_dashscope_key(
    tmp_path,
    monkeypatch,
) -> None:
    (tmp_path / ".env").write_text(
        "#DEEPSEEK_API_KEY=\n"
        "#ARK_AGENT_PLAN_API_KEY=\n"
        "DASHSCOPE_API_KEY=dashscope-key\n"
        "DASHSCOPE_MODEL=qwen3.6-plus\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("WEREWOLF_DEFAULT_MODEL", raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("ARK_AGENT_PLAN_API_KEY", raising=False)
    monkeypatch.delenv("ARK_API_KEY", raising=False)

    with pytest.raises(ModelRuntimeConfigurationError, match="no_enabled_model_configuration"):
        default_model_name()

def test_default_model_name_rejects_missing_configured_keys(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("WEREWOLF_DEFAULT_MODEL", raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("ARK_AGENT_PLAN_API_KEY", raising=False)
    monkeypatch.delenv("ARK_API_KEY", raising=False)

    with pytest.raises(ModelRuntimeConfigurationError, match="no_enabled_model_configuration"):
        default_model_name()

def test_environment_example_uses_empty_deepseek_key_placeholder() -> None:
    example = os.path.join(os.path.dirname(__file__), "..", ".env.example")

    with open(example, encoding="utf-8") as file:
        contents = file.read()

    assert "WEREWOLF_DEFAULT_MODEL=\n" in contents
    assert "ARK_AGENT_PLAN_API_KEY=\n" in contents
    assert "ARK_AGENT_PLAN_BASE_URL=https://ark.cn-beijing.volces.com/api/plan/v3\n" in contents
    assert f"ARK_AGENT_PLAN_MODELS={','.join(ARK_AGENT_PLAN_MODELS)}\n" in contents
    assert "DEEPSEEK_API_KEY=\n" in contents
    assert "DEEPSEEK_MODEL=deepseek-v4-flash\n" in contents
    assert "MINIMAX_API_KEY" not in contents
    assert "DASHSCOPE_API_KEY" not in contents

