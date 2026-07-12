from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, Request, Response
from sqlalchemy import func, select
from sqlalchemy.exc import OperationalError, ProgrammingError
from sqlalchemy.orm import Session

from app.admin.rbac import AdminPermission
from app.api.admin.dependencies import AdminPrincipal, require_admin_permission
from app.api.admin.errors import AdminAPIProblem, request_id_for
from app.api.schemas.admin_rule_sets import (
    PLAYER_COUNT_MAX,
    PLAYER_COUNT_MIN,
    REASON_MAX_LENGTH,
    REASON_MIN_LENGTH,
    RULE_SET_ID_PATTERN,
    RULE_TAG_MAX_LENGTH,
    RULE_TAGS_MAX_ITEMS,
    AdminRuleSetDetailResponse,
    AdminRuleSetListResponse,
    AdminRuleSetOptionsResponse,
    AdminRuleSetResponse,
    AdminRuleSetUsage,
    AdminRuleSetWarning,
    RuleSetSort,
    RuleSetStatus,
)
from app.db.session import get_db
from app.models.game_session import GameSessionRecord
from app.models.judge_voice_asset import JudgeVoiceAssetRecord
from app.models.live import LiveRunRecord
from app.models.virtual_player_profile import VirtualPlayerProfile
from app.rule_sets.errors import RuleSetCatalogCorrupt
from app.rule_sets.repository import (
    RuleSetAggregate,
    get_rule_set_aggregate,
    list_rule_sets,
)
from app.rule_sets.snapshots import admin_rule_set_snapshot


router = APIRouter()
RecoverableDatabaseError = (OperationalError, ProgrammingError)

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
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    q: Annotated[str | None, Query(max_length=120)] = None,
    status: RuleSetStatus | None = None,
    player_count: Annotated[int | None, Query(ge=0)] = None,
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
