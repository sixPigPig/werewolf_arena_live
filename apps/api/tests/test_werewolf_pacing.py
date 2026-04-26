from __future__ import annotations

import pytest

from app.werewolf.pacing import (
    SUPPORTED_EVENT_PACING,
    EventPacer,
    validate_event_pacing,
)


def test_validate_event_pacing_accepts_supported_modes() -> None:
    assert SUPPORTED_EVENT_PACING == ("off", "standard", "slow")

    assert validate_event_pacing("off") == "off"
    assert validate_event_pacing("standard") == "standard"
    assert validate_event_pacing("slow") == "slow"


def test_validate_event_pacing_rejects_unsupported_mode() -> None:
    with pytest.raises(ValueError, match="Unsupported event pacing mode: fast"):
        validate_event_pacing("fast")


def test_event_pacer_off_does_not_sleep() -> None:
    calls: list[float] = []
    pacer = EventPacer("off", sleeper=calls.append)

    pacer.wait("phase_started")

    assert calls == []


def test_event_pacer_standard_sleeps_for_event_delay() -> None:
    calls: list[float] = []
    pacer = EventPacer("standard", sleeper=calls.append)

    pacer.wait("model_response_received")

    assert calls == [1.5]


def test_event_pacer_slow_sleeps_for_event_delay() -> None:
    calls: list[float] = []
    pacer = EventPacer("slow", sleeper=calls.append)

    pacer.wait("state_updated")

    assert calls == [4.0]
