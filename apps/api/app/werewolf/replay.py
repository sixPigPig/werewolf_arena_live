from __future__ import annotations

import copy
import logging
import re
from datetime import UTC, datetime
from typing import Any, Protocol

from sqlalchemy import update
from sqlalchemy.orm import Session

from app.models.game_session import GameReplayPayload, GameSessionRecord
from app.models.live import LiveRunRecord
from app.core.config import settings
from app.werewolf.checkpoint import (
    ResumeCheckpointError,
    report_resume_checkpoint_error,
    resolved_rule_set_from_checkpoint,
)
from app.werewolf.live import validate_rule_set_revision_metadata
from app.werewolf.models import GameState, RoundLog
from app.rule_sets.types import CompiledRuleSet
from app.werewolf.quality_store import enqueue_quality_evaluation


logger = logging.getLogger(__name__)

SESSION_ID_RE = r"^game_[0-9a-f]{8}$"
_SESSION_PATTERN = re.compile(SESSION_ID_RE)
LIVE_COMPLETION_RECEIPT_KEY = "_live_completion_receipt_v1"


class ReplayNotFoundError(Exception):
    """Raised when a replay session cannot be loaded."""


class ReplayWriteFencedError(RuntimeError):
    """Raised when a superseded live worker attempts to write replay state."""


class GameRecordStore(Protocol):
    def list_sessions(self) -> list[dict[str, Any]]: ...

    def load_session(self, session_id: str) -> dict[str, Any]: ...

    def load_resume_checkpoint(self, session_id: str) -> dict[str, Any]: ...

    def save_game(self, state: GameState, logs: list[RoundLog]) -> None: ...

    def save_game_payload(self, *, state: dict[str, Any], logs: list[Any]) -> None: ...

    def save_resume_checkpoint(self, session_id: str, checkpoint: dict[str, Any]) -> None: ...

    def clear_resume_checkpoint(self, session_id: str) -> None: ...


class DatabaseReplayStore:
    def __init__(
        self,
        db: Session,
        *,
        run_id: str | None = None,
        worker_id: str | None = None,
        fence_token: int | None = None,
    ) -> None:
        self.db = db
        self.run_id = run_id
        self.worker_id = worker_id
        self.fence_token = fence_token

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
        payload_session_id, state, logs, _rounds = _validated_game_payload(
            state=payload.state,
            logs=payload.logs,
        )
        if payload_session_id != session_id:
            raise ReplayNotFoundError
        public_state = copy.deepcopy(state)
        public_state.pop(LIVE_COMPLETION_RECEIPT_KEY, None)
        return {
            "session_id": session_id,
            "status": record.status,
            "state": public_state,
            "logs": copy.deepcopy(logs),
            "resumable": _valid_checkpoint_or_none(session_id, payload.checkpoint) is not None,
        }

    def load_resume_checkpoint(self, session_id: str) -> dict[str, Any]:
        self._validate_session_id(session_id)
        payload = self.db.get(GameReplayPayload, session_id)
        if payload is None or payload.checkpoint is None:
            error = ResumeCheckpointError("missing")
            report_resume_checkpoint_error(error)
            raise error
        _validated_checkpoint_payload(session_id, payload.checkpoint)
        return copy.deepcopy(payload.checkpoint)

    def save_game(self, state: GameState, logs: list[RoundLog]) -> None:
        self.save_game_payload(
            state=state.to_dict(),
            logs=[log.to_dict() for log in logs],
        )

    def save_game_with_live_completion(
        self,
        state: GameState,
        logs: list[RoundLog],
        *,
        run_id: str,
        terminal_keep_from_event_id: int,
    ) -> None:
        if (
            not isinstance(run_id, str)
            or not run_id
            or type(terminal_keep_from_event_id) is not int
            or terminal_keep_from_event_id < 1
            or not state.winner
            or (self.run_id is not None and self.run_id != run_id)
        ):
            raise ValueError("invalid live completion receipt")
        state_payload = state.to_dict()
        state_payload[LIVE_COMPLETION_RECEIPT_KEY] = {
            "schema_version": 1,
            "run_id": run_id,
            "session_id": state.session_id,
            "winner": state.winner,
            "terminal_keep_from_event_id": terminal_keep_from_event_id,
        }
        self.save_game_payload(
            state=state_payload,
            logs=[log.to_dict() for log in logs],
        )

    def load_live_completion_receipt(
        self,
        session_id: str,
        *,
        run_id: str,
    ) -> dict[str, object] | None:
        self._validate_session_id(session_id)
        record = self.db.get(GameSessionRecord, session_id)
        payload = self.db.get(GameReplayPayload, session_id)
        if record is None or payload is None or record.status != "complete":
            return None
        receipt = payload.state.get(LIVE_COMPLETION_RECEIPT_KEY)
        if not isinstance(receipt, dict):
            return None
        winner = receipt.get("winner")
        terminal_keep = receipt.get("terminal_keep_from_event_id")
        if (
            receipt.get("schema_version") != 1
            or receipt.get("run_id") != run_id
            or receipt.get("session_id") != session_id
            or not isinstance(winner, str)
            or not winner
            or winner != record.winner
            or winner != payload.state.get("winner")
            or type(terminal_keep) is not int
            or terminal_keep < 1
        ):
            return None
        return {
            "winner": winner,
            "terminal_keep_from_event_id": terminal_keep,
        }

    def save_game_payload(self, *, state: dict[str, Any], logs: list[Any]) -> None:
        session_id, state, logs, rounds = _validated_game_payload(state=state, logs=logs)
        rule_set_projection = _validated_rule_set_projection(state)
        status = "partial" if state.get("error_message") else "complete"
        existing_payload = self.db.get(GameReplayPayload, session_id)
        checkpoint = _valid_checkpoint_or_none(
            session_id,
            existing_payload.checkpoint if existing_payload is not None else None,
        )
        resumable = status == "partial" and checkpoint is not None
        try:
            self._guard_write_fence(session_id)
            record = self._get_or_create_record(session_id)
            record.status = status
            record.winner = str(state.get("winner") or "") or None
            record.round_count = len(rounds)
            _apply_rule_set_projection(record, rule_set_projection)
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
        if status in {"complete", "partial"} and settings.quality_evaluation_enabled:
            try:
                enqueue_quality_evaluation(
                    self.db,
                    session_id=session_id,
                    run_id=self.run_id,
                    evaluator_version=settings.quality_evaluation_version,
                )
                self.db.commit()
            except Exception as exc:
                self.db.rollback()
                logger.warning(
                    "Quality evaluation enqueue failed after terminal replay commit",
                    extra={
                        "session_id": session_id,
                        "error_type": type(exc).__name__,
                    },
                )

    def save_resume_checkpoint(self, session_id: str, checkpoint: dict[str, Any]) -> None:
        self._validate_session_id(session_id)
        state, logs, _checkpoint, rounds, compiled = _validated_checkpoint_payload(
            session_id,
            checkpoint,
        )
        rule_set_projection = _checkpoint_rule_set_projection(state, compiled)
        try:
            self._guard_write_fence(session_id)
            record = self._get_or_create_record(session_id)
            record.status = "partial"
            record.winner = str(state.get("winner") or "") or None
            record.round_count = len(rounds)
            _apply_rule_set_projection(record, rule_set_projection)
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
            self._guard_write_fence(session_id)
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

    def _guard_write_fence(self, session_id: str) -> None:
        values = (self.run_id, self.worker_id, self.fence_token)
        if all(value is None for value in values):
            return
        if self.run_id is None or self.worker_id is None or self.fence_token is None:
            raise ValueError("Replay write fencing requires run_id, worker_id and fence_token")
        result = self.db.execute(
            update(LiveRunRecord)
            .where(
                LiveRunRecord.run_id == self.run_id,
                LiveRunRecord.session_id == session_id,
                LiveRunRecord.status.in_(("queued", "running")),
                LiveRunRecord.worker_id == self.worker_id,
                LiveRunRecord.fence_token == self.fence_token,
                LiveRunRecord.lease_expires_at > datetime.now(tz=UTC),
            )
            .values(fence_token=LiveRunRecord.fence_token)
            .execution_options(synchronize_session=False)
        )
        if result.rowcount != 1:
            self.db.rollback()
            raise ReplayWriteFencedError(
                f"Replay write for {self.run_id} was rejected by its fencing token"
            )


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


def _validated_rule_set_projection(
    state: dict[str, Any],
) -> tuple[dict[str, Any] | None, str | None, str | None, int | None, str | None]:
    if "rule_set" not in state:
        return None, None, None, None, None
    rule_set = state.get("rule_set")
    if not isinstance(rule_set, dict):
        raise ReplayNotFoundError
    rule_set_id = rule_set.get("id")
    if not isinstance(rule_set_id, str) or not rule_set_id or rule_set_id.strip() != rule_set_id:
        raise ReplayNotFoundError

    revision_id = rule_set.get("revision_id")
    revision_no = rule_set.get("revision_no")
    content_hash = rule_set.get("content_hash")
    try:
        validate_rule_set_revision_metadata(
            rule_set_revision_id=revision_id,
            rule_set_revision_no=revision_no,
            rule_set_content_hash=content_hash,
            rule_set=rule_set,
        )
        if set(rule_set) & {
            "revision_id",
            "revision_no",
            "schema_version",
            "content_hash",
        }:
            from app.rule_sets import resolve_rule_set_snapshot

            resolve_rule_set_snapshot(rule_set)
    except ValueError as error:
        raise ReplayNotFoundError from error

    return rule_set, rule_set_id, revision_id, revision_no, content_hash


def _apply_rule_set_projection(
    record: GameSessionRecord,
    projection: tuple[
        dict[str, Any] | None,
        str | None,
        str | None,
        int | None,
        str | None,
    ],
) -> None:
    rule_set, rule_set_id, revision_id, revision_no, content_hash = projection
    record.rule_set_id = rule_set_id
    record.rule_set_revision_id = revision_id
    record.rule_set_revision_no = revision_no
    record.rule_set_content_hash = content_hash
    record.rule_set = copy.deepcopy(rule_set)


def _checkpoint_rule_set_projection(
    state: dict[str, Any],
    compiled: CompiledRuleSet,
) -> tuple[dict[str, Any], str, str | None, int | None, str]:
    rule_set = state["rule_set"]
    if not isinstance(rule_set, dict):
        raise ResumeCheckpointError("invalid_structure")
    return (
        copy.deepcopy(rule_set),
        compiled.rule_set.id,
        compiled.revision_id,
        compiled.revision_no,
        compiled.content_hash,
    )


def _validated_checkpoint_payload(
    session_id: str,
    checkpoint: Any,
) -> tuple[dict[str, Any], list[Any], dict[str, Any], list[Any], CompiledRuleSet]:
    try:
        return _validated_checkpoint_payload_unreported(session_id, checkpoint)
    except ResumeCheckpointError as error:
        report_resume_checkpoint_error(error)
        raise


def _validated_checkpoint_payload_unreported(
    session_id: str,
    checkpoint: Any,
) -> tuple[dict[str, Any], list[Any], dict[str, Any], list[Any], CompiledRuleSet]:
    if not _SESSION_PATTERN.fullmatch(session_id):
        raise ResumeCheckpointError("invalid_structure")
    if not isinstance(checkpoint, dict):
        raise ResumeCheckpointError("invalid_structure")
    if checkpoint.get("session_id") != session_id:
        raise ResumeCheckpointError("invalid_structure")

    state = checkpoint.get("state_at_round_start")
    if not isinstance(state, dict):
        raise ResumeCheckpointError("invalid_structure")
    if state.get("session_id") != session_id:
        raise ResumeCheckpointError("invalid_structure")
    rounds = state.get("rounds", [])
    if not isinstance(rounds, list):
        raise ResumeCheckpointError("invalid_structure")

    logs = checkpoint.get("logs_before_round")
    if not isinstance(logs, list):
        raise ResumeCheckpointError("invalid_structure")

    compiled = resolved_rule_set_from_checkpoint(checkpoint)
    return state, logs, checkpoint, rounds, compiled


def _valid_checkpoint_or_none(session_id: str, checkpoint: Any) -> dict[str, Any] | None:
    if checkpoint is None:
        return None
    try:
        _state, _logs, validated_checkpoint, _rounds, _compiled = _validated_checkpoint_payload(
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
