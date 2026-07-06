from __future__ import annotations

import copy
import re
from datetime import UTC, datetime
from typing import Any, Protocol

from sqlalchemy.orm import Session

from app.models.game_session import GameReplayPayload, GameSessionRecord
from app.werewolf.checkpoint import (
    CHECKPOINT_SCHEMA_VERSION,
    ResumeCheckpointError,
)
from app.werewolf.models import GameState, RoundLog

SESSION_ID_RE = r"^game_[0-9a-f]{8}$"
_SESSION_PATTERN = re.compile(SESSION_ID_RE)


class ReplayNotFoundError(Exception):
    """Raised when a replay session cannot be loaded."""


class GameRecordStore(Protocol):
    def list_sessions(self) -> list[dict[str, Any]]:
        ...

    def load_session(self, session_id: str) -> dict[str, Any]:
        ...

    def load_resume_checkpoint(self, session_id: str) -> dict[str, Any]:
        ...

    def save_game(self, state: GameState, logs: list[RoundLog]) -> None:
        ...

    def save_game_payload(self, *, state: dict[str, Any], logs: list[Any]) -> None:
        ...

    def save_resume_checkpoint(self, session_id: str, checkpoint: dict[str, Any]) -> None:
        ...

    def clear_resume_checkpoint(self, session_id: str) -> None:
        ...


class DatabaseReplayStore:
    def __init__(self, db: Session) -> None:
        self.db = db

    def list_sessions(self) -> list[dict[str, Any]]:
        records = (
            self.db.query(GameSessionRecord)
            .order_by(GameSessionRecord.created_at.desc(), GameSessionRecord.session_id.desc())
            .all()
        )
        return [
            {
                "session_id": record.session_id,
                "status": record.status,
                "winner": record.winner,
                "round_count": record.round_count,
                "created_at": _format_datetime(record.created_at),
                "rule_set": copy.deepcopy(record.rule_set),
                "resumable": bool(record.resumable),
            }
            for record in records
        ]

    def load_session(self, session_id: str) -> dict[str, Any]:
        self._validate_session_id(session_id)
        record = self.db.get(GameSessionRecord, session_id)
        payload = self.db.get(GameReplayPayload, session_id)
        if record is None or payload is None:
            raise ReplayNotFoundError
        state = _dict_payload(payload.state)
        logs = _list_payload(payload.logs)
        return {
            "session_id": session_id,
            "status": record.status,
            "state": copy.deepcopy(state),
            "logs": copy.deepcopy(logs),
            "resumable": bool(record.resumable),
        }

    def load_resume_checkpoint(self, session_id: str) -> dict[str, Any]:
        self._validate_session_id(session_id)
        payload = self.db.get(GameReplayPayload, session_id)
        if payload is None or not isinstance(payload.checkpoint, dict):
            raise ResumeCheckpointError
        checkpoint = copy.deepcopy(payload.checkpoint)
        if checkpoint.get("schema_version") != CHECKPOINT_SCHEMA_VERSION:
            raise ResumeCheckpointError
        return checkpoint

    def save_game(self, state: GameState, logs: list[RoundLog]) -> None:
        self.save_game_payload(
            state=state.to_dict(),
            logs=[log.to_dict() for log in logs],
        )

    def save_game_payload(self, *, state: dict[str, Any], logs: list[Any]) -> None:
        session_id = str(state.get("session_id") or "")
        self._validate_session_id(session_id)
        status = "partial" if state.get("error_message") else "complete"
        existing_payload = self.db.get(GameReplayPayload, session_id)
        checkpoint = existing_payload.checkpoint if existing_payload is not None else None
        resumable = status == "partial" and isinstance(checkpoint, dict)
        record = self._get_or_create_record(session_id)
        record.status = status
        record.winner = str(state.get("winner") or "") or None
        record.round_count = len(_list_payload(state.get("rounds", [])))
        record.rule_set = copy.deepcopy(state.get("rule_set"))
        record.resumable = resumable

        payload = self._get_or_create_payload(session_id)
        payload.state = copy.deepcopy(state)
        payload.logs = copy.deepcopy(logs)
        if status == "complete":
            payload.checkpoint = None
            record.resumable = False
        self.db.commit()

    def save_resume_checkpoint(self, session_id: str, checkpoint: dict[str, Any]) -> None:
        self._validate_session_id(session_id)
        if checkpoint.get("schema_version") != CHECKPOINT_SCHEMA_VERSION:
            raise ResumeCheckpointError
        state = _dict_payload(checkpoint.get("state_at_round_start"))
        logs = _list_payload(checkpoint.get("logs_before_round", []))
        record = self._get_or_create_record(session_id)
        record.status = "partial"
        record.winner = str(state.get("winner") or "") or None
        record.round_count = len(_list_payload(state.get("rounds", [])))
        record.rule_set = copy.deepcopy(state.get("rule_set"))
        record.resumable = True

        payload = self._get_or_create_payload(session_id)
        payload.state = copy.deepcopy(state)
        payload.logs = copy.deepcopy(logs)
        payload.checkpoint = copy.deepcopy(checkpoint)
        self.db.commit()

    def clear_resume_checkpoint(self, session_id: str) -> None:
        self._validate_session_id(session_id)
        record = self.db.get(GameSessionRecord, session_id)
        payload = self.db.get(GameReplayPayload, session_id)
        if record is None or payload is None:
            return
        payload.checkpoint = None
        record.resumable = False
        self.db.commit()

    def _get_or_create_record(self, session_id: str) -> GameSessionRecord:
        record = self.db.get(GameSessionRecord, session_id)
        if record is None:
            record = GameSessionRecord(session_id=session_id, status="partial")
            self.db.add(record)
            self.db.flush()
        return record

    def _get_or_create_payload(self, session_id: str) -> GameReplayPayload:
        payload = self.db.get(GameReplayPayload, session_id)
        if payload is None:
            payload = GameReplayPayload(session_id=session_id, state={}, logs=[])
            self.db.add(payload)
            self.db.flush()
        return payload

    def _validate_session_id(self, session_id: str) -> None:
        if not _SESSION_PATTERN.fullmatch(session_id):
            raise ReplayNotFoundError


def _dict_payload(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ReplayNotFoundError
    return value


def _list_payload(value: Any) -> list[Any]:
    if not isinstance(value, list):
        raise ReplayNotFoundError
    return value


def _format_datetime(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
