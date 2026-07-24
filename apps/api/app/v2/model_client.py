from __future__ import annotations

import asyncio
from dataclasses import dataclass
import json
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
class V2ModelSpeech:
    text: str
    provider_request_id: str
    first_token_ms: int
    sentence_ms: int
    raw_response: str | None = None


@dataclass(frozen=True)
class V2ModelDecision:
    target_player_id: str | None
    speech: str
    provider_request_id: str
    first_token_ms: int
    completed_ms: int
    raw_response: str | None = None


class V2ModelClient:
    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model_id: str,
        first_token_seconds: float,
        total_seconds: float,
    ) -> None:
        self._api_key = api_key.strip()
        self._url = f"{base_url.rstrip('/')}/responses"
        self._model_id = model_id.strip()
        self._first_token_seconds = first_token_seconds
        self._total_seconds = total_seconds

    def resolve_model_id(self, model_id: str | None = None) -> str:
        return (model_id or self._model_id).strip()

    def build_request_payload(
        self,
        *,
        action_context: dict[str, Any],
        decision: bool,
        model_id: str | None = None,
    ) -> dict[str, Any]:
        return build_model_request_payload(
            action_context,
            decision=decision,
            model_id=self.resolve_model_id(model_id),
        )

    async def generate_judge_sentence(
        self,
        *,
        action_context: dict[str, Any],
        attempt_id: str,
        model_id: str | None = None,
    ) -> V2ModelSpeech:
        raw, provider_request_id, first_token_ms, completed_ms = await self._stream_text(
            action_context=action_context,
            attempt_id=attempt_id,
            max_output_tokens=256,
            input_builder=_model_input,
            model_id=model_id,
        )
        return V2ModelSpeech(
            text=_required_speech(raw, error_code="model_empty_speech"),
            provider_request_id=provider_request_id,
            first_token_ms=first_token_ms,
            sentence_ms=completed_ms,
            raw_response=raw,
        )

    async def generate_action_decision(
        self,
        *,
        action_context: dict[str, Any],
        attempt_id: str,
        model_id: str | None = None,
    ) -> V2ModelDecision:
        raw, provider_request_id, first_token_ms, completed_ms = await self._stream_text(
            action_context=action_context,
            attempt_id=attempt_id,
            max_output_tokens=256,
            input_builder=_decision_model_input,
            model_id=model_id,
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
        input_builder: Any,
        model_id: str | None,
    ) -> tuple[str, str, int, int]:
        selected_model_id = self.resolve_model_id(model_id)
        if not self._api_key or not selected_model_id:
            raise V2ModelError("model_not_configured")
        started = time.monotonic()
        first_token_at: float | None = None
        provider_request_id = attempt_id
        text = ""
        payload = build_model_request_payload(
            action_context,
            decision=input_builder is _decision_model_input,
            model_id=selected_model_id,
            max_output_tokens=max_output_tokens,
        )
        timeout = httpx.Timeout(connect=8.0, read=None, write=8.0, pool=8.0)
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                async with client.stream(
                    "POST",
                    self._url,
                    headers={
                        "Authorization": f"Bearer {self._api_key}",
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
                            line = await asyncio.wait_for(anext(lines), timeout=remaining)
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
                        response_object = event.get("response")
                        if isinstance(response_object, dict):
                            candidate_id = response_object.get("id")
                            if isinstance(candidate_id, str) and candidate_id:
                                provider_request_id = candidate_id
                        if event.get("type") == "response.output_text.delta":
                            delta = event.get("delta")
                            if not isinstance(delta, str) or not delta:
                                continue
                            if first_token_at is None:
                                first_token_at = time.monotonic()
                            text += delta
                        if event.get("type") in {"response.failed", "error"}:
                            raise V2ModelError("model_provider_failed")
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


def build_model_request_payload(
    action_context: dict[str, Any],
    *,
    decision: bool,
    model_id: str,
    max_output_tokens: int = 256,
) -> dict[str, Any]:
    return {
        "model": model_id,
        "stream": True,
        "max_output_tokens": max_output_tokens,
        "thinking": {"type": "disabled"},
        "input": (
            _decision_model_input(action_context)
            if decision
            else _model_input(action_context)
        ),
    }


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
                        "target_player_id 必须是候选列表中的 player_id；无需选择目标或"
                        "允许放弃时可为 null。严格遵守 output_contract.target_policy；"
                        "speech 是准备直接播报的自然中文，可以包含多句话。"
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
        try:
            value = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
        raise V2QualityError("model_decision_invalid_shape")
    raise V2QualityError("model_decision_invalid_json")


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
