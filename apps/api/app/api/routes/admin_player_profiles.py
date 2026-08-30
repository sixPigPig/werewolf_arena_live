from __future__ import annotations

import base64
from collections.abc import AsyncIterator, Callable
from dataclasses import replace
import logging
import time
from typing import Annotated, Protocol

from fastapi import APIRouter, Depends, Path, Query, Request, Response
from sqlalchemy import select
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
from app.api.schemas.admin_player_profiles import (
    AdminPlayerProfileAiDraftRequest,
    AdminPlayerProfileAiDraftResponse,
    AdminPlayerProfileCreate,
    AdminPlayerProfileListResponse,
    AdminPlayerProfileMove,
    AdminPlayerProfileOptionsResponse,
    AdminPlayerProfileResponse,
    AdminPlayerProfileTransition,
    AdminPlayerProfileUpdate,
    AdminPlayerTtsSpeakersResponse,
    AdminPlayerVoicePreviewRequest,
    AdminPlayerVoicePreviewResponse,
    PlayerProfileSort,
    PlayerProfileStatus,
)
from app.api.routes.player_profiles import (
    PlayerProfileAiDraftRequest,
    PlayerProfileAiInvalidResponse,
    PlayerProfileAiProviderUnavailable,
    generate_ai_player_draft,
    get_player_profile_ai_provider,
)
from app.core.config import settings
from app.db.session import get_db
from app.models.model_configuration import ModelConfigurationRecord
from app.models.virtual_player_profile import VirtualPlayerProfile
from app.player_profiles.errors import (
    PlayerProfileNotFound,
    PlayerProfileTransitionError,
    PlayerProfileValidationError,
    PlayerProfileVersionConflict,
)
from app.player_profiles.service import (
    archive_player_profile,
    create_player_profile,
    current_player_profile_version,
    get_player_profile,
    list_admin_player_profiles,
    move_published_player_profile,
    publish_player_profile,
    restore_player_profile,
    update_player_profile,
)
from app.player_profiles.snapshots import (
    admin_player_profile_snapshot,
    audit_player_profile_snapshot,
)
from app.shared.player_avatar_assets import SYSTEM_AVATAR_ASSET_IDS, avatar_asset_url
from app.shared.player_presets import (
    APPEARANCE_PRESETS,
    PERSONALITY_PRESETS,
    STRATEGY_LABELS,
    STRATEGY_PRESETS,
)
from app.shared.speech_delivery import (
    DELIVERY_MAPPING_VERSION,
    compile_context_texts,
    normalize_delivery,
)
from app.shared.tts_speaker_catalog import (
    TtsSpeakerCatalogUnavailable,
    VolcengineTtsSpeakerCatalog,
    dialects_for_tts_speaker,
    gender_for_tts_speaker,
    tts_speaker_catalog,
)
from app.shared.tts_text import chunk_text_for_tts
from app.shared.volcengine_tts import (
    TtsSynthesisItem,
    VolcengineTtsClient,
    VolcengineTtsConfig,
    mime_type_for_format,
    supports_tts_context_texts,
)

router = APIRouter()
RecoverableDatabaseError = (OperationalError, ProgrammingError)
logger = logging.getLogger(__name__)
PLAYER_VOICE_PREVIEW_AUDIO_FORMAT = "mp3"
PLAYER_VOICE_PREVIEW_MAX_AUDIO_BYTES = 2 * 1024 * 1024
PROFILE_TTS_CONTEXT_UNSUPPORTED_DETAIL = (
    "tts_speaker is incompatible with the configured TTS resource; "
    "delivery context requires a seed-tts-2.0 preset *_uranus_bigtts speaker"
)


class PlayerVoicePreviewTtsClient(Protocol):
    async def synthesize(
        self,
        *,
        speaker: str,
        text_chunks: list[str],
        context_texts: list[str] | tuple[str, ...] | None = None,
        dialect: str = "",
    ) -> AsyncIterator[TtsSynthesisItem]: ...


def get_player_voice_preview_tts_config() -> VolcengineTtsConfig:
    return VolcengineTtsConfig(
        enabled=settings.ark_tts_enabled,
        api_key=settings.ark_tts_api_key,
        resource_id=settings.ark_tts_resource_id,
        ws_url=settings.ark_tts_ws_url,
        player_speaker=settings.ark_tts_player_speaker,
        judge_speaker=settings.ark_tts_judge_speaker,
        audio_format=PLAYER_VOICE_PREVIEW_AUDIO_FORMAT,
        sample_rate=settings.ark_tts_sample_rate,
    )


def get_player_voice_preview_client_factory() -> Callable[
    [VolcengineTtsConfig], PlayerVoicePreviewTtsClient
]:
    return VolcengineTtsClient


def get_tts_speaker_catalog() -> VolcengineTtsSpeakerCatalog:
    return tts_speaker_catalog


@router.post(
    "/player-profile-voice-previews",
    response_model=AdminPlayerVoicePreviewResponse,
)
async def preview_player_profile_voice(
    request_body: AdminPlayerVoicePreviewRequest,
    request: Request,
    response: Response,
    _principal: Annotated[
        AdminPrincipal,
        Depends(require_admin_permission(AdminPermission.PLAYERS_WRITE)),
    ],
    _csrf: Annotated[AdminPrincipal, Depends(require_admin_csrf)],
    config: Annotated[
        VolcengineTtsConfig,
        Depends(get_player_voice_preview_tts_config),
    ],
    client_factory: Annotated[
        Callable[[VolcengineTtsConfig], PlayerVoicePreviewTtsClient],
        Depends(get_player_voice_preview_client_factory),
    ],
) -> AdminPlayerVoicePreviewResponse:
    if not config.available:
        raise _voice_preview_problem(
            status_code=503,
            code="admin_player_voice_preview_unavailable",
            title="Voice preview unavailable",
            detail="语音试听服务未启用或配置不完整，请联系管理员。",
        )

    speaker = request_body.speaker or config.player_speaker.strip()
    if (
        not speaker.startswith("zh_")
        or gender_for_tts_speaker(speaker) is None
        or not supports_tts_context_texts(
            resource_id=config.resource_id,
            speaker=speaker,
        )
    ):
        raise _voice_preview_problem(
            status_code=422,
            code="admin_player_voice_preview_context_unsupported",
            title="Voice preview speaker unsupported",
            detail="当前仅支持 seed-tts-2.0 预置大模型音色的安全演绎试听。",
        )

    base_delivery = normalize_delivery(
        request_body.base_delivery.model_dump(exclude_none=True)
    )
    effective_delivery = normalize_delivery(
        request_body.turn_delivery.model_dump(exclude_none=True),
        base_mood=str(base_delivery["mood"]),
        base_intensity=str(base_delivery["intensity"]),
        base_pace=str(base_delivery["pace"]),
        base_instruction=str(base_delivery["instruction"]),
    )
    try:
        _ensure_tts_dialect_supported(
            speaker=speaker,
            dialect=request_body.dialect,
        )
    except PlayerProfileValidationError as exc:
        raise _voice_preview_problem(
            status_code=422,
            code="admin_player_voice_preview_dialect_unsupported",
            title="Voice preview dialect unsupported",
            detail="所选音色不支持这个方言，请重新选择。",
        ) from exc
    context_texts = compile_context_texts(
        effective_delivery,
        dialect=request_body.dialect or "",
    )
    audio = bytearray()
    started_at = time.monotonic()
    try:
        client = client_factory(replace(config, audio_format=PLAYER_VOICE_PREVIEW_AUDIO_FORMAT))
        async for item in client.synthesize(
            speaker=speaker,
            text_chunks=chunk_text_for_tts(request_body.say),
            context_texts=context_texts,
            dialect=request_body.dialect or "",
        ):
            if not isinstance(item, bytes):
                continue
            if len(item) > PLAYER_VOICE_PREVIEW_MAX_AUDIO_BYTES - len(audio):
                raise _voice_preview_problem(
                    status_code=502,
                    code="admin_player_voice_preview_audio_too_large",
                    title="Voice preview audio too large",
                    detail="试听音频超过安全大小限制，请缩短测试文本后重试。",
                )
            audio.extend(item)
    except AdminAPIProblem:
        raise
    except Exception as exc:
        logger.warning("Player voice preview provider failed")
        raise _voice_preview_problem(
            status_code=502,
            code="admin_player_voice_preview_failed",
            title="Voice preview failed",
            detail="语音供应商未能完成试听，请稍后重试。",
        ) from exc

    if not audio:
        raise _voice_preview_problem(
            status_code=502,
            code="admin_player_voice_preview_empty_audio",
            title="Voice preview returned no audio",
            detail="语音供应商未返回可播放音频，请稍后重试。",
        )

    elapsed_ms = max(0, round((time.monotonic() - started_at) * 1000))
    _set_private_headers(request, response)
    return AdminPlayerVoicePreviewResponse(
        speaker=speaker,
        dialect=request_body.dialect,
        effective_delivery=effective_delivery,
        context_texts=context_texts,
        delivery_mapping_version=DELIVERY_MAPPING_VERSION,
        audio_format=PLAYER_VOICE_PREVIEW_AUDIO_FORMAT,
        mime_type=mime_type_for_format(PLAYER_VOICE_PREVIEW_AUDIO_FORMAT),
        sample_rate=config.sample_rate,
        elapsed_ms=elapsed_ms,
        audio_byte_length=len(audio),
        audio_base64=base64.b64encode(audio).decode("ascii"),
    )


@router.post(
    "/player-profile-ai-drafts",
    response_model=AdminPlayerProfileAiDraftResponse,
)
def generate_admin_player_profile_ai_draft(
    request_body: AdminPlayerProfileAiDraftRequest,
    request: Request,
    response: Response,
    db: Annotated[Session, Depends(get_db)],
    principal: Annotated[
        AdminPrincipal,
        Depends(require_admin_permission(AdminPermission.PLAYERS_AI_GENERATE)),
    ],
    _csrf: Annotated[AdminPrincipal, Depends(require_admin_csrf)],
    provider: Annotated[object, Depends(get_player_profile_ai_provider)],
) -> AdminPlayerProfileAiDraftResponse:
    try:
        existing_names = list(
            db.scalars(
                select(VirtualPlayerProfile.display_name)
                .order_by(VirtualPlayerProfile.updated_at.desc())
                .limit(200)
            )
        )
        draft = generate_ai_player_draft(
            PlayerProfileAiDraftRequest(
                mode=request_body.mode,
                existing_names=existing_names,
            ),
            provider,
        )
        record_audit_event(
            db,
            request=request,
            actor_user_id=principal.user.id,
            action="admin.player_profile.ai_draft.generate",
            resource_type="player_profile_ai_draft",
            resource_id=None,
            result="success",
            after={"mode": request_body.mode, "display_name": draft.display_name},
        )
        db.commit()
    except PlayerProfileAiProviderUnavailable as exc:
        _record_ai_draft_failure(
            db,
            request=request,
            principal=principal,
            mode=request_body.mode,
            reason="provider_unavailable",
        )
        raise AdminAPIProblem(
            status_code=503,
            code="admin_player_ai_provider_unavailable",
            title="AI draft provider unavailable",
            detail="The AI draft provider is temporarily unavailable.",
        ) from exc
    except PlayerProfileAiInvalidResponse as exc:
        _record_ai_draft_failure(
            db,
            request=request,
            principal=principal,
            mode=request_body.mode,
            reason="invalid_provider_response",
        )
        raise AdminAPIProblem(
            status_code=502,
            code="admin_player_ai_response_invalid",
            title="AI draft response invalid",
            detail="The provider returned an invalid player draft.",
        ) from exc
    except RecoverableDatabaseError as exc:
        db.rollback()
        raise _database_unavailable() from exc
    _set_private_headers(request, response)
    return AdminPlayerProfileAiDraftResponse.model_validate(draft.model_dump())


@router.get("/player-profiles", response_model=AdminPlayerProfileListResponse)
def list_profiles(
    request: Request,
    response: Response,
    db: Annotated[Session, Depends(get_db)],
    _principal: Annotated[
        AdminPrincipal,
        Depends(require_admin_permission(AdminPermission.PLAYERS_READ)),
    ],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    q: Annotated[str | None, Query(max_length=120)] = None,
    status: PlayerProfileStatus | None = None,
    model: Annotated[str | None, Query(max_length=120)] = None,
    personality_id: Annotated[str | None, Query(max_length=40)] = None,
    sort: PlayerProfileSort = "display_order",
) -> AdminPlayerProfileListResponse:
    try:
        result = list_admin_player_profiles(
            db,
            page=page,
            page_size=page_size,
            query_text=q,
            status=status,
            model=model,
            personality_id=personality_id,
            sort=sort,
        )
    except RecoverableDatabaseError as exc:
        raise _database_unavailable() from exc
    _set_private_headers(request, response)
    return AdminPlayerProfileListResponse(
        items=[admin_player_profile_snapshot(profile) for profile in result.items],
        pagination={
            "page": result.page,
            "page_size": result.page_size,
            "total": result.total,
            "pages": result.pages,
        },
    )


@router.get("/player-profile-options", response_model=AdminPlayerProfileOptionsResponse)
def get_profile_options(
    request: Request,
    response: Response,
    db: Annotated[Session, Depends(get_db)],
    _principal: Annotated[
        AdminPrincipal,
        Depends(require_admin_permission(AdminPermission.PLAYERS_READ)),
    ],
) -> AdminPlayerProfileOptionsResponse:
    _set_private_headers(request, response)
    try:
        model_configurations = list(
            db.scalars(
                select(ModelConfigurationRecord)
                .where(
                    ModelConfigurationRecord.available.is_(True),
                    ModelConfigurationRecord.enabled.is_(True),
                )
                .order_by(
                    ModelConfigurationRecord.is_default.desc(),
                    ModelConfigurationRecord.provider,
                    ModelConfigurationRecord.model_id,
                )
            )
        )
    except RecoverableDatabaseError as exc:
        raise _database_unavailable() from exc
    return AdminPlayerProfileOptionsResponse(
        models=[
            {
                "provider": item.provider,
                "model_id": item.model_id,
                "label": (
                    f"{_model_provider_label(item.provider)} · "
                    f"{item.display_name or item.model_id}"
                ),
                "description": item.description or "",
            }
            for item in model_configurations
        ],
        personalities=[
            {
                "id": preset.id,
                "label": preset.label,
                "description": preset.description,
            }
            for preset in PERSONALITY_PRESETS.values()
        ],
        appearances=[
            {
                "id": preset.id,
                "label": preset.label,
                "description": preset.description,
                "avatar_asset_id": SYSTEM_AVATAR_ASSET_IDS.get(preset.id),
                "avatar_image_url": (
                    avatar_asset_url(SYSTEM_AVATAR_ASSET_IDS[preset.id])
                    if preset.id in SYSTEM_AVATAR_ASSET_IDS
                    else ""
                ),
            }
            for preset in APPEARANCE_PRESETS.values()
        ],
        strategies=[
            {
                "id": strategy_id,
                "label": STRATEGY_LABELS[strategy_id],
                "description": description,
            }
            for strategy_id, description in STRATEGY_PRESETS.items()
        ],
        constraints={
            "tags_max_items": 8,
            "tag_max_length": 20,
            "example_messages_max_items": 5,
            "example_message_max_length": 240,
        },
    )


@router.get(
    "/player-profile-tts-speakers",
    response_model=AdminPlayerTtsSpeakersResponse,
)
def get_profile_tts_speakers(
    request: Request,
    response: Response,
    _principal: Annotated[
        AdminPrincipal,
        Depends(require_admin_permission(AdminPermission.PLAYERS_READ)),
    ],
    catalog: Annotated[
        VolcengineTtsSpeakerCatalog,
        Depends(get_tts_speaker_catalog),
    ],
) -> AdminPlayerTtsSpeakersResponse:
    try:
        items = catalog.list_supported(resource_id=settings.ark_tts_resource_id)
    except TtsSpeakerCatalogUnavailable as exc:
        raise AdminAPIProblem(
            status_code=503,
            code="admin_player_tts_speakers_unavailable",
            title="TTS speaker catalog unavailable",
            detail="无法从火山引擎读取可用音色列表，请稍后重试。",
        ) from exc
    _set_private_headers(request, response)
    return AdminPlayerTtsSpeakersResponse(
        resource_id=settings.ark_tts_resource_id,
        items=[
            {
                "voice_type": item.voice_type,
                "name": item.name,
                "gender": item.gender,
                "dialects": [
                    {"id": dialect.id, "label": dialect.label}
                    for dialect in item.dialects
                ],
            }
            for item in items
        ],
    )


@router.post(
    "/player-profiles",
    response_model=AdminPlayerProfileResponse,
    status_code=201,
)
def create_profile(
    request_body: AdminPlayerProfileCreate,
    request: Request,
    response: Response,
    db: Annotated[Session, Depends(get_db)],
    principal: Annotated[
        AdminPrincipal,
        Depends(require_admin_permission(AdminPermission.PLAYERS_WRITE)),
    ],
    _csrf: Annotated[AdminPrincipal, Depends(require_admin_csrf)],
) -> AdminPlayerProfileResponse:
    try:
        _ensure_profile_tts_context_capability(
            requested_speaker=request_body.tts_speaker,
            gender=request_body.gender,
            dialect=request_body.tts_dialect,
        )
        profile = create_player_profile(
            db,
            values=request_body.model_dump(),
            initial_status="draft",
            actor_user_id=principal.user.id,
            allow_external_avatar_url=False,
        )
        after = audit_player_profile_snapshot(profile)
        record_audit_event(
            db,
            request=request,
            actor_user_id=principal.user.id,
            action="admin.player_profile.create",
            resource_type="player_profile",
            resource_id=profile.id,
            result="success",
            after=after,
        )
        db.commit()
        db.refresh(profile)
    except PlayerProfileValidationError as exc:
        _record_failed_create(
            db,
            request=request,
            principal=principal,
            request_body=request_body,
            reason=str(exc),
        )
        raise _validation_problem(str(exc)) from exc
    except RecoverableDatabaseError as exc:
        db.rollback()
        raise _database_unavailable() from exc
    _set_private_headers(request, response)
    return AdminPlayerProfileResponse.model_validate(admin_player_profile_snapshot(profile))


@router.get("/player-profiles/{profile_id}", response_model=AdminPlayerProfileResponse)
def get_profile(
    profile_id: Annotated[str, Path(min_length=1, max_length=36)],
    request: Request,
    response: Response,
    db: Annotated[Session, Depends(get_db)],
    _principal: Annotated[
        AdminPrincipal,
        Depends(require_admin_permission(AdminPermission.PLAYERS_READ)),
    ],
) -> AdminPlayerProfileResponse:
    try:
        profile = get_player_profile(db, profile_id)
    except PlayerProfileNotFound as exc:
        raise _not_found() from exc
    except RecoverableDatabaseError as exc:
        raise _database_unavailable() from exc
    _set_private_headers(request, response)
    return AdminPlayerProfileResponse.model_validate(
        admin_player_profile_snapshot(profile)
    )


@router.patch("/player-profiles/{profile_id}", response_model=AdminPlayerProfileResponse)
def update_profile(
    profile_id: Annotated[str, Path(min_length=1, max_length=36)],
    request_body: AdminPlayerProfileUpdate,
    request: Request,
    response: Response,
    db: Annotated[Session, Depends(get_db)],
    principal: Annotated[
        AdminPrincipal,
        Depends(require_admin_permission(AdminPermission.PLAYERS_WRITE)),
    ],
    _csrf: Annotated[AdminPrincipal, Depends(require_admin_csrf)],
) -> AdminPlayerProfileResponse:
    action = "admin.player_profile.update"
    expected_version = request_body.expected_version
    try:
        existing = get_player_profile(db, profile_id)
        updates = request_body.model_dump(exclude_unset=True)
        updates.pop("expected_version")
        if "tts_speaker" in updates and not updates["tts_speaker"]:
            updates.setdefault("tts_dialect", None)
        if {"gender", "tts_speaker", "tts_dialect"} & updates.keys():
            _ensure_profile_tts_context_capability(
                requested_speaker=updates.get("tts_speaker", existing.tts_speaker),
                current_speaker=existing.tts_speaker,
                gender=str(updates.get("gender", existing.gender)),
                current_gender=existing.gender,
                dialect=updates.get("tts_dialect", existing.tts_dialect),
                current_dialect=existing.tts_dialect,
            )
        if existing.status == "published" or "featured" in updates:
            _require_extra_permission(principal, AdminPermission.PLAYERS_PUBLISH)
        before = audit_player_profile_snapshot(existing)
        profile = update_player_profile(
            db,
            profile_id,
            updates=updates,
            expected_version=expected_version,
            actor_user_id=principal.user.id,
            allow_external_avatar_url=False,
        )
        _commit_successful_mutation(
            db,
            request=request,
            principal=principal,
            action=action,
            profile=profile,
            before=before,
        )
    except (
        PlayerProfileNotFound,
        PlayerProfileVersionConflict,
        PlayerProfileTransitionError,
        PlayerProfileValidationError,
    ) as exc:
        _raise_profile_problem(
            db,
            request=request,
            principal=principal,
            action=action,
            profile_id=profile_id,
            exc=exc,
            expected_version=expected_version,
        )
    except RecoverableDatabaseError as exc:
        db.rollback()
        raise _database_unavailable() from exc
    _set_private_headers(request, response)
    return AdminPlayerProfileResponse.model_validate(admin_player_profile_snapshot(profile))


@router.post(
    "/player-profiles/{profile_id}/move",
    response_model=AdminPlayerProfileResponse,
)
def move_profile(
    profile_id: Annotated[str, Path(min_length=1, max_length=36)],
    request_body: AdminPlayerProfileMove,
    request: Request,
    response: Response,
    db: Annotated[Session, Depends(get_db)],
    principal: Annotated[
        AdminPrincipal,
        Depends(require_admin_permission(AdminPermission.PLAYERS_PUBLISH)),
    ],
    _csrf: Annotated[AdminPrincipal, Depends(require_admin_csrf)],
) -> AdminPlayerProfileResponse:
    action = "admin.player_profile.move"
    try:
        existing = get_player_profile(db, profile_id)
        before = audit_player_profile_snapshot(existing)
        profile = move_published_player_profile(
            db,
            profile_id,
            direction=request_body.direction,
            expected_version=request_body.expected_version,
            actor_user_id=principal.user.id,
        )
        _commit_successful_mutation(
            db,
            request=request,
            principal=principal,
            action=action,
            profile=profile,
            before=before,
        )
    except (
        PlayerProfileNotFound,
        PlayerProfileVersionConflict,
        PlayerProfileTransitionError,
        PlayerProfileValidationError,
    ) as exc:
        _raise_profile_problem(
            db,
            request=request,
            principal=principal,
            action=action,
            profile_id=profile_id,
            exc=exc,
            expected_version=request_body.expected_version,
        )
    except RecoverableDatabaseError as exc:
        db.rollback()
        raise _database_unavailable() from exc
    _set_private_headers(request, response)
    return AdminPlayerProfileResponse.model_validate(admin_player_profile_snapshot(profile))


@router.post(
    "/player-profiles/{profile_id}/publish",
    response_model=AdminPlayerProfileResponse,
)
def publish_profile(
    profile_id: Annotated[str, Path(min_length=1, max_length=36)],
    request_body: AdminPlayerProfileTransition,
    request: Request,
    response: Response,
    db: Annotated[Session, Depends(get_db)],
    principal: Annotated[
        AdminPrincipal,
        Depends(require_admin_permission(AdminPermission.PLAYERS_PUBLISH)),
    ],
    _csrf: Annotated[AdminPrincipal, Depends(require_admin_csrf)],
) -> AdminPlayerProfileResponse:
    return _transition_profile(
        profile_id=profile_id,
        request_body=request_body,
        request=request,
        response=response,
        db=db,
        principal=principal,
        action="admin.player_profile.publish",
        transition=publish_player_profile,
    )


@router.post(
    "/player-profiles/{profile_id}/archive",
    response_model=AdminPlayerProfileResponse,
)
def archive_profile(
    profile_id: Annotated[str, Path(min_length=1, max_length=36)],
    request_body: AdminPlayerProfileTransition,
    request: Request,
    response: Response,
    db: Annotated[Session, Depends(get_db)],
    principal: Annotated[
        AdminPrincipal,
        Depends(require_admin_permission(AdminPermission.PLAYERS_ARCHIVE)),
    ],
    _csrf: Annotated[AdminPrincipal, Depends(require_admin_csrf)],
) -> AdminPlayerProfileResponse:
    return _transition_profile(
        profile_id=profile_id,
        request_body=request_body,
        request=request,
        response=response,
        db=db,
        principal=principal,
        action="admin.player_profile.archive",
        transition=archive_player_profile,
    )


@router.post(
    "/player-profiles/{profile_id}/restore",
    response_model=AdminPlayerProfileResponse,
)
def restore_profile(
    profile_id: Annotated[str, Path(min_length=1, max_length=36)],
    request_body: AdminPlayerProfileTransition,
    request: Request,
    response: Response,
    db: Annotated[Session, Depends(get_db)],
    principal: Annotated[
        AdminPrincipal,
        Depends(require_admin_permission(AdminPermission.PLAYERS_ARCHIVE)),
    ],
    _csrf: Annotated[AdminPrincipal, Depends(require_admin_csrf)],
) -> AdminPlayerProfileResponse:
    return _transition_profile(
        profile_id=profile_id,
        request_body=request_body,
        request=request,
        response=response,
        db=db,
        principal=principal,
        action="admin.player_profile.restore",
        transition=restore_player_profile,
    )


def _transition_profile(
    *,
    profile_id: str,
    request_body: AdminPlayerProfileTransition,
    request: Request,
    response: Response,
    db: Session,
    principal: AdminPrincipal,
    action: str,
    transition: Callable[..., VirtualPlayerProfile],
) -> AdminPlayerProfileResponse:
    try:
        existing = get_player_profile(db, profile_id)
        before = audit_player_profile_snapshot(existing)
        profile = transition(
            db,
            profile_id,
            expected_version=request_body.expected_version,
            actor_user_id=principal.user.id,
        )
        _commit_successful_mutation(
            db,
            request=request,
            principal=principal,
            action=action,
            profile=profile,
            before=before,
            reason=request_body.reason,
        )
    except (
        PlayerProfileNotFound,
        PlayerProfileVersionConflict,
        PlayerProfileTransitionError,
        PlayerProfileValidationError,
    ) as exc:
        _raise_profile_problem(
            db,
            request=request,
            principal=principal,
            action=action,
            profile_id=profile_id,
            exc=exc,
            reason=request_body.reason,
            expected_version=request_body.expected_version,
        )
    except RecoverableDatabaseError as exc:
        db.rollback()
        raise _database_unavailable() from exc
    _set_private_headers(request, response)
    return AdminPlayerProfileResponse.model_validate(admin_player_profile_snapshot(profile))


def _commit_successful_mutation(
    db: Session,
    *,
    request: Request,
    principal: AdminPrincipal,
    action: str,
    profile: VirtualPlayerProfile,
    before: dict[str, object] | None,
    reason: str | None = None,
) -> None:
    record_audit_event(
        db,
        request=request,
        actor_user_id=principal.user.id,
        action=action,
        resource_type="player_profile",
        resource_id=profile.id,
        result="success",
        reason=reason,
        before=before,
        after=audit_player_profile_snapshot(profile),
    )
    db.commit()
    db.refresh(profile)


def _raise_profile_problem(
    db: Session,
    *,
    request: Request,
    principal: AdminPrincipal,
    action: str,
    profile_id: str,
    exc: Exception,
    reason: str | None = None,
    expected_version: int | None = None,
) -> None:
    db.rollback()
    current_version = current_player_profile_version(db, profile_id)
    result = "conflict" if isinstance(
        exc,
        (PlayerProfileVersionConflict, PlayerProfileTransitionError),
    ) else "failure"
    record_audit_event(
        db,
        request=request,
        actor_user_id=principal.user.id,
        action=action,
        resource_type="player_profile",
        resource_id=profile_id,
        result=result,
        reason=reason or str(exc),
        after={
            "expected_version": expected_version,
            "current_version": current_version,
        },
    )
    db.commit()
    if isinstance(exc, PlayerProfileNotFound):
        raise _not_found() from exc
    if isinstance(exc, PlayerProfileVersionConflict):
        raise AdminAPIProblem(
            status_code=409,
            code="admin_player_profile_version_conflict",
            title="Player profile changed",
            detail="The player profile was changed by another user. Reload and try again.",
            extensions={"current_version": current_version},
        ) from exc
    if isinstance(exc, PlayerProfileTransitionError):
        raise AdminAPIProblem(
            status_code=409,
            code="admin_player_profile_transition_conflict",
            title="Invalid player profile transition",
            detail=(
                f"A player profile in '{exc.current_status}' status cannot transition "
                f"to '{exc.target_status}'."
            ),
            extensions={"current_version": current_version},
        ) from exc
    if isinstance(exc, PlayerProfileValidationError):
        raise _validation_problem(str(exc)) from exc
    raise exc


def _require_extra_permission(
    principal: AdminPrincipal,
    permission: AdminPermission,
) -> None:
    if permission not in principal.permissions:
        raise AdminAPIProblem(
            status_code=403,
            code="admin_permission_denied",
            title="Permission denied",
            detail=f"The '{permission.value}' permission is required.",
        )


def _model_provider_label(provider: str) -> str:
    return {
        "agent_plan": "火山方舟 Agent Plan",
        "ark": "火山方舟标准推理 API",
        "deepseek": "DeepSeek 官方 API",
    }.get(provider, provider)


def _record_failed_create(
    db: Session,
    *,
    request: Request,
    principal: AdminPrincipal,
    request_body: AdminPlayerProfileCreate,
    reason: str,
) -> None:
    db.rollback()
    record_audit_event(
        db,
        request=request,
        actor_user_id=principal.user.id,
        action="admin.player_profile.create",
        resource_type="player_profile",
        resource_id=None,
        result="failure",
        reason=reason,
        after={
            "display_name": request_body.display_name,
            "model_provider": request_body.model_provider,
            "model": request_body.model,
            "target_status": "draft",
        },
    )
    try:
        db.commit()
    except RecoverableDatabaseError as exc:
        db.rollback()
        raise _database_unavailable() from exc


def _record_ai_draft_failure(
    db: Session,
    *,
    request: Request,
    principal: AdminPrincipal,
    mode: str,
    reason: str,
) -> None:
    db.rollback()
    record_audit_event(
        db,
        request=request,
        actor_user_id=principal.user.id,
        action="admin.player_profile.ai_draft.generate",
        resource_type="player_profile_ai_draft",
        resource_id=None,
        result="failure",
        reason=reason,
        after={"mode": mode},
    )
    try:
        db.commit()
    except RecoverableDatabaseError as exc:
        db.rollback()
        raise _database_unavailable() from exc


def _voice_preview_problem(
    *,
    status_code: int,
    code: str,
    title: str,
    detail: str,
) -> AdminAPIProblem:
    return AdminAPIProblem(
        status_code=status_code,
        code=code,
        title=title,
        detail=detail,
    )


def _ensure_profile_tts_context_capability(
    *,
    requested_speaker: object,
    current_speaker: str | None = None,
    gender: str = "female",
    current_gender: str | None = None,
    dialect: object = None,
    current_dialect: str | None = None,
) -> None:
    speaker = str(requested_speaker or "").strip()
    normalized_dialect = str(dialect or "").strip()
    if not speaker:
        if normalized_dialect:
            raise PlayerProfileValidationError(
                "tts_dialect requires an explicit TTS 2.0 speaker"
            )
        return
    unchanged_legacy_selection = (
        speaker == str(current_speaker or "").strip()
        and gender == str(current_gender or gender)
        and normalized_dialect == str(current_dialect or "").strip()
    )
    if unchanged_legacy_selection:
        return
    expected_gender = gender_for_tts_speaker(speaker)
    if (
        speaker.startswith("zh_")
        and expected_gender is not None
        and supports_tts_context_texts(
            resource_id=settings.ark_tts_resource_id,
            speaker=speaker,
        )
    ):
        if gender != expected_gender:
            raise PlayerProfileValidationError(
                "tts_speaker gender does not match the player gender"
            )
        _ensure_tts_dialect_supported(speaker=speaker, dialect=normalized_dialect)
        return
    raise PlayerProfileValidationError(PROFILE_TTS_CONTEXT_UNSUPPORTED_DETAIL)


def _ensure_tts_dialect_supported(*, speaker: str, dialect: object) -> None:
    normalized = str(dialect or "").strip()
    if not normalized:
        return
    allowed = {item.id for item in dialects_for_tts_speaker(speaker)}
    if normalized not in allowed:
        raise PlayerProfileValidationError(
            "tts_dialect is not supported by the selected TTS 2.0 speaker"
        )


def _set_private_headers(request: Request, response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    response.headers["X-Request-ID"] = request_id_for(request)


def _not_found() -> AdminAPIProblem:
    return AdminAPIProblem(
        status_code=404,
        code="admin_player_profile_not_found",
        title="Player profile not found",
        detail="The requested player profile does not exist.",
    )


def _validation_problem(detail: str) -> AdminAPIProblem:
    return AdminAPIProblem(
        status_code=422,
        code="admin_player_profile_invalid",
        title="Invalid player profile",
        detail=detail,
    )


def _database_unavailable() -> AdminAPIProblem:
    return AdminAPIProblem(
        status_code=503,
        code="admin_player_profile_database_unavailable",
        title="Player profile database unavailable",
        detail="Player profile data is temporarily unavailable.",
    )
