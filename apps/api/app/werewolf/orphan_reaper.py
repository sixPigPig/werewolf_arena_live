from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import logging
from threading import Event
from typing import Literal

from sqlalchemy.orm import Session, sessionmaker

from app.werewolf.checkpoint import ResumeCheckpointError
from app.werewolf.live import LiveGameRun, LiveRunRegistry, RunRecoveryCandidate
from app.werewolf.replay import DatabaseReplayStore, ReplayNotFoundError


logger = logging.getLogger(__name__)
RecoveryOutcome = Literal["resumed", "canceled", "failed"]
RecoveryExecutor = Callable[[LiveGameRun, LiveRunRegistry], None]


@dataclass(frozen=True)
class OrphanRecoveryResult:
    run_id: str
    session_id: str
    attempt: int
    outcome: RecoveryOutcome


def run_next_orphan_recovery(
    session_factory: sessionmaker[Session],
    registry: LiveRunRegistry,
    *,
    stale_grace_seconds: float,
    backoff_seconds: float,
    max_attempts: int,
    execute_recovery: RecoveryExecutor | None = None,
) -> OrphanRecoveryResult | None:
    now = datetime.now(tz=UTC)
    stale_before = now - timedelta(seconds=stale_grace_seconds)
    candidates = registry.recovery_candidates(
        stale_before=_format_datetime(stale_before),
        now=_format_datetime(now),
        max_attempts=max_attempts,
        limit=20,
    )
    for candidate in candidates:
        result = _claim_and_recover(
            session_factory,
            registry,
            candidate=candidate,
            now=now,
            stale_before=stale_before,
            backoff_seconds=backoff_seconds,
            max_attempts=max_attempts,
            execute_recovery=execute_recovery,
        )
        if result is not None:
            logger.info(
                "live_run_orphan_recovery run_id=%s attempt=%s outcome=%s",
                result.run_id,
                result.attempt,
                result.outcome,
            )
            return result
    return None


def run_live_run_reaper(
    session_factory: sessionmaker[Session],
    registry: LiveRunRegistry,
    *,
    stop_event: Event,
    poll_seconds: float,
    stale_grace_seconds: float,
    backoff_seconds: float,
    max_attempts: int,
    once: bool = False,
    on_recovery: Callable[[OrphanRecoveryResult], None] | None = None,
    on_scan: Callable[[], None] | None = None,
    on_error: Callable[[str], None] | None = None,
    execute_recovery: RecoveryExecutor | None = None,
) -> int:
    processed_count = 0
    while not stop_event.is_set():
        try:
            if on_scan is not None:
                on_scan()
            result = run_next_orphan_recovery(
                session_factory,
                registry,
                stale_grace_seconds=stale_grace_seconds,
                backoff_seconds=backoff_seconds,
                max_attempts=max_attempts,
                execute_recovery=execute_recovery,
            )
        except Exception:
            logger.exception("Live run orphan reaper scan failed")
            if on_error is not None:
                try:
                    on_error("scan_failed")
                except Exception:
                    logger.exception("Failed to persist live run reaper error telemetry")
            if once:
                raise
            result = None
        if result is not None:
            processed_count += 1
            if on_recovery is not None:
                try:
                    on_recovery(result)
                except Exception:
                    logger.exception("Failed to persist live run recovery telemetry")
        if once:
            break
        if result is None:
            stop_event.wait(poll_seconds)
    return processed_count


def _claim_and_recover(
    session_factory: sessionmaker[Session],
    registry: LiveRunRegistry,
    *,
    candidate: RunRecoveryCandidate,
    now: datetime,
    stale_before: datetime,
    backoff_seconds: float,
    max_attempts: int,
    execute_recovery: RecoveryExecutor | None,
) -> OrphanRecoveryResult | None:
    delay = min(backoff_seconds * (2**candidate.recovery_attempts), 24 * 60 * 60)
    run = registry.try_claim_orphan(
        candidate,
        stale_before=_format_datetime(stale_before),
        recovery_not_before=_format_datetime(now + timedelta(seconds=delay)),
        max_attempts=max_attempts,
    )
    if run is None:
        return None
    attempt = run.recovery_attempts
    if run.stop_requested_at is not None:
        registry.mark_canceled(run.run_id)
        return OrphanRecoveryResult(
            run_id=run.run_id,
            session_id=run.session_id,
            attempt=attempt,
            outcome="canceled",
        )

    with session_factory() as db:
        try:
            DatabaseReplayStore(db).load_resume_checkpoint(run.session_id)
        except (ReplayNotFoundError, ResumeCheckpointError):
            registry.mark_failed(
                run.run_id,
                error="Orphaned live run has no valid resume checkpoint",
            )
            return OrphanRecoveryResult(
                run_id=run.run_id,
                session_id=run.session_id,
                attempt=attempt,
                outcome="failed",
            )

    executor = execute_recovery or _execute_recovery
    executor(run, registry)
    final_status = registry.get_run(run.run_id).status
    outcome: RecoveryOutcome = (
        "canceled"
        if final_status == "canceled"
        else "failed"
        if final_status == "failed"
        else "resumed"
    )
    return OrphanRecoveryResult(
        run_id=run.run_id,
        session_id=run.session_id,
        attempt=attempt,
        outcome=outcome,
    )


def _execute_recovery(run: LiveGameRun, registry: LiveRunRegistry) -> None:
    from app.api.routes.games import _resume_game_in_background

    _resume_game_in_background(
        run_id=run.run_id,
        registry=registry,
        session_id=run.session_id,
    )


def _format_datetime(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
