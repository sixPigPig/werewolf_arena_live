from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from sqlalchemy import exists, select
from sqlalchemy.orm import object_session

from app.match.models import (
    GameRecord,
    GameRecordEvent,
    GameRun,
    MatchState,
)


AudioMode = Literal["tts", "text_only", "legacy_unknown"]
MatchStatus = Literal["waiting", "running", "completed", "failed", "canceled"]
ExecutionState = Literal["unowned", "owned", "stale", "stopped"]


@dataclass(frozen=True)
class RuntimeStateProjection:
    audio_mode: AudioMode
    match_status: MatchStatus
    execution_state: ExecutionState
    winner: Literal["villagers", "werewolves"] | None
    completion_reason: str | None
    completed_at: datetime | None


def delivery_audio_mode(snapshot: object) -> AudioMode:
    if not isinstance(snapshot, dict):
        return "legacy_unknown"
    mode = snapshot.get("mode")
    if mode in {"tts", "text_only", "legacy_unknown"}:
        return mode
    return "legacy_unknown"


def project_runtime_state(
    *,
    game: GameRecord,
    run: GameRun,
    match: MatchState | None,
    now: datetime,
    completion_event_present: bool | None = None,
) -> RuntimeStateProjection:
    winner = match.winner if match is not None else None
    if winner not in {"villagers", "werewolves"}:
        winner = None
    completion_reason = match.completion_reason if match is not None else None
    completed = (
        game.phase_state == "game_completed"
        and winner is not None
        and completion_reason is not None
        and run.completed_at is not None
        and run.run_id == game.current_run_id
        and (
            completion_event_present
            if completion_event_present is not None
            else _has_durable_completion_event(game=game, run=run)
        )
    )
    if completed:
        match_status: MatchStatus = "completed"
    elif game.status == "canceled" or run.status == "canceled":
        match_status = "canceled"
    elif game.phase_state == "failed" or game.status == "failed" or run.status == "failed":
        match_status = "failed"
    elif game.status == "waiting_to_start" and run.status == "waiting_to_start":
        match_status = "waiting"
    else:
        match_status = "running"

    owner_field_presence = (
        run.worker_id is not None,
        run.worker_heartbeat_at is not None,
        run.lease_expires_at is not None,
    )
    owner_fields_inconsistent = (
        any(owner_field_presence) and not all(owner_field_presence)
    ) or (all(owner_field_presence) and run.fence_token < 1)
    if owner_fields_inconsistent:
        execution_state: ExecutionState = "stale"
    elif run.worker_id is not None and run.lease_expires_at is not None:
        execution_state = (
            "owned" if _as_utc(run.lease_expires_at) > _as_utc(now) else "stale"
        )
    elif game.status in {"awaiting_observation", "canceled", "failed"}:
        execution_state = "stopped"
    else:
        execution_state = "unowned"

    return RuntimeStateProjection(
        audio_mode=delivery_audio_mode(game.delivery_snapshot),
        match_status=match_status,
        execution_state=execution_state,
        winner=winner,
        completion_reason=completion_reason,
        completed_at=run.completed_at,
    )


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _has_durable_completion_event(*, game: GameRecord, run: GameRun) -> bool:
    session = object_session(game)
    if session is None:
        return False
    return bool(
        session.scalar(
            select(
                exists().where(
                    GameRecordEvent.game_id == game.game_id,
                    GameRecordEvent.run_id == run.run_id,
                    GameRecordEvent.event_type == "game_completed",
                )
            )
        )
    )
