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
from app.werewolf.privacy_projection import ProjectionAudience, project_live_event
from app.werewolf.voice import (
    VoiceSpeakerConfig,
    VoiceUtterance,
    build_voice_messages,
    chunk_text_for_tts,
    event_to_voice_utterance,
    is_public_complete_speech_event,
    is_public_speech_event,
    voice_job_candidate,
)
from app.werewolf.volcengine_tts import (
    TtsSubtitleTiming,
    TtsSynthesisItem,
    VolcengineTtsClient,
    VolcengineTtsConfig,
    mime_type_for_format,
)

logger = logging.getLogger(__name__)

TERMINAL_EVENT_TYPES = {"game_completed", "game_failed", "game_canceled"}
TERMINAL_RUN_STATUSES = {"completed", "failed", "canceled"}
IDLE_POLL_SECONDS = 0.1
REQUEST_DELTA_COALESCE_SECONDS = 0.5
PLAYBACK_ACK_TIMEOUT_SECONDS = 60.0
TERMINAL_UNAVAILABLE_MESSAGE = "语音只支持进行中的实时对局；该对局已结束或异常中断。"


class TtsClient(Protocol):
    async def synthesize(
        self,
        *,
        speaker: str,
        text_chunks: list[str],
    ) -> AsyncIterator[TtsSynthesisItem]:
        pass


class VoiceStore(Protocol):
    def claim_streamed_utterance(self, utterance: VoiceUtterance) -> bool:
        pass

    def release_streamed_utterance(
        self,
        utterance: VoiceUtterance,
        *,
        error_type: str,
    ) -> None:
        pass

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

    def update_subtitle_timings(
        self,
        utterance_id: str,
        *,
        subtitle_timings: list[dict[str, Any]],
    ) -> None:
        pass

    def find_recent_utterance(
        self,
        *,
        run_id: str,
        current_event_id: int,
        audience: ProjectionAudience = "player_public",
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
    subtitle_timings: list[dict[str, Any]]


@dataclass(frozen=True)
class RecentUtteranceReplayResult:
    should_continue: bool
    last_source_event_id: int | None = None


PlaybackAckQueue = asyncio.Queue[str]


class LiveVoiceStreamService:
    def __init__(
        self,
        *,
        registry: LiveRunRegistry,
        config: VolcengineTtsConfig,
        client_factory: Callable[[VolcengineTtsConfig], TtsClient] = VolcengineTtsClient,
        voice_store_factory: Callable[[str], VoiceStore | None] | None = None,
        judge_voice_asset_dir: Path = DEFAULT_JUDGE_VOICE_ASSET_DIR,
        judge_voice_asset_loader: Callable[[str], StaticJudgeVoiceAsset | None] | None = None,
        persist_streamed_voices: bool = True,
    ) -> None:
        self.registry = registry
        self.config = config
        self.client_factory = client_factory
        self.voice_store_factory = voice_store_factory
        self.judge_voice_asset_dir = judge_voice_asset_dir
        self.judge_voice_asset_loader = judge_voice_asset_loader
        self.persist_streamed_voices = persist_streamed_voices

    @property
    def available(self) -> bool:
        return self.config.available

    async def stream_run(
        self,
        run_id: str,
        websocket: WebSocket,
        *,
        current_event_id: int | None = None,
        playback_ack_required: bool = False,
        audience: ProjectionAudience = "player_public",
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

        canonical_historical_events = self.registry.events_after(run_id)
        last_event_id = canonical_historical_events[-1].id if canonical_historical_events else None
        historical_events = [
            projected
            for event in canonical_historical_events
            if (projected := project_live_event(event, audience)) is not None
        ]
        run = self.registry.try_get_run(run_id)
        if run is None:
            return
        if run.status in TERMINAL_RUN_STATUSES:
            await websocket.send_json(_voice_unavailable_payload("terminal"))
            return

        voice_store = self.voice_store_factory(run.session_id) if self.voice_store_factory else None
        playback_acks: PlaybackAckQueue | None = asyncio.Queue() if playback_ack_required else None
        disconnect_task = asyncio.create_task(_watch_websocket_control(websocket, playback_acks))
        subscriber: queue.Queue[LiveEvent] | None = None
        speaker_config = VoiceSpeakerConfig(
            player_speaker=self.config.player_speaker,
            judge_speaker=self.config.judge_speaker,
        )
        try:
            recent_replay = await _replay_recent_utterance(
                websocket,
                voice_store,
                run_id=run_id,
                current_event_id=current_event_id,
                audience=audience,
                disconnect_task=disconnect_task,
                playback_acks=playback_acks,
            )
            if not recent_replay.should_continue:
                return

            if current_event_id is None:
                replay_after_id = last_event_id
            else:
                replay_after_id = (
                    recent_replay.last_source_event_id
                    if recent_replay.last_source_event_id is not None
                    else current_event_id - 1
                )
            context_events = [
                event
                for event in historical_events
                if replay_after_id is None or event.id <= replay_after_id
            ]
            pending_events = deque(
                event
                for event in historical_events
                if current_event_id is not None and event.id > replay_after_id
            )
            voice_context = _build_voice_context(context_events)
            streamed_delta_request_ids: set[str] = set()
            subscriber = self.registry.subscribe(run_id, after_id=last_event_id)
            while True:
                canonical_event = await _next_voice_event(
                    subscriber,
                    disconnect_task,
                    pending_events,
                )
                if canonical_event is None:
                    return
                event = project_live_event(canonical_event, audience)
                if event is None:
                    continue
                is_terminal = event.type in TERMINAL_EVENT_TYPES
                _update_voice_context_before_event(voice_context, event)
                utterance = event_to_voice_utterance(
                    event,
                    speaker_config,
                    player_seats=voice_context.player_seats,
                    previous_night_deaths=voice_context.previous_night_deaths,
                    peaceful_night=voice_context.peaceful_night,
                )
                if utterance is not None and audience == "spectator_god_view":
                    public_event = project_live_event(canonical_event, "player_public")
                    public_speaker_kind = (
                        voice_job_candidate(public_event)
                        if public_event is not None
                        else None
                    )
                    if public_speaker_kind != utterance.speaker_kind:
                        utterance = replace(
                            utterance,
                            audience="spectator_god_view",
                        )
                if (
                    utterance is not None
                    and utterance.request_id in streamed_delta_request_ids
                    and is_public_complete_speech_event(event)
                ):
                    utterance = None

                if utterance is not None:
                    started_from_delta = is_public_speech_event(event)
                    utterance = await _coalesce_request_deltas(
                        utterance,
                        subscriber,
                        disconnect_task,
                        pending_events,
                        speaker_config,
                        voice_context.player_seats,
                        audience,
                    )
                    if started_from_delta and utterance.request_id is not None:
                        streamed_delta_request_ids.add(utterance.request_id)
                    if disconnect_task.done():
                        return
                    persistence_store = _claim_voice_persistence_store(
                        voice_store if self.persist_streamed_voices else None,
                        utterance,
                    )
                    chunks = chunk_text_for_tts(utterance.text)
                    static_asset = self._static_asset_for_utterance(utterance)
                    if static_asset is not None:
                        if not await self._stream_static_utterance(
                            websocket,
                            utterance,
                            static_asset,
                            disconnect_task,
                            persistence_store,
                            playback_acks,
                        ):
                            return
                    elif chunks and not await self._stream_utterance(
                        websocket,
                        utterance,
                        chunks,
                        disconnect_task,
                        persistence_store,
                        playback_acks,
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
        asset = (
            self.judge_voice_asset_loader(utterance.static_asset_id)
            if self.judge_voice_asset_loader is not None
            else None
        )
        if asset is None:
            asset = _load_static_judge_voice_asset(
                self.judge_voice_asset_dir,
                utterance.static_asset_id,
            )
        if asset is None:
            return None
        return asset

    async def _stream_static_utterance(
        self,
        websocket: WebSocket,
        utterance: VoiceUtterance,
        asset: StaticJudgeVoiceAsset,
        disconnect_task: asyncio.Task[None],
        voice_store: VoiceStore | None,
        playback_acks: PlaybackAckQueue | None,
    ) -> bool:
        started_at = time.monotonic()
        persistence_enabled = _persist_voice_operation(
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
            last_source_event_id=utterance.last_source_event_id,
            speaker_kind=utterance.speaker_kind,
            speaker_name=utterance.speaker_name,
            audio=asset.audio,
            mime_type=asset.mime_type,
            duration_ms=0,
            audio_format=asset.audio_format,
            sample_rate=asset.sample_rate,
            chunk_index=0,
            audience=utterance.audience,
        )
        try:
            await websocket.send_json(start_message)
            if _mark_voice_stream_disconnected_if_needed(
                disconnect_task,
                voice_store,
                utterance,
            ):
                return False
            if asset.subtitle_timings:
                subtitle_message = {
                    "type": "subtitle_timing",
                    "utterance_id": utterance.utterance_id,
                    "cues": asset.subtitle_timings,
                }
                await websocket.send_json(subtitle_message)
                if persistence_enabled:
                    persistence_enabled = _persist_voice_operation(
                        voice_store,
                        utterance,
                        "update_subtitle_timings",
                        lambda: voice_store.update_subtitle_timings(
                            utterance.utterance_id,
                            subtitle_timings=asset.subtitle_timings,
                        ),
                    )
                if _mark_voice_stream_disconnected_if_needed(
                    disconnect_task,
                    voice_store,
                    utterance,
                ):
                    return False
            await websocket.send_json(chunk_message)
            if persistence_enabled:
                persistence_enabled = _persist_voice_operation(
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
            if persistence_enabled:
                _persist_voice_operation(
                    voice_store,
                    utterance,
                    "complete_utterance",
                    lambda: voice_store.complete_utterance(
                        utterance.utterance_id,
                        duration_ms=duration_ms,
                    ),
                )
            if not await _wait_for_playback_ack(
                utterance.utterance_id,
                playback_acks,
                disconnect_task,
            ):
                return False
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
        playback_acks: PlaybackAckQueue | None,
    ) -> bool:
        started_at = time.monotonic()
        audio_format = self.config.audio_format
        sample_rate = self.config.sample_rate
        mime_type = mime_type_for_format(audio_format)
        client = self.client_factory(self.config)
        persistence_enabled = _persist_voice_operation(
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
                    **(
                        {"last_source_event_id": utterance.last_source_event_id}
                        if utterance.last_source_event_id is not None
                        else {}
                    ),
                    "speaker_kind": utterance.speaker_kind,
                    "speaker_name": utterance.speaker_name,
                    "audience": utterance.audience,
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
        audio_task: asyncio.Task[TtsSynthesisItem] | None = None
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

                if isinstance(audio, TtsSubtitleTiming):
                    subtitle_message = build_subtitle_timing_message(
                        utterance.utterance_id,
                        audio,
                    )
                    await websocket.send_json(subtitle_message)
                    if persistence_enabled:
                        persistence_enabled = _persist_voice_operation(
                            voice_store,
                            utterance,
                            "update_subtitle_timings",
                            lambda: voice_store.update_subtitle_timings(
                                utterance.utterance_id,
                                subtitle_timings=subtitle_message["cues"],
                            ),
                        )
                    continue

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
                    audience=utterance.audience,
                )
                await websocket.send_json(chunk_message)
                if persistence_enabled:
                    persistence_enabled = _persist_voice_operation(
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
            if persistence_enabled:
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
            if persistence_enabled:
                _persist_voice_operation(
                    voice_store,
                    utterance,
                    "complete_utterance",
                    lambda: voice_store.complete_utterance(
                        utterance.utterance_id,
                        duration_ms=duration_ms,
                    ),
                )
            if not await _wait_for_playback_ack(
                utterance.utterance_id,
                playback_acks,
                disconnect_task,
            ):
                return False
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


async def _watch_websocket_control(
    websocket: WebSocket,
    playback_acks: PlaybackAckQueue | None,
) -> None:
    try:
        while True:
            message = await websocket.receive()
            if message.get("type") == "websocket.disconnect":
                return
            if playback_acks is not None:
                utterance_id = _playback_ack_utterance_id(message)
                if utterance_id is not None:
                    playback_acks.put_nowait(utterance_id)
    except WebSocketDisconnect:
        return


def _playback_ack_utterance_id(message: dict[str, Any]) -> str | None:
    text = message.get("text")
    if not isinstance(text, str):
        return None
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict) or payload.get("type") != "voice_played":
        return None
    utterance_id = payload.get("utterance_id")
    return utterance_id if isinstance(utterance_id, str) else None


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
    if payload.get("peaceful_night") is True:
        return True
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
        (line for line in lines if isinstance(line, dict) and line.get("id") == asset_id),
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

    audio_format = (
        _string_manifest_value(
            matching_line,
            "audio_format",
        )
        or _string_manifest_value(manifest, "audio_format")
        or audio_path.suffix.lstrip(".")
    )
    if not audio_format:
        return None
    mime_type = (
        _string_manifest_value(matching_line, "mime_type")
        or _string_manifest_value(manifest, "mime_type")
        or mime_type_for_format(audio_format)
    )
    sample_rate = (
        _int_manifest_value(
            matching_line,
            "sample_rate",
        )
        or _int_manifest_value(manifest, "sample_rate")
        or 24000
    )

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
        subtitle_timings=_subtitle_timings_from_manifest_line(matching_line),
    )


def load_static_judge_voice_asset(
    asset_dir: Path,
    asset_id: str,
) -> StaticJudgeVoiceAsset | None:
    """Load one controlled static judge asset for playback or materialization."""
    return _load_static_judge_voice_asset(asset_dir, asset_id)


def build_static_judge_playback_voices(
    events: list[dict[str, Any]],
    *,
    asset_dir: Path = DEFAULT_JUDGE_VOICE_ASSET_DIR,
    speaker_config: VoiceSpeakerConfig | None = None,
    asset_loader: Callable[[str], StaticJudgeVoiceAsset | None] | None = None,
) -> list[dict[str, Any]]:
    config = speaker_config or VoiceSpeakerConfig(
        player_speaker="",
        judge_speaker="static-judge-asset",
    )
    voice_context = VoiceStreamContext(player_seats={})
    voices: list[dict[str, Any]] = []
    for event_data in events:
        event = _live_event_from_playback_dict(event_data)
        if event is None:
            continue
        _update_voice_context_before_event(voice_context, event)
        utterance = event_to_voice_utterance(
            event,
            config,
            player_seats=voice_context.player_seats,
            previous_night_deaths=voice_context.previous_night_deaths,
            peaceful_night=voice_context.peaceful_night,
        )
        if utterance is not None and utterance.static_asset_id is not None:
            asset = asset_loader(utterance.static_asset_id) if asset_loader is not None else None
            if asset is None:
                asset = _load_static_judge_voice_asset(asset_dir, utterance.static_asset_id)
            if asset is not None:
                start_message, chunk_message, _end_message = build_voice_messages(
                    utterance_id=(
                        f"static_judge_{utterance.source_event_id}_{utterance.static_asset_id}"
                    ),
                    source_event_id=utterance.source_event_id,
                    last_source_event_id=utterance.last_source_event_id,
                    speaker_kind=utterance.speaker_kind,
                    speaker_name=utterance.speaker_name,
                    audio=asset.audio,
                    mime_type=asset.mime_type,
                    duration_ms=0,
                    audio_format=asset.audio_format,
                    sample_rate=asset.sample_rate,
                    chunk_index=0,
                    audience=utterance.audience,
                )
                voices.append(
                    {
                        "utterance_id": start_message["utterance_id"],
                        "source_event_id": start_message["source_event_id"],
                        "last_source_event_id": start_message.get(
                            "last_source_event_id",
                            start_message["source_event_id"],
                        ),
                        "speaker_kind": start_message["speaker_kind"],
                        "speaker_name": start_message["speaker_name"],
                        "audience": start_message["audience"],
                        "mime_type": start_message["mime_type"],
                        "audio_format": start_message["audio_format"],
                        "sample_rate": start_message["sample_rate"],
                        "duration_ms": None,
                        "subtitle_timings": asset.subtitle_timings,
                        "chunks": [
                            {
                                "chunk_index": chunk_message["chunk_index"],
                                "data": chunk_message["data"],
                            }
                        ],
                    }
                )
        _update_voice_context_after_event(voice_context, event)
    return voices


def build_voice_playback_coverage(
    events: list[dict[str, Any]],
    effective_voices: list[dict[str, Any]],
    *,
    materialization_lag_ms: int | None = None,
    audience: ProjectionAudience = "player_public",
) -> dict[str, Any]:
    narratable_keys: set[tuple[int, str]] = set()
    terminal_keys: set[tuple[int, str]] = set()
    for event_data in events:
        event = _live_event_from_playback_dict(event_data)
        if event is None:
            continue
        speaker_kind = voice_job_candidate(event, audience=audience)
        if speaker_kind is None:
            continue
        key = (event.id, speaker_kind)
        narratable_keys.add(key)
        if event.type in TERMINAL_EVENT_TYPES:
            terminal_keys.add(key)

    voice_ranges = [
        (
            source_event_id,
            max(source_event_id, last_source_event_id),
            speaker_kind,
        )
        for voice in effective_voices
        if isinstance((source_event_id := voice.get("source_event_id")), int)
        and isinstance(
            (last_source_event_id := voice.get("last_source_event_id", source_event_id)),
            int,
        )
        and isinstance((speaker_kind := voice.get("speaker_kind")), str)
    ]
    covered_keys = {
        (event_id, speaker_kind)
        for event_id, speaker_kind in narratable_keys
        if any(
            voice_kind == speaker_kind and first_event_id <= event_id <= last_event_id
            for first_event_id, last_event_id, voice_kind in voice_ranges
        )
    }
    return {
        "narratable_event_count": len(narratable_keys),
        "effective_voice_event_count": len(covered_keys),
        "missing_narratable_event_count": len(narratable_keys - covered_keys),
        "terminal_judge_voice_present": bool(terminal_keys)
        and terminal_keys.issubset(covered_keys),
        "voice_materialization_lag_ms": materialization_lag_ms,
    }


def _live_event_from_playback_dict(data: dict[str, Any]) -> LiveEvent | None:
    try:
        event_id = data.get("id")
        event_type = data.get("type")
        run_id = data.get("run_id")
        session_id = data.get("session_id")
        created_at = data.get("created_at")
        if (
            not isinstance(event_id, int)
            or not isinstance(event_type, str)
            or not isinstance(run_id, str)
            or not isinstance(session_id, str)
            or not isinstance(created_at, str)
        ):
            return None
        payload = data.get("payload")
        return LiveEvent(
            id=event_id,
            type=event_type,
            run_id=run_id,
            session_id=session_id,
            created_at=created_at,
            round=data.get("round") if isinstance(data.get("round"), int) else None,
            phase=data.get("phase") if isinstance(data.get("phase"), str) else None,
            actor=data.get("actor") if isinstance(data.get("actor"), str) else None,
            action=data.get("action") if isinstance(data.get("action"), str) else None,
            payload=payload if isinstance(payload, dict) else {},
        )
    except (TypeError, ValueError):
        return None


def build_subtitle_timing_message(
    utterance_id: str,
    timing: TtsSubtitleTiming,
) -> dict[str, Any]:
    return {
        "type": "subtitle_timing",
        "utterance_id": utterance_id,
        "cues": [
            {"text": cue.text, "start_ms": cue.start_ms, "end_ms": cue.end_ms}
            for cue in timing.cues
        ],
    }


def _subtitle_timings_from_manifest_line(line: dict[str, Any]) -> list[dict[str, Any]]:
    timings = line.get("subtitle_timings")
    if not isinstance(timings, list):
        return []
    normalized: list[dict[str, Any]] = []
    for timing in timings:
        if not isinstance(timing, dict):
            continue
        text = timing.get("text")
        start_ms = timing.get("start_ms")
        end_ms = timing.get("end_ms")
        if (
            isinstance(text, str)
            and isinstance(start_ms, int)
            and isinstance(end_ms, int)
            and end_ms > start_ms
        ):
            normalized.append({"text": text, "start_ms": start_ms, "end_ms": end_ms})
    return normalized


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
    audience: ProjectionAudience = "player_public",
    disconnect_task: asyncio.Task[None],
    playback_acks: PlaybackAckQueue | None,
) -> RecentUtteranceReplayResult:
    if voice_store is None or current_event_id is None:
        return RecentUtteranceReplayResult(should_continue=True)

    try:
        utterance = voice_store.find_recent_utterance(
            run_id=run_id,
            current_event_id=current_event_id,
            audience=audience,
        )
    except Exception:
        logger.warning(
            "Voice replay lookup failed",
            exc_info=True,
            extra={"run_id": run_id, "current_event_id": current_event_id},
        )
        return RecentUtteranceReplayResult(should_continue=True)
    if utterance is None or utterance.get("status") != "complete":
        return RecentUtteranceReplayResult(should_continue=True)

    utterance_id = utterance.get("utterance_id")
    if not isinstance(utterance_id, str):
        return RecentUtteranceReplayResult(should_continue=True)
    try:
        chunks = voice_store.load_chunks(utterance_id)
    except Exception:
        logger.warning(
            "Voice replay chunk load failed",
            exc_info=True,
            extra={"run_id": run_id, "utterance_id": utterance_id},
        )
        return RecentUtteranceReplayResult(should_continue=True)
    if not chunks:
        return RecentUtteranceReplayResult(should_continue=True)

    duration_ms = utterance.get("duration_ms")
    if not isinstance(duration_ms, int):
        duration_ms = 0
    source_event_id = utterance.get("source_event_id")
    last_source_event_id = utterance.get("last_source_event_id")
    sample_rate = utterance.get("sample_rate")
    speaker_kind = utterance.get("speaker_kind")
    speaker_name = utterance.get("speaker_name")
    mime_type = utterance.get("mime_type")
    audio_format = utterance.get("audio_format")
    audience = utterance.get("audience")
    if audience not in {"player_public", "spectator_god_view"}:
        audience = "player_public"
    if (
        not isinstance(source_event_id, int)
        or speaker_kind not in {"player", "judge"}
        or not isinstance(speaker_name, str)
        or not isinstance(mime_type, str)
        or not isinstance(audio_format, str)
        or not isinstance(sample_rate, int)
    ):
        return RecentUtteranceReplayResult(should_continue=True)
    if not isinstance(last_source_event_id, int):
        last_source_event_id = source_event_id

    start_message, _chunk_message, _end_message = build_voice_messages(
        utterance_id=utterance_id,
        source_event_id=source_event_id,
        last_source_event_id=last_source_event_id,
        speaker_kind=speaker_kind,
        speaker_name=speaker_name,
        audio=chunks[0],
        mime_type=mime_type,
        duration_ms=duration_ms,
        audio_format=audio_format,
        sample_rate=sample_rate,
        chunk_index=0,
        audience=audience,
    )
    if not await _send_replay_message(websocket, start_message, disconnect_task):
        return RecentUtteranceReplayResult(should_continue=False)

    subtitle_timings = _subtitle_timings_from_utterance(utterance)
    if subtitle_timings:
        if not await _send_replay_message(
            websocket,
            {
                "type": "subtitle_timing",
                "utterance_id": utterance_id,
                "cues": subtitle_timings,
            },
            disconnect_task,
        ):
            return RecentUtteranceReplayResult(should_continue=False)

    for chunk_index, audio in enumerate(chunks):
        _start_message, chunk_message, _end_message = build_voice_messages(
            utterance_id=utterance_id,
            source_event_id=source_event_id,
            last_source_event_id=last_source_event_id,
            speaker_kind=speaker_kind,
            speaker_name=speaker_name,
            audio=audio,
            mime_type=mime_type,
            duration_ms=duration_ms,
            audio_format=audio_format,
            sample_rate=sample_rate,
            chunk_index=chunk_index,
            audience=audience,
        )
        if not await _send_replay_message(websocket, chunk_message, disconnect_task):
            return RecentUtteranceReplayResult(should_continue=False)

    end_message = {
        "type": "voice_end",
        "utterance_id": utterance_id,
        "duration_ms": duration_ms,
    }
    if not await _send_replay_message(websocket, end_message, disconnect_task):
        return RecentUtteranceReplayResult(should_continue=False)
    if not await _wait_for_playback_ack(
        utterance_id,
        playback_acks,
        disconnect_task,
    ):
        return RecentUtteranceReplayResult(should_continue=False)
    return RecentUtteranceReplayResult(
        should_continue=True,
        last_source_event_id=last_source_event_id,
    )


def _subtitle_timings_from_utterance(utterance: dict[str, Any]) -> list[dict[str, Any]]:
    value = utterance.get("subtitle_timings")
    if not isinstance(value, list):
        return []
    cues: list[dict[str, Any]] = []
    for cue in value:
        if not isinstance(cue, dict):
            continue
        text = cue.get("text")
        start_ms = cue.get("start_ms")
        end_ms = cue.get("end_ms")
        if (
            isinstance(text, str)
            and isinstance(start_ms, int)
            and isinstance(end_ms, int)
            and end_ms > start_ms
        ):
            cues.append({"text": text, "start_ms": start_ms, "end_ms": end_ms})
    return cues


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


async def _wait_for_playback_ack(
    utterance_id: str,
    playback_acks: PlaybackAckQueue | None,
    disconnect_task: asyncio.Task[None],
) -> bool:
    if playback_acks is None:
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        return True

    deadline = asyncio.get_running_loop().time() + PLAYBACK_ACK_TIMEOUT_SECONDS
    while True:
        if disconnect_task.done():
            return False
        remaining_seconds = deadline - asyncio.get_running_loop().time()
        if remaining_seconds <= 0:
            return True
        ack_task = asyncio.create_task(playback_acks.get())
        done, pending = await asyncio.wait(
            {ack_task, disconnect_task},
            return_when=asyncio.FIRST_COMPLETED,
            timeout=remaining_seconds,
        )
        if ack_task in pending:
            ack_task.cancel()
            with suppress(asyncio.CancelledError):
                await ack_task
        if not done:
            return True
        if disconnect_task in done:
            return False
        if ack_task.result() == utterance_id:
            return True


def _persist_voice_operation(
    voice_store: VoiceStore | None,
    utterance: VoiceUtterance,
    persistence_operation: str,
    persist: Callable[[], None],
) -> bool:
    if voice_store is None:
        return True
    try:
        persist()
        return True
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
        _release_voice_persistence_claim(
            voice_store,
            utterance,
            error_type=f"{persistence_operation}_failed",
        )
        return False


def _claim_voice_persistence_store(
    voice_store: VoiceStore | None,
    utterance: VoiceUtterance,
) -> VoiceStore | None:
    if voice_store is None:
        return None
    try:
        return voice_store if voice_store.claim_streamed_utterance(utterance) else None
    except Exception:
        logger.warning(
            "Voice persistence claim failed",
            exc_info=True,
            extra={
                "run_id": utterance.run_id,
                "source_event_id": utterance.source_event_id,
                "utterance_id": utterance.utterance_id,
                "speaker_kind": utterance.speaker_kind,
                "audience": utterance.audience,
            },
        )
        return None


def _release_voice_persistence_claim(
    voice_store: VoiceStore,
    utterance: VoiceUtterance,
    *,
    error_type: str,
) -> None:
    try:
        voice_store.release_streamed_utterance(
            utterance,
            error_type=error_type,
        )
    except Exception:
        logger.warning(
            "Voice persistence claim release failed",
            exc_info=True,
            extra={
                "run_id": utterance.run_id,
                "source_event_id": utterance.source_event_id,
                "utterance_id": utterance.utterance_id,
                "speaker_kind": utterance.speaker_kind,
                "audience": utterance.audience,
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
    if voice_store is not None:
        _release_voice_persistence_claim(
            voice_store,
            utterance,
            error_type="live_stream_interrupted",
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
    audience: ProjectionAudience = "player_public",
) -> VoiceUtterance:
    if utterance.request_id is None or utterance.speaker_kind != "player":
        return utterance

    texts = [utterance.text]
    last_source_event_id = utterance.last_source_event_id or utterance.source_event_id
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

        projected_event = project_live_event(event, audience)
        if projected_event is None:
            continue
        event = projected_event

        if _is_same_request_progress_event(utterance, event):
            last_source_event_id = max(last_source_event_id, event.id)
            continue

        next_utterance = event_to_voice_utterance(
            event,
            speaker_config,
            player_seats=player_seats,
        )
        if _is_same_request_utterance(utterance, next_utterance):
            last_source_event_id = max(
                last_source_event_id,
                next_utterance.last_source_event_id or next_utterance.source_event_id,
            )
            if is_public_complete_speech_event(event):
                return replace(
                    utterance,
                    last_source_event_id=last_source_event_id,
                    text=next_utterance.text,
                )
            texts.append(next_utterance.text)
            continue

        pending_events.appendleft(event)
        break

    if len(texts) == 1:
        return utterance
    return replace(
        utterance,
        last_source_event_id=last_source_event_id,
        text="".join(texts),
    )


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


def _is_same_request_progress_event(
    utterance: VoiceUtterance,
    event: LiveEvent,
) -> bool:
    return (
        event.type == "model_response_received"
        and event.payload.get("request_id") == utterance.request_id
        and event.action == utterance.action
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
