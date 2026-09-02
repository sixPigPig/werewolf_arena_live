from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Any, Literal


PRE_EXILE_PIPELINE_SCHEMA_VERSION = 3

_CONTRACT_KEY = "pre_exile_pipeline_contract"
_UNSUPPORTED_ERROR = "unsupported_pre_exile_pipeline_contract"
_CONTRACT_KEYS_V1 = frozenset(
    {
        "schema_version",
        "mode",
        "action_types",
        "launch_boundary",
        "accept_boundary",
        "self_explosion_admission_mode",
        "speculative_vote_admission_mode",
        "speculative_vote_capacity_recovery_mode",
        "wolf_vote_gate",
        "vote_abort_policy",
        "private_context_mode",
        "result_commit_mode",
        "fallback_mode",
        "inflight_recovery_mode",
    }
)
_CONTRACT_KEYS_V2 = frozenset(
    {
        *_CONTRACT_KEYS_V1,
        "self_explosion_early_empty_stream_hidden_retry_max_retries",
    }
)
_CONTRACT_KEYS_V3 = _CONTRACT_KEYS_V2


class PreExilePipelineContractError(ValueError):
    pass


@dataclass(frozen=True)
class ResolvedPreExilePipelineContract:
    status: Literal["supported", "legacy_sequential"]
    mode: Literal["sealed_last_speech_overlap", "sequential"]
    source: Literal["frozen_contract", "legacy_missing_contract"]
    schema_version: int | None
    action_types: tuple[Literal["werewolf_self_explosion", "exile_vote"], ...]
    launch_boundary: Literal["last_public_speech_sealed", "disabled"]
    accept_boundary: Literal[
        "last_public_speech_closed",
        "last_public_speech_sealed",
        "disabled",
    ]
    self_explosion_admission_mode: Literal["normal", "disabled"]
    speculative_vote_admission_mode: Literal["idle_only", "normal", "disabled"]
    speculative_vote_capacity_recovery_mode: Literal["normal_batch_after_close_once", "disabled"]
    wolf_vote_gate: Literal["own_no_explosion_result", "disabled"]
    vote_abort_policy: Literal["any_explosion_discards_all_votes", "disabled"]
    private_context_mode: Literal["sealed_snapshot_plus_own_no_explosion_fact", "disabled"]
    result_commit_mode: Literal["durable_atomic_arbiter", "disabled"]
    fallback_mode: Literal["before_launch_sequential_only", "sequential"]
    inflight_recovery_mode: Literal["no_duplicate_provider", "disabled"]
    self_explosion_early_empty_stream_hidden_retry_max_retries: Literal[0, 1]

    def enables(self, action_type: str) -> bool:
        return (
            self.status == "supported"
            and self.mode == "sealed_last_speech_overlap"
            and action_type in self.action_types
        )


def current_pre_exile_pipeline_contract() -> dict[str, Any]:
    """Return the overlap contract frozen only into newly created games."""

    return {
        "schema_version": PRE_EXILE_PIPELINE_SCHEMA_VERSION,
        "mode": "sealed_last_speech_overlap",
        "action_types": ["werewolf_self_explosion", "exile_vote"],
        "launch_boundary": "last_public_speech_sealed",
        "accept_boundary": "last_public_speech_sealed",
        "self_explosion_admission_mode": "normal",
        "speculative_vote_admission_mode": "normal",
        "speculative_vote_capacity_recovery_mode": "normal_batch_after_close_once",
        "wolf_vote_gate": "own_no_explosion_result",
        "vote_abort_policy": "any_explosion_discards_all_votes",
        "private_context_mode": "sealed_snapshot_plus_own_no_explosion_fact",
        "result_commit_mode": "durable_atomic_arbiter",
        "fallback_mode": "before_launch_sequential_only",
        "inflight_recovery_mode": "no_duplicate_provider",
        "self_explosion_early_empty_stream_hidden_retry_max_retries": 1,
    }


def _schema_v2_pre_exile_pipeline_contract() -> dict[str, Any]:
    """Return the idle-only vote overlap contract retained for frozen games."""

    return {
        "schema_version": 2,
        "mode": "sealed_last_speech_overlap",
        "action_types": ["werewolf_self_explosion", "exile_vote"],
        "launch_boundary": "last_public_speech_sealed",
        "accept_boundary": "last_public_speech_closed",
        "self_explosion_admission_mode": "normal",
        "speculative_vote_admission_mode": "idle_only",
        "speculative_vote_capacity_recovery_mode": "normal_batch_after_close_once",
        "wolf_vote_gate": "own_no_explosion_result",
        "vote_abort_policy": "any_explosion_discards_all_votes",
        "private_context_mode": "sealed_snapshot_plus_own_no_explosion_fact",
        "result_commit_mode": "durable_atomic_arbiter",
        "fallback_mode": "before_launch_sequential_only",
        "inflight_recovery_mode": "no_duplicate_provider",
        "self_explosion_early_empty_stream_hidden_retry_max_retries": 1,
    }


def _schema_v1_pre_exile_pipeline_contract() -> dict[str, Any]:
    """Return the original overlap contract for frozen-game compatibility."""

    return {
        "schema_version": 1,
        "mode": "sealed_last_speech_overlap",
        "action_types": ["werewolf_self_explosion", "exile_vote"],
        "launch_boundary": "last_public_speech_sealed",
        "accept_boundary": "last_public_speech_closed",
        "self_explosion_admission_mode": "normal",
        "speculative_vote_admission_mode": "idle_only",
        "speculative_vote_capacity_recovery_mode": "normal_batch_after_close_once",
        "wolf_vote_gate": "own_no_explosion_result",
        "vote_abort_policy": "any_explosion_discards_all_votes",
        "private_context_mode": "sealed_snapshot_plus_own_no_explosion_fact",
        "result_commit_mode": "durable_atomic_arbiter",
        "fallback_mode": "before_launch_sequential_only",
        "inflight_recovery_mode": "no_duplicate_provider",
    }


def pre_exile_context_sha256(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def schema_v2_pre_exile_pipeline_contract() -> dict[str, Any]:
    """Return the idle-only vote overlap contract retained for frozen games."""

    return _schema_v2_pre_exile_pipeline_contract()


def freeze_pre_exile_pipeline_contract(
    rule_snapshot: dict[str, Any] | None,
) -> dict[str, Any]:
    frozen = dict(rule_snapshot or {})
    frozen[_CONTRACT_KEY] = current_pre_exile_pipeline_contract()
    return frozen


def resolve_pre_exile_pipeline_contract(
    rule_snapshot: dict[str, Any] | None,
) -> ResolvedPreExilePipelineContract:
    """Resolve a frozen contract; missing legacy contracts stay sequential."""

    if not isinstance(rule_snapshot, dict) or _CONTRACT_KEY not in rule_snapshot:
        return ResolvedPreExilePipelineContract(
            status="legacy_sequential",
            mode="sequential",
            source="legacy_missing_contract",
            schema_version=None,
            action_types=(),
            launch_boundary="disabled",
            accept_boundary="disabled",
            self_explosion_admission_mode="disabled",
            speculative_vote_admission_mode="disabled",
            speculative_vote_capacity_recovery_mode="disabled",
            wolf_vote_gate="disabled",
            vote_abort_policy="disabled",
            private_context_mode="disabled",
            result_commit_mode="disabled",
            fallback_mode="sequential",
            inflight_recovery_mode="disabled",
            self_explosion_early_empty_stream_hidden_retry_max_retries=0,
        )
    contract = validate_pre_exile_pipeline_contract(rule_snapshot[_CONTRACT_KEY])
    schema_version = contract["schema_version"]
    return ResolvedPreExilePipelineContract(
        status="supported",
        mode="sealed_last_speech_overlap",
        source="frozen_contract",
        schema_version=schema_version,
        action_types=("werewolf_self_explosion", "exile_vote"),
        launch_boundary="last_public_speech_sealed",
        accept_boundary=contract["accept_boundary"],
        self_explosion_admission_mode="normal",
        speculative_vote_admission_mode=contract["speculative_vote_admission_mode"],
        speculative_vote_capacity_recovery_mode="normal_batch_after_close_once",
        wolf_vote_gate="own_no_explosion_result",
        vote_abort_policy="any_explosion_discards_all_votes",
        private_context_mode="sealed_snapshot_plus_own_no_explosion_fact",
        result_commit_mode="durable_atomic_arbiter",
        fallback_mode="before_launch_sequential_only",
        inflight_recovery_mode="no_duplicate_provider",
        self_explosion_early_empty_stream_hidden_retry_max_retries=(
            contract["self_explosion_early_empty_stream_hidden_retry_max_retries"]
            if schema_version >= 2
            else 0
        ),
    )


def validate_pre_exile_pipeline_contract(contract: Any) -> dict[str, Any]:
    if type(contract) is not dict:
        _raise_unsupported()
    schema_version = contract.get("schema_version")
    if type(schema_version) is not int or schema_version not in {1, 2, 3}:
        _raise_unsupported()
    if schema_version == 1:
        expected = _schema_v1_pre_exile_pipeline_contract()
        expected_keys = _CONTRACT_KEYS_V1
    elif schema_version == 2:
        expected = _schema_v2_pre_exile_pipeline_contract()
        expected_keys = _CONTRACT_KEYS_V2
    else:
        expected = current_pre_exile_pipeline_contract()
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


def pre_exile_pipeline_contract_summary(
    rule_snapshot: dict[str, Any] | None,
) -> dict[str, Any]:
    resolved = resolve_pre_exile_pipeline_contract(rule_snapshot)
    return {
        "status": resolved.status,
        "schema_version": resolved.schema_version,
        "mode": resolved.mode,
        "action_types": list(resolved.action_types),
        "launch_boundary": resolved.launch_boundary,
        "accept_boundary": resolved.accept_boundary,
        "self_explosion_admission_mode": resolved.self_explosion_admission_mode,
        "speculative_vote_admission_mode": resolved.speculative_vote_admission_mode,
        "speculative_vote_capacity_recovery_mode": (
            resolved.speculative_vote_capacity_recovery_mode
        ),
        "wolf_vote_gate": resolved.wolf_vote_gate,
        "vote_abort_policy": resolved.vote_abort_policy,
        "private_context_mode": resolved.private_context_mode,
        "result_commit_mode": resolved.result_commit_mode,
        "fallback_mode": resolved.fallback_mode,
        "inflight_recovery_mode": resolved.inflight_recovery_mode,
        "self_explosion_early_empty_stream_hidden_retry_max_retries": (
            resolved.self_explosion_early_empty_stream_hidden_retry_max_retries
        ),
    }


def _raise_unsupported() -> None:
    raise PreExilePipelineContractError(_UNSUPPORTED_ERROR)
