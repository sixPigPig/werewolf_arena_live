from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


@dataclass
class StoredPlayerProfile:
    id: str
    owner_user_id: int | None
    display_name: str
    model: str
    personality_id: str
    personality_text: str
    appearance_id: str
    avatar_prompt: str
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

    def create_profile(
        self,
        *,
        display_name: str,
        model: str,
        personality_id: str,
        personality_text: str,
        appearance_id: str,
        avatar_prompt: str,
        tags: list[str],
        avatar_image_url: str = "",
        avatar_image_path: str = "",
        avatar_image_mime: str = "",
        short_description: str = "",
        background_story: str = "",
        speaking_style: str = "",
        catchphrases: list[str] | None = None,
        strategy_profile: str = "balanced",
        risk_tolerance: int = 3,
        bluffing_tendency: int = 3,
        trust_tendency: int = 3,
        leadership_tendency: int = 3,
        talkativeness: int = 3,
        example_messages: list[str] | None = None,
        favorite: bool = False,
    ) -> StoredPlayerProfile:
        now = datetime.now(UTC)
        profile = StoredPlayerProfile(
            id=str(uuid.uuid4()),
            owner_user_id=None,
            display_name=display_name,
            model=model,
            personality_id=personality_id,
            personality_text=personality_text,
            appearance_id=appearance_id,
            avatar_prompt=avatar_prompt,
            avatar_image_url=avatar_image_url,
            avatar_image_path=avatar_image_path,
            avatar_image_mime=avatar_image_mime,
            short_description=short_description,
            background_story=background_story,
            speaking_style=speaking_style,
            catchphrases=catchphrases or [],
            strategy_profile=strategy_profile,
            risk_tolerance=risk_tolerance,
            bluffing_tendency=bluffing_tendency,
            trust_tendency=trust_tendency,
            leadership_tendency=leadership_tendency,
            talkativeness=talkativeness,
            example_messages=example_messages or [],
            favorite=favorite,
            tags=tags,
            created_at=now,
            updated_at=now,
        )
        profiles = self._read_profiles()
        profiles.append(profile)
        self._write_profiles(profiles)
        return profile

    def update_profile(
        self,
        profile_id: str,
        updates: dict[str, Any],
    ) -> StoredPlayerProfile | None:
        profiles = self._read_profiles()
        updated_profile: StoredPlayerProfile | None = None
        for profile in profiles:
            if profile.id != profile_id:
                continue
            for field_name, value in updates.items():
                setattr(profile, field_name, value)
            profile.updated_at = datetime.now(UTC)
            updated_profile = profile
            break
        if updated_profile is None:
            return None
        self._write_profiles(profiles)
        return updated_profile

    def delete_profile(self, profile_id: str) -> bool:
        profiles = self._read_profiles()
        remaining = [profile for profile in profiles if profile.id != profile_id]
        if len(remaining) == len(profiles):
            return False
        self._write_profiles(remaining)
        return True

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

    def _write_profiles(self, profiles: list[StoredPlayerProfile]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": 3,
            "profiles": [_profile_to_payload(profile) for profile in profiles],
        }
        temp_path = self.path.with_suffix(f"{self.path.suffix}.tmp")
        temp_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temp_path.replace(self.path)


def _profile_from_payload(payload: dict[str, Any]) -> StoredPlayerProfile | None:
    profile_id = _optional_string(payload.get("id"))
    display_name = _optional_string(payload.get("display_name") or payload.get("name"))
    model = _optional_string(payload.get("model"))
    if profile_id is None or display_name is None or model is None:
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
        model=model,
        personality_id=personality_id,
        personality_text=str(
            payload.get("personality_text")
            if payload.get("personality_text") is not None
            else payload.get("personality") or ""
        ),
        appearance_id=appearance_id,
        avatar_prompt=str(payload.get("avatar_prompt") or ""),
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


def _profile_to_payload(profile: StoredPlayerProfile) -> dict[str, Any]:
    return {
        "id": profile.id,
        "owner_user_id": profile.owner_user_id,
        "display_name": profile.display_name,
        "model": profile.model,
        "personality_id": profile.personality_id,
        "personality_text": profile.personality_text,
        "appearance_id": profile.appearance_id,
        "avatar_prompt": profile.avatar_prompt,
        "avatar_image_url": profile.avatar_image_url,
        "avatar_image_path": profile.avatar_image_path,
        "avatar_image_mime": profile.avatar_image_mime,
        "short_description": profile.short_description,
        "background_story": profile.background_story,
        "speaking_style": profile.speaking_style,
        "catchphrases": profile.catchphrases,
        "strategy_profile": profile.strategy_profile,
        "risk_tolerance": profile.risk_tolerance,
        "bluffing_tendency": profile.bluffing_tendency,
        "trust_tendency": profile.trust_tendency,
        "leadership_tendency": profile.leadership_tendency,
        "talkativeness": profile.talkativeness,
        "example_messages": profile.example_messages,
        "favorite": profile.favorite,
        "tags": profile.tags,
        "created_at": profile.created_at.isoformat(),
        "updated_at": profile.updated_at.isoformat(),
    }


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


def player_profile_store_for_logs_dir(logs_dir: str | Path) -> PlayerProfileFileStore:
    return PlayerProfileFileStore(Path(logs_dir) / "player_profiles.json")
