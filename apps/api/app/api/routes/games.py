from collections.abc import Callable
import logging
import queue
import random
import threading
from typing import Annotated, Any, Iterator

from fastapi import (
    APIRouter,
    Depends,
    Header,
    HTTPException,
    Path,
    Query,
    Request,
    Response,
    WebSocket,
)
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import delete, select
from sqlalchemy.exc import OperationalError, ProgrammingError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.api.public.dependencies import public_problem
from app.api.schemas.public_rule_sets import (
    PublicRuleSetCatalogItem,
    PublicRuleSetCatalogResponse,
)
from app.core.config import settings
from app.db.session import SessionLocal, get_db
from app.models.judge_voice_asset import JudgeVoiceAssetRecord
from app.models.live import LiveEventRecord, LiveRunRecord
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
from app.rule_sets.snapshots import (
    public_rule_set_catalog_snapshot,
    resolve_rule_set_snapshot,
)
from app.rule_sets.types import CompiledRuleSet
from app.werewolf.checkpoint import ResumeCheckpointError
from app.werewolf.config import choose_player_names
from app.werewolf.debate_realism import lineup_quality_warnings
from app.werewolf.live import (
    EventSink,
    GameRunCanceled,
    LiveEvent,
    LiveGameRun,
    LiveRunRegistry,
    RunActivationExpectedState,
    RunLeaseState,
    RunLeaseUnavailable,
    RunRecoveryCandidate,
    format_sse,
)
from app.werewolf.live_store import (
    DatabaseLiveStore,
    stored_event_matches,
)
from app.werewolf.player_configs import (
    PlayerConfig,
    clean_optional_string,
    player_config_from_profile,
    player_configs_from_serialized,
    validate_unique_effective_player_names,
)
from app.werewolf.player_presets import is_valid_appearance, is_valid_personality
from app.werewolf.providers import configured_model_options, default_model_name
from app.werewolf.replay import (
    DatabaseReplayStore,
    GameRecordStore,
    ReplayNotFoundError,
    ReplayWriteFencedError,
    SESSION_ID_RE,
)
from app.werewolf.replay_playback import build_replay_playback
from app.werewolf.rules import (
    DEFAULT_RULE_SET_ID,
    OFFICIAL_RULE_SETS,
    get_rule_set,
    role_summary,
    rule_set_snapshot,
)
from app.werewolf.runner import GameRunError, new_session_id, resume_game, run_game
from app.werewolf.voice import VoiceUtterance
from app.werewolf.judge_voice_assets import DEFAULT_JUDGE_VOICE_ASSET_DIR
from app.werewolf.voice_stream import (
    LiveVoiceStreamService,
    StaticJudgeVoiceAsset,
    build_static_judge_playback_voices,
)
from app.werewolf.voice_store import DatabaseVoiceStore
from app.werewolf.volcengine_tts import VolcengineTtsConfig


router = APIRouter()
logger = logging.getLogger(__name__)
RecoverableDatabaseError = (OperationalError, ProgrammingError)
PLAYER_PROFILE_DATABASE_UNAVAILABLE = "Player profile database unavailable"

_STATIC_RULE_REVISIONS = {
    "classic_8": (
        "e9fa678e-9b18-5079-91d2-f74835364fb6",
        "00095728147a022c48eab88faf21a14567ad0afa13ab9418306e84ff85b10131",
        True,
    ),
    "starter_6": (
        "b607e17e-b86f-5eb0-9dc2-b8df09aa71ab",
        "f2c52827ff3eea2725fbf2f1a01436f69c7e6465a64dec9a92bd7a07a9368f4c",
        False,
    ),
    "social_8": (
        "2b4a993f-e4e6-5312-b11d-92874851a70a",
        "21e1bd2bb495e4479a346724c85a9722477f840afc2c99c389558a52427a0fbc",
        False,
    ),
    "classic_12_seer_witch_hunter_idiot": (
        "0489f6ac-16fd-5323-96ce-ee256c98cf32",
        "bcae38e48a7791fa0f7ae236c90f1852056938ea60f5447532e5d879260d6da2",
        False,
    ),
}


class CreatePlayerConfigRequest(BaseModel):
    seat: int = Field(ge=1)
    profile_id: str | None = Field(default=None, min_length=1, max_length=36)
    name: str | None = Field(default=None, min_length=1, max_length=80)
    display_name: str | None = Field(default=None, min_length=1, max_length=80)
    model: str | None = Field(default=None, min_length=1, max_length=120)
    personality_id: str | None = Field(default=None, min_length=1, max_length=40)
    personality: str | None = None
    personality_text: str | None = None
    appearance_id: str | None = Field(default=None, min_length=1, max_length=40)
    avatar_prompt: str | None = Field(default=None, max_length=500)
    tags: list[str] | None = Field(default=None, max_length=8)


class CreateGameRunRequest(BaseModel):
    villager_model: str = Field(default_factory=default_model_name)
    werewolf_model: str = Field(default_factory=default_model_name)
    seed: int | None = None
    max_rounds: int = Field(default=8, ge=1, le=20)
    rule_set_id: str = DEFAULT_RULE_SET_ID
    expected_rule_revision_id: str | None = Field(default=None, max_length=36)
    player_configs: list[CreatePlayerConfigRequest] = Field(default_factory=list)


def get_replay_store(db: Annotated[Session, Depends(get_db)]) -> DatabaseReplayStore:
    return DatabaseReplayStore(db)


class SessionLiveStore:
    def __init__(self, session_factory: Callable[[], Session] | None = None) -> None:
        self.session_factory = session_factory or SessionLocal

    def save_new_run(self, run: LiveGameRun) -> None:
        db = self.session_factory()
        try:
            DatabaseLiveStore(db).save_new_run(run)
        finally:
            db.close()

    def save_run(self, run: LiveGameRun) -> None:
        db = self.session_factory()
        try:
            DatabaseLiveStore(db).save_run(run)
        finally:
            db.close()

    def activate_run(
        self,
        run_id: str,
        *,
        expected_events: tuple[LiveEvent, ...],
        expected_status: str,
        expected_started_at: str | None,
        activation: LiveEvent,
        worker_id: str,
        fence_token: int,
        started_at: str,
    ) -> None:
        db = self.session_factory()
        try:
            DatabaseLiveStore(db).activate_run(
                run_id,
                expected_events=expected_events,
                expected_status=expected_status,
                expected_started_at=expected_started_at,
                activation=activation,
                worker_id=worker_id,
                fence_token=fence_token,
                started_at=started_at,
            )
        finally:
            db.close()

    def activation_was_committed(
        self,
        expected_state: RunActivationExpectedState,
    ) -> bool:
        db = self.session_factory()
        try:
            return DatabaseLiveStore(db).activation_was_committed(expected_state)
        finally:
            db.close()

    def append_event(
        self,
        event: LiveEvent,
        *,
        worker_id: str,
        fence_token: int,
    ) -> None:
        db = self.session_factory()
        try:
            DatabaseLiveStore(db).append_event(
                event,
                worker_id=worker_id,
                fence_token=fence_token,
            )
        finally:
            db.close()

    def load_run(self, run_id: str) -> LiveGameRun | None:
        db = self.session_factory()
        try:
            return DatabaseLiveStore(db).load_run(run_id)
        finally:
            db.close()

    def active_run_for_session(self, session_id: str) -> LiveGameRun | None:
        db = self.session_factory()
        try:
            return DatabaseLiveStore(db).active_run_for_session(session_id)
        finally:
            db.close()

    def events_after(self, run_id: str, *, after_id: int | None = None) -> list[LiveEvent]:
        db = self.session_factory()
        try:
            return DatabaseLiveStore(db).events_after(run_id, after_id=after_id)
        finally:
            db.close()

    def acquire_lease(
        self,
        run_id: str,
        *,
        expected_events: tuple[LiveEvent, ...],
        worker_id: str,
        heartbeat_at: str,
        lease_expires_at: str,
    ) -> RunLeaseState | None:
        db = self.session_factory()
        try:
            return DatabaseLiveStore(db).acquire_lease(
                run_id,
                expected_events=expected_events,
                worker_id=worker_id,
                heartbeat_at=heartbeat_at,
                lease_expires_at=lease_expires_at,
            )
        finally:
            db.close()

    def heartbeat_lease(
        self,
        run_id: str,
        *,
        worker_id: str,
        heartbeat_at: str,
        lease_expires_at: str,
        fence_token: int,
    ) -> RunLeaseState | None:
        db = self.session_factory()
        try:
            return DatabaseLiveStore(db).heartbeat_lease(
                run_id,
                worker_id=worker_id,
                heartbeat_at=heartbeat_at,
                lease_expires_at=lease_expires_at,
                fence_token=fence_token,
            )
        finally:
            db.close()

    def recovery_candidates(
        self,
        *,
        stale_before: str,
        now: str,
        max_attempts: int,
        limit: int,
    ) -> list[RunRecoveryCandidate]:
        db = self.session_factory()
        try:
            return DatabaseLiveStore(db).recovery_candidates(
                stale_before=stale_before,
                now=now,
                max_attempts=max_attempts,
                limit=limit,
            )
        finally:
            db.close()

    def acquire_recovery_lease(
        self,
        run_id: str,
        *,
        expected_events: tuple[LiveEvent, ...],
        worker_id: str,
        expected_attempts: int,
        max_attempts: int,
        stale_before: str,
        heartbeat_at: str,
        lease_expires_at: str,
        recovery_not_before: str,
    ) -> RunLeaseState | None:
        db = self.session_factory()
        try:
            return DatabaseLiveStore(db).acquire_recovery_lease(
                run_id,
                expected_events=expected_events,
                worker_id=worker_id,
                expected_attempts=expected_attempts,
                max_attempts=max_attempts,
                stale_before=stale_before,
                heartbeat_at=heartbeat_at,
                lease_expires_at=lease_expires_at,
                recovery_not_before=recovery_not_before,
            )
        finally:
            db.close()


class SessionVoiceStore:
    def __init__(
        self,
        *,
        session_id: str,
        session_factory: Callable[[], Session] | None = None,
    ) -> None:
        self.session_id = session_id
        self.session_factory = session_factory or SessionLocal

    def upsert_utterance(
        self,
        utterance: VoiceUtterance,
        *,
        audio_format: str,
        sample_rate: int,
        mime_type: str,
        status: str = "synthesizing",
    ) -> None:
        db = self.session_factory()
        try:
            DatabaseVoiceStore(db, session_id=self.session_id).upsert_utterance(
                utterance,
                audio_format=audio_format,
                sample_rate=sample_rate,
                mime_type=mime_type,
                status=status,
            )
        finally:
            db.close()

    def append_chunk(self, utterance_id: str, *, chunk_index: int, audio: bytes) -> None:
        db = self.session_factory()
        try:
            DatabaseVoiceStore(db, session_id=self.session_id).append_chunk(
                utterance_id,
                chunk_index=chunk_index,
                audio=audio,
            )
        finally:
            db.close()

    def complete_utterance(self, utterance_id: str, *, duration_ms: int) -> None:
        db = self.session_factory()
        try:
            DatabaseVoiceStore(db, session_id=self.session_id).complete_utterance(
                utterance_id,
                duration_ms=duration_ms,
            )
        finally:
            db.close()

    def fail_utterance(self, utterance_id: str, *, message: str) -> None:
        db = self.session_factory()
        try:
            DatabaseVoiceStore(db, session_id=self.session_id).fail_utterance(
                utterance_id,
                message=message,
            )
        finally:
            db.close()

    def update_subtitle_timings(
        self,
        utterance_id: str,
        *,
        subtitle_timings: list[dict[str, Any]],
    ) -> None:
        db = self.session_factory()
        try:
            DatabaseVoiceStore(db, session_id=self.session_id).update_subtitle_timings(
                utterance_id,
                subtitle_timings=subtitle_timings,
            )
        finally:
            db.close()

    def find_recent_utterance(
        self,
        *,
        run_id: str,
        current_event_id: int,
    ) -> dict[str, Any] | None:
        db = self.session_factory()
        try:
            return DatabaseVoiceStore(db, session_id=self.session_id).find_recent_utterance(
                run_id=run_id,
                current_event_id=current_event_id,
            )
        finally:
            db.close()

    def load_chunks(self, utterance_id: str) -> list[bytes]:
        db = self.session_factory()
        try:
            return DatabaseVoiceStore(db, session_id=self.session_id).load_chunks(utterance_id)
        finally:
            db.close()


live_registry = LiveRunRegistry(
    live_store=SessionLiveStore(),
    lease_seconds=settings.live_run_lease_seconds,
    heartbeat_seconds=settings.live_run_heartbeat_seconds,
    event_poll_seconds=settings.live_run_event_poll_seconds,
)


def get_live_registry() -> LiveRunRegistry:
    return live_registry


def get_tts_config() -> VolcengineTtsConfig:
    return VolcengineTtsConfig(
        enabled=settings.ark_tts_enabled,
        api_key=settings.ark_tts_api_key,
        resource_id=settings.ark_tts_resource_id,
        ws_url=settings.ark_tts_ws_url,
        player_speaker=settings.ark_tts_player_speaker,
        judge_speaker=settings.ark_tts_judge_speaker,
        audio_format=settings.ark_tts_audio_format,
        sample_rate=settings.ark_tts_sample_rate,
    )


def get_voice_streamer(
    registry: Annotated[LiveRunRegistry, Depends(get_live_registry)],
    config: Annotated[VolcengineTtsConfig, Depends(get_tts_config)],
) -> LiveVoiceStreamService:
    return LiveVoiceStreamService(
        registry=registry,
        config=config,
        voice_store_factory=lambda session_id: SessionVoiceStore(session_id=session_id),
        judge_voice_asset_loader=_persistent_judge_voice_loader(),
    )


def _persistent_judge_voice_loader() -> Callable[[str], StaticJudgeVoiceAsset | None]:
    cache: dict[str, StaticJudgeVoiceAsset | None] = {}

    def load(asset_id: str) -> StaticJudgeVoiceAsset | None:
        if asset_id not in cache:
            cache[asset_id] = _load_persistent_judge_voice_asset(asset_id)
        return cache[asset_id]

    return load


def _load_persistent_judge_voice_asset(asset_id: str) -> StaticJudgeVoiceAsset | None:
    db = SessionLocal()
    try:
        return _static_judge_voice_asset_from_record(db.get(JudgeVoiceAssetRecord, asset_id))
    finally:
        db.close()


def _static_judge_voice_asset_from_record(
    record: JudgeVoiceAssetRecord | None,
) -> StaticJudgeVoiceAsset | None:
    if record is None or not record.data:
        return None
    return StaticJudgeVoiceAsset(
        audio=bytes(record.data),
        audio_format=record.audio_format,
        mime_type=record.mime_type,
        sample_rate=record.sample_rate,
        subtitle_timings=(
            record.subtitle_timings if isinstance(record.subtitle_timings, list) else []
        ),
    )


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
) -> list[PlayerConfig]:
    configs = normalize_player_config_requests(
        requests,
        player_count,
        db,
    )
    configs_by_seat = {config.seat: config for config in configs}
    missing_profile_seats = [
        seat
        for seat in range(1, player_count + 1)
        if not configs_by_seat.get(seat) or not configs_by_seat[seat].profile_id
    ]
    if not missing_profile_seats:
        return sorted(configs, key=lambda config: config.seat)

    used_profile_ids = {config.profile_id for config in configs if config.profile_id is not None}
    available_profiles = [
        profile
        for profile in list_available_player_profiles(db)
        if clean_optional_string(getattr(profile, "id", None)) not in used_profile_ids
    ]
    available_count = len(used_profile_ids) + len(available_profiles)
    if len(available_profiles) < len(missing_profile_seats):
        raise HTTPException(
            status_code=422,
            detail=(
                f"Player profile library has {available_count} available players, "
                f"but {player_count} seats require virtual players"
            ),
        )

    rng = random.Random(f"{seed}:player-profiles") if seed is not None else random.Random()
    selected_profiles = rng.sample(available_profiles, len(missing_profile_seats))
    next_configs = list(configs)
    for seat, profile in zip(missing_profile_seats, selected_profiles, strict=True):
        existing = configs_by_seat.get(seat)
        overrides = existing.to_dict() if existing is not None else {"seat": seat}
        if existing is not None and existing.profile_id is None:
            overrides.pop("name", None)
        overrides["profile_id"] = str(getattr(profile, "id"))
        next_config = player_config_from_profile(
            seat=seat,
            profile=profile,
            overrides=overrides,
        )
        next_configs = [config for config in next_configs if config.seat != seat] + [next_config]

    return sorted(next_configs, key=lambda config: config.seat)


def list_available_player_profiles(
    db: Session,
) -> list[object]:
    try:
        return list(list_published_player_profiles(db))
    except RecoverableDatabaseError as exc:
        raise _profile_database_unavailable() from exc


@router.get("")
def list_games(store: Annotated[GameRecordStore, Depends(get_replay_store)]) -> dict:
    return {"sessions": store.list_sessions()}


def _catalog_item(snapshot: dict[str, object]) -> PublicRuleSetCatalogItem:
    return PublicRuleSetCatalogItem.model_validate(
        {field_name: snapshot[field_name] for field_name in PublicRuleSetCatalogItem.model_fields}
    )


def _static_rule_set_entries() -> list[tuple[CompiledRuleSet, PublicRuleSetCatalogItem]]:
    entries: list[tuple[CompiledRuleSet, PublicRuleSetCatalogItem]] = []
    for rule_set in OFFICIAL_RULE_SETS:
        revision_id, content_hash, is_default = _STATIC_RULE_REVISIONS[rule_set.id]
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
        compiled = resolve_rule_set_snapshot(snapshot)
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
    entry = next(
        (
            (compiled, item)
            for compiled, item in _static_rule_set_entries()
            if item.id == rule_set_id
        ),
        None,
    )
    if entry is None:
        raise RuleSetNotFound(rule_set_id)
    compiled, item = entry
    if expected_revision_id is not None and item.revision_id != expected_revision_id:
        raise RuleRevisionChanged(
            rule_set_id,
            expected_revision_id=expected_revision_id,
            current_revision_id=item.revision_id,
        )
    return compiled


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
        _rollback_quietly(db)
        raise public_problem(
            request,
            status_code=503,
            code="rule_set_store_unavailable",
            detail="Rule set catalog is temporarily unavailable.",
        ) from exc
    return PublicRuleSetCatalogResponse(rule_sets=items)


@router.get("/model-options")
def list_model_options() -> dict:
    return {"models": configured_model_options()}


@router.post("/runs", status_code=201)
def create_game_run(
    request_body: CreateGameRunRequest,
    request: Request,
    registry: Annotated[LiveRunRegistry, Depends(get_live_registry)],
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    run: LiveGameRun | None = None
    staged = False
    try:
        compiled = _resolve_selected_rule_set(
            db,
            rule_set_id=request_body.rule_set_id,
            expected_revision_id=request_body.expected_rule_revision_id,
        )
        player_configs = complete_player_configs_from_library(
            requests=request_body.player_configs,
            player_count=compiled.rule_set.player_count,
            seed=request_body.seed,
            db=db,
        )
        try:
            validate_unique_effective_player_names(
                default_names=choose_player_names(
                    request_body.seed,
                    player_count=compiled.rule_set.player_count,
                ),
                player_configs=player_configs,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        run = registry.prepare_run(
            session_id=new_session_id(),
            villager_model=request_body.villager_model,
            werewolf_model=request_body.werewolf_model,
            seed=request_body.seed,
            max_rounds=request_body.max_rounds,
            rule_set_id=compiled.rule_set.id,
            rule_set_revision_id=compiled.revision_id,
            rule_set_revision_no=compiled.revision_no,
            rule_set_content_hash=compiled.content_hash,
            rule_set=compiled.snapshot,
            player_configs=player_configs,
            lineup_quality_warnings=lineup_quality_warnings(player_configs),
        )
        DatabaseLiveStore(db).stage_new_run(run)
        staged = True
        db.commit()
    except RuleRevisionChanged as exc:
        try:
            current_item = _current_rule_set_catalog_item(db, exc.rule_set_id)
        except Exception as catalog_exc:
            _rollback_quietly(db)
            raise public_problem(
                request,
                status_code=503,
                code="rule_set_store_unavailable",
                detail="Rule set catalog is temporarily unavailable.",
            ) from catalog_exc
        _rollback_quietly(db)
        raise public_problem(
            request,
            status_code=409,
            code="rule_revision_changed",
            detail="The selected rule revision has changed.",
            extensions={"current_rule_set": current_item.model_dump()},
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
        if staged and run is not None:
            _attempt_committed_run_compensation(db, run)
        raise public_problem(
            request,
            status_code=503,
            code="rule_set_store_unavailable",
            detail="Rule set data is temporarily unavailable.",
        ) from exc

    try:
        registry.attach_prepared_run(run)
        _start_game_thread(run=run, compiled=compiled, registry=registry)
    except Exception as exc:
        _recover_after_run_start_failure(db=db, registry=registry, run=run)
        raise public_problem(
            request,
            status_code=503,
            code="game_run_start_unavailable",
            detail="The game worker could not be started.",
        ) from exc

    if request_body.expected_rule_revision_id is None:
        logger.info(
            "Created a live run through the legacy revision compatibility path",
            extra={
                "event_code": "legacy_rule_create",
                "rule_set_id": compiled.rule_set.id,
                "rule_set_revision_no": compiled.revision_no,
                "rule_set_schema_version": compiled.schema_version,
                "rule_set_content_hash_prefix": compiled.content_hash[:12],
            },
        )
    return run.to_summary()


def _rollback_quietly(db: Session) -> None:
    try:
        db.rollback()
    except Exception:
        return


def _compensate_committed_run(db: Session, run: LiveGameRun) -> bool:
    record = db.scalar(
        select(LiveRunRecord)
        .where(
            LiveRunRecord.run_id == run.run_id,
            LiveRunRecord.session_id == run.session_id,
            LiveRunRecord.status == "queued",
            LiveRunRecord.worker_id == run.worker_id,
            LiveRunRecord.fence_token == 0,
            LiveRunRecord.control_version == 0,
            LiveRunRecord.stop_requested_at.is_(None),
            LiveRunRecord.worker_heartbeat_at.is_(None),
            LiveRunRecord.lease_expires_at.is_(None),
        )
        .with_for_update()
    )
    if record is None:
        db.rollback()
        return False
    if len(run.events) != 1:
        db.rollback()
        return False
    expected_event = run.events[0]
    events = tuple(
        db.scalars(
            select(LiveEventRecord)
            .where(LiveEventRecord.run_id == run.run_id)
            .order_by(LiveEventRecord.event_id.asc())
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    )
    if len(events) != 1 or not _stored_event_matches(events[0], expected_event):
        db.rollback()
        return False
    db.execute(delete(LiveEventRecord).where(LiveEventRecord.run_id == run.run_id))
    db.delete(record)
    db.commit()
    return True


def _stored_event_matches(record: LiveEventRecord, expected: LiveEvent) -> bool:
    return stored_event_matches(record, expected)


def _attempt_committed_run_compensation(db: Session, run: LiveGameRun) -> bool:
    try:
        return _compensate_committed_run(db, run)
    except Exception:
        _rollback_quietly(db)
        return False


def _recover_after_run_start_failure(
    *,
    db: Session,
    registry: LiveRunRegistry,
    run: LiveGameRun,
) -> None:
    registry.detach_prepared_run(run)
    if _attempt_committed_run_compensation(db, run):
        return
    logger.error(
        "Live run start failed; durable queued run retained for recovery",
        extra={
            "event_code": "live_run_start_recovery_required",
            "rule_set_id": run.rule_set_id,
            "rule_set_revision_no": run.rule_set_revision_no,
        },
    )


def _profile_database_unavailable() -> HTTPException:
    return HTTPException(status_code=503, detail=PLAYER_PROFILE_DATABASE_UNAVAILABLE)


@router.get("/runs/{run_id}")
def get_game_run(
    run_id: str,
    registry: Annotated[LiveRunRegistry, Depends(get_live_registry)],
) -> dict:
    run = registry.try_get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Game run not found")
    return run.to_summary()


@router.get("/runs/{run_id}/events")
def stream_game_run_events(
    run_id: str,
    registry: Annotated[LiveRunRegistry, Depends(get_live_registry)],
    after_id: Annotated[int | None, Query(ge=0)] = None,
    last_event_id: Annotated[str | None, Header(alias="Last-Event-ID")] = None,
) -> StreamingResponse:
    if registry.try_get_run(run_id) is None:
        raise HTTPException(status_code=404, detail="Game run not found")

    return StreamingResponse(
        _event_stream(
            registry,
            run_id,
            after_id=_resolve_event_resume_id(after_id, last_event_id),
        ),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache"},
    )


@router.websocket("/runs/{run_id}/voice-stream")
async def stream_game_run_voice(
    websocket: WebSocket,
    run_id: str,
    registry: Annotated[LiveRunRegistry, Depends(get_live_registry)],
    streamer: Annotated[LiveVoiceStreamService, Depends(get_voice_streamer)],
    current_event_id: Annotated[int | None, Query(ge=0)] = None,
    playback_ack: Annotated[bool, Query()] = False,
) -> None:
    await websocket.accept()
    if registry.try_get_run(run_id) is None:
        await websocket.send_json(
            {
                "type": "voice_unavailable",
                "reason": "run_not_found",
                "message": "对局不存在或已失效，请返回大厅重新开始。",
            }
        )
        await websocket.close()
        return
    await streamer.stream_run(
        run_id,
        websocket,
        current_event_id=current_event_id,
        playback_ack_required=playback_ack,
    )


@router.post("/{session_id}/resume", status_code=201)
def resume_game_run(
    session_id: Annotated[
        str,
        Path(pattern=SESSION_ID_RE),
    ],
    store: Annotated[GameRecordStore, Depends(get_replay_store)],
    registry: Annotated[LiveRunRegistry, Depends(get_live_registry)],
    response: Response,
) -> dict:
    run, created = start_resume_game_run(
        session_id=session_id,
        store=store,
        registry=registry,
    )
    if not created:
        response.status_code = 200
        return run.to_summary()
    return registry.get_run(run.run_id).to_summary()


def start_resume_game_run(
    *,
    session_id: str,
    store: GameRecordStore,
    registry: LiveRunRegistry,
) -> tuple[LiveGameRun, bool]:
    active_run = registry.try_get_active_run_for_session(session_id)
    try:
        checkpoint = store.load_resume_checkpoint(session_id)
    except ResumeCheckpointError as exc:
        if active_run is not None:
            return active_run, False
        raise HTTPException(status_code=404, detail="Resume checkpoint not found") from exc
    if active_run is not None:
        claimed_run = registry.try_claim_stale_run(active_run.run_id)
        if claimed_run is None:
            return active_run, False
        active_run = claimed_run
    run_params = checkpoint.get("run_params", {})
    if not isinstance(run_params, dict):
        raise HTTPException(status_code=422, detail="Resume checkpoint is invalid")
    rule_set_id = str(run_params.get("rule_set_id") or DEFAULT_RULE_SET_ID)
    try:
        rule_set = get_rule_set(rule_set_id)
    except KeyError as exc:
        raise HTTPException(status_code=422, detail=f"Unknown rule set: {rule_set_id}") from exc
    max_rounds = int(run_params.get("max_rounds") or 8)
    seed = run_params.get("seed")
    try:
        checkpoint_player_configs = player_configs_from_serialized(run_params.get("player_configs"))
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail="Resume checkpoint is invalid") from exc
    if active_run is None:
        run, created = registry.get_or_create_active_run(
            session_id=session_id,
            villager_model=str(run_params.get("villager_model") or default_model_name()),
            werewolf_model=str(run_params.get("werewolf_model") or default_model_name()),
            seed=seed if isinstance(seed, int) else None,
            max_rounds=max_rounds,
            rule_set_id=rule_set.id,
            rule_set=rule_set_snapshot(rule_set),
            player_configs=checkpoint_player_configs,
        )
        if not created:
            return run, False
    else:
        run = active_run
    thread = threading.Thread(
        target=_resume_game_in_background,
        kwargs={"run_id": run.run_id, "registry": registry, "session_id": session_id},
        daemon=True,
    )
    thread.start()
    return run, True


@router.get("/{session_id}/playback")
def get_game_playback(
    session_id: Annotated[
        str,
        Path(pattern=SESSION_ID_RE),
    ],
    store: Annotated[GameRecordStore, Depends(get_replay_store)],
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    try:
        playback = build_replay_playback(store.load_session(session_id))
    except ReplayNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Game session not found") from exc

    try:
        persisted_events = DatabaseLiveStore(db).playback_events_for_session(session_id)
    except RecoverableDatabaseError:
        persisted_events = []

    saved_voices: list[dict[str, Any]] = []
    if persisted_events:
        playback["events"] = persisted_events
        try:
            saved_voices = DatabaseVoiceStore(
                db,
                session_id=session_id,
            ).list_playback_voices()
        except RecoverableDatabaseError:
            saved_voices = []

    static_judge_voices = build_static_judge_playback_voices(
        playback["events"],
        asset_dir=DEFAULT_JUDGE_VOICE_ASSET_DIR,
        asset_loader=lambda asset_id: _static_judge_voice_asset_from_record(
            db.get(JudgeVoiceAssetRecord, asset_id)
        ),
    )
    playback["voices"] = _merge_playback_voices(saved_voices, static_judge_voices)
    return playback


def _merge_playback_voices(
    saved_voices: list[dict[str, Any]],
    fallback_voices: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    merged = list(saved_voices)
    saved_keys = {
        (voice.get("source_event_id"), voice.get("speaker_kind")) for voice in saved_voices
    }
    for voice in fallback_voices:
        key = (voice.get("source_event_id"), voice.get("speaker_kind"))
        if key in saved_keys:
            continue
        saved_keys.add(key)
        merged.append(voice)
    return sorted(
        merged,
        key=lambda voice: (
            voice.get("source_event_id") if isinstance(voice.get("source_event_id"), int) else 0,
            voice.get("utterance_id") if isinstance(voice.get("utterance_id"), str) else "",
        ),
    )


@router.get("/{session_id}")
def get_game(
    session_id: Annotated[
        str,
        Path(pattern=SESSION_ID_RE),
    ],
    store: Annotated[GameRecordStore, Depends(get_replay_store)],
) -> dict:
    try:
        return store.load_session(session_id)
    except ReplayNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Game session not found") from exc


def _start_game_thread(
    *,
    run: LiveGameRun,
    compiled: CompiledRuleSet,
    registry: LiveRunRegistry,
) -> None:
    thread = threading.Thread(
        target=_run_game_in_background,
        kwargs={
            "run_id": run.run_id,
            "registry": registry,
            "session_id": run.session_id,
            "villager_model": run.villager_model,
            "werewolf_model": run.werewolf_model,
            "seed": run.seed,
            "max_rounds": run.max_rounds,
            "rule_set_id": compiled.rule_set.id,
            "compiled": compiled,
            "player_configs": player_configs_from_serialized(run.player_configs),
        },
        daemon=True,
    )
    thread.start()


def _run_game_in_background(
    *,
    run_id: str,
    registry: LiveRunRegistry,
    session_id: str,
    villager_model: str,
    werewolf_model: str,
    seed: int | None,
    max_rounds: int,
    rule_set_id: str | None = None,
    compiled: CompiledRuleSet | None = None,
    player_configs: list[PlayerConfig] | None = None,
) -> None:
    selected_rule_set_id = compiled.rule_set.id if compiled is not None else rule_set_id
    if selected_rule_set_id is None:
        raise ValueError("A compiled rule set or rule_set_id is required")
    try:
        registry.mark_running(run_id)
    except GameRunCanceled:
        registry.mark_canceled(run_id)
        return
    except RunLeaseUnavailable:
        return
    db = SessionLocal()
    try:
        worker_id, fence_token = registry.write_fence(run_id)
        with registry.maintain_lease(run_id):
            result = run_game(
                record_store=DatabaseReplayStore(
                    db,
                    run_id=run_id,
                    worker_id=worker_id,
                    fence_token=fence_token,
                ),
                villager_model=villager_model,
                werewolf_model=werewolf_model,
                seed=seed,
                rule_set_id=selected_rule_set_id,
                max_rounds=max_rounds,
                session_id=session_id,
                event_sink=EventSink(registry, run_id, fence_token=fence_token),
                player_configs=player_configs,
            )
    except GameRunCanceled:
        registry.mark_canceled(run_id)
        return
    except (RunLeaseUnavailable, ReplayWriteFencedError):
        return
    except GameRunError as exc:
        registry.mark_failed(run_id, error=str(exc))
        return
    except Exception as exc:
        registry.mark_failed(run_id, error=str(exc))
        return
    finally:
        db.close()

    registry.mark_completed(run_id, winner=result.winner)


def _resume_game_in_background(
    *,
    run_id: str,
    registry: LiveRunRegistry,
    session_id: str,
) -> None:
    try:
        registry.mark_running(run_id)
    except GameRunCanceled:
        registry.mark_canceled(run_id)
        return
    except RunLeaseUnavailable:
        return
    db = SessionLocal()
    try:
        worker_id, fence_token = registry.write_fence(run_id)
        with registry.maintain_lease(run_id):
            result = resume_game(
                session_id=session_id,
                record_store=DatabaseReplayStore(
                    db,
                    run_id=run_id,
                    worker_id=worker_id,
                    fence_token=fence_token,
                ),
                event_sink=EventSink(registry, run_id, fence_token=fence_token),
            )
    except GameRunCanceled:
        registry.mark_canceled(run_id)
        return
    except (RunLeaseUnavailable, ReplayWriteFencedError):
        return
    except GameRunError as exc:
        registry.mark_failed(run_id, error=str(exc))
        return
    except Exception as exc:
        registry.mark_failed(run_id, error=str(exc))
        return
    finally:
        db.close()

    registry.mark_completed(run_id, winner=result.winner)


def _event_stream(
    registry: LiveRunRegistry,
    run_id: str,
    *,
    after_id: int | None = None,
) -> Iterator[str]:
    last_event_id = after_id
    for event in registry.events_after(run_id, after_id=after_id):
        last_event_id = event.id
        yield format_sse(event)
        if _is_terminal_event(event):
            return

    subscriber: queue.Queue[LiveEvent] | None = None
    try:
        subscriber = registry.subscribe(run_id, after_id=last_event_id)
        while True:
            try:
                event = subscriber.get(timeout=15)
            except queue.Empty:
                yield ": heartbeat\n\n"
                continue

            yield format_sse(event)
            if _is_terminal_event(event):
                return
    finally:
        if subscriber is not None:
            registry.unsubscribe(run_id, subscriber)


def _is_terminal_event(event: LiveEvent) -> bool:
    return event.type in {"game_completed", "game_failed", "game_canceled"}


def _resolve_event_resume_id(
    after_id: int | None,
    last_event_id: str | None,
) -> int | None:
    if after_id is not None:
        return after_id
    if last_event_id is None:
        return None
    try:
        return int(last_event_id)
    except ValueError:
        return None
