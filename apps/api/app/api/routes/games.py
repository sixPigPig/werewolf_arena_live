from pathlib import Path as FilePath
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path

from app.core.config import settings
from app.werewolf.replay import ReplayNotFoundError, ReplayStore


router = APIRouter()


def get_replay_store() -> ReplayStore:
    return ReplayStore(FilePath(settings.werewolf_logs_dir))


@router.get("")
def list_games(store: Annotated[ReplayStore, Depends(get_replay_store)]) -> dict:
    return {"sessions": store.list_sessions()}


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
