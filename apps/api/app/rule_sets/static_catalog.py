from __future__ import annotations

from app.rule_sets.errors import RuleRevisionChanged, RuleSetNotFound
from app.rule_sets.snapshots import resolve_rule_set_snapshot
from app.rule_sets.types import CompiledRuleSet
from app.werewolf.rules import (
    OFFICIAL_RULE_SETS,
    freeze_rule_set_snapshot,
    rule_set_snapshot,
)


STATIC_RULE_REVISIONS = {
    "classic_8": (
        "e9fa678e-9b18-5079-91d2-f74835364fb6",
        "104d9818faac73536d50d57ca93eb623ca2dc044a4e334c6b72fcdbb0c2f5cef",
        True,
    ),
    "starter_6": (
        "b607e17e-b86f-5eb0-9dc2-b8df09aa71ab",
        "d0e67f0238dbb448afa86fd1b5b02ba303861572962b3054d8a3ea0ad913700f",
        False,
    ),
    "social_8": (
        "2b4a993f-e4e6-5312-b11d-92874851a70a",
        "25c6780c9e94df7729becf64a01a65e879236ae43c7efb0de03ac87312d1a21b",
        False,
    ),
    "classic_12_seer_witch_hunter_idiot": (
        "0489f6ac-16fd-5323-96ce-ee256c98cf32",
        "b81db40986fb3be46e377d68dc3870a0137fe78779c5f0997a5eeeb42a5e396a",
        False,
    ),
}


def static_compiled_rule_set_entries() -> list[tuple[CompiledRuleSet, bool]]:
    entries: list[tuple[CompiledRuleSet, bool]] = []
    for rule_set in OFFICIAL_RULE_SETS:
        revision_id, content_hash, is_default = STATIC_RULE_REVISIONS[rule_set.id]
        snapshot: dict[str, object] = rule_set_snapshot(rule_set)
        snapshot.update(
            {
                "version": "1",
                "revision_id": revision_id,
                "revision_no": 1,
                "schema_version": 1,
                "content_hash": content_hash,
            }
        )
        legacy_compiled = resolve_rule_set_snapshot(snapshot)
        frozen_snapshot = freeze_rule_set_snapshot(legacy_compiled.rule_set)
        frozen_snapshot.update(
            {
                "revision_id": revision_id,
                "revision_no": 1,
                "schema_version": 1,
                "content_hash": content_hash,
            }
        )
        entries.append((resolve_rule_set_snapshot(frozen_snapshot), is_default))
    return entries


def resolve_static_rule_set(
    rule_set_id: str,
    *,
    expected_revision_id: str | None,
) -> CompiledRuleSet:
    entry = next(
        (
            compiled
            for compiled, _is_default in static_compiled_rule_set_entries()
            if compiled.rule_set.id == rule_set_id
        ),
        None,
    )
    if entry is None:
        raise RuleSetNotFound(rule_set_id)
    if expected_revision_id is not None and entry.revision_id != expected_revision_id:
        raise RuleRevisionChanged(
            rule_set_id,
            expected_revision_id=expected_revision_id,
            current_revision_id=entry.revision_id,
        )
    return entry
