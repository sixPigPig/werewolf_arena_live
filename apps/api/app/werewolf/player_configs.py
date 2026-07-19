from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.werewolf.player_avatar_assets import avatar_asset_url
from app.werewolf.player_profile_prompts import compose_player_profile_prompt
from app.werewolf.player_presets import default_personality_text


@dataclass(frozen=True)
class PlayerConfig:
    seat: int
    profile_id: str | None
    name: str
    model: str
    personality_id: str
    personality: str
    appearance_id: str
    avatar_prompt: str
    tags: tuple[str, ...]
    avatar_image_url: str = ""
    avatar_asset_id: str | None = None
    catchphrases: tuple[str, ...] = ()
    strategy_profile: str = "balanced"
    tts_speaker: str = ""
    tts_dialect: str = ""
    base_delivery_mood: str = "neutral"
    base_delivery_intensity: str = "medium"
    base_delivery_pace: str = "natural"
    base_delivery_instruction: str = ""
    voice_enabled: bool = True
    voice_config_version: int = 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "seat": self.seat,
            "profile_id": self.profile_id,
            "name": self.name,
            "model": self.model,
            "personality_id": self.personality_id,
            "personality": self.personality,
            "appearance_id": self.appearance_id,
            "avatar_prompt": self.avatar_prompt,
            "avatar_image_url": self.avatar_image_url,
            "avatar_asset_id": self.avatar_asset_id,
            "catchphrases": list(self.catchphrases),
            "strategy_profile": self.strategy_profile,
            "tts_speaker": self.tts_speaker,
            "tts_dialect": self.tts_dialect,
            "base_delivery_mood": self.base_delivery_mood,
            "base_delivery_intensity": self.base_delivery_intensity,
            "base_delivery_pace": self.base_delivery_pace,
            "base_delivery_instruction": self.base_delivery_instruction,
            "voice_enabled": self.voice_enabled,
            "voice_config_version": self.voice_config_version,
            "tags": list(self.tags),
        }


def clean_optional_string(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        value = str(value)
    cleaned = value.strip()
    return cleaned or None


def player_config_from_profile(
    seat: int,
    profile: object | None,
    overrides: dict[str, Any] | None = None,
) -> PlayerConfig:
    overrides = overrides or {}
    override_personality_id = _override_string(overrides, "personality_id")
    profile_personality_id = _profile_string(profile, "personality_id")
    personality_id = override_personality_id or profile_personality_id or "balanced"
    explicit_personality = (
        _override_string(overrides, "personality")
        or _override_string(overrides, "personality_text")
    )
    profile_personality = None
    if override_personality_id is None or override_personality_id == profile_personality_id:
        profile_personality = _profile_string(profile, "personality_text")
    if explicit_personality:
        personality = explicit_personality
    else:
        base_personality = profile_personality or default_personality_text(personality_id)
        personality = (
            compose_player_profile_prompt(profile, base_personality)
            if profile is not None
            else base_personality
        )
    profile_id = (
        _override_string(overrides, "profile_id")
        or _profile_string(profile, "id")
    )

    return PlayerConfig(
        seat=seat,
        profile_id=profile_id,
        name=(
            _override_string(overrides, "name")
            or _override_string(overrides, "display_name")
            or _profile_string(profile, "display_name")
            or ""
        ),
        model=_override_string(overrides, "model") or _profile_string(profile, "model") or "",
        personality_id=personality_id,
        personality=personality,
        appearance_id=(
            _override_string(overrides, "appearance_id")
            or _profile_string(profile, "appearance_id")
            or "default"
        ),
        avatar_prompt=(
            _override_string(overrides, "avatar_prompt")
            or _profile_string(profile, "avatar_prompt")
            or ""
        ),
        avatar_image_url=(
            _override_string(overrides, "avatar_image_url")
            or _profile_avatar_image_url(profile)
            or ""
        ),
        avatar_asset_id=(
            _override_string(overrides, "avatar_asset_id")
            or _profile_string(profile, "avatar_asset_id")
        ),
        catchphrases=_tags_from_value(
            overrides["catchphrases"]
            if "catchphrases" in overrides
            else getattr(profile, "catchphrases", ())
        ),
        strategy_profile=(
            _override_string(overrides, "strategy_profile")
            or _profile_string(profile, "strategy_profile")
            or "balanced"
        ),
        tts_speaker=(
            _override_string(overrides, "tts_speaker")
            or _profile_string(profile, "tts_speaker")
            or ""
        ),
        tts_dialect=(
            _override_string(overrides, "tts_dialect")
            or _profile_string(profile, "tts_dialect")
            or ""
        ),
        base_delivery_mood=(
            _override_string(overrides, "base_delivery_mood")
            or _profile_string(profile, "base_delivery_mood")
            or "neutral"
        ),
        base_delivery_intensity=(
            _override_string(overrides, "base_delivery_intensity")
            or _profile_string(profile, "base_delivery_intensity")
            or "medium"
        ),
        base_delivery_pace=(
            _override_string(overrides, "base_delivery_pace")
            or _profile_string(profile, "base_delivery_pace")
            or "natural"
        ),
        base_delivery_instruction=(
            _override_string(overrides, "base_delivery_instruction")
            or _profile_string(profile, "base_delivery_instruction")
            or ""
        ),
        voice_enabled=(
            _override_bool(overrides, "voice_enabled", default=True)
            if "voice_enabled" in overrides
            else _profile_bool(profile, "voice_enabled", default=True)
        ),
        voice_config_version=_profile_int(
            profile,
            "voice_config_version",
            default=_profile_int(profile, "version", default=1),
        ),
        tags=_tags_from_value(
            overrides["tags"] if "tags" in overrides else getattr(profile, "tags", ())
        ),
    )


def player_config_from_dict(data: dict[str, Any]) -> PlayerConfig:
    return PlayerConfig(
        seat=int(data["seat"]),
        profile_id=clean_optional_string(data.get("profile_id")),
        name=clean_optional_string(data.get("name")) or "",
        model=clean_optional_string(data.get("model")) or "",
        personality_id=clean_optional_string(data.get("personality_id")) or "balanced",
        personality=clean_optional_string(data.get("personality")) or "",
        appearance_id=clean_optional_string(data.get("appearance_id")) or "default",
        avatar_prompt=clean_optional_string(data.get("avatar_prompt")) or "",
        avatar_image_url=clean_optional_string(data.get("avatar_image_url")) or "",
        avatar_asset_id=clean_optional_string(data.get("avatar_asset_id")),
        catchphrases=_tags_from_value(data.get("catchphrases")),
        strategy_profile=clean_optional_string(data.get("strategy_profile")) or "balanced",
        tts_speaker=clean_optional_string(data.get("tts_speaker")) or "",
        tts_dialect=clean_optional_string(data.get("tts_dialect")) or "",
        base_delivery_mood=(
            clean_optional_string(data.get("base_delivery_mood")) or "neutral"
        ),
        base_delivery_intensity=(
            clean_optional_string(data.get("base_delivery_intensity")) or "medium"
        ),
        base_delivery_pace=(
            clean_optional_string(data.get("base_delivery_pace")) or "natural"
        ),
        base_delivery_instruction=(
            clean_optional_string(data.get("base_delivery_instruction")) or ""
        ),
        voice_enabled=_bool_from_value(data.get("voice_enabled"), default=True),
        voice_config_version=_int_from_value(
            data.get("voice_config_version"),
            default=1,
        ),
        tags=_tags_from_value(data.get("tags")),
    )


def player_configs_from_serialized(value: object) -> list[PlayerConfig]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError("player_configs must be a list")
    configs: list[PlayerConfig] = []
    for item in value:
        if not isinstance(item, dict):
            raise ValueError("player_configs must contain objects")
        configs.append(player_config_from_dict(item))
    return configs


def validate_unique_player_config_seats(player_configs: list[PlayerConfig] | None) -> None:
    seen: set[int] = set()
    for config in player_configs or []:
        if config.seat in seen:
            raise ValueError(f"Duplicate player config seat: {config.seat}")
        seen.add(config.seat)


def validate_unique_effective_player_names(
    *,
    default_names: list[str],
    player_configs: list[PlayerConfig] | None,
) -> None:
    validate_unique_player_config_seats(player_configs)
    configs_by_seat = {config.seat: config for config in player_configs or []}
    seen: set[str] = set()
    for seat, default_name in enumerate(default_names, start=1):
        player_config = configs_by_seat.get(seat)
        player_name = player_config.name if player_config and player_config.name else default_name
        if player_name in seen:
            raise ValueError(f"Duplicate player name: {player_name}")
        seen.add(player_name)


def _override_string(overrides: dict[str, Any], key: str) -> str | None:
    if key not in overrides:
        return None
    return clean_optional_string(overrides[key])


def _profile_string(profile: object | None, key: str) -> str | None:
    if profile is None:
        return None
    return clean_optional_string(getattr(profile, key, None))


def _override_bool(overrides: dict[str, Any], key: str, *, default: bool) -> bool:
    if key not in overrides:
        return default
    return _bool_from_value(overrides.get(key), default=default)


def _profile_bool(
    profile: object | None,
    key: str,
    *,
    default: bool,
) -> bool:
    if profile is None:
        return default
    return _bool_from_value(getattr(profile, key, None), default=default)


def _profile_int(profile: object | None, key: str, *, default: int) -> int:
    if profile is None:
        return default
    return _int_from_value(getattr(profile, key, None), default=default)


def _bool_from_value(value: object, *, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes", "on"}:
            return True
        if normalized in {"false", "0", "no", "off"}:
            return False
    return default


def _int_from_value(value: object, *, default: int) -> int:
    if isinstance(value, bool):
        return default
    try:
        parsed = int(value) if value is not None else default
    except (TypeError, ValueError, OverflowError):
        return default
    return max(1, parsed)


def _profile_avatar_image_url(profile: object | None) -> str | None:
    if profile is None:
        return None
    avatar_asset_id = clean_optional_string(getattr(profile, "avatar_asset_id", None))
    if avatar_asset_id is not None:
        return avatar_asset_url(avatar_asset_id)
    return None


def _tags_from_value(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, (list, tuple)):
        return ()
    tags: list[str] = []
    seen: set[str] = set()
    for item in value:
        tag = clean_optional_string(item)
        if tag is None or tag in seen:
            continue
        tags.append(tag)
        seen.add(tag)
    return tuple(tags)
