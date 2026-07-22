from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import WebSocket
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings, settings
from app.db.session import SessionLocal
from app.v2.action_engine import V2ActionEngine, V2ModelPort, V2TtsPort
from app.v2.contracts import (
    V2ActorResponse,
    V2CurrentPresentationResponse,
    V2LiveSnapshotResponse,
)
from app.v2.model_client import V2ModelClient
from app.v2.public_projection import project_public_player_seats
from app.v2.repository import V2ActionRepository, V2PresentationIdentity
from app.v2.service import current_presentation, get_game, server_now
from app.v2.tts_client import V2TtsClient


class V2ClientProtocolError(RuntimeError):
    pass


@dataclass
class _Subscriber:
    websocket: WebSocket
    ready: bool = False


class _GameChannel:
    def __init__(
        self,
        *,
        game_id: str,
        snapshot_factory: Any,
        engine: V2ActionEngine,
    ) -> None:
        self.game_id = game_id
        self._snapshot_factory = snapshot_factory
        self._engine = engine
        self._lock = asyncio.Lock()
        self._subscribers: dict[str, _Subscriber] = {}
        self._task: asyncio.Task[None] | None = None
        self._current_identity: V2PresentationIdentity | None = None
        self._sample_cursor = 0

    async def connect(self, websocket: WebSocket) -> str:
        subscriber_id = f"v2_conn_{uuid4().hex[:16]}"
        async with self._lock:
            subscriber = _Subscriber(websocket=websocket)
            self._subscribers[subscriber_id] = subscriber
            await websocket.send_json(self._snapshot())
        return subscriber_id

    async def ready(self, subscriber_id: str, message: dict[str, Any]) -> None:
        _validate_ready(message)
        async with self._lock:
            subscriber = self._subscribers.get(subscriber_id)
            if subscriber is None:
                raise V2ClientProtocolError("unknown_connection")
            if subscriber.ready:
                return
            await subscriber.websocket.send_json(self._snapshot())
            subscriber.ready = True
            snapshot = self._snapshot()
            if snapshot["live_state"] == "ready" and self._task is None:
                self._task = asyncio.create_task(
                    self._engine.run_first_judge_sentence(
                        game_id=self.game_id,
                        broadcaster=self,
                    )
                )
                self._task.add_done_callback(self._task_done)

    async def disconnect(self, subscriber_id: str) -> None:
        async with self._lock:
            self._subscribers.pop(subscriber_id, None)

    async def broadcast_json(self, value: dict[str, Any]) -> None:
        await self._broadcast(value, binary=False)

    async def broadcast_bytes(self, value: bytes) -> None:
        await self._broadcast(value, binary=True)

    async def set_current(
        self,
        identity: V2PresentationIdentity | None,
        sample_cursor: int,
    ) -> None:
        async with self._lock:
            self._current_identity = identity
            self._sample_cursor = sample_cursor

    async def _broadcast(self, value: Any, *, binary: bool) -> None:
        async with self._lock:
            failed: list[str] = []
            for subscriber_id, subscriber in self._subscribers.items():
                if not subscriber.ready:
                    continue
                try:
                    if binary:
                        await subscriber.websocket.send_bytes(value)
                    else:
                        await subscriber.websocket.send_json(value)
                except Exception:
                    failed.append(subscriber_id)
            for subscriber_id in failed:
                self._subscribers.pop(subscriber_id, None)

    def _snapshot(self) -> dict[str, Any]:
        return self._snapshot_factory(
            game_id=self.game_id,
            sample_cursor=self._sample_cursor,
        )

    def _task_done(self, task: asyncio.Task[None]) -> None:
        if self._task is task:
            self._task = None


class V2LiveRuntime:
    def __init__(
        self,
        *,
        session_factory: sessionmaker[Session],
        model_client: V2ModelPort,
        tts_client: V2TtsPort,
        voice_root: Path,
        sample_rate: int,
    ) -> None:
        self._session_factory = session_factory
        self._repository = V2ActionRepository(session_factory)
        self._engine = V2ActionEngine(
            repository=self._repository,
            model_client=model_client,
            tts_client=tts_client,
            voice_root=voice_root,
            sample_rate=sample_rate,
        )
        self._channels: dict[str, _GameChannel] = {}
        self._channels_lock = asyncio.Lock()

    async def connect(self, *, game_id: str, websocket: WebSocket) -> tuple[str, _GameChannel]:
        channel = await self._channel(game_id)
        return await channel.connect(websocket), channel

    async def ready(
        self,
        *,
        channel: _GameChannel,
        subscriber_id: str,
        message: dict[str, Any],
    ) -> None:
        await channel.ready(subscriber_id, message)

    async def disconnect(
        self,
        *,
        channel: _GameChannel,
        subscriber_id: str,
    ) -> None:
        await channel.disconnect(subscriber_id)

    def snapshot(self, *, game_id: str, sample_cursor: int = 0) -> dict[str, Any]:
        with self._session_factory() as db:
            game = get_game(db, game_id)
            presentation = current_presentation(db, game_id)
            current = None
            if presentation is not None and presentation.action_id is not None:
                current = V2CurrentPresentationResponse(
                    action_id=presentation.action_id,
                    presentation_seq=presentation.presentation_seq,
                    presentation_id=presentation.presentation_id,
                    phase_id=presentation.phase_id,
                    actor=V2ActorResponse(
                        kind=presentation.actor_kind,
                        id=presentation.actor_id,
                    ),
                    speech_id=presentation.speech_id,
                    segment_index=presentation.segment_index,
                    subtitle_text=presentation.subtitle_text,
                    join_sample_cursor=sample_cursor,
                )
            response = V2LiveSnapshotResponse(
                audience="player_public",
                game_id=game.game_id,
                run_id=game.current_run_id,
                live_state=_live_state(game.status),
                latest_presentation_seq=game.last_presentation_seq,
                server_time=server_now(),
                public_players=project_public_player_seats(game.players_snapshot),
                current_presentation=current,
            )
            return response.model_dump(mode="json")

    async def _channel(self, game_id: str) -> _GameChannel:
        async with self._channels_lock:
            channel = self._channels.get(game_id)
            if channel is None:
                self.snapshot(game_id=game_id)
                channel = _GameChannel(
                    game_id=game_id,
                    snapshot_factory=self.snapshot,
                    engine=self._engine,
                )
                self._channels[game_id] = channel
            return channel


def build_v2_live_runtime(config: Settings = settings) -> V2LiveRuntime:
    return V2LiveRuntime(
        session_factory=SessionLocal,
        model_client=V2ModelClient(
            api_key=config.live_v2_model_api_key,
            base_url=config.live_v2_model_base_url,
            model_id=config.live_v2_model_id,
            first_token_seconds=config.live_v2_model_first_token_seconds,
            total_seconds=config.live_v2_model_total_seconds,
        ),
        tts_client=V2TtsClient(
            enabled=config.live_v2_tts_enabled,
            api_key=config.live_v2_tts_api_key,
            resource_id=config.live_v2_tts_resource_id,
            ws_url=config.live_v2_tts_ws_url,
            speaker=config.live_v2_tts_judge_speaker,
            sample_rate=config.live_v2_tts_sample_rate,
            first_chunk_seconds=config.live_v2_tts_first_chunk_seconds,
            idle_seconds=config.live_v2_tts_idle_seconds,
        ),
        voice_root=Path(config.live_v2_voice_storage_dir),
        sample_rate=config.live_v2_tts_sample_rate,
    )


def _validate_ready(message: dict[str, Any]) -> None:
    if message.get("protocol_version") != 1 or message.get("type") != "client.ready":
        raise V2ClientProtocolError("invalid_ready_message")
    audio = message.get("audio")
    if not isinstance(audio, dict):
        raise V2ClientProtocolError("missing_audio_capability")
    expected = {"encoding": "pcm_s16le", "sample_rate": 24000, "channels": 1}
    if any(audio.get(key) != value for key, value in expected.items()):
        raise V2ClientProtocolError("unsupported_audio_capability")


def _live_state(status: str) -> str:
    if status in {
        "ready",
        "generating",
        "broadcasting",
        "finalizing",
        "awaiting_observation",
        "failed",
    }:
        return status
    return "failed"
