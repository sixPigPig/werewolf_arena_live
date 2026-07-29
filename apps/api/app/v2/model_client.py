from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
import json
import re
import time
from typing import Any
import unicodedata

import httpx

from app.model_catalog.defaults import (
    DEFAULT_NON_THINKING_MAX_TOKENS,
    DEFAULT_THINKING_MAX_TOKENS,
)


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
        elapsed_ms: int | None = None,
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
        self.elapsed_ms = elapsed_ms


class V2QualityError(RuntimeError):
    def __init__(self, code: str, *, raw_response: str | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.raw_response = raw_response


@dataclass(frozen=True)
class V2ModelDecision:
    target_player_id: str | None
    speech: str | None
    provider_request_id: str
    first_token_ms: int
    completed_ms: int
    raw_response: str | None = None
    boolean_field: str | None = None
    boolean_value: bool | None = None
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


@dataclass(frozen=True)
class _ProviderEvent:
    candidate_id: str | None = None
    text_delta: str | None = None
    reasoning_delta: str | None = None
    failed: bool = False
    finish_reason: str | None = None


_RETRYABLE_HTTP_STATUSES = frozenset({502, 503, 504})
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


class V2ModelClient:
    def __init__(
        self,
        *,
        agent_plan_api_key: str,
        agent_plan_base_url: str,
        deepseek_api_key: str,
        deepseek_base_url: str,
        first_token_seconds: float,
        total_seconds: float,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._routes = {
            "agent_plan": _ProviderRoute(
                api_key=agent_plan_api_key.strip(),
                url=f"{agent_plan_base_url.rstrip('/')}/responses",
                protocol="responses",
            ),
            "deepseek": _ProviderRoute(
                api_key=deepseek_api_key.strip(),
                url=f"{deepseek_base_url.rstrip('/')}/chat/completions",
                protocol="chat_completions",
            ),
        }
        self._first_token_seconds = first_token_seconds
        self._total_seconds = total_seconds
        self._transport = transport

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
        raw, provider_request_id, first_token_ms, completed_ms = await self._stream_text(
            action_context=action_context,
            attempt_id=attempt_id,
            max_output_tokens=None,
            decision=True,
            target=target,
            check_cancellation=check_cancellation,
        )
        output_contract = action_context.get("output_contract")
        repair_kind = _decision_repair_kind(raw, output_contract)
        try:
            (
                target_player_id,
                normalized_speech,
                boolean_field,
                boolean_value,
            ) = _decision_fields(raw, output_contract)
        except V2QualityError as exc:
            raise V2QualityError(exc.code, raw_response=raw) from exc
        return V2ModelDecision(
            target_player_id=target_player_id,
            speech=normalized_speech,
            provider_request_id=provider_request_id,
            first_token_ms=first_token_ms,
            completed_ms=completed_ms,
            raw_response=raw,
            boolean_field=boolean_field,
            boolean_value=boolean_value,
            repair_kind=repair_kind,
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
    ) -> tuple[str, str, int, int]:
        _check(check_cancellation)
        route = self._routes[target.provider]
        started = time.monotonic()
        first_token_at: float | None = None
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
        timeout = httpx.Timeout(connect=8.0, read=None, write=8.0, pool=8.0)
        phase_timeout = asyncio.timeout_at(started + self._first_token_seconds)
        try:
            async with phase_timeout:
                async with httpx.AsyncClient(
                    timeout=timeout,
                    transport=self._transport,
                ) as client:
                    async with client.stream(
                        "POST",
                        route.url,
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
                        if response.status_code >= 400:
                            await response.aread()
                            raise V2ModelError(
                                f"model_http_{response.status_code}",
                                retryable=response.status_code in _RETRYABLE_HTTP_STATUSES,
                                failure_stage="http_response",
                                http_status=response.status_code,
                                provider_request_id=provider_request_id,
                                response_headers_seen=True,
                                elapsed_ms=round((time.monotonic() - started) * 1000),
                            )
                        lines = response.aiter_lines().__aiter__()
                        while True:
                            _check(check_cancellation)
                            elapsed = time.monotonic() - started
                            deadline = (
                                self._first_token_seconds
                                if first_token_at is None
                                else self._total_seconds
                            )
                            remaining = deadline - elapsed
                            if remaining <= 0:
                                raise _model_timeout_error(
                                    started=started,
                                    first_token_at=first_token_at,
                                    provider_request_id=provider_request_id,
                                    response_headers_seen=response_headers_seen,
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
                                raise _model_timeout_error(
                                    started=started,
                                    first_token_at=first_token_at,
                                    provider_request_id=provider_request_id,
                                    response_headers_seen=response_headers_seen,
                                ) from exc
                            event = _sse_data(line)
                            if event is None:
                                continue
                            provider_event = _provider_event(
                                event,
                                protocol=route.protocol,
                            )
                            if provider_event.candidate_id:
                                provider_request_id = provider_event.candidate_id
                            if provider_event.failed:
                                raise V2ModelError(
                                    "model_provider_failed",
                                    failure_stage=(
                                        "first_token"
                                        if first_token_at is None
                                        else "stream"
                                    ),
                                    provider_request_id=provider_request_id,
                                    first_token_seen=first_token_at is not None,
                                    response_headers_seen=True,
                                    elapsed_ms=round(
                                        (time.monotonic() - started) * 1000
                                    ),
                                )
                            if provider_event.finish_reason:
                                finish_reason = provider_event.finish_reason
                            if provider_event.reasoning_delta:
                                reasoning_seen = True
                                if first_token_at is None:
                                    first_token_at = time.monotonic()
                                    phase_timeout.reschedule(
                                        started + self._total_seconds
                                    )
                            if provider_event.text_delta:
                                if first_token_at is None:
                                    first_token_at = time.monotonic()
                                    phase_timeout.reschedule(
                                        started + self._total_seconds
                                    )
                                text += provider_event.text_delta
        except V2ModelError:
            raise
        except TimeoutError as exc:
            raise _model_timeout_error(
                started=started,
                first_token_at=first_token_at,
                provider_request_id=provider_request_id,
                response_headers_seen=response_headers_seen,
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
                elapsed_ms=round((time.monotonic() - started) * 1000),
            ) from exc
        if not text.strip():
            if finish_reason in {"length", "max_output_tokens"}:
                raise V2ModelError("model_output_budget_exhausted")
            if first_token_at is None:
                raise V2ModelError("model_empty_stream")
            if reasoning_seen:
                raise V2ModelError("model_empty_stream")
        if first_token_at is None:
            raise V2ModelError("model_empty_stream")
        completed = time.monotonic()
        return (
            text.strip(),
            provider_request_id,
            round((first_token_at - started) * 1000),
            round((completed - started) * 1000),
        )


def _model_timeout_error(
    *,
    started: float,
    first_token_at: float | None,
    provider_request_id: str,
    response_headers_seen: bool,
) -> V2ModelError:
    before_first_token = first_token_at is None
    return V2ModelError(
        "model_first_token_timeout" if before_first_token else "model_total_timeout",
        retryable=True,
        failure_stage=(
            "response_headers"
            if not response_headers_seen
            else ("first_token" if before_first_token else "stream")
        ),
        provider_request_id=provider_request_id,
        first_token_seen=not before_first_token,
        response_headers_seen=response_headers_seen,
        elapsed_ms=round((time.monotonic() - started) * 1000),
    )


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
    started = time.monotonic()
    try:
        while True:
            remaining = timeout - (time.monotonic() - started)
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
    output_contract = action_context.get("output_contract")
    if not isinstance(output_contract, dict):
        raise V2ModelError("model_decision_contract_missing")
    kind = output_contract.get("kind")
    speech_instruction = _speech_output_instruction(output_contract)
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
            f"{speech_instruction}"
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
            + f"{speech_instruction}"
        )
    elif kind == "speech":
        output_instruction = (
            "输出一个 JSON 对象，只使用 speech 表示本次发言。"
            f"{speech_instruction}"
            "不要输出 target_player_id。"
        )
    else:
        raise V2ModelError("model_decision_contract_invalid")
    return [
        {
            "role": "system",
            "content": [
                {
                    "type": "input_text",
                    "text": (
                        "你正在扮演一名狼人杀玩家。hard_rules、self 中的法官私密信息"
                        "和 public_state 是权威事实；history 只是玩家公开说法，可能真实、"
                        "撒谎或判断错误；history.source_rules 规定发言来源和时间因果边界，"
                        "必须遵守。history.timeline 按 record_seq 保留全部公开发言，"
                        "annotations、questions 和 relations 只引用这条时间线，不是"
                        "额外事实。你可以自主判断、伪装身份和制定策略，但不得使用未提供"
                        "的私密信息，也不要把玩家说法当成法官确认。"
                        f"{output_instruction}"
                        "只能用“N号”称呼玩家，不得猜测或生成玩家姓名。"
                    ),
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


def _speech_output_instruction(output_contract: dict[str, Any]) -> str:
    speech = output_contract.get("speech")
    speech = speech if isinstance(speech, dict) else {}
    mode = speech.get("mode")
    if mode == "required":
        return "speech 必须是准备直接播报的非空自然中文，可以包含多句话。"
    if mode == "optional":
        return "speech 可省略或为 null；若提供，必须是可直接播报的非空自然中文。"
    if mode == "forbidden":
        return "不得输出 speech。"
    if mode == "required_if_true":
        return (
            "决定字段为 true 时 speech 必须是可直接播报的非空自然中文；"
            "为 false 时不要发言，speech 应省略或为 null。"
        )
    raise V2ModelError("model_decision_contract_invalid")


def _sse_data(line: str) -> dict[str, Any] | None:
    if not line.startswith("data:"):
        return None
    raw = line[5:].strip()
    if not raw or raw == "[DONE]":
        return None
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise V2ModelError("model_invalid_sse") from exc
    if not isinstance(value, dict):
        raise V2ModelError("model_invalid_event")
    return value


def _decision_object(raw: str) -> dict[str, Any]:
    candidates = [raw.strip()]
    start = raw.find("{")
    end = raw.rfind("}")
    if 0 <= start < end:
        candidates.append(raw[start : end + 1])
    for candidate in candidates:
        delimiter_repaired = _repair_compatibility_key_delimiter(candidate)
        normalized = _normalize_json_syntax_nfkc(delimiter_repaired)
        normalized_repaired = _repair_compatibility_key_delimiter(normalized)
        serialized_candidates = (
            candidate,
            _repair_structural_smart_quotes(candidate),
            normalized,
            _repair_structural_smart_quotes(normalized),
            normalized_repaired,
            _repair_structural_smart_quotes(normalized_repaired),
        )
        for serialized in dict.fromkeys(serialized_candidates):
            try:
                value = json.loads(serialized)
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                return value
            raise V2QualityError("model_decision_invalid_shape")
    raise V2QualityError("model_decision_invalid_json")


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
        r'("(?:target_player_id|speech)"\s*:\s*)“',
        r'\1"',
        value,
    )
    return re.sub(r"”(?=\s*[,}])", '"', repaired)


def _decision_fields(
    raw: str,
    output_contract: Any,
) -> tuple[str | None, str | None, str | None, bool | None]:
    if not isinstance(output_contract, dict):
        raise V2QualityError("model_decision_contract_missing")
    kind = output_contract.get("kind")
    if kind == "boolean":
        field = output_contract.get("field")
        if not isinstance(field, str) or not field.strip():
            raise V2QualityError("model_decision_contract_invalid")
        try:
            value = _decision_payload(
                _decision_object(raw),
                output_contract=output_contract,
            )
        except V2QualityError:
            boolean_value = _boolean_fragment(raw, field=field)
            if boolean_value is None:
                raise
            speech = _fallback_speech(
                raw,
                output_contract=output_contract,
                boolean_value=boolean_value,
            )
        else:
            boolean_value = value.get(field)
            if not isinstance(boolean_value, bool):
                raise V2QualityError("model_decision_invalid_boolean")
            speech = _speech_field(
                value.get("speech"),
                output_contract=output_contract,
                boolean_value=boolean_value,
            )
        return None, speech, field, boolean_value
    if kind == "target":
        try:
            value = _decision_object(raw)
        except V2QualityError:
            return (
                _target_fragment(raw),
                _fallback_speech(raw, output_contract=output_contract),
                None,
                None,
            )
        value = _decision_payload(value, output_contract=output_contract)
        target_player_id = value.get("target_player_id")
        if target_player_id is not None and not (
            isinstance(target_player_id, str) and target_player_id.strip()
        ):
            target_player_id = None
        speech = _speech_field(
            value.get("speech"),
            output_contract=output_contract,
        )
        return (
            target_player_id.strip() if target_player_id else None,
            speech,
            None,
            None,
        )
    if kind == "speech":
        try:
            value = _decision_object(raw)
        except V2QualityError:
            speech = _fallback_speech(raw, output_contract=output_contract)
        else:
            value = _decision_payload(value, output_contract=output_contract)
            speech = _speech_field(
                value.get("speech"),
                output_contract=output_contract,
            )
        return None, speech, None, None
    raise V2QualityError("model_decision_contract_invalid")


def _decision_repair_kind(raw: str, output_contract: Any) -> str | None:
    if not isinstance(output_contract, dict):
        return None
    if output_contract.get("kind") not in {"boolean", "speech", "target"}:
        return None
    try:
        value = _decision_object(raw)
    except V2QualityError:
        stripped = _strip_json_fence(raw)
        if _looks_like_structured_speech(stripped):
            return "structured_speech_fragment_recovered"
        return "plain_text_speech_fallback"
    if isinstance(value.get("output"), dict) or isinstance(value.get("decision"), dict):
        return "nested_output_object_recovered"
    if {"schema_version", "action_id", "action_type"}.intersection(value):
        return "metadata_wrapper_recovered"
    allowed_fields = _expected_output_fields(output_contract)
    if allowed_fields.intersection(value) and set(value) - allowed_fields:
        return "extra_output_fields_ignored"
    return None


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
        raise V2QualityError("model_decision_unexpected_speech")
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
        return {"speech", field} if isinstance(field, str) else {"speech"}
    if kind == "target":
        return {"target_player_id", "speech"}
    if kind == "speech":
        return {"speech"}
    return set()


def _is_context_echo_object(value: dict[str, Any]) -> bool:
    context_fields = {
        "output_contract",
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
