from __future__ import annotations

from dataclasses import dataclass
from typing import Any

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
    personality = (
        explicit_personality
        or profile_personality
        or default_personality_text(personality_id)
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
            or _profile_string(profile, "avatar_image_url")
            or ""
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
