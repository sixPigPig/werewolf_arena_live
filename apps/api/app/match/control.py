from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
import json
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.match.models import (
    GameControlRequest,
    GameRecord,
    GameRecordEvent,
    GameRun,
    MatchState,
    ModelActionRecovery,
)
from app.match.event_contract import canonical_event_payload, model_event_audience
from app.match.execution import database_utc_now
from app.match.runtime_state import project_runtime_state


ACTIVE_GAME_STATES = frozenset(
    {
        "waiting_to_start",
        "ready",
        "generating",
        "broadcasting",
        "finalizing",
        "paused_model_error",
    }
)


class GameControlError(RuntimeError):
    code = "admin_v2_game_control_rejected"


class GameControlNotFound(GameControlError):
    code = "admin_v2_game_not_found"


class GameControlNotActive(GameControlError):
    code = "admin_v2_game_not_active"


class GameStopAlreadyRequested(GameControlError):
    code = "admin_v2_game_stop_already_requested"


class GameModelActionNotPaused(GameControlError):
    code = "admin_v2_model_action_not_paused"


class GameControlIdempotencyConflict(GameControlError):
    code = "admin_idempotency_conflict"


@dataclass(frozen=True)
class GameStopRequestResult:
    control: GameControlRequest
    game: GameRecord
    run: GameRun
    replayed: bool


@dataclass(frozen=True)
class GameModelRetryRequestResult:
    control: GameControlRequest
    game: GameRecord
    run: GameRun
    action_id: str
    replayed: bool


def request_game_stop(
    db: Session,
    *,
    game_id: str,
    actor_user_id: int,
    idempotency_key: str,
    reason: str,
) -> GameStopRequestResult:
    normalized_reason = reason.strip()
    request_hash = _request_hash(
        action="stop",
        game_id=game_id,
        reason=normalized_reason,
    )
    existing = db.scalar(
        select(GameControlRequest).where(
            GameControlRequest.actor_user_id == actor_user_id,
            GameControlRequest.idempotency_key == idempotency_key,
        )
    )
    if existing is not None:
        if existing.request_hash != request_hash:
            raise GameControlIdempotencyConflict
        game = db.get(GameRecord, existing.game_id)
        run = db.get(GameRun, existing.run_id)
        if game is None or run is None:
            raise GameControlNotFound
        return GameStopRequestResult(
            control=existing,
            game=game,
            run=run,
            replayed=True,
        )

    game = db.scalar(select(GameRecord).where(GameRecord.game_id == game_id).with_for_update())
    if game is None:
        raise GameControlNotFound
    run = db.get(GameRun, game.current_run_id)
    if run is None:
        raise GameControlNotFound
    stoppable_incomplete_terminal = False
    if game.status == "awaiting_observation":
        runtime_state = project_runtime_state(
            game=game,
            run=run,
            match=db.get(MatchState, game.game_id),
            now=database_utc_now(db),
        )
        stoppable_incomplete_terminal = runtime_state.match_status == "running"
    if game.status not in ACTIVE_GAME_STATES and not stoppable_incomplete_terminal:
        raise GameControlNotActive
    if run.stop_requested_at is not None:
        raise GameStopAlreadyRequested

    requested_at = datetime.now(tz=UTC)
    run.stop_requested_at = requested_at
    control = GameControlRequest(
        id=str(uuid4()),
        actor_user_id=actor_user_id,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
        action="stop",
        game_id=game.game_id,
        run_id=run.run_id,
    )
    db.add(control)
    next_seq = game.last_record_seq + 1
    db.add(
        GameRecordEvent(
            game_id=game.game_id,
            event_id=next_seq,
            record_seq=next_seq,
            run_id=run.run_id,
            event_type="game_stop_requested",
            payload_schema_version=1,
            payload=canonical_event_payload({
                "source": "admin",
                "reason_code": "operator_interrupted",
            }, audience="god_view"),
        )
    )
    game.last_record_seq = next_seq
    return GameStopRequestResult(
        control=control,
        game=game,
        run=run,
        replayed=False,
    )


def request_model_action_retry(
    db: Session,
    *,
    game_id: str,
    actor_user_id: int,
    idempotency_key: str,
    reason: str,
) -> GameModelRetryRequestResult:
    normalized_reason = reason.strip()
    request_hash = _request_hash(
        action="retry_model_action",
        game_id=game_id,
        reason=normalized_reason,
    )
    existing = db.scalar(
        select(GameControlRequest).where(
            GameControlRequest.actor_user_id == actor_user_id,
            GameControlRequest.idempotency_key == idempotency_key,
        )
    )
    if existing is not None:
        if existing.action != "retry_model_action" or existing.request_hash != request_hash:
            raise GameControlIdempotencyConflict
        game = db.get(GameRecord, existing.game_id)
        run = db.get(GameRun, existing.run_id)
        action_id = _control_model_action_id(db, existing)
        if game is None or run is None or action_id is None:
            raise GameControlNotFound
        return GameModelRetryRequestResult(
            control=existing,
            game=game,
            run=run,
            action_id=action_id,
            replayed=True,
        )

    game = db.scalar(select(GameRecord).where(GameRecord.game_id == game_id).with_for_update())
    if game is None:
        raise GameControlNotFound
    run = db.get(GameRun, game.current_run_id)
    if run is None:
        raise GameControlNotFound
    if (
        game.status != "paused_model_error"
        or run.status != "paused_model_error"
        or run.stop_requested_at is not None
    ):
        raise GameModelActionNotPaused
    paused = db.scalar(
        select(GameRecordEvent)
        .where(
            GameRecordEvent.game_id == game.game_id,
            GameRecordEvent.event_type == "model_action_paused",
        )
        .order_by(GameRecordEvent.record_seq.desc())
        .limit(1)
    )
    action_id = (
        paused.payload.get("action_id")
        if paused is not None and isinstance(paused.payload, dict)
        else None
    )
    if not isinstance(action_id, str):
        raise GameModelActionNotPaused

    control = GameControlRequest(
        id=str(uuid4()),
        actor_user_id=actor_user_id,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
        action="retry_model_action",
        game_id=game.game_id,
        run_id=run.run_id,
    )
    db.add(control)
    recovery = db.get(ModelActionRecovery, action_id)
    if recovery is None or recovery.state != "paused":
        raise GameModelActionNotPaused
    recovery.state = "retry_requested"
    recovery.control_request_id = control.id
    next_seq = game.last_record_seq + 1
    db.add(
        GameRecordEvent(
            game_id=game.game_id,
            event_id=next_seq,
            record_seq=next_seq,
            run_id=run.run_id,
            event_type="model_action_retry_requested",
            payload_schema_version=1,
            payload=canonical_event_payload(
                {
                    "source": "admin",
                    "action_id": action_id,
                    "control_request_id": control.id,
                    "reason_code": "operator_retry",
                    "recovery_id": recovery.recovery_id,
                    "request_hash": recovery.request_hash,
                },
                audience=_model_retry_event_audience(paused, recovery),
            ),
        )
    )
    game.last_record_seq = next_seq
    return GameModelRetryRequestResult(
        control=control,
        game=game,
        run=run,
        action_id=action_id,
        replayed=False,
    )


def _control_model_action_id(
    db: Session,
    control: GameControlRequest,
) -> str | None:
    events = list(
        db.scalars(
            select(GameRecordEvent)
            .where(
                GameRecordEvent.game_id == control.game_id,
                GameRecordEvent.event_type == "model_action_retry_requested",
            )
            .order_by(GameRecordEvent.record_seq.desc())
        )
    )
    for event in events:
        payload = event.payload if isinstance(event.payload, dict) else {}
        if payload.get("control_request_id") == control.id:
            action_id = payload.get("action_id")
            return action_id if isinstance(action_id, str) else None
    return None


def _event_audience(event: GameRecordEvent) -> str:
    payload = event.payload if isinstance(event.payload, dict) else {}
    audience = payload.get("audience")
    if isinstance(audience, str):
        return audience
    # Legacy paused actions predate the event audience contract. Keep the
    # operator recovery path available while failing closed for delivery.
    return "god_view"


def _model_retry_event_audience(
    event: GameRecordEvent,
    recovery: ModelActionRecovery,
) -> str:
    snapshot = recovery.action_snapshot if isinstance(recovery.action_snapshot, dict) else {}
    actor_kind = snapshot.get("actor_kind")
    return model_event_audience(
        action_audience=_event_audience(event),
        actor_kind=actor_kind if isinstance(actor_kind, str) else "unknown",
    )


def _request_hash(*, action: str, game_id: str, reason: str) -> str:
    payload = {
        "action": action,
        "game_id": game_id,
        "reason": reason,
    }
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()
    ).hexdigest()
