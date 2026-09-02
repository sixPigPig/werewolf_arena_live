from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Literal


MODEL_GENERATION_POLICY_SCHEMA_VERSION = 6
MODEL_GENERATION_POLICY_SUPPORTED_SCHEMA_VERSIONS = frozenset({4, 6})
MODEL_GENERATION_POLICY_CLASSIFICATION_VERSION = 1
MODEL_GENERATION_POLICY_ENFORCEMENT = "observe_only"
MODEL_GENERATION_POLICY_REASONING_PARAMETER_MODE = "inherit_frozen_model_configuration"

_CONTRACT_KEY = "model_generation_policy_contract"
_UNSUPPORTED_ERROR = "unsupported_model_generation_policy_contract"
_TOP_LEVEL_KEYS_V1 = frozenset(
    {
        "schema_version",
        "classification_version",
        "enforcement",
        "reasoning_parameter_mode",
        "default_profile",
        "profiles",
        "action_profiles",
    }
)
_TOP_LEVEL_KEYS_V2 = frozenset({*_TOP_LEVEL_KEYS_V1, "execution"})
_TOP_LEVEL_KEYS_V3 = _TOP_LEVEL_KEYS_V2
_TOP_LEVEL_KEYS_V4 = _TOP_LEVEL_KEYS_V3
_PROFILE_NAMES = frozenset(
    {
        "strategic_full",
        "recoverable_public_speech",
        "isolated_auxiliary",
    }
)
_PROFILE_KEYS = frozenset(
    {
        "reasoning_only_timeout_ms",
        "timeout_max_attempts",
    }
)
_EXECUTION_KEYS_V2 = frozenset(
    {
        "automatic_retry_enforcement",
        "output_budget_max_attempts",
        "attempt_hard_timeout_max_attempts",
        "transport_max_attempts",
        "post_token_transport_max_attempts",
        "queue_wait_budget_mode",
        "action_wall_timeout_ms",
        "blocking_required_target_output_timeout_mode",
        "blocking_required_target_queue_wait_budget_mode",
        "private_round_memory_mode",
    }
)
_EXECUTION_KEYS_V3 = frozenset({*_EXECUTION_KEYS_V2, "required_target_exhaustion"})
_EXECUTION_KEYS_V4 = _EXECUTION_KEYS_V3
_EXECUTION_KEYS_V6 = frozenset(
    {
        "automatic_retry_enforcement",
        "transport_max_attempts",
        "post_token_transport_max_attempts",
        "queue_wait_budget_mode",
        "required_target_exhaustion",
        "private_round_memory_mode",
    }
)
_REQUIRED_TARGET_EXHAUSTION_V4 = {
    "eligible_failure_modes": [
        "output_budget_exhausted",
        "attempt_hard_timeout",
        "action_wall_timeout",
    ],
    "day_vote_outcome": "technical_abstain",
    "night_required_target_outcome": "technical_no_action",
    "transport_mode": "retry_then_pause",
    "machine_format_mode": "retry_then_pause",
}
_REQUIRED_TARGET_EXHAUSTION = {
    "eligible_failure_modes": [
        "empty_visible_output",
        "unparseable_output",
    ],
    "day_vote_outcome": "technical_abstain",
    "night_required_target_outcome": "technical_no_action",
    "transport_mode": "retry_then_pause",
    "machine_format_mode": "retry_then_pause",
}
_ACTION_PROFILES = {
    "day_debate_speech": "recoverable_public_speech",
    "sheriff_campaign_speech": "recoverable_public_speech",
    "sheriff_pk_speech": "recoverable_public_speech",
    "exile_pk_speech": "recoverable_public_speech",
    "exile_last_words": "recoverable_public_speech",
    "first_night_last_words": "recoverable_public_speech",
    "private_round_memory": "isolated_auxiliary",
}
_MAX_REASONING_ONLY_TIMEOUT_MS = 86_400_000
_MAX_TIMEOUT_ATTEMPTS = 3
_MAX_ACTION_WALL_TIMEOUT_MS = 1_800_000


class ModelGenerationPolicyContractError(ValueError):
    pass


RequiredTargetExhaustionFailureMode = Literal[
    "output_budget_exhausted",
    "attempt_hard_timeout",
    "action_wall_timeout",
    "empty_visible_output",
    "unparseable_output",
]
RequiredTargetTechnicalOutcome = Literal[
    "technical_abstain",
    "technical_no_action",
]
TechnicalOutcomeFailureCategory = Literal["output_budget", "timeout", "machine_format"]
TECHNICAL_OUTCOME_FAILURE_MODES = frozenset(
    {
        "output_budget_exhausted",
        "attempt_hard_timeout",
        "action_wall_timeout",
        "empty_visible_output",
        "unparseable_output",
    }
)


@dataclass(frozen=True)
class ResolvedRequiredTargetExhaustionPolicy:
    eligible_failure_modes: tuple[RequiredTargetExhaustionFailureMode, ...]
    day_vote_outcome: Literal["technical_abstain"]
    night_required_target_outcome: Literal["technical_no_action"]
    transport_mode: Literal["retry_then_pause"]
    machine_format_mode: Literal["retry_then_pause"]


@dataclass(frozen=True)
class ResolvedModelGenerationPolicy:
    status: Literal["supported", "legacy_disabled"]
    enforcement: Literal["observe_only", "disabled"]
    profile: str | None
    source: Literal[
        "explicit_action_profile",
        "default_profile",
        "legacy_missing_contract",
    ]
    schema_version: int | None
    classification_version: int | None
    reasoning_parameter_mode: str | None
    reasoning_only_timeout_ms: int | None
    timeout_max_attempts: int | None
    automatic_retry_enforcement: Literal["enforce", "legacy_behavior", "disabled"]
    output_budget_max_attempts: int | None
    attempt_hard_timeout_max_attempts: int | None
    transport_max_attempts: int | None
    post_token_transport_max_attempts: int | None
    queue_wait_budget_mode: Literal["wall_clock", "active_only", "disabled"]
    action_wall_timeout_ms: int | None
    blocking_required_target_output_timeout_mode: Literal[
        "technical_outcome",
        "legacy_behavior",
        "disabled",
    ]
    blocking_required_target_queue_wait_budget_mode: Literal[
        "wall_clock",
        "active_only",
        "disabled",
    ]
    required_target_exhaustion: ResolvedRequiredTargetExhaustionPolicy | None
    private_round_memory_mode: Literal[
        "blocking_generation",
        "disabled",
    ]


def current_model_generation_policy_contract() -> dict[str, Any]:
    """Return the generation-policy contract emitted for new games."""

    return {
        "schema_version": MODEL_GENERATION_POLICY_SCHEMA_VERSION,
        "classification_version": MODEL_GENERATION_POLICY_CLASSIFICATION_VERSION,
        "enforcement": MODEL_GENERATION_POLICY_ENFORCEMENT,
        "reasoning_parameter_mode": MODEL_GENERATION_POLICY_REASONING_PARAMETER_MODE,
        "default_profile": "strategic_full",
        "profiles": {
            "strategic_full": {},
            "recoverable_public_speech": {},
            "isolated_auxiliary": {},
        },
        "action_profiles": dict(_ACTION_PROFILES),
        "execution": {
            "automatic_retry_enforcement": "enforce",
            "transport_max_attempts": 2,
            "post_token_transport_max_attempts": 1,
            "queue_wait_budget_mode": "wall_clock",
            "required_target_exhaustion": deepcopy(_REQUIRED_TARGET_EXHAUSTION),
            "private_round_memory_mode": "blocking_generation",
        },
    }


def schema_v4_model_generation_policy_contract() -> dict[str, Any]:
    """Return the timeout/budget contract retained for frozen games."""

    return {
        "schema_version": 4,
        "classification_version": MODEL_GENERATION_POLICY_CLASSIFICATION_VERSION,
        "enforcement": MODEL_GENERATION_POLICY_ENFORCEMENT,
        "reasoning_parameter_mode": MODEL_GENERATION_POLICY_REASONING_PARAMETER_MODE,
        "default_profile": "strategic_full",
        "profiles": {
            "strategic_full": {
                "reasoning_only_timeout_ms": None,
                "timeout_max_attempts": 2,
            },
            "recoverable_public_speech": {
                "reasoning_only_timeout_ms": 180_000,
                "timeout_max_attempts": 1,
            },
            "isolated_auxiliary": {
                "reasoning_only_timeout_ms": 240_000,
                "timeout_max_attempts": 1,
            },
        },
        "action_profiles": dict(_ACTION_PROFILES),
        "execution": {
            "automatic_retry_enforcement": "enforce",
            "output_budget_max_attempts": 1,
            "attempt_hard_timeout_max_attempts": 1,
            "transport_max_attempts": 2,
            "post_token_transport_max_attempts": 1,
            "queue_wait_budget_mode": "wall_clock",
            "action_wall_timeout_ms": 300_000,
            "blocking_required_target_output_timeout_mode": "technical_outcome",
            "blocking_required_target_queue_wait_budget_mode": "wall_clock",
            "required_target_exhaustion": deepcopy(_REQUIRED_TARGET_EXHAUSTION_V4),
            "private_round_memory_mode": "blocking_generation",
        },
    }


def technical_outcome_failure_category(
    failure_mode: RequiredTargetExhaustionFailureMode | str,
) -> TechnicalOutcomeFailureCategory | None:
    if failure_mode == "output_budget_exhausted":
        return "output_budget"
    if failure_mode in {"attempt_hard_timeout", "action_wall_timeout"}:
        return "timeout"
    if failure_mode in {"empty_visible_output", "unparseable_output"}:
        return "machine_format"
    return None


def frozen_model_generation_policy_schema_version(
    rule_snapshot: dict[str, Any] | None,
) -> int:
    frozen = resolve_model_generation_policy_contract(rule_snapshot)
    schema_version = frozen.get("schema_version") if isinstance(frozen, dict) else None
    if isinstance(schema_version, int) and not isinstance(schema_version, bool):
        return schema_version
    return MODEL_GENERATION_POLICY_SCHEMA_VERSION


def freeze_model_generation_policy_contract(
    rule_snapshot: dict[str, Any] | None,
) -> dict[str, Any]:
    frozen = dict(rule_snapshot or {})
    frozen[_CONTRACT_KEY] = current_model_generation_policy_contract()
    return frozen


def resolve_model_generation_policy_contract(
    rule_snapshot: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Resolve a frozen contract, treating a missing legacy key as disabled."""

    if not isinstance(rule_snapshot, dict) or _CONTRACT_KEY not in rule_snapshot:
        return None
    return validate_model_generation_policy_contract(rule_snapshot[_CONTRACT_KEY])


def validate_model_generation_policy_contract(
    contract: Any,
) -> dict[str, Any]:
    if type(contract) is not dict:
        _raise_unsupported()
    schema_version = contract.get("schema_version")
    if type(schema_version) is not int or schema_version not in MODEL_GENERATION_POLICY_SUPPORTED_SCHEMA_VERSIONS:
        _raise_unsupported()
    expected_keys = _TOP_LEVEL_KEYS_V4
    if set(contract) != expected_keys:
        _raise_unsupported()
    if not _is_exact_int(contract["classification_version"], expected=1):
        _raise_unsupported()
    if contract["enforcement"] != MODEL_GENERATION_POLICY_ENFORCEMENT:
        _raise_unsupported()
    if contract["reasoning_parameter_mode"] != MODEL_GENERATION_POLICY_REASONING_PARAMETER_MODE:
        _raise_unsupported()
    if contract["default_profile"] != "strategic_full":
        _raise_unsupported()
    profiles = contract["profiles"]
    if type(profiles) is not dict or set(profiles) != _PROFILE_NAMES:
        _raise_unsupported()
    if schema_version == 6:
        for profile in profiles.values():
            if type(profile) is not dict or set(profile):
                _raise_unsupported()
    else:
        for profile_name, profile in profiles.items():
            if type(profile) is not dict or set(profile) != _PROFILE_KEYS:
                _raise_unsupported()
            timeout_ms = profile["reasoning_only_timeout_ms"]
            if profile_name == "strategic_full":
                if timeout_ms is not None:
                    _raise_unsupported()
            elif not _is_bounded_int(
                timeout_ms,
                minimum=1,
                maximum=_MAX_REASONING_ONLY_TIMEOUT_MS,
            ):
                _raise_unsupported()
            if not _is_bounded_int(
                profile["timeout_max_attempts"],
                minimum=1,
                maximum=_MAX_TIMEOUT_ATTEMPTS,
            ):
                _raise_unsupported()
    action_profiles = contract["action_profiles"]
    if not _strict_contract_equal(action_profiles, _ACTION_PROFILES):
        _raise_unsupported()
    execution = contract["execution"]
    expected_execution_keys = (
        _EXECUTION_KEYS_V6 if schema_version == 6 else _EXECUTION_KEYS_V4
    )
    if type(execution) is not dict or set(execution) != expected_execution_keys:
        _raise_unsupported()
    if execution["automatic_retry_enforcement"] != "enforce":
        _raise_unsupported()
    for key in (
        "transport_max_attempts",
        "post_token_transport_max_attempts",
    ):
        if not _is_bounded_int(
            execution[key],
            minimum=1,
            maximum=_MAX_TIMEOUT_ATTEMPTS,
        ):
            _raise_unsupported()
    if execution["post_token_transport_max_attempts"] > execution["transport_max_attempts"]:
        _raise_unsupported()
    if execution["queue_wait_budget_mode"] != "wall_clock":
        _raise_unsupported()
    if schema_version == 4:
        for key in (
            "output_budget_max_attempts",
            "attempt_hard_timeout_max_attempts",
        ):
            if not _is_bounded_int(
                execution[key],
                minimum=1,
                maximum=_MAX_TIMEOUT_ATTEMPTS,
            ):
                _raise_unsupported()
        if not _is_bounded_int(
            execution["action_wall_timeout_ms"],
            minimum=1,
            maximum=_MAX_ACTION_WALL_TIMEOUT_MS,
        ):
            _raise_unsupported()
        if execution["blocking_required_target_output_timeout_mode"] != "technical_outcome":
            _raise_unsupported()
        if execution["blocking_required_target_queue_wait_budget_mode"] != "wall_clock":
            _raise_unsupported()
    expected_exhaustion = (
        _REQUIRED_TARGET_EXHAUSTION if schema_version == 6 else _REQUIRED_TARGET_EXHAUSTION_V4
    )
    if not _strict_contract_equal(
        execution["required_target_exhaustion"],
        expected_exhaustion,
    ):
        _raise_unsupported()
    if execution["private_round_memory_mode"] != "blocking_generation":
        _raise_unsupported()
    return deepcopy(contract)


def is_supported_model_generation_policy_contract(contract: Any) -> bool:
    try:
        validate_model_generation_policy_contract(contract)
    except ModelGenerationPolicyContractError:
        return False
    return True


def resolve_model_generation_action_policy(
    contract: dict[str, Any] | None,
    *,
    action_type: str,
) -> ResolvedModelGenerationPolicy:
    """Resolve immutable reasoning telemetry and execution policy for an action."""

    if contract is None:
        return ResolvedModelGenerationPolicy(
            status="legacy_disabled",
            enforcement="disabled",
            profile=None,
            source="legacy_missing_contract",
            schema_version=None,
            classification_version=None,
            reasoning_parameter_mode=None,
            reasoning_only_timeout_ms=None,
            timeout_max_attempts=None,
            automatic_retry_enforcement="legacy_behavior",
            output_budget_max_attempts=None,
            attempt_hard_timeout_max_attempts=None,
            transport_max_attempts=None,
            post_token_transport_max_attempts=None,
            queue_wait_budget_mode="active_only",
            action_wall_timeout_ms=None,
            blocking_required_target_output_timeout_mode="legacy_behavior",
            blocking_required_target_queue_wait_budget_mode="active_only",
            required_target_exhaustion=None,
            # A missing contract disables the new policy, not the old runtime
            # behavior. Report the effective legacy modes truthfully.
            private_round_memory_mode="blocking_generation",
        )
    validated = validate_model_generation_policy_contract(contract)
    action_profiles = validated["action_profiles"]
    if action_type in action_profiles:
        profile = action_profiles[action_type]
        source: Literal["explicit_action_profile", "default_profile"] = "explicit_action_profile"
    else:
        profile = validated["default_profile"]
        source = "default_profile"
    profile_contract = validated["profiles"][profile]
    execution = validated.get("execution")
    schema_version = validated["schema_version"]
    return ResolvedModelGenerationPolicy(
        status="supported",
        enforcement=validated["enforcement"],
        profile=profile,
        source=source,
        schema_version=schema_version,
        classification_version=validated["classification_version"],
        reasoning_parameter_mode=validated["reasoning_parameter_mode"],
        reasoning_only_timeout_ms=(
            profile_contract.get("reasoning_only_timeout_ms")
            if schema_version == 4
            else None
        ),
        timeout_max_attempts=(
            profile_contract.get("timeout_max_attempts")
            if schema_version == 4
            else None
        ),
        automatic_retry_enforcement=(
            execution["automatic_retry_enforcement"] if execution is not None else "legacy_behavior"
        ),
        output_budget_max_attempts=(
            execution.get("output_budget_max_attempts") if execution is not None else None
        ),
        attempt_hard_timeout_max_attempts=(
            execution.get("attempt_hard_timeout_max_attempts") if execution is not None else None
        ),
        transport_max_attempts=(
            execution["transport_max_attempts"] if execution is not None else None
        ),
        post_token_transport_max_attempts=(
            execution["post_token_transport_max_attempts"] if execution is not None else None
        ),
        queue_wait_budget_mode=(
            execution["queue_wait_budget_mode"] if execution is not None else "active_only"
        ),
        action_wall_timeout_ms=(
            execution.get("action_wall_timeout_ms") if execution is not None else None
        ),
        blocking_required_target_output_timeout_mode=(
            execution.get("blocking_required_target_output_timeout_mode")
            if execution is not None and schema_version == 4
            else "disabled" if schema_version == 6
            else "legacy_behavior"
        ),
        blocking_required_target_queue_wait_budget_mode=(
            execution.get("blocking_required_target_queue_wait_budget_mode")
            if execution is not None and schema_version == 4
            else "disabled" if schema_version == 6
            else "active_only"
        ),
        required_target_exhaustion=(
            ResolvedRequiredTargetExhaustionPolicy(
                eligible_failure_modes=tuple(
                    execution["required_target_exhaustion"]["eligible_failure_modes"]
                ),
                day_vote_outcome=(execution["required_target_exhaustion"]["day_vote_outcome"]),
                night_required_target_outcome=(
                    execution["required_target_exhaustion"]["night_required_target_outcome"]
                ),
                transport_mode=execution["required_target_exhaustion"]["transport_mode"],
                machine_format_mode=(
                    execution["required_target_exhaustion"]["machine_format_mode"]
                ),
            )
            if execution is not None and "required_target_exhaustion" in execution
            else None
        ),
        private_round_memory_mode=(
            execution["private_round_memory_mode"]
            if execution is not None
            else "blocking_generation"
        ),
    )


def _strict_contract_equal(actual: Any, expected: Any) -> bool:
    if type(actual) is not type(expected):
        return False
    if isinstance(expected, dict):
        return set(actual) == set(expected) and all(
            _strict_contract_equal(actual[key], value) for key, value in expected.items()
        )
    if isinstance(expected, list):
        return len(actual) == len(expected) and all(
            _strict_contract_equal(actual_value, expected_value)
            for actual_value, expected_value in zip(actual, expected, strict=True)
        )
    return actual == expected


def _is_exact_int(value: Any, *, expected: int) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value == expected


def _is_bounded_int(value: Any, *, minimum: int, maximum: int) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and minimum <= value <= maximum


def _raise_unsupported() -> None:
    raise ModelGenerationPolicyContractError(_UNSUPPORTED_ERROR)
