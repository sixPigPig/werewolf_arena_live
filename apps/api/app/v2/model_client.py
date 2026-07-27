from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
import json
import re
import time
from typing import Any

import httpx


class V2ModelError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class V2QualityError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class V2ModelDecision:
    target_player_id: str | None
    speech: str
    provider_request_id: str
    first_token_ms: int
    completed_ms: int
    raw_response: str | None = None


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
            max_output_tokens=256,
            decision=True,
            target=target,
            check_cancellation=check_cancellation,
        )
        target_player_id, normalized_speech = _decision_fields(raw)
        return V2ModelDecision(
            target_player_id=target_player_id,
            speech=normalized_speech,
            provider_request_id=provider_request_id,
            first_token_ms=first_token_ms,
            completed_ms=completed_ms,
            raw_response=raw,
        )

    async def _stream_text(
        self,
        *,
        action_context: dict[str, Any],
        attempt_id: str,
        max_output_tokens: int,
        decision: bool,
        target: V2ModelTarget,
        check_cancellation: Callable[[], None] | None,
    ) -> tuple[str, str, int, int]:
        _check(check_cancellation)
        route = self._routes[target.provider]
        started = time.monotonic()
        first_token_at: float | None = None
        provider_request_id = attempt_id
        text = ""
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
        try:
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
                    if response.status_code >= 400:
                        await response.aread()
                        raise V2ModelError(f"model_http_{response.status_code}")
                    provider_request_id = (
                        response.headers.get("x-request-id")
                        or response.headers.get("x-tt-logid")
                        or attempt_id
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
                            code = (
                                "model_first_token_timeout"
                                if first_token_at is None
                                else "model_total_timeout"
                            )
                            raise V2ModelError(code)
                        try:
                            line = await _next_with_cancellation(
                                lines,
                                timeout=remaining,
                                check_cancellation=check_cancellation,
                            )
                        except StopAsyncIteration:
                            break
                        except TimeoutError as exc:
                            code = (
                                "model_first_token_timeout"
                                if first_token_at is None
                                else "model_total_timeout"
                            )
                            raise V2ModelError(code) from exc
                        event = _sse_data(line)
                        if event is None:
                            continue
                        candidate_id, delta, failed = _provider_event(
                            event,
                            protocol=route.protocol,
                        )
                        if candidate_id:
                            provider_request_id = candidate_id
                        if failed:
                            raise V2ModelError("model_provider_failed")
                        if delta:
                            if first_token_at is None:
                                first_token_at = time.monotonic()
                            text += delta
        except V2ModelError:
            raise
        except (httpx.HTTPError, OSError) as exc:
            raise V2ModelError("model_transport_failed") from exc
        if first_token_at is None:
            raise V2ModelError("model_empty_stream")
        completed = time.monotonic()
        return (
            text.strip(),
            provider_request_id,
            round((first_token_at - started) * 1000),
            round((completed - started) * 1000),
        )


def _provider_event(
    event: dict[str, Any],
    *,
    protocol: str,
) -> tuple[str | None, str | None, bool]:
    if protocol == "responses":
        response_object = event.get("response")
        candidate_id = (
            response_object.get("id")
            if isinstance(response_object, dict)
            and isinstance(response_object.get("id"), str)
            else None
        )
        delta = (
            event.get("delta")
            if event.get("type") == "response.output_text.delta"
            and isinstance(event.get("delta"), str)
            else None
        )
        return candidate_id, delta, event.get("type") in {"response.failed", "error"}

    candidate_id = event.get("id") if isinstance(event.get("id"), str) else None
    choices = event.get("choices")
    delta: str | None = None
    if isinstance(choices, list) and choices and isinstance(choices[0], dict):
        delta_object = choices[0].get("delta")
        if isinstance(delta_object, dict) and isinstance(delta_object.get("content"), str):
            delta = delta_object["content"]
    return candidate_id, delta, "error" in event


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
    max_output_tokens: int = 256,
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
    max_output_tokens: int = 256,
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


def _effective_max_tokens(parameters: dict[str, Any], requested: int) -> int:
    configured = parameters.get("max_tokens")
    if isinstance(configured, int) and not isinstance(configured, bool):
        return min(configured, requested)
    return requested


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
    return [
        {
            "role": "system",
            "content": [
                {
                    "type": "input_text",
                    "text": (
                        "你正在扮演一名狼人杀玩家。只根据给出的实时动作上下文做决定，"
                        "不得使用未提供的私密信息。输出一个 JSON 对象，其中包含"
                        "target_player_id 和 speech 两个字段。需要选择目标时，"
                        "target_player_id 必须是候选列表中的 seat_N 引用；无需选择目标或"
                        "允许放弃时可为 null。严格遵守 output_contract.target_policy；"
                        "speech 是准备直接播报的自然中文，可以包含多句话。"
                        "只能用“N号”称呼玩家，不得猜测或生成玩家姓名。"
                        "上下文中的 public_rule_contract 是本局冻结的公开规则；"
                        "public_match_state 是法官确认的当前公开存活状态；"
                        "private_authoritative_facts 是当前玩家被法官确认知晓的私有事实；"
                        "authoritative_public_facts 是法官公开确认的事实；"
                        "public_statements 只是玩家说法，可能真实、撒谎或判断错误。"
                        "这些信息只界定当前玩家知道什么，如何判断、是否公开私有事实以及"
                        "采用何种策略均由你自主决定。"
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
        repaired = _repair_structural_smart_quotes(candidate)
        for serialized in dict.fromkeys((candidate, repaired)):
            try:
                value = json.loads(serialized)
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                return value
            raise V2QualityError("model_decision_invalid_shape")
    raise V2QualityError("model_decision_invalid_json")


def _repair_structural_smart_quotes(value: str) -> str:
    repaired = re.sub(
        r'("(?:target_player_id|speech)"\s*:\s*)“',
        r'\1"',
        value,
    )
    return re.sub(r"”(?=\s*[,}])", '"', repaired)


def _decision_fields(raw: str) -> tuple[str | None, str]:
    try:
        value = _decision_object(raw)
    except V2QualityError:
        return None, _required_speech(
            raw,
            error_code="model_decision_invalid_speech",
        )
    target_player_id = value.get("target_player_id")
    if target_player_id is not None and not (
        isinstance(target_player_id, str) and target_player_id.strip()
    ):
        target_player_id = None
    speech = _required_speech(
        value.get("speech"),
        error_code="model_decision_invalid_speech",
    )
    return (target_player_id.strip() if target_player_id else None), speech


def _required_speech(value: Any, *, error_code: str) -> str:
    if not isinstance(value, str):
        raise V2QualityError(error_code)
    speech = value.strip()
    if not speech:
        raise V2QualityError(error_code)
    return speech
