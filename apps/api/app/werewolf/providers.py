from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol

Transport = Callable[[str, dict[str, str], dict[str, Any]], dict[str, Any]]
Sleep = Callable[[float], None]


class ProviderLike(Protocol):
    def complete_json(self, *, model: str, prompt: str, temperature: float) -> str:
        pass


@dataclass(frozen=True)
class OpenAICompatibleProviderConfig:
    name: str
    env_prefix: str
    default_base_url: str
    default_model: str
    model_prefixes: tuple[str, ...]
    api_host_base_path: str = ""
    response_format: dict[str, str] | None = None
    extra_payload: dict[str, Any] = field(default_factory=dict)


DEEPSEEK_CONFIG = OpenAICompatibleProviderConfig(
    name="DeepSeek",
    env_prefix="DEEPSEEK",
    default_base_url="https://api.deepseek.com",
    default_model="deepseek-chat",
    model_prefixes=("deepseek-",),
    response_format={"type": "json_object"},
)

MINIMAX_CONFIG = OpenAICompatibleProviderConfig(
    name="MiniMax",
    env_prefix="MINIMAX",
    default_base_url="https://api.minimax.io/v1",
    default_model="MiniMax-M2.7",
    model_prefixes=("minimax-",),
    api_host_base_path="/v1",
    extra_payload={"reasoning_split": True},
)

OPENAI_COMPATIBLE_PROVIDER_CONFIGS = (DEEPSEEK_CONFIG, MINIMAX_CONFIG)


class OpenAICompatibleProvider:
    def __init__(
        self,
        *,
        config: OpenAICompatibleProviderConfig,
        api_key: str | None = None,
        base_url: str | None = None,
        transport: Transport | None = None,
        max_retries: int = 3,
        sleep: Sleep = time.sleep,
    ) -> None:
        dotenv = _load_dotenv(Path(".env"), prefixes=(config.env_prefix,))
        api_key_name = f"{config.env_prefix}_API_KEY"
        base_url_name = f"{config.env_prefix}_BASE_URL"
        api_host_name = f"{config.env_prefix}_API_HOST"

        self.config = config
        self.api_key = api_key or os.getenv(api_key_name) or dotenv.get(api_key_name)
        if not self.api_key:
            raise RuntimeError(f"{api_key_name} is required to call {config.name}.")

        api_host = os.getenv(api_host_name) or dotenv.get(api_host_name)
        self.base_url = (
            base_url
            or os.getenv(base_url_name)
            or dotenv.get(base_url_name)
            or _base_url_from_api_host(api_host, config.api_host_base_path)
            or config.default_base_url
        ).rstrip("/")
        self.transport = transport or _urlopen_transport
        self.max_retries = max_retries
        self.sleep = sleep

    def complete_json(self, *, model: str, prompt: str, temperature: float) -> str:
        payload = {
            "model": model,
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
        payload.update(self.config.extra_payload)

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
            "User-Agent": "werewolf-arena-live/0.1",
        }
        response = self._send_with_retries(f"{self.base_url}/chat/completions", headers, payload)
        return response["choices"][0]["message"]["content"]

    def _send_with_retries(
        self,
        url: str,
        headers: dict[str, str],
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        last_error: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            try:
                return self.transport(url, headers, payload)
            except urllib.error.HTTPError as exc:
                raise RuntimeError(_http_error_message(self.config, url, exc)) from exc
            except (urllib.error.URLError, TimeoutError, ConnectionResetError, OSError) as exc:
                last_error = exc
                if attempt == self.max_retries:
                    break
                self.sleep(min(2.0, 0.25 * attempt))

        raise RuntimeError(
            f"{self.config.name} network request failed after "
            f"{self.max_retries} attempts: {last_error}"
        ) from last_error


class DeepSeekProvider(OpenAICompatibleProvider):
    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        transport: Transport | None = None,
        max_retries: int = 3,
        sleep: Sleep = time.sleep,
    ) -> None:
        super().__init__(
            config=DEEPSEEK_CONFIG,
            api_key=api_key,
            base_url=base_url,
            transport=transport,
            max_retries=max_retries,
            sleep=sleep,
        )


class MiniMaxProvider(OpenAICompatibleProvider):
    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        transport: Transport | None = None,
        max_retries: int = 3,
        sleep: Sleep = time.sleep,
    ) -> None:
        super().__init__(
            config=MINIMAX_CONFIG,
            api_key=api_key,
            base_url=base_url,
            transport=transport,
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

    def complete_json(self, *, model: str, prompt: str, temperature: float) -> str:
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
        return provider.complete_json(model=model, prompt=prompt, temperature=temperature)

    def _registration_for_model(self, model: str) -> ModelProviderRegistration | None:
        for registration in self.registrations:
            if registration.matches(model):
                return registration
        return None


def create_model_provider(
    *,
    transport: Transport | None = None,
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
    max_retries: int,
    sleep: Sleep,
) -> Callable[[], ProviderLike]:
    return lambda: OpenAICompatibleProvider(
        config=config,
        transport=transport,
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
        model_names=_configured_model_names(config.env_prefix),
    )


def _configured_model_names(env_prefix: str) -> tuple[str, ...]:
    dotenv = _load_dotenv(Path(".env"), prefixes=(env_prefix,))
    model_name = os.getenv(f"{env_prefix}_MODEL") or dotenv.get(f"{env_prefix}_MODEL")
    return (model_name,) if model_name else ()


def default_model_name() -> str:
    dotenv = _load_dotenv(Path(".env"), prefixes=("WEREWOLF",))
    explicit_default = os.getenv("WEREWOLF_DEFAULT_MODEL") or dotenv.get("WEREWOLF_DEFAULT_MODEL")
    if explicit_default:
        return explicit_default

    for config in OPENAI_COMPATIBLE_PROVIDER_CONFIGS:
        if _has_api_key(config.env_prefix):
            configured_names = _configured_model_names(config.env_prefix)
            return configured_names[0] if configured_names else config.default_model

    return DEEPSEEK_CONFIG.default_model


def _has_api_key(env_prefix: str) -> bool:
    dotenv = _load_dotenv(Path(".env"), prefixes=(env_prefix,))
    api_key_name = f"{env_prefix}_API_KEY"
    return bool(os.getenv(api_key_name) or dotenv.get(api_key_name))


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
    if config.env_prefix == "MINIMAX" and exc.code == 401:
        message += (
            " Check MINIMAX_API_KEY and make sure MINIMAX_BASE_URL/MINIMAX_API_HOST "
            "matches the key region: Global=https://api.minimax.io/v1, "
            "Mainland=https://api.minimaxi.com/v1."
        )
    return message


def _read_http_error_body(exc: urllib.error.HTTPError) -> str:
    try:
        return exc.read().decode("utf-8", errors="replace")
    except Exception:
        return str(exc)


def _urlopen_transport(url: str, headers: dict[str, str], payload: dict[str, Any]) -> dict[str, Any]:
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(url, data=data, headers=headers, method="POST")
    with urllib.request.urlopen(request, timeout=120) as response:
        return json.loads(response.read().decode("utf-8"))


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
