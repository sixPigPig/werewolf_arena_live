from __future__ import annotations

import copy
import re
from datetime import UTC, datetime
from pathlib import Path
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


class ReplayStore:
    # Temporary construction compatibility until API routes are converted to
    # DatabaseReplayStore. This shim intentionally exposes no file-backed sessions.
    def __init__(self, logs_root: Path) -> None:
        self.logs_root = logs_root

    def list_sessions(self) -> list[dict[str, Any]]:
        return []

    def load_session(self, _session_id: str) -> dict[str, Any]:
        raise ReplayNotFoundError

    def load_resume_checkpoint(self, _session_id: str) -> dict[str, Any]:
        raise ResumeCheckpointError

    def save_game(self, _state: GameState, _logs: list[RoundLog]) -> None:
        _raise_removed_replay_store_error()

    def save_game_payload(self, *, state: dict[str, Any], logs: list[Any]) -> None:
        del state, logs
        _raise_removed_replay_store_error()

    def save_resume_checkpoint(self, session_id: str, checkpoint: dict[str, Any]) -> None:
        del session_id, checkpoint
        _raise_removed_replay_store_error()

    def clear_resume_checkpoint(self, _session_id: str) -> None:
        _raise_removed_replay_store_error()


def _raise_removed_replay_store_error() -> None:
    raise RuntimeError(
        "ReplayStore file-backed storage has been removed; use DatabaseReplayStore "
        "after API route conversion."
    )


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
        rows = (
            self.db.query(GameSessionRecord, GameReplayPayload)
            .join(
                GameReplayPayload,
                GameReplayPayload.session_id == GameSessionRecord.session_id,
            )
            .order_by(GameSessionRecord.created_at.desc(), GameSessionRecord.session_id.desc())
            .all()
        )
        sessions = []
        for record, payload in rows:
            checkpoint = _valid_checkpoint_or_none(record.session_id, payload.checkpoint)
            sessions.append(
                {
                    "session_id": record.session_id,
                    "status": record.status,
                    "winner": record.winner,
                    "round_count": record.round_count,
                    "created_at": _format_datetime(record.created_at),
                    "rule_set": copy.deepcopy(record.rule_set),
                    "resumable": checkpoint is not None,
                }
            )
        return sessions

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
            "resumable": _valid_checkpoint_or_none(session_id, payload.checkpoint) is not None,
        }

    def load_resume_checkpoint(self, session_id: str) -> dict[str, Any]:
        self._validate_session_id(session_id)
        payload = self.db.get(GameReplayPayload, session_id)
        if payload is None:
            raise ResumeCheckpointError
        _validated_checkpoint_payload(session_id, payload.checkpoint)
        return copy.deepcopy(payload.checkpoint)

    def save_game(self, state: GameState, logs: list[RoundLog]) -> None:
        self.save_game_payload(
            state=state.to_dict(),
            logs=[log.to_dict() for log in logs],
        )

    def save_game_payload(self, *, state: dict[str, Any], logs: list[Any]) -> None:
        session_id, state, logs, rounds = _validated_game_payload(state=state, logs=logs)
        status = "partial" if state.get("error_message") else "complete"
        existing_payload = self.db.get(GameReplayPayload, session_id)
        checkpoint = _valid_checkpoint_or_none(
            session_id,
            existing_payload.checkpoint if existing_payload is not None else None,
        )
        resumable = status == "partial" and checkpoint is not None
        try:
            record = self._get_or_create_record(session_id)
            record.status = status
            record.winner = str(state.get("winner") or "") or None
            record.round_count = len(rounds)
            record.rule_set = copy.deepcopy(state.get("rule_set"))
            record.resumable = resumable

            payload = self._get_or_create_payload(session_id)
            payload.state = copy.deepcopy(state)
            payload.logs = copy.deepcopy(logs)
            if status == "complete":
                payload.checkpoint = None
                record.resumable = False
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise

    def save_resume_checkpoint(self, session_id: str, checkpoint: dict[str, Any]) -> None:
        self._validate_session_id(session_id)
        state, logs, _checkpoint, rounds = _validated_checkpoint_payload(session_id, checkpoint)
        try:
            record = self._get_or_create_record(session_id)
            record.status = "partial"
            record.winner = str(state.get("winner") or "") or None
            record.round_count = len(rounds)
            record.rule_set = copy.deepcopy(state.get("rule_set"))
            record.resumable = True

            payload = self._get_or_create_payload(session_id)
            payload.state = copy.deepcopy(state)
            payload.logs = copy.deepcopy(logs)
            payload.checkpoint = copy.deepcopy(_checkpoint)
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise

    def clear_resume_checkpoint(self, session_id: str) -> None:
        self._validate_session_id(session_id)
        try:
            record = self.db.get(GameSessionRecord, session_id)
            payload = self.db.get(GameReplayPayload, session_id)
            if record is None and payload is None:
                return
            if payload is not None:
                payload.checkpoint = None
            if record is not None:
                record.resumable = False
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise

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


def _validated_game_payload(
    *,
    state: Any,
    logs: Any,
) -> tuple[str, dict[str, Any], list[Any], list[Any]]:
    state = _dict_payload(state)
    logs = _list_payload(logs)
    session_id = str(state.get("session_id") or "")
    if not _SESSION_PATTERN.fullmatch(session_id):
        raise ReplayNotFoundError
    rounds = _list_payload(state.get("rounds", []))
    return session_id, state, logs, rounds


def _validated_checkpoint_payload(
    session_id: str,
    checkpoint: Any,
) -> tuple[dict[str, Any], list[Any], dict[str, Any], list[Any]]:
    if not _SESSION_PATTERN.fullmatch(session_id):
        raise ResumeCheckpointError
    if not isinstance(checkpoint, dict):
        raise ResumeCheckpointError
    if checkpoint.get("schema_version") != CHECKPOINT_SCHEMA_VERSION:
        raise ResumeCheckpointError
    if checkpoint.get("session_id") != session_id:
        raise ResumeCheckpointError

    state = checkpoint.get("state_at_round_start")
    if not isinstance(state, dict):
        raise ResumeCheckpointError
    if state.get("session_id") != session_id:
        raise ResumeCheckpointError
    rounds = state.get("rounds", [])
    if not isinstance(rounds, list):
        raise ResumeCheckpointError

    logs = checkpoint.get("logs_before_round")
    if not isinstance(logs, list):
        raise ResumeCheckpointError

    return state, logs, checkpoint, rounds


def _valid_checkpoint_or_none(session_id: str, checkpoint: Any) -> dict[str, Any] | None:
    try:
        _state, _logs, validated_checkpoint, _rounds = _validated_checkpoint_payload(
            session_id,
            checkpoint,
        )
    except ResumeCheckpointError:
        return None
    return validated_checkpoint


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
