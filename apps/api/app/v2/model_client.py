from __future__ import annotations

import asyncio
from collections.abc import Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
import json
import re
from typing import Any, Literal
import unicodedata

import httpx

from app.model_catalog.defaults import (
    DEFAULT_NON_THINKING_MAX_TOKENS,
    DEFAULT_THINKING_MAX_TOKENS,
)


V2ModelFailureCategory = Literal[
    "transport",
    "timeout",
    "machine_format",
    "provider_configuration",
    "internal_invariant",
]


@dataclass(frozen=True)
class V2FailureDisposition:
    category: V2ModelFailureCategory
    retryable: bool
    pausable: bool
    max_attempts: int


class V2ModelError(RuntimeError):
    def __init__(
        self,
        code: str,
        *,
        retryable: bool = False,
        failure_stage: str | None = None,
        exception_type: str | None = None,
        errno: int | None = None,
        http_status: int | None = None,
        provider_request_id: str | None = None,
        first_token_seen: bool = False,
        response_headers_seen: bool = False,
        response_headers: dict[str, str] | None = None,
        first_token_ms: int | None = None,
        first_token_kind: str | None = None,
        first_visible_text_ms: int | None = None,
        timeout_scope: str | None = None,
        elapsed_ms: int | None = None,
        retry_after_seconds: float | None = None,
        queue_wait_ms: int | None = None,
        provider_in_flight: int | None = None,
        provider_concurrency_limit: int | None = None,
        reasoning_delta_count: int = 0,
        text_delta_count: int = 0,
        max_inter_delta_ms: int | None = None,
        last_progress_ms: int | None = None,
    ) -> None:
        super().__init__(code)
        self.code = code
        self.retryable = retryable
        self.failure_stage = failure_stage
        self.exception_type = exception_type
        self.errno = errno
        self.http_status = http_status
        self.provider_request_id = provider_request_id
        self.first_token_seen = first_token_seen
        self.response_headers_seen = response_headers_seen
        self.response_headers = dict(response_headers or {})
        self.first_token_ms = first_token_ms
        self.first_token_kind = first_token_kind
        self.first_visible_text_ms = first_visible_text_ms
        self.timeout_scope = timeout_scope
        self.elapsed_ms = elapsed_ms
        self.retry_after_seconds = retry_after_seconds
        self.queue_wait_ms = queue_wait_ms
        self.provider_in_flight = provider_in_flight
        self.provider_concurrency_limit = provider_concurrency_limit
        self.reasoning_delta_count = reasoning_delta_count
        self.text_delta_count = text_delta_count
        self.max_inter_delta_ms = max_inter_delta_ms
        self.last_progress_ms = last_progress_ms


class V2QualityError(V2ModelError):
    def __init__(self, code: str, *, raw_response: str | None = None) -> None:
        super().__init__(
            code,
            retryable=code
            not in {
                "model_decision_contract_missing",
                "model_decision_contract_invalid",
            },
            failure_stage="machine_format",
        )
        self.raw_response = raw_response


@dataclass(frozen=True)
class V2ModelDecision:
    target_player_id: str | None
    speech: str | None
    provider_request_id: str
    first_token_ms: int
    completed_ms: int
    decision_note: str | None = None
    raw_response: str | None = None
    boolean_field: str | None = None
    boolean_value: bool | None = None
    repair_kind: str | None = None
    queue_wait_ms: int = 0
    provider_in_flight: int | None = None
    provider_concurrency_limit: int | None = None
    first_visible_text_ms: int | None = None
    reasoning_delta_count: int = 0
    text_delta_count: int = 0
    max_inter_delta_ms: int | None = None
    last_progress_ms: int | None = None


V2ModelProgressStage = Literal[
    "queued",
    "admitted",
    "response_headers",
    "first_token",
    "first_text",
]
V2ModelTokenKind = Literal["reasoning", "text"]


@dataclass(frozen=True)
class V2ModelProgress:
    stage: V2ModelProgressStage
    provider_request_id: str
    elapsed_ms: int
    response_headers: dict[str, str] | None = None
    token_kind: V2ModelTokenKind | None = None
    provider: str | None = None
    queue_wait_ms: int | None = None
    provider_in_flight: int | None = None
    provider_concurrency_limit: int | None = None


@dataclass(frozen=True)
class ParsedDecisionObject:
    value: dict[str, Any]
    repair_kind: str | None = None


@dataclass(frozen=True)
class V2ModelTarget:
    provider: str
    model_id: str
    parameters: dict[str, Any]


@dataclass(frozen=True)
class _ProviderRoute:
    api_key: str
    url: str
    protocol: str
    max_in_flight: int


@dataclass(frozen=True)
class _ProviderAdmission:
    queue_wait_ms: int
    provider_in_flight: int
    provider_concurrency_limit: int


@dataclass(frozen=True)
class _StreamResult:
    text: str
    provider_request_id: str
    first_token_ms: int
    completed_ms: int
    queue_wait_ms: int
    provider_in_flight: int
    provider_concurrency_limit: int
    first_visible_text_ms: int | None
    reasoning_delta_count: int
    text_delta_count: int
    max_inter_delta_ms: int | None
    last_progress_ms: int | None


class _ProviderGate:
    def __init__(self, limit: int) -> None:
        self.limit = limit
        self._semaphore = asyncio.Semaphore(limit)
        self._in_flight = 0

    @asynccontextmanager
    async def admit(
        self,
        *,
        check_cancellation: Callable[[], None] | None,
    ):
        loop = asyncio.get_running_loop()
        queued_at = loop.time()
        await _acquire_with_cancellation(
            self._semaphore,
            check_cancellation=check_cancellation,
        )
        self._in_flight += 1
        admission = _ProviderAdmission(
            queue_wait_ms=round((loop.time() - queued_at) * 1000),
            provider_in_flight=self._in_flight,
            provider_concurrency_limit=self.limit,
        )
        try:
            yield admission
        finally:
            self._in_flight -= 1
            self._semaphore.release()


@dataclass(frozen=True)
class _ProviderEvent:
    candidate_id: str | None = None
    text_delta: str | None = None
    reasoning_delta: str | None = None
    failed: bool = False
    finish_reason: str | None = None


_RETRYABLE_HTTP_STATUSES = frozenset({429, 502, 503, 504})
_RETRYABLE_TRANSPORT_ERRORS = (
    httpx.ConnectError,
    httpx.ConnectTimeout,
    httpx.ProxyError,
    httpx.ReadError,
    httpx.WriteError,
    httpx.RemoteProtocolError,
    httpx.PoolTimeout,
    OSError,
)
_DIAGNOSTIC_RESPONSE_HEADER_NAMES = frozenset(
    {
        "content-type",
        "date",
        "ratelimit-limit",
        "ratelimit-policy",
        "ratelimit-remaining",
        "ratelimit-reset",
        "request-id",
        "retry-after",
        "server",
        "traceparent",
        "tracestate",
        "x-envoy-upstream-service-time",
        "x-ratelimit-limit",
        "x-ratelimit-limit-requests",
        "x-ratelimit-limit-tokens",
        "x-ratelimit-remaining",
        "x-ratelimit-remaining-requests",
        "x-ratelimit-remaining-tokens",
        "x-ratelimit-reset",
        "x-ratelimit-reset-requests",
        "x-ratelimit-reset-tokens",
        "x-request-id",
        "x-response-time",
        "x-tt-logid",
    }
)
_MAX_DIAGNOSTIC_RESPONSE_HEADERS = 64
_MAX_DIAGNOSTIC_RESPONSE_HEADER_VALUE_CHARS = 1_024


def model_failure_disposition(exc: V2ModelError) -> V2FailureDisposition:
    if isinstance(exc, V2QualityError):
        recoverable = exc.code not in {
            "model_decision_contract_missing",
            "model_decision_contract_invalid",
        }
        return V2FailureDisposition(
            category="machine_format" if recoverable else "internal_invariant",
            retryable=recoverable,
            pausable=recoverable,
            max_attempts=2 if recoverable else 1,
        )
    if exc.code in {
        "model_first_token_timeout",
        "model_stream_idle_timeout",
        "model_attempt_hard_timeout",
        "model_total_timeout",
    }:
        return V2FailureDisposition(
            category="timeout",
            retryable=True,
            pausable=True,
            max_attempts=2,
        )
    if exc.code in {
        "model_transport_failed",
        "model_empty_stream",
        "model_invalid_sse",
        "model_invalid_event",
        "model_provider_failed",
    } or (exc.http_status in _RETRYABLE_HTTP_STATUSES):
        return V2FailureDisposition(
            category="transport",
            retryable=True,
            pausable=True,
            max_attempts=3,
        )
    if exc.code == "model_output_budget_exhausted":
        return V2FailureDisposition(
            category="machine_format",
            retryable=True,
            pausable=True,
            max_attempts=2,
        )
    if exc.code in {
        "model_not_configured",
        "model_provider_not_configured",
        "model_provider_credentials_missing",
    } or (exc.http_status is not None and 400 <= exc.http_status < 500):
        return V2FailureDisposition(
            category="provider_configuration",
            retryable=False,
            pausable=False,
            max_attempts=1,
        )
    return V2FailureDisposition(
        category="internal_invariant",
        retryable=exc.retryable,
        pausable=False,
        max_attempts=1,
    )


class V2ModelClient:
    def __init__(
        self,
        *,
        agent_plan_api_key: str,
        agent_plan_base_url: str,
        ark_api_key: str,
        ark_base_url: str,
        deepseek_api_key: str,
        deepseek_base_url: str,
        first_token_seconds: float,
        stream_idle_seconds: float,
        total_seconds: float,
        agent_plan_max_in_flight: int = 3,
        ark_max_in_flight: int = 3,
        deepseek_max_in_flight: int = 32,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._routes = {
            "agent_plan": _ProviderRoute(
                api_key=agent_plan_api_key.strip(),
                url=f"{agent_plan_base_url.rstrip('/')}/responses",
                protocol="responses",
                max_in_flight=agent_plan_max_in_flight,
            ),
            "ark": _ProviderRoute(
                api_key=ark_api_key.strip(),
                url=f"{ark_base_url.rstrip('/')}/responses",
                protocol="responses",
                max_in_flight=ark_max_in_flight,
            ),
            "deepseek": _ProviderRoute(
                api_key=deepseek_api_key.strip(),
                url=f"{deepseek_base_url.rstrip('/')}/chat/completions",
                protocol="chat_completions",
                max_in_flight=deepseek_max_in_flight,
            ),
        }
        self._first_token_seconds = first_token_seconds
        self._stream_idle_seconds = stream_idle_seconds
        self._total_seconds = total_seconds
        self._transport = transport
        self._gates = {
            provider: _ProviderGate(route.max_in_flight) for provider, route in self._routes.items()
        }
        self._clients: dict[str, httpx.AsyncClient] = {}

    @property
    def manages_attempt_timeout(self) -> bool:
        return True

    @property
    def first_token_seconds(self) -> float:
        return self._first_token_seconds

    @property
    def stream_idle_seconds(self) -> float:
        return self._stream_idle_seconds

    def provider_concurrency_limit(self, provider: str) -> int | None:
        route = self._routes.get(provider)
        return route.max_in_flight if route is not None else None

    async def aclose(self) -> None:
        clients = tuple(self._clients.values())
        self._clients.clear()
        for client in clients:
            await client.aclose()

    def _client_for(self, provider: str) -> httpx.AsyncClient:
        existing = self._clients.get(provider)
        if existing is not None:
            return existing
        route = self._routes[provider]
        client = httpx.AsyncClient(
            timeout=httpx.Timeout(connect=8.0, read=None, write=8.0, pool=8.0),
            limits=httpx.Limits(
                max_connections=route.max_in_flight,
                max_keepalive_connections=route.max_in_flight,
            ),
            transport=self._transport,
            trust_env=False,
        )
        self._clients[provider] = client
        return client

    def resolve_model_target(
        self,
        *,
        model_provider: str,
        model_id: str,
        model_parameters: dict[str, Any],
    ) -> V2ModelTarget:
        provider = model_provider.strip()
        selected_model_id = model_id.strip()
        if not provider or not selected_model_id:
            raise V2ModelError("model_not_configured")
        route = self._routes.get(provider)
        if route is None:
            raise V2ModelError("model_provider_not_configured")
        if not route.api_key:
            raise V2ModelError("model_provider_credentials_missing")
        return V2ModelTarget(
            provider=provider,
            model_id=selected_model_id,
            parameters=dict(model_parameters),
        )

    def build_request_payload(
        self,
        *,
        action_context: dict[str, Any],
        decision: bool,
        target: V2ModelTarget,
    ) -> dict[str, Any]:
        route = self._routes[target.provider]
        if route.protocol == "responses":
            return build_model_request_payload(
                action_context,
                decision=decision,
                model_id=target.model_id,
                parameters=target.parameters,
            )
        return build_chat_completions_request_payload(
            action_context,
            decision=decision,
            model_id=target.model_id,
            parameters=target.parameters,
        )

    async def generate_action_decision(
        self,
        *,
        action_context: dict[str, Any],
        attempt_id: str,
        target: V2ModelTarget,
        check_cancellation: Callable[[], None] | None = None,
    ) -> V2ModelDecision:
        return await self.generate_action_decision_with_progress(
            action_context=action_context,
            attempt_id=attempt_id,
            target=target,
            check_cancellation=check_cancellation,
            on_progress=None,
        )

    async def generate_action_decision_with_progress(
        self,
        *,
        action_context: dict[str, Any],
        attempt_id: str,
        target: V2ModelTarget,
        check_cancellation: Callable[[], None] | None = None,
        on_progress: Callable[[V2ModelProgress], None] | None = None,
    ) -> V2ModelDecision:
        result = await self._stream_text(
            action_context=action_context,
            attempt_id=attempt_id,
            max_output_tokens=None,
            decision=True,
            target=target,
            check_cancellation=check_cancellation,
            on_progress=on_progress,
        )
        raw = result.text
        output_contract = _decision_output_contract(action_context)
        try:
            try:
                parsed_object = _parse_decision_object(raw, output_contract=output_contract)
            except V2QualityError as exc:
                if not _decision_parse_can_fallback(exc):
                    raise
                parsed_object = None
            repair_kind = _decision_repair_kind(
                raw,
                output_contract,
                parsed_object=parsed_object,
            )
            (
                target_player_id,
                normalized_speech,
                boolean_field,
                boolean_value,
            ) = _decision_fields(
                raw,
                output_contract,
                parsed_object=parsed_object,
            )
            decision_note = _decision_note(
                raw,
                output_contract,
                parsed_object=parsed_object,
            )
        except V2QualityError as exc:
            raise V2QualityError(exc.code, raw_response=raw) from exc
        return V2ModelDecision(
            target_player_id=target_player_id,
            speech=normalized_speech,
            provider_request_id=result.provider_request_id,
            first_token_ms=result.first_token_ms,
            completed_ms=result.completed_ms,
            decision_note=decision_note,
            raw_response=raw,
            boolean_field=boolean_field,
            boolean_value=boolean_value,
            repair_kind=repair_kind,
            queue_wait_ms=result.queue_wait_ms,
            provider_in_flight=result.provider_in_flight,
            provider_concurrency_limit=result.provider_concurrency_limit,
            first_visible_text_ms=result.first_visible_text_ms,
            reasoning_delta_count=result.reasoning_delta_count,
            text_delta_count=result.text_delta_count,
            max_inter_delta_ms=result.max_inter_delta_ms,
            last_progress_ms=result.last_progress_ms,
        )

    async def _stream_text(
        self,
        *,
        action_context: dict[str, Any],
        attempt_id: str,
        max_output_tokens: int | None,
        decision: bool,
        target: V2ModelTarget,
        check_cancellation: Callable[[], None] | None,
        on_progress: Callable[[V2ModelProgress], None] | None,
    ) -> _StreamResult:
        _check(check_cancellation)
        route = self._routes[target.provider]
        gate = self._gates[target.provider]
        loop = asyncio.get_running_loop()
        queued_at = loop.time()
        if on_progress is not None:
            on_progress(
                V2ModelProgress(
                    stage="queued",
                    provider_request_id=attempt_id,
                    elapsed_ms=0,
                    provider=target.provider,
                    provider_concurrency_limit=route.max_in_flight,
                )
            )
        async with gate.admit(check_cancellation=check_cancellation) as admission:
            if on_progress is not None:
                on_progress(
                    V2ModelProgress(
                        stage="admitted",
                        provider_request_id=attempt_id,
                        elapsed_ms=admission.queue_wait_ms,
                        provider=target.provider,
                        queue_wait_ms=admission.queue_wait_ms,
                        provider_in_flight=admission.provider_in_flight,
                        provider_concurrency_limit=(admission.provider_concurrency_limit),
                    )
                )
            return await self._stream_text_admitted(
                action_context=action_context,
                attempt_id=attempt_id,
                max_output_tokens=max_output_tokens,
                decision=decision,
                target=target,
                route=route,
                admission=admission,
                queued_at=queued_at,
                check_cancellation=check_cancellation,
                on_progress=on_progress,
            )

    async def _stream_text_admitted(
        self,
        *,
        action_context: dict[str, Any],
        attempt_id: str,
        max_output_tokens: int | None,
        decision: bool,
        target: V2ModelTarget,
        route: _ProviderRoute,
        admission: _ProviderAdmission,
        queued_at: float,
        check_cancellation: Callable[[], None] | None,
        on_progress: Callable[[V2ModelProgress], None] | None,
    ) -> _StreamResult:
        loop = asyncio.get_running_loop()
        started = loop.time()
        first_token_at: float | None = None
        first_text_at: float | None = None
        last_progress_at: float | None = None
        max_inter_delta_ms: int | None = None
        reasoning_delta_count = 0
        text_delta_count = 0
        response_headers_seen = False
        provider_request_id = attempt_id
        text = ""
        reasoning_seen = False
        finish_reason: str | None = None
        payload = (
            build_model_request_payload(
                action_context,
                decision=decision,
                model_id=target.model_id,
                max_output_tokens=max_output_tokens,
                parameters=target.parameters,
            )
            if route.protocol == "responses"
            else build_chat_completions_request_payload(
                action_context,
                decision=decision,
                model_id=target.model_id,
                max_output_tokens=max_output_tokens,
                parameters=target.parameters,
            )
        )
        client = self._client_for(target.provider)
        response_header_timeout = min(
            self._first_token_seconds,
            self._total_seconds,
        )
        try:
            async with _stream_response_with_cancellation(
                client,
                "POST",
                route.url,
                timeout=response_header_timeout,
                check_cancellation=check_cancellation,
                headers={
                    "Authorization": f"Bearer {route.api_key}",
                    "Content-Type": "application/json",
                    "Accept": "text/event-stream",
                },
                json=payload,
            ) as response:
                response_headers_seen = True
                provider_request_id = (
                    response.headers.get("x-request-id")
                    or response.headers.get("x-tt-logid")
                    or attempt_id
                )
                response_headers = _diagnostic_response_headers(response.headers)
                if on_progress is not None:
                    on_progress(
                        V2ModelProgress(
                            stage="response_headers",
                            provider_request_id=provider_request_id,
                            elapsed_ms=round((loop.time() - started) * 1000),
                            response_headers=response_headers,
                        )
                    )
                if response.status_code >= 400:
                    await response.aread()
                    raise V2ModelError(
                        f"model_http_{response.status_code}",
                        retryable=response.status_code in _RETRYABLE_HTTP_STATUSES,
                        failure_stage="http_response",
                        http_status=response.status_code,
                        provider_request_id=provider_request_id,
                        response_headers_seen=True,
                        elapsed_ms=round((loop.time() - started) * 1000),
                        retry_after_seconds=_retry_after_seconds(
                            response.headers.get("Retry-After")
                        ),
                        **_stream_diagnostic_fields(
                            started=started,
                            admission=admission,
                            reasoning_delta_count=reasoning_delta_count,
                            text_delta_count=text_delta_count,
                            max_inter_delta_ms=max_inter_delta_ms,
                            last_progress_at=last_progress_at,
                        ),
                    )
                lines = response.aiter_lines().__aiter__()
                while True:
                    _check(check_cancellation)
                    now = loop.time()
                    hard_remaining = self._total_seconds - (now - started)
                    if first_token_at is None:
                        phase_remaining = self._first_token_seconds - (now - started)
                        timeout_scope = "first_token"
                    else:
                        assert last_progress_at is not None
                        phase_remaining = self._stream_idle_seconds - (now - last_progress_at)
                        timeout_scope = "stream_idle"
                    remaining = min(hard_remaining, phase_remaining)
                    if remaining <= 0:
                        scope = "attempt_hard" if hard_remaining <= 0 else timeout_scope
                        raise _model_timeout_error(
                            scope=scope,
                            started=started,
                            first_token_at=first_token_at,
                            provider_request_id=provider_request_id,
                            response_headers_seen=response_headers_seen,
                            admission=admission,
                            reasoning_delta_count=reasoning_delta_count,
                            text_delta_count=text_delta_count,
                            max_inter_delta_ms=max_inter_delta_ms,
                            last_progress_at=last_progress_at,
                        )
                    try:
                        line = await _next_with_cancellation(
                            lines,
                            timeout=remaining,
                            check_cancellation=check_cancellation,
                        )
                    except StopAsyncIteration:
                        break
                    except TimeoutError as exc:
                        now = loop.time()
                        scope = (
                            "attempt_hard"
                            if now - started >= self._total_seconds
                            else ("first_token" if first_token_at is None else "stream_idle")
                        )
                        raise _model_timeout_error(
                            scope=scope,
                            started=started,
                            first_token_at=first_token_at,
                            provider_request_id=provider_request_id,
                            response_headers_seen=response_headers_seen,
                            admission=admission,
                            reasoning_delta_count=reasoning_delta_count,
                            text_delta_count=text_delta_count,
                            max_inter_delta_ms=max_inter_delta_ms,
                            last_progress_at=last_progress_at,
                        ) from exc
                    event = _sse_data(line)
                    if event is None:
                        continue
                    provider_event = _provider_event(event, protocol=route.protocol)
                    if provider_event.candidate_id:
                        provider_request_id = provider_event.candidate_id
                    if provider_event.failed:
                        raise V2ModelError(
                            "model_provider_failed",
                            retryable=True,
                            failure_stage=("first_token" if first_token_at is None else "stream"),
                            provider_request_id=provider_request_id,
                            first_token_seen=first_token_at is not None,
                            response_headers_seen=True,
                            elapsed_ms=round((loop.time() - started) * 1000),
                            **_stream_diagnostic_fields(
                                started=started,
                                admission=admission,
                                reasoning_delta_count=reasoning_delta_count,
                                text_delta_count=text_delta_count,
                                max_inter_delta_ms=max_inter_delta_ms,
                                last_progress_at=last_progress_at,
                            ),
                        )
                    if provider_event.finish_reason:
                        finish_reason = provider_event.finish_reason
                    token_kind: V2ModelTokenKind | None = None
                    if provider_event.reasoning_delta:
                        reasoning_seen = True
                        reasoning_delta_count += 1
                        token_kind = "reasoning"
                    if provider_event.text_delta:
                        text_delta_count += 1
                        token_kind = token_kind or "text"
                        text += provider_event.text_delta
                    if token_kind is None:
                        continue
                    progress_at = loop.time()
                    if last_progress_at is not None:
                        inter_delta_ms = round((progress_at - last_progress_at) * 1000)
                        max_inter_delta_ms = max(max_inter_delta_ms or 0, inter_delta_ms)
                    last_progress_at = progress_at
                    if first_token_at is None:
                        first_token_at = progress_at
                        if on_progress is not None:
                            on_progress(
                                V2ModelProgress(
                                    stage="first_token",
                                    provider_request_id=provider_request_id,
                                    elapsed_ms=round((first_token_at - started) * 1000),
                                    token_kind=token_kind,
                                )
                            )
                    if (
                        provider_event.text_delta
                        and first_text_at is None
                        and provider_event.text_delta.strip()
                    ):
                        first_text_at = progress_at
                        if on_progress is not None:
                            on_progress(
                                V2ModelProgress(
                                    stage="first_text",
                                    provider_request_id=provider_request_id,
                                    elapsed_ms=round((first_text_at - started) * 1000),
                                    token_kind="text",
                                )
                            )
        except V2ModelError:
            raise
        except TimeoutError as exc:
            timeout_scope: Literal["first_token", "attempt_hard"] = (
                "attempt_hard" if loop.time() - started >= self._total_seconds else "first_token"
            )
            raise _model_timeout_error(
                scope=timeout_scope,
                started=started,
                first_token_at=first_token_at,
                provider_request_id=provider_request_id,
                response_headers_seen=response_headers_seen,
                admission=admission,
                reasoning_delta_count=reasoning_delta_count,
                text_delta_count=text_delta_count,
                max_inter_delta_ms=max_inter_delta_ms,
                last_progress_at=last_progress_at,
            ) from exc
        except (httpx.HTTPError, OSError) as exc:
            root = _root_exception(exc)
            root_errno = getattr(root, "errno", None)
            raise V2ModelError(
                "model_transport_failed",
                retryable=isinstance(exc, _RETRYABLE_TRANSPORT_ERRORS),
                failure_stage=_transport_failure_stage(
                    exc,
                    first_token_seen=first_token_at is not None,
                ),
                exception_type=f"{type(root).__module__}.{type(root).__name__}",
                errno=(
                    root_errno
                    if isinstance(root_errno, int) and not isinstance(root_errno, bool)
                    else None
                ),
                provider_request_id=provider_request_id,
                first_token_seen=first_token_at is not None,
                response_headers_seen=response_headers_seen,
                elapsed_ms=round((loop.time() - started) * 1000),
                **_stream_diagnostic_fields(
                    started=started,
                    admission=admission,
                    reasoning_delta_count=reasoning_delta_count,
                    text_delta_count=text_delta_count,
                    max_inter_delta_ms=max_inter_delta_ms,
                    last_progress_at=last_progress_at,
                ),
            ) from exc
        if not text.strip():
            if finish_reason in {"length", "max_output_tokens"}:
                raise V2ModelError("model_output_budget_exhausted", retryable=True)
            if first_token_at is None:
                raise V2ModelError("model_empty_stream", retryable=True)
            if reasoning_seen:
                raise V2ModelError("model_empty_stream", retryable=True)
        if first_token_at is None:
            raise V2ModelError("model_empty_stream", retryable=True)
        completed = loop.time()
        return _StreamResult(
            text=text.strip(),
            provider_request_id=provider_request_id,
            first_token_ms=round((first_token_at - started) * 1000),
            completed_ms=round((completed - started) * 1000),
            queue_wait_ms=round((started - queued_at) * 1000),
            provider_in_flight=admission.provider_in_flight,
            provider_concurrency_limit=admission.provider_concurrency_limit,
            first_visible_text_ms=(
                round((first_text_at - started) * 1000) if first_text_at is not None else None
            ),
            reasoning_delta_count=reasoning_delta_count,
            text_delta_count=text_delta_count,
            max_inter_delta_ms=max_inter_delta_ms,
            last_progress_ms=(
                round((last_progress_at - started) * 1000) if last_progress_at is not None else None
            ),
        )


def _model_timeout_error(
    *,
    scope: Literal["first_token", "stream_idle", "attempt_hard"],
    started: float,
    first_token_at: float | None,
    provider_request_id: str,
    response_headers_seen: bool,
    admission: _ProviderAdmission,
    reasoning_delta_count: int,
    text_delta_count: int,
    max_inter_delta_ms: int | None,
    last_progress_at: float | None,
) -> V2ModelError:
    before_first_token = first_token_at is None
    code = {
        "first_token": "model_first_token_timeout",
        "stream_idle": "model_stream_idle_timeout",
        "attempt_hard": "model_attempt_hard_timeout",
    }[scope]
    return V2ModelError(
        code,
        retryable=True,
        failure_stage=(
            "response_headers"
            if not response_headers_seen
            else ("first_token" if before_first_token else "stream")
        ),
        provider_request_id=provider_request_id,
        first_token_seen=not before_first_token,
        response_headers_seen=response_headers_seen,
        timeout_scope=scope,
        elapsed_ms=round((asyncio.get_running_loop().time() - started) * 1000),
        **_stream_diagnostic_fields(
            started=started,
            admission=admission,
            reasoning_delta_count=reasoning_delta_count,
            text_delta_count=text_delta_count,
            max_inter_delta_ms=max_inter_delta_ms,
            last_progress_at=last_progress_at,
        ),
    )


def _stream_diagnostic_fields(
    *,
    started: float,
    admission: _ProviderAdmission,
    reasoning_delta_count: int,
    text_delta_count: int,
    max_inter_delta_ms: int | None,
    last_progress_at: float | None,
) -> dict[str, int | None]:
    return {
        "queue_wait_ms": admission.queue_wait_ms,
        "provider_in_flight": admission.provider_in_flight,
        "provider_concurrency_limit": admission.provider_concurrency_limit,
        "reasoning_delta_count": reasoning_delta_count,
        "text_delta_count": text_delta_count,
        "max_inter_delta_ms": max_inter_delta_ms,
        "last_progress_ms": (
            round((last_progress_at - started) * 1000) if last_progress_at is not None else None
        ),
    }


def _retry_after_seconds(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        seconds = float(value.strip())
    except ValueError:
        return None
    return max(0.0, seconds)


def _diagnostic_response_headers(headers: httpx.Headers) -> dict[str, str]:
    output: dict[str, str] = {}
    for name, value in headers.multi_items():
        normalized_name = name.lower()
        if normalized_name not in _DIAGNOSTIC_RESPONSE_HEADER_NAMES:
            continue
        output[normalized_name] = value[:_MAX_DIAGNOSTIC_RESPONSE_HEADER_VALUE_CHARS]
        if len(output) >= _MAX_DIAGNOSTIC_RESPONSE_HEADERS:
            break
    return output


def _root_exception(exc: BaseException) -> BaseException:
    current = exc
    seen: set[int] = set()
    while id(current) not in seen:
        seen.add(id(current))
        nested = current.__cause__ or current.__context__
        if nested is None:
            break
        current = nested
    return current


def _transport_failure_stage(
    exc: BaseException,
    *,
    first_token_seen: bool,
) -> str:
    if first_token_seen:
        return "stream"
    if isinstance(
        exc,
        (
            httpx.ConnectError,
            httpx.ConnectTimeout,
            httpx.ProxyError,
            httpx.PoolTimeout,
        ),
    ):
        return "connect"
    if isinstance(exc, httpx.WriteError):
        return "write"
    if isinstance(exc, (httpx.ReadError, httpx.RemoteProtocolError)):
        return "read"
    return "transport"


def _provider_event(
    event: dict[str, Any],
    *,
    protocol: str,
) -> _ProviderEvent:
    if protocol == "responses":
        response_object = event.get("response")
        candidate_id = (
            response_object.get("id")
            if isinstance(response_object, dict) and isinstance(response_object.get("id"), str)
            else None
        )
        text_delta = (
            event.get("delta")
            if event.get("type") == "response.output_text.delta"
            and isinstance(event.get("delta"), str)
            else None
        )
        reasoning_delta = (
            event.get("delta")
            if event.get("type")
            in {
                "response.reasoning_summary_text.delta",
                "response.reasoning_text.delta",
            }
            and isinstance(event.get("delta"), str)
            else None
        )
        response_status = (
            response_object.get("status") if isinstance(response_object, dict) else None
        )
        incomplete_details = (
            response_object.get("incomplete_details") if isinstance(response_object, dict) else None
        )
        incomplete_reason = (
            incomplete_details.get("reason")
            if isinstance(incomplete_details, dict)
            and isinstance(incomplete_details.get("reason"), str)
            else None
        )
        return _ProviderEvent(
            candidate_id=candidate_id,
            text_delta=text_delta,
            reasoning_delta=reasoning_delta,
            failed=event.get("type") in {"response.failed", "error"},
            finish_reason=(
                incomplete_reason
                if response_status == "incomplete" or event.get("type") == "response.incomplete"
                else None
            ),
        )

    candidate_id = event.get("id") if isinstance(event.get("id"), str) else None
    choices = event.get("choices")
    text_delta: str | None = None
    reasoning_delta: str | None = None
    finish_reason: str | None = None
    if isinstance(choices, list) and choices and isinstance(choices[0], dict):
        delta_object = choices[0].get("delta")
        if isinstance(delta_object, dict) and isinstance(delta_object.get("content"), str):
            text_delta = delta_object["content"]
        if isinstance(delta_object, dict) and isinstance(
            delta_object.get("reasoning_content"), str
        ):
            reasoning_delta = delta_object["reasoning_content"]
        if isinstance(choices[0].get("finish_reason"), str):
            finish_reason = choices[0]["finish_reason"]
    return _ProviderEvent(
        candidate_id=candidate_id,
        text_delta=text_delta,
        reasoning_delta=reasoning_delta,
        failed="error" in event,
        finish_reason=finish_reason,
    )


async def _next_with_cancellation(
    lines: Any,
    *,
    timeout: float,
    check_cancellation: Callable[[], None] | None,
) -> str:
    task = asyncio.create_task(anext(lines))
    loop = asyncio.get_running_loop()
    started = loop.time()
    try:
        while True:
            remaining = timeout - (loop.time() - started)
            if remaining <= 0:
                raise TimeoutError
            done, _pending = await asyncio.wait(
                {task},
                timeout=min(remaining, 0.25),
            )
            if task in done:
                return task.result()
            _check(check_cancellation)
    finally:
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)


@asynccontextmanager
async def _stream_response_with_cancellation(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    *,
    timeout: float,
    check_cancellation: Callable[[], None] | None,
    **kwargs: Any,
):
    stream_context = client.stream(method, url, **kwargs)
    enter_task = asyncio.create_task(stream_context.__aenter__())
    loop = asyncio.get_running_loop()
    started = loop.time()
    entered = False
    try:
        while True:
            remaining = timeout - (loop.time() - started)
            if remaining <= 0:
                raise TimeoutError
            done, _pending = await asyncio.wait(
                {enter_task},
                timeout=min(remaining, 0.25),
            )
            if enter_task in done:
                response = enter_task.result()
                entered = True
                break
            _check(check_cancellation)
        try:
            yield response
        except BaseException as exc:
            await stream_context.__aexit__(type(exc), exc, exc.__traceback__)
            raise
        else:
            await stream_context.__aexit__(None, None, None)
    finally:
        if not entered:
            if not enter_task.done():
                enter_task.cancel()
                await asyncio.gather(enter_task, return_exceptions=True)
            elif not enter_task.cancelled():
                try:
                    enter_task.result()
                except BaseException:
                    pass
                else:
                    # The request may have crossed the completion boundary
                    # immediately after the wait timed out or cancellation was
                    # observed. Close that response explicitly so a raced
                    # cancellation cannot leak a pooled connection.
                    await stream_context.__aexit__(None, None, None)


async def _acquire_with_cancellation(
    semaphore: asyncio.Semaphore,
    *,
    check_cancellation: Callable[[], None] | None,
) -> None:
    task = asyncio.create_task(semaphore.acquire())
    handed_off = False
    try:
        while True:
            done, _pending = await asyncio.wait({task}, timeout=0.25)
            if task in done:
                task.result()
                handed_off = True
                return
            _check(check_cancellation)
    finally:
        if not handed_off:
            if not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
            elif not task.cancelled():
                try:
                    acquired = task.result()
                except BaseException:
                    pass
                else:
                    # If cancellation won the race just after acquire
                    # completed, return the permit here because ownership was
                    # never handed to _ProviderGate.
                    if acquired:
                        semaphore.release()


def _check(check_cancellation: Callable[[], None] | None) -> None:
    if check_cancellation is not None:
        check_cancellation()


def build_model_request_payload(
    action_context: dict[str, Any],
    *,
    decision: bool,
    model_id: str,
    max_output_tokens: int | None = None,
    parameters: dict[str, Any] | None = None,
) -> dict[str, Any]:
    configured = dict(parameters or {})
    payload: dict[str, Any] = {
        "model": model_id,
        "stream": True,
        "max_output_tokens": _effective_max_tokens(configured, max_output_tokens),
        "input": (
            _decision_model_input(action_context) if decision else _model_input(action_context)
        ),
    }
    _apply_common_parameters(
        payload,
        configured,
        include_penalties=False,
    )
    return payload


def build_chat_completions_request_payload(
    action_context: dict[str, Any],
    *,
    decision: bool,
    model_id: str,
    max_output_tokens: int | None = None,
    parameters: dict[str, Any] | None = None,
) -> dict[str, Any]:
    configured = dict(parameters or {})
    response_input = (
        _decision_model_input(action_context) if decision else _model_input(action_context)
    )
    payload: dict[str, Any] = {
        "model": model_id,
        "stream": True,
        "max_tokens": _effective_max_tokens(configured, max_output_tokens),
        "messages": [
            {
                "role": item["role"],
                "content": "\n".join(
                    content["text"]
                    for content in item["content"]
                    if isinstance(content, dict) and isinstance(content.get("text"), str)
                ),
            }
            for item in response_input
        ],
        "response_format": {"type": "json_object"},
    }
    _apply_common_parameters(
        payload,
        configured,
        include_penalties=True,
    )
    if configured.get("thinking", "default") != "disabled":
        payload.pop("temperature", None)
        payload.pop("top_p", None)
        payload.pop("frequency_penalty", None)
        payload.pop("presence_penalty", None)
    return payload


def _effective_max_tokens(
    parameters: dict[str, Any],
    requested: int | None,
) -> int:
    configured = parameters.get("max_tokens")
    if isinstance(configured, int) and not isinstance(configured, bool):
        return configured
    if isinstance(requested, int) and not isinstance(requested, bool):
        return requested
    if parameters.get("thinking", "default") == "disabled":
        return DEFAULT_NON_THINKING_MAX_TOKENS
    return DEFAULT_THINKING_MAX_TOKENS


def _apply_common_parameters(
    payload: dict[str, Any],
    parameters: dict[str, Any],
    *,
    include_penalties: bool,
) -> None:
    thinking = parameters.get("thinking", "default")
    if thinking in {"enabled", "disabled"}:
        payload["thinking"] = {"type": thinking}
    reasoning_effort = parameters.get("reasoning_effort")
    if thinking != "disabled" and isinstance(reasoning_effort, str) and reasoning_effort:
        payload["reasoning_effort"] = reasoning_effort
    parameter_names = ["temperature", "top_p"]
    if include_penalties:
        parameter_names.extend(("frequency_penalty", "presence_penalty"))
    for parameter in parameter_names:
        value = parameters.get(parameter)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            payload[parameter] = value


def _model_input(action_context: dict[str, Any]) -> list[dict[str, Any]]:
    context_json = json.dumps(action_context, ensure_ascii=False, separators=(",", ":"))
    return [
        {
            "role": "system",
            "content": [
                {
                    "type": "input_text",
                    "text": (
                        "你是狼人杀直播法官。根据实时动作要求，输出自然、适合直接播报的"
                        "中文法官话术。只输出播报正文，不要附加解释或"
                        "玩家身份信息。"
                    ),
                }
            ],
        },
        {
            "role": "user",
            "content": [
                {
                    "type": "input_text",
                    "text": f"请执行这个实时动作：{context_json}",
                }
            ],
        },
    ]


def _decision_model_input(action_context: dict[str, Any]) -> list[dict[str, Any]]:
    context_json = json.dumps(action_context, ensure_ascii=False, separators=(",", ":"))
    output_contract = _decision_output_contract(action_context)
    if not isinstance(output_contract, dict):
        raise V2ModelError("model_decision_contract_missing")
    kind = output_contract.get("kind")
    speech_instruction = _speech_output_instruction(output_contract)
    note_instruction = _decision_note_output_instruction(output_contract)
    if kind == "boolean":
        field = output_contract.get("field")
        if not isinstance(field, str) or not field.strip():
            raise V2ModelError("model_decision_contract_invalid")
        boolean = output_contract.get("boolean")
        boolean = boolean if isinstance(boolean, dict) else {}
        output_instruction = (
            f"输出一个 JSON 对象，决定字段必须是 {field}，且必须为布尔值。"
            f"true 表示{boolean.get('true_means') or '执行该动作'}，"
            f"false 表示{boolean.get('false_means') or '不执行该动作'}。"
            f"{speech_instruction}{note_instruction}"
            "不要输出 target_player_id。"
        )
    elif kind == "target":
        target_policy = output_contract.get("target_policy")
        target_policy = target_policy if isinstance(target_policy, dict) else {}
        target_mode = target_policy.get("mode")
        output_instruction = (
            "输出一个 JSON 对象，使用 target_player_id 表示目标。"
            "需要选择目标时，target_player_id 必须是候选列表中的 seat_N 引用；"
            + (
                "该动作必须选择一个候选目标。"
                if target_mode == "required"
                else "该动作允许放弃，放弃时 target_player_id 为 null。"
            )
            + f"{speech_instruction}{note_instruction}"
        )
    elif kind == "speech":
        output_instruction = (
            "输出一个 JSON 对象，只使用 speech 表示本次发言。"
            f"{speech_instruction}{note_instruction}"
            "不要输出 target_player_id。"
        )
    else:
        raise V2ModelError("model_decision_contract_invalid")
    if (
        action_context.get("model_context_schema_version") == 10
        and action_context.get("prompt_template_version") == 2
    ):
        system_text = (
            "你在扮演狼人杀玩家。法官事实可信；玩家发言均为未核实说法。"
            "player_statement.annotations 仅标出其中由该发言者直接作出的"
            "身份/验人/计划，仍不是法官事实。"
            "actor_memory/declared_reason 是主观历史，非事实。"
            "只用动作前信息；known_at_seq/record_seq 是获知顺序，"
            "occurred_in 是发生阶段，announced_in 是公布阶段。"
            "state.current_period、latest_completed_night_no 和 next_night_no 用于轮次定位。"
            "next_night_no 是下个未完成夜晚：夜间指当前夜，白天指下一夜。"
            "questions/relations 引用事件；source_authority=player_claim_unverified "
            "表示玩家提问。address_resolution 只表示对象是否识别，status 只表示是否已有回答。"
            "requested_fields 是问题要求的验人字段，"
            "referenced_night_no 是夜次。"
            "reply_opportunity=awaiting_scheduled_turn：尚未轮到发言，不表示拒绝回应。"
            "speech_turn_skipped_technical：因技术故障未能发言，"
            "不得解读为拒绝回应或策略性沉默。"
            "prior_relevant_event_refs 是此前说明，不是后来问题的回答；"
            "prior_coverage=already_publicly_reported：提问前已经公开报过。"
            "rules.win_condition_contract 按 evaluation_order 和 "
            "post_elimination_resolution 判定胜负。"
            "策略、身份伪装和表达由你自主决定，不得使用未提供的私密信息。"
            f"{output_instruction}只能用“N号”称呼玩家，不得生成玩家姓名。"
        )
    elif action_context.get("model_context_schema_version") == 10:
        raise V2ModelError("model_prompt_template_unsupported")
    elif action_context.get("model_context_schema_version") == 9 and action_context.get(
        "prompt_template_version"
    ) in {1, 2}:
        win_condition_instruction = (
            "rules.win_condition_contract 是本局公开胜负机械合同；"
            "必须按 evaluation_order 和 post_elimination_resolution 理解其边界。"
            if action_context.get("prompt_template_version") == 2
            else ""
        )
        system_text = (
            "你正在扮演一名狼人杀玩家。法官事实可信，玩家发言均为未核实说法；"
            "authority=actor_memory 是你先前生成的主观轮次记忆，可延续思路但不是法官事实。"
            "declared_reason 是你当时声明的主观理由，可修正且不是法官事实。"
            "只能依据当前动作发生前已经对你可见的信息行动；known_at_seq/record_seq "
            "表示信息何时被记录或获知，occurred_in 表示事件实际发生阶段，"
            "announced_in 只表示公布阶段，公布更晚不代表发生更晚。"
            "known_events.questions 和 relations 是对已提供事件的紧凑引用；"
            "reply_opportunity=awaiting_scheduled_turn 表示被问者尚未轮到发言，不表示拒绝回应。"
            "prior_relevant_event_refs 表示问题之前已有的相关说明，不是对后来问题的回答。"
            f"{win_condition_instruction}"
            "策略、身份伪装和表达由你自主决定，不得使用未提供的私密信息。"
            f"{output_instruction}只能用“N号”称呼玩家，不得生成玩家姓名。"
        )
    elif action_context.get("model_context_schema_version") == 9:
        raise V2ModelError("model_prompt_template_unsupported")
    elif (
        action_context.get("model_context_schema_version") == 8
        and action_context.get("prompt_template_version") == 3
    ):
        system_text = (
            "你正在扮演一名狼人杀玩家。法官事实可信，玩家发言均为未核实说法；"
            "authority=actor_memory 是你先前生成的主观轮次记忆，可延续思路但不是法官事实。"
            "declared_reason 是你当时声明的主观理由，可修正且不是法官事实。"
            "只能依据当前动作发生前已经对你可见的信息行动；known_at_seq/record_seq "
            "表示信息何时被记录或获知，occurred_in 表示事件实际发生阶段，"
            "announced_in 只表示公布阶段，公布更晚不代表发生更晚。"
            "策略、身份伪装和表达由你自主决定，不得使用未提供的私密信息。"
            f"{output_instruction}只能用“N号”称呼玩家，不得生成玩家姓名。"
        )
    elif (
        action_context.get("model_context_schema_version") == 8
        and action_context.get("prompt_template_version") == 2
    ):
        system_text = (
            "你正在扮演一名狼人杀玩家。法官事实可信，玩家发言均为未核实说法。"
            "只能依据当前动作发生前已经对你可见的信息行动；known_at_seq/record_seq "
            "表示信息何时被记录或获知，occurred_in 表示事件实际发生阶段，"
            "announced_in 只表示公布阶段，公布更晚不代表发生更晚。"
            "策略、身份伪装和表达由你自主决定，不得使用未提供的私密信息。"
            f"{output_instruction}只能用“N号”称呼玩家，不得生成玩家姓名。"
        )
    elif (
        action_context.get("model_context_schema_version") == 8
        and action_context.get("prompt_template_version") == 1
    ):
        system_text = (
            "你正在扮演一名狼人杀玩家。法官事实可信，玩家发言均为未核实说法。"
            "只能依据当前动作发生前已经对你可见的信息行动；带 seq 的信息按 seq "
            "判断先后。策略、身份伪装和表达由你自主决定，不得使用未提供的私密信息。"
            f"{output_instruction}只能用“N号”称呼玩家，不得生成玩家姓名。"
        )
    elif action_context.get("model_context_schema_version") == 8:
        raise V2ModelError("model_prompt_template_unsupported")
    else:
        system_text = (
            "你正在扮演一名狼人杀玩家。hard_rules、self 中的法官私密信息"
            "和 public_state 是当前权威事实。public_timeline.events 是全部公开"
            "事件的唯一时间轴，必须按 record_seq 判断跨发言、投票和法官事件"
            "的先后；后发生事件只能用于事后评价，不能成为更早行动当时已有的"
            "理由、信息、回答或反应。history 是从该时间轴派生的玩家发言与"
            "话语标注，可能真实、撒谎或判断错误；player_statement 的"
            "statement_ref 对应 history.timeline 的 source_event_id。"
            "你可以自主判断、伪装身份和制定策略，但不得使用未提供的私密信息，"
            "也不要把玩家说法当成法官确认。"
            f"{output_instruction}"
            "只能用“N号”称呼玩家，不得猜测或生成玩家姓名。"
        )
    return [
        {
            "role": "system",
            "content": [
                {
                    "type": "input_text",
                    "text": system_text,
                }
            ],
        },
        {
            "role": "user",
            "content": [
                {
                    "type": "input_text",
                    "text": f"请完成这个实时动作：{context_json}",
                }
            ],
        },
    ]


def _decision_output_contract(action_context: dict[str, Any]) -> dict[str, Any] | None:
    response = action_context.get("response")
    if isinstance(response, dict):
        return response
    output_contract = action_context.get("output_contract")
    return output_contract if isinstance(output_contract, dict) else None


def _speech_output_instruction(output_contract: dict[str, Any]) -> str:
    speech = output_contract.get("speech")
    speech = speech if isinstance(speech, dict) else {}
    mode = speech.get("mode")
    private_memory = output_contract.get("presentation_kind") == "private_round_memory"
    if mode == "required" and private_memory:
        instruction = (
            "speech 必须是仅供你本人后续决策使用的非空中文轮次记忆，"
            "不会公开播报，不要写成对其他玩家喊话。"
        )
    elif mode == "required":
        instruction = "speech 必须是准备直接播报的非空自然中文。"
    elif mode == "optional":
        instruction = "speech 可省略或为 null；若提供，必须是可直接播报的非空自然中文。"
    elif mode == "forbidden":
        return "不得输出 speech。"
    elif mode == "required_if_true":
        instruction = (
            "决定字段为 true 时 speech 必须是可直接播报的非空自然中文；"
            "为 false 时不要发言，speech 应省略或为 null。"
        )
    else:
        raise V2ModelError("model_decision_contract_invalid")

    max_chars = speech.get("max_chars")
    if isinstance(max_chars, int) and max_chars > 0:
        instruction += f"speech 不得超过{max_chars}字。"
    max_sentences = speech.get("max_sentences")
    if isinstance(max_sentences, int) and max_sentences > 0:
        instruction += (
            "speech 只能包含一句话。"
            if max_sentences == 1
            else f"speech 不得超过{max_sentences}句话。"
        )
    return instruction


def _decision_note_output_instruction(output_contract: dict[str, Any]) -> str:
    note = output_contract.get("decision_note")
    if not isinstance(note, dict) or note.get("mode") == "none":
        return ""
    if note.get("mode") != "optional":
        raise V2ModelError("model_decision_contract_invalid")
    max_chars = note.get("max_chars")
    limit = max_chars if isinstance(max_chars, int) and max_chars > 0 else 120
    return (
        f"请用 decision_note 提供不超过{limit}字的一句简短对局理由；"
        "它是可供后续动作引用的主观声明，不是法官事实或隐藏推理过程。"
    )


def _sse_data(line: str) -> dict[str, Any] | None:
    if not line.startswith("data:"):
        return None
    raw = line[5:].strip()
    if not raw or raw == "[DONE]":
        return None
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise V2ModelError("model_invalid_sse", retryable=True) from exc
    if not isinstance(value, dict):
        raise V2ModelError("model_invalid_event", retryable=True)
    return value


def _decision_object(raw: str) -> dict[str, Any]:
    return _parse_decision_object(raw, output_contract=None).value


def _parse_decision_object(
    raw: str,
    *,
    output_contract: Any,
) -> ParsedDecisionObject:
    duplicate = _duplicate_decision_object(raw, output_contract=output_contract)
    if duplicate is not None:
        return duplicate
    if _has_additional_json_document(raw):
        raise V2QualityError("model_decision_invalid_json_document")
    return ParsedDecisionObject(value=_single_decision_object(raw))


def _decision_parse_can_fallback(exc: V2QualityError) -> bool:
    return exc.code in {
        "model_decision_invalid_json",
        "model_decision_invalid_shape",
    }


def _single_decision_object(raw: str) -> dict[str, Any]:
    candidates = [raw.strip()]
    start = raw.find("{")
    end = raw.rfind("}")
    if 0 <= start < end:
        candidates.append(raw[start : end + 1])
    for candidate in candidates:
        for serialized in _serialized_decision_candidates(candidate):
            try:
                value = json.loads(serialized)
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                return value
            raise V2QualityError("model_decision_invalid_shape")
    raise V2QualityError("model_decision_invalid_json")


def _serialized_decision_candidates(value: str) -> tuple[str, ...]:
    delimiter_repaired = _repair_compatibility_key_delimiter(value)
    normalized = _normalize_json_syntax_nfkc(delimiter_repaired)
    normalized_repaired = _repair_compatibility_key_delimiter(normalized)
    candidates = (
        value,
        _repair_single_trailing_brace(value),
        _repair_structural_smart_quotes(value),
        normalized,
        _repair_single_trailing_brace(normalized),
        _repair_structural_smart_quotes(normalized),
        normalized_repaired,
        _repair_single_trailing_brace(normalized_repaired),
        _repair_structural_smart_quotes(normalized_repaired),
    )
    return tuple(dict.fromkeys(candidates))


def _duplicate_decision_object(
    raw: str,
    *,
    output_contract: Any,
) -> ParsedDecisionObject | None:
    for serialized in _serialized_decision_candidates(raw.strip()):
        objects = _two_top_level_json_objects(serialized)
        if objects is None:
            continue
        first, second = objects
        first_semantics = _decision_object_semantics(first, output_contract)
        second_semantics = _decision_object_semantics(second, output_contract)
        if first_semantics != second_semantics:
            raise V2QualityError("model_decision_ambiguous_multiple_objects")
        return ParsedDecisionObject(
            value=first,
            repair_kind="duplicate_identical_json_ignored",
        )
    return None


def _two_top_level_json_objects(
    serialized: str,
) -> tuple[dict[str, Any], dict[str, Any]] | None:
    value = serialized.strip()
    decoder = json.JSONDecoder()
    try:
        first, first_end = decoder.raw_decode(value)
    except json.JSONDecodeError:
        return None
    if not isinstance(first, dict):
        return None

    position = _skip_json_whitespace(value, first_end)
    fenced = False
    fence = re.match(r"```(?:json)?[ \t]*(?:\r?\n)", value[position:], flags=re.IGNORECASE)
    if fence is not None:
        fenced = True
        position += fence.end()
        position = _skip_json_whitespace(value, position)
    elif position >= len(value) or value[position] != "{":
        return None

    try:
        second, second_end = decoder.raw_decode(value, position)
    except json.JSONDecodeError:
        return None
    if not isinstance(second, dict):
        return None
    position = _skip_json_whitespace(value, second_end)
    if fenced:
        if not value.startswith("```", position):
            return None
        position = _skip_json_whitespace(value, position + 3)
    if position != len(value):
        return None
    return first, second


def _skip_json_whitespace(value: str, position: int) -> int:
    while position < len(value) and value[position].isspace():
        position += 1
    return position


def _has_additional_json_document(raw: str) -> bool:
    stripped = _strip_json_fence(raw)
    for serialized in _serialized_decision_candidates(stripped):
        start = serialized.find("{")
        if start < 0:
            continue
        try:
            first, first_end = json.JSONDecoder().raw_decode(serialized, start)
        except json.JSONDecodeError:
            continue
        if not isinstance(first, dict):
            continue
        tail = serialized[first_end:].lstrip()
        if tail.startswith("{"):
            return True
        if tail.startswith("```"):
            prefix = serialized[:start]
            after_fence = tail[3:].lstrip()
            if "```" in prefix and not after_fence.startswith(("{", "```", "json\n", "json\r\n")):
                continue
            return True
    return False


def _decision_object_semantics(
    value: dict[str, Any],
    output_contract: Any,
) -> str:
    if not isinstance(output_contract, dict):
        payload = value
    else:
        _decision_fields_from_object(
            value,
            output_contract,
        )
        _decision_note_from_object(value, output_contract)
        payload = _decision_payload(value, output_contract=output_contract)
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _repair_single_trailing_brace(value: str) -> str:
    stripped = value.strip()
    if not stripped.endswith("}"):
        return value
    try:
        parsed, end = json.JSONDecoder().raw_decode(stripped)
    except json.JSONDecodeError:
        return value
    if isinstance(parsed, dict) and stripped[end:].strip() == "}":
        return stripped[:end]
    return value


def _repair_compatibility_key_delimiter(value: str) -> str:
    return re.sub(
        (
            r'(?P<prefix>[{｛,，]\s*)"'
            r"(?P<key>[A-Za-z_][A-Za-z0-9_]*)"
            r'(?P<delimiter>[:：])"'
        ),
        r'\g<prefix>"\g<key>"\g<delimiter>"',
        value,
    )


def _normalize_json_syntax_nfkc(value: str) -> str:
    normalized: list[str] = []
    in_string = False
    string_is_key = False
    escaped = False
    for char in value:
        if in_string:
            if escaped:
                normalized.append(char)
                escaped = False
                continue
            if char == "\\":
                normalized.append(char)
                escaped = True
                continue
            if char in {'"', "＂"}:
                normalized.append('"')
                in_string = False
                string_is_key = False
                continue
            normalized.append(unicodedata.normalize("NFKC", char) if string_is_key else char)
            continue

        compatible = unicodedata.normalize("NFKC", char)
        normalized.append(compatible)
        if compatible == '"':
            previous = next(
                (item for item in reversed(normalized[:-1]) if not item.isspace()),
                "",
            )
            in_string = True
            string_is_key = previous in {"{", ","}
    return "".join(normalized)


def _repair_structural_smart_quotes(value: str) -> str:
    repaired = re.sub(
        r'("(?:target_player_id|speech|decision_note)"\s*:\s*)“',
        r'\1"',
        value,
    )
    return re.sub(r"”(?=\s*[,}])", '"', repaired)


_PARSED_OBJECT_UNSET = object()


def _decision_fields(
    raw: str,
    output_contract: Any,
    *,
    parsed_object: ParsedDecisionObject | None | object = _PARSED_OBJECT_UNSET,
) -> tuple[str | None, str | None, str | None, bool | None]:
    if not isinstance(output_contract, dict):
        raise V2QualityError("model_decision_contract_missing")
    kind = output_contract.get("kind")
    if kind == "boolean":
        field = output_contract.get("field")
        if not isinstance(field, str) or not field.strip():
            raise V2QualityError("model_decision_contract_invalid")
        try:
            value = _parsed_decision_value(
                raw,
                output_contract=output_contract,
                parsed_object=parsed_object,
            )
        except V2QualityError as exc:
            if not _decision_parse_can_fallback(exc):
                raise
            boolean_value = _boolean_fragment(raw, field=field)
            if boolean_value is None:
                raise
            speech = _fallback_speech(
                raw,
                output_contract=output_contract,
                boolean_value=boolean_value,
            )
        else:
            return _decision_fields_from_object(
                value,
                output_contract,
            )
        return None, speech, field, boolean_value
    if kind == "target":
        try:
            value = _parsed_decision_value(
                raw,
                output_contract=output_contract,
                parsed_object=parsed_object,
            )
        except V2QualityError as exc:
            if not _decision_parse_can_fallback(exc):
                raise
            return (
                _target_fragment(raw),
                _fallback_speech(raw, output_contract=output_contract),
                None,
                None,
            )
        return _decision_fields_from_object(value, output_contract)
    if kind == "speech":
        try:
            value = _parsed_decision_value(
                raw,
                output_contract=output_contract,
                parsed_object=parsed_object,
            )
        except V2QualityError as exc:
            if not _decision_parse_can_fallback(exc):
                raise
            speech = _fallback_speech(raw, output_contract=output_contract)
        else:
            return _decision_fields_from_object(value, output_contract)
        return None, speech, None, None
    raise V2QualityError("model_decision_contract_invalid")


def _parsed_decision_value(
    raw: str,
    *,
    output_contract: dict[str, Any],
    parsed_object: ParsedDecisionObject | None | object,
) -> dict[str, Any]:
    if parsed_object is _PARSED_OBJECT_UNSET:
        return _parse_decision_object(raw, output_contract=output_contract).value
    if parsed_object is None:
        raise V2QualityError("model_decision_invalid_json")
    assert isinstance(parsed_object, ParsedDecisionObject)
    return parsed_object.value


def _decision_fields_from_object(
    value: dict[str, Any],
    output_contract: dict[str, Any],
) -> tuple[str | None, str | None, str | None, bool | None]:
    payload = _decision_payload(value, output_contract=output_contract)
    kind = output_contract.get("kind")
    if kind == "boolean":
        field = output_contract.get("field")
        if not isinstance(field, str) or not field.strip():
            raise V2QualityError("model_decision_contract_invalid")
        boolean_value = payload.get(field)
        if not isinstance(boolean_value, bool):
            raise V2QualityError("model_decision_invalid_boolean")
        speech = _speech_field(
            payload.get("speech"),
            output_contract=output_contract,
            boolean_value=boolean_value,
        )
        return None, speech, field, boolean_value
    if kind == "target":
        target_player_id = payload.get("target_player_id")
        if target_player_id is not None and not isinstance(target_player_id, str):
            raise V2QualityError("model_decision_invalid_target")
        speech = _speech_field(
            payload.get("speech"),
            output_contract=output_contract,
        )
        return (
            target_player_id.strip() if target_player_id else None,
            speech,
            None,
            None,
        )
    if kind == "speech":
        speech = _speech_field(
            payload.get("speech"),
            output_contract=output_contract,
        )
        return None, speech, None, None
    raise V2QualityError("model_decision_contract_invalid")


def _decision_repair_kind(
    raw: str,
    output_contract: Any,
    *,
    parsed_object: ParsedDecisionObject | None | object = _PARSED_OBJECT_UNSET,
) -> str | None:
    if not isinstance(output_contract, dict):
        return None
    if output_contract.get("kind") not in {"boolean", "speech", "target"}:
        return None
    if parsed_object is _PARSED_OBJECT_UNSET:
        try:
            parsed_object = _parse_decision_object(raw, output_contract=output_contract)
        except V2QualityError as exc:
            if not _decision_parse_can_fallback(exc):
                raise
            parsed_object = None
    if parsed_object is None:
        stripped = _strip_json_fence(raw)
        if _looks_like_structured_speech(stripped):
            return "structured_speech_fragment_recovered"
        return "plain_text_speech_fallback"
    assert isinstance(parsed_object, ParsedDecisionObject)
    if parsed_object.repair_kind is not None:
        return parsed_object.repair_kind
    value = parsed_object.value
    if _repair_single_trailing_brace(raw) != raw:
        return "single_trailing_brace_removed"
    if isinstance(value.get("output"), dict) or isinstance(value.get("decision"), dict):
        return "nested_output_object_recovered"
    if {"schema_version", "action_id", "action_type"}.intersection(value):
        return "metadata_wrapper_recovered"
    allowed_fields = _expected_output_fields(output_contract)
    if allowed_fields.intersection(value) and set(value) - allowed_fields:
        return "extra_output_fields_ignored"
    return None


def _decision_note(
    raw: str,
    output_contract: Any,
    *,
    parsed_object: ParsedDecisionObject | None | object = _PARSED_OBJECT_UNSET,
) -> str | None:
    if not isinstance(output_contract, dict):
        return None
    note_contract = output_contract.get("decision_note")
    if not isinstance(note_contract, dict) or note_contract.get("mode") == "none":
        return None
    if note_contract.get("mode") != "optional":
        raise V2QualityError("model_decision_contract_invalid")
    try:
        value = _parsed_decision_value(
            raw,
            output_contract=output_contract,
            parsed_object=parsed_object,
        )
    except V2QualityError as exc:
        if not _decision_parse_can_fallback(exc):
            raise
        return None
    return _decision_note_from_object(value, output_contract)


def _decision_note_from_object(
    value: dict[str, Any],
    output_contract: dict[str, Any],
) -> str | None:
    note_contract = output_contract.get("decision_note")
    if not isinstance(note_contract, dict) or note_contract.get("mode") == "none":
        return None
    if note_contract.get("mode") != "optional":
        raise V2QualityError("model_decision_contract_invalid")
    note_value = _decision_payload(
        value,
        output_contract=output_contract,
    ).get("decision_note")
    if note_value is None:
        return None
    if not isinstance(note_value, str):
        raise V2QualityError("model_decision_invalid_note")
    note = note_value.strip()
    if not note:
        return None
    return note


def _speech_field(
    value: Any,
    *,
    output_contract: dict[str, Any],
    boolean_value: bool | None = None,
) -> str | None:
    speech_contract = output_contract.get("speech")
    if not isinstance(speech_contract, dict):
        raise V2QualityError("model_decision_contract_invalid")
    mode = speech_contract.get("mode")
    if mode == "forbidden":
        if value is None or value == "":
            return None
        if not isinstance(value, str):
            raise V2QualityError("model_decision_invalid_speech")
        speech = value.strip()
        if not speech:
            return None
        if _looks_like_structured_speech(speech):
            raise V2QualityError("model_decision_structured_speech_leak")
        # Parsing must preserve a provider's extra speech so the action layer can
        # audit and normalize the contract violation without retrying the model.
        return speech
    if mode == "required_if_true" and boolean_value is False:
        if value is not None and not isinstance(value, str):
            raise V2QualityError("model_decision_invalid_speech")
        return None
    required = mode == "required" or (mode == "required_if_true" and boolean_value is True)
    if mode not in {"required", "optional", "required_if_true"}:
        raise V2QualityError("model_decision_contract_invalid")
    if value is None:
        if required:
            raise V2QualityError("model_decision_invalid_speech")
        return None
    if not isinstance(value, str):
        raise V2QualityError("model_decision_invalid_speech")
    speech = value.strip()
    if speech:
        if _looks_like_structured_speech(speech):
            raise V2QualityError("model_decision_structured_speech_leak")
        return speech
    if required:
        raise V2QualityError("model_decision_invalid_speech")
    return None


def _fallback_speech(
    raw: str,
    *,
    output_contract: dict[str, Any],
    boolean_value: bool | None = None,
) -> str | None:
    stripped = _strip_json_fence(raw)
    if _looks_like_context_echo(stripped):
        raise V2QualityError("model_decision_structured_speech_leak")
    if _looks_like_structured_speech(stripped):
        recovered = _json_string_fragment(stripped, field="speech")
        if recovered is None or _looks_like_structured_speech(recovered):
            raise V2QualityError("model_decision_structured_speech_leak")
        return _speech_field(
            recovered,
            output_contract=output_contract,
            boolean_value=boolean_value,
        )
    return _speech_field(
        raw,
        output_contract=output_contract,
        boolean_value=boolean_value,
    )


def _boolean_fragment(raw: str, *, field: str) -> bool | None:
    stripped = _strip_json_fence(raw)
    if _looks_like_context_echo(stripped):
        return None
    match = re.search(
        rf'"{re.escape(field)}"\s*:\s*(true|false)(?=\s*[,}}])',
        stripped,
        flags=re.IGNORECASE,
    )
    if match is None:
        return None
    return match.group(1).lower() == "true"


def _target_fragment(raw: str) -> str | None:
    stripped = _strip_json_fence(raw)
    if _looks_like_context_echo(stripped):
        return None
    match = re.search(
        r'"target_player_id"\s*:\s*"([^"\\]+)"',
        stripped,
    )
    if match is None:
        return None
    target = match.group(1).strip()
    return target or None


def _strip_json_fence(raw: str) -> str:
    stripped = raw.strip()
    if not stripped.startswith("```"):
        return stripped
    first_newline = stripped.find("\n")
    if first_newline < 0:
        return stripped
    stripped = stripped[first_newline + 1 :]
    if stripped.rstrip().endswith("```"):
        stripped = stripped.rstrip()[:-3]
    return stripped.strip()


def _looks_like_context_echo(value: str) -> bool:
    prefix = value[:1_500]
    return any(
        marker in prefix
        for marker in (
            '"output_contract"',
            '"response"',
            '"known_events"',
            '"model_context_schema_version"',
            '"hard_rules"',
            '"public_state"',
            '"history"',
            '"self"',
            '"public_rule_contract"',
            '"public_match_state"',
            '"actor_private"',
            '"private_authoritative_facts"',
            '"self_identity"',
            '"ability_runtime_state"',
            '"current_action_effect"',
            '"private_judge_facts"',
            '"public_judge_facts"',
            '"canonical_public_timeline"',
            '"public_event_counters"',
            '"current_information_summary"',
            '"public_statements"',
        )
    )


def _decision_payload(
    value: dict[str, Any],
    *,
    output_contract: dict[str, Any],
) -> dict[str, Any]:
    output = value.get("output")
    if isinstance(output, dict):
        return output
    decision = value.get("decision")
    if isinstance(decision, dict):
        return decision
    if _expected_output_fields(output_contract).intersection(value):
        return value
    if _is_context_echo_object(value):
        raise V2QualityError("model_decision_structured_speech_leak")
    return value


def _expected_output_fields(output_contract: dict[str, Any]) -> set[str]:
    kind = output_contract.get("kind")
    if kind == "boolean":
        field = output_contract.get("field")
        fields = {"speech", field} if isinstance(field, str) else {"speech"}
        return _with_decision_note(fields, output_contract)
    if kind == "target":
        return _with_decision_note({"target_player_id", "speech"}, output_contract)
    if kind == "speech":
        return _with_decision_note({"speech"}, output_contract)
    return set()


def _with_decision_note(
    fields: set[str],
    output_contract: dict[str, Any],
) -> set[str]:
    note = output_contract.get("decision_note")
    if isinstance(note, dict) and note.get("mode") == "optional":
        return {*fields, "decision_note"}
    return fields


def _is_context_echo_object(value: dict[str, Any]) -> bool:
    context_fields = {
        "output_contract",
        "response",
        "known_events",
        "model_context_schema_version",
        "hard_rules",
        "public_state",
        "history",
        "self",
        "public_rule_contract",
        "public_match_state",
        "actor_private",
        "private_authoritative_facts",
        "self_identity",
        "ability_runtime_state",
        "current_action_effect",
        "private_judge_facts",
        "public_judge_facts",
        "canonical_public_timeline",
        "public_event_counters",
        "current_information_summary",
        "public_statements",
    }
    return any(
        field in value and isinstance(value[field], (dict, list)) for field in context_fields
    )


def _looks_like_structured_speech(value: str) -> bool:
    stripped = value.lstrip()
    return stripped.startswith(("{", "[", "```json", "```JSON"))


def _json_string_fragment(raw: str, *, field: str) -> str | None:
    match = re.search(rf'"{re.escape(field)}"\s*:\s*"', raw)
    if match is None:
        return None
    value_start = match.end()
    chars: list[str] = []
    index = value_start
    while index < len(raw):
        char = raw[index]
        if char == "\\":
            decoded, next_index = _decode_json_escape(raw, index)
            chars.append(decoded)
            index = next_index
            continue
        if char == '"':
            tail = raw[index + 1 :]
            if re.match(r"\s*(?:[,}])", tail) or not tail.strip():
                break
            chars.append(char)
            index += 1
            continue
        chars.append(char)
        index += 1
    recovered = "".join(chars).strip()
    return recovered or None


def _decode_json_escape(raw: str, slash_index: int) -> tuple[str, int]:
    if slash_index + 1 >= len(raw):
        return "\\", slash_index + 1
    escape = raw[slash_index + 1]
    simple = {
        '"': '"',
        "\\": "\\",
        "/": "/",
        "b": "\b",
        "f": "\f",
        "n": "\n",
        "r": "\r",
        "t": "\t",
    }
    if escape in simple:
        return simple[escape], slash_index + 2
    if escape == "u" and slash_index + 6 <= len(raw):
        code = raw[slash_index + 2 : slash_index + 6]
        if re.fullmatch(r"[0-9a-fA-F]{4}", code):
            return chr(int(code, 16)), slash_index + 6
    return escape, slash_index + 2


def _required_speech(value: Any, *, error_code: str) -> str:
    if not isinstance(value, str):
        raise V2QualityError(error_code)
    speech = value.strip()
    if not speech:
        raise V2QualityError(error_code)
    return speech
