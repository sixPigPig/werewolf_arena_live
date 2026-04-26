from __future__ import annotations

import time
from collections.abc import Callable
from typing import Literal, cast

EventPacingMode = Literal["off", "standard", "slow"]
SUPPORTED_EVENT_PACING = ("off", "standard", "slow")

_STANDARD_DELAYS: dict[str, float] = {
    "phase_started": 1.0,
    "action_requested": 1.0,
    "model_response_received": 1.5,
    "action_parsed": 1.0,
    "state_updated": 1.5,
    "game_completed": 2.0,
    "game_failed": 2.0,
}

_SLOW_DELAYS: dict[str, float] = {
    "phase_started": 3.0,
    "action_requested": 3.0,
    "model_response_received": 4.0,
    "action_parsed": 3.0,
    "state_updated": 4.0,
    "game_completed": 4.0,
    "game_failed": 4.0,
}


def validate_event_pacing(value: str) -> EventPacingMode:
    if value not in SUPPORTED_EVENT_PACING:
        raise ValueError(f"Unsupported event pacing mode: {value}")
    return cast(EventPacingMode, value)


class EventPacer:
    def __init__(
        self,
        mode: EventPacingMode,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        self.mode = validate_event_pacing(mode)
        self._sleeper = sleeper

    def delay_for(self, event_type: str) -> float:
        if self.mode == "off":
            return 0.0
        if self.mode == "standard":
            return _STANDARD_DELAYS.get(event_type, 0.0)
        return _SLOW_DELAYS.get(event_type, 0.0)

    def wait(self, event_type: str) -> None:
        delay = self.delay_for(event_type)
        if delay > 0:
            self._sleeper(delay)
