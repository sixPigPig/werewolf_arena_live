# Streaming Model Live Experience Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Improve the live spectator page by streaming visible model progress while keeping full JSON responses as the only authority for game state.

**Architecture:** Keep the existing backend SSE run stream. Add OpenAI-compatible streaming support and request progress events in the backend, then coalesce `model_response_delta` and `model_thinking_tick` into the active director cue on the frontend. Game rules still advance only after full JSON parsing and validation.

**Tech Stack:** FastAPI, Python dataclasses/threading/urllib, pytest, React, TypeScript, Vitest, browser `EventSource`.

**Post-review implementation guardrails:** Public live SSE payloads must not include `prompt`, `world_state`, or full `raw_response`. `model_response_delta.delta` is the same sanitized public text as `visible_text`, not raw provider output. `action_parsed.result` is sanitized to public display fields only; internal logs and checkpoints remain the authority for full prompt/response debugging.

---

## File Structure

Backend:

- Create `apps/api/app/werewolf/streaming.py`: visible JSON field extraction, OpenAI-compatible stream chunk parsing, and model request progress tick helper.
- Modify `apps/api/app/werewolf/providers.py`: add optional streaming transport and `stream_json()` to `OpenAICompatibleProvider` and `RoutingModelProvider`.
- Modify `apps/api/app/werewolf/lm.py`: add `generate_action_with_events()` that owns request IDs, model progress events, streaming fallback, retries, and final JSON validation.
- Modify `apps/api/app/werewolf/engine.py`: replace the direct `generate_action()` call with `generate_action_with_events()` for live event publishing.
- Modify backend tests in `apps/api/tests/test_werewolf_lm.py`, `apps/api/tests/test_werewolf_runner.py`, and `apps/api/tests/test_games_api.py`.

Frontend:

- Modify `apps/web/src/features/games/hooks/useGameRunEvents.ts`: subscribe to new event types.
- Modify `apps/web/src/features/games/liveSpectator.ts`: add `streaming` status and track accumulated visible text.
- Modify `apps/web/src/features/games/liveDirector.ts`: add `buildDirectorCues()` to merge delta/tick events into the request cue.
- Modify `apps/web/src/features/games/hooks/useLiveDirector.ts`: use `buildDirectorCues()` instead of mapping each raw event one-to-one.
- Modify `apps/web/src/features/games/components/LivePlayerPanel.tsx`: label the new `streaming` status.
- Modify `apps/web/src/features/games/components/LiveDirectorStage.tsx`: render streaming/waiting cues cleanly.
- Modify `apps/web/src/features/games/components/LiveEventTimeline.tsx`: hide delta/tick from the default timeline.
- Modify `apps/web/src/pages/LiveGamePage.tsx`: pass filtered or raw events according to the updated timeline API.
- Modify frontend tests in `apps/web/src/features/games/hooks/useGameRunEvents.test.tsx`, `apps/web/src/features/games/liveSpectator.test.ts`, `apps/web/src/features/games/liveDirector.test.ts`, and `apps/web/src/pages/LiveGamePage.test.tsx`.

---

### Task 1: Backend Streaming Primitives

**Files:**
- Create: `apps/api/app/werewolf/streaming.py`
- Modify: `apps/api/tests/test_werewolf_lm.py`

- [ ] **Step 1: Write failing tests for visible field extraction**

Append these imports to `apps/api/tests/test_werewolf_lm.py`:

```python
from app.werewolf.streaming import (
    VisibleJsonFieldExtractor,
    action_visible_stream_field,
    extract_openai_chat_delta,
)
```

Append these tests near the existing LM unit tests:

```python
def test_visible_json_field_extractor_streams_only_new_public_text() -> None:
    extractor = VisibleJsonFieldExtractor("say")

    assert extractor.update('{"reasoning":"先观察",') == ""
    assert extractor.update('{"reasoning":"先观察","say":"我') == "我"
    assert extractor.update('{"reasoning":"先观察","say":"我不是') == "不是"
    assert extractor.update('{"reasoning":"先观察","say":"我不是狼"}') == "狼"
    assert extractor.update('{"reasoning":"先观察","say":"我不是狼"}') == ""


def test_visible_json_field_extractor_decodes_escaped_text() -> None:
    extractor = VisibleJsonFieldExtractor("summary")

    assert extractor.update('{"summary":"第一行\\n') == "第一行"
    assert extractor.update('{"summary":"第一行\\n第二行"}') == "\n第二行"


def test_action_visible_stream_field_only_allows_public_actions() -> None:
    assert action_visible_stream_field("debate") == "say"
    assert action_visible_stream_field("sheriff_speech") == "say"
    assert action_visible_stream_field("sheriff_pk_speech") == "say"
    assert action_visible_stream_field("summarize") == "summary"
    assert action_visible_stream_field("vote") is None
    assert action_visible_stream_field("remove") is None


def test_extract_openai_chat_delta_reads_compatible_sse_chunks() -> None:
    chunk = (
        'data: {"choices":[{"delta":{"content":"我不是狼"}}]}\\n\\n'
    ).encode("utf-8")

    assert extract_openai_chat_delta(chunk) == "我不是狼"
    assert extract_openai_chat_delta(b"data: [DONE]\\n\\n") is None
    assert extract_openai_chat_delta(b": heartbeat\\n\\n") is None
```

- [ ] **Step 2: Run tests and verify failure**

From `apps/api`, run:

```bash
uv run pytest tests/test_werewolf_lm.py::test_visible_json_field_extractor_streams_only_new_public_text tests/test_werewolf_lm.py::test_visible_json_field_extractor_decodes_escaped_text tests/test_werewolf_lm.py::test_action_visible_stream_field_only_allows_public_actions tests/test_werewolf_lm.py::test_extract_openai_chat_delta_reads_compatible_sse_chunks -q
```

Expected: FAIL because `app.werewolf.streaming` does not exist.

- [ ] **Step 3: Add streaming primitives**

Create `apps/api/app/werewolf/streaming.py` with these definitions:

```python
from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Protocol

PUBLIC_STREAM_FIELD_BY_ACTION = {
    "debate": "say",
    "sheriff_speech": "say",
    "sheriff_pk_speech": "say",
    "summarize": "summary",
}


def action_visible_stream_field(action: str) -> str | None:
    return PUBLIC_STREAM_FIELD_BY_ACTION.get(action)


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
                chars.append(text[index : index + 6])
                index += 6
                continue
            chars.append(text[index : index + 2])
            index += 2
            continue
        chars.append(char)
        index += 1
    return "".join(chars)


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
    if not text or text.startswith(":"):
        return None

    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("data:"):
            continue
        data = line.removeprefix("data:").strip()
        if data == "[DONE]":
            return None
        try:
            payload = json.loads(data)
        except json.JSONDecodeError:
            return None
        choices = payload.get("choices")
        if not isinstance(choices, list) or not choices:
            return None
        first_choice = choices[0]
        if not isinstance(first_choice, dict):
            return None
        delta = first_choice.get("delta")
        if not isinstance(delta, dict):
            return None
        content = delta.get("content")
        return content if isinstance(content, str) and content else None
    return None
```

- [ ] **Step 4: Run tests and verify pass**

From `apps/api`, run the same focused command from Step 2.

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/api/app/werewolf/streaming.py apps/api/tests/test_werewolf_lm.py
git commit -m "feat: add model stream parsing primitives"
```

---

### Task 2: Provider Streaming Support

**Files:**
- Modify: `apps/api/app/werewolf/providers.py`
- Modify: `apps/api/tests/test_werewolf_lm.py`

- [ ] **Step 1: Write failing provider stream tests**

Append this test to `apps/api/tests/test_werewolf_lm.py`:

```python
def test_openai_compatible_provider_streams_chat_deltas(monkeypatch) -> None:
    requests = []

    def fake_stream_transport(url: str, headers: dict[str, str], payload: dict) -> list[str]:
        requests.append({"url": url, "headers": headers, "payload": payload})
        return ["我", "不是", "狼"]

    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    provider = DeepSeekProvider(stream_transport=fake_stream_transport)

    chunks = list(
        provider.stream_json(
            model="deepseek-chat",
            prompt='请输出 json：{"say":"我不是狼"}',
            temperature=0.3,
        )
    )

    assert chunks == ["我", "不是", "狼"]
    assert requests[0]["url"] == "https://api.deepseek.com/chat/completions"
    assert requests[0]["headers"]["Authorization"] == "Bearer test-key"
    assert requests[0]["payload"]["stream"] is True
    assert requests[0]["payload"]["model"] == "deepseek-chat"
    assert requests[0]["payload"]["response_format"] == {"type": "json_object"}


def test_model_provider_router_exposes_stream_json(monkeypatch) -> None:
    def fake_stream_transport(url: str, headers: dict[str, str], payload: dict) -> list[str]:
        del url, headers, payload
        return ['{"reasoning":"x","say":"你好"}']

    monkeypatch.setenv("DEEPSEEK_API_KEY", "deepseek-key")
    provider = create_model_provider(stream_transport=fake_stream_transport)

    assert list(provider.stream_json(model="deepseek-chat", prompt="{}", temperature=0.3)) == [
        '{"reasoning":"x","say":"你好"}'
    ]
```

- [ ] **Step 2: Run tests and verify failure**

From `apps/api`, run:

```bash
uv run pytest tests/test_werewolf_lm.py::test_openai_compatible_provider_streams_chat_deltas tests/test_werewolf_lm.py::test_model_provider_router_exposes_stream_json -q
```

Expected: FAIL because providers do not accept `stream_transport` and router does not expose `stream_json()`.

- [ ] **Step 3: Add provider stream transport types**

In `apps/api/app/werewolf/providers.py`, add this type alias below `Transport`:

```python
StreamTransport = Callable[[str, dict[str, str], dict[str, Any]], Any]
```

Update `OpenAICompatibleProvider.__init__()` parameters:

```python
        stream_transport: StreamTransport | None = None,
```

Store it after `self.transport`:

```python
        self.stream_transport = stream_transport or _urlopen_stream_transport
```

Apply the same optional `stream_transport` parameter to `DeepSeekProvider`, `MiniMaxProvider`, `QwenProvider`, `create_model_provider()`, and `_openai_provider_factory()`.

- [ ] **Step 4: Add `stream_json()` to providers**

In `OpenAICompatibleProvider`, add:

```python
    def stream_json(self, *, model: str, prompt: str, temperature: float) -> Any:
        payload = self._chat_payload(model=model, prompt=prompt, temperature=temperature)
        payload["stream"] = True
        headers = self._headers()
        return self.stream_transport(f"{self.base_url}/chat/completions", headers, payload)
```

Refactor the duplicated payload/header construction in `complete_json()` into helpers:

```python
    def _chat_payload(self, *, model: str, prompt: str, temperature: float) -> dict[str, Any]:
        payload: dict[str, Any] = {
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
        payload.update(self.config.extra_payload)
        return payload

    def _headers(self) -> dict[str, str]:
        return {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
            "User-Agent": "werewolf-arena-live/0.1",
        }
```

Update `complete_json()` to call these helpers:

```python
    def complete_json(self, *, model: str, prompt: str, temperature: float) -> str:
        payload = self._chat_payload(model=model, prompt=prompt, temperature=temperature)
        headers = self._headers()
        response = self._send_with_retries(f"{self.base_url}/chat/completions", headers, payload)
        return response["choices"][0]["message"]["content"]
```

Add this method to `RoutingModelProvider`:

```python
    def stream_json(self, *, model: str, prompt: str, temperature: float) -> Any:
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
        stream_method = getattr(provider, "stream_json", None)
        if not callable(stream_method):
            raise RuntimeError(f"Provider {registration.name} does not support streaming.")
        return stream_method(model=model, prompt=prompt, temperature=temperature)
```

- [ ] **Step 5: Add URL opener stream transport**

Import the parser near the top of `providers.py`:

```python
from app.werewolf.streaming import extract_openai_chat_delta
```

Add this function below `_urlopen_transport()`:

```python
def _urlopen_stream_transport(
    url: str,
    headers: dict[str, str],
    payload: dict[str, Any],
) -> Any:
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(url, data=data, headers=headers, method="POST")
    with urllib.request.urlopen(request, timeout=120) as response:
        for line in response:
            delta = extract_openai_chat_delta(line)
            if delta is not None:
                yield delta
```

- [ ] **Step 6: Run tests and verify pass**

From `apps/api`, run:

```bash
uv run pytest tests/test_werewolf_lm.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add apps/api/app/werewolf/providers.py apps/api/tests/test_werewolf_lm.py
git commit -m "feat: support streaming model providers"
```

---

### Task 3: Model Progress Events And Action Helper

**Files:**
- Modify: `apps/api/app/werewolf/streaming.py`
- Modify: `apps/api/app/werewolf/lm.py`
- Modify: `apps/api/tests/test_werewolf_lm.py`

- [ ] **Step 1: Write failing tests for progress and streamed action events**

Append these test helpers to `apps/api/tests/test_werewolf_lm.py`:

```python
class CapturingLmEventSink:
    def __init__(self) -> None:
        self.events: list[dict[str, object]] = []

    def publish(self, event_type: str, **kwargs: object) -> None:
        self.events.append({"type": event_type, **kwargs})


class StreamingFakeProvider:
    def __init__(self, chunks: list[str]) -> None:
        self.chunks = chunks
        self.calls = 0

    def complete_json(self, *, model: str, prompt: str, temperature: float) -> str:
        del model, prompt, temperature
        self.calls += 1
        return "".join(self.chunks)

    def stream_json(self, *, model: str, prompt: str, temperature: float) -> list[str]:
        del model, prompt, temperature
        self.calls += 1
        return self.chunks
```

Append these tests:

```python
def test_generate_action_with_events_streams_public_visible_text() -> None:
    from app.werewolf.lm import generate_action_with_events

    sink = CapturingLmEventSink()
    provider = StreamingFakeProvider(
        ['{"reasoning":"试探",', '"say":"我', '不是', '狼"}']
    )

    value, log = generate_action_with_events(
        provider=provider,
        action="debate",
        world_state=_world_state_for_special_action("村民", ""),
        model="deepseek-chat",
        allowed_values=None,
        result_key="say",
        event_sink=sink,
        event_context={
            "round_number": 1,
            "phase": "day",
            "actor": "Alice",
            "action": "debate",
        },
        request_id_factory=lambda: "req_public",
        enable_progress_ticks=False,
    )

    assert value == "我不是狼"
    assert log.raw_response == '{"reasoning":"试探","say":"我不是狼"}'
    delta_events = [event for event in sink.events if event["type"] == "model_response_delta"]
    assert [event["payload"]["visible_text"] for event in delta_events] == ["我", "不是", "狼"]
    assert all(event["payload"]["request_id"] == "req_public" for event in delta_events)


def test_generate_action_with_events_suppresses_private_action_deltas() -> None:
    from app.werewolf.lm import generate_action_with_events

    sink = CapturingLmEventSink()
    provider = StreamingFakeProvider(
        ['{"reasoning":"夜晚决策",', '"remove":"Bob"}']
    )

    value, log = generate_action_with_events(
        provider=provider,
        action="remove",
        world_state=_world_state_for_special_action("狼人", "Bob、Carol"),
        model="deepseek-chat",
        allowed_values=["Bob", "Carol"],
        result_key="remove",
        event_sink=sink,
        event_context={
            "round_number": 1,
            "phase": "night",
            "actor": "Alice",
            "action": "remove",
        },
        request_id_factory=lambda: "req_private",
        enable_progress_ticks=False,
    )

    assert value == "Bob"
    assert log.result == {"reasoning": "夜晚决策", "remove": "Bob"}
    assert [event["type"] for event in sink.events].count("model_response_delta") == 0
```

- [ ] **Step 2: Run tests and verify failure**

From `apps/api`, run:

```bash
uv run pytest tests/test_werewolf_lm.py::test_generate_action_with_events_streams_public_visible_text tests/test_werewolf_lm.py::test_generate_action_with_events_suppresses_private_action_deltas -q
```

Expected: FAIL because `generate_action_with_events()` does not exist.

- [ ] **Step 3: Add `ModelRequestProgress`**

Append this to `apps/api/app/werewolf/streaming.py`:

```python
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
    ) -> Any:
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
        tick_interval: float = 2.0,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self.event_sink = event_sink
        self.context = context
        self.request_id = request_id
        self.model = model
        self.tick_interval = tick_interval
        self.monotonic = monotonic
        self.started_at = monotonic()
        self.last_delta_at = self.started_at
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def record_delta(self) -> None:
        self.last_delta_at = self.monotonic()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=0.5)

    def _run(self) -> None:
        while not self._stop_event.wait(self.tick_interval):
            now = self.monotonic()
            if now - self.last_delta_at < self.tick_interval:
                continue
            elapsed_ms = int((now - self.started_at) * 1000)
            self.event_sink.publish(
                "model_thinking_tick",
                round_number=self.context.round_number,
                phase=self.context.phase,
                actor=self.context.actor,
                action=self.context.action,
                payload={
                    "request_id": self.request_id,
                    "model": self.model,
                    "elapsed_ms": elapsed_ms,
                    "message": waiting_message_for_action(self.context.action),
                },
            )


def waiting_message_for_action(action: str | None) -> str:
    if action in {"debate", "sheriff_speech", "sheriff_pk_speech"}:
        return "正在组织发言..."
    if action == "summarize":
        return "正在总结本轮线索..."
    if action in {"vote", "sheriff_vote", "sheriff_runoff_vote"}:
        return "正在权衡投票目标..."
    if action in {"remove", "protect", "investigate", "witch_save", "witch_poison", "hunter_shoot"}:
        return "正在分析夜晚行动..."
    return "正在分析局势..."
```

- [ ] **Step 4: Add `generate_action_with_events()`**

In `apps/api/app/werewolf/lm.py`, add imports:

```python
import uuid
from collections.abc import Callable

from app.werewolf.streaming import (
    ModelEventContext,
    ModelRequestProgress,
    VisibleJsonFieldExtractor,
    action_visible_stream_field,
)
```

Update `LmLog` so streamed requests can carry their request ID into later engine events:

```python
@dataclass
class LmLog:
    prompt: str
    raw_response: str
    result: dict[str, Any] | None
    request_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        data = {
            "prompt": self.prompt,
            "raw_response": self.raw_response,
            "result": self.result,
        }
        if self.request_id is not None:
            data["request_id"] = self.request_id
        return data
```

Add this function below `generate_action()`:

```python
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
    prompt, _schema = build_prompt(action, world_state)
    raw_responses: list[str] = []
    last_result: dict[str, Any] | None = None
    last_request_id: str | None = None
    visible_field = action_visible_stream_field(action)

    for attempt in range(retries):
        request_id = request_id_factory() if request_id_factory else f"req_{uuid.uuid4().hex[:12]}"
        last_request_id = request_id
        temperature = min(1.0, 0.4 + attempt * 0.2)
        context = ModelEventContext(
            round_number=event_context.get("round_number"),
            phase=event_context.get("phase"),
            actor=event_context.get("actor"),
            action=event_context.get("action"),
        )
        event_sink.publish(
            "model_request_started",
            round_number=context.round_number,
            phase=context.phase,
            actor=context.actor,
            action=context.action,
            payload={
                "request_id": request_id,
                "model": model,
                "world_state": json.loads(json.dumps(world_state, ensure_ascii=False)),
            },
        )
        progress = ModelRequestProgress(
            event_sink=event_sink,
            context=context,
            request_id=request_id,
            model=model,
        )
        if enable_progress_ticks:
            progress.start()
        try:
            raw_response = _complete_json_with_optional_stream(
                provider=provider,
                model=model,
                prompt=prompt,
                temperature=temperature,
                action=action,
                visible_field=visible_field,
                event_sink=event_sink,
                context=context,
                request_id=request_id,
                progress=progress,
            )
        except Exception as exc:
            progress.stop()
            event_sink.publish(
                "model_request_failed",
                round_number=context.round_number,
                phase=context.phase,
                actor=context.actor,
                action=context.action,
                payload={"request_id": request_id, "model": model, "error": str(exc)},
            )
            raise
        finally:
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
                prompt=prompt,
                raw_response=raw_response,
                result=result,
                request_id=request_id,
            )

    return None, LmLog(
        prompt=prompt,
        raw_response="\n--- retry ---\n".join(raw_responses),
        result=last_result,
        request_id=last_request_id,
    )
```

Add this helper below it:

```python
def _complete_json_with_optional_stream(
    *,
    provider: ModelProvider,
    model: str,
    prompt: str,
    temperature: float,
    action: str,
    visible_field: str | None,
    event_sink: Any,
    context: ModelEventContext,
    request_id: str,
    progress: ModelRequestProgress,
) -> str:
    stream_method = getattr(provider, "stream_json", None)
    if not callable(stream_method):
        return provider.complete_json(model=model, prompt=prompt, temperature=temperature)

    raw_parts: list[str] = []
    extractor = VisibleJsonFieldExtractor(visible_field) if visible_field else None
    for chunk in stream_method(model=model, prompt=prompt, temperature=temperature):
        raw_parts.append(str(chunk))
        raw_response = "".join(raw_parts)
        visible_text = extractor.update(raw_response) if extractor is not None else ""
        if not visible_text:
            continue
        progress.record_delta()
        event_sink.publish(
            "model_response_delta",
            round_number=context.round_number,
            phase=context.phase,
            actor=context.actor,
            action=context.action,
            payload={
                "request_id": request_id,
                "model": model,
                "delta": str(chunk),
                "visible_text": visible_text,
                "field": visible_field,
                "is_public": True,
            },
        )
    return "".join(raw_parts)
```

- [ ] **Step 5: Run focused tests and full LM tests**

From `apps/api`, run:

```bash
uv run pytest tests/test_werewolf_lm.py::test_generate_action_with_events_streams_public_visible_text tests/test_werewolf_lm.py::test_generate_action_with_events_suppresses_private_action_deltas -q
uv run pytest tests/test_werewolf_lm.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add apps/api/app/werewolf/streaming.py apps/api/app/werewolf/lm.py apps/api/tests/test_werewolf_lm.py
git commit -m "feat: publish model streaming progress events"
```

---

### Task 4: Engine Integration

**Files:**
- Modify: `apps/api/app/werewolf/engine.py`
- Modify: `apps/api/tests/test_werewolf_runner.py`

- [ ] **Step 1: Write failing engine event test**

Append this provider to `apps/api/tests/test_werewolf_runner.py` near the other provider fakes:

```python
class StreamingSpeechProvider(ScriptedChineseProvider):
    def stream_json(self, *, model: str, prompt: str, temperature: float) -> list[str]:
        del model, temperature
        if '"say"' in prompt:
            return ['{"reasoning":"公开发言",', '"say":"我', '不是', '狼"}']
        return [self.complete_json(model="deepseek-chat", prompt=prompt, temperature=0.4)]
```

Append this test near `test_run_game_publishes_live_events`:

```python
def test_run_game_publishes_streaming_model_events(tmp_path) -> None:
    sink = CapturingEventSink()

    run_game(
        logs_dir=tmp_path,
        seed=21,
        max_rounds=1,
        provider=StreamingSpeechProvider(),
        session_id="session_20260424_120000_ab12cd34",
        event_sink=sink,
    )

    event_types = [event["type"] for event in sink.events]
    assert "model_request_started" in event_types
    assert "model_response_delta" in event_types
    assert "model_response_received" in event_types
    assert "action_parsed" in event_types

    started_event = next(event for event in sink.events if event["type"] == "model_request_started")
    delta_event = next(event for event in sink.events if event["type"] == "model_response_delta")
    response_event = next(event for event in sink.events if event["type"] == "model_response_received")
    assert started_event["payload"]["request_id"].startswith("req_")
    assert delta_event["payload"]["request_id"].startswith("req_")
    assert response_event["payload"]["request_id"].startswith("req_")
```

- [ ] **Step 2: Run test and verify failure**

From `apps/api`, run:

```bash
uv run pytest tests/test_werewolf_runner.py::test_run_game_publishes_streaming_model_events -q
```

Expected: FAIL because the engine still uses `generate_action()` and does not publish delta events.

- [ ] **Step 3: Replace direct model call in engine**

In `apps/api/app/werewolf/engine.py`, change the import:

```python
from app.werewolf.lm import ModelProvider, generate_action_with_events
```

In `GameEngine._player_action()`, keep the existing `action_requested` publish. Remove the existing `model_request_started` publish block. Replace the direct `generate_action()` call with:

```python
            value, lm_log = generate_action_with_events(
                provider=self.provider,
                action=action,
                world_state=world_state,
                model=player.model,
                allowed_values=options if options else None,
                result_key=result_key,
                event_sink=self.event_sink,
                event_context={
                    "round_number": round_state.number,
                    "phase": phase,
                    "actor": player.name,
                    "action": action,
                },
            )
```

Remove the `model_request_failed` publish from the engine exception block because `generate_action_with_events()` now publishes it with `request_id`. Keep checkpoint recording and `raise`.

When publishing `model_response_received`, include the request ID produced by `generate_action_with_events()`:

```python
            payload={
                "request_id": lm_log.request_id,
                "prompt": lm_log.prompt,
                "raw_response": lm_log.raw_response,
            },
```

- [ ] **Step 4: Update mutability regression test expectation**

`MutatingWorldStateSink` in `apps/api/tests/test_werewolf_runner.py` still mutates the `model_request_started` payload. Keep that test meaningful by asserting the copied payload still exists:

```python
assert any(
    event["type"] == "model_request_started"
    and isinstance(event.get("payload"), dict)
    and "world_state" in event["payload"]
    for event in sink.events
)
```

Do not relax the existing mutation safety assertions below that test.

- [ ] **Step 5: Run backend runner tests**

From `apps/api`, run:

```bash
uv run pytest tests/test_werewolf_runner.py -q
uv run pytest tests/test_games_api.py::test_game_run_events_replays_existing_events -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add apps/api/app/werewolf/engine.py apps/api/app/werewolf/lm.py apps/api/tests/test_werewolf_runner.py
git commit -m "feat: stream model progress through game engine"
```

---

### Task 5: Frontend Event Intake And Spectator State

**Files:**
- Modify: `apps/web/src/features/games/hooks/useGameRunEvents.ts`
- Modify: `apps/web/src/features/games/liveSpectator.ts`
- Modify: `apps/web/src/features/games/components/LivePlayerPanel.tsx`
- Modify: `apps/web/src/features/games/hooks/useGameRunEvents.test.tsx`
- Modify: `apps/web/src/features/games/liveSpectator.test.ts`

- [ ] **Step 1: Write failing EventSource test**

Append this test to `apps/web/src/features/games/hooks/useGameRunEvents.test.tsx`:

```tsx
  it("subscribes to model streaming progress events", async () => {
    vi.stubGlobal("EventSource", MockEventSource);

    const { result } = renderHook(() => useGameRunEvents("run_1234abcd"));
    const source = MockEventSource.instances[0];
    act(() => {
      source.emit("model_response_delta", {
        id: 3,
        type: "model_response_delta",
        run_id: "run_1234abcd",
        session_id: "session_20260424_120000_ab12cd34",
        created_at: "2026-04-24T12:00:04Z",
        round: 1,
        phase: "day",
        actor: "张三",
        action: "debate",
        payload: {
          request_id: "req_123",
          visible_text: "我不是狼",
          field: "say",
          is_public: true,
        },
      });
      source.emit("model_thinking_tick", {
        id: 4,
        type: "model_thinking_tick",
        run_id: "run_1234abcd",
        session_id: "session_20260424_120000_ab12cd34",
        created_at: "2026-04-24T12:00:05Z",
        round: 1,
        phase: "day",
        actor: "张三",
        action: "debate",
        payload: {
          request_id: "req_123",
          elapsed_ms: 3000,
          message: "正在组织发言...",
        },
      });
    });

    await waitFor(() => expect(result.current.events).toHaveLength(2));
    expect(result.current.events.map((event) => event.type)).toEqual([
      "model_response_delta",
      "model_thinking_tick",
    ]);
  });
```

- [ ] **Step 2: Write failing spectator state test**

Append this test to `apps/web/src/features/games/liveSpectator.test.ts`:

```ts
  it("accumulates streamed visible text for the active player", () => {
    const state = deriveLiveSpectatorState([
      event({
        id: 1,
        type: "game_started",
        payload: {
          players: [{ name: "张三", role: "村民", model: "deepseek-chat" }],
        },
      }),
      event({
        id: 2,
        type: "model_request_started",
        actor: "张三",
        action: "debate",
        round: 1,
        phase: "day",
        payload: { request_id: "req_123", model: "deepseek-chat" },
      }),
      event({
        id: 3,
        type: "model_response_delta",
        actor: "张三",
        action: "debate",
        round: 1,
        phase: "day",
        payload: { request_id: "req_123", visible_text: "我", is_public: true },
      }),
      event({
        id: 4,
        type: "model_response_delta",
        actor: "张三",
        action: "debate",
        round: 1,
        phase: "day",
        payload: { request_id: "req_123", visible_text: "不是狼", is_public: true },
      }),
    ]);

    expect(state.players[0]).toMatchObject({
      status: "streaming",
      lastAction: "debate",
      lastDetail: "我不是狼",
    });
  });
```

- [ ] **Step 3: Run tests and verify failure**

From repo root, run:

```bash
pnpm --dir apps/web test -- --run src/features/games/hooks/useGameRunEvents.test.tsx src/features/games/liveSpectator.test.ts
```

Expected: FAIL because new event types and `streaming` status are not supported.

- [ ] **Step 4: Subscribe to new event types**

In `apps/web/src/features/games/hooks/useGameRunEvents.ts`, add the new event types to `EVENT_TYPES` after `model_request_started`:

```ts
  "model_thinking_tick",
  "model_response_delta",
```

- [ ] **Step 5: Add streaming state**

In `apps/web/src/features/games/liveSpectator.ts`, extend `LivePlayerStatus`:

```ts
  | "streaming"
```

Add request tracking to `LivePlayer`:

```ts
  activeRequestId: string | null;
```

Initialize it in `ensurePlayer()`:

```ts
    activeRequestId: null,
```

Update `statusForActorEvent()`:

```ts
  if (type === "model_response_delta") {
    return "streaming";
  }
  if (type === "model_thinking_tick") {
    return "requesting";
  }
```

Update `detailForEvent()` before raw response handling:

```ts
  const visibleText = payload.visible_text;
  if (typeof visibleText === "string") {
    return visibleText;
  }

  const message = payload.message;
  if (typeof message === "string") {
    return message;
  }
```

Inside the main event loop, after `player.lastDetail = detailForEvent(event);`, add:

```ts
      const payload = payloadForEvent(event);
      const requestId =
        typeof payload.request_id === "string" ? payload.request_id : null;
      if (event.type === "model_request_started") {
        player.activeRequestId = requestId;
        player.lastDetail = "";
      }
      if (event.type === "model_response_delta") {
        if (requestId && player.activeRequestId !== requestId) {
          player.activeRequestId = requestId;
          player.lastDetail = "";
        }
        const visibleText =
          typeof payload.visible_text === "string" ? payload.visible_text : "";
        player.lastDetail = `${player.lastDetail}${visibleText}`;
      }
      if (event.type === "action_parsed") {
        player.activeRequestId = null;
      }
```

- [ ] **Step 6: Label streaming in player panel**

In `apps/web/src/features/games/components/LivePlayerPanel.tsx`, add:

```ts
  streaming: "发言中",
```

to `STATUS_LABELS`.

- [ ] **Step 7: Run tests and verify pass**

From repo root, run:

```bash
pnpm --dir apps/web test -- --run src/features/games/hooks/useGameRunEvents.test.tsx src/features/games/liveSpectator.test.ts
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add apps/web/src/features/games/hooks/useGameRunEvents.ts apps/web/src/features/games/liveSpectator.ts apps/web/src/features/games/components/LivePlayerPanel.tsx apps/web/src/features/games/hooks/useGameRunEvents.test.tsx apps/web/src/features/games/liveSpectator.test.ts
git commit -m "feat: track streamed model progress in live state"
```

---

### Task 6: Frontend Director Coalescing And Timeline Filtering

**Files:**
- Modify: `apps/web/src/features/games/liveDirector.ts`
- Modify: `apps/web/src/features/games/hooks/useLiveDirector.ts`
- Modify: `apps/web/src/features/games/components/LiveEventTimeline.tsx`
- Modify: `apps/web/src/pages/LiveGamePage.tsx`
- Modify: `apps/web/src/features/games/liveDirector.test.ts`
- Modify: `apps/web/src/pages/LiveGamePage.test.tsx`

- [ ] **Step 1: Write failing director coalescing test**

Append this test to `apps/web/src/features/games/liveDirector.test.ts`:

```ts
  it("coalesces streaming deltas into the matching request cue", () => {
    const cues = buildDirectorCues([
      event({
        id: 2,
        type: "model_request_started",
        actor: "张三",
        action: "debate",
        payload: { request_id: "req_123", model: "deepseek-chat" },
      }),
      event({
        id: 3,
        type: "model_response_delta",
        actor: "张三",
        action: "debate",
        payload: { request_id: "req_123", visible_text: "我", is_public: true },
      }),
      event({
        id: 4,
        type: "model_response_delta",
        actor: "张三",
        action: "debate",
        payload: { request_id: "req_123", visible_text: "不是狼", is_public: true },
      }),
    ]);

    expect(cues).toHaveLength(1);
    expect(cues[0]).toMatchObject({
      eventId: 2,
      title: "张三 正在发言",
      body: "张三：我不是狼",
      importance: "key",
      compressible: false,
    });
  });
```

Update the import at the top:

```ts
import { buildDirectorCues, toDirectorCue } from "./liveDirector";
```

- [ ] **Step 2: Run director test and verify failure**

From repo root, run:

```bash
pnpm --dir apps/web test -- --run src/features/games/liveDirector.test.ts
```

Expected: FAIL because `buildDirectorCues()` does not exist.

- [ ] **Step 3: Implement `buildDirectorCues()`**

In `apps/web/src/features/games/liveDirector.ts`, export this function above `toDirectorCue()`:

```ts
export function buildDirectorCues(events: LiveGameEvent[]): DirectorCue[] {
  const cues: DirectorCue[] = [];
  const requestCueIndex = new Map<string, number>();

  for (const event of events) {
    const payload = payloadForEvent(event);
    const requestId = stringField(payload, "request_id");

    if (event.type === "model_response_delta") {
      if (!requestId || !requestCueIndex.has(requestId)) {
        continue;
      }
      const visibleText = stringField(payload, "visible_text");
      if (!visibleText) {
        continue;
      }
      const cue = cues[requestCueIndex.get(requestId)!];
      const prefix = cue.body ? "" : `${event.actor || "未知玩家"}：`;
      cue.title = `${event.actor || "未知玩家"} 正在发言`;
      cue.body = `${cue.body}${prefix}${visibleText}`;
      cue.importance = "key";
      cue.durationMs = longTextDuration(cue.body);
      cue.compressible = false;
      continue;
    }

    if (event.type === "model_thinking_tick") {
      if (!requestId || !requestCueIndex.has(requestId)) {
        continue;
      }
      const message = stringField(payload, "message");
      const elapsedMs = payload.elapsed_ms;
      const cue = cues[requestCueIndex.get(requestId)!];
      if (!cue.body && message) {
        cue.body =
          typeof elapsedMs === "number"
            ? `${message}\n已等待 ${Math.round(elapsedMs / 1000)} 秒`
            : message;
      }
      continue;
    }

    const cue = toDirectorCue(event);
    cues.push(cue);
    if (event.type === "model_request_started" && requestId) {
      requestCueIndex.set(requestId, cues.length - 1);
    }
  }

  return cues;
}
```

Add this helper near the other private helpers if it does not already exist:

```ts
function payloadForEvent(event: LiveGameEvent): Record<string, unknown> {
  return isRecord(event.payload) ? event.payload : {};
}
```

If `payloadForEvent()` conflicts with existing local logic, keep one copy and update callers.

- [ ] **Step 4: Use coalesced cues in director hook**

In `apps/web/src/features/games/hooks/useLiveDirector.ts`, change imports:

```ts
import { buildDirectorCues } from "../liveDirector";
```

Replace:

```ts
  const cues = useMemo(() => events.map(toDirectorCue), [events]);
```

with:

```ts
  const cues = useMemo(() => buildDirectorCues(events), [events]);
```

- [ ] **Step 5: Filter timeline noise**

In `apps/web/src/features/games/components/LiveEventTimeline.tsx`, add:

```ts
const HIDDEN_TIMELINE_EVENT_TYPES = new Set([
  "model_response_delta",
  "model_thinking_tick",
]);
```

Inside `LiveEventTimeline`, before the empty-state check, add:

```ts
  const visibleEvents = events.filter(
    (event) => !HIDDEN_TIMELINE_EVENT_TYPES.has(event.type),
  );
```

Use `visibleEvents` for the empty check and `.map()`:

```ts
  if (visibleEvents.length === 0) {
    return <p className="p-4 text-sm text-slate-600">等待实时事件...</p>;
  }

  return (
    <ol className="divide-y divide-slate-200">
      {visibleEvents.map((event) => {
```

- [ ] **Step 6: Update page test to expect streaming body**

In `apps/web/src/pages/LiveGamePage.test.tsx`, add emitted delta events between `model_request_started` and `model_response_received` in the relevant live page test. Use payloads:

```ts
payload: {
  request_id: "req_123",
  visible_text: "我不是狼",
  is_public: true,
}
```

Then add assertions:

```ts
expect(await screen.findByText(/张三：我不是狼/)).toBeInTheDocument();
expect(screen.queryByText("model_response_delta")).not.toBeInTheDocument();
```

- [ ] **Step 7: Run frontend tests**

From repo root, run:

```bash
pnpm --dir apps/web test -- --run src/features/games/liveDirector.test.ts src/pages/LiveGamePage.test.tsx
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add apps/web/src/features/games/liveDirector.ts apps/web/src/features/games/hooks/useLiveDirector.ts apps/web/src/features/games/components/LiveEventTimeline.tsx apps/web/src/pages/LiveGamePage.tsx apps/web/src/features/games/liveDirector.test.ts apps/web/src/pages/LiveGamePage.test.tsx
git commit -m "feat: coalesce streaming events in live director"
```

---

### Task 7: Verification And Polish

**Files:**
- Modify: only files touched by Tasks 1-6 when a verification command reports a concrete failure in that file.

- [ ] **Step 1: Run backend targeted tests**

From `apps/api`, run:

```bash
uv run pytest tests/test_werewolf_lm.py tests/test_werewolf_runner.py tests/test_games_api.py tests/test_live.py -q
```

Expected: PASS.

- [ ] **Step 2: Run frontend targeted tests**

From repo root, run:

```bash
pnpm --dir apps/web test -- --run src/features/games/hooks/useGameRunEvents.test.tsx src/features/games/liveSpectator.test.ts src/features/games/liveDirector.test.ts src/pages/LiveGamePage.test.tsx
```

Expected: PASS.

- [ ] **Step 3: Run full frontend build**

From repo root, run:

```bash
pnpm --dir apps/web build
```

Expected: PASS with Vite build output and no TypeScript errors.

- [ ] **Step 4: Run full backend tests**

From `apps/api`, run:

```bash
uv run pytest -q
```

Expected: PASS.

- [ ] **Step 5: Manual live smoke test**

Start the API and web app using the existing project commands:

```bash
make api
pnpm dev
```

Create a live game from the web UI. During a public speech action, verify:

- The active player enters a streaming/responding visual state.
- The main director stage updates with visible speech text before `model_response_received`.
- The raw timeline does not fill with `model_response_delta` rows.
- The game still reaches `game_completed` or `game_failed` normally.

- [ ] **Step 6: Final commit for any verification fixes**

If Step 1-5 required small fixes, commit them:

```bash
git add apps/api apps/web
git commit -m "fix: polish streaming live experience"
```

If no fixes were needed, skip this commit.

---

## Self-Review Notes

Spec coverage:

- Waiting feedback is covered by `ModelRequestProgress`, `model_thinking_tick`, frontend spectator state, and director cue updates.
- Public text streaming is covered by provider `stream_json()`, `VisibleJsonFieldExtractor`, `model_response_delta`, and director coalescing.
- Private action safety is covered by `action_visible_stream_field()` tests and suppression tests for `remove`.
- Full JSON authority is preserved because `generate_action_with_events()` still parses the full `raw_response` before returning a value.
- SSE architecture is preserved; no WebSocket work is planned.
- Timeline noise control is covered by `LiveEventTimeline` filtering.

Placeholder scan:

- The plan has no intentionally empty implementation sections.
- Each task includes exact files, test snippets, implementation snippets, commands, and expected outcomes.

Type consistency:

- Backend request IDs use `request_id`.
- Frontend payload reads `request_id`, `visible_text`, `elapsed_ms`, and `message`.
- New frontend status is `streaming`, with `LivePlayerPanel` label `发言中`.
