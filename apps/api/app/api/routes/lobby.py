from dataclasses import replace
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy.exc import OperationalError, ProgrammingError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.api.public.dependencies import public_problem
from app.api.schemas.public_rule_sets import (
    PublicRuleSetCatalogItem,
    PublicRuleSetCatalogResponse,
)
from app.core.config import settings
from app.db.session import get_db
from app.player_profiles.errors import PlayerProfileNotFound
from app.player_profiles.service import (
    get_published_player_profile,
    list_published_player_profiles,
)
from app.rule_sets.errors import (
    RuleRevisionChanged,
    RuleSetCatalogCorrupt,
    RuleSetError,
    RuleSetNotFound,
    RuleSetUnavailable,
)
from app.rule_sets.repository import get_rule_set_aggregate, list_published_rule_sets
from app.rule_sets.service import resolve_published_rule_set
from app.rule_sets.snapshots import public_rule_set_catalog_snapshot
from app.rule_sets.static_catalog import (
    resolve_static_rule_set as _shared_resolve_static_rule_set,
    static_compiled_rule_set_entries,
)
from app.rule_sets.telemetry import record_rule_snapshot_failure
from app.rule_sets.types import CompiledRuleSet
from app.shared.lineup_quality import (
    LineupQualityPolicyV1,
    evaluate_lineup_quality,
    plan_diverse_lineup,
)
from app.shared.player_configs import (
    PlayerConfig,
    clean_optional_string,
    player_config_from_profile,
)
from app.shared.player_presets import is_valid_appearance, is_valid_personality
from app.shared.rules import DEFAULT_RULE_SET_ID, role_summary


router = APIRouter()
RecoverableDatabaseError = (OperationalError, ProgrammingError)
PLAYER_PROFILE_DATABASE_UNAVAILABLE = "Player profile database unavailable"


class CreatePlayerConfigRequest(BaseModel):
    seat: int = Field(ge=1)
    profile_id: str | None = Field(default=None, min_length=1, max_length=36)
    name: str | None = Field(default=None, min_length=1, max_length=80)
    display_name: str | None = Field(default=None, min_length=1, max_length=80)
    model_provider: str | None = Field(default=None, min_length=1, max_length=32)
    model: str | None = Field(default=None, min_length=1, max_length=120)
    personality_id: str | None = Field(default=None, min_length=1, max_length=40)
    personality: str | None = None
    personality_text: str | None = None
    appearance_id: str | None = Field(default=None, min_length=1, max_length=40)
    tags: list[str] | None = Field(default=None, max_length=8)


class LineupPreviewRequest(BaseModel):
    rule_set_id: str = DEFAULT_RULE_SET_ID
    expected_rule_revision_id: str | None = Field(default=None, max_length=36)
    seed: int | None = None
    player_configs: list[CreatePlayerConfigRequest] = Field(default_factory=list)
    locked_seats: list[int] = Field(default_factory=list, max_length=24)
    repair_scope: Literal["empty_only", "unlocked_all"] = "empty_only"
    lineup_quality_policy_version: int = Field(default=1, ge=1, le=1)


def _profile_database_unavailable() -> HTTPException:
    return HTTPException(status_code=503, detail=PLAYER_PROFILE_DATABASE_UNAVAILABLE)


def _rollback_quietly(db: Session) -> None:
    try:
        db.rollback()
    except Exception:
        return


def _lineup_quality_policy() -> LineupQualityPolicyV1:
    return LineupQualityPolicyV1(mode=settings.werewolf_lineup_quality_mode)


def list_available_player_profiles(
    db: Session,
) -> list[object]:
    try:
        return list(list_published_player_profiles(db))
    except RecoverableDatabaseError as exc:
        raise _profile_database_unavailable() from exc


def normalize_player_config_requests(
    requests: list[CreatePlayerConfigRequest],
    player_count: int,
    db: Session,
) -> list[PlayerConfig]:
    if len(requests) > player_count:
        raise HTTPException(status_code=422, detail="Too many player configs")

    seen_seats: set[int] = set()
    configs: list[PlayerConfig] = []
    for request in requests:
        if request.seat > player_count:
            raise HTTPException(
                status_code=422,
                detail=f"Player config seat out of range: {request.seat}",
            )
        if request.seat in seen_seats:
            raise HTTPException(
                status_code=422,
                detail=f"Duplicate player config seat: {request.seat}",
            )
        seen_seats.add(request.seat)

        profile_id = clean_optional_string(request.profile_id)
        profile = None
        if profile_id is not None:
            try:
                profile = get_published_player_profile(db, profile_id)
            except RecoverableDatabaseError as exc:
                raise _profile_database_unavailable() from exc
            except PlayerProfileNotFound:
                raise HTTPException(status_code=422, detail=f"Unknown player profile: {profile_id}")

        personality_id = (
            clean_optional_string(request.personality_id)
            or clean_optional_string(getattr(profile, "personality_id", None))
            or "balanced"
        )
        appearance_id = (
            clean_optional_string(request.appearance_id)
            or clean_optional_string(getattr(profile, "appearance_id", None))
            or "default"
        )
        if not is_valid_personality(personality_id):
            raise HTTPException(status_code=422, detail=f"Unknown personality_id: {personality_id}")
        if not is_valid_appearance(appearance_id):
            raise HTTPException(status_code=422, detail=f"Unknown appearance_id: {appearance_id}")

        overrides = request.model_dump(exclude_unset=True)
        if profile_id is not None:
            overrides["profile_id"] = profile_id
        configs.append(
            player_config_from_profile(
                seat=request.seat,
                profile=profile,
                overrides=overrides,
            )
        )

    return configs


def complete_player_configs_from_library(
    *,
    requests: list[CreatePlayerConfigRequest],
    player_count: int,
    seed: int | None,
    db: Session,
    repair_scope: Literal["empty_only", "unlocked_all"] = "empty_only",
    locked_seats: list[int] | tuple[int, ...] = (),
    policy: LineupQualityPolicyV1 | None = None,
) -> list[PlayerConfig]:
    configs = normalize_player_config_requests(
        requests,
        player_count,
        db,
    )
    available_profiles = list_available_player_profiles(db)
    if len(available_profiles) < player_count:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Player profile library has {len(available_profiles)} available players, "
                f"but {player_count} seats require virtual players"
            ),
        )
    candidates = [
        player_config_from_profile(
            seat=0,
            profile=profile,
            overrides={"profile_id": str(getattr(profile, "id"))},
        )
        for profile in available_profiles
    ]
    lineup = plan_diverse_lineup(
        configs,
        candidates,
        player_count=player_count,
        seed=seed,
        repair_scope=repair_scope,
        locked_seats=locked_seats,
        policy=policy or _lineup_quality_policy(),
    )
    return [
        replace(
            config,
            tts_speaker=config.tts_speaker or settings.ark_tts_player_speaker,
        )
        for config in lineup
    ]


def _catalog_item(snapshot: dict[str, object]) -> PublicRuleSetCatalogItem:
    payload = {
        field_name: snapshot[field_name]
        for field_name in PublicRuleSetCatalogItem.model_fields
        if field_name in snapshot
    }
    payload["werewolf_attack_policy"] = snapshot.get("werewolf_attack_policy")
    return PublicRuleSetCatalogItem.model_validate(payload)


def _static_rule_set_entries() -> list[tuple[CompiledRuleSet, PublicRuleSetCatalogItem]]:
    entries: list[tuple[CompiledRuleSet, PublicRuleSetCatalogItem]] = []
    for compiled, is_default in static_compiled_rule_set_entries():
        catalog_snapshot: dict[str, object] = dict(compiled.snapshot)
        catalog_snapshot.update(
            {
                "is_default": is_default,
                "role_summary": role_summary(compiled.rule_set),
            }
        )
        entries.append((compiled, _catalog_item(catalog_snapshot)))
    return entries


def _static_rule_set_catalog_items() -> list[PublicRuleSetCatalogItem]:
    return [item for _compiled, item in _static_rule_set_entries()]


def _database_rule_set_catalog_items(db: Session) -> list[PublicRuleSetCatalogItem]:
    return [
        _catalog_item(public_rule_set_catalog_snapshot(aggregate))
        for aggregate in list_published_rule_sets(db)
    ]


def _current_rule_set_catalog_item(
    db: Session,
    rule_set_id: str,
) -> PublicRuleSetCatalogItem:
    if settings.rule_set_catalog_source == "static":
        for item in _static_rule_set_catalog_items():
            if item.id == rule_set_id:
                return item
        raise RuleSetNotFound(rule_set_id)
    aggregate = get_rule_set_aggregate(db, rule_set_id)
    if aggregate is None:
        raise RuleSetNotFound(rule_set_id)
    return _catalog_item(public_rule_set_catalog_snapshot(aggregate))


def _resolve_static_rule_set(
    rule_set_id: str,
    *,
    expected_revision_id: str | None,
) -> CompiledRuleSet:
    return _shared_resolve_static_rule_set(
        rule_set_id,
        expected_revision_id=expected_revision_id,
    )


def _resolve_selected_rule_set(
    db: Session,
    *,
    rule_set_id: str,
    expected_revision_id: str | None,
) -> CompiledRuleSet:
    if settings.rule_set_catalog_source == "static":
        return _resolve_static_rule_set(
            rule_set_id,
            expected_revision_id=expected_revision_id,
        )
    return resolve_published_rule_set(
        db,
        rule_set_id,
        expected_revision_id=expected_revision_id,
        for_update=True,
    )


@router.get("/rule-sets", response_model=PublicRuleSetCatalogResponse)
def list_rule_sets(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
) -> PublicRuleSetCatalogResponse:
    try:
        items = (
            _static_rule_set_catalog_items()
            if settings.rule_set_catalog_source == "static"
            else _database_rule_set_catalog_items(db)
        )
    except (
        RuleSetError,
        RuleSetCatalogCorrupt,
        SQLAlchemyError,
        ValidationError,
        KeyError,
        TypeError,
        ValueError,
    ) as exc:
        if isinstance(exc, RuleSetCatalogCorrupt):
            record_rule_snapshot_failure(exc.reason)
        _rollback_quietly(db)
        raise public_problem(
            request,
            status_code=503,
            code="rule_set_store_unavailable",
            detail="Rule set catalog is temporarily unavailable.",
        ) from exc
    return PublicRuleSetCatalogResponse(rule_sets=items)


@router.post("/lineup-preview")
def preview_game_lineup(
    request_body: LineupPreviewRequest,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, object]:
    try:
        compiled = _resolve_selected_rule_set(
            db,
            rule_set_id=request_body.rule_set_id,
            expected_revision_id=request_body.expected_rule_revision_id,
        )
        player_count = compiled.rule_set.player_count
        locked_seats = set(request_body.locked_seats)
        if len(locked_seats) != len(request_body.locked_seats) or any(
            seat < 1 or seat > player_count for seat in locked_seats
        ):
            raise HTTPException(status_code=422, detail="locked_seats are invalid")
        policy = _lineup_quality_policy()
        player_configs = complete_player_configs_from_library(
            requests=request_body.player_configs,
            player_count=player_count,
            seed=request_body.seed,
            db=db,
            repair_scope=request_body.repair_scope,
            locked_seats=tuple(sorted(locked_seats)),
            policy=policy,
        )
        requested_profiles = {
            item.seat: clean_optional_string(item.profile_id)
            for item in request_body.player_configs
        }
        resolved_profiles = {config.seat: config.profile_id for config in player_configs}
        report = evaluate_lineup_quality(
            player_configs,
            player_count=player_count,
            policy=policy,
            was_repaired=requested_profiles != resolved_profiles,
        )
        is_locked_manual_lineup = (
            len(requested_profiles) == player_count
            and all(requested_profiles.values())
            and locked_seats == set(requested_profiles)
        )
        if policy.mode == "repair" and report.is_blocked and not is_locked_manual_lineup:
            raise public_problem(
                request,
                status_code=422,
                code="lineup_quality_unsatisfied",
                detail="The available player profiles cannot satisfy the active quality policy.",
                extensions={
                    "lineup_quality_report": report.to_dict(),
                    "missing_dimensions": sorted(
                        {
                            violation.code
                            for violation in report.violations
                            if violation.severity == "error"
                        }
                    ),
                },
            )
        return {
            "player_configs": [config.to_dict() for config in player_configs],
            "lineup_quality_report": report.to_dict(),
            "rule_set_revision_id": compiled.revision_id,
        }
    except RuleRevisionChanged as exc:
        _rollback_quietly(db)
        raise public_problem(
            request,
            status_code=409,
            code="rule_revision_changed",
            detail="The selected rule revision has changed.",
        ) from exc
    except (RuleSetNotFound, RuleSetUnavailable) as exc:
        _rollback_quietly(db)
        raise public_problem(
            request,
            status_code=409,
            code="rule_set_unavailable",
            detail="The selected rule set is unavailable.",
        ) from exc
    except HTTPException:
        _rollback_quietly(db)
        raise
    except Exception as exc:
        _rollback_quietly(db)
        raise public_problem(
            request,
            status_code=503,
            code="lineup_preview_unavailable",
            detail="The lineup preview is temporarily unavailable.",
        ) from exc
