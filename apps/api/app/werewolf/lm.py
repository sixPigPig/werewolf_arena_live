from __future__ import annotations

import json
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

from app.werewolf.prompts_zh import build_prompt
from app.werewolf.streaming import (
    ModelEventContext,
    ModelRequestProgress,
    VisibleJsonFieldExtractor,
    action_visible_stream_field,
    waiting_message_for_action,
)

DEFAULT_RETRIES = 3
STREAM_DELTA_FLUSH_CHARS = 12
STREAM_DELTA_FLUSH_SECONDS = 0.12
PUBLIC_MODEL_FAILURE_MESSAGE = "模型请求失败，正在中止本次行动"


class ModelProvider(Protocol):
    def complete_json(self, *, model: str, prompt: str, temperature: float) -> str:
        pass


@dataclass
class LmLog:
    prompt: str
    raw_response: str
    result: dict[str, Any] | None
    request_id: str | None = None
    invalid_attempts: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        value = {
            "prompt": self.prompt,
            "raw_response": self.raw_response,
            "result": self.result,
        }
        if self.request_id is not None:
            value["request_id"] = self.request_id
        if self.invalid_attempts:
            value["invalid_attempts"] = self.invalid_attempts
        return value


class FakeProvider:
    def __init__(self, responses: list[dict[str, Any] | str]) -> None:
        self.responses = responses
        self.calls = 0

    def complete_json(self, *, model: str, prompt: str, temperature: float) -> str:
        del model, prompt, temperature
        response = self.responses[min(self.calls, len(self.responses) - 1)]
        self.calls += 1
        if isinstance(response, str):
            return response
        return json.dumps(response, ensure_ascii=False)


def generate_action(
    *,
    provider: ModelProvider,
    action: str,
    world_state: dict[str, Any],
    model: str,
    allowed_values: list[Any] | None = None,
    result_key: str | None = None,
    retries: int = DEFAULT_RETRIES,
) -> tuple[Any | None, LmLog]:
    base_prompt, _schema = build_prompt(action, world_state)
    raw_responses: list[str] = []
    invalid_attempts: list[dict[str, Any]] = []
    last_result: dict[str, Any] | None = None
    current_prompt = base_prompt

    for attempt in range(retries):
        if invalid_attempts:
            current_prompt = _prompt_with_invalid_feedback(base_prompt, invalid_attempts[-1])
        raw_response = provider.complete_json(
            model=model,
            prompt=current_prompt,
            temperature=min(1.0, 0.4 + attempt * 0.2),
        )
        raw_responses.append(raw_response)
        try:
            result = parse_json_object(raw_response)
        except ValueError:
            continue

        last_result = result
        value = result.get(result_key) if result_key else result
        normalized_value = _normalize_allowed_value(value, allowed_values)
        if allowed_values is None or normalized_value in allowed_values:
            return normalized_value, LmLog(
                prompt=current_prompt,
                raw_response=raw_response,
                result=result,
                invalid_attempts=invalid_attempts.copy(),
            )
        invalid_attempts.append(
            _invalid_attempt(
                value=normalized_value,
                allowed_values=allowed_values,
                result_key=result_key,
            )
        )

    return None, LmLog(
        prompt=current_prompt,
        raw_response="\n--- retry ---\n".join(raw_responses),
        result=last_result,
        invalid_attempts=invalid_attempts.copy(),
    )


def generate_action_with_events(
    *,
    provider: ModelProvider,
    action: str,
    world_state: dict[str, Any],
    model: str,
    allowed_values: list[Any] | None = None,
    result_key: str | None = None,
    retries: int = DEFAULT_RETRIES,
    event_sink: Any,
    event_context: dict[str, Any],
    request_id_factory: Callable[[], str] | None = None,
    enable_progress_ticks: bool = True,
) -> tuple[Any | None, LmLog]:
    base_prompt, _schema = build_prompt(action, world_state)
    raw_responses: list[str] = []
    invalid_attempts: list[dict[str, Any]] = []
    last_result: dict[str, Any] | None = None
    last_request_id: str | None = None
    current_prompt = base_prompt
    context = ModelEventContext(
        round_number=event_context.get("round_number"),
        phase=event_context.get("phase"),
        actor=event_context.get("actor"),
        action=event_context.get("action"),
    )

    for attempt in range(retries):
        if invalid_attempts:
            current_prompt = _prompt_with_invalid_feedback(base_prompt, invalid_attempts[-1])
        request_id = (
            request_id_factory()
            if request_id_factory is not None
            else f"req_{uuid.uuid4().hex[:12]}"
        )
        last_request_id = request_id
        temperature = min(1.0, 0.4 + attempt * 0.2)
        visible_field = action_visible_stream_field(action)
        waiting_message = waiting_message_for_action(action)
        _publish_model_event(
            event_sink,
            "model_request_started",
            context=context,
            payload={
                "request_id": request_id,
                "model": model,
                "message": waiting_message,
                "stream_field": visible_field,
                "is_public": visible_field is not None,
            },
        )
        progress = ModelRequestProgress(
            event_sink=event_sink,
            context=context,
            request_id=request_id,
            model=model,
            message=waiting_message,
        )
        if enable_progress_ticks:
            progress.start()

        progress_stopped = False
        try:
            raw_response = _complete_json_with_optional_stream(
                provider=provider,
                model=model,
                prompt=current_prompt,
                temperature=temperature,
                action=action,
                event_sink=event_sink,
                context=context,
                request_id=request_id,
                progress=progress,
            )
        except Exception:
            progress.stop()
            progress_stopped = True
            _publish_model_event(
                event_sink,
                "model_request_failed",
                context=context,
                payload={
                    "request_id": request_id,
                    "model": model,
                    "message": PUBLIC_MODEL_FAILURE_MESSAGE,
                },
            )
            raise
        finally:
            if not progress_stopped:
                progress.stop()

        raw_responses.append(raw_response)
        try:
            result = parse_json_object(raw_response)
        except ValueError:
            continue

        last_result = result
        value = result.get(result_key) if result_key else result
        normalized_value = _normalize_allowed_value(value, allowed_values)
        if allowed_values is None or normalized_value in allowed_values:
            return normalized_value, LmLog(
                prompt=current_prompt,
                raw_response=raw_response,
                result=result,
                request_id=request_id,
                invalid_attempts=invalid_attempts.copy(),
            )
        invalid_attempts.append(
            _invalid_attempt(
                value=normalized_value,
                allowed_values=allowed_values,
                result_key=result_key,
            )
        )
        _publish_model_event(
            event_sink,
            "model_retry_scheduled",
            context=context,
            payload={
                "request_id": request_id,
                "model": model,
                "attempt": attempt + 2,
                "invalid_value": normalized_value,
                "allowed_values": allowed_values.copy(),
                "result_key": result_key,
                "message": "模型选择不在候选项中，正在带反馈重试。",
            },
        )

    return None, LmLog(
        prompt=current_prompt,
        raw_response="\n--- retry ---\n".join(raw_responses),
        result=last_result,
        request_id=last_request_id,
        invalid_attempts=invalid_attempts.copy(),
    )


def _complete_json_with_optional_stream(
    *,
    provider: ModelProvider,
    model: str,
    prompt: str,
    temperature: float,
    action: str,
    event_sink: Any,
    context: ModelEventContext,
    request_id: str,
    progress: ModelRequestProgress,
) -> str:
    stream_json = getattr(provider, "stream_json", None)
    if callable(stream_json):
        raw_chunks: list[str] = []
        visible_field = action_visible_stream_field(action)
        extractor = VisibleJsonFieldExtractor(visible_field) if visible_field else None
        pending_visible_text = ""
        last_delta_published_at = time.monotonic()
        try:
            for chunk in stream_json(model=model, prompt=prompt, temperature=temperature):
                raw_chunks.append(chunk)
                if extractor is None or visible_field is None:
                    continue
                raw_response = "".join(raw_chunks)
                visible_text = extractor.update(raw_response)
                if not visible_text:
                    continue
                progress.record_delta()
                pending_visible_text += visible_text
                now = time.monotonic()
                if (
                    len(pending_visible_text) >= STREAM_DELTA_FLUSH_CHARS
                    or now - last_delta_published_at >= STREAM_DELTA_FLUSH_SECONDS
                ):
                    _publish_visible_delta(
                        event_sink,
                        context=context,
                        request_id=request_id,
                        model=model,
                        field=visible_field,
                        visible_text=pending_visible_text,
                    )
                    pending_visible_text = ""
                    last_delta_published_at = now
        except Exception:
            if raw_chunks:
                raise
            return provider.complete_json(model=model, prompt=prompt, temperature=temperature)

        if pending_visible_text and visible_field is not None:
            _publish_visible_delta(
                event_sink,
                context=context,
                request_id=request_id,
                model=model,
                field=visible_field,
                visible_text=pending_visible_text,
            )
        if raw_chunks:
            return "".join(raw_chunks)

    return provider.complete_json(model=model, prompt=prompt, temperature=temperature)


def _publish_visible_delta(
    event_sink: Any,
    *,
    context: ModelEventContext,
    request_id: str,
    model: str,
    field: str,
    visible_text: str,
) -> None:
    _publish_model_event(
        event_sink,
        "model_response_delta",
        context=context,
        payload={
            "request_id": request_id,
            "model": model,
            "delta": visible_text,
            "visible_text": visible_text,
            "field": field,
            "is_public": True,
        },
    )


def _publish_model_event(
    event_sink: Any,
    event_type: str,
    *,
    context: ModelEventContext,
    payload: dict[str, Any],
) -> None:
    event_sink.publish(
        event_type,
        round_number=context.round_number,
        phase=context.phase,
        actor=context.actor,
        action=context.action,
        payload=payload,
    )


def _normalize_allowed_value(value: Any, allowed_values: list[Any] | None) -> Any:
    if allowed_values is None:
        return value
    if value in allowed_values:
        return value
    if all(isinstance(item, str) for item in allowed_values) and value is not None:
        return str(value)
    return value


def _invalid_attempt(
    *,
    value: Any,
    allowed_values: list[Any],
    result_key: str | None,
) -> dict[str, Any]:
    return {
        "value": value,
        "allowed_values": allowed_values.copy(),
        "result_key": result_key or "result",
    }


def _prompt_with_invalid_feedback(
    base_prompt: str,
    invalid_attempt: dict[str, Any],
) -> str:
    allowed_values = "、".join(str(item) for item in invalid_attempt["allowed_values"])
    result_key = str(invalid_attempt["result_key"])
    value = str(invalid_attempt["value"])
    return (
        f"{base_prompt}\n\n"
        "上次输出无效，请修正。\n"
        f"上次输出的 {result_key} 为“{value}”，但该值不在合法候选中。\n"
        f"本次必须从以下候选中选择 {result_key}：{allowed_values}。\n"
        "如果你原本最怀疑的人不在候选中，请在剩余候选中重新排序，或选择合法的放弃/不使用选项。\n"
        "只输出合法 JSON。"
    )


def parse_json_object(raw_response: str) -> dict[str, Any]:
    content = raw_response.strip()
    if content.startswith("```"):
        content = content.strip("`")
        if content.startswith("json"):
            content = content[4:]
        content = content.strip()

    decoder = json.JSONDecoder()
    try:
        parsed, _index = decoder.raw_decode(content)
    except json.JSONDecodeError as exc:
        raise ValueError("Model response was not valid JSON.") from exc

    if not isinstance(parsed, dict):
        raise ValueError("Model response JSON must be an object.")
    return parsed
