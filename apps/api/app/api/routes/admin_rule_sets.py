from __future__ import annotations

from typing import Annotated, NoReturn

from fastapi import APIRouter, Depends, Path, Query, Request, Response
from sqlalchemy import func, select
from sqlalchemy.exc import OperationalError, ProgrammingError
from sqlalchemy.orm import Session

from app.admin.audit import record_audit_event
from app.admin.rbac import AdminPermission
from app.api.admin.dependencies import (
    AdminPrincipal,
    require_admin_csrf,
    require_admin_permission,
)
from app.api.admin.errors import AdminAPIProblem, request_id_for
from app.api.schemas.admin_rule_sets import (
    PLAYER_COUNT_MAX,
    PLAYER_COUNT_MIN,
    REASON_MAX_LENGTH,
    REASON_MIN_LENGTH,
    RULE_SET_ID_PATTERN,
    RULE_TAG_MAX_LENGTH,
    RULE_TAGS_MAX_ITEMS,
    AdminRuleSetCreate,
    AdminRuleSetArchive,
    AdminRuleSetDefaultTransition,
    AdminRuleSetDetailResponse,
    AdminRuleSetDraftUpdate,
    AdminRuleSetDuplicate,
    AdminRuleSetListResponse,
    AdminRuleSetOptionsResponse,
    AdminRuleSetResponse,
    AdminRuleSetUsage,
    AdminRuleSetValidate,
    AdminRuleSetValidationResponse,
    AdminRuleSetWarning,
    AdminRuleSetTransition,
    RuleSetSort,
    RuleSetStatus,
)
from app.db.session import get_db
from app.models.game_session import GameSessionRecord
from app.models.judge_voice_asset import JudgeVoiceAssetRecord
from app.models.live import LiveRunRecord
from app.models.rule_set import RuleSetRecord, RuleSetRevisionRecord
from app.models.virtual_player_profile import VirtualPlayerProfile
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
    list_rule_sets,
)
from app.rule_sets.service import (
    archive_rule_set,
    create_rule_set,
    duplicate_rule_set,
    publish_rule_set,
    restore_rule_set,
    set_default_rule_set,
    update_rule_set_draft,
    validate_rule_set_draft,
)
from app.rule_sets.snapshots import (
    admin_rule_set_snapshot,
    audit_rule_set_snapshot,
)
from app.rule_sets.types import RuleValidationIssue
from app.rule_sets.validation import normalize_rule_set_config
from app.werewolf.rules import render_rule_text


router = APIRouter()
RecoverableDatabaseError = (OperationalError, ProgrammingError)
MutationFailure = (
    DefaultRuleRequired,
    RuleRevisionChanged,
    RuleSetCatalogCorrupt,
    RuleSetNotFound,
    RuleSetRevisionNotFound,
    RuleSetTransitionConflict,
    RuleSetUnavailable,
    RuleSetValidationFailed,
    RuleSetVersionConflict,
    ValueError,
    *RecoverableDatabaseError,
)
_MAX_PAGE = 2_147_483_647

_ROLE_OPTIONS = (
    {"id": "werewolf", "label": "狼人", "min_count": 1, "max_count": 5},
    {"id": "villager", "label": "村民", "min_count": 0, "max_count": 11},
    {"id": "seer", "label": "预言家", "min_count": 0, "max_count": 1},
    {"id": "guard", "label": "守卫", "min_count": 0, "max_count": 1},
    {"id": "witch", "label": "女巫", "min_count": 0, "max_count": 1},
    {"id": "hunter", "label": "猎人", "min_count": 0, "max_count": 1},
    {"id": "idiot", "label": "白痴", "min_count": 0, "max_count": 1},
)
_WIN_CONDITIONS = (
    {"value": "wolves_gte_others", "label": "狼人数量不少于好人"},
    {"value": "slaughter_side", "label": "屠边"},
)
_SPEECH_POLICIES = (
    {"value": "sequential", "label": "顺序发言"},
    {"value": "sheriff_directed", "label": "警长指定发言顺序"},
)
_BADGE_POLICIES = (
    {"value": "none", "label": "不撕警徽"},
    {"value": "double", "label": "双爆吞警徽"},
)
_STATUSES = (
    {"value": "draft", "label": "草稿"},
    {"value": "published", "label": "已发布"},
    {"value": "archived", "label": "已归档"},
)
_SORTS = tuple(
    {"value": value, "label": value}
    for value in (
        "display_order",
        "-display_order",
        "updated_at",
        "-updated_at",
        "name",
        "-name",
        "created_at",
        "-created_at",
    )
)


@router.get("/rule-set-options", response_model=AdminRuleSetOptionsResponse)
def get_rule_set_options(
    request: Request,
    response: Response,
    _principal: Annotated[
        AdminPrincipal,
        Depends(require_admin_permission(AdminPermission.RULES_READ)),
    ],
) -> AdminRuleSetOptionsResponse:
    _set_private_headers(request, response)
    return AdminRuleSetOptionsResponse(
        roles=list(_ROLE_OPTIONS),
        win_conditions=list(_WIN_CONDITIONS),
        sheriff_vote_weights=[1.0, 1.5, 2.0],
        speech_policies=list(_SPEECH_POLICIES),
        sheriff_badge_bomb_policies=list(_BADGE_POLICIES),
        statuses=list(_STATUSES),
        sorts=list(_SORTS),
        constraints={
            "player_count_min": PLAYER_COUNT_MIN,
            "player_count_max": PLAYER_COUNT_MAX,
            "tags_max_items": RULE_TAGS_MAX_ITEMS,
            "tag_max_length": RULE_TAG_MAX_LENGTH,
            "id_pattern": RULE_SET_ID_PATTERN,
            "reason_min_length": REASON_MIN_LENGTH,
            "reason_max_length": REASON_MAX_LENGTH,
        },
    )


@router.get("/rule-sets", response_model=AdminRuleSetListResponse)
def list_admin_rule_sets(
    request: Request,
    response: Response,
    db: Annotated[Session, Depends(get_db)],
    _principal: Annotated[
        AdminPrincipal,
        Depends(require_admin_permission(AdminPermission.RULES_READ)),
    ],
    page: Annotated[int, Query(ge=1, le=_MAX_PAGE)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    q: Annotated[str | None, Query(max_length=120)] = None,
    status: RuleSetStatus | None = None,
    player_count: Annotated[
        int | None,
        Query(ge=PLAYER_COUNT_MIN, le=PLAYER_COUNT_MAX),
    ] = None,
    sort: RuleSetSort = "display_order",
) -> AdminRuleSetListResponse:
    try:
        result = list_rule_sets(
            db,
            page=page,
            page_size=page_size,
            q=q,
            status=status,
            player_count=player_count,
            sort=sort,
        )
        items = [
            AdminRuleSetResponse.model_validate(admin_rule_set_snapshot(aggregate))
            for aggregate in result.items
        ]
    except (RuleSetCatalogCorrupt, *RecoverableDatabaseError) as exc:
        raise _store_unavailable() from exc
    _set_private_headers(request, response)
    return AdminRuleSetListResponse(
        items=items,
        pagination={
            "page": result.page,
            "page_size": result.page_size,
            "total": result.total,
            "pages": result.pages,
        },
    )


@router.get("/rule-sets/{rule_set_id}", response_model=AdminRuleSetDetailResponse)
def get_admin_rule_set(
    rule_set_id: Annotated[str, Path(pattern=RULE_SET_ID_PATTERN)],
    request: Request,
    response: Response,
    db: Annotated[Session, Depends(get_db)],
    _principal: Annotated[
        AdminPrincipal,
        Depends(require_admin_permission(AdminPermission.RULES_READ)),
    ],
) -> AdminRuleSetDetailResponse:
    try:
        aggregate = get_rule_set_aggregate(db, rule_set_id, revision_limit=50)
        if aggregate is None:
            raise _not_found()
        snapshot = admin_rule_set_snapshot(aggregate)
        usage = _usage_counts(db, rule_set_id)
        warnings = _operational_warnings(db, aggregate)
    except AdminAPIProblem:
        raise
    except (RuleSetCatalogCorrupt, *RecoverableDatabaseError) as exc:
        raise _store_unavailable() from exc
    _set_private_headers(request, response)
    return AdminRuleSetDetailResponse.model_validate(
        {**snapshot, "usage": usage, "warnings": warnings}
    )


@router.post(
    "/rule-sets",
    response_model=AdminRuleSetResponse,
    status_code=201,
)
def create_admin_rule_set(
    request_body: AdminRuleSetCreate,
    request: Request,
    response: Response,
    db: Annotated[Session, Depends(get_db)],
    principal: Annotated[
        AdminPrincipal,
        Depends(require_admin_permission(AdminPermission.RULES_WRITE)),
    ],
    _csrf: Annotated[AdminPrincipal, Depends(require_admin_csrf)],
) -> AdminRuleSetResponse:
    action = "admin.rule_set.create"
    try:
        aggregate = create_rule_set(
            db,
            rule_set_id=request_body.id,
            config=normalize_rule_set_config(request_body.config.model_dump()),
            display_order=request_body.display_order,
            actor_user_id=principal.user.id,
        )
        payload = AdminRuleSetResponse.model_validate(admin_rule_set_snapshot(aggregate))
        _commit_successful_mutation(
            db,
            request=request,
            principal=principal,
            action=action,
            resource_id=aggregate.record.id,
            before=None,
            after=audit_rule_set_snapshot(aggregate, changed_fields=("created",)),
        )
    except MutationFailure as exc:
        _raise_mutation_problem(
            db,
            request=request,
            principal=principal,
            action=action,
            resource_id=request_body.id,
            current_rule_set_id=request_body.id,
            exc=exc,
        )
    _set_private_headers(request, response)
    return payload


@router.patch(
    "/rule-sets/{rule_set_id}/draft",
    response_model=AdminRuleSetResponse,
)
def update_admin_rule_set_draft(
    rule_set_id: Annotated[str, Path(pattern=RULE_SET_ID_PATTERN)],
    request_body: AdminRuleSetDraftUpdate,
    request: Request,
    response: Response,
    db: Annotated[Session, Depends(get_db)],
    principal: Annotated[
        AdminPrincipal,
        Depends(require_admin_permission(AdminPermission.RULES_WRITE)),
    ],
    _csrf: Annotated[AdminPrincipal, Depends(require_admin_csrf)],
) -> AdminRuleSetResponse:
    action = "admin.rule_set.update"
    try:
        existing = get_rule_set_aggregate(db, rule_set_id, revision_limit=1)
        before = audit_rule_set_snapshot(existing) if existing is not None else None
        aggregate = update_rule_set_draft(
            db,
            rule_set_id,
            config=normalize_rule_set_config(request_body.config.model_dump()),
            display_order=request_body.display_order,
            expected_rule_set_lock_version=request_body.expected_rule_set_lock_version,
            expected_revision_lock_version=request_body.expected_revision_lock_version,
            actor_user_id=principal.user.id,
        )
        payload = AdminRuleSetResponse.model_validate(admin_rule_set_snapshot(aggregate))
        _commit_successful_mutation(
            db,
            request=request,
            principal=principal,
            action=action,
            resource_id=rule_set_id,
            before=before,
            after=audit_rule_set_snapshot(
                aggregate,
                changed_fields=("display_order", "draft_revision"),
            ),
        )
    except MutationFailure as exc:
        _raise_mutation_problem(
            db,
            request=request,
            principal=principal,
            action=action,
            resource_id=rule_set_id,
            current_rule_set_id=rule_set_id,
            exc=exc,
            expected={
                "expected_rule_set_lock_version": (request_body.expected_rule_set_lock_version),
                "expected_revision_lock_version": (request_body.expected_revision_lock_version),
            },
        )
    _set_private_headers(request, response)
    return payload


@router.post(
    "/rule-sets/{rule_set_id}/validate",
    response_model=AdminRuleSetValidationResponse,
    response_model_exclude_none=True,
)
def validate_admin_rule_set_draft(
    rule_set_id: Annotated[str, Path(pattern=RULE_SET_ID_PATTERN)],
    request_body: AdminRuleSetValidate,
    request: Request,
    response: Response,
    db: Annotated[Session, Depends(get_db)],
    principal: Annotated[
        AdminPrincipal,
        Depends(require_admin_permission(AdminPermission.RULES_WRITE)),
    ],
    _csrf: Annotated[AdminPrincipal, Depends(require_admin_csrf)],
) -> AdminRuleSetValidationResponse:
    action = "admin.rule_set.validate"
    try:
        result = validate_rule_set_draft(
            db,
            rule_set_id,
            expected_revision_lock_version=request_body.expected_revision_lock_version,
        )
        errors = [_issue_response(issue) for issue in result.validation.errors]
        warnings = [_issue_response(issue) for issue in result.validation.warnings]
        warnings.extend(_operational_warnings(db, result.aggregate))
        valid = result.validation.valid
        if result.compiled is None:
            payload = AdminRuleSetValidationResponse(
                valid=False,
                errors=errors,
                warnings=warnings,
            )
        else:
            payload = AdminRuleSetValidationResponse(
                valid=True,
                errors=errors,
                warnings=warnings,
                compiled_snapshot=result.compiled.snapshot,
                content_hash=result.compiled.content_hash,
                rule_text_preview=render_rule_text(result.compiled.rule_set),
            )
        _commit_successful_mutation(
            db,
            request=request,
            principal=principal,
            action=action,
            resource_id=rule_set_id,
            result="success" if valid else "rejected",
            reason=None if valid else "rule_set_validation_failed",
            before=audit_rule_set_snapshot(result.aggregate),
            after=audit_rule_set_snapshot(
                result.aggregate,
                changed_fields=("validation",),
            ),
        )
    except MutationFailure as exc:
        _raise_mutation_problem(
            db,
            request=request,
            principal=principal,
            action=action,
            resource_id=rule_set_id,
            current_rule_set_id=rule_set_id,
            exc=exc,
            expected={
                "expected_revision_lock_version": (request_body.expected_revision_lock_version)
            },
        )
    _set_private_headers(request, response)
    return payload


@router.post(
    "/rule-sets/{rule_set_id}/publish",
    response_model=AdminRuleSetResponse,
)
def publish_admin_rule_set(
    rule_set_id: Annotated[str, Path(pattern=RULE_SET_ID_PATTERN)],
    request_body: AdminRuleSetTransition,
    request: Request,
    response: Response,
    db: Annotated[Session, Depends(get_db)],
    principal: Annotated[
        AdminPrincipal,
        Depends(require_admin_permission(AdminPermission.RULES_PUBLISH)),
    ],
    _csrf: Annotated[AdminPrincipal, Depends(require_admin_csrf)],
) -> AdminRuleSetResponse:
    action = "admin.rule_set.publish"
    try:
        existing = get_rule_set_aggregate(db, rule_set_id, revision_limit=1)
        before = audit_rule_set_snapshot(existing) if existing is not None else None
        aggregate = publish_rule_set(
            db,
            rule_set_id,
            expected_rule_set_lock_version=request_body.expected_rule_set_lock_version,
            expected_revision_lock_version=request_body.expected_revision_lock_version,
            reason=request_body.reason,
            actor_user_id=principal.user.id,
        )
        payload = AdminRuleSetResponse.model_validate(admin_rule_set_snapshot(aggregate))
        _commit_successful_mutation(
            db,
            request=request,
            principal=principal,
            action=action,
            resource_id=rule_set_id,
            reason=request_body.reason,
            before=before,
            after=audit_rule_set_snapshot(
                aggregate,
                changed_fields=("status", "draft_revision", "published_revision"),
            ),
        )
    except MutationFailure as exc:
        _raise_mutation_problem(
            db,
            request=request,
            principal=principal,
            action=action,
            resource_id=rule_set_id,
            current_rule_set_id=rule_set_id,
            exc=exc,
            reason=request_body.reason,
            expected={
                "expected_rule_set_lock_version": (request_body.expected_rule_set_lock_version),
                "expected_revision_lock_version": (request_body.expected_revision_lock_version),
            },
        )
    _set_private_headers(request, response)
    return payload


@router.post(
    "/rule-sets/{rule_set_id}/archive",
    response_model=AdminRuleSetResponse,
)
def archive_admin_rule_set(
    rule_set_id: Annotated[str, Path(pattern=RULE_SET_ID_PATTERN)],
    request_body: AdminRuleSetArchive,
    request: Request,
    response: Response,
    db: Annotated[Session, Depends(get_db)],
    principal: Annotated[
        AdminPrincipal,
        Depends(require_admin_permission(AdminPermission.RULES_ARCHIVE)),
    ],
    _csrf: Annotated[AdminPrincipal, Depends(require_admin_csrf)],
) -> AdminRuleSetResponse:
    action = "admin.rule_set.archive"
    try:
        existing = get_rule_set_aggregate(db, rule_set_id, revision_limit=1)
        before = audit_rule_set_snapshot(existing) if existing is not None else None
        aggregate = archive_rule_set(
            db,
            rule_set_id,
            expected_rule_set_lock_version=request_body.expected_rule_set_lock_version,
            replacement_default_rule_set_id=request_body.replacement_default_rule_set_id,
            replacement_expected_lock_version=request_body.replacement_expected_lock_version,
            reason=request_body.reason,
            actor_user_id=principal.user.id,
        )
        payload = AdminRuleSetResponse.model_validate(admin_rule_set_snapshot(aggregate))
        changed_fields = ["status", "is_default"]
        if request_body.replacement_default_rule_set_id is not None:
            changed_fields.append("replacement_default_rule_set_id")
        _commit_successful_mutation(
            db,
            request=request,
            principal=principal,
            action=action,
            resource_id=rule_set_id,
            reason=request_body.reason,
            before=before,
            after=audit_rule_set_snapshot(aggregate, changed_fields=changed_fields),
        )
    except MutationFailure as exc:
        _raise_mutation_problem(
            db,
            request=request,
            principal=principal,
            action=action,
            resource_id=rule_set_id,
            current_rule_set_id=rule_set_id,
            exc=exc,
            reason=request_body.reason,
            expected={
                "expected_rule_set_lock_version": (request_body.expected_rule_set_lock_version),
                "expected_revision_lock_version": (request_body.expected_revision_lock_version),
                "replacement_default_rule_set_id": (request_body.replacement_default_rule_set_id),
                "replacement_expected_lock_version": (
                    request_body.replacement_expected_lock_version
                ),
            },
        )
    _set_private_headers(request, response)
    return payload


@router.post(
    "/rule-sets/{rule_set_id}/restore",
    response_model=AdminRuleSetResponse,
)
def restore_admin_rule_set(
    rule_set_id: Annotated[str, Path(pattern=RULE_SET_ID_PATTERN)],
    request_body: AdminRuleSetTransition,
    request: Request,
    response: Response,
    db: Annotated[Session, Depends(get_db)],
    principal: Annotated[
        AdminPrincipal,
        Depends(require_admin_permission(AdminPermission.RULES_ARCHIVE)),
    ],
    _csrf: Annotated[AdminPrincipal, Depends(require_admin_csrf)],
) -> AdminRuleSetResponse:
    action = "admin.rule_set.restore"
    try:
        existing = get_rule_set_aggregate(db, rule_set_id, revision_limit=1)
        before = audit_rule_set_snapshot(existing) if existing is not None else None
        aggregate = restore_rule_set(
            db,
            rule_set_id,
            expected_rule_set_lock_version=request_body.expected_rule_set_lock_version,
            reason=request_body.reason,
            actor_user_id=principal.user.id,
        )
        payload = AdminRuleSetResponse.model_validate(admin_rule_set_snapshot(aggregate))
        _commit_successful_mutation(
            db,
            request=request,
            principal=principal,
            action=action,
            resource_id=rule_set_id,
            reason=request_body.reason,
            before=before,
            after=audit_rule_set_snapshot(aggregate, changed_fields=("status",)),
        )
    except MutationFailure as exc:
        _raise_mutation_problem(
            db,
            request=request,
            principal=principal,
            action=action,
            resource_id=rule_set_id,
            current_rule_set_id=rule_set_id,
            exc=exc,
            reason=request_body.reason,
            expected={
                "expected_rule_set_lock_version": (request_body.expected_rule_set_lock_version),
                "expected_revision_lock_version": (request_body.expected_revision_lock_version),
            },
        )
    _set_private_headers(request, response)
    return payload


@router.post(
    "/rule-sets/{rule_set_id}/set-default",
    response_model=AdminRuleSetResponse,
)
def set_default_admin_rule_set(
    rule_set_id: Annotated[str, Path(pattern=RULE_SET_ID_PATTERN)],
    request_body: AdminRuleSetDefaultTransition,
    request: Request,
    response: Response,
    db: Annotated[Session, Depends(get_db)],
    principal: Annotated[
        AdminPrincipal,
        Depends(require_admin_permission(AdminPermission.RULES_SET_DEFAULT)),
    ],
    _csrf: Annotated[AdminPrincipal, Depends(require_admin_csrf)],
) -> AdminRuleSetResponse:
    action = "admin.rule_set.set_default"
    try:
        existing = get_rule_set_aggregate(db, rule_set_id, revision_limit=1)
        before = audit_rule_set_snapshot(existing) if existing is not None else None
        change = set_default_rule_set(
            db,
            rule_set_id,
            expected_rule_set_lock_version=request_body.expected_rule_set_lock_version,
            previous_default_expected_lock_version=(
                request_body.previous_default_expected_lock_version
            ),
            reason=request_body.reason,
            actor_user_id=principal.user.id,
        )
        aggregate = change.current_default
        payload = AdminRuleSetResponse.model_validate(admin_rule_set_snapshot(aggregate))
        _commit_successful_mutation(
            db,
            request=request,
            principal=principal,
            action=action,
            resource_id=rule_set_id,
            reason=request_body.reason,
            before=before,
            after=audit_rule_set_snapshot(aggregate, changed_fields=("is_default",)),
        )
    except MutationFailure as exc:
        _raise_mutation_problem(
            db,
            request=request,
            principal=principal,
            action=action,
            resource_id=rule_set_id,
            current_rule_set_id=rule_set_id,
            exc=exc,
            reason=request_body.reason,
            expected={
                "expected_rule_set_lock_version": (request_body.expected_rule_set_lock_version),
                "previous_default_expected_lock_version": (
                    request_body.previous_default_expected_lock_version
                ),
            },
        )
    _set_private_headers(request, response)
    return payload


@router.post(
    "/rule-sets/{rule_set_id}/duplicate",
    response_model=AdminRuleSetResponse,
    status_code=201,
)
def duplicate_admin_rule_set(
    rule_set_id: Annotated[str, Path(pattern=RULE_SET_ID_PATTERN)],
    request_body: AdminRuleSetDuplicate,
    request: Request,
    response: Response,
    db: Annotated[Session, Depends(get_db)],
    principal: Annotated[
        AdminPrincipal,
        Depends(require_admin_permission(AdminPermission.RULES_WRITE)),
    ],
    _csrf: Annotated[AdminPrincipal, Depends(require_admin_csrf)],
) -> AdminRuleSetResponse:
    action = "admin.rule_set.duplicate"
    try:
        source = get_rule_set_aggregate(db, rule_set_id, revision_limit=1)
        before = audit_rule_set_snapshot(source) if source is not None else None
        aggregate = duplicate_rule_set(
            db,
            rule_set_id,
            new_rule_set_id=request_body.new_rule_set_id,
            new_name=request_body.new_name,
            expected_source_lock_version=request_body.expected_source_lock_version,
            actor_user_id=principal.user.id,
        )
        payload = AdminRuleSetResponse.model_validate(admin_rule_set_snapshot(aggregate))
        _commit_successful_mutation(
            db,
            request=request,
            principal=principal,
            action=action,
            resource_id=aggregate.record.id,
            before=before,
            after=audit_rule_set_snapshot(
                aggregate,
                changed_fields=("created", "duplicated_from"),
            ),
        )
    except MutationFailure as exc:
        _raise_mutation_problem(
            db,
            request=request,
            principal=principal,
            action=action,
            resource_id=request_body.new_rule_set_id,
            current_rule_set_id=rule_set_id,
            exc=exc,
            expected={
                "expected_rule_set_lock_version": (request_body.expected_source_lock_version)
            },
        )
    _set_private_headers(request, response)
    return payload


def _usage_counts(db: Session, rule_set_id: str) -> AdminRuleSetUsage:
    live_run_count = int(
        db.scalar(
            select(func.count())
            .select_from(LiveRunRecord)
            .where(LiveRunRecord.rule_set_id == rule_set_id)
        )
        or 0
    )
    game_session_count = int(
        db.scalar(
            select(func.count())
            .select_from(GameSessionRecord)
            .where(GameSessionRecord.rule_set["id"].as_string() == rule_set_id)
        )
        or 0
    )
    return AdminRuleSetUsage(
        game_count=game_session_count,
        live_count=live_run_count,
    )


def _operational_warnings(
    db: Session,
    aggregate: RuleSetAggregate,
) -> list[AdminRuleSetWarning]:
    revision = aggregate.draft or aggregate.published
    if revision is None or revision.player_count <= 0:
        return []
    required = revision.player_count
    published_profiles = int(
        db.scalar(
            select(func.count())
            .select_from(VirtualPlayerProfile)
            .where(VirtualPlayerProfile.status == "published")
        )
        or 0
    )
    covered_seats = int(
        db.scalar(
            select(func.count(func.distinct(JudgeVoiceAssetRecord.seat_number))).where(
                JudgeVoiceAssetRecord.seat_number.is_not(None),
                JudgeVoiceAssetRecord.seat_number >= 1,
                JudgeVoiceAssetRecord.seat_number <= required,
                JudgeVoiceAssetRecord.size_bytes > 0,
            )
        )
        or 0
    )
    warnings: list[AdminRuleSetWarning] = []
    if published_profiles < required:
        warnings.append(
            AdminRuleSetWarning(
                code="published_player_shortage",
                path="player_profiles",
                message=(
                    f"Only {published_profiles} published player profiles are available "
                    f"for {required} seats."
                ),
            )
        )
    if covered_seats < required:
        warnings.append(
            AdminRuleSetWarning(
                code="judge_seat_coverage",
                path="judge_voice_assets",
                message=(f"Judge voice assets cover {covered_seats} of {required} required seats."),
            )
        )
    return warnings[:10]


def _raise_mutation_problem(
    db: Session,
    *,
    request: Request,
    principal: AdminPrincipal,
    action: str,
    resource_id: str,
    current_rule_set_id: str,
    exc: Exception,
    reason: str | None = None,
    expected: dict[str, object] | None = None,
) -> NoReturn:
    db.rollback()
    failure_rule_set_id = _bounded_identifier(getattr(exc, "rule_set_id", None), 80)
    current = _current_rule_set_versions(
        db,
        failure_rule_set_id or current_rule_set_id,
    )
    problem = _mutation_problem(exc, current=current)
    attempt = _bounded_attempt(expected)
    attempt.update(current)
    try:
        record_audit_event(
            db,
            request=request,
            actor_user_id=principal.user.id,
            action=action,
            resource_type="rule_set",
            resource_id=resource_id,
            result=_failure_result(exc),
            reason=reason or problem.code,
            after=attempt,
        )
        db.commit()
    except RecoverableDatabaseError:
        db.rollback()
        raise _store_unavailable() from None
    raise problem from None


def _current_rule_set_versions(db: Session, rule_set_id: str) -> dict[str, object]:
    empty = {
        "current_rule_set_id": _bounded_identifier(rule_set_id, 80),
        "current_status": None,
        "current_rule_set_lock_version": None,
        "current_revision_id": None,
        "current_revision_lock_version": None,
    }
    try:
        row = db.execute(
            select(
                RuleSetRecord.status.label("current_status"),
                RuleSetRecord.lock_version.label("rule_set_lock_version"),
                RuleSetRecord.draft_revision_id,
                RuleSetRecord.current_published_revision_id,
            ).where(RuleSetRecord.id == rule_set_id)
        ).one_or_none()
        if row is None:
            return empty
        current_revision_id = row.draft_revision_id or row.current_published_revision_id
        current_revision_lock_version: int | None = None
        if current_revision_id is not None:
            current_revision_lock_version = db.scalar(
                select(RuleSetRevisionRecord.lock_version).where(
                    RuleSetRevisionRecord.id == current_revision_id
                )
            )
    except RecoverableDatabaseError:
        db.rollback()
        return empty
    return {
        "current_rule_set_id": _bounded_identifier(rule_set_id, 80),
        "current_status": _bounded_status(row.current_status),
        "current_rule_set_lock_version": _bounded_lock_version(row.rule_set_lock_version),
        "current_revision_id": _bounded_identifier(current_revision_id, 36),
        "current_revision_lock_version": _bounded_lock_version(current_revision_lock_version),
    }


def _mutation_problem(
    exc: Exception,
    *,
    current: dict[str, object],
) -> AdminAPIProblem:
    if isinstance(exc, RuleSetValidationFailed):
        return AdminAPIProblem(
            status_code=422,
            code="rule_set_validation_failed",
            title="Rule set validation failed",
            detail="The rule set has validation errors.",
            extensions={
                "errors": [
                    {
                        "code": issue.code,
                        "path": issue.path,
                        "message": issue.message,
                    }
                    for issue in exc.issues
                ]
            },
        )
    if isinstance(exc, ValueError):
        return AdminAPIProblem(
            status_code=422,
            code="rule_set_validation_failed",
            title="Rule set validation failed",
            detail="The rule set has validation errors.",
            extensions={
                "errors": [
                    {
                        "code": "rule_configuration_invalid",
                        "path": "config",
                        "message": "Rule configuration is invalid.",
                    }
                ]
            },
        )
    if isinstance(exc, RuleSetVersionConflict):
        current_rule_set_lock_version = current["current_rule_set_lock_version"]
        current_revision_lock_version = current["current_revision_lock_version"]
        return AdminAPIProblem(
            status_code=409,
            code="rule_set_version_conflict",
            title="Rule set changed",
            detail="The rule set was changed by another user. Reload and try again.",
            extensions={
                "current_rule_set_lock_version": (
                    current_rule_set_lock_version
                    if current_rule_set_lock_version is not None
                    else exc.current_rule_set_lock_version
                ),
                "current_revision_lock_version": (
                    current_revision_lock_version
                    if current_revision_lock_version is not None
                    else exc.current_revision_lock_version
                ),
            },
        )
    if isinstance(exc, (RuleSetRevisionNotFound, RuleRevisionChanged)):
        current_revision_id = current["current_revision_id"]
        if current_revision_id is None and isinstance(exc, RuleRevisionChanged):
            current_revision_id = exc.current_revision_id
        return AdminAPIProblem(
            status_code=409,
            code="rule_revision_changed",
            title="Rule revision changed",
            detail="The rule set revision changed. Reload and try again.",
            extensions={"current_revision_id": current_revision_id},
        )
    if isinstance(exc, (RuleSetTransitionConflict, RuleSetUnavailable)):
        current_status = current["current_status"]
        if current_status is None:
            current_status = exc.current_status
        return AdminAPIProblem(
            status_code=409,
            code="rule_set_unavailable",
            title="Rule set unavailable",
            detail="The requested rule set operation is unavailable in its current state.",
            extensions={"current_status": current_status},
        )
    if isinstance(exc, DefaultRuleRequired):
        return AdminAPIProblem(
            status_code=409,
            code="default_rule_required",
            title="Default rule required",
            detail="A published default rule set is required for this operation.",
        )
    if isinstance(exc, RuleSetNotFound):
        return _not_found()
    return _store_unavailable()


def _failure_result(exc: Exception) -> str:
    if isinstance(exc, (RuleSetValidationFailed, ValueError)):
        return "rejected"
    if isinstance(
        exc,
        (
            DefaultRuleRequired,
            RuleRevisionChanged,
            RuleSetRevisionNotFound,
            RuleSetTransitionConflict,
            RuleSetUnavailable,
            RuleSetVersionConflict,
        ),
    ):
        return "conflict"
    return "failure"


_ATTEMPT_LOCK_VERSION_FIELDS = frozenset(
    {
        "expected_rule_set_lock_version",
        "expected_revision_lock_version",
        "previous_default_expected_lock_version",
        "replacement_expected_lock_version",
    }
)
_ATTEMPT_ID_FIELDS = frozenset({"replacement_default_rule_set_id"})


def _bounded_attempt(expected: dict[str, object] | None) -> dict[str, object]:
    if expected is None:
        return {}
    attempt: dict[str, object] = {}
    for field in _ATTEMPT_LOCK_VERSION_FIELDS:
        if field in expected:
            attempt[field] = _bounded_lock_version(expected[field])
    for field in _ATTEMPT_ID_FIELDS:
        if field in expected:
            attempt[field] = _bounded_identifier(expected[field], 80)
    return attempt


def _bounded_lock_version(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return max(0, min(value, 2_147_483_647))


def _bounded_identifier(value: object, maximum: int) -> str | None:
    if value is None:
        return None
    return value[:maximum] if isinstance(value, str) else None


def _bounded_status(value: object) -> str | None:
    return value if value in {"draft", "published", "archived"} else None


def _commit_successful_mutation(
    db: Session,
    *,
    request: Request,
    principal: AdminPrincipal,
    action: str,
    resource_id: str,
    before: dict | list | None,
    after: dict | list | None,
    result: str = "success",
    reason: str | None = None,
) -> None:
    record_audit_event(
        db,
        request=request,
        actor_user_id=principal.user.id,
        action=action,
        resource_type="rule_set",
        resource_id=resource_id,
        result=result,
        reason=reason,
        before=before,
        after=after,
    )
    db.commit()


def _issue_response(issue: RuleValidationIssue) -> AdminRuleSetWarning:
    return AdminRuleSetWarning(
        code=issue.code,
        path=issue.path,
        message=issue.message,
    )


def _set_private_headers(request: Request, response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    response.headers["X-Request-ID"] = request_id_for(request)


def _not_found() -> AdminAPIProblem:
    return AdminAPIProblem(
        status_code=404,
        code="admin_rule_set_not_found",
        title="Rule set not found",
        detail="The requested rule set does not exist.",
    )


def _store_unavailable() -> AdminAPIProblem:
    return AdminAPIProblem(
        status_code=503,
        code="rule_set_store_unavailable",
        title="Rule set store unavailable",
        detail="Rule set data is temporarily unavailable.",
    )
