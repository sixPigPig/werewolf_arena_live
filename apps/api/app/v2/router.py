from __future__ import annotations

import math
from pathlib import Path
from typing import Annotated, Literal

from fastapi import (
    APIRouter,
    Depends,
    Header,
    HTTPException,
    Path as PathParameter,
    Query,
    Request,
    Response,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.admin.rbac import AdminPermission
from app.api.admin.dependencies import AdminPrincipal, require_admin_permission
from app.api.admin.errors import AdminAPIProblem, request_id_for
from app.core.config import settings
from app.db.session import get_db
from app.v2.contracts import (
    AdminV2EventResponse,
    AdminV2GameDetailResponse,
    AdminV2GameListItem,
    AdminV2GameListResponse,
    AdminV2Pagination,
    AdminV2PresentationResponse,
    AdminV2RunResponse,
    AdminV2VoiceAssetResponse,
    V2ActorResponse,
    V2ApiMetaResponse,
    V2CurrentPresentationResponse,
    V2GameCreateRequest,
    V2GameCreateResponse,
    V2GamePhaseResponse,
    V2GodViewIdentitySnapshotResponse,
    V2LiveSnapshotResponse,
)
from app.v2.god_view_projection import project_god_view_player_identities
from app.v2.live_runtime import V2ClientProtocolError, V2LiveRuntime
from app.v2.public_projection import (
    project_public_player_seats,
    project_public_role_assignment_status,
    project_public_rule_snapshot,
)
from app.v2.service import (
    V2GodViewAccessDenied,
    V2GodViewUnavailable,
    V2RecordNotFound,
    V2VoiceAssetUnavailable,
    authorize_god_view,
    create_ready_game,
    current_presentation,
    game_detail,
    get_game,
    get_voice_asset,
    god_view_role_assignments,
    list_games,
    player_state_map,
    role_assignment_count,
    server_now,
    voice_asset_path,
)


public_router = APIRouter()
god_view_router = APIRouter()
admin_router = APIRouter()
GAME_ID_PATTERN = r"v2_game_[0-9a-f]{16}"
VOICE_ID_PATTERN = r"v2_voice_[0-9a-f]{16}"
GOD_VIEW_WEBSOCKET_SUBPROTOCOL = "live-v2-god-view"


def get_v2_voice_root() -> Path:
    return Path(settings.live_v2_voice_storage_dir)


@public_router.get("/meta", response_model=V2ApiMetaResponse)
def read_v2_meta(response: Response) -> V2ApiMetaResponse:
    response.headers["Cache-Control"] = "no-store"
    return V2ApiMetaResponse()


@public_router.post("/games", response_model=V2GameCreateResponse, status_code=201)
def create_v2_game(
    body: V2GameCreateRequest,
    db: Annotated[Session, Depends(get_db)],
) -> V2GameCreateResponse:
    lobby = body.lobby_snapshot
    rule_snapshot = None
    players_snapshot = None
    if lobby is not None:
        rule_snapshot = {
            "schema_version": lobby.schema_version,
            "source": "existing_mobile_lobby",
            "rule_set_revision_id": lobby.rule_set_revision_id,
            "seed": lobby.seed,
            "max_rounds": lobby.max_rounds,
            "allow_lineup_quality_warnings": lobby.allow_lineup_quality_warnings,
            "lineup_quality_report": lobby.lineup_quality_report.model_dump(mode="json"),
            "rule_set": lobby.rule_set.model_dump(mode="json", exclude_none=True),
        }
        players_snapshot = [
            item.model_dump(mode="json", exclude_none=True) for item in lobby.player_configs
        ]
    game, run, god_view_access_token = create_ready_game(
        db,
        title=body.title,
        rule_snapshot=rule_snapshot,
        players_snapshot=players_snapshot,
    )
    return V2GameCreateResponse(
        game_id=game.game_id,
        run_id=run.run_id,
        status=game.status,
        snapshot_url=f"/api/v2/live/games/{game.game_id}/snapshot",
        websocket_url=f"/api/v2/live/games/{game.game_id}/ws",
        god_view_snapshot_url=(f"/api/v2/god-view/games/{game.game_id}/identity-snapshot"),
        god_view_websocket_url=f"/api/v2/god-view/games/{game.game_id}/ws",
        god_view_access_token=god_view_access_token,
    )


@public_router.get(
    "/live/games/{game_id}/snapshot",
    response_model=V2LiveSnapshotResponse,
)
def read_live_snapshot(
    game_id: Annotated[str, PathParameter(pattern=GAME_ID_PATTERN)],
    request: Request,
    response: Response,
    db: Annotated[Session, Depends(get_db)],
) -> V2LiveSnapshotResponse:
    try:
        game = get_game(db, game_id)
        presentation = current_presentation(db, game_id)
    except V2RecordNotFound as exc:
        raise HTTPException(status_code=404, detail="V2 game not found") from exc
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["X-Request-ID"] = request_id_for(request)
    return V2LiveSnapshotResponse(
        audience="player_public",
        game_id=game.game_id,
        run_id=game.current_run_id,
        live_state=_live_state(game.status),
        game_phase=_game_phase(game),
        latest_presentation_seq=game.last_presentation_seq,
        server_time=server_now(),
        public_rule=project_public_rule_snapshot(game.rule_snapshot),
        public_players=project_public_player_seats(game.players_snapshot),
        public_role_assignment=project_public_role_assignment_status(
            role_assignment_count(db, game.game_id)
        ),
        current_presentation=(
            V2CurrentPresentationResponse(
                action_id=presentation.action_id,
                presentation_seq=presentation.presentation_seq,
                presentation_id=presentation.presentation_id,
                phase_id=presentation.phase_id,
                actor=V2ActorResponse(
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


@public_router.websocket("/live/games/{game_id}/ws")
async def live_websocket(websocket: WebSocket, game_id: str) -> None:
    if not _valid_game_id(game_id):
        await websocket.close(code=4404)
        return
    await websocket.accept()
    runtime: V2LiveRuntime = websocket.app.state.v2_live_runtime
    subscriber_id: str | None = None
    channel = None
    try:
        subscriber_id, channel = await runtime.connect(game_id=game_id, websocket=websocket)
        while True:
            message = await websocket.receive_json()
            if not isinstance(message, dict):
                raise V2ClientProtocolError("message_must_be_object")
            await runtime.ready(
                channel=channel,
                subscriber_id=subscriber_id,
                message=message,
            )
    except V2RecordNotFound:
        await websocket.close(code=4404)
    except V2ClientProtocolError:
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
    except V2GodViewAccessDenied:
        await websocket.close(code=4403)
        return

    await websocket.accept(subprotocol=GOD_VIEW_WEBSOCKET_SUBPROTOCOL)
    runtime: V2LiveRuntime = websocket.app.state.v2_live_runtime
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
                raise V2ClientProtocolError("message_must_be_object")
            await runtime.ready(
                channel=channel,
                subscriber_id=subscriber_id,
                message=message,
            )
    except V2RecordNotFound:
        await websocket.close(code=4404)
    except V2GodViewUnavailable:
        await websocket.close(code=4409)
    except V2ClientProtocolError:
        await websocket.close(code=4400)
    except WebSocketDisconnect:
        pass
    finally:
        if subscriber_id is not None and channel is not None:
            await runtime.disconnect(channel=channel, subscriber_id=subscriber_id)


@god_view_router.get(
    "/god-view/games/{game_id}/identity-snapshot",
    response_model=V2GodViewIdentitySnapshotResponse,
)
def read_god_view_identity_snapshot(
    game_id: Annotated[str, PathParameter(pattern=GAME_ID_PATTERN)],
    request: Request,
    response: Response,
    db: Annotated[Session, Depends(get_db)],
    authorization: Annotated[str | None, Header()] = None,
) -> V2GodViewIdentitySnapshotResponse:
    try:
        authorize_god_view(
            db,
            game_id=game_id,
            token=_bearer_token(authorization),
        )
    except V2GodViewAccessDenied as exc:
        raise HTTPException(status_code=403, detail="God view access denied") from exc
    try:
        game = get_game(db, game_id)
        assignments = god_view_role_assignments(db, game_id)
    except V2RecordNotFound as exc:
        raise HTTPException(status_code=404, detail="V2 game not found") from exc
    except V2GodViewUnavailable as exc:
        raise HTTPException(status_code=409, detail="God view identity unavailable") from exc

    response.headers["Cache-Control"] = "private, no-store"
    response.headers["X-Request-ID"] = request_id_for(request)
    return V2GodViewIdentitySnapshotResponse(
        game_id=game.game_id,
        run_id=game.current_run_id,
        live_state=_live_state(game.status),
        game_phase=_game_phase(game),
        server_time=server_now(),
        rule=project_public_rule_snapshot(game.rule_snapshot),
        players=project_god_view_player_identities(
            players_snapshot=game.players_snapshot,
            assignments=assignments,
            player_states=player_state_map(db, game_id),
        ),
    )


@admin_router.get("/games", response_model=AdminV2GameListResponse)
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
) -> AdminV2GameListResponse:
    records, total = list_games(db, page=page, page_size=page_size)
    _set_admin_headers(request, response)
    return AdminV2GameListResponse(
        items=[_admin_game_item(record) for record in records],
        pagination=AdminV2Pagination(
            page=page,
            page_size=page_size,
            total=total,
            pages=math.ceil(total / page_size) if total else 0,
        ),
    )


@admin_router.get("/games/{game_id}", response_model=AdminV2GameDetailResponse)
def read_admin_v2_game(
    game_id: Annotated[str, PathParameter(pattern=GAME_ID_PATTERN)],
    request: Request,
    response: Response,
    db: Annotated[Session, Depends(get_db)],
    _principal: Annotated[
        AdminPrincipal,
        Depends(require_admin_permission(AdminPermission.V2_GAMES_READ)),
    ],
) -> AdminV2GameDetailResponse:
    try:
        (
            game,
            runs,
            events,
            presentations,
            voices,
            player_states,
            action_windows,
            ability_instances,
            ability_activations,
            effect_intents,
            knowledge_facts,
        ) = game_detail(db, game_id)
    except V2RecordNotFound as exc:
        raise AdminAPIProblem(
            status_code=404,
            code="admin_v2_game_not_found",
            title="V2 game not found",
            detail="The requested V2 game record does not exist.",
        ) from exc
    _set_admin_headers(request, response)
    return AdminV2GameDetailResponse(
        **_admin_game_item(game).model_dump(),
        rule_snapshot=game.rule_snapshot,
        players_snapshot=game.players_snapshot,
        ability_snapshot=game.ability_snapshot,
        runs=[AdminV2RunResponse.model_validate(run, from_attributes=True) for run in runs],
        events=[
            AdminV2EventResponse.model_validate(event, from_attributes=True) for event in events
        ],
        presentations=[
            AdminV2PresentationResponse.model_validate(item, from_attributes=True)
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
    except V2RecordNotFound as exc:
        raise HTTPException(status_code=404, detail="V2 voice asset not found") from exc
    except V2VoiceAssetUnavailable as exc:
        raise HTTPException(status_code=409, detail="V2 voice asset is not ready") from exc
    return FileResponse(
        path,
        media_type=asset.mime_type,
        headers={"Cache-Control": "private, no-store"},
    )


def _admin_game_item(record: object) -> AdminV2GameListItem:
    return AdminV2GameListItem.model_validate(record, from_attributes=True)


def _admin_voice_asset(asset: object) -> AdminV2VoiceAssetResponse:
    value = AdminV2VoiceAssetResponse.model_validate(
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


def _record_fields(value: object, *names: str) -> dict[str, object]:
    return {name: getattr(value, name) for name in names}


def _set_admin_headers(request: Request, response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    response.headers["X-Request-ID"] = request_id_for(request)


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
    "ready",
    "generating",
    "broadcasting",
    "finalizing",
    "awaiting_observation",
    "failed",
]:
    if status in {
        "ready",
        "generating",
        "broadcasting",
        "finalizing",
        "awaiting_observation",
    }:
        return status
    return "failed"


def _game_phase(game: object) -> V2GamePhaseResponse:
    return V2GamePhaseResponse(
        phase_seq=game.phase_seq,
        phase_id=game.phase_id,
        phase_state=game.phase_state,
    )
