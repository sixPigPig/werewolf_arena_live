from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Literal


MODEL_GENERATION_POLICY_SCHEMA_VERSION = 1
MODEL_GENERATION_POLICY_CLASSIFICATION_VERSION = 1
MODEL_GENERATION_POLICY_ENFORCEMENT = "observe_only"
MODEL_GENERATION_POLICY_REASONING_PARAMETER_MODE = "inherit_frozen_model_configuration"

_CONTRACT_KEY = "model_generation_policy_contract"
_UNSUPPORTED_ERROR = "unsupported_model_generation_policy_contract"
_TOP_LEVEL_KEYS = frozenset(
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


class V2ModelGenerationPolicyContractError(ValueError):
    pass


@dataclass(frozen=True)
class V2ResolvedModelGenerationPolicy:
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


def current_model_generation_policy_contract() -> dict[str, Any]:
    """Return the only generation-policy contract emitted for new games."""

    return {
        "schema_version": MODEL_GENERATION_POLICY_SCHEMA_VERSION,
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
    }


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
    if type(contract) is not dict or set(contract) != _TOP_LEVEL_KEYS:
        _raise_unsupported()
    if not _is_exact_int(contract["schema_version"], expected=1):
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
    return deepcopy(contract)


def is_supported_model_generation_policy_contract(contract: Any) -> bool:
    try:
        validate_model_generation_policy_contract(contract)
    except V2ModelGenerationPolicyContractError:
        return False
    return True


def resolve_model_generation_action_policy(
    contract: dict[str, Any] | None,
    *,
    action_type: str,
) -> V2ResolvedModelGenerationPolicy:
    """Resolve immutable shadow metadata without changing request behavior."""

    if contract is None:
        return V2ResolvedModelGenerationPolicy(
            status="legacy_disabled",
            enforcement="disabled",
            profile=None,
            source="legacy_missing_contract",
            schema_version=None,
            classification_version=None,
            reasoning_parameter_mode=None,
            reasoning_only_timeout_ms=None,
            timeout_max_attempts=None,
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
    return V2ResolvedModelGenerationPolicy(
        status="supported",
        enforcement=validated["enforcement"],
        profile=profile,
        source=source,
        schema_version=validated["schema_version"],
        classification_version=validated["classification_version"],
        reasoning_parameter_mode=validated["reasoning_parameter_mode"],
        reasoning_only_timeout_ms=profile_contract["reasoning_only_timeout_ms"],
        timeout_max_attempts=profile_contract["timeout_max_attempts"],
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
    raise V2ModelGenerationPolicyContractError(_UNSUPPORTED_ERROR)
