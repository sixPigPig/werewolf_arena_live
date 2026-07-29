from __future__ import annotations

from collections.abc import Iterator
from dataclasses import replace
import json

import pytest
from sqlalchemy import create_engine, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.db.base import Base
from app.models.rule_set import RuleSetRecord, RuleSetRevisionRecord
from app.rule_sets import service as service_module
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
from app.rule_sets.service import (
    RuleSetDefaultChange,
    archive_rule_set,
    create_rule_set,
    duplicate_rule_set,
    publish_rule_set,
    resolve_published_rule_set,
    restore_rule_set,
    set_default_rule_set,
    update_rule_set_draft,
    validate_rule_set_draft,
)
from app.rule_sets.snapshots import canonical_rule_set_config, rule_set_content_hash
from app.rule_sets.types import RuleSetConfig, RuleValidationIssue
from app.rule_sets.validation import normalize_rule_set_config


@pytest.fixture
def db() -> Iterator[Session]:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def _config(*, name: str = "自定义 8 人局", description: str = "自定义规则。") -> RuleSetConfig:
    return normalize_rule_set_config(
        {
            "name": name,
            "description": description,
            "complexity": "标准",
            "estimated_duration": "中",
            "rule_tags": ["标准", "顺序发言"],
            "role_counts": {
                "werewolf": 2,
                "villager": 4,
                "seer": 1,
                "guard": 1,
                "witch": 0,
                "hunter": 0,
                "idiot": 0,
            },
            "win_condition": "wolves_gte_others",
            "sheriff_enabled": False,
            "sheriff_vote_weight": 1.0,
            "speech_policy": "sequential",
            "werewolf_self_explosion_enabled": False,
            "first_night_last_words_enabled": False,
            "sheriff_badge_bomb_policy": "none",
        }
    )


def _published(db: Session, rule_set_id: str, *, display_order: int = 1):
    created = create_rule_set(
        db,
        rule_set_id=rule_set_id,
        config=_config(name=f"{rule_set_id} 规则"),
        display_order=display_order,
        actor_user_id=101,
    )
    assert created.draft is not None
    return publish_rule_set(
        db,
        rule_set_id,
        expected_rule_set_lock_version=created.record.lock_version,
        expected_revision_lock_version=created.draft.lock_version,
        reason="Publish test rule",
        actor_user_id=101,
    )


def _seed_default(db: Session, aggregate):
    aggregate.record.is_default = True
    db.flush()
    return aggregate


def test_create_publish_fork_and_republish_workflow(db: Session) -> None:
    initial = _config()
    created = create_rule_set(
        db,
        rule_set_id="custom_8",
        config=initial,
        display_order=7,
        actor_user_id=101,
    )

    assert created.record.status == "draft"
    assert created.record.lock_version == 1
    assert created.record.current_published_revision_id is None
    assert created.draft is not None
    assert created.draft.revision_no == 1
    assert created.draft.state == "draft"
    assert created.draft.config == canonical_rule_set_config(initial)

    first_revision_id = created.draft.id
    published = publish_rule_set(
        db,
        "custom_8",
        expected_rule_set_lock_version=1,
        expected_revision_lock_version=1,
        reason="Initial publication",
        actor_user_id=101,
    )

    assert published.record.status == "published"
    assert published.record.draft_revision_id is None
    assert published.record.current_published_revision_id == first_revision_id
    assert published.published is not None
    assert published.published.state == "published"
    assert published.published.schema_version == 1
    assert published.published.content_hash == rule_set_content_hash(initial)
    assert published.published.config == canonical_rule_set_config(initial)
    assert published.published.publish_reason == "Initial publication"
    assert published.published.published_by_user_id == 101
    assert published.published.published_at is not None
    assert resolve_published_rule_set(db, "custom_8").revision_id == first_revision_id

    revised_config = _config(name="自定义 8 人局 v2")
    forked = update_rule_set_draft(
        db,
        "custom_8",
        config=revised_config,
        display_order=8,
        expected_rule_set_lock_version=published.record.lock_version,
        expected_revision_lock_version=None,
        actor_user_id=202,
    )

    assert forked.record.status == "published"
    assert forked.record.current_published_revision_id == first_revision_id
    assert forked.draft is not None
    assert forked.draft.revision_no == 2
    assert forked.draft.state == "draft"
    assert forked.draft.id != first_revision_id

    second_revision_id = forked.draft.id
    republished = publish_rule_set(
        db,
        "custom_8",
        expected_rule_set_lock_version=forked.record.lock_version,
        expected_revision_lock_version=forked.draft.lock_version,
        reason="Publish revised rules",
        actor_user_id=202,
    )

    assert republished.record.current_published_revision_id == second_revision_id
    assert republished.published is not None
    assert republished.published.revision_no == 2
    assert republished.published.content_hash == rule_set_content_hash(revised_config)
    history = {revision.id: revision for revision in republished.revisions}
    assert history[first_revision_id].state == "superseded"
    assert history[second_revision_id].state == "published"


def test_create_stores_a_detached_normalized_management_config(db: Session) -> None:
    config = _config()
    created = create_rule_set(
        db,
        rule_set_id="detached_8",
        config=config,
        display_order=1,
        actor_user_id=101,
    )
    assert created.draft is not None

    config.role_counts["villager"] = 99

    assert created.draft.config["role_counts"]["villager"] == 4  # type: ignore[index]
    assert isinstance(created.draft.config["rule_tags"], list)


@pytest.mark.parametrize("display_order", [-1, True])
def test_create_rejects_invalid_display_order_without_database_leak(
    db: Session,
    display_order: object,
) -> None:
    with pytest.raises(RuleSetValidationFailed) as caught:
        create_rule_set(
            db,
            rule_set_id="invalid_order_8",
            config=_config(),
            display_order=display_order,  # type: ignore[arg-type]
            actor_user_id=101,
        )

    assert caught.value.revision_id is None
    assert caught.value.issues == (
        RuleValidationIssue(
            code="display_order_nonnegative",
            path="display_order",
            message="Display order must be a non-negative integer.",
        ),
    )
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None
    assert db.get(RuleSetRecord, "invalid_order_8") is None


def test_create_integrity_race_maps_to_chain_free_bounded_conflict(
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret = "SECRET SQL PARAMS DRIVER CONFIG DESCRIPTION"
    original_flush = db.flush

    def inject_create_race(*args, **kwargs):
        if any(
            isinstance(candidate, RuleSetRecord) and candidate.id == "create_race_8"
            for candidate in db.new
        ):
            raise IntegrityError(
                f"INSERT INTO rule_sets VALUES ({secret})",
                {"description": secret},
                RuntimeError(secret),
            )
        return original_flush(*args, **kwargs)

    monkeypatch.setattr(db, "flush", inject_create_race)
    with pytest.raises(RuleSetVersionConflict) as caught:
        create_rule_set(
            db,
            rule_set_id="create_race_8",
            config=_config(description=secret),
            display_order=1,
            actor_user_id=101,
        )

    error = caught.value
    encoded = json.dumps({"message": str(error), "attributes": vars(error)})
    assert secret not in encoded
    assert "INSERT INTO" not in encoded
    assert error.__cause__ is None
    assert error.__context__ is None
    db.rollback()


def test_invalid_draft_validation_returns_errors_and_publish_rejects(db: Session) -> None:
    secret = "SECRET-DESCRIPTION-MUST-NOT-ENTER-ERRORS"
    invalid = replace(
        _config(description=secret),
        role_counts={
            "werewolf": 1,
            "villager": 1,
            "seer": 0,
            "guard": 0,
            "witch": 0,
            "hunter": 0,
            "idiot": 0,
        },
    )
    created = create_rule_set(
        db,
        rule_set_id="invalid_2",
        config=invalid,
        display_order=1,
        actor_user_id=101,
    )
    assert created.draft is not None

    result = validate_rule_set_draft(
        db,
        "invalid_2",
        expected_revision_lock_version=created.draft.lock_version,
    )

    assert result.aggregate.record.id == "invalid_2"
    assert result.validation.valid is False
    assert result.compiled is None
    assert {issue.code for issue in result.validation.errors} >= {
        "player_count_out_of_range",
        "wolves_must_be_fewer_than_good_players",
    }

    with pytest.raises(RuleSetValidationFailed) as caught:
        publish_rule_set(
            db,
            "invalid_2",
            expected_rule_set_lock_version=created.record.lock_version,
            expected_revision_lock_version=created.draft.lock_version,
            reason="Attempt invalid publication",
            actor_user_id=101,
        )

    assert caught.value.rule_set_id == "invalid_2"
    assert caught.value.revision_id == created.draft.id
    assert caught.value.issues == result.validation.errors
    assert secret not in str(caught.value)
    assert created.record.status == "draft"
    assert created.draft.state == "draft"


def test_parent_and_draft_optimistic_versions_are_required(db: Session) -> None:
    created = create_rule_set(
        db,
        rule_set_id="versioned_8",
        config=_config(),
        display_order=1,
        actor_user_id=101,
    )
    assert created.draft is not None

    with pytest.raises(RuleSetVersionConflict) as parent_conflict:
        update_rule_set_draft(
            db,
            "versioned_8",
            config=_config(name="Stale parent"),
            display_order=2,
            expected_rule_set_lock_version=99,
            expected_revision_lock_version=created.draft.lock_version,
            actor_user_id=202,
        )
    assert parent_conflict.value.expected_rule_set_lock_version == 99
    assert parent_conflict.value.current_rule_set_lock_version == created.record.lock_version

    with pytest.raises(RuleSetVersionConflict) as revision_conflict:
        validate_rule_set_draft(
            db,
            "versioned_8",
            expected_revision_lock_version=99,
        )
    assert revision_conflict.value.expected_revision_lock_version == 99
    assert revision_conflict.value.current_revision_lock_version == created.draft.lock_version

    with pytest.raises(RuleSetVersionConflict):
        publish_rule_set(
            db,
            "versioned_8",
            expected_rule_set_lock_version=created.record.lock_version,
            expected_revision_lock_version=99,
            reason="Stale revision",
            actor_user_id=101,
        )

    published = publish_rule_set(
        db,
        "versioned_8",
        expected_rule_set_lock_version=created.record.lock_version,
        expected_revision_lock_version=created.draft.lock_version,
        reason="Current versions",
        actor_user_id=101,
    )
    with pytest.raises(RuleSetRevisionNotFound):
        validate_rule_set_draft(
            db,
            "versioned_8",
            expected_revision_lock_version=published.published.lock_version,  # type: ignore[union-attr]
        )


def test_archive_and_restore_preserve_revisions_for_published_and_draft_rules(
    db: Session,
) -> None:
    published = _published(db, "lifecycle_8")
    assert published.published is not None
    revision_id = published.published.id
    revision_count = len(published.revisions)

    archived = archive_rule_set(
        db,
        "lifecycle_8",
        expected_rule_set_lock_version=published.record.lock_version,
        replacement_default_rule_set_id=None,
        replacement_expected_lock_version=None,
        reason="Retire this rule",
        actor_user_id=202,
    )

    assert archived.record.status == "archived"
    assert archived.record.archived_at is not None
    assert archived.record.archived_by_user_id == 202
    assert archived.record.current_published_revision_id == revision_id
    assert len(archived.revisions) == revision_count
    with pytest.raises(RuleSetUnavailable):
        resolve_published_rule_set(db, "lifecycle_8")

    restored = restore_rule_set(
        db,
        "lifecycle_8",
        expected_rule_set_lock_version=archived.record.lock_version,
        reason="Restore published rule",
        actor_user_id=303,
    )
    assert restored.record.status == "published"
    assert restored.record.archived_at is None
    assert restored.record.current_published_revision_id == revision_id
    assert len(restored.revisions) == revision_count

    draft = create_rule_set(
        db,
        rule_set_id="draft_lifecycle_8",
        config=_config(),
        display_order=2,
        actor_user_id=101,
    )
    draft_revision_id = draft.draft.id  # type: ignore[union-attr]
    archived_draft = archive_rule_set(
        db,
        "draft_lifecycle_8",
        expected_rule_set_lock_version=draft.record.lock_version,
        replacement_default_rule_set_id=None,
        replacement_expected_lock_version=None,
        reason="Pause draft",
        actor_user_id=202,
    )
    restored_draft = restore_rule_set(
        db,
        "draft_lifecycle_8",
        expected_rule_set_lock_version=archived_draft.record.lock_version,
        reason="Resume draft",
        actor_user_id=303,
    )
    assert restored_draft.record.status == "draft"
    assert restored_draft.draft is not None
    assert restored_draft.draft.id == draft_revision_id
    assert len(restored_draft.revisions) == 1


def test_publishing_an_archived_rule_draft_restores_and_supersedes(db: Session) -> None:
    published = _published(db, "archived_edit_8")
    first_revision_id = published.published.id  # type: ignore[union-attr]
    archived = archive_rule_set(
        db,
        "archived_edit_8",
        expected_rule_set_lock_version=published.record.lock_version,
        replacement_default_rule_set_id=None,
        replacement_expected_lock_version=None,
        reason="Archive before revision",
        actor_user_id=202,
    )
    forked = update_rule_set_draft(
        db,
        "archived_edit_8",
        config=_config(name="Archived edit v2"),
        display_order=1,
        expected_rule_set_lock_version=archived.record.lock_version,
        expected_revision_lock_version=None,
        actor_user_id=202,
    )

    assert forked.record.status == "archived"
    assert forked.draft is not None and forked.draft.revision_no == 2
    restored_by_publish = publish_rule_set(
        db,
        "archived_edit_8",
        expected_rule_set_lock_version=forked.record.lock_version,
        expected_revision_lock_version=forked.draft.lock_version,
        reason="Restore through publication",
        actor_user_id=202,
    )
    history = {revision.id: revision for revision in restored_by_publish.revisions}
    assert restored_by_publish.record.status == "published"
    assert restored_by_publish.record.archived_at is None
    assert history[first_revision_id].state == "superseded"
    assert restored_by_publish.published is not None
    assert restored_by_publish.published.revision_no == 2


def test_duplicate_uses_preferred_draft_and_copies_no_lifecycle_state(db: Session) -> None:
    published = _published(db, "source_8", display_order=9)
    draft_config = _config(name="Source working copy", description="Unpublished source changes")
    source = update_rule_set_draft(
        db,
        "source_8",
        config=draft_config,
        display_order=9,
        expected_rule_set_lock_version=published.record.lock_version,
        expected_revision_lock_version=None,
        actor_user_id=202,
    )
    source_version = source.record.lock_version

    duplicate = duplicate_rule_set(
        db,
        "source_8",
        new_rule_set_id="source_copy_8",
        new_name="  Source Copy  ",
        expected_source_lock_version=source_version,
        actor_user_id=303,
    )

    assert duplicate.record.id == "source_copy_8"
    assert duplicate.record.status == "draft"
    assert duplicate.record.is_default is False
    assert duplicate.record.current_published_revision_id is None
    assert duplicate.record.archived_at is None
    assert duplicate.record.display_order == 9
    assert duplicate.record.created_by_user_id == 303
    assert duplicate.draft is not None
    assert duplicate.draft.revision_no == 1
    assert duplicate.draft.name == "Source Copy"
    assert duplicate.draft.description == "Unpublished source changes"
    assert duplicate.draft.content_hash is None
    assert duplicate.draft.published_at is None
    assert source.record.lock_version == source_version

    with pytest.raises(RuleSetTransitionConflict):
        duplicate_rule_set(
            db,
            "source_8",
            new_rule_set_id="source_copy_8",
            new_name="Duplicate ID",
            expected_source_lock_version=source_version,
            actor_user_id=303,
        )


def test_invalid_lifecycle_transitions_are_bounded_conflicts(db: Session) -> None:
    published = _published(db, "transition_8")
    with pytest.raises(RuleSetTransitionConflict) as restore_conflict:
        restore_rule_set(
            db,
            "transition_8",
            expected_rule_set_lock_version=published.record.lock_version,
            reason="Already active",
            actor_user_id=101,
        )
    assert restore_conflict.value.current_status == "published"
    assert restore_conflict.value.target_status == "published"

    archived = archive_rule_set(
        db,
        "transition_8",
        expected_rule_set_lock_version=published.record.lock_version,
        replacement_default_rule_set_id=None,
        replacement_expected_lock_version=None,
        reason="Archive once",
        actor_user_id=101,
    )
    with pytest.raises(RuleSetTransitionConflict):
        archive_rule_set(
            db,
            "transition_8",
            expected_rule_set_lock_version=archived.record.lock_version,
            replacement_default_rule_set_id=None,
            replacement_expected_lock_version=None,
            reason="Archive twice",
            actor_user_id=101,
        )


def test_default_archive_requires_and_atomically_switches_to_valid_replacement(
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    current = _seed_default(db, _published(db, "z_default_8", display_order=1))
    replacement = _published(db, "a_replacement_8", display_order=2)
    current_version = current.record.lock_version
    replacement_version = replacement.record.lock_version

    with pytest.raises(DefaultRuleRequired):
        archive_rule_set(
            db,
            "z_default_8",
            expected_rule_set_lock_version=current_version,
            replacement_default_rule_set_id=None,
            replacement_expected_lock_version=None,
            reason="Cannot remove the only default",
            actor_user_id=202,
        )
    assert current.record.is_default is True
    assert current.record.status == "published"

    with pytest.raises(RuleSetVersionConflict) as stale_replacement:
        archive_rule_set(
            db,
            "z_default_8",
            expected_rule_set_lock_version=current_version,
            replacement_default_rule_set_id="a_replacement_8",
            replacement_expected_lock_version=99,
            reason="Switch default while archiving",
            actor_user_id=202,
        )
    assert stale_replacement.value.current_rule_set_lock_version == replacement_version
    assert current.record.is_default is True
    assert replacement.record.is_default is False

    locked_ids: list[str] = []
    original_get = service_module.get_rule_set_aggregate

    def tracked_get(
        session: Session,
        rule_set_id: str,
        *,
        revision_limit: int = 50,
        for_update: bool = False,
    ):
        if for_update:
            locked_ids.append(rule_set_id)
        return original_get(
            session,
            rule_set_id,
            revision_limit=revision_limit,
            for_update=for_update,
        )

    monkeypatch.setattr(service_module, "get_rule_set_aggregate", tracked_get)
    archived = archive_rule_set(
        db,
        "z_default_8",
        expected_rule_set_lock_version=current_version,
        replacement_default_rule_set_id="a_replacement_8",
        replacement_expected_lock_version=replacement_version,
        reason="Switch default while archiving",
        actor_user_id=202,
    )

    assert locked_ids[:2] == ["a_replacement_8", "z_default_8"]
    assert archived.record.status == "archived"
    assert archived.record.is_default is False
    assert archived.record.lock_version == current_version + 1
    assert replacement.record.status == "published"
    assert replacement.record.is_default is True
    assert replacement.record.lock_version == replacement_version + 1
    defaults = tuple(db.scalars(select(RuleSetRecord).where(RuleSetRecord.is_default.is_(True))))
    assert [record.id for record in defaults] == ["a_replacement_8"]


def test_default_handoff_second_flush_failure_maps_and_caller_rollback_is_atomic(
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    current = _seed_default(db, _published(db, "z_atomic_default_8", display_order=1))
    replacement = _published(db, "a_atomic_target_8", display_order=2)
    db.commit()
    current_record = db.get(RuleSetRecord, current.record.id)
    replacement_record = db.get(RuleSetRecord, replacement.record.id)
    assert current_record is not None and replacement_record is not None
    current_id = current_record.id
    replacement_id = replacement_record.id
    current_version = current_record.lock_version
    replacement_version = replacement_record.lock_version
    secret = "SECRET DEFAULT UNIQUE SQL DRIVER"
    original_flush = db.flush

    def fail_replacement_flush(*args, **kwargs):
        if current_record.status == "archived" and replacement_record.is_default:
            raise IntegrityError(
                f"UPDATE rule_sets SET is_default = true ({secret})",
                {"secret": secret},
                RuntimeError(secret),
            )
        return original_flush(*args, **kwargs)

    monkeypatch.setattr(db, "flush", fail_replacement_flush)
    with pytest.raises(RuleSetVersionConflict) as caught:
        archive_rule_set(
            db,
            current_record.id,
            expected_rule_set_lock_version=current_version,
            replacement_default_rule_set_id=replacement_record.id,
            replacement_expected_lock_version=replacement_version,
            reason="Atomic replacement",
            actor_user_id=303,
        )

    error = caught.value
    assert secret not in json.dumps({"message": str(error), "attributes": vars(error)})
    assert error.__cause__ is None
    assert error.__context__ is None
    monkeypatch.setattr(db, "flush", original_flush)
    db.rollback()
    restored_current = db.get(RuleSetRecord, current_id)
    restored_target = db.get(RuleSetRecord, replacement_id)
    assert restored_current is not None and restored_current.status == "published"
    assert restored_current.is_default is True
    assert restored_target is not None and restored_target.status == "published"
    assert restored_target.is_default is False


def test_set_default_locks_in_stable_order_and_returns_both_aggregates(
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    previous = _seed_default(db, _published(db, "z_previous_8", display_order=1))
    target = _published(db, "a_target_8", display_order=2)
    previous_version = previous.record.lock_version
    target_version = target.record.lock_version
    locked_ids: list[str] = []
    original_get = service_module.get_rule_set_aggregate

    def tracked_get(
        session: Session,
        rule_set_id: str,
        *,
        revision_limit: int = 50,
        for_update: bool = False,
    ):
        if for_update:
            locked_ids.append(rule_set_id)
        return original_get(
            session,
            rule_set_id,
            revision_limit=revision_limit,
            for_update=for_update,
        )

    monkeypatch.setattr(service_module, "get_rule_set_aggregate", tracked_get)
    change = set_default_rule_set(
        db,
        "a_target_8",
        expected_rule_set_lock_version=target_version,
        previous_default_expected_lock_version=previous_version,
        reason="Promote target",
        actor_user_id=303,
    )

    assert isinstance(change, RuleSetDefaultChange)
    assert locked_ids[:2] == ["a_target_8", "z_previous_8"]
    assert change.previous_default is not None
    assert change.previous_default.record.id == "z_previous_8"
    assert change.previous_default.record.is_default is False
    assert change.current_default.record.id == "a_target_8"
    assert change.current_default.record.is_default is True
    assert previous.record.lock_version == previous_version + 1
    assert target.record.lock_version == target_version + 1

    draft_target = create_rule_set(
        db,
        rule_set_id="draft_default_8",
        config=_config(),
        display_order=3,
        actor_user_id=101,
    )
    with pytest.raises(RuleSetUnavailable):
        set_default_rule_set(
            db,
            "draft_default_8",
            expected_rule_set_lock_version=draft_target.record.lock_version,
            previous_default_expected_lock_version=target.record.lock_version,
            reason="Drafts cannot be default",
            actor_user_id=303,
        )
    assert target.record.is_default is True


def test_resolve_requires_exact_current_revision_and_hash_checked_projection(
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    published = _published(db, "resolved_8")
    assert published.published is not None
    revision_id = published.published.id
    locked: list[bool] = []
    original_get = service_module.get_rule_set_aggregate

    def tracked_get(
        session: Session,
        rule_set_id: str,
        *,
        revision_limit: int = 50,
        for_update: bool = False,
    ):
        locked.append(for_update)
        return original_get(
            session,
            rule_set_id,
            revision_limit=revision_limit,
            for_update=for_update,
        )

    monkeypatch.setattr(service_module, "get_rule_set_aggregate", tracked_get)
    resolved = resolve_published_rule_set(
        db,
        "resolved_8",
        expected_revision_id=revision_id,
        for_update=True,
    )
    assert locked[0] is True
    assert resolved.revision_id == revision_id
    assert resolved.revision_no == 1
    assert resolved.content_hash == published.published.content_hash
    assert resolved.snapshot["revision_id"] == revision_id
    assert "is_default" not in resolved.snapshot
    assert "display_order" not in resolved.snapshot
    assert "role_summary" not in resolved.snapshot

    with pytest.raises(RuleRevisionChanged) as changed:
        resolve_published_rule_set(
            db,
            "resolved_8",
            expected_revision_id="00000000-0000-0000-0000-000000000000",
        )
    assert changed.value.current_revision_id == revision_id
    assert changed.value.expected_revision_id == "00000000-0000-0000-0000-000000000000"

    with pytest.raises(RuleSetNotFound):
        resolve_published_rule_set(db, "missing_8")

    db.execute(
        update(RuleSetRevisionRecord)
        .where(RuleSetRevisionRecord.id == revision_id)
        .values(content_hash="0" * 64)
    )
    db.expire_all()
    with pytest.raises(RuleSetCatalogCorrupt) as corrupt:
        resolve_published_rule_set(db, "resolved_8")
    assert corrupt.value.reason == "content_hash_mismatch"
    assert "自定义规则" not in str(corrupt.value)
    assert corrupt.value.__cause__ is None
    assert corrupt.value.__context__ is None


def test_lifecycle_keeps_published_and_superseded_content_immutable(db: Session) -> None:
    first = _published(db, "immutable_8")
    assert first.published is not None
    first_revision_id = first.published.id
    forked = update_rule_set_draft(
        db,
        "immutable_8",
        config=_config(name="Immutable v2"),
        display_order=1,
        expected_rule_set_lock_version=first.record.lock_version,
        expected_revision_lock_version=None,
        actor_user_id=202,
    )
    assert forked.draft is not None
    second = publish_rule_set(
        db,
        "immutable_8",
        expected_rule_set_lock_version=forked.record.lock_version,
        expected_revision_lock_version=forked.draft.lock_version,
        reason="Freeze v2",
        actor_user_id=202,
    )
    assert second.published is not None
    second_revision_id = second.published.id
    db.commit()

    superseded = db.get(RuleSetRevisionRecord, first_revision_id)
    assert superseded is not None and superseded.state == "superseded"
    superseded.description = "rewrite superseded"
    with pytest.raises(ValueError, match="superseded rule revision is immutable"):
        db.flush()
    db.rollback()

    current = db.get(RuleSetRevisionRecord, second_revision_id)
    assert current is not None and current.state == "published"
    current.description = "rewrite published"
    with pytest.raises(ValueError, match="published rule revision content is immutable"):
        db.flush()


def test_real_stale_orm_write_maps_to_bounded_version_conflict(tmp_path) -> None:
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'rule-race.sqlite'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)

    with factory() as seed:
        created = create_rule_set(
            seed,
            rule_set_id="racing_8",
            config=_config(),
            display_order=1,
            actor_user_id=101,
        )
        seed.commit()
        assert created.draft is not None

    with factory() as stale, factory() as winner:
        stale_parent = stale.get(RuleSetRecord, "racing_8")
        assert stale_parent is not None and stale_parent.draft_revision_id is not None
        stale_revision = stale.get(RuleSetRevisionRecord, stale_parent.draft_revision_id)
        assert stale_revision is not None
        expected_parent_version = stale_parent.lock_version
        expected_revision_version = stale_revision.lock_version
        stale.commit()

        winning = update_rule_set_draft(
            winner,
            "racing_8",
            config=_config(name="Winning edit"),
            display_order=2,
            expected_rule_set_lock_version=expected_parent_version,
            expected_revision_lock_version=expected_revision_version,
            actor_user_id=202,
        )
        winner.commit()
        assert winning.record.lock_version == expected_parent_version + 1

        with pytest.raises(RuleSetVersionConflict) as caught:
            update_rule_set_draft(
                stale,
                "racing_8",
                config=_config(name="Stale edit"),
                display_order=3,
                expected_rule_set_lock_version=expected_parent_version,
                expected_revision_lock_version=expected_revision_version,
                actor_user_id=303,
            )
        assert caught.value.rule_set_id == "racing_8"
        assert caught.value.expected_rule_set_lock_version == expected_parent_version
        assert caught.value.__cause__ is None
        assert caught.value.__context__ is None


def test_restore_rejects_corrupt_archived_publication_without_exposing_it(
    db: Session,
) -> None:
    published = _published(db, "corrupt_restore_8")
    assert published.published is not None
    archived = archive_rule_set(
        db,
        "corrupt_restore_8",
        expected_rule_set_lock_version=published.record.lock_version,
        replacement_default_rule_set_id=None,
        replacement_expected_lock_version=None,
        reason="Archive before corruption check",
        actor_user_id=202,
    )
    archived_version = archived.record.lock_version
    db.execute(
        update(RuleSetRevisionRecord)
        .where(RuleSetRevisionRecord.id == archived.published.id)  # type: ignore[union-attr]
        .values(content_hash="0" * 64)
    )
    db.expire_all()

    with pytest.raises(RuleSetCatalogCorrupt) as caught:
        restore_rule_set(
            db,
            "corrupt_restore_8",
            expected_rule_set_lock_version=archived_version,
            reason="Do not restore corrupt publication",
            actor_user_id=303,
        )
    assert caught.value.reason == "content_hash_mismatch"
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None
    saved = db.get(RuleSetRecord, "corrupt_restore_8")
    assert saved is not None and saved.status == "archived"


def test_draft_config_corruption_maps_to_bounded_catalog_failure(db: Session) -> None:
    created = create_rule_set(
        db,
        rule_set_id="corrupt_draft_8",
        config=_config(),
        display_order=1,
        actor_user_id=101,
    )
    assert created.draft is not None
    secret = "SECRET-DESCRIPTION-MUST-NOT-LEAK"
    db.execute(
        update(RuleSetRevisionRecord)
        .where(RuleSetRevisionRecord.id == created.draft.id)
        .values(config={"description": secret})
    )
    db.expire_all()

    with pytest.raises(RuleSetCatalogCorrupt) as validation_error:
        validate_rule_set_draft(
            db,
            "corrupt_draft_8",
            expected_revision_lock_version=created.draft.lock_version,
        )
    assert validation_error.value.reason == "revision_config_invalid"
    assert secret not in str(validation_error.value)
    assert validation_error.value.__cause__ is None
    assert validation_error.value.__context__ is None

    with pytest.raises(RuleSetCatalogCorrupt) as publish_error:
        publish_rule_set(
            db,
            "corrupt_draft_8",
            expected_rule_set_lock_version=created.record.lock_version,
            expected_revision_lock_version=created.draft.lock_version,
            reason="Reject corrupt draft",
            actor_user_id=101,
        )
    assert publish_error.value.reason == "revision_config_invalid"
    assert publish_error.value.__cause__ is None
    assert publish_error.value.__context__ is None


def test_existing_id_and_stale_fork_precondition_use_domain_conflicts(db: Session) -> None:
    published = _published(db, "existing_8")
    with pytest.raises(RuleSetTransitionConflict):
        create_rule_set(
            db,
            rule_set_id="existing_8",
            config=_config(),
            display_order=1,
            actor_user_id=101,
        )

    with pytest.raises(RuleSetVersionConflict) as stale_fork:
        update_rule_set_draft(
            db,
            "existing_8",
            config=_config(name="Invalid fork precondition"),
            display_order=1,
            expected_rule_set_lock_version=published.record.lock_version,
            expected_revision_lock_version=1,
            actor_user_id=202,
        )
    assert stale_fork.value.expected_revision_lock_version == 1
    assert stale_fork.value.current_revision_lock_version is None


def test_domain_error_payloads_bound_identifiers_versions_and_issues() -> None:
    secret = "SECRET-CONFIG-SQL-DRIVER-DESCRIPTION"
    huge_id = "r" * 80 + secret
    huge_revision = "v" * 36 + secret
    huge_version = 10**100
    conflict = RuleSetVersionConflict(
        huge_id,
        revision_id=huge_revision,
        expected_rule_set_lock_version=huge_version,
        current_rule_set_lock_version=-huge_version,
        expected_revision_lock_version=huge_version,
        current_revision_lock_version=-huge_version,
    )
    assert len(conflict.rule_set_id) == 80
    assert len(conflict.revision_id or "") == 36
    for version in (
        conflict.expected_rule_set_lock_version,
        conflict.current_rule_set_lock_version,
        conflict.expected_revision_lock_version,
        conflict.current_revision_lock_version,
    ):
        assert version is None or 0 <= version <= 2_147_483_647

    issues = [
        RuleValidationIssue(
            code="c" * 80 + secret,
            path="p" * 120 + secret,
            message=secret,
        )
        for _ in range(75)
    ]
    validation = RuleSetValidationFailed(
        huge_id,
        revision_id=huge_revision,
        issues=issues,
    )
    assert len(validation.issues) == 50
    assert all(len(issue.code) <= 80 for issue in validation.issues)
    assert all(len(issue.path) <= 120 for issue in validation.issues)
    assert all(len(issue.message) <= 240 for issue in validation.issues)
    assert {issue.message for issue in validation.issues} == {"Rule configuration is invalid."}

    catalog = RuleSetCatalogCorrupt(
        huge_id,
        pointer=secret,
        revision_id=huge_revision,
        reason=secret,
    )
    assert catalog.pointer == "catalog_pointer"
    assert catalog.reason == "catalog_inconsistent"
    assert len(catalog.rule_set_id) == 80
    assert len(catalog.revision_id or "") == 36

    errors = (
        conflict,
        validation,
        catalog,
        RuleSetNotFound(huge_id),
        RuleSetRevisionNotFound(huge_id, revision_id=huge_revision),
        RuleSetTransitionConflict(
            huge_id,
            current_status="s" * 20 + secret,
            target_status="t" * 20 + secret,
        ),
        RuleSetUnavailable(
            huge_id,
            current_status="s" * 20 + secret,
            current_revision_id=huge_revision,
        ),
        RuleRevisionChanged(
            huge_id,
            expected_revision_id=huge_revision,
            current_revision_id=huge_revision,
        ),
        DefaultRuleRequired(huge_id, replacement_rule_set_id=huge_id),
    )
    encoded = json.dumps(
        [{"message": str(error), "attributes": vars(error)} for error in errors],
        default=str,
    )
    assert secret not in encoded


def test_all_service_operations_flush_and_never_commit(
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_flush = db.flush
    flushes = 0

    def tracked_flush(*args, **kwargs):
        nonlocal flushes
        flushes += 1
        return original_flush(*args, **kwargs)

    def forbidden_commit() -> None:
        raise AssertionError("lifecycle services must not commit")

    def forbidden_rollback() -> None:
        raise AssertionError("lifecycle services must not rollback")

    monkeypatch.setattr(db, "flush", tracked_flush)
    monkeypatch.setattr(db, "commit", forbidden_commit)
    monkeypatch.setattr(db, "rollback", forbidden_rollback)

    def call_and_require_flush(operation):
        before = flushes
        result = operation()
        assert flushes > before
        return result

    created = call_and_require_flush(
        lambda: create_rule_set(
            db,
            rule_set_id="flush_a_8",
            config=_config(),
            display_order=1,
            actor_user_id=101,
        )
    )
    assert created.draft is not None
    call_and_require_flush(
        lambda: validate_rule_set_draft(
            db,
            "flush_a_8",
            expected_revision_lock_version=created.draft.lock_version,
        )
    )
    published = call_and_require_flush(
        lambda: publish_rule_set(
            db,
            "flush_a_8",
            expected_rule_set_lock_version=created.record.lock_version,
            expected_revision_lock_version=created.draft.lock_version,
            reason="Publish flush test",
            actor_user_id=101,
        )
    )
    call_and_require_flush(lambda: resolve_published_rule_set(db, "flush_a_8"))
    forked = call_and_require_flush(
        lambda: update_rule_set_draft(
            db,
            "flush_a_8",
            config=_config(name="Flush A v2"),
            display_order=2,
            expected_rule_set_lock_version=published.record.lock_version,
            expected_revision_lock_version=None,
            actor_user_id=202,
        )
    )
    duplicated = call_and_require_flush(
        lambda: duplicate_rule_set(
            db,
            "flush_a_8",
            new_rule_set_id="flush_b_8",
            new_name="Flush B",
            expected_source_lock_version=forked.record.lock_version,
            actor_user_id=202,
        )
    )
    assert duplicated.draft is not None
    published_b = call_and_require_flush(
        lambda: publish_rule_set(
            db,
            "flush_b_8",
            expected_rule_set_lock_version=duplicated.record.lock_version,
            expected_revision_lock_version=duplicated.draft.lock_version,
            reason="Publish replacement",
            actor_user_id=202,
        )
    )
    default_a = call_and_require_flush(
        lambda: set_default_rule_set(
            db,
            "flush_a_8",
            expected_rule_set_lock_version=forked.record.lock_version,
            previous_default_expected_lock_version=None,
            reason="Establish default",
            actor_user_id=303,
        )
    )
    archived_a = call_and_require_flush(
        lambda: archive_rule_set(
            db,
            "flush_a_8",
            expected_rule_set_lock_version=default_a.current_default.record.lock_version,
            replacement_default_rule_set_id="flush_b_8",
            replacement_expected_lock_version=published_b.record.lock_version,
            reason="Archive with replacement",
            actor_user_id=303,
        )
    )
    call_and_require_flush(
        lambda: restore_rule_set(
            db,
            "flush_a_8",
            expected_rule_set_lock_version=archived_a.record.lock_version,
            reason="Restore flush test",
            actor_user_id=303,
        )
    )
