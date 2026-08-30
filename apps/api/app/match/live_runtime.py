from __future__ import annotations

import asyncio
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
import logging
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from fastapi import WebSocket
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings, settings
from app.db.session import SessionLocal
from app.judge_configuration import (
    RuntimeJudgeConfiguration,
    build_judge_voice_snapshot,
    configuration_from_voice_snapshot,
    runtime_judge_configuration,
)
from app.match.action_engine import (
    ActionEngine,
    ModelPort,
    ModelRetryPolicy,
    TtsPort,
)
from app.match.contracts import (
    ActorResponse,
    CurrentPresentationResponse,
    DirectorLiveSnapshotResponse,
    GamePhaseResponse,
    GodViewLiveSnapshotResponse,
    LiveSnapshotResponse,
    MatchStateResponse,
)
from app.match.day_engine import DayEngine
from app.match.day_speech_pipeline_repository import DaySpeechPipelineRepository
from app.match.director_projection import project_director_scene
from app.match.god_view_projection import project_god_view_player_identities
from app.match.first_night_engine import NightEngine
from app.match.execution import RunFence, bind_run_fence, database_utc_now
from app.match.flow_engine import LiveFlowEngine
from app.match.model_client import ModelClient
from app.match.model_context_contract import (
    supports_model_context_contract,
)
from app.match.model_generation_policy_contract import (
    ModelGenerationPolicyContractError,
    resolve_model_generation_policy_contract,
)
from app.match.night_repository import NightRepository
from app.match.match_repository import MatchRepository
from app.match.models import GameRecord, GameRun
from app.match.public_projection import (
    project_public_player_seats,
    project_public_role_assignment_status,
    project_public_rule_snapshot,
)
from app.match.protocol import live_state
from app.match.pre_exile_pipeline_repository import PreExilePipelineRepository
from app.match.repository import ActionRepository, PresentationIdentity
from app.match.runtime_state import project_runtime_state
from app.match.service import (
    RecordNotFound,
    current_presentation,
    current_action_context,
    get_game,
    get_match_state,
    god_view_role_assignments,
    player_state_map,
    role_assignment_count,
    server_now,
)
from app.match.tts_client import TtsClient


logger = logging.getLogger(__name__)


class ClientProtocolError(RuntimeError):
    pass


Audience = Literal["player_public", "spectator_directed", "spectator_god_view"]


def _audience_targets(value: str) -> tuple[Audience, ...]:
    if value == "all":
        return ("player_public", "spectator_directed", "spectator_god_view")
    if value == "public":
        return ("player_public", "spectator_directed")
    if value == "god_view":
        return ("spectator_directed", "spectator_god_view")
    if value == "director":
        return ("spectator_directed",)
    raise ClientProtocolError("invalid_server_audience")


@dataclass
class _Subscriber:
    websocket: WebSocket
    audience: Audience
    ready: bool = False


class _GameChannel:
    def __init__(
        self,
        *,
        game_id: str,
        snapshot_factory: Any,
        engine: LiveFlowEngine,
        repository: ActionRepository | None = None,
        game_starter: Callable[..., bool] | None = None,
        worker_id: str = "test_worker",
        lease_seconds: float = 15.0,
        heartbeat_seconds: float = 3.0,
        tts_capability_enabled: bool = True,
    ) -> None:
        self.game_id = game_id
        self._snapshot_factory = snapshot_factory
        self._repository = repository
        self._legacy_game_starter = game_starter
        self._engine = engine
        self._worker_id = worker_id
        self._lease_seconds = lease_seconds
        self._heartbeat_seconds = heartbeat_seconds
        self._tts_capability_enabled = tts_capability_enabled
        self._lock = asyncio.Lock()
        self._subscribers: dict[str, _Subscriber] = {}
        self._task: asyncio.Task[None] | None = None
        self._current_identity: dict[Audience, PresentationIdentity | None] = {
            "player_public": None,
            "spectator_directed": None,
            "spectator_god_view": None,
        }
        self._sample_cursor: dict[Audience, int] = {
            "player_public": 0,
            "spectator_directed": 0,
            "spectator_god_view": 0,
        }

    async def connect(self, websocket: WebSocket, *, audience: Audience) -> str:
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
                raise ClientProtocolError("unknown_connection")
            before_start = self._snapshot(subscriber.audience)
            _validate_ready(
                message,
                audience=subscriber.audience,
                audio_required=before_start.get("audio_mode", "tts") == "tts",
            )
            if subscriber.ready:
                return
            if (
                before_start["live_state"] == "waiting_to_start"
                and before_start.get("audio_mode") == "tts"
                and not self._tts_capability_enabled
            ):
                raise ClientProtocolError("v2_audio_mode_unavailable")
            subscriber.ready = True
            if before_start["live_state"] == "waiting_to_start":
                if self._repository is not None:
                    claim = self._repository.start_and_claim_execution(
                        game_id=self.game_id,
                        audience=subscriber.audience,
                        worker_id=self._worker_id,
                        lease_seconds=self._lease_seconds,
                    )
                    if claim.status == "owned" and claim.fence is not None:
                        self._register_owned_task(claim.fence)
                elif self._legacy_game_starter is not None:
                    self._legacy_game_starter(
                        game_id=self.game_id,
                        audience=subscriber.audience,
                    )
            snapshot = self._snapshot(subscriber.audience)
            await subscriber.websocket.send_json(snapshot)

    def _register_owned_task(self, fence: RunFence) -> None:
        if self._task is not None:
            return
        self._task = asyncio.create_task(self._run_owned(fence))
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
        identity: PresentationIdentity,
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
        identity: PresentationIdentity | None,
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

    def _snapshot(self, audience: Audience) -> dict[str, Any]:
        return self._snapshot_factory(
            game_id=self.game_id,
            sample_cursor=self._sample_cursor[audience],
            audience=audience,
        )

    def _task_done(self, task: asyncio.Task[None]) -> None:
        if self._task is task:
            self._task = None
        with suppress(asyncio.CancelledError):
            error = task.exception()
            if error is not None:
                logger.error(
                    "Live V2 owned task failed",
                    exc_info=(type(error), error, error.__traceback__),
                    extra={"game_id": self.game_id, "worker_id": self._worker_id},
                )

    async def _run_owned(self, fence: RunFence) -> None:
        if self._repository is None:
            raise RuntimeError("V2 execution repository is unavailable")
        task = asyncio.current_task()
        if task is None:
            raise RuntimeError("V2 engine task is unavailable")
        lease_lost = asyncio.Event()
        heartbeat = asyncio.create_task(self._heartbeat(fence, task, lease_lost))
        release_reason = "completed"
        try:
            with bind_run_fence(fence):
                await self._engine.run(game_id=self.game_id, broadcaster=self)
                release_reason = self._repository.execution_release_reason(fence=fence)
        except asyncio.CancelledError:
            release_reason = "canceled"
            raise
        except Exception:
            release_reason = "failed"
            raise
        finally:
            heartbeat.cancel()
            with suppress(asyncio.CancelledError):
                await heartbeat
            if not lease_lost.is_set():
                loss_reason = "execution_release_rejected"
                try:
                    released = self._repository.release_execution(
                        fence=fence,
                        reason=release_reason,
                    )
                except Exception:
                    logger.exception(
                        "Live V2 execution release failed closed",
                        extra={
                            "game_id": self.game_id,
                            "run_id": fence.run_id,
                            "worker_id": fence.worker_id,
                            "fence_token": fence.fence_token,
                        },
                    )
                    released = False
                    loss_reason = "execution_release_storage_error"
                if released:
                    await self._broadcast_current_snapshots()
                else:
                    try:
                        self._repository.record_execution_heartbeat_lost(
                            fence=fence,
                            reason=loss_reason,
                        )
                    except Exception:
                        logger.exception(
                            "Live V2 execution release loss could not be persisted",
                            extra={
                                "game_id": self.game_id,
                                "run_id": fence.run_id,
                                "worker_id": fence.worker_id,
                                "fence_token": fence.fence_token,
                            },
                        )

    async def _broadcast_current_snapshots(self) -> None:
        """Refresh connected clients after runtime-only state changes."""
        async with self._lock:
            snapshots: dict[Audience, dict[str, Any]] = {}
            failed: list[str] = []
            for subscriber_id, subscriber in self._subscribers.items():
                if not subscriber.ready:
                    continue
                try:
                    snapshot = snapshots.get(subscriber.audience)
                    if snapshot is None:
                        snapshot = self._snapshot(subscriber.audience)
                        snapshots[subscriber.audience] = snapshot
                    await subscriber.websocket.send_json(snapshot)
                except Exception:
                    failed.append(subscriber_id)
            for subscriber_id in failed:
                self._subscribers.pop(subscriber_id, None)

    async def _heartbeat(
        self,
        fence: RunFence,
        engine_task: asyncio.Task[None],
        lease_lost: asyncio.Event,
    ) -> None:
        if self._repository is None:
            lease_lost.set()
            engine_task.cancel()
            return
        while True:
            await asyncio.sleep(self._heartbeat_seconds)
            try:
                owned = self._repository.heartbeat_execution(
                    fence=fence,
                    lease_seconds=self._lease_seconds,
                )
                loss_reason = "fence_or_lease_rejected"
            except Exception:
                logger.exception(
                    "Live V2 execution heartbeat failed closed",
                    extra={"game_id": self.game_id, "worker_id": self._worker_id},
                )
                owned = False
                loss_reason = "heartbeat_storage_error"
            if not owned:
                logger.error(
                    "Live V2 execution lease lost",
                    extra={
                        "game_id": self.game_id,
                        "run_id": fence.run_id,
                        "worker_id": fence.worker_id,
                        "fence_token": fence.fence_token,
                        "reason": loss_reason,
                    },
                )
                try:
                    self._repository.record_execution_heartbeat_lost(
                        fence=fence,
                        reason=loss_reason,
                    )
                except Exception:
                    logger.exception(
                        "Live V2 execution heartbeat loss could not be persisted",
                        extra={
                            "game_id": self.game_id,
                            "run_id": fence.run_id,
                            "worker_id": fence.worker_id,
                            "fence_token": fence.fence_token,
                        },
                    )
                lease_lost.set()
                engine_task.cancel()
                return


class LiveRuntime:
    def __init__(
        self,
        *,
        session_factory: sessionmaker[Session],
        model_client: ModelPort,
        tts_client: TtsPort | None,
        voice_root: Path,
        sample_rate: int,
        judge_configuration_provider: Callable[[str], RuntimeJudgeConfiguration],
        model_retry_policy: ModelRetryPolicy = ModelRetryPolicy(),
        tts_client_factory: Callable[[], TtsPort] | None = None,
        tts_capability_enabled: bool | None = None,
        worker_id: str | None = None,
        lease_seconds: float = 15.0,
        heartbeat_seconds: float = 3.0,
    ) -> None:
        if heartbeat_seconds >= lease_seconds:
            raise ValueError("V2 heartbeat interval must be shorter than its lease")
        self._session_factory = session_factory
        self._model_client = model_client
        self._worker_id = worker_id or f"v2_worker_{uuid4().hex[:20]}"
        self._lease_seconds = lease_seconds
        self._heartbeat_seconds = heartbeat_seconds
        self._tts_capability_enabled = (
            bool(getattr(tts_client, "enabled", True))
            if tts_capability_enabled is None
            else tts_capability_enabled
        )
        if tts_client is None and tts_client_factory is None:
            self._tts_capability_enabled = False
        self._repository = ActionRepository(
            session_factory,
            enforce_execution_fence=True,
        )
        self._night_repository = NightRepository(
            session_factory,
            enforce_execution_fence=True,
        )
        self._match_repository = MatchRepository(
            session_factory,
            enforce_execution_fence=True,
        )
        self._day_speech_pipeline_repository = DaySpeechPipelineRepository(session_factory)
        self._pre_exile_pipeline_repository = PreExilePipelineRepository(session_factory)
        self._action_engine = ActionEngine(
            repository=self._repository,
            model_client=model_client,
            tts_client=tts_client,
            tts_client_factory=tts_client_factory,
            tts_capability_enabled=self._tts_capability_enabled,
            voice_root=voice_root,
            sample_rate=sample_rate,
            judge_configuration_provider=judge_configuration_provider,
            model_retry_policy=model_retry_policy,
        )
        self._day_engine = DayEngine(
            repository=self._match_repository,
            action_engine=self._action_engine,
            day_speech_pipeline_repository=self._day_speech_pipeline_repository,
            pre_exile_pipeline_repository=self._pre_exile_pipeline_repository,
        )
        self._first_night_engine = NightEngine(
            repository=self._night_repository,
            action_engine=self._action_engine,
            day_engine=self._day_engine,
        )
        self._engine = LiveFlowEngine(
            action_repository=self._repository,
            night_repository=self._night_repository,
            match_repository=self._match_repository,
            action_engine=self._action_engine,
            first_night_engine=self._first_night_engine,
            day_engine=self._day_engine,
        )
        self._channels: dict[str, _GameChannel] = {}
        self._channels_lock = asyncio.Lock()

    @property
    def tts_capability_enabled(self) -> bool:
        return self._tts_capability_enabled

    @property
    def default_audio_mode(self) -> Literal["tts", "text_only"]:
        return "tts" if self._tts_capability_enabled else "text_only"

    async def aclose(self) -> None:
        close = getattr(self._model_client, "aclose", None)
        if callable(close):
            await close()

    async def connect(
        self,
        *,
        game_id: str,
        websocket: WebSocket,
        audience: Audience = "player_public",
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

    async def retry_paused_model_action(
        self,
        *,
        game_id: str,
        action_id: str,
        control_request_id: str,
    ) -> bool:
        return await self._action_engine.retry_paused_model_action(
            game_id=game_id,
            action_id=action_id,
            control_request_id=control_request_id,
        )

    def snapshot(
        self,
        *,
        game_id: str,
        sample_cursor: int = 0,
        audience: Audience = "player_public",
    ) -> dict[str, Any]:
        with self._session_factory() as db:
            game = get_game(db, game_id)
            match = get_match_state(db, game_id)
            run = db.get(GameRun, game.current_run_id)
            if run is None:
                raise RecordNotFound(f"missing current run for {game_id}")
            runtime_state = project_runtime_state(
                game=game,
                run=run,
                match=match,
                now=database_utc_now(db),
            )
            runtime_fields = {
                "audio_mode": runtime_state.audio_mode,
                "match_status": runtime_state.match_status,
                "execution_state": runtime_state.execution_state,
                "winner": runtime_state.winner,
                "completion_reason": runtime_state.completion_reason,
                "completed_at": runtime_state.completed_at,
            }
            presentation = current_presentation(db, game_id, audience=audience)
            states = player_state_map(db, game_id)
            current = None
            if presentation is not None and presentation.action_id is not None:
                current = CurrentPresentationResponse(
                    action_id=presentation.action_id,
                    presentation_seq=presentation.presentation_seq,
                    presentation_id=presentation.presentation_id,
                    phase_id=presentation.phase_id,
                    actor=ActorResponse(
                        kind=presentation.actor_kind,
                        id=presentation.actor_id,
                    ),
                    speech_id=presentation.speech_id,
                    segment_index=presentation.segment_index,
                    subtitle_text=presentation.subtitle_text,
                    join_sample_cursor=sample_cursor,
                )
            if audience == "spectator_directed":
                response = DirectorLiveSnapshotResponse(
                    game_id=game.game_id,
                    run_id=game.current_run_id,
                    live_state=_live_state(game.status),
                    **runtime_fields,
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
                response = GodViewLiveSnapshotResponse(
                    game_id=game.game_id,
                    run_id=game.current_run_id,
                    live_state=_live_state(game.status),
                    **runtime_fields,
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
                response = LiveSnapshotResponse(
                    audience="player_public",
                    game_id=game.game_id,
                    run_id=game.current_run_id,
                    live_state=_live_state(game.status),
                    **runtime_fields,
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
                with self._session_factory() as db:
                    game = get_game(db, game_id)
                    if not supports_model_context_contract(game.rule_snapshot):
                        raise ClientProtocolError("unsupported_model_context_contract")
                    try:
                        resolve_model_generation_policy_contract(game.rule_snapshot)
                    except ModelGenerationPolicyContractError as exc:
                        raise ClientProtocolError(
                            "unsupported_model_generation_policy_contract"
                        ) from exc
                channel = _GameChannel(
                    game_id=game_id,
                    snapshot_factory=self.snapshot,
                    repository=self._repository,
                    engine=self._engine,
                    worker_id=self._worker_id,
                    lease_seconds=self._lease_seconds,
                    heartbeat_seconds=self._heartbeat_seconds,
                    tts_capability_enabled=self._tts_capability_enabled,
                )
                self._channels[game_id] = channel
            return channel


def build_live_runtime(config: Settings = settings) -> LiveRuntime:
    return LiveRuntime(
        session_factory=SessionLocal,
        model_client=ModelClient(
            agent_plan_api_key=config.live_v2_agent_plan_api_key,
            agent_plan_base_url=config.live_v2_agent_plan_base_url,
            ark_api_key=config.live_v2_ark_api_key,
            ark_base_url=config.live_v2_ark_base_url,
            deepseek_api_key=config.live_v2_deepseek_api_key,
            deepseek_base_url=config.live_v2_deepseek_base_url,
            first_token_seconds=config.live_v2_model_first_token_seconds,
            stream_idle_seconds=config.live_v2_model_stream_idle_seconds,
            total_seconds=config.live_v2_model_attempt_total_seconds,
            agent_plan_max_in_flight=config.live_v2_agent_plan_max_in_flight,
            ark_max_in_flight=config.live_v2_ark_max_in_flight,
            deepseek_max_in_flight=config.live_v2_deepseek_max_in_flight,
            agent_plan_supports_strict_json_schema=(
                config.live_v2_agent_plan_supports_strict_json_schema
            ),
            ark_supports_strict_json_schema=config.live_v2_ark_supports_strict_json_schema,
            deepseek_supports_strict_json_schema=(
                config.live_v2_deepseek_supports_strict_json_schema
            ),
        ),
        tts_client=None,
        tts_client_factory=(
            (
                lambda: TtsClient(
                    enabled=True,
                    api_key=config.live_v2_tts_api_key,
                    resource_id=config.live_v2_tts_resource_id,
                    ws_url=config.live_v2_tts_ws_url,
                    speaker=config.live_v2_tts_judge_speaker,
                    sample_rate=config.live_v2_tts_sample_rate,
                    first_chunk_seconds=config.live_v2_tts_first_chunk_seconds,
                    idle_seconds=config.live_v2_tts_idle_seconds,
                )
            )
            if config.live_v2_tts_enabled
            else None
        ),
        tts_capability_enabled=config.live_v2_tts_enabled,
        voice_root=Path(config.live_v2_voice_storage_dir),
        sample_rate=config.live_v2_tts_sample_rate,
        judge_configuration_provider=lambda game_id: _runtime_judge_configuration(
            config,
            game_id,
        ),
        model_retry_policy=ModelRetryPolicy(
            max_attempts=config.live_v2_model_max_attempts,
            attempt_total_seconds=config.live_v2_model_attempt_total_seconds,
            action_total_seconds=config.live_v2_model_action_total_seconds,
            base_delay_seconds=config.live_v2_model_retry_base_delay_seconds,
            jitter_seconds=config.live_v2_model_retry_jitter_seconds,
        ),
        lease_seconds=config.live_run_lease_seconds,
        heartbeat_seconds=config.live_run_heartbeat_seconds,
    )


def _runtime_judge_configuration(
    config: Settings,
    game_id: str,
) -> RuntimeJudgeConfiguration:
    try:
        with SessionLocal.begin() as db:
            game = db.get(GameRecord, game_id)
            if game is not None:
                frozen = configuration_from_voice_snapshot(game.judge_voice_snapshot)
                if frozen is not None:
                    return frozen
            current = runtime_judge_configuration(
                db,
                default_tts_speaker=config.live_v2_tts_judge_speaker,
            )
            if game is None:
                return current
            snapshot = build_judge_voice_snapshot(current)
            game.judge_voice_snapshot = snapshot
            return configuration_from_voice_snapshot(snapshot) or current
    except Exception:
        logger.warning("Falling back to environment judge configuration", exc_info=True)
        return RuntimeJudgeConfiguration(
            voice_mode="fixed",
            tts_speaker=config.live_v2_tts_judge_speaker,
            random_tts_speakers=(),
            version=0,
        )


def _validate_ready(
    message: dict[str, Any],
    *,
    audience: Audience,
    audio_required: bool,
) -> None:
    expected_type = {
        "player_public": "client.ready",
        "spectator_directed": "director.ready",
        "spectator_god_view": "god_view.ready",
    }[audience]
    if message.get("protocol_version") != 1 or message.get("type") != expected_type:
        raise ClientProtocolError("invalid_ready_message")
    audio = message.get("audio")
    if audio is None and not audio_required:
        return
    if not isinstance(audio, dict):
        raise ClientProtocolError("missing_audio_capability")
    expected = {"encoding": "pcm_s16le", "sample_rate": 24000, "channels": 1}
    if any(audio.get(key) != value for key, value in expected.items()):
        raise ClientProtocolError("unsupported_audio_capability")


def _live_state(status: str) -> str:
    if status in {
        "waiting_to_start",
        "ready",
        "generating",
        "broadcasting",
        "finalizing",
        "awaiting_observation",
        "paused_model_error",
        "canceled",
        "failed",
    }:
        return status
    return "failed"


def _game_phase(game: Any) -> GamePhaseResponse:
    return GamePhaseResponse(
        phase_seq=game.phase_seq,
        phase_id=game.phase_id,
        phase_state=game.phase_state,
    )


def _match_state(match: Any) -> MatchStateResponse | None:
    if match is None:
        return None
    return MatchStateResponse(
        round_no=match.round_no,
        sheriff_player_id=match.sheriff_player_id,
        sheriff_badge_state=match.sheriff_badge_state,
        winner=match.winner,
    )
