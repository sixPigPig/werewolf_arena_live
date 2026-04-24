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
        if not self.logs_root.exists() or not self.logs_root.is_dir():
            return []

        sessions = []
        try:
            directories = list(self.logs_root.iterdir())
        except OSError:
            return []

        for directory in directories:
            if (
                directory.is_symlink()
                or not _SESSION_PATTERN.fullmatch(directory.name)
            ):
                continue
            try:
                if not directory.is_dir():
                    continue
            except OSError:
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
                }
            )

        return sorted(sessions, key=lambda item: item["session_id"], reverse=True)

    def load_session(self, session_id: str) -> dict[str, Any]:
        if not _SESSION_PATTERN.fullmatch(session_id):
            raise ReplayNotFoundError

        session_dir = self.logs_root / session_id
        if session_dir.is_symlink() or not session_dir.is_dir():
            raise ReplayNotFoundError

        resolved_session_dir = session_dir.resolve()
        try:
            resolved_session_dir.relative_to(self.logs_root.resolve())
        except ValueError as exc:
            raise ReplayNotFoundError from exc

        state_path, status = self._state_path_for_directory(session_dir)
        if state_path is None or status is None:
            raise ReplayNotFoundError

        logs_path = session_dir / "game_logs.json"
        logs = self._read_json(logs_path) if logs_path.exists() else []
        state = self._read_state(state_path)
        return {
            "session_id": session_id,
            "status": status,
            "state": state,
            "logs": logs,
        }

    def _state_path_for_directory(self, directory: Path) -> tuple[Path | None, str | None]:
        complete_path = directory / "game_complete.json"
        if complete_path.is_symlink():
            return None, None

        if self._is_regular_json_file(complete_path):
            return complete_path, "complete"

        partial_path = directory / "game_partial.json"
        if partial_path.is_symlink():
            return None, None

        if self._is_regular_json_file(partial_path):
            return partial_path, "partial"

        return None, None

    def _is_regular_json_file(self, path: Path) -> bool:
        return path.exists() and not path.is_symlink() and path.is_file()

    def _read_json(self, path: Path) -> Any:
        if path.is_symlink():
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
