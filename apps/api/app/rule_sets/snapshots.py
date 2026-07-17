from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import replace
from collections.abc import Iterable, Mapping
from typing import TYPE_CHECKING, cast

from app.models.rule_set import RuleSetRevisionRecord
from app.rule_sets.errors import RuleSetCatalogCorrupt
from app.rule_sets.telemetry import record_rule_snapshot_failure
from app.rule_sets.types import CompiledRuleSet, RuleRoleId, RuleSetConfig
from app.rule_sets.validation import (
    RULE_ROLE_IDS,
    normalize_rule_set_config,
    validate_rule_set_config,
)
from app.werewolf.rules import (
    ACTION_DEBATE,
    ACTION_EXILE_LAST_WORDS,
    ACTION_HUNTER_SHOOT,
    ACTION_INVESTIGATE,
    ACTION_PROTECT,
    ACTION_REMOVE,
    ACTION_SHERIFF_PK_SPEECH,
    ACTION_SHERIFF_RUN,
    ACTION_SHERIFF_RUNOFF_VOTE,
    ACTION_SHERIFF_SPEECH,
    ACTION_SHERIFF_VOTE,
    ACTION_SHERIFF_WITHDRAW,
    ACTION_SPEECH_ORDER,
    ACTION_SUMMARIZE,
    ACTION_VOTE,
    ACTION_WEREWOLF_SELF_EXPLOSION,
    ACTION_WITCH_POISON,
    ACTION_WITCH_SAVE,
    MODEL_GROUP_VILLAGER,
    MODEL_GROUP_WEREWOLF,
    REVEAL_POLICY_HIDDEN,
    ROLE_CATEGORY_CIVILIAN,
    ROLE_CATEGORY_GOD,
    ROLE_CATEGORY_WEREWOLF,
    RULE_SET_VERSION,
    SPEECH_POLICY_SHERIFF_DIRECTED,
    TEAM_VILLAGERS,
    TEAM_WEREWOLVES,
    RoleSpec,
    RuleSet,
    rule_set_snapshot,
)


if TYPE_CHECKING:
    from app.rule_sets.repository import RuleSetAggregate


RULE_SCHEMA_VERSION = 1
_MAX_ADMIN_REVISION_HISTORY = 50
ROLE_ORDER: tuple[RuleRoleId, ...] = (
    "werewolf",
    "seer",
    "guard",
    "witch",
    "hunter",
    "idiot",
    "villager",
)

_RUNTIME_FIELDS = (
    "id",
    "version",
    "name",
    "description",
    "player_count",
    "roles",
    "night_actions",
    "day_actions",
    "win_condition",
    "reveal_policy",
    "complexity",
    "estimated_duration",
    "sheriff_enabled",
    "sheriff_vote_weight",
    "werewolf_self_explosion_enabled",
    "exile_last_words_enabled",
    "sheriff_badge_bomb_policy",
    "speech_policy",
    "speech_rounds",
    "rule_tags",
)
_RUNTIME_FIELD_SET = frozenset(_RUNTIME_FIELDS)
_LEGACY_OPTIONAL_RUNTIME_FIELDS = frozenset({"exile_last_words_enabled"})
_REVISION_FIELDS = frozenset({"revision_id", "revision_no", "schema_version", "content_hash"})
_ROLE_FIELDS = frozenset({"role", "count", "team", "model_group", "category"})
_CONTENT_HASH_PATTERN = re.compile(r"[0-9a-f]{64}")
_CHANGED_FIELD_PATTERN = re.compile(r"[A-Za-z][A-Za-z0-9_.-]{0,119}")

_ROLE_DEFINITIONS: dict[RuleRoleId, tuple[str, str, str, str]] = {
    "werewolf": (
        "狼人",
        TEAM_WEREWOLVES,
        MODEL_GROUP_WEREWOLF,
        ROLE_CATEGORY_WEREWOLF,
    ),
    "seer": ("预言家", TEAM_VILLAGERS, MODEL_GROUP_VILLAGER, ROLE_CATEGORY_GOD),
    "guard": ("守卫", TEAM_VILLAGERS, MODEL_GROUP_VILLAGER, ROLE_CATEGORY_GOD),
    "witch": ("女巫", TEAM_VILLAGERS, MODEL_GROUP_VILLAGER, ROLE_CATEGORY_GOD),
    "hunter": ("猎人", TEAM_VILLAGERS, MODEL_GROUP_VILLAGER, ROLE_CATEGORY_GOD),
    "idiot": ("白痴", TEAM_VILLAGERS, MODEL_GROUP_VILLAGER, ROLE_CATEGORY_GOD),
    "villager": (
        "村民",
        TEAM_VILLAGERS,
        MODEL_GROUP_VILLAGER,
        ROLE_CATEGORY_CIVILIAN,
    ),
}
_ROLE_IDS_BY_DEFINITION = {definition: role_id for role_id, definition in _ROLE_DEFINITIONS.items()}


def canonical_rule_set_config(config: RuleSetConfig) -> dict[str, object]:
    config = _normalize_config_boundary(config)
    return {
        "name": config.name,
        "description": config.description,
        "complexity": config.complexity,
        "estimated_duration": config.estimated_duration,
        "rule_tags": list(config.rule_tags),
        "role_counts": {role_id: config.role_counts[role_id] for role_id in RULE_ROLE_IDS},
        "win_condition": config.win_condition,
        "sheriff_enabled": config.sheriff_enabled,
        "sheriff_vote_weight": float(config.sheriff_vote_weight),
        "speech_policy": config.speech_policy,
        "werewolf_self_explosion_enabled": config.werewolf_self_explosion_enabled,
        "sheriff_badge_bomb_policy": config.sheriff_badge_bomb_policy,
    }


def rule_set_content_hash(config: RuleSetConfig) -> str:
    payload = {
        "schema_version": RULE_SCHEMA_VERSION,
        "config": canonical_rule_set_config(config),
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def compile_rule_set_config(
    rule_set_id: str,
    config: RuleSetConfig,
    *,
    revision_id: str,
    revision_no: int,
) -> CompiledRuleSet:
    _validate_rule_set_id(rule_set_id)
    _validate_revision_metadata(revision_id, revision_no, RULE_SCHEMA_VERSION, None)
    config = _normalize_config_boundary(config)
    return _compile_rule_set(
        rule_set_id,
        config,
        version=str(revision_no),
        revision_id=revision_id,
        revision_no=revision_no,
    )


def rule_set_config_from_snapshot(snapshot: Mapping[str, object]) -> RuleSetConfig:
    _, config = _resolve_snapshot(snapshot)
    return config


def resolve_rule_set_snapshot(snapshot: Mapping[str, object]) -> CompiledRuleSet:
    try:
        compiled, _ = _resolve_snapshot(snapshot)
    except Exception as exc:
        record_rule_snapshot_failure(_snapshot_failure_reason(exc))
        raise
    return compiled


def _snapshot_failure_reason(exc: Exception) -> str:
    message = str(exc)
    if message in {
        "snapshot content_hash does not match canonical configuration",
        "content_hash must be 64 lowercase hexadecimal characters",
    }:
        return "content_hash_mismatch"
    if message == f"schema_version must be {RULE_SCHEMA_VERSION}":
        return "schema_version_unsupported"
    return "invalid_snapshot"


def admin_rule_revision_snapshot(
    revision: RuleSetRevisionRecord,
    *,
    include_config: bool,
) -> dict[str, object]:
    return {
        "id": revision.id,
        "rule_set_id": revision.rule_set_id,
        "revision_no": revision.revision_no,
        "state": revision.state,
        "schema_version": revision.schema_version,
        "content_hash": revision.content_hash,
        "lock_version": revision.lock_version,
        "config": _admin_revision_config(revision) if include_config else None,
        "player_count": revision.player_count,
        "role_summary": revision.role_summary,
        "created_at": revision.created_at,
        "updated_at": revision.updated_at,
        "published_at": revision.published_at,
        "published_by": _actor_id(revision.published_by_user_id),
    }


def admin_rule_set_snapshot(aggregate: RuleSetAggregate) -> dict[str, object]:
    record = aggregate.record
    return {
        "id": record.id,
        "status": record.status,
        "is_default": record.is_default,
        "display_order": record.display_order,
        "lock_version": record.lock_version,
        "draft_revision": (
            admin_rule_revision_snapshot(aggregate.draft, include_config=True)
            if aggregate.draft is not None
            else None
        ),
        "published_revision": (
            admin_rule_revision_snapshot(aggregate.published, include_config=True)
            if aggregate.published is not None
            else None
        ),
        "revisions": [
            admin_rule_revision_snapshot(revision, include_config=False)
            for revision in aggregate.revisions[:_MAX_ADMIN_REVISION_HISTORY]
        ],
        "created_at": record.created_at,
        "updated_at": record.updated_at,
    }


def public_rule_set_catalog_snapshot(aggregate: RuleSetAggregate) -> dict[str, object]:
    compiled = compile_published_rule_set_aggregate(aggregate)
    record = aggregate.record
    snapshot: dict[str, object] = {key: value for key, value in compiled.snapshot.items()}
    snapshot["roles"] = [dict(role) for role in cast(list[dict[str, object]], snapshot["roles"])]
    snapshot.update(
        {
            "is_default": record.is_default,
            "display_order": record.display_order,
            "role_summary": " / ".join(
                f"{role.count} {role.role}" for role in compiled.rule_set.roles
            ),
        }
    )
    return snapshot


def audit_rule_set_snapshot(
    aggregate: RuleSetAggregate,
    *,
    changed_fields: Iterable[str] = (),
) -> dict[str, object]:
    return {
        "id": aggregate.record.id,
        "status": aggregate.record.status,
        "lock_version": aggregate.record.lock_version,
        "draft_revision": _audit_revision_snapshot(aggregate.draft),
        "published_revision": _audit_revision_snapshot(aggregate.published),
        "changed_fields": _bounded_changed_fields(changed_fields),
    }


def _compile_rule_set(
    rule_set_id: str,
    config: RuleSetConfig,
    *,
    version: str,
    revision_id: str | None,
    revision_no: int | None,
) -> CompiledRuleSet:
    roles = tuple(
        RoleSpec(
            _ROLE_DEFINITIONS[role_id][0],
            config.role_counts[role_id],
            _ROLE_DEFINITIONS[role_id][1],
            _ROLE_DEFINITIONS[role_id][2],
            _ROLE_DEFINITIONS[role_id][3],
        )
        for role_id in ROLE_ORDER
        if config.role_counts[role_id]
    )
    rule_set = RuleSet(
        id=rule_set_id,
        version=version,
        name=config.name,
        description=config.description,
        player_count=config.player_count,
        roles=roles,
        night_actions=_night_actions(config),
        day_actions=_day_actions(config),
        win_condition=config.win_condition,
        reveal_policy=REVEAL_POLICY_HIDDEN,
        complexity=config.complexity,
        estimated_duration=config.estimated_duration,
        sheriff_enabled=config.sheriff_enabled,
        sheriff_vote_weight=config.sheriff_vote_weight,
        speech_policy=config.speech_policy,
        speech_rounds=1,
        rule_tags=config.rule_tags,
        werewolf_self_explosion_enabled=config.werewolf_self_explosion_enabled,
        exile_last_words_enabled=True,
        sheriff_badge_bomb_policy=config.sheriff_badge_bomb_policy,
    )
    content_hash = rule_set_content_hash(config)
    snapshot = rule_set_snapshot(rule_set)
    if revision_id is not None and revision_no is not None:
        snapshot.update(
            {
                "revision_id": revision_id,
                "revision_no": revision_no,
                "schema_version": RULE_SCHEMA_VERSION,
                "content_hash": content_hash,
            }
        )
    return CompiledRuleSet(
        rule_set=rule_set,
        snapshot=snapshot,
        schema_version=RULE_SCHEMA_VERSION,
        revision_id=revision_id,
        revision_no=revision_no,
        content_hash=content_hash,
    )


def _resolve_snapshot(
    snapshot: Mapping[str, object],
) -> tuple[CompiledRuleSet, RuleSetConfig]:
    managed = _validate_snapshot_shape(snapshot)
    _validate_runtime_types(snapshot)
    role_counts = _role_counts_from_snapshot(snapshot["roles"])
    config = normalize_rule_set_config(
        {
            "name": snapshot["name"],
            "description": snapshot["description"],
            "complexity": snapshot["complexity"],
            "estimated_duration": snapshot["estimated_duration"],
            "rule_tags": snapshot["rule_tags"],
            "role_counts": role_counts,
            "win_condition": snapshot["win_condition"],
            "sheriff_enabled": snapshot["sheriff_enabled"],
            "sheriff_vote_weight": snapshot["sheriff_vote_weight"],
            "speech_policy": snapshot["speech_policy"],
            "werewolf_self_explosion_enabled": snapshot["werewolf_self_explosion_enabled"],
            "sheriff_badge_bomb_policy": snapshot["sheriff_badge_bomb_policy"],
        }
    )
    _raise_for_invalid_config(config)

    rule_set_id = cast(str, snapshot["id"])
    if managed:
        revision_id = cast(str, snapshot["revision_id"])
        revision_no = cast(int, snapshot["revision_no"])
        schema_version = cast(int, snapshot["schema_version"])
        content_hash = cast(str, snapshot["content_hash"])
        _validate_revision_metadata(
            revision_id,
            revision_no,
            schema_version,
            content_hash,
        )
        if snapshot["version"] != str(revision_no):
            raise ValueError("managed snapshot version must equal revision_no")
        compiled = compile_rule_set_config(
            rule_set_id,
            config,
            revision_id=revision_id,
            revision_no=revision_no,
        )
        if content_hash != compiled.content_hash:
            raise ValueError("snapshot content_hash does not match canonical configuration")
    else:
        if snapshot["version"] != RULE_SET_VERSION:
            raise ValueError(f"legacy snapshot version must be {RULE_SET_VERSION}")
        compiled = _compile_rule_set(
            rule_set_id,
            config,
            version=RULE_SET_VERSION,
            revision_id=None,
            revision_no=None,
        )

    if snapshot.get("exile_last_words_enabled") is not True:
        legacy_rule_set = replace(
            compiled.rule_set,
            day_actions=tuple(
                action
                for action in compiled.rule_set.day_actions
                if action != ACTION_EXILE_LAST_WORDS
            ),
            exile_last_words_enabled=False,
        )
        legacy_snapshot = {
            **compiled.snapshot,
            "day_actions": list(legacy_rule_set.day_actions),
            "exile_last_words_enabled": False,
        }
        if "exile_last_words_enabled" not in snapshot:
            legacy_snapshot.pop("exile_last_words_enabled", None)
        compiled = replace(
            compiled,
            rule_set=legacy_rule_set,
            snapshot=legacy_snapshot,
        )

    _compare_runtime_snapshot(snapshot, compiled.snapshot)
    return compiled, config


def _validate_snapshot_shape(snapshot: Mapping[str, object]) -> bool:
    if not isinstance(snapshot, Mapping):
        raise ValueError("rule set snapshot must be a mapping")

    fields = set(snapshot)
    unknown = fields - _RUNTIME_FIELD_SET - _REVISION_FIELDS
    if unknown:
        names = ", ".join(sorted(str(field) for field in unknown))
        raise ValueError(f"Unsupported snapshot fields: {names}")

    missing = _RUNTIME_FIELD_SET - _LEGACY_OPTIONAL_RUNTIME_FIELDS - fields
    if missing:
        names = ", ".join(sorted(missing))
        raise ValueError(f"Snapshot is missing required fields: {names}")

    present_revision_fields = fields & _REVISION_FIELDS
    if present_revision_fields and present_revision_fields != _REVISION_FIELDS:
        raise ValueError("snapshot revision metadata must be all present or all absent")
    return bool(present_revision_fields)


def _validate_runtime_types(snapshot: Mapping[str, object]) -> None:
    for field in (
        "id",
        "version",
        "name",
        "description",
        "win_condition",
        "reveal_policy",
        "complexity",
        "estimated_duration",
        "sheriff_badge_bomb_policy",
        "speech_policy",
    ):
        if not isinstance(snapshot[field], str):
            raise ValueError(f"snapshot field {field} must be text")
    _validate_rule_set_id(cast(str, snapshot["id"]))

    for field in ("player_count", "speech_rounds"):
        value = snapshot[field]
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(f"snapshot field {field} must be an integer")

    for field in ("sheriff_enabled", "werewolf_self_explosion_enabled"):
        if not isinstance(snapshot[field], bool):
            raise ValueError(f"snapshot field {field} must be a boolean")
    if "exile_last_words_enabled" in snapshot and not isinstance(
        snapshot["exile_last_words_enabled"], bool
    ):
        raise ValueError("snapshot field exile_last_words_enabled must be a boolean")

    vote_weight = snapshot["sheriff_vote_weight"]
    if isinstance(vote_weight, bool) or not isinstance(vote_weight, (int, float)):
        raise ValueError("snapshot field sheriff_vote_weight must be numeric")
    if not isinstance(vote_weight, float):
        raise ValueError("snapshot field sheriff_vote_weight must be a float")
    if not math.isfinite(vote_weight):
        raise ValueError("snapshot field sheriff_vote_weight must be finite")

    _validate_string_list(snapshot["night_actions"], "night_actions")
    _validate_string_list(snapshot["day_actions"], "day_actions")
    _validate_string_list(snapshot["rule_tags"], "rule_tags")
    if not isinstance(snapshot["roles"], list):
        raise ValueError("snapshot field roles must be a list")


def _validate_string_list(value: object, field: str) -> None:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ValueError(f"snapshot field {field} must be a list of strings")


def _role_counts_from_snapshot(value: object) -> dict[RuleRoleId, int]:
    if not isinstance(value, list):
        raise ValueError("snapshot field roles must be a list")

    counts: dict[RuleRoleId, int] = {role_id: 0 for role_id in RULE_ROLE_IDS}
    seen: set[RuleRoleId] = set()
    for index, raw_role in enumerate(value):
        if not isinstance(raw_role, Mapping):
            raise ValueError(f"snapshot role {index} must be a mapping")
        fields = set(raw_role)
        if fields != _ROLE_FIELDS:
            raise ValueError(f"snapshot role {index} must contain exactly the runtime role fields")

        count = raw_role["count"]
        if isinstance(count, bool) or not isinstance(count, int) or count <= 0:
            raise ValueError(f"snapshot role {index} count must be a positive integer")
        metadata = (
            raw_role["role"],
            raw_role["team"],
            raw_role["model_group"],
            raw_role["category"],
        )
        if any(not isinstance(field, str) for field in metadata):
            raise ValueError(f"snapshot role metadata must be text (index {index})")
        definition = (
            cast(str, metadata[0]),
            cast(str, metadata[1]),
            cast(str, metadata[2]),
            cast(str, metadata[3]),
        )
        role_id = _ROLE_IDS_BY_DEFINITION.get(definition)
        if role_id is None:
            raise ValueError(f"snapshot role {index} has unsupported role metadata")
        if role_id in seen:
            raise ValueError(f"snapshot role {index} duplicates {role_id}")
        seen.add(role_id)
        counts[role_id] = count
    return counts


def _compare_runtime_snapshot(
    snapshot: Mapping[str, object], expected: Mapping[str, object]
) -> None:
    for field in _RUNTIME_FIELDS:
        if field in _LEGACY_OPTIONAL_RUNTIME_FIELDS and field not in snapshot:
            continue
        if snapshot[field] != expected[field]:
            raise ValueError(f"snapshot field {field} does not match compiled configuration")


def _raise_for_invalid_config(config: RuleSetConfig) -> None:
    if not isinstance(config, RuleSetConfig):
        raise ValueError("config must be a normalized RuleSetConfig")
    result = validate_rule_set_config(config)
    if result.valid:
        return
    issues = ", ".join(f"{issue.code} ({issue.path})" for issue in result.errors)
    raise ValueError(f"rule configuration is invalid: {issues}")


def _normalize_config_boundary(config: RuleSetConfig) -> RuleSetConfig:
    if not isinstance(config, RuleSetConfig):
        raise ValueError("config must be a normalized RuleSetConfig")
    try:
        normalized = normalize_rule_set_config(
            {
                "name": config.name,
                "description": config.description,
                "complexity": config.complexity,
                "estimated_duration": config.estimated_duration,
                "rule_tags": config.rule_tags,
                "role_counts": config.role_counts,
                "win_condition": config.win_condition,
                "sheriff_enabled": config.sheriff_enabled,
                "sheriff_vote_weight": config.sheriff_vote_weight,
                "speech_policy": config.speech_policy,
                "werewolf_self_explosion_enabled": (config.werewolf_self_explosion_enabled),
                "sheriff_badge_bomb_policy": config.sheriff_badge_bomb_policy,
            }
        )
    except ValueError:
        raise
    except (AttributeError, KeyError, OverflowError, TypeError) as error:
        raise ValueError("config must be a valid normalized RuleSetConfig") from error
    _raise_for_invalid_config(normalized)
    return normalized


def _validate_rule_set_id(rule_set_id: str) -> None:
    if not isinstance(rule_set_id, str) or not rule_set_id.strip():
        raise ValueError("rule_set_id must be non-empty text")


def _validate_revision_metadata(
    revision_id: object,
    revision_no: object,
    schema_version: object,
    content_hash: object | None,
) -> None:
    if not isinstance(revision_id, str) or not revision_id.strip():
        raise ValueError("revision_id must be non-empty text")
    if isinstance(revision_no, bool) or not isinstance(revision_no, int) or revision_no <= 0:
        raise ValueError("revision_no must be a positive integer")
    if (
        isinstance(schema_version, bool)
        or not isinstance(schema_version, int)
        or schema_version != RULE_SCHEMA_VERSION
    ):
        raise ValueError(f"schema_version must be {RULE_SCHEMA_VERSION}")
    if content_hash is not None and (
        not isinstance(content_hash, str) or _CONTENT_HASH_PATTERN.fullmatch(content_hash) is None
    ):
        raise ValueError("content_hash must be 64 lowercase hexadecimal characters")


def _night_actions(config: RuleSetConfig) -> tuple[str, ...]:
    actions = [ACTION_REMOVE]
    if config.role_counts["guard"]:
        actions.append(ACTION_PROTECT)
    if config.role_counts["seer"]:
        actions.append(ACTION_INVESTIGATE)
    if config.role_counts["witch"]:
        actions.extend((ACTION_WITCH_SAVE, ACTION_WITCH_POISON))
    return tuple(actions)


def _day_actions(config: RuleSetConfig) -> tuple[str, ...]:
    actions: list[str] = []
    if config.sheriff_enabled:
        actions.extend(
            (
                ACTION_SHERIFF_RUN,
                ACTION_SHERIFF_SPEECH,
                ACTION_SHERIFF_WITHDRAW,
                ACTION_SHERIFF_VOTE,
                ACTION_SHERIFF_PK_SPEECH,
                ACTION_SHERIFF_RUNOFF_VOTE,
            )
        )
    if config.werewolf_self_explosion_enabled:
        actions.append(ACTION_WEREWOLF_SELF_EXPLOSION)
    if config.sheriff_enabled and config.speech_policy == SPEECH_POLICY_SHERIFF_DIRECTED:
        actions.append(ACTION_SPEECH_ORDER)
    actions.extend((ACTION_DEBATE, ACTION_VOTE))
    actions.append(ACTION_EXILE_LAST_WORDS)
    if config.role_counts["hunter"]:
        actions.append(ACTION_HUNTER_SHOOT)
    actions.append(ACTION_SUMMARIZE)
    return tuple(actions)


def _admin_revision_config(revision: RuleSetRevisionRecord) -> dict[str, object]:
    failure: RuleSetCatalogCorrupt | None = None
    try:
        config = normalize_rule_set_config(revision.config)
    except (AttributeError, KeyError, OverflowError, TypeError, ValueError):
        failure = RuleSetCatalogCorrupt(
            revision.rule_set_id,
            revision_id=revision.id,
            reason="revision_config_invalid",
        )
    if failure is not None:
        raise failure
    return {
        "name": config.name,
        "description": config.description,
        "complexity": config.complexity,
        "estimated_duration": config.estimated_duration,
        "rule_tags": list(config.rule_tags),
        "role_counts": {role_id: config.role_counts[role_id] for role_id in RULE_ROLE_IDS},
        "win_condition": config.win_condition,
        "sheriff_enabled": config.sheriff_enabled,
        "sheriff_vote_weight": config.sheriff_vote_weight,
        "speech_policy": config.speech_policy,
        "werewolf_self_explosion_enabled": config.werewolf_self_explosion_enabled,
        "sheriff_badge_bomb_policy": config.sheriff_badge_bomb_policy,
    }


def compile_published_rule_set_aggregate(
    aggregate: RuleSetAggregate,
    *,
    allow_archived: bool = False,
) -> CompiledRuleSet:
    record = aggregate.record
    revision = aggregate.published
    parent_available = record.status == "published" and record.archived_at is None
    archived_retention = (
        allow_archived and record.status == "archived" and record.archived_at is not None
    )
    if (
        not (parent_available or archived_retention)
        or revision is None
        or record.current_published_revision_id != revision.id
        or revision.rule_set_id != record.id
        or revision.state != "published"
    ):
        raise RuleSetCatalogCorrupt(
            record.id,
            pointer="current_published_revision_id",
            revision_id=(
                revision.id if revision is not None else record.current_published_revision_id
            ),
            reason="public_revision_unavailable",
        )
    if revision.schema_version != RULE_SCHEMA_VERSION:
        raise RuleSetCatalogCorrupt(
            record.id,
            pointer="current_published_revision_id",
            revision_id=revision.id,
            reason="schema_version_unsupported",
        )
    failure: RuleSetCatalogCorrupt | None = None
    try:
        config = normalize_rule_set_config(revision.config)
        compiled = compile_rule_set_config(
            record.id,
            config,
            revision_id=revision.id,
            revision_no=revision.revision_no,
        )
    except (AttributeError, KeyError, OverflowError, TypeError, ValueError):
        failure = RuleSetCatalogCorrupt(
            record.id,
            pointer="current_published_revision_id",
            revision_id=revision.id,
            reason="published_config_invalid",
        )
    if failure is not None:
        raise failure
    if revision.content_hash != compiled.content_hash:
        raise RuleSetCatalogCorrupt(
            record.id,
            pointer="current_published_revision_id",
            revision_id=revision.id,
            reason="content_hash_mismatch",
        )
    return compiled


def _audit_revision_snapshot(
    revision: RuleSetRevisionRecord | None,
) -> dict[str, object] | None:
    if revision is None:
        return None
    return {
        "id": revision.id,
        "rule_set_id": revision.rule_set_id,
        "revision_no": revision.revision_no,
        "state": revision.state,
        "schema_version": revision.schema_version,
        "content_hash": revision.content_hash,
        "lock_version": revision.lock_version,
    }


def _bounded_changed_fields(changed_fields: Iterable[str]) -> list[str]:
    bounded: list[str] = []
    seen: set[str] = set()
    for field in changed_fields:
        if len(bounded) >= 50:
            break
        if not isinstance(field, str):
            continue
        normalized = field[:120]
        if _CHANGED_FIELD_PATTERN.fullmatch(normalized) is not None and normalized not in seen:
            seen.add(normalized)
            bounded.append(normalized)
    return bounded


def _actor_id(value: int | None) -> str | None:
    return str(value) if value is not None else None
