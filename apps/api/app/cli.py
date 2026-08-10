from __future__ import annotations

import argparse
import json
import signal
import sys
from datetime import datetime
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
from app.rule_sets.snapshots import resolve_rule_set_snapshot
from app.v2.model_concurrency_canary import (
    DEFAULT_E1_CANARY_CORPUS_PATH,
    E1CanaryContractError,
    build_e1_canary_dry_run_report,
    load_e1_canary_budget_ledger,
    load_e1_canary_corpus,
    validate_e1_canary_live_prerequisites,
)
from app.v2.model_context_cutover import preflight_v12_model_context_cutover
from app.werewolf.judge_voice_assets import DEFAULT_JUDGE_VOICE_ASSET_DIR
from app.werewolf.providers import default_model_name
from app.werewolf.replay import DatabaseReplayStore
from app.werewolf.orphan_reaper import OrphanRecoveryResult, run_live_run_reaper
from app.werewolf.private_memory_cleanup import cleanup_private_round_memory
from app.werewolf.quality_store import enqueue_recent_missing_evaluations
from app.werewolf.quality_worker import run_quality_evaluation_worker
from app.werewolf.live import LiveRunRegistry
from app.werewolf.liveness_review import (
    analyze_review_ratings,
    build_review_package,
    load_manifest,
    load_ratings,
    write_review_package,
)
from app.werewolf.runner import GameRunError, run_game
from app.werewolf.rules import DEFAULT_RULE_SET_ID, freeze_rule_set_snapshot, get_rule_set
from app.werewolf.voice_materializer import (
    LIVE_VOICE_MATERIALIZER_WORKER_TYPE,
    run_voice_materializer_worker,
)
from app.werewolf.volcengine_tts import VolcengineTtsConfig
from app.werewolf.worker_telemetry import (
    JUDGE_VOICE_WORKER_TYPE,
    QUALITY_EVALUATION_WORKER_TYPE,
    RuntimeWorkerTelemetry,
    live_run_reaper_is_alive,
    runtime_worker_is_alive,
)


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="werewolf-api")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_game_parser = subparsers.add_parser("run-game", help="Run one Werewolf game.")
    run_game_parser.add_argument("--villager-model")
    run_game_parser.add_argument("--werewolf-model")
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

    materializer_parser = subparsers.add_parser(
        "run-live-voice-materializer",
        help="Materialize durable live event audio independently of WebSocket clients.",
    )
    materializer_parser.add_argument("--once", action="store_true")
    materializer_parser.add_argument(
        "--poll-seconds",
        type=float,
        default=settings.live_voice_materializer_poll_seconds,
    )
    materializer_parser.set_defaults(func=_run_live_voice_materializer_command)

    materializer_probe_parser = subparsers.add_parser(
        "check-live-voice-materializer",
        help="Exit successfully when a live voice materializer heartbeat is fresh.",
    )
    materializer_probe_parser.add_argument(
        "--max-age-seconds",
        type=float,
        default=settings.live_voice_materializer_probe_max_age_seconds,
    )
    materializer_probe_parser.set_defaults(func=_check_live_voice_materializer_command)

    quality_worker_parser = subparsers.add_parser(
        "run-quality-evaluator",
        help="Evaluate terminal games from the persistent quality queue.",
    )
    quality_worker_parser.add_argument("--once", action="store_true")
    quality_worker_parser.add_argument(
        "--poll-seconds",
        type=float,
        default=settings.quality_evaluation_poll_seconds,
    )
    quality_worker_parser.set_defaults(func=_run_quality_evaluator_command)

    quality_probe_parser = subparsers.add_parser(
        "check-quality-evaluator",
        help="Exit successfully when a quality evaluator heartbeat is fresh.",
    )
    quality_probe_parser.add_argument(
        "--max-age-seconds",
        type=float,
        default=settings.quality_evaluation_probe_max_age_seconds,
    )
    quality_probe_parser.set_defaults(func=_check_quality_evaluator_command)

    quality_backfill_parser = subparsers.add_parser(
        "backfill-quality-evaluations",
        help="Dry-run or enqueue a bounded terminal-game quality backfill.",
    )
    quality_backfill_parser.add_argument("--session-id")
    quality_backfill_parser.add_argument("--since")
    quality_backfill_parser.add_argument("--limit", type=int, default=100)
    quality_backfill_parser.add_argument("--apply", action="store_true")
    quality_backfill_parser.set_defaults(func=_backfill_quality_evaluations_command)

    review_export_parser = subparsers.add_parser(
        "export-liveness-review",
        help="Export a deterministic anonymous frozen-scene A/B review package.",
    )
    review_export_parser.add_argument("--manifest", type=Path, required=True)
    review_export_parser.add_argument("--output-dir", type=Path, required=True)
    review_export_parser.add_argument("--randomization-seed", required=True)
    review_export_parser.set_defaults(func=_export_liveness_review_command)

    review_analyze_parser = subparsers.add_parser(
        "analyze-liveness-review",
        help="Analyze anonymous ratings with scenario-cluster bootstrap intervals.",
    )
    review_analyze_parser.add_argument("--answer-key", type=Path, required=True)
    review_analyze_parser.add_argument("--ratings", type=Path, action="append", required=True)
    review_analyze_parser.add_argument("--output", type=Path)
    review_analyze_parser.add_argument("--bootstrap-samples", type=int, default=10_000)
    review_analyze_parser.add_argument("--bootstrap-seed", type=int, default=0)
    review_analyze_parser.set_defaults(func=_analyze_liveness_review_command)

    live_reaper_parser = subparsers.add_parser(
        "run-live-run-reaper",
        help="Recover or terminate live runs whose worker lease expired.",
    )
    live_reaper_parser.add_argument(
        "--once",
        action="store_true",
        help="Process at most one orphaned run, then exit.",
    )
    live_reaper_parser.add_argument(
        "--poll-seconds",
        type=float,
        default=settings.live_run_reaper_poll_seconds,
    )
    live_reaper_parser.add_argument(
        "--stale-grace-seconds",
        type=float,
        default=settings.live_run_reaper_stale_grace_seconds,
    )
    live_reaper_parser.add_argument(
        "--backoff-seconds",
        type=float,
        default=settings.live_run_reaper_backoff_seconds,
    )
    live_reaper_parser.add_argument(
        "--max-attempts",
        type=int,
        default=settings.live_run_reaper_max_attempts,
    )
    live_reaper_parser.add_argument(
        "--heartbeat-seconds",
        type=float,
        default=settings.live_run_reaper_heartbeat_seconds,
    )
    live_reaper_parser.set_defaults(func=_run_live_run_reaper_command)

    reaper_probe_parser = subparsers.add_parser(
        "check-live-run-reaper",
        help="Exit successfully when a reaper database heartbeat is fresh.",
    )
    reaper_probe_parser.add_argument(
        "--max-age-seconds",
        type=float,
        default=settings.live_run_reaper_probe_max_age_seconds,
    )
    reaper_probe_parser.set_defaults(func=_check_live_run_reaper_command)

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

    redact_private_memory_parser = subparsers.add_parser(
        "redact-private-round-memory",
        help="Dry-run or apply redaction of leaked private round-memory events and voices.",
    )
    redact_private_memory_parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply the cleanup in one transaction. Without this flag the command is a dry-run.",
    )
    redact_private_memory_parser.set_defaults(func=_redact_private_round_memory_command)

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


def _run_game_command(args: argparse.Namespace) -> int:
    db = SessionLocal()
    try:
        default_model = (
            default_model_name()
            if args.villager_model is None or args.werewolf_model is None
            else None
        )
        compiled = resolve_rule_set_snapshot(
            freeze_rule_set_snapshot(get_rule_set(DEFAULT_RULE_SET_ID))
        )
        result = run_game(
            record_store=DatabaseReplayStore(db),
            compiled_rule_set=compiled,
            villager_model=args.villager_model or default_model,
            werewolf_model=args.werewolf_model or default_model,
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
    print(f"匹配={result.matched_count} 删除={result.deleted_count} 跳过={result.skipped_count}")
    if not args.yes and result.matched_count:
        print("未传入 --yes，未删除旧对局目录。")
    return 0


def _redact_private_round_memory_command(args: argparse.Namespace) -> int:
    with SessionLocal() as db:
        try:
            result = cleanup_private_round_memory(db, apply=args.apply)
            if args.apply:
                db.commit()
            else:
                db.rollback()
        except Exception as exc:
            db.rollback()
            print(f"私密回合记忆清理失败: {exc}", file=sys.stderr)
            return 1

    mode = "apply" if result.applied else "dry-run"
    print(
        f"模式={mode} run={result.run_count} 事件={result.event_count} "
        f"语音={result.voice_count} 音频块={result.audio_chunk_count} "
        f"失败={result.failure_count}"
    )
    if not result.applied and (result.event_count or result.voice_count):
        print("未传入 --apply，数据库未修改。")
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


def _run_live_voice_materializer_command(args: argparse.Namespace) -> int:
    if not 0.1 <= args.poll_seconds <= 60:
        print("--poll-seconds must be between 0.1 and 60", file=sys.stderr)
        return 2

    stop_event = Event()
    worker_id = f"live-voice-materializer-{uuid4().hex}"
    telemetry = RuntimeWorkerTelemetry(
        SessionLocal,
        worker_id=worker_id,
        worker_type=LIVE_VOICE_MATERIALIZER_WORKER_TYPE,
        heartbeat_seconds=settings.live_voice_materializer_heartbeat_seconds,
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
        processed_count = run_voice_materializer_worker(
            SessionLocal,
            config=_live_voice_tts_config(),
            worker_id=worker_id,
            stop_event=stop_event,
            poll_seconds=args.poll_seconds,
            once=args.once,
            lease_seconds=settings.live_voice_materializer_lease_seconds,
            max_attempts=settings.live_voice_materializer_max_attempts,
            backoff_seconds=settings.live_voice_materializer_backoff_seconds,
            on_job=lambda key: print(
                f"run_id={key[0]} source_event_id={key[1]} speaker_kind={key[2]}",
                flush=True,
            ),
        )
    except Exception as exc:
        print(f"live voice materializer failed: {type(exc).__name__}", file=sys.stderr)
        return 1
    finally:
        if telemetry_started:
            telemetry.stop()
        for signal_number, handler in previous_handlers.items():
            signal.signal(signal_number, handler)

    if args.once and processed_count == 0:
        print("voice_job=none")
    return 0


def _check_live_voice_materializer_command(args: argparse.Namespace) -> int:
    if not 5 <= args.max_age_seconds <= 300:
        print("--max-age-seconds must be between 5 and 300", file=sys.stderr)
        return 2
    try:
        with SessionLocal() as db:
            alive = runtime_worker_is_alive(
                db,
                worker_type=LIVE_VOICE_MATERIALIZER_WORKER_TYPE,
                max_age_seconds=args.max_age_seconds,
            )
    except Exception as exc:
        print(f"live_voice_materializer=unknown error={type(exc).__name__}", file=sys.stderr)
        return 2
    print("live_voice_materializer=ok" if alive else "live_voice_materializer=stale")
    return 0 if alive else 1


def _run_quality_evaluator_command(args: argparse.Namespace) -> int:
    if not 0.1 <= args.poll_seconds <= 60:
        print("--poll-seconds must be between 0.1 and 60", file=sys.stderr)
        return 2
    if not settings.quality_evaluation_enabled:
        print("quality evaluation is disabled", file=sys.stderr)
        return 2
    if not settings.quality_evaluation_hmac_key:
        print("quality evaluation HMAC key is unavailable", file=sys.stderr)
        return 2

    stop_event = Event()
    worker_id = f"quality-evaluator-{uuid4().hex}"
    telemetry = RuntimeWorkerTelemetry(
        SessionLocal,
        worker_id=worker_id,
        worker_type=QUALITY_EVALUATION_WORKER_TYPE,
        heartbeat_seconds=settings.quality_evaluation_heartbeat_seconds,
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
        processed_count = run_quality_evaluation_worker(
            SessionLocal,
            hmac_key=settings.quality_evaluation_hmac_key,
            worker_id=worker_id,
            stop_event=stop_event,
            poll_seconds=args.poll_seconds,
            once=args.once,
            lease_seconds=settings.quality_evaluation_lease_seconds,
            max_attempts=settings.quality_evaluation_max_attempts,
            backoff_seconds=settings.quality_evaluation_backoff_seconds,
            on_job=lambda evaluation_id: print(f"evaluation_id={evaluation_id}", flush=True),
        )
    except Exception as exc:
        print(f"quality evaluator failed: {type(exc).__name__}", file=sys.stderr)
        return 1
    finally:
        if telemetry_started:
            telemetry.stop()
        for signal_number, handler in previous_handlers.items():
            signal.signal(signal_number, handler)

    if args.once and processed_count == 0:
        print("evaluation_id=none")
    return 0


def _check_quality_evaluator_command(args: argparse.Namespace) -> int:
    if not 5 <= args.max_age_seconds <= 300:
        print("--max-age-seconds must be between 5 and 300", file=sys.stderr)
        return 2
    try:
        with SessionLocal() as db:
            alive = runtime_worker_is_alive(
                db,
                worker_type=QUALITY_EVALUATION_WORKER_TYPE,
                max_age_seconds=args.max_age_seconds,
            )
    except Exception as exc:
        print(f"quality_evaluator=unknown error={type(exc).__name__}", file=sys.stderr)
        return 2
    print("quality_evaluator=ok" if alive else "quality_evaluator=stale")
    return 0 if alive else 1


def _backfill_quality_evaluations_command(args: argparse.Namespace) -> int:
    if not 1 <= args.limit <= 1000:
        print("--limit must be between 1 and 1000", file=sys.stderr)
        return 2
    try:
        since = datetime.fromisoformat(args.since) if args.since else None
    except ValueError:
        print("--since must be an ISO-8601 datetime", file=sys.stderr)
        return 2
    with SessionLocal() as db:
        try:
            result = enqueue_recent_missing_evaluations(
                db,
                evaluator_version=settings.quality_evaluation_version,
                session_id=args.session_id,
                since=since,
                limit=args.limit,
                dry_run=not args.apply,
            )
            if args.apply:
                db.commit()
            else:
                db.rollback()
        except Exception as exc:
            db.rollback()
            print(f"quality backfill failed: {type(exc).__name__}", file=sys.stderr)
            return 1
    print(
        f"mode={'apply' if args.apply else 'dry-run'} matched={result['matched']} "
        f"enqueued={result['enqueued']} skipped={result['skipped']}"
    )
    return 0


def _export_liveness_review_command(args: argparse.Namespace) -> int:
    try:
        manifest = load_manifest(args.manifest)
        package = build_review_package(
            manifest,
            randomization_seed=args.randomization_seed,
        )
        write_review_package(
            package,
            args.output_dir,
            media_root=args.manifest.parent,
        )
    except Exception as exc:
        print(f"liveness review export failed: {exc}", file=sys.stderr)
        return 1
    print(
        f"review_id={package.reviewer_packet['review_id']} "
        f"items={len(package.reviewer_packet['items'])} output={args.output_dir}"
    )
    return 0


def _analyze_liveness_review_command(args: argparse.Namespace) -> int:
    try:
        answer_key = json.loads(args.answer_key.read_text(encoding="utf-8"))
        ratings = [rating for path in args.ratings for rating in load_ratings(path)]
        result = analyze_review_ratings(
            answer_key=answer_key,
            ratings=ratings,
            bootstrap_samples=args.bootstrap_samples,
            bootstrap_seed=args.bootstrap_seed,
        )
        rendered = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True)
        if args.output is not None:
            args.output.write_text(rendered + "\n", encoding="utf-8")
        else:
            print(rendered)
    except Exception as exc:
        print(f"liveness review analysis failed: {exc}", file=sys.stderr)
        return 1
    return 0


def _live_voice_tts_config() -> VolcengineTtsConfig:
    return VolcengineTtsConfig(
        enabled=settings.ark_tts_enabled,
        api_key=settings.ark_tts_api_key,
        resource_id=settings.ark_tts_resource_id,
        ws_url=settings.ark_tts_ws_url,
        player_speaker=settings.ark_tts_player_speaker,
        judge_speaker=settings.ark_tts_judge_speaker,
        audio_format=settings.ark_tts_audio_format,
        sample_rate=settings.ark_tts_sample_rate,
    )


def _run_live_run_reaper_command(args: argparse.Namespace) -> int:
    if not 1 <= args.poll_seconds <= 60:
        print("--poll-seconds must be between 1 and 60", file=sys.stderr)
        return 2
    if not 0 <= args.stale_grace_seconds <= 600:
        print("--stale-grace-seconds must be between 0 and 600", file=sys.stderr)
        return 2
    if not 5 <= args.backoff_seconds <= 3600:
        print("--backoff-seconds must be between 5 and 3600", file=sys.stderr)
        return 2
    if not 1 <= args.max_attempts <= 10:
        print("--max-attempts must be between 1 and 10", file=sys.stderr)
        return 2
    if not 1 <= args.heartbeat_seconds <= 60:
        print("--heartbeat-seconds must be between 1 and 60", file=sys.stderr)
        return 2

    from app.api.routes.games import SessionLiveStore

    registry = LiveRunRegistry(
        live_store=SessionLiveStore(SessionLocal),
        lease_seconds=settings.live_run_lease_seconds,
        heartbeat_seconds=settings.live_run_heartbeat_seconds,
        event_poll_seconds=settings.live_run_event_poll_seconds,
    )
    stop_event = Event()
    telemetry = RuntimeWorkerTelemetry(
        SessionLocal,
        worker_id=registry.worker_id,
        heartbeat_seconds=args.heartbeat_seconds,
    )

    def request_stop(_signum: int, _frame: object) -> None:
        stop_event.set()

    def report(result: OrphanRecoveryResult) -> None:
        print(
            f"run_id={result.run_id} outcome={result.outcome} attempt={result.attempt}",
            flush=True,
        )
        telemetry.record_recovery(result)

    previous_handlers = {
        signal_number: signal.signal(signal_number, request_stop)
        for signal_number in (signal.SIGINT, signal.SIGTERM)
    }
    telemetry_started = False
    try:
        telemetry.start()
        telemetry_started = True
        processed_count = run_live_run_reaper(
            SessionLocal,
            registry,
            stop_event=stop_event,
            poll_seconds=args.poll_seconds,
            stale_grace_seconds=args.stale_grace_seconds,
            backoff_seconds=args.backoff_seconds,
            max_attempts=args.max_attempts,
            once=args.once,
            on_recovery=report,
            on_scan=telemetry.record_scan,
            on_error=telemetry.record_error,
        )
    except Exception as exc:
        print(f"live run reaper failed: {type(exc).__name__}", file=sys.stderr)
        return 1
    finally:
        if telemetry_started:
            telemetry.stop()
        for signal_number, handler in previous_handlers.items():
            signal.signal(signal_number, handler)

    if args.once and processed_count == 0:
        print("run_id=none")
    return 0


def _check_live_run_reaper_command(args: argparse.Namespace) -> int:
    if not 5 <= args.max_age_seconds <= 300:
        print("--max-age-seconds must be between 5 and 300", file=sys.stderr)
        return 2
    try:
        with SessionLocal() as db:
            alive = live_run_reaper_is_alive(
                db,
                max_age_seconds=args.max_age_seconds,
            )
    except Exception as exc:
        print(f"reaper=unknown error={type(exc).__name__}", file=sys.stderr)
        return 2
    print("reaper=ok" if alive else "reaper=stale")
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
