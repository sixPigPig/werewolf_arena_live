from __future__ import annotations

import pytest

from app.werewolf.checkpoint import action_log_from_dict
from app.werewolf.execution_budget import ModelDeadlineExceeded
from app.werewolf.execution_telemetry import (
    render_action_execution_metrics,
    reset_action_execution_metrics_for_tests,
)
from app.werewolf.lm import FakeProvider, generate_action_with_events


class CapturingSink:
    def __init__(self) -> None:
        self.events: list[dict[str, object]] = []

    def publish(self, event_type: str, **kwargs: object) -> None:
        self.events.append({"type": event_type, **kwargs})


def _world_state() -> dict[str, object]:
    return {
        "name": "Alice",
        "role": "女巫",
        "round": 1,
        "observations": [],
        "remaining_players": "Alice、Bob、Carol",
        "debate": [],
        "bidding_rationale": "",
        "personality": "",
        "rule_text": "你正在进行一局数字版狼人杀。",
        "werewolf_context": "",
        "debate_turns_left": 0,
        "options": ["Bob", "Carol", "不使用毒药"],
    }


def test_each_provider_attempt_has_one_terminal_result_and_shared_action_id() -> None:
    reset_action_execution_metrics_for_tests()
    sink = CapturingSink()
    provider = FakeProvider(
        [
            {"reasoning": "非法候选", "poison": "Nobody"},
            {"reasoning": "合法候选", "poison": "Bob"},
        ]
    )
    request_ids = iter(["req_invalid", "req_valid"])

    value, log = generate_action_with_events(
        provider=provider,
        action="witch_poison",
        world_state=_world_state(),
        model="deepseek-chat",
        allowed_values=["Bob", "Carol", "不使用毒药"],
        result_key="poison",
        retries=2,
        event_sink=sink,
        event_context={
            "round_number": 1,
            "phase": "night",
            "actor": "Alice",
            "action": "witch_poison",
        },
        action_id_factory=lambda: "act_shared",
        request_id_factory=lambda: next(request_ids),
        enable_progress_ticks=False,
    )

    assert value == "Bob"
    assert log.action_id == "act_shared"
    assert log.request_id == "req_valid"
    assert log.invalid_attempts[0]["action_id"] == "act_shared"
    assert log.invalid_attempts[0]["request_id"] == "req_invalid"
    assert log.attempt_outcomes == [
        {
            "action_id": "act_shared",
            "request_id": "req_invalid",
            "attempt_result": "invalid_response",
        },
        {
            "action_id": "act_shared",
            "request_id": "req_valid",
            "attempt_result": "valid_response",
        },
    ]
    assert log.to_dict()["attempt_outcomes"] == log.attempt_outcomes
    terminals = [
        event
        for event in sink.events
        if event["type"] in {"model_attempt_completed", "model_request_failed"}
    ]
    assert [event["payload"]["attempt_result"] for event in terminals] == [
        "invalid_response",
        "valid_response",
    ]
    assert {event["payload"]["action_id"] for event in terminals} == {"act_shared"}
    assert [event["payload"]["request_id"] for event in terminals] == [
        "req_invalid",
        "req_valid",
    ]
    metrics = render_action_execution_metrics()
    assert 'werewolf_model_attempt_total{result="invalid_response"} 1' in metrics
    assert 'werewolf_model_attempt_total{result="valid_response"} 1' in metrics


def test_deadline_failure_is_a_timed_out_attempt_without_private_error_text() -> None:
    reset_action_execution_metrics_for_tests()
    sink = CapturingSink()

    class DeadlineProvider:
        def complete_json(self, *, model: str, prompt: str, temperature: float) -> str:
            del model, prompt, temperature
            raise ModelDeadlineExceeded("SENTINEL_PRIVATE_TIMEOUT")

    with pytest.raises(ModelDeadlineExceeded) as error:
        generate_action_with_events(
            provider=DeadlineProvider(),
            action="witch_poison",
            world_state=_world_state(),
            model="deepseek-chat",
            allowed_values=["Bob", "Carol", "不使用毒药"],
            result_key="poison",
            event_sink=sink,
            event_context={
                "round_number": 1,
                "phase": "night",
                "actor": "Alice",
                "action": "witch_poison",
            },
            action_id_factory=lambda: "act_timeout",
            request_id_factory=lambda: "req_timeout",
            enable_progress_ticks=False,
        )

    assert getattr(error.value, "attempt_outcomes") == [
        {
            "action_id": "act_timeout",
            "request_id": "req_timeout",
            "attempt_result": "timed_out",
        }
    ]
    assert "SENTINEL_PRIVATE_TIMEOUT" not in str(
        getattr(error.value, "attempt_outcomes")
    )
    failure = next(event for event in sink.events if event["type"] == "model_request_failed")
    assert failure["payload"] == {
        "request_id": "req_timeout",
        "model": "deepseek-chat",
        "message": "模型请求失败，正在中止本次行动",
        "attempt_result": "timed_out",
        "action_id": "act_timeout",
    }
    assert "SENTINEL_PRIVATE_TIMEOUT" not in str(sink.events)
    metrics = render_action_execution_metrics()
    assert 'werewolf_model_attempt_total{result="timed_out"} 1' in metrics


def test_checkpoint_restore_whitelists_attempt_outcome_ledger() -> None:
    restored = action_log_from_dict(
        {
            "actor": "Alice",
            "action": "vote",
            "options": ["Bob"],
            "choice": "Bob",
            "lm_log": {
                "prompt": "",
                "raw_response": "",
                "result": {"vote": "Bob"},
                "attempt_outcomes": [
                    {
                        "action_id": "act_safe",
                        "request_id": "req_safe",
                        "attempt_result": "valid_response",
                        "raw_response": "SENTINEL_PRIVATE_RESPONSE",
                    },
                    {
                        "action_id": "act_safe",
                        "request_id": "req_safe",
                        "attempt_result": "transport_failed",
                    },
                    {
                        "action_id": "SENTINEL_PRIVATE_ACTION",
                        "request_id": "req_unknown",
                        "attempt_result": "private_provider_error",
                    },
                    {
                        "action_id": "act_malformed",
                        "request_id": "req_malformed",
                        "attempt_result": ["valid_response"],
                    },
                ],
            },
        }
    )

    assert restored.lm_log.attempt_outcomes == [
        {
            "action_id": "act_safe",
            "request_id": "req_safe",
            "attempt_result": "valid_response",
        }
    ]
    serialized = restored.to_dict()
    assert serialized["lm_log"]["attempt_outcomes"] == restored.lm_log.attempt_outcomes
    assert "SENTINEL_PRIVATE" not in str(serialized)
