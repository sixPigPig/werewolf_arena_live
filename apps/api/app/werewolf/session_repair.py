from __future__ import annotations

import argparse
import copy
import json
from typing import Any

from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.models.game_session import GameReplayPayload
from app.werewolf.checkpoint import valid_cached_model_responses
from app.werewolf.projection_backfill import rebuild_live_event_projections


def repair_resume_session(
    db: Session,
    *,
    session_id: str,
    apply: bool,
) -> dict[str, Any]:
    payload = db.get(GameReplayPayload, session_id)
    if payload is None or not isinstance(payload.checkpoint, dict):
        raise ValueError("Resume checkpoint not found")

    checkpoint = copy.deepcopy(payload.checkpoint)
    cached = checkpoint.get("cached_model_responses")
    cached_count = len(cached) if isinstance(cached, list) else 0
    valid_cached = valid_cached_model_responses(cached)
    removed_count = cached_count - len(valid_cached)

    logs = checkpoint.get("logs_before_round")
    log_rounds = sorted(
        {
            number
            for entry in logs if isinstance(logs, list) and isinstance(entry, dict)
            if isinstance((number := entry.get("number")), int)
        }
    ) if isinstance(logs, list) else []
    state = checkpoint.get("state_at_round_start")
    rounds = state.get("rounds") if isinstance(state, dict) else []
    state_rounds = sorted(
        {
            number
            for entry in rounds if isinstance(rounds, list) and isinstance(entry, dict)
            if isinstance((number := entry.get("number")), int)
        }
    ) if isinstance(rounds, list) else []

    missing_log_rounds = sorted(set(state_rounds) - set(log_rounds))
    if apply and (removed_count or missing_log_rounds):
        checkpoint["cached_model_responses"] = valid_cached
        existing_logs = [
            copy.deepcopy(entry)
            for entry in logs
            if isinstance(logs, list) and isinstance(entry, dict)
        ]
        checkpoint["logs_before_round"] = sorted(
            [*existing_logs, *({"number": number} for number in missing_log_rounds)],
            key=lambda entry: int(entry["number"]),
        )
        payload.checkpoint = checkpoint
        db.flush()

    projection_counts = rebuild_live_event_projections(
        db,
        apply=apply,
        session_id=session_id,
        limit=10_000,
    )
    return {
        "session_id": session_id,
        "mode": "apply" if apply else "dry-run",
        "cached_responses": {
            "scanned": cached_count,
            "kept": len(valid_cached),
            "removed": removed_count,
        },
        "checkpoint_rounds": {
            "state": state_rounds,
            "logs": log_rounds,
            "missing_from_logs": missing_log_rounds,
            "placeholders_added": len(missing_log_rounds) if apply else 0,
        },
        "projections": projection_counts,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Repair one resumable session without printing private model content."
    )
    parser.add_argument("--session-id", required=True)
    parser.add_argument("--apply", action="store_true", help="write changes; default is dry-run")
    args = parser.parse_args()

    with SessionLocal() as db:
        result = repair_resume_session(
            db,
            session_id=args.session_id,
            apply=args.apply,
        )
        if args.apply:
            db.commit()
        else:
            db.rollback()
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
