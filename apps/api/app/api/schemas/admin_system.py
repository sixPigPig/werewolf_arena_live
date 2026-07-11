from __future__ import annotations

from datetime import datetime
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.api.schemas.common import PaginationResponse

AdminRoleValue = Literal["viewer", "content_editor", "operator", "super_admin"]
AdminIdentityStatus = Literal["unbound", "bound"]
AdminUserSort = Literal[
    "display_name",
    "-display_name",
    "email",
    "-email",
    "updated_at",
    "-updated_at",
    "created_at",
    "-created_at",
]
AdminAuditSort = Literal["created_at", "-created_at"]
_EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


class AdminSystemRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AdminUserListItem(BaseModel):
    id: str
    email: str
    display_name: str
    role: AdminRoleValue
    is_active: bool
    identity_status: AdminIdentityStatus
    active_session_count: int
    last_session_at: datetime | None
    created_at: datetime
    updated_at: datetime
    version: int


class AdminUserListResponse(BaseModel):
    items: list[AdminUserListItem]
    pagination: PaginationResponse


class AdminUserCreate(AdminSystemRequest):
    email: str = Field(min_length=3, max_length=255)
    display_name: str = Field(min_length=1, max_length=120)
    role: AdminRoleValue
    reason: str = Field(min_length=3, max_length=500)

    @field_validator("email", "display_name", "reason", mode="before")
    @classmethod
    def trim_strings(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        normalized = value.lower()
        if not _EMAIL_RE.fullmatch(normalized):
            raise ValueError("A valid email address is required")
        return normalized


class AdminUserUpdate(AdminSystemRequest):
    expected_version: int = Field(ge=1)
    display_name: str | None = Field(default=None, min_length=1, max_length=120)
    role: AdminRoleValue | None = None
    is_active: bool | None = None
    reason: str = Field(min_length=3, max_length=500)

    @model_validator(mode="before")
    @classmethod
    def reject_null_account_fields(cls, value: object) -> object:
        if isinstance(value, dict):
            null_fields = [
                field
                for field in ("display_name", "role", "is_active")
                if field in value and value[field] is None
            ]
            if null_fields:
                raise ValueError(f"Fields may not be null: {', '.join(null_fields)}")
        return value

    @field_validator("display_name", "reason", mode="before")
    @classmethod
    def trim_strings(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @model_validator(mode="after")
    def require_change(self) -> "AdminUserUpdate":
        if not (self.model_fields_set & {"display_name", "role", "is_active"}):
            raise ValueError("At least one account field must be updated")
        return self


class AdminSessionRevokeRequest(AdminSystemRequest):
    reason: str = Field(min_length=3, max_length=500)

    @field_validator("reason", mode="before")
    @classmethod
    def trim_reason(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class AdminSessionRevokeResponse(BaseModel):
    user_id: str
    revoked_count: int


class AdminAuditActor(BaseModel):
    id: str
    email: str
    display_name: str


class AdminAuditEventItem(BaseModel):
    id: str
    actor: AdminAuditActor | None
    action: str
    resource_type: str
    resource_id: str | None
    result: str
    reason: str | None
    request_id: str | None
    created_at: datetime


class AdminAuditEventListResponse(BaseModel):
    items: list[AdminAuditEventItem]
    pagination: PaginationResponse
