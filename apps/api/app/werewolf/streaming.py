from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass
from typing import Any, Protocol

PUBLIC_STREAM_FIELD_BY_ACTION = {
    "debate": "say",
    "sheriff_speech": "say",
    "sheriff_pk_speech": "say",
    "summarize": "summary",
}


class ProgressEventSink(Protocol):
    def publish(
        self,
        event_type: str,
        *,
        round_number: int | None = None,
        phase: str | None = None,
        actor: str | None = None,
        action: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> object:
        pass


@dataclass(frozen=True)
class ModelEventContext:
    round_number: int | None
    phase: str | None
    actor: str | None
    action: str | None


class ModelRequestProgress:
    def __init__(
        self,
        *,
        event_sink: ProgressEventSink,
        context: ModelEventContext,
        request_id: str,
        model: str,
        message: str,
        tick_interval: float = 2.0,
        delta_suppression_seconds: float = 1.0,
    ) -> None:
        self.event_sink = event_sink
        self.context = context
        self.request_id = request_id
        self.model = model
        self.message = message
        self.tick_interval = tick_interval
        self.delta_suppression_seconds = delta_suppression_seconds
        self._started_at = time.monotonic()
        self._last_delta_at: float | None = None
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None:
            return
        self._started_at = time.monotonic()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def record_delta(self) -> None:
        with self._lock:
            self._last_delta_at = time.monotonic()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=max(0.1, self.tick_interval + 0.1))

    def _run(self) -> None:
        while not self._stop_event.wait(self.tick_interval):
            now = time.monotonic()
            if self._should_suppress_tick(now):
                continue
            self.event_sink.publish(
                "model_thinking_tick",
                round_number=self.context.round_number,
                phase=self.context.phase,
                actor=self.context.actor,
                action=self.context.action,
                payload={
                    "request_id": self.request_id,
                    "model": self.model,
                    "elapsed_ms": int((now - self._started_at) * 1000),
                    "message": self.message,
                },
            )

    def _should_suppress_tick(self, now: float) -> bool:
        with self._lock:
            last_delta_at = self._last_delta_at
        return (
            last_delta_at is not None
            and now - last_delta_at < self.delta_suppression_seconds
        )


def action_visible_stream_field(action: str) -> str | None:
    return PUBLIC_STREAM_FIELD_BY_ACTION.get(action)


def waiting_message_for_action(action: str) -> str:
    if action in {"debate", "sheriff_speech", "sheriff_pk_speech"}:
        return "玩家正在组织公开发言..."
    if action == "summarize":
        return "正在整理本轮总结..."
    if action in {"vote", "sheriff_vote", "sheriff_runoff_vote"}:
        return "玩家正在权衡投票选择..."
    if action in {
        "investigate",
        "remove",
        "werewolf_discuss",
        "werewolf_kill_vote",
        "protect",
        "witch_save",
        "witch_poison",
        "hunter_shoot",
    }:
        return "夜晚行动正在秘密决策..."
    return "模型正在思考下一步行动..."


class VisibleJsonFieldExtractor:
    def __init__(self, field: str) -> None:
        self.field = field
        self._visible_text = ""

    def update(self, raw_text: str) -> str:
        visible_text = extract_json_string_field_prefix(raw_text, self.field)
        if not visible_text.startswith(self._visible_text):
            self._visible_text = ""
        delta = visible_text[len(self._visible_text) :]
        self._visible_text = visible_text
        return delta


def extract_json_string_field_prefix(raw_text: str, field: str) -> str:
    marker = json.dumps(field, ensure_ascii=False)
    marker_index = raw_text.find(marker)
    if marker_index < 0:
        return ""

    colon_index = raw_text.find(":", marker_index + len(marker))
    if colon_index < 0:
        return ""

    index = colon_index + 1
    while index < len(raw_text) and raw_text[index].isspace():
        index += 1
    if index >= len(raw_text) or raw_text[index] != '"':
        return ""

    raw_value = _raw_json_string_prefix(raw_text[index + 1 :])
    return _decode_json_string_prefix(raw_value)


def _raw_json_string_prefix(text: str) -> str:
    chars: list[str] = []
    index = 0
    while index < len(text):
        char = text[index]
        if char == '"':
            break
        if char == "\\":
            if index + 1 >= len(text):
                break
            next_char = text[index + 1]
            if next_char == "u":
                if index + 6 > len(text):
                    break
                if _is_high_surrogate_escape(text[index : index + 6]):
                    if index + 12 > len(text):
                        break
                    if not _is_low_surrogate_escape(text[index + 6 : index + 12]):
                        break
                    chars.append(text[index : index + 12])
                    index += 12
                    continue
                chars.append(text[index : index + 6])
                index += 6
                continue
            if index + 2 > len(text):
                break
            chars.append(text[index : index + 2])
            index += 2
            continue
        chars.append(char)
        index += 1
    return "".join(chars)


def _is_high_surrogate_escape(text: str) -> bool:
    return len(text) == 6 and _is_surrogate_escape_in_range(text, 0xD800, 0xDBFF)


def _is_low_surrogate_escape(text: str) -> bool:
    return len(text) == 6 and _is_surrogate_escape_in_range(text, 0xDC00, 0xDFFF)


def _is_surrogate_escape_in_range(text: str, start: int, end: int) -> bool:
    if not text.startswith("\\u"):
        return False
    try:
        codepoint = int(text[2:], 16)
    except ValueError:
        return False
    return start <= codepoint <= end


def _decode_json_string_prefix(raw_value: str) -> str:
    if raw_value == "":
        return ""
    try:
        return json.loads(f'"{raw_value}"')
    except json.JSONDecodeError:
        trimmed = raw_value.rstrip("\\")
        return json.loads('"' + trimmed + '"')


def extract_openai_chat_delta(chunk: bytes) -> str | None:
    text = chunk.decode("utf-8", errors="replace").strip()
    if not text:
        return None

    contents: list[str] = []
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("data:"):
            continue
        data = line.removeprefix("data:").strip()
        if data == "[DONE]":
            return "".join(contents) if contents else None
        try:
            payload = json.loads(data)
        except json.JSONDecodeError:
            continue
        choices = payload.get("choices")
        if not isinstance(choices, list) or not choices:
            continue
        first_choice = choices[0]
        if not isinstance(first_choice, dict):
            continue
        delta = first_choice.get("delta")
        if not isinstance(delta, dict):
            continue
        content = delta.get("content")
        if isinstance(content, str) and content:
            contents.append(content)
    return "".join(contents) if contents else None
