from __future__ import annotations

import argparse
import json
import signal
import sys
from pathlib import Path
from threading import Event
from typing import Sequence
from uuid import uuid4

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
from app.match.model_concurrency_canary import (
    DEFAULT_E1_CANARY_CORPUS_PATH,
    E1CanaryContractError,
    build_e1_canary_dry_run_report,
    load_e1_canary_budget_ledger,
    load_e1_canary_corpus,
    validate_e1_canary_live_prerequisites,
)
from app.match.model_context_cutover import preflight_v12_model_context_cutover
from app.shared.judge_voice_assets import DEFAULT_JUDGE_VOICE_ASSET_DIR
from app.shared.worker_telemetry import (
    JUDGE_VOICE_WORKER_TYPE,
    RuntimeWorkerTelemetry,
    runtime_worker_is_alive,
)


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    return args.func(args)

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="werewolf-api")
    subparsers = parser.add_subparsers(dest="command", required=True)

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

    voice_worker_probe_parser = subparsers.add_parser(
        "check-judge-voice-worker",
        help="Exit successfully when a judge voice worker database heartbeat is fresh.",
    )
    voice_worker_probe_parser.add_argument(
        "--max-age-seconds",
        type=float,
        default=settings.judge_voice_worker_probe_max_age_seconds,
    )
    voice_worker_probe_parser.set_defaults(func=_check_judge_voice_worker_command)

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

    v12_cutover_parser = subparsers.add_parser(
        "preflight-v12-model-context-cutover",
        help="Read-only check that every V11 V2 game is safe history before V12 cutover.",
    )
    v12_cutover_parser.add_argument(
        "--json",
        action="store_true",
        help="Print the complete machine-readable cutover report.",
    )
    v12_cutover_parser.set_defaults(func=_preflight_v12_model_context_cutover_command)

    e1_canary_parser = subparsers.add_parser(
        "run-v2-agent-plan-canary",
        help="Validate the fixed E1 Agent Plan workload without external calls by default.",
    )
    e1_canary_parser.add_argument(
        "--corpus",
        type=Path,
        default=DEFAULT_E1_CANARY_CORPUS_PATH,
    )
    e1_canary_parser.add_argument(
        "--caps",
        nargs="+",
        type=int,
        choices=(3, 4, 6),
        default=[3, 4],
    )
    e1_canary_parser.add_argument("--json", action="store_true")
    e1_canary_parser.add_argument(
        "--execute",
        action="store_true",
        help="Request live mode. This build still fails closed before creating a client.",
    )
    e1_canary_parser.add_argument("--confirm-external-model-calls", action="store_true")
    e1_canary_parser.add_argument("--confirm-billing-authorized", action="store_true")
    e1_canary_parser.add_argument("--budget-ledger", type=Path)
    e1_canary_parser.set_defaults(func=_run_v2_agent_plan_canary_command)

    return parser

def _purge_legacy_game_records_command(args: argparse.Namespace) -> int:
    result = purge_legacy_game_records(args.logs_dir, confirm=args.yes)
    print(f"匹配={result.matched_count} 删除={result.deleted_count} 跳过={result.skipped_count}")
    if not args.yes and result.matched_count:
        print("未传入 --yes，未删除旧对局目录。")
    return 0

def _preflight_v12_model_context_cutover_command(args: argparse.Namespace) -> int:
    try:
        with SessionLocal() as db:
            report = preflight_v12_model_context_cutover(db)
    except Exception as exc:
        print(
            f"V12 model-context cutover preflight failed: {type(exc).__name__}",
            file=sys.stderr,
        )
        return 2

    if args.json:
        print(json.dumps(report.as_dict(), ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(
            "cutover=v11_to_v12 read_only=true "
            f"scanned={report.scanned_game_count} candidates={report.candidate_count} "
            f"safe={report.safe_history_count} blocking={report.blocking_count}"
        )
        for finding in report.findings:
            if finding.is_safe_history:
                continue
            print(
                f"BLOCK game_id={finding.game_id} run_id={finding.current_run_id} "
                f"prompt={finding.prompt_template_version} "
                f"match_status={finding.match_status} "
                f"execution_state={finding.execution_state} "
                f"reasons={','.join(finding.reason_codes)}"
            )
    return 0 if report.deployable else 1

def _run_v2_agent_plan_canary_command(args: argparse.Namespace) -> int:
    try:
        corpus = load_e1_canary_corpus(args.corpus)
        if not args.execute:
            report = build_e1_canary_dry_run_report(corpus, caps=args.caps)
            if args.json:
                print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
            else:
                print(
                    "e1_canary=dry_run external_requests=0 http_client_created=false "
                    f"attempts_per_cap={report['attempts_per_cap']} "
                    f"caps={','.join(str(cap) for cap in report['caps'])} "
                    f"configured_tokens_per_cap={report['configured_output_tokens_per_cap']}"
                )
                print(
                    f"corpus_sha256={report['corpus_sha256']} "
                    f"schedule_sha256={report['schedule_sha256']}"
                )
            return 0

        if args.budget_ledger is None:
            raise E1CanaryContractError("canary_budget_ledger_required")
        ledger = load_e1_canary_budget_ledger(args.budget_ledger)
        validate_e1_canary_live_prerequisites(
            corpus,
            caps=args.caps,
            confirm_external_model_calls=args.confirm_external_model_calls,
            confirm_billing_authorized=args.confirm_billing_authorized,
            ledger=ledger,
        )
    except E1CanaryContractError as exc:
        print(f"E1 Agent Plan canary refused: {exc.code}", file=sys.stderr)
        return 2

    print(
        "E1 Agent Plan canary refused: live_execution_not_implemented; no HTTP client was created.",
        file=sys.stderr,
    )
    return 2

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

    print(f"读取={result.read_count} 导入={result.imported_count} 跳过={result.skipped_count}")
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
    telemetry = RuntimeWorkerTelemetry(
        SessionLocal,
        worker_id=f"judge-voice-worker-{uuid4().hex}",
        worker_type=JUDGE_VOICE_WORKER_TYPE,
        heartbeat_seconds=settings.judge_voice_worker_heartbeat_seconds,
    )

    def request_stop(_signum: int, _frame: object) -> None:
        stop_event.set()

    previous_handlers = {
        signal_number: signal.signal(signal_number, request_stop)
        for signal_number in (signal.SIGINT, signal.SIGTERM)
    }
    telemetry_started = False
    try:
        telemetry.start()
        telemetry_started = True
        processed_count = run_voice_generation_worker(
            SessionLocal,
            stop_event=stop_event,
            poll_seconds=args.poll_seconds,
            once=args.once,
            on_job=lambda job_id: print(f"job_id={job_id}", flush=True),
        )
    except Exception as exc:
        print(f"judge voice worker failed: {type(exc).__name__}", file=sys.stderr)
        return 1
    finally:
        if telemetry_started:
            telemetry.stop()
        for signal_number, handler in previous_handlers.items():
            signal.signal(signal_number, handler)

    if args.once and processed_count == 0:
        print("job_id=none")
    return 0

def _check_judge_voice_worker_command(args: argparse.Namespace) -> int:
    if not 5 <= args.max_age_seconds <= 300:
        print("--max-age-seconds must be between 5 and 300", file=sys.stderr)
        return 2
    try:
        with SessionLocal() as db:
            alive = runtime_worker_is_alive(
                db,
                worker_type=JUDGE_VOICE_WORKER_TYPE,
                max_age_seconds=args.max_age_seconds,
            )
    except Exception as exc:
        print(f"judge_voice_worker=unknown error={type(exc).__name__}", file=sys.stderr)
        return 2
    print("judge_voice_worker=ok" if alive else "judge_voice_worker=stale")
    return 0 if alive else 1

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



if __name__ == "__main__":
    raise SystemExit(main())
