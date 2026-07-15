from __future__ import annotations

import inspect
import json
import os
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from app.werewolf.execution_budget import ModelCallOptions, ModelDeadlineExceeded
from app.werewolf.streaming import extract_openai_chat_delta

Transport = Callable[[str, dict[str, str], dict[str, Any]], dict[str, Any]]
StreamTransport = Callable[[str, dict[str, str], dict[str, Any]], Any]
Sleep = Callable[[float], None]

STREAM_SOCKET_TIMEOUT_SECONDS = 30
STREAM_NO_CONTENT_TIMEOUT_SECONDS = 60
STREAM_TOTAL_TIMEOUT_SECONDS = 180


class StreamStalledError(RuntimeError):
    pass


class ProviderLike(Protocol):
    def complete_json(
        self,
        *,
        model: str,
        prompt: str,
        temperature: float,
        call_options: ModelCallOptions | None = None,
    ) -> str:
        pass

    def stream_json(
        self,
        *,
        model: str,
        prompt: str,
        temperature: float,
        call_options: ModelCallOptions | None = None,
    ) -> Any:
        pass


@dataclass(frozen=True)
class OpenAICompatibleProviderConfig:
    name: str
    env_prefix: str
    default_base_url: str
    default_model: str
    model_prefixes: tuple[str, ...]
    available_models: tuple[str, ...] = ()
    api_key_env_aliases: tuple[str, ...] = ()
    api_host_base_path: str = ""
    model_aliases: dict[str, str] = field(default_factory=dict)
    response_format: dict[str, str] | None = None
    extra_payload: dict[str, Any] = field(default_factory=dict)


ARK_AGENT_PLAN_MODELS = (
    "doubao-seed-2-0-lite-260215",
    "glm-5-2-260617",
    "minimax-m3",
)

ARK_AGENT_PLAN_CONFIG = OpenAICompatibleProviderConfig(
    name="火山方舟 Agent Plan",
    env_prefix="ARK_AGENT_PLAN",
    default_base_url="https://ark.cn-beijing.volces.com/api/plan/v3",
    default_model=ARK_AGENT_PLAN_MODELS[0],
    model_prefixes=(),
    available_models=ARK_AGENT_PLAN_MODELS,
    api_key_env_aliases=("ARK_API_KEY",),
    api_host_base_path="/api/plan/v3",
)

DEEPSEEK_CONFIG = OpenAICompatibleProviderConfig(
    name="DeepSeek",
    env_prefix="DEEPSEEK",
    default_base_url="https://api.deepseek.com",
    default_model="deepseek-v4-flash",
    model_prefixes=("deepseek-",),
    response_format={"type": "json_object"},
)

QWEN_CONFIG = OpenAICompatibleProviderConfig(
    name="Qwen",
    env_prefix="DASHSCOPE",
    default_base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
    default_model="qwen3.6-plus",
    model_prefixes=("qwen",),
    api_host_base_path="/compatible-mode/v1",
    model_aliases={
        "qwen3.6-plus": "qwen3.6-plus",
        "qwen3.6-plus-preview": "qwen3.6-plus-preview",
    },
)

OPENAI_COMPATIBLE_PROVIDER_CONFIGS = (
    ARK_AGENT_PLAN_CONFIG,
    DEEPSEEK_CONFIG,
    QWEN_CONFIG,
)


class OpenAICompatibleProvider:
    def __init__(
        self,
        *,
        config: OpenAICompatibleProviderConfig,
        api_key: str | None = None,
        base_url: str | None = None,
        transport: Transport | None = None,
        stream_transport: StreamTransport | None = None,
        max_retries: int = 3,
        sleep: Sleep = time.sleep,
    ) -> None:
        dotenv = _load_dotenv(Path(".env"), prefixes=_dotenv_prefixes(config))
        api_key_name = f"{config.env_prefix}_API_KEY"
        base_url_name = f"{config.env_prefix}_BASE_URL"
        api_host_name = f"{config.env_prefix}_API_HOST"

        self.config = config
        api_key_env_names = (api_key_name, *config.api_key_env_aliases)
        self.api_key = api_key or next(
            (value for name in api_key_env_names if (value := os.getenv(name) or dotenv.get(name))),
            None,
        )
        if not self.api_key:
            accepted_names = " or ".join(api_key_env_names)
            raise RuntimeError(f"{accepted_names} is required to call {config.name}.")

        api_host = os.getenv(api_host_name) or dotenv.get(api_host_name)
        self.base_url = (
            base_url
            or os.getenv(base_url_name)
            or dotenv.get(base_url_name)
            or _base_url_from_api_host(api_host, config.api_host_base_path)
            or config.default_base_url
        ).rstrip("/")
        self.transport = transport or _urlopen_transport
        self.stream_transport = stream_transport or _urlopen_stream_transport
        self.max_retries = max_retries
        self.sleep = sleep

    def complete_json(
        self,
        *,
        model: str,
        prompt: str,
        temperature: float,
        call_options: ModelCallOptions | None = None,
    ) -> str:
        payload = self._chat_payload(
            model=model,
            prompt=prompt,
            temperature=temperature,
            call_options=call_options,
        )
        headers = self._headers()
        response = self._send_with_retries(
            f"{self.base_url}/chat/completions",
            headers,
            payload,
            call_options=call_options,
        )
        return response["choices"][0]["message"]["content"]

    def stream_json(
        self,
        *,
        model: str,
        prompt: str,
        temperature: float,
        call_options: ModelCallOptions | None = None,
    ) -> Any:
        payload = self._chat_payload(
            model=model,
            prompt=prompt,
            temperature=temperature,
            call_options=call_options,
        )
        payload["stream"] = True
        headers = self._headers()
        return self._stream_with_retries(
            f"{self.base_url}/chat/completions",
            headers,
            payload,
            call_options=call_options,
        )

    def _chat_payload(
        self,
        *,
        model: str,
        prompt: str,
        temperature: float,
        call_options: ModelCallOptions | None,
    ) -> dict[str, Any]:
        payload = {
            "model": self.config.model_aliases.get(model.lower(), model),
            "messages": [
                {
                    "role": "system",
                    "content": "你是狼人杀游戏玩家。所有内容使用中文，并严格输出 json。",
                },
                {"role": "user", "content": prompt},
            ],
            "temperature": temperature,
            "stream": False,
        }
        if self.config.response_format is not None:
            payload["response_format"] = self.config.response_format
        if call_options is not None and call_options.max_output_tokens is not None:
            payload["max_tokens"] = call_options.max_output_tokens
        payload.update(self.config.extra_payload)
        return payload

    def _headers(self) -> dict[str, str]:
        return {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
            "User-Agent": "werewolf-arena-live/0.1",
        }

    def _send_with_retries(
        self,
        url: str,
        headers: dict[str, str],
        payload: dict[str, Any],
        *,
        call_options: ModelCallOptions | None,
    ) -> dict[str, Any]:
        last_error: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            try:
                attempt_options = (
                    call_options.for_attempt(time.monotonic())
                    if call_options
                    else None
                )
                return _call_transport(
                    self.transport,
                    url,
                    headers,
                    payload,
                    call_options=attempt_options,
                )
            except ModelDeadlineExceeded:
                raise
            except urllib.error.HTTPError as exc:
                raise RuntimeError(_http_error_message(self.config, url, exc)) from exc
            except (urllib.error.URLError, TimeoutError, ConnectionResetError, OSError) as exc:
                last_error = exc
                if attempt == self.max_retries:
                    break
                self._sleep_before_retry(attempt, call_options)

        if call_options is not None and _is_timeout_error(last_error):
            raise ModelDeadlineExceeded(
                "model action deadline exceeded during provider request"
            ) from last_error
        raise RuntimeError(
            f"{self.config.name} network request failed after "
            f"{self.max_retries} attempts: {last_error}"
        ) from last_error

    def _stream_with_retries(
        self,
        url: str,
        headers: dict[str, str],
        payload: dict[str, Any],
        *,
        call_options: ModelCallOptions | None,
    ) -> Any:
        last_error: Exception | None = None
        yielded_any = False
        for attempt in range(1, self.max_retries + 1):
            try:
                attempt_options = (
                    call_options.for_attempt(time.monotonic())
                    if call_options
                    else None
                )
                stream = _call_transport(
                    self.stream_transport,
                    url,
                    headers,
                    payload,
                    call_options=attempt_options,
                )
                for chunk in stream:
                    yielded_any = True
                    yield chunk
                return
            except ModelDeadlineExceeded:
                raise
            except urllib.error.HTTPError as exc:
                raise RuntimeError(_http_error_message(self.config, url, exc)) from exc
            except (urllib.error.URLError, TimeoutError, ConnectionResetError, OSError) as exc:
                last_error = exc
                if yielded_any:
                    raise RuntimeError(
                        f"{self.config.name} streaming request failed after partial output: {exc}"
                    ) from exc
                if attempt == self.max_retries:
                    break
                self._sleep_before_retry(attempt, call_options)

        if call_options is not None and _is_timeout_error(last_error):
            raise ModelDeadlineExceeded(
                "model action deadline exceeded during provider stream"
            ) from last_error
        raise RuntimeError(
            f"{self.config.name} streaming request failed after "
            f"{self.max_retries} attempts: {last_error}"
        ) from last_error

    def _sleep_before_retry(
        self,
        attempt: int,
        call_options: ModelCallOptions | None,
    ) -> None:
        delay = min(2.0, 0.25 * attempt)
        if call_options is not None:
            remaining = call_options.remaining_seconds(time.monotonic())
            if remaining <= delay:
                raise ModelDeadlineExceeded(
                    "model action deadline exhausted before provider retry"
                )
        self.sleep(delay)


def _is_timeout_error(error: Exception | None) -> bool:
    if isinstance(error, TimeoutError):
        return True
    if isinstance(error, urllib.error.URLError):
        return isinstance(error.reason, TimeoutError)
    return False


class DeepSeekProvider(OpenAICompatibleProvider):
    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        transport: Transport | None = None,
        stream_transport: StreamTransport | None = None,
        max_retries: int = 3,
        sleep: Sleep = time.sleep,
    ) -> None:
        super().__init__(
            config=DEEPSEEK_CONFIG,
            api_key=api_key,
            base_url=base_url,
            transport=transport,
            stream_transport=stream_transport,
            max_retries=max_retries,
            sleep=sleep,
        )


class ArkAgentPlanProvider(OpenAICompatibleProvider):
    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        transport: Transport | None = None,
        stream_transport: StreamTransport | None = None,
        max_retries: int = 3,
        sleep: Sleep = time.sleep,
    ) -> None:
        super().__init__(
            config=ARK_AGENT_PLAN_CONFIG,
            api_key=api_key,
            base_url=base_url,
            transport=transport,
            stream_transport=stream_transport,
            max_retries=max_retries,
            sleep=sleep,
        )


class QwenProvider(OpenAICompatibleProvider):
    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        transport: Transport | None = None,
        stream_transport: StreamTransport | None = None,
        max_retries: int = 3,
        sleep: Sleep = time.sleep,
    ) -> None:
        super().__init__(
            config=QWEN_CONFIG,
            api_key=api_key,
            base_url=base_url,
            transport=transport,
            stream_transport=stream_transport,
            max_retries=max_retries,
            sleep=sleep,
        )


@dataclass(frozen=True)
class ModelProviderRegistration:
    name: str
    factory: Callable[[], ProviderLike]
    model_prefixes: tuple[str, ...] = ()
    model_names: tuple[str, ...] = ()

    def matches(self, model: str) -> bool:
        normalized_model = model.lower()
        return normalized_model in {name.lower() for name in self.model_names} or any(
            normalized_model.startswith(prefix.lower()) for prefix in self.model_prefixes
        )


class RoutingModelProvider:
    def __init__(self, registrations: list[ModelProviderRegistration]) -> None:
        self.registrations = registrations
        self._providers: dict[str, ProviderLike] = {}

    def complete_json(
        self,
        *,
        model: str,
        prompt: str,
        temperature: float,
        call_options: ModelCallOptions | None = None,
    ) -> str:
        provider = self._provider_for_model(model)
        return _call_provider(
            provider.complete_json,
            model=model,
            prompt=prompt,
            temperature=temperature,
            call_options=call_options,
        )

    def stream_json(
        self,
        *,
        model: str,
        prompt: str,
        temperature: float,
        call_options: ModelCallOptions | None = None,
    ) -> Any:
        provider = self._provider_for_model(model)
        stream_json = getattr(provider, "stream_json", None)
        if not callable(stream_json):
            raise RuntimeError(f"Provider for model {model} does not support stream_json.")
        return _call_provider(
            stream_json,
            model=model,
            prompt=prompt,
            temperature=temperature,
            call_options=call_options,
        )

    def _provider_for_model(self, model: str) -> ProviderLike:
        registration = self._registration_for_model(model)
        if registration is None:
            known_patterns = ", ".join(
                pattern
                for item in self.registrations
                for pattern in (*item.model_names, *item.model_prefixes)
            )
            raise RuntimeError(
                f"No provider registered for model {model}. "
                f"Known model names or prefixes: {known_patterns}."
            )

        provider = self._providers.get(registration.name)
        if provider is None:
            provider = registration.factory()
            self._providers[registration.name] = provider
        return provider

    def _registration_for_model(self, model: str) -> ModelProviderRegistration | None:
        for registration in self.registrations:
            if registration.matches(model):
                return registration
        return None


def create_model_provider(
    *,
    transport: Transport | None = None,
    stream_transport: StreamTransport | None = None,
    max_retries: int = 3,
    sleep: Sleep = time.sleep,
) -> RoutingModelProvider:
    return RoutingModelProvider(
        [
            _registration_for_config(
                config,
                _openai_provider_factory(
                    config,
                    transport=transport,
                    stream_transport=stream_transport,
                    max_retries=max_retries,
                    sleep=sleep,
                ),
            )
            for config in OPENAI_COMPATIBLE_PROVIDER_CONFIGS
        ]
    )


def _openai_provider_factory(
    config: OpenAICompatibleProviderConfig,
    *,
    transport: Transport | None,
    stream_transport: StreamTransport | None,
    max_retries: int,
    sleep: Sleep,
) -> Callable[[], ProviderLike]:
    return lambda: OpenAICompatibleProvider(
        config=config,
        transport=transport,
        stream_transport=stream_transport,
        max_retries=max_retries,
        sleep=sleep,
    )


def _registration_for_config(
    config: OpenAICompatibleProviderConfig,
    factory: Callable[[], ProviderLike],
) -> ModelProviderRegistration:
    return ModelProviderRegistration(
        name=config.name,
        factory=factory,
        model_prefixes=config.model_prefixes,
        model_names=_configured_model_names(config),
    )


def _configured_model_names(config: OpenAICompatibleProviderConfig) -> tuple[str, ...]:
    dotenv = _load_dotenv(Path(".env"), prefixes=(config.env_prefix,))
    models_name = f"{config.env_prefix}_MODELS"
    model_name = f"{config.env_prefix}_MODEL"
    configured_models = os.getenv(models_name) or dotenv.get(models_name)
    if configured_models:
        return _split_model_names(configured_models)

    configured_model = os.getenv(model_name) or dotenv.get(model_name)
    if configured_model:
        return (configured_model,)
    return config.available_models


def _split_model_names(value: str) -> tuple[str, ...]:
    return tuple(dict.fromkeys(name.strip() for name in value.split(",") if name.strip()))


def configured_model_options() -> list[dict[str, str]]:
    default_model = default_model_name()
    configured_options: list[dict[str, str]] = []
    for config in OPENAI_COMPATIBLE_PROVIDER_CONFIGS:
        if not _has_api_key(config):
            continue

        configured_names = _configured_model_names(config) or (config.default_model,)
        configured_options.extend(
            {
                "id": model_name,
                "label": f"{config.name} · {model_name}",
            }
            for model_name in configured_names
        )

    options_by_id = {option["id"]: option for option in configured_options}
    default_option = options_by_id.get(
        default_model,
        {"id": default_model, "label": f"默认模型 · {default_model}"},
    )
    options = [default_option]
    seen = {default_model}
    for option in configured_options:
        if option["id"] in seen:
            continue
        options.append(option)
        seen.add(option["id"])
    return options


def default_model_name() -> str:
    dotenv = _load_dotenv(Path(".env"), prefixes=("WEREWOLF",))
    explicit_default = os.getenv("WEREWOLF_DEFAULT_MODEL") or dotenv.get("WEREWOLF_DEFAULT_MODEL")
    if explicit_default:
        return _canonical_model_name(explicit_default)

    for config in OPENAI_COMPATIBLE_PROVIDER_CONFIGS:
        if _has_api_key(config):
            configured_names = _configured_model_names(config)
            if config.default_model in configured_names:
                return config.default_model
            return configured_names[0] if configured_names else config.default_model

    return DEEPSEEK_CONFIG.default_model


def _canonical_model_name(model: str) -> str:
    normalized_model = model.lower()
    for config in OPENAI_COMPATIBLE_PROVIDER_CONFIGS:
        if canonical_name := config.model_aliases.get(normalized_model):
            return canonical_name
    return model


def _has_api_key(config: OpenAICompatibleProviderConfig) -> bool:
    dotenv = _load_dotenv(Path(".env"), prefixes=_dotenv_prefixes(config))
    api_key_env_names = (f"{config.env_prefix}_API_KEY", *config.api_key_env_aliases)
    return any(os.getenv(name) or dotenv.get(name) for name in api_key_env_names)


def _dotenv_prefixes(config: OpenAICompatibleProviderConfig) -> tuple[str, ...]:
    alias_prefixes = tuple(name.removesuffix("_API_KEY") for name in config.api_key_env_aliases)
    return tuple(dict.fromkeys((config.env_prefix, *alias_prefixes)))


def _base_url_from_api_host(api_host: str | None, base_path: str) -> str | None:
    if not api_host:
        return None

    normalized_host = api_host.rstrip("/")
    normalized_base_path = base_path.strip("/")
    if not normalized_base_path:
        return normalized_host

    if normalized_host.endswith(f"/{normalized_base_path}"):
        return normalized_host
    return f"{normalized_host}/{normalized_base_path}"


def _http_error_message(
    config: OpenAICompatibleProviderConfig,
    url: str,
    exc: urllib.error.HTTPError,
) -> str:
    body = _read_http_error_body(exc)
    message = f"{config.name} request failed with HTTP {exc.code}: {body}"
    if config.env_prefix == "ARK_AGENT_PLAN" and exc.code == 401:
        message += (
            " Check ARK_AGENT_PLAN_API_KEY/ARK_API_KEY and make sure "
            "ARK_AGENT_PLAN_BASE_URL/ARK_AGENT_PLAN_API_HOST points to the Agent Plan "
            "data plane, for example https://ark.cn-beijing.volces.com/api/plan/v3."
        )
    if config.env_prefix == "DASHSCOPE" and exc.code == 401:
        message += (
            " Check DASHSCOPE_API_KEY and make sure DASHSCOPE_BASE_URL/DASHSCOPE_API_HOST "
            "matches the key region: Beijing=https://dashscope.aliyuncs.com/compatible-mode/v1, "
            "Singapore=https://dashscope-intl.aliyuncs.com/compatible-mode/v1, "
            "Virginia=https://dashscope-us.aliyuncs.com/compatible-mode/v1."
        )
    return message


def _read_http_error_body(exc: urllib.error.HTTPError) -> str:
    try:
        return exc.read().decode("utf-8", errors="replace")
    except Exception:
        return str(exc)


def _call_provider(
    method: Callable[..., Any],
    *,
    model: str,
    prompt: str,
    temperature: float,
    call_options: ModelCallOptions | None,
) -> Any:
    if "call_options" in inspect.signature(method).parameters:
        return method(
            model=model,
            prompt=prompt,
            temperature=temperature,
            call_options=call_options,
        )
    return method(model=model, prompt=prompt, temperature=temperature)


def _call_transport(
    transport: Callable[..., Any],
    url: str,
    headers: dict[str, str],
    payload: dict[str, Any],
    *,
    call_options: ModelCallOptions | None,
) -> Any:
    if "call_options" in inspect.signature(transport).parameters:
        return transport(
            url,
            headers,
            payload,
            call_options=call_options,
        )
    return transport(url, headers, payload)


def _urlopen_transport(
    url: str,
    headers: dict[str, str],
    payload: dict[str, Any],
    *,
    call_options: ModelCallOptions | None = None,
) -> dict[str, Any]:
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(url, data=data, headers=headers, method="POST")
    timeout = call_options.request_timeout_seconds if call_options else 120
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _urlopen_stream_transport(
    url: str,
    headers: dict[str, str],
    payload: dict[str, Any],
    *,
    call_options: ModelCallOptions | None = None,
) -> Any:
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(url, data=data, headers=headers, method="POST")
    started_at = time.monotonic()
    last_content_at = started_at
    received_content = False
    socket_timeout = STREAM_SOCKET_TIMEOUT_SECONDS
    if call_options is not None:
        attempt_options = call_options.for_attempt(started_at)
        socket_timeout = min(
            socket_timeout,
            attempt_options.request_timeout_seconds,
            attempt_options.first_token_timeout_seconds
            or attempt_options.request_timeout_seconds,
        )
    with urllib.request.urlopen(request, timeout=socket_timeout) as response:
        for line in response:
            now = time.monotonic()
            total_timeout = (
                call_options.remaining_seconds(started_at)
                if call_options
                else STREAM_TOTAL_TIMEOUT_SECONDS
            )
            if now - started_at > total_timeout:
                raise ModelDeadlineExceeded("model streaming deadline exceeded")
            if (
                call_options is not None
                and not received_content
                and call_options.first_token_timeout_seconds is not None
                and now - started_at > call_options.first_token_timeout_seconds
            ):
                raise ModelDeadlineExceeded("model first token deadline exceeded")
            if call_options is None and now - started_at > STREAM_TOTAL_TIMEOUT_SECONDS:
                raise StreamStalledError(
                    f"streaming response exceeded {STREAM_TOTAL_TIMEOUT_SECONDS} seconds"
                )
            delta = extract_openai_chat_delta(line)
            if delta is not None:
                received_content = True
                last_content_at = now
                yield delta
                continue
            if now - last_content_at > STREAM_NO_CONTENT_TIMEOUT_SECONDS:
                raise StreamStalledError(
                    "streaming response produced no content for "
                    f"{STREAM_NO_CONTENT_TIMEOUT_SECONDS} seconds"
                )


def _load_dotenv(path: Path, *, prefixes: tuple[str, ...] | None = None) -> dict[str, str]:
    if not path.exists():
        return {}

    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if prefixes is not None and not any(key.startswith(f"{prefix}_") for prefix in prefixes):
            continue
        values[key] = value.strip().strip("\"'")
    return values
