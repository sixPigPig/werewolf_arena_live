from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Sequence

import uvicorn

from app.core.config import settings
from app.db.session import SessionLocal
from app.legacy_game_record_cleanup import purge_legacy_game_records
from app.player_avatar_asset_migration import (
    PlayerAvatarAssetMigrationError,
    migrate_player_avatar_assets,
)
from app.player_profile_import import PlayerProfileImportError, import_player_profiles
from app.werewolf.evaluator import evaluate_replay
from app.werewolf.providers import default_model_name
from app.werewolf.replay import DatabaseReplayStore
from app.werewolf.runner import GameRunError, run_game


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="werewolf-api")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_game_parser = subparsers.add_parser("run-game", help="Run one Werewolf game.")
    default_model = default_model_name()
    run_game_parser.add_argument("--villager-model", default=default_model)
    run_game_parser.add_argument("--werewolf-model", default=default_model)
    run_game_parser.add_argument("--seed", type=int, default=None)
    run_game_parser.add_argument("--max-rounds", type=int, default=8)
    run_game_parser.set_defaults(func=_run_game_command)

    serve_parser = subparsers.add_parser("serve", help="Run the FastAPI backend.")
    serve_parser.add_argument("--host", default="127.0.0.1")
    serve_parser.add_argument("--port", type=int, default=8000)
    serve_parser.add_argument("--reload", action="store_true")
    serve_parser.set_defaults(func=_serve_command)

    import_profiles_parser = subparsers.add_parser(
        "import-player-profiles",
        help="Import legacy JSON player profiles into PostgreSQL.",
    )
    import_profiles_parser.add_argument("--source", type=Path, required=True)
    import_profiles_parser.set_defaults(func=_import_player_profiles_command)

    migrate_avatar_parser = subparsers.add_parser(
        "migrate-player-avatar-assets",
        help="Import legacy file-backed player avatar images into PostgreSQL.",
    )
    migrate_avatar_parser.add_argument(
        "--logs-dir",
        type=Path,
        default=Path(settings.werewolf_logs_dir),
    )
    migrate_avatar_parser.set_defaults(func=_migrate_player_avatar_assets_command)

    purge_records_parser = subparsers.add_parser(
        "purge-legacy-game-records",
        help="Delete legacy file-backed game_* records from a logs directory.",
    )
    purge_records_parser.add_argument(
        "--logs-dir",
        type=Path,
        default=Path(settings.werewolf_logs_dir),
    )
    purge_records_parser.add_argument("--yes", action="store_true")
    purge_records_parser.set_defaults(func=_purge_legacy_game_records_command)

    evaluate_parser = subparsers.add_parser(
        "evaluate-replay",
        help="Evaluate a game_complete.json replay for realism issues.",
    )
    evaluate_parser.add_argument("--source", type=Path, required=True)
    evaluate_parser.set_defaults(func=_evaluate_replay_command)

    return parser


def _run_game_command(args: argparse.Namespace) -> int:
    db = SessionLocal()
    try:
        result = run_game(
            record_store=DatabaseReplayStore(db),
            villager_model=args.villager_model,
            werewolf_model=args.werewolf_model,
            seed=args.seed,
            max_rounds=args.max_rounds,
        )
    except GameRunError as exc:
        print(str(exc), file=sys.stderr)
        if exc.session_id:
            print(f"session_id={exc.session_id}", file=sys.stderr)
        return 1
    finally:
        db.close()

    print(f"胜利阵营={result.winner}")
    print(f"session_id={result.session_id}")
    return 0


def _purge_legacy_game_records_command(args: argparse.Namespace) -> int:
    result = purge_legacy_game_records(args.logs_dir, confirm=args.yes)
    print(
        f"匹配={result.matched_count} "
        f"删除={result.deleted_count} "
        f"跳过={result.skipped_count}"
    )
    if not args.yes and result.matched_count:
        print("未传入 --yes，未删除旧对局目录。")
    return 0


def _serve_command(args: argparse.Namespace) -> int:
    uvicorn.run("app.main:app", host=args.host, port=args.port, reload=args.reload)
    return 0


def _import_player_profiles_command(args: argparse.Namespace) -> int:
    db = SessionLocal()
    try:
        result = import_player_profiles(args.source, db)
    except PlayerProfileImportError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    finally:
        db.close()

    print(
        f"读取={result.read_count} "
        f"导入={result.imported_count} "
        f"跳过={result.skipped_count}"
    )
    return 0


def _migrate_player_avatar_assets_command(args: argparse.Namespace) -> int:
    db = SessionLocal()
    try:
        result = migrate_player_avatar_assets(logs_dir=args.logs_dir, db=db)
    except PlayerAvatarAssetMigrationError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    finally:
        db.close()

    print(
        f"扫描={result.scanned_count} "
        f"导入={result.imported_count} "
        f"复用={result.reused_count} "
        f"缺失={result.missing_count} "
        f"回填={result.updated_count}"
    )
    return 0


def _evaluate_replay_command(args: argparse.Namespace) -> int:
    report = evaluate_replay(args.source)
    print(f"session_id={report.session_id}")
    if not report.issues:
        print("issues=0")
        return 0

    print(f"issues={len(report.issues)}")
    for issue in report.issues:
        print(f"{issue.code} round={issue.round_number} detail={issue.detail}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
