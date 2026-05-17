from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.werewolf.checkpoint import (
    ResumeCheckpointError,
    has_resume_checkpoint,
    load_resume_checkpoint,
)


SESSION_ID_RE = r"^game_[0-9a-f]{8}$"
_SESSION_PATTERN = re.compile(SESSION_ID_RE)


class ReplayNotFoundError(Exception):
    """Raised when a replay session cannot be loaded."""


class ReplayStore:
    def __init__(self, logs_root: Path) -> None:
        self.logs_root = logs_root

    def list_sessions(self) -> list[dict[str, Any]]:
        if not self._is_directory(self.logs_root):
            return []

        sessions = []
        try:
            directories = list(self.logs_root.iterdir())
        except OSError:
            return []

        for directory in directories:
            if (
                self._is_symlink(directory)
                or not _SESSION_PATTERN.fullmatch(directory.name)
            ):
                continue
            if not self._is_directory(directory):
                continue

            state_path, status = self._state_path_for_directory(directory)
            checkpoint = self._checkpoint_for_directory(directory)
            if state_path is None or status is None:
                if checkpoint is None:
                    continue
                status = "partial"
                state = checkpoint["state_at_round_start"]
            else:
                try:
                    state = self._read_state(state_path)
                except ReplayNotFoundError:
                    continue

            rounds = state.get("rounds", [])
            sessions.append(
                {
                    "session_id": directory.name,
                    "status": status,
                    "winner": state.get("winner"),
                    "round_count": len(rounds),
                    "created_at": self._created_at_for_directory(directory, state_path),
                    "rule_set": state.get("rule_set"),
                    "resumable": checkpoint is not None,
                }
            )

        return sorted(
            sessions,
            key=lambda item: (item["created_at"] or "", item["session_id"]),
            reverse=True,
        )

    def load_session(self, session_id: str) -> dict[str, Any]:
        if not _SESSION_PATTERN.fullmatch(session_id):
            raise ReplayNotFoundError

        session_dir = self.logs_root / session_id
        if self._is_symlink(session_dir) or not self._is_directory(session_dir):
            raise ReplayNotFoundError

        try:
            resolved_session_dir = session_dir.resolve()
            resolved_logs_root = self.logs_root.resolve()
            resolved_session_dir.relative_to(resolved_logs_root)
        except (OSError, RuntimeError, ValueError) as exc:
            raise ReplayNotFoundError from exc

        state_path, status = self._state_path_for_directory(session_dir)
        checkpoint = self._checkpoint_for_directory(session_dir)
        if state_path is None or status is None:
            if checkpoint is None:
                raise ReplayNotFoundError
            return {
                "session_id": session_id,
                "status": "partial",
                "state": checkpoint["state_at_round_start"],
                "logs": checkpoint.get("logs_before_round", []),
                "resumable": True,
            }

        logs_path = session_dir / "game_logs.json"
        logs = self._read_logs(logs_path) if self._path_exists(logs_path) else []
        state = self._read_state(state_path)
        return {
            "session_id": session_id,
            "status": status,
            "state": state,
            "logs": logs,
            "resumable": checkpoint is not None,
        }

    def _state_path_for_directory(self, directory: Path) -> tuple[Path | None, str | None]:
        complete_path = directory / "game_complete.json"
        if self._is_symlink(complete_path):
            return None, None

        if self._is_regular_json_file(complete_path):
            return complete_path, "complete"

        partial_path = directory / "game_partial.json"
        if self._is_symlink(partial_path):
            return None, None

        if self._is_regular_json_file(partial_path):
            return partial_path, "partial"

        return None, None

    def _path_exists(self, path: Path) -> bool:
        try:
            return path.exists()
        except OSError:
            return False

    def _is_directory(self, path: Path) -> bool:
        try:
            return path.exists() and path.is_dir()
        except OSError:
            return False

    def _is_symlink(self, path: Path) -> bool:
        try:
            return path.is_symlink()
        except OSError:
            return True

    def _is_regular_json_file(self, path: Path) -> bool:
        try:
            return path.exists() and not path.is_symlink() and path.is_file()
        except OSError:
            return False

    def _read_json(self, path: Path) -> Any:
        if self._is_symlink(path):
            raise ReplayNotFoundError

        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ReplayNotFoundError from exc

    def _read_state(self, path: Path) -> dict[str, Any]:
        state = self._read_json(path)
        if not isinstance(state, dict):
            raise ReplayNotFoundError

        rounds = state.get("rounds", [])
        if not isinstance(rounds, list):
            raise ReplayNotFoundError

        return state

    def _read_logs(self, path: Path) -> list[Any]:
        logs = self._read_json(path)
        if not isinstance(logs, list):
            raise ReplayNotFoundError

        return logs

    def _checkpoint_for_directory(self, directory: Path) -> dict[str, Any] | None:
        try:
            if not has_resume_checkpoint(directory):
                return None
            return load_resume_checkpoint(directory)
        except ResumeCheckpointError:
            return None

    def _created_at_for_directory(
        self,
        directory: Path,
        state_path: Path | None,
    ) -> str | None:
        timestamp_path = state_path or directory
        try:
            created_at = datetime.fromtimestamp(timestamp_path.stat().st_mtime, tz=UTC)
        except OSError:
            return None

        return created_at.isoformat().replace("+00:00", "Z")
