from __future__ import annotations

from app.core.config import settings
from app.match.action_engine import _ModelAttemptProgressTrace
from app.match.model_client import ModelProgress


def _stream_delta(elapsed_ms: int, text_delta_count: int) -> ModelProgress:
    return ModelProgress(
        stage="stream_delta",
        provider_request_id="req_1",
        elapsed_ms=elapsed_ms,
        text_delta="x",
        text_delta_count=text_delta_count,
        text_character_count=text_delta_count * 2,
    )


def test_stream_progress_persisted_at_min_interval() -> None:
    trace = _ModelAttemptProgressTrace()
    with_settings = settings.live_v2_stream_progress_min_interval_ms

    first = trace.accept(_stream_delta(100, 1))
    assert first is not None and first[0] == "model_stream_progress"

    assert trace.accept(_stream_delta(1000, 2)) is None
    assert trace.accept(_stream_delta(2000, 3)) is None

    threshold_event = trace.accept(_stream_delta(100 + with_settings, 4))
    assert threshold_event is not None

    assert trace.accept(_stream_delta(100 + with_settings + 100, 5)) is None


def test_stream_progress_counters_stay_exact_when_throttled() -> None:
    trace = _ModelAttemptProgressTrace()
    trace.accept(_stream_delta(0, 1))
    trace.accept(_stream_delta(100, 2))
    trace.accept(_stream_delta(200, 3))

    assert trace.text_delta_count == 3
    assert trace.text_character_count == 6
    assert trace.last_stream_event_ms == 0


def test_stream_progress_zero_interval_persists_every_delta(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "live_v2_stream_progress_min_interval_ms", 0)
    trace = _ModelAttemptProgressTrace()

    events = [trace.accept(_stream_delta(ms, ms)) for ms in (0, 100, 200, 300)]

    assert all(event is not None for event in events)


def test_non_delta_stages_bypass_throttle() -> None:
    trace = _ModelAttemptProgressTrace()

    queued = trace.accept(
        ModelProgress(
            stage="queued",
            provider_request_id="req_1",
            elapsed_ms=10,
            provider="agent_plan",
        )
    )
    admitted = trace.accept(
        ModelProgress(
            stage="admitted",
            provider_request_id="req_1",
            elapsed_ms=20,
        )
    )
    headers = trace.accept(
        ModelProgress(
            stage="response_headers",
            provider_request_id="req_1",
            elapsed_ms=30,
            response_headers={},
        )
    )
    first_token = trace.accept(
        ModelProgress(
            stage="first_token",
            provider_request_id="req_1",
            elapsed_ms=40,
            token_kind="reasoning",
        )
    )

    assert queued is not None and queued[0] == "model_request_queued"
    assert admitted is not None and admitted[0] == "model_request_admitted"
    assert headers is not None and headers[0] == "model_response_headers_received"
    assert first_token is not None and first_token[0] == "model_first_token_received"
