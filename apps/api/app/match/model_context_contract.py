from __future__ import annotations

from typing import Any


MODEL_CONTEXT_SCHEMA_VERSION = 13
PROMPT_TEMPLATE_VERSION = 6
# Runtime support is deliberately exact. Historical contracts may remain
# readable for diagnostics, but no older snapshot may resume under V13.
LEGACY_PROMPT_TEMPLATE_VERSIONS: frozenset[int] = frozenset()
SUPPORTED_PROMPT_TEMPLATE_VERSIONS = frozenset({PROMPT_TEMPLATE_VERSION})
MODEL_PROMPT_SCHEMA_VERSION = MODEL_CONTEXT_SCHEMA_VERSION
KNOWN_EVENTS_SCHEMA_VERSION = 7
PUBLIC_TIMELINE_SCHEMA_VERSION = 1
DISCOURSE_LEDGER_SCHEMA_VERSION = 5
CURRENT_DISCOURSE_LEDGER_SCHEMA_VERSION = DISCOURSE_LEDGER_SCHEMA_VERSION
DISCOURSE_MODEL_VIEW_SCHEMA_VERSION = 5
MODEL_VIEW_SELECTOR_VERSION = 3

_CONTRACT_KEY = "model_context_contract"

HISTORICAL_V11_MODEL_CONTEXT_SCHEMA_VERSION = 11
HISTORICAL_V11_PROMPT_TEMPLATE_VERSIONS = frozenset({3, 4})
HISTORICAL_V11_KNOWN_EVENTS_SCHEMA_VERSION = 5


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
    return is_current_model_context_contract(contract)


def is_historical_v11_model_context_contract(
    contract: dict[str, Any] | None,
) -> bool:
    if not isinstance(contract, dict):
        return False
    expected_keys = set(current_model_context_contract())
    if set(contract) != expected_keys:
        return False
    expected = {
        "model_context_schema_version": HISTORICAL_V11_MODEL_CONTEXT_SCHEMA_VERSION,
        "known_events_schema_version": HISTORICAL_V11_KNOWN_EVENTS_SCHEMA_VERSION,
        "ledger_schema_version": CURRENT_DISCOURSE_LEDGER_SCHEMA_VERSION,
        "model_view_schema_version": DISCOURSE_MODEL_VIEW_SCHEMA_VERSION,
        "model_view_selector_version": 2,
    }
    for key, value in expected.items():
        actual = contract.get(key)
        if not isinstance(actual, int) or isinstance(actual, bool) or actual != value:
            return False
    prompt_version = contract.get("prompt_template_version")
    return (
        isinstance(prompt_version, int)
        and not isinstance(prompt_version, bool)
        and prompt_version in HISTORICAL_V11_PROMPT_TEMPLATE_VERSIONS
    )


def supports_current_model_context_contract(
    rule_snapshot: dict[str, Any] | None,
) -> bool:
    return is_current_model_context_contract(frozen_model_context_contract(rule_snapshot))
