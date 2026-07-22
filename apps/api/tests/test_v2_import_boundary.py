from __future__ import annotations

import ast
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


def test_api_v2_does_not_import_old_werewolf_business_modules() -> None:
    violations: list[str] = []
    for path in sorted((REPOSITORY_ROOT / "apps/api/app/v2").glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and (node.module or "").startswith(
                "app.werewolf"
            ):
                violations.append(f"{path.name}:{node.lineno}:{node.module}")
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.startswith("app.werewolf"):
                        violations.append(f"{path.name}:{node.lineno}:{alias.name}")
    assert violations == []


def test_web_v2_does_not_import_old_game_live_or_replay_modules() -> None:
    forbidden = (
        "@werewolf-arena/game-client",
        "/live/",
        "/replay/",
        "game-client",
    )
    violations: list[str] = []
    for directory in (
        REPOSITORY_ROOT / "apps/mobile-web/src/v2",
        REPOSITORY_ROOT / "apps/admin-web/src/v2",
    ):
        for path in sorted(directory.rglob("*.ts*")):
            for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if "from " not in line:
                    continue
                if any(token in line.lower() for token in forbidden):
                    violations.append(f"{path.relative_to(REPOSITORY_ROOT)}:{line_number}")
    assert violations == []
