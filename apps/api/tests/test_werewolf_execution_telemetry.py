from app.werewolf import execution_telemetry
from app.werewolf.execution_telemetry import (
    record_action_batch,
    record_action_execution,
    record_model_progress_event,
    render_action_execution_metrics,
    reset_action_execution_metrics_for_tests,
)


def _record_completed_action(action_id: str) -> None:
    record_action_execution(
        action_kind="required_discrete",
        model="deepseek-chat",
        result="completed",
        duration_ms=100,
        first_token_ms=None,
        fallback_reason=None,
        action_id=action_id,
    )


def test_finalized_action_deduplication_is_bounded(monkeypatch) -> None:
    reset_action_execution_metrics_for_tests()
    monkeypatch.setattr(execution_telemetry, "MAX_FINALIZED_ACTION_IDS", 2)

    _record_completed_action("action-a")
    _record_completed_action("action-a")
    _record_completed_action("action-b")
    _record_completed_action("action-c")
    _record_completed_action("action-a")

    metrics = render_action_execution_metrics()
    assert (
        'werewolf_logical_action_total{action_kind="required_discrete",'
        'provider="deepseek",result="completed"} 4'
    ) in metrics
    assert len(execution_telemetry._FINALIZED_ACTION_IDS) == 2


def test_action_execution_metrics_cover_latency_timeout_fallback_and_batch() -> None:
    reset_action_execution_metrics_for_tests()
    record_action_execution(
        action_kind="public_speech",
        model="doubao-seed-2-0-lite-260215",
        result="completed",
        duration_ms=1250,
        first_token_ms=125,
        fallback_reason=None,
    )
    record_action_execution(
        action_kind="required_discrete",
        model="SENTINEL_PRIVATE_MODEL",
        result="fallback",
        duration_ms=15000,
        first_token_ms=None,
        fallback_reason="SENTINEL_PRIVATE_REASON",
    )
    record_action_execution(
        action_kind="optional_discrete",
        model="deepseek-chat",
        result="fallback",
        duration_ms=12000,
        first_token_ms=None,
        fallback_reason="timeout_optional_abstain",
    )
    record_action_batch(
        action_kind="optional_discrete",
        result="deadline",
        duration_ms=12000,
    )
    record_model_progress_event("model_request_started")
    record_model_progress_event(
        "model_attempt_completed",
        attempt_result="invalid_response",
    )
    record_model_progress_event("model_request_started")
    record_model_progress_event(
        "model_attempt_completed",
        attempt_result="valid_response",
    )

    metrics = render_action_execution_metrics()

    assert (
        "werewolf_model_action_duration_seconds_sum"
        '{action_kind="public_speech",provider="ark_agent_plan",'
        'result="completed"} 1.25'
    ) in metrics
    assert (
        "werewolf_model_first_token_seconds_sum"
        '{action_kind="public_speech",provider="ark_agent_plan",'
        'result="completed"} 0.125'
    ) in metrics
    assert (
        'werewolf_model_timeout_total{action_kind="optional_discrete",'
        'provider="deepseek"} 1'
    ) in metrics
    assert (
        'werewolf_action_fallback_total{action_kind="required_discrete",'
        'reason="other"} 1'
    ) in metrics
    assert (
        "werewolf_action_batch_duration_seconds_sum"
        '{action_kind="optional_discrete",result="deadline"} 12.0'
    ) in metrics
    assert 'werewolf_model_progress_event_total{stage="started"} 2' in metrics
    assert 'werewolf_model_attempt_total{result="invalid_response"} 1' in metrics
    assert 'werewolf_model_attempt_total{result="valid_response"} 1' in metrics
    assert (
        'werewolf_logical_action_total{action_kind="public_speech",'
        'provider="ark_agent_plan",result="completed"} 1'
    ) in metrics
    assert "SENTINEL_PRIVATE" not in metrics
