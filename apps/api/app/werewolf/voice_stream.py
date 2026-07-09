from __future__ import annotations

import asyncio
import inspect
import json
import logging
import queue
import time
from collections import deque
from collections.abc import AsyncIterator, Callable
from contextlib import suppress
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Protocol

from fastapi import WebSocket, WebSocketDisconnect

from app.werewolf.judge_voice_assets import DEFAULT_JUDGE_VOICE_ASSET_DIR
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
TERMINAL_UNAVAILABLE_MESSAGE = "语音只支持进行中的实时对局；该对局已结束或异常中断。"


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

    def find_recent_utterance(
        self,
        *,
        run_id: str,
        current_event_id: int,
    ) -> dict[str, Any] | None:
        pass

    def load_chunks(self, utterance_id: str) -> list[bytes]:
        pass


@dataclass
class VoiceStreamContext:
    player_seats: dict[str, int]
    previous_night_deaths: tuple[str, ...] = ()
    peaceful_night: bool = False


@dataclass(frozen=True)
class StaticJudgeVoiceAsset:
    audio: bytes
    audio_format: str
    mime_type: str
    sample_rate: int


class LiveVoiceStreamService:
    def __init__(
        self,
        *,
        registry: LiveRunRegistry,
        config: VolcengineTtsConfig,
        client_factory: Callable[[VolcengineTtsConfig], TtsClient] = VolcengineTtsClient,
        voice_store_factory: Callable[[str], VoiceStore | None] | None = None,
        judge_voice_asset_dir: Path = DEFAULT_JUDGE_VOICE_ASSET_DIR,
    ) -> None:
        self.registry = registry
        self.config = config
        self.client_factory = client_factory
        self.voice_store_factory = voice_store_factory
        self.judge_voice_asset_dir = judge_voice_asset_dir

    @property
    def available(self) -> bool:
        return self.config.available

    async def stream_run(
        self,
        run_id: str,
        websocket: WebSocket,
        *,
        current_event_id: int | None = None,
    ) -> None:
        if not self.available:
            await websocket.send_json(self.config.unavailable_payload)
            return

        run = self.registry.try_get_run(run_id)
        if run is None:
            return
        if run.status in TERMINAL_RUN_STATUSES:
            await websocket.send_json(_voice_unavailable_payload("terminal"))
            return

        historical_events = self.registry.events_after(run_id)
        last_event_id = historical_events[-1].id if historical_events else None
        run = self.registry.try_get_run(run_id)
        if run is None:
            return
        if run.status in TERMINAL_RUN_STATUSES:
            await websocket.send_json(_voice_unavailable_payload("terminal"))
            return

        voice_store = self.voice_store_factory(run.session_id) if self.voice_store_factory else None
        disconnect_task = asyncio.create_task(_watch_websocket_disconnect(websocket))
        subscriber: queue.Queue[LiveEvent] | None = None
        pending_events: deque[LiveEvent] = deque()
        voice_context = _build_voice_context(historical_events)
        speaker_config = VoiceSpeakerConfig(
            player_speaker=self.config.player_speaker,
            judge_speaker=self.config.judge_speaker,
        )
        try:
            if not await _replay_recent_utterance(
                websocket,
                voice_store,
                run_id=run_id,
                current_event_id=current_event_id,
                disconnect_task=disconnect_task,
            ):
                return

            subscriber = self.registry.subscribe(run_id, after_id=last_event_id)
            while True:
                event = await _next_voice_event(
                    subscriber,
                    disconnect_task,
                    pending_events,
                )
                if event is None:
                    return
                is_terminal = event.type in TERMINAL_EVENT_TYPES
                _update_voice_context_before_event(voice_context, event)
                utterance = event_to_voice_utterance(
                    event,
                    speaker_config,
                    player_seats=voice_context.player_seats,
                    previous_night_deaths=voice_context.previous_night_deaths,
                    peaceful_night=voice_context.peaceful_night,
                )

                if utterance is not None:
                    utterance = await _coalesce_request_deltas(
                        utterance,
                        subscriber,
                        disconnect_task,
                        pending_events,
                        speaker_config,
                        voice_context.player_seats,
                    )
                    if disconnect_task.done():
                        return
                    chunks = chunk_text_for_tts(utterance.text)
                    static_asset = self._static_asset_for_utterance(utterance)
                    if static_asset is not None:
                        if not await self._stream_static_utterance(
                            websocket,
                            utterance,
                            static_asset,
                            disconnect_task,
                            voice_store,
                        ):
                            return
                    elif chunks and not await self._stream_utterance(
                        websocket,
                        utterance,
                        chunks,
                        disconnect_task,
                        voice_store,
                    ):
                        return

                _update_voice_context_after_event(voice_context, event)

                if is_terminal:
                    return
        except WebSocketDisconnect:
            return
        finally:
            disconnect_task.cancel()
            with suppress(asyncio.CancelledError):
                await disconnect_task
            if subscriber is not None:
                self.registry.unsubscribe(run_id, subscriber)

    def _static_asset_for_utterance(
        self,
        utterance: VoiceUtterance,
    ) -> StaticJudgeVoiceAsset | None:
        if utterance.speaker_kind != "judge" or utterance.static_asset_id is None:
            return None
        asset = _load_static_judge_voice_asset(
            self.judge_voice_asset_dir,
            utterance.static_asset_id,
        )
        if asset is None:
            return None
        if asset.audio_format.lower() != self.config.audio_format.lower():
            return None
        return asset

    async def _stream_static_utterance(
        self,
        websocket: WebSocket,
        utterance: VoiceUtterance,
        asset: StaticJudgeVoiceAsset,
        disconnect_task: asyncio.Task[None],
        voice_store: VoiceStore | None,
    ) -> bool:
        started_at = time.monotonic()
        _persist_voice_operation(
            voice_store,
            utterance,
            "upsert_utterance",
            lambda: voice_store.upsert_utterance(
                utterance,
                audio_format=asset.audio_format,
                sample_rate=asset.sample_rate,
                mime_type=asset.mime_type,
                status="synthesizing",
            ),
        )
        start_message, chunk_message, _end_message = build_voice_messages(
            utterance_id=utterance.utterance_id,
            source_event_id=utterance.source_event_id,
            speaker_kind=utterance.speaker_kind,
            speaker_name=utterance.speaker_name,
            audio=asset.audio,
            mime_type=asset.mime_type,
            duration_ms=0,
            audio_format=asset.audio_format,
            sample_rate=asset.sample_rate,
            chunk_index=0,
        )
        try:
            await websocket.send_json(start_message)
            if _mark_voice_stream_disconnected_if_needed(
                disconnect_task,
                voice_store,
                utterance,
            ):
                return False
            await websocket.send_json(chunk_message)
            _persist_voice_operation(
                voice_store,
                utterance,
                "append_chunk",
                lambda: voice_store.append_chunk(
                    utterance.utterance_id,
                    chunk_index=0,
                    audio=asset.audio,
                ),
            )
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


def _build_voice_context(events: list[LiveEvent]) -> VoiceStreamContext:
    context = VoiceStreamContext(player_seats={})
    for event in events:
        _update_voice_context_before_event(context, event)
        _update_voice_context_after_event(context, event)
    return context


def _update_voice_context_before_event(
    context: VoiceStreamContext,
    event: LiveEvent,
) -> None:
    payload = _payload_for_event(event)
    if event.type == "game_started":
        players = payload.get("players")
        if isinstance(players, list):
            context.player_seats = {
                player["name"]: index
                for index, player in enumerate(players, start=1)
                if isinstance(player, dict) and isinstance(player.get("name"), str)
            }
    if event.type == "state_updated":
        night_deaths = _night_death_names_from_payload(payload)
        if night_deaths:
            context.previous_night_deaths = tuple(night_deaths)
            context.peaceful_night = False
        elif _is_peaceful_night_payload(payload):
            context.previous_night_deaths = ()
            context.peaceful_night = True


def _update_voice_context_after_event(
    context: VoiceStreamContext,
    event: LiveEvent,
) -> None:
    if event.type == "phase_started" and event.phase == "day":
        context.previous_night_deaths = ()
        context.peaceful_night = False


def _night_death_names_from_payload(payload: dict[str, Any]) -> list[str]:
    deaths = payload.get("night_deaths")
    if isinstance(deaths, list):
        return [
            death["player"]
            for death in deaths
            if isinstance(death, dict) and isinstance(death.get("player"), str)
        ]
    eliminated = payload.get("eliminated")
    return [eliminated] if isinstance(eliminated, str) and eliminated else []


def _is_peaceful_night_payload(payload: dict[str, Any]) -> bool:
    attacked = payload.get("attacked")
    protected_player = payload.get("protected")
    eliminated = payload.get("eliminated")
    return bool(
        (isinstance(attacked, str) and protected_player == attacked)
        or (isinstance(eliminated, str) and protected_player == eliminated)
        or (isinstance(protected_player, str) and eliminated is None)
    )


def _payload_for_event(event: LiveEvent) -> dict[str, Any]:
    return event.payload if isinstance(event.payload, dict) else {}


def _load_static_judge_voice_asset(
    asset_dir: Path,
    asset_id: str,
) -> StaticJudgeVoiceAsset | None:
    manifest_path = asset_dir / "manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception:
        return None
    lines = manifest.get("lines")
    if not isinstance(lines, list):
        return None

    matching_line = next(
        (
            line
            for line in lines
            if isinstance(line, dict) and line.get("id") == asset_id
        ),
        None,
    )
    if matching_line is None or matching_line.get("exists") is False:
        return None

    filename = matching_line.get("filename")
    if not isinstance(filename, str) or Path(filename).name != filename:
        return None
    audio_path = asset_dir / filename
    if not audio_path.exists():
        return None

    audio_format = _string_manifest_value(
        matching_line,
        "audio_format",
    ) or _string_manifest_value(manifest, "audio_format") or audio_path.suffix.lstrip(".")
    if not audio_format:
        return None
    mime_type = (
        _string_manifest_value(matching_line, "mime_type")
        or _string_manifest_value(manifest, "mime_type")
        or mime_type_for_format(audio_format)
    )
    sample_rate = _int_manifest_value(
        matching_line,
        "sample_rate",
    ) or _int_manifest_value(manifest, "sample_rate") or 24000

    try:
        audio = audio_path.read_bytes()
    except Exception:
        return None
    if not audio:
        return None

    return StaticJudgeVoiceAsset(
        audio=audio,
        audio_format=audio_format,
        mime_type=mime_type,
        sample_rate=sample_rate,
    )


def _string_manifest_value(data: dict[str, Any], key: str) -> str:
    value = data.get(key)
    return value if isinstance(value, str) else ""


def _int_manifest_value(data: dict[str, Any], key: str) -> int | None:
    value = data.get(key)
    return value if isinstance(value, int) else None


async def _replay_recent_utterance(
    websocket: WebSocket,
    voice_store: VoiceStore | None,
    *,
    run_id: str,
    current_event_id: int | None,
    disconnect_task: asyncio.Task[None],
) -> bool:
    if voice_store is None or current_event_id is None:
        return True

    try:
        utterance = voice_store.find_recent_utterance(
            run_id=run_id,
            current_event_id=current_event_id,
        )
    except Exception:
        logger.warning(
            "Voice replay lookup failed",
            exc_info=True,
            extra={"run_id": run_id, "current_event_id": current_event_id},
        )
        return True
    if utterance is None or utterance.get("status") != "complete":
        return True

    utterance_id = utterance.get("utterance_id")
    if not isinstance(utterance_id, str):
        return True
    try:
        chunks = voice_store.load_chunks(utterance_id)
    except Exception:
        logger.warning(
            "Voice replay chunk load failed",
            exc_info=True,
            extra={"run_id": run_id, "utterance_id": utterance_id},
        )
        return True
    if not chunks:
        return True

    duration_ms = utterance.get("duration_ms")
    if not isinstance(duration_ms, int):
        duration_ms = 0
    source_event_id = utterance.get("source_event_id")
    sample_rate = utterance.get("sample_rate")
    speaker_kind = utterance.get("speaker_kind")
    speaker_name = utterance.get("speaker_name")
    mime_type = utterance.get("mime_type")
    audio_format = utterance.get("audio_format")
    if (
        not isinstance(source_event_id, int)
        or speaker_kind not in {"player", "judge"}
        or not isinstance(speaker_name, str)
        or not isinstance(mime_type, str)
        or not isinstance(audio_format, str)
        or not isinstance(sample_rate, int)
    ):
        return True

    start_message, _chunk_message, _end_message = build_voice_messages(
        utterance_id=utterance_id,
        source_event_id=source_event_id,
        speaker_kind=speaker_kind,
        speaker_name=speaker_name,
        audio=chunks[0],
        mime_type=mime_type,
        duration_ms=duration_ms,
        audio_format=audio_format,
        sample_rate=sample_rate,
        chunk_index=0,
    )
    if not await _send_replay_message(websocket, start_message, disconnect_task):
        return False

    for chunk_index, audio in enumerate(chunks):
        _start_message, chunk_message, _end_message = build_voice_messages(
            utterance_id=utterance_id,
            source_event_id=source_event_id,
            speaker_kind=speaker_kind,
            speaker_name=speaker_name,
            audio=audio,
            mime_type=mime_type,
            duration_ms=duration_ms,
            audio_format=audio_format,
            sample_rate=sample_rate,
            chunk_index=chunk_index,
        )
        if not await _send_replay_message(websocket, chunk_message, disconnect_task):
            return False

    end_message = {
        "type": "voice_end",
        "utterance_id": utterance_id,
        "duration_ms": duration_ms,
    }
    return await _send_replay_message(websocket, end_message, disconnect_task)


async def _send_replay_message(
    websocket: WebSocket,
    message: dict[str, Any],
    disconnect_task: asyncio.Task[None],
) -> bool:
    if disconnect_task.done():
        return False
    try:
        await websocket.send_json(message)
    except WebSocketDisconnect:
        return False
    await asyncio.sleep(0)
    return not disconnect_task.done()


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
    player_seats: dict[str, int],
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

        next_utterance = event_to_voice_utterance(
            event,
            speaker_config,
            player_seats=player_seats,
        )
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


def _voice_unavailable_payload(reason: str) -> dict[str, str]:
    if reason == "terminal":
        return {
            "type": "voice_unavailable",
            "reason": "terminal",
            "message": TERMINAL_UNAVAILABLE_MESSAGE,
        }
    return {
        "type": "voice_unavailable",
        "reason": reason,
        "message": "语音服务暂不可用，请稍后重试。",
    }
