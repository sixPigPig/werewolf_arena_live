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
from app.api.public.dependencies import get_current_public_websocket_principal
from app.db.base import Base
from app.main import app
from app.models.live import VoiceMaterializationJobRecord
from app.werewolf import voice_stream as voice_stream_module
from app.werewolf.live import LiveRunRegistry
from app.werewolf.voice import VoiceUtterance
from app.werewolf.voice_stream import (
    LiveVoiceStreamService,
    StaticJudgeVoiceAsset,
    build_static_judge_playback_voices,
)
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


def test_playback_ack_tracker_keeps_out_of_order_ack_for_the_next_utterance() -> None:
    async def scenario() -> None:
        acknowledgements: asyncio.Queue[str] = asyncio.Queue()
        disconnect_task = asyncio.create_task(asyncio.Event().wait())
        acknowledgements.put_nowait("voice-next")
        acknowledgements.put_nowait("voice-current")
        try:
            assert await voice_stream_module._wait_for_playback_ack(
                "voice-current",
                acknowledgements,
                disconnect_task,
            )
            assert await voice_stream_module._wait_for_playback_ack(
                "voice-next",
                acknowledgements,
                disconnect_task,
            )
            assert acknowledgements.empty()
        finally:
            disconnect_task.cancel()

    asyncio.run(scenario())


def test_playback_ack_accepts_status_and_played_duration() -> None:
    acknowledgement = voice_stream_module._playback_ack(
        {
            "text": json.dumps(
                {
                    "type": "voice_played",
                    "utterance_id": "voice-1",
                    "status": "interrupted",
                    "played_ms": 730,
                }
            )
        }
    )

    assert acknowledgement == voice_stream_module.PlaybackAck(
        utterance_id="voice-1",
        client_status="interrupted",
        played_ms=730,
    )


def test_legacy_playback_ack_defaults_to_completed() -> None:
    acknowledgement = voice_stream_module._playback_ack(
        {
            "text": json.dumps(
                {"type": "voice_played", "utterance_id": "voice-legacy"}
            )
        }
    )

    assert acknowledgement == voice_stream_module.PlaybackAck(
        utterance_id="voice-legacy"
    )


def test_static_judge_playback_voice_uses_media_duration_not_send_time() -> None:
    voices = build_static_judge_playback_voices(
        [
            {
                "id": 7,
                "type": "game_completed",
                "run_id": "run-static-duration",
                "session_id": "game-static-duration",
                "created_at": "2026-07-17T00:00:00Z",
                "payload": {"winner": "好人阵营"},
            }
        ],
        asset_loader=lambda _asset_id: StaticJudgeVoiceAsset(
            audio=b"encoded-audio",
            audio_format="mp3",
            mime_type="audio/mpeg",
            sample_rate=24000,
            subtitle_timings=[
                {"text": "游戏结束，", "start_ms": 0, "end_ms": 400},
                {"text": "好人阵营获胜。", "start_ms": 400, "end_ms": 900},
            ],
            duration_ms=1100,
        ),
    )

    assert len(voices) == 1
    assert voices[0]["duration_ms"] == 1100
    assert max(cue["end_ms"] for cue in voices[0]["subtitle_timings"]) == 900


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
        audience: str = "player_public",
    ) -> None:
        self.calls.append(
            {
                "run_id": run_id,
                "current_event_id": current_event_id,
                "playback_ack_required": playback_ack_required,
                "audience": audience,
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


class ContextRecordingTtsClient:
    instances: list["ContextRecordingTtsClient"] = []

    def __init__(self, config: VolcengineTtsConfig) -> None:
        self.config = config
        self.calls: list[dict] = []
        ContextRecordingTtsClient.instances.append(self)

    async def synthesize(
        self,
        *,
        speaker: str,
        text_chunks: list[str],
        context_texts: list[str] | tuple[str, ...] | None = None,
    ) -> AsyncIterator[bytes]:
        self.calls.append(
            {
                "speaker": speaker,
                "text_chunks": text_chunks,
                "context_texts": list(context_texts) if context_texts else None,
            }
        )
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
        self.claimed: list[VoiceUtterance] = []
        self.released: list[dict] = []
        self.utterances: list[dict] = []
        self.chunks: list[dict] = []
        self.completed: list[dict] = []
        self.failed: list[dict] = []
        self.subtitle_timings: list[dict] = []
        self.recent_utterance: dict | None = None
        self.materialized_utterances: dict[str, dict] = {}
        self.replay_chunks: list[bytes] = []
        self.find_recent_calls: list[dict] = []

    def claim_streamed_utterance(self, utterance: VoiceUtterance) -> bool:
        self.claimed.append(utterance)
        return True

    def release_streamed_utterance(
        self,
        utterance: VoiceUtterance,
        *,
        error_type: str,
    ) -> None:
        self.released.append({"utterance": utterance, "error_type": error_type})

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
        audience: str = "player_public",
    ) -> dict | None:
        self.find_recent_calls.append(
            {
                "run_id": run_id,
                "current_event_id": current_event_id,
                "audience": audience,
            }
        )
        return self.recent_utterance

    def load_chunks(self, utterance_id: str) -> list[bytes]:
        return (
            self.replay_chunks
            if self.recent_utterance
            or utterance_id in self.materialized_utterances
            else []
        )

    def load_utterance(self, utterance_id: str) -> dict | None:
        return self.materialized_utterances.get(utterance_id)


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
    presentation_id: str | None = None,
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
        presentation_id=presentation_id,
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




def test_get_voice_streamer_persists_private_audio_and_subtitles_from_god_view(
    db_session: Session,
) -> None:
    SubtitleTtsClient.instances.clear()
    session_factory = sessionmaker(
        bind=db_session.get_bind(),
        autoflush=False,
        autocommit=False,
    )
    registry = LiveRunRegistry(live_store=SessionLiveStore(session_factory))
    run = create_run(registry)
    registry.publish(
        run.run_id,
        "game_started",
        payload={
            "players": [
                {"name": "阿青", "role": "werewolf", "model": "test-model"},
                {"name": "白石", "role": "villager", "model": "test-model"},
            ]
        },
    )
    websocket = FakeWebSocket()
    service = get_voice_streamer(registry, BASE_TTS_CONFIG)
    service.client_factory = SubtitleTtsClient
    service.voice_store_factory = lambda session_id: SessionVoiceStore(
        session_id=session_id,
        session_factory=session_factory,
    )

    async def stream_private_event() -> None:
        task = asyncio.create_task(
            service.stream_run(
                run.run_id,
                websocket,
                audience="spectator_god_view",
            )
        )
        await wait_for_subscription(registry, run.run_id)
        private_event = registry.publish(
            run.run_id,
            "action_parsed",
            actor="阿青",
            action="werewolf_discuss",
            phase="night",
            payload={
                "visible_result": {
                    "message": "我先发言。",
                    "decision_stage": "proposal",
                }
            },
        )
        await wait_for_messages(websocket, 4)
        private_judge_event = registry.publish(
            run.run_id,
            "judge_cue",
            phase="night",
            action="werewolf_tiebreak_result",
            payload={
                "cue_id": "werewolf_tiebreak_result",
                "visible_text": "我先发言。",
                "static_asset_id": None,
            },
        )
        await wait_for_messages(websocket, 8)
        websocket.disconnect()
        await asyncio.wait_for(task, timeout=1)
        with session_factory() as db:
            for event_id, speaker_kind in (
                (private_event.id, "player"),
                (private_judge_event.id, "judge"),
            ):
                job = db.get(
                    VoiceMaterializationJobRecord,
                    (run.run_id, event_id, speaker_kind),
                )
                assert job is not None and job.status == "complete"

    asyncio.run(stream_private_event())

    with session_factory() as db:
        voices = DatabaseVoiceStore(db, session_id=run.session_id).list_playback_voices(
            allowed_audiences=frozenset({"spectator_god_view"})
        )
    assert len(voices) == 2
    assert {voice["speaker_kind"] for voice in voices} == {"player", "judge"}
    assert all(voice["audience"] == "spectator_god_view" for voice in voices)
    assert all(
        voice["subtitle_timings"]
        == [
            {"text": "我", "start_ms": 0, "end_ms": 180},
            {"text": "先发言。", "start_ms": 180, "end_ms": 820},
        ]
        for voice in voices
    )
    assert all([chunk["data"] for chunk in voice["chunks"]] == ["YWJj"] for voice in voices)


def test_live_stream_claim_is_single_writer_and_released_after_failure(
    db_session: Session,
) -> None:
    session_factory = sessionmaker(
        bind=db_session.get_bind(),
        autoflush=False,
        autocommit=False,
    )
    registry = LiveRunRegistry(live_store=SessionLiveStore(session_factory))
    run = create_run(registry)
    private_event = registry.publish(
        run.run_id,
        "action_parsed",
        actor="阿青",
        action="werewolf_discuss",
        phase="night",
        payload={"visible_result": {"message": "今晚先刀白石。"}},
    )
    utterance = VoiceUtterance(
        utterance_id="voice-live-private",
        run_id=run.run_id,
        source_event_id=private_event.id,
        request_id=None,
        speaker_kind="player",
        speaker_name="1号玩家",
        speaker="player",
        text="今晚先刀白石。",
        action="werewolf_discuss",
        audience="spectator_god_view",
    )
    first = SessionVoiceStore(session_id=run.session_id, session_factory=session_factory)
    second = SessionVoiceStore(session_id=run.session_id, session_factory=session_factory)

    assert first.claim_streamed_utterance(utterance) is True
    assert second.claim_streamed_utterance(replace(utterance, utterance_id="voice-second")) is False

    first.release_streamed_utterance(utterance, error_type="test_failure")

    replacement = replace(utterance, utterance_id="voice-replacement")
    assert second.claim_streamed_utterance(replacement) is True


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
            "audience": "player_public",
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
            "audience": "player_public",
        }
    ]


def test_god_view_voice_stream_route_uses_private_projection() -> None:
    registry = LiveRunRegistry()
    run = create_run(registry)
    streamer = FakeVoiceStreamer()
    override_registry(registry)
    override_streamer(streamer)
    app.dependency_overrides[get_current_public_websocket_principal] = lambda: object()

    with client_with_overrides() as client:
        with client.websocket_connect(
            f"/api/v1/games/runs/{run.run_id}/god-view/voice-stream?current_event_id=7"
        ) as ws:
            assert ws.receive_json()["type"] == "voice_start"

    assert streamer.calls == [
        {
            "run_id": run.run_id,
            "current_event_id": 7,
            "playback_ack_required": False,
            "audience": "spectator_god_view",
        }
    ]


def test_god_view_voice_stream_route_requires_public_session() -> None:
    registry = LiveRunRegistry()
    run = create_run(registry)
    override_registry(registry)
    override_streamer(FakeVoiceStreamer())

    with client_with_overrides() as client:
        with pytest.raises(WebSocketDisconnect) as exc_info:
            with client.websocket_connect(
                f"/api/v1/games/runs/{run.run_id}/god-view/voice-stream"
            ):
                pass

    assert exc_info.value.code == 1008


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




def test_voice_stream_service_streams_and_persists_private_wolf_chat_to_god_view(
    tmp_path,
) -> None:
    SubtitleTtsClient.instances.clear()
    registry = LiveRunRegistry()
    run = create_run(registry)
    registry.publish(
        run.run_id,
        "game_started",
        payload={
            "players": [
                {"name": "张三", "role": "werewolf", "model": "test-model"},
                {"name": "李四", "role": "villager", "model": "test-model"},
            ]
        },
    )
    websocket = FakeWebSocket()
    voice_store = RecordingVoiceStore()
    service = LiveVoiceStreamService(
        registry=registry,
        config=BASE_TTS_CONFIG,
        client_factory=SubtitleTtsClient,
        voice_store_factory=lambda session_id: voice_store,
        judge_voice_asset_dir=tmp_path / "judge-voice",
    )

    async def stream_private_event() -> None:
        task = asyncio.create_task(
            service.stream_run(
                run.run_id,
                websocket,
                audience="spectator_god_view",
            )
        )
        await wait_for_subscription(registry, run.run_id)
        private_event = registry.publish(
            run.run_id,
            "action_parsed",
            actor="张三",
            action="werewolf_discuss",
            payload={
                "choice": "李四",
                "result": {"target": "李四", "message": "李四带队能力强，建议先处理。"},
                "visible_result": {
                    "target": "李四",
                    "message": "李四带队能力强，建议先处理。",
                },
                "message": "李四带队能力强，建议先处理。",
                "decision_stage": "proposal",
            },
        )
        await wait_for_messages(websocket, 4)
        websocket.disconnect()
        await asyncio.wait_for(task, timeout=1)
        assert websocket.messages[0]["source_event_id"] == private_event.id

    asyncio.run(stream_private_event())

    assert SubtitleTtsClient.instances[0].calls == [
        {"speaker": "player", "text_chunks": ["李四带队能力强，", "建议先处理。"]}
    ]
    assert [message["type"] for message in websocket.messages] == [
        "voice_start",
        "subtitle_timing",
        "audio_chunk",
        "voice_end",
    ]
    start, subtitle, chunk, end = websocket.messages
    assert start["speaker_name"] == "1号玩家"
    assert start["audience"] == "spectator_god_view"
    assert voice_store.utterances[0]["utterance"].audience == "spectator_god_view"
    assert voice_store.utterances[0]["utterance"].text == "李四带队能力强，建议先处理。"
    assert voice_store.subtitle_timings == [
        {
            "utterance_id": start["utterance_id"],
            "subtitle_timings": subtitle["cues"],
        }
    ]
    assert voice_store.chunks == [
        {
            "utterance_id": start["utterance_id"],
            "chunk_index": chunk["chunk_index"],
            "audio": b"abc",
        }
    ]
    assert voice_store.completed == [
        {
            "utterance_id": start["utterance_id"],
            "duration_ms": end["duration_ms"],
        }
    ]


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
              "duration_ms": 1250,
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
    voice_store = RecordingVoiceStore()
    service = LiveVoiceStreamService(
        registry=registry,
        config=replace(BASE_TTS_CONFIG, audio_format="mp3"),
        client_factory=RecordingTtsClient,
        voice_store_factory=lambda _session_id: voice_store,
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
    start, subtitle, chunk, end = websocket.messages[:4]
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
    assert end["duration_ms"] == 1250
    end_start, end_subtitle, end_chunk, end_end = websocket.messages[4:8]
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
    assert end_end["duration_ms"] == 1000
    assert [item["duration_ms"] for item in voice_store.completed] == [1250, 1000]


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


def test_voice_stream_service_does_not_speak_delta_or_rejected_draft() -> None:
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
                "request_id": "req-rejected",
                "visible_text": "这是尚未通过校验的初稿。",
                "is_public": True,
            },
        )
        registry.publish(
            run.run_id,
            "action_quality_warning",
            actor="阿青",
            action="debate",
            payload={
                "request_id": "req-rejected",
                "visible_result": {"say": "这是被拒绝的完整初稿。"},
                "warning_codes": ["speech_quality_rejected"],
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


def test_voice_broker_fans_out_and_seals_committed_speech_without_second_tts_call() -> None:
    RecordingTtsClient.instances.clear()
    registry = LiveRunRegistry()
    run = create_run(registry)
    websocket = FakeWebSocket()
    store = RecordingVoiceStore()
    service = LiveVoiceStreamService(
        registry=registry,
        config=BASE_TTS_CONFIG,
        client_factory=RecordingTtsClient,
        voice_store_factory=lambda _session_id: store,
        materialized_voice_wait_seconds=0.5,
    )

    async def stream_events() -> None:
        task = asyncio.create_task(service.stream_run(run.run_id, websocket))
        await wait_for_subscription(registry, run.run_id)
        event = registry.publish(
            run.run_id,
            "model_response_delta",
            actor="阿青",
            action="debate",
            payload={
                "schema_version": 2,
                "commit_state": "accepted_segment",
                "generation_stage": "renderer",
                "action_id": "act-committed",
                "request_id": "req-committed",
                "speech_id": "sp-committed",
                "speech_stream_mode": "segments_v2",
                "segment_id": "seg-committed-0",
                "segment_index": 0,
                "segment_final": False,
                "visible_text": "我先把这一票讲清楚。",
                "delta": "我先把这一票讲清楚。",
                "is_public": True,
                "presentation_id": "pres-committed-0",
                "experience_revision": "liveness-v1",
                "voice_snapshot": {
                    "enabled": True,
                    "speaker": "player",
                    "effective_context_texts": [],
                },
            },
        )
        utterance_id = voice_stream_module.deterministic_voice_utterance_id(
            run.run_id,
            event.id,
            "player",
        )
        store.materialized_utterances[utterance_id] = {
            "utterance_id": utterance_id,
            "run_id": run.run_id,
            "source_event_id": event.id,
            "last_source_event_id": event.id,
            "speaker_kind": "player",
            "speaker_name": "当前玩家",
            "mime_type": "audio/pcm",
            "audio_format": "pcm",
            "sample_rate": 24000,
            "audience": "player_public",
            "duration_ms": 320,
            "status": "complete",
            "speech_id": "sp-committed",
            "segment_id": "seg-committed-0",
            "segment_index": 0,
            "segment_final": False,
            "presentation_id": "pres-committed-0",
            "subtitle_timings": [],
        }
        store.replay_chunks = [b"durable-audio"]
        for _ in range(50):
            if any(message.get("type") == "voice_end" for message in websocket.messages):
                break
            await asyncio.sleep(0.01)
        registry.publish(
            run.run_id,
            "action_parsed",
            actor="阿青",
            action="debate",
            payload={
                "speech_id": "sp-committed",
                "speech_stream_mode": "segments_v2",
                "segment_count": 1,
                "final_segment_index": 0,
                "speech_status": "spoken",
            },
        )
        for _ in range(50):
            if any(message.get("type") == "speech_sealed" for message in websocket.messages):
                break
            await asyncio.sleep(0.01)
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
    assert [message["type"] for message in websocket.messages[:5]] == [
        "speech_opened",
        "voice_start",
        "audio_chunk",
        "voice_end",
        "speech_sealed",
    ]
    assert websocket.messages[0]["speech_id"] == "sp-committed"
    assert websocket.messages[1]["speech_id"] == "sp-committed"
    assert websocket.messages[2]["data"]
    assert websocket.messages[4] == {
        "type": "speech_sealed",
        "speech_id": "sp-committed",
        "final_segment_index": 0,
        "segment_count": 1,
        "speech_status": "spoken",
        "last_source_event_id": websocket.messages[1]["source_event_id"] + 1,
    }


def test_voice_broker_releases_speech_lock_when_materialization_is_unavailable() -> None:
    registry = LiveRunRegistry()
    run = create_run(registry)
    websocket = FakeWebSocket()
    service = LiveVoiceStreamService(
        registry=registry,
        config=BASE_TTS_CONFIG,
        client_factory=RecordingTtsClient,
        voice_store_factory=lambda _session_id: RecordingVoiceStore(),
        materialized_voice_wait_seconds=0.1,
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
                "schema_version": 2,
                "commit_state": "accepted_segment",
                "generation_stage": "renderer",
                "action_id": "act-unavailable",
                "request_id": "req-unavailable",
                "speech_id": "sp-unavailable",
                "speech_stream_mode": "segments_v2",
                "segment_id": "seg-unavailable-0",
                "segment_index": 0,
                "segment_final": False,
                "visible_text": "这句暂时没有音频。",
                "delta": "这句暂时没有音频。",
                "is_public": True,
            },
        )
        await wait_for_messages(websocket, 3)
        registry.mark_completed(run.run_id, winner="好人阵营")
        await asyncio.wait_for(task, timeout=1)

    asyncio.run(stream_events())

    assert [message["type"] for message in websocket.messages[:3]] == [
        "speech_opened",
        "voice_error",
        "speech_preempted",
    ]
    assert websocket.messages[2] == {
        "type": "speech_preempted",
        "speech_id": "sp-unavailable",
        "reason": "voice_materialization_unavailable",
    }


def test_voice_broker_preempts_current_speech_and_discards_queued_segments() -> None:
    registry = LiveRunRegistry()
    run = create_run(registry)
    websocket = FakeWebSocket()
    store = RecordingVoiceStore()
    service = LiveVoiceStreamService(
        registry=registry,
        config=BASE_TTS_CONFIG,
        client_factory=RecordingTtsClient,
        voice_store_factory=lambda _session_id: store,
        materialized_voice_wait_seconds=0.5,
    )

    def materialized(event_id: int, segment_index: int) -> tuple[str, dict]:
        utterance_id = voice_stream_module.deterministic_voice_utterance_id(
            run.run_id,
            event_id,
            "player",
        )
        return utterance_id, {
            "utterance_id": utterance_id,
            "run_id": run.run_id,
            "source_event_id": event_id,
            "last_source_event_id": event_id,
            "speaker_kind": "player",
            "speaker_name": "当前玩家",
            "mime_type": "audio/pcm",
            "audio_format": "pcm",
            "sample_rate": 24000,
            "audience": "player_public",
            "duration_ms": 320,
            "status": "complete",
            "speech_id": "sp-preempt",
            "segment_id": f"seg-preempt-{segment_index}",
            "segment_index": segment_index,
            "segment_final": False,
            "subtitle_timings": [],
        }

    def publish_segment(index: int):
        return registry.publish(
            run.run_id,
            "model_response_delta",
            actor="阿青",
            action="debate",
            payload={
                "schema_version": 2,
                "commit_state": "accepted_segment",
                "generation_stage": "renderer",
                "action_id": "act-preempt",
                "request_id": "req-preempt",
                "speech_id": "sp-preempt",
                "speech_stream_mode": "segments_v2",
                "segment_id": f"seg-preempt-{index}",
                "segment_index": index,
                "segment_final": False,
                "visible_text": f"第{index + 1}句。",
                "delta": f"第{index + 1}句。",
                "is_public": True,
                "experience_revision": "liveness-v1",
            },
        )

    async def stream_events() -> None:
        task = asyncio.create_task(service.stream_run(run.run_id, websocket))
        await wait_for_subscription(registry, run.run_id)
        first = publish_segment(0)
        first_id, first_record = materialized(first.id, 0)
        store.materialized_utterances[first_id] = first_record
        store.replay_chunks = [b"first"]
        for _ in range(50):
            if any(message.get("type") == "voice_end" for message in websocket.messages):
                break
            await asyncio.sleep(0.01)

        second = publish_segment(1)
        await asyncio.sleep(0)
        registry.publish(
            run.run_id,
            "speech_playback_preempted",
            actor="阿青",
            action="debate",
            payload={
                "schema_version": 1,
                "action_id": "act-preempt",
                "speech_id": "sp-preempt",
                "reason": "self_explosion",
                "trigger_source": {
                    "source_run_id": run.run_id,
                    "source_event_id": second.id + 1,
                },
                "cut_after_segment_index": 0,
                "audience": "player_public",
            },
        )
        second_id, second_record = materialized(second.id, 1)
        store.materialized_utterances[second_id] = second_record
        for _ in range(50):
            if any(message.get("type") == "voice_preempt" for message in websocket.messages):
                break
            await asyncio.sleep(0.01)
        registry.mark_completed(run.run_id, winner="好人阵营")
        await asyncio.wait_for(task, timeout=1)

    asyncio.run(stream_events())

    starts = [
        message
        for message in websocket.messages
        if message.get("type") == "voice_start"
        and message.get("speech_id") == "sp-preempt"
    ]
    assert [message.get("segment_index") for message in starts] == [0]
    preempt = next(
        message
        for message in websocket.messages
        if message.get("type") == "voice_preempt"
    )
    assert preempt["speech_id"] == "sp-preempt"
    assert preempt["reason"] == "self_explosion"
    assert preempt["trigger_source"]["source_run_id"] == run.run_id
    assert preempt["cut_after_segment_index"] == 0
    assert preempt["fade_out_ms"] == 120




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
        presentation_id="hp_0123456789abcdef01234567",
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
            "presentation_id": "hp_0123456789abcdef01234567",
            "speaker_kind": "player",
            "speaker_name": "阿青",
            "audience": "player_public",
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














def test_voice_stream_service_ignores_unsegmented_public_action() -> None:
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
    assert player_calls == []


















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
