from __future__ import annotations

import asyncio
import inspect
import logging
import queue
import time
from collections import deque
from collections.abc import AsyncIterator, Callable
from contextlib import suppress
from dataclasses import replace
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
REQUEST_DELTA_COALESCE_SECONDS = 0.16


class TtsClient(Protocol):
    async def synthesize(
        self,
        *,
        speaker: str,
        text_chunks: list[str],
    ) -> AsyncIterator[bytes]:
        pass


class VoiceStore(Protocol):
    def upsert_utterance(
        self,
        utterance: VoiceUtterance,
        *,
        audio_format: str,
        sample_rate: int,
        mime_type: str,
        status: str = "synthesizing",
    ) -> None:
        pass

    def append_chunk(self, utterance_id: str, *, chunk_index: int, audio: bytes) -> None:
        pass

    def complete_utterance(self, utterance_id: str, *, duration_ms: int) -> None:
        pass

    def fail_utterance(self, utterance_id: str, *, message: str) -> None:
        pass


class LiveVoiceStreamService:
    def __init__(
        self,
        *,
        registry: LiveRunRegistry,
        config: VolcengineTtsConfig,
        client_factory: Callable[[VolcengineTtsConfig], TtsClient] = VolcengineTtsClient,
        voice_store_factory: Callable[[str], VoiceStore | None] | None = None,
    ) -> None:
        self.registry = registry
        self.config = config
        self.client_factory = client_factory
        self.voice_store_factory = voice_store_factory

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

        voice_store = self.voice_store_factory(run.session_id) if self.voice_store_factory else None
        subscriber = self.registry.subscribe(run_id, after_id=last_event_id)
        disconnect_task = asyncio.create_task(_watch_websocket_disconnect(websocket))
        pending_events: deque[LiveEvent] = deque()
        speaker_config = VoiceSpeakerConfig(
            player_speaker=self.config.player_speaker,
            judge_speaker=self.config.judge_speaker,
        )
        try:
            while True:
                event = await _next_voice_event(
                    subscriber,
                    disconnect_task,
                    pending_events,
                )
                if event is None:
                    return
                is_terminal = event.type in TERMINAL_EVENT_TYPES
                utterance = event_to_voice_utterance(event, speaker_config)

                if utterance is not None:
                    utterance = await _coalesce_request_deltas(
                        utterance,
                        subscriber,
                        disconnect_task,
                        pending_events,
                        speaker_config,
                    )
                    if disconnect_task.done():
                        return
                    chunks = chunk_text_for_tts(utterance.text)
                    if chunks and not await self._stream_utterance(
                        websocket,
                        utterance,
                        chunks,
                        disconnect_task,
                        voice_store,
                    ):
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
        disconnect_task: asyncio.Task[None],
        voice_store: VoiceStore | None,
    ) -> bool:
        started_at = time.monotonic()
        audio_format = self.config.audio_format
        sample_rate = self.config.sample_rate
        mime_type = mime_type_for_format(audio_format)
        client = self.client_factory(self.config)
        _persist_voice_operation(
            voice_store,
            utterance,
            "upsert_utterance",
            lambda: voice_store.upsert_utterance(
                utterance,
                audio_format=audio_format,
                sample_rate=sample_rate,
                mime_type=mime_type,
                status="synthesizing",
            ),
        )
        try:
            await websocket.send_json(
                {
                    "type": "voice_start",
                    "utterance_id": utterance.utterance_id,
                    "source_event_id": utterance.source_event_id,
                    "speaker_kind": utterance.speaker_kind,
                    "speaker_name": utterance.speaker_name,
                    "mime_type": mime_type,
                    "audio_format": audio_format,
                    "sample_rate": sample_rate,
                }
            )
        except asyncio.CancelledError:
            _mark_voice_stream_interrupted(
                voice_store,
                utterance,
                "Voice stream canceled",
            )
            raise
        except WebSocketDisconnect:
            _mark_voice_stream_interrupted(
                voice_store,
                utterance,
                "Voice stream disconnected",
            )
            raise
        audio_iterator = client.synthesize(
            speaker=utterance.speaker,
            text_chunks=chunks,
        )
        audio_task: asyncio.Task[bytes] | None = None
        chunk_index = 0
        try:
            while True:
                audio_task = asyncio.create_task(anext(audio_iterator))
                done, _pending = await asyncio.wait(
                    {audio_task, disconnect_task},
                    return_when=asyncio.FIRST_COMPLETED,
                )
                if disconnect_task in done:
                    await _cancel_audio_task(audio_task)
                    await _close_async_iterator(audio_iterator)
                    _mark_voice_stream_interrupted(
                        voice_store,
                        utterance,
                        "Voice stream disconnected",
                    )
                    return False

                try:
                    audio = audio_task.result()
                except StopAsyncIteration:
                    break
                audio_task = None

                _start, chunk_message, _end = build_voice_messages(
                    utterance_id=utterance.utterance_id,
                    source_event_id=utterance.source_event_id,
                    speaker_kind=utterance.speaker_kind,
                    speaker_name=utterance.speaker_name,
                    audio=audio,
                    mime_type=mime_type,
                    duration_ms=0,
                    audio_format=audio_format,
                    sample_rate=sample_rate,
                    chunk_index=chunk_index,
                )
                await websocket.send_json(chunk_message)
                _persist_voice_operation(
                    voice_store,
                    utterance,
                    "append_chunk",
                    lambda: voice_store.append_chunk(
                        utterance.utterance_id,
                        chunk_index=chunk_index,
                        audio=audio,
                    ),
                )
                chunk_index += 1
        except asyncio.CancelledError:
            if audio_task is not None:
                await _cancel_audio_task(audio_task)
            await _close_async_iterator(audio_iterator)
            _mark_voice_stream_interrupted(
                voice_store,
                utterance,
                "Voice stream canceled",
            )
            raise
        except WebSocketDisconnect:
            await _close_async_iterator(audio_iterator)
            _mark_voice_stream_interrupted(
                voice_store,
                utterance,
                "Voice stream disconnected",
            )
            raise
        except Exception:
            await _close_async_iterator(audio_iterator)
            _persist_voice_operation(
                voice_store,
                utterance,
                "fail_utterance",
                lambda: voice_store.fail_utterance(
                    utterance.utterance_id,
                    message="Voice synthesis failed",
                ),
            )
            logger.warning(
                "Voice synthesis failed",
                extra={
                    "run_id": utterance.run_id,
                    "source_event_id": utterance.source_event_id,
                    "request_id": utterance.request_id,
                    "utterance_id": utterance.utterance_id,
                    "speaker_kind": utterance.speaker_kind,
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
            return True

        try:
            await _close_async_iterator(audio_iterator)
            if _mark_voice_stream_disconnected_if_needed(
                disconnect_task,
                voice_store,
                utterance,
            ):
                return False
            duration_ms = int((time.monotonic() - started_at) * 1000)
            await websocket.send_json(
                {
                    "type": "voice_end",
                    "utterance_id": utterance.utterance_id,
                    "duration_ms": duration_ms,
                }
            )
            _persist_voice_operation(
                voice_store,
                utterance,
                "complete_utterance",
                lambda: voice_store.complete_utterance(
                    utterance.utterance_id,
                    duration_ms=duration_ms,
                ),
            )
        except asyncio.CancelledError:
            _mark_voice_stream_interrupted(
                voice_store,
                utterance,
                "Voice stream canceled",
            )
            raise
        except WebSocketDisconnect:
            _mark_voice_stream_interrupted(
                voice_store,
                utterance,
                "Voice stream disconnected",
            )
            raise
        return True


async def _watch_websocket_disconnect(websocket: WebSocket) -> None:
    try:
        while True:
            message = await websocket.receive()
            if message.get("type") == "websocket.disconnect":
                return
    except WebSocketDisconnect:
        return


def _persist_voice_operation(
    voice_store: VoiceStore | None,
    utterance: VoiceUtterance,
    persistence_operation: str,
    persist: Callable[[], None],
) -> None:
    if voice_store is None:
        return
    try:
        persist()
    except Exception:
        logger.warning(
            "Voice persistence failed",
            exc_info=True,
            extra={
                "run_id": utterance.run_id,
                "source_event_id": utterance.source_event_id,
                "request_id": utterance.request_id,
                "utterance_id": utterance.utterance_id,
                "speaker_kind": utterance.speaker_kind,
                "persistence_operation": persistence_operation,
            },
        )


def _mark_voice_stream_interrupted(
    voice_store: VoiceStore | None,
    utterance: VoiceUtterance,
    message: str,
) -> None:
    _persist_voice_operation(
        voice_store,
        utterance,
        "fail_utterance",
        lambda: voice_store.fail_utterance(
            utterance.utterance_id,
            message=message,
        ),
    )


def _mark_voice_stream_disconnected_if_needed(
    disconnect_task: asyncio.Task[None],
    voice_store: VoiceStore | None,
    utterance: VoiceUtterance,
) -> bool:
    if not disconnect_task.done():
        return False
    _mark_voice_stream_interrupted(
        voice_store,
        utterance,
        "Voice stream disconnected",
    )
    return True


async def _close_async_iterator(iterator: AsyncIterator[bytes]) -> None:
    close = getattr(iterator, "aclose", None)
    if close is None:
        return
    with suppress(Exception):
        close_result = close()
        if inspect.isawaitable(close_result):
            await close_result


async def _cancel_audio_task(task: asyncio.Task[bytes]) -> None:
    task.cancel()
    with suppress(asyncio.CancelledError, Exception):
        await task


async def _next_subscriber_event(
    subscriber: queue.Queue[LiveEvent],
    disconnect_task: asyncio.Task[None],
) -> LiveEvent | None:
    return await _poll_subscriber_event(
        subscriber,
        disconnect_task,
        timeout_seconds=None,
    )


async def _poll_subscriber_event(
    subscriber: queue.Queue[LiveEvent],
    disconnect_task: asyncio.Task[None],
    *,
    timeout_seconds: float | None,
) -> LiveEvent | None:
    deadline = time.monotonic() + timeout_seconds if timeout_seconds is not None else None
    while True:
        if disconnect_task.done():
            return None
        try:
            return subscriber.get_nowait()
        except queue.Empty:
            poll_timeout = IDLE_POLL_SECONDS
            if deadline is not None:
                remaining_seconds = deadline - time.monotonic()
                if remaining_seconds <= 0:
                    return None
                poll_timeout = min(poll_timeout, remaining_seconds)
            done, _pending = await asyncio.wait(
                {disconnect_task},
                timeout=poll_timeout,
            )
            if done:
                return None


async def _next_voice_event(
    subscriber: queue.Queue[LiveEvent],
    disconnect_task: asyncio.Task[None],
    pending_events: deque[LiveEvent],
) -> LiveEvent | None:
    if pending_events:
        return pending_events.popleft()
    return await _next_subscriber_event(subscriber, disconnect_task)


async def _coalesce_request_deltas(
    utterance: VoiceUtterance,
    subscriber: queue.Queue[LiveEvent],
    disconnect_task: asyncio.Task[None],
    pending_events: deque[LiveEvent],
    speaker_config: VoiceSpeakerConfig,
) -> VoiceUtterance:
    if utterance.request_id is None or utterance.speaker_kind != "player":
        return utterance

    texts = [utterance.text]
    while True:
        if pending_events:
            event = pending_events.popleft()
        else:
            event = await _poll_subscriber_event(
                subscriber,
                disconnect_task,
                timeout_seconds=REQUEST_DELTA_COALESCE_SECONDS,
            )
            if event is None:
                break

        next_utterance = event_to_voice_utterance(event, speaker_config)
        if _is_same_request_utterance(utterance, next_utterance):
            texts.append(next_utterance.text)
            continue

        pending_events.appendleft(event)
        break

    if len(texts) == 1:
        return utterance
    return replace(utterance, text="".join(texts))


def _is_same_request_utterance(
    utterance: VoiceUtterance,
    next_utterance: VoiceUtterance | None,
) -> bool:
    return (
        next_utterance is not None
        and next_utterance.request_id == utterance.request_id
        and next_utterance.speaker_kind == utterance.speaker_kind
        and next_utterance.speaker_name == utterance.speaker_name
        and next_utterance.action == utterance.action
    )
