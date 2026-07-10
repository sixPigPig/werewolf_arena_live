from __future__ import annotations

from collections import defaultdict, deque
from threading import Lock
from time import monotonic


class SlidingWindowRateLimiter:
    def __init__(self, *, max_keys: int = 4096) -> None:
        self._events: dict[str, deque[float]] = defaultdict(deque)
        self._lock = Lock()
        self._last_sweep = 0.0
        self._max_keys = max_keys

    def allow(
        self,
        key: str,
        *,
        limit: int,
        window_seconds: float,
        now: float | None = None,
    ) -> bool:
        timestamp = monotonic() if now is None else now
        cutoff = timestamp - window_seconds
        with self._lock:
            if (
                timestamp - self._last_sweep >= window_seconds
            ):
                self._sweep(cutoff)
                self._last_sweep = timestamp
            if key not in self._events and len(self._events) >= self._max_keys:
                return False
            events = self._events[key]
            while events and events[0] <= cutoff:
                events.popleft()
            if len(events) >= limit:
                return False
            events.append(timestamp)
            return True

    def reset(self) -> None:
        with self._lock:
            self._events.clear()
            self._last_sweep = 0.0

    def _sweep(self, cutoff: float) -> None:
        empty_keys: list[str] = []
        for key, events in self._events.items():
            while events and events[0] <= cutoff:
                events.popleft()
            if not events:
                empty_keys.append(key)
        for key in empty_keys:
            self._events.pop(key, None)


public_session_creation_limiter = SlidingWindowRateLimiter()
public_favorite_write_limiter = SlidingWindowRateLimiter()
