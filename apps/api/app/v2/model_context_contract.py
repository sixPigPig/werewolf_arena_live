from __future__ import annotations

from typing import Any


MODEL_CONTEXT_SCHEMA_VERSION = 8
PROMPT_TEMPLATE_VERSION = 1
MODEL_PROMPT_SCHEMA_VERSION = MODEL_CONTEXT_SCHEMA_VERSION
KNOWN_EVENTS_SCHEMA_VERSION = 1
PUBLIC_TIMELINE_SCHEMA_VERSION = 1
DISCOURSE_LEDGER_SCHEMA_VERSION = 2
DISCOURSE_MODEL_VIEW_SCHEMA_VERSION = 3
MODEL_VIEW_SELECTOR_VERSION = 1

_CONTRACT_KEY = "model_context_contract"


def current_model_context_contract() -> dict[str, int]:
    return {
        "model_context_schema_version": MODEL_CONTEXT_SCHEMA_VERSION,
        "prompt_template_version": PROMPT_TEMPLATE_VERSION,
        "known_events_schema_version": KNOWN_EVENTS_SCHEMA_VERSION,
        "ledger_schema_version": DISCOURSE_LEDGER_SCHEMA_VERSION,
        "model_view_schema_version": DISCOURSE_MODEL_VIEW_SCHEMA_VERSION,
        "model_view_selector_version": MODEL_VIEW_SELECTOR_VERSION,
    }


def legacy_v7_model_context_contract() -> dict[str, int]:
    return {
        "prompt_schema_version": 7,
        "public_timeline_schema_version": 1,
        "ledger_schema_version": 2,
        "model_view_schema_version": 2,
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
    contract = _contract_tuple(frozen_model_context_contract(rule_snapshot))
    return contract in {
        _contract_tuple(current_model_context_contract()),
        _contract_tuple(legacy_v7_model_context_contract()),
    }


def is_legacy_v7_model_context_contract(contract: dict[str, Any] | None) -> bool:
    return _contract_tuple(contract) == _contract_tuple(legacy_v7_model_context_contract())


def supports_current_model_context_contract(
    rule_snapshot: dict[str, Any] | None,
) -> bool:
    """Backward-compatible name for callers that mean any supported frozen contract."""

    return supports_model_context_contract(rule_snapshot)


def _contract_tuple(value: dict[str, Any] | None) -> tuple[tuple[str, int], ...]:
    if not isinstance(value, dict):
        return ()
    return tuple(
        sorted(
            (key, item)
            for key, item in value.items()
            if isinstance(key, str) and isinstance(item, int) and not isinstance(item, bool)
        )
    )
