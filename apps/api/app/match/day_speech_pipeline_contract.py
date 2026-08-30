from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal


DAY_SPEECH_PIPELINE_SCHEMA_VERSION = 3

_CONTRACT_KEY = "day_speech_pipeline_contract"
_UNSUPPORTED_ERROR = "unsupported_day_speech_pipeline_contract"
_CONTRACT_KEYS_V1 = frozenset(
    {
        "schema_version",
        "mode",
        "action_types",
        "max_lookahead",
        "context_source",
        "admission_mode",
        "fallback_mode",
    }
)
_CONTRACT_KEYS_V2 = frozenset(
    {
        *_CONTRACT_KEYS_V1,
        "post_predecessor_close_grace_ms",
        "duplicate_foreground_fallback_forbidden_failure_categories",
        "early_transport_hidden_retry_max_retries",
        "prefetch_capacity_unavailable_fallback_mode",
    }
)
_CONTRACT_KEYS_V3 = frozenset(
    {
        *_CONTRACT_KEYS_V1,
        "post_predecessor_close_wait_mode",
        "duplicate_foreground_fallback_forbidden_failure_categories",
        "early_transport_hidden_retry_max_retries",
        "prefetch_capacity_unavailable_fallback_mode",
    }
)


class DaySpeechPipelineContractError(ValueError):
    pass


@dataclass(frozen=True)
class ResolvedDaySpeechPipelineContract:
    status: Literal["supported", "legacy_sequential"]
    mode: Literal["one_ahead", "sequential"]
    source: Literal["frozen_contract", "legacy_missing_contract"]
    schema_version: int | None
    action_types: tuple[Literal["day_debate_speech"], ...]
    max_lookahead: Literal[0, 1]
    context_source: Literal["active_sealed_predecessor", "disabled"]
    admission_mode: Literal["idle_only", "disabled"]
    fallback_mode: Literal["fallback_sequential", "sequential"]
    post_predecessor_close_grace_ms: int | None
    post_predecessor_close_wait_mode: Literal[
        "disabled",
        "deadline_then_technical_skip",
        "await_same_inflight_to_terminal",
    ]
    duplicate_foreground_fallback_forbidden_failure_categories: tuple[
        Literal["output_budget", "timeout"], ...
    ]
    early_transport_hidden_retry_max_retries: Literal[0, 1]
    prefetch_capacity_unavailable_fallback_mode: Literal["fallback_sequential", "disabled"]

    def enables(self, action_type: str) -> bool:
        return (
            self.status == "supported"
            and self.mode == "one_ahead"
            and action_type in self.action_types
        )


def current_day_speech_pipeline_contract() -> dict[str, Any]:
    """Return the one-ahead contract frozen only into newly created games."""

    return {
        "schema_version": DAY_SPEECH_PIPELINE_SCHEMA_VERSION,
        "mode": "one_ahead",
        "action_types": ["day_debate_speech"],
        "max_lookahead": 1,
        "context_source": "active_sealed_predecessor",
        "admission_mode": "idle_only",
        "fallback_mode": "fallback_sequential",
        "post_predecessor_close_wait_mode": "await_same_inflight_to_terminal",
        "duplicate_foreground_fallback_forbidden_failure_categories": [
            "output_budget",
            "timeout",
        ],
        "early_transport_hidden_retry_max_retries": 1,
        "prefetch_capacity_unavailable_fallback_mode": "fallback_sequential",
    }


def _schema_v1_day_speech_pipeline_contract() -> dict[str, Any]:
    """Return the exact P2 contract retained for frozen-game compatibility."""

    return {
        "schema_version": 1,
        "mode": "one_ahead",
        "action_types": ["day_debate_speech"],
        "max_lookahead": 1,
        "context_source": "active_sealed_predecessor",
        "admission_mode": "idle_only",
        "fallback_mode": "fallback_sequential",
    }


def _schema_v2_day_speech_pipeline_contract() -> dict[str, Any]:
    """Return the exact P3 contract retained for frozen-game compatibility."""

    return {
        "schema_version": 2,
        "mode": "one_ahead",
        "action_types": ["day_debate_speech"],
        "max_lookahead": 1,
        "context_source": "active_sealed_predecessor",
        "admission_mode": "idle_only",
        "fallback_mode": "fallback_sequential",
        "post_predecessor_close_grace_ms": 30_000,
        "duplicate_foreground_fallback_forbidden_failure_categories": [
            "output_budget",
            "timeout",
        ],
        "early_transport_hidden_retry_max_retries": 1,
        "prefetch_capacity_unavailable_fallback_mode": "fallback_sequential",
    }


def freeze_day_speech_pipeline_contract(
    rule_snapshot: dict[str, Any] | None,
) -> dict[str, Any]:
    frozen = dict(rule_snapshot or {})
    frozen[_CONTRACT_KEY] = current_day_speech_pipeline_contract()
    return frozen


def resolve_day_speech_pipeline_contract(
    rule_snapshot: dict[str, Any] | None,
) -> ResolvedDaySpeechPipelineContract:
    """Resolve a frozen contract; missing legacy contracts remain sequential."""

    if not isinstance(rule_snapshot, dict) or _CONTRACT_KEY not in rule_snapshot:
        return ResolvedDaySpeechPipelineContract(
            status="legacy_sequential",
            mode="sequential",
            source="legacy_missing_contract",
            schema_version=None,
            action_types=(),
            max_lookahead=0,
            context_source="disabled",
            admission_mode="disabled",
            fallback_mode="sequential",
            post_predecessor_close_grace_ms=None,
            post_predecessor_close_wait_mode="disabled",
            duplicate_foreground_fallback_forbidden_failure_categories=(),
            early_transport_hidden_retry_max_retries=0,
            prefetch_capacity_unavailable_fallback_mode="disabled",
        )
    contract = validate_day_speech_pipeline_contract(rule_snapshot[_CONTRACT_KEY])
    schema_version = contract["schema_version"]
    return ResolvedDaySpeechPipelineContract(
        status="supported",
        mode="one_ahead",
        source="frozen_contract",
        schema_version=schema_version,
        action_types=("day_debate_speech",),
        max_lookahead=1,
        context_source="active_sealed_predecessor",
        admission_mode="idle_only",
        fallback_mode="fallback_sequential",
        post_predecessor_close_grace_ms=(
            contract["post_predecessor_close_grace_ms"] if schema_version == 2 else None
        ),
        post_predecessor_close_wait_mode=(
            contract["post_predecessor_close_wait_mode"]
            if schema_version == DAY_SPEECH_PIPELINE_SCHEMA_VERSION
            else "deadline_then_technical_skip"
            if schema_version == 2
            else "disabled"
        ),
        duplicate_foreground_fallback_forbidden_failure_categories=(
            tuple(contract["duplicate_foreground_fallback_forbidden_failure_categories"])
            if schema_version in {2, DAY_SPEECH_PIPELINE_SCHEMA_VERSION}
            else ()
        ),
        early_transport_hidden_retry_max_retries=(
            contract["early_transport_hidden_retry_max_retries"]
            if schema_version in {2, DAY_SPEECH_PIPELINE_SCHEMA_VERSION}
            else 0
        ),
        prefetch_capacity_unavailable_fallback_mode="fallback_sequential",
    )


def validate_day_speech_pipeline_contract(contract: Any) -> dict[str, Any]:
    if type(contract) is not dict:
        _raise_unsupported()
    schema_version = contract.get("schema_version")
    if type(schema_version) is not int or schema_version not in {
        1,
        2,
        DAY_SPEECH_PIPELINE_SCHEMA_VERSION,
    }:
        _raise_unsupported()
    if schema_version == 1:
        expected = _schema_v1_day_speech_pipeline_contract()
        expected_keys = _CONTRACT_KEYS_V1
    elif schema_version == 2:
        expected = _schema_v2_day_speech_pipeline_contract()
        expected_keys = _CONTRACT_KEYS_V2
    else:
        expected = current_day_speech_pipeline_contract()
        expected_keys = _CONTRACT_KEYS_V3
    if set(contract) != expected_keys:
        _raise_unsupported()
    for key, expected_value in expected.items():
        value = contract[key]
        if isinstance(expected_value, int):
            if type(value) is not int or value != expected_value:
                _raise_unsupported()
        elif isinstance(expected_value, list):
            if type(value) is not list or value != expected_value:
                _raise_unsupported()
        elif type(value) is not str or value != expected_value:
            _raise_unsupported()
    return {
        key: list(contract[key]) if isinstance(contract[key], list) else contract[key]
        for key in expected
    }


def day_speech_pipeline_contract_summary(
    rule_snapshot: dict[str, Any] | None,
) -> dict[str, Any]:
    resolved = resolve_day_speech_pipeline_contract(rule_snapshot)
    return {
        "status": resolved.status,
        "schema_version": resolved.schema_version,
        "mode": resolved.mode,
        "action_types": list(resolved.action_types),
        "max_lookahead": resolved.max_lookahead,
        "context_source": resolved.context_source,
        "admission_mode": resolved.admission_mode,
        "fallback_mode": resolved.fallback_mode,
        "post_predecessor_close_grace_ms": resolved.post_predecessor_close_grace_ms,
        "post_predecessor_close_wait_mode": resolved.post_predecessor_close_wait_mode,
        "duplicate_foreground_fallback_forbidden_failure_categories": list(
            resolved.duplicate_foreground_fallback_forbidden_failure_categories
        ),
        "early_transport_hidden_retry_max_retries": (
            resolved.early_transport_hidden_retry_max_retries
        ),
        "prefetch_capacity_unavailable_fallback_mode": (
            resolved.prefetch_capacity_unavailable_fallback_mode
        ),
    }


def _raise_unsupported() -> None:
    raise DaySpeechPipelineContractError(_UNSUPPORTED_ERROR)
