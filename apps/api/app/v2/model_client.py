from __future__ import annotations

import asyncio
from dataclasses import dataclass
import json
import re
import time
from typing import Any

import httpx


_SENTENCE_END = re.compile(r"[。！？!?]")
_FORBIDDEN_OUTPUT = re.compile(r"[`#{}\[\]\n\r]")


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

    async def generate_first_sentence(
        self,
        *,
        action_context: dict[str, Any],
        attempt_id: str,
    ) -> V2ModelSpeech:
        if not self._api_key or not self._model_id:
            raise V2ModelError("model_not_configured")
        started = time.monotonic()
        first_token_at: float | None = None
        provider_request_id = attempt_id
        text = ""
        payload = {
            "model": self._model_id,
            "stream": True,
            "max_output_tokens": 96,
            "thinking": {"type": "disabled"},
            "input": _model_input(action_context),
        }
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
                        event_type = event.get("type")
                        response_object = event.get("response")
                        if isinstance(response_object, dict):
                            candidate_id = response_object.get("id")
                            if isinstance(candidate_id, str) and candidate_id:
                                provider_request_id = candidate_id
                        if event_type == "response.output_text.delta":
                            delta = event.get("delta")
                            if not isinstance(delta, str) or not delta:
                                continue
                            if first_token_at is None:
                                first_token_at = time.monotonic()
                            text += delta
                            sentence = _accepted_sentence(text)
                            if sentence is not None:
                                completed = time.monotonic()
                                return V2ModelSpeech(
                                    text=sentence,
                                    provider_request_id=provider_request_id,
                                    first_token_ms=round((first_token_at - started) * 1000),
                                    sentence_ms=round((completed - started) * 1000),
                                )
                        if event_type in {"response.failed", "error"}:
                            raise V2ModelError("model_provider_failed")
        except V2ModelError:
            raise
        except (httpx.HTTPError, OSError) as exc:
            raise V2ModelError("model_transport_failed") from exc
        if first_token_at is None:
            raise V2ModelError("model_empty_stream")
        raise V2QualityError("model_no_complete_sentence")


def _model_input(action_context: dict[str, Any]) -> list[dict[str, Any]]:
    context_json = json.dumps(action_context, ensure_ascii=False, separators=(",", ":"))
    return [
        {
            "role": "system",
            "content": [
                {
                    "type": "input_text",
                    "text": (
                        "你是狼人杀直播法官。只输出一句自然、简短、适合直接播报的中文开场白。"
                        "必须用句号、问号或感叹号结束；不要输出引号、标题、列表、Markdown、"
                        "解释或玩家身份信息。"
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


def _accepted_sentence(text: str) -> str | None:
    match = _SENTENCE_END.search(text)
    if match is None:
        if len(text) > 160:
            raise V2QualityError("model_sentence_too_long")
        return None
    sentence = text[: match.end()].strip()
    if len(sentence) < 6:
        raise V2QualityError("model_sentence_too_short")
    if len(sentence) > 120:
        raise V2QualityError("model_sentence_too_long")
    if _FORBIDDEN_OUTPUT.search(sentence):
        raise V2QualityError("model_sentence_forbidden_format")
    if sentence[0] in "\"'“‘《" or sentence[-1] in "\"'”’》":
        raise V2QualityError("model_sentence_quoted")
    return sentence
