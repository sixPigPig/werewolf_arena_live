from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, aliased

from app.models.rule_set import RuleSetRecord, RuleSetRevisionRecord
from app.rule_sets.errors import RuleSetCatalogCorrupt


RuleSetStatus = Literal["draft", "published", "archived"]
RuleSetSort = Literal[
    "display_order",
    "-display_order",
    "updated_at",
    "-updated_at",
    "name",
    "-name",
    "created_at",
    "-created_at",
]

_RULE_SET_STATUSES = frozenset({"draft", "published", "archived"})
_RULE_SET_SORTS = frozenset(
    {
        "display_order",
        "-display_order",
        "updated_at",
        "-updated_at",
        "name",
        "-name",
        "created_at",
        "-created_at",
    }
)
_MAX_PAGE_SIZE = 100
_MAX_REVISION_HISTORY = 50


@dataclass(frozen=True)
class RuleSetAggregate:
    record: RuleSetRecord
    draft: RuleSetRevisionRecord | None
    published: RuleSetRevisionRecord | None
    revisions: tuple[RuleSetRevisionRecord, ...] = ()


@dataclass(frozen=True)
class RuleSetPage:
    items: tuple[RuleSetAggregate, ...]
    page: int
    page_size: int
    total: int
    pages: int


def list_rule_sets(
    db: Session,
    *,
    page: int,
    page_size: int,
    q: str | None = None,
    status: RuleSetStatus | None = None,
    player_count: int | None = None,
    sort: RuleSetSort = "display_order",
) -> RuleSetPage:
    _validate_page(page, page_size)
    if status is not None and status not in _RULE_SET_STATUSES:
        raise ValueError("status has an unsupported value")
    if isinstance(player_count, bool) or (
        player_count is not None and (not isinstance(player_count, int) or player_count < 0)
    ):
        raise ValueError("player_count must be a non-negative integer")
    if sort not in _RULE_SET_SORTS:
        raise ValueError("sort has an unsupported value")

    draft = aliased(RuleSetRevisionRecord)
    published = aliased(RuleSetRevisionRecord)
    query = (
        select(RuleSetRecord)
        .outerjoin(draft, draft.id == RuleSetRecord.draft_revision_id)
        .outerjoin(
            published,
            published.id == RuleSetRecord.current_published_revision_id,
        )
    )
    if q is not None and (term := q.strip()):
        pattern = f"%{_escape_like(term)}%"
        query = query.where(
            or_(
                RuleSetRecord.id.ilike(pattern, escape="\\"),
                draft.name.ilike(pattern, escape="\\"),
                draft.description.ilike(pattern, escape="\\"),
                draft.role_summary.ilike(pattern, escape="\\"),
                published.name.ilike(pattern, escape="\\"),
                published.description.ilike(pattern, escape="\\"),
                published.role_summary.ilike(pattern, escape="\\"),
            )
        )
    if status is not None:
        query = query.where(RuleSetRecord.status == status)
    if player_count is not None:
        query = query.where(
            func.coalesce(draft.player_count, published.player_count) == player_count
        )

    total = int(db.scalar(select(func.count()).select_from(query.subquery())) or 0)
    records = tuple(
        db.scalars(
            query.order_by(*_sort_columns(sort, draft=draft, published=published))
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    )
    return RuleSetPage(
        items=_aggregates_for_records(db, records),
        page=page,
        page_size=page_size,
        total=total,
        pages=math.ceil(total / page_size) if total else 0,
    )


def get_rule_set_record(
    db: Session,
    rule_set_id: str,
    *,
    for_update: bool = False,
) -> RuleSetRecord | None:
    record = _fetch_rule_set_record(db, rule_set_id, for_update=for_update)
    if record is not None:
        _aggregates_for_records(db, (record,))
    return record


def get_rule_set_aggregate(
    db: Session,
    rule_set_id: str,
    *,
    revision_limit: int = _MAX_REVISION_HISTORY,
    for_update: bool = False,
) -> RuleSetAggregate | None:
    record = _fetch_rule_set_record(db, rule_set_id, for_update=for_update)
    if record is None:
        return None
    aggregate = _aggregates_for_records(db, (record,))[0]
    revisions = list_rule_set_revisions(db, rule_set_id, limit=revision_limit)
    return RuleSetAggregate(
        record=aggregate.record,
        draft=aggregate.draft,
        published=aggregate.published,
        revisions=revisions,
    )


def get_rule_set_revision(
    db: Session,
    revision_id: str,
    *,
    for_update: bool = False,
) -> RuleSetRevisionRecord | None:
    query = select(RuleSetRevisionRecord).where(RuleSetRevisionRecord.id == revision_id)
    if for_update:
        query = query.with_for_update()
    return db.scalar(query)


def list_rule_set_revisions(
    db: Session,
    rule_set_id: str,
    *,
    limit: int = _MAX_REVISION_HISTORY,
) -> tuple[RuleSetRevisionRecord, ...]:
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 50:
        raise ValueError("limit must be between 1 and 50")
    return tuple(
        db.scalars(
            select(RuleSetRevisionRecord)
            .where(RuleSetRevisionRecord.rule_set_id == rule_set_id)
            .order_by(
                RuleSetRevisionRecord.revision_no.desc(),
                RuleSetRevisionRecord.id.desc(),
            )
            .limit(limit)
        )
    )


def next_rule_set_revision_no(db: Session, rule_set_id: str) -> int:
    current = db.scalar(
        select(func.max(RuleSetRevisionRecord.revision_no)).where(
            RuleSetRevisionRecord.rule_set_id == rule_set_id
        )
    )
    return int(current or 0) + 1


def list_published_rule_sets(db: Session) -> tuple[RuleSetAggregate, ...]:
    records = tuple(
        db.scalars(
            select(RuleSetRecord)
            .where(
                RuleSetRecord.status == "published",
                RuleSetRecord.archived_at.is_(None),
            )
            .order_by(
                RuleSetRecord.is_default.desc(),
                RuleSetRecord.display_order.asc(),
                RuleSetRecord.id.asc(),
            )
        )
    )
    aggregates = _aggregates_for_records(db, records)
    return tuple(
        RuleSetAggregate(
            record=aggregate.record,
            draft=None,
            published=aggregate.published,
        )
        for aggregate in aggregates
    )


def _fetch_rule_set_record(
    db: Session,
    rule_set_id: str,
    *,
    for_update: bool,
) -> RuleSetRecord | None:
    query = select(RuleSetRecord).where(RuleSetRecord.id == rule_set_id)
    if for_update:
        query = query.with_for_update()
    return db.scalar(query)


def _aggregates_for_records(
    db: Session,
    records: tuple[RuleSetRecord, ...],
) -> tuple[RuleSetAggregate, ...]:
    pointer_ids = {
        pointer_id
        for record in records
        for pointer_id in (
            record.draft_revision_id,
            record.current_published_revision_id,
        )
        if pointer_id is not None
    }
    revisions_by_id: dict[str, RuleSetRevisionRecord] = {}
    if pointer_ids:
        revisions_by_id = {
            revision.id: revision
            for revision in db.scalars(
                select(RuleSetRevisionRecord).where(RuleSetRevisionRecord.id.in_(pointer_ids))
            )
        }

    return tuple(
        RuleSetAggregate(
            record=record,
            draft=_pointer_revision(
                record,
                pointer="draft_revision_id",
                revision_id=record.draft_revision_id,
                expected_state="draft",
                revisions_by_id=revisions_by_id,
            ),
            published=_pointer_revision(
                record,
                pointer="current_published_revision_id",
                revision_id=record.current_published_revision_id,
                expected_state="published",
                revisions_by_id=revisions_by_id,
            ),
        )
        for record in records
    )


def _pointer_revision(
    record: RuleSetRecord,
    *,
    pointer: str,
    revision_id: str | None,
    expected_state: str,
    revisions_by_id: dict[str, RuleSetRevisionRecord],
) -> RuleSetRevisionRecord | None:
    if revision_id is None:
        return None
    revision = revisions_by_id.get(revision_id)
    if revision is None:
        raise RuleSetCatalogCorrupt(
            record.id,
            pointer=pointer,
            revision_id=revision_id,
            reason="pointer_target_missing",
        )
    if revision.rule_set_id != record.id:
        raise RuleSetCatalogCorrupt(
            record.id,
            pointer=pointer,
            revision_id=revision_id,
            reason="pointer_owner_mismatch",
        )
    if revision.state != expected_state:
        raise RuleSetCatalogCorrupt(
            record.id,
            pointer=pointer,
            revision_id=revision_id,
            reason="pointer_state_mismatch",
        )
    return revision


def _sort_columns(
    sort: RuleSetSort,
    *,
    draft: object,
    published: object,
) -> tuple[object, ...]:
    descending = sort.startswith("-")
    field = sort.removeprefix("-")
    if field == "name":
        column = func.lower(func.coalesce(draft.name, published.name, RuleSetRecord.id))
    else:
        column = getattr(RuleSetRecord, field)
    ordered = column.desc() if descending else column.asc()
    return ordered, RuleSetRecord.id.asc()


def _validate_page(page: int, page_size: int) -> None:
    if isinstance(page, bool) or not isinstance(page, int) or page < 1:
        raise ValueError("page must be a positive integer")
    if (
        isinstance(page_size, bool)
        or not isinstance(page_size, int)
        or not 1 <= page_size <= _MAX_PAGE_SIZE
    ):
        raise ValueError(f"page_size must be between 1 and {_MAX_PAGE_SIZE}")


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


__all__ = [
    "RuleSetAggregate",
    "RuleSetCatalogCorrupt",
    "RuleSetPage",
    "RuleSetSort",
    "RuleSetStatus",
    "get_rule_set_aggregate",
    "get_rule_set_record",
    "get_rule_set_revision",
    "list_published_rule_sets",
    "list_rule_set_revisions",
    "list_rule_sets",
    "next_rule_set_revision_no",
]
