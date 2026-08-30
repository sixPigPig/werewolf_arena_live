from __future__ import annotations

import copy
import json
import logging
import math
from datetime import datetime
from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import (
    APIRouter,
    Depends,
    Header,
    HTTPException,
    Path as PathParameter,
    Query,
    Request,
    Response,
    status,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.admin.audit import record_audit_event
from app.admin.rbac import AdminPermission
from app.api.admin.dependencies import (
    AdminPrincipal,
    require_admin_csrf,
    require_admin_permission,
)
from app.api.admin.errors import AdminAPIProblem, request_id_for
from app.core.config import settings
from app.db.session import get_db
from app.judge_configuration import build_judge_voice_snapshot, runtime_judge_configuration
from app.model_catalog.defaults import (
    max_output_tokens_limit,
    normalize_model_parameters,
)
from app.models.model_configuration import ModelConfigurationRecord
from app.models.virtual_player_profile import VirtualPlayerProfile
from app.rule_sets.errors import RuleRevisionChanged, RuleSetNotFound, RuleSetUnavailable
from app.rule_sets.service import resolve_published_rule_set
from app.rule_sets.static_catalog import resolve_static_rule_set
from app.match.contracts import (
    AdminEventPageResponse,
    AdminEventResponse,
    AdminGameDetailResponse,
    AdminGameControlRequest,
    AdminGameControlResponse,
    AdminGameListItem,
    AdminGameListResponse,
    AdminModelRequestPageResponse,
    AdminModelRequestResponse,
    AdminModelRequestSummaryResponse,
    AdminModelActionRetryResponse,
    AdminPagination,
    AdminPresentationResponse,
    AdminRunResponse,
    AdminVoiceAssetResponse,
    ActorResponse,
    ApiMetaResponse,
    CurrentPresentationResponse,
    DirectorLiveSnapshotResponse,
    GameCreateRequest,
    GameCreateResponse,
    GamePhaseResponse,
    GodViewIdentitySnapshotResponse,
    LiveSnapshotResponse,
    LobbyCreateSnapshot,
    MatchStateResponse,
)
from app.match.control import (
    GameControlError,
    GameControlIdempotencyConflict,
    GameModelActionNotPaused,
    GameControlNotActive,
    GameControlNotFound,
    GameStopAlreadyRequested,
    request_model_action_retry,
    request_game_stop,
)
from app.match.execution import database_utc_now
from app.match.event_contract import (
    AUDIENCE_CONTRACT_VERSION,
    EVENT_AUDIENCES,
    model_event_audience,
)
from app.match.model_client import ModelError, build_model_request_payload
from app.match.model_context_compaction import (
    ModelContextCompactionError,
    canonical_known_events_v5_sha256,
    expand_known_events_v7,
)
from app.match.model_context_contract import (
    CURRENT_DISCOURSE_LEDGER_SCHEMA_VERSION,
    DISCOURSE_MODEL_VIEW_SCHEMA_VERSION,
    KNOWN_EVENTS_SCHEMA_VERSION,
    MODEL_CONTEXT_SCHEMA_VERSION,
    MODEL_VIEW_SELECTOR_VERSION,
    PROMPT_TEMPLATE_VERSION,
)
from app.match.model_failure_episode import FailureEpisode, derive_failure_episodes
from app.match.model_failure_impact import classify_model_failure_impact
from app.match.god_view_projection import project_god_view_player_identities
from app.match.live_runtime import ClientProtocolError, LiveRuntime
from app.match.models import GameRun
from app.match.public_projection import (
    project_public_player_seats,
    project_public_role_assignment_status,
    project_public_rule_snapshot,
)
from app.match.runtime_state import project_runtime_state
from app.match.service import (
    GodViewAccessDenied,
    GodViewUnavailable,
    RecordNotFound,
    VoiceAssetUnavailable,
    all_game_events,
    authorize_god_view,
    create_waiting_game,
    current_presentation,
    game_summary,
    get_game_event,
    get_game,
    get_match_state,
    get_voice_asset,
    god_view_role_assignments,
    list_game_events,
    list_game_presentations,
    list_games,
    player_state_map,
    role_assignment_count,
    server_now,
    voice_asset_path,
)


public_router = APIRouter()
god_view_router = APIRouter()
admin_router = APIRouter()
logger = logging.getLogger(__name__)
GAME_ID_PATTERN = r"v2_game_[0-9a-f]{16}"
VOICE_ID_PATTERN = r"v2_voice_[0-9a-f]{16}"
GOD_VIEW_WEBSOCKET_SUBPROTOCOL = "live-v2-god-view"


def get_v2_voice_root() -> Path:
    return Path(settings.live_v2_voice_storage_dir)


@public_router.get("/meta", response_model=ApiMetaResponse)
def read_v2_meta(response: Response) -> ApiMetaResponse:
    response.headers["Cache-Control"] = "no-store"
    return ApiMetaResponse()


@public_router.post("/games", response_model=GameCreateResponse, status_code=201)
def create_v2_game(
    body: GameCreateRequest,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
) -> GameCreateResponse | JSONResponse:
    runtime: LiveRuntime = request.app.state.live_runtime
    audio_mode = body.audio_mode or runtime.default_audio_mode
    if audio_mode == "tts" and not runtime.tts_capability_enabled:
        return JSONResponse(
            status_code=409,
            content={
                "code": "v2_audio_mode_unavailable",
                "requested_audio_mode": "tts",
            },
        )
    delivery_snapshot = {
        "schema_version": 1,
        "mode": audio_mode,
        "source": (
            "explicit_create_request" if body.audio_mode is not None else "legacy_runtime_default"
        ),
    }
    lobby = body.lobby_snapshot
    frozen_rule_set = lobby.rule_set.model_dump(mode="json", exclude_none=True)
    frozen_rule_revision_id = lobby.rule_set_revision_id
    if lobby.model_binding_mode == "profile_library":
        frozen_rule_set, frozen_rule_revision_id = _resolve_library_rule_snapshot(
            db,
            lobby,
        )
    rule_snapshot = {
        "schema_version": lobby.schema_version,
        "source": "existing_mobile_lobby",
        "model_binding_mode": lobby.model_binding_mode,
        "rule_set_revision_id": frozen_rule_revision_id,
        "seed": lobby.seed,
        "max_rounds": lobby.max_rounds,
        "allow_lineup_quality_warnings": lobby.allow_lineup_quality_warnings,
        "lineup_quality_report": lobby.lineup_quality_report.model_dump(mode="json"),
        "rule_set": frozen_rule_set,
    }
    players_snapshot = []
    for item in lobby.player_configs:
        player_snapshot = item.model_dump(mode="json", exclude_none=True)
        if lobby.model_binding_mode == "profile_library":
            profile = db.get(VirtualPlayerProfile, item.profile_id)
            if profile is None or profile.status != "published":
                raise HTTPException(
                    status_code=409,
                    detail={
                        "code": "v2_player_profile_unavailable",
                        "profile_id": item.profile_id,
                    },
                )
            submitted_binding = (item.model_provider, item.model)
            if any(submitted_binding) and submitted_binding != (
                profile.model_provider,
                profile.model,
            ):
                raise HTTPException(
                    status_code=409,
                    detail={
                        "code": "v2_player_model_binding_mismatch",
                        "profile_id": item.profile_id,
                        "submitted_model_provider": item.model_provider,
                        "submitted_model": item.model,
                        "library_model_provider": profile.model_provider,
                        "library_model": profile.model,
                    },
                )
            player_snapshot.update(_library_player_snapshot(profile))
        model_configuration = db.get(
            ModelConfigurationRecord,
            (
                player_snapshot["model_provider"],
                player_snapshot["model"],
            ),
        )
        if (
            model_configuration is None
            or not model_configuration.available
            or not model_configuration.enabled
        ):
            raise HTTPException(
                status_code=422,
                detail=(
                    "Player model is not enabled: "
                    f"{player_snapshot['model_provider']}/{player_snapshot['model']}"
                ),
            )
        player_snapshot["model_parameters"] = normalize_model_parameters(
            model_configuration.provider,
            model_configuration.model_id,
            model_configuration.parameter_values,
            supports_thinking=model_configuration.supports_thinking,
            limit=max_output_tokens_limit(
                model_configuration.provider,
                model_configuration.model_id,
            ),
            enforce_auto_max_tokens=True,
        )
        player_snapshot["model_supports_thinking"] = model_configuration.supports_thinking
        player_snapshot["model_configuration_updated_at"] = (
            model_configuration.updated_at.isoformat()
        )
        players_snapshot.append(player_snapshot)
    game, run, god_view_access_token = create_waiting_game(
        db,
        title=body.title,
        delivery_snapshot=delivery_snapshot,
        rule_snapshot=rule_snapshot,
        players_snapshot=players_snapshot,
        judge_voice_snapshot=build_judge_voice_snapshot(
            runtime_judge_configuration(
                db,
                default_tts_speaker=settings.live_v2_tts_judge_speaker,
            )
        ),
    )
    return GameCreateResponse(
        game_id=game.game_id,
        run_id=run.run_id,
        status=game.status,
        audio_mode=audio_mode,
        snapshot_url=f"/api/v2/live/games/{game.game_id}/snapshot",
        websocket_url=f"/api/v2/live/games/{game.game_id}/ws",
        director_snapshot_url=f"/api/v2/director/games/{game.game_id}/snapshot",
        director_websocket_url=f"/api/v2/director/games/{game.game_id}/ws",
        god_view_snapshot_url=(f"/api/v2/god-view/games/{game.game_id}/identity-snapshot"),
        god_view_websocket_url=f"/api/v2/god-view/games/{game.game_id}/ws",
        god_view_access_token=god_view_access_token,
    )


def _resolve_library_rule_snapshot(
    db: Session,
    lobby: LobbyCreateSnapshot,
) -> tuple[dict[str, Any], str]:
    expected_revision_id = lobby.rule_set_revision_id
    assert expected_revision_id is not None
    try:
        if settings.rule_set_catalog_source == "static":
            compiled = resolve_static_rule_set(
                lobby.rule_set.id,
                expected_revision_id=expected_revision_id,
            )
        else:
            compiled = resolve_published_rule_set(
                db,
                lobby.rule_set.id,
                expected_revision_id=expected_revision_id,
                for_update=True,
            )
    except RuleRevisionChanged as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "rule_revision_changed",
                "rule_set_id": exc.rule_set_id,
                "expected_revision_id": exc.expected_revision_id,
                "current_revision_id": exc.current_revision_id,
            },
        ) from exc
    except (RuleSetNotFound, RuleSetUnavailable) as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "rule_set_unavailable",
                "rule_set_id": exc.rule_set_id,
            },
        ) from exc

    if compiled.revision_id is None:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "rule_set_unavailable",
                "rule_set_id": lobby.rule_set.id,
            },
        )
    submitted_hash = lobby.rule_set.content_hash
    if submitted_hash is not None and submitted_hash != compiled.content_hash:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "v2_rule_snapshot_mismatch",
                "rule_set_id": lobby.rule_set.id,
                "field": "content_hash",
            },
        )
    if lobby.rule_set.player_count != compiled.rule_set.player_count:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "v2_rule_snapshot_mismatch",
                "rule_set_id": lobby.rule_set.id,
                "field": "player_count",
            },
        )
    return copy.deepcopy(compiled.snapshot), compiled.revision_id


def _library_player_snapshot(profile: VirtualPlayerProfile) -> dict[str, Any]:
    return {
        "profile_id": profile.id,
        "name": profile.display_name,
        "model_provider": profile.model_provider,
        "model": profile.model,
        "personality_id": profile.personality_id,
        "personality": profile.personality_text,
        "appearance_id": profile.appearance_id,
        "avatar_image_url": profile.avatar_image_url,
        "avatar_asset_id": profile.avatar_asset_id,
        "strategy_profile": profile.strategy_profile,
        "tts_speaker": profile.tts_speaker,
        "tts_dialect": profile.tts_dialect,
        "base_delivery_mood": profile.base_delivery_mood,
        "base_delivery_intensity": profile.base_delivery_intensity,
        "base_delivery_pace": profile.base_delivery_pace,
        "base_delivery_instruction": profile.base_delivery_instruction,
        "voice_enabled": profile.voice_enabled,
        "voice_config_version": profile.voice_config_version,
        "tags": list(profile.tags),
    }


@public_router.get(
    "/live/games/{game_id}/snapshot",
    response_model=LiveSnapshotResponse,
)
def read_live_snapshot(
    game_id: Annotated[str, PathParameter(pattern=GAME_ID_PATTERN)],
    request: Request,
    response: Response,
    db: Annotated[Session, Depends(get_db)],
) -> LiveSnapshotResponse:
    try:
        game = get_game(db, game_id)
        presentation = current_presentation(db, game_id)
    except RecordNotFound as exc:
        raise HTTPException(status_code=404, detail="V2 game not found") from exc
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["X-Request-ID"] = request_id_for(request)
    match = get_match_state(db, game_id)
    run = _current_run(db, game)
    runtime_state = project_runtime_state(
        game=game,
        run=run,
        match=match,
        now=database_utc_now(db),
    )
    return LiveSnapshotResponse(
        audience="player_public",
        game_id=game.game_id,
        run_id=game.current_run_id,
        live_state=_live_state(game.status),
        **_runtime_state_fields(runtime_state),
        game_phase=_game_phase(game),
        match_state=_match_state(match),
        latest_presentation_seq=game.last_presentation_seq,
        server_time=server_now(),
        public_rule=project_public_rule_snapshot(game.rule_snapshot),
        public_players=project_public_player_seats(
            game.players_snapshot,
            player_states=player_state_map(db, game.game_id),
        ),
        public_role_assignment=project_public_role_assignment_status(
            role_assignment_count(db, game.game_id)
        ),
        current_presentation=(
            CurrentPresentationResponse(
                action_id=presentation.action_id,
                presentation_seq=presentation.presentation_seq,
                presentation_id=presentation.presentation_id,
                phase_id=presentation.phase_id,
                actor=ActorResponse(
                    kind=presentation.actor_kind,
                    id=presentation.actor_id,
                ),
                speech_id=presentation.speech_id,
                segment_index=presentation.segment_index,
                subtitle_text=presentation.subtitle_text,
                join_sample_cursor=0,
            )
            if presentation is not None and presentation.action_id is not None
            else None
        ),
    )


@public_router.get(
    "/director/games/{game_id}/snapshot",
    response_model=DirectorLiveSnapshotResponse,
)
def read_director_snapshot(
    game_id: Annotated[str, PathParameter(pattern=GAME_ID_PATTERN)],
    request: Request,
    response: Response,
) -> DirectorLiveSnapshotResponse:
    runtime: LiveRuntime = request.app.state.live_runtime
    try:
        payload = runtime.snapshot(game_id=game_id, audience="spectator_directed")
    except RecordNotFound as exc:
        raise HTTPException(status_code=404, detail="V2 game not found") from exc
    except GodViewUnavailable as exc:
        raise HTTPException(status_code=409, detail="Director identity unavailable") from exc
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["X-Request-ID"] = request_id_for(request)
    return DirectorLiveSnapshotResponse.model_validate(payload)


@public_router.websocket("/director/games/{game_id}/ws")
async def director_live_websocket(websocket: WebSocket, game_id: str) -> None:
    if not _valid_game_id(game_id):
        await websocket.close(code=4404)
        return
    await websocket.accept()
    runtime: LiveRuntime = websocket.app.state.live_runtime
    subscriber_id: str | None = None
    channel = None
    try:
        subscriber_id, channel = await runtime.connect(
            game_id=game_id,
            websocket=websocket,
            audience="spectator_directed",
        )
        while True:
            message = await websocket.receive_json()
            if not isinstance(message, dict):
                raise ClientProtocolError("message_must_be_object")
            await runtime.ready(
                channel=channel,
                subscriber_id=subscriber_id,
                message=message,
            )
    except RecordNotFound:
        await websocket.close(code=4404)
    except GodViewUnavailable:
        await websocket.close(code=4409)
    except ClientProtocolError:
        await websocket.close(code=4400)
    except WebSocketDisconnect:
        pass
    finally:
        if subscriber_id is not None and channel is not None:
            await runtime.disconnect(channel=channel, subscriber_id=subscriber_id)


@public_router.websocket("/live/games/{game_id}/ws")
async def live_websocket(websocket: WebSocket, game_id: str) -> None:
    if not _valid_game_id(game_id):
        await websocket.close(code=4404)
        return
    await websocket.accept()
    runtime: LiveRuntime = websocket.app.state.live_runtime
    subscriber_id: str | None = None
    channel = None
    try:
        subscriber_id, channel = await runtime.connect(game_id=game_id, websocket=websocket)
        while True:
            message = await websocket.receive_json()
            if not isinstance(message, dict):
                raise ClientProtocolError("message_must_be_object")
            await runtime.ready(
                channel=channel,
                subscriber_id=subscriber_id,
                message=message,
            )
    except RecordNotFound:
        await websocket.close(code=4404)
    except ClientProtocolError:
        await websocket.close(code=4400)
    except WebSocketDisconnect:
        pass
    finally:
        if subscriber_id is not None and channel is not None:
            await runtime.disconnect(channel=channel, subscriber_id=subscriber_id)


@god_view_router.websocket("/god-view/games/{game_id}/ws")
async def god_view_websocket(
    websocket: WebSocket,
    game_id: str,
    db: Annotated[Session, Depends(get_db)],
) -> None:
    if not _valid_game_id(game_id):
        await websocket.close(code=4404)
        return
    access_token = _god_view_websocket_token(websocket)
    try:
        authorize_god_view(db, game_id=game_id, token=access_token)
    except GodViewAccessDenied:
        await websocket.close(code=4403)
        return

    await websocket.accept(subprotocol=GOD_VIEW_WEBSOCKET_SUBPROTOCOL)
    runtime: LiveRuntime = websocket.app.state.live_runtime
    subscriber_id: str | None = None
    channel = None
    try:
        subscriber_id, channel = await runtime.connect(
            game_id=game_id,
            websocket=websocket,
            audience="spectator_god_view",
        )
        while True:
            message = await websocket.receive_json()
            if not isinstance(message, dict):
                raise ClientProtocolError("message_must_be_object")
            await runtime.ready(
                channel=channel,
                subscriber_id=subscriber_id,
                message=message,
            )
    except RecordNotFound:
        await websocket.close(code=4404)
    except GodViewUnavailable:
        await websocket.close(code=4409)
    except ClientProtocolError:
        await websocket.close(code=4400)
    except WebSocketDisconnect:
        pass
    finally:
        if subscriber_id is not None and channel is not None:
            await runtime.disconnect(channel=channel, subscriber_id=subscriber_id)


@god_view_router.get(
    "/god-view/games/{game_id}/identity-snapshot",
    response_model=GodViewIdentitySnapshotResponse,
)
def read_god_view_identity_snapshot(
    game_id: Annotated[str, PathParameter(pattern=GAME_ID_PATTERN)],
    request: Request,
    response: Response,
    db: Annotated[Session, Depends(get_db)],
    authorization: Annotated[str | None, Header()] = None,
) -> GodViewIdentitySnapshotResponse:
    try:
        authorize_god_view(
            db,
            game_id=game_id,
            token=_bearer_token(authorization),
        )
    except GodViewAccessDenied as exc:
        raise HTTPException(status_code=403, detail="God view access denied") from exc
    try:
        game = get_game(db, game_id)
        assignments = god_view_role_assignments(db, game_id)
    except RecordNotFound as exc:
        raise HTTPException(status_code=404, detail="V2 game not found") from exc
    except GodViewUnavailable as exc:
        raise HTTPException(status_code=409, detail="God view identity unavailable") from exc

    response.headers["Cache-Control"] = "private, no-store"
    response.headers["X-Request-ID"] = request_id_for(request)
    match = get_match_state(db, game_id)
    run = _current_run(db, game)
    runtime_state = project_runtime_state(
        game=game,
        run=run,
        match=match,
        now=database_utc_now(db),
    )
    return GodViewIdentitySnapshotResponse(
        game_id=game.game_id,
        run_id=game.current_run_id,
        live_state=_live_state(game.status),
        **_runtime_state_fields(runtime_state),
        game_phase=_game_phase(game),
        match_state=_match_state(match),
        server_time=server_now(),
        rule=project_public_rule_snapshot(game.rule_snapshot),
        players=project_god_view_player_identities(
            players_snapshot=game.players_snapshot,
            assignments=assignments,
            player_states=player_state_map(db, game_id),
        ),
    )


@admin_router.get("/games", response_model=AdminGameListResponse)
def list_admin_v2_games(
    request: Request,
    response: Response,
    db: Annotated[Session, Depends(get_db)],
    _principal: Annotated[
        AdminPrincipal,
        Depends(require_admin_permission(AdminPermission.V2_GAMES_READ)),
    ],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> AdminGameListResponse:
    records, total = list_games(db, page=page, page_size=page_size)
    database_now = database_utc_now(db)
    _set_admin_headers(request, response)
    return AdminGameListResponse(
        items=[_admin_game_item(record, db=db, now=database_now) for record in records],
        pagination=AdminPagination(
            page=page,
            page_size=page_size,
            total=total,
            pages=math.ceil(total / page_size) if total else 0,
        ),
    )


@admin_router.get("/games/{game_id}", response_model=AdminGameDetailResponse)
def read_admin_v2_game(
    game_id: Annotated[str, PathParameter(pattern=GAME_ID_PATTERN)],
    request: Request,
    response: Response,
    db: Annotated[Session, Depends(get_db)],
    _principal: Annotated[
        AdminPrincipal,
        Depends(require_admin_permission(AdminPermission.V2_GAMES_READ)),
    ],
) -> AdminGameDetailResponse:
    try:
        (
            game,
            runs,
            presentations,
            voices,
            role_assignments,
            player_states,
            action_windows,
            ability_instances,
            ability_activations,
            effect_intents,
            knowledge_facts,
            match_state,
        ) = game_summary(db, game_id)
    except RecordNotFound as exc:
        raise AdminAPIProblem(
            status_code=404,
            code="admin_v2_game_not_found",
            title="V2 game not found",
            detail="The requested V2 game record does not exist.",
        ) from exc
    _set_admin_headers(request, response)
    database_now = database_utc_now(db)
    player_identities = (
        project_god_view_player_identities(
            players_snapshot=game.players_snapshot,
            assignments=role_assignments,
            player_states={item.player_id: item for item in player_states},
        )
        if role_assignments
        else []
    )
    return AdminGameDetailResponse(
        **_admin_game_item(
            game,
            db=db,
            run=next((item for item in runs if item.run_id == game.current_run_id), None),
            match=match_state,
            now=database_now,
        ).model_dump(),
        rule_snapshot=game.rule_snapshot,
        players_snapshot=game.players_snapshot,
        judge_voice_snapshot=game.judge_voice_snapshot,
        delivery_snapshot=game.delivery_snapshot,
        ability_snapshot=game.ability_snapshot,
        player_identities=player_identities,
        match_state=(
            _record_fields(
                match_state,
                "round_no",
                "sheriff_player_id",
                "sheriff_badge_state",
                "pre_sheriff_explosion_count",
                "winner",
                "completion_reason",
                "created_at",
                "updated_at",
            )
            if match_state is not None
            else None
        ),
        runs=[AdminRunResponse.model_validate(run, from_attributes=True) for run in runs],
        presentations=[
            AdminPresentationResponse.model_validate(item, from_attributes=True)
            for item in presentations
        ],
        voice_assets=[_admin_voice_asset(item) for item in voices],
        player_states=[
            _record_fields(
                item,
                "player_id",
                "seat",
                "alive",
                "death_cause",
                "death_window_seq",
                "state",
                "updated_at",
            )
            for item in player_states
        ],
        action_windows=[
            _record_fields(
                item,
                "window_id",
                "run_id",
                "window_seq",
                "window_type",
                "state",
                "ability_snapshot_hash",
                "plan",
                "result",
                "opened_at",
                "closed_at",
            )
            for item in action_windows
        ],
        ability_instances=[
            _record_fields(
                item,
                "ability_instance_id",
                "ability_id",
                "ability_version",
                "owner_scope",
                "owner_id",
                "owner_role_key",
                "state",
                "created_at",
            )
            for item in ability_instances
        ],
        ability_activations=[
            _record_fields(
                item,
                "activation_id",
                "window_id",
                "ability_instance_id",
                "occurrence",
                "action_id",
                "decision_id",
                "actor_player_id",
                "status",
                "skip_reason",
                "knowledge_fact_ids",
                "decision",
                "result",
                "opened_at",
                "closed_at",
            )
            for item in ability_activations
        ],
        effect_intents=[
            _record_fields(
                item,
                "effect_intent_id",
                "window_id",
                "activation_id",
                "effect_type",
                "actor_id",
                "target_player_id",
                "payload",
                "state",
                "created_at",
                "resolved_at",
            )
            for item in effect_intents
        ],
        knowledge_facts=[
            _record_fields(
                item,
                "knowledge_fact_id",
                "source_activation_id",
                "owner_scope",
                "owner_id",
                "fact_type",
                "payload",
                "created_at",
            )
            for item in knowledge_facts
        ],
    )


@admin_router.get(
    "/games/{game_id}/events",
    response_model=AdminEventPageResponse,
)
def list_admin_v2_game_events(
    game_id: Annotated[str, PathParameter(pattern=GAME_ID_PATTERN)],
    request: Request,
    response: Response,
    db: Annotated[Session, Depends(get_db)],
    _principal: Annotated[
        AdminPrincipal,
        Depends(require_admin_permission(AdminPermission.V2_GAMES_READ)),
    ],
    after_record_seq: Annotated[int, Query(ge=0)] = 0,
    page_size: Annotated[int, Query(ge=1, le=500)] = 250,
) -> AdminEventPageResponse:
    try:
        events, has_more = list_game_events(
            db,
            game_id,
            after_record_seq=after_record_seq,
            page_size=page_size,
        )
    except RecordNotFound as exc:
        raise AdminAPIProblem(
            status_code=404,
            code="admin_v2_game_not_found",
            title="V2 game not found",
            detail="The requested V2 game record does not exist.",
        ) from exc
    _set_admin_headers(request, response)
    next_after_record_seq = events[-1].record_seq if events else after_record_seq
    return AdminEventPageResponse(
        items=[_admin_event_summary(event) for event in events],
        after_record_seq=after_record_seq,
        next_after_record_seq=next_after_record_seq,
        has_more=has_more,
    )


@admin_router.get(
    "/games/{game_id}/events/{event_id}",
    response_model=AdminEventResponse,
)
def read_admin_v2_game_event(
    game_id: Annotated[str, PathParameter(pattern=GAME_ID_PATTERN)],
    event_id: Annotated[int, PathParameter(ge=1)],
    request: Request,
    response: Response,
    db: Annotated[Session, Depends(get_db)],
    _principal: Annotated[
        AdminPrincipal,
        Depends(require_admin_permission(AdminPermission.V2_GAMES_READ)),
    ],
) -> AdminEventResponse:
    try:
        event = get_game_event(db, game_id=game_id, event_id=event_id)
    except RecordNotFound as exc:
        raise AdminAPIProblem(
            status_code=404,
            code="admin_v2_event_not_found",
            title="V2 event not found",
            detail="The requested V2 event does not exist.",
        ) from exc
    _set_admin_headers(request, response)
    return AdminEventResponse.model_validate(event, from_attributes=True)


@admin_router.get(
    "/games/{game_id}/model-requests",
    response_model=AdminModelRequestPageResponse,
)
def list_admin_v2_model_requests(
    game_id: Annotated[str, PathParameter(pattern=GAME_ID_PATTERN)],
    request: Request,
    response: Response,
    db: Annotated[Session, Depends(get_db)],
    _principal: Annotated[
        AdminPrincipal,
        Depends(require_admin_permission(AdminPermission.V2_GAMES_READ)),
    ],
    after_record_seq: Annotated[int, Query(ge=0)] = 0,
    page_size: Annotated[int, Query(ge=1, le=500)] = 250,
) -> AdminModelRequestPageResponse:
    try:
        events = all_game_events(db, game_id)
        presentations = list_game_presentations(db, game_id)
    except RecordNotFound as exc:
        raise AdminAPIProblem(
            status_code=404,
            code="admin_v2_game_not_found",
            title="V2 game not found",
            detail="The requested V2 game record does not exist.",
        ) from exc
    changed = sorted(
        (
            item
            for item in _admin_model_requests(events, presentations)
            if item.last_record_seq > after_record_seq
        ),
        key=lambda item: (item.last_record_seq, item.record_seq, item.attempt_id),
    )
    page = changed[:page_size]
    if len(changed) > len(page) and page:
        boundary_record_seq = page[-1].last_record_seq
        page.extend(
            item for item in changed[len(page) :] if item.last_record_seq == boundary_record_seq
        )
    has_more = len(changed) > len(page)
    current_record_seq = events[-1].record_seq if events else after_record_seq
    _set_admin_headers(request, response)
    return AdminModelRequestPageResponse(
        items=[_admin_model_request_summary(item) for item in page],
        after_record_seq=after_record_seq,
        next_after_record_seq=(page[-1].last_record_seq if has_more else current_record_seq),
        has_more=has_more,
    )


@admin_router.get(
    "/games/{game_id}/model-requests/{attempt_id}",
    response_model=AdminModelRequestResponse,
)
def read_admin_v2_model_request(
    game_id: Annotated[str, PathParameter(pattern=GAME_ID_PATTERN)],
    attempt_id: Annotated[str, PathParameter(min_length=1, max_length=80)],
    request: Request,
    response: Response,
    db: Annotated[Session, Depends(get_db)],
    _principal: Annotated[
        AdminPrincipal,
        Depends(require_admin_permission(AdminPermission.V2_GAMES_READ)),
    ],
) -> AdminModelRequestResponse:
    try:
        events = all_game_events(db, game_id)
        presentations = list_game_presentations(db, game_id)
    except RecordNotFound as exc:
        raise AdminAPIProblem(
            status_code=404,
            code="admin_v2_game_not_found",
            title="V2 game not found",
            detail="The requested V2 game record does not exist.",
        ) from exc
    result = next(
        (
            item
            for item in _admin_model_requests(
                events,
                presentations,
                expanded_known_events_attempt_id=attempt_id,
            )
            if item.attempt_id == attempt_id
        ),
        None,
    )
    if result is None:
        raise AdminAPIProblem(
            status_code=404,
            code="admin_v2_model_request_not_found",
            title="V2 model request not found",
            detail="The requested V2 model request does not exist.",
        )
    _set_admin_headers(request, response)
    return result


@admin_router.post(
    "/games/{game_id}/retry-model-action",
    response_model=AdminModelActionRetryResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def retry_admin_v2_model_action(
    game_id: Annotated[str, PathParameter(pattern=GAME_ID_PATTERN)],
    request_body: AdminGameControlRequest,
    request: Request,
    response: Response,
    db: Annotated[Session, Depends(get_db)],
    principal: Annotated[AdminPrincipal, Depends(require_admin_csrf)],
    idempotency_key: Annotated[
        str,
        Header(alias="Idempotency-Key", min_length=8, max_length=160),
    ],
) -> AdminModelActionRetryResponse:
    if AdminPermission.RUNS_CONTROL not in principal.permissions:
        raise AdminAPIProblem(
            status_code=403,
            code="admin_permission_denied",
            title="Permission denied",
            detail="The 'runs.control' permission is required.",
        )
    try:
        result = request_model_action_retry(
            db,
            game_id=game_id,
            actor_user_id=principal.user.id,
            idempotency_key=idempotency_key,
            reason=request_body.reason,
        )
        if not result.replayed:
            record_audit_event(
                db,
                request=request,
                actor_user_id=principal.user.id,
                action="admin.v2_game.retry_model_action",
                resource_type="v2_game",
                resource_id=game_id,
                result="success",
                reason=request_body.reason,
                before={
                    "game_status": result.game.status,
                    "run_status": result.run.status,
                    "action_id": result.action_id,
                },
                after={
                    "retry_requested": True,
                    "reason_code": "operator_retry",
                },
            )
        db.commit()
    except GameControlError as exc:
        db.rollback()
        _audit_v2_control_rejection(
            db,
            request=request,
            principal=principal,
            game_id=game_id,
            reason=request_body.reason,
            code=exc.code,
            audit_action="admin.v2_game.retry_model_action",
        )
        raise _v2_control_problem(exc) from exc
    except IntegrityError as exc:
        db.rollback()
        raise AdminAPIProblem(
            status_code=409,
            code="admin_idempotency_conflict",
            title="Idempotency conflict",
            detail="The idempotency key was accepted by another request.",
        ) from exc

    if result.replayed:
        response.status_code = status.HTTP_200_OK
    db.expire_all()
    run = db.get(type(result.run), result.run.run_id)
    if run is None:
        raise AdminAPIProblem(
            status_code=503,
            code="admin_v2_game_control_unavailable",
            title="V2 game control unavailable",
            detail="The retry request was persisted but its run could not be reloaded.",
        )
    if run.status == "paused_model_error":
        runtime: LiveRuntime = request.app.state.live_runtime
        resumed = await runtime.retry_paused_model_action(
            game_id=game_id,
            action_id=result.action_id,
            control_request_id=result.control.id,
        )
        db.expire_all()
        run = db.get(type(result.run), result.run.run_id)
        if not resumed or run is None:
            raise AdminAPIProblem(
                status_code=503,
                code="admin_v2_model_action_retry_unavailable",
                title="V2 model action retry unavailable",
                detail=(
                    "The retry request was persisted, but no local or durable paused "
                    "action could accept it."
                ),
            )
    _set_admin_headers(request, response)
    return AdminModelActionRetryResponse(
        action="retry_model_action",
        game_id=game_id,
        run_id=run.run_id,
        run_status=run.status,
        action_id=result.action_id,
        replayed=result.replayed,
    )


@admin_router.post(
    "/games/{game_id}/stop",
    response_model=AdminGameControlResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def stop_admin_v2_game(
    game_id: Annotated[str, PathParameter(pattern=GAME_ID_PATTERN)],
    request_body: AdminGameControlRequest,
    request: Request,
    response: Response,
    db: Annotated[Session, Depends(get_db)],
    principal: Annotated[AdminPrincipal, Depends(require_admin_csrf)],
    idempotency_key: Annotated[
        str,
        Header(alias="Idempotency-Key", min_length=8, max_length=160),
    ],
) -> AdminGameControlResponse:
    if AdminPermission.RUNS_CONTROL not in principal.permissions:
        raise AdminAPIProblem(
            status_code=403,
            code="admin_permission_denied",
            title="Permission denied",
            detail="The 'runs.control' permission is required.",
        )
    try:
        result = request_game_stop(
            db,
            game_id=game_id,
            actor_user_id=principal.user.id,
            idempotency_key=idempotency_key,
            reason=request_body.reason,
        )
        if not result.replayed:
            record_audit_event(
                db,
                request=request,
                actor_user_id=principal.user.id,
                action="admin.v2_game.stop",
                resource_type="v2_game",
                resource_id=game_id,
                result="success",
                reason=request_body.reason,
                before={
                    "game_status": result.game.status,
                    "run_status": result.run.status,
                },
                after={
                    "stop_requested": True,
                    "reason_code": "operator_interrupted",
                },
            )
        db.commit()
    except GameControlError as exc:
        db.rollback()
        _audit_v2_control_rejection(
            db,
            request=request,
            principal=principal,
            game_id=game_id,
            reason=request_body.reason,
            code=exc.code,
        )
        raise _v2_control_problem(exc) from exc
    except IntegrityError as exc:
        db.rollback()
        raise AdminAPIProblem(
            status_code=409,
            code="admin_idempotency_conflict",
            title="Idempotency conflict",
            detail="The idempotency key was accepted by another request.",
        ) from exc

    if result.replayed:
        response.status_code = status.HTTP_200_OK
    if not result.replayed or result.run.status != "canceled":
        runtime: LiveRuntime = request.app.state.live_runtime
        try:
            await runtime.interrupt(game_id=game_id)
        except Exception:
            logger.exception(
                "V2 stop request persisted but local runtime interruption failed",
                extra={"game_id": game_id, "run_id": result.run.run_id},
            )

    db.expire_all()
    run = db.get(type(result.run), result.run.run_id)
    if run is None or run.stop_requested_at is None:
        raise AdminAPIProblem(
            status_code=503,
            code="admin_v2_game_control_unavailable",
            title="V2 game control unavailable",
            detail="The stop request was persisted but its run state could not be reloaded.",
        )
    _set_admin_headers(request, response)
    return AdminGameControlResponse(
        action="stop",
        game_id=game_id,
        run_id=run.run_id,
        run_status=run.status,
        stop_requested_at=run.stop_requested_at,
        replayed=result.replayed,
    )


@admin_router.get("/games/{game_id}/voice-assets/{voice_asset_id}/audio")
def read_admin_v2_voice_audio(
    game_id: Annotated[str, PathParameter(pattern=GAME_ID_PATTERN)],
    voice_asset_id: Annotated[str, PathParameter(pattern=VOICE_ID_PATTERN)],
    db: Annotated[Session, Depends(get_db)],
    root: Annotated[Path, Depends(get_v2_voice_root)],
    _principal: Annotated[
        AdminPrincipal,
        Depends(require_admin_permission(AdminPermission.V2_GAMES_READ)),
    ],
) -> FileResponse:
    try:
        asset = get_voice_asset(db, game_id=game_id, voice_asset_id=voice_asset_id)
        path = voice_asset_path(root=root, asset=asset)
    except RecordNotFound as exc:
        raise HTTPException(status_code=404, detail="V2 voice asset not found") from exc
    except VoiceAssetUnavailable as exc:
        raise HTTPException(status_code=409, detail="V2 voice asset is not ready") from exc
    return FileResponse(
        path,
        media_type=asset.mime_type,
        headers={"Cache-Control": "private, no-store"},
    )


def _admin_game_item(
    record: object,
    *,
    db: Session,
    run: GameRun | None = None,
    match: object | None = None,
    now: datetime,
) -> AdminGameListItem:
    game = record
    current_run = run or _current_run(db, game)
    current_match = match if match is not None else get_match_state(db, game.game_id)
    runtime_state = project_runtime_state(
        game=game,
        run=current_run,
        match=current_match,
        now=now,
    )
    return AdminGameListItem.model_validate(
        {
            **game.__dict__,
            **_runtime_state_fields(runtime_state),
        }
    )


def _current_run(db: Session, game: object) -> GameRun:
    run = db.get(GameRun, game.current_run_id)
    if run is None:
        raise RecordNotFound(f"missing current run for {game.game_id}")
    return run


def _runtime_state_fields(runtime_state: object) -> dict[str, Any]:
    return {
        "audio_mode": runtime_state.audio_mode,
        "match_status": runtime_state.match_status,
        "execution_state": runtime_state.execution_state,
        "winner": runtime_state.winner,
        "completion_reason": runtime_state.completion_reason,
        "completed_at": runtime_state.completed_at,
    }


def _admin_voice_asset(asset: object) -> AdminVoiceAssetResponse:
    value = AdminVoiceAssetResponse.model_validate(
        {**asset.__dict__, "audio_url": None},
    )
    if value.state != "ready":
        return value
    return value.model_copy(
        update={
            "audio_url": (
                f"/api/v1/admin/v2/games/{asset.game_id}/voice-assets/{asset.voice_asset_id}/audio"
            )
        }
    )


_ADMIN_ACTION_CONTEXT_KEYS = {
    "schema_version",
    "action_id",
    "action_type",
    "game_id",
    "run_id",
    "phase_id",
    "actor",
    "objective",
    "ability_id",
    "activation_id",
    "audience",
    "speech_source",
    "round_no",
    "window_id",
}
_ADMIN_STREAM_CONTENT_LIMIT = 200_000


def _admin_event_summary(event: object) -> AdminEventResponse:
    payload = event.payload if isinstance(event.payload, dict) else {}
    projected = dict(payload)
    if event.event_type == "action_opened":
        context = payload.get("context")
        projected["context"] = (
            {key: value for key, value in context.items() if key in _ADMIN_ACTION_CONTEXT_KEYS}
            if isinstance(context, dict)
            else {}
        )
    elif event.event_type == "model_request_started":
        projected.pop("request_payload", None)
    elif event.event_type == "model_response_received":
        projected.pop("raw_response", None)
        projected.pop("parsed_output", None)
        projected.pop("passive_observations", None)
    elif event.event_type == "model_request_failed":
        projected.pop("raw_response", None)
    elif event.event_type == "model_stream_progress":
        projected.pop("reasoning_delta", None)
        projected.pop("text_delta", None)
    return AdminEventResponse.model_validate(
        {**event.__dict__, "payload": projected},
    )


def _admin_model_request_summary(
    item: AdminModelRequestResponse,
) -> AdminModelRequestSummaryResponse:
    return AdminModelRequestSummaryResponse.model_validate(
        item.model_dump(
            exclude={
                "request_payload",
                "expanded_known_events",
                "known_events_expansion_status",
                "raw_response",
                "parsed_output",
                "passive_observations",
            }
        )
    )


def _admin_request_model_context(
    request_payload: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if not isinstance(request_payload, dict):
        return None
    candidate_texts: list[str] = []
    for container_key in ("input", "messages"):
        items = request_payload.get(container_key)
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict) or item.get("role") != "user":
                continue
            content = item.get("content")
            if isinstance(content, str):
                candidate_texts.append(content)
            elif isinstance(content, list):
                candidate_texts.extend(
                    part["text"]
                    for part in content
                    if isinstance(part, dict) and isinstance(part.get("text"), str)
                )
    for text in reversed(candidate_texts):
        json_start = text.find("{")
        if json_start < 0:
            continue
        try:
            value = json.loads(text[json_start:])
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        if isinstance(value, dict):
            return value
    return None


def _admin_expanded_known_events(
    request_payload: dict[str, Any] | None,
    *,
    prompt_schema_version: int | None,
    model_context_schema_version: int | None,
    prompt_template_version: int | None,
    model_view_selector_version: int | None,
    prompt_projection: dict[str, Any] | None,
) -> tuple[
    dict[str, Any] | None,
    Literal["verified", "not_applicable", "unavailable", "invalid"],
]:
    if model_context_schema_version is None:
        return None, "unavailable"
    if (
        prompt_schema_version != MODEL_CONTEXT_SCHEMA_VERSION
        or model_context_schema_version != MODEL_CONTEXT_SCHEMA_VERSION
        or model_view_selector_version != MODEL_VIEW_SELECTOR_VERSION
    ):
        return None, "invalid"
    if prompt_template_version != PROMPT_TEMPLATE_VERSION:
        return None, "invalid"
    expected_projection_contract = {
        "model_context_schema_version": MODEL_CONTEXT_SCHEMA_VERSION,
        "prompt_template_version": PROMPT_TEMPLATE_VERSION,
        "known_events_schema_version": KNOWN_EVENTS_SCHEMA_VERSION,
        "ledger_schema_version": CURRENT_DISCOURSE_LEDGER_SCHEMA_VERSION,
        "model_view_schema_version": DISCOURSE_MODEL_VIEW_SCHEMA_VERSION,
        "model_view_selector_version": MODEL_VIEW_SELECTOR_VERSION,
    }
    if not isinstance(prompt_projection, dict) or any(
        prompt_projection.get(key) != expected
        for key, expected in expected_projection_contract.items()
    ):
        return None, "invalid"
    model_context = _admin_request_model_context(request_payload)
    if model_context is None:
        return None, "unavailable"
    if (
        model_context.get("model_context_schema_version") != MODEL_CONTEXT_SCHEMA_VERSION
        or model_context.get("prompt_template_version") != PROMPT_TEMPLATE_VERSION
    ):
        return None, "invalid"
    known_events = model_context.get("known_events")
    if not isinstance(known_events, dict):
        return None, "invalid"
    try:
        expanded = expand_known_events_v7(known_events)
    except ModelContextCompactionError:
        return None, "invalid"
    selector = prompt_projection.get("selector")
    expanded_events = expanded.get("events")
    retained_refs = prompt_projection.get("retained_event_refs")
    if (
        not isinstance(selector, dict)
        or not isinstance(expanded_events, list)
        or not isinstance(retained_refs, list)
    ):
        return None, "invalid"
    expanded_refs = [
        event.get("event_ref") for event in expanded_events if isinstance(event, dict)
    ]
    selector_retained = selector.get("retained")
    selector_refs = (
        [entry.get("event_ref") for entry in selector_retained if isinstance(entry, dict)]
        if isinstance(selector_retained, list)
        else None
    )
    if (
        len(expanded_refs) != len(expanded_events)
        or any(not isinstance(ref, str) for ref in expanded_refs)
        or any(not isinstance(ref, str) for ref in retained_refs)
        or selector_refs is None
        or any(not isinstance(ref, str) for ref in selector_refs)
        or selector.get("retained_count") != len(expanded_refs)
        or len(set(expanded_refs)) != len(expanded_refs)
        or set(expanded_refs) != set(retained_refs)
        or set(expanded_refs) != set(selector_refs)
        or prompt_projection.get("emitted_event_count") != len(expanded_refs)
        or prompt_projection.get("canonical_sha256")
        != canonical_known_events_v5_sha256(expanded)
    ):
        return None, "invalid"
    return expanded, "verified"


def _admin_model_requests(
    events: list[object],
    presentations: list[object],
    *,
    expanded_known_events_attempt_id: str | None = None,
) -> list[AdminModelRequestResponse]:
    events_by_run: dict[str | None, list[object]] = {}
    for event in events:
        events_by_run.setdefault(getattr(event, "run_id", None), []).append(event)
    failure_episodes_by_attempt: dict[tuple[str | None, str], FailureEpisode] = {}
    for run_events in events_by_run.values():
        for episode in derive_failure_episodes(run_events):
            for source_attempt_id in episode.source_attempt_ids:
                failure_episodes_by_attempt.setdefault((episode.run_id, source_attempt_id), episode)

    action_contexts: dict[tuple[str | None, str], dict[str, Any]] = {}
    presentations_by_action = {
        (getattr(item, "run_id", None), item.action_id): item
        for item in presentations
        if isinstance(item.action_id, str) and item.action_id
    }
    responses: dict[tuple[str | None, str], object] = {}
    response_headers: dict[tuple[str | None, str], object] = {}
    first_tokens: dict[tuple[str | None, str], object] = {}
    first_texts: dict[tuple[str | None, str], object] = {}
    stream_progresses: dict[tuple[str | None, str], list[object]] = {}
    failures: dict[tuple[str | None, str], object] = {}
    retry_schedules: dict[tuple[str | None, str], object] = {}
    action_failures: dict[tuple[str | None, str], object] = {}
    action_successes: dict[tuple[str | None, str], object] = {}
    tts_starts: dict[tuple[str | None, str], object] = {}
    starts: list[object] = []
    last_record_seq_by_attempt: dict[tuple[str | None, str], int] = {}
    last_record_seq_by_action: dict[tuple[str | None, str], int] = {}

    for event in events:
        payload = event.payload if isinstance(event.payload, dict) else {}
        event_run_id = getattr(event, "run_id", None)
        action_id = payload.get("action_id")
        attempt_id = payload.get("attempt_id")
        if isinstance(attempt_id, str):
            attempt_key = (event_run_id, attempt_id)
            last_record_seq_by_attempt[attempt_key] = max(
                last_record_seq_by_attempt.get(attempt_key, 0),
                event.record_seq,
            )
        if isinstance(action_id, str):
            action_key = (event_run_id, action_id)
            last_record_seq_by_action[action_key] = max(
                last_record_seq_by_action.get(action_key, 0),
                event.record_seq,
            )
        if event.event_type == "action_opened" and isinstance(action_id, str):
            context = payload.get("context")
            if isinstance(context, dict):
                action_contexts[(event_run_id, action_id)] = context
        elif event.event_type == "model_request_started":
            starts.append(event)
        elif event.event_type == "model_response_headers_received" and isinstance(attempt_id, str):
            response_headers[(event_run_id, attempt_id)] = event
        elif event.event_type == "model_first_token_received" and isinstance(attempt_id, str):
            first_tokens[(event_run_id, attempt_id)] = event
        elif event.event_type == "model_first_text_delta_received" and isinstance(attempt_id, str):
            first_texts[(event_run_id, attempt_id)] = event
        elif event.event_type == "model_stream_progress" and isinstance(attempt_id, str):
            stream_progresses.setdefault((event_run_id, attempt_id), []).append(event)
        elif event.event_type == "model_response_received" and isinstance(attempt_id, str):
            responses[(event_run_id, attempt_id)] = event
        elif event.event_type == "model_request_failed" and isinstance(attempt_id, str):
            failures[(event_run_id, attempt_id)] = event
        elif event.event_type == "model_retry_scheduled" and isinstance(attempt_id, str):
            retry_schedules[(event_run_id, attempt_id)] = event
        elif event.event_type == "action_failed" and isinstance(action_id, str):
            action_failures[(event_run_id, action_id)] = event
        elif event.event_type == "action_succeeded" and isinstance(action_id, str):
            action_successes[(event_run_id, action_id)] = event
        elif event.event_type == "tts_stream_started" and isinstance(action_id, str):
            tts_starts[(event_run_id, action_id)] = event

    started_attempt_keys = {
        (getattr(event, "run_id", None), event.payload.get("attempt_id"))
        for event in starts
        if isinstance(event.payload, dict) and isinstance(event.payload.get("attempt_id"), str)
    }
    starts.extend(
        event for attempt_key, event in failures.items() if attempt_key not in started_attempt_keys
    )
    starts.sort(key=lambda event: event.record_seq)

    result: list[AdminModelRequestResponse] = []
    for start in starts:
        payload = start.payload if isinstance(start.payload, dict) else {}
        attempt_id = payload.get("attempt_id")
        action_id = payload.get("action_id")
        if not isinstance(attempt_id, str) or not isinstance(action_id, str):
            continue
        run_id = getattr(start, "run_id", None)
        attempt_key = (run_id, attempt_id)
        action_key = (run_id, action_id)
        context = action_contexts.get(action_key, {})
        actor = context.get("actor") if isinstance(context.get("actor"), dict) else {}
        presentation = presentations_by_action.get(action_key) or presentations_by_action.get(
            (None, action_id)
        )
        response = responses.get(attempt_key)
        response_payload = (
            response.payload if response is not None and isinstance(response.payload, dict) else {}
        )
        first_token = first_tokens.get(attempt_key)
        first_payload = (
            first_token.payload
            if first_token is not None and isinstance(first_token.payload, dict)
            else {}
        )
        headers_event = response_headers.get(attempt_key)
        headers_payload = (
            headers_event.payload
            if headers_event is not None and isinstance(headers_event.payload, dict)
            else {}
        )
        first_text = first_texts.get(attempt_key)
        first_text_payload = (
            first_text.payload
            if first_text is not None and isinstance(first_text.payload, dict)
            else {}
        )
        stream_snapshot = _admin_model_stream_snapshot(
            stream_progresses.get(attempt_key, []),
            include_content=attempt_id == expanded_known_events_attempt_id,
        )
        stream_payload = stream_snapshot["last_payload"]
        failure = failures.get(attempt_key) or action_failures.get(action_key)
        failure_payload = (
            failure.payload if failure is not None and isinstance(failure.payload, dict) else {}
        )
        retry_schedule = retry_schedules.get(attempt_key)
        retry_payload = (
            retry_schedule.payload
            if retry_schedule is not None and isinstance(retry_schedule.payload, dict)
            else {}
        )
        model_id = payload.get("model_id")
        model_id = model_id if isinstance(model_id, str) and model_id else None
        actor_kind = payload.get("actor_kind") or actor.get("kind") or "unknown"
        actor_id = payload.get("actor_id") or actor.get("id") or "unknown"
        request_kind = payload.get("request_kind")
        if request_kind not in {"speech", "decision"}:
            request_kind = "decision" if actor_kind == "player" else "speech"
        model_context_schema_version = (
            payload.get("model_context_schema_version")
            if isinstance(payload.get("model_context_schema_version"), int)
            and not isinstance(payload.get("model_context_schema_version"), bool)
            else None
        )
        prompt_template_version = (
            payload.get("prompt_template_version")
            if isinstance(payload.get("prompt_template_version"), int)
            and not isinstance(payload.get("prompt_template_version"), bool)
            else None
        )
        prompt_projection = (
            payload.get("prompt_projection")
            if isinstance(payload.get("prompt_projection"), dict)
            else None
        )
        request_payload = payload.get("request_payload")
        prompt_schema_version = (
            payload.get("prompt_schema_version")
            if isinstance(payload.get("prompt_schema_version"), int)
            and not isinstance(payload.get("prompt_schema_version"), bool)
            else None
        )
        model_view_selector_version = (
            payload.get("model_view_selector_version")
            if isinstance(payload.get("model_view_selector_version"), int)
            and not isinstance(payload.get("model_view_selector_version"), bool)
            else None
        )
        input_source: Literal["persisted", "reconstructed", "unavailable"]
        if isinstance(request_payload, dict):
            input_source = "persisted"
        elif (
            model_context_schema_version == MODEL_CONTEXT_SCHEMA_VERSION
            and prompt_template_version == PROMPT_TEMPLATE_VERSION
            and context.get("model_context_schema_version") == MODEL_CONTEXT_SCHEMA_VERSION
            and context.get("prompt_template_version") == PROMPT_TEMPLATE_VERSION
        ):
            try:
                request_payload = build_model_request_payload(
                    context,
                    decision=request_kind == "decision",
                    model_id=model_id or "",
                    max_output_tokens=16_384,
                )
            except (ModelError, KeyError, TypeError, ValueError):
                request_payload = None
                input_source = "unavailable"
            else:
                input_source = "reconstructed"
        else:
            request_payload = None
            input_source = "unavailable"
        expanded_known_events, known_events_expansion_status = (
            _admin_expanded_known_events(
                request_payload,
                prompt_schema_version=prompt_schema_version,
                model_context_schema_version=model_context_schema_version,
                prompt_template_version=prompt_template_version,
                model_view_selector_version=model_view_selector_version,
                prompt_projection=prompt_projection,
            )
            if attempt_id == expanded_known_events_attempt_id
            else (None, "unavailable")
        )

        parsed_output = response_payload.get("parsed_output")
        raw_response = response_payload.get("raw_response")
        if not isinstance(raw_response, str):
            raw_response = failure_payload.get("raw_response")
        if not isinstance(raw_response, str):
            raw_response = None
        if not isinstance(parsed_output, dict):
            parsed_output = None
        output_source: Literal["persisted", "legacy_inferred", "unavailable"]
        if raw_response is not None or parsed_output is not None:
            output_source = "persisted"
        elif presentation is not None:
            parsed_output = {"speech": presentation.subtitle_text}
            output_source = "legacy_inferred"
        else:
            output_source = "unavailable"

        if response is not None:
            status: Literal[
                "running",
                "succeeded",
                "failed",
                "skipped",
                "canceled",
            ] = "succeeded"
            completed_at = response.created_at
        elif failure is not None:
            status = "failed"
            completed_at = failure.created_at
        elif action_key in action_successes or presentation is not None:
            status = "succeeded"
            completed_at = (
                action_successes[action_key].created_at
                if action_key in action_successes
                else presentation.created_at
            )
        else:
            status = "running"
            completed_at = None

        tts_start = tts_starts.get(action_key)
        tts_payload = (
            tts_start.payload
            if tts_start is not None and isinstance(tts_start.payload, dict)
            else {}
        )
        provider_request_id = (
            response_payload.get("provider_request_id")
            or first_payload.get("provider_request_id")
            or first_text_payload.get("provider_request_id")
            or headers_payload.get("provider_request_id")
            or stream_payload.get("provider_request_id")
            or failure_payload.get("provider_request_id")
        )
        passive_observations = (
            response_payload.get("passive_observations")
            if isinstance(response_payload.get("passive_observations"), list)
            else []
        )
        binding_prior_failure_streak = _first_int(payload.get("model_binding_prior_failure_streak"))
        binding_failed_streak = _first_int(failure_payload.get("model_binding_failure_streak"))
        if response is not None and binding_prior_failure_streak is not None:
            binding_failure_streak = 0
            binding_health_status = "healthy"
            binding_recovered_after_failures = (
                binding_prior_failure_streak if binding_prior_failure_streak > 0 else None
            )
        elif binding_failed_streak is not None:
            binding_failure_streak = binding_failed_streak
            raw_binding_health_status = failure_payload.get("model_binding_health_status")
            binding_health_status = (
                raw_binding_health_status
                if raw_binding_health_status in {"healthy", "impaired", "degraded"}
                else None
            )
            binding_recovered_after_failures = None
        else:
            binding_failure_streak = binding_prior_failure_streak
            raw_binding_health_status = payload.get("model_binding_health_status")
            binding_health_status = (
                raw_binding_health_status
                if raw_binding_health_status in {"healthy", "impaired", "degraded"}
                else None
            )
            binding_recovered_after_failures = None
        stored_audience, effective_audience, audience_source = _admin_model_request_audience(
            payload=payload,
            context=context,
            presentation=presentation,
        )
        retry_cycle = _first_int(payload.get("retry_cycle")) or 1
        cycle_attempt_no = (
            _first_int(payload.get("cycle_attempt_no"))
            or _first_int(payload.get("attempt_no"))
            or 1
        )
        vote_batch_stage = context.get("vote_batch_stage")
        vote_batch_stage = vote_batch_stage if isinstance(vote_batch_stage, str) else None
        if retry_cycle > 1:
            retry_scope = "operator_retry"
        elif cycle_attempt_no > 1:
            retry_scope = "same_action"
        elif vote_batch_stage == "concurrent_initial":
            retry_scope = "batch_initial"
        elif vote_batch_stage in {"concurrent_recovery", "sequential_recovery"}:
            retry_scope = "batch_recovery"
        else:
            retry_scope = "action"
        failed_automatic_count = _first_int(
            failure_payload.get("automatic_machine_format_attempt_count")
        )
        started_automatic_count = _first_int(payload.get("automatic_machine_format_attempt_count"))
        failed_automatic_budget = _first_int(failure_payload.get("automatic_machine_format_budget"))
        started_automatic_budget = _first_int(payload.get("automatic_machine_format_budget"))
        prior_output_budget_failures = _first_int(
            failure_payload.get("prior_output_budget_failures"),
            retry_payload.get("prior_output_budget_failures"),
            payload.get("prior_output_budget_failures"),
        )
        output_budget_failure_count = _first_int(
            failure_payload.get("output_budget_failure_count"),
            retry_payload.get("output_budget_failure_count"),
            payload.get("output_budget_failure_count"),
        )
        automatic_output_budget_attempt_count = _first_int(
            failure_payload.get("automatic_output_budget_attempt_count"),
            retry_payload.get("automatic_output_budget_attempt_count"),
            payload.get("automatic_output_budget_attempt_count"),
        )
        automatic_output_budget_budget = _first_int(
            failure_payload.get("automatic_output_budget_budget"),
            retry_payload.get("automatic_output_budget_budget"),
            payload.get("automatic_output_budget_budget"),
        )
        diagnostic_payload = (
            response_payload
            if response is not None
            else failure_payload
            if failure is not None
            else stream_payload
        )
        raw_generation_policy_contract_status = _first_str(
            diagnostic_payload.get("model_generation_policy_contract_status"),
            payload.get("model_generation_policy_contract_status"),
        )
        generation_policy_contract_status = (
            raw_generation_policy_contract_status
            if raw_generation_policy_contract_status in {"supported", "legacy_disabled"}
            else None
        )
        raw_generation_policy_enforcement = _first_str(
            diagnostic_payload.get("model_generation_policy_enforcement"),
            payload.get("model_generation_policy_enforcement"),
        )
        generation_policy_enforcement = (
            raw_generation_policy_enforcement
            if raw_generation_policy_enforcement in {"observe_only", "disabled"}
            else None
        )
        raw_generation_policy_reasoning_parameter_mode = _first_str(
            diagnostic_payload.get("model_generation_policy_reasoning_parameter_mode"),
            payload.get("model_generation_policy_reasoning_parameter_mode"),
        )
        generation_policy_reasoning_parameter_mode = (
            raw_generation_policy_reasoning_parameter_mode
            if raw_generation_policy_reasoning_parameter_mode
            == "inherit_frozen_model_configuration"
            else None
        )
        raw_generation_policy_profile = _first_str(
            diagnostic_payload.get("model_generation_policy_profile"),
            payload.get("model_generation_policy_profile"),
        )
        generation_policy_profile = (
            raw_generation_policy_profile
            if raw_generation_policy_profile
            in {
                "strategic_full",
                "recoverable_public_speech",
                "isolated_auxiliary",
            }
            else None
        )
        raw_generation_policy_profile_source = _first_str(
            diagnostic_payload.get("model_generation_policy_profile_source"),
            payload.get("model_generation_policy_profile_source"),
        )
        generation_policy_profile_source = (
            raw_generation_policy_profile_source
            if raw_generation_policy_profile_source
            in {
                "explicit_action_profile",
                "default_profile",
                "legacy_missing_contract",
            }
            else None
        )
        shadow_would_timeout = diagnostic_payload.get("shadow_would_timeout")
        if not isinstance(shadow_would_timeout, bool):
            shadow_would_timeout = payload.get("shadow_would_timeout")
        if not isinstance(shadow_would_timeout, bool):
            shadow_would_timeout = None
        raw_finish_reason = diagnostic_payload.get("finish_reason")
        finish_reason = (
            raw_finish_reason
            if raw_finish_reason
            in {
                "completed",
                "stop",
                "length",
                "max_output_tokens",
                "content_filter",
                "tool_calls",
                "unknown",
            }
            else None
        )
        raw_usage_consistency = diagnostic_payload.get("usage_consistency")
        usage_consistency = (
            raw_usage_consistency
            if raw_usage_consistency in {"exact", "provider_total_mismatch", "unavailable"}
            else None
        )
        raw_automatic_retry_stop_reason = failure_payload.get("automatic_retry_stop_reason")
        automatic_retry_stop_reason = (
            raw_automatic_retry_stop_reason
            if raw_automatic_retry_stop_reason
            in {
                "not_retryable",
                "decision_family_budget_exhausted",
                "attempt_limit_reached",
                "insufficient_action_budget",
            }
            else None
        )
        failure_episode = failure_episodes_by_attempt.get(attempt_key)
        has_model_failure = attempt_key in failures
        failure_resolution = (
            failure_episode.resolution
            if failure_episode is not None
            else "legacy_unavailable"
            if has_model_failure
            else None
        )
        resolution_updated_at_record_seq = (
            failure_episode.resolution_updated_at_record_seq
            if failure_episode is not None
            else None
        )
        failure_impact = classify_model_failure_impact(
            has_failure=failure is not None,
            failure_code=(
                failure_payload.get("failure_code")
                if isinstance(failure_payload.get("failure_code"), str)
                else None
            ),
            failure_category=(
                failure_payload.get("failure_category")
                if isinstance(failure_payload.get("failure_category"), str)
                else None
            ),
            failure_stage=(
                failure_payload.get("failure_stage")
                if isinstance(failure_payload.get("failure_stage"), str)
                else None
            ),
            failure_resolution=failure_resolution,
            provider_activity_observed=(
                headers_event is not None
                or first_token is not None
                or first_text is not None
                or bool(stream_progresses.get(attempt_key))
                or response is not None
            ),
        )
        if status == "failed" and failure_impact.display_status is not None:
            status = failure_impact.display_status
        result.append(
            AdminModelRequestResponse(
                attempt_id=attempt_id,
                decision_family_id=(
                    payload.get("decision_family_id")
                    if isinstance(payload.get("decision_family_id"), str)
                    else (
                        context.get("decision_family_id")
                        if isinstance(context.get("decision_family_id"), str)
                        else None
                    )
                ),
                retry_scope=retry_scope,
                vote_batch_stage=vote_batch_stage,
                automatic_machine_format_attempt_count=(
                    failed_automatic_count
                    if failed_automatic_count is not None
                    else started_automatic_count
                ),
                automatic_machine_format_budget=(
                    failed_automatic_budget
                    if failed_automatic_budget is not None
                    else started_automatic_budget
                ),
                prior_output_budget_failures=prior_output_budget_failures,
                output_budget_failure_count=output_budget_failure_count,
                automatic_output_budget_attempt_count=(automatic_output_budget_attempt_count),
                automatic_output_budget_budget=automatic_output_budget_budget,
                attempt_no=_first_int(payload.get("attempt_no")) or 1,
                cycle_attempt_no=cycle_attempt_no,
                retry_cycle=retry_cycle,
                max_attempts=_first_int(payload.get("max_attempts")) or 1,
                retry_of_attempt_id=(
                    payload.get("retry_of_attempt_id")
                    if isinstance(payload.get("retry_of_attempt_id"), str)
                    else None
                ),
                record_seq=start.record_seq,
                last_record_seq=max(
                    start.record_seq,
                    last_record_seq_by_attempt.get(attempt_key, 0),
                    last_record_seq_by_action.get(action_key, 0),
                    resolution_updated_at_record_seq or 0,
                ),
                action_id=action_id,
                run_id=start.run_id,
                phase_id=str(context.get("phase_id") or "unknown"),
                action_type=str(context.get("action_type") or "unknown"),
                actor_kind=str(actor_kind),
                actor_id=str(actor_id),
                audience=effective_audience,
                stored_audience=stored_audience,
                effective_audience=effective_audience,
                audience_source=audience_source,
                request_kind=request_kind,
                model_id=model_id,
                model_provider=(
                    payload.get("model_provider")
                    if isinstance(payload.get("model_provider"), str)
                    else None
                ),
                judge_configuration_version=(
                    payload.get("judge_configuration_version")
                    if isinstance(payload.get("judge_configuration_version"), int)
                    else None
                ),
                prompt_schema_version=prompt_schema_version,
                model_context_schema_version=model_context_schema_version,
                prompt_template_version=prompt_template_version,
                model_view_selector_version=model_view_selector_version,
                prompt_projection=prompt_projection,
                output_enforcement=(
                    payload.get("output_enforcement")
                    if isinstance(payload.get("output_enforcement"), dict)
                    else None
                ),
                status=status,
                request_payload=request_payload,
                expanded_known_events=expanded_known_events,
                known_events_expansion_status=known_events_expansion_status,
                input_source=input_source,
                raw_response=raw_response,
                parsed_output=parsed_output,
                passive_observation_count=len(passive_observations),
                passive_observations=passive_observations,
                stream_reasoning=stream_snapshot["reasoning"],
                stream_text=stream_snapshot["text"],
                stream_reasoning_character_count=(stream_snapshot["reasoning_character_count"]),
                stream_text_character_count=stream_snapshot["text_character_count"],
                stream_estimated_reasoning_tokens=(stream_snapshot["estimated_reasoning_tokens"]),
                stream_estimated_output_tokens=stream_snapshot["estimated_output_tokens"],
                stream_content_truncated=stream_snapshot["content_truncated"],
                stream_progress_updated_at=stream_snapshot["updated_at"],
                output_source=output_source,
                provider_request_id=(
                    provider_request_id if isinstance(provider_request_id, str) else None
                ),
                model_generation_policy_contract_status=(generation_policy_contract_status),
                model_generation_policy_schema_version=_first_int(
                    diagnostic_payload.get("model_generation_policy_schema_version"),
                    payload.get("model_generation_policy_schema_version"),
                ),
                model_generation_policy_classification_version=_first_int(
                    diagnostic_payload.get("model_generation_policy_classification_version"),
                    payload.get("model_generation_policy_classification_version"),
                ),
                model_generation_policy_enforcement=(generation_policy_enforcement),
                model_generation_policy_reasoning_parameter_mode=(
                    generation_policy_reasoning_parameter_mode
                ),
                model_generation_policy_profile=generation_policy_profile,
                model_generation_policy_profile_source=(generation_policy_profile_source),
                reasoning_only_timeout_ms=_first_int(
                    diagnostic_payload.get("reasoning_only_timeout_ms"),
                    payload.get("reasoning_only_timeout_ms"),
                ),
                timeout_max_attempts=_first_int(
                    diagnostic_payload.get("timeout_max_attempts"),
                    payload.get("timeout_max_attempts"),
                ),
                shadow_would_timeout=shadow_would_timeout,
                finish_reason=finish_reason,
                provider_usage=_admin_provider_usage(diagnostic_payload.get("provider_usage")),
                usage_update_count=_first_int(diagnostic_payload.get("usage_update_count")),
                usage_conflict_observed=(
                    diagnostic_payload.get("usage_conflict_observed")
                    if isinstance(diagnostic_payload.get("usage_conflict_observed"), bool)
                    else None
                ),
                usage_consistency=usage_consistency,
                queue_wait_ms=_first_int(
                    diagnostic_payload.get("queue_wait_ms"),
                ),
                provider_in_flight=_first_int(
                    diagnostic_payload.get("provider_in_flight"),
                ),
                provider_concurrency_limit=_first_int(
                    diagnostic_payload.get("provider_concurrency_limit"),
                ),
                first_token_ms=_first_int(
                    response_payload.get("first_token_ms"),
                    first_payload.get("first_token_ms"),
                    failure_payload.get("first_token_ms"),
                ),
                reasoning_only_elapsed_ms=_first_int(
                    diagnostic_payload.get("reasoning_only_elapsed_ms"),
                ),
                completed_ms=_first_int(
                    response_payload.get("completed_ms"),
                    tts_payload.get("sentence_ms"),
                ),
                reasoning_delta_count=_first_int(
                    diagnostic_payload.get("reasoning_delta_count"),
                ),
                text_delta_count=_first_int(
                    diagnostic_payload.get("text_delta_count"),
                ),
                max_inter_delta_ms=_first_int(
                    diagnostic_payload.get("max_inter_delta_ms"),
                ),
                last_progress_ms=_first_int(
                    diagnostic_payload.get("last_progress_ms"),
                ),
                failure_kind=(
                    failure_payload.get("failure_kind")
                    if isinstance(failure_payload.get("failure_kind"), str)
                    else None
                ),
                failure_code=(
                    failure_payload.get("failure_code")
                    if isinstance(failure_payload.get("failure_code"), str)
                    else None
                ),
                failure_category=(
                    failure_payload.get("failure_category")
                    if isinstance(failure_payload.get("failure_category"), str)
                    else None
                ),
                failure_impact=failure_impact.failure_impact,
                counts_as_failure=failure_impact.counts_as_failure,
                repair_kind=(
                    response_payload.get("repair_kind")
                    if isinstance(response_payload.get("repair_kind"), str)
                    else None
                ),
                application_validation_result=(
                    response_payload.get("application_validation_result")
                    if response_payload.get("application_validation_result")
                    in {"accepted", "rejected"}
                    else failure_payload.get("application_validation_result")
                    if failure_payload.get("application_validation_result")
                    in {"accepted", "rejected"}
                    else None
                ),
                retryable=(
                    failure_payload.get("retryable")
                    if isinstance(failure_payload.get("retryable"), bool)
                    else None
                ),
                terminal=(
                    failure_payload.get("terminal")
                    if isinstance(failure_payload.get("terminal"), bool)
                    else None
                ),
                failure_stage=(
                    failure_payload.get("failure_stage")
                    if isinstance(failure_payload.get("failure_stage"), str)
                    else None
                ),
                exception_type=(
                    failure_payload.get("exception_type")
                    if isinstance(failure_payload.get("exception_type"), str)
                    else None
                ),
                errno=_first_int(failure_payload.get("errno")),
                http_status=_first_int(failure_payload.get("http_status")),
                first_token_seen=(
                    failure_payload.get("first_token_seen")
                    if isinstance(failure_payload.get("first_token_seen"), bool)
                    else (True if first_token is not None else None)
                ),
                response_headers_seen=(
                    failure_payload.get("response_headers_seen")
                    if isinstance(
                        failure_payload.get("response_headers_seen"),
                        bool,
                    )
                    else (True if headers_event is not None else None)
                ),
                response_headers=(
                    headers_payload.get("response_headers")
                    if isinstance(headers_payload.get("response_headers"), dict)
                    else (
                        failure_payload.get("response_headers")
                        if isinstance(failure_payload.get("response_headers"), dict)
                        else None
                    )
                ),
                first_token_kind=(
                    first_payload.get("first_token_kind")
                    if isinstance(first_payload.get("first_token_kind"), str)
                    else (
                        failure_payload.get("first_token_kind")
                        if isinstance(failure_payload.get("first_token_kind"), str)
                        else None
                    )
                ),
                first_visible_text_ms=_first_int(
                    first_text_payload.get("first_visible_text_ms"),
                    failure_payload.get("first_visible_text_ms"),
                ),
                timeout_scope=(
                    failure_payload.get("timeout_scope")
                    if isinstance(failure_payload.get("timeout_scope"), str)
                    else None
                ),
                failure_elapsed_ms=_first_int(failure_payload.get("elapsed_ms")),
                attempt_budget_ms=_first_int(
                    failure_payload.get("attempt_budget_ms"),
                    payload.get("attempt_budget_ms"),
                ),
                action_budget_ms=_first_int(
                    failure_payload.get("action_budget_ms"),
                    payload.get("action_budget_ms"),
                ),
                action_elapsed_ms=_first_int(
                    failure_payload.get("action_elapsed_ms"),
                ),
                action_remaining_ms=_first_int(
                    failure_payload.get("action_remaining_ms"),
                    payload.get("action_remaining_ms"),
                ),
                effective_attempt_limit=_first_int(
                    failure_payload.get("effective_attempt_limit"),
                ),
                retry_delay_ms=_first_int(
                    failure_payload.get("retry_delay_ms"),
                ),
                required_retry_window_ms=_first_int(
                    failure_payload.get("required_retry_window_ms"),
                ),
                automatic_retry_scheduled=(
                    failure_payload.get("automatic_retry_scheduled")
                    if isinstance(failure_payload.get("automatic_retry_scheduled"), bool)
                    else None
                ),
                automatic_retry_stop_reason=automatic_retry_stop_reason,
                failure_episode_id=(
                    failure_episode.failure_episode_id if failure_episode is not None else None
                ),
                failure_resolution=failure_resolution,
                failure_episode_source_attempt_ids=(
                    list(failure_episode.source_attempt_ids)
                    if failure_episode is not None
                    else None
                ),
                failure_episode_source_event_refs=(
                    [
                        {
                            "event_type": ref.event_type,
                            "event_id": ref.event_id,
                            "record_seq": ref.record_seq,
                        }
                        for ref in failure_episode.source_event_refs
                    ]
                    if failure_episode is not None
                    else None
                ),
                failure_episode_terminal_event_refs=(
                    [
                        {
                            "event_type": ref.event_type,
                            "event_id": ref.event_id,
                            "record_seq": ref.record_seq,
                        }
                        for ref in failure_episode.terminal_event_refs
                    ]
                    if failure_episode is not None
                    else None
                ),
                resolution_event_type=(
                    failure_episode.resolution_event_type if failure_episode is not None else None
                ),
                resolution_event_id=(
                    _first_int(failure_episode.resolution_event_id)
                    if failure_episode is not None
                    else None
                ),
                resolution_event_record_seq=(
                    failure_episode.resolution_event_record_seq
                    if failure_episode is not None
                    else None
                ),
                supporting_event_type=(
                    failure_episode.supporting_event_type if failure_episode is not None else None
                ),
                supporting_event_id=(
                    _first_int(failure_episode.supporting_event_id)
                    if failure_episode is not None
                    else None
                ),
                supporting_event_record_seq=(
                    failure_episode.supporting_event_record_seq
                    if failure_episode is not None
                    else None
                ),
                resolution_updated_at_record_seq=resolution_updated_at_record_seq,
                failure_episode_invariant_errors=(
                    list(failure_episode.invariant_errors) if failure_episode is not None else None
                ),
                model_binding_failure_streak=binding_failure_streak,
                model_binding_health_status=binding_health_status,
                model_binding_recovered_after_failures=(binding_recovered_after_failures),
                started_at=start.created_at,
                completed_at=completed_at,
            )
        )
    return result


def _admin_model_request_audience(
    *,
    payload: dict[str, Any],
    context: dict[str, Any],
    presentation: object | None,
) -> tuple[
    str | None,
    str,
    Literal[
        "event_contract",
        "event_contract_narrowed",
        "presentation",
        "legacy_event",
        "action_context",
        "legacy_unknown",
    ],
]:
    raw_stored_audience = payload.get("audience")
    stored_audience = raw_stored_audience if isinstance(raw_stored_audience, str) else None
    if (
        payload.get("audience_contract_version") == AUDIENCE_CONTRACT_VERSION
        and isinstance(stored_audience, str)
        and stored_audience in EVENT_AUDIENCES
    ):
        actor_kind = payload.get("actor_kind")
        effective_audience = model_event_audience(
            action_audience=stored_audience,
            actor_kind=actor_kind if isinstance(actor_kind, str) else "unknown",
        )
        source: Literal["event_contract", "event_contract_narrowed"] = (
            "event_contract" if effective_audience == stored_audience else "event_contract_narrowed"
        )
        return stored_audience, effective_audience, source
    candidates: tuple[
        tuple[object, Literal["presentation", "legacy_event", "action_context"]],
        ...,
    ] = (
        (getattr(presentation, "audience", None), "presentation"),
        (raw_stored_audience, "legacy_event"),
        (context.get("audience"), "action_context"),
    )
    for candidate, source in candidates:
        if isinstance(candidate, str) and candidate in EVENT_AUDIENCES:
            return stored_audience, candidate, source
    return stored_audience, "legacy_unknown", "legacy_unknown"


def _first_int(*values: object) -> int | None:
    return next(
        (value for value in values if isinstance(value, int) and not isinstance(value, bool)),
        None,
    )


def _first_str(*values: object) -> str | None:
    return next((value for value in values if isinstance(value, str)), None)


def _admin_provider_usage(value: object) -> dict[str, int] | None:
    if not isinstance(value, dict):
        return None
    normalized = {
        key: item
        for key in (
            "input_tokens",
            "output_tokens",
            "reasoning_tokens",
            "total_tokens",
            "cached_input_tokens",
        )
        for item in (value.get(key),)
        if isinstance(item, int) and not isinstance(item, bool) and item >= 0
    }
    return normalized or None


def _admin_model_stream_snapshot(
    events: list[object],
    *,
    include_content: bool,
) -> dict[str, Any]:
    reasoning_parts: list[str] = []
    text_parts: list[str] = []
    last_payload: dict[str, Any] = {}
    updated_at: datetime | None = None
    for event in events if include_content else events[-1:]:
        payload = event.payload if isinstance(event.payload, dict) else {}
        if include_content:
            reasoning_delta = payload.get("reasoning_delta")
            text_delta = payload.get("text_delta")
            if isinstance(reasoning_delta, str):
                reasoning_parts.append(reasoning_delta)
            if isinstance(text_delta, str):
                text_parts.append(text_delta)
        last_payload = payload
        candidate_updated_at = getattr(event, "created_at", None)
        if isinstance(candidate_updated_at, datetime):
            updated_at = candidate_updated_at

    reasoning = "".join(reasoning_parts)
    text = "".join(text_parts)
    reasoning_character_count = _first_int(last_payload.get("reasoning_character_count"))
    text_character_count = _first_int(last_payload.get("text_character_count"))
    if reasoning_character_count is None:
        reasoning_character_count = len(reasoning)
    if text_character_count is None:
        text_character_count = len(text)
    content_truncated = (
        len(reasoning) > _ADMIN_STREAM_CONTENT_LIMIT
        or len(text) > _ADMIN_STREAM_CONTENT_LIMIT
        or reasoning_character_count > len(reasoning)
        or text_character_count > len(text)
    )
    return {
        "reasoning": reasoning[:_ADMIN_STREAM_CONTENT_LIMIT] or None,
        "text": text[:_ADMIN_STREAM_CONTENT_LIMIT] or None,
        "reasoning_character_count": reasoning_character_count,
        "text_character_count": text_character_count,
        "estimated_reasoning_tokens": _first_int(last_payload.get("estimated_reasoning_tokens")),
        "estimated_output_tokens": _first_int(last_payload.get("estimated_output_tokens")),
        "content_truncated": content_truncated,
        "updated_at": updated_at,
        "last_payload": last_payload,
    }


def _record_fields(value: object, *names: str) -> dict[str, object]:
    return {name: getattr(value, name) for name in names}


def _set_admin_headers(request: Request, response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    response.headers["X-Request-ID"] = request_id_for(request)


def _audit_v2_control_rejection(
    db: Session,
    *,
    request: Request,
    principal: AdminPrincipal,
    game_id: str,
    reason: str,
    code: str,
    audit_action: str = "admin.v2_game.stop",
) -> None:
    record_audit_event(
        db,
        request=request,
        actor_user_id=principal.user.id,
        action=audit_action,
        resource_type="v2_game",
        resource_id=game_id,
        result="rejected",
        reason=reason,
        after={"code": code},
    )
    db.commit()


def _v2_control_problem(exc: GameControlError) -> AdminAPIProblem:
    if isinstance(exc, GameControlNotFound):
        return AdminAPIProblem(
            status_code=404,
            code=exc.code,
            title="V2 game not found",
            detail="The requested V2 game does not exist.",
        )
    if isinstance(exc, GameControlIdempotencyConflict):
        return AdminAPIProblem(
            status_code=409,
            code=exc.code,
            title="Idempotency conflict",
            detail="This idempotency key was already used for another control request.",
        )
    if isinstance(exc, GameStopAlreadyRequested):
        detail = "A stop request is already pending for this V2 game."
    elif isinstance(exc, GameModelActionNotPaused):
        detail = "Only a V2 game paused on a recoverable model error can be retried."
    elif isinstance(exc, GameControlNotActive):
        detail = "Only an active V2 game can be stopped."
    else:
        detail = "The V2 game stop request was rejected."
    return AdminAPIProblem(
        status_code=409,
        code=exc.code,
        title="V2 game control rejected",
        detail=detail,
    )


def _valid_game_id(game_id: str) -> bool:
    if not game_id.startswith("v2_game_") or len(game_id) != len("v2_game_") + 16:
        return False
    return all(character in "0123456789abcdef" for character in game_id[8:])


def _bearer_token(authorization: str | None) -> str | None:
    if authorization is None:
        return None
    scheme, separator, token = authorization.partition(" ")
    if separator != " " or scheme.lower() != "bearer" or not token:
        return None
    return token


def _god_view_websocket_token(websocket: WebSocket) -> str | None:
    protocols = websocket.scope.get("subprotocols")
    if (
        not isinstance(protocols, list)
        or len(protocols) != 2
        or protocols[0] != GOD_VIEW_WEBSOCKET_SUBPROTOCOL
    ):
        return None
    token = protocols[1]
    return token if isinstance(token, str) and token else None


def _live_state(
    status: str,
) -> Literal[
    "waiting_to_start",
    "ready",
    "generating",
    "broadcasting",
    "finalizing",
    "awaiting_observation",
    "paused_model_error",
    "canceled",
    "failed",
]:
    if status in {
        "waiting_to_start",
        "ready",
        "generating",
        "broadcasting",
        "finalizing",
        "awaiting_observation",
        "paused_model_error",
        "canceled",
    }:
        return status
    return "failed"


def _game_phase(game: object) -> GamePhaseResponse:
    return GamePhaseResponse(
        phase_seq=game.phase_seq,
        phase_id=game.phase_id,
        phase_state=game.phase_state,
    )


def _match_state(match: object | None) -> MatchStateResponse | None:
    if match is None:
        return None
    return MatchStateResponse(
        round_no=match.round_no,
        sheriff_player_id=match.sheriff_player_id,
        sheriff_badge_state=match.sheriff_badge_state,
        winner=match.winner,
    )
