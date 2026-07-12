from __future__ import annotations

import json
from dataclasses import FrozenInstanceError
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from app.db.base import Base
from app.models import RuleSetRecord, RuleSetRevisionRecord
from app.rule_sets.repository import (
    RuleSetAggregate,
    RuleSetCatalogCorrupt,
    RuleSetPage,
    get_rule_set_aggregate,
    get_rule_set_record,
    get_rule_set_revision,
    list_published_rule_sets,
    list_rule_set_revisions,
    list_rule_sets,
    next_rule_set_revision_no,
)
from app.rule_sets.snapshots import (
    admin_rule_revision_snapshot,
    admin_rule_set_snapshot,
    audit_rule_set_snapshot,
    canonical_rule_set_config,
    public_rule_set_catalog_snapshot,
    rule_set_content_hash,
)
from app.rule_sets.validation import normalize_rule_set_config


CLASSIC_REVISION_ID = "00000000-0000-0000-0000-000000000102"
CLASSIC_OLD_REVISION_ID = "00000000-0000-0000-0000-000000000101"
STARTER_REVISION_ID = "00000000-0000-0000-0000-000000000201"
DRAFT_REVISION_ID = "00000000-0000-0000-0000-000000000301"
ARCHIVED_REVISION_ID = "00000000-0000-0000-0000-000000000401"


@pytest.fixture
def db() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        _seed_catalog(session)
        yield session


def _raw_config(
    *,
    name: str,
    description: str,
    role_counts: dict[str, int],
    complexity: str = "标准",
    estimated_duration: str = "中",
) -> dict[str, object]:
    return {
        "name": name,
        "description": description,
        "complexity": complexity,
        "estimated_duration": estimated_duration,
        "rule_tags": [complexity, "顺序发言"],
        "role_counts": role_counts,
        "win_condition": "wolves_gte_others",
        "sheriff_enabled": False,
        "sheriff_vote_weight": 1.0,
        "speech_policy": "sequential",
        "werewolf_self_explosion_enabled": False,
        "sheriff_badge_bomb_policy": "none",
    }


def _classic_config(*, name: str = "经典 8 人局") -> dict[str, object]:
    return _raw_config(
        name=name,
        description="包含狼人、预言家、守卫与村民的官方标准局。",
        role_counts={
            "werewolf": 2,
            "villager": 4,
            "seer": 1,
            "guard": 1,
            "witch": 0,
            "hunter": 0,
            "idiot": 0,
        },
    )


def _starter_config() -> dict[str, object]:
    return _raw_config(
        name="新手 6 人快局",
        description="更短的官方入门局,适合快速观察模型策略。",
        role_counts={
            "werewolf": 1,
            "villager": 3,
            "seer": 1,
            "guard": 1,
            "witch": 0,
            "hunter": 0,
            "idiot": 0,
        },
        complexity="入门",
        estimated_duration="短",
    )


def _social_config(*, name: str) -> dict[str, object]:
    return _raw_config(
        name=name,
        description="仅保留狼人夜晚行动的心理博弈局。",
        role_counts={
            "werewolf": 2,
            "villager": 6,
            "seer": 0,
            "guard": 0,
            "witch": 0,
            "hunter": 0,
            "idiot": 0,
        },
        complexity="心理",
    )


def _revision(
    *,
    revision_id: str,
    rule_set_id: str,
    revision_no: int,
    state: str,
    config: dict[str, object],
    updated_at: datetime,
) -> RuleSetRevisionRecord:
    normalized = normalize_rule_set_config(config)
    stored_config = canonical_rule_set_config(normalized)
    role_names = {
        "werewolf": "狼人",
        "seer": "预言家",
        "guard": "守卫",
        "witch": "女巫",
        "hunter": "猎人",
        "idiot": "白痴",
        "villager": "村民",
    }
    role_summary = " / ".join(
        f"{count} {role_names[role_id]}"
        for role_id, count in normalized.role_counts.items()
        if count
    )
    published = state != "draft"
    return RuleSetRevisionRecord(
        id=revision_id,
        rule_set_id=rule_set_id,
        revision_no=revision_no,
        state=state,
        schema_version=1,
        content_hash=rule_set_content_hash(normalized) if published else None,
        name=normalized.name,
        description=normalized.description,
        player_count=normalized.player_count,
        role_summary=role_summary,
        complexity=normalized.complexity,
        estimated_duration=normalized.estimated_duration,
        config=stored_config,
        created_at=updated_at,
        updated_at=updated_at,
        published_at=updated_at if published else None,
    )


def _seed_catalog(db: Session) -> None:
    day_1 = datetime(2026, 7, 1, tzinfo=UTC)
    day_2 = datetime(2026, 7, 2, tzinfo=UTC)
    day_3 = datetime(2026, 7, 3, tzinfo=UTC)
    day_4 = datetime(2026, 7, 4, tzinfo=UTC)
    records = (
        RuleSetRecord(
            id="classic_8",
            status="published",
            current_published_revision_id=CLASSIC_REVISION_ID,
            is_default=True,
            display_order=2,
            created_at=day_1,
            updated_at=day_1,
        ),
        RuleSetRecord(
            id="starter_6",
            status="published",
            current_published_revision_id=STARTER_REVISION_ID,
            is_default=False,
            display_order=1,
            created_at=day_2,
            updated_at=day_2,
        ),
        RuleSetRecord(
            id="draft_only",
            status="draft",
            draft_revision_id=DRAFT_REVISION_ID,
            is_default=False,
            display_order=3,
            created_at=day_3,
            updated_at=day_3,
        ),
        RuleSetRecord(
            id="archived_social",
            status="archived",
            current_published_revision_id=ARCHIVED_REVISION_ID,
            is_default=False,
            display_order=4,
            created_at=day_4,
            updated_at=day_4,
            archived_at=day_4,
        ),
    )
    revisions = (
        _revision(
            revision_id=CLASSIC_OLD_REVISION_ID,
            rule_set_id="classic_8",
            revision_no=1,
            state="superseded",
            config=_classic_config(name="经典 8 人局（旧版）"),
            updated_at=day_1,
        ),
        _revision(
            revision_id=CLASSIC_REVISION_ID,
            rule_set_id="classic_8",
            revision_no=2,
            state="published",
            config=_classic_config(),
            updated_at=day_1,
        ),
        _revision(
            revision_id=STARTER_REVISION_ID,
            rule_set_id="starter_6",
            revision_no=1,
            state="published",
            config=_starter_config(),
            updated_at=day_2,
        ),
        _revision(
            revision_id=DRAFT_REVISION_ID,
            rule_set_id="draft_only",
            revision_no=1,
            state="draft",
            config=_starter_config() | {"name": "Draft Only Rule"},
            updated_at=day_3,
        ),
        _revision(
            revision_id=ARCHIVED_REVISION_ID,
            rule_set_id="archived_social",
            revision_no=1,
            state="published",
            config=_social_config(name="Archived Social Rule"),
            updated_at=day_4,
        ),
    )
    db.add_all((*records, *revisions))
    db.commit()


def test_list_rule_sets_filters_sorts_and_pages_with_immutable_containers(
    db: Session,
) -> None:
    first = list_rule_sets(db, page=1, page_size=2)

    assert isinstance(first, RuleSetPage)
    assert [item.record.id for item in first.items] == ["starter_6", "classic_8"]
    assert (first.page, first.page_size, first.total, first.pages) == (1, 2, 4, 2)
    assert isinstance(first.items, tuple)
    assert all(isinstance(item.revisions, tuple) for item in first.items)
    with pytest.raises(FrozenInstanceError):
        first.page = 2  # type: ignore[misc]

    second = list_rule_sets(db, page=2, page_size=2)
    assert [item.record.id for item in second.items] == ["draft_only", "archived_social"]

    query_match = list_rule_sets(db, page=1, page_size=20, q="draft only")
    assert [item.record.id for item in query_match.items] == ["draft_only"]

    archived = list_rule_sets(db, page=1, page_size=20, status="archived")
    assert [item.record.id for item in archived.items] == ["archived_social"]

    six_player = list_rule_sets(db, page=1, page_size=20, player_count=6)
    assert [item.record.id for item in six_player.items] == ["starter_6", "draft_only"]

    newest = list_rule_sets(db, page=1, page_size=20, sort="-updated_at")
    assert [item.record.id for item in newest.items] == [
        "archived_social",
        "draft_only",
        "starter_6",
        "classic_8",
    ]

    by_name = list_rule_sets(db, page=1, page_size=20, sort="name")
    assert [item.record.id for item in by_name.items] == [
        "archived_social",
        "draft_only",
        "starter_6",
        "classic_8",
    ]


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"page": 0, "page_size": 20}, "page"),
        ({"page": 1, "page_size": 101}, "page_size"),
        ({"page": 1, "page_size": 20, "sort": "unknown"}, "sort"),
        ({"page": 1, "page_size": 20, "player_count": True}, "player_count"),
    ],
)
def test_list_rule_sets_rejects_unsafe_query_bounds(
    db: Session,
    kwargs: dict[str, object],
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        list_rule_sets(db, **kwargs)  # type: ignore[arg-type]


def test_single_record_revision_and_bounded_history_reads(db: Session) -> None:
    record = get_rule_set_record(db, "classic_8")
    aggregate = get_rule_set_aggregate(db, "classic_8")
    current = get_rule_set_revision(db, CLASSIC_REVISION_ID)

    assert record is not None and record.id == "classic_8"
    assert get_rule_set_record(db, "missing") is None
    assert aggregate is not None
    assert aggregate.record is record
    assert aggregate.draft is None
    assert aggregate.published is current
    assert [revision.revision_no for revision in aggregate.revisions] == [2, 1]
    assert get_rule_set_revision(db, "missing") is None
    assert list_rule_set_revisions(db, "classic_8", limit=1) == (current,)
    assert next_rule_set_revision_no(db, "classic_8") == 3
    assert next_rule_set_revision_no(db, "missing") == 1

    with pytest.raises(ValueError, match="limit"):
        list_rule_set_revisions(db, "classic_8", limit=51)


def test_aggregate_read_executes_one_parent_pointer_and_history_statement(
    db: Session,
) -> None:
    engine = db.get_bind()
    statements: list[str] = []

    def count_statement(
        _connection: object,
        _cursor: object,
        statement: str,
        _parameters: object,
        _context: object,
        _executemany: bool,
    ) -> None:
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", count_statement)
    try:
        aggregate = get_rule_set_aggregate(db, "classic_8")
    finally:
        event.remove(engine, "before_cursor_execute", count_statement)

    assert aggregate is not None
    assert len(statements) == 3


def test_default_repository_history_returns_latest_fifty_in_deterministic_order(
    db: Session,
) -> None:
    db.add_all(
        _revision(
            revision_id=f"20000000-0000-0000-0000-{revision_no:012d}",
            rule_set_id="classic_8",
            revision_no=revision_no,
            state="superseded",
            config=_classic_config(name=f"历史版本 {revision_no}"),
            updated_at=datetime(2026, 7, 1, tzinfo=UTC),
        )
        for revision_no in range(3, 58)
    )
    db.commit()

    history = list_rule_set_revisions(db, "classic_8")
    aggregate = get_rule_set_aggregate(db, "classic_8")

    assert aggregate is not None
    assert len(history) == len(aggregate.revisions) == 50
    assert [revision.revision_no for revision in history] == list(range(57, 7, -1))
    assert [revision.id for revision in history] == [
        f"20000000-0000-0000-0000-{revision_no:012d}" for revision_no in range(57, 7, -1)
    ]
    assert aggregate.revisions == history
    assert next_rule_set_revision_no(db, "classic_8") == 58


def test_public_listing_excludes_draft_and_archived_and_is_default_first(
    db: Session,
) -> None:
    aggregates = list_published_rule_sets(db)

    assert isinstance(aggregates, tuple)
    assert [aggregate.record.id for aggregate in aggregates] == [
        "classic_8",
        "starter_6",
    ]
    assert all(aggregate.record.status == "published" for aggregate in aggregates)
    assert all(aggregate.draft is None for aggregate in aggregates)
    assert all(aggregate.published is not None for aggregate in aggregates)


def test_public_listing_breaks_equal_display_order_ties_by_stable_id(db: Session) -> None:
    timestamp = datetime(2026, 7, 5, tzinfo=UTC)
    alpha_revision_id = "00000000-0000-0000-0000-000000000501"
    zeta_revision_id = "00000000-0000-0000-0000-000000000601"
    db.add_all(
        (
            RuleSetRecord(
                id="zeta_rule",
                status="published",
                current_published_revision_id=zeta_revision_id,
                is_default=False,
                display_order=5,
                created_at=timestamp,
                updated_at=timestamp,
            ),
            RuleSetRecord(
                id="alpha_rule",
                status="published",
                current_published_revision_id=alpha_revision_id,
                is_default=False,
                display_order=5,
                created_at=timestamp,
                updated_at=timestamp,
            ),
            _revision(
                revision_id=zeta_revision_id,
                rule_set_id="zeta_rule",
                revision_no=1,
                state="published",
                config=_social_config(name="Zeta Rule"),
                updated_at=timestamp,
            ),
            _revision(
                revision_id=alpha_revision_id,
                rule_set_id="alpha_rule",
                revision_no=1,
                state="published",
                config=_social_config(name="Alpha Rule"),
                updated_at=timestamp,
            ),
        )
    )
    db.commit()

    aggregates = list_published_rule_sets(db)

    assert [aggregate.record.id for aggregate in aggregates] == [
        "classic_8",
        "starter_6",
        "alpha_rule",
        "zeta_rule",
    ]
    assert "draft_only" not in {aggregate.record.id for aggregate in aggregates}
    assert "archived_social" not in {aggregate.record.id for aggregate in aggregates}


@pytest.mark.parametrize(
    ("pointer", "foreign_revision_id"),
    [
        ("current_published_revision_id", STARTER_REVISION_ID),
        ("draft_revision_id", DRAFT_REVISION_ID),
    ],
)
def test_parent_pointer_ownership_mismatch_raises_catalog_corrupt(
    db: Session,
    pointer: str,
    foreign_revision_id: str,
) -> None:
    record = db.get(RuleSetRecord, "classic_8")
    assert record is not None
    setattr(record, pointer, foreign_revision_id)
    db.flush()

    for read in (
        lambda: get_rule_set_record(db, "classic_8"),
        lambda: get_rule_set_aggregate(db, "classic_8"),
        lambda: list_published_rule_sets(db),
    ):
        with pytest.raises(RuleSetCatalogCorrupt) as error:
            read()
        _assert_bounded_catalog_error(
            error.value,
            pointer=pointer,
            revision_id=foreign_revision_id,
            reason="pointer_owner_mismatch",
        )


@pytest.mark.parametrize(
    ("pointer", "revision_id", "reason"),
    [
        (
            "current_published_revision_id",
            "00000000-0000-0000-0000-000000000999",
            "pointer_target_missing",
        ),
        (
            "draft_revision_id",
            "00000000-0000-0000-0000-000000000998",
            "pointer_target_missing",
        ),
        (
            "current_published_revision_id",
            CLASSIC_OLD_REVISION_ID,
            "pointer_state_mismatch",
        ),
        (
            "draft_revision_id",
            CLASSIC_REVISION_ID,
            "pointer_state_mismatch",
        ),
    ],
)
def test_parent_pointer_missing_target_or_wrong_state_is_rejected_at_every_read_boundary(
    db: Session,
    pointer: str,
    revision_id: str,
    reason: str,
) -> None:
    record = db.get(RuleSetRecord, "classic_8")
    assert record is not None
    setattr(record, pointer, revision_id)
    db.flush()

    for read in (
        lambda: get_rule_set_record(db, "classic_8"),
        lambda: get_rule_set_aggregate(db, "classic_8"),
        lambda: list_published_rule_sets(db),
    ):
        with pytest.raises(RuleSetCatalogCorrupt) as error:
            read()
        _assert_bounded_catalog_error(
            error.value,
            pointer=pointer,
            revision_id=revision_id,
            reason=reason,
        )


def test_public_listing_never_silently_uses_a_foreign_published_pointer(
    db: Session,
) -> None:
    record = db.get(RuleSetRecord, "classic_8")
    assert record is not None
    record.current_published_revision_id = STARTER_REVISION_ID
    db.flush()

    with pytest.raises(RuleSetCatalogCorrupt, match="classic_8"):
        list_published_rule_sets(db)


def test_public_snapshot_compiles_untrusted_json_and_verifies_managed_metadata(
    db: Session,
) -> None:
    aggregate = get_rule_set_aggregate(db, "classic_8")
    assert aggregate is not None and aggregate.published is not None
    aggregate.published.name = "tampered denormalized name"
    aggregate.published.description = "tampered denormalized description"

    snapshot = public_rule_set_catalog_snapshot(aggregate)

    assert snapshot["id"] == "classic_8"
    assert snapshot["name"] == "经典 8 人局"
    assert snapshot["description"] == "包含狼人、预言家、守卫与村民的官方标准局。"
    assert snapshot["version"] == "2"
    assert snapshot["revision_id"] == CLASSIC_REVISION_ID
    assert snapshot["revision_no"] == 2
    assert snapshot["schema_version"] == 1
    assert snapshot["content_hash"] == aggregate.published.content_hash
    assert snapshot["is_default"] is True
    assert snapshot["display_order"] == 2
    assert snapshot["player_count"] == 8
    assert snapshot["role_summary"] == "2 狼人 / 1 预言家 / 1 守卫 / 4 村民"
    assert [role["role"] for role in snapshot["roles"]] == [
        "狼人",
        "预言家",
        "守卫",
        "村民",
    ]
    assert "config" not in snapshot


def test_public_snapshot_preserves_normalized_ascii_comma_and_detaches_results(
    db: Session,
) -> None:
    aggregate = get_rule_set_aggregate(db, "starter_6")
    assert aggregate is not None

    first = public_rule_set_catalog_snapshot(aggregate)
    roles = first["roles"]
    assert isinstance(roles, list)
    roles[0]["count"] = 99
    second = public_rule_set_catalog_snapshot(aggregate)

    assert first["description"] == "更短的官方入门局,适合快速观察模型策略。"
    assert second["roles"][0]["count"] == 1


@pytest.mark.parametrize("corruption", ["config", "hash", "schema"])
def test_public_snapshot_maps_persisted_corruption_to_bounded_catalog_error(
    db: Session,
    corruption: str,
) -> None:
    aggregate = get_rule_set_aggregate(db, "classic_8")
    assert aggregate is not None and aggregate.published is not None
    if corruption == "config":
        aggregate.published.config = {"name": "not a complete configuration"}
    elif corruption == "hash":
        aggregate.published.content_hash = "f" * 64
    else:
        aggregate.published.schema_version = 2

    with pytest.raises(RuleSetCatalogCorrupt) as error:
        public_rule_set_catalog_snapshot(aggregate)

    message = str(error.value)
    assert "classic_8" in message
    assert "not a complete configuration" not in message
    assert "description" not in message
    assert error.value.__cause__ is None
    assert error.value.__context__ is None


def test_admin_snapshot_corruption_has_no_raw_exception_chain(db: Session) -> None:
    aggregate = get_rule_set_aggregate(db, "classic_8")
    assert aggregate is not None and aggregate.published is not None
    aggregate.published.config = {"description": "SECRET ADMIN CONFIG"}

    with pytest.raises(RuleSetCatalogCorrupt) as error:
        admin_rule_revision_snapshot(aggregate.published, include_config=True)

    assert error.value.reason == "revision_config_invalid"
    assert "SECRET ADMIN CONFIG" not in str(error.value)
    assert error.value.__cause__ is None
    assert error.value.__context__ is None


def test_admin_snapshots_detach_config_and_bound_revision_history(db: Session) -> None:
    aggregate = get_rule_set_aggregate(db, "classic_8")
    assert aggregate is not None and aggregate.published is not None

    revision_snapshot = admin_rule_revision_snapshot(
        aggregate.published,
        include_config=True,
    )
    config = revision_snapshot["config"]
    assert isinstance(config, dict)
    role_counts = config["role_counts"]
    assert isinstance(role_counts, dict)
    role_counts["werewolf"] = 99
    assert aggregate.published.config["role_counts"]["werewolf"] == 2

    metadata_only = admin_rule_revision_snapshot(
        aggregate.published,
        include_config=False,
    )
    assert metadata_only["config"] is None
    assert "description" not in metadata_only
    assert "name" not in metadata_only

    snapshot = admin_rule_set_snapshot(aggregate)
    assert snapshot["id"] == "classic_8"
    assert snapshot["draft_revision"] is None
    assert snapshot["published_revision"]["config"] is not None
    assert [item["revision_no"] for item in snapshot["revisions"]] == [2, 1]
    assert all(item["config"] is None for item in snapshot["revisions"])


def test_admin_snapshot_caps_caller_supplied_revision_history_at_fifty(
    db: Session,
) -> None:
    aggregate = get_rule_set_aggregate(db, "classic_8")
    assert aggregate is not None
    supplied = tuple(
        _revision(
            revision_id=f"10000000-0000-0000-0000-{revision_no:012d}",
            rule_set_id="classic_8",
            revision_no=revision_no,
            state="superseded",
            config=_classic_config(name=f"历史版本 {revision_no}"),
            updated_at=datetime(2026, 7, 1, tzinfo=UTC),
        )
        for revision_no in range(55, 0, -1)
    )
    unbounded = RuleSetAggregate(
        record=aggregate.record,
        draft=aggregate.draft,
        published=aggregate.published,
        revisions=supplied,
    )

    snapshot = admin_rule_set_snapshot(unbounded)

    assert len(snapshot["revisions"]) == 50
    assert [item["revision_no"] for item in snapshot["revisions"]] == list(range(55, 5, -1))
    assert all(item["config"] is None for item in snapshot["revisions"])
    assert all("name" not in item and "description" not in item for item in snapshot["revisions"])


def test_audit_snapshot_contains_only_bounded_metadata_and_changed_fields(
    db: Session,
) -> None:
    aggregate = get_rule_set_aggregate(db, "classic_8")
    assert aggregate is not None
    changed_fields = [
        "description",
        "config",
        '{"description":"must-not-enter-audit"}',
        *(f"field_{index}" for index in range(80)),
    ]

    snapshot = audit_rule_set_snapshot(aggregate, changed_fields=changed_fields)
    encoded = json.dumps(snapshot, ensure_ascii=False)

    assert snapshot["id"] == "classic_8"
    assert snapshot["status"] == "published"
    assert snapshot["published_revision"]["id"] == CLASSIC_REVISION_ID
    assert snapshot["published_revision"]["revision_no"] == 2
    assert len(snapshot["changed_fields"]) <= 50
    assert all(len(field) <= 120 for field in snapshot["changed_fields"])
    assert "config" not in snapshot["published_revision"]
    assert "description" not in snapshot["published_revision"]
    assert "roles" not in encoded
    assert "tampered" not in encoded
    assert "must-not-enter-audit" not in encoded


def _assert_bounded_catalog_error(
    error: RuleSetCatalogCorrupt,
    *,
    pointer: str,
    revision_id: str,
    reason: str,
) -> None:
    assert vars(error) == {
        "rule_set_id": "classic_8",
        "pointer": pointer,
        "revision_id": revision_id,
        "reason": reason,
    }
    assert len(str(error)) <= 200
    assert "config" not in str(error)
    assert "description" not in str(error)
