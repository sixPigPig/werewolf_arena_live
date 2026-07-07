import asyncio
from collections.abc import AsyncIterator, Generator
from contextlib import contextmanager
from dataclasses import replace

import pytest
from fastapi import WebSocketDisconnect
from fastapi.testclient import TestClient

from app.api.routes.games import get_live_registry, get_voice_streamer
from app.main import app
from app.werewolf.live import LiveRunRegistry
from app.werewolf.voice_stream import LiveVoiceStreamService
from app.werewolf.volcengine_tts import VolcengineTtsConfig


BASE_TTS_CONFIG = VolcengineTtsConfig(
    enabled=True,
    api_key="ark-test-key",
    resource_id="seed-tts-2.0",
    ws_url="wss://example.test",
    player_speaker="player",
    judge_speaker="judge",
    audio_format="mp3",
    sample_rate=24000,
)


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


class FakeWebSocket:
    def __init__(self) -> None:
        self.messages: list[dict] = []
        self.receive_calls = 0
        self._disconnect_event: asyncio.Event | None = None

    async def send_json(self, message: dict) -> None:
        self.messages.append(message)

    async def receive(self) -> dict:
        self.receive_calls += 1
        await self._disconnect().wait()
        raise WebSocketDisconnect()

    def disconnect(self) -> None:
        self._disconnect().set()

    def _disconnect(self) -> asyncio.Event:
        if self._disconnect_event is None:
            self._disconnect_event = asyncio.Event()
        return self._disconnect_event


class RecordingTtsClient:
    instances: list["RecordingTtsClient"] = []

    def __init__(self, config: VolcengineTtsConfig) -> None:
        self.config = config
        self.calls: list[dict] = []
        RecordingTtsClient.instances.append(self)

    async def synthesize(
        self,
        *,
        speaker: str,
        text_chunks: list[str],
    ) -> AsyncIterator[bytes]:
        self.calls.append({"speaker": speaker, "text_chunks": text_chunks})
        yield b"abc"


class FailingTtsClient:
    def __init__(self, config: VolcengineTtsConfig) -> None:
        self.config = config

    async def synthesize(
        self,
        *,
        speaker: str,
        text_chunks: list[str],
    ) -> AsyncIterator[bytes]:
        raise RuntimeError("vendor failed")
        yield b"unreachable"


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


def create_run(registry: LiveRunRegistry):
    return registry.create_run(
        session_id="game_1200abcd",
        villager_model="deepseek-chat",
        werewolf_model="deepseek-chat",
        seed=21,
        max_rounds=8,
        **classic_rule_kwargs(),
    )


async def wait_for_subscription(registry: LiveRunRegistry, run_id: str) -> None:
    for _ in range(20):
        if registry.get_run(run_id).subscribers:
            return
        await asyncio.sleep(0)
    raise AssertionError("voice stream did not subscribe")


def override_registry(registry: LiveRunRegistry) -> None:
    app.dependency_overrides[get_live_registry] = lambda: registry


def override_streamer(streamer: FakeVoiceStreamer) -> None:
    app.dependency_overrides[get_voice_streamer] = lambda: streamer


@contextmanager
def client_with_overrides() -> Generator[TestClient, None, None]:
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def test_voice_stream_route_forwards_stream_messages() -> None:
    registry = LiveRunRegistry()
    run = create_run(registry)
    override_registry(registry)
    override_streamer(FakeVoiceStreamer())

    with client_with_overrides() as client:
        with client.websocket_connect(f"/api/v1/games/runs/{run.run_id}/voice-stream") as ws:
            assert ws.receive_json()["type"] == "voice_start"
            assert ws.receive_json()["type"] == "audio_chunk"
            assert ws.receive_json()["type"] == "voice_end"


def test_voice_stream_route_reports_unknown_run() -> None:
    override_registry(LiveRunRegistry())
    override_streamer(FakeVoiceStreamer())

    with client_with_overrides() as client:
        with client.websocket_connect("/api/v1/games/runs/run_missing/voice-stream") as ws:
            assert ws.receive_json() == {
                "type": "voice_error",
                "message": "Game run not found",
            }


def test_voice_stream_route_reports_unavailable_when_disabled() -> None:
    registry = LiveRunRegistry()
    run = create_run(registry)
    override_registry(registry)
    override_streamer(FakeVoiceStreamer(available=False))

    with client_with_overrides() as client:
        with client.websocket_connect(f"/api/v1/games/runs/{run.run_id}/voice-stream") as ws:
            assert ws.receive_json() == {"type": "voice_unavailable"}


def test_voice_stream_service_streams_public_voice_events_and_unsubscribes() -> None:
    RecordingTtsClient.instances.clear()
    registry = LiveRunRegistry()
    run = create_run(registry)
    websocket = FakeWebSocket()
    service = LiveVoiceStreamService(
        registry=registry,
        config=BASE_TTS_CONFIG,
        client_factory=RecordingTtsClient,
    )

    async def stream_live_events() -> None:
        task = asyncio.create_task(service.stream_run(run.run_id, websocket))
        await wait_for_subscription(registry, run.run_id)
        registry.publish(
            run.run_id,
            "model_response_delta",
            actor="狼人",
            action="werewolf_discussion",
            payload={
                "request_id": "req-private",
                "visible_text": "今晚刀谁。",
                "is_public": True,
            },
        )
        public_event = registry.publish(
            run.run_id,
            "model_response_delta",
            actor="阿青",
            action="debate",
            payload={
                "request_id": "req-public",
                "visible_text": "我是阿青，我先发言。",
                "is_public": True,
            },
        )
        registry.mark_completed(run.run_id, winner="好人阵营")
        await asyncio.wait_for(task, timeout=1)
        assert websocket.messages[0]["source_event_id"] == public_event.id

    asyncio.run(stream_live_events())

    assert registry.get_run(run.run_id).subscribers == []
    assert RecordingTtsClient.instances[0].calls == [
        {"speaker": "player", "text_chunks": ["我是阿青，", "我先发言。"]}
    ]
    assert [message["type"] for message in websocket.messages] == [
        "voice_start",
        "audio_chunk",
        "voice_end",
        "voice_start",
        "audio_chunk",
        "voice_end",
    ]
    assert websocket.messages[1]["data"] == "YWJj"


def test_voice_stream_service_ignores_public_action_when_flag_is_false() -> None:
    RecordingTtsClient.instances.clear()
    registry = LiveRunRegistry()
    run = create_run(registry)
    websocket = FakeWebSocket()
    service = LiveVoiceStreamService(
        registry=registry,
        config=BASE_TTS_CONFIG,
        client_factory=RecordingTtsClient,
    )

    async def stream_events() -> None:
        task = asyncio.create_task(service.stream_run(run.run_id, websocket))
        await wait_for_subscription(registry, run.run_id)
        registry.publish(
            run.run_id,
            "model_response_delta",
            actor="阿青",
            action="debate",
            payload={
                "request_id": "req-private",
                "visible_text": "这句动作公开但标记不是公开。",
                "is_public": False,
            },
        )
        registry.mark_completed(run.run_id, winner="好人阵营")
        await asyncio.wait_for(task, timeout=1)

    asyncio.run(stream_events())

    assert [instance.calls for instance in RecordingTtsClient.instances] == [
        [{"speaker": "judge", "text_chunks": ["对局结束，", "好人阵营获胜。"]}]
    ]


def test_voice_stream_service_does_not_replay_historical_events_on_connect() -> None:
    RecordingTtsClient.instances.clear()
    registry = LiveRunRegistry()
    run = create_run(registry)
    registry.publish(
        run.run_id,
        "model_response_delta",
        actor="阿青",
        action="debate",
        payload={
            "request_id": "req-historical",
            "visible_text": "这是连接前的历史发言。",
            "is_public": True,
        },
    )
    websocket = FakeWebSocket()
    service = LiveVoiceStreamService(
        registry=registry,
        config=BASE_TTS_CONFIG,
        client_factory=RecordingTtsClient,
    )

    async def stream_new_events() -> None:
        task = asyncio.create_task(service.stream_run(run.run_id, websocket))
        await wait_for_subscription(registry, run.run_id)
        registry.publish(
            run.run_id,
            "model_response_delta",
            actor="阿青",
            action="debate",
            payload={
                "request_id": "req-live",
                "visible_text": "这是连接后的现场发言。",
                "is_public": True,
            },
        )
        registry.mark_completed(run.run_id, winner="好人阵营")
        await asyncio.wait_for(task, timeout=1)

    asyncio.run(stream_new_events())

    calls = [call for instance in RecordingTtsClient.instances for call in instance.calls]
    assert calls == [
        {"speaker": "player", "text_chunks": ["这是连接后的现场发言。"]},
        {"speaker": "judge", "text_chunks": ["对局结束，", "好人阵营获胜。"]},
    ]


def test_voice_stream_service_returns_without_subscribing_when_run_is_terminal() -> None:
    RecordingTtsClient.instances.clear()
    registry = LiveRunRegistry()
    run = create_run(registry)
    registry.mark_completed(run.run_id, winner="好人阵营")
    websocket = FakeWebSocket()
    service = LiveVoiceStreamService(
        registry=registry,
        config=BASE_TTS_CONFIG,
        client_factory=RecordingTtsClient,
    )

    asyncio.run(service.stream_run(run.run_id, websocket))

    assert registry.get_run(run.run_id).subscribers == []
    assert websocket.messages == []
    assert RecordingTtsClient.instances == []


def test_voice_stream_service_stops_on_client_disconnect_and_unsubscribes() -> None:
    registry = LiveRunRegistry()
    run = create_run(registry)
    websocket = FakeWebSocket()
    service = LiveVoiceStreamService(
        registry=registry,
        config=BASE_TTS_CONFIG,
        client_factory=RecordingTtsClient,
    )

    async def run_and_disconnect() -> None:
        task = asyncio.create_task(service.stream_run(run.run_id, websocket))
        await wait_for_subscription(registry, run.run_id)
        websocket.disconnect()
        await asyncio.wait_for(task, timeout=1)

    asyncio.run(run_and_disconnect())

    assert websocket.receive_calls > 0
    assert registry.get_run(run.run_id).subscribers == []


def test_voice_stream_service_polls_subscriber_without_executor_threads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    RecordingTtsClient.instances.clear()
    registry = LiveRunRegistry()
    run = create_run(registry)
    websocket = FakeWebSocket()
    service = LiveVoiceStreamService(
        registry=registry,
        config=BASE_TTS_CONFIG,
        client_factory=RecordingTtsClient,
    )

    async def fail_to_thread(*args, **kwargs):
        raise AssertionError("voice stream should not use executor threads for queue polling")

    monkeypatch.setattr(asyncio, "to_thread", fail_to_thread)

    async def stream_live_events() -> None:
        task = asyncio.create_task(service.stream_run(run.run_id, websocket))
        await wait_for_subscription(registry, run.run_id)
        registry.mark_completed(run.run_id, winner="好人阵营")
        await asyncio.wait_for(task, timeout=1)

    asyncio.run(stream_live_events())

    assert registry.get_run(run.run_id).subscribers == []


def test_voice_stream_service_reports_unavailable_without_subscribing() -> None:
    registry = LiveRunRegistry()
    run = create_run(registry)
    websocket = FakeWebSocket()
    service = LiveVoiceStreamService(
        registry=registry,
        config=replace(BASE_TTS_CONFIG, enabled=False),
        client_factory=RecordingTtsClient,
    )

    asyncio.run(service.stream_run(run.run_id, websocket))

    assert websocket.messages == [{"type": "voice_unavailable"}]
    assert registry.get_run(run.run_id).subscribers == []


def test_voice_stream_service_reports_synthesis_error_and_unsubscribes() -> None:
    registry = LiveRunRegistry()
    run = create_run(registry)
    websocket = FakeWebSocket()
    service = LiveVoiceStreamService(
        registry=registry,
        config=BASE_TTS_CONFIG,
        client_factory=FailingTtsClient,
    )

    async def stream_live_events() -> None:
        task = asyncio.create_task(service.stream_run(run.run_id, websocket))
        await wait_for_subscription(registry, run.run_id)
        public_event = registry.publish(
            run.run_id,
            "model_response_delta",
            actor="阿青",
            action="debate",
            payload={
                "request_id": "req-public",
                "visible_text": "我先发言。",
                "is_public": True,
            },
        )
        await asyncio.wait_for(task, timeout=1)
        assert websocket.messages[0]["source_event_id"] == public_event.id

    asyncio.run(stream_live_events())

    assert registry.get_run(run.run_id).subscribers == []
    assert websocket.messages == [
        {
            "type": "voice_start",
            "utterance_id": websocket.messages[0]["utterance_id"],
            "source_event_id": websocket.messages[0]["source_event_id"],
            "speaker_kind": "player",
            "speaker_name": "阿青",
            "mime_type": "audio/mpeg",
        },
        {
            "type": "voice_error",
            "utterance_id": websocket.messages[0]["utterance_id"],
            "source_event_id": websocket.messages[0]["source_event_id"],
            "message": "Voice synthesis failed",
        },
    ]


def test_voice_stream_service_unsubscribes_when_cancelled() -> None:
    registry = LiveRunRegistry()
    run = create_run(registry)
    websocket = FakeWebSocket()
    service = LiveVoiceStreamService(
        registry=registry,
        config=BASE_TTS_CONFIG,
        client_factory=RecordingTtsClient,
    )

    async def run_and_cancel() -> None:
        task = asyncio.create_task(service.stream_run(run.run_id, websocket))
        await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(run_and_cancel())

    assert registry.get_run(run.run_id).subscribers == []
