from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


@dataclass
class StoredPlayerProfile:
    id: str
    owner_user_id: int | None
    display_name: str
    model_provider: str
    model: str
    personality_id: str
    personality_text: str
    appearance_id: str
    avatar_prompt: str
    avatar_asset_id: str | None
    avatar_image_url: str
    avatar_image_path: str
    avatar_image_mime: str
    short_description: str
    background_story: str
    speaking_style: str
    catchphrases: list[str]
    strategy_profile: str
    risk_tolerance: int
    bluffing_tendency: int
    trust_tendency: int
    leadership_tendency: int
    talkativeness: int
    example_messages: list[str]
    favorite: bool
    tags: list[str]
    created_at: datetime
    updated_at: datetime


class PlayerProfileFileStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def list_profiles(self) -> list[StoredPlayerProfile]:
        return sorted(
            self._read_profiles(),
            key=lambda profile: (profile.updated_at, profile.id),
            reverse=True,
        )

    def get_profile(self, profile_id: str) -> StoredPlayerProfile | None:
        for profile in self._read_profiles():
            if profile.id == profile_id:
                return profile
        return None

    def _read_profiles(self) -> list[StoredPlayerProfile]:
        if not self.path.exists():
            return []
        data = json.loads(self.path.read_text(encoding="utf-8"))
        raw_profiles = data.get("profiles", []) if isinstance(data, dict) else []
        return [
            profile
            for item in raw_profiles
            if isinstance(item, dict)
            for profile in [_profile_from_payload(item)]
            if profile is not None
        ]

def _profile_from_payload(payload: dict[str, Any]) -> StoredPlayerProfile | None:
    profile_id = _optional_string(payload.get("id"))
    display_name = _optional_string(payload.get("display_name") or payload.get("name"))
    model_provider = _optional_string(payload.get("model_provider"))
    model = _optional_string(payload.get("model"))
    if profile_id is None or display_name is None or model_provider is None or model is None:
        return None

    personality_id = _optional_string(payload.get("personality_id")) or "balanced"
    appearance_id = (
        _optional_string(payload.get("appearance_id") or payload.get("skin_id"))
        or "default"
    )
    created_at = _parse_datetime(payload.get("created_at"))
    return StoredPlayerProfile(
        id=profile_id,
        owner_user_id=_optional_int(payload.get("owner_user_id")),
        display_name=display_name,
        model_provider=model_provider,
        model=model,
        personality_id=personality_id,
        personality_text=str(
            payload.get("personality_text")
            if payload.get("personality_text") is not None
            else payload.get("personality") or ""
        ),
        appearance_id=appearance_id,
        avatar_prompt=str(payload.get("avatar_prompt") or ""),
        avatar_asset_id=_optional_string(payload.get("avatar_asset_id")),
        avatar_image_url=str(payload.get("avatar_image_url") or ""),
        avatar_image_path=str(payload.get("avatar_image_path") or ""),
        avatar_image_mime=str(payload.get("avatar_image_mime") or ""),
        short_description=str(payload.get("short_description") or ""),
        background_story=str(payload.get("background_story") or ""),
        speaking_style=str(payload.get("speaking_style") or ""),
        catchphrases=_strings_from_payload(payload.get("catchphrases")),
        strategy_profile=_optional_string(payload.get("strategy_profile")) or "balanced",
        risk_tolerance=_int_from_payload(payload.get("risk_tolerance"), default=3),
        bluffing_tendency=_int_from_payload(payload.get("bluffing_tendency"), default=3),
        trust_tendency=_int_from_payload(payload.get("trust_tendency"), default=3),
        leadership_tendency=_int_from_payload(payload.get("leadership_tendency"), default=3),
        talkativeness=_int_from_payload(payload.get("talkativeness"), default=3),
        example_messages=_strings_from_payload(payload.get("example_messages")),
        favorite=_bool_from_payload(payload.get("favorite"), default=False),
        tags=_tags_from_payload(payload.get("tags")),
        created_at=created_at,
        updated_at=_parse_datetime(payload.get("updated_at"), fallback=created_at),
    )


def _optional_string(value: object) -> str | None:
    if value is None:
        return None
    cleaned = str(value).strip()
    return cleaned or None


def _optional_int(value: object) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _int_from_payload(value: object, *, default: int) -> int:
    parsed = _optional_int(value)
    if parsed is None:
        return default
    return parsed


def _bool_from_payload(value: object, *, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes", "on"}:
            return True
        if normalized in {"false", "0", "no", "off"}:
            return False
    if value is None:
        return default
    return bool(value)


def _parse_datetime(value: object, fallback: datetime | None = None) -> datetime:
    if isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                return parsed.replace(tzinfo=UTC)
            return parsed
        except ValueError:
            pass
    return fallback or datetime.now(UTC)


def _tags_from_payload(value: object) -> list[str]:
    return _strings_from_payload(value)


def _strings_from_payload(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]
