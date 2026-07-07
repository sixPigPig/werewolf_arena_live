from __future__ import annotations

import asyncio
import logging
import queue
import time
from collections.abc import AsyncIterator, Callable
from contextlib import suppress
from typing import Protocol

from fastapi import WebSocket, WebSocketDisconnect

from app.werewolf.live import LiveEvent, LiveRunRegistry
from app.werewolf.voice import (
    VoiceSpeakerConfig,
    VoiceUtterance,
    build_voice_messages,
    chunk_text_for_tts,
    event_to_voice_utterance,
)
from app.werewolf.volcengine_tts import (
    VolcengineTtsClient,
    VolcengineTtsConfig,
    mime_type_for_format,
)

logger = logging.getLogger(__name__)

TERMINAL_EVENT_TYPES = {"game_completed", "game_failed"}
TERMINAL_RUN_STATUSES = {"completed", "failed"}
IDLE_POLL_SECONDS = 0.1


class TtsClient(Protocol):
    async def synthesize(
        self,
        *,
        speaker: str,
        text_chunks: list[str],
    ) -> AsyncIterator[bytes]:
        pass


class LiveVoiceStreamService:
    def __init__(
        self,
        *,
        registry: LiveRunRegistry,
        config: VolcengineTtsConfig,
        client_factory: Callable[[VolcengineTtsConfig], TtsClient] = VolcengineTtsClient,
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

        run = self.registry.try_get_run(run_id)
        if run is None or run.status in TERMINAL_RUN_STATUSES:
            return

        historical_events = self.registry.events_after(run_id)
        last_event_id = historical_events[-1].id if historical_events else None
        run = self.registry.try_get_run(run_id)
        if run is None or run.status in TERMINAL_RUN_STATUSES:
            return

        subscriber = self.registry.subscribe(run_id, after_id=last_event_id)
        disconnect_task = asyncio.create_task(_watch_websocket_disconnect(websocket))
        speaker_config = VoiceSpeakerConfig(
            player_speaker=self.config.player_speaker,
            judge_speaker=self.config.judge_speaker,
        )
        try:
            while True:
                event = await _next_subscriber_event(subscriber, disconnect_task)
                if event is None:
                    return
                is_terminal = event.type in TERMINAL_EVENT_TYPES
                utterance = event_to_voice_utterance(event, speaker_config)

                if utterance is not None:
                    chunks = chunk_text_for_tts(utterance.text)
                    if chunks and not await self._stream_utterance(websocket, utterance, chunks):
                        return

                if is_terminal:
                    return
        except WebSocketDisconnect:
            return
        finally:
            disconnect_task.cancel()
            with suppress(asyncio.CancelledError):
                await disconnect_task
            self.registry.unsubscribe(run_id, subscriber)

    async def _stream_utterance(
        self,
        websocket: WebSocket,
        utterance: VoiceUtterance,
        chunks: list[str],
    ) -> bool:
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
            async for audio in client.synthesize(
                speaker=utterance.speaker,
                text_chunks=chunks,
            ):
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
        except WebSocketDisconnect:
            raise
        except Exception:
            logger.warning(
                "Voice synthesis failed",
                extra={
                    "run_id": utterance.run_id,
                    "source_event_id": utterance.source_event_id,
                },
            )
            await websocket.send_json(
                {
                    "type": "voice_error",
                    "utterance_id": utterance.utterance_id,
                    "source_event_id": utterance.source_event_id,
                    "message": "Voice synthesis failed",
                }
            )
            return False

        await websocket.send_json(
            {
                "type": "voice_end",
                "utterance_id": utterance.utterance_id,
                "duration_ms": int((time.monotonic() - started_at) * 1000),
            }
        )
        return True


async def _watch_websocket_disconnect(websocket: WebSocket) -> None:
    try:
        while True:
            message = await websocket.receive()
            if message.get("type") == "websocket.disconnect":
                return
    except WebSocketDisconnect:
        return


async def _next_subscriber_event(
    subscriber: queue.Queue[LiveEvent],
    disconnect_task: asyncio.Task[None],
) -> LiveEvent | None:
    while True:
        if disconnect_task.done():
            return None
        try:
            return subscriber.get_nowait()
        except queue.Empty:
            done, _pending = await asyncio.wait({disconnect_task}, timeout=IDLE_POLL_SECONDS)
            if done:
                return None
