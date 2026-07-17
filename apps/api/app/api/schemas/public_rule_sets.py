from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class PublicRuleRole(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    role: str = Field(min_length=1)
    count: int = Field(ge=1)
    team: str = Field(min_length=1)
    model_group: str = Field(min_length=1)
    category: str = Field(min_length=1)


class PublicRuleSetCatalogItem(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    id: str = Field(min_length=1, max_length=80)
    version: str = Field(min_length=1)
    name: str = Field(min_length=1, max_length=120)
    description: str
    player_count: int = Field(ge=1)
    roles: list[PublicRuleRole] = Field(min_length=1)
    night_actions: list[str]
    day_actions: list[str]
    win_condition: str = Field(min_length=1)
    reveal_policy: str = Field(min_length=1)
    complexity: str = Field(min_length=1, max_length=40)
    estimated_duration: str = Field(min_length=1, max_length=40)
    role_summary: str = Field(min_length=1)
    sheriff_enabled: bool
    sheriff_vote_weight: float
    speech_policy: Literal["sequential", "sheriff_directed"]
    speech_rounds: int = Field(ge=1)
    rule_tags: list[str]
    werewolf_self_explosion_enabled: bool
    exile_last_words_enabled: bool
    sheriff_badge_bomb_policy: Literal["none", "double"]
    revision_id: str = Field(min_length=1, max_length=36)
    revision_no: int = Field(ge=1)
    schema_version: int = Field(ge=1)
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    is_default: bool


class PublicRuleSetCatalogResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    rule_sets: list[PublicRuleSetCatalogItem]
