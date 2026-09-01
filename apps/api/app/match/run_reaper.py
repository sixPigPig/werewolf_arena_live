from __future__ import annotations

import asyncio
import logging

from sqlalchemy.orm import Session, sessionmaker

from app.match.repository import ActionRepository

logger = logging.getLogger(__name__)


class RunReaper:
    """Periodically fails active V2 runs whose execution lease has expired.

    Without this, a worker that dies mid-run (process exit, machine sleep)
    leaves the game stuck in an active status forever.
    """

    def __init__(
        self,
        *,
        session_factory: sessionmaker[Session],
        interval_seconds: float,
        grace_seconds: float,
    ) -> None:
        self._repository = ActionRepository(session_factory)
        self._interval_seconds = interval_seconds
        self._grace_seconds = grace_seconds
        self._task: asyncio.Task[None] | None = None

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._run_loop(), name="v2-run-reaper")

    async def stop(self) -> None:
        task = self._task
        self._task = None
        if task is None:
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    async def _run_loop(self) -> None:
        while True:
            try:
                reaped = await asyncio.to_thread(
                    self._repository.reap_stale_runs,
                    grace_seconds=self._grace_seconds,
                )
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Live V2 run reaper sweep failed")
            else:
                for entry in reaped:
                    logger.error(
                        "Live V2 run reaped after worker lease expiry",
                        extra={
                            "game_id": entry["game_id"],
                            "run_id": entry["run_id"],
                            "previous_status": entry["previous_status"],
                            "invalidated_worker_id": entry["invalidated_worker_id"],
                        },
                    )
            await asyncio.sleep(self._interval_seconds)
