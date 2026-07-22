from __future__ import annotations

import math
from pathlib import Path
from typing import Annotated, Literal

from fastapi import (
    APIRouter,
    Depends,
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
    V2LiveSnapshotResponse,
)
from app.v2.live_runtime import V2ClientProtocolError, V2LiveRuntime
from app.v2.service import (
    V2RecordNotFound,
    V2VoiceAssetUnavailable,
    create_ready_game,
    current_presentation,
    game_detail,
    get_game,
    get_voice_asset,
    list_games,
    server_now,
    voice_asset_path,
)


public_router = APIRouter()
admin_router = APIRouter()
GAME_ID_PATTERN = r"v2_game_[0-9a-f]{16}"
VOICE_ID_PATTERN = r"v2_voice_[0-9a-f]{16}"


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
    game, run = create_ready_game(
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
        latest_presentation_seq=game.last_presentation_seq,
        server_time=server_now(),
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
        game, runs, events, presentations, voices = game_detail(db, game_id)
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
        runs=[AdminV2RunResponse.model_validate(run, from_attributes=True) for run in runs],
        events=[AdminV2EventResponse.model_validate(event, from_attributes=True) for event in events],
        presentations=[
            AdminV2PresentationResponse.model_validate(item, from_attributes=True)
            for item in presentations
        ],
        voice_assets=[_admin_voice_asset(item) for item in voices],
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
                f"/api/v1/admin/v2/games/{asset.game_id}/voice-assets/"
                f"{asset.voice_asset_id}/audio"
            )
        }
    )


def _set_admin_headers(request: Request, response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    response.headers["X-Request-ID"] = request_id_for(request)


def _valid_game_id(game_id: str) -> bool:
    if not game_id.startswith("v2_game_") or len(game_id) != len("v2_game_") + 16:
        return False
    return all(character in "0123456789abcdef" for character in game_id[8:])


def _live_state(status: str) -> Literal[
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
