from __future__ import annotations

from app.werewolf.lm import LmLog
from app.werewolf.models import ActionLog


def test_timeout_fallback_keeps_model_and_effective_results_separate() -> None:
    action = ActionLog(
        actor="1号玩家",
        action="vote",
        options=["2号玩家", "3号玩家"],
        choice="3号玩家",
        lm_log=LmLog(
            prompt="",
            raw_response="",
            result={"vote": "3号玩家"},
            attempt_outcomes=[
                {
                    "action_id": "act_1",
                    "request_id": "req_1",
                    "attempt_result": "timed_out",
                }
            ],
        ),
        fallback_choice="3号玩家",
        fallback_reason="timeout_deterministic_legal_choice",
        reason_code="timeout_deterministic_legal_choice",
        effective_origin="system_fallback",
        execution_status="fallback",
    )

    payload = action.to_dict()

    assert payload["model_result"] == {
        "status": "timed_out",
        "choice": None,
        "reasoning": None,
        "attempt_ids": ["req_1"],
    }
    assert payload["effective_result"] == {
        "origin": "system_fallback",
        "choice": "3号玩家",
        "reason_code": "timeout_deterministic_legal_choice",
    }
    assert payload["lifecycle_status"] == "fallback"


def test_rule_default_without_provider_attempt_is_not_model_output() -> None:
    action = ActionLog(
        actor="1号玩家",
        action="sheriff_badge",
        options=["撕毁警徽"],
        choice="撕毁警徽",
        lm_log=LmLog(
            prompt="",
            raw_response="",
            result={"badge": "撕毁警徽"},
        ),
        fallback_choice="撕毁警徽",
        fallback_reason="rule_default",
        reason_code="rule_default",
        effective_origin="system_fallback",
        execution_status="fallback",
    )

    payload = action.to_dict()

    assert payload["model_result"] == {
        "status": "not_requested",
        "choice": None,
        "reasoning": None,
        "attempt_ids": [],
    }
    assert payload["effective_result"]["origin"] == "system_fallback"
    assert payload["effective_result"]["reason_code"] == "rule_default"


def test_rule_default_after_timeout_keeps_model_timeout_status() -> None:
    action = ActionLog(
        actor="1号玩家",
        action="sheriff_badge",
        options=["2号玩家", "撕毁警徽"],
        choice="撕毁警徽",
        lm_log=LmLog(
            prompt="",
            raw_response="",
            result={"badge": "撕毁警徽"},
            attempt_outcomes=[
                {
                    "action_id": "act_badge",
                    "request_id": "req_badge",
                    "attempt_result": "timed_out",
                }
            ],
        ),
        fallback_choice="撕毁警徽",
        fallback_reason="timeout_rule_default_badge_destroy",
        reason_code="rule_default",
        effective_origin="system_fallback",
        execution_status="fallback",
    )

    payload = action.to_dict()

    assert payload["model_result"]["status"] == "timed_out"
    assert payload["model_result"]["choice"] is None
    assert payload["effective_result"] == {
        "origin": "system_fallback",
        "choice": "撕毁警徽",
        "reason_code": "rule_default",
    }


def test_canceled_action_never_has_effective_choice_or_fallback() -> None:
    action = ActionLog(
        actor="4号玩家",
        action="debate",
        options=[],
        choice=None,
        lm_log=LmLog(prompt="", raw_response="", result=None),
        reason_code="self_explosion_cancelled",
        effective_origin="none",
        execution_status="canceled",
    )

    payload = action.to_dict()

    assert payload["model_result"]["status"] == "canceled"
    assert payload["effective_result"] == {
        "origin": "none",
        "choice": None,
        "reason_code": "self_explosion_cancelled",
    }
    assert payload["lifecycle_status"] == "canceled"
    assert payload["fallback_reason"] is None
