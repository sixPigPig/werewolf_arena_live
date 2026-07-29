from __future__ import annotations

from datetime import datetime

from app.models.virtual_player_profile import VirtualPlayerProfile
from app.werewolf.player_avatar_assets import avatar_asset_url


def admin_player_profile_snapshot(profile: VirtualPlayerProfile) -> dict[str, object]:
    return {
        "id": profile.id,
        "display_name": profile.display_name,
        "model_provider": profile.model_provider,
        "model": profile.model,
        "personality_id": profile.personality_id,
        "personality_text": profile.personality_text,
        "appearance_id": profile.appearance_id,
        "avatar_asset_id": profile.avatar_asset_id,
        "avatar_image_url": _admin_avatar_image_url(profile),
        "avatar_image_mime": profile.avatar_image_mime,
        "short_description": profile.short_description,
        "background_story": profile.background_story,
        "speaking_style": profile.speaking_style,
        "gender": profile.gender,
        "tts_speaker": profile.tts_speaker or None,
        "tts_dialect": profile.tts_dialect or None,
        "base_delivery_mood": profile.base_delivery_mood,
        "base_delivery_intensity": profile.base_delivery_intensity,
        "base_delivery_pace": profile.base_delivery_pace,
        "base_delivery_instruction": profile.base_delivery_instruction or None,
        "voice_enabled": profile.voice_enabled,
        "voice_config_version": profile.voice_config_version,
        "strategy_profile": profile.strategy_profile,
        "risk_tolerance": profile.risk_tolerance,
        "bluffing_tendency": profile.bluffing_tendency,
        "trust_tendency": profile.trust_tendency,
        "leadership_tendency": profile.leadership_tendency,
        "talkativeness": profile.talkativeness,
        "example_messages": list(profile.example_messages),
        "display_order": profile.display_order,
        "featured": profile.featured,
        "tags": list(profile.tags),
        "status": profile.status,
        "version": profile.version,
        "created_at": profile.created_at,
        "updated_at": profile.updated_at,
        "published_at": profile.published_at,
        "deleted_at": profile.deleted_at,
        "published_by": _actor_id(profile.published_by_user_id),
        "updated_by": _actor_id(profile.updated_by_user_id),
    }


def public_player_profile_snapshot(profile: VirtualPlayerProfile) -> dict[str, object]:
    return {
        "id": profile.id,
        "display_name": profile.display_name,
        "model_provider": profile.model_provider,
        "model": profile.model,
        "personality_id": profile.personality_id,
        "personality_text": profile.personality_text,
        "appearance_id": profile.appearance_id,
        "avatar_image_url": _public_avatar_image_url(profile),
        "short_description": profile.short_description,
        "background_story": profile.background_story,
        "speaking_style": profile.speaking_style,
        "strategy_profile": profile.strategy_profile,
        "risk_tolerance": profile.risk_tolerance,
        "bluffing_tendency": profile.bluffing_tendency,
        "trust_tendency": profile.trust_tendency,
        "leadership_tendency": profile.leadership_tendency,
        "talkativeness": profile.talkativeness,
        "example_messages": list(profile.example_messages),
        "display_order": profile.display_order,
        "featured": profile.featured,
        "tags": list(profile.tags),
    }


def audit_player_profile_snapshot(profile: VirtualPlayerProfile) -> dict[str, object]:
    snapshot = admin_player_profile_snapshot(profile)
    return {key: _json_value(value) for key, value in snapshot.items()}


def _admin_avatar_image_url(profile: VirtualPlayerProfile) -> str:
    if profile.avatar_asset_id:
        return avatar_asset_url(profile.avatar_asset_id)
    return ""


def _public_avatar_image_url(profile: VirtualPlayerProfile) -> str:
    if profile.avatar_asset_id:
        return avatar_asset_url(profile.avatar_asset_id)
    return ""


def _actor_id(value: int | None) -> str | None:
    return str(value) if value is not None else None


def _json_value(value: object) -> object:
    if isinstance(value, datetime):
        return value.isoformat()
    return value
