from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


FailureImpact = Literal[
    "expected_control_flow",
    "user_visible_degradation",
    "operational_failure",
]

_EXPECTED_CONTROL_FLOW_CODES = frozenset(
    {
        "pre_exile_pipeline_generation_canceled",
        "pre_exile_pipeline_canceled",
        "day_speech_prefetch_canceled",
    }
)
_USER_VISIBLE_DEGRADATION_CODES = frozenset(
    {
        "day_speech_prefetch_post_close_deadline",
    }
)
_USER_VISIBLE_DEGRADATION_RESOLUTIONS = frozenset(
    {
        "technical_skip",
        "technical_false_fallback",
    }
)


@dataclass(frozen=True)
class ModelFailureImpact:
    failure_impact: FailureImpact | None
    counts_as_failure: bool


def classify_model_failure_impact(
    *,
    has_failure: bool,
    failure_code: str | None,
    failure_category: str | None,
    failure_stage: str | None,
    failure_resolution: str | None,
    provider_activity_observed: bool = False,
) -> ModelFailureImpact:
    """Classify a persisted failure without changing its durable event semantics."""

    if not has_failure:
        return ModelFailureImpact(failure_impact=None, counts_as_failure=False)

    if failure_code in _USER_VISIBLE_DEGRADATION_CODES:
        return ModelFailureImpact(
            failure_impact="user_visible_degradation",
            counts_as_failure=True,
        )

    capacity_not_admitted = failure_code == "model_prefetch_capacity_unavailable" or (
        failure_category == "admission_capacity"
        and failure_stage in {None, "provider_admission"}
    )
    if capacity_not_admitted and not provider_activity_observed:
        return ModelFailureImpact(
            failure_impact="expected_control_flow",
            counts_as_failure=False,
        )

    if failure_code in _EXPECTED_CONTROL_FLOW_CODES:
        return ModelFailureImpact(
            failure_impact="expected_control_flow",
            counts_as_failure=False,
        )

    if failure_resolution in _USER_VISIBLE_DEGRADATION_RESOLUTIONS:
        return ModelFailureImpact(
            failure_impact="user_visible_degradation",
            counts_as_failure=True,
        )

    return ModelFailureImpact(
        failure_impact="operational_failure",
        counts_as_failure=True,
    )
