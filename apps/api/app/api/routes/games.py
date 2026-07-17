from collections.abc import Callable
import json
import logging
import queue
import threading
import time
from typing import Annotated, Any, Iterator, Literal

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

from app.api.public.dependencies import (
    PublicPrincipal,
    get_current_public_principal,
    get_current_public_websocket_principal,
    public_problem,
)
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
from app.rule_sets.telemetry import (
    record_legacy_rule_create,
    record_rule_checkpoint_failure,
    record_rule_create_conflict,
    record_rule_snapshot_failure,
)
from app.werewolf.checkpoint import (
    ResumeCheckpointError,
    report_resume_checkpoint_error,
    resolved_rule_set_from_checkpoint,
)
from app.werewolf.config import choose_player_names
from app.werewolf.debate_realism import lineup_quality_warnings
from app.werewolf.lineup_quality import (
    LineupQualityPolicyV1,
    evaluate_lineup_quality,
    plan_diverse_lineup,
)
from app.werewolf.live import (
    EventSink,
    GameRunCanceled,
    LiveEvent,
    LiveGameRun,
    ProjectedLiveEvent,
    LiveRunRegistry,
    RunActivationExpectedEvent,
    RunActivationExpectedState,
    RunLeaseState,
    RunLeaseUnavailable,
    RunRecoveryCandidate,
    RunRuleSetExpectedState,
    RunRuleSetMismatch,
    format_sse,
    live_run_matches_compiled_rule_set,
)
from app.werewolf.live_store import (
    DatabaseLiveStore,
    stored_event_matches,
)
from app.werewolf.privacy_projection import ProjectionAudience, project_live_event
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
from app.werewolf.replay_playback import (
    PRIVATE_ROUND_MEMORY_ACTION,
    build_public_game_session,
    build_replay_playback,
    filter_public_playback_voices,
    private_round_memory_event_ids,
    project_playback_events,
)
from app.werewolf.rules import (
    DEFAULT_RULE_SET_ID,
    OFFICIAL_RULE_SETS,
    role_summary,
    rule_set_snapshot,
)
from app.werewolf.judge_voice_assets import DEFAULT_JUDGE_VOICE_ASSET_DIR
from app.werewolf.runner import GameRunError, new_session_id, resume_game, run_game
from app.werewolf.voice import VoiceUtterance
from app.werewolf.voice_materializer import LIVE_VOICE_MATERIALIZER_WORKER_TYPE
from app.werewolf.voice_stream import (
    LiveVoiceStreamService,
    StaticJudgeVoiceAsset,
    build_static_judge_playback_voices,
    build_voice_playback_coverage,
)
from app.werewolf.voice_store import DatabaseVoiceStore
from app.werewolf.volcengine_tts import VolcengineTtsConfig
from app.werewolf.worker_telemetry import runtime_worker_is_alive


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
    lineup_quality_policy_version: int = Field(default=1, ge=1, le=1)
    allow_lineup_quality_warnings: bool = False


class LineupPreviewRequest(BaseModel):
    rule_set_id: str = DEFAULT_RULE_SET_ID
    expected_rule_revision_id: str | None = Field(default=None, max_length=36)
    seed: int | None = None
    player_configs: list[CreatePlayerConfigRequest] = Field(default_factory=list)
    locked_seats: list[int] = Field(default_factory=list, max_length=24)
    repair_scope: Literal["empty_only", "unlocked_all"] = "empty_only"
    lineup_quality_policy_version: int = Field(default=1, ge=1, le=1)


def get_replay_store(db: Annotated[Session, Depends(get_db)]) -> DatabaseReplayStore:
    return DatabaseReplayStore(db)


def live_voice_materializer_is_available(db: Session) -> bool:
    return not settings.ark_tts_enabled or runtime_worker_is_alive(
        db,
        worker_type=LIVE_VOICE_MATERIALIZER_WORKER_TYPE,
        max_age_seconds=settings.live_voice_materializer_probe_max_age_seconds,
    )


def _require_live_voice_materializer(db: Session, request: Request) -> None:
    if live_voice_materializer_is_available(db):
        return
    raise public_problem(
        request,
        status_code=503,
        code="live_voice_materializer_unavailable",
        detail="Voice persistence is unavailable; retry after the backend is ready.",
    )


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
        expected_events: tuple[LiveEvent | RunActivationExpectedEvent, ...],
        expected_rule_set: RunRuleSetExpectedState,
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
                expected_rule_set=expected_rule_set,
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

    def fail_run(
        self,
        run_id: str,
        *,
        expected_events: tuple[LiveEvent | RunActivationExpectedEvent, ...],
        expected_rule_set: RunRuleSetExpectedState,
        expected_status: str,
        failure: LiveEvent,
        worker_id: str,
        fence_token: int,
        completed_at: str,
        error: str,
    ) -> None:
        db = self.session_factory()
        try:
            DatabaseLiveStore(db).fail_run(
                run_id,
                expected_events=expected_events,
                expected_rule_set=expected_rule_set,
                expected_status=expected_status,
                failure=failure,
                worker_id=worker_id,
                fence_token=fence_token,
                completed_at=completed_at,
                error=error,
            )
        finally:
            db.close()

    def failure_was_committed(
        self,
        expected_state: RunActivationExpectedState,
    ) -> bool:
        db = self.session_factory()
        try:
            return DatabaseLiveStore(db).failure_was_committed(expected_state)
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

    def latest_run_for_session(self, session_id: str) -> LiveGameRun | None:
        db = self.session_factory()
        try:
            return DatabaseLiveStore(db).latest_run_for_session(session_id)
        finally:
            db.close()

    def events_after(self, run_id: str, *, after_id: int | None = None) -> list[LiveEvent]:
        db = self.session_factory()
        try:
            return DatabaseLiveStore(db).events_after(run_id, after_id=after_id)
        finally:
            db.close()

    def projected_events_after(
        self,
        run_id: str,
        *,
        audience: ProjectionAudience,
        after_id: int | None = None,
    ) -> list[ProjectedLiveEvent]:
        db = self.session_factory()
        try:
            return DatabaseLiveStore(db).projected_events_after(
                run_id,
                audience=audience,
                after_id=after_id,
            )
        finally:
            db.close()

    def acquire_lease(
        self,
        run_id: str,
        *,
        expected_events: tuple[LiveEvent | RunActivationExpectedEvent, ...],
        expected_rule_set: RunRuleSetExpectedState,
        worker_id: str,
        heartbeat_at: str,
        lease_expires_at: str,
    ) -> RunLeaseState | None:
        db = self.session_factory()
        try:
            return DatabaseLiveStore(db).acquire_lease(
                run_id,
                expected_events=expected_events,
                expected_rule_set=expected_rule_set,
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
        expected_rule_set: RunRuleSetExpectedState,
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
                expected_rule_set=expected_rule_set,
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

    def claim_streamed_utterance(self, utterance: VoiceUtterance) -> bool:
        db = self.session_factory()
        try:
            return DatabaseVoiceStore(
                db,
                session_id=self.session_id,
            ).claim_streamed_utterance(
                utterance,
                lease_seconds=settings.live_voice_materializer_lease_seconds,
            )
        finally:
            db.close()

    def release_streamed_utterance(
        self,
        utterance: VoiceUtterance,
        *,
        error_type: str,
    ) -> None:
        db = self.session_factory()
        try:
            DatabaseVoiceStore(
                db,
                session_id=self.session_id,
            ).release_streamed_utterance(
                utterance,
                error_type=error_type,
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
                satisfy_materialization_jobs=True,
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
        audience: str = "player_public",
    ) -> dict[str, Any] | None:
        db = self.session_factory()
        try:
            return DatabaseVoiceStore(db, session_id=self.session_id).find_recent_utterance(
                run_id=run_id,
                current_event_id=current_event_id,
                audience=audience,
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
        persist_streamed_voices=True,
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
    return plan_diverse_lineup(
        configs,
        candidates,
        player_count=player_count,
        seed=seed,
        repair_scope=repair_scope,
        locked_seats=locked_seats,
        policy=policy or _lineup_quality_policy(),
    )


def _lineup_quality_policy() -> LineupQualityPolicyV1:
    return LineupQualityPolicyV1(mode=settings.werewolf_lineup_quality_mode)


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


@router.get("/model-options")
def list_model_options() -> dict:
    return {"models": configured_model_options()}


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
        _require_live_voice_materializer(db, request)
        compiled = _resolve_selected_rule_set(
            db,
            rule_set_id=request_body.rule_set_id,
            expected_revision_id=request_body.expected_rule_revision_id,
        )
        policy = _lineup_quality_policy()
        player_configs = complete_player_configs_from_library(
            requests=request_body.player_configs,
            player_count=compiled.rule_set.player_count,
            seed=request_body.seed,
            db=db,
            policy=policy,
        )
        requested_profiles = {
            item.seat: clean_optional_string(item.profile_id)
            for item in request_body.player_configs
        }
        resolved_profiles = {config.seat: config.profile_id for config in player_configs}
        lineup_report = evaluate_lineup_quality(
            player_configs,
            player_count=compiled.rule_set.player_count,
            policy=policy,
            was_repaired=requested_profiles != resolved_profiles,
        )
        manual_complete = len(requested_profiles) == compiled.rule_set.player_count and all(
            requested_profiles.values()
        )
        override_allowed = (
            policy.mode == "repair"
            and manual_complete
            and request_body.allow_lineup_quality_warnings
        )
        if lineup_report.is_blocked and policy.mode != "observe" and not override_allowed:
            raise public_problem(
                request,
                status_code=422,
                code="lineup_quality_gate_failed",
                detail="The selected lineup does not satisfy the active quality policy.",
                extensions={"lineup_quality_report": lineup_report.to_dict()},
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
            lineup_quality_report=lineup_report.to_dict(),
        )
        DatabaseLiveStore(db).stage_new_run(run)
        staged = True
        db.commit()
    except RuleRevisionChanged as exc:
        try:
            current_item = _current_rule_set_catalog_item(db, exc.rule_set_id)
        except Exception as catalog_exc:
            record_rule_create_conflict(exc.rule_set_id, None)
            if isinstance(catalog_exc, RuleSetCatalogCorrupt):
                record_rule_snapshot_failure(catalog_exc.reason)
            _rollback_quietly(db)
            raise public_problem(
                request,
                status_code=503,
                code="rule_set_store_unavailable",
                detail="Rule set catalog is temporarily unavailable.",
            ) from catalog_exc
        record_rule_create_conflict(exc.rule_set_id, current_item.revision_no)
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
    except RuleSetCatalogCorrupt as exc:
        record_rule_snapshot_failure(exc.reason)
        _rollback_quietly(db)
        raise public_problem(
            request,
            status_code=503,
            code="rule_set_store_unavailable",
            detail="Rule set data is temporarily unavailable.",
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
        record_legacy_rule_create(compiled.rule_set.id, compiled.revision_no)
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
    summary = run.to_summary()
    if summary.get("error"):
        summary["error"] = "对局异常中断。"
    return summary


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
            audience="player_public",
        ),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache"},
    )


@router.get("/runs/{run_id}/god-view/events")
def stream_game_run_god_view_events(
    run_id: str,
    registry: Annotated[LiveRunRegistry, Depends(get_live_registry)],
    _principal: Annotated[PublicPrincipal, Depends(get_current_public_principal)],
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
            audience="spectator_god_view",
        ),
        media_type="text/event-stream",
        headers={"Cache-Control": "private, no-store"},
    )


@router.get("/runs/{run_id}/timeline-events")
def stream_game_session_timeline_events(
    run_id: str,
    db: Annotated[Session, Depends(get_db)],
    after_id: Annotated[int | None, Query(ge=0)] = None,
    last_event_id: Annotated[str | None, Header(alias="Last-Event-ID")] = None,
) -> StreamingResponse:
    if db.get(LiveRunRecord, run_id) is None:
        raise HTTPException(status_code=404, detail="Game run not found")
    return StreamingResponse(
        _timeline_event_stream(
            db,
            run_id,
            after_id=_resolve_event_resume_id(after_id, last_event_id),
            audience="player_public",
        ),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache"},
    )


@router.get("/runs/{run_id}/god-view/timeline-events")
def stream_game_session_god_view_timeline_events(
    run_id: str,
    db: Annotated[Session, Depends(get_db)],
    _principal: Annotated[PublicPrincipal, Depends(get_current_public_principal)],
    after_id: Annotated[int | None, Query(ge=0)] = None,
    last_event_id: Annotated[str | None, Header(alias="Last-Event-ID")] = None,
) -> StreamingResponse:
    if db.get(LiveRunRecord, run_id) is None:
        raise HTTPException(status_code=404, detail="Game run not found")
    return StreamingResponse(
        _timeline_event_stream(
            db,
            run_id,
            after_id=_resolve_event_resume_id(after_id, last_event_id),
            audience="spectator_god_view",
        ),
        media_type="text/event-stream",
        headers={"Cache-Control": "private, no-store"},
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


@router.websocket("/runs/{run_id}/god-view/voice-stream")
async def stream_game_run_god_view_voice(
    websocket: WebSocket,
    run_id: str,
    registry: Annotated[LiveRunRegistry, Depends(get_live_registry)],
    streamer: Annotated[LiveVoiceStreamService, Depends(get_voice_streamer)],
    _principal: Annotated[
        PublicPrincipal,
        Depends(get_current_public_websocket_principal),
    ],
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
        audience="spectator_god_view",
    )


@router.post("/{session_id}/resume", status_code=201)
def resume_game_run(
    session_id: Annotated[
        str,
        Path(pattern=SESSION_ID_RE),
    ],
    store: Annotated[GameRecordStore, Depends(get_replay_store)],
    registry: Annotated[LiveRunRegistry, Depends(get_live_registry)],
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    response: Response,
) -> dict:
    _require_live_voice_materializer(db, request)
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
    try:
        checkpoint = store.load_resume_checkpoint(session_id)
    except ResumeCheckpointError as exc:
        report_resume_checkpoint_error(exc)
        if exc.reason == "missing":
            raise HTTPException(status_code=404, detail="Resume checkpoint not found") from exc
        raise HTTPException(status_code=422, detail="Resume checkpoint is invalid") from exc
    try:
        compiled = resolved_rule_set_from_checkpoint(checkpoint)
    except ResumeCheckpointError as exc:
        report_resume_checkpoint_error(exc)
        raise HTTPException(status_code=422, detail="Resume checkpoint is invalid") from exc

    run_params = checkpoint.get("run_params")
    if not isinstance(run_params, dict):
        raise _invalid_resume_checkpoint("invalid_structure")
    max_rounds = run_params.get("max_rounds")
    seed = run_params.get("seed")
    villager_model = run_params.get("villager_model")
    werewolf_model = run_params.get("werewolf_model")
    if (
        type(max_rounds) is not int
        or max_rounds <= 0
        or (seed is not None and type(seed) is not int)
        or type(villager_model) is not str
        or not villager_model
        or type(werewolf_model) is not str
        or not werewolf_model
    ):
        raise _invalid_resume_checkpoint("invalid_structure")
    try:
        checkpoint_player_configs = player_configs_from_serialized(run_params.get("player_configs"))
    except (KeyError, TypeError, ValueError) as exc:
        raise _invalid_resume_checkpoint("invalid_structure") from exc

    active_run = registry.try_get_active_run_for_session(session_id)
    if active_run is not None:
        _require_live_run_matches_checkpoint(active_run, compiled)
        try:
            claimed_run = registry.try_claim_stale_run(active_run.run_id)
        except RunRuleSetMismatch as exc:
            raise _invalid_resume_checkpoint("rule_metadata_mismatch") from exc
        if claimed_run is None:
            return active_run, False
        active_run = claimed_run
        _require_live_run_matches_checkpoint(active_run, compiled)
    if active_run is None:
        parent_run = registry.latest_run_for_session(session_id)
        resume_from_round = int(checkpoint.get("round_number") or 1)
        run, created = registry.get_or_create_active_run(
            session_id=session_id,
            villager_model=villager_model,
            werewolf_model=werewolf_model,
            seed=seed,
            max_rounds=max_rounds,
            parent_run_id=parent_run.run_id if parent_run is not None else None,
            resume_from_round=resume_from_round if parent_run is not None else None,
            attempt_no=(parent_run.attempt_no + 1) if parent_run is not None else 1,
            rule_set_id=compiled.rule_set.id,
            rule_set_revision_id=compiled.revision_id,
            rule_set_revision_no=compiled.revision_no,
            rule_set_content_hash=compiled.content_hash,
            rule_set=compiled.snapshot,
            player_configs=checkpoint_player_configs,
        )
        _require_live_run_matches_checkpoint(run, compiled)
        if not created:
            return run, False
    else:
        run = active_run
    thread = threading.Thread(
        target=_resume_game_in_background,
        kwargs={
            "run_id": run.run_id,
            "registry": registry,
            "session_id": session_id,
            "expected_compiled_rule_set": compiled,
        },
        daemon=True,
    )
    thread.start()
    return run, True


def _require_live_run_matches_checkpoint(
    run: LiveGameRun,
    compiled: CompiledRuleSet,
) -> None:
    if not live_run_matches_compiled_rule_set(run, compiled):
        raise _invalid_resume_checkpoint("rule_metadata_mismatch")


def _invalid_resume_checkpoint(reason: str) -> HTTPException:
    record_rule_checkpoint_failure(reason)
    return HTTPException(status_code=422, detail="Resume checkpoint is invalid")


@router.get("/{session_id}/playback")
def get_game_playback(
    session_id: Annotated[
        str,
        Path(pattern=SESSION_ID_RE),
    ],
    store: Annotated[GameRecordStore, Depends(get_replay_store)],
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    return _get_game_playback(
        session_id,
        store=store,
        db=db,
        audience="player_public",
    )


@router.get("/{session_id}/god-view/playback")
def get_game_god_view_playback(
    session_id: Annotated[
        str,
        Path(pattern=SESSION_ID_RE),
    ],
    store: Annotated[GameRecordStore, Depends(get_replay_store)],
    db: Annotated[Session, Depends(get_db)],
    _principal: Annotated[PublicPrincipal, Depends(get_current_public_principal)],
) -> dict:
    return _get_game_playback(
        session_id,
        store=store,
        db=db,
        audience="spectator_god_view",
    )


@router.get("/{session_id}/playback/voices/{utterance_id}")
def get_game_playback_voice(
    session_id: Annotated[str, Path(pattern=SESSION_ID_RE)],
    utterance_id: Annotated[str, Path(min_length=1, max_length=128)],
    store: Annotated[GameRecordStore, Depends(get_replay_store)],
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    return _get_game_playback_voice(
        session_id,
        utterance_id,
        store=store,
        db=db,
        audience="player_public",
    )


@router.get("/{session_id}/god-view/playback/voices/{utterance_id}")
def get_game_god_view_playback_voice(
    session_id: Annotated[str, Path(pattern=SESSION_ID_RE)],
    utterance_id: Annotated[str, Path(min_length=1, max_length=128)],
    store: Annotated[GameRecordStore, Depends(get_replay_store)],
    db: Annotated[Session, Depends(get_db)],
    _principal: Annotated[PublicPrincipal, Depends(get_current_public_principal)],
) -> dict:
    return _get_game_playback_voice(
        session_id,
        utterance_id,
        store=store,
        db=db,
        audience="spectator_god_view",
    )


def _get_game_playback_voice(
    session_id: str,
    utterance_id: str,
    *,
    store: GameRecordStore,
    db: Session,
    audience: ProjectionAudience,
) -> dict:
    playback = _get_game_playback(
        session_id,
        store=store,
        db=db,
        audience=audience,
    )
    allowed_voice = next(
        (
            voice
            for voice in playback.get("voices", [])
            if voice.get("utterance_id") == utterance_id
        ),
        None,
    )
    if not isinstance(allowed_voice, dict):
        raise HTTPException(status_code=404, detail="Playback voice not found")
    inline_chunks = allowed_voice.get("chunks")
    if isinstance(inline_chunks, list) and inline_chunks:
        return allowed_voice

    try:
        allowed_audiences = (
            frozenset({"player_public", "spectator_god_view"})
            if audience == "spectator_god_view"
            else frozenset({"player_public"})
        )
        stored_voice = DatabaseVoiceStore(
            db,
            session_id=session_id,
        ).load_playback_voice(
            utterance_id,
            excluded_actions=frozenset({PRIVATE_ROUND_MEMORY_ACTION}),
            allowed_audiences=allowed_audiences,
        )
    except RecoverableDatabaseError:
        stored_voice = None
    if stored_voice is None:
        raise HTTPException(status_code=404, detail="Playback voice not found")
    return {**allowed_voice, "chunks": stored_voice["chunks"]}


def _get_game_playback(
    session_id: str,
    *,
    store: GameRecordStore,
    db: Session,
    audience: ProjectionAudience,
) -> dict:
    try:
        playback = build_replay_playback(store.load_session(session_id))
    except ReplayNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Game session not found") from exc

    try:
        persisted_events = DatabaseLiveStore(db).playback_events_for_session(
            session_id,
            audience=audience,
        )
    except RecoverableDatabaseError:
        persisted_events = []

    saved_voices: list[dict[str, Any]] = []
    materialization_lag_ms: int | None = None
    if persisted_events:
        private_event_ids = private_round_memory_event_ids(persisted_events)
        playback["events"] = persisted_events
        try:
            voice_store = DatabaseVoiceStore(
                db,
                session_id=session_id,
            )
            allowed_audiences = (
                frozenset({"player_public", "spectator_god_view"})
                if audience == "spectator_god_view"
                else frozenset({"player_public"})
            )
            saved_voices = voice_store.list_playback_voices(
                excluded_actions=frozenset({PRIVATE_ROUND_MEMORY_ACTION}),
                allowed_audiences=allowed_audiences,
                include_chunks=False,
            )
            materialization_lag_ms = voice_store.max_materialization_lag_ms(
                allowed_audiences=allowed_audiences,
            )
            saved_voices = _map_playback_voices_to_timeline(
                saved_voices,
                persisted_events,
            )
            saved_voices = filter_public_playback_voices(
                saved_voices,
                private_event_ids=private_event_ids,
            )
        except RecoverableDatabaseError:
            saved_voices = []

    if not persisted_events:
        playback["events"] = project_playback_events(
            playback["events"],
            audience=audience,
        )
    public_event_ids = {
        event.get("id") for event in playback["events"] if isinstance(event.get("id"), int)
    }
    saved_voices = [
        voice for voice in saved_voices if voice.get("source_event_id") in public_event_ids
    ]

    static_judge_voices = build_static_judge_playback_voices(
        playback["events"],
        asset_dir=DEFAULT_JUDGE_VOICE_ASSET_DIR,
        asset_loader=lambda asset_id: _static_judge_voice_asset_from_record(
            db.get(JudgeVoiceAssetRecord, asset_id)
        ),
    )
    playback["voices"] = _merge_playback_voices(saved_voices, static_judge_voices)
    playback["voice_coverage"] = build_voice_playback_coverage(
        playback["events"],
        playback["voices"],
        materialization_lag_ms=materialization_lag_ms,
        audience=audience,
    )
    return playback


def _map_playback_voices_to_timeline(
    voices: list[dict[str, Any]],
    events: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    source_events = {
        (event.get("source_run_id"), event.get("source_event_id")): event
        for event in events
        if isinstance(event.get("source_run_id"), str)
        and isinstance(event.get("source_event_id"), int)
        and isinstance(event.get("id"), int)
    }
    source_to_timeline = {
        key: event["id"] for key, event in source_events.items()
    }
    mapped: list[dict[str, Any]] = []
    for voice in voices:
        run_id = voice.get("run_id")
        first_source_id = voice.get("source_event_id")
        last_source_id = voice.get("last_source_event_id", first_source_id)
        if not isinstance(run_id, str) or not isinstance(first_source_id, int):
            continue
        if not isinstance(last_source_id, int):
            last_source_id = first_source_id
        first_timeline_id = source_to_timeline.get((run_id, first_source_id))
        if not isinstance(first_timeline_id, int):
            continue
        last_timeline_id = source_to_timeline.get((run_id, last_source_id))
        if not isinstance(last_timeline_id, int):
            candidates = [
                timeline_id
                for (source_run_id, source_event_id), timeline_id in source_to_timeline.items()
                if source_run_id == run_id and first_source_id <= source_event_id <= last_source_id
            ]
            last_timeline_id = max(candidates, default=first_timeline_id)
        source_event = source_events.get((run_id, first_source_id), {})
        source_payload = source_event.get("payload")
        request_id = (
            source_payload.get("request_id")
            if isinstance(source_payload, dict)
            else None
        )
        if voice.get("speaker_kind") == "player" and isinstance(request_id, str):
            request_timeline_ids = [
                event["id"]
                for event in events
                if event.get("source_run_id") == run_id
                and isinstance(event.get("id"), int)
                and isinstance(event.get("payload"), dict)
                and event["payload"].get("request_id") == request_id
            ]
            if request_timeline_ids:
                first_timeline_id = min(first_timeline_id, *request_timeline_ids)
                last_timeline_id = max(last_timeline_id, *request_timeline_ids)
        mapped.append(
            {
                **{key: value for key, value in voice.items() if key != "run_id"},
                "source_event_id": first_timeline_id,
                "last_source_event_id": last_timeline_id,
            }
        )
    return mapped


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
        return build_public_game_session(store.load_session(session_id))
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
    compiled: CompiledRuleSet,
    player_configs: list[PlayerConfig] | None = None,
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
                compiled_rule_set=compiled,
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

    registry.mark_completed(
        run_id,
        winner=result.winner,
        p2_diagnostics=getattr(result, "p2_diagnostics", None),
    )


def _resume_game_in_background(
    *,
    run_id: str,
    registry: LiveRunRegistry,
    session_id: str,
    expected_compiled_rule_set: CompiledRuleSet,
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
                expected_compiled_rule_set=expected_compiled_rule_set,
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

    registry.mark_completed(
        run_id,
        winner=result.winner,
        p2_diagnostics=getattr(result, "p2_diagnostics", None),
    )


def _event_stream(
    registry: LiveRunRegistry,
    run_id: str,
    *,
    after_id: int | None = None,
    audience: ProjectionAudience = "player_public",
) -> Iterator[str]:
    last_event_id = after_id
    for event in registry.projected_events_after(
        run_id,
        after_id=after_id,
        audience=audience,
    ):
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

            projected = project_live_event(event, audience)
            if projected is not None:
                yield format_sse(projected)
            if _is_terminal_event(event):
                return
    finally:
        if subscriber is not None:
            registry.unsubscribe(run_id, subscriber)


def _timeline_event_stream(
    db: Session,
    run_id: str,
    *,
    after_id: int | None = None,
    audience: ProjectionAudience = "player_public",
) -> Iterator[str]:
    cursor = after_id or 0
    last_heartbeat = time.monotonic()
    while True:
        db.expire_all()
        timeline = DatabaseLiveStore(db).session_timeline_for_run(
            run_id,
            audience=audience,
        )
        if timeline is None:
            return
        emitted_terminal = False
        for event in timeline.events:
            if event.id <= cursor:
                continue
            cursor = event.id
            payload = event.to_dict(run_id=timeline.current_run_id)
            data = json.dumps(payload, ensure_ascii=False)
            yield f"id: {event.id}\nevent: {event.type}\ndata: {data}\n\n"
            emitted_terminal = event.type in {
                "game_completed",
                "game_failed",
                "game_canceled",
            }
        if emitted_terminal:
            return
        if time.monotonic() - last_heartbeat >= 15:
            yield ": heartbeat\n\n"
            last_heartbeat = time.monotonic()
        time.sleep(0.25)


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
