from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.game_session import GameReplayPayload
from app.models.live import LiveEventRecord, LiveRunRecord


_MODEL_EVENT_TYPES = (
    "model_request_started",
    "model_response_received",
    "model_request_failed",
)
_REQUEST_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,79}")
_MAX_REQUESTS = 1000
_MAX_PROMPT_LENGTH = 200_000
_MAX_RESPONSE_LENGTH = 200_000
_MAX_ERROR_LENGTH = 4_000


@dataclass(frozen=True)
class AdminGameModelRequestRecord:
    sequence: int
    request_id: str
    round_number: int | None
    phase: str | None
    actor: str | None
    action: str
    model: str | None
    status: str
    attempt_count: int
    invalid_attempt_count: int
    run_id: str | None
    event_id: int | None
    created_at: datetime | None
    prompt: str | None
    raw_response: str | None
    parsed_output: str | None
    raw_choice: str | None
    error: str | None


def load_admin_game_model_requests(
    db: Session,
    *,
    session_id: str,
) -> list[AdminGameModelRequestRecord] | None:
    replay = db.execute(
        select(GameReplayPayload.state, GameReplayPayload.logs).where(
            GameReplayPayload.session_id == session_id
        )
    ).one_or_none()
    if replay is None:
        return None
    state = replay.state if isinstance(replay.state, dict) else {}
    logs = replay.logs if isinstance(replay.logs, list) else []
    player_models = {
        name: model
        for item in state.get("players", [])
        if isinstance(item, dict)
        if (name := _optional_text(item.get("name"), max_length=120)) is not None
        if (model := _optional_text(item.get("model"), max_length=120)) is not None
    }
    event_metadata = _model_event_metadata(db, session_id=session_id)
    requests: dict[str, AdminGameModelRequestRecord] = {}
    sequence = 0

    def visit(value: object, *, round_number: int | None = None) -> None:
        nonlocal sequence
        if isinstance(value, list):
            for child in value:
                visit(child, round_number=round_number)
            return
        if not isinstance(value, dict):
            return
        local_round = _optional_non_negative_int(value.get("number"))
        if local_round is None:
            local_round = round_number
        lm_log = value.get("lm_log")
        if isinstance(lm_log, dict):
            request_id = _request_id(lm_log.get("request_id"))
            if request_id is not None and request_id not in requests:
                metadata = event_metadata.get(request_id, {})
                actor = _first_text(value.get("actor"), metadata.get("actor"), max_length=120)
                raw_response = _optional_content(
                    lm_log.get("raw_response"),
                    max_length=_MAX_RESPONSE_LENGTH,
                )
                parsed_output = _json_text(
                    lm_log.get("result", lm_log.get("parsed")),
                    max_length=_MAX_RESPONSE_LENGTH,
                )
                status = str(metadata.get("status") or "response_missing")
                if raw_response is not None or parsed_output is not None:
                    status = "completed"
                requests[request_id] = AdminGameModelRequestRecord(
                    sequence=sequence,
                    request_id=request_id,
                    round_number=(
                        local_round
                        if local_round is not None
                        else _optional_non_negative_int(metadata.get("round_number"))
                    ),
                    phase=_optional_text(metadata.get("phase"), max_length=40),
                    actor=actor,
                    action=(
                        _first_text(
                            value.get("action"),
                            metadata.get("action"),
                            max_length=80,
                        )
                        or "unknown"
                    ),
                    model=_first_text(
                        value.get("model"),
                        lm_log.get("model"),
                        metadata.get("model"),
                        player_models.get(actor or ""),
                        max_length=120,
                    ),
                    status=status,
                    attempt_count=_non_negative_int(value.get("attempt_count"), default=1),
                    invalid_attempt_count=_invalid_attempt_count(lm_log),
                    run_id=_optional_text(metadata.get("run_id"), max_length=32),
                    event_id=_optional_non_negative_int(metadata.get("event_id")),
                    created_at=(
                        metadata.get("created_at")
                        if isinstance(metadata.get("created_at"), datetime)
                        else None
                    ),
                    prompt=_optional_content(
                        lm_log.get("prompt"),
                        max_length=_MAX_PROMPT_LENGTH,
                    ),
                    raw_response=raw_response,
                    parsed_output=parsed_output,
                    raw_choice=_json_text(
                        lm_log.get("raw_choice", value.get("raw_choice")),
                        max_length=_MAX_RESPONSE_LENGTH,
                    ),
                    error=_optional_text(
                        metadata.get("error"),
                        max_length=_MAX_ERROR_LENGTH,
                    ),
                )
                sequence += 1
        for key, child in value.items():
            if key != "lm_log":
                visit(child, round_number=local_round)

    visit(logs)
    for request_id, metadata in event_metadata.items():
        if request_id in requests or len(requests) >= _MAX_REQUESTS:
            continue
        actor = _optional_text(metadata.get("actor"), max_length=120)
        requests[request_id] = AdminGameModelRequestRecord(
            sequence=sequence,
            request_id=request_id,
            round_number=_optional_non_negative_int(metadata.get("round_number")),
            phase=_optional_text(metadata.get("phase"), max_length=40),
            actor=actor,
            action=_optional_text(metadata.get("action"), max_length=80) or "unknown",
            model=_first_text(
                metadata.get("model"),
                player_models.get(actor or ""),
                max_length=120,
            ),
            status=str(metadata.get("status") or "response_missing"),
            attempt_count=1,
            invalid_attempt_count=0,
            run_id=_optional_text(metadata.get("run_id"), max_length=32),
            event_id=_optional_non_negative_int(metadata.get("event_id")),
            created_at=(
                metadata.get("created_at")
                if isinstance(metadata.get("created_at"), datetime)
                else None
            ),
            prompt=None,
            raw_response=None,
            parsed_output=None,
            raw_choice=None,
            error=_optional_text(metadata.get("error"), max_length=_MAX_ERROR_LENGTH),
        )
        sequence += 1
    return sorted(
        requests.values(),
        key=lambda item: (
            item.round_number if item.round_number is not None else 10_000,
            item.event_id if item.event_id is not None else 1_000_000 + item.sequence,
            item.sequence,
        ),
    )[:_MAX_REQUESTS]


def _model_event_metadata(db: Session, *, session_id: str) -> dict[str, dict[str, Any]]:
    metadata: dict[str, dict[str, Any]] = {}
    rows = db.execute(
        select(
            LiveEventRecord.run_id,
            LiveEventRecord.event_id,
            LiveEventRecord.type,
            LiveEventRecord.round,
            LiveEventRecord.phase,
            LiveEventRecord.actor,
            LiveEventRecord.action,
            LiveEventRecord.payload,
            LiveEventRecord.created_at,
            LiveRunRecord.status,
        )
        .join(LiveRunRecord, LiveRunRecord.run_id == LiveEventRecord.run_id)
        .where(
            LiveEventRecord.session_id == session_id,
            LiveEventRecord.type.in_(_MODEL_EVENT_TYPES),
        )
        .order_by(LiveEventRecord.created_at.asc(), LiveEventRecord.event_id.asc())
    )
    for (
        run_id,
        event_id,
        event_type,
        round_number,
        phase,
        actor,
        action,
        payload,
        created_at,
        run_status,
    ) in rows:
        safe_payload = payload if isinstance(payload, dict) else {}
        request_id = _request_id(safe_payload.get("request_id"))
        if request_id is None:
            continue
        item = metadata.setdefault(request_id, {})
        if event_type == "model_request_started" or "event_id" not in item:
            item.update(
                {
                    "run_id": run_id,
                    "event_id": event_id,
                    "round_number": round_number,
                    "phase": phase,
                    "actor": actor,
                    "action": action,
                    "created_at": created_at,
                }
            )
        model = _optional_text(safe_payload.get("model"), max_length=120)
        if model is not None:
            item["model"] = model
        if event_type == "model_request_failed":
            item["status"] = "failed"
            item["error"] = safe_payload.get("message")
        elif event_type == "model_response_received" and item.get("status") != "failed":
            item["status"] = "completed"
        else:
            item.setdefault(
                "status",
                "pending" if run_status in {"queued", "running"} else "response_missing",
            )
    return metadata


def _request_id(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized if _REQUEST_ID_RE.fullmatch(normalized) else None


def _optional_text(value: object, *, max_length: int) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    if not normalized:
        return None
    return normalized[:max_length]


def _optional_content(value: object, *, max_length: int) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = value.replace("\x00", "")
    return cleaned[:max_length] if cleaned.strip() else None


def _first_text(*values: object, max_length: int) -> str | None:
    for value in values:
        if (text := _optional_text(value, max_length=max_length)) is not None:
            return text
    return None


def _json_text(value: object, *, max_length: int) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return _optional_content(value, max_length=max_length)
    try:
        rendered = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True)
    except (TypeError, ValueError):
        return None
    return rendered[:max_length]


def _optional_non_negative_int(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value if value >= 0 else None


def _non_negative_int(value: object, *, default: int) -> int:
    parsed = _optional_non_negative_int(value)
    return parsed if parsed is not None else default


def _invalid_attempt_count(lm_log: dict[str, Any]) -> int:
    invalid_attempts = lm_log.get("invalid_attempts")
    return len(invalid_attempts) if isinstance(invalid_attempts, list) else 0
