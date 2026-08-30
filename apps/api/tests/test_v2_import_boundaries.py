from __future__ import annotations

import ast
from pathlib import Path


MATCH_ROOT = Path(__file__).parents[1] / "app" / "match"
FORBIDDEN_PREFIXES = (
    "app.werewolf",
    "app.v2",
    "app.models.game_session",
    "app.models.live",
    "app.api.routes.games",
    "app.api.routes.lobby",
)


def test_v2_business_code_does_not_import_old_game_live_or_replay_modules() -> None:
    violations: list[str] = []
    for path in sorted(MATCH_ROOT.rglob("*.py")):
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            modules: list[str] = []
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                modules = [node.module]
            for module in modules:
                if module.startswith(FORBIDDEN_PREFIXES):
                    violations.append(f"{path.relative_to(MATCH_ROOT)}:{node.lineno} imports {module}")
    assert violations == []
