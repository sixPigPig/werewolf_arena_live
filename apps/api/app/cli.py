from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Sequence

import uvicorn

from app.werewolf.runner import GameRunError, run_game


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="werewolf-api")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_game_parser = subparsers.add_parser("run-game", help="Run one Werewolf game.")
    run_game_parser.add_argument("--villager-model", default="deepseek-chat")
    run_game_parser.add_argument("--werewolf-model", default="deepseek-chat")
    run_game_parser.add_argument("--seed", type=int, default=None)
    run_game_parser.add_argument("--logs-dir", type=Path, default=Path("logs"))
    run_game_parser.add_argument("--max-rounds", type=int, default=8)
    run_game_parser.set_defaults(func=_run_game_command)

    serve_parser = subparsers.add_parser("serve", help="Run the FastAPI backend.")
    serve_parser.add_argument("--host", default="127.0.0.1")
    serve_parser.add_argument("--port", type=int, default=8000)
    serve_parser.add_argument("--reload", action="store_true")
    serve_parser.set_defaults(func=_serve_command)

    return parser


def _run_game_command(args: argparse.Namespace) -> int:
    try:
        result = run_game(
            villager_model=args.villager_model,
            werewolf_model=args.werewolf_model,
            seed=args.seed,
            logs_dir=args.logs_dir,
            max_rounds=args.max_rounds,
        )
    except GameRunError as exc:
        print(str(exc), file=sys.stderr)
        if exc.log_directory:
            print(f"日志目录={exc.log_directory}", file=sys.stderr)
        return 1

    print(f"胜利阵营={result.winner}")
    print(f"session_id={result.session_id}")
    print(f"日志目录={result.log_directory}")
    return 0


def _serve_command(args: argparse.Namespace) -> int:
    uvicorn.run("app.main:app", host=args.host, port=args.port, reload=args.reload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
