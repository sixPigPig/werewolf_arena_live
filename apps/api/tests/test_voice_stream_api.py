import asyncio
import json
from collections.abc import AsyncIterator, Generator
from contextlib import contextmanager
from dataclasses import replace

import pytest
from fastapi import WebSocketDisconnect
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.routes.games import (
    SessionLiveStore,
    SessionVoiceStore,
    get_live_registry,
    get_voice_streamer,
)
from app.db.base import Base
from app.main import app
from app.models.live import VoiceMaterializationJobRecord
from app.werewolf import voice_stream as voice_stream_module
from app.werewolf.live import LiveRunRegistry
from app.werewolf.voice import VoiceUtterance
from app.werewolf.voice_stream import LiveVoiceStreamService
from app.werewolf.voice_store import DatabaseVoiceStore
from app.werewolf.volcengine_tts import TtsSubtitleCue, TtsSubtitleTiming, VolcengineTtsConfig


BASE_TTS_CONFIG = VolcengineTtsConfig(
    enabled=True,
    api_key="ark-test-key",
    resource_id="seed-tts-2.0",
    ws_url="wss://example.test",
    player_speaker="player",
    judge_speaker="judge",
    audio_format="pcm",
    sample_rate=24000,
)


class FakeVoiceStreamer:
    def __init__(self, *, available: bool = True) -> None:
        self.available = available
        self.calls: list[dict] = []

    async def stream_run(
        self,
        run_id: str,
        websocket,
        *,
        current_event_id: int | None = None,
        playback_ack_required: bool = False,
    ) -> None:
        self.calls.append(
            {
                "run_id": run_id,
                "current_event_id": current_event_id,
                "playback_ack_required": playback_ack_required,
            }
        )
        if not self.available:
            await websocket.send_json(
                {
                    "type": "voice_unavailable",
                    "reason": "disabled",
                    "message": "语音服务未启用，请检查后端语音配置。",
                }
            )
            return
        await websocket.send_json(
            {
                "type": "voice_start",
                "utterance_id": "voice_1",
                "source_event_id": 2,
                "speaker_kind": "player",
                "speaker_name": "阿青",
                "mime_type": "audio/L16",
                "audio_format": "pcm",
                "sample_rate": 24000,
            }
        )
        await websocket.send_json(
            {
                "type": "audio_chunk",
                "utterance_id": "voice_1",
                "chunk_index": 0,
                "mime_type": "audio/L16",
                "audio_format": "pcm",
                "sample_rate": 24000,
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
        self._incoming_messages: asyncio.Queue[dict] | None = None

    async def send_json(self, message: dict) -> None:
        self.messages.append(message)

    async def receive(self) -> dict:
        self.receive_calls += 1
        incoming_task = asyncio.create_task(self._incoming().get())
        disconnect_task = asyncio.create_task(self._disconnect().wait())
        done, pending = await asyncio.wait(
            {incoming_task, disconnect_task},
            return_when=asyncio.FIRST_COMPLETED,
        )
        for task in pending:
            task.cancel()
        if disconnect_task in done:
            raise WebSocketDisconnect()
        return incoming_task.result()

    def send_client_json(self, message: dict) -> None:
        self._incoming().put_nowait({"type": "websocket.receive", "text": json.dumps(message)})

    def disconnect(self) -> None:
        self._disconnect().set()

    def _incoming(self) -> asyncio.Queue[dict]:
        if self._incoming_messages is None:
            self._incoming_messages = asyncio.Queue()
        return self._incoming_messages

    def _disconnect(self) -> asyncio.Event:
        if self._disconnect_event is None:
            self._disconnect_event = asyncio.Event()
        return self._disconnect_event


class DisconnectingOnVoiceStartWebSocket(FakeWebSocket):
    async def send_json(self, message: dict) -> None:
        if message.get("type") == "voice_start":
            raise WebSocketDisconnect()
        await super().send_json(message)


class DisconnectingOnVoiceEndWebSocket(FakeWebSocket):
    async def send_json(self, message: dict) -> None:
        if message.get("type") == "voice_end":
            raise WebSocketDisconnect()
        await super().send_json(message)


class MarkingDisconnectOnVoiceEndWebSocket(FakeWebSocket):
    async def send_json(self, message: dict) -> None:
        await super().send_json(message)
        if message.get("type") == "voice_end":
            self.disconnect()
            await asyncio.sleep(0)


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


class MultiChunkTtsClient:
    instances: list["MultiChunkTtsClient"] = []

    def __init__(self, config: VolcengineTtsConfig) -> None:
        self.config = config
        self.calls: list[dict] = []
        MultiChunkTtsClient.instances.append(self)

    async def synthesize(
        self,
        *,
        speaker: str,
        text_chunks: list[str],
    ) -> AsyncIterator[bytes]:
        self.calls.append({"speaker": speaker, "text_chunks": text_chunks})
        yield b"first"
        await asyncio.sleep(0)
        yield b"second"


class SubtitleTtsClient:
    instances: list["SubtitleTtsClient"] = []

    def __init__(self, config: VolcengineTtsConfig) -> None:
        self.config = config
        self.calls: list[dict] = []
        SubtitleTtsClient.instances.append(self)

    async def synthesize(
        self,
        *,
        speaker: str,
        text_chunks: list[str],
    ) -> AsyncIterator[bytes | TtsSubtitleTiming]:
        self.calls.append({"speaker": speaker, "text_chunks": text_chunks})
        yield TtsSubtitleTiming(
            cues=(
                TtsSubtitleCue(text="我", start_ms=0, end_ms=180),
                TtsSubtitleCue(text="先发言。", start_ms=180, end_ms=820),
            )
        )
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


class FailingThenRecordingTtsClient:
    instances: list["FailingThenRecordingTtsClient"] = []

    def __init__(self, config: VolcengineTtsConfig) -> None:
        self.config = config
        self.calls: list[dict] = []
        FailingThenRecordingTtsClient.instances.append(self)

    async def synthesize(
        self,
        *,
        speaker: str,
        text_chunks: list[str],
    ) -> AsyncIterator[bytes]:
        self.calls.append({"speaker": speaker, "text_chunks": text_chunks})
        if len(FailingThenRecordingTtsClient.instances) == 1:
            raise RuntimeError("vendor failed")
        yield b"abc"


class RecordingVoiceStore:
    def __init__(self) -> None:
        self.utterances: list[dict] = []
        self.chunks: list[dict] = []
        self.completed: list[dict] = []
        self.failed: list[dict] = []
        self.subtitle_timings: list[dict] = []
        self.recent_utterance: dict | None = None
        self.replay_chunks: list[bytes] = []
        self.find_recent_calls: list[dict] = []

    def upsert_utterance(
        self,
        utterance,
        *,
        audio_format: str,
        sample_rate: int,
        mime_type: str,
        status: str = "synthesizing",
    ) -> None:
        self.utterances.append(
            {
                "utterance": utterance,
                "audio_format": audio_format,
                "sample_rate": sample_rate,
                "mime_type": mime_type,
                "status": status,
            }
        )

    def append_chunk(self, utterance_id: str, *, chunk_index: int, audio: bytes) -> None:
        self.chunks.append(
            {
                "utterance_id": utterance_id,
                "chunk_index": chunk_index,
                "audio": audio,
            }
        )

    def complete_utterance(self, utterance_id: str, *, duration_ms: int) -> None:
        self.completed.append({"utterance_id": utterance_id, "duration_ms": duration_ms})

    def fail_utterance(self, utterance_id: str, *, message: str) -> None:
        self.failed.append({"utterance_id": utterance_id, "message": message})

    def update_subtitle_timings(
        self,
        utterance_id: str,
        *,
        subtitle_timings: list[dict],
    ) -> None:
        self.subtitle_timings.append(
            {"utterance_id": utterance_id, "subtitle_timings": subtitle_timings}
        )

    def find_recent_utterance(
        self,
        *,
        run_id: str,
        current_event_id: int,
    ) -> dict | None:
        self.find_recent_calls.append({"run_id": run_id, "current_event_id": current_event_id})
        return self.recent_utterance

    def load_chunks(self, utterance_id: str) -> list[bytes]:
        return self.replay_chunks if self.recent_utterance else []


class FailingVoiceStore(RecordingVoiceStore):
    def __init__(self, *, fail_method: str) -> None:
        super().__init__()
        self.fail_method = fail_method

    def upsert_utterance(
        self,
        utterance,
        *,
        audio_format: str,
        sample_rate: int,
        mime_type: str,
        status: str = "synthesizing",
    ) -> None:
        if self.fail_method == "upsert_utterance":
            raise RuntimeError("voice persistence failed")
        super().upsert_utterance(
            utterance,
            audio_format=audio_format,
            sample_rate=sample_rate,
            mime_type=mime_type,
            status=status,
        )

    def append_chunk(self, utterance_id: str, *, chunk_index: int, audio: bytes) -> None:
        if self.fail_method == "append_chunk":
            raise RuntimeError("voice persistence failed")
        super().append_chunk(utterance_id, chunk_index=chunk_index, audio=audio)


class PendingSynthesisIterator:
    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.cancelled = asyncio.Event()
        self.closed = asyncio.Event()

    def __aiter__(self) -> "PendingSynthesisIterator":
        return self

    async def __anext__(self) -> bytes:
        self.started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            self.cancelled.set()
            raise
        raise StopAsyncIteration

    async def aclose(self) -> None:
        self.closed.set()


class PendingTtsClient:
    iterators: list[PendingSynthesisIterator] = []

    def __init__(self, config: VolcengineTtsConfig) -> None:
        self.config = config

    def synthesize(
        self,
        *,
        speaker: str,
        text_chunks: list[str],
    ) -> PendingSynthesisIterator:
        iterator = PendingSynthesisIterator()
        PendingTtsClient.iterators.append(iterator)
        return iterator


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


@pytest.fixture
def db_session() -> Generator[Session, None, None]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    with TestingSessionLocal() as session:
        yield session


def stored_voice_utterance(
    *,
    utterance_id: str,
    run_id: str,
    source_event_id: int,
    text: str,
    speaker_kind: str = "player",
) -> VoiceUtterance:
    return VoiceUtterance(
        utterance_id=utterance_id,
        run_id=run_id,
        source_event_id=source_event_id,
        request_id=f"req-{utterance_id}",
        speaker_kind=speaker_kind,
        speaker_name="阿青",
        speaker="player",
        text=text,
        action="debate",
    )


async def wait_for_subscription(registry: LiveRunRegistry, run_id: str) -> None:
    for _ in range(20):
        if registry.get_run(run_id).subscribers:
            return
        await asyncio.sleep(0)
    raise AssertionError("voice stream did not subscribe")


async def wait_for_messages(websocket: FakeWebSocket, count: int) -> None:
    for _ in range(60):
        if len(websocket.messages) >= count:
            return
        await asyncio.sleep(0.01)
    raise AssertionError(f"voice stream only sent {len(websocket.messages)} messages")


def override_registry(registry: LiveRunRegistry) -> None:
    app.dependency_overrides[get_live_registry] = lambda: registry


def test_get_voice_streamer_persists_audio_generated_for_live_playback(
    db_session: Session,
) -> None:
    MultiChunkTtsClient.instances.clear()
    session_factory = sessionmaker(
        bind=db_session.get_bind(),
        autoflush=False,
        autocommit=False,
    )
    registry = LiveRunRegistry(live_store=SessionLiveStore(session_factory))
    run = create_run(registry)
    websocket = FakeWebSocket()
    service = get_voice_streamer(registry, BASE_TTS_CONFIG)
    assert service.voice_store_factory is not None
    service.client_factory = MultiChunkTtsClient
    service.voice_store_factory = lambda session_id: SessionVoiceStore(
        session_id=session_id,
        session_factory=session_factory,
    )

    async def stream_live_events() -> None:
        task = asyncio.create_task(service.stream_run(run.run_id, websocket))
        await wait_for_subscription(registry, run.run_id)
        registry.publish(
            run.run_id,
            "model_response_delta",
            actor="阿青",
            action="debate",
            payload={
                "request_id": "req-live-persist",
                "visible_text": "这段现场语音需要保存。",
                "is_public": True,
            },
        )
        final_event = registry.publish(
            run.run_id,
            "action_parsed",
            actor="阿青",
            action="debate",
            payload={
                "request_id": "req-live-persist",
                "visible_result": {"say": "这段现场语音需要保存。"},
            },
        )
        registry.mark_completed(run.run_id, winner="好人阵营")
        await asyncio.wait_for(task, timeout=1)
        with session_factory() as db:
            job = db.get(
                VoiceMaterializationJobRecord,
                (run.run_id, final_event.id, "player"),
            )
            assert job is not None and job.status == "complete"

    asyncio.run(stream_live_events())

    with session_factory() as db:
        voices = DatabaseVoiceStore(db, session_id=run.session_id).list_playback_voices()
    player_voice = next(voice for voice in voices if voice["speaker_kind"] == "player")
    assert [chunk["data"] for chunk in player_voice["chunks"]] == [
        "Zmlyc3Q=",
        "c2Vjb25k",
    ]


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
            start = ws.receive_json()
            chunk = ws.receive_json()
            assert start["type"] == "voice_start"
            assert start["audio_format"] == "pcm"
            assert start["sample_rate"] == 24000
            assert chunk["type"] == "audio_chunk"
            assert chunk["audio_format"] == "pcm"
            assert chunk["sample_rate"] == 24000
            assert chunk["chunk_index"] == 0
            assert ws.receive_json()["type"] == "voice_end"


def test_voice_stream_route_forwards_current_event_id_query() -> None:
    registry = LiveRunRegistry()
    run = create_run(registry)
    streamer = FakeVoiceStreamer()
    override_registry(registry)
    override_streamer(streamer)

    with client_with_overrides() as client:
        with client.websocket_connect(
            f"/api/v1/games/runs/{run.run_id}/voice-stream?current_event_id=7"
        ) as ws:
            assert ws.receive_json()["type"] == "voice_start"

    assert streamer.calls == [
        {
            "run_id": run.run_id,
            "current_event_id": 7,
            "playback_ack_required": False,
        }
    ]


def test_voice_stream_route_forwards_playback_ack_query() -> None:
    registry = LiveRunRegistry()
    run = create_run(registry)
    streamer = FakeVoiceStreamer()
    override_registry(registry)
    override_streamer(streamer)

    with client_with_overrides() as client:
        with client.websocket_connect(
            f"/api/v1/games/runs/{run.run_id}/voice-stream?current_event_id=7&playback_ack=1"
        ) as ws:
            assert ws.receive_json()["type"] == "voice_start"

    assert streamer.calls == [
        {
            "run_id": run.run_id,
            "current_event_id": 7,
            "playback_ack_required": True,
        }
    ]


def test_voice_stream_route_reports_unknown_run() -> None:
    override_registry(LiveRunRegistry())
    override_streamer(FakeVoiceStreamer())

    with client_with_overrides() as client:
        with client.websocket_connect("/api/v1/games/runs/run_missing/voice-stream") as ws:
            assert ws.receive_json() == {
                "type": "voice_unavailable",
                "reason": "run_not_found",
                "message": "对局不存在或已失效，请返回大厅重新开始。",
            }


def test_voice_stream_route_reports_unavailable_when_disabled() -> None:
    registry = LiveRunRegistry()
    run = create_run(registry)
    override_registry(registry)
    override_streamer(FakeVoiceStreamer(available=False))

    with client_with_overrides() as client:
        with client.websocket_connect(f"/api/v1/games/runs/{run.run_id}/voice-stream") as ws:
            assert ws.receive_json() == {
                "type": "voice_unavailable",
                "reason": "disabled",
                "message": "语音服务未启用，请检查后端语音配置。",
            }


def test_voice_stream_service_streams_public_voice_events_and_unsubscribes(tmp_path) -> None:
    RecordingTtsClient.instances.clear()
    registry = LiveRunRegistry()
    run = create_run(registry)
    websocket = FakeWebSocket()
    service = LiveVoiceStreamService(
        registry=registry,
        config=BASE_TTS_CONFIG,
        client_factory=RecordingTtsClient,
        judge_voice_asset_dir=tmp_path / "judge-voice",
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
    assert websocket.messages[0]["audio_format"] == "pcm"
    assert websocket.messages[0]["sample_rate"] == 24000
    assert websocket.messages[1]["chunk_index"] == 0
    assert websocket.messages[1]["audio_format"] == "pcm"
    assert websocket.messages[1]["sample_rate"] == 24000
    assert websocket.messages[1]["data"] == "YWJj"
    assert websocket.messages[4]["chunk_index"] == 0


def test_voice_stream_service_uses_static_judge_assets_when_available(tmp_path) -> None:
    RecordingTtsClient.instances.clear()
    asset_dir = tmp_path / "judge-voice"
    asset_dir.mkdir()
    (asset_dir / "night_start.mp3").write_bytes(b"static-night")
    (asset_dir / "werewolves_choose.mp3").write_bytes(b"static-wolves")
    (asset_dir / "witch_death_seat_02.mp3").write_bytes(b"static-witch")
    (asset_dir / "game_over_villagers.mp3").write_bytes(b"static-end")
    (asset_dir / "manifest.json").write_text(
        """
        {
          "audio_format": "mp3",
          "sample_rate": 24000,
          "mime_type": "audio/mpeg",
          "lines": [
            {
              "id": "night_start",
              "filename": "night_start.mp3",
              "exists": true,
              "subtitle_timings": [
                {"text": "夜晚降临，", "start_ms": 0, "end_ms": 500},
                {"text": "所有玩家请闭眼。", "start_ms": 500, "end_ms": 1100}
              ]
            },
            {
              "id": "werewolves_choose",
              "filename": "werewolves_choose.mp3",
              "exists": true,
              "subtitle_timings": [
                {"text": "狼人请选择今晚袭击的目标。", "start_ms": 0, "end_ms": 1200}
              ]
            },
            {
              "id": "witch_death_seat_02",
              "filename": "witch_death_seat_02.mp3",
              "exists": true,
              "subtitle_timings": [
                {"text": "今晚被狼人袭击的玩家是2号玩家。", "start_ms": 0, "end_ms": 1400}
              ]
            },
            {
              "id": "game_over_villagers",
              "filename": "game_over_villagers.mp3",
              "exists": true,
              "subtitle_timings": [
                {"text": "游戏结束，", "start_ms": 0, "end_ms": 400},
                {"text": "好人阵营获胜。", "start_ms": 400, "end_ms": 1000}
              ]
            }
          ]
        }
        """,
        encoding="utf-8",
    )
    registry = LiveRunRegistry()
    run = create_run(registry)
    websocket = FakeWebSocket()
    service = LiveVoiceStreamService(
        registry=registry,
        config=replace(BASE_TTS_CONFIG, audio_format="mp3"),
        client_factory=RecordingTtsClient,
        judge_voice_asset_dir=asset_dir,
    )

    async def stream_live_events() -> None:
        task = asyncio.create_task(service.stream_run(run.run_id, websocket))
        await wait_for_subscription(registry, run.run_id)
        registry.publish(
            run.run_id,
            "phase_started",
            round_number=1,
            phase="night",
            payload={"active_players": ["阿青", "白石"]},
        )
        registry.publish(
            run.run_id,
            "action_requested",
            round_number=1,
            phase="night",
            action="remove",
        )
        registry.publish(
            run.run_id,
            "judge_cue",
            round_number=1,
            phase="night",
            action="witch_death",
            payload={"target": "2号玩家"},
        )
        registry.mark_completed(run.run_id, winner="好人阵营")
        await asyncio.wait_for(task, timeout=1)

    asyncio.run(stream_live_events())

    assert RecordingTtsClient.instances == []
    assert [message["type"] for message in websocket.messages] == [
        "voice_start",
        "subtitle_timing",
        "audio_chunk",
        "voice_end",
        "voice_start",
        "subtitle_timing",
        "audio_chunk",
        "voice_end",
    ]
    start, subtitle, chunk, _end = websocket.messages[:4]
    assert start["speaker_kind"] == "judge"
    assert start["speaker_name"] == "法官"
    assert start["audio_format"] == "mp3"
    assert start["sample_rate"] == 24000
    assert subtitle == {
        "type": "subtitle_timing",
        "utterance_id": start["utterance_id"],
        "cues": [
            {"text": "夜晚降临，", "start_ms": 0, "end_ms": 500},
            {"text": "所有玩家请闭眼。", "start_ms": 500, "end_ms": 1100},
        ],
    }
    assert chunk["data"] == "c3RhdGljLW5pZ2h0"
    end_start, end_subtitle, end_chunk, _end = websocket.messages[4:8]
    assert end_start["speaker_kind"] == "judge"
    assert end_subtitle == {
        "type": "subtitle_timing",
        "utterance_id": end_start["utterance_id"],
        "cues": [
            {"text": "游戏结束，", "start_ms": 0, "end_ms": 400},
            {"text": "好人阵营获胜。", "start_ms": 400, "end_ms": 1000},
        ],
    }
    assert end_chunk["data"] == "c3RhdGljLWVuZA=="


def test_voice_stream_service_announces_explicit_dawn_deaths_once(tmp_path) -> None:
    RecordingTtsClient.instances.clear()
    registry = LiveRunRegistry()
    run = create_run(registry)
    websocket = FakeWebSocket()
    service = LiveVoiceStreamService(
        registry=registry,
        config=BASE_TTS_CONFIG,
        client_factory=RecordingTtsClient,
        judge_voice_asset_dir=tmp_path / "missing-judge-voice",
    )

    async def stream_live_events() -> None:
        task = asyncio.create_task(service.stream_run(run.run_id, websocket))
        await wait_for_subscription(registry, run.run_id)
        registry.publish(
            run.run_id,
            "state_updated",
            round_number=2,
            phase="night",
            action="night_resolved",
            payload={
                "narration_mode": "explicit_v1",
                "night_deaths": [
                    {
                        "player": "阿青",
                        "cause": "werewolf_attack",
                        "source": "狼人",
                    }
                ],
            },
        )
        registry.publish(
            run.run_id,
            "judge_cue",
            round_number=2,
            phase="day",
            action="dawn_deaths",
            payload={
                "cue_id": "dawn_deaths",
                "visible_text": "昨夜死亡的玩家是 1号玩家。",
                "players": ["1号玩家"],
            },
        )
        registry.publish(
            run.run_id,
            "phase_started",
            round_number=2,
            phase="day",
            payload={"narration_mode": "explicit_v1"},
        )
        registry.mark_completed(run.run_id, winner="好人阵营")
        await asyncio.wait_for(task, timeout=1)

    asyncio.run(stream_live_events())

    spoken_texts = [
        "".join(call["text_chunks"])
        for instance in RecordingTtsClient.instances
        for call in instance.calls
    ]
    assert spoken_texts.count("昨夜死亡的玩家是 1号玩家。") == 1
    assert len([text for text in spoken_texts if text.startswith("昨夜死亡")]) == 1


def test_voice_stream_service_plays_static_sheriff_direction_prompt(tmp_path) -> None:
    RecordingTtsClient.instances.clear()
    asset_dir = tmp_path / "judge-voice"
    asset_dir.mkdir()
    (asset_dir / "sheriff_choose_badge_side.mp3").write_bytes(b"static-direction")
    (asset_dir / "game_over_villagers.mp3").write_bytes(b"static-end")
    (asset_dir / "manifest.json").write_text(
        """
        {
          "audio_format": "mp3",
          "sample_rate": 24000,
          "mime_type": "audio/mpeg",
          "lines": [
            {
              "id": "sheriff_choose_badge_side",
              "filename": "sheriff_choose_badge_side.mp3",
              "exists": true
            },
            {
              "id": "game_over_villagers",
              "filename": "game_over_villagers.mp3",
              "exists": true
            }
          ]
        }
        """,
        encoding="utf-8",
    )
    registry = LiveRunRegistry()
    run = create_run(registry)
    websocket = FakeWebSocket()
    service = LiveVoiceStreamService(
        registry=registry,
        config=replace(BASE_TTS_CONFIG, audio_format="mp3"),
        client_factory=RecordingTtsClient,
        judge_voice_asset_dir=asset_dir,
    )

    async def stream_live_events() -> None:
        task = asyncio.create_task(service.stream_run(run.run_id, websocket))
        await wait_for_subscription(registry, run.run_id)
        registry.publish(
            run.run_id,
            "action_requested",
            round_number=1,
            phase="day",
            actor="阿青",
            action="speech_order",
            payload={"options": ["警左发言", "警右发言"]},
        )
        registry.mark_completed(run.run_id, winner="好人阵营")
        await asyncio.wait_for(task, timeout=1)

    asyncio.run(stream_live_events())

    assert RecordingTtsClient.instances == []
    assert [message["type"] for message in websocket.messages] == [
        "voice_start",
        "audio_chunk",
        "voice_end",
        "voice_start",
        "audio_chunk",
        "voice_end",
    ]
    direction_start, direction_chunk, direction_end = websocket.messages[:3]
    assert direction_start["speaker_kind"] == "judge"
    assert direction_start["speaker_name"] == "法官"
    assert direction_start["audio_format"] == "mp3"
    assert direction_chunk["data"] == "c3RhdGljLWRpcmVjdGlvbg=="
    assert direction_end["utterance_id"] == direction_start["utterance_id"]


def test_voice_stream_service_uses_static_judge_assets_when_format_differs_from_live_config(
    tmp_path,
) -> None:
    RecordingTtsClient.instances.clear()
    asset_dir = tmp_path / "judge-voice"
    asset_dir.mkdir()
    (asset_dir / "night_start.mp3").write_bytes(b"static-night")
    (asset_dir / "game_over_villagers.mp3").write_bytes(b"static-end")
    (asset_dir / "manifest.json").write_text(
        """
        {
          "audio_format": "mp3",
          "sample_rate": 24000,
          "mime_type": "audio/mpeg",
          "lines": [
            {
              "id": "night_start",
              "filename": "night_start.mp3",
              "exists": true,
              "subtitle_timings": [
                {"text": "夜晚降临，", "start_ms": 0, "end_ms": 500}
              ]
            },
            {
              "id": "game_over_villagers",
              "filename": "game_over_villagers.mp3",
              "exists": true,
              "subtitle_timings": [
                {"text": "游戏结束，", "start_ms": 0, "end_ms": 400}
              ]
            }
          ]
        }
        """,
        encoding="utf-8",
    )
    registry = LiveRunRegistry()
    run = create_run(registry)
    websocket = FakeWebSocket()
    service = LiveVoiceStreamService(
        registry=registry,
        config=BASE_TTS_CONFIG,
        client_factory=RecordingTtsClient,
        judge_voice_asset_dir=asset_dir,
    )

    async def stream_live_events() -> None:
        task = asyncio.create_task(service.stream_run(run.run_id, websocket))
        await wait_for_subscription(registry, run.run_id)
        registry.publish(
            run.run_id,
            "phase_started",
            round_number=1,
            phase="night",
            payload={"active_players": ["阿青", "白石"]},
        )
        registry.mark_completed(run.run_id, winner="好人阵营")
        await asyncio.wait_for(task, timeout=1)

    asyncio.run(stream_live_events())

    assert RecordingTtsClient.instances == []
    start, subtitle, chunk, _end = websocket.messages[:4]
    assert start["speaker_kind"] == "judge"
    assert start["audio_format"] == "mp3"
    assert start["sample_rate"] == 24000
    assert subtitle == {
        "type": "subtitle_timing",
        "utterance_id": start["utterance_id"],
        "cues": [{"text": "夜晚降临，", "start_ms": 0, "end_ms": 500}],
    }
    assert chunk["audio_format"] == "mp3"
    assert chunk["data"] == "c3RhdGljLW5pZ2h0"


def test_voice_stream_service_streams_multiple_audio_chunks_per_utterance(tmp_path) -> None:
    MultiChunkTtsClient.instances.clear()
    registry = LiveRunRegistry()
    run = create_run(registry)
    websocket = FakeWebSocket()
    service = LiveVoiceStreamService(
        registry=registry,
        config=BASE_TTS_CONFIG,
        client_factory=MultiChunkTtsClient,
        judge_voice_asset_dir=tmp_path / "judge-voice",
    )

    async def stream_live_events() -> None:
        task = asyncio.create_task(service.stream_run(run.run_id, websocket))
        await wait_for_subscription(registry, run.run_id)
        registry.publish(
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
        registry.mark_completed(run.run_id, winner="好人阵营")
        await asyncio.wait_for(task, timeout=1)

    asyncio.run(stream_live_events())

    assert [message["type"] for message in websocket.messages[:4]] == [
        "voice_start",
        "audio_chunk",
        "audio_chunk",
        "voice_end",
    ]
    start, first_chunk, second_chunk, _end = websocket.messages[:4]
    assert start["audio_format"] == "pcm"
    assert start["sample_rate"] == 24000
    assert first_chunk["chunk_index"] == 0
    assert first_chunk["audio_format"] == "pcm"
    assert first_chunk["sample_rate"] == 24000
    assert first_chunk["data"] == "Zmlyc3Q="
    assert second_chunk["chunk_index"] == 1
    assert second_chunk["audio_format"] == "pcm"
    assert second_chunk["sample_rate"] == 24000
    assert second_chunk["data"] == "c2Vjb25k"
    assert websocket.messages[5]["chunk_index"] == 0


def test_voice_stream_service_forwards_and_persists_subtitle_timing_events() -> None:
    SubtitleTtsClient.instances.clear()
    registry = LiveRunRegistry()
    run = create_run(registry)
    websocket = FakeWebSocket()
    voice_store = RecordingVoiceStore()
    service = LiveVoiceStreamService(
        registry=registry,
        config=BASE_TTS_CONFIG,
        client_factory=SubtitleTtsClient,
        voice_store_factory=lambda session_id: voice_store,
    )

    async def stream_live_events() -> None:
        task = asyncio.create_task(service.stream_run(run.run_id, websocket))
        await wait_for_subscription(registry, run.run_id)
        registry.publish(
            run.run_id,
            "model_response_delta",
            actor="阿青",
            action="debate",
            payload={
                "request_id": "req-subtitle",
                "visible_text": "我先发言。",
                "is_public": True,
            },
        )
        registry.mark_completed(run.run_id, winner="好人阵营")
        await asyncio.wait_for(task, timeout=1)

    asyncio.run(stream_live_events())

    start, subtitle, chunk, end = websocket.messages[:4]
    assert [message["type"] for message in websocket.messages[:4]] == [
        "voice_start",
        "subtitle_timing",
        "audio_chunk",
        "voice_end",
    ]
    assert subtitle == {
        "type": "subtitle_timing",
        "utterance_id": start["utterance_id"],
        "cues": [
            {"text": "我", "start_ms": 0, "end_ms": 180},
            {"text": "先发言。", "start_ms": 180, "end_ms": 820},
        ],
    }
    assert chunk["utterance_id"] == start["utterance_id"]
    assert end["utterance_id"] == start["utterance_id"]
    matching_timings = [
        timing
        for timing in voice_store.subtitle_timings
        if timing["utterance_id"] == start["utterance_id"]
    ]
    assert matching_timings == [
        {
            "utterance_id": start["utterance_id"],
            "subtitle_timings": subtitle["cues"],
        }
    ]


def test_voice_stream_service_persists_successful_utterance_chunks_and_completion() -> None:
    MultiChunkTtsClient.instances.clear()
    registry = LiveRunRegistry()
    run = create_run(registry)
    websocket = FakeWebSocket()
    voice_store = RecordingVoiceStore()
    service = LiveVoiceStreamService(
        registry=registry,
        config=BASE_TTS_CONFIG,
        client_factory=MultiChunkTtsClient,
        voice_store_factory=lambda session_id: voice_store,
    )

    async def stream_live_events() -> None:
        task = asyncio.create_task(service.stream_run(run.run_id, websocket))
        await wait_for_subscription(registry, run.run_id)
        registry.publish(
            run.run_id,
            "model_response_delta",
            actor="阿青",
            action="debate",
            payload={
                "request_id": "req-persist",
                "visible_text": "我先发言。",
                "is_public": True,
            },
        )
        registry.mark_completed(run.run_id, winner="好人阵营")
        await asyncio.wait_for(task, timeout=1)

    asyncio.run(stream_live_events())

    start, first_chunk, second_chunk, end = websocket.messages[:4]
    assert [message["type"] for message in websocket.messages[:4]] == [
        "voice_start",
        "audio_chunk",
        "audio_chunk",
        "voice_end",
    ]
    assert voice_store.utterances[0]["utterance"].utterance_id == start["utterance_id"]
    assert voice_store.utterances[0]["utterance"].text == "我先发言。"
    assert voice_store.utterances[0]["audio_format"] == "pcm"
    assert voice_store.utterances[0]["sample_rate"] == 24000
    assert voice_store.utterances[0]["mime_type"] == "audio/L16"
    assert voice_store.utterances[0]["status"] == "synthesizing"
    assert voice_store.chunks[:2] == [
        {
            "utterance_id": start["utterance_id"],
            "chunk_index": first_chunk["chunk_index"],
            "audio": b"first",
        },
        {
            "utterance_id": start["utterance_id"],
            "chunk_index": second_chunk["chunk_index"],
            "audio": b"second",
        },
    ]
    assert voice_store.completed[0]["utterance_id"] == start["utterance_id"]
    assert voice_store.completed[0]["duration_ms"] == end["duration_ms"]
    assert voice_store.failed == []


def test_voice_stream_service_ignores_private_summary_deltas(
    db_session: Session,
) -> None:
    RecordingTtsClient.instances.clear()
    registry = LiveRunRegistry()
    run = create_run(registry)
    store = DatabaseVoiceStore(db_session, session_id=run.session_id)
    websocket = FakeWebSocket()
    service = LiveVoiceStreamService(
        registry=registry,
        config=BASE_TTS_CONFIG,
        client_factory=RecordingTtsClient,
        voice_store_factory=lambda session_id: store,
    )

    async def stream_live_events() -> None:
        task = asyncio.create_task(service.stream_run(run.run_id, websocket))
        await wait_for_subscription(registry, run.run_id)
        registry.publish(
            run.run_id,
            "model_response_delta",
            actor="阿青",
            action="summarize",
            phase="summary",
            payload={
                "request_id": "req-summary",
                "visible_text": "这一轮先看票型，",
                "is_public": True,
            },
        )
        registry.publish(
            run.run_id,
            "model_response_delta",
            actor="阿青",
            action="summarize",
            phase="summary",
            payload={
                "request_id": "req-summary",
                "visible_text": "再听下一轮发言。",
                "is_public": True,
            },
        )
        registry.mark_completed(run.run_id, winner="好人阵营")
        await asyncio.wait_for(task, timeout=1)

        saved_text = "\n".join(
            str(voice.get("text") or "") for voice in store.list_playback_voices()
        )
        assert "这一轮先看票型" not in saved_text
        assert "再听下一轮发言" not in saved_text

    asyncio.run(stream_live_events())


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

    player_calls = [
        call
        for instance in RecordingTtsClient.instances
        for call in instance.calls
        if call["speaker"] == "player"
    ]
    assert player_calls == []


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
    player_calls = [call for call in calls if call["speaker"] == "player"]
    assert player_calls == [
        {"speaker": "player", "text_chunks": ["这是连接后的现场发言。"]},
    ]


def test_voice_stream_service_replays_historical_current_event_on_connect(tmp_path) -> None:
    RecordingTtsClient.instances.clear()
    asset_dir = tmp_path / "judge-voice"
    asset_dir.mkdir()
    (asset_dir / "game_intro.mp3").write_bytes(b"static-intro")
    (asset_dir / "night_start.mp3").write_bytes(b"static-night")
    (asset_dir / "manifest.json").write_text(
        """
        {
          "audio_format": "mp3",
          "sample_rate": 24000,
          "mime_type": "audio/mpeg",
          "lines": [
            {"id": "game_intro", "filename": "game_intro.mp3", "exists": true},
            {"id": "night_start", "filename": "night_start.mp3", "exists": true}
          ]
        }
        """,
        encoding="utf-8",
    )
    registry = LiveRunRegistry()
    run = create_run(registry)
    game_started = registry.publish(
        run.run_id,
        "game_started",
        payload={
            "players": [
                {"name": "阿青", "role": "villager", "model": "test-model"},
                {"name": "白石", "role": "werewolf", "model": "test-model"},
            ]
        },
    )
    night_started = registry.publish(
        run.run_id,
        "phase_started",
        round_number=1,
        phase="night",
        payload={"active_players": ["阿青", "白石"]},
    )
    websocket = FakeWebSocket()
    service = LiveVoiceStreamService(
        registry=registry,
        config=replace(BASE_TTS_CONFIG, audio_format="mp3"),
        client_factory=RecordingTtsClient,
        judge_voice_asset_dir=asset_dir,
    )

    async def stream_events() -> None:
        task = asyncio.create_task(
            service.stream_run(
                run.run_id,
                websocket,
                current_event_id=game_started.id,
            )
        )
        await wait_for_subscription(registry, run.run_id)
        registry.mark_completed(run.run_id, winner="好人阵营")
        await asyncio.wait_for(task, timeout=1)

    asyncio.run(stream_events())

    first_start, first_chunk, first_end = websocket.messages[:3]
    second_start, second_chunk, second_end = websocket.messages[3:6]
    assert [message["type"] for message in websocket.messages[:6]] == [
        "voice_start",
        "audio_chunk",
        "voice_end",
        "voice_start",
        "audio_chunk",
        "voice_end",
    ]
    assert first_start["source_event_id"] == game_started.id
    assert first_start["speaker_kind"] == "judge"
    assert first_start["speaker_name"] == "法官"
    assert first_start["audio_format"] == "mp3"
    assert first_chunk["data"] == "c3RhdGljLWludHJv"
    assert first_end["utterance_id"] == first_start["utterance_id"]
    assert second_start["source_event_id"] == night_started.id
    assert second_start["speaker_kind"] == "judge"
    assert second_start["speaker_name"] == "法官"
    assert second_start["audio_format"] == "mp3"
    assert second_chunk["data"] == "c3RhdGljLW5pZ2h0"
    assert second_end["utterance_id"] == second_start["utterance_id"]


def test_voice_stream_service_replays_recent_complete_utterance_then_streams_future_events() -> (
    None
):
    RecordingTtsClient.instances.clear()
    registry = LiveRunRegistry()
    run = create_run(registry)
    registry.publish(
        run.run_id,
        "game_started",
        payload={
            "players": [
                {"name": "阿青", "role": "villager", "model": "test-model"},
                {"name": "白石", "role": "werewolf", "model": "test-model"},
            ]
        },
    )
    voice_store = RecordingVoiceStore()
    voice_store.recent_utterance = {
        "utterance_id": "stored-voice-1",
        "run_id": run.run_id,
        "source_event_id": 6,
        "last_source_event_id": 7,
        "speaker_kind": "player",
        "speaker_name": "阿青",
        "audio_format": "pcm",
        "sample_rate": 24000,
        "mime_type": "audio/L16",
        "status": "complete",
        "duration_ms": 345,
        "subtitle_timings": [
            {"text": "旧", "start_ms": 0, "end_ms": 120},
            {"text": "发言", "start_ms": 120, "end_ms": 345},
        ],
    }
    voice_store.replay_chunks = [b"old-audio-0", b"old-audio-1"]
    websocket = FakeWebSocket()
    service = LiveVoiceStreamService(
        registry=registry,
        config=BASE_TTS_CONFIG,
        client_factory=RecordingTtsClient,
        voice_store_factory=lambda session_id: voice_store,
    )

    async def stream_events() -> None:
        task = asyncio.create_task(service.stream_run(run.run_id, websocket, current_event_id=7))
        await wait_for_subscription(registry, run.run_id)
        registry.publish(
            run.run_id,
            "model_response_delta",
            actor="白石",
            action="debate",
            payload={
                "request_id": "req-live-after-replay",
                "visible_text": "这是重连后的现场发言。",
                "is_public": True,
            },
        )
        registry.mark_completed(run.run_id, winner="好人阵营")
        await asyncio.wait_for(task, timeout=1)

    asyncio.run(stream_events())

    assert voice_store.find_recent_calls == [{"run_id": run.run_id, "current_event_id": 7}]
    assert websocket.messages[:5] == [
        {
            "type": "voice_start",
            "utterance_id": "stored-voice-1",
            "source_event_id": 6,
            "last_source_event_id": 7,
            "speaker_kind": "player",
            "speaker_name": "阿青",
            "mime_type": "audio/L16",
            "audio_format": "pcm",
            "sample_rate": 24000,
        },
        {
            "type": "subtitle_timing",
            "utterance_id": "stored-voice-1",
            "cues": [
                {"text": "旧", "start_ms": 0, "end_ms": 120},
                {"text": "发言", "start_ms": 120, "end_ms": 345},
            ],
        },
        {
            "type": "audio_chunk",
            "utterance_id": "stored-voice-1",
            "chunk_index": 0,
            "mime_type": "audio/L16",
            "audio_format": "pcm",
            "sample_rate": 24000,
            "data": "b2xkLWF1ZGlvLTA=",
        },
        {
            "type": "audio_chunk",
            "utterance_id": "stored-voice-1",
            "chunk_index": 1,
            "mime_type": "audio/L16",
            "audio_format": "pcm",
            "sample_rate": 24000,
            "data": "b2xkLWF1ZGlvLTE=",
        },
        {
            "type": "voice_end",
            "utterance_id": "stored-voice-1",
            "duration_ms": 345,
        },
    ]
    assert [message["type"] for message in websocket.messages[5:8]] == [
        "voice_start",
        "audio_chunk",
        "voice_end",
    ]
    assert websocket.messages[5]["speaker_name"] == "2号玩家"
    calls = [call for instance in RecordingTtsClient.instances for call in instance.calls]
    assert calls[0] == {
        "speaker": "player",
        "text_chunks": ["这是重连后的现场发言。"],
    }


def test_voice_stream_service_replays_database_utterance_when_newer_rows_are_invalid(
    db_session: Session,
) -> None:
    RecordingTtsClient.instances.clear()
    registry = LiveRunRegistry()
    run = create_run(registry)
    store = DatabaseVoiceStore(db_session, session_id=run.session_id)
    complete = stored_voice_utterance(
        utterance_id="stored-complete",
        run_id=run.run_id,
        source_event_id=4,
        text="这是可回放的历史发言。",
    )
    failed = stored_voice_utterance(
        utterance_id="stored-failed",
        run_id=run.run_id,
        source_event_id=7,
        text="这是失败的历史发言。",
    )
    chunkless = stored_voice_utterance(
        utterance_id="stored-chunkless",
        run_id=run.run_id,
        source_event_id=8,
        text="这是没有音频的历史发言。",
    )
    invalid_kind = stored_voice_utterance(
        utterance_id="stored-invalid-kind",
        run_id=run.run_id,
        source_event_id=9,
        text="这是角色类型异常的历史发言。",
        speaker_kind="moderator",
    )
    store.upsert_utterance(
        complete,
        audio_format="pcm",
        sample_rate=24000,
        mime_type="audio/L16",
    )
    store.append_chunk("stored-complete", chunk_index=0, audio=b"complete-audio")
    store.complete_utterance("stored-complete", duration_ms=456)
    store.upsert_utterance(
        failed,
        audio_format="pcm",
        sample_rate=24000,
        mime_type="audio/L16",
    )
    store.append_chunk("stored-failed", chunk_index=0, audio=b"failed-audio")
    store.fail_utterance("stored-failed", message="tts failed")
    store.upsert_utterance(
        chunkless,
        audio_format="pcm",
        sample_rate=24000,
        mime_type="audio/L16",
    )
    store.complete_utterance("stored-chunkless", duration_ms=100)
    store.upsert_utterance(
        invalid_kind,
        audio_format="pcm",
        sample_rate=24000,
        mime_type="audio/L16",
    )
    store.append_chunk("stored-invalid-kind", chunk_index=0, audio=b"invalid-kind-audio")
    store.complete_utterance("stored-invalid-kind", duration_ms=100)
    websocket = FakeWebSocket()
    service = LiveVoiceStreamService(
        registry=registry,
        config=BASE_TTS_CONFIG,
        client_factory=RecordingTtsClient,
        voice_store_factory=lambda session_id: DatabaseVoiceStore(
            db_session,
            session_id=session_id,
        ),
    )

    async def stream_then_disconnect() -> None:
        task = asyncio.create_task(service.stream_run(run.run_id, websocket, current_event_id=9))
        await wait_for_subscription(registry, run.run_id)
        websocket.disconnect()
        await asyncio.wait_for(task, timeout=1)

    asyncio.run(stream_then_disconnect())

    assert websocket.messages == [
        {
            "type": "voice_start",
            "utterance_id": "stored-complete",
            "source_event_id": 4,
            "last_source_event_id": 4,
            "speaker_kind": "player",
            "speaker_name": "阿青",
            "mime_type": "audio/L16",
            "audio_format": "pcm",
            "sample_rate": 24000,
        },
        {
            "type": "audio_chunk",
            "utterance_id": "stored-complete",
            "chunk_index": 0,
            "mime_type": "audio/L16",
            "audio_format": "pcm",
            "sample_rate": 24000,
            "data": "Y29tcGxldGUtYXVkaW8=",
        },
        {
            "type": "voice_end",
            "utterance_id": "stored-complete",
            "duration_ms": 456,
        },
    ]
    assert RecordingTtsClient.instances == []
    assert registry.get_run(run.run_id).subscribers == []


@pytest.mark.parametrize(
    ("status", "chunks"),
    [
        ("synthesizing", [b"partial-audio"]),
        ("complete", []),
    ],
)
def test_voice_stream_service_ignores_incomplete_or_chunkless_recent_utterance(
    status: str,
    chunks: list[bytes],
) -> None:
    registry = LiveRunRegistry()
    run = create_run(registry)
    voice_store = RecordingVoiceStore()
    voice_store.recent_utterance = {
        "utterance_id": "stored-voice-ignored",
        "run_id": run.run_id,
        "source_event_id": 6,
        "last_source_event_id": 7,
        "speaker_kind": "player",
        "speaker_name": "阿青",
        "audio_format": "pcm",
        "sample_rate": 24000,
        "mime_type": "audio/L16",
        "status": status,
        "duration_ms": 345,
    }
    voice_store.replay_chunks = chunks
    websocket = FakeWebSocket()
    service = LiveVoiceStreamService(
        registry=registry,
        config=BASE_TTS_CONFIG,
        client_factory=RecordingTtsClient,
        voice_store_factory=lambda session_id: voice_store,
    )

    async def stream_then_disconnect() -> None:
        task = asyncio.create_task(service.stream_run(run.run_id, websocket, current_event_id=7))
        await wait_for_subscription(registry, run.run_id)
        websocket.disconnect()
        await asyncio.wait_for(task, timeout=1)

    asyncio.run(stream_then_disconnect())

    assert websocket.messages == []
    assert registry.get_run(run.run_id).subscribers == []


def test_voice_stream_service_reports_unavailable_when_run_is_terminal() -> None:
    RecordingTtsClient.instances.clear()
    registry = LiveRunRegistry()
    run = create_run(registry)
    registry.mark_failed(run.run_id, error="engine failed")
    websocket = FakeWebSocket()
    service = LiveVoiceStreamService(
        registry=registry,
        config=BASE_TTS_CONFIG,
        client_factory=RecordingTtsClient,
    )

    asyncio.run(service.stream_run(run.run_id, websocket))

    assert registry.get_run(run.run_id).subscribers == []
    assert websocket.messages == [
        {
            "type": "voice_unavailable",
            "reason": "terminal",
            "message": "语音只支持进行中的实时对局；该对局已结束或异常中断。",
        }
    ]
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

    assert websocket.messages == [
        {
            "type": "voice_unavailable",
            "reason": "disabled",
            "message": "语音服务未启用，请检查后端语音配置。",
        }
    ]
    assert registry.get_run(run.run_id).subscribers == []


def test_voice_stream_service_reports_misconfigured_reason() -> None:
    registry = LiveRunRegistry()
    run = create_run(registry)
    websocket = FakeWebSocket()
    service = LiveVoiceStreamService(
        registry=registry,
        config=replace(BASE_TTS_CONFIG, api_key=""),
        client_factory=RecordingTtsClient,
    )

    asyncio.run(service.stream_run(run.run_id, websocket))

    assert websocket.messages == [
        {
            "type": "voice_unavailable",
            "reason": "misconfigured",
            "message": "语音模型配置不完整，请检查 Ark API Key、资源 ID 和音色配置。",
        }
    ]
    assert registry.get_run(run.run_id).subscribers == []


def test_voice_stream_service_continues_after_synthesis_error(tmp_path) -> None:
    FailingThenRecordingTtsClient.instances.clear()
    registry = LiveRunRegistry()
    run = create_run(registry)
    websocket = FakeWebSocket()
    service = LiveVoiceStreamService(
        registry=registry,
        config=BASE_TTS_CONFIG,
        client_factory=FailingThenRecordingTtsClient,
        judge_voice_asset_dir=tmp_path / "judge-voice",
    )

    async def stream_live_events() -> None:
        task = asyncio.create_task(service.stream_run(run.run_id, websocket))
        await wait_for_subscription(registry, run.run_id)
        first_event = registry.publish(
            run.run_id,
            "model_response_delta",
            actor="阿青",
            action="debate",
            payload={
                "request_id": "req-fails",
                "visible_text": "我先发言。",
                "is_public": True,
            },
        )
        second_event = registry.publish(
            run.run_id,
            "model_response_delta",
            actor="白石",
            action="debate",
            payload={
                "request_id": "req-recovers",
                "visible_text": "我继续发言。",
                "is_public": True,
            },
        )
        registry.mark_completed(run.run_id, winner="好人阵营")
        await asyncio.wait_for(task, timeout=1)
        assert websocket.messages[0]["source_event_id"] == first_event.id
        assert websocket.messages[2]["source_event_id"] == second_event.id

    asyncio.run(stream_live_events())

    assert registry.get_run(run.run_id).subscribers == []
    assert [message["type"] for message in websocket.messages] == [
        "voice_start",
        "voice_error",
        "voice_start",
        "audio_chunk",
        "voice_end",
        "voice_start",
        "audio_chunk",
        "voice_end",
    ]
    assert websocket.messages[1] == {
        "type": "voice_error",
        "utterance_id": websocket.messages[0]["utterance_id"],
        "source_event_id": websocket.messages[0]["source_event_id"],
        "message": "Voice synthesis failed",
    }
    assert websocket.messages[2]["audio_format"] == "pcm"
    assert websocket.messages[2]["sample_rate"] == 24000
    assert websocket.messages[3]["chunk_index"] == 0
    assert websocket.messages[3]["audio_format"] == "pcm"
    assert websocket.messages[3]["sample_rate"] == 24000


def test_voice_stream_service_persists_synthesis_failure_and_continues() -> None:
    FailingThenRecordingTtsClient.instances.clear()
    registry = LiveRunRegistry()
    run = create_run(registry)
    websocket = FakeWebSocket()
    voice_store = RecordingVoiceStore()
    service = LiveVoiceStreamService(
        registry=registry,
        config=BASE_TTS_CONFIG,
        client_factory=FailingThenRecordingTtsClient,
        voice_store_factory=lambda session_id: voice_store,
    )

    async def stream_live_events() -> None:
        task = asyncio.create_task(service.stream_run(run.run_id, websocket))
        await wait_for_subscription(registry, run.run_id)
        registry.publish(
            run.run_id,
            "model_response_delta",
            actor="阿青",
            action="debate",
            payload={
                "request_id": "req-fails",
                "visible_text": "我先发言。",
                "is_public": True,
            },
        )
        registry.publish(
            run.run_id,
            "model_response_delta",
            actor="白石",
            action="debate",
            payload={
                "request_id": "req-recovers",
                "visible_text": "我继续发言。",
                "is_public": True,
            },
        )
        registry.mark_completed(run.run_id, winner="好人阵营")
        await asyncio.wait_for(task, timeout=1)

    asyncio.run(stream_live_events())

    assert [message["type"] for message in websocket.messages[:5]] == [
        "voice_start",
        "voice_error",
        "voice_start",
        "audio_chunk",
        "voice_end",
    ]
    failed_utterance_id = websocket.messages[0]["utterance_id"]
    recovered_utterance_id = websocket.messages[2]["utterance_id"]
    assert voice_store.failed == [
        {
            "utterance_id": failed_utterance_id,
            "message": "Voice synthesis failed",
        }
    ]
    assert voice_store.completed[0]["utterance_id"] == recovered_utterance_id
    assert voice_store.chunks[0] == {
        "utterance_id": recovered_utterance_id,
        "chunk_index": 0,
        "audio": b"abc",
    }


@pytest.mark.parametrize("fail_method", ["upsert_utterance", "append_chunk"])
def test_voice_stream_service_continues_audio_when_persistence_fails(
    fail_method: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    RecordingTtsClient.instances.clear()
    registry = LiveRunRegistry()
    run = create_run(registry)
    websocket = FakeWebSocket()
    voice_store = FailingVoiceStore(fail_method=fail_method)
    service = LiveVoiceStreamService(
        registry=registry,
        config=BASE_TTS_CONFIG,
        client_factory=RecordingTtsClient,
        voice_store_factory=lambda session_id: voice_store,
    )

    async def stream_live_events() -> None:
        task = asyncio.create_task(service.stream_run(run.run_id, websocket))
        await wait_for_subscription(registry, run.run_id)
        registry.publish(
            run.run_id,
            "model_response_delta",
            actor="阿青",
            action="debate",
            payload={
                "request_id": "req-persist-fails",
                "visible_text": "我先发言。",
                "is_public": True,
            },
        )
        registry.mark_completed(run.run_id, winner="好人阵营")
        await asyncio.wait_for(task, timeout=1)

    with caplog.at_level("WARNING", logger="app.werewolf.voice_stream"):
        asyncio.run(stream_live_events())

    assert [message["type"] for message in websocket.messages[:3]] == [
        "voice_start",
        "audio_chunk",
        "voice_end",
    ]
    start, chunk, _end = websocket.messages[:3]
    assert chunk["utterance_id"] == start["utterance_id"]
    assert chunk["chunk_index"] == 0
    assert chunk["data"] == "YWJj"
    assert "voice_error" not in [message["type"] for message in websocket.messages]
    assert any(
        record.message == "Voice persistence failed"
        and record.utterance_id == start["utterance_id"]
        and record.persistence_operation == fail_method
        for record in caplog.records
    )


def test_voice_stream_service_skips_dependent_persistence_after_upsert_failure(
    caplog: pytest.LogCaptureFixture,
) -> None:
    RecordingTtsClient.instances.clear()
    registry = LiveRunRegistry()
    run = create_run(registry)
    websocket = FakeWebSocket()
    voice_store = FailingVoiceStore(fail_method="upsert_utterance")
    service = LiveVoiceStreamService(
        registry=registry,
        config=BASE_TTS_CONFIG,
        client_factory=RecordingTtsClient,
        voice_store_factory=lambda session_id: voice_store,
    )

    async def stream_live_events() -> None:
        task = asyncio.create_task(service.stream_run(run.run_id, websocket))
        await wait_for_subscription(registry, run.run_id)
        registry.publish(
            run.run_id,
            "model_response_delta",
            actor="阿青",
            action="debate",
            payload={
                "request_id": "req-persist-parent-fails",
                "visible_text": "我先发言。",
                "is_public": True,
            },
        )
        registry.mark_completed(run.run_id, winner="好人阵营")
        await asyncio.wait_for(task, timeout=1)

    with caplog.at_level("WARNING", logger="app.werewolf.voice_stream"):
        asyncio.run(stream_live_events())

    assert [message["type"] for message in websocket.messages[:3]] == [
        "voice_start",
        "audio_chunk",
        "voice_end",
    ]
    utterance_id = websocket.messages[0]["utterance_id"]
    assert [chunk for chunk in voice_store.chunks if chunk["utterance_id"] == utterance_id] == []
    assert [
        completed
        for completed in voice_store.completed
        if completed["utterance_id"] == utterance_id
    ] == []
    assert [
        record.persistence_operation
        for record in caplog.records
        if record.message == "Voice persistence failed" and record.utterance_id == utterance_id
    ] == ["upsert_utterance"]


def test_voice_stream_service_groups_immediate_deltas_by_request_id() -> None:
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
        first_event = registry.publish(
            run.run_id,
            "model_response_delta",
            actor="阿青",
            action="debate",
            payload={
                "request_id": "req-shared",
                "visible_text": "我是阿青，",
                "is_public": True,
            },
        )
        registry.publish(
            run.run_id,
            "model_response_delta",
            actor="阿青",
            action="debate",
            payload={
                "request_id": "req-shared",
                "visible_text": "我继续发言。",
                "is_public": True,
            },
        )
        registry.mark_completed(run.run_id, winner="好人阵营")
        await asyncio.wait_for(task, timeout=1)
        assert websocket.messages[0]["source_event_id"] == first_event.id

    asyncio.run(stream_live_events())

    player_calls = [
        call
        for instance in RecordingTtsClient.instances
        for call in instance.calls
        if call["speaker"] == "player"
    ]
    assert player_calls == [
        {
            "speaker": "player",
            "text_chunks": ["我是阿青，", "我继续发言。"],
        }
    ]
    assert [message["type"] for message in websocket.messages[:3]] == [
        "voice_start",
        "audio_chunk",
        "voice_end",
    ]
    assert websocket.messages[0]["audio_format"] == "pcm"
    assert websocket.messages[0]["sample_rate"] == 24000
    assert websocket.messages[1]["chunk_index"] == 0
    assert websocket.messages[1]["audio_format"] == "pcm"
    assert websocket.messages[1]["sample_rate"] == 24000


@pytest.mark.parametrize("with_response_received", [False, True])
def test_voice_stream_service_does_not_repeat_final_speech_after_deltas(
    with_response_received: bool,
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

    async def stream_live_events() -> None:
        task = asyncio.create_task(service.stream_run(run.run_id, websocket))
        await wait_for_subscription(registry, run.run_id)
        registry.publish(
            run.run_id,
            "model_response_delta",
            actor="阿青",
            action="debate",
            payload={
                "request_id": "req-no-repeat",
                "visible_text": "我是阿青，",
                "is_public": True,
            },
        )
        registry.publish(
            run.run_id,
            "model_response_delta",
            actor="阿青",
            action="debate",
            payload={
                "request_id": "req-no-repeat",
                "visible_text": "我继续发言。",
                "is_public": True,
            },
        )
        if with_response_received:
            registry.publish(
                run.run_id,
                "model_response_received",
                actor="阿青",
                action="debate",
                payload={
                    "request_id": "req-no-repeat",
                    "message": "模型返回已接收，正在解析行动",
                },
            )
        registry.publish(
            run.run_id,
            "action_parsed",
            actor="阿青",
            action="debate",
            payload={
                "request_id": "req-no-repeat",
                "visible_result": {"say": "我是阿青，我继续发言。"},
            },
        )
        registry.mark_completed(run.run_id, winner="好人阵营")
        await asyncio.wait_for(task, timeout=1)

    asyncio.run(stream_live_events())

    player_calls = [
        call
        for instance in RecordingTtsClient.instances
        for call in instance.calls
        if call["speaker"] == "player"
    ]
    assert player_calls == [
        {
            "speaker": "player",
            "text_chunks": ["我是阿青，", "我继续发言。"],
        }
    ]


def test_voice_stream_service_uses_final_speech_when_no_deltas_were_streamed() -> None:
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
            "action_parsed",
            actor="阿青",
            action="debate",
            payload={
                "request_id": "req-final-only",
                "visible_result": {"say": "这是最终完整发言。"},
            },
        )
        registry.mark_completed(run.run_id, winner="好人阵营")
        await asyncio.wait_for(task, timeout=1)

    asyncio.run(stream_live_events())

    player_calls = [
        call
        for instance in RecordingTtsClient.instances
        for call in instance.calls
        if call["speaker"] == "player"
    ]
    assert player_calls == [
        {
            "speaker": "player",
            "text_chunks": ["这是最终完整发言。"],
        }
    ]


def test_voice_stream_service_groups_delayed_deltas_by_request_id() -> None:
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
            actor="阿青",
            action="debate",
            payload={
                "request_id": "req-delayed",
                "visible_text": "第一句，",
                "is_public": True,
            },
        )
        await asyncio.sleep(0.02)
        registry.publish(
            run.run_id,
            "model_response_delta",
            actor="阿青",
            action="debate",
            payload={
                "request_id": "req-delayed",
                "visible_text": "第二句。",
                "is_public": True,
            },
        )
        registry.mark_completed(run.run_id, winner="好人阵营")
        await asyncio.wait_for(task, timeout=1)

    asyncio.run(stream_live_events())

    player_calls = [
        call
        for instance in RecordingTtsClient.instances
        for call in instance.calls
        if call["speaker"] == "player"
    ]
    assert player_calls == [
        {
            "speaker": "player",
            "text_chunks": ["第一句，", "第二句。"],
        }
    ]


def test_voice_stream_service_waits_for_playback_ack_before_next_tts_request() -> None:
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
        task = asyncio.create_task(
            service.stream_run(
                run.run_id,
                websocket,
                playback_ack_required=True,
            )
        )
        await wait_for_subscription(registry, run.run_id)
        registry.publish(
            run.run_id,
            "model_response_delta",
            actor="阿青",
            action="debate",
            payload={
                "request_id": "req-first",
                "visible_text": "我是第一位发言。",
                "is_public": True,
            },
        )
        registry.publish(
            run.run_id,
            "model_response_delta",
            actor="白石",
            action="debate",
            payload={
                "request_id": "req-second",
                "visible_text": "我是第二位发言。",
                "is_public": True,
            },
        )
        await wait_for_messages(websocket, 3)

        calls_before_ack = [
            call for instance in RecordingTtsClient.instances for call in instance.calls
        ]
        assert calls_before_ack == [
            {"speaker": "player", "text_chunks": ["我是第一位发言。"]},
        ]
        first_utterance_id = websocket.messages[0]["utterance_id"]
        websocket.send_client_json({"type": "voice_played", "utterance_id": first_utterance_id})
        await wait_for_messages(websocket, 6)

        second_utterance_id = websocket.messages[3]["utterance_id"]
        websocket.send_client_json({"type": "voice_played", "utterance_id": second_utterance_id})
        registry.mark_completed(run.run_id, winner="好人阵营")
        await wait_for_messages(websocket, 9)
        websocket.send_client_json(
            {"type": "voice_played", "utterance_id": websocket.messages[6]["utterance_id"]}
        )
        await asyncio.wait_for(task, timeout=1)

    asyncio.run(stream_live_events())

    player_calls = [call for instance in RecordingTtsClient.instances for call in instance.calls]
    assert player_calls[:2] == [
        {"speaker": "player", "text_chunks": ["我是第一位发言。"]},
        {"speaker": "player", "text_chunks": ["我是第二位发言。"]},
    ]


def test_voice_stream_service_releases_playback_ack_wait_after_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(voice_stream_module, "PLAYBACK_ACK_TIMEOUT_SECONDS", 0.01)
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
        task = asyncio.create_task(
            service.stream_run(
                run.run_id,
                websocket,
                playback_ack_required=True,
            )
        )
        await wait_for_subscription(registry, run.run_id)
        registry.publish(
            run.run_id,
            "model_response_delta",
            actor="阿青",
            action="debate",
            payload={
                "request_id": "req-first",
                "visible_text": "我是第一位发言。",
                "is_public": True,
            },
        )
        registry.publish(
            run.run_id,
            "model_response_delta",
            actor="白石",
            action="debate",
            payload={
                "request_id": "req-second",
                "visible_text": "我是第二位发言。",
                "is_public": True,
            },
        )

        await wait_for_messages(websocket, 6)
        websocket.disconnect()
        await asyncio.wait_for(task, timeout=1)

    asyncio.run(stream_live_events())

    player_calls = [call for instance in RecordingTtsClient.instances for call in instance.calls]
    assert player_calls[:2] == [
        {"speaker": "player", "text_chunks": ["我是第一位发言。"]},
        {"speaker": "player", "text_chunks": ["我是第二位发言。"]},
    ]


def test_voice_stream_service_cleans_up_pending_synthesis_on_disconnect() -> None:
    PendingTtsClient.iterators.clear()
    registry = LiveRunRegistry()
    run = create_run(registry)
    websocket = FakeWebSocket()
    voice_store = RecordingVoiceStore()
    service = LiveVoiceStreamService(
        registry=registry,
        config=BASE_TTS_CONFIG,
        client_factory=PendingTtsClient,
        voice_store_factory=lambda session_id: voice_store,
    )

    async def stream_and_disconnect_during_synthesis() -> None:
        task = asyncio.create_task(service.stream_run(run.run_id, websocket))
        await wait_for_subscription(registry, run.run_id)
        registry.publish(
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
        for _ in range(120):
            if PendingTtsClient.iterators:
                break
            await asyncio.sleep(0.01)
        assert PendingTtsClient.iterators
        iterator = PendingTtsClient.iterators[0]
        await asyncio.wait_for(iterator.started.wait(), timeout=1)

        websocket.disconnect()
        await asyncio.wait_for(task, timeout=1)

        assert iterator.cancelled.is_set()
        assert iterator.closed.is_set()

    asyncio.run(stream_and_disconnect_during_synthesis())

    assert registry.get_run(run.run_id).subscribers == []
    assert [message["type"] for message in websocket.messages] == ["voice_start"]
    assert voice_store.failed == [
        {
            "utterance_id": websocket.messages[0]["utterance_id"],
            "message": "Voice stream disconnected",
        }
    ]


def test_voice_stream_service_marks_utterance_failed_when_voice_start_disconnects() -> None:
    RecordingTtsClient.instances.clear()
    registry = LiveRunRegistry()
    run = create_run(registry)
    websocket = DisconnectingOnVoiceStartWebSocket()
    voice_store = RecordingVoiceStore()
    service = LiveVoiceStreamService(
        registry=registry,
        config=BASE_TTS_CONFIG,
        client_factory=RecordingTtsClient,
        voice_store_factory=lambda session_id: voice_store,
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
                "request_id": "req-public",
                "visible_text": "我先发言。",
                "is_public": True,
            },
        )
        registry.mark_completed(run.run_id, winner="好人阵营")
        await asyncio.wait_for(task, timeout=1)

    asyncio.run(stream_events())

    utterance_id = voice_store.utterances[0]["utterance"].utterance_id
    assert websocket.messages == []
    assert voice_store.failed == [
        {
            "utterance_id": utterance_id,
            "message": "Voice stream disconnected",
        }
    ]
    assert voice_store.completed == []
    assert voice_store.chunks == []


def test_voice_stream_service_marks_utterance_failed_when_voice_end_disconnects() -> None:
    RecordingTtsClient.instances.clear()
    registry = LiveRunRegistry()
    run = create_run(registry)
    websocket = DisconnectingOnVoiceEndWebSocket()
    voice_store = RecordingVoiceStore()
    service = LiveVoiceStreamService(
        registry=registry,
        config=BASE_TTS_CONFIG,
        client_factory=RecordingTtsClient,
        voice_store_factory=lambda session_id: voice_store,
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
                "request_id": "req-public",
                "visible_text": "我先发言。",
                "is_public": True,
            },
        )
        registry.mark_completed(run.run_id, winner="好人阵营")
        await asyncio.wait_for(task, timeout=1)

    asyncio.run(stream_events())

    assert [message["type"] for message in websocket.messages] == [
        "voice_start",
        "audio_chunk",
    ]
    assert voice_store.failed == [
        {
            "utterance_id": websocket.messages[0]["utterance_id"],
            "message": "Voice stream disconnected",
        }
    ]
    assert voice_store.completed == []


def test_voice_stream_service_completes_when_disconnect_task_finishes_after_voice_end() -> None:
    RecordingTtsClient.instances.clear()
    registry = LiveRunRegistry()
    run = create_run(registry)
    websocket = MarkingDisconnectOnVoiceEndWebSocket()
    voice_store = RecordingVoiceStore()
    service = LiveVoiceStreamService(
        registry=registry,
        config=BASE_TTS_CONFIG,
        client_factory=RecordingTtsClient,
        voice_store_factory=lambda session_id: voice_store,
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
                "request_id": "req-public",
                "visible_text": "我先发言。",
                "is_public": True,
            },
        )
        registry.mark_completed(run.run_id, winner="好人阵营")
        await asyncio.wait_for(task, timeout=1)

    asyncio.run(stream_events())

    assert [message["type"] for message in websocket.messages[:3]] == [
        "voice_start",
        "audio_chunk",
        "voice_end",
    ]
    assert voice_store.failed == []
    assert voice_store.completed[0]["utterance_id"] == websocket.messages[0]["utterance_id"]
    assert voice_store.completed[0]["duration_ms"] == websocket.messages[2]["duration_ms"]


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
        await wait_for_subscription(registry, run.run_id)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(run_and_cancel())

    assert registry.get_run(run.run_id).subscribers == []
