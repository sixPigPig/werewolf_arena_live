from __future__ import annotations

import ast
from pathlib import Path


V2_ROOT = Path(__file__).parents[1] / "app" / "v2"
FORBIDDEN_PREFIXES = (
    "app.werewolf",
    "app.models.game_session",
    "app.models.live",
    "app.api.routes.games",
)


def test_v2_business_code_does_not_import_old_game_live_or_replay_modules() -> None:
    violations: list[str] = []
    for path in sorted(V2_ROOT.glob("*.py")):
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            modules: list[str] = []
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                modules = [node.module]
            for module in modules:
                if module.startswith(FORBIDDEN_PREFIXES):
                    violations.append(f"{path.name}:{node.lineno} imports {module}")
    assert violations == []
