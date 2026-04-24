from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


SESSION_ID_RE = r"^session_(\d{8})_(\d{6})_[A-Za-z0-9_-]+$"
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
            if state_path is None or status is None:
                continue

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
                    "created_at": created_at_from_session_id(directory.name),
                    "rule_set": state.get("rule_set"),
                }
            )

        return sorted(sessions, key=lambda item: item["session_id"], reverse=True)

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
        if state_path is None or status is None:
            raise ReplayNotFoundError

        logs_path = session_dir / "game_logs.json"
        logs = self._read_logs(logs_path) if self._path_exists(logs_path) else []
        state = self._read_state(state_path)
        return {
            "session_id": session_id,
            "status": status,
            "state": state,
            "logs": logs,
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


def created_at_from_session_id(session_id: str) -> str | None:
    match = _SESSION_PATTERN.fullmatch(session_id)
    if match is None:
        return None

    raw_value = "".join(match.groups())
    try:
        created_at = datetime.strptime(raw_value, "%Y%m%d%H%M%S").replace(tzinfo=UTC)
    except ValueError:
        return None

    return created_at.isoformat().replace("+00:00", "Z")
