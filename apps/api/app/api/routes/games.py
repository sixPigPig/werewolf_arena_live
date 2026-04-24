from pathlib import Path as FilePath
import queue
import threading
from typing import Annotated, Iterator

from fastapi import APIRouter, Depends, HTTPException, Path
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.core.config import settings
from app.werewolf.live import EventSink, LiveEvent, LiveRunRegistry, format_sse
from app.werewolf.replay import ReplayNotFoundError, ReplayStore
from app.werewolf.rules import (
    DEFAULT_RULE_SET_ID,
    get_rule_set,
    list_rule_set_summaries,
    rule_set_snapshot,
)
from app.werewolf.runner import GameRunError, new_session_id, run_game


router = APIRouter()
live_registry = LiveRunRegistry()


class CreateGameRunRequest(BaseModel):
    villager_model: str = "deepseek-chat"
    werewolf_model: str = "deepseek-chat"
    seed: int | None = None
    max_rounds: int = Field(default=8, ge=1, le=20)
    rule_set_id: str = DEFAULT_RULE_SET_ID


def get_replay_store() -> ReplayStore:
    return ReplayStore(FilePath(settings.werewolf_logs_dir))


def get_live_registry() -> LiveRunRegistry:
    return live_registry


@router.get("")
def list_games(store: Annotated[ReplayStore, Depends(get_replay_store)]) -> dict:
    return {"sessions": store.list_sessions()}


@router.get("/rule-sets")
def list_rule_sets() -> dict:
    return {"rule_sets": list_rule_set_summaries()}


@router.post("/runs", status_code=201)
def create_game_run(
    request: CreateGameRunRequest,
    registry: Annotated[LiveRunRegistry, Depends(get_live_registry)],
) -> dict:
    try:
        rule_set = get_rule_set(request.rule_set_id)
    except KeyError as exc:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown rule set: {request.rule_set_id}",
        ) from exc
    rule_snapshot = rule_set_snapshot(rule_set)
    session_id = new_session_id()
    run = registry.create_run(
        session_id=session_id,
        villager_model=request.villager_model,
        werewolf_model=request.werewolf_model,
        seed=request.seed,
        max_rounds=request.max_rounds,
        rule_set_id=rule_set.id,
        rule_set=rule_snapshot,
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
) -> StreamingResponse:
    if registry.try_get_run(run_id) is None:
        raise HTTPException(status_code=404, detail="Game run not found")

    return StreamingResponse(
        _event_stream(registry, run_id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache"},
    )


@router.get("/{session_id}")
def get_game(
    session_id: Annotated[
        str,
        Path(pattern=r"^session_\d{8}_\d{6}_[A-Za-z0-9_-]+$"),
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
) -> None:
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
            event_sink=EventSink(registry, run_id),
        )
    except GameRunError as exc:
        registry.mark_failed(run_id, error=str(exc))
        return
    except Exception as exc:
        registry.mark_failed(run_id, error=str(exc))
        return

    registry.mark_completed(run_id, winner=result.winner)


def _event_stream(registry: LiveRunRegistry, run_id: str) -> Iterator[str]:
    last_event_id: int | None = None
    for event in registry.events_after(run_id, after_id=None):
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
