from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
import logging
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from fastapi import WebSocket
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings, settings
from app.db.session import SessionLocal
from app.judge_configuration import RuntimeJudgeConfiguration, runtime_judge_configuration
from app.v2.action_engine import V2ActionEngine, V2ModelPort, V2TtsPort
from app.v2.contracts import (
    V2ActorResponse,
    V2CurrentPresentationResponse,
    V2DirectorLiveSnapshotResponse,
    V2GamePhaseResponse,
    V2GodViewLiveSnapshotResponse,
    V2LiveSnapshotResponse,
    V2MatchStateResponse,
)
from app.v2.day_engine import V2DayEngine
from app.v2.director_projection import project_director_scene
from app.v2.god_view_projection import project_god_view_player_identities
from app.v2.first_night_engine import V2NightEngine
from app.v2.flow_engine import V2LiveFlowEngine
from app.v2.model_client import V2ModelClient
from app.v2.night_repository import V2NightRepository
from app.v2.match_repository import V2MatchRepository
from app.v2.public_projection import (
    project_public_player_seats,
    project_public_role_assignment_status,
    project_public_rule_snapshot,
)
from app.v2.protocol import live_state
from app.v2.repository import V2ActionRepository, V2PresentationIdentity
from app.v2.service import (
    current_presentation,
    current_action_context,
    get_game,
    get_match_state,
    god_view_role_assignments,
    player_state_map,
    role_assignment_count,
    server_now,
)
from app.v2.tts_client import V2TtsClient


logger = logging.getLogger(__name__)


class V2ClientProtocolError(RuntimeError):
    pass


V2Audience = Literal["player_public", "spectator_directed", "spectator_god_view"]


def _audience_targets(value: str) -> tuple[V2Audience, ...]:
    if value == "all":
        return ("player_public", "spectator_directed", "spectator_god_view")
    if value == "public":
        return ("player_public", "spectator_directed")
    if value == "god_view":
        return ("spectator_directed", "spectator_god_view")
    if value == "director":
        return ("spectator_directed",)
    raise V2ClientProtocolError("invalid_server_audience")


@dataclass
class _Subscriber:
    websocket: WebSocket
    audience: V2Audience
    ready: bool = False


class _GameChannel:
    def __init__(
        self,
        *,
        game_id: str,
        snapshot_factory: Any,
        game_starter: Callable[..., bool],
        engine: V2LiveFlowEngine,
    ) -> None:
        self.game_id = game_id
        self._snapshot_factory = snapshot_factory
        self._game_starter = game_starter
        self._engine = engine
        self._lock = asyncio.Lock()
        self._subscribers: dict[str, _Subscriber] = {}
        self._task: asyncio.Task[None] | None = None
        self._current_identity: dict[V2Audience, V2PresentationIdentity | None] = {
            "player_public": None,
            "spectator_directed": None,
            "spectator_god_view": None,
        }
        self._sample_cursor: dict[V2Audience, int] = {
            "player_public": 0,
            "spectator_directed": 0,
            "spectator_god_view": 0,
        }

    async def connect(self, websocket: WebSocket, *, audience: V2Audience) -> str:
        subscriber_id = f"v2_conn_{uuid4().hex[:16]}"
        async with self._lock:
            subscriber = _Subscriber(websocket=websocket, audience=audience)
            self._subscribers[subscriber_id] = subscriber
            await websocket.send_json(self._snapshot(audience))
        return subscriber_id

    async def ready(self, subscriber_id: str, message: dict[str, Any]) -> None:
        async with self._lock:
            subscriber = self._subscribers.get(subscriber_id)
            if subscriber is None:
                raise V2ClientProtocolError("unknown_connection")
            _validate_ready(message, audience=subscriber.audience)
            if subscriber.ready:
                return
            subscriber.ready = True
            before_start = self._snapshot(subscriber.audience)
            if before_start["live_state"] == "waiting_to_start":
                self._game_starter(game_id=self.game_id, audience=subscriber.audience)
            snapshot = self._snapshot(subscriber.audience)
            await subscriber.websocket.send_json(snapshot)
            if snapshot["live_state"] == "ready" and self._task is None:
                self._task = asyncio.create_task(
                    self._engine.run(
                        game_id=self.game_id,
                        broadcaster=self,
                    )
                )
                self._task.add_done_callback(self._task_done)

    async def disconnect(self, subscriber_id: str) -> None:
        async with self._lock:
            self._subscribers.pop(subscriber_id, None)

    async def interrupt(self) -> None:
        async with self._lock:
            task = self._task
        if task is None or task.done():
            return
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    async def broadcast_json(
        self,
        value: dict[str, Any],
        *,
        audience: str = "all",
    ) -> None:
        await self._broadcast(value, binary=False, audience=audience)

    async def broadcast_bytes(self, value: bytes, *, audience: str = "all") -> None:
        await self._broadcast(value, binary=True, audience=audience)

    async def broadcast_audio(
        self,
        value: bytes,
        *,
        identity: V2PresentationIdentity,
        next_sample_cursor: int,
        audience: str = "all",
    ) -> None:
        async with self._lock:
            targets = _audience_targets(audience)
            failed: list[str] = []
            for subscriber_id, subscriber in self._subscribers.items():
                if not subscriber.ready or subscriber.audience not in targets:
                    continue
                try:
                    await subscriber.websocket.send_bytes(value)
                except Exception:
                    failed.append(subscriber_id)
            for subscriber_id in failed:
                self._subscribers.pop(subscriber_id, None)
            for target in targets:
                self._current_identity[target] = identity
                self._sample_cursor[target] = next_sample_cursor

    async def set_current(
        self,
        identity: V2PresentationIdentity | None,
        sample_cursor: int,
        *,
        audience: str = "all",
    ) -> None:
        async with self._lock:
            for target in _audience_targets(audience):
                self._current_identity[target] = identity
                self._sample_cursor[target] = sample_cursor

    async def _broadcast(self, value: Any, *, binary: bool, audience: str) -> None:
        async with self._lock:
            failed: list[str] = []
            for subscriber_id, subscriber in self._subscribers.items():
                if not subscriber.ready or subscriber.audience not in _audience_targets(audience):
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

    def _snapshot(self, audience: V2Audience) -> dict[str, Any]:
        return self._snapshot_factory(
            game_id=self.game_id,
            sample_cursor=self._sample_cursor[audience],
            audience=audience,
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
        judge_configuration_provider: Callable[[], RuntimeJudgeConfiguration],
    ) -> None:
        self._session_factory = session_factory
        self._repository = V2ActionRepository(session_factory)
        self._night_repository = V2NightRepository(session_factory)
        self._match_repository = V2MatchRepository(session_factory)
        self._action_engine = V2ActionEngine(
            repository=self._repository,
            model_client=model_client,
            tts_client=tts_client,
            voice_root=voice_root,
            sample_rate=sample_rate,
            judge_configuration_provider=judge_configuration_provider,
        )
        self._first_night_engine = V2NightEngine(
            repository=self._night_repository,
            action_engine=self._action_engine,
        )
        self._day_engine = V2DayEngine(
            repository=self._match_repository,
            action_engine=self._action_engine,
        )
        self._engine = V2LiveFlowEngine(
            action_repository=self._repository,
            night_repository=self._night_repository,
            match_repository=self._match_repository,
            action_engine=self._action_engine,
            first_night_engine=self._first_night_engine,
            day_engine=self._day_engine,
        )
        self._channels: dict[str, _GameChannel] = {}
        self._channels_lock = asyncio.Lock()

    async def connect(
        self,
        *,
        game_id: str,
        websocket: WebSocket,
        audience: V2Audience = "player_public",
    ) -> tuple[str, _GameChannel]:
        channel = await self._channel(game_id)
        return await channel.connect(websocket, audience=audience), channel

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

    async def interrupt(self, *, game_id: str) -> str:
        async with self._channels_lock:
            channel = self._channels.get(game_id)
        if channel is not None:
            await channel.interrupt()
        result = self._repository.cancel_game(game_id)
        if result.changed and channel is not None:
            await channel.set_current(None, 0)
            await channel.broadcast_json(
                live_state(
                    game_id=game_id,
                    run_id=result.run_id,
                    state="canceled",
                    reason="operator_interrupted",
                )
            )
        return result.status

    def snapshot(
        self,
        *,
        game_id: str,
        sample_cursor: int = 0,
        audience: V2Audience = "player_public",
    ) -> dict[str, Any]:
        with self._session_factory() as db:
            game = get_game(db, game_id)
            match = get_match_state(db, game_id)
            presentation = current_presentation(db, game_id, audience=audience)
            states = player_state_map(db, game_id)
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
            if audience == "spectator_directed":
                response = V2DirectorLiveSnapshotResponse(
                    game_id=game.game_id,
                    run_id=game.current_run_id,
                    live_state=_live_state(game.status),
                    game_phase=_game_phase(game),
                    match_state=_match_state(match),
                    latest_presentation_seq=game.last_presentation_seq,
                    server_time=server_now(),
                    rule=project_public_rule_snapshot(game.rule_snapshot),
                    players=project_god_view_player_identities(
                        players_snapshot=game.players_snapshot,
                        assignments=god_view_role_assignments(db, game.game_id),
                        player_states=states,
                    ),
                    current_scene=project_director_scene(
                        phase_id=game.phase_id,
                        phase_state=game.phase_state,
                        action_context=current_action_context(db, game.game_id),
                    ),
                    current_presentation=current,
                )
            elif audience == "spectator_god_view":
                response = V2GodViewLiveSnapshotResponse(
                    game_id=game.game_id,
                    run_id=game.current_run_id,
                    live_state=_live_state(game.status),
                    game_phase=_game_phase(game),
                    match_state=_match_state(match),
                    latest_presentation_seq=game.last_presentation_seq,
                    server_time=server_now(),
                    rule=project_public_rule_snapshot(game.rule_snapshot),
                    players=project_god_view_player_identities(
                        players_snapshot=game.players_snapshot,
                        assignments=god_view_role_assignments(db, game.game_id),
                        player_states=states,
                    ),
                    current_presentation=current,
                )
            else:
                response = V2LiveSnapshotResponse(
                    audience="player_public",
                    game_id=game.game_id,
                    run_id=game.current_run_id,
                    live_state=_live_state(game.status),
                    game_phase=_game_phase(game),
                    match_state=_match_state(match),
                    latest_presentation_seq=game.last_presentation_seq,
                    server_time=server_now(),
                    public_rule=project_public_rule_snapshot(game.rule_snapshot),
                    public_players=project_public_player_seats(
                        game.players_snapshot,
                        player_states=states,
                    ),
                    public_role_assignment=project_public_role_assignment_status(
                        role_assignment_count(db, game.game_id)
                    ),
                    current_presentation=current,
                )
            return response.model_dump(mode="json")

    async def _channel(self, game_id: str) -> _GameChannel:
        async with self._channels_lock:
            channel = self._channels.get(game_id)
            if channel is None:
                self.snapshot(game_id=game_id, audience="player_public")
                channel = _GameChannel(
                    game_id=game_id,
                    snapshot_factory=self.snapshot,
                    game_starter=self._repository.start_game,
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
        judge_configuration_provider=lambda: _runtime_judge_configuration(config),
    )


def _runtime_judge_configuration(config: Settings) -> RuntimeJudgeConfiguration:
    try:
        with SessionLocal() as db:
            return runtime_judge_configuration(
                db,
                default_model_id=config.live_v2_model_id,
                default_tts_speaker=config.live_v2_tts_judge_speaker,
            )
    except Exception:
        logger.warning("Falling back to environment judge configuration", exc_info=True)
        return RuntimeJudgeConfiguration(
            model_provider="agent_plan",
            model_id=config.live_v2_model_id,
            tts_speaker=config.live_v2_tts_judge_speaker,
            version=0,
        )


def _validate_ready(message: dict[str, Any], *, audience: V2Audience) -> None:
    expected_type = {
        "player_public": "client.ready",
        "spectator_directed": "director.ready",
        "spectator_god_view": "god_view.ready",
    }[audience]
    if message.get("protocol_version") != 1 or message.get("type") != expected_type:
        raise V2ClientProtocolError("invalid_ready_message")
    audio = message.get("audio")
    if not isinstance(audio, dict):
        raise V2ClientProtocolError("missing_audio_capability")
    expected = {"encoding": "pcm_s16le", "sample_rate": 24000, "channels": 1}
    if any(audio.get(key) != value for key, value in expected.items()):
        raise V2ClientProtocolError("unsupported_audio_capability")


def _live_state(status: str) -> str:
    if status in {
        "waiting_to_start",
        "ready",
        "generating",
        "broadcasting",
        "finalizing",
        "awaiting_observation",
        "canceled",
        "failed",
    }:
        return status
    return "failed"


def _game_phase(game: Any) -> V2GamePhaseResponse:
    return V2GamePhaseResponse(
        phase_seq=game.phase_seq,
        phase_id=game.phase_id,
        phase_state=game.phase_state,
    )


def _match_state(match: Any) -> V2MatchStateResponse | None:
    if match is None:
        return None
    return V2MatchStateResponse(
        round_no=match.round_no,
        sheriff_player_id=match.sheriff_player_id,
        sheriff_badge_state=match.sheriff_badge_state,
        winner=match.winner,
    )
