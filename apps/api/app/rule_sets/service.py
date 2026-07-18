from __future__ import annotations

import uuid
from dataclasses import dataclass, replace
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import StaleDataError

from app.models.rule_set import RuleSetRecord, RuleSetRevisionRecord
from app.rule_sets.contracts import build_admin_rule_contract
from app.rule_sets.errors import (
    DefaultRuleRequired,
    RuleRevisionChanged,
    RuleSetCatalogCorrupt,
    RuleSetNotFound,
    RuleSetRevisionNotFound,
    RuleSetTransitionConflict,
    RuleSetUnavailable,
    RuleSetValidationFailed,
    RuleSetVersionConflict,
)
from app.rule_sets.repository import (
    RuleSetAggregate,
    get_rule_set_aggregate,
    get_rule_set_record,
    next_rule_set_revision_no,
)
from app.rule_sets.snapshots import (
    RULE_SCHEMA_VERSION,
    compile_published_rule_set_aggregate,
    compile_rule_set_config,
    public_rule_set_catalog_snapshot,
    resolve_rule_set_snapshot,
)
from app.rule_sets.types import (
    CompiledRuleSet,
    RuleSetConfig,
    RuleSetValidationResult,
    RuleValidationIssue,
)
from app.rule_sets.validation import (
    RULE_ROLE_IDS,
    normalize_rule_set_config,
    validate_rule_set_config,
)


_ROLE_ORDER = ("werewolf", "seer", "guard", "witch", "hunter", "idiot", "villager")
_ROLE_LABELS = {
    "werewolf": "狼人",
    "villager": "村民",
    "seer": "预言家",
    "guard": "守卫",
    "witch": "女巫",
    "hunter": "猎人",
    "idiot": "白痴",
}
_PUBLIC_METADATA_FIELDS = frozenset({"is_default", "display_order", "role_summary"})


@dataclass(frozen=True)
class RuleSetDraftValidation:
    aggregate: RuleSetAggregate
    validation: RuleSetValidationResult
    compiled: CompiledRuleSet | None


@dataclass(frozen=True)
class RuleSetDefaultChange:
    previous_default: RuleSetAggregate | None
    current_default: RuleSetAggregate


def compile_rule_set_revision(revision: RuleSetRevisionRecord) -> CompiledRuleSet:
    return compile_rule_set_config(
        revision.rule_set_id,
        _normalized_revision_config(revision),
        revision_id=revision.id,
        revision_no=revision.revision_no,
    )


def create_rule_set(
    db: Session,
    *,
    rule_set_id: str,
    config: RuleSetConfig,
    display_order: int,
    actor_user_id: int,
) -> RuleSetAggregate:
    _validate_display_order(rule_set_id, display_order)
    _flush_with_conflict(db, rule_set_id)
    if (existing := get_rule_set_record(db, rule_set_id)) is not None:
        raise RuleSetTransitionConflict(
            rule_set_id,
            current_status=existing.status,
            target_status="draft",
        )
    normalized = _normalize_management_config(config)
    revision_id = str(uuid.uuid4())
    now = datetime.now(UTC)
    record = RuleSetRecord(
        id=rule_set_id,
        status="draft",
        current_published_revision_id=None,
        draft_revision_id=revision_id,
        is_default=False,
        display_order=display_order,
        created_by_user_id=actor_user_id,
        updated_by_user_id=actor_user_id,
        archived_by_user_id=None,
        created_at=now,
        updated_at=now,
        archived_at=None,
    )
    revision = _new_draft_revision(
        revision_id=revision_id,
        rule_set_id=rule_set_id,
        revision_no=1,
        config=normalized,
        actor_user_id=actor_user_id,
        now=now,
    )
    db.add_all((record, revision))
    _flush_with_conflict(db, rule_set_id)
    return _required_aggregate(db, rule_set_id)


def update_rule_set_draft(
    db: Session,
    rule_set_id: str,
    *,
    config: RuleSetConfig,
    display_order: int,
    expected_rule_set_lock_version: int,
    expected_revision_lock_version: int | None,
    actor_user_id: int,
) -> RuleSetAggregate:
    _validate_display_order(rule_set_id, display_order)
    _flush_with_conflict(
        db,
        rule_set_id,
        expected_rule_set_lock_version=expected_rule_set_lock_version,
        expected_revision_lock_version=expected_revision_lock_version,
    )
    aggregate = _required_aggregate(db, rule_set_id, for_update=True)
    if aggregate.record.lock_version != expected_rule_set_lock_version:
        raise RuleSetVersionConflict(
            rule_set_id,
            expected_rule_set_lock_version=expected_rule_set_lock_version,
            current_rule_set_lock_version=aggregate.record.lock_version,
            expected_revision_lock_version=expected_revision_lock_version,
            current_revision_lock_version=(
                aggregate.draft.lock_version if aggregate.draft is not None else None
            ),
        )

    normalized = _normalize_management_config(config)
    now = datetime.now(UTC)
    draft = aggregate.draft
    if draft is None:
        if expected_revision_lock_version is not None:
            raise RuleSetVersionConflict(
                rule_set_id,
                expected_rule_set_lock_version=expected_rule_set_lock_version,
                current_rule_set_lock_version=aggregate.record.lock_version,
                expected_revision_lock_version=expected_revision_lock_version,
                current_revision_lock_version=None,
            )
        draft = _new_draft_revision(
            revision_id=str(uuid.uuid4()),
            rule_set_id=rule_set_id,
            revision_no=next_rule_set_revision_no(db, rule_set_id),
            config=normalized,
            actor_user_id=actor_user_id,
            now=now,
        )
        db.add(draft)
        aggregate.record.draft_revision_id = draft.id
    else:
        if draft.lock_version != expected_revision_lock_version:
            raise RuleSetVersionConflict(
                rule_set_id,
                revision_id=draft.id,
                expected_rule_set_lock_version=expected_rule_set_lock_version,
                current_rule_set_lock_version=aggregate.record.lock_version,
                expected_revision_lock_version=expected_revision_lock_version,
                current_revision_lock_version=draft.lock_version,
            )
        _write_draft_config(draft, normalized)
        draft.updated_by_user_id = actor_user_id
        draft.updated_at = now

    aggregate.record.display_order = display_order
    aggregate.record.updated_by_user_id = actor_user_id
    aggregate.record.updated_at = now
    _flush_with_conflict(
        db,
        rule_set_id,
        revision_id=draft.id,
        expected_rule_set_lock_version=expected_rule_set_lock_version,
        expected_revision_lock_version=expected_revision_lock_version,
    )
    return _required_aggregate(db, rule_set_id)


def validate_rule_set_draft(
    db: Session,
    rule_set_id: str,
    *,
    expected_revision_lock_version: int,
) -> RuleSetDraftValidation:
    _flush_with_conflict(
        db,
        rule_set_id,
        expected_revision_lock_version=expected_revision_lock_version,
    )
    aggregate = _required_aggregate(db, rule_set_id, for_update=True)
    draft = aggregate.draft
    if draft is None:
        raise RuleSetRevisionNotFound(
            rule_set_id,
            revision_id=aggregate.record.draft_revision_id,
        )
    if draft.lock_version != expected_revision_lock_version:
        raise RuleSetVersionConflict(
            rule_set_id,
            revision_id=draft.id,
            current_rule_set_lock_version=aggregate.record.lock_version,
            expected_revision_lock_version=expected_revision_lock_version,
            current_revision_lock_version=draft.lock_version,
        )

    config = _normalized_revision_config(draft)
    validation = validate_rule_set_config(config)
    compiled: CompiledRuleSet | None = None
    if validation.valid:
        candidate = compile_rule_set_revision(draft)
        compiled = resolve_rule_set_snapshot(candidate.snapshot)
    return RuleSetDraftValidation(
        aggregate=aggregate,
        validation=validation,
        compiled=compiled,
    )


def archive_rule_set(
    db: Session,
    rule_set_id: str,
    *,
    expected_rule_set_lock_version: int,
    replacement_default_rule_set_id: str | None,
    replacement_expected_lock_version: int | None,
    reason: str,
    actor_user_id: int,
) -> RuleSetAggregate:
    _flush_with_conflict(
        db,
        rule_set_id,
        expected_rule_set_lock_version=expected_rule_set_lock_version,
    )
    lock_ids = [rule_set_id]
    if replacement_default_rule_set_id is not None:
        lock_ids.append(replacement_default_rule_set_id)
    locked = _lock_rule_set_aggregates(db, lock_ids)
    aggregate = locked[rule_set_id]
    record = aggregate.record
    _ensure_parent_version(
        record,
        expected_rule_set_lock_version=expected_rule_set_lock_version,
    )
    if record.status == "archived":
        raise RuleSetTransitionConflict(
            rule_set_id,
            current_status=record.status,
            target_status="archived",
        )
    if record.is_default:
        if (
            replacement_default_rule_set_id is None
            or replacement_expected_lock_version is None
            or replacement_default_rule_set_id == rule_set_id
        ):
            raise DefaultRuleRequired(
                rule_set_id,
                replacement_rule_set_id=replacement_default_rule_set_id,
            )
        replacement = locked[replacement_default_rule_set_id]
        _ensure_parent_version(
            replacement.record,
            expected_rule_set_lock_version=replacement_expected_lock_version,
        )
        _require_publishable_default(replacement)
        now = datetime.now(UTC)
        _mark_archived(record, actor_user_id=actor_user_id, now=now)
        _flush_with_conflict(
            db,
            rule_set_id,
            expected_rule_set_lock_version=expected_rule_set_lock_version,
        )
        _mark_default(replacement.record, actor_user_id=actor_user_id, now=now)
        _flush_with_conflict(
            db,
            replacement.record.id,
            expected_rule_set_lock_version=replacement_expected_lock_version,
        )
        return _required_aggregate(db, rule_set_id)

    if replacement_default_rule_set_id is not None or replacement_expected_lock_version is not None:
        raise RuleSetTransitionConflict(
            rule_set_id,
            current_status=record.status,
            target_status="archived",
        )

    now = datetime.now(UTC)
    _mark_archived(record, actor_user_id=actor_user_id, now=now)
    _flush_with_conflict(
        db,
        rule_set_id,
        expected_rule_set_lock_version=expected_rule_set_lock_version,
    )
    return _required_aggregate(db, rule_set_id)


def restore_rule_set(
    db: Session,
    rule_set_id: str,
    *,
    expected_rule_set_lock_version: int,
    reason: str,
    actor_user_id: int,
) -> RuleSetAggregate:
    _flush_with_conflict(
        db,
        rule_set_id,
        expected_rule_set_lock_version=expected_rule_set_lock_version,
    )
    aggregate = _required_aggregate(db, rule_set_id, for_update=True)
    record = aggregate.record
    _ensure_parent_version(
        record,
        expected_rule_set_lock_version=expected_rule_set_lock_version,
    )
    if record.status != "archived":
        raise RuleSetTransitionConflict(
            rule_set_id,
            current_status=record.status,
            target_status=("published" if aggregate.published is not None else "draft"),
        )

    if aggregate.published is not None:
        compile_published_rule_set_aggregate(aggregate, allow_archived=True)
        target_status = "published"
    elif aggregate.draft is not None:
        target_status = "draft"
    else:
        raise RuleSetRevisionNotFound(rule_set_id)

    now = datetime.now(UTC)
    record.status = target_status
    record.updated_by_user_id = actor_user_id
    record.archived_by_user_id = None
    record.updated_at = now
    record.archived_at = None
    _flush_with_conflict(
        db,
        rule_set_id,
        expected_rule_set_lock_version=expected_rule_set_lock_version,
    )
    return _required_aggregate(db, rule_set_id)


def set_default_rule_set(
    db: Session,
    rule_set_id: str,
    *,
    expected_rule_set_lock_version: int,
    previous_default_expected_lock_version: int | None,
    reason: str,
    actor_user_id: int,
) -> RuleSetDefaultChange:
    _flush_with_conflict(
        db,
        rule_set_id,
        expected_rule_set_lock_version=expected_rule_set_lock_version,
    )
    previous_default_id = db.scalar(
        select(RuleSetRecord.id)
        .where(RuleSetRecord.is_default.is_(True))
        .order_by(RuleSetRecord.id.asc())
        .limit(1)
    )
    lock_ids = [rule_set_id]
    if previous_default_id is not None:
        lock_ids.append(previous_default_id)
    locked = _lock_rule_set_aggregates(db, lock_ids)
    target = locked[rule_set_id]
    _ensure_parent_version(
        target.record,
        expected_rule_set_lock_version=expected_rule_set_lock_version,
    )
    _require_publishable_default(target)

    if previous_default_id == rule_set_id:
        if (
            previous_default_expected_lock_version is not None
            and previous_default_expected_lock_version != target.record.lock_version
        ):
            _ensure_parent_version(
                target.record,
                expected_rule_set_lock_version=previous_default_expected_lock_version,
            )
        _flush_with_conflict(
            db,
            rule_set_id,
            expected_rule_set_lock_version=expected_rule_set_lock_version,
        )
        return RuleSetDefaultChange(previous_default=None, current_default=target)

    previous = locked.get(previous_default_id) if previous_default_id is not None else None
    if previous is not None:
        _ensure_parent_version(
            previous.record,
            expected_rule_set_lock_version=(
                previous_default_expected_lock_version
                if previous_default_expected_lock_version is not None
                else None
            ),
        )
    elif previous_default_expected_lock_version is not None:
        raise RuleSetVersionConflict(
            rule_set_id,
            expected_rule_set_lock_version=previous_default_expected_lock_version,
            current_rule_set_lock_version=None,
        )

    now = datetime.now(UTC)
    if previous is not None:
        previous.record.is_default = False
        previous.record.updated_by_user_id = actor_user_id
        previous.record.updated_at = now
        _flush_with_conflict(
            db,
            previous.record.id,
            expected_rule_set_lock_version=previous_default_expected_lock_version,
        )
    _mark_default(target.record, actor_user_id=actor_user_id, now=now)
    _flush_with_conflict(
        db,
        rule_set_id,
        expected_rule_set_lock_version=expected_rule_set_lock_version,
    )
    return RuleSetDefaultChange(
        previous_default=(
            _required_aggregate(db, previous.record.id) if previous is not None else None
        ),
        current_default=_required_aggregate(db, rule_set_id),
    )


def duplicate_rule_set(
    db: Session,
    source_rule_set_id: str,
    *,
    new_rule_set_id: str,
    new_name: str,
    expected_source_lock_version: int,
    actor_user_id: int,
) -> RuleSetAggregate:
    _flush_with_conflict(
        db,
        source_rule_set_id,
        expected_rule_set_lock_version=expected_source_lock_version,
    )
    source = _required_aggregate(db, source_rule_set_id, for_update=True)
    _ensure_parent_version(
        source.record,
        expected_rule_set_lock_version=expected_source_lock_version,
    )
    existing = get_rule_set_record(db, new_rule_set_id)
    if existing is not None:
        raise RuleSetTransitionConflict(
            new_rule_set_id,
            current_status=existing.status,
            target_status="draft",
        )

    source_revision = source.draft or source.published
    if source_revision is None:
        raise RuleSetRevisionNotFound(source_rule_set_id)
    source_config = _normalized_revision_config(source_revision)
    duplicated_config = _normalize_management_config(
        replace(
            source_config,
            name=new_name,
            role_counts=dict(source_config.role_counts),
        )
    )
    return create_rule_set(
        db,
        rule_set_id=new_rule_set_id,
        config=duplicated_config,
        display_order=source.record.display_order,
        actor_user_id=actor_user_id,
    )


def publish_rule_set(
    db: Session,
    rule_set_id: str,
    *,
    expected_rule_set_lock_version: int,
    expected_revision_lock_version: int,
    reason: str,
    actor_user_id: int,
) -> RuleSetAggregate:
    _flush_with_conflict(
        db,
        rule_set_id,
        expected_rule_set_lock_version=expected_rule_set_lock_version,
        expected_revision_lock_version=expected_revision_lock_version,
    )
    aggregate = _required_aggregate(db, rule_set_id, for_update=True)
    record = aggregate.record
    draft = aggregate.draft
    if record.lock_version != expected_rule_set_lock_version:
        raise RuleSetVersionConflict(
            rule_set_id,
            expected_rule_set_lock_version=expected_rule_set_lock_version,
            current_rule_set_lock_version=record.lock_version,
            expected_revision_lock_version=expected_revision_lock_version,
            current_revision_lock_version=(draft.lock_version if draft is not None else None),
        )
    if draft is None:
        raise RuleSetRevisionNotFound(
            rule_set_id,
            revision_id=record.draft_revision_id,
        )
    if draft.lock_version != expected_revision_lock_version:
        raise RuleSetVersionConflict(
            rule_set_id,
            revision_id=draft.id,
            expected_rule_set_lock_version=expected_rule_set_lock_version,
            current_rule_set_lock_version=record.lock_version,
            expected_revision_lock_version=expected_revision_lock_version,
            current_revision_lock_version=draft.lock_version,
        )

    config = _normalized_revision_config(draft)
    validation = validate_rule_set_config(config)
    if not validation.valid:
        raise RuleSetValidationFailed(
            rule_set_id,
            revision_id=draft.id,
            issues=validation.errors,
        )
    compiled = compile_rule_set_revision(draft)
    contract = build_admin_rule_contract(compiled.rule_set)
    if contract.issues:
        raise RuleSetValidationFailed(
            rule_set_id,
            revision_id=draft.id,
            issues=contract.issues,
        )
    round_tripped = resolve_rule_set_snapshot(compiled.snapshot)
    if round_tripped.snapshot != compiled.snapshot:
        raise ValueError("compiled rule set round-trip failed")

    if aggregate.published is not None:
        aggregate.published.state = "superseded"
        _flush_with_conflict(
            db,
            rule_set_id,
            revision_id=aggregate.published.id,
            expected_rule_set_lock_version=expected_rule_set_lock_version,
            expected_revision_lock_version=expected_revision_lock_version,
        )

    now = datetime.now(UTC)
    _write_draft_config(draft, config)
    draft.state = "published"
    draft.schema_version = RULE_SCHEMA_VERSION
    draft.content_hash = compiled.content_hash
    draft.published_by_user_id = actor_user_id
    draft.publish_reason = reason
    draft.published_at = now
    draft.updated_by_user_id = actor_user_id
    draft.updated_at = now

    record.status = "published"
    record.current_published_revision_id = draft.id
    record.draft_revision_id = None
    record.updated_by_user_id = actor_user_id
    record.archived_by_user_id = None
    record.updated_at = now
    record.archived_at = None
    _flush_with_conflict(
        db,
        rule_set_id,
        revision_id=draft.id,
        expected_rule_set_lock_version=expected_rule_set_lock_version,
        expected_revision_lock_version=expected_revision_lock_version,
    )
    return _required_aggregate(db, rule_set_id)


def resolve_published_rule_set(
    db: Session,
    rule_set_id: str,
    *,
    expected_revision_id: str | None = None,
    for_update: bool = False,
) -> CompiledRuleSet:
    _flush_with_conflict(db, rule_set_id)
    aggregate = _required_aggregate(db, rule_set_id, for_update=for_update)
    revision = aggregate.published
    if revision is None or aggregate.record.status != "published":
        raise RuleSetUnavailable(
            rule_set_id,
            current_status=aggregate.record.status,
            current_revision_id=(revision.id if revision is not None else None),
        )
    if expected_revision_id is not None and revision.id != expected_revision_id:
        raise RuleRevisionChanged(
            rule_set_id,
            expected_revision_id=expected_revision_id,
            current_revision_id=revision.id,
        )
    return _compile_public_aggregate(aggregate)


def _required_aggregate(
    db: Session,
    rule_set_id: str,
    *,
    for_update: bool = False,
) -> RuleSetAggregate:
    aggregate = get_rule_set_aggregate(db, rule_set_id, for_update=for_update)
    if aggregate is None:
        raise RuleSetNotFound(rule_set_id)
    return aggregate


def _lock_rule_set_aggregates(
    db: Session,
    rule_set_ids: list[str],
) -> dict[str, RuleSetAggregate]:
    locked: dict[str, RuleSetAggregate] = {}
    for locked_id in sorted(set(rule_set_ids)):
        locked[locked_id] = _required_aggregate(db, locked_id, for_update=True)
    return locked


def _ensure_parent_version(
    record: RuleSetRecord,
    *,
    expected_rule_set_lock_version: int | None,
) -> None:
    if record.lock_version != expected_rule_set_lock_version:
        raise RuleSetVersionConflict(
            record.id,
            expected_rule_set_lock_version=expected_rule_set_lock_version,
            current_rule_set_lock_version=record.lock_version,
        )


def _normalized_revision_config(revision: RuleSetRevisionRecord) -> RuleSetConfig:
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
    return config


def _flush_with_conflict(
    db: Session,
    rule_set_id: str,
    *,
    revision_id: str | None = None,
    expected_rule_set_lock_version: int | None = None,
    expected_revision_lock_version: int | None = None,
) -> None:
    conflict: RuleSetVersionConflict | None = None
    try:
        db.flush()
    except (IntegrityError, StaleDataError):
        conflict = RuleSetVersionConflict(
            rule_set_id,
            revision_id=revision_id,
            expected_rule_set_lock_version=expected_rule_set_lock_version,
            current_rule_set_lock_version=None,
            expected_revision_lock_version=expected_revision_lock_version,
            current_revision_lock_version=None,
        )
    if conflict is not None:
        raise conflict


def _validate_display_order(rule_set_id: str, display_order: int) -> None:
    if isinstance(display_order, bool) or not isinstance(display_order, int) or display_order < 0:
        raise RuleSetValidationFailed(
            rule_set_id,
            revision_id=None,
            issues=(
                RuleValidationIssue(
                    code="display_order_nonnegative",
                    path="display_order",
                    message="Display order must be a non-negative integer.",
                ),
            ),
        )


def _require_publishable_default(aggregate: RuleSetAggregate) -> None:
    revision = aggregate.published
    if (
        aggregate.record.status != "published"
        or aggregate.record.archived_at is not None
        or revision is None
    ):
        raise RuleSetUnavailable(
            aggregate.record.id,
            current_status=aggregate.record.status,
            current_revision_id=(revision.id if revision is not None else None),
        )
    _compile_public_aggregate(aggregate)


def _compile_public_aggregate(aggregate: RuleSetAggregate) -> CompiledRuleSet:
    catalog_snapshot = public_rule_set_catalog_snapshot(aggregate)
    runtime_snapshot = {
        key: value for key, value in catalog_snapshot.items() if key not in _PUBLIC_METADATA_FIELDS
    }
    return resolve_rule_set_snapshot(runtime_snapshot)


def _mark_archived(
    record: RuleSetRecord,
    *,
    actor_user_id: int,
    now: datetime,
) -> None:
    record.status = "archived"
    record.is_default = False
    record.updated_by_user_id = actor_user_id
    record.archived_by_user_id = actor_user_id
    record.updated_at = now
    record.archived_at = now


def _mark_default(
    record: RuleSetRecord,
    *,
    actor_user_id: int,
    now: datetime,
) -> None:
    record.is_default = True
    record.updated_by_user_id = actor_user_id
    record.updated_at = now


def _normalize_management_config(config: RuleSetConfig) -> RuleSetConfig:
    if not isinstance(config, RuleSetConfig):
        raise ValueError("config must be a RuleSetConfig")
    return normalize_rule_set_config(_detached_config(config))


def _detached_config(config: RuleSetConfig) -> dict[str, object]:
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


def _new_draft_revision(
    *,
    revision_id: str,
    rule_set_id: str,
    revision_no: int,
    config: RuleSetConfig,
    actor_user_id: int,
    now: datetime,
) -> RuleSetRevisionRecord:
    return RuleSetRevisionRecord(
        id=revision_id,
        rule_set_id=rule_set_id,
        revision_no=revision_no,
        state="draft",
        schema_version=RULE_SCHEMA_VERSION,
        content_hash=None,
        lock_version=1,
        name=config.name,
        description=config.description,
        player_count=config.player_count,
        role_summary=_role_summary(config),
        complexity=config.complexity,
        estimated_duration=config.estimated_duration,
        config=_detached_config(config),
        created_by_user_id=actor_user_id,
        updated_by_user_id=actor_user_id,
        published_by_user_id=None,
        publish_reason=None,
        created_at=now,
        updated_at=now,
        published_at=None,
    )


def _write_draft_config(revision: RuleSetRevisionRecord, config: RuleSetConfig) -> None:
    revision.name = config.name
    revision.description = config.description
    revision.player_count = config.player_count
    revision.role_summary = _role_summary(config)
    revision.complexity = config.complexity
    revision.estimated_duration = config.estimated_duration
    revision.config = _detached_config(config)


def _role_summary(config: RuleSetConfig) -> str:
    return " / ".join(
        f"{config.role_counts[role_id]} {_ROLE_LABELS[role_id]}"
        for role_id in _ROLE_ORDER
        if config.role_counts[role_id]
    )


__all__ = [
    "RuleSetDefaultChange",
    "RuleSetDraftValidation",
    "archive_rule_set",
    "create_rule_set",
    "duplicate_rule_set",
    "publish_rule_set",
    "resolve_published_rule_set",
    "restore_rule_set",
    "set_default_rule_set",
    "update_rule_set_draft",
    "validate_rule_set_draft",
]
