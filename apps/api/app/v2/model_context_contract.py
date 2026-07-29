from __future__ import annotations

from typing import Any


MODEL_PROMPT_SCHEMA_VERSION = 6
PUBLIC_TIMELINE_SCHEMA_VERSION = 1
DISCOURSE_LEDGER_SCHEMA_VERSION = 2
DISCOURSE_MODEL_VIEW_SCHEMA_VERSION = 1

_CONTRACT_KEY = "model_context_contract"


def current_model_context_contract() -> dict[str, int]:
    return {
        "prompt_schema_version": MODEL_PROMPT_SCHEMA_VERSION,
        "public_timeline_schema_version": PUBLIC_TIMELINE_SCHEMA_VERSION,
        "ledger_schema_version": DISCOURSE_LEDGER_SCHEMA_VERSION,
        "model_view_schema_version": DISCOURSE_MODEL_VIEW_SCHEMA_VERSION,
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


def supports_current_model_context_contract(
    rule_snapshot: dict[str, Any] | None,
) -> bool:
    return frozen_model_context_contract(rule_snapshot) == current_model_context_contract()
