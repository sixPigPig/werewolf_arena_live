from __future__ import annotations

from typing import Any


MODEL_CONTEXT_SCHEMA_VERSION = 11
PROMPT_TEMPLATE_VERSION = 4
# Before bumping the current template, explicitly add the outgoing version to
# this legacy set so frozen games remain resumable across deployments.
LEGACY_PROMPT_TEMPLATE_VERSIONS = frozenset({3})
SUPPORTED_PROMPT_TEMPLATE_VERSIONS = LEGACY_PROMPT_TEMPLATE_VERSIONS | {PROMPT_TEMPLATE_VERSION}
MODEL_PROMPT_SCHEMA_VERSION = MODEL_CONTEXT_SCHEMA_VERSION
KNOWN_EVENTS_SCHEMA_VERSION = 5
PUBLIC_TIMELINE_SCHEMA_VERSION = 1
DISCOURSE_LEDGER_SCHEMA_VERSION = 5
CURRENT_DISCOURSE_LEDGER_SCHEMA_VERSION = DISCOURSE_LEDGER_SCHEMA_VERSION
DISCOURSE_MODEL_VIEW_SCHEMA_VERSION = 5
MODEL_VIEW_SELECTOR_VERSION = 2

_CONTRACT_KEY = "model_context_contract"


def current_model_context_contract() -> dict[str, int]:
    return {
        "model_context_schema_version": MODEL_CONTEXT_SCHEMA_VERSION,
        "prompt_template_version": PROMPT_TEMPLATE_VERSION,
        "known_events_schema_version": KNOWN_EVENTS_SCHEMA_VERSION,
        "ledger_schema_version": CURRENT_DISCOURSE_LEDGER_SCHEMA_VERSION,
        "model_view_schema_version": DISCOURSE_MODEL_VIEW_SCHEMA_VERSION,
        "model_view_selector_version": MODEL_VIEW_SELECTOR_VERSION,
    }


def freeze_model_context_contract(
    rule_snapshot: dict[str, Any] | None,
) -> dict[str, Any]:
    frozen = dict(rule_snapshot or {})
    frozen[_CONTRACT_KEY] = current_model_context_contract()
    return frozen


def frozen_model_context_contract(
    rule_snapshot: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if not isinstance(rule_snapshot, dict):
        return None
    value = rule_snapshot.get(_CONTRACT_KEY)
    return dict(value) if isinstance(value, dict) else None


def supports_model_context_contract(
    rule_snapshot: dict[str, Any] | None,
) -> bool:
    return is_supported_model_context_contract(frozen_model_context_contract(rule_snapshot))


def is_current_model_context_contract(contract: dict[str, Any] | None) -> bool:
    expected = current_model_context_contract()
    return (
        isinstance(contract, dict)
        and set(contract) == set(expected)
        and all(
            isinstance(contract[key], int)
            and not isinstance(contract[key], bool)
            and contract[key] == value
            for key, value in expected.items()
        )
    )


def is_supported_model_context_contract(contract: dict[str, Any] | None) -> bool:
    expected = current_model_context_contract()
    if not isinstance(contract, dict) or set(contract) != set(expected):
        return False
    for key, value in expected.items():
        actual = contract.get(key)
        if not isinstance(actual, int) or isinstance(actual, bool):
            return False
        if key == "prompt_template_version":
            if actual not in SUPPORTED_PROMPT_TEMPLATE_VERSIONS:
                return False
        elif actual != value:
            return False
    return True


def supports_current_model_context_contract(
    rule_snapshot: dict[str, Any] | None,
) -> bool:
    return is_current_model_context_contract(frozen_model_context_contract(rule_snapshot))
