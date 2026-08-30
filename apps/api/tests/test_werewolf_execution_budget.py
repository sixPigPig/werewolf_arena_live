import pytest

from app.shared.execution_budget import (
    ActionExecutionBudgetV1,
    ModelDeadlineExceeded,
)


@pytest.mark.parametrize(
    ("action", "kind", "total", "batch", "first_token"),
    [
        ("vote", "required_discrete", 15.0, 15.0, None),
        ("witch_poison", "optional_discrete", 12.0, 12.0, None),
        ("debate", "public_speech", 45.0, None, 10.0),
        ("werewolf_discuss", "private_text", 25.0, 25.0, 8.0),
    ],
)
def test_action_execution_budget_classifies_actions(
    action: str,
    kind: str,
    total: float,
    batch: float | None,
    first_token: float | None,
) -> None:
    spec = ActionExecutionBudgetV1().for_action(action)

    assert spec.kind == kind
    assert spec.total_budget_seconds == total
    assert spec.batch_deadline_seconds == batch
    assert spec.first_token_timeout_seconds == first_token


def test_model_call_attempts_keep_deadline_and_reduce_request_timeout() -> None:
    options = ActionExecutionBudgetV1().for_action("vote").call_options(100.0)

    first = options.for_attempt(101.0)
    late = options.for_attempt(114.5)

    assert first.deadline_at_monotonic == late.deadline_at_monotonic == 115.0
    assert first.request_timeout_seconds == 12.0
    assert late.request_timeout_seconds == 0.5
    with pytest.raises(ModelDeadlineExceeded):
        options.for_attempt(115.0)
