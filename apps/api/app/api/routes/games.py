from pathlib import Path as FilePath
import queue
import threading
from typing import Annotated, Any, Iterator

from fastapi import APIRouter, Depends, Header, HTTPException, Path, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.exc import OperationalError, ProgrammingError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import get_db
from app.models.virtual_player_profile import VirtualPlayerProfile
from app.werewolf.live import EventSink, LiveEvent, LiveRunRegistry, format_sse
from app.werewolf.pacing import EventPacer, EventPacingMode
from app.werewolf.player_configs import (
    PlayerConfig,
    clean_optional_string,
    player_config_from_profile,
    player_configs_from_serialized,
    validate_unique_effective_player_names,
)
from app.werewolf.player_profile_store import (
    PlayerProfileFileStore,
    player_profile_store_for_logs_dir,
)
from app.werewolf.player_presets import is_valid_appearance, is_valid_personality
from app.werewolf.providers import configured_model_options, default_model_name
from app.werewolf.config import choose_player_names
from app.werewolf.checkpoint import ResumeCheckpointError, load_resume_checkpoint
from app.werewolf.replay import ReplayNotFoundError, ReplayStore, SESSION_ID_RE
from app.werewolf.rules import (
    DEFAULT_RULE_SET_ID,
    get_rule_set,
    list_rule_set_summaries,
    rule_set_snapshot,
)
from app.werewolf.runner import GameRunError, new_session_id, resume_game, run_game


router = APIRouter()
live_registry = LiveRunRegistry()
RecoverableDatabaseError = (OperationalError, ProgrammingError)


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
    event_pacing: EventPacingMode = "off"
    player_configs: list[CreatePlayerConfigRequest] = Field(default_factory=list)


def get_replay_store() -> ReplayStore:
    return ReplayStore(FilePath(settings.werewolf_logs_dir))


def get_live_registry() -> LiveRunRegistry:
    return live_registry


def get_player_profile_store() -> PlayerProfileFileStore:
    return player_profile_store_for_logs_dir(settings.werewolf_logs_dir)


def normalize_player_config_requests(
    requests: list[CreatePlayerConfigRequest],
    player_count: int,
    db: Session,
    profile_store: PlayerProfileFileStore,
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
            except RecoverableDatabaseError:
                profile = profile_store.get_profile(profile_id)
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


@router.get("")
def list_games(store: Annotated[ReplayStore, Depends(get_replay_store)]) -> dict:
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
    profile_store: Annotated[PlayerProfileFileStore, Depends(get_player_profile_store)],
) -> dict:
    try:
        rule_set = get_rule_set(request.rule_set_id)
    except KeyError as exc:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown rule set: {request.rule_set_id}",
        ) from exc
    rule_snapshot = rule_set_snapshot(rule_set)
    player_configs = normalize_player_config_requests(
        request.player_configs,
        rule_set.player_count,
        db,
        profile_store,
    )
    try:
        validate_unique_effective_player_names(
            default_names=choose_player_names(request.seed, player_count=rule_set.player_count),
            player_configs=player_configs,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
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
        event_pacing=request.event_pacing,
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
            "event_pacing": request.event_pacing,
            "player_configs": player_configs,
        },
        daemon=True,
    )
    thread.start()
    return registry.get_run(run.run_id).to_summary()


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


@router.post("/{session_id}/resume", status_code=201)
def resume_game_run(
    session_id: Annotated[
        str,
        Path(pattern=SESSION_ID_RE),
    ],
    store: Annotated[ReplayStore, Depends(get_replay_store)],
    registry: Annotated[LiveRunRegistry, Depends(get_live_registry)],
) -> dict:
    checkpoint_directory = store.logs_root / session_id
    try:
        checkpoint = load_resume_checkpoint(checkpoint_directory)
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
        checkpoint_player_configs = player_configs_from_serialized(
            run_params.get("player_configs")
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail="Resume checkpoint is invalid") from exc
    run = registry.create_run(
        session_id=session_id,
        villager_model=str(run_params.get("villager_model") or default_model_name()),
        werewolf_model=str(run_params.get("werewolf_model") or default_model_name()),
        seed=seed if isinstance(seed, int) else None,
        max_rounds=max_rounds,
        rule_set_id=rule_set.id,
        rule_set=rule_set_snapshot(rule_set),
        player_configs=checkpoint_player_configs,
        event_pacing="off",
    )
    thread = threading.Thread(
        target=_resume_game_in_background,
        kwargs={
            "run_id": run.run_id,
            "registry": registry,
            "session_id": session_id,
            "logs_dir": store.logs_root,
            "event_pacing": "off",
        },
        daemon=True,
    )
    thread.start()
    return registry.get_run(run.run_id).to_summary()


@router.get("/{session_id}")
def get_game(
    session_id: Annotated[
        str,
        Path(pattern=SESSION_ID_RE),
    ],
    store: Annotated[ReplayStore, Depends(get_replay_store)],
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
    event_pacing: EventPacingMode,
    player_configs: list[PlayerConfig] | None = None,
) -> None:
    pacer = EventPacer(event_pacing)
    pacer.wait("run_started")
    registry.mark_running(run_id)
    try:
        result = run_game(
            villager_model=villager_model,
            werewolf_model=werewolf_model,
            seed=seed,
            rule_set_id=rule_set_id,
            logs_dir=settings.werewolf_logs_dir,
            max_rounds=max_rounds,
            session_id=session_id,
            event_sink=PacedEventSink(EventSink(registry, run_id), pacer),
            player_configs=player_configs,
        )
    except GameRunError as exc:
        pacer.wait("game_failed")
        registry.mark_failed(run_id, error=str(exc))
        return
    except Exception as exc:
        pacer.wait("game_failed")
        registry.mark_failed(run_id, error=str(exc))
        return

    pacer.wait("game_completed")
    registry.mark_completed(run_id, winner=result.winner)


def _resume_game_in_background(
    *,
    run_id: str,
    registry: LiveRunRegistry,
    session_id: str,
    logs_dir: FilePath,
    event_pacing: EventPacingMode,
) -> None:
    pacer = EventPacer(event_pacing)
    pacer.wait("run_started")
    registry.mark_running(run_id)
    try:
        result = resume_game(
            session_id=session_id,
            logs_dir=logs_dir,
            event_sink=PacedEventSink(EventSink(registry, run_id), pacer),
        )
    except GameRunError as exc:
        pacer.wait("game_failed")
        registry.mark_failed(run_id, error=str(exc))
        return
    except Exception as exc:
        pacer.wait("game_failed")
        registry.mark_failed(run_id, error=str(exc))
        return

    pacer.wait("game_completed")
    registry.mark_completed(run_id, winner=result.winner)


class PacedEventSink:
    def __init__(self, delegate: EventSink, pacer: EventPacer) -> None:
        self._delegate = delegate
        self._pacer = pacer

    def publish(
        self,
        event_type: str,
        *,
        round_number: int | None = None,
        phase: str | None = None,
        actor: str | None = None,
        action: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> LiveEvent:
        self._pacer.wait(event_type)
        return self._delegate.publish(
            event_type,
            round_number=round_number,
            phase=phase,
            actor=actor,
            action=action,
            payload=payload,
        )


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
