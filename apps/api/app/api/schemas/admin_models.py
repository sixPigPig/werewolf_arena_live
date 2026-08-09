from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class AdminModelParameters(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    thinking: Literal["enabled", "disabled"]
    reasoning_effort: str | None
    temperature: float | None = None
    top_p: float | None = None
    max_tokens_mode: Literal["auto", "manual"]
    max_tokens: int = Field(ge=1, strict=True)
    frequency_penalty: float | None = None
    presence_penalty: float | None = None


class AdminModelReasoningPolicy(BaseModel):
    thinking_options: list[Literal["enabled", "disabled"]]
    default_thinking: Literal["enabled", "disabled"]
    thinking_locked: bool
    reasoning_effort_options: list[str]
    default_reasoning_effort: str | None
    max_tokens_by_effort: dict[str, int]
    default_max_tokens: int
    disabled_max_tokens: int | None
    sampling_parameters_allowed_when_thinking: bool


class AdminModelSource(BaseModel):
    provider: Literal["agent_plan", "ark", "deepseek"]
    label: str
    refresh_mode: Literal["manual", "automatic"]
    status: Literal["ok", "error"]
    model_count: int
    last_synced_at: datetime | None
    docs_url: str
    error: str | None


class AdminModelItem(BaseModel):
    provider: Literal["agent_plan", "ark", "deepseek"]
    model_id: str
    source_model_id: str | None
    display_name: str
    description: str | None
    available: bool
    enabled: bool
    is_default: bool
    selected_by_source: bool
    supports_thinking: bool
    assigned_profile_count: int
    parameters: AdminModelParameters
    reasoning_policy: AdminModelReasoningPolicy
    max_output_tokens_limit: int
    docs_url: str
    updated_at: datetime


class AdminModelCatalogResponse(BaseModel):
    generated_at: datetime
    sources: list[AdminModelSource]
    models: list[AdminModelItem]


class AdminModelConfigurationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    enabled: bool
    is_default: bool = False
    parameters: AdminModelParameters
