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
        if not self.logs_root.exists():
            return []

        sessions = []
        for directory in self.logs_root.iterdir():
            if not directory.is_dir() or not _SESSION_PATTERN.fullmatch(directory.name):
                continue

            state_path, status = self._state_path_for_directory(directory)
            if state_path is None or status is None:
                continue

            state = self._read_json(state_path)
            sessions.append(
                {
                    "session_id": directory.name,
                    "status": status,
                    "winner": state.get("winner"),
                    "round_count": len(state.get("rounds", [])),
                    "created_at": created_at_from_session_id(directory.name),
                }
            )

        return sorted(sessions, key=lambda item: item["session_id"], reverse=True)

    def load_session(self, session_id: str) -> dict[str, Any]:
        if not _SESSION_PATTERN.fullmatch(session_id):
            raise ReplayNotFoundError

        session_dir = (self.logs_root / session_id).resolve()
        try:
            session_dir.relative_to(self.logs_root.resolve())
        except ValueError as exc:
            raise ReplayNotFoundError from exc

        state_path, status = self._state_path_for_directory(session_dir)
        if state_path is None or status is None:
            raise ReplayNotFoundError

        logs_path = session_dir / "game_logs.json"
        logs = self._read_json(logs_path) if logs_path.exists() else []
        return {
            "session_id": session_id,
            "status": status,
            "state": self._read_json(state_path),
            "logs": logs,
        }

    def _state_path_for_directory(self, directory: Path) -> tuple[Path | None, str | None]:
        complete_path = directory / "game_complete.json"
        if complete_path.exists():
            return complete_path, "complete"

        partial_path = directory / "game_partial.json"
        if partial_path.exists():
            return partial_path, "partial"

        return None, None

    def _read_json(self, path: Path) -> Any:
        return json.loads(path.read_text(encoding="utf-8"))


def created_at_from_session_id(session_id: str) -> str | None:
    match = _SESSION_PATTERN.fullmatch(session_id)
    if match is None:
        return None

    raw_value = "".join(match.groups())
    created_at = datetime.strptime(raw_value, "%Y%m%d%H%M%S").replace(tzinfo=UTC)
    return created_at.isoformat().replace("+00:00", "Z")
