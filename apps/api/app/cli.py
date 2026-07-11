from __future__ import annotations

import argparse
import signal
import sys
from pathlib import Path
from threading import Event
from typing import Sequence

import uvicorn
from sqlalchemy import func, select

from app.admin.rbac import AdminRole
from app.core.config import settings
from app.admin.voice_jobs import run_voice_generation_worker
from app.db.session import SessionLocal
from app.legacy_game_record_cleanup import purge_legacy_game_records
from app.judge_voice_asset_import import (
    JudgeVoiceAssetImportError,
    import_judge_voice_assets,
)
from app.player_avatar_asset_migration import (
    PlayerAvatarAssetMigrationError,
    migrate_player_avatar_assets,
)
from app.player_profile_import import PlayerProfileImportError, import_player_profiles
from app.models.user import User
from app.werewolf.evaluator import evaluate_replay
from app.werewolf.judge_voice_assets import DEFAULT_JUDGE_VOICE_ASSET_DIR
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

    import_voice_parser = subparsers.add_parser(
        "import-judge-voice-assets",
        help="Import legacy judge voice files into PostgreSQL.",
    )
    import_voice_parser.add_argument(
        "--source",
        type=Path,
        default=DEFAULT_JUDGE_VOICE_ASSET_DIR,
    )
    import_voice_parser.set_defaults(func=_import_judge_voice_assets_command)

    voice_worker_parser = subparsers.add_parser(
        "run-judge-voice-worker",
        help="Claim and run persistent judge voice generation jobs.",
    )
    voice_worker_parser.add_argument(
        "--once",
        action="store_true",
        help="Process at most one queued job, then exit.",
    )
    voice_worker_parser.add_argument(
        "--poll-seconds",
        type=float,
        default=settings.judge_voice_worker_poll_seconds,
        help="Seconds to wait before polling an empty queue.",
    )
    voice_worker_parser.set_defaults(func=_run_judge_voice_worker_command)

    provision_admin_parser = subparsers.add_parser(
        "provision-admin-user",
        help="Create or update a pre-authorized Admin user for OIDC binding.",
    )
    provision_admin_parser.add_argument("--email", required=True)
    provision_admin_parser.add_argument("--display-name", required=True)
    provision_admin_parser.add_argument(
        "--role",
        required=True,
        choices=[role.value for role in AdminRole],
    )
    provision_admin_parser.set_defaults(func=_provision_admin_user_command)

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


def _import_judge_voice_assets_command(args: argparse.Namespace) -> int:
    db = SessionLocal()
    try:
        result = import_judge_voice_assets(
            asset_dir=args.source,
            audio_format=settings.ark_tts_judge_asset_audio_format,
            sample_rate=settings.ark_tts_judge_asset_sample_rate,
            db=db,
        )
    except JudgeVoiceAssetImportError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    finally:
        db.close()
    print(
        f"扫描={result.scanned_count} "
        f"导入={result.imported_count} "
        f"更新={result.updated_count} "
        f"复用={result.reused_count} "
        f"缺失={result.missing_count} "
        f"字节={result.byte_count}"
    )
    return 0


def _run_judge_voice_worker_command(args: argparse.Namespace) -> int:
    if not 0.25 <= args.poll_seconds <= 60:
        print("--poll-seconds must be between 0.25 and 60", file=sys.stderr)
        return 2

    stop_event = Event()

    def request_stop(_signum: int, _frame: object) -> None:
        stop_event.set()

    previous_handlers = {
        signal_number: signal.signal(signal_number, request_stop)
        for signal_number in (signal.SIGINT, signal.SIGTERM)
    }
    try:
        processed_count = run_voice_generation_worker(
            SessionLocal,
            stop_event=stop_event,
            poll_seconds=args.poll_seconds,
            once=args.once,
            on_job=lambda job_id: print(f"job_id={job_id}", flush=True),
        )
    finally:
        for signal_number, handler in previous_handlers.items():
            signal.signal(signal_number, handler)

    if args.once and processed_count == 0:
        print("job_id=none")
    return 0


def _provision_admin_user_command(args: argparse.Namespace) -> int:
    email = args.email.strip().lower()
    display_name = args.display_name.strip()
    if "@" not in email or len(email) > 255 or not display_name or len(display_name) > 120:
        print("invalid admin email or display name", file=sys.stderr)
        return 2
    with SessionLocal() as db:
        user = db.scalar(select(User).where(func.lower(User.email) == email))
        action = "updated"
        if user is None:
            user = User(email=email, display_name=display_name)
            db.add(user)
            action = "created"
        user.display_name = display_name
        user.admin_role = args.role
        user.is_active = True
        if action == "updated":
            user.admin_version += 1
        db.flush()
        user_id = user.id
        db.commit()
    print(f"user_id={user_id} action={action} role={args.role}")
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
