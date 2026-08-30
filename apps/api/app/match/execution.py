from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Iterator

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.match.models import GameRecord, GameRun


class RunFenceRejected(RuntimeError):
    pass


@dataclass(frozen=True)
class RunFence:
    run_id: str
    worker_id: str
    fence_token: int


_CURRENT_RUN_FENCE: ContextVar[RunFence | None] = ContextVar(
    "current_run_fence",
    default=None,
)


@contextmanager
def bind_run_fence(fence: RunFence) -> Iterator[None]:
    token = _CURRENT_RUN_FENCE.set(fence)
    try:
        yield
    finally:
        _CURRENT_RUN_FENCE.reset(token)


def current_run_fence() -> RunFence | None:
    return _CURRENT_RUN_FENCE.get()


def require_run_fence(
    db: Session,
    game: GameRecord,
    *,
    fence: RunFence | None = None,
    lock: bool = True,
) -> GameRun:
    expected = fence or current_run_fence()
    if expected is None:
        raise RunFenceRejected("v2_run_execution_fence_missing")
    if expected.run_id != game.current_run_id:
        raise RunFenceRejected("v2_run_execution_run_changed")
    statement = select(GameRun).where(GameRun.run_id == game.current_run_id)
    if lock:
        statement = statement.with_for_update()
    run = db.scalar(statement.execution_options(populate_existing=True))
    if run is None:
        raise RunFenceRejected("v2_run_execution_run_missing")
    if run.worker_id != expected.worker_id or run.fence_token != expected.fence_token:
        raise RunFenceRejected("v2_run_execution_lease_lost")
    if run.lease_expires_at is None:
        raise RunFenceRejected("v2_run_execution_lease_missing")
    database_now = database_utc_now(db)
    if _as_utc(run.lease_expires_at) <= _as_utc(database_now):
        raise RunFenceRejected("v2_run_execution_lease_expired")
    return run


def database_utc_now(db: Session) -> datetime:
    """Read the database clock used by lease comparisons and extensions."""
    bind = db.get_bind()
    clock = (
        func.clock_timestamp()
        if bind is not None and bind.dialect.name == "postgresql"
        else func.current_timestamp()
    )
    value = db.scalar(select(clock))
    if not isinstance(value, datetime):
        value = datetime.now(tz=UTC)
    return _as_utc(value)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
