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
    first_night_last_words_enabled: bool
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


class AdminRuleContractClause(BaseModel):
    clause_id: str = Field(min_length=1, max_length=160)
    priority: Literal["P0", "P1", "P2"]
    roles: list[str] = Field(max_length=20)
    phases: list[str] = Field(max_length=20)
    actions: list[str] = Field(max_length=30)
    audience: Literal["player_public", "role_private", "internal_only"]
    engine_constraint_ids: list[str] = Field(min_length=1, max_length=20)
    model_rule_text: str | None = Field(default=None, min_length=1, max_length=2000)
    coverage_status: Literal["covered", "broken"]
    uncovered_engine_constraint_ids: list[str] = Field(max_length=20)

    @model_validator(mode="after")
    def require_safe_model_text_and_consistent_coverage(self) -> "AdminRuleContractClause":
        if (self.audience == "internal_only") != (self.model_rule_text is None):
            raise ValueError("Model rule text must match the clause audience")
        if (self.coverage_status == "covered") != (not self.uncovered_engine_constraint_ids):
            raise ValueError("Clause coverage status is inconsistent")
        return self


class AdminRuleContractResponse(BaseModel):
    schema_version: int = Field(ge=1)
    revision_id: str = Field(min_length=1, max_length=80)
    canonical_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    coverage_status: Literal["covered", "broken"]
    publish_ready: bool
    missing_p0_clause_ids: list[str] = Field(max_length=20)
    broken_engine_constraint_ids: list[str] = Field(max_length=50)
    clauses: list[AdminRuleContractClause] = Field(max_length=100)

    @model_validator(mode="after")
    def require_consistent_publish_readiness(self) -> "AdminRuleContractResponse":
        if self.publish_ready != (self.coverage_status == "covered"):
            raise ValueError("Contract publish readiness is inconsistent")
        if self.publish_ready and (
            self.missing_p0_clause_ids
            or self.broken_engine_constraint_ids
            or any(clause.coverage_status != "covered" for clause in self.clauses)
        ):
            raise ValueError("Publishable contract cannot contain coverage blockers")
        if len({clause.clause_id for clause in self.clauses}) != len(self.clauses):
            raise ValueError("Rule clause IDs must be unique")
        return self


class AdminRuleSetValidationResponse(BaseModel):
    valid: bool
    errors: list[AdminRuleSetWarning] = Field(max_length=50)
    warnings: list[AdminRuleSetWarning] = Field(max_length=50)
    rule_contract: AdminRuleContractResponse | None = None
    compiled_snapshot: dict[str, object] | None = None
    content_hash: str | None = Field(default=None, min_length=64, max_length=64)
    rule_text_preview: str | None = Field(default=None, max_length=10_000)


class AdminRuleSetDetailResponse(AdminRuleSetResponse):
    revisions: list[AdminRuleSetHistoryRevisionResponse] = Field(max_length=50)
    usage: AdminRuleSetUsage
    warnings: list[AdminRuleSetWarning] = Field(max_length=10)
    rule_contract: AdminRuleContractResponse | None = None


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
