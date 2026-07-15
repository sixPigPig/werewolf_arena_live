from __future__ import annotations

import json
import inspect
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

from app.werewolf.action_choice import normalize_action_choice
from app.werewolf.execution_budget import ModelCallOptions, ModelDeadlineExceeded
from app.werewolf.execution_telemetry import record_model_progress_event
from app.werewolf.prompts_zh import build_prompt
from app.werewolf.streaming import (
    ModelEventContext,
    ModelRequestProgress,
    VisibleJsonFieldExtractor,
    action_visible_stream_field,
    escape_unescaped_json_string_control_chars,
    waiting_message_for_action,
)

DEFAULT_RETRIES = 3
STREAM_DELTA_FLUSH_CHARS = 12
STREAM_DELTA_FLUSH_SECONDS = 0.12
PUBLIC_MODEL_FAILURE_MESSAGE = "模型请求失败，正在中止本次行动"


class EmptyModelResponseError(ValueError):
    """The provider completed successfully but returned no usable content."""


class ModelProvider(Protocol):
    def complete_json(
        self,
        *,
        model: str,
        prompt: str,
        temperature: float,
        call_options: ModelCallOptions | None = None,
    ) -> str:
        pass


@dataclass
class LmLog:
    prompt: str
    raw_response: str
    result: dict[str, Any] | None
    request_id: str | None = None
    invalid_attempts: list[dict[str, Any]] = field(default_factory=list)
    raw_choice: object | None = None
    choice_normalization_kind: str | None = None
    speech_mission: dict[str, object] | None = field(default=None, repr=False)
    speech_quality_report: dict[str, object] | None = field(default=None, repr=False)
    speech_quality_attempt_count: int = field(default=0, repr=False)
    speech_quality_retry_exhausted: bool = field(default=False, repr=False)
    speech_quality_initial_codes: list[str] = field(default_factory=list, repr=False)
    first_token_ms: int | None = field(default=None, repr=False)

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
        if self.choice_normalization_kind is not None:
            value["raw_choice"] = self.raw_choice
            value["choice_normalization_kind"] = self.choice_normalization_kind
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
    call_options: ModelCallOptions | None = None,
) -> tuple[Any | None, LmLog]:
    base_prompt, _schema = build_prompt(action, world_state)
    raw_responses: list[str] = []
    invalid_attempts: list[dict[str, Any]] = []
    last_result: dict[str, Any] | None = None
    last_raw_choice: object | None = None
    last_normalization_kind: str | None = None
    current_prompt = base_prompt

    for attempt in range(retries):
        if invalid_attempts:
            current_prompt = _prompt_with_invalid_feedback(base_prompt, invalid_attempts[-1])
        attempt_options = (
            call_options.for_attempt(time.monotonic()) if call_options else None
        )
        raw_response = _call_provider_method(
            provider.complete_json,
            model=model,
            prompt=current_prompt,
            temperature=min(1.0, 0.4 + attempt * 0.2),
            call_options=attempt_options,
        )
        raw_responses.append(raw_response)
        try:
            result = parse_json_object(raw_response)
        except EmptyModelResponseError:
            invalid_attempts.append(
                _invalid_response_attempt("empty_content", result_key=result_key)
            )
            continue
        except ValueError:
            invalid_attempts.append(
                _invalid_response_attempt("invalid_json", result_key=result_key)
            )
            continue

        last_result = result
        value = result.get(result_key) if result_key else result
        normalization = (
            normalize_action_choice(value, allowed_values)
            if allowed_values is not None
            else None
        )
        last_raw_choice = value if normalization is not None else None
        last_normalization_kind = normalization.kind if normalization is not None else None
        normalized_value = normalization.canonical_value if normalization else value
        if allowed_values is None or normalized_value in allowed_values:
            return normalized_value, LmLog(
                prompt=current_prompt,
                raw_response=raw_response,
                result=result,
                invalid_attempts=invalid_attempts.copy(),
                raw_choice=value if normalization is not None else None,
                choice_normalization_kind=(
                    normalization.kind if normalization is not None else None
                ),
            )
        invalid_attempts.append(
            _invalid_attempt(
                value=value,
                allowed_values=allowed_values,
                result_key=result_key,
            )
        )

    return None, LmLog(
        prompt=current_prompt,
        raw_response="\n--- retry ---\n".join(raw_responses),
        result=last_result,
        invalid_attempts=invalid_attempts.copy(),
        raw_choice=last_raw_choice,
        choice_normalization_kind=last_normalization_kind,
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
    call_options: ModelCallOptions | None = None,
) -> tuple[Any | None, LmLog]:
    base_prompt, _schema = build_prompt(action, world_state)
    raw_responses: list[str] = []
    invalid_attempts: list[dict[str, Any]] = []
    last_result: dict[str, Any] | None = None
    last_raw_choice: object | None = None
    last_normalization_kind: str | None = None
    last_request_id: str | None = None
    last_first_token_ms: int | None = None
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
            attempt_options = (
                call_options.for_attempt(time.monotonic()) if call_options else None
            )
            raw_response, last_first_token_ms = _complete_json_with_optional_stream(
                provider=provider,
                model=model,
                prompt=current_prompt,
                temperature=temperature,
                action=action,
                event_sink=event_sink,
                context=context,
                request_id=request_id,
                progress=progress,
                call_options=attempt_options,
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
        except (EmptyModelResponseError, ValueError) as exc:
            reason_code = (
                "empty_content"
                if isinstance(exc, EmptyModelResponseError)
                else "invalid_json"
            )
            invalid_attempts.append(
                _invalid_response_attempt(reason_code, result_key=result_key)
            )
            if attempt + 1 < retries:
                _publish_model_event(
                    event_sink,
                    "model_retry_scheduled",
                    context=context,
                    payload={
                        "request_id": request_id,
                        "model": model,
                        "attempt": attempt + 2,
                        "reason_code": reason_code,
                        "message": (
                            "模型返回为空，正在重试。"
                            if reason_code == "empty_content"
                            else "模型返回格式无效，正在重试。"
                        ),
                    },
                )
            continue

        last_result = result
        value = result.get(result_key) if result_key else result
        normalization = (
            normalize_action_choice(value, allowed_values)
            if allowed_values is not None
            else None
        )
        last_raw_choice = value if normalization is not None else None
        last_normalization_kind = normalization.kind if normalization is not None else None
        normalized_value = normalization.canonical_value if normalization else value
        if allowed_values is None or normalized_value in allowed_values:
            return normalized_value, LmLog(
                prompt=current_prompt,
                raw_response=raw_response,
                result=result,
                request_id=request_id,
                invalid_attempts=invalid_attempts.copy(),
                raw_choice=value if normalization is not None else None,
                choice_normalization_kind=(
                    normalization.kind if normalization is not None else None
                ),
                first_token_ms=last_first_token_ms,
            )
        invalid_attempts.append(
            _invalid_attempt(
                value=value,
                allowed_values=allowed_values,
                result_key=result_key,
            )
        )
        if attempt + 1 < retries:
            _publish_model_event(
                event_sink,
                "model_retry_scheduled",
                context=context,
                payload={
                    "request_id": request_id,
                    "model": model,
                    "attempt": attempt + 2,
                    "invalid_value": value,
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
        raw_choice=last_raw_choice,
        choice_normalization_kind=last_normalization_kind,
        first_token_ms=last_first_token_ms,
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
    call_options: ModelCallOptions | None,
) -> tuple[str, int | None]:
    response_started_at = time.monotonic()
    stream_json = getattr(provider, "stream_json", None)
    if callable(stream_json):
        raw_chunks: list[str] = []
        visible_field = action_visible_stream_field(action)
        extractor = VisibleJsonFieldExtractor(visible_field) if visible_field else None
        pending_visible_text = ""
        last_delta_published_at = time.monotonic()
        stream_started_at = last_delta_published_at
        received_first_token = False
        first_token_ms: int | None = None
        try:
            stream = _call_provider_method(
                stream_json,
                model=model,
                prompt=prompt,
                temperature=temperature,
                call_options=call_options,
            )
            for chunk in stream:
                now = time.monotonic()
                _ensure_call_within_deadline(
                    call_options,
                    now=now,
                    stream_started_at=stream_started_at,
                    received_first_token=received_first_token,
                )
                if not received_first_token:
                    first_token_ms = max(
                        0,
                        round((now - response_started_at) * 1000),
                    )
                received_first_token = True
                raw_chunks.append(chunk)
                if extractor is None or visible_field is None:
                    continue
                raw_response = "".join(raw_chunks)
                visible_text = extractor.update(raw_response)
                if not visible_text:
                    continue
                progress.record_delta()
                pending_visible_text += visible_text
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
        except Exception as exc:
            if raw_chunks or isinstance(exc, ModelDeadlineExceeded):
                raise
            complete_response = _call_provider_method(
                provider.complete_json,
                model=model,
                prompt=prompt,
                temperature=temperature,
                call_options=(
                    call_options.for_attempt(time.monotonic())
                    if call_options
                    else None
                ),
            )
            return complete_response, max(
                0,
                round((time.monotonic() - response_started_at) * 1000),
            )

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
            return "".join(raw_chunks), first_token_ms

    complete_response = _call_provider_method(
        provider.complete_json,
        model=model,
        prompt=prompt,
        temperature=temperature,
        call_options=(
            call_options.for_attempt(time.monotonic()) if call_options else None
        ),
    )
    return complete_response, max(
        0,
        round((time.monotonic() - response_started_at) * 1000),
    )


def _call_provider_method(
    method: Callable[..., Any],
    *,
    model: str,
    prompt: str,
    temperature: float,
    call_options: ModelCallOptions | None,
) -> Any:
    parameters = inspect.signature(method).parameters
    if "call_options" in parameters:
        return method(
            model=model,
            prompt=prompt,
            temperature=temperature,
            call_options=call_options,
        )
    return method(model=model, prompt=prompt, temperature=temperature)


def _ensure_call_within_deadline(
    call_options: ModelCallOptions | None,
    *,
    now: float,
    stream_started_at: float,
    received_first_token: bool,
) -> None:
    if call_options is None:
        return
    if call_options.remaining_seconds(now) <= 0:
        raise ModelDeadlineExceeded("model streaming deadline exceeded")
    first_token_timeout = call_options.first_token_timeout_seconds
    if (
        not received_first_token
        and first_token_timeout is not None
        and now - stream_started_at > first_token_timeout
    ):
        raise ModelDeadlineExceeded("model first token deadline exceeded")


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
    record_model_progress_event(event_type)
    event_sink.publish(
        event_type,
        round_number=context.round_number,
        phase=context.phase,
        actor=context.actor,
        action=context.action,
        payload=payload,
    )


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


def _invalid_response_attempt(
    reason_code: str,
    *,
    result_key: str | None,
) -> dict[str, Any]:
    return {
        "reason_code": reason_code,
        "value": None,
        "allowed_values": [],
        "result_key": result_key or "result",
    }


def _prompt_with_invalid_feedback(
    base_prompt: str,
    invalid_attempt: dict[str, Any],
) -> str:
    reason_code = invalid_attempt.get("reason_code")
    if reason_code == "empty_content":
        return f"{base_prompt}\n\n上次输出为空。本次必须只输出符合要求的合法 JSON。"
    if reason_code == "invalid_json":
        return f"{base_prompt}\n\n上次输出不是合法 JSON。本次必须只输出符合要求的合法 JSON。"
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
    if not content:
        raise EmptyModelResponseError("Model response content was empty.")
    if content.startswith("```"):
        content = content.strip("`")
        if content.startswith("json"):
            content = content[4:]
        content = content.strip()

    decoder = json.JSONDecoder()
    try:
        parsed, _index = decoder.raw_decode(content)
    except json.JSONDecodeError as exc:
        try:
            parsed, _index = decoder.raw_decode(
                escape_unescaped_json_string_control_chars(content)
            )
        except json.JSONDecodeError:
            raise ValueError("Model response was not valid JSON.") from exc

    if not isinstance(parsed, dict):
        raise ValueError("Model response JSON must be an object.")
    return parsed
