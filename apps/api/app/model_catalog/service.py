from __future__ import annotations

import json
import subprocess
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Iterable, Literal

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from app.core.config import settings
from app.model_catalog.defaults import (
    ReasoningPolicy,
    default_parameter_values,
    max_output_tokens_limit,
    normalize_model_parameters,
    reasoning_policy_for_model,
)
from app.models.model_configuration import ModelConfigurationRecord
from app.models.virtual_player_profile import VirtualPlayerProfile
from app.shared.providers import (
    ARK_AGENT_PLAN_CONFIG,
    DEEPSEEK_CONFIG,
    OpenAICompatibleProvider,
    bootstrap_default_model_name,
    environment_model_names,
    open_url_direct,
)

ModelProviderName = Literal["agent_plan", "ark", "deepseek"]
UNSUPPORTED_CATALOG_MODELS = frozenset({("agent_plan", "auto")})

ARK_DOCS_URL = "https://api.volcengine.com/api-docs/view?action=ChatCompletions&serviceCode=ark&version=2024-01-01"
ARK_STANDARD_DOCS_URL = "https://www.volcengine.com/docs/82379/1298454"
DEEPSEEK_MODELS_URL = "https://api-docs.deepseek.com/zh-cn/quick_start/pricing"
DEEPSEEK_THINKING_URL = "https://api-docs.deepseek.com/zh-cn/guides/thinking_mode"


class ModelCatalogUnavailable(RuntimeError):
    pass


@dataclass(frozen=True)
class DiscoveredModel:
    provider: ModelProviderName
    model_id: str
    source_model_id: str
    display_name: str
    description: str
    supports_thinking: bool
    source_details: dict[str, Any]


@dataclass(frozen=True)
class CatalogSourceState:
    provider: ModelProviderName
    label: str
    refresh_mode: Literal["manual", "automatic"]
    status: Literal["ok", "error"]
    model_count: int
    last_synced_at: datetime | None
    docs_url: str
    error: str | None = None


@dataclass(frozen=True)
class CatalogModelItem:
    provider: ModelProviderName
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
    parameters: dict[str, Any]
    reasoning_policy: ReasoningPolicy
    max_output_tokens_limit: int
    docs_url: str
    updated_at: datetime


@dataclass(frozen=True)
class CatalogSnapshot:
    sources: tuple[CatalogSourceState, ...]
    models: tuple[CatalogModelItem, ...]


class AgentPlanCatalogClient:
    def list_models(self) -> list[DiscoveredModel]:
        command = [
            settings.model_catalog_arkcli_path,
            "plans",
            "model-list",
            "--plan",
            settings.model_catalog_agent_plan,
        ]
        try:
            result = subprocess.run(
                command,
                check=False,
                capture_output=True,
                text=True,
                timeout=settings.model_catalog_sync_timeout_seconds,
            )
        except FileNotFoundError as exc:
            raise ModelCatalogUnavailable(
                "arkcli is not installed in the API runtime."
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise ModelCatalogUnavailable("Agent Plan model discovery timed out.") from exc
        if result.returncode != 0:
            raise ModelCatalogUnavailable(_safe_cli_error(result.stdout, result.stderr))
        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise ModelCatalogUnavailable("arkcli returned invalid model-list JSON.") from exc
        if not isinstance(payload, dict):
            raise ModelCatalogUnavailable("arkcli returned an invalid model-list payload.")
        raw_models = payload.get("models")
        if not isinstance(raw_models, list):
            raise ModelCatalogUnavailable("arkcli model-list did not include a models array.")
        selected_id = payload.get("selected_model_id") or payload.get("ark_latest_model_id")
        discovered: list[DiscoveredModel] = []
        for raw_model in raw_models:
            if not isinstance(raw_model, dict):
                continue
            source_model_id = _non_empty_string(raw_model.get("model_id"))
            runtime_model_id = (
                _non_empty_string(raw_model.get("output_name")) or source_model_id
            )
            if not source_model_id or not runtime_model_id:
                continue
            model_name = _non_empty_string(raw_model.get("model_name")) or runtime_model_id
            description = _non_empty_string(raw_model.get("description")) or ""
            supports_thinking = bool(raw_model.get("enabled_thinking")) or (
                "思考" in description or runtime_model_id.startswith("deepseek-")
            )
            discovered.append(
                DiscoveredModel(
                    provider="agent_plan",
                    model_id=runtime_model_id,
                    source_model_id=source_model_id,
                    display_name=model_name,
                    description=description,
                    supports_thinking=supports_thinking,
                    source_details={
                        "selected": bool(raw_model.get("selected"))
                        or selected_id in {source_model_id, runtime_model_id},
                        "plan": payload.get("plan") or settings.model_catalog_agent_plan,
                    },
                )
            )
        if not discovered:
            raise ModelCatalogUnavailable("Agent Plan returned an empty model catalog.")
        return discovered


class DeepSeekCatalogClient:
    def list_models(self) -> list[DiscoveredModel]:
        try:
            provider = OpenAICompatibleProvider(config=DEEPSEEK_CONFIG)
        except RuntimeError as exc:
            raise ModelCatalogUnavailable("DEEPSEEK_API_KEY is not configured.") from exc
        request = urllib.request.Request(
            f"{provider.base_url}/models",
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {provider.api_key}",
                "User-Agent": "werewolf-arena-live/0.1",
            },
        )
        try:
            with open_url_direct(
                request,
                timeout=settings.model_catalog_deepseek_timeout_seconds,
            ) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raise ModelCatalogUnavailable(
                f"DeepSeek model discovery failed with HTTP {exc.code}."
            ) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise ModelCatalogUnavailable("DeepSeek model discovery is unavailable.") from exc
        except json.JSONDecodeError as exc:
            raise ModelCatalogUnavailable("DeepSeek returned invalid model-list JSON.") from exc
        raw_models = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(raw_models, list):
            raise ModelCatalogUnavailable("DeepSeek did not return a models array.")
        discovered = []
        for raw_model in raw_models:
            if not isinstance(raw_model, dict):
                continue
            model_id = _non_empty_string(raw_model.get("id"))
            if not model_id:
                continue
            discovered.append(
                DiscoveredModel(
                    provider="deepseek",
                    model_id=model_id,
                    source_model_id=model_id,
                    display_name=model_id,
                    description=_deepseek_description(model_id),
                    supports_thinking=True,
                    source_details={"owned_by": raw_model.get("owned_by", "deepseek")},
                )
            )
        if not discovered:
            raise ModelCatalogUnavailable("DeepSeek returned an empty model catalog.")
        return discovered


def get_catalog_snapshot(
    db: Session,
    *,
    deepseek_client: DeepSeekCatalogClient | None = None,
) -> CatalogSnapshot:
    bootstrap_environment_catalog(db)
    db.flush()
    deepseek_error: str | None = None
    try:
        deepseek_models = (deepseek_client or DeepSeekCatalogClient()).list_models()
        _sync_discovered_models(db, "deepseek", deepseek_models)
    except ModelCatalogUnavailable as exc:
        deepseek_error = str(exc)
    db.commit()
    return _snapshot_from_database(db, deepseek_error=deepseek_error)


def sync_agent_plan_catalog(
    db: Session,
    *,
    client: AgentPlanCatalogClient | None = None,
) -> CatalogSnapshot:
    bootstrap_environment_catalog(db)
    db.flush()
    models = (client or AgentPlanCatalogClient()).list_models()
    _sync_discovered_models(db, "agent_plan", models)
    db.commit()
    return _snapshot_from_database(db, deepseek_error=None)


def update_model_configuration(
    db: Session,
    *,
    provider: ModelProviderName,
    model_id: str,
    enabled: bool,
    is_default: bool,
    parameters: dict[str, Any],
) -> ModelConfigurationRecord:
    record = db.get(ModelConfigurationRecord, (provider, model_id))
    if record is None:
        raise LookupError("model configuration not found")
    if enabled and not record.available:
        raise ValueError("an unavailable model cannot be enabled")
    assigned_count = _assigned_profile_counts(db).get((provider, model_id), 0)
    if not enabled and assigned_count:
        raise ModelConfigurationConflict(
            f"{assigned_count} player profiles still use this model."
        )
    if not enabled and record.is_default:
        raise ModelConfigurationConflict("Select another default model before disabling this one.")
    if record.is_default and not is_default:
        raise ModelConfigurationConflict("Select another model as default instead of clearing it.")
    advertised_supports_thinking = record.supports_thinking or (
        (record.source_details or {}).get("bootstrap") == "environment"
        and _bootstrap_supports_thinking(provider, model_id)
    )
    policy = reasoning_policy_for_model(
        provider,
        model_id,
        supports_thinking=advertised_supports_thinking,
    )
    supports_thinking = "enabled" in policy.thinking_options
    record.supports_thinking = supports_thinking
    previous_parameters = dict(record.parameter_values)
    reasoning_changed = (
        parameters.get("thinking") != previous_parameters.get("thinking")
        or parameters.get("reasoning_effort")
        != previous_parameters.get("reasoning_effort")
    )
    if reasoning_changed:
        parameters = {**parameters, "max_tokens_mode": "auto"}
    normalized_parameters = validate_parameter_values(
        provider=provider,
        model_id=model_id,
        supports_thinking=supports_thinking,
        values=parameters,
    )
    if is_default:
        if not enabled:
            raise ValueError("the default model must be enabled")
        db.execute(
            update(ModelConfigurationRecord)
            .where(ModelConfigurationRecord.is_default.is_(True))
            .values(is_default=False)
        )
        db.flush()
    record.enabled = enabled
    record.is_default = is_default
    record.parameter_values = normalized_parameters
    return record


class ModelConfigurationConflict(RuntimeError):
    pass


def validate_parameter_values(
    *,
    provider: ModelProviderName,
    model_id: str,
    supports_thinking: bool,
    values: dict[str, Any],
) -> dict[str, Any]:
    normalized = normalize_model_parameters(
        provider,
        model_id,
        values,
        supports_thinking=supports_thinking,
        limit=_max_output_tokens_limit(provider, model_id),
    )
    thinking = normalized["thinking"]
    sampling_parameters = {
        "temperature",
        "top_p",
        "frequency_penalty",
        "presence_penalty",
    }
    policy = reasoning_policy_for_model(
        provider,
        model_id,
        supports_thinking=supports_thinking,
    )
    if (
        thinking != "disabled"
        and not policy.sampling_parameters_allowed_when_thinking
        and any(
            parameter in normalized for parameter in sampling_parameters
        )
    ):
        raise ValueError(
            "this model ignores sampling and penalty parameters unless thinking is disabled"
        )
    return normalized


def bootstrap_environment_catalog(db: Session) -> None:
    _delete_unsupported_catalog_models(db)
    now = datetime.now(tz=UTC)
    default_model = bootstrap_default_model_name()
    providers: tuple[tuple[ModelProviderName, Any], ...] = (
        ("agent_plan", ARK_AGENT_PLAN_CONFIG),
        ("ark", None),
        ("deepseek", DEEPSEEK_CONFIG),
    )
    has_default = db.scalar(
        select(func.count()).select_from(ModelConfigurationRecord).where(
            ModelConfigurationRecord.is_default.is_(True)
        )
    )
    for provider_name, config in providers:
        model_ids = (
            _configured_ark_model_ids()
            if provider_name == "ark"
            else environment_model_names(config)
        )
        for model_id in model_ids:
            if _is_unsupported_catalog_model(provider_name, model_id):
                continue
            record = db.get(ModelConfigurationRecord, (provider_name, model_id))
            bootstrap_supports_thinking = _bootstrap_supports_thinking(
                provider_name,
                model_id,
            )
            if record is None:
                parameter_values = default_parameter_values(
                    provider_name,
                    model_id,
                    supports_thinking=bootstrap_supports_thinking,
                    limit=_max_output_tokens_limit(provider_name, model_id),
                )
                record = ModelConfigurationRecord(
                    provider=provider_name,
                    model_id=model_id,
                    source_model_id=model_id,
                    display_name=model_id,
                    description=None,
                    available=True,
                    enabled=True,
                    is_default=not has_default and model_id == default_model,
                    supports_thinking=bootstrap_supports_thinking,
                    parameter_values=parameter_values,
                    source_details={"bootstrap": "environment"},
                    last_synced_at=None,
                    created_at=now,
                    updated_at=now,
                )
                db.add(record)
                if record.is_default:
                    has_default = 1
            elif (record.source_details or {}).get("bootstrap") == "environment":
                policy = reasoning_policy_for_model(
                    provider_name,
                    model_id,
                    supports_thinking=bootstrap_supports_thinking,
                )
                record.supports_thinking = "enabled" in policy.thinking_options
                record.parameter_values = normalize_model_parameters(
                    provider_name,
                    model_id,
                    record.parameter_values,
                    supports_thinking=record.supports_thinking,
                    limit=_max_output_tokens_limit(provider_name, model_id),
                    enforce_auto_max_tokens=True,
                )
                record.updated_at = now


def _sync_discovered_models(
    db: Session,
    provider: ModelProviderName,
    models: Iterable[DiscoveredModel],
) -> None:
    now = datetime.now(tz=UTC)
    configured_ids = set(
        _configured_ark_model_ids()
        if provider == "ark"
        else environment_model_names(
            ARK_AGENT_PLAN_CONFIG if provider == "agent_plan" else DEEPSEEK_CONFIG
        )
    )
    configured_ids = {
        model_id
        for model_id in configured_ids
        if not _is_unsupported_catalog_model(provider, model_id)
    }
    discovered_ids: set[str] = set()
    for model in models:
        if _is_unsupported_catalog_model(provider, model.model_id):
            continue
        discovered_ids.add(model.model_id)
        record = db.get(ModelConfigurationRecord, (provider, model.model_id))
        reasoning_policy = reasoning_policy_for_model(
            provider,
            model.model_id,
            supports_thinking=model.supports_thinking,
        )
        supports_thinking = "enabled" in reasoning_policy.thinking_options
        if record is None:
            parameter_values = default_parameter_values(
                provider,
                model.model_id,
                supports_thinking=supports_thinking,
                limit=_max_output_tokens_limit(provider, model.model_id),
            )
            record = ModelConfigurationRecord(
                provider=provider,
                model_id=model.model_id,
                enabled=model.model_id in configured_ids,
                is_default=False,
                parameter_values=parameter_values,
                created_at=now,
            )
            db.add(record)
        record.source_model_id = model.source_model_id
        record.display_name = model.display_name
        record.description = model.description
        record.available = True
        capability_changed = record.supports_thinking != supports_thinking
        record.supports_thinking = supports_thinking
        record.parameter_values = (
            default_parameter_values(
                provider,
                model.model_id,
                supports_thinking=supports_thinking,
                limit=_max_output_tokens_limit(provider, model.model_id),
            )
            if capability_changed
            else normalize_model_parameters(
                provider,
                model.model_id,
                record.parameter_values,
                supports_thinking=supports_thinking,
                limit=_max_output_tokens_limit(provider, model.model_id),
                enforce_auto_max_tokens=True,
            )
        )
        record.source_details = {
            **model.source_details,
            "advertised_supports_thinking": model.supports_thinking,
        }
        record.last_synced_at = now
        record.updated_at = now
    stale_records = list(
        db.scalars(
            select(ModelConfigurationRecord).where(
                ModelConfigurationRecord.provider == provider,
                ModelConfigurationRecord.model_id.not_in(discovered_ids),
            )
        )
    )
    for record in stale_records:
        record.available = False
        record.is_default = False
        record.last_synced_at = now
        record.updated_at = now


def _delete_unsupported_catalog_models(db: Session) -> None:
    for provider, model_id in UNSUPPORTED_CATALOG_MODELS:
        db.execute(
            delete(ModelConfigurationRecord).where(
                ModelConfigurationRecord.provider == provider,
                ModelConfigurationRecord.model_id == model_id,
            )
        )


def _is_unsupported_catalog_model(provider: str, model_id: str) -> bool:
    return (provider, model_id.strip().lower()) in UNSUPPORTED_CATALOG_MODELS


def _snapshot_from_database(
    db: Session,
    *,
    deepseek_error: str | None,
) -> CatalogSnapshot:
    records = list(
        db.scalars(
            select(ModelConfigurationRecord).order_by(
                ModelConfigurationRecord.provider,
                ModelConfigurationRecord.available.desc(),
                ModelConfigurationRecord.model_id,
            )
        )
    )
    assignment_counts = _assigned_profile_counts(db)
    models = tuple(
        CatalogModelItem(
            provider=record.provider,  # type: ignore[arg-type]
            model_id=record.model_id,
            source_model_id=record.source_model_id,
            display_name=record.display_name or record.model_id,
            description=record.description,
            available=record.available,
            enabled=record.enabled,
            is_default=record.is_default,
            selected_by_source=bool((record.source_details or {}).get("selected")),
            supports_thinking=record.supports_thinking,
            assigned_profile_count=assignment_counts.get(
                (record.provider, record.model_id),
                0,
            ),
            parameters=normalize_model_parameters(
                record.provider,
                record.model_id,
                record.parameter_values,
                supports_thinking=record.supports_thinking,
                limit=_max_output_tokens_limit(
                    record.provider,  # type: ignore[arg-type]
                    record.model_id,
                ),
                enforce_auto_max_tokens=True,
            ),
            reasoning_policy=reasoning_policy_for_model(
                record.provider,  # type: ignore[arg-type]
                record.model_id,
                supports_thinking=record.supports_thinking,
            ),
            max_output_tokens_limit=_max_output_tokens_limit(
                record.provider,  # type: ignore[arg-type]
                record.model_id,
            ),
            docs_url=(
                DEEPSEEK_THINKING_URL
                if record.provider == "deepseek"
                else (ARK_STANDARD_DOCS_URL if record.provider == "ark" else ARK_DOCS_URL)
            ),
            updated_at=record.updated_at,
        )
        for record in records
        if record.provider in {"agent_plan", "ark", "deepseek"}
    )
    sources = (
        _source_state(
            records,
            provider="agent_plan",
            label="火山方舟 Agent Plan",
            refresh_mode="manual",
            docs_url=ARK_DOCS_URL,
        ),
        _source_state(
            records,
            provider="deepseek",
            label="DeepSeek 官方 API",
            refresh_mode="automatic",
            docs_url=DEEPSEEK_MODELS_URL,
            error=deepseek_error,
        ),
        _source_state(
            records,
            provider="ark",
            label="火山方舟标准推理 API",
            refresh_mode="manual",
            docs_url=ARK_STANDARD_DOCS_URL,
        ),
    )
    return CatalogSnapshot(sources=sources, models=models)


def _source_state(
    records: list[ModelConfigurationRecord],
    *,
    provider: ModelProviderName,
    label: str,
    refresh_mode: Literal["manual", "automatic"],
    docs_url: str,
    error: str | None = None,
) -> CatalogSourceState:
    matching = [record for record in records if record.provider == provider]
    synced_at = max(
        (record.last_synced_at for record in matching if record.last_synced_at is not None),
        default=None,
    )
    return CatalogSourceState(
        provider=provider,
        label=label,
        refresh_mode=refresh_mode,
        status="error" if error else "ok",
        model_count=sum(1 for record in matching if record.available),
        last_synced_at=synced_at,
        docs_url=docs_url,
        error=error,
    )


def _assigned_profile_counts(db: Session) -> dict[tuple[str, str], int]:
    return {
        (provider, model_id): count
        for provider, model_id, count in db.execute(
            select(
                VirtualPlayerProfile.model_provider,
                VirtualPlayerProfile.model,
                func.count(),
            )
            .where(VirtualPlayerProfile.status != "archived")
            .group_by(
                VirtualPlayerProfile.model_provider,
                VirtualPlayerProfile.model,
            )
        )
    }


def _bootstrap_supports_thinking(
    provider: ModelProviderName,
    model_id: str,
) -> bool:
    normalized = model_id.lower()
    if "doubao-seed-2-0-code-preview" in normalized:
        return False
    if provider == "deepseek":
        return normalized.startswith("deepseek-v4")
    return any(
        family in normalized
        for family in (
            "doubao-",
            "glm-5-2",
            "deepseek-v4",
            "kimi-k3",
            "minimax-m3",
        )
    )


def _max_output_tokens_limit(
    provider: ModelProviderName,
    model_id: str,
) -> int:
    return max_output_tokens_limit(provider, model_id)


def _non_empty_string(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _configured_ark_model_ids() -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(
            model_id.strip()
            for model_id in settings.live_v2_ark_models.split(",")
            if model_id.strip()
        )
    )


def _deepseek_description(model_id: str) -> str:
    if model_id == "deepseek-v4-pro":
        return "DeepSeek V4 旗舰模型，面向高质量推理与 Agent 任务。"
    if model_id == "deepseek-v4-flash":
        return "DeepSeek V4 低延迟模型，兼顾推理能力、速度与调用成本。"
    return "DeepSeek 官方 API 模型。"


def _safe_cli_error(stdout: str, stderr: str) -> str:
    combined = " ".join(part.strip() for part in (stdout, stderr) if part.strip())
    if "requires Volc SSO STS" in combined or "auth login volc-sso" in combined:
        return "Agent Plan sync requires an authenticated arkcli Volc SSO session."
    return "Agent Plan model discovery failed."
