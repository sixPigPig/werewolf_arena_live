from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.api.schemas.common import PaginationResponse


RULE_SET_ID_PATTERN = r"^[a-z][a-z0-9_]{2,79}$"
REASON_MIN_LENGTH = 3
REASON_MAX_LENGTH = 500
PLAYER_COUNT_MIN = 6
PLAYER_COUNT_MAX = 12
RULE_TAGS_MAX_ITEMS = 8
RULE_TAG_MAX_LENGTH = 20

RuleSetStatus = Literal["draft", "published", "archived"]
RuleRevisionState = Literal["draft", "published", "superseded"]
RuleSetSort = Literal[
    "display_order",
    "-display_order",
    "updated_at",
    "-updated_at",
    "name",
    "-name",
    "created_at",
    "-created_at",
]
RuleTag = Annotated[str, Field(min_length=1, max_length=RULE_TAG_MAX_LENGTH)]


class AdminRuleSetRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class AdminRuleRoleCounts(AdminRuleSetRequest):
    werewolf: int = Field(ge=0)
    villager: int = Field(ge=0)
    seer: int = Field(ge=0)
    guard: int = Field(ge=0)
    witch: int = Field(ge=0)
    hunter: int = Field(ge=0)
    idiot: int = Field(ge=0)


class AdminRuleSetConfig(AdminRuleSetRequest):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=1000)
    complexity: str = Field(min_length=1, max_length=40)
    estimated_duration: str = Field(min_length=1, max_length=40)
    rule_tags: list[RuleTag] = Field(default_factory=list, max_length=RULE_TAGS_MAX_ITEMS)
    role_counts: AdminRuleRoleCounts
    win_condition: Literal["wolves_gte_others", "slaughter_side"]
    sheriff_enabled: bool
    sheriff_vote_weight: float
    speech_policy: Literal["sequential", "sheriff_directed"]
    werewolf_self_explosion_enabled: bool
    sheriff_badge_bomb_policy: Literal["none", "double"]


class AdminRuleSetCreate(AdminRuleSetRequest):
    id: str = Field(pattern=RULE_SET_ID_PATTERN)
    display_order: int = Field(ge=0)
    config: AdminRuleSetConfig


class AdminRuleSetDraftUpdate(AdminRuleSetRequest):
    expected_rule_set_lock_version: int = Field(ge=1)
    expected_revision_lock_version: int | None = Field(ge=1)
    display_order: int = Field(ge=0)
    config: AdminRuleSetConfig


class AdminRuleSetValidate(AdminRuleSetRequest):
    expected_revision_lock_version: int = Field(ge=1)


class AdminRuleSetTransition(AdminRuleSetRequest):
    expected_rule_set_lock_version: int = Field(ge=1)
    reason: str = Field(min_length=REASON_MIN_LENGTH, max_length=REASON_MAX_LENGTH)

    @field_validator("reason", mode="before")
    @classmethod
    def trim_reason(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class AdminRuleSetPublish(AdminRuleSetRequest):
    expected_rule_set_lock_version: int = Field(ge=1)
    expected_revision_lock_version: int = Field(ge=1)
    reason: str = Field(min_length=REASON_MIN_LENGTH, max_length=REASON_MAX_LENGTH)

    @field_validator("reason", mode="before")
    @classmethod
    def trim_reason(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class AdminRuleSetArchive(AdminRuleSetTransition):
    replacement_default_rule_set_id: str | None = Field(
        default=None,
        pattern=RULE_SET_ID_PATTERN,
    )
    replacement_expected_lock_version: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def require_complete_replacement_version_pair(self) -> "AdminRuleSetArchive":
        if (self.replacement_default_rule_set_id is None) != (
            self.replacement_expected_lock_version is None
        ):
            raise ValueError("Replacement rule set ID and version must be provided together")
        return self


class AdminRuleSetDefaultTransition(AdminRuleSetRequest):
    expected_rule_set_lock_version: int = Field(ge=1)
    previous_default_expected_lock_version: int | None = Field(default=None, ge=1)
    reason: str = Field(min_length=REASON_MIN_LENGTH, max_length=REASON_MAX_LENGTH)

    @field_validator("reason", mode="before")
    @classmethod
    def trim_reason(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class AdminRuleSetDuplicate(AdminRuleSetRequest):
    expected_source_lock_version: int = Field(ge=1)
    new_rule_set_id: str = Field(pattern=RULE_SET_ID_PATTERN)
    new_name: str = Field(min_length=1, max_length=120)


AdminRuleSetValidateRequest = AdminRuleSetValidate
AdminRuleSetTransitionRequest = AdminRuleSetTransition
AdminRuleSetPublishRequest = AdminRuleSetPublish
AdminRuleSetArchiveRequest = AdminRuleSetArchive
AdminRuleSetRestoreRequest = AdminRuleSetTransition
AdminRuleSetSetDefaultRequest = AdminRuleSetDefaultTransition
AdminRuleSetDuplicateRequest = AdminRuleSetDuplicate


class AdminRuleSetRevisionResponse(BaseModel):
    id: str = Field(min_length=1, max_length=36)
    rule_set_id: str = Field(pattern=RULE_SET_ID_PATTERN)
    revision_no: int = Field(ge=1)
    state: RuleRevisionState
    schema_version: int = Field(ge=1)
    content_hash: str | None = Field(default=None, max_length=64)
    lock_version: int = Field(ge=1)
    config: AdminRuleSetConfig | None
    player_count: int = Field(ge=0)
    role_summary: str = Field(max_length=500)
    created_at: datetime
    updated_at: datetime
    published_at: datetime | None
    published_by: str | None


class AdminRuleSetResponse(BaseModel):
    id: str = Field(pattern=RULE_SET_ID_PATTERN)
    status: RuleSetStatus
    is_default: bool
    display_order: int = Field(ge=0)
    lock_version: int = Field(ge=1)
    draft_revision: AdminRuleSetRevisionResponse | None
    published_revision: AdminRuleSetRevisionResponse | None
    revisions: list[AdminRuleSetRevisionResponse] = Field(max_length=50)
    created_at: datetime
    updated_at: datetime


class AdminRuleSetListResponse(BaseModel):
    items: list[AdminRuleSetResponse]
    pagination: PaginationResponse


class AdminRuleSetUsage(BaseModel):
    game_count: int = Field(ge=0)
    live_count: int = Field(ge=0)


class AdminRuleSetHistoryRevisionResponse(AdminRuleSetRevisionResponse):
    usage: AdminRuleSetUsage


class AdminRuleSetWarning(BaseModel):
    code: str = Field(min_length=1, max_length=80)
    path: str = Field(min_length=1, max_length=120)
    message: str = Field(min_length=1, max_length=500)


class AdminRuleSetValidationResponse(BaseModel):
    valid: bool
    errors: list[AdminRuleSetWarning] = Field(max_length=50)
    warnings: list[AdminRuleSetWarning] = Field(max_length=50)
    compiled_snapshot: dict[str, object] | None = None
    content_hash: str | None = Field(default=None, min_length=64, max_length=64)
    rule_text_preview: str | None = Field(default=None, max_length=10_000)


class AdminRuleSetDetailResponse(AdminRuleSetResponse):
    revisions: list[AdminRuleSetHistoryRevisionResponse] = Field(max_length=50)
    usage: AdminRuleSetUsage
    warnings: list[AdminRuleSetWarning] = Field(max_length=10)


class AdminRuleRoleOption(BaseModel):
    id: str
    label: str
    min_count: int = Field(ge=0)
    max_count: int = Field(ge=0, le=PLAYER_COUNT_MAX)


class AdminRuleChoice(BaseModel):
    value: str
    label: str


class AdminRuleSetConstraints(BaseModel):
    player_count_min: int
    player_count_max: int
    tags_max_items: int
    tag_max_length: int
    id_pattern: str
    reason_min_length: int
    reason_max_length: int


class AdminRuleSetOptionsResponse(BaseModel):
    roles: list[AdminRuleRoleOption]
    win_conditions: list[AdminRuleChoice]
    sheriff_vote_weights: list[float]
    speech_policies: list[AdminRuleChoice]
    sheriff_badge_bomb_policies: list[AdminRuleChoice]
    statuses: list[AdminRuleChoice]
    sorts: list[AdminRuleChoice]
    constraints: AdminRuleSetConstraints
