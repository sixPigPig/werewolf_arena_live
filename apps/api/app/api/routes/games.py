from collections.abc import Callable
import queue
import random
import threading
from typing import Annotated, Any, Iterator

from fastapi import APIRouter, Depends, Header, HTTPException, Path, Query, Response, WebSocket
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.exc import OperationalError, ProgrammingError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import SessionLocal, get_db
from app.models.virtual_player_profile import VirtualPlayerProfile
from app.werewolf.checkpoint import ResumeCheckpointError
from app.werewolf.config import choose_player_names
from app.werewolf.debate_realism import lineup_quality_warnings
from app.werewolf.live import EventSink, LiveEvent, LiveGameRun, LiveRunRegistry, format_sse
from app.werewolf.live_store import DatabaseLiveStore
from app.werewolf.player_configs import (
    PlayerConfig,
    clean_optional_string,
    player_config_from_profile,
    player_configs_from_serialized,
    validate_unique_effective_player_names,
)
from app.werewolf.player_presets import is_valid_appearance, is_valid_personality
from app.werewolf.providers import configured_model_options, default_model_name
from app.werewolf.replay import (
    DatabaseReplayStore,
    GameRecordStore,
    ReplayNotFoundError,
    SESSION_ID_RE,
)
from app.werewolf.replay_playback import build_replay_playback
from app.werewolf.rules import (
    DEFAULT_RULE_SET_ID,
    get_rule_set,
    list_rule_set_summaries,
    rule_set_snapshot,
)
from app.werewolf.runner import GameRunError, new_session_id, resume_game, run_game
from app.werewolf.voice import VoiceUtterance
from app.werewolf.voice_stream import LiveVoiceStreamService
from app.werewolf.voice_store import DatabaseVoiceStore
from app.werewolf.volcengine_tts import VolcengineTtsConfig


router = APIRouter()
RecoverableDatabaseError = (OperationalError, ProgrammingError)
PLAYER_PROFILE_DATABASE_UNAVAILABLE = "Player profile database unavailable"


class CreatePlayerConfigRequest(BaseModel):
    seat: int = Field(ge=1)
    profile_id: str | None = Field(default=None, min_length=1)
    name: str | None = Field(default=None, min_length=1, max_length=80)
    display_name: str | None = Field(default=None, min_length=1, max_length=80)
    model: str | None = Field(default=None, min_length=1, max_length=120)
    personality_id: str | None = Field(default=None, min_length=1, max_length=40)
    personality: str | None = None
    personality_text: str | None = None
    appearance_id: str | None = Field(default=None, min_length=1, max_length=40)
    avatar_prompt: str | None = Field(default=None, max_length=500)
    tags: list[str] | None = Field(default=None, max_length=8)


class CreateGameRunRequest(BaseModel):
    villager_model: str = Field(default_factory=default_model_name)
    werewolf_model: str = Field(default_factory=default_model_name)
    seed: int | None = None
    max_rounds: int = Field(default=8, ge=1, le=20)
    rule_set_id: str = DEFAULT_RULE_SET_ID
    player_configs: list[CreatePlayerConfigRequest] = Field(default_factory=list)


def get_replay_store(db: Annotated[Session, Depends(get_db)]) -> DatabaseReplayStore:
    return DatabaseReplayStore(db)


class SessionLiveStore:
    def __init__(self, session_factory: Callable[[], Session] | None = None) -> None:
        self.session_factory = session_factory or SessionLocal

    def save_run(self, run: LiveGameRun) -> None:
        db = self.session_factory()
        try:
            DatabaseLiveStore(db).save_run(run)
        finally:
            db.close()

    def append_event(self, event: LiveEvent) -> None:
        db = self.session_factory()
        try:
            DatabaseLiveStore(db).append_event(event)
        finally:
            db.close()


class SessionVoiceStore:
    def __init__(
        self,
        *,
        session_id: str,
        session_factory: Callable[[], Session] | None = None,
    ) -> None:
        self.session_id = session_id
        self.session_factory = session_factory or SessionLocal

    def upsert_utterance(
        self,
        utterance: VoiceUtterance,
        *,
        audio_format: str,
        sample_rate: int,
        mime_type: str,
        status: str = "synthesizing",
    ) -> None:
        db = self.session_factory()
        try:
            DatabaseVoiceStore(db, session_id=self.session_id).upsert_utterance(
                utterance,
                audio_format=audio_format,
                sample_rate=sample_rate,
                mime_type=mime_type,
                status=status,
            )
        finally:
            db.close()

    def append_chunk(self, utterance_id: str, *, chunk_index: int, audio: bytes) -> None:
        db = self.session_factory()
        try:
            DatabaseVoiceStore(db, session_id=self.session_id).append_chunk(
                utterance_id,
                chunk_index=chunk_index,
                audio=audio,
            )
        finally:
            db.close()

    def complete_utterance(self, utterance_id: str, *, duration_ms: int) -> None:
        db = self.session_factory()
        try:
            DatabaseVoiceStore(db, session_id=self.session_id).complete_utterance(
                utterance_id,
                duration_ms=duration_ms,
            )
        finally:
            db.close()

    def fail_utterance(self, utterance_id: str, *, message: str) -> None:
        db = self.session_factory()
        try:
            DatabaseVoiceStore(db, session_id=self.session_id).fail_utterance(
                utterance_id,
                message=message,
            )
        finally:
            db.close()

    def find_recent_utterance(
        self,
        *,
        run_id: str,
        current_event_id: int,
    ) -> dict[str, Any] | None:
        db = self.session_factory()
        try:
            return DatabaseVoiceStore(db, session_id=self.session_id).find_recent_utterance(
                run_id=run_id,
                current_event_id=current_event_id,
            )
        finally:
            db.close()

    def load_chunks(self, utterance_id: str) -> list[bytes]:
        db = self.session_factory()
        try:
            return DatabaseVoiceStore(db, session_id=self.session_id).load_chunks(utterance_id)
        finally:
            db.close()


live_registry = LiveRunRegistry(live_store=SessionLiveStore())


def get_live_registry() -> LiveRunRegistry:
    return live_registry


def get_tts_config() -> VolcengineTtsConfig:
    return VolcengineTtsConfig(
        enabled=settings.ark_tts_enabled,
        api_key=settings.ark_tts_api_key,
        resource_id=settings.ark_tts_resource_id,
        ws_url=settings.ark_tts_ws_url,
        player_speaker=settings.ark_tts_player_speaker,
        judge_speaker=settings.ark_tts_judge_speaker,
        audio_format=settings.ark_tts_audio_format,
        sample_rate=settings.ark_tts_sample_rate,
    )


def get_voice_streamer(
    registry: Annotated[LiveRunRegistry, Depends(get_live_registry)],
    config: Annotated[VolcengineTtsConfig, Depends(get_tts_config)],
) -> LiveVoiceStreamService:
    return LiveVoiceStreamService(
        registry=registry,
        config=config,
        voice_store_factory=lambda session_id: SessionVoiceStore(session_id=session_id),
    )


def normalize_player_config_requests(
    requests: list[CreatePlayerConfigRequest],
    player_count: int,
    db: Session,
) -> list[PlayerConfig]:
    if len(requests) > player_count:
        raise HTTPException(status_code=422, detail="Too many player configs")

    seen_seats: set[int] = set()
    configs: list[PlayerConfig] = []
    for request in requests:
        if request.seat > player_count:
            raise HTTPException(
                status_code=422,
                detail=f"Player config seat out of range: {request.seat}",
            )
        if request.seat in seen_seats:
            raise HTTPException(
                status_code=422,
                detail=f"Duplicate player config seat: {request.seat}",
            )
        seen_seats.add(request.seat)

        profile_id = clean_optional_string(request.profile_id)
        profile = None
        if profile_id is not None:
            try:
                profile = db.get(VirtualPlayerProfile, profile_id)
            except RecoverableDatabaseError as exc:
                raise _profile_database_unavailable() from exc
            if profile is None:
                raise HTTPException(status_code=422, detail=f"Unknown player profile: {profile_id}")

        personality_id = (
            clean_optional_string(request.personality_id)
            or clean_optional_string(getattr(profile, "personality_id", None))
            or "balanced"
        )
        appearance_id = (
            clean_optional_string(request.appearance_id)
            or clean_optional_string(getattr(profile, "appearance_id", None))
            or "default"
        )
        if not is_valid_personality(personality_id):
            raise HTTPException(status_code=422, detail=f"Unknown personality_id: {personality_id}")
        if not is_valid_appearance(appearance_id):
            raise HTTPException(status_code=422, detail=f"Unknown appearance_id: {appearance_id}")

        overrides = request.model_dump(exclude_unset=True)
        if profile_id is not None:
            overrides["profile_id"] = profile_id
        configs.append(
            player_config_from_profile(
                seat=request.seat,
                profile=profile,
                overrides=overrides,
            )
        )

    return configs


def complete_player_configs_from_library(
    *,
    requests: list[CreatePlayerConfigRequest],
    player_count: int,
    seed: int | None,
    db: Session,
) -> list[PlayerConfig]:
    configs = normalize_player_config_requests(
        requests,
        player_count,
        db,
    )
    configs_by_seat = {config.seat: config for config in configs}
    missing_profile_seats = [
        seat
        for seat in range(1, player_count + 1)
        if not configs_by_seat.get(seat) or not configs_by_seat[seat].profile_id
    ]
    if not missing_profile_seats:
        return sorted(configs, key=lambda config: config.seat)

    used_profile_ids = {config.profile_id for config in configs if config.profile_id is not None}
    available_profiles = [
        profile
        for profile in list_available_player_profiles(db)
        if clean_optional_string(getattr(profile, "id", None)) not in used_profile_ids
    ]
    available_count = len(used_profile_ids) + len(available_profiles)
    if len(available_profiles) < len(missing_profile_seats):
        raise HTTPException(
            status_code=422,
            detail=(
                f"Player profile library has {available_count} available players, "
                f"but {player_count} seats require virtual players"
            ),
        )

    rng = random.Random(f"{seed}:player-profiles") if seed is not None else random.Random()
    selected_profiles = rng.sample(available_profiles, len(missing_profile_seats))
    next_configs = list(configs)
    for seat, profile in zip(missing_profile_seats, selected_profiles, strict=True):
        existing = configs_by_seat.get(seat)
        overrides = existing.to_dict() if existing is not None else {"seat": seat}
        if existing is not None and existing.profile_id is None:
            overrides.pop("name", None)
        overrides["profile_id"] = str(getattr(profile, "id"))
        next_config = player_config_from_profile(
            seat=seat,
            profile=profile,
            overrides=overrides,
        )
        next_configs = [config for config in next_configs if config.seat != seat] + [next_config]

    return sorted(next_configs, key=lambda config: config.seat)


def list_available_player_profiles(
    db: Session,
) -> list[object]:
    try:
        return list(
            db.query(VirtualPlayerProfile)
            .order_by(VirtualPlayerProfile.display_order.asc(), VirtualPlayerProfile.id.asc())
            .all()
        )
    except RecoverableDatabaseError as exc:
        raise _profile_database_unavailable() from exc


@router.get("")
def list_games(store: Annotated[GameRecordStore, Depends(get_replay_store)]) -> dict:
    return {"sessions": store.list_sessions()}


@router.get("/rule-sets")
def list_rule_sets() -> dict:
    return {"rule_sets": list_rule_set_summaries()}


@router.get("/model-options")
def list_model_options() -> dict:
    return {"models": configured_model_options()}


@router.post("/runs", status_code=201)
def create_game_run(
    request: CreateGameRunRequest,
    registry: Annotated[LiveRunRegistry, Depends(get_live_registry)],
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    try:
        rule_set = get_rule_set(request.rule_set_id)
    except KeyError as exc:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown rule set: {request.rule_set_id}",
        ) from exc
    rule_snapshot = rule_set_snapshot(rule_set)
    player_configs = complete_player_configs_from_library(
        requests=request.player_configs,
        player_count=rule_set.player_count,
        seed=request.seed,
        db=db,
    )
    try:
        validate_unique_effective_player_names(
            default_names=choose_player_names(request.seed, player_count=rule_set.player_count),
            player_configs=player_configs,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    lineup_warnings = lineup_quality_warnings(player_configs)
    session_id = new_session_id()
    run = registry.create_run(
        session_id=session_id,
        villager_model=request.villager_model,
        werewolf_model=request.werewolf_model,
        seed=request.seed,
        max_rounds=request.max_rounds,
        rule_set_id=rule_set.id,
        rule_set=rule_snapshot,
        player_configs=player_configs,
        lineup_quality_warnings=lineup_warnings,
    )
    thread = threading.Thread(
        target=_run_game_in_background,
        kwargs={
            "run_id": run.run_id,
            "registry": registry,
            "session_id": session_id,
            "villager_model": request.villager_model,
            "werewolf_model": request.werewolf_model,
            "seed": request.seed,
            "max_rounds": request.max_rounds,
            "rule_set_id": rule_set.id,
            "player_configs": player_configs,
        },
        daemon=True,
    )
    thread.start()
    return registry.get_run(run.run_id).to_summary()


def _profile_database_unavailable() -> HTTPException:
    return HTTPException(status_code=503, detail=PLAYER_PROFILE_DATABASE_UNAVAILABLE)


@router.get("/runs/{run_id}")
def get_game_run(
    run_id: str,
    registry: Annotated[LiveRunRegistry, Depends(get_live_registry)],
) -> dict:
    run = registry.try_get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Game run not found")
    return run.to_summary()


@router.get("/runs/{run_id}/events")
def stream_game_run_events(
    run_id: str,
    registry: Annotated[LiveRunRegistry, Depends(get_live_registry)],
    after_id: Annotated[int | None, Query(ge=0)] = None,
    last_event_id: Annotated[str | None, Header(alias="Last-Event-ID")] = None,
) -> StreamingResponse:
    if registry.try_get_run(run_id) is None:
        raise HTTPException(status_code=404, detail="Game run not found")

    return StreamingResponse(
        _event_stream(
            registry,
            run_id,
            after_id=_resolve_event_resume_id(after_id, last_event_id),
        ),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache"},
    )


@router.websocket("/runs/{run_id}/voice-stream")
async def stream_game_run_voice(
    websocket: WebSocket,
    run_id: str,
    registry: Annotated[LiveRunRegistry, Depends(get_live_registry)],
    streamer: Annotated[LiveVoiceStreamService, Depends(get_voice_streamer)],
    current_event_id: Annotated[int | None, Query(ge=0)] = None,
) -> None:
    await websocket.accept()
    if registry.try_get_run(run_id) is None:
        await websocket.send_json(
            {
                "type": "voice_unavailable",
                "reason": "run_not_found",
                "message": "对局不存在或已失效，请返回大厅重新开始。",
            }
        )
        await websocket.close()
        return
    await streamer.stream_run(run_id, websocket, current_event_id=current_event_id)


@router.post("/{session_id}/resume", status_code=201)
def resume_game_run(
    session_id: Annotated[
        str,
        Path(pattern=SESSION_ID_RE),
    ],
    store: Annotated[GameRecordStore, Depends(get_replay_store)],
    registry: Annotated[LiveRunRegistry, Depends(get_live_registry)],
    response: Response,
) -> dict:
    active_run = registry.try_get_active_run_for_session(session_id)
    if active_run is not None:
        response.status_code = 200
        return active_run.to_summary()

    try:
        checkpoint = store.load_resume_checkpoint(session_id)
    except ResumeCheckpointError as exc:
        raise HTTPException(status_code=404, detail="Resume checkpoint not found") from exc

    run_params = checkpoint.get("run_params", {})
    if not isinstance(run_params, dict):
        raise HTTPException(status_code=422, detail="Resume checkpoint is invalid")

    rule_set_id = str(run_params.get("rule_set_id") or DEFAULT_RULE_SET_ID)
    try:
        rule_set = get_rule_set(rule_set_id)
    except KeyError as exc:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown rule set: {rule_set_id}",
        ) from exc

    max_rounds = int(run_params.get("max_rounds") or 8)
    seed = run_params.get("seed")
    try:
        checkpoint_player_configs = player_configs_from_serialized(run_params.get("player_configs"))
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail="Resume checkpoint is invalid") from exc
    run, created = registry.get_or_create_active_run(
        session_id=session_id,
        villager_model=str(run_params.get("villager_model") or default_model_name()),
        werewolf_model=str(run_params.get("werewolf_model") or default_model_name()),
        seed=seed if isinstance(seed, int) else None,
        max_rounds=max_rounds,
        rule_set_id=rule_set.id,
        rule_set=rule_set_snapshot(rule_set),
        player_configs=checkpoint_player_configs,
    )
    if not created:
        response.status_code = 200
        return run.to_summary()
    thread = threading.Thread(
        target=_resume_game_in_background,
        kwargs={
            "run_id": run.run_id,
            "registry": registry,
            "session_id": session_id,
        },
        daemon=True,
    )
    thread.start()
    return registry.get_run(run.run_id).to_summary()


@router.get("/{session_id}/playback")
def get_game_playback(
    session_id: Annotated[
        str,
        Path(pattern=SESSION_ID_RE),
    ],
    store: Annotated[GameRecordStore, Depends(get_replay_store)],
) -> dict:
    try:
        return build_replay_playback(store.load_session(session_id))
    except ReplayNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Game session not found") from exc


@router.get("/{session_id}")
def get_game(
    session_id: Annotated[
        str,
        Path(pattern=SESSION_ID_RE),
    ],
    store: Annotated[GameRecordStore, Depends(get_replay_store)],
) -> dict:
    try:
        return store.load_session(session_id)
    except ReplayNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Game session not found") from exc


def _run_game_in_background(
    *,
    run_id: str,
    registry: LiveRunRegistry,
    session_id: str,
    villager_model: str,
    werewolf_model: str,
    seed: int | None,
    max_rounds: int,
    rule_set_id: str,
    player_configs: list[PlayerConfig] | None = None,
) -> None:
    registry.mark_running(run_id)
    db = SessionLocal()
    try:
        result = run_game(
            record_store=DatabaseReplayStore(db),
            villager_model=villager_model,
            werewolf_model=werewolf_model,
            seed=seed,
            rule_set_id=rule_set_id,
            max_rounds=max_rounds,
            session_id=session_id,
            event_sink=EventSink(registry, run_id),
            player_configs=player_configs,
        )
    except GameRunError as exc:
        registry.mark_failed(run_id, error=str(exc))
        return
    except Exception as exc:
        registry.mark_failed(run_id, error=str(exc))
        return
    finally:
        db.close()

    registry.mark_completed(run_id, winner=result.winner)


def _resume_game_in_background(
    *,
    run_id: str,
    registry: LiveRunRegistry,
    session_id: str,
) -> None:
    registry.mark_running(run_id)
    db = SessionLocal()
    try:
        result = resume_game(
            session_id=session_id,
            record_store=DatabaseReplayStore(db),
            event_sink=EventSink(registry, run_id),
        )
    except GameRunError as exc:
        registry.mark_failed(run_id, error=str(exc))
        return
    except Exception as exc:
        registry.mark_failed(run_id, error=str(exc))
        return
    finally:
        db.close()

    registry.mark_completed(run_id, winner=result.winner)


def _event_stream(
    registry: LiveRunRegistry,
    run_id: str,
    *,
    after_id: int | None = None,
) -> Iterator[str]:
    last_event_id = after_id
    for event in registry.events_after(run_id, after_id=after_id):
        last_event_id = event.id
        yield format_sse(event)
        if _is_terminal_event(event):
            return

    subscriber: queue.Queue[LiveEvent] | None = None
    try:
        subscriber = registry.subscribe(run_id, after_id=last_event_id)
        while True:
            try:
                event = subscriber.get(timeout=15)
            except queue.Empty:
                yield ": heartbeat\n\n"
                continue

            yield format_sse(event)
            if _is_terminal_event(event):
                return
    finally:
        if subscriber is not None:
            registry.unsubscribe(run_id, subscriber)


def _is_terminal_event(event: LiveEvent) -> bool:
    return event.type in {"game_completed", "game_failed"}


def _resolve_event_resume_id(
    after_id: int | None,
    last_event_id: str | None,
) -> int | None:
    if after_id is not None:
        return after_id
    if last_event_id is None:
        return None
    try:
        return int(last_event_id)
    except ValueError:
        return None
