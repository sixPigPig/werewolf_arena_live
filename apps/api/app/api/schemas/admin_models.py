from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class AdminModelParameters(BaseModel):
    thinking: Literal["default", "enabled", "disabled"] = "default"
    reasoning_effort: str | None = None
    temperature: float | None = None
    top_p: float | None = None
    max_tokens: int | None = None
    frequency_penalty: float | None = None
    presence_penalty: float | None = None


class AdminModelSource(BaseModel):
    provider: Literal["agent_plan", "deepseek"]
    label: str
    refresh_mode: Literal["manual", "automatic"]
    status: Literal["ok", "error"]
    model_count: int
    last_synced_at: datetime | None
    docs_url: str
    error: str | None


class AdminModelItem(BaseModel):
    provider: Literal["agent_plan", "deepseek"]
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
    reasoning_effort_options: list[str]
    max_output_tokens_limit: int
    docs_url: str
    updated_at: datetime


class AdminModelCatalogResponse(BaseModel):
    generated_at: datetime
    sources: list[AdminModelSource]
    models: list[AdminModelItem]


class AdminModelConfigurationRequest(BaseModel):
    enabled: bool
    is_default: bool = False
    parameters: AdminModelParameters = Field(default_factory=AdminModelParameters)
