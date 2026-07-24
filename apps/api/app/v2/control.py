from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
import json
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.v2.models import (
    V2GameControlRequest,
    V2GameRecord,
    V2GameRecordEvent,
    V2GameRun,
)


ACTIVE_V2_GAME_STATES = frozenset(
    {
        "ready",
        "generating",
        "broadcasting",
        "finalizing",
        "awaiting_observation",
    }
)


class V2GameControlError(RuntimeError):
    code = "admin_v2_game_control_rejected"


class V2GameControlNotFound(V2GameControlError):
    code = "admin_v2_game_not_found"


class V2GameControlNotActive(V2GameControlError):
    code = "admin_v2_game_not_active"


class V2GameStopAlreadyRequested(V2GameControlError):
    code = "admin_v2_game_stop_already_requested"


class V2GameControlIdempotencyConflict(V2GameControlError):
    code = "admin_idempotency_conflict"


@dataclass(frozen=True)
class V2GameStopRequestResult:
    control: V2GameControlRequest
    game: V2GameRecord
    run: V2GameRun
    replayed: bool


def request_v2_game_stop(
    db: Session,
    *,
    game_id: str,
    actor_user_id: int,
    idempotency_key: str,
    reason: str,
) -> V2GameStopRequestResult:
    normalized_reason = reason.strip()
    request_hash = _request_hash(game_id=game_id, reason=normalized_reason)
    existing = db.scalar(
        select(V2GameControlRequest).where(
            V2GameControlRequest.actor_user_id == actor_user_id,
            V2GameControlRequest.idempotency_key == idempotency_key,
        )
    )
    if existing is not None:
        if existing.request_hash != request_hash:
            raise V2GameControlIdempotencyConflict
        game = db.get(V2GameRecord, existing.game_id)
        run = db.get(V2GameRun, existing.run_id)
        if game is None or run is None:
            raise V2GameControlNotFound
        return V2GameStopRequestResult(
            control=existing,
            game=game,
            run=run,
            replayed=True,
        )

    game = db.scalar(
        select(V2GameRecord)
        .where(V2GameRecord.game_id == game_id)
        .with_for_update()
    )
    if game is None:
        raise V2GameControlNotFound
    run = db.get(V2GameRun, game.current_run_id)
    if run is None:
        raise V2GameControlNotFound
    if game.status not in ACTIVE_V2_GAME_STATES:
        raise V2GameControlNotActive
    if run.stop_requested_at is not None:
        raise V2GameStopAlreadyRequested

    requested_at = datetime.now(tz=UTC)
    run.stop_requested_at = requested_at
    control = V2GameControlRequest(
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
        V2GameRecordEvent(
            game_id=game.game_id,
            event_id=next_seq,
            record_seq=next_seq,
            run_id=run.run_id,
            event_type="game_stop_requested",
            payload_schema_version=1,
            payload={
                "source": "admin",
                "reason_code": "operator_interrupted",
            },
        )
    )
    game.last_record_seq = next_seq
    return V2GameStopRequestResult(
        control=control,
        game=game,
        run=run,
        replayed=False,
    )


def _request_hash(*, game_id: str, reason: str) -> str:
    payload = {
        "action": "stop",
        "game_id": game_id,
        "reason": reason,
    }
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()
    ).hexdigest()
