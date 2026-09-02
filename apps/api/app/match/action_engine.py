from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
from dataclasses import asdict, dataclass, replace
import hashlib
import json
import logging
from pathlib import Path
import random
import time
from typing import Any, Literal, Protocol
from uuid import uuid4

from app.core.config import settings
from app.judge_configuration import RuntimeJudgeConfiguration
from app.match.director_projection import project_director_scene
from app.match.event_contract import model_event_audience
from app.match.judge_speech import JudgeTemplateError, render_judge_speech
from app.match.model_context import (
    ModelContextProjectionInvariantError,
    ModelPlayerReference,
    model_prompt_metadata,
    project_model_action_context_with_metadata,
    resolve_model_target,
    sanitize_model_speech,
)
from app.match.model_client import (
    FailureDisposition,
    ModelDecision,
    ModelError,
    ModelProgress,
    ProviderAdmissionMode,
    ModelTarget,
    QualityError,
    UsageConsistency,
    model_failure_disposition,
)
from app.match.model_failure_episode import stable_failure_episode_id
from app.match.model_generation_policy_contract import (
    MODEL_GENERATION_POLICY_SUPPORTED_SCHEMA_VERSIONS,
    RequiredTargetExhaustionFailureMode,
    RequiredTargetTechnicalOutcome,
    ResolvedModelGenerationPolicy,
    resolve_model_generation_action_policy,
)
from app.match.model_observation import observe_model_speech
from app.match.protocol import (
    LiveProtocolError,
    audio_frame,
    director_scene_changed,
    live_state,
    game_phase_changed,
    presentation_closed,
    presentation_failed,
    presentation_opened,
    segment_committed,
)
from app.match.repository import (
    ActionClaim,
    ActionRepository,
    ExecutionOwnershipLost,
    PresentationIdentity,
    RepositoryError,
)
from app.match.tts_client import TtsError
from app.match.voice_recorder import VoiceRecorder, VoiceRecordingError
from app.model_catalog.defaults import reasoning_policy_for_model


logger = logging.getLogger(__name__)


class ModelPort(Protocol):
    def resolve_model_target(
        self,
        *,
        model_provider: str,
        model_id: str,
        model_supports_thinking: bool,
        model_parameters: dict[str, Any],
    ) -> ModelTarget: ...

    def build_request_payload(
        self,
        *,
        action_context: dict[str, Any],
        decision: bool,
        target: ModelTarget,
    ) -> dict[str, Any]: ...

    def output_enforcement_metadata(
        self,
        *,
        action_context: dict[str, Any],
        decision: bool,
        target: ModelTarget,
    ) -> dict[str, str | int | None]: ...

    async def generate_action_decision(
        self,
        *,
        action_context: dict[str, Any],
        attempt_id: str | None,
        target: ModelTarget,
        check_cancellation: Callable[[], None] | None = None,
        admission_mode: ProviderAdmissionMode = "normal",
    ) -> ModelDecision: ...


class TtsPort(Protocol):
    def synthesize(
        self,
        *,
        text: str,
        attempt_id: str,
        speaker: str | None = None,
        dialect: str | None = None,
        check_cancellation: Callable[[], None] | None = None,
    ) -> AsyncIterator[bytes]: ...


class BroadcastPort(Protocol):
    async def broadcast_json(
        self,
        value: dict[str, Any],
        *,
        audience: str = "all",
    ) -> None: ...

    async def broadcast_bytes(self, value: bytes, *, audience: str = "all") -> None: ...

    async def broadcast_audio(
        self,
        value: bytes,
        *,
        identity: PresentationIdentity,
        next_sample_cursor: int,
        audience: str = "all",
    ) -> None: ...

    async def set_current(
        self,
        identity: PresentationIdentity | None,
        sample_cursor: int,
        *,
        audience: str = "all",
    ) -> None: ...


@dataclass(frozen=True)
class DecisionContract:
    kind: Literal["speech", "target", "boolean"]
    speech_mode: Literal[
        "required",
        "optional",
        "forbidden",
        "required_if_true",
    ] = "required"
    speech_max_chars: int | None = None
    speech_max_sentences: int | None = None
    target_mode: Literal["none", "required", "optional"] = "none"
    boolean_field: str | None = None
    true_meaning: str | None = None
    false_meaning: str | None = None
    decision_note_mode: Literal["none", "optional"] = "none"
    decision_note_max_chars: int = 120


@dataclass(frozen=True)
class SpeechSpec:
    action_type: str
    phase_id: str
    required_phase_state: str
    objective: str
    success_live_state: str
    success_phase_state: str
    actor_kind: str = "judge"
    actor_id: str = "judge"
    audience: str = "all"
    speaker: str | None = None
    dialect: str | None = None
    model_provider: str | None = None
    model_id: str | None = None
    model_supports_thinking: bool | None = None
    model_parameters: dict[str, Any] | None = None
    activation_id: str | None = None
    output_kind: str = "public_speech"
    decision_contract: DecisionContract = DecisionContract(kind="speech")
    target_exhaustion_outcome: RequiredTargetTechnicalOutcome | None = None
    context: dict[str, Any] | None = None
    allowed_target_ids: tuple[str, ...] | None = None
    model_players: tuple[ModelPlayerReference, ...] = ()
    best_effort: bool = False
    defer_presentation: bool = False
    isolated_failure: bool = False
    pause_on_model_failure: bool = False
    disable_provider_thinking: bool = False
    batch_id: str | None = None
    projection_at_seq: int | None = None
    decision_family_id: str | None = None
    prior_machine_format_failures: int = 0
    automatic_machine_format_budget: int | None = None
    prior_output_budget_failures: int = 0
    automatic_output_budget_budget: int | None = None
    preflight_pause_failure: PreflightPauseFailure | None = None
    model_admission_mode: ProviderAdmissionMode = "normal"
    pipeline_slot_id: str | None = None
    pipeline_stage: Literal["generation", "presentation"] | None = None
    pipeline_kind: Literal["pre_exile"] | None = None
    pipeline_result_kind: Literal["self_explosion", "exile_vote"] | None = None
    pipeline_empty_stream_max_attempts: Literal[1, 2] = 1
    pipeline_retry_mode: Literal[
        "disabled",
        "empty_stream_once_while_predecessor_active",
    ] = "disabled"

    def __post_init__(self) -> None:
        if self.prior_machine_format_failures < 0:
            raise ValueError("prior_machine_format_failures must be non-negative")
        if self.prior_output_budget_failures < 0:
            raise ValueError("prior_output_budget_failures must be non-negative")
        if (
            self.automatic_machine_format_budget is not None
            and self.automatic_machine_format_budget < 0
        ):
            raise ValueError("automatic_machine_format_budget must be non-negative")
        if (
            self.automatic_output_budget_budget is not None
            and self.automatic_output_budget_budget < 0
        ):
            raise ValueError("automatic_output_budget_budget must be non-negative")
        if self.preflight_pause_failure is not None and self.isolated_failure:
            raise ValueError("preflight pause requires a blocking action")
        if self.pause_on_model_failure and not self.isolated_failure:
            raise ValueError("pause on model failure only extends isolated actions")
        if self.model_admission_mode not in {"normal", "idle_only"}:
            raise ValueError("unsupported model admission mode")
        if (self.pipeline_slot_id is None) != (self.pipeline_stage is None):
            raise ValueError("pipeline slot and stage must be provided together")
        if self.pipeline_slot_id is not None and not self.pipeline_slot_id.strip():
            raise ValueError("pipeline slot id must be non-empty")
        if self.pipeline_kind == "pre_exile":
            if self.pipeline_stage != "generation":
                raise ValueError("pre-exile pipeline only supports generation")
            if self.pipeline_result_kind not in {"self_explosion", "exile_vote"}:
                raise ValueError("pre-exile pipeline requires a result kind")
            if self.audience != "god_view":
                raise ValueError("pre-exile pipeline generation must stay in god view")
            if (
                self.pipeline_retry_mode != "disabled"
                and self.pipeline_result_kind != "self_explosion"
            ):
                raise ValueError("pre-exile pipeline retry is reserved for self-explosion")
        elif self.pipeline_result_kind is not None:
            raise ValueError("pipeline result kind requires a pre-exile pipeline")
        if self.pipeline_stage == "generation" and not (
            self.defer_presentation and self.isolated_failure
        ):
            raise ValueError("pipeline generation must be isolated and defer presentation")
        if self.pipeline_stage == "presentation" and self.defer_presentation:
            raise ValueError("pipeline presentation cannot defer presentation")
        if self.model_admission_mode == "idle_only" and self.pipeline_stage != "generation":
            raise ValueError("idle-only admission is reserved for pipeline generation")
        if self.pipeline_empty_stream_max_attempts not in {1, 2}:
            raise ValueError("unsupported pipeline empty-stream attempt limit")
        if self.pipeline_retry_mode not in {
            "disabled",
            "empty_stream_once_while_predecessor_active",
        }:
            raise ValueError("unsupported pipeline retry mode")
        if self.pipeline_retry_mode != "disabled" and self.pipeline_stage != "generation":
            raise ValueError("pipeline retry mode is reserved for pipeline generation")
        if self.pipeline_retry_mode == "disabled" and self.pipeline_empty_stream_max_attempts != 1:
            raise ValueError("pipeline attempt expansion requires an enabled retry mode")
        if self.pipeline_retry_mode != "disabled" and self.pipeline_empty_stream_max_attempts != 2:
            raise ValueError("pipeline retry mode requires exactly two attempts")
        if self.target_exhaustion_outcome is not None and not (
            self.decision_contract.kind == "target"
            and self.decision_contract.target_mode == "required"
        ):
            raise ValueError("target exhaustion outcome requires a required target contract")
        if isinstance(self.context, dict) and "projection_at_seq" in self.context:
            raise ValueError("projection_at_seq must use the dedicated spec field")
        if self.projection_at_seq is None:
            return
        if (
            not isinstance(self.projection_at_seq, int)
            or isinstance(self.projection_at_seq, bool)
            or self.projection_at_seq <= 0
        ):
            raise ValueError("projection_at_seq must be a positive integer")
        if not isinstance(self.batch_id, str) or not self.batch_id.strip():
            raise ValueError("projection_at_seq requires a batch_id")
        cutoff = (
            self.context.get("public_cutoff_record_seq") if isinstance(self.context, dict) else None
        )
        if (
            not isinstance(cutoff, int)
            or isinstance(cutoff, bool)
            or cutoff <= 0
            or cutoff != self.projection_at_seq
        ):
            raise ValueError("projection_at_seq must match public_cutoff_record_seq")


@dataclass(frozen=True)
class PreflightPauseFailure:
    failure_code: str
    failure_category: str
    source_action_id: str
    source_attempt_id: str
    automatic_machine_format_attempt_count: int
    automatic_output_budget_attempt_count: int = 0
    source_failure_episode_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class ActionFailure:
    code: str
    category: str | None
    terminal_attempt_id: str | None
    machine_format_failure_count: int = 0
    last_machine_format_attempt_id: str | None = None
    last_machine_format_failure_code: str | None = None
    output_budget_failure_count: int = 0
    last_output_budget_attempt_id: str | None = None
    last_output_budget_failure_code: str | None = None
    failure_episode_id: str | None = None

    def __post_init__(self) -> None:
        if self.machine_format_failure_count < 0:
            raise ValueError("machine_format_failure_count must be non-negative")
        if self.machine_format_failure_count > 0 and (
            not self.last_machine_format_attempt_id or not self.last_machine_format_failure_code
        ):
            raise ValueError("machine-format failure lineage is required")
        if self.output_budget_failure_count < 0:
            raise ValueError("output_budget_failure_count must be non-negative")
        if self.output_budget_failure_count > 0 and (
            not self.last_output_budget_attempt_id or not self.last_output_budget_failure_code
        ):
            raise ValueError("output-budget failure lineage is required")


@dataclass(frozen=True)
class ActionTechnicalOutcome:
    kind: RequiredTargetTechnicalOutcome
    failure_mode: RequiredTargetExhaustionFailureMode
    failure: ActionFailure
    supporting_event_record_seq: int

    def __post_init__(self) -> None:
        if (
            not isinstance(self.supporting_event_record_seq, int)
            or isinstance(self.supporting_event_record_seq, bool)
            or self.supporting_event_record_seq <= 0
        ):
            raise ValueError("technical outcome requires a supporting event record seq")
        expected_category = (
            "output_budget" if self.failure_mode == "output_budget_exhausted" else "timeout"
        )
        if self.failure.category != expected_category:
            raise ValueError("technical outcome failure category does not match its mode")


@dataclass(frozen=True)
class ActionResult:
    action_id: str | None = None
    decision: ModelDecision | None = None
    failure: ActionFailure | None = None
    technical_outcome: ActionTechnicalOutcome | None = None
    model_response_record_seq: int | None = None
    terminal_event_record_seq: int | None = None
    model_attempt_id: str | None = None
    request_payload_sha256: str | None = None
    projected_context_sha256: str | None = None
    projected_known_event_refs: tuple[str, ...] | None = None
    projected_known_events_sha256: str | None = None

    def __post_init__(self) -> None:
        for field_name, value in (
            ("model_response_record_seq", self.model_response_record_seq),
            ("terminal_event_record_seq", self.terminal_event_record_seq),
        ):
            if value is not None and (type(value) is not int or value <= 0):
                raise ValueError(f"{field_name} must be a positive integer")
            if value is not None and not self.action_id:
                raise ValueError(f"{field_name} requires an action_id")
        for field_name, value in (
            ("model_attempt_id", self.model_attempt_id),
            ("request_payload_sha256", self.request_payload_sha256),
            ("projected_context_sha256", self.projected_context_sha256),
            ("projected_known_events_sha256", self.projected_known_events_sha256),
        ):
            if value is not None and (not isinstance(value, str) or not value):
                raise ValueError(f"{field_name} must be a non-empty string")
            if value is not None and not self.action_id:
                raise ValueError(f"{field_name} requires an action_id")
        if self.projected_known_event_refs is not None:
            if (
                any(
                    not isinstance(item, str) or not item
                    for item in self.projected_known_event_refs
                )
                or len(self.projected_known_event_refs)
                != len(set(self.projected_known_event_refs))
            ):
                raise ValueError("projected_known_event_refs must be unique non-empty strings")
            if not self.action_id:
                raise ValueError("projected_known_event_refs requires an action_id")
        if self.failure is not None and not self.action_id:
            raise ValueError("failed action result requires an action_id")
        if self.technical_outcome is not None:
            if not self.action_id:
                raise ValueError("technical outcome result requires an action_id")
            if self.decision is not None or self.failure is not None:
                raise ValueError("technical outcome result cannot carry a decision or failure")


@dataclass(frozen=True)
class ModelRetryPolicy:
    max_attempts: int = 3
    attempt_total_seconds: float = 180.0
    action_total_seconds: float = 300.0
    base_delay_seconds: float = 0.5
    jitter_seconds: float = 0.25

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        if self.attempt_total_seconds <= 0:
            raise ValueError("attempt_total_seconds must be positive")
        if self.action_total_seconds < self.attempt_total_seconds:
            raise ValueError("action_total_seconds must be at least attempt_total_seconds")
        if self.base_delay_seconds < 0 or self.jitter_seconds < 0:
            raise ValueError("retry delays must not be negative")


def _is_blocking_required_target(spec: SpeechSpec) -> bool:
    contract = spec.decision_contract
    return (
        contract.kind == "target"
        and contract.target_mode == "required"
        and bool(spec.allowed_target_ids)
        and not spec.best_effort
        and not spec.isolated_failure
    )


def _effective_model_attempt_limit(
    *,
    spec: SpeechSpec,
    exc: ModelError,
    disposition: FailureDisposition,
    policy: ModelRetryPolicy,
    generation_policy: ResolvedModelGenerationPolicy | None = None,
) -> int:
    if generation_policy is not None and generation_policy.automatic_retry_enforcement == "enforce":
        required_target = _is_blocking_required_target(spec)
        # Required-target actions still need a frozen abstention/no-op rule at
        # their batch or ability layer. Preserve their existing recovery path
        # until that rule is present instead of turning a shorter model wait
        # into an indefinite operator pause.
        preserve_required_target_output_timeout = required_target and (
            generation_policy.blocking_required_target_output_timeout_mode == "legacy_behavior"
            or spec.target_exhaustion_outcome is None
        )
        if disposition.category == "output_budget" and not (
            preserve_required_target_output_timeout
        ):
            return min(
                policy.max_attempts,
                generation_policy.output_budget_max_attempts or 1,
            )
        if disposition.category == "timeout" and not (preserve_required_target_output_timeout):
            hard_timeout = exc.code == "model_attempt_hard_timeout" or exc.timeout_scope in {
                "attempt_hard",
                "action_budget",
            }
            return min(
                policy.max_attempts,
                (
                    generation_policy.attempt_hard_timeout_max_attempts
                    if hard_timeout
                    else generation_policy.timeout_max_attempts
                )
                or 1,
            )
        if disposition.category == "transport":
            max_attempts = (
                generation_policy.post_token_transport_max_attempts
                if exc.first_token_seen or not exc.retryable
                else generation_policy.transport_max_attempts
            )
            return min(policy.max_attempts, max_attempts or 1)
    if exc.code == "model_output_budget_exhausted" and _is_blocking_required_target(spec):
        return min(policy.max_attempts, 3)
    return min(policy.max_attempts, disposition.max_attempts)


@dataclass
class _PausedModelActionWaiter:
    action_id: str
    requested: asyncio.Event
    resumed: asyncio.Event
    control_request_id: str | None = None
    resume_succeeded: bool = False


@dataclass
class _ModelAttemptProgressTrace:
    provider_request_id: str | None = None
    response_headers: dict[str, str] | None = None
    first_token_ms: int | None = None
    first_token_kind: str | None = None
    first_visible_text_ms: int | None = None
    queue_wait_ms: int = 0
    provider_in_flight: int | None = None
    provider_concurrency_limit: int | None = None
    reasoning_delta_count: int = 0
    text_delta_count: int = 0
    reasoning_character_count: int | None = None
    text_character_count: int | None = None
    estimated_reasoning_tokens: int | None = None
    estimated_output_tokens: int | None = None
    max_inter_delta_ms: int | None = None
    last_progress_ms: int | None = None
    provider_usage: dict[str, int] | None = None
    usage_update_count: int = 0
    usage_conflict_observed: bool = False
    usage_consistency: UsageConsistency = "unavailable"
    queued_recorded: bool = False
    admitted_recorded: bool = False
    response_headers_recorded: bool = False
    first_token_recorded: bool = False
    first_text_recorded: bool = False
    last_stream_event_ms: int | None = None

    def accept(self, progress: ModelProgress) -> tuple[str, dict[str, Any]] | None:
        self.provider_request_id = progress.provider_request_id
        if progress.stage == "queued":
            if self.queued_recorded:
                return None
            self.queued_recorded = True
            self.provider_concurrency_limit = progress.provider_concurrency_limit
            return (
                "model_request_queued",
                {
                    "model_provider": progress.provider,
                    "provider_concurrency_limit": progress.provider_concurrency_limit,
                },
            )
        if progress.stage == "admitted":
            if self.admitted_recorded:
                return None
            self.admitted_recorded = True
            self.queue_wait_ms = progress.queue_wait_ms or 0
            self.provider_in_flight = progress.provider_in_flight
            self.provider_concurrency_limit = progress.provider_concurrency_limit
            return (
                "model_request_admitted",
                {
                    "model_provider": progress.provider,
                    "queue_wait_ms": self.queue_wait_ms,
                    "provider_in_flight": progress.provider_in_flight,
                    "provider_concurrency_limit": progress.provider_concurrency_limit,
                },
            )
        if progress.stage == "response_headers":
            if self.response_headers_recorded:
                return None
            self.response_headers_recorded = True
            self.response_headers = dict(progress.response_headers or {})
            return (
                "model_response_headers_received",
                {
                    "provider_request_id": progress.provider_request_id,
                    "response_headers": self.response_headers,
                    "response_headers_ms": progress.elapsed_ms,
                },
            )
        if progress.stage == "first_token":
            if self.first_token_recorded:
                return None
            self.first_token_recorded = True
            self.first_token_ms = progress.elapsed_ms
            self.first_token_kind = progress.token_kind
            return (
                "model_first_token_received",
                {
                    "provider_request_id": progress.provider_request_id,
                    "first_token_ms": progress.elapsed_ms,
                    "first_token_kind": progress.token_kind,
                },
            )
        if progress.stage == "first_text":
            if self.first_text_recorded:
                return None
            self.first_text_recorded = True
            self.first_visible_text_ms = progress.elapsed_ms
            return (
                "model_first_text_delta_received",
                {
                    "provider_request_id": progress.provider_request_id,
                    "first_visible_text_ms": progress.elapsed_ms,
                },
            )
        if progress.stage == "stream_delta":
            if progress.reasoning_delta_count is not None:
                self.reasoning_delta_count = max(
                    self.reasoning_delta_count,
                    progress.reasoning_delta_count,
                )
            if progress.text_delta_count is not None:
                self.text_delta_count = max(
                    self.text_delta_count,
                    progress.text_delta_count,
                )
            if progress.reasoning_character_count is not None:
                self.reasoning_character_count = max(
                    self.reasoning_character_count or 0,
                    progress.reasoning_character_count,
                )
            if progress.text_character_count is not None:
                self.text_character_count = max(
                    self.text_character_count or 0,
                    progress.text_character_count,
                )
            if progress.estimated_reasoning_tokens is not None:
                self.estimated_reasoning_tokens = max(
                    self.estimated_reasoning_tokens or 0,
                    progress.estimated_reasoning_tokens,
                )
            if progress.estimated_output_tokens is not None:
                self.estimated_output_tokens = max(
                    self.estimated_output_tokens or 0,
                    progress.estimated_output_tokens,
                )
            if progress.max_inter_delta_ms is not None:
                self.max_inter_delta_ms = max(
                    self.max_inter_delta_ms or 0,
                    progress.max_inter_delta_ms,
                )
            if progress.last_progress_ms is not None:
                self.last_progress_ms = max(
                    self.last_progress_ms or 0,
                    progress.last_progress_ms,
                )
            if progress.usage_update_count is not None:
                if progress.usage_update_count >= self.usage_update_count:
                    self.usage_update_count = progress.usage_update_count
                    self.provider_usage = (
                        dict(progress.provider_usage)
                        if progress.provider_usage is not None
                        else None
                    )
                    if progress.usage_consistency is not None:
                        self.usage_consistency = progress.usage_consistency
            if progress.usage_conflict_observed is not None:
                self.usage_conflict_observed = (
                    self.usage_conflict_observed or progress.usage_conflict_observed
                )
            # Persisting every delta dominated the event table (~70% of rows);
            # sampled progress keeps diagnostics while counters stay exact
            # because model_response_received carries the final values.
            if self.last_stream_event_ms is not None:
                min_interval_ms = settings.live_v2_stream_progress_min_interval_ms
                if progress.elapsed_ms - self.last_stream_event_ms < min_interval_ms:
                    return None
            self.last_stream_event_ms = progress.elapsed_ms
            return (
                "model_stream_progress",
                {
                    "provider_request_id": progress.provider_request_id,
                    "elapsed_ms": progress.elapsed_ms,
                    "reasoning_delta": progress.reasoning_delta,
                    "text_delta": progress.text_delta,
                    "reasoning_character_count": progress.reasoning_character_count,
                    "text_character_count": progress.text_character_count,
                    "estimated_reasoning_tokens": progress.estimated_reasoning_tokens,
                    "estimated_output_tokens": progress.estimated_output_tokens,
                    "reasoning_delta_count": progress.reasoning_delta_count,
                    "text_delta_count": progress.text_delta_count,
                    "max_inter_delta_ms": progress.max_inter_delta_ms,
                    "last_progress_ms": progress.last_progress_ms,
                    "provider_usage": progress.provider_usage,
                    "usage_update_count": progress.usage_update_count,
                    "usage_conflict_observed": progress.usage_conflict_observed,
                    "usage_consistency": progress.usage_consistency,
                    "token_count_source": (
                        "provider"
                        if progress.provider_usage is not None
                        and (
                            "output_tokens" in progress.provider_usage
                            or "reasoning_tokens" in progress.provider_usage
                        )
                        else "local_estimate"
                    ),
                },
            )
        raise AssertionError(f"unknown model progress stage {progress.stage}")

    def failure_stage(self) -> str:
        if self.first_token_recorded:
            return "stream"
        if self.response_headers_recorded:
            return "first_token"
        if self.queued_recorded and not self.admitted_recorded:
            return "queue"
        return "response_headers"


class ActionEngine:
    def __init__(
        self,
        *,
        repository: ActionRepository,
        model_client: ModelPort,
        tts_client: TtsPort | None,
        tts_client_factory: Callable[[], TtsPort] | None,
        tts_capability_enabled: bool,
        voice_root: Path,
        sample_rate: int,
        judge_configuration_provider: Callable[[str], RuntimeJudgeConfiguration],
        model_retry_policy: ModelRetryPolicy = ModelRetryPolicy(),
    ) -> None:
        self._repository = repository
        self._model_client = model_client
        self._tts_client = tts_client
        self._tts_client_factory = tts_client_factory
        self._tts_capability_enabled = tts_capability_enabled
        self._voice_root = voice_root
        self._sample_rate = sample_rate
        self._judge_configuration_provider = judge_configuration_provider
        self._model_retry_policy = model_retry_policy
        self._paused_model_actions: dict[str, _PausedModelActionWaiter] = {}
        self._paused_model_actions_lock = asyncio.Lock()

    def _tts_client_for_claim(self, claim: ActionClaim) -> TtsPort | None:
        if claim.audio_mode == "text_only":
            return None
        if claim.audio_mode != "tts":
            raise RepositoryError("v2_audio_mode_unknown")
        if not self._tts_capability_enabled:
            raise RepositoryError("v2_audio_mode_unavailable")
        if self._tts_client is None:
            if self._tts_client_factory is None:
                raise RepositoryError("v2_audio_mode_unavailable")
            self._tts_client = self._tts_client_factory()
        if not bool(getattr(self._tts_client, "enabled", True)):
            raise RepositoryError("v2_audio_mode_unavailable")
        return self._tts_client

    def check_cancellation(self, game_id: str) -> None:
        self._repository.check_cancellation(game_id)

    async def retry_paused_model_action(
        self,
        *,
        game_id: str,
        action_id: str,
        control_request_id: str,
    ) -> bool:
        async with self._paused_model_actions_lock:
            waiter = self._paused_model_actions.get(game_id)
            if waiter is None or waiter.action_id != action_id:
                return self._repository.has_durable_model_action_retry(
                    game_id=game_id,
                    action_id=action_id,
                )
            if waiter.requested.is_set():
                return False
            waiter.control_request_id = control_request_id
            waiter.requested.set()
        await waiter.resumed.wait()
        return waiter.resume_succeeded

    async def _pause_for_model_retry(
        self,
        *,
        claim: ActionClaim,
        attempt_id: str | None,
        failure_code: str,
        recovery: dict[str, Any],
        broadcaster: BroadcastPort,
        audience: str,
        failure_episode_id: str | None = None,
        source_failure_episode_ids: tuple[str, ...] = (),
        on_paused: Callable[[], None] | None = None,
        operator_wait: bool = True,
    ) -> None:
        waiter = _PausedModelActionWaiter(
            action_id=claim.action_id,
            requested=asyncio.Event(),
            resumed=asyncio.Event(),
        )
        async with self._paused_model_actions_lock:
            if claim.game_id in self._paused_model_actions:
                raise RepositoryError("model action is already paused")
            self._paused_model_actions[claim.game_id] = waiter
        try:
            self._repository.pause_model_action(
                claim=claim,
                attempt_id=attempt_id,
                failure_code=failure_code,
                recovery=recovery,
                failure_episode_id=failure_episode_id,
                source_failure_episode_ids=source_failure_episode_ids,
            )
            if on_paused is not None:
                on_paused()
            await broadcaster.broadcast_json(
                live_state(
                    game_id=claim.game_id,
                    run_id=claim.run_id,
                    state="paused_model_error",
                    reason=failure_code,
                ),
                audience="all",
            )
            loop = asyncio.get_running_loop()
            auto_resume_deadline: float | None = (
                loop.time() + settings.live_v2_model_auto_retry_seconds
                if settings.live_v2_model_auto_retry_enabled
                else None
            )
            auto_resumed = False
            while not waiter.requested.is_set():
                self.check_cancellation(claim.game_id)
                durable_control_request_id = self._repository.pending_model_action_retry(
                    game_id=claim.game_id,
                    action_id=claim.action_id,
                )
                if durable_control_request_id is not None:
                    waiter.control_request_id = durable_control_request_id
                    waiter.requested.set()
                    break
                if (
                    auto_resume_deadline is not None
                    and loop.time() >= auto_resume_deadline
                ):
                    auto_resume_deadline = None
                    auto_resumed = self._repository.auto_resume_model_action(
                        claim=claim,
                        failure_code=failure_code,
                    )
                    if auto_resumed:
                        waiter.requested.set()
                        break
                    if not operator_wait:
                        # Isolated batch actions have no operator watching the
                        # pause; once auto-retry is exhausted, release the run
                        # and let the action fail into the caller's recovery.
                        self._repository.abandon_model_action_pause(
                            claim=claim,
                            failure_code=failure_code,
                        )
                        await broadcaster.broadcast_json(
                            live_state(
                                game_id=claim.game_id,
                                run_id=claim.run_id,
                                state="generating",
                            ),
                            audience=audience,
                        )
                        raise ModelError(failure_code)
                try:
                    await asyncio.wait_for(waiter.requested.wait(), timeout=0.25)
                except TimeoutError:
                    continue
            if not auto_resumed:
                if waiter.control_request_id is None:
                    raise RepositoryError("model retry has no control request")
                self._repository.resume_model_action(
                    claim=claim,
                    control_request_id=waiter.control_request_id,
                )
            waiter.resume_succeeded = True
            await broadcaster.broadcast_json(
                live_state(
                    game_id=claim.game_id,
                    run_id=claim.run_id,
                    state="generating",
                ),
                audience=audience,
            )
        finally:
            waiter.resumed.set()
            async with self._paused_model_actions_lock:
                if self._paused_model_actions.get(claim.game_id) is waiter:
                    self._paused_model_actions.pop(claim.game_id, None)

    async def run_opening_to_nightfall(
        self,
        *,
        game_id: str,
        broadcaster: BroadcastPort,
    ) -> None:
        opening_completed = await self._run_judge_sentence(
            game_id=game_id,
            broadcaster=broadcaster,
            spec=_OPENING_SPEECH,
        )
        if not opening_completed:
            return
        try:
            transition = self._repository.transition_to_first_night(game_id=game_id)
        except ExecutionOwnershipLost:
            raise
        except Exception as exc:
            failure_kind, failure_code = _failure(exc)
            logger.warning(
                "Live V2 phase transition failed",
                extra={
                    "game_id": game_id,
                    "failure_kind": failure_kind,
                    "failure_code": failure_code,
                },
            )
            try:
                failed_run_id = self._repository.fail_phase_transition(
                    game_id=game_id,
                    failure_kind=failure_kind,
                    failure_code=failure_code,
                )
            except Exception:
                logger.exception("Live V2 could not persist phase transition failure")
                return
            await broadcaster.broadcast_json(
                live_state(
                    game_id=game_id,
                    run_id=failed_run_id,
                    state="failed",
                    reason=failure_code,
                )
            )
            return
        await broadcaster.broadcast_json(game_phase_changed(transition))
        await self._run_judge_sentence(
            game_id=game_id,
            broadcaster=broadcaster,
            spec=_NIGHTFALL_ANNOUNCEMENT,
        )

    async def run_judge_speech(
        self,
        *,
        game_id: str,
        broadcaster: BroadcastPort,
        spec: SpeechSpec,
    ) -> bool:
        return (
            await self._run_model_action(
                game_id=game_id,
                broadcaster=broadcaster,
                spec=spec,
                decision=False,
            )
            is not None
        )

    async def complete_pipeline_speech_technical_skip(
        self,
        *,
        game_id: str,
        broadcaster: BroadcastPort,
        player_id: str,
        player_seat: int,
        action_type: str,
        phase_id: str,
        required_phase_state: str,
        round_no: int,
        speech_round: int,
        speech_order: list[str],
        source_slot_id: str,
        source_action_id: str,
        source_failure: ActionFailure,
        source_terminal_event_record_seq: int,
        on_presentation_opened: Callable[[PresentationIdentity], None] | None = None,
        on_presentation_closed: Callable[[PresentationIdentity], None] | None = None,
    ) -> ActionResult | None:
        """Commit and announce a prefetched public-speech technical skip.

        The source model action is already terminal. This method never opens a
        second player-model request; it records a sanitized public fact and
        presents a fixed judge cue instead.
        """

        if action_type != "day_debate_speech":
            raise ValueError("pipeline technical skip only supports day debate speech")
        if type(player_seat) is not int or player_seat <= 0:
            raise ValueError("pipeline technical skip requires a positive player seat")
        if type(round_no) is not int or round_no <= 0:
            raise ValueError("pipeline technical skip requires a positive round number")
        if type(speech_round) is not int or speech_round <= 0:
            raise ValueError("pipeline technical skip requires a positive speech round")
        if not speech_order or any(not player for player in speech_order):
            raise ValueError("pipeline technical skip requires a speech order")
        if (
            type(source_terminal_event_record_seq) is not int
            or source_terminal_event_record_seq <= 0
        ):
            raise ValueError("pipeline technical skip requires terminal source lineage")

        public_record_seq = self._repository.append_event(
            game_id=game_id,
            event_type="action_skipped_technical",
            audience="all",
            payload={
                "action_id": source_action_id,
                "phase_id": phase_id,
                "round_no": round_no,
                "action_type": action_type,
                "actor_id": player_id,
                "player_seat": player_seat,
                "reason": "technical_failure",
            },
        )
        self._repository.append_event(
            game_id=game_id,
            event_type="day_speech_technical_skip_lineage_recorded",
            audience="god_view",
            payload={
                "phase_id": phase_id,
                "round_no": round_no,
                "action_type": action_type,
                "player_id": player_id,
                "player_seat": player_seat,
                "source_slot_id": source_slot_id,
                "source_action_id": source_action_id,
                "source_terminal_event_record_seq": source_terminal_event_record_seq,
                "source_failure_code": source_failure.code,
                "source_failure_category": source_failure.category,
                "source_attempt_id": source_failure.terminal_attempt_id,
                "source_failure_episode_id": source_failure.failure_episode_id,
                "public_skip_record_seq": public_record_seq,
            },
        )
        return await self._run_model_action(
            game_id=game_id,
            broadcaster=broadcaster,
            spec=SpeechSpec(
                action_type="judge_day_speech_technical_skip",
                phase_id=phase_id,
                required_phase_state=required_phase_state,
                objective=f"说明{player_seat}号本轮因技术原因未能完成发言，流程继续",
                success_live_state="ready",
                success_phase_state=required_phase_state,
                actor_kind="judge",
                actor_id="judge",
                audience="all",
                context={
                    "round_no": round_no,
                    "player_seat": player_seat,
                    "skipped_player_id": player_id,
                    "speech_round": speech_round,
                    "speech_order": list(speech_order),
                    "public_skip_record_seq": public_record_seq,
                },
                best_effort=False,
            ),
            decision=False,
            on_presentation_opened=on_presentation_opened,
            on_presentation_closed=on_presentation_closed,
        )

    async def run_player_decision(
        self,
        *,
        game_id: str,
        broadcaster: BroadcastPort,
        spec: SpeechSpec,
        on_presentation_opened: Callable[[PresentationIdentity], None] | None = None,
        on_presentation_closed: Callable[[PresentationIdentity], None] | None = None,
        model_retry_guard: Callable[[ModelError, int], bool] | None = None,
        on_model_admission_pending: Callable[[], None] | None = None,
    ) -> ModelDecision | None:
        result = await self.run_player_decision_result(
            game_id=game_id,
            broadcaster=broadcaster,
            spec=spec,
            on_presentation_opened=on_presentation_opened,
            on_presentation_closed=on_presentation_closed,
            model_retry_guard=model_retry_guard,
            on_model_admission_pending=on_model_admission_pending,
        )
        return result.decision if result is not None else None

    async def run_player_decision_result(
        self,
        *,
        game_id: str,
        broadcaster: BroadcastPort,
        spec: SpeechSpec,
        on_presentation_opened: Callable[[PresentationIdentity], None] | None = None,
        on_presentation_closed: Callable[[PresentationIdentity], None] | None = None,
        model_retry_guard: Callable[[ModelError, int], bool] | None = None,
        on_model_admission_pending: Callable[[], None] | None = None,
    ) -> ActionResult | None:
        return await self._run_model_action(
            game_id=game_id,
            broadcaster=broadcaster,
            spec=spec,
            decision=True,
            on_presentation_opened=on_presentation_opened,
            on_presentation_closed=on_presentation_closed,
            model_retry_guard=model_retry_guard,
            on_model_admission_pending=on_model_admission_pending,
        )

    async def present_player_decision(
        self,
        *,
        game_id: str,
        broadcaster: BroadcastPort,
        spec: SpeechSpec,
        decision: ModelDecision,
        on_presentation_opened: Callable[[PresentationIdentity], None] | None = None,
        on_presentation_closed: Callable[[PresentationIdentity], None] | None = None,
    ) -> bool:
        return (
            await self.present_player_decision_result(
                game_id=game_id,
                broadcaster=broadcaster,
                spec=spec,
                decision=decision,
                on_presentation_opened=on_presentation_opened,
                on_presentation_closed=on_presentation_closed,
            )
            is not None
        )

    async def present_player_decision_result(
        self,
        *,
        game_id: str,
        broadcaster: BroadcastPort,
        spec: SpeechSpec,
        decision: ModelDecision,
        on_presentation_opened: Callable[[PresentationIdentity], None] | None = None,
        on_presentation_closed: Callable[[PresentationIdentity], None] | None = None,
    ) -> ActionResult | None:
        return await self._run_model_action(
            game_id=game_id,
            broadcaster=broadcaster,
            spec=spec,
            decision=True,
            precomputed_decision=decision,
            on_presentation_opened=on_presentation_opened,
            on_presentation_closed=on_presentation_closed,
        )

    async def _run_judge_sentence(
        self,
        *,
        game_id: str,
        broadcaster: BroadcastPort,
        spec: SpeechSpec,
    ) -> bool:
        return await self.run_judge_speech(
            game_id=game_id,
            broadcaster=broadcaster,
            spec=spec,
        )

    async def _run_model_action(
        self,
        *,
        game_id: str,
        broadcaster: BroadcastPort,
        spec: SpeechSpec,
        decision: bool,
        precomputed_decision: ModelDecision | None = None,
        on_presentation_opened: Callable[[PresentationIdentity], None] | None = None,
        on_presentation_closed: Callable[[PresentationIdentity], None] | None = None,
        model_retry_guard: Callable[[ModelError, int], bool] | None = None,
        on_model_admission_pending: Callable[[], None] | None = None,
    ) -> ActionResult | None:
        action_id = f"v2_action_{uuid4().hex[:16]}"
        judge_configuration = None
        if spec.actor_kind == "judge":
            judge_configuration = self._judge_configuration_provider(game_id)
            model_id = None
            speaker = judge_configuration.tts_speaker
        else:
            model_provider = spec.model_provider
            model_id = spec.model_id
            speaker = spec.speaker
        context = _action_context(game_id=game_id, action_id=action_id, spec=spec)
        if judge_configuration is not None:
            context["judge_configuration"] = {
                "voice_mode": judge_configuration.voice_mode,
                "tts_speaker": judge_configuration.tts_speaker,
                "random_tts_speakers": list(judge_configuration.random_tts_speakers),
                "version": judge_configuration.version,
            }
            context["speech_source"] = "template"
        model_audience = model_event_audience(
            action_audience=spec.audience,
            actor_kind=spec.actor_kind,
        )
        claim = self._repository.claim_action(
            game_id=game_id,
            action_id=action_id,
            context=context,
            expected_phase_id=spec.phase_id,
            expected_phase_state=spec.required_phase_state,
            audience=spec.audience,
            context_audience=(model_audience if spec.actor_kind == "player" else spec.audience),
            activation_id=spec.activation_id,
            best_effort=spec.best_effort,
            non_blocking=spec.defer_presentation,
        )
        if claim is None:
            return None
        context["run_id"] = claim.run_id

        def check_cancellation() -> None:
            self._repository.check_cancellation(claim.game_id)

        identity: PresentationIdentity | None = None
        recorder: VoiceRecorder | None = None
        model_attempt_id: str | None = None
        model_attempt_no: int | None = None
        current_cycle_attempt_no: int | None = None
        model_request_started_recorded = False
        model_request_completed = False
        model_response_record_seq: int | None = None
        terminal_event_record_seq: int | None = None
        request_payload_sha256: str | None = None
        projected_context_sha256: str | None = None
        projected_known_event_refs: tuple[str, ...] | None = None
        projected_known_events_sha256: str | None = None
        model_failure_recorded = False
        active_failure_episode_id: str | None = None
        resolved_generation_policy: ResolvedModelGenerationPolicy | None = None
        resolved_model_provider = spec.model_provider
        resolved_model_id = spec.model_id
        machine_format_failure_count = 0
        last_machine_format_attempt_id: str | None = None
        last_machine_format_failure_code: str | None = None
        output_budget_failure_count = 0
        last_output_budget_attempt_id: str | None = None
        last_output_budget_failure_code: str | None = None
        tts_attempt_id: str | None = None
        retry_cycle = 1
        model_admission_pending_notified = False

        def clear_active_failure_episode() -> None:
            nonlocal active_failure_episode_id
            active_failure_episode_id = None

        try:
            check_cancellation()
            resolved_generation_policy = resolve_model_generation_action_policy(
                claim.model_generation_policy_contract,
                action_type=spec.action_type,
            )
            assert resolved_generation_policy is not None
            if not spec.best_effort and not spec.defer_presentation:
                await broadcaster.broadcast_json(
                    director_scene_changed(
                        game_id=claim.game_id,
                        run_id=claim.run_id,
                        scene=project_director_scene(
                            phase_id=spec.phase_id,
                            phase_state=spec.required_phase_state,
                            action_context=context,
                        ),
                    ),
                    audience="director",
                )
                await broadcaster.broadcast_json(
                    live_state(
                        game_id=claim.game_id,
                        run_id=claim.run_id,
                        state="generating",
                    ),
                    audience=spec.audience,
                )
            model_decision: ModelDecision | None = None
            if precomputed_decision is not None:
                model_decision = precomputed_decision
                speech_text = precomputed_decision.speech
                sentence_ms = precomputed_decision.completed_ms
            elif judge_configuration is not None:
                rendered = render_judge_speech(
                    action_type=spec.action_type,
                    context=context,
                )
                speech_text = rendered.text
                sentence_ms = 0
                self._repository.append_event(
                    game_id=claim.game_id,
                    event_type="judge_speech_rendered",
                    audience=claim.audience,
                    payload={
                        "action_id": claim.action_id,
                        "template_id": rendered.template_id,
                        "template_version": rendered.template_version,
                        "variables": rendered.variables,
                        "text": rendered.text,
                        "voice_mode": judge_configuration.voice_mode,
                        "tts_speaker": judge_configuration.tts_speaker,
                        "judge_configuration_version": judge_configuration.version,
                    },
                )
            else:
                model_attempt_id = f"v2_model_{uuid4().hex[:16]}"
                model_attempt_no = 1
                if model_provider is None or model_id is None:
                    raise ModelError("model_not_configured")
                if not isinstance(spec.model_supports_thinking, bool):
                    raise ModelError("model_parameters_invalid")
                model_parameters, thinking_source = _action_model_parameters(spec)
                model_target = self._model_client.resolve_model_target(
                    model_provider=model_provider,
                    model_id=model_id,
                    model_supports_thinking=spec.model_supports_thinking,
                    model_parameters=model_parameters,
                )
                model_target, thinking_source = _apply_provider_thinking_override(
                    model_target,
                    thinking_source=thinking_source,
                    enabled=spec.disable_provider_thinking,
                )
                resolved_model_provider = model_target.provider
                resolved_model_id = model_target.model_id
                projected_model_context = project_model_action_context_with_metadata(
                    context,
                    players=spec.model_players,
                    model_context_contract=claim.model_context_contract,
                    action_record_seq=claim.action_record_seq,
                    projection_at_seq=spec.projection_at_seq,
                )
                model_context = projected_model_context.context
                projected_context_sha256 = hashlib.sha256(
                    json.dumps(
                        model_context,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    ).encode("utf-8")
                ).hexdigest()
                projected_known_events = model_context.get("known_events")
                if isinstance(projected_known_events, dict):
                    projected_known_event_refs = tuple(
                        str(item["event_ref"])
                        for item in projected_model_context.observation_context.get(
                            "known_events", {}
                        ).get("events", [])
                        if isinstance(item, dict)
                        and isinstance(item.get("event_ref"), str)
                    )
                    projected_known_events_sha256 = hashlib.sha256(
                        json.dumps(
                            projected_known_events,
                            ensure_ascii=False,
                            sort_keys=True,
                            separators=(",", ":"),
                        ).encode("utf-8")
                    ).hexdigest()
                observation_context = projected_model_context.observation_context
                prompt_projection = model_prompt_metadata(
                    model_context,
                    projection_metadata=(projected_model_context.projection_metadata),
                )
                output_enforcement_metadata = self._model_client.output_enforcement_metadata(
                    action_context=model_context,
                    decision=decision,
                    target=model_target,
                )
                output_enforcement = {
                    "requested": output_enforcement_metadata.get("requested_output_enforcement"),
                    "actual": output_enforcement_metadata.get("provider_output_enforcement"),
                    "schema_name": output_enforcement_metadata.get("output_schema_name"),
                    "schema_version": output_enforcement_metadata.get("output_schema_version"),
                }
                request_payload = self._model_client.build_request_payload(
                    action_context=model_context,
                    decision=decision,
                    target=model_target,
                )
                request_payload_sha256 = hashlib.sha256(
                    json.dumps(
                        request_payload,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    ).encode("utf-8")
                ).hexdigest()
                configured_max_tokens = model_target.parameters["max_tokens"]
                max_tokens_mode = model_target.parameters["max_tokens_mode"]
                effective_max_tokens = request_payload.get(
                    "max_output_tokens",
                    request_payload.get("max_tokens"),
                )
                retry_policy = self._model_retry_policy
                manages_attempt_timeout = bool(
                    getattr(self._model_client, "manages_attempt_timeout", False)
                )
                previous_attempt_id: str | None = None
                model_attempt_no = 0
                if spec.preflight_pause_failure is not None:
                    preflight = spec.preflight_pause_failure
                    self._repository.append_event(
                        game_id=claim.game_id,
                        event_type="model_automatic_retry_suppressed",
                        audience=model_audience,
                        payload={
                            "action_id": claim.action_id,
                            "decision_family_id": spec.decision_family_id,
                            "source_action_id": preflight.source_action_id,
                            "source_attempt_id": preflight.source_attempt_id,
                            "failure_code": preflight.failure_code,
                            "failure_category": preflight.failure_category,
                            "automatic_machine_format_attempt_count": (
                                preflight.automatic_machine_format_attempt_count
                            ),
                            "automatic_output_budget_attempt_count": (
                                preflight.automatic_output_budget_attempt_count
                            ),
                            "prior_output_budget_failures": (spec.prior_output_budget_failures),
                            "automatic_output_budget_budget": (spec.automatic_output_budget_budget),
                            "source_failure_episode_ids": list(
                                preflight.source_failure_episode_ids
                            ),
                            "suppression_reason": "decision_family_budget_exhausted",
                        },
                    )
                    await self._pause_for_model_retry(
                        claim=claim,
                        attempt_id=None,
                        failure_code=preflight.failure_code,
                        recovery=_model_action_recovery_snapshot(
                            spec=spec,
                            target=model_target,
                            request_payload=request_payload,
                            model_context=model_context,
                            failure_category=preflight.failure_category,
                            attempt_no=0,
                            retry_cycle=retry_cycle,
                            machine_format_failure_count=0,
                            output_budget_failure_count=0,
                        ),
                        broadcaster=broadcaster,
                        audience=spec.audience,
                        source_failure_episode_ids=(preflight.source_failure_episode_ids),
                    )
                    previous_attempt_id = preflight.source_attempt_id
                    retry_cycle += 1
                while model_decision is None:
                    model_started_at = time.monotonic()
                    blocking_required_target = _is_blocking_required_target(spec)
                    effective_queue_wait_budget_mode = (
                        resolved_generation_policy.blocking_required_target_queue_wait_budget_mode
                        if blocking_required_target
                        else resolved_generation_policy.queue_wait_budget_mode
                    )
                    effective_output_timeout_retry_mode = (
                        resolved_generation_policy.blocking_required_target_output_timeout_mode
                        if blocking_required_target
                        else resolved_generation_policy.automatic_retry_enforcement
                    )
                    wall_clock_budget_enforced = (
                        resolved_generation_policy.action_wall_timeout_ms is not None
                        and effective_queue_wait_budget_mode == "wall_clock"
                    )
                    action_budget_seconds = retry_policy.action_total_seconds
                    if resolved_generation_policy.action_wall_timeout_ms is not None:
                        action_budget_seconds = min(
                            action_budget_seconds,
                            resolved_generation_policy.action_wall_timeout_ms / 1000,
                        )
                    model_deadline = model_started_at + action_budget_seconds
                    model_queue_wait_seconds = 0.0
                    # Operator resume starts a new retry cycle.  The observed
                    # window for a possible third output-budget attempt is
                    # therefore cycle-local, while the decision-family counter
                    # below only consumes automatic failures from cycle one.
                    cycle_output_budget_failure_count = 0
                    attempt_ids = [
                        (
                            model_attempt_id
                            if model_attempt_no == 0
                            else f"v2_model_{uuid4().hex[:16]}"
                        ),
                        *[
                            f"v2_model_{uuid4().hex[:16]}"
                            for _ in range(retry_policy.max_attempts - 1)
                        ],
                    ]
                    resumed_after_pause = False
                    for cycle_attempt_index, attempt_id in enumerate(attempt_ids):
                        model_attempt_id = attempt_id
                        model_attempt_no += 1
                        cycle_attempt_no = cycle_attempt_index + 1
                        current_cycle_attempt_no = cycle_attempt_no
                        model_request_started_recorded = False
                        model_failure_recorded = False
                        binding_prior_failure_streak = (
                            self._repository.model_binding_failure_streak(
                                game_id=claim.game_id,
                                actor_id=spec.actor_id,
                                model_provider=model_target.provider,
                                model_id=model_target.model_id,
                            )
                        )
                        attempt_started_at = time.monotonic()
                        attempt_queued_at: float | None = None
                        attempt_progress = _ModelAttemptProgressTrace()
                        managed_action_timeout: asyncio.Timeout | None = None
                        progress_method = getattr(
                            type(self._model_client),
                            "generate_action_decision_with_progress",
                            None,
                        )
                        progress_capable = callable(progress_method)

                        def persist_model_progress(
                            progress: ModelProgress,
                            *,
                            observed_attempt_id: str = attempt_id,
                        ) -> None:
                            nonlocal attempt_started_at
                            nonlocal model_deadline
                            nonlocal model_queue_wait_seconds
                            nonlocal attempt_queued_at
                            if progress.stage == "queued" and attempt_queued_at is None:
                                attempt_queued_at = time.monotonic()
                            if progress.stage == "admitted":
                                queue_wait_seconds = (progress.queue_wait_ms or 0) / 1000
                                model_queue_wait_seconds += queue_wait_seconds
                                if not wall_clock_budget_enforced:
                                    model_deadline += queue_wait_seconds
                                attempt_started_at = time.monotonic()
                                if managed_action_timeout is not None:
                                    active_action_remaining = max(
                                        0.0,
                                        model_deadline - time.monotonic(),
                                    )
                                    managed_action_timeout.reschedule(
                                        asyncio.get_running_loop().time() + active_action_remaining
                                    )
                            observed = attempt_progress.accept(progress)
                            if observed is None:
                                return
                            event_type, progress_payload = observed
                            self._repository.append_event(
                                game_id=claim.game_id,
                                event_type=event_type,
                                audience=model_audience,
                                payload={
                                    "action_id": claim.action_id,
                                    "attempt_id": observed_attempt_id,
                                    **progress_payload,
                                },
                            )

                        self._repository.append_event(
                            game_id=claim.game_id,
                            event_type="model_request_started",
                            audience=model_audience,
                            payload={
                                "action_id": claim.action_id,
                                "attempt_id": model_attempt_id,
                                "decision_family_id": spec.decision_family_id,
                                "prior_machine_format_failures": (
                                    spec.prior_machine_format_failures
                                ),
                                "automatic_machine_format_budget": (
                                    spec.automatic_machine_format_budget
                                ),
                                "automatic_machine_format_attempt_count": (
                                    min(
                                        spec.prior_machine_format_failures
                                        + machine_format_failure_count,
                                        spec.automatic_machine_format_budget,
                                    )
                                    if spec.automatic_machine_format_budget is not None
                                    else None
                                ),
                                "prior_output_budget_failures": (spec.prior_output_budget_failures),
                                "automatic_output_budget_budget": (
                                    spec.automatic_output_budget_budget
                                ),
                                "automatic_output_budget_attempt_count": (
                                    min(
                                        spec.prior_output_budget_failures
                                        + output_budget_failure_count,
                                        spec.automatic_output_budget_budget,
                                    )
                                    if spec.automatic_output_budget_budget is not None
                                    else None
                                ),
                                "attempt_no": model_attempt_no,
                                "cycle_attempt_no": cycle_attempt_no,
                                "retry_cycle": retry_cycle,
                                "max_attempts": retry_policy.max_attempts,
                                "attempt_budget_ms": round(
                                    retry_policy.attempt_total_seconds * 1000
                                ),
                                "action_budget_ms": round(action_budget_seconds * 1000),
                                "action_wall_budget_enforced": wall_clock_budget_enforced,
                                "blocking_required_target": blocking_required_target,
                                "effective_output_timeout_retry_mode": (
                                    effective_output_timeout_retry_mode
                                ),
                                "effective_queue_wait_budget_mode": (
                                    effective_queue_wait_budget_mode
                                ),
                                "first_token_timeout_ms": round(
                                    getattr(
                                        self._model_client,
                                        "first_token_seconds",
                                        retry_policy.attempt_total_seconds,
                                    )
                                    * 1000
                                ),
                                "stream_idle_timeout_ms": round(
                                    getattr(
                                        self._model_client,
                                        "stream_idle_seconds",
                                        retry_policy.attempt_total_seconds,
                                    )
                                    * 1000
                                ),
                                "provider_concurrency_limit": (
                                    self._model_client.provider_concurrency_limit(
                                        model_target.provider
                                    )
                                    if callable(
                                        getattr(
                                            self._model_client,
                                            "provider_concurrency_limit",
                                            None,
                                        )
                                    )
                                    else None
                                ),
                                "action_remaining_ms": max(
                                    0,
                                    round((model_deadline - time.monotonic()) * 1000),
                                ),
                                "retry_of_attempt_id": previous_attempt_id,
                                **(
                                    {"failure_episode_id": (active_failure_episode_id)}
                                    if active_failure_episode_id is not None
                                    else {}
                                ),
                                "request_kind": "decision" if decision else "speech",
                                "model_id": model_target.model_id,
                                "model_provider": model_target.provider,
                                "model_binding_prior_failure_streak": (
                                    binding_prior_failure_streak
                                ),
                                "model_binding_health_status": (
                                    _model_binding_health_status(binding_prior_failure_streak)
                                ),
                                "model_parameters": dict(model_target.parameters),
                                "configured_max_tokens": (configured_max_tokens),
                                "effective_max_tokens": effective_max_tokens,
                                "max_tokens_source": "model_configuration",
                                "max_tokens_mode": max_tokens_mode,
                                "thinking": model_target.parameters["thinking"],
                                "thinking_source": thinking_source,
                                "judge_configuration_version": None,
                                "actor_kind": spec.actor_kind,
                                "actor_id": spec.actor_id,
                                "prompt_schema_version": (
                                    model_context.get("prompt_schema_version")
                                    or model_context.get("model_context_schema_version")
                                ),
                                "model_context_schema_version": model_context.get(
                                    "model_context_schema_version"
                                ),
                                "prompt_template_version": model_context.get(
                                    "prompt_template_version"
                                ),
                                "model_view_selector_version": prompt_projection.get(
                                    "model_view_selector_version"
                                ),
                                "prompt_projection": prompt_projection,
                                "model_context": model_context,
                                "output_enforcement": output_enforcement,
                                "request_payload": request_payload,
                                **_model_generation_policy_audit_payload(
                                    policy=resolved_generation_policy,
                                    action_type=spec.action_type,
                                    model_provider=resolved_model_provider,
                                    model_id=resolved_model_id,
                                ),
                            },
                        )
                        model_request_started_recorded = True
                        check_cancellation()
                        remaining = model_deadline - time.monotonic()
                        try:
                            if remaining <= 0:
                                raise ModelError(
                                    "model_total_timeout",
                                    failure_stage="action_budget",
                                    elapsed_ms=0,
                                )
                            request_timeout = min(
                                remaining,
                                retry_policy.attempt_total_seconds,
                            )
                            timeout_stage = (
                                "attempt_budget"
                                if retry_policy.attempt_total_seconds <= remaining
                                else "action_budget"
                            )
                            try:

                                async def generate_once() -> ModelDecision:
                                    nonlocal model_admission_pending_notified
                                    if (
                                        on_model_admission_pending is not None
                                        and not model_admission_pending_notified
                                    ):
                                        on_model_admission_pending()
                                        model_admission_pending_notified = True
                                    if progress_capable:
                                        progress_kwargs: dict[str, Any] = {
                                            "action_context": model_context,
                                            "attempt_id": model_attempt_id,
                                            "target": model_target,
                                            "check_cancellation": check_cancellation,
                                            "on_progress": persist_model_progress,
                                        }
                                        if spec.model_admission_mode != "normal":
                                            progress_kwargs["admission_mode"] = (
                                                spec.model_admission_mode
                                            )
                                        return await progress_method(
                                            self._model_client,
                                            **progress_kwargs,
                                        )
                                    generation_kwargs: dict[str, Any] = {
                                        "action_context": model_context,
                                        "attempt_id": model_attempt_id,
                                        "target": model_target,
                                        "check_cancellation": check_cancellation,
                                    }
                                    if spec.model_admission_mode != "normal":
                                        generation_kwargs["admission_mode"] = (
                                            spec.model_admission_mode
                                        )
                                    return await self._model_client.generate_action_decision(
                                        **generation_kwargs,
                                    )

                                if manages_attempt_timeout:
                                    async with asyncio.timeout(
                                        remaining if wall_clock_budget_enforced else None
                                    ) as action_timeout:
                                        managed_action_timeout = action_timeout
                                        model_decision = await generate_once()
                                else:
                                    async with asyncio.timeout(request_timeout):
                                        model_decision = await generate_once()
                                _validate_model_target_decision(
                                    model_decision,
                                    spec=spec,
                                )
                            except TimeoutError as exc:
                                observed_timeout_stage = (
                                    "action_budget" if manages_attempt_timeout else timeout_stage
                                )
                                raise ModelError(
                                    "model_total_timeout",
                                    retryable=observed_timeout_stage == "attempt_budget",
                                    failure_stage=(
                                        attempt_progress.failure_stage()
                                        if progress_capable
                                        else observed_timeout_stage
                                    ),
                                    provider_request_id=(attempt_progress.provider_request_id),
                                    first_token_seen=(attempt_progress.first_token_recorded),
                                    response_headers_seen=(
                                        attempt_progress.response_headers_recorded
                                    ),
                                    response_headers=(attempt_progress.response_headers),
                                    first_token_ms=attempt_progress.first_token_ms,
                                    first_token_kind=(attempt_progress.first_token_kind),
                                    first_visible_text_ms=(attempt_progress.first_visible_text_ms),
                                    timeout_scope=observed_timeout_stage,
                                    elapsed_ms=round(
                                        (time.monotonic() - attempt_started_at) * 1000
                                    ),
                                ) from exc
                        except ModelError as exc:
                            _enrich_model_error_from_progress(
                                exc,
                                attempt_progress,
                                progress_capable=progress_capable,
                            )
                            if model_decision is not None:
                                _enrich_model_error_from_decision(exc, model_decision)
                            # Validation errors are raised after the client has
                            # returned a decision object. Never carry that invalid
                            # object across an automatic or operator-triggered retry.
                            model_decision = None
                            disposition = model_failure_disposition(exc)
                            if disposition.category == "machine_format":
                                if retry_cycle == 1:
                                    machine_format_failure_count += 1
                                last_machine_format_attempt_id = model_attempt_id
                                last_machine_format_failure_code = exc.code
                            if disposition.category == "output_budget":
                                cycle_output_budget_failure_count += 1
                                if retry_cycle == 1:
                                    output_budget_failure_count += 1
                                last_output_budget_attempt_id = model_attempt_id
                                last_output_budget_failure_code = exc.code
                            family_machine_format_attempt_count = (
                                spec.prior_machine_format_failures + machine_format_failure_count
                            )
                            family_machine_format_retry_available = (
                                disposition.category != "machine_format"
                                or retry_cycle > 1
                                or spec.automatic_machine_format_budget is None
                                or family_machine_format_attempt_count
                                < spec.automatic_machine_format_budget
                            )
                            family_output_budget_attempt_count = (
                                spec.prior_output_budget_failures + output_budget_failure_count
                            )
                            family_output_budget_retry_available = (
                                disposition.category != "output_budget"
                                or retry_cycle > 1
                                or spec.automatic_output_budget_budget is None
                                or family_output_budget_attempt_count
                                < spec.automatic_output_budget_budget
                            )
                            family_retry_available = (
                                family_machine_format_retry_available
                                and family_output_budget_retry_available
                            )
                            remaining = model_deadline - time.monotonic()
                            delay_seconds = _model_retry_delay_seconds(
                                disposition=disposition,
                                exc=exc,
                                cycle_attempt_no=cycle_attempt_no,
                                policy=retry_policy,
                            )
                            required_retry_window = _required_retry_window_seconds(
                                spec=spec,
                                disposition=disposition,
                                exc=exc,
                                policy=retry_policy,
                                cycle_output_budget_failure_count=(
                                    cycle_output_budget_failure_count
                                ),
                            )
                            effective_attempt_limit = _effective_model_attempt_limit(
                                spec=spec,
                                exc=exc,
                                disposition=disposition,
                                policy=retry_policy,
                                generation_policy=resolved_generation_policy,
                            )
                            pipeline_retry_guard_allowed: bool | None = None
                            pipeline_retry_guard_error = False
                            pipeline_retry_enabled = (
                                spec.pipeline_stage == "generation"
                                and spec.pipeline_retry_mode
                                == "empty_stream_once_while_predecessor_active"
                            )
                            if (
                                pipeline_retry_enabled
                                and disposition.category == "output_budget"
                            ):
                                # The guarded expansion is exclusively for an empty
                                # stream. Repeating the same output budget can spend
                                # the full reasoning allocation again without adding
                                # any new recovery signal.
                                effective_attempt_limit = 1
                            if (
                                pipeline_retry_enabled
                                and disposition.category == "transport"
                            ):
                                # The frozen pipeline contract only permits a second
                                # physical attempt for the known empty-stream case and
                                # only while the predecessor presentation is active.
                                # Other transport failures remain single-attempt.
                                pipeline_retry_guard_allowed = False
                                effective_attempt_limit = 1
                                if (
                                    exc.code == "model_empty_stream"
                                    and cycle_attempt_no < spec.pipeline_empty_stream_max_attempts
                                    and model_retry_guard is not None
                                ):
                                    try:
                                        pipeline_retry_guard_allowed = bool(
                                            model_retry_guard(exc, cycle_attempt_no)
                                        )
                                    except (asyncio.CancelledError, ExecutionOwnershipLost):
                                        raise
                                    except Exception:
                                        pipeline_retry_guard_error = True
                                        logger.warning(
                                            "Live V2 pipeline retry guard failed closed",
                                            exc_info=True,
                                            extra={
                                                "game_id": claim.game_id,
                                                "action_id": claim.action_id,
                                                "slot_id": spec.pipeline_slot_id,
                                            },
                                        )
                                if pipeline_retry_guard_allowed:
                                    effective_attempt_limit = min(
                                        retry_policy.max_attempts,
                                        spec.pipeline_empty_stream_max_attempts,
                                    )
                                    # This retry is deliberately hidden inside the
                                    # predecessor's playback window. Do not burn that
                                    # narrow window on the generic backoff delay.
                                    delay_seconds = 0.0
                            if (
                                disposition.category == "output_budget"
                                and retry_cycle == 1
                                and spec.automatic_output_budget_budget is not None
                            ):
                                family_remaining = max(
                                    0,
                                    spec.automatic_output_budget_budget
                                    - family_output_budget_attempt_count,
                                )
                                effective_attempt_limit = min(
                                    effective_attempt_limit,
                                    cycle_attempt_no + family_remaining,
                                )
                            retryable = (
                                disposition.retryable
                                and family_retry_available
                                and cycle_attempt_no < effective_attempt_limit
                                and remaining > delay_seconds + required_retry_window
                            )
                            if not disposition.retryable:
                                automatic_retry_stop_reason = "not_retryable"
                            elif (
                                pipeline_retry_guard_allowed is False
                                and exc.code == "model_empty_stream"
                            ):
                                automatic_retry_stop_reason = "attempt_limit_reached"
                            elif not family_retry_available:
                                automatic_retry_stop_reason = "decision_family_budget_exhausted"
                            elif cycle_attempt_no >= effective_attempt_limit:
                                automatic_retry_stop_reason = "attempt_limit_reached"
                            elif remaining <= delay_seconds + required_retry_window:
                                automatic_retry_stop_reason = "insufficient_action_budget"
                            else:
                                automatic_retry_stop_reason = None
                            binding_health_counted = disposition.category != "admission_capacity"
                            binding_failure_streak = binding_prior_failure_streak + int(
                                binding_health_counted
                            )
                            binding_health_status = _model_binding_health_status(
                                binding_failure_streak
                            )
                            failure_episode_id = active_failure_episode_id
                            if failure_episode_id is None:
                                failure_episode_id = stable_failure_episode_id(
                                    game_id=claim.game_id,
                                    run_id=claim.run_id,
                                    action_id=claim.action_id,
                                    retry_cycle=retry_cycle,
                                    first_failed_attempt_id=model_attempt_id,
                                )
                            unadmitted_queue_wait_seconds = (
                                max(0.0, time.monotonic() - attempt_queued_at)
                                if attempt_queued_at is not None
                                and not attempt_progress.admitted_recorded
                                else 0.0
                            )
                            observed_queue_wait_seconds = (
                                model_queue_wait_seconds + unadmitted_queue_wait_seconds
                            )
                            action_active_elapsed_seconds = max(
                                0.0,
                                time.monotonic() - model_started_at - observed_queue_wait_seconds,
                            )
                            failure_payload = _model_failure_payload(
                                action_id=claim.action_id,
                                attempt_id=model_attempt_id,
                                attempt_no=model_attempt_no,
                                max_attempts=retry_policy.max_attempts,
                                retry_cycle=retry_cycle,
                                cycle_attempt_no=cycle_attempt_no,
                                exc=exc,
                                failure_category=disposition.category,
                                retryable=disposition.retryable,
                                action_recoverable=disposition.pausable,
                                terminal=not retryable,
                                attempt_budget_ms=round(retry_policy.attempt_total_seconds * 1000),
                                action_budget_ms=round(action_budget_seconds * 1000),
                                action_elapsed_ms=round(action_active_elapsed_seconds * 1000),
                                action_remaining_ms=max(
                                    0,
                                    round((model_deadline - time.monotonic()) * 1000),
                                ),
                                model_binding_failure_streak=(binding_failure_streak),
                                model_binding_health_status=(binding_health_status),
                            )
                            failure_payload.update(
                                _model_generation_policy_audit_payload(
                                    policy=resolved_generation_policy,
                                    action_type=spec.action_type,
                                    model_provider=resolved_model_provider,
                                    model_id=resolved_model_id,
                                    explicit_reasoning_only_elapsed_ms=(
                                        exc.reasoning_only_elapsed_ms
                                    ),
                                    first_token_ms=exc.first_token_ms,
                                    first_visible_text_ms=exc.first_visible_text_ms,
                                    terminal_elapsed_ms=exc.elapsed_ms,
                                )
                            )
                            failure_payload["failure_episode_id"] = failure_episode_id
                            failure_payload.update(
                                {
                                    "action_wall_elapsed_ms": round(
                                        (time.monotonic() - model_started_at) * 1000
                                    ),
                                    "action_wall_budget_enforced": (wall_clock_budget_enforced),
                                    "observed_queue_wait_elapsed_ms": round(
                                        observed_queue_wait_seconds * 1000
                                    ),
                                    "blocking_required_target": blocking_required_target,
                                    "effective_output_timeout_retry_mode": (
                                        effective_output_timeout_retry_mode
                                    ),
                                    "effective_queue_wait_budget_mode": (
                                        effective_queue_wait_budget_mode
                                    ),
                                    "effective_attempt_limit": effective_attempt_limit,
                                    "retry_delay_ms": round(delay_seconds * 1000),
                                    "required_retry_window_ms": round(required_retry_window * 1000),
                                    "automatic_retry_scheduled": retryable,
                                    "automatic_retry_stop_reason": (automatic_retry_stop_reason),
                                    "model_binding_health_counted": binding_health_counted,
                                    "pipeline_retry_mode": spec.pipeline_retry_mode,
                                    "pipeline_empty_stream_max_attempts": (
                                        spec.pipeline_empty_stream_max_attempts
                                    ),
                                    "pipeline_retry_guard_allowed": (pipeline_retry_guard_allowed),
                                    "pipeline_retry_guard_error": pipeline_retry_guard_error,
                                }
                            )
                            if spec.decision_family_id is not None:
                                failure_payload["decision_family_id"] = spec.decision_family_id
                            if disposition.category == "machine_format":
                                failure_payload["automatic_machine_format_attempt_count"] = (
                                    min(
                                        family_machine_format_attempt_count,
                                        spec.automatic_machine_format_budget,
                                    )
                                    if spec.automatic_machine_format_budget is not None
                                    else family_machine_format_attempt_count
                                )
                                failure_payload["automatic_machine_format_budget"] = (
                                    spec.automatic_machine_format_budget
                                )
                            if disposition.category == "output_budget":
                                failure_payload.update(
                                    {
                                        "output_budget_failure_count": (
                                            output_budget_failure_count
                                        ),
                                        "last_output_budget_attempt_id": (
                                            last_output_budget_attempt_id
                                        ),
                                        "last_output_budget_failure_code": (
                                            last_output_budget_failure_code
                                        ),
                                        "prior_output_budget_failures": (
                                            spec.prior_output_budget_failures
                                        ),
                                        "automatic_output_budget_attempt_count": (
                                            min(
                                                family_output_budget_attempt_count,
                                                spec.automatic_output_budget_budget,
                                            )
                                            if spec.automatic_output_budget_budget is not None
                                            else family_output_budget_attempt_count
                                        ),
                                        "automatic_output_budget_budget": (
                                            spec.automatic_output_budget_budget
                                        ),
                                    }
                                )
                            self._repository.append_event(
                                game_id=claim.game_id,
                                event_type="model_request_failed",
                                audience=model_audience,
                                payload=failure_payload,
                            )
                            model_failure_recorded = True
                            active_failure_episode_id = failure_episode_id
                            if binding_health_counted:
                                self._repository.append_event(
                                    game_id=claim.game_id,
                                    event_type="model_binding_health_updated",
                                    audience="god_view",
                                    payload={
                                        "action_id": claim.action_id,
                                        "attempt_id": model_attempt_id,
                                        "phase_id": spec.phase_id,
                                        "actor_id": spec.actor_id,
                                        "model_provider": model_target.provider,
                                        "model_id": model_target.model_id,
                                        "status": binding_health_status,
                                        "consecutive_failure_count": (binding_failure_streak),
                                        "failure_code": exc.code,
                                        "failure_category": disposition.category,
                                        "failure_stage": exc.failure_stage,
                                        "first_token_seen": exc.first_token_seen,
                                        "response_headers_seen": (exc.response_headers_seen),
                                    },
                                )
                            previous_attempt_id = model_attempt_id
                            if retryable:
                                next_attempt_id = attempt_ids[cycle_attempt_index + 1]
                                self._repository.append_event(
                                    game_id=claim.game_id,
                                    event_type="model_retry_scheduled",
                                    audience=model_audience,
                                    payload={
                                        "action_id": claim.action_id,
                                        "attempt_id": model_attempt_id,
                                        "decision_family_id": spec.decision_family_id,
                                        "next_attempt_id": next_attempt_id,
                                        "attempt_no": model_attempt_no,
                                        "next_attempt_no": model_attempt_no + 1,
                                        "cycle_attempt_no": cycle_attempt_no,
                                        "retry_cycle": retry_cycle,
                                        "max_attempts": retry_policy.max_attempts,
                                        "effective_attempt_limit": (effective_attempt_limit),
                                        "failure_code": exc.code,
                                        "failure_episode_id": failure_episode_id,
                                        "delay_ms": round(delay_seconds * 1000),
                                        "required_retry_window_ms": round(
                                            required_retry_window * 1000
                                        ),
                                        "retry_after_ms": (
                                            round(exc.retry_after_seconds * 1000)
                                            if exc.retry_after_seconds is not None
                                            else None
                                        ),
                                        "action_remaining_ms": max(
                                            0,
                                            round((model_deadline - time.monotonic()) * 1000),
                                        ),
                                        **(
                                            {
                                                "output_budget_failure_count": (
                                                    output_budget_failure_count
                                                ),
                                                "prior_output_budget_failures": (
                                                    spec.prior_output_budget_failures
                                                ),
                                                "automatic_output_budget_attempt_count": (
                                                    min(
                                                        family_output_budget_attempt_count,
                                                        spec.automatic_output_budget_budget,
                                                    )
                                                    if spec.automatic_output_budget_budget
                                                    is not None
                                                    else family_output_budget_attempt_count
                                                ),
                                                "automatic_output_budget_budget": (
                                                    spec.automatic_output_budget_budget
                                                ),
                                            }
                                            if disposition.category == "output_budget"
                                            else {}
                                        ),
                                    },
                                )
                                await _sleep_with_cancellation(
                                    delay_seconds,
                                    check_cancellation=check_cancellation,
                                )
                                continue
                            target_technical_outcome = _technical_target_exhaustion_outcome(
                                spec=spec,
                                exc=exc,
                                generation_policy=resolved_generation_policy,
                            )
                            if target_technical_outcome is not None:
                                target_outcome_kind, target_failure_mode = target_technical_outcome
                                event_type = "technical_target_outcome_applied"
                                technical_outcome_record_seq = self._repository.append_event(
                                    game_id=claim.game_id,
                                    event_type=event_type,
                                    audience=claim.audience,
                                    payload={
                                        "action_id": claim.action_id,
                                        "activation_id": spec.activation_id,
                                        "attempt_id": model_attempt_id,
                                        "failure_episode_id": failure_episode_id,
                                        "action_type": spec.action_type,
                                        "actor_id": spec.actor_id,
                                        "phase_id": spec.phase_id,
                                        "round_no": (
                                            spec.context.get("round_no")
                                            if isinstance(spec.context, dict)
                                            else None
                                        ),
                                        "failure_code": exc.code,
                                        "failure_category": disposition.category,
                                        "target_exhaustion_failure_mode": target_failure_mode,
                                        "technical_outcome": target_outcome_kind,
                                        "target_player_id": None,
                                        "model_generation_policy_schema_version": (
                                            resolved_generation_policy.schema_version
                                        ),
                                    },
                                )
                                self._repository.complete_silent_action(
                                    claim=claim,
                                    next_live_state=spec.success_live_state,
                                    next_phase_state=spec.success_phase_state,
                                    best_effort=spec.best_effort,
                                    failure_episode_id=failure_episode_id,
                                    technical_outcome_record_seq=(technical_outcome_record_seq),
                                )
                                clear_active_failure_episode()
                                if not spec.best_effort and not spec.defer_presentation:
                                    await broadcaster.broadcast_json(
                                        live_state(
                                            game_id=claim.game_id,
                                            run_id=claim.run_id,
                                            state=spec.success_live_state,
                                            reason=event_type,
                                        ),
                                        audience=spec.audience,
                                    )
                                return ActionResult(
                                    action_id=claim.action_id,
                                    technical_outcome=ActionTechnicalOutcome(
                                        kind=target_outcome_kind,
                                        failure_mode=target_failure_mode,
                                        failure=ActionFailure(
                                            code=exc.code,
                                            category=disposition.category,
                                            terminal_attempt_id=model_attempt_id,
                                            machine_format_failure_count=(
                                                machine_format_failure_count
                                            ),
                                            last_machine_format_attempt_id=(
                                                last_machine_format_attempt_id
                                            ),
                                            last_machine_format_failure_code=(
                                                last_machine_format_failure_code
                                            ),
                                            output_budget_failure_count=(
                                                output_budget_failure_count
                                            ),
                                            last_output_budget_attempt_id=(
                                                last_output_budget_attempt_id
                                            ),
                                            last_output_budget_failure_code=(
                                                last_output_budget_failure_code
                                            ),
                                            failure_episode_id=failure_episode_id,
                                        ),
                                        supporting_event_record_seq=(technical_outcome_record_seq),
                                    ),
                                    model_response_record_seq=model_response_record_seq,
                                    terminal_event_record_seq=terminal_event_record_seq,
                                )
                            technical_outcome = _technical_exhaustion_outcome(
                                spec=spec,
                                exc=exc,
                                attempt_id=model_attempt_id,
                            )
                            if technical_outcome is not None:
                                technical_decision, event_type = technical_outcome
                                technical_outcome_record_seq = self._repository.append_event(
                                    game_id=claim.game_id,
                                    event_type=event_type,
                                    audience=claim.audience,
                                    payload={
                                        "action_id": claim.action_id,
                                        "attempt_id": model_attempt_id,
                                        "failure_episode_id": failure_episode_id,
                                        "action_type": spec.action_type,
                                        "actor_id": spec.actor_id,
                                        "phase_id": spec.phase_id,
                                        "round_no": (
                                            spec.context.get("round_no")
                                            if isinstance(spec.context, dict)
                                            else None
                                        ),
                                        "failure_code": exc.code,
                                        "failure_category": disposition.category,
                                        "raw_response_preserved": isinstance(
                                            exc,
                                            QualityError,
                                        )
                                        and exc.raw_response is not None,
                                    },
                                )
                                self._repository.complete_silent_action(
                                    claim=claim,
                                    next_live_state=spec.success_live_state,
                                    next_phase_state=spec.success_phase_state,
                                    best_effort=spec.best_effort,
                                    failure_episode_id=failure_episode_id,
                                    technical_outcome_record_seq=(technical_outcome_record_seq),
                                )
                                clear_active_failure_episode()
                                if not spec.best_effort and not spec.defer_presentation:
                                    await broadcaster.broadcast_json(
                                        live_state(
                                            game_id=claim.game_id,
                                            run_id=claim.run_id,
                                            state=spec.success_live_state,
                                            reason=event_type,
                                        ),
                                        audience=spec.audience,
                                    )
                                return ActionResult(
                                    action_id=claim.action_id,
                                    decision=technical_decision,
                                    model_response_record_seq=model_response_record_seq,
                                    terminal_event_record_seq=terminal_event_record_seq,
                                )
                            if (
                                not spec.best_effort
                                and (
                                    not spec.isolated_failure
                                    or spec.pause_on_model_failure
                                )
                                and _can_pause_for_model_failure(exc)
                            ):
                                await self._pause_for_model_retry(
                                    claim=claim,
                                    attempt_id=model_attempt_id,
                                    failure_code=exc.code,
                                    recovery=_model_action_recovery_snapshot(
                                        spec=spec,
                                        target=model_target,
                                        request_payload=request_payload,
                                        model_context=model_context,
                                        failure_category=disposition.category,
                                        attempt_no=model_attempt_no,
                                        retry_cycle=retry_cycle,
                                        machine_format_failure_count=(machine_format_failure_count),
                                        output_budget_failure_count=(output_budget_failure_count),
                                    ),
                                    broadcaster=broadcaster,
                                    audience=spec.audience,
                                    failure_episode_id=failure_episode_id,
                                    on_paused=clear_active_failure_episode,
                                )
                                retry_cycle += 1
                                resumed_after_pause = True
                                break
                            raise
                        break
                    if model_decision is not None:
                        break
                    if resumed_after_pause:
                        continue
                    raise ModelError("model_attempt_cycle_incomplete")
                raw_model_speech = model_decision.speech
                original_target = model_decision.target_player_id
                resolved_target = (
                    resolve_model_target(
                        original_target,
                        players=spec.model_players,
                    )
                    if spec.model_players
                    else original_target
                )
                sanitized_speech = (
                    sanitize_model_speech(
                        raw_model_speech,
                        players=spec.model_players,
                    )
                    if raw_model_speech is not None
                    else None
                )
                raw_decision_note = model_decision.decision_note
                passive_observations = _observe_model_output_fields(
                    speech=sanitized_speech,
                    decision_note=raw_decision_note,
                    hard_rules=(
                        observation_context.get("hard_rules")
                        if isinstance(observation_context.get("hard_rules"), dict)
                        else {}
                    ),
                    model_context=observation_context,
                )
                constrained_speech, speech_constraint_reasons = _constrain_model_speech(
                    sanitized_speech,
                    # Character limits remain model-facing guidance. Preserve the
                    # complete spoken response when a model exceeds that guidance.
                    max_chars=None,
                    max_sentences=spec.decision_contract.speech_max_sentences,
                )
                constrained_decision_note, decision_note_constraint_reasons = (
                    _constrain_model_speech(
                        raw_decision_note,
                        max_chars=spec.decision_contract.decision_note_max_chars,
                        max_sentences=None,
                    )
                )
                model_decision = replace(
                    model_decision,
                    target_player_id=resolved_target,
                    speech=(
                        None
                        if spec.decision_contract.speech_mode == "forbidden"
                        else constrained_speech
                    ),
                    decision_note=constrained_decision_note,
                )
                if not attempt_progress.first_token_recorded:
                    self._repository.append_event(
                        game_id=claim.game_id,
                        event_type="model_first_token_received",
                        audience=model_audience,
                        payload={
                            "action_id": claim.action_id,
                            "attempt_id": model_attempt_id,
                            "provider_request_id": model_decision.provider_request_id,
                            "first_token_ms": model_decision.first_token_ms,
                            "observation_source": "decision_result_fallback",
                        },
                    )
                parsed_output: dict[str, Any] = {
                    "target_player_ref": (original_target if spec.model_players else None),
                    "target_player_id": resolved_target,
                    "speech": model_decision.speech,
                    "decision_note": model_decision.decision_note,
                }
                if (
                    model_decision.boolean_field is not None
                    and model_decision.boolean_value is not None
                ):
                    parsed_output[model_decision.boolean_field] = model_decision.boolean_value
                fallback_raw_output = {
                    key: value
                    for key, value in parsed_output.items()
                    if key != "target_player_ref" and value is not None
                }
                model_response_record_seq = self._repository.append_event(
                    game_id=claim.game_id,
                    event_type="model_response_received",
                    audience=model_audience,
                    payload={
                        "action_id": claim.action_id,
                        "attempt_id": model_attempt_id,
                        "retry_cycle": retry_cycle,
                        **(
                            {"failure_episode_id": active_failure_episode_id}
                            if active_failure_episode_id is not None
                            else {}
                        ),
                        "provider_request_id": model_decision.provider_request_id,
                        "raw_response": (
                            model_decision.raw_response
                            if model_decision.raw_response is not None
                            else json.dumps(
                                fallback_raw_output,
                                ensure_ascii=False,
                            )
                        ),
                        "parsed_output": parsed_output,
                        "passive_observations": passive_observations,
                        "repair_kind": model_decision.repair_kind,
                        "application_validation_result": "accepted",
                        "action_budget_ms": round(action_budget_seconds * 1000),
                        "action_elapsed_ms": round(
                            max(
                                0.0,
                                time.monotonic() - model_started_at - model_queue_wait_seconds,
                            )
                            * 1000
                        ),
                        "action_wall_elapsed_ms": round(
                            (time.monotonic() - model_started_at) * 1000
                        ),
                        "action_remaining_ms": max(
                            0,
                            round((model_deadline - time.monotonic()) * 1000),
                        ),
                        "action_wall_budget_enforced": wall_clock_budget_enforced,
                        "observed_queue_wait_elapsed_ms": round(model_queue_wait_seconds * 1000),
                        "blocking_required_target": blocking_required_target,
                        "effective_output_timeout_retry_mode": (
                            effective_output_timeout_retry_mode
                        ),
                        "effective_queue_wait_budget_mode": effective_queue_wait_budget_mode,
                        "first_token_ms": model_decision.first_token_ms,
                        "first_visible_text_ms": model_decision.first_visible_text_ms,
                        "completed_ms": model_decision.completed_ms,
                        "queue_wait_ms": model_decision.queue_wait_ms,
                        "provider_in_flight": model_decision.provider_in_flight,
                        "provider_concurrency_limit": (model_decision.provider_concurrency_limit),
                        "reasoning_delta_count": model_decision.reasoning_delta_count,
                        "text_delta_count": model_decision.text_delta_count,
                        "max_inter_delta_ms": model_decision.max_inter_delta_ms,
                        "last_progress_ms": model_decision.last_progress_ms,
                        "finish_reason": model_decision.finish_reason,
                        "provider_usage": model_decision.provider_usage,
                        "usage_update_count": model_decision.usage_update_count,
                        "usage_conflict_observed": (model_decision.usage_conflict_observed),
                        "usage_consistency": model_decision.usage_consistency,
                        "reasoning_only_elapsed_ms": (model_decision.reasoning_only_elapsed_ms),
                        **_model_generation_policy_audit_payload(
                            policy=resolved_generation_policy,
                            action_type=spec.action_type,
                            model_provider=resolved_model_provider,
                            model_id=resolved_model_id,
                            explicit_reasoning_only_elapsed_ms=(
                                model_decision.reasoning_only_elapsed_ms
                            ),
                            first_token_ms=model_decision.first_token_ms,
                            first_visible_text_ms=(model_decision.first_visible_text_ms),
                            terminal_elapsed_ms=model_decision.completed_ms,
                        ),
                    },
                )
                model_request_completed = True
                clear_active_failure_episode()
                if binding_prior_failure_streak > 0:
                    self._repository.append_event(
                        game_id=claim.game_id,
                        event_type="model_binding_health_updated",
                        audience="god_view",
                        payload={
                            "action_id": claim.action_id,
                            "attempt_id": model_attempt_id,
                            "phase_id": spec.phase_id,
                            "actor_id": spec.actor_id,
                            "model_provider": model_target.provider,
                            "model_id": model_target.model_id,
                            "status": "healthy",
                            "consecutive_failure_count": 0,
                            "recovered_after_failure_count": (binding_prior_failure_streak),
                        },
                    )
                if model_decision.repair_kind is not None:
                    self._repository.append_event(
                        game_id=claim.game_id,
                        event_type="model_response_repair_applied",
                        audience=model_audience,
                        payload={
                            "action_id": claim.action_id,
                            "attempt_id": model_attempt_id,
                            "repair_kind": model_decision.repair_kind,
                            "raw_response_preserved": True,
                        },
                    )
                self._repository.resolve_model_action_recovery(
                    claim=claim,
                    attempt_id=model_attempt_id,
                    attempt_no=model_attempt_no,
                    retry_cycle=retry_cycle,
                )
                if (
                    spec.decision_contract.speech_mode == "forbidden"
                    and raw_model_speech is not None
                ):
                    self._repository.append_event(
                        game_id=claim.game_id,
                        event_type="model_decision_speech_normalized",
                        audience=model_audience,
                        payload={
                            "action_id": claim.action_id,
                            "attempt_id": model_attempt_id,
                            "reason": "speech_forbidden",
                        },
                    )
                elif speech_constraint_reasons:
                    self._repository.append_event(
                        game_id=claim.game_id,
                        event_type="model_decision_speech_normalized",
                        audience=model_audience,
                        payload={
                            "action_id": claim.action_id,
                            "attempt_id": model_attempt_id,
                            "reason": "speech_constraint",
                            "constraints": list(speech_constraint_reasons),
                            "max_chars": spec.decision_contract.speech_max_chars,
                            "max_sentences": spec.decision_contract.speech_max_sentences,
                            "original_chars": _speech_character_count(sanitized_speech or ""),
                            "normalized_chars": _speech_character_count(
                                model_decision.speech or ""
                            ),
                        },
                    )
                if decision_note_constraint_reasons:
                    self._repository.append_event(
                        game_id=claim.game_id,
                        event_type="model_decision_note_normalized",
                        audience=model_audience,
                        payload={
                            "action_id": claim.action_id,
                            "attempt_id": model_attempt_id,
                            "reason": "decision_note_constraint",
                            "constraints": list(decision_note_constraint_reasons),
                            "max_chars": spec.decision_contract.decision_note_max_chars,
                            "original_chars": _speech_character_count(raw_decision_note or ""),
                            "normalized_chars": _speech_character_count(
                                constrained_decision_note or ""
                            ),
                        },
                    )
                normalized_target = resolved_target
                normalization_reason: str | None = None
                if spec.decision_contract.kind != "target":
                    if original_target is not None:
                        normalized_target = None
                        normalization_reason = "targetless_action"
                elif original_target is not None and resolved_target is None:
                    if spec.decision_contract.target_mode == "required":
                        raise RepositoryError(
                            "required model target became invalid after validation"
                        )
                    normalized_target = None
                    normalization_reason = "target_not_allowed"
                elif normalized_target is None:
                    if spec.decision_contract.target_mode == "required":
                        raise RepositoryError(
                            "required model target disappeared after validation"
                        )
                elif normalized_target not in (spec.allowed_target_ids or ()):
                    if spec.decision_contract.target_mode == "required":
                        raise RepositoryError(
                            "required model target left the frozen candidate set"
                        )
                    normalized_target = None
                    normalization_reason = "target_not_allowed"
                if normalization_reason is not None:
                    model_decision = replace(
                        model_decision,
                        target_player_id=normalized_target,
                    )
                    self._repository.append_event(
                        game_id=claim.game_id,
                        event_type="model_decision_target_normalized",
                        audience=model_audience,
                        payload={
                            "action_id": claim.action_id,
                            "original_target_player_ref": (
                                original_target if spec.model_players else None
                            ),
                            "original_target_player_id": resolved_target,
                            "normalized_target_player_id": normalized_target,
                            "reason": normalization_reason,
                        },
                    )
                speech_text = model_decision.speech
                sentence_ms = model_decision.completed_ms
            check_cancellation()
            if speech_text is None or spec.defer_presentation:
                terminal_event_record_seq = self._repository.complete_silent_action(
                    claim=claim,
                    next_live_state=spec.success_live_state,
                    next_phase_state=spec.success_phase_state,
                    best_effort=spec.best_effort,
                    source_attempt_id=model_attempt_id,
                    source_model_response_record_seq=model_response_record_seq,
                    provider_request_id=(
                        model_decision.provider_request_id
                        if model_decision is not None
                        else None
                    ),
                )
                if not spec.best_effort and not spec.defer_presentation:
                    await broadcaster.broadcast_json(
                        live_state(
                            game_id=claim.game_id,
                            run_id=claim.run_id,
                            state=spec.success_live_state,
                        ),
                        audience=spec.audience,
                    )
                return ActionResult(
                    action_id=claim.action_id,
                    decision=model_decision,
                    model_response_record_seq=model_response_record_seq,
                    terminal_event_record_seq=terminal_event_record_seq,
                    model_attempt_id=model_attempt_id,
                    request_payload_sha256=request_payload_sha256,
                    projected_context_sha256=projected_context_sha256,
                    projected_known_event_refs=projected_known_event_refs,
                    projected_known_events_sha256=projected_known_events_sha256,
                )
            presentation_id = f"v2_pres_{uuid4().hex[:16]}"
            speech_id = f"v2_speech_{uuid4().hex[:16]}"
            tts_client = self._tts_client_for_claim(claim)
            voice_asset_id = f"v2_voice_{uuid4().hex[:16]}" if tts_client else None
            identity = self._repository.open_presentation(
                claim=claim,
                presentation_id=presentation_id,
                speech_id=speech_id,
                voice_asset_id=voice_asset_id,
                subtitle_text=speech_text,
                sample_rate=self._sample_rate,
                actor_kind=spec.actor_kind,
                actor_id=spec.actor_id,
            )
            await broadcaster.set_current(identity, 0, audience=spec.audience)
            await broadcaster.broadcast_json(presentation_opened(identity), audience=spec.audience)
            await broadcaster.broadcast_json(segment_committed(identity), audience=spec.audience)
            if on_presentation_opened is not None:
                on_presentation_opened(identity)
            if not spec.best_effort:
                await broadcaster.broadcast_json(
                    live_state(
                        game_id=claim.game_id,
                        run_id=claim.run_id,
                        state="broadcasting",
                    ),
                    audience=spec.audience,
                )
            if tts_client is None:
                self._repository.append_event(
                    game_id=claim.game_id,
                    event_type="tts_skipped",
                    audience=identity.audience,
                    payload={
                        "action_id": claim.action_id,
                        "presentation_id": identity.presentation_id,
                        "reason_code": "configured_text_only",
                        "configured_audio_mode": "text_only",
                        "delivery_mode": "text_only",
                    },
                )
                self._repository.complete_text_action(
                    identity=identity,
                    next_live_state=spec.success_live_state,
                    next_phase_state=spec.success_phase_state,
                    best_effort=spec.best_effort,
                )
                if on_presentation_closed is not None:
                    on_presentation_closed(identity)
                await broadcaster.broadcast_json(
                    presentation_closed(
                        identity,
                        final_chunk_index=-1,
                        final_sample_cursor=0,
                    ),
                    audience=spec.audience,
                )
                await broadcaster.set_current(None, 0, audience=spec.audience)
                if spec.success_live_state == "awaiting_observation" and not spec.best_effort:
                    await broadcaster.broadcast_json(
                        live_state(
                            game_id=claim.game_id,
                            run_id=claim.run_id,
                            state="awaiting_observation",
                        ),
                        audience=spec.audience,
                    )
                return ActionResult(
                    action_id=claim.action_id,
                    decision=model_decision,
                    model_response_record_seq=model_response_record_seq,
                    terminal_event_record_seq=terminal_event_record_seq,
                    model_attempt_id=model_attempt_id,
                    request_payload_sha256=request_payload_sha256,
                    projected_context_sha256=projected_context_sha256,
                    projected_known_event_refs=projected_known_event_refs,
                    projected_known_events_sha256=projected_known_events_sha256,
                )
            if identity.voice_asset_id is None:
                raise RepositoryError("enabled TTS action has no voice asset")
            tts_attempt_id = f"v2_tts_{uuid4().hex[:16]}"
            self._repository.append_event(
                game_id=claim.game_id,
                event_type="tts_stream_started",
                audience=identity.audience,
                payload={
                    "action_id": claim.action_id,
                    "presentation_id": identity.presentation_id,
                    "attempt_id": tts_attempt_id,
                    "tts_attempt_id": tts_attempt_id,
                    "sentence_ms": sentence_ms,
                    "speaker": speaker,
                    "dialect": spec.dialect,
                    "judge_configuration_version": (
                        judge_configuration.version if judge_configuration is not None else None
                    ),
                },
            )
            recorder = VoiceRecorder(
                root=self._voice_root,
                storage_key=identity.storage_key,
                sample_rate=self._sample_rate,
            )
            tts_started = time.monotonic()
            official_end: float | None = None
            sample_cursor = 0
            chunk_index = 0
            first_chunk = True
            async for pcm in tts_client.synthesize(
                text=speech_text,
                attempt_id=tts_attempt_id,
                speaker=speaker,
                dialect=spec.dialect,
                check_cancellation=check_cancellation,
            ):
                check_cancellation()
                sample_count = recorder.append(pcm)
                if first_chunk:
                    first_chunk = False
                    first_chunk_ms = round((time.monotonic() - tts_started) * 1000)
                    for event_type in (
                        "tts_first_chunk_received",
                        "voice_recording_started",
                        "audio_broadcast_started",
                    ):
                        self._repository.append_event(
                            game_id=claim.game_id,
                            event_type=event_type,
                            audience=identity.audience,
                            payload={
                                "action_id": claim.action_id,
                                "presentation_id": identity.presentation_id,
                                "attempt_id": tts_attempt_id,
                                "tts_attempt_id": tts_attempt_id,
                                "voice_asset_id": identity.voice_asset_id,
                                "first_chunk_ms": first_chunk_ms,
                            },
                        )
                packet = audio_frame(
                    identity,
                    chunk_index=chunk_index,
                    start_sample=sample_cursor,
                    sample_count=sample_count,
                    sample_rate=self._sample_rate,
                    pcm=pcm,
                )
                next_sample_cursor = sample_cursor + sample_count
                await broadcaster.broadcast_audio(
                    packet,
                    identity=identity,
                    next_sample_cursor=next_sample_cursor,
                    audience=spec.audience,
                )
                now = time.monotonic()
                duration = sample_count / self._sample_rate
                official_end = max(official_end or now, now) + duration
                sample_cursor = next_sample_cursor
                chunk_index += 1
            if first_chunk or official_end is None:
                raise TtsError("tts_empty_audio")
            check_cancellation()
            self._repository.mark_finalizing(
                identity=identity,
                tts_attempt_id=tts_attempt_id,
                sample_count=sample_cursor,
                best_effort=spec.best_effort,
            )
            if not spec.best_effort:
                await broadcaster.broadcast_json(
                    live_state(
                        game_id=claim.game_id,
                        run_id=claim.run_id,
                        state="finalizing",
                    ),
                    audience=spec.audience,
                )
            recorded = recorder.finalize()
            if recorded.sample_count != sample_cursor:
                recorder.discard_finalized()
                recorder = None
                raise VoiceRecordingError("recorded sample count differs from broadcast")
            self._repository.mark_voice_ready(
                identity=identity,
                tts_attempt_id=tts_attempt_id,
                sample_count=recorded.sample_count,
                duration_ms=recorded.duration_ms,
                pcm_sha256=recorded.pcm_sha256,
                size_bytes=recorded.size_bytes,
            )
            recorder = None
            remaining = official_end - time.monotonic()
            while remaining > 0:
                await asyncio.sleep(min(remaining, 0.1))
                check_cancellation()
                remaining = official_end - time.monotonic()
            check_cancellation()
            self._repository.complete_action(
                identity=identity,
                tts_attempt_id=tts_attempt_id,
                final_chunk_index=chunk_index - 1,
                final_sample_cursor=sample_cursor,
                next_live_state=spec.success_live_state,
                next_phase_state=spec.success_phase_state,
                best_effort=spec.best_effort,
            )
            if on_presentation_closed is not None:
                on_presentation_closed(identity)
            await broadcaster.broadcast_json(
                presentation_closed(
                    identity,
                    final_chunk_index=chunk_index - 1,
                    final_sample_cursor=sample_cursor,
                ),
                audience=spec.audience,
            )
            await broadcaster.set_current(
                None,
                sample_cursor,
                audience=spec.audience,
            )
            if spec.success_live_state == "awaiting_observation" and not spec.best_effort:
                await broadcaster.broadcast_json(
                    live_state(
                        game_id=claim.game_id,
                        run_id=claim.run_id,
                        state="awaiting_observation",
                    ),
                    audience=spec.audience,
                )
            return ActionResult(
                action_id=claim.action_id,
                decision=model_decision,
                model_response_record_seq=model_response_record_seq,
                terminal_event_record_seq=terminal_event_record_seq,
                model_attempt_id=model_attempt_id,
                request_payload_sha256=request_payload_sha256,
                projected_context_sha256=projected_context_sha256,
                projected_known_event_refs=projected_known_event_refs,
                projected_known_events_sha256=projected_known_events_sha256,
            )
        except asyncio.CancelledError as exc:
            if recorder is not None:
                try:
                    recorder.discard_finalized()
                except BaseException:
                    logger.warning(
                        "Live V2 could not discard canceled voice recording",
                        exc_info=True,
                        extra={"game_id": claim.game_id, "action_id": claim.action_id},
                    )
            if spec.pipeline_stage == "generation":
                if spec.pipeline_kind == "pre_exile":
                    cancellation_code = "pre_exile_pipeline_generation_canceled"
                else:
                    cancellation_code = (
                        "day_speech_prefetch_post_close_deadline"
                        if exc.args and exc.args[0] == "day_speech_prefetch_post_close_deadline"
                        else "day_speech_prefetch_canceled"
                    )
                cancellation_kind = (
                    "timeout"
                    if cancellation_code == "day_speech_prefetch_post_close_deadline"
                    else "canceled"
                )
                cancellation_terminal_record_seq: int | None = None
                try:
                    if (
                        model_attempt_id is not None
                        and model_request_started_recorded
                        and model_attempt_no is not None
                        and model_attempt_no > 0
                        and current_cycle_attempt_no is not None
                        and not model_request_completed
                        and not model_failure_recorded
                    ):
                        failure_episode_id = active_failure_episode_id
                        if failure_episode_id is None:
                            failure_episode_id = stable_failure_episode_id(
                                game_id=claim.game_id,
                                run_id=claim.run_id,
                                action_id=claim.action_id,
                                retry_cycle=retry_cycle,
                                first_failed_attempt_id=model_attempt_id,
                            )
                        self._repository.append_event(
                            game_id=claim.game_id,
                            event_type="model_request_failed",
                            audience=model_audience,
                            payload={
                                "action_id": claim.action_id,
                                "attempt_id": model_attempt_id,
                                "attempt_no": model_attempt_no,
                                "cycle_attempt_no": current_cycle_attempt_no,
                                "retry_cycle": retry_cycle,
                                "max_attempts": self._model_retry_policy.max_attempts,
                                "failure_kind": cancellation_kind,
                                "failure_code": cancellation_code,
                                "failure_category": (
                                    "timeout" if cancellation_kind == "timeout" else "canceled"
                                ),
                                "failure_episode_id": failure_episode_id,
                                "retryable": False,
                                "attempt_terminal": True,
                                "action_recoverable": False,
                                "run_terminal": False,
                                "terminal": True,
                                "automatic_retry_scheduled": False,
                                "automatic_retry_stop_reason": "not_retryable",
                                "pipeline_retry_mode": spec.pipeline_retry_mode,
                                "pipeline_empty_stream_max_attempts": (
                                    spec.pipeline_empty_stream_max_attempts
                                ),
                            },
                        )
                        active_failure_episode_id = failure_episode_id
                        model_failure_recorded = True
                    persisted_terminal_record_seq = self._repository.fail_action(
                        claim=claim,
                        failure_kind=cancellation_kind,
                        failure_code=cancellation_code,
                        identity=identity,
                        tts_attempt_id=tts_attempt_id,
                        best_effort=spec.best_effort,
                        failure_episode_id=active_failure_episode_id,
                        failure_episode_disposition="isolated_action_failure",
                    )
                    if (
                        type(persisted_terminal_record_seq) is int
                        and persisted_terminal_record_seq > 0
                    ):
                        cancellation_terminal_record_seq = persisted_terminal_record_seq
                except ExecutionOwnershipLost:
                    raise
                except BaseException:
                    # A stop request or secondary persistence error must never
                    # replace the cancellation that reached this action.
                    logger.warning(
                        "Live V2 could not persist canceled day speech prefetch",
                        exc_info=True,
                        extra={"game_id": claim.game_id, "action_id": claim.action_id},
                    )
                if cancellation_terminal_record_seq is not None and (
                    cancellation_kind == "timeout" or spec.pipeline_kind == "pre_exile"
                ):
                    return ActionResult(
                        action_id=claim.action_id,
                        terminal_event_record_seq=cancellation_terminal_record_seq,
                        failure=ActionFailure(
                            code=cancellation_code,
                            category=("timeout" if cancellation_kind == "timeout" else "canceled"),
                            terminal_attempt_id=model_attempt_id,
                            machine_format_failure_count=machine_format_failure_count,
                            last_machine_format_attempt_id=last_machine_format_attempt_id,
                            last_machine_format_failure_code=last_machine_format_failure_code,
                            output_budget_failure_count=output_budget_failure_count,
                            last_output_budget_attempt_id=last_output_budget_attempt_id,
                            last_output_budget_failure_code=last_output_budget_failure_code,
                            failure_episode_id=active_failure_episode_id,
                        ),
                    )
            raise
        except ExecutionOwnershipLost:
            if recorder is not None:
                try:
                    recorder.discard_finalized()
                except BaseException:
                    logger.warning(
                        "Live V2 could not discard ownership-lost voice recording",
                        exc_info=True,
                        extra={"game_id": claim.game_id, "action_id": claim.action_id},
                    )
            raise
        except Exception as exc:
            if recorder is not None:
                recorder.discard_finalized()
            failure_kind, failure_code = _failure(exc)
            if (
                model_attempt_id is not None
                and not model_request_completed
                and not model_failure_recorded
                and isinstance(
                    exc,
                    (ModelError, ModelContextProjectionInvariantError),
                )
            ):
                try:
                    failure_episode_id = stable_failure_episode_id(
                        game_id=claim.game_id,
                        run_id=claim.run_id,
                        action_id=claim.action_id,
                        retry_cycle=retry_cycle,
                        first_failed_attempt_id=model_attempt_id,
                    )
                    failure_payload: dict[str, Any] = {
                        "action_id": claim.action_id,
                        "attempt_id": model_attempt_id,
                        "decision_family_id": spec.decision_family_id,
                        "attempt_no": model_attempt_no,
                        "cycle_attempt_no": 1,
                        "retry_cycle": retry_cycle,
                        "max_attempts": self._model_retry_policy.max_attempts,
                        "failure_kind": failure_kind,
                        "failure_code": failure_code,
                        "failure_category": (
                            model_failure_disposition(exc).category
                            if isinstance(exc, ModelError)
                            else "internal_invariant"
                        ),
                        "failure_episode_id": failure_episode_id,
                        "pre_provider_failure": True,
                        "retryable": False,
                        "effective_attempt_limit": 1,
                        "retry_delay_ms": 0,
                        "required_retry_window_ms": 0,
                        "automatic_retry_scheduled": False,
                        "automatic_retry_stop_reason": "not_retryable",
                        "terminal": True,
                    }
                    if resolved_generation_policy is not None:
                        failure_payload.update(
                            _model_generation_policy_audit_payload(
                                policy=resolved_generation_policy,
                                action_type=spec.action_type,
                                model_provider=resolved_model_provider,
                                model_id=resolved_model_id,
                                explicit_reasoning_only_elapsed_ms=(
                                    exc.reasoning_only_elapsed_ms
                                    if isinstance(exc, ModelError)
                                    else None
                                ),
                                first_token_ms=(
                                    exc.first_token_ms if isinstance(exc, ModelError) else None
                                ),
                                first_visible_text_ms=(
                                    exc.first_visible_text_ms
                                    if isinstance(exc, ModelError)
                                    else None
                                ),
                                terminal_elapsed_ms=(
                                    exc.elapsed_ms if isinstance(exc, ModelError) else None
                                ),
                            )
                        )
                    if isinstance(exc, QualityError):
                        failure_payload["application_validation_result"] = "rejected"
                        if exc.raw_response is not None:
                            failure_payload["raw_response"] = exc.raw_response
                    if isinstance(exc, ModelContextProjectionInvariantError):
                        failure_payload["invariant_code"] = exc.invariant_code
                    self._repository.append_event(
                        game_id=claim.game_id,
                        event_type="model_request_failed",
                        audience=model_audience,
                        payload=failure_payload,
                    )
                    model_failure_recorded = True
                    active_failure_episode_id = failure_episode_id
                except Exception:
                    logger.exception("Live V2 could not persist model request failure")
            logger.warning(
                "Live V2 action failed: %s (%s: %s)",
                failure_code,
                type(exc).__name__,
                exc,
                extra={
                    "game_id": claim.game_id,
                    "action_id": claim.action_id,
                    "action_type": spec.action_type,
                    "failure_kind": failure_kind,
                    "failure_code": failure_code,
                },
            )
            try:
                persisted_terminal_event_record_seq = self._repository.fail_action(
                    claim=claim,
                    failure_kind=failure_kind,
                    failure_code=failure_code,
                    identity=identity,
                    tts_attempt_id=tts_attempt_id,
                    best_effort=spec.best_effort,
                    failure_episode_id=active_failure_episode_id,
                    failure_episode_disposition=(
                        "isolated_action_failure"
                        if spec.isolated_failure or spec.best_effort or spec.defer_presentation
                        else "run_failure"
                    ),
                )
                if (
                    type(persisted_terminal_event_record_seq) is int
                    and persisted_terminal_event_record_seq > 0
                ):
                    terminal_event_record_seq = persisted_terminal_event_record_seq
            except Exception:
                logger.exception("Live V2 could not persist action failure")
            if identity is None and not spec.best_effort and not spec.defer_presentation:
                await broadcaster.broadcast_json(
                    live_state(
                        game_id=claim.game_id,
                        run_id=claim.run_id,
                        state="failed",
                        reason=failure_code,
                    ),
                    audience="all",
                )
            elif identity is not None:
                await broadcaster.broadcast_json(
                    presentation_failed(
                        identity,
                        failure_kind=failure_kind,
                        failure_code=failure_code,
                    ),
                    audience=identity.audience,
                )
                await broadcaster.set_current(None, 0, audience=identity.audience)
            if spec.isolated_failure:
                failure_category = (
                    model_failure_disposition(exc).category
                    if isinstance(exc, ModelError)
                    else None
                )
                return ActionResult(
                    action_id=claim.action_id,
                    model_response_record_seq=model_response_record_seq,
                    terminal_event_record_seq=terminal_event_record_seq,
                    failure=ActionFailure(
                        code=failure_code,
                        category=failure_category,
                        terminal_attempt_id=model_attempt_id,
                        machine_format_failure_count=machine_format_failure_count,
                        last_machine_format_attempt_id=(last_machine_format_attempt_id),
                        last_machine_format_failure_code=(last_machine_format_failure_code),
                        output_budget_failure_count=output_budget_failure_count,
                        last_output_budget_attempt_id=(last_output_budget_attempt_id),
                        last_output_budget_failure_code=(last_output_budget_failure_code),
                        failure_episode_id=active_failure_episode_id,
                    ),
                )
            return None


_OPENING_SPEECH = SpeechSpec(
    action_type="judge_opening_speech",
    phase_id="opening",
    required_phase_state="opening_ready",
    objective="播报本场直播的固定法官开场词",
    success_live_state="ready",
    success_phase_state="opening_speech_closed",
)

_NIGHTFALL_ANNOUNCEMENT = SpeechSpec(
    action_type="judge_nightfall_announcement",
    phase_id="first_night",
    required_phase_state="nightfall_ready",
    objective="播报本局进入首夜并提醒所有玩家闭眼",
    success_live_state="awaiting_observation",
    success_phase_state="nightfall_announced",
)


def _action_context(
    *,
    game_id: str,
    action_id: str,
    spec: SpeechSpec,
) -> dict[str, Any]:
    output_contract = _output_contract(spec)
    return {
        "schema_version": 1,
        "action_id": action_id,
        "action_type": spec.action_type,
        "game_id": game_id,
        "phase_id": spec.phase_id,
        "actor": {"kind": spec.actor_kind, "id": spec.actor_id},
        "objective": spec.objective,
        "output_contract": output_contract,
        "influence": {
            "schema_version": 1,
            "status": "disabled",
            "captured_at": None,
            "strength": 0,
            "signals": [],
        },
        **(spec.context or {}),
        **({"batch_id": spec.batch_id} if spec.batch_id is not None else {}),
        **(
            {"decision_family_id": spec.decision_family_id}
            if spec.decision_family_id is not None
            else {}
        ),
        **(
            {"projection_at_seq": spec.projection_at_seq}
            if spec.projection_at_seq is not None
            else {}
        ),
        **(
            {
                "pipeline": (
                    {
                        "kind": "pre_exile",
                        "pipeline_id": spec.pipeline_slot_id,
                        "result_kind": spec.pipeline_result_kind,
                        "stage": spec.pipeline_stage,
                        "model_admission_mode": spec.model_admission_mode,
                        **(
                            {
                                "retry_mode": spec.pipeline_retry_mode,
                                "empty_stream_max_attempts": (
                                    spec.pipeline_empty_stream_max_attempts
                                ),
                            }
                            if spec.pipeline_retry_mode != "disabled"
                            else {}
                        ),
                    }
                    if spec.pipeline_kind == "pre_exile"
                    else {
                        "slot_id": spec.pipeline_slot_id,
                        "stage": spec.pipeline_stage,
                        "model_admission_mode": spec.model_admission_mode,
                        **(
                            {
                                "retry_mode": spec.pipeline_retry_mode,
                                "empty_stream_max_attempts": (
                                    spec.pipeline_empty_stream_max_attempts
                                ),
                            }
                            if spec.pipeline_retry_mode != "disabled"
                            else {}
                        ),
                    }
                )
            }
            if spec.pipeline_slot_id is not None
            else {}
        ),
    }


def _action_model_parameters(
    spec: SpeechSpec,
) -> tuple[dict[str, Any], str]:
    return dict(spec.model_parameters or {}), "model_configuration"


def _apply_provider_thinking_override(
    target: Any,
    *,
    thinking_source: str,
    enabled: bool,
) -> tuple[Any, str]:
    """Apply the vote-phase thinking policy on the resolved provider payload.

    This must stay a payload-level override: the frozen player parameters are
    a validated canonical contract, so editing that dict (e.g. flipping
    thinking to disabled while reasoning_effort/max_tokens still match the
    enabled configuration) fails frozen validation and kills every request
    with `model_parameters_invalid` before it reaches the provider.

    Forced-thinking families (no ``disabled`` option) never receive
    ``thinking.type=disabled``. If they expose effort grades, the override
    keeps thinking on and floors effort instead.
    """
    if (
        not enabled
        or not target.supports_thinking
        or target.parameters.get("thinking") != "enabled"
    ):
        return target, thinking_source
    policy = reasoning_policy_for_model(
        target.provider,
        target.model_id,
        supports_thinking=target.supports_thinking,
    )
    if "disabled" in policy.thinking_options:
        return (
            replace(
                target,
                parameters={
                    **target.parameters,
                    "thinking": "disabled",
                    "reasoning_effort": None,
                },
            ),
            "vote_phase_thinking_policy",
        )
    if policy.reasoning_effort_options:
        return (
            replace(
                target,
                parameters={
                    **target.parameters,
                    "thinking": "enabled",
                    "reasoning_effort": policy.reasoning_effort_options[0],
                },
            ),
            "vote_phase_thinking_policy_effort_floor",
        )
    return target, thinking_source


def _output_contract(spec: SpeechSpec) -> dict[str, Any]:
    contract = spec.decision_contract
    speech: dict[str, Any] = {
        "type": "string",
        "mode": contract.speech_mode,
    }
    if contract.speech_mode in {"required", "required_if_true"}:
        speech["min_length"] = 1
    if contract.speech_max_chars is not None:
        speech["max_chars"] = contract.speech_max_chars
    if contract.speech_max_sentences is not None:
        speech["max_sentences"] = contract.speech_max_sentences
    output: dict[str, Any] = {
        "kind": contract.kind,
        "presentation_kind": spec.output_kind,
        "language": "zh-CN",
        "speech": speech,
    }
    if contract.decision_note_mode == "optional":
        output["decision_note"] = {
            "type": "string",
            "mode": "optional",
            "max_chars": contract.decision_note_max_chars,
        }
    if contract.kind == "speech":
        output["required_fields"] = ["speech"] if contract.speech_mode == "required" else []
        return output
    if contract.kind == "target":
        if contract.target_mode == "none":
            raise LiveProtocolError("target contract requires a target mode")
        if contract.target_mode == "required" and not spec.allowed_target_ids:
            raise LiveProtocolError("required target contract requires allowed targets")
        output["target_field"] = "target_player_id"
        output["target_policy"] = {
            "mode": contract.target_mode,
            "allowed_target_ids": list(spec.allowed_target_ids or ()),
        }
        output["required_fields"] = [
            *(["target_player_id"] if contract.target_mode == "required" else []),
            *(["speech"] if contract.speech_mode == "required" else []),
        ]
        return output
    if not contract.boolean_field:
        raise LiveProtocolError("boolean contract requires a semantic field")
    output["field"] = contract.boolean_field
    output["required_fields"] = [
        contract.boolean_field,
        *(["speech"] if contract.speech_mode == "required" else []),
    ]
    output["boolean"] = {
        "type": "boolean",
        "true_means": contract.true_meaning,
        "false_means": contract.false_meaning,
    }
    if contract.speech_mode == "required_if_true":
        speech["condition"] = {
            "field": contract.boolean_field,
            "equals": True,
        }
    return output


_SPEECH_SENTENCE_ENDINGS = frozenset("。！？!?\n")
_SPEECH_SENTENCE_CLOSERS = frozenset("”’」』）)]}")


def _observe_model_output_fields(
    *,
    speech: str | None,
    decision_note: str | None,
    hard_rules: dict[str, Any],
    model_context: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    observations: list[dict[str, Any]] = []
    for output_field, text in (
        ("speech", speech),
        ("decision_note", decision_note),
    ):
        try:
            for raw_observation in observe_model_speech(
                text,
                hard_rules=hard_rules,
                model_context=model_context,
            ):
                observation = dict(raw_observation)
                observation["output_field"] = output_field
                for signal_field in ("signals", "conflicts"):
                    raw_signals = observation.get(signal_field)
                    if not isinstance(raw_signals, list):
                        continue
                    observation[signal_field] = [
                        {**signal, "output_field": output_field}
                        if isinstance(signal, dict)
                        else signal
                        for signal in raw_signals
                    ]
                observations.append(observation)
        except Exception as exc:  # Output-field labeling must remain passive too.
            observations.append(
                {
                    "code": "model_observation_failed",
                    "severity": "warning",
                    "confidence": "unknown",
                    "detector_version": 1,
                    "error_type": type(exc).__name__,
                    "output_field": output_field,
                    "effect": "observed_only",
                }
            )
    return observations


def _constrain_model_speech(
    speech: str | None,
    *,
    max_chars: int | None,
    max_sentences: int | None,
) -> tuple[str | None, tuple[str, ...]]:
    if speech is None:
        return None, ()

    constrained = speech.strip()
    reasons: list[str] = []
    if max_sentences is not None and max_sentences > 0:
        boundaries = [
            index
            for index, character in enumerate(constrained)
            if character in _SPEECH_SENTENCE_ENDINGS
        ]
        if len(boundaries) >= max_sentences:
            cutoff = boundaries[max_sentences - 1] + 1
            while cutoff < len(constrained) and constrained[cutoff] in _SPEECH_SENTENCE_CLOSERS:
                cutoff += 1
            if constrained[cutoff:].strip():
                constrained = constrained[:cutoff].strip()
                reasons.append("max_sentences_exceeded")

    if max_chars is not None and max_chars > 0 and _speech_character_count(constrained) > max_chars:
        constrained = _speech_prefix(constrained, max_chars=max_chars).rstrip()
        reasons.append("max_chars_exceeded")

    return constrained, tuple(reasons)


def _speech_character_count(text: str) -> int:
    return sum(not character.isspace() for character in text)


def _speech_prefix(text: str, *, max_chars: int) -> str:
    accepted: list[str] = []
    used = 0
    for character in text:
        if not character.isspace():
            if used >= max_chars:
                break
            used += 1
        accepted.append(character)
    return "".join(accepted)


def _can_pause_for_model_failure(exc: ModelError) -> bool:
    return model_failure_disposition(exc).pausable


def _validate_model_target_decision(
    decision: ModelDecision,
    *,
    spec: SpeechSpec,
) -> None:
    contract = spec.decision_contract
    if contract.kind != "target":
        return
    original_target = decision.target_player_id
    resolved_target = (
        resolve_model_target(original_target, players=spec.model_players)
        if spec.model_players
        else original_target
    )
    if resolved_target is not None and resolved_target not in (spec.allowed_target_ids or ()):
        resolved_target = None
    if contract.target_mode == "required" and resolved_target is None:
        raise QualityError(
            "model_decision_required_target_missing",
            raw_response=decision.raw_response,
        )


def _model_action_recovery_snapshot(
    *,
    spec: SpeechSpec,
    target: ModelTarget,
    request_payload: dict[str, Any],
    model_context: dict[str, Any],
    failure_category: str,
    attempt_no: int,
    retry_cycle: int,
    machine_format_failure_count: int,
    output_budget_failure_count: int,
) -> dict[str, Any]:
    canonical_request = json.dumps(
        request_payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    family_machine_format_failure_count = (
        spec.prior_machine_format_failures + machine_format_failure_count
    )
    automatic_machine_format_attempt_count = (
        min(
            family_machine_format_failure_count,
            spec.automatic_machine_format_budget,
        )
        if spec.automatic_machine_format_budget is not None
        else None
    )
    family_output_budget_failure_count = (
        spec.prior_output_budget_failures + output_budget_failure_count
    )
    automatic_output_budget_attempt_count = (
        min(
            family_output_budget_failure_count,
            spec.automatic_output_budget_budget,
        )
        if spec.automatic_output_budget_budget is not None
        else None
    )
    return {
        "action_type": spec.action_type,
        "actor_id": spec.actor_id,
        "decision_family_id": spec.decision_family_id,
        "prior_machine_format_failures": family_machine_format_failure_count,
        "automatic_machine_format_attempt_count": (automatic_machine_format_attempt_count),
        "automatic_machine_format_budget": spec.automatic_machine_format_budget,
        "prior_output_budget_failures": family_output_budget_failure_count,
        "automatic_output_budget_attempt_count": (automatic_output_budget_attempt_count),
        "automatic_output_budget_budget": spec.automatic_output_budget_budget,
        "exhaustion_scope": (
            "decision_family" if spec.preflight_pause_failure is not None else "action"
        ),
        "source_action_id": (
            spec.preflight_pause_failure.source_action_id
            if spec.preflight_pause_failure is not None
            else None
        ),
        "source_attempt_id": (
            spec.preflight_pause_failure.source_attempt_id
            if spec.preflight_pause_failure is not None
            else None
        ),
        "model_provider": target.provider,
        "model_id": target.model_id,
        "request_payload": request_payload,
        "request_hash": hashlib.sha256(canonical_request.encode()).hexdigest(),
        "model_context": model_context,
        "action_snapshot": asdict(spec),
        "failure_category": failure_category,
        "attempt_no": attempt_no,
        "retry_cycle": retry_cycle,
    }


_TECHNICAL_SKIP_ACTION_TYPES = frozenset(
    {
        "day_debate_speech",
        "sheriff_campaign_speech",
        "sheriff_pk_speech",
        "exile_pk_speech",
        "exile_last_words",
        "first_night_last_words",
    }
)
_TECHNICAL_FALSE_FALLBACK_ACTION_TYPES = frozenset(
    {
        "sheriff_run",
        "sheriff_withdraw",
        "werewolf_self_explosion",
    }
)


def _technical_target_exhaustion_outcome(
    *,
    spec: SpeechSpec,
    exc: ModelError,
    generation_policy: ResolvedModelGenerationPolicy,
) -> tuple[RequiredTargetTechnicalOutcome, RequiredTargetExhaustionFailureMode] | None:
    target_policy = generation_policy.required_target_exhaustion
    if (
        generation_policy.schema_version not in MODEL_GENERATION_POLICY_SUPPORTED_SCHEMA_VERSIONS
        or generation_policy.blocking_required_target_output_timeout_mode != "technical_outcome"
        or target_policy is None
        or spec.target_exhaustion_outcome is None
        or spec.decision_contract.kind != "target"
        or spec.decision_contract.target_mode != "required"
        or not spec.allowed_target_ids
    ):
        return None
    if spec.target_exhaustion_outcome not in {
        target_policy.day_vote_outcome,
        target_policy.night_required_target_outcome,
    }:
        return None
    failure_mode = _required_target_exhaustion_failure_mode(exc)
    if failure_mode is None or failure_mode not in target_policy.eligible_failure_modes:
        return None
    return spec.target_exhaustion_outcome, failure_mode


def _required_target_exhaustion_failure_mode(
    exc: ModelError,
) -> RequiredTargetExhaustionFailureMode | None:
    if exc.code == "model_output_budget_exhausted":
        return "output_budget_exhausted"
    if exc.code == "model_attempt_hard_timeout" or exc.timeout_scope == "attempt_hard":
        return "attempt_hard_timeout"
    if exc.code == "model_total_timeout" and (
        exc.timeout_scope == "action_budget" or exc.failure_stage == "action_budget"
    ):
        return "action_wall_timeout"
    return None


def _technical_exhaustion_outcome(
    *,
    spec: SpeechSpec,
    exc: ModelError,
    attempt_id: str,
) -> tuple[ModelDecision, str] | None:
    # A prefetched turn is not yet public.  Its failure must stay private and
    # fall back to the normal foreground turn instead of publishing a skip
    # while the predecessor is still speaking.
    if spec.pipeline_stage == "generation" and spec.pipeline_kind != "pre_exile":
        return None
    if not model_failure_disposition(exc).pausable:
        return None
    if spec.action_type in _TECHNICAL_SKIP_ACTION_TYPES and spec.decision_contract.kind == "speech":
        return (
            ModelDecision(
                target_player_id=None,
                speech=None,
                provider_request_id=attempt_id,
                first_token_ms=0,
                completed_ms=exc.elapsed_ms or 0,
            ),
            "action_skipped_technical",
        )
    if (
        spec.action_type in _TECHNICAL_FALSE_FALLBACK_ACTION_TYPES
        and spec.decision_contract.kind == "boolean"
        and spec.decision_contract.boolean_field is not None
    ):
        return (
            ModelDecision(
                target_player_id=None,
                speech=None,
                provider_request_id=attempt_id,
                first_token_ms=0,
                completed_ms=exc.elapsed_ms or 0,
                boolean_field=spec.decision_contract.boolean_field,
                boolean_value=False,
            ),
            "technical_fallback_applied",
        )
    return None


def _model_generation_policy_audit_payload(
    *,
    policy: ResolvedModelGenerationPolicy,
    action_type: str,
    model_provider: str | None,
    model_id: str | None,
    explicit_reasoning_only_elapsed_ms: int | None = None,
    first_token_ms: int | None = None,
    first_visible_text_ms: int | None = None,
    terminal_elapsed_ms: int | None = None,
) -> dict[str, Any]:
    reasoning_only_elapsed_ms = _resolved_reasoning_only_elapsed_ms(
        explicit=explicit_reasoning_only_elapsed_ms,
        first_token_ms=first_token_ms,
        first_visible_text_ms=first_visible_text_ms,
        terminal_elapsed_ms=terminal_elapsed_ms,
    )
    reasoning_only_timeout_ms = policy.reasoning_only_timeout_ms
    shadow_would_timeout = (
        reasoning_only_elapsed_ms >= reasoning_only_timeout_ms
        if policy.enforcement == "observe_only"
        and reasoning_only_elapsed_ms is not None
        and reasoning_only_timeout_ms is not None
        else None
    )
    return {
        "model_provider": model_provider,
        "model_id": model_id,
        "action_type": action_type,
        "model_generation_policy_contract_status": policy.status,
        "model_generation_policy_schema_version": policy.schema_version,
        "model_generation_policy_classification_version": (policy.classification_version),
        "model_generation_policy_enforcement": policy.enforcement,
        "model_generation_policy_profile": policy.profile,
        "model_generation_policy_profile_source": policy.source,
        "model_generation_policy_reasoning_parameter_mode": (policy.reasoning_parameter_mode),
        "reasoning_only_timeout_ms": reasoning_only_timeout_ms,
        "timeout_max_attempts": policy.timeout_max_attempts,
        "automatic_retry_enforcement": policy.automatic_retry_enforcement,
        "output_budget_max_attempts": policy.output_budget_max_attempts,
        "attempt_hard_timeout_max_attempts": (policy.attempt_hard_timeout_max_attempts),
        "transport_max_attempts": policy.transport_max_attempts,
        "post_token_transport_max_attempts": (policy.post_token_transport_max_attempts),
        "queue_wait_budget_mode": policy.queue_wait_budget_mode,
        "action_wall_timeout_ms": policy.action_wall_timeout_ms,
        "blocking_required_target_output_timeout_mode": (
            policy.blocking_required_target_output_timeout_mode
        ),
        "blocking_required_target_queue_wait_budget_mode": (
            policy.blocking_required_target_queue_wait_budget_mode
        ),
        "required_target_exhaustion": (
            {
                "eligible_failure_modes": list(
                    policy.required_target_exhaustion.eligible_failure_modes
                ),
                "day_vote_outcome": policy.required_target_exhaustion.day_vote_outcome,
                "night_required_target_outcome": (
                    policy.required_target_exhaustion.night_required_target_outcome
                ),
                "transport_mode": policy.required_target_exhaustion.transport_mode,
                "machine_format_mode": (policy.required_target_exhaustion.machine_format_mode),
            }
            if policy.required_target_exhaustion is not None
            else None
        ),
        "private_round_memory_mode": policy.private_round_memory_mode,
        "reasoning_only_elapsed_ms": reasoning_only_elapsed_ms,
        "shadow_would_timeout": shadow_would_timeout,
    }


def _resolved_reasoning_only_elapsed_ms(
    *,
    explicit: int | None,
    first_token_ms: int | None,
    first_visible_text_ms: int | None,
    terminal_elapsed_ms: int | None,
) -> int | None:
    if isinstance(explicit, int) and not isinstance(explicit, bool) and explicit >= 0:
        return explicit
    if (
        not isinstance(first_token_ms, int)
        or isinstance(first_token_ms, bool)
        or first_token_ms < 0
    ):
        return None
    terminal_ms = (
        first_visible_text_ms
        if isinstance(first_visible_text_ms, int)
        and not isinstance(first_visible_text_ms, bool)
        and first_visible_text_ms >= 0
        else terminal_elapsed_ms
    )
    if not isinstance(terminal_ms, int) or isinstance(terminal_ms, bool) or terminal_ms < 0:
        return None
    return max(0, terminal_ms - first_token_ms)


def _model_failure_payload(
    *,
    action_id: str,
    attempt_id: str,
    attempt_no: int,
    max_attempts: int,
    retry_cycle: int,
    cycle_attempt_no: int,
    exc: ModelError,
    failure_category: str,
    retryable: bool,
    action_recoverable: bool,
    terminal: bool,
    attempt_budget_ms: int,
    action_budget_ms: int,
    action_elapsed_ms: int,
    action_remaining_ms: int,
    model_binding_failure_streak: int,
    model_binding_health_status: str,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "action_id": action_id,
        "attempt_id": attempt_id,
        "attempt_no": attempt_no,
        "cycle_attempt_no": cycle_attempt_no,
        "retry_cycle": retry_cycle,
        "max_attempts": max_attempts,
        "failure_kind": "model",
        "failure_code": exc.code,
        "failure_category": failure_category,
        "retryable": retryable,
        "attempt_terminal": True,
        "action_recoverable": action_recoverable,
        "run_terminal": not action_recoverable,
        "terminal": terminal,
        "attempt_budget_ms": attempt_budget_ms,
        "action_budget_ms": action_budget_ms,
        "action_elapsed_ms": action_elapsed_ms,
        "action_remaining_ms": action_remaining_ms,
        "model_binding_failure_streak": model_binding_failure_streak,
        "model_binding_health_status": model_binding_health_status,
        "failure_stage": exc.failure_stage,
        "exception_type": exc.exception_type,
        "errno": exc.errno,
        "http_status": exc.http_status,
        "provider_request_id": exc.provider_request_id,
        "first_token_seen": exc.first_token_seen,
        "response_headers_seen": exc.response_headers_seen,
        "response_headers": exc.response_headers or None,
        "first_token_ms": exc.first_token_ms,
        "first_token_kind": exc.first_token_kind,
        "first_visible_text_ms": exc.first_visible_text_ms,
        "timeout_scope": exc.timeout_scope,
        "elapsed_ms": exc.elapsed_ms,
        "retry_after_ms": (
            round(exc.retry_after_seconds * 1000) if exc.retry_after_seconds is not None else None
        ),
        "queue_wait_ms": exc.queue_wait_ms,
        "provider_in_flight": exc.provider_in_flight,
        "provider_concurrency_limit": exc.provider_concurrency_limit,
        "reasoning_delta_count": exc.reasoning_delta_count,
        "text_delta_count": exc.text_delta_count,
        "reasoning_character_count": exc.reasoning_character_count,
        "text_character_count": exc.text_character_count,
        "estimated_reasoning_tokens": exc.estimated_reasoning_tokens,
        "estimated_output_tokens": exc.estimated_output_tokens,
        "max_inter_delta_ms": exc.max_inter_delta_ms,
        "last_progress_ms": exc.last_progress_ms,
        "finish_reason": exc.finish_reason,
        "provider_usage": exc.provider_usage,
        "usage_update_count": exc.usage_update_count,
        "usage_conflict_observed": exc.usage_conflict_observed,
        "usage_consistency": exc.usage_consistency,
        "reasoning_only_elapsed_ms": exc.reasoning_only_elapsed_ms,
    }
    if isinstance(exc, QualityError):
        payload["application_validation_result"] = "rejected"
        if exc.raw_response is not None:
            payload["raw_response"] = exc.raw_response
    return {key: value for key, value in payload.items() if value is not None}


def _model_binding_health_status(consecutive_failure_count: int) -> str:
    if consecutive_failure_count <= 0:
        return "healthy"
    if consecutive_failure_count == 1:
        return "impaired"
    return "degraded"


def _required_retry_window_seconds(
    *,
    spec: SpeechSpec,
    disposition: FailureDisposition,
    exc: ModelError,
    policy: ModelRetryPolicy,
    cycle_output_budget_failure_count: int = 0,
) -> float:
    if disposition.category == "output_budget":
        if (
            cycle_output_budget_failure_count == 2
            and _is_blocking_required_target(spec)
            and policy.max_attempts >= 3
        ):
            elapsed_ms = exc.elapsed_ms
            if (
                isinstance(elapsed_ms, (int, float))
                and not isinstance(elapsed_ms, bool)
                and elapsed_ms > 0
            ):
                return min(policy.attempt_total_seconds, elapsed_ms / 1000)
            return policy.attempt_total_seconds
        return 0.0
    if disposition.category != "timeout":
        return 0.0
    if (
        spec.action_type in _TECHNICAL_SKIP_ACTION_TYPES
        and spec.decision_contract.kind == "speech"
        and not exc.first_token_seen
        and exc.failure_stage in {"response_headers", "first_token"}
        and isinstance(exc.elapsed_ms, int)
        and not isinstance(exc.elapsed_ms, bool)
        and exc.elapsed_ms > 0
    ):
        # A public speech gets one bounded second chance after a pre-token
        # stall. The retry still shares the original action deadline and never
        # substitutes another model or fabricates speech.
        return min(policy.attempt_total_seconds, exc.elapsed_ms / 1000)
    return policy.attempt_total_seconds


def _enrich_model_error_from_progress(
    exc: ModelError,
    progress: _ModelAttemptProgressTrace,
    *,
    progress_capable: bool,
) -> None:
    if exc.provider_request_id is None and progress.provider_request_id is not None:
        exc.provider_request_id = progress.provider_request_id
    if progress.response_headers_recorded:
        exc.response_headers_seen = True
        exc.response_headers = dict(progress.response_headers or {})
    if progress.first_token_recorded:
        exc.first_token_seen = True
        exc.first_token_ms = progress.first_token_ms
        exc.first_token_kind = progress.first_token_kind
    if progress.first_text_recorded:
        exc.first_visible_text_ms = progress.first_visible_text_ms
    if exc.queue_wait_ms is None and progress.admitted_recorded:
        exc.queue_wait_ms = progress.queue_wait_ms
    if exc.provider_in_flight is None:
        exc.provider_in_flight = progress.provider_in_flight
    if exc.provider_concurrency_limit is None:
        exc.provider_concurrency_limit = progress.provider_concurrency_limit
    if progress_capable and exc.failure_stage is None:
        exc.failure_stage = progress.failure_stage()
    exc.reasoning_delta_count = max(
        exc.reasoning_delta_count,
        progress.reasoning_delta_count,
    )
    exc.text_delta_count = max(
        exc.text_delta_count,
        progress.text_delta_count,
    )
    for field_name in (
        "reasoning_character_count",
        "text_character_count",
        "estimated_reasoning_tokens",
        "estimated_output_tokens",
        "max_inter_delta_ms",
        "last_progress_ms",
    ):
        observed = getattr(progress, field_name)
        if observed is None:
            continue
        current = getattr(exc, field_name)
        setattr(exc, field_name, max(current or 0, observed))
    if progress.usage_update_count > exc.usage_update_count:
        exc.provider_usage = (
            dict(progress.provider_usage) if progress.provider_usage is not None else None
        )
        exc.usage_update_count = progress.usage_update_count
        exc.usage_consistency = progress.usage_consistency
    elif exc.provider_usage is None and progress.provider_usage is not None:
        exc.provider_usage = dict(progress.provider_usage)
        exc.usage_consistency = progress.usage_consistency
    exc.usage_conflict_observed = (
        exc.usage_conflict_observed or progress.usage_conflict_observed
    )


def _enrich_model_error_from_decision(
    exc: ModelError,
    decision: ModelDecision,
) -> None:
    """Preserve terminal stream diagnostics when application validation rejects."""

    if exc.provider_request_id is None:
        exc.provider_request_id = decision.provider_request_id
    if exc.first_token_ms is None:
        exc.first_token_ms = decision.first_token_ms
    exc.first_token_seen = True
    if exc.first_visible_text_ms is None:
        exc.first_visible_text_ms = decision.first_visible_text_ms
    if exc.elapsed_ms is None:
        exc.elapsed_ms = decision.completed_ms
    if exc.queue_wait_ms is None:
        exc.queue_wait_ms = decision.queue_wait_ms
    if exc.provider_in_flight is None:
        exc.provider_in_flight = decision.provider_in_flight
    if exc.provider_concurrency_limit is None:
        exc.provider_concurrency_limit = decision.provider_concurrency_limit
    exc.reasoning_delta_count = decision.reasoning_delta_count
    exc.text_delta_count = decision.text_delta_count
    if exc.max_inter_delta_ms is None:
        exc.max_inter_delta_ms = decision.max_inter_delta_ms
    if exc.last_progress_ms is None:
        exc.last_progress_ms = decision.last_progress_ms
    if exc.finish_reason is None:
        exc.finish_reason = decision.finish_reason
    if exc.provider_usage is None and decision.provider_usage is not None:
        exc.provider_usage = dict(decision.provider_usage)
    exc.usage_update_count = decision.usage_update_count
    exc.usage_conflict_observed = decision.usage_conflict_observed
    exc.usage_consistency = decision.usage_consistency
    if exc.reasoning_only_elapsed_ms is None:
        exc.reasoning_only_elapsed_ms = decision.reasoning_only_elapsed_ms


def _model_retry_delay_seconds(
    *,
    disposition: FailureDisposition,
    exc: ModelError,
    cycle_attempt_no: int,
    policy: ModelRetryPolicy,
) -> float:
    if disposition.category == "timeout":
        return 0.0
    if exc.http_status == 429:
        base = exc.retry_after_seconds
        if base is None:
            base = 2.0 if cycle_attempt_no == 1 else 8.0
    else:
        base = min(
            2.0,
            policy.base_delay_seconds * (4 ** max(0, cycle_attempt_no - 1)),
        )
    return base + random.uniform(0, policy.jitter_seconds)


async def _sleep_with_cancellation(
    seconds: float,
    *,
    check_cancellation: Callable[[], None],
) -> None:
    deadline = time.monotonic() + seconds
    while True:
        check_cancellation()
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return
        await asyncio.sleep(min(remaining, 0.25))


def _failure(exc: Exception) -> tuple[str, str]:
    if isinstance(exc, JudgeTemplateError):
        return "quality", "judge_template_invalid"
    if isinstance(exc, QualityError):
        return "quality", exc.code
    if isinstance(exc, ModelContextProjectionInvariantError):
        return "model", "model_context_projection_invariant_failed"
    if isinstance(exc, ModelError):
        return "model", exc.code
    if isinstance(exc, TtsError):
        return "tts", exc.code
    if isinstance(exc, VoiceRecordingError):
        return "recording", "voice_recording_failed"
    if isinstance(exc, LiveProtocolError):
        return "protocol", str(exc)
    if isinstance(exc, RepositoryError):
        return "protocol", "repository_state_conflict"
    return "protocol", "unexpected_action_failure"
