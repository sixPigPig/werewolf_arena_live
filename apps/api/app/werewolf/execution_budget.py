from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Literal


ActionBudgetKind = Literal[
    "required_discrete",
    "optional_discrete",
    "public_speech",
    "private_text",
]

PUBLIC_SPEECH_ACTIONS = frozenset(
    {"debate", "sheriff_speech", "sheriff_pk_speech", "exile_pk_speech", "exile_last_words"}
)
OPTIONAL_DISCRETE_ACTIONS = frozenset(
    {
        "witch_save",
        "witch_poison",
        "hunter_shoot",
        "werewolf_self_explosion",
        "sheriff_withdraw",
        "sheriff_badge",
    }
)
PRIVATE_TEXT_ACTIONS = frozenset({"werewolf_discuss", "summarize"})


class ModelDeadlineExceeded(TimeoutError):
    pass


@dataclass(frozen=True)
class ModelCallOptions:
    deadline_at_monotonic: float
    request_timeout_seconds: float
    first_token_timeout_seconds: float | None = None
    max_output_tokens: int | None = None

    def remaining_seconds(self, now: float) -> float:
        return max(0.0, self.deadline_at_monotonic - now)

    def for_attempt(self, now: float) -> "ModelCallOptions":
        remaining = self.remaining_seconds(now)
        if remaining <= 0:
            raise ModelDeadlineExceeded("model action deadline exceeded")
        return replace(
            self,
            request_timeout_seconds=min(self.request_timeout_seconds, remaining),
            first_token_timeout_seconds=(
                min(self.first_token_timeout_seconds, remaining)
                if self.first_token_timeout_seconds is not None
                else None
            ),
        )


@dataclass(frozen=True)
class ActionBudgetSpecV1:
    kind: ActionBudgetKind
    request_timeout_seconds: float
    total_budget_seconds: float
    batch_deadline_seconds: float | None
    first_token_timeout_seconds: float | None = None
    max_output_tokens: int | None = None

    def call_options(self, started_at_monotonic: float) -> ModelCallOptions:
        return ModelCallOptions(
            deadline_at_monotonic=(
                started_at_monotonic + self.total_budget_seconds
            ),
            request_timeout_seconds=self.request_timeout_seconds,
            first_token_timeout_seconds=self.first_token_timeout_seconds,
            max_output_tokens=self.max_output_tokens,
        )


@dataclass(frozen=True)
class ActionExecutionBudgetV1:
    schema_version: int = 1
    required_request_seconds: float = 12.0
    required_total_seconds: float = 15.0
    required_batch_seconds: float = 15.0
    optional_request_seconds: float = 10.0
    optional_total_seconds: float = 12.0
    optional_batch_seconds: float = 12.0
    public_speech_request_seconds: float = 45.0
    public_speech_total_seconds: float = 45.0
    public_speech_first_token_seconds: float = 10.0
    private_text_request_seconds: float = 25.0
    private_text_total_seconds: float = 25.0
    private_text_batch_seconds: float = 25.0
    private_text_first_token_seconds: float = 8.0

    def for_action(self, action: str) -> ActionBudgetSpecV1:
        if action in PUBLIC_SPEECH_ACTIONS:
            return ActionBudgetSpecV1(
                kind="public_speech",
                request_timeout_seconds=self.public_speech_request_seconds,
                total_budget_seconds=self.public_speech_total_seconds,
                batch_deadline_seconds=None,
                first_token_timeout_seconds=self.public_speech_first_token_seconds,
            )
        if action in OPTIONAL_DISCRETE_ACTIONS:
            return ActionBudgetSpecV1(
                kind="optional_discrete",
                request_timeout_seconds=self.optional_request_seconds,
                total_budget_seconds=self.optional_total_seconds,
                batch_deadline_seconds=self.optional_batch_seconds,
            )
        if action in PRIVATE_TEXT_ACTIONS:
            return ActionBudgetSpecV1(
                kind="private_text",
                request_timeout_seconds=self.private_text_request_seconds,
                total_budget_seconds=self.private_text_total_seconds,
                batch_deadline_seconds=self.private_text_batch_seconds,
                first_token_timeout_seconds=self.private_text_first_token_seconds,
            )
        return ActionBudgetSpecV1(
            kind="required_discrete",
            request_timeout_seconds=self.required_request_seconds,
            total_budget_seconds=self.required_total_seconds,
            batch_deadline_seconds=self.required_batch_seconds,
        )
