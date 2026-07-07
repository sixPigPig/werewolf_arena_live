# Live Voice Streaming Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add opt-in, near-real-time TTS voice playback to the mobile live page through a backend Volcengine WebSocket proxy.

**Architecture:** Keep the existing SSE live event stream for match state and subtitles. Add a backend `/voice-stream` WebSocket that filters public live events, streams text to Volcengine TTS, and forwards audio chunk messages to the browser. The mobile frontend adds a voice hook and one compact control while preserving subtitle-only fallback.

**Tech Stack:** FastAPI WebSocket routes, Pydantic settings, Volcengine Ark TTS 2.0 WebSocket protocol, Python `websockets`, React 19, Vitest, Testing Library.

---

## File Structure

- Modify `apps/api/pyproject.toml` and `apps/api/uv.lock`: add the `websockets` client dependency for backend outbound TTS connections.
- Modify `apps/api/.env.example`: document all `ARK_TTS_*` configuration values.
- Modify `apps/api/app/core/config.py`: parse TTS settings.
- Create `apps/api/app/werewolf/voice.py`: pure voice domain logic, event filtering, text chunking, utterance metadata, and WebSocket message helpers.
- Create `apps/api/app/werewolf/volcengine_tts.py`: Volcengine adapter that hides vendor headers, session lifecycle, and protocol helper usage.
- Create `apps/api/app/werewolf/voice_stream.py`: run-level voice stream coordinator that subscribes to live events and bridges utterances to the adapter.
- Modify `apps/api/app/api/routes/games.py`: add `/runs/{run_id}/voice-stream`, expose voice settings through dependencies, and keep existing SSE unchanged.
- Create `apps/api/tests/test_voice.py`: pure backend unit tests for filtering, chunking, and message serialization.
- Create `apps/api/tests/test_voice_stream_api.py`: FastAPI WebSocket route tests with a fake voice streamer.
- Create `packages/game-client/src/live/liveVoiceStream.ts`: browser WebSocket URL, message types, audio queue reducer, and React hook.
- Modify `packages/game-client/src/live/index.ts`: export voice stream utilities.
- Create `packages/game-client/src/live/liveVoiceStream.test.tsx`: hook/reducer tests.
- Modify `apps/mobile-web/src/pages/LivePage.tsx`: instantiate `useLiveVoiceStream` and pass voice state/actions to theater controls.
- Modify `apps/mobile-web/src/components/MobileLiveTheater.tsx`: add the voice button and status label.
- Modify `apps/mobile-web/src/components/MobileLiveTheater.test.tsx` if needed, otherwise extend `apps/mobile-web/src/pages/LivePage.test.tsx`: cover control states in the rendered page.
- Modify `apps/mobile-web/src/styles/index.css`: add small control-state styles only if existing button classes need a voice state variant.

## Task 1: Backend Settings And Dependency

**Files:**
- Modify: `apps/api/pyproject.toml`
- Modify: `apps/api/uv.lock`
- Modify: `apps/api/.env.example`
- Modify: `apps/api/app/core/config.py`
- Test: `apps/api/tests/test_config.py`

- [ ] **Step 1: Write failing settings tests**

Append these tests to `apps/api/tests/test_config.py`:

```python
def test_settings_defaults_disable_tts() -> None:
    settings = Settings(_env_file=None)

    assert settings.ark_tts_enabled is False
    assert settings.ark_tts_api_key == ""
    assert settings.ark_tts_resource_id == "seed-tts-2.0"
    assert (
        settings.ark_tts_ws_url
        == "wss://openspeech.bytedance.com/api/v3/plan/tts/bidirection"
    )
    assert settings.ark_tts_audio_format == "mp3"
    assert settings.ark_tts_sample_rate == 24000


def test_settings_reads_tts_env_values(monkeypatch) -> None:
    monkeypatch.setenv("ARK_TTS_ENABLED", "true")
    monkeypatch.setenv("ARK_TTS_API_KEY", "ark-test-key")
    monkeypatch.setenv("ARK_TTS_PLAYER_SPEAKER", "player-speaker")
    monkeypatch.setenv("ARK_TTS_JUDGE_SPEAKER", "judge-speaker")
    monkeypatch.setenv("ARK_TTS_SAMPLE_RATE", "16000")

    settings = Settings(_env_file=None)

    assert settings.ark_tts_enabled is True
    assert settings.ark_tts_api_key == "ark-test-key"
    assert settings.ark_tts_player_speaker == "player-speaker"
    assert settings.ark_tts_judge_speaker == "judge-speaker"
    assert settings.ark_tts_sample_rate == 16000
```

- [ ] **Step 2: Run the failing tests**

Run:

```bash
cd apps/api && .venv/bin/python -m pytest tests/test_config.py -q
```

Expected: the two new tests fail because the `Settings` fields do not exist.

- [ ] **Step 3: Add backend settings**

In `apps/api/app/core/config.py`, add these fields to `Settings` after `werewolf_logs_dir`:

```python
    ark_tts_enabled: bool = False
    ark_tts_api_key: str = ""
    ark_tts_resource_id: str = "seed-tts-2.0"
    ark_tts_ws_url: str = "wss://openspeech.bytedance.com/api/v3/plan/tts/bidirection"
    ark_tts_player_speaker: str = "zh_female_gaolengyujie_uranus_bigtts"
    ark_tts_judge_speaker: str = "zh_female_vv_uranus_bigtts"
    ark_tts_audio_format: str = "mp3"
    ark_tts_sample_rate: int = 24000
```

- [ ] **Step 4: Add the dependency and lockfile update**

In `apps/api/pyproject.toml`, add `"websockets"` to `[project].dependencies`.

Run:

```bash
cd apps/api && uv lock
```

Expected: `apps/api/uv.lock` updates and includes `websockets`.

- [ ] **Step 5: Document env values**

Append to `apps/api/.env.example`:

```env
ARK_TTS_ENABLED=false
ARK_TTS_API_KEY=
ARK_TTS_RESOURCE_ID=seed-tts-2.0
ARK_TTS_WS_URL=wss://openspeech.bytedance.com/api/v3/plan/tts/bidirection
ARK_TTS_PLAYER_SPEAKER=zh_female_gaolengyujie_uranus_bigtts
ARK_TTS_JUDGE_SPEAKER=zh_female_vv_uranus_bigtts
ARK_TTS_AUDIO_FORMAT=mp3
ARK_TTS_SAMPLE_RATE=24000
```

- [ ] **Step 6: Run settings tests**

Run:

```bash
cd apps/api && .venv/bin/python -m pytest tests/test_config.py -q
```

Expected: all settings tests pass.

- [ ] **Step 7: Commit**

```bash
git add apps/api/pyproject.toml apps/api/uv.lock apps/api/.env.example apps/api/app/core/config.py apps/api/tests/test_config.py
git commit -m "feat(api): add live voice settings"
```

## Task 2: Backend Voice Domain Logic

**Files:**
- Create: `apps/api/app/werewolf/voice.py`
- Test: `apps/api/tests/test_voice.py`

- [ ] **Step 1: Write failing pure unit tests**

Create `apps/api/tests/test_voice.py`:

```python
from app.werewolf.live import LiveEvent
from app.werewolf.voice import (
    VoiceSpeakerConfig,
    build_voice_messages,
    chunk_text_for_tts,
    event_to_voice_utterance,
    is_public_speech_event,
)


def live_event(
    event_id: int,
    event_type: str,
    *,
    actor: str | None = None,
    action: str | None = None,
    payload: dict | None = None,
    phase: str | None = None,
) -> LiveEvent:
    return LiveEvent(
        id=event_id,
        type=event_type,
        run_id="run_1",
        session_id="game_1",
        created_at="2026-07-07T00:00:00Z",
        phase=phase,
        actor=actor,
        action=action,
        payload=payload or {},
    )


def test_public_speech_event_matches_supported_actions() -> None:
    event = live_event(
        4,
        "model_response_delta",
        actor="阿青",
        action="debate",
        payload={"request_id": "req-1", "visible_text": "我先发言。"},
    )

    assert is_public_speech_event(event) is True


def test_private_or_non_speech_event_is_not_public_speech() -> None:
    night_event = live_event(
        5,
        "model_response_delta",
        actor="狼人",
        action="werewolf_discussion",
        payload={"request_id": "req-2", "visible_text": "今晚刀谁。"},
    )
    state_event = live_event(6, "state_updated", payload={"role": "werewolf"})

    assert is_public_speech_event(night_event) is False
    assert is_public_speech_event(state_event) is False


def test_chunk_text_for_tts_keeps_sentence_punctuation() -> None:
    chunks = chunk_text_for_tts("我是阿青，我先听后置位发言。警上信息不多！", max_chars=12)

    assert chunks == ["我是阿青，", "我先听后置位发言。", "警上信息不多！"]


def test_event_to_player_voice_utterance_uses_visible_text() -> None:
    config = VoiceSpeakerConfig(player_speaker="player", judge_speaker="judge")
    event = live_event(
        8,
        "model_response_delta",
        actor="阿青",
        action="sheriff_speech",
        payload={"request_id": "req-8", "visible_text": "我竞选警长。"},
    )

    utterance = event_to_voice_utterance(event, config)

    assert utterance is not None
    assert utterance.source_event_id == 8
    assert utterance.request_id == "req-8"
    assert utterance.speaker_kind == "player"
    assert utterance.speaker_name == "阿青"
    assert utterance.speaker == "player"
    assert utterance.text == "我竞选警长。"


def test_event_to_judge_voice_utterance_for_phase_start_is_short() -> None:
    config = VoiceSpeakerConfig(player_speaker="player", judge_speaker="judge")
    event = live_event(9, "phase_started", phase="night")

    utterance = event_to_voice_utterance(event, config)

    assert utterance is not None
    assert utterance.speaker_kind == "judge"
    assert utterance.speaker_name == "法官"
    assert utterance.speaker == "judge"
    assert utterance.text == "天黑请闭眼。"


def test_voice_messages_serialize_audio_chunks() -> None:
    start, chunk, end = build_voice_messages(
        utterance_id="voice_1",
        source_event_id=10,
        speaker_kind="player",
        speaker_name="阿青",
        audio=b"abc",
        mime_type="audio/mpeg",
        duration_ms=1200,
    )

    assert start["type"] == "voice_start"
    assert start["source_event_id"] == 10
    assert chunk == {
        "type": "audio_chunk",
        "utterance_id": "voice_1",
        "mime_type": "audio/mpeg",
        "data": "YWJj",
    }
    assert end == {"type": "voice_end", "utterance_id": "voice_1", "duration_ms": 1200}
```

- [ ] **Step 2: Run failing tests**

Run:

```bash
cd apps/api && .venv/bin/python -m pytest tests/test_voice.py -q
```

Expected: import fails because `app.werewolf.voice` does not exist.

- [ ] **Step 3: Implement pure voice logic**

Create `apps/api/app/werewolf/voice.py`:

```python
from __future__ import annotations

import base64
import re
import uuid
from dataclasses import dataclass
from typing import Any, Literal

from app.werewolf.live import LiveEvent

SpeakerKind = Literal["player", "judge"]
PUBLIC_SPEECH_ACTIONS = {"debate", "sheriff_speech", "sheriff_pk_speech"}
SENTENCE_PATTERN = re.compile(r"[^，。！？；,.!?;]+[，。！？；,.!?;]?")


@dataclass(frozen=True)
class VoiceSpeakerConfig:
    player_speaker: str
    judge_speaker: str


@dataclass(frozen=True)
class VoiceUtterance:
    utterance_id: str
    run_id: str
    source_event_id: int
    request_id: str | None
    speaker_kind: SpeakerKind
    speaker_name: str
    speaker: str
    text: str
    action: str | None


def is_public_speech_event(event: LiveEvent) -> bool:
    return event.type == "model_response_delta" and event.action in PUBLIC_SPEECH_ACTIONS


def chunk_text_for_tts(text: str, *, max_chars: int = 24) -> list[str]:
    normalized = " ".join(text.split()).strip()
    if not normalized:
        return []

    chunks: list[str] = []
    for phrase in SENTENCE_PATTERN.findall(normalized) or [normalized]:
        phrase = phrase.strip()
        if not phrase:
            continue
        if len(phrase) <= max_chars:
            chunks.append(phrase)
            continue
        for start in range(0, len(phrase), max_chars):
            chunks.append(phrase[start : start + max_chars])
    return chunks


def event_to_voice_utterance(
    event: LiveEvent,
    config: VoiceSpeakerConfig,
) -> VoiceUtterance | None:
    if is_public_speech_event(event):
        visible_text = _string_payload(event, "visible_text").strip()
        if not visible_text:
            return None
        speaker_name = event.actor or "当前玩家"
        return VoiceUtterance(
            utterance_id=f"voice_{uuid.uuid4().hex[:12]}",
            run_id=event.run_id,
            source_event_id=event.id,
            request_id=_string_payload(event, "request_id") or None,
            speaker_kind="player",
            speaker_name=speaker_name,
            speaker=config.player_speaker,
            text=visible_text,
            action=event.action,
        )

    judge_text = _judge_text_for_event(event)
    if judge_text is None:
        return None

    return VoiceUtterance(
        utterance_id=f"voice_{uuid.uuid4().hex[:12]}",
        run_id=event.run_id,
        source_event_id=event.id,
        request_id=None,
        speaker_kind="judge",
        speaker_name="法官",
        speaker=config.judge_speaker,
        text=judge_text,
        action=event.action,
    )


def build_voice_messages(
    *,
    utterance_id: str,
    source_event_id: int,
    speaker_kind: SpeakerKind,
    speaker_name: str,
    audio: bytes,
    mime_type: str,
    duration_ms: int,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    return (
        {
            "type": "voice_start",
            "utterance_id": utterance_id,
            "source_event_id": source_event_id,
            "speaker_kind": speaker_kind,
            "speaker_name": speaker_name,
            "mime_type": mime_type,
        },
        {
            "type": "audio_chunk",
            "utterance_id": utterance_id,
            "mime_type": mime_type,
            "data": base64.b64encode(audio).decode("ascii"),
        },
        {
            "type": "voice_end",
            "utterance_id": utterance_id,
            "duration_ms": duration_ms,
        },
    )


def _judge_text_for_event(event: LiveEvent) -> str | None:
    if event.type == "phase_started" and event.phase == "night":
        return "天黑请闭眼。"
    if event.type == "phase_started" and event.phase == "day":
        return "天亮了，进入白天发言。"
    if event.type == "game_completed":
        winner = _string_payload(event, "winner") or "胜利阵营"
        return f"对局结束，{winner}获胜。"
    if event.type == "game_failed":
        return "对局异常中断。"
    return None


def _string_payload(event: LiveEvent, key: str) -> str:
    value = event.payload.get(key)
    return value if isinstance(value, str) else ""
```

- [ ] **Step 4: Run pure tests**

Run:

```bash
cd apps/api && .venv/bin/python -m pytest tests/test_voice.py -q
```

Expected: all `test_voice.py` tests pass.

- [ ] **Step 5: Commit**

```bash
git add apps/api/app/werewolf/voice.py apps/api/tests/test_voice.py
git commit -m "feat(api): derive live voice utterances"
```

## Task 3: Volcengine TTS Adapter

**Files:**
- Create: `apps/api/app/werewolf/volcengine_tts_protocol.py`
- Create: `apps/api/app/werewolf/volcengine_tts.py`
- Test: `apps/api/tests/test_volcengine_tts.py`

- [ ] **Step 1: Vendor the official protocol helper**

Run:

```bash
curl -L https://arkdoc.tos-cn-beijing.volces.com/files/CodingPlan/protocols.py \
  -o apps/api/app/werewolf/volcengine_tts_protocol.py
```

Expected: the file exists and imports `websockets`.

Run:

```bash
cd apps/api && .venv/bin/ruff format app/werewolf/volcengine_tts_protocol.py
```

Expected: formatting succeeds. If ruff reports style issues inside the vendored helper that would require invasive changes, keep the file as-is and add `# ruff: noqa` as the first line.

- [ ] **Step 2: Write failing adapter tests**

Create `apps/api/tests/test_volcengine_tts.py`:

```python
from app.werewolf.volcengine_tts import (
    VolcengineTtsConfig,
    build_tts_headers,
    build_tts_request,
    mime_type_for_format,
)


def test_build_tts_headers_uses_connect_id_and_resource_id() -> None:
    config = VolcengineTtsConfig(
        enabled=True,
        api_key="ark-key",
        resource_id="seed-tts-2.0",
        ws_url="wss://example.test",
        player_speaker="player",
        judge_speaker="judge",
        audio_format="mp3",
        sample_rate=24000,
    )

    headers = build_tts_headers(config, connect_id="connect-1")

    assert headers == {
        "X-Api-Key": "ark-key",
        "X-Api-Resource-Id": "seed-tts-2.0",
        "X-Api-Connect-Id": "connect-1",
        "X-Control-Require-Usage-Tokens-Return": "*",
    }


def test_build_tts_request_contains_speaker_text_and_audio_params() -> None:
    request = build_tts_request(
        speaker="player",
        text="我先发言。",
        audio_format="mp3",
        sample_rate=24000,
    )

    assert request == {
        "req_params": {
            "speaker": "player",
            "text": "我先发言。",
            "audio_params": {
                "format": "mp3",
                "sample_rate": 24000,
                "enable_timestamp": False,
            },
        }
    }


def test_mime_type_for_supported_formats() -> None:
    assert mime_type_for_format("mp3") == "audio/mpeg"
    assert mime_type_for_format("wav") == "audio/wav"
    assert mime_type_for_format("pcm") == "audio/L16"
```

- [ ] **Step 3: Run failing adapter tests**

Run:

```bash
cd apps/api && .venv/bin/python -m pytest tests/test_volcengine_tts.py -q
```

Expected: import fails because `app.werewolf.volcengine_tts` does not exist.

- [ ] **Step 4: Implement adapter shell**

Create `apps/api/app/werewolf/volcengine_tts.py`:

```python
from __future__ import annotations

import json
import logging
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

import websockets

from app.werewolf import volcengine_tts_protocol as protocol

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class VolcengineTtsConfig:
    enabled: bool
    api_key: str
    resource_id: str
    ws_url: str
    player_speaker: str
    judge_speaker: str
    audio_format: str
    sample_rate: int

    @property
    def available(self) -> bool:
        return self.enabled and bool(self.api_key.strip())


def build_tts_headers(
    config: VolcengineTtsConfig,
    *,
    connect_id: str,
) -> dict[str, str]:
    return {
        "X-Api-Key": config.api_key,
        "X-Api-Resource-Id": config.resource_id,
        "X-Api-Connect-Id": connect_id,
        "X-Control-Require-Usage-Tokens-Return": "*",
    }


def build_tts_request(
    *,
    speaker: str,
    text: str,
    audio_format: str,
    sample_rate: int,
) -> dict[str, Any]:
    return {
        "req_params": {
            "speaker": speaker,
            "text": text,
            "audio_params": {
                "format": audio_format,
                "sample_rate": sample_rate,
                "enable_timestamp": False,
            },
        }
    }


def mime_type_for_format(audio_format: str) -> str:
    formats = {
        "mp3": "audio/mpeg",
        "wav": "audio/wav",
        "pcm": "audio/L16",
    }
    return formats.get(audio_format.lower(), "application/octet-stream")


class VolcengineTtsClient:
    def __init__(self, config: VolcengineTtsConfig) -> None:
        self.config = config

    async def synthesize(
        self,
        *,
        speaker: str,
        text_chunks: list[str],
    ) -> AsyncIterator[bytes]:
        if not self.config.available:
            raise RuntimeError("Volcengine TTS is not configured")

        connect_id = str(uuid.uuid4())
        headers = build_tts_headers(self.config, connect_id=connect_id)
        logger.info("Opening Volcengine TTS session", extra={"connect_id": connect_id})

        async with websockets.connect(
            self.config.ws_url,
            additional_headers=headers,
            max_size=10 * 1024 * 1024,
        ) as websocket:
            session_id = str(uuid.uuid4())
            await protocol.start_connection(websocket)
            await protocol.wait_for_event(
                websocket,
                protocol.MsgType.FullServerResponse,
                protocol.EventType.ConnectionStarted,
            )
            await protocol.start_session(websocket, b"{}", session_id)
            await protocol.wait_for_event(
                websocket,
                protocol.MsgType.FullServerResponse,
                protocol.EventType.SessionStarted,
            )

            for text in text_chunks:
                request = build_tts_request(
                    speaker=speaker,
                    text=text,
                    audio_format=self.config.audio_format,
                    sample_rate=self.config.sample_rate,
                )
                await protocol.task_request(
                    websocket,
                    json.dumps(request, ensure_ascii=False).encode("utf-8"),
                    session_id,
                )

            await protocol.finish_session(websocket, session_id)

            while True:
                message = await protocol.receive_message(websocket)
                if message.type == protocol.MsgType.AudioOnlyServer:
                    yield message.payload
                    continue
                if message.type == protocol.MsgType.FullServerResponse:
                    if getattr(message, "event", None) == protocol.EventType.SessionFinished:
                        break
                    continue
                if message.type == protocol.MsgType.Error:
                    raise RuntimeError("Volcengine TTS returned an error")
                break

            await protocol.finish_connection(websocket)
```

- [ ] **Step 5: Run adapter tests**

Run:

```bash
cd apps/api && .venv/bin/python -m pytest tests/test_volcengine_tts.py -q
```

Expected: adapter tests pass.

- [ ] **Step 6: Run a static import check**

Run:

```bash
cd apps/api && .venv/bin/python - <<'PY'
from app.werewolf.volcengine_tts import VolcengineTtsClient
print(VolcengineTtsClient.__name__)
PY
```

Expected output contains `VolcengineTtsClient`.

- [ ] **Step 7: Commit**

```bash
git add apps/api/app/werewolf/volcengine_tts_protocol.py apps/api/app/werewolf/volcengine_tts.py apps/api/tests/test_volcengine_tts.py
git commit -m "feat(api): add volcengine tts adapter"
```

## Task 4: Backend Voice Stream Coordinator And API Route

**Files:**
- Create: `apps/api/app/werewolf/voice_stream.py`
- Modify: `apps/api/app/api/routes/games.py`
- Test: `apps/api/tests/test_voice_stream_api.py`

- [ ] **Step 1: Write failing API tests**

Create `apps/api/tests/test_voice_stream_api.py`:

```python
from collections.abc import Generator

from fastapi.testclient import TestClient

from app.api.routes.games import get_live_registry, get_voice_streamer
from app.main import app
from app.werewolf.live import LiveRunRegistry


class FakeVoiceStreamer:
    def __init__(self, *, available: bool = True) -> None:
        self.available = available

    async def stream_run(self, run_id: str, websocket) -> None:
        if not self.available:
            await websocket.send_json({"type": "voice_unavailable"})
            return
        await websocket.send_json(
            {
                "type": "voice_start",
                "utterance_id": "voice_1",
                "source_event_id": 2,
                "speaker_kind": "player",
                "speaker_name": "阿青",
                "mime_type": "audio/mpeg",
            }
        )
        await websocket.send_json(
            {
                "type": "audio_chunk",
                "utterance_id": "voice_1",
                "mime_type": "audio/mpeg",
                "data": "YWJj",
            }
        )
        await websocket.send_json(
            {"type": "voice_end", "utterance_id": "voice_1", "duration_ms": 1000}
        )


def classic_rule_kwargs() -> dict:
    return {
        "rule_set_id": "classic_8",
        "rule_set": {
            "id": "classic_8",
            "version": "2026.04",
            "name": "经典 8 人局",
            "player_count": 8,
            "roles": [],
        },
    }


def override_registry(registry: LiveRunRegistry) -> None:
    app.dependency_overrides[get_live_registry] = lambda: registry


def override_streamer(streamer: FakeVoiceStreamer) -> None:
    app.dependency_overrides[get_voice_streamer] = lambda: streamer


def client_with_overrides() -> Generator[TestClient, None, None]:
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def test_voice_stream_route_forwards_stream_messages() -> None:
    registry = LiveRunRegistry()
    run = registry.create_run(
        session_id="game_1200abcd",
        villager_model="deepseek-chat",
        werewolf_model="deepseek-chat",
        seed=21,
        max_rounds=8,
        **classic_rule_kwargs(),
    )
    override_registry(registry)
    override_streamer(FakeVoiceStreamer())

    with next(client_with_overrides()) as client:
        with client.websocket_connect(f"/api/v1/games/runs/{run.run_id}/voice-stream") as ws:
            assert ws.receive_json()["type"] == "voice_start"
            assert ws.receive_json()["type"] == "audio_chunk"
            assert ws.receive_json()["type"] == "voice_end"


def test_voice_stream_route_reports_unknown_run() -> None:
    override_registry(LiveRunRegistry())
    override_streamer(FakeVoiceStreamer())

    with next(client_with_overrides()) as client:
        with client.websocket_connect("/api/v1/games/runs/run_missing/voice-stream") as ws:
            assert ws.receive_json() == {
                "type": "voice_error",
                "message": "Game run not found",
            }


def test_voice_stream_route_reports_unavailable_when_disabled() -> None:
    registry = LiveRunRegistry()
    run = registry.create_run(
        session_id="game_1200abcd",
        villager_model="deepseek-chat",
        werewolf_model="deepseek-chat",
        seed=21,
        max_rounds=8,
        **classic_rule_kwargs(),
    )
    override_registry(registry)
    override_streamer(FakeVoiceStreamer(available=False))

    with next(client_with_overrides()) as client:
        with client.websocket_connect(f"/api/v1/games/runs/{run.run_id}/voice-stream") as ws:
            assert ws.receive_json() == {"type": "voice_unavailable"}
```

- [ ] **Step 2: Run failing API tests**

Run:

```bash
cd apps/api && .venv/bin/python -m pytest tests/test_voice_stream_api.py -q
```

Expected: import fails because `get_voice_streamer` does not exist.

- [ ] **Step 3: Implement coordinator**

Create `apps/api/app/werewolf/voice_stream.py`:

```python
from __future__ import annotations

import logging
import asyncio
import time
from collections.abc import Callable

from fastapi import WebSocket

from app.werewolf.live import LiveRunRegistry
from app.werewolf.voice import (
    VoiceSpeakerConfig,
    build_voice_messages,
    chunk_text_for_tts,
    event_to_voice_utterance,
)
from app.werewolf.volcengine_tts import VolcengineTtsClient, VolcengineTtsConfig, mime_type_for_format

logger = logging.getLogger(__name__)


class LiveVoiceStreamService:
    def __init__(
        self,
        *,
        registry: LiveRunRegistry,
        config: VolcengineTtsConfig,
        client_factory: Callable[[VolcengineTtsConfig], VolcengineTtsClient] = VolcengineTtsClient,
    ) -> None:
        self.registry = registry
        self.config = config
        self.client_factory = client_factory

    @property
    def available(self) -> bool:
        return self.config.available

    async def stream_run(self, run_id: str, websocket: WebSocket) -> None:
        if not self.available:
            await websocket.send_json({"type": "voice_unavailable"})
            return

        subscriber = self.registry.subscribe(run_id)
        speaker_config = VoiceSpeakerConfig(
            player_speaker=self.config.player_speaker,
            judge_speaker=self.config.judge_speaker,
        )
        try:
            while True:
                event = await asyncio.to_thread(subscriber.get)
                utterance = event_to_voice_utterance(event, speaker_config)
                if utterance is None:
                    continue
                chunks = chunk_text_for_tts(utterance.text)
                if not chunks:
                    continue
                await self._stream_utterance(websocket, utterance, chunks)
                if event.type in {"game_completed", "game_failed"}:
                    break
        finally:
            self.registry.unsubscribe(run_id, subscriber)

    async def _stream_utterance(self, websocket: WebSocket, utterance, chunks: list[str]) -> None:
        started_at = time.monotonic()
        mime_type = mime_type_for_format(self.config.audio_format)
        client = self.client_factory(self.config)
        await websocket.send_json(
            {
                "type": "voice_start",
                "utterance_id": utterance.utterance_id,
                "source_event_id": utterance.source_event_id,
                "speaker_kind": utterance.speaker_kind,
                "speaker_name": utterance.speaker_name,
                "mime_type": mime_type,
            }
        )
        try:
            async for audio in client.synthesize(speaker=utterance.speaker, text_chunks=chunks):
                _start, chunk_message, _end = build_voice_messages(
                    utterance_id=utterance.utterance_id,
                    source_event_id=utterance.source_event_id,
                    speaker_kind=utterance.speaker_kind,
                    speaker_name=utterance.speaker_name,
                    audio=audio,
                    mime_type=mime_type,
                    duration_ms=0,
                )
                await websocket.send_json(chunk_message)
        except Exception:
            logger.exception("Voice synthesis failed", extra={"run_id": utterance.run_id})
            await websocket.send_json(
                {
                    "type": "voice_error",
                    "utterance_id": utterance.utterance_id,
                    "source_event_id": utterance.source_event_id,
                    "message": "Voice synthesis failed",
                }
            )
            return

        await websocket.send_json(
            {
                "type": "voice_end",
                "utterance_id": utterance.utterance_id,
                "duration_ms": int((time.monotonic() - started_at) * 1000),
            }
        )
```

- [ ] **Step 4: Wire the route**

In `apps/api/app/api/routes/games.py`, extend imports:

```python
from fastapi import WebSocket
from app.core.config import settings
from app.werewolf.voice_stream import LiveVoiceStreamService
from app.werewolf.volcengine_tts import VolcengineTtsConfig
```

Add dependencies near `get_live_registry`:

```python
def get_tts_config() -> VolcengineTtsConfig:
    return VolcengineTtsConfig(
        enabled=settings.ark_tts_enabled,
        api_key=settings.ark_tts_api_key,
        resource_id=settings.ark_tts_resource_id,
        ws_url=settings.ark_tts_ws_url,
        player_speaker=settings.ark_tts_player_speaker,
        judge_speaker=settings.ark_tts_judge_speaker,
        audio_format=settings.ark_tts_audio_format,
        sample_rate=settings.ark_tts_sample_rate,
    )


def get_voice_streamer(
    registry: Annotated[LiveRunRegistry, Depends(get_live_registry)],
    config: Annotated[VolcengineTtsConfig, Depends(get_tts_config)],
) -> LiveVoiceStreamService:
    return LiveVoiceStreamService(registry=registry, config=config)
```

Add the WebSocket route after `stream_game_run_events`:

```python
@router.websocket("/runs/{run_id}/voice-stream")
async def stream_game_run_voice(
    websocket: WebSocket,
    run_id: str,
    registry: Annotated[LiveRunRegistry, Depends(get_live_registry)],
    streamer: Annotated[LiveVoiceStreamService, Depends(get_voice_streamer)],
) -> None:
    await websocket.accept()
    if registry.try_get_run(run_id) is None:
        await websocket.send_json({"type": "voice_error", "message": "Game run not found"})
        await websocket.close()
        return
    await streamer.stream_run(run_id, websocket)
```

- [ ] **Step 5: Run API route tests**

Run:

```bash
cd apps/api && .venv/bin/python -m pytest tests/test_voice_stream_api.py -q
```

Expected: route tests pass.

- [ ] **Step 6: Run backend voice-related tests**

Run:

```bash
cd apps/api && .venv/bin/python -m pytest tests/test_config.py tests/test_voice.py tests/test_volcengine_tts.py tests/test_voice_stream_api.py -q
```

Expected: all selected backend tests pass.

- [ ] **Step 7: Commit**

```bash
git add apps/api/app/werewolf/voice_stream.py apps/api/app/api/routes/games.py apps/api/tests/test_voice_stream_api.py
git commit -m "feat(api): stream live voice over websocket"
```

## Task 5: Game Client Voice Hook And Queue

**Files:**
- Create: `packages/game-client/src/live/liveVoiceStream.ts`
- Modify: `packages/game-client/src/live/index.ts`
- Test: `packages/game-client/src/live/liveVoiceStream.test.tsx`

- [ ] **Step 1: Write failing hook and reducer tests**

Create `packages/game-client/src/live/liveVoiceStream.test.tsx`:

```tsx
import { act, renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  createVoiceQueue,
  enqueueVoiceMessage,
  resolveVoiceStreamUrl,
  useLiveVoiceStream,
  type LiveVoiceMessage,
} from "./liveVoiceStream";

class MockWebSocket {
  static instances: MockWebSocket[] = [];
  onopen: (() => void) | null = null;
  onmessage: ((event: MessageEvent) => void) | null = null;
  onerror: (() => void) | null = null;
  onclose: (() => void) | null = null;
  close = vi.fn();
  url: string;

  constructor(url: string) {
    this.url = url;
    MockWebSocket.instances.push(this);
  }

  emit(message: LiveVoiceMessage) {
    this.onmessage?.({ data: JSON.stringify(message) } as MessageEvent);
  }
}

describe("live voice stream", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    MockWebSocket.instances = [];
  });

  it("builds a websocket url from api base url", () => {
    expect(resolveVoiceStreamUrl("run-1", "http://localhost:8000")).toBe(
      "ws://localhost:8000/api/v1/games/runs/run-1/voice-stream",
    );
    expect(resolveVoiceStreamUrl("run-1", "https://example.com")).toBe(
      "wss://example.com/api/v1/games/runs/run-1/voice-stream",
    );
  });

  it("groups chunks by utterance and marks completed audio", () => {
    let queue = createVoiceQueue();
    queue = enqueueVoiceMessage(queue, {
      type: "voice_start",
      utterance_id: "voice-1",
      source_event_id: 4,
      speaker_kind: "player",
      speaker_name: "阿青",
      mime_type: "audio/mpeg",
    });
    queue = enqueueVoiceMessage(queue, {
      type: "audio_chunk",
      utterance_id: "voice-1",
      mime_type: "audio/mpeg",
      data: "YWJj",
    });
    queue = enqueueVoiceMessage(queue, {
      type: "voice_end",
      utterance_id: "voice-1",
      duration_ms: 1000,
    });

    expect(queue.items).toHaveLength(1);
    expect(queue.items[0]).toMatchObject({
      utteranceId: "voice-1",
      sourceEventId: 4,
      speakerName: "阿青",
      status: "ready",
    });
    expect(queue.items[0].chunks).toEqual(["YWJj"]);
  });

  it("does not connect until enabled", () => {
    vi.stubGlobal("WebSocket", MockWebSocket);

    renderHook(() =>
      useLiveVoiceStream("run-1", {
        currentEventId: 1,
        enabled: false,
        isPaused: false,
      }),
    );

    expect(MockWebSocket.instances).toHaveLength(0);
  });

  it("connects when enabled and records playing speaker after a start message", () => {
    vi.stubGlobal("WebSocket", MockWebSocket);

    const { result } = renderHook(() =>
      useLiveVoiceStream("run-1", {
        currentEventId: 4,
        enabled: true,
        isPaused: false,
      }),
    );

    act(() => {
      MockWebSocket.instances[0].onopen?.();
      MockWebSocket.instances[0].emit({
        type: "voice_start",
        utterance_id: "voice-1",
        source_event_id: 4,
        speaker_kind: "player",
        speaker_name: "阿青",
        mime_type: "audio/mpeg",
      });
    });

    expect(result.current.connectionState).toBe("open");
    expect(result.current.currentSpeakerName).toBe("阿青");
  });
});
```

- [ ] **Step 2: Run failing package tests**

Run:

```bash
pnpm --dir packages/game-client test -- --run liveVoiceStream
```

Expected: import fails because `liveVoiceStream.ts` does not exist.

- [ ] **Step 3: Implement voice stream utilities and hook**

Create `packages/game-client/src/live/liveVoiceStream.ts`:

```ts
import { useEffect, useMemo, useReducer, useState } from "react";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "";
const STALE_EVENT_DISTANCE = 8;

export type LiveVoiceConnectionState =
  | "idle"
  | "connecting"
  | "open"
  | "error"
  | "closed"
  | "unavailable";

export type LiveVoiceMessage =
  | {
      type: "voice_start";
      utterance_id: string;
      source_event_id: number;
      speaker_kind: "player" | "judge";
      speaker_name: string;
      mime_type: string;
    }
  | {
      type: "audio_chunk";
      utterance_id: string;
      mime_type: string;
      data: string;
    }
  | {
      type: "voice_end";
      utterance_id: string;
      duration_ms: number;
    }
  | {
      type: "voice_error";
      utterance_id?: string;
      source_event_id?: number;
      message: string;
    }
  | {
      type: "voice_unavailable";
    };

export type LiveVoiceQueueItem = {
  utteranceId: string;
  sourceEventId: number;
  speakerKind: "player" | "judge";
  speakerName: string;
  mimeType: string;
  chunks: string[];
  status: "receiving" | "ready" | "error";
};

export type LiveVoiceQueue = {
  items: LiveVoiceQueueItem[];
  errors: string[];
};

export function resolveVoiceStreamUrl(runId: string, baseUrl = API_BASE_URL) {
  const base = baseUrl || window.location.origin;
  const url = new URL(`/api/v1/games/runs/${runId}/voice-stream`, base);
  url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
  return url.toString();
}

export function createVoiceQueue(): LiveVoiceQueue {
  return { items: [], errors: [] };
}

export function enqueueVoiceMessage(
  queue: LiveVoiceQueue,
  message: LiveVoiceMessage,
): LiveVoiceQueue {
  if (message.type === "voice_unavailable") {
    return queue;
  }
  if (message.type === "voice_error") {
    return { ...queue, errors: [...queue.errors, message.message] };
  }
  if (message.type === "voice_start") {
    return {
      ...queue,
      items: [
        ...queue.items,
        {
          utteranceId: message.utterance_id,
          sourceEventId: message.source_event_id,
          speakerKind: message.speaker_kind,
          speakerName: message.speaker_name,
          mimeType: message.mime_type,
          chunks: [],
          status: "receiving",
        },
      ],
    };
  }
  if (message.type === "audio_chunk") {
    return {
      ...queue,
      items: queue.items.map((item) =>
        item.utteranceId === message.utterance_id
          ? { ...item, chunks: [...item.chunks, message.data] }
          : item,
      ),
    };
  }
  return {
    ...queue,
    items: queue.items.map((item) =>
      item.utteranceId === message.utterance_id
        ? { ...item, status: "ready" }
        : item,
    ),
  };
}

export function pruneStaleVoiceQueue(
  queue: LiveVoiceQueue,
  currentEventId: number | null,
): LiveVoiceQueue {
  if (currentEventId === null) {
    return queue;
  }

  return {
    ...queue,
    items: queue.items.filter(
      (item) =>
        item.speakerKind === "player" ||
        currentEventId - item.sourceEventId <= STALE_EVENT_DISTANCE,
    ),
  };
}

export function useLiveVoiceStream(
  runId: string | undefined,
  {
    currentEventId,
    enabled,
    isPaused,
  }: {
    currentEventId: number | null;
    enabled: boolean;
    isPaused: boolean;
  },
) {
  const [connectionState, setConnectionState] =
    useState<LiveVoiceConnectionState>(enabled ? "connecting" : "idle");
  const [queue, dispatch] = useReducer(enqueueVoiceMessage, undefined, createVoiceQueue);
  const streamUrl = useMemo(
    () => (runId ? resolveVoiceStreamUrl(runId) : null),
    [runId],
  );
  const visibleQueue = useMemo(
    () => pruneStaleVoiceQueue(queue, currentEventId),
    [currentEventId, queue],
  );
  const currentItem =
    visibleQueue.items.find((item) => item.status === "ready") ??
    visibleQueue.items[0] ??
    null;

  useEffect(() => {
    if (!enabled || !streamUrl) {
      setConnectionState(enabled ? "error" : "idle");
      return;
    }

    setConnectionState("connecting");
    const socket = new WebSocket(streamUrl);
    socket.onopen = () => setConnectionState("open");
    socket.onerror = () => setConnectionState("error");
    socket.onclose = () => setConnectionState("closed");
    socket.onmessage = (event) => {
      try {
        const message = JSON.parse(event.data as string) as LiveVoiceMessage;
        if (message.type === "voice_unavailable") {
          setConnectionState("unavailable");
          return;
        }
        dispatch(message);
      } catch {
        setConnectionState("error");
      }
    };

    return () => {
      socket.close();
    };
  }, [enabled, streamUrl]);

  return {
    connectionState,
    currentSpeakerName: isPaused ? null : currentItem?.speakerName ?? null,
    currentItem,
    errors: visibleQueue.errors,
  };
}
```

This task intentionally stops before browser audio playback. The reducer and connection state need to be stable before adding audio side effects.

- [ ] **Step 4: Export voice utilities**

Append to `packages/game-client/src/live/index.ts`:

```ts
export * from "./liveVoiceStream";
```

- [ ] **Step 5: Run hook tests**

Run:

```bash
pnpm --dir packages/game-client test -- --run liveVoiceStream
```

Expected: `liveVoiceStream` tests pass.

- [ ] **Step 6: Commit**

```bash
git add packages/game-client/src/live/liveVoiceStream.ts packages/game-client/src/live/liveVoiceStream.test.tsx packages/game-client/src/live/index.ts
git commit -m "feat(client): add live voice stream hook"
```

## Task 6: Browser Audio Playback In The Hook

**Files:**
- Modify: `packages/game-client/src/live/liveVoiceStream.ts`
- Modify: `packages/game-client/src/live/liveVoiceStream.test.tsx`

- [ ] **Step 1: Add failing playback tests**

Append to `packages/game-client/src/live/liveVoiceStream.test.tsx`:

```tsx
it("creates an audio element for a ready current utterance", () => {
  vi.stubGlobal("WebSocket", MockWebSocket);
  const play = vi.fn().mockResolvedValue(undefined);
  const pause = vi.fn();
  vi.spyOn(document, "createElement").mockImplementation((tagName) => {
    const element = HTMLElement.prototype.ownerDocument!.createElement.call(
      document,
      tagName,
    );
    if (tagName === "audio") {
      Object.assign(element, { play, pause });
    }
    return element;
  });

  renderHook(() =>
    useLiveVoiceStream("run-1", {
      currentEventId: 4,
      enabled: true,
      isPaused: false,
    }),
  );

  act(() => {
    MockWebSocket.instances[0].onopen?.();
    MockWebSocket.instances[0].emit({
      type: "voice_start",
      utterance_id: "voice-1",
      source_event_id: 4,
      speaker_kind: "player",
      speaker_name: "阿青",
      mime_type: "audio/mpeg",
    });
    MockWebSocket.instances[0].emit({
      type: "audio_chunk",
      utterance_id: "voice-1",
      mime_type: "audio/mpeg",
      data: "YWJj",
    });
    MockWebSocket.instances[0].emit({
      type: "voice_end",
      utterance_id: "voice-1",
      duration_ms: 1000,
    });
  });

  expect(play).toHaveBeenCalled();
});
```

- [ ] **Step 2: Run failing playback test**

Run:

```bash
pnpm --dir packages/game-client test -- --run liveVoiceStream
```

Expected: the new playback test fails because the hook does not create or play audio.

- [ ] **Step 3: Implement audio playback side effect**

In `packages/game-client/src/live/liveVoiceStream.ts`, add helpers:

```ts
function base64ToBlob(chunks: string[], mimeType: string) {
  const bytes = chunks.flatMap((chunk) =>
    Array.from(atob(chunk), (character) => character.charCodeAt(0)),
  );
  return new Blob([new Uint8Array(bytes)], { type: mimeType });
}
```

Update imports:

```ts
import { useEffect, useMemo, useReducer, useRef, useState } from "react";
```

Inside `useLiveVoiceStream`, after `currentItem`, add:

```ts
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const playedUtteranceRef = useRef<string | null>(null);

  useEffect(() => {
    if (!currentItem || currentItem.status !== "ready" || isPaused) {
      audioRef.current?.pause();
      return;
    }
    if (playedUtteranceRef.current === currentItem.utteranceId) {
      return;
    }

    const blob = base64ToBlob(currentItem.chunks, currentItem.mimeType);
    const objectUrl = URL.createObjectURL(blob);
    const audio = document.createElement("audio");
    audio.src = objectUrl;
    audioRef.current = audio;
    playedUtteranceRef.current = currentItem.utteranceId;
    void audio.play().catch(() => {
      setConnectionState("error");
    });

    return () => {
      audio.pause();
      URL.revokeObjectURL(objectUrl);
    };
  }, [currentItem, isPaused]);
```

- [ ] **Step 4: Run hook tests**

Run:

```bash
pnpm --dir packages/game-client test -- --run liveVoiceStream
```

Expected: all `liveVoiceStream` tests pass.

- [ ] **Step 5: Commit**

```bash
git add packages/game-client/src/live/liveVoiceStream.ts packages/game-client/src/live/liveVoiceStream.test.tsx
git commit -m "feat(client): play live voice audio"
```

## Task 7: Mobile Live Page Voice Control

**Files:**
- Modify: `apps/mobile-web/src/pages/LivePage.tsx`
- Modify: `apps/mobile-web/src/components/MobileLiveTheater.tsx`
- Modify: `apps/mobile-web/src/pages/LivePage.test.tsx`
- Modify: `apps/mobile-web/src/styles/index.css`

- [ ] **Step 1: Write failing page test for voice control**

In `apps/mobile-web/src/pages/LivePage.test.tsx`, update the `vi.mock("@werewolf-arena/game-client"` return value to include the real `useLiveVoiceStream` unless explicitly mocked. Add to the hoisted mocks:

```ts
  useLiveVoiceStream: vi.fn(),
```

Add it to the mock return:

```ts
    useLiveVoiceStream: gameClientMocks.useLiveVoiceStream,
```

In `beforeEach`, add:

```ts
    gameClientMocks.useLiveVoiceStream.mockReturnValue({
      connectionState: "idle",
      currentSpeakerName: null,
      currentItem: null,
      errors: [],
    });
```

Append this test:

```tsx
it("lets the viewer enable live voice", async () => {
  const user = userEvent.setup();

  renderLiveRoute();

  const voiceButton = await screen.findByRole("button", { name: "开启语音" });
  expect(voiceButton).toBeVisible();

  await user.click(voiceButton);

  expect(gameClientMocks.useLiveVoiceStream).toHaveBeenLastCalledWith(
    "run-1",
    expect.objectContaining({ enabled: true }),
  );
});
```

- [ ] **Step 2: Run failing mobile test**

Run:

```bash
pnpm --dir apps/mobile-web test -- --run LivePage
```

Expected: test fails because no voice button exists.

- [ ] **Step 3: Wire hook in `LivePage`**

Modify imports in `apps/mobile-web/src/pages/LivePage.tsx`:

```ts
  useLiveVoiceStream,
```

Change React import:

```ts
import { useMemo, useState } from "react";
```

Inside `LivePage`, after the director creation, add:

```ts
  const [voiceEnabled, setVoiceEnabled] = useState(false);
  const voice = useLiveVoiceStream(gameId, {
    currentEventId: director.currentEventId,
    enabled: voiceEnabled,
    isPaused: director.isPaused,
  });
```

Pass props to `MobileLiveTheater`:

```tsx
          onToggleVoice={() => setVoiceEnabled((current) => !current)}
          voiceEnabled={voiceEnabled}
          voiceState={voice}
```

- [ ] **Step 4: Add theater props and control**

In `apps/mobile-web/src/components/MobileLiveTheater.tsx`, import `Volume2`:

```ts
import { Gauge, Mic, Pause, Play, Radio, RotateCcw, Volume2 } from "lucide-react";
```

Add a local type:

```ts
export type MobileLiveVoiceState = {
  connectionState: "idle" | "connecting" | "open" | "error" | "closed" | "unavailable";
  currentSpeakerName: string | null;
};
```

Add props to `MobileLiveTheaterProps`:

```ts
  onToggleVoice: () => void;
  voiceEnabled: boolean;
  voiceState: MobileLiveVoiceState;
```

Pass them to `LiveTheaterControls`.

Add props to `LiveTheaterControlsProps`:

```ts
  onToggleVoice: () => void;
  voiceEnabled: boolean;
  voiceState: MobileLiveVoiceState;
```

Add this button in `.mobile-live-action-bar` after the pause button:

```tsx
        <button
          aria-label={voiceEnabled ? "关闭语音" : "开启语音"}
          className="mobile-button"
          disabled={voiceState.connectionState === "unavailable"}
          onClick={onToggleVoice}
          type="button"
        >
          <span className="mobile-live-control-icon">
            <Volume2 aria-hidden="true" size={18} strokeWidth={2.8} />
          </span>
          <span className="mobile-live-control-label">
            {voiceControlLabel(voiceEnabled, voiceState)}
          </span>
        </button>
```

Add helper near `liveStageEventLabel`:

```ts
function voiceControlLabel(
  enabled: boolean,
  state: MobileLiveVoiceState,
) {
  if (state.connectionState === "unavailable") {
    return "不可用";
  }
  if (!enabled) {
    return "语音";
  }
  if (state.connectionState === "connecting") {
    return "连接中";
  }
  if (state.connectionState === "error") {
    return "重试";
  }
  return state.currentSpeakerName ?? "语音";
}
```

- [ ] **Step 5: Add stable voice-control label width**

Add to `apps/mobile-web/src/styles/index.css`:

```css
.mobile-live-control-label {
  min-width: 2.5em;
}
```

- [ ] **Step 6: Run mobile test**

Run:

```bash
pnpm --dir apps/mobile-web test -- --run LivePage
```

Expected: `LivePage` tests pass.

- [ ] **Step 7: Commit**

```bash
git add apps/mobile-web/src/pages/LivePage.tsx apps/mobile-web/src/components/MobileLiveTheater.tsx apps/mobile-web/src/pages/LivePage.test.tsx apps/mobile-web/src/styles/index.css
git commit -m "feat(mobile): add live voice control"
```

If `apps/mobile-web/src/styles/index.css` was not changed, omit it from `git add`.

## Task 8: Verification And Cleanup

**Files:**
- Modify only files needed to fix verification failures.

- [ ] **Step 1: Run backend tests**

Run:

```bash
cd apps/api && .venv/bin/python -m pytest tests/test_config.py tests/test_live.py tests/test_voice.py tests/test_volcengine_tts.py tests/test_voice_stream_api.py -q
```

Expected: all selected backend tests pass.

- [ ] **Step 2: Run frontend package tests**

Run:

```bash
pnpm --dir packages/game-client test -- --run liveVoiceStream useGameRunEvents liveDirector
```

Expected: all selected game-client tests pass.

- [ ] **Step 3: Run mobile tests**

Run:

```bash
pnpm --dir apps/mobile-web test -- --run LivePage MobileLivePhaseBar mobileLiveSubtitle
```

Expected: selected mobile tests pass.

- [ ] **Step 4: Run lint for touched workspaces**

Run:

```bash
cd apps/api && .venv/bin/ruff check app tests
pnpm --dir apps/mobile-web lint
```

Expected: both commands pass.

- [ ] **Step 5: Manual disabled-state check**

Run API without TTS credentials:

```bash
make api
```

In another terminal, run mobile:

```bash
make mobile-web
```

Expected: live page loads normally. Voice control is present but either remains off until clicked or reports unavailable without breaking subtitles.

- [ ] **Step 6: Manual configured-state smoke check**

Run API with a valid Ark key:

```bash
cd apps/api && ARK_TTS_ENABLED=true ARK_TTS_API_KEY="$ARK_TTS_API_KEY" .venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Run mobile:

```bash
VITE_API_BASE_URL=http://127.0.0.1:8000 pnpm --dir apps/mobile-web dev --host 0.0.0.0 --port 5174
```

Expected: after starting a live game and clicking the voice control once, player speech begins producing voice messages and subtitles continue to update.

- [ ] **Step 7: Final commit if verification fixes were needed**

If Step 1 through Step 6 required fixes:

```bash
git add -u
git commit -m "fix: stabilize live voice streaming"
```

If no fixes were needed, do not create an empty commit.

## Self-Review

- Spec coverage: backend proxy, Volcengine credentials, `/voice-stream`, player and judge voices, subtitle fallback, configuration, tests, and rollout are covered by Tasks 1 through 8.
- Scope check: ASR, per-player voices, persisted replay audio, and replay playback are explicitly outside this implementation plan.
- Placeholder scan: the plan contains concrete paths, snippets, commands, and expected outcomes for each task.
- Type consistency: `VoiceUtterance`, `VolcengineTtsConfig`, application WebSocket message names, and `useLiveVoiceStream` are named consistently across backend, client, and mobile tasks.
