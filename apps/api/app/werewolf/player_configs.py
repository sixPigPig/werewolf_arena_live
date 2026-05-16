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
    personality_id = (
        _override_string(overrides, "personality_id")
        or _profile_string(profile, "personality_id")
        or "balanced"
    )
    explicit_personality = (
        _override_string(overrides, "personality")
        or _override_string(overrides, "personality_text")
    )
    personality = (
        explicit_personality
        or _profile_string(profile, "personality_text")
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
        tags=_tags_from_value(
            overrides["tags"] if "tags" in overrides else getattr(profile, "tags", ())
        ),
    )


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
