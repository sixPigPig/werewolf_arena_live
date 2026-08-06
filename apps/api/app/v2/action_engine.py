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

from app.judge_configuration import RuntimeJudgeConfiguration
from app.v2.director_projection import project_director_scene
from app.v2.judge_speech import V2JudgeTemplateError, render_judge_speech
from app.v2.model_context import (
    V2ModelPlayerReference,
    model_prompt_metadata,
    project_model_action_context_with_metadata,
    resolve_model_target,
    sanitize_model_speech,
)
from app.v2.model_client import (
    V2FailureDisposition,
    V2ModelDecision,
    V2ModelError,
    V2ModelTarget,
    V2QualityError,
    model_failure_disposition,
)
from app.v2.model_observation import observe_model_speech
from app.v2.protocol import (
    V2LiveProtocolError,
    audio_frame,
    director_scene_changed,
    live_state,
    game_phase_changed,
    presentation_closed,
    presentation_failed,
    presentation_opened,
    segment_committed,
)
from app.v2.repository import (
    V2ActionClaim,
    V2ActionRepository,
    V2PresentationIdentity,
    V2RepositoryError,
)
from app.v2.tts_client import V2TtsError
from app.v2.voice_recorder import V2VoiceRecorder, V2VoiceRecordingError


logger = logging.getLogger(__name__)


class V2ModelPort(Protocol):
    def resolve_model_target(
        self,
        *,
        model_provider: str,
        model_id: str,
        model_parameters: dict[str, Any],
    ) -> V2ModelTarget: ...

    def build_request_payload(
        self,
        *,
        action_context: dict[str, Any],
        decision: bool,
        target: V2ModelTarget,
    ) -> dict[str, Any]: ...

    async def generate_action_decision(
        self,
        *,
        action_context: dict[str, Any],
        attempt_id: str,
        target: V2ModelTarget,
        check_cancellation: Callable[[], None] | None = None,
    ) -> V2ModelDecision: ...


class V2TtsPort(Protocol):
    def synthesize(
        self,
        *,
        text: str,
        attempt_id: str,
        speaker: str | None = None,
        dialect: str | None = None,
        check_cancellation: Callable[[], None] | None = None,
    ) -> AsyncIterator[bytes]: ...


class V2BroadcastPort(Protocol):
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
        identity: V2PresentationIdentity,
        next_sample_cursor: int,
        audience: str = "all",
    ) -> None: ...

    async def set_current(
        self,
        identity: V2PresentationIdentity | None,
        sample_cursor: int,
        *,
        audience: str = "all",
    ) -> None: ...


@dataclass(frozen=True)
class V2DecisionContract:
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
class V2SpeechSpec:
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
    model_parameters: dict[str, Any] | None = None
    activation_id: str | None = None
    output_kind: str = "public_speech"
    decision_contract: V2DecisionContract = V2DecisionContract(kind="speech")
    context: dict[str, Any] | None = None
    allowed_target_ids: tuple[str, ...] | None = None
    model_players: tuple[V2ModelPlayerReference, ...] = ()
    best_effort: bool = False
    defer_presentation: bool = False
    isolated_failure: bool = False
    batch_id: str | None = None


@dataclass(frozen=True)
class V2ActionResult:
    decision: V2ModelDecision | None = None


@dataclass(frozen=True)
class V2ModelRetryPolicy:
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


@dataclass
class _PausedModelActionWaiter:
    action_id: str
    requested: asyncio.Event
    resumed: asyncio.Event
    control_request_id: str | None = None
    resume_succeeded: bool = False


class V2ActionEngine:
    def __init__(
        self,
        *,
        repository: V2ActionRepository,
        model_client: V2ModelPort,
        tts_client: V2TtsPort,
        voice_root: Path,
        sample_rate: int,
        judge_configuration_provider: Callable[[str], RuntimeJudgeConfiguration],
        model_retry_policy: V2ModelRetryPolicy = V2ModelRetryPolicy(),
    ) -> None:
        self._repository = repository
        self._model_client = model_client
        self._tts_client = tts_client
        self._voice_root = voice_root
        self._sample_rate = sample_rate
        self._judge_configuration_provider = judge_configuration_provider
        self._model_retry_policy = model_retry_policy
        self._paused_model_actions: dict[str, _PausedModelActionWaiter] = {}
        self._paused_model_actions_lock = asyncio.Lock()

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
        claim: V2ActionClaim,
        attempt_id: str,
        failure_code: str,
        recovery: dict[str, Any],
        broadcaster: V2BroadcastPort,
        audience: str,
    ) -> None:
        waiter = _PausedModelActionWaiter(
            action_id=claim.action_id,
            requested=asyncio.Event(),
            resumed=asyncio.Event(),
        )
        async with self._paused_model_actions_lock:
            if claim.game_id in self._paused_model_actions:
                raise V2RepositoryError("model action is already paused")
            self._paused_model_actions[claim.game_id] = waiter
        try:
            self._repository.pause_model_action(
                claim=claim,
                attempt_id=attempt_id,
                failure_code=failure_code,
                recovery=recovery,
            )
            await broadcaster.broadcast_json(
                live_state(
                    game_id=claim.game_id,
                    run_id=claim.run_id,
                    state="paused_model_error",
                    reason=failure_code,
                ),
                audience="all",
            )
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
                try:
                    await asyncio.wait_for(waiter.requested.wait(), timeout=0.25)
                except TimeoutError:
                    continue
            if waiter.control_request_id is None:
                raise V2RepositoryError("model retry has no control request")
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
        broadcaster: V2BroadcastPort,
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
        broadcaster: V2BroadcastPort,
        spec: V2SpeechSpec,
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

    async def run_player_decision(
        self,
        *,
        game_id: str,
        broadcaster: V2BroadcastPort,
        spec: V2SpeechSpec,
    ) -> V2ModelDecision | None:
        result = await self._run_model_action(
            game_id=game_id,
            broadcaster=broadcaster,
            spec=spec,
            decision=True,
        )
        return result.decision if result is not None else None

    async def present_player_decision(
        self,
        *,
        game_id: str,
        broadcaster: V2BroadcastPort,
        spec: V2SpeechSpec,
        decision: V2ModelDecision,
    ) -> bool:
        return (
            await self._run_model_action(
                game_id=game_id,
                broadcaster=broadcaster,
                spec=spec,
                decision=True,
                precomputed_decision=decision,
            )
            is not None
        )

    async def _run_judge_sentence(
        self,
        *,
        game_id: str,
        broadcaster: V2BroadcastPort,
        spec: V2SpeechSpec,
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
        broadcaster: V2BroadcastPort,
        spec: V2SpeechSpec,
        decision: bool,
        precomputed_decision: V2ModelDecision | None = None,
    ) -> V2ActionResult | None:
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
        claim = self._repository.claim_action(
            game_id=game_id,
            action_id=action_id,
            context=context,
            expected_phase_id=spec.phase_id,
            expected_phase_state=spec.required_phase_state,
            activation_id=spec.activation_id,
            best_effort=spec.best_effort,
            non_blocking=spec.defer_presentation,
        )
        if claim is None:
            return None
        context["run_id"] = claim.run_id

        def check_cancellation() -> None:
            self._repository.check_cancellation(claim.game_id)

        identity: V2PresentationIdentity | None = None
        recorder: V2VoiceRecorder | None = None
        model_attempt_id: str | None = None
        model_attempt_no: int | None = None
        model_request_completed = False
        model_failure_recorded = False
        try:
            check_cancellation()
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
            model_decision: V2ModelDecision | None = None
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
                    raise V2ModelError("model_not_configured")
                model_parameters, thinking_source = _action_model_parameters(spec)
                model_target = self._model_client.resolve_model_target(
                    model_provider=model_provider,
                    model_id=model_id,
                    model_parameters=model_parameters,
                )
                projected_model_context = project_model_action_context_with_metadata(
                    context,
                    players=spec.model_players,
                    model_context_contract=claim.model_context_contract,
                    action_record_seq=claim.action_record_seq,
                )
                model_context = projected_model_context.context
                observation_context = projected_model_context.observation_context
                prompt_projection = model_prompt_metadata(
                    model_context,
                    projection_metadata=(projected_model_context.projection_metadata),
                )
                request_payload = self._model_client.build_request_payload(
                    action_context=model_context,
                    decision=decision,
                    target=model_target,
                )
                configured_max_tokens = model_target.parameters.get("max_tokens")
                effective_max_tokens = request_payload.get(
                    "max_output_tokens",
                    request_payload.get("max_tokens"),
                )
                retry_policy = self._model_retry_policy
                retry_cycle = 1
                previous_attempt_id: str | None = None
                model_attempt_no = 0
                while model_decision is None:
                    model_started_at = time.monotonic()
                    model_deadline = model_started_at + retry_policy.action_total_seconds
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
                        model_failure_recorded = False
                        attempt_started_at = time.monotonic()
                        self._repository.append_event(
                            game_id=claim.game_id,
                            event_type="model_request_started",
                            payload={
                                "action_id": claim.action_id,
                                "attempt_id": model_attempt_id,
                                "attempt_no": model_attempt_no,
                                "cycle_attempt_no": cycle_attempt_no,
                                "retry_cycle": retry_cycle,
                                "max_attempts": retry_policy.max_attempts,
                                "attempt_budget_ms": round(
                                    retry_policy.attempt_total_seconds * 1000
                                ),
                                "action_budget_ms": round(retry_policy.action_total_seconds * 1000),
                                "action_remaining_ms": max(
                                    0,
                                    round((model_deadline - time.monotonic()) * 1000),
                                ),
                                "retry_of_attempt_id": previous_attempt_id,
                                "request_kind": "decision" if decision else "speech",
                                "model_id": model_target.model_id,
                                "model_provider": model_target.provider,
                                "model_parameters": dict(model_target.parameters),
                                "configured_max_tokens": (
                                    configured_max_tokens
                                    if isinstance(configured_max_tokens, int)
                                    and not isinstance(configured_max_tokens, bool)
                                    else None
                                ),
                                "effective_max_tokens": effective_max_tokens,
                                "max_tokens_source": (
                                    "model_configuration"
                                    if isinstance(configured_max_tokens, int)
                                    and not isinstance(configured_max_tokens, bool)
                                    else "thinking_mode_default"
                                ),
                                "thinking": model_target.parameters.get(
                                    "thinking",
                                    "default",
                                ),
                                "thinking_source": thinking_source,
                                "judge_configuration_version": None,
                                "actor_kind": spec.actor_kind,
                                "actor_id": spec.actor_id,
                                "audience": spec.audience,
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
                                "request_payload": request_payload,
                            },
                        )
                        check_cancellation()
                        remaining = model_deadline - time.monotonic()
                        try:
                            if remaining <= 0:
                                raise V2ModelError(
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
                                async with asyncio.timeout(request_timeout):
                                    model_decision = (
                                        await self._model_client.generate_action_decision(
                                            action_context=model_context,
                                            attempt_id=model_attempt_id,
                                            target=model_target,
                                            check_cancellation=check_cancellation,
                                        )
                                    )
                                    _validate_model_target_decision(
                                        model_decision,
                                        spec=spec,
                                    )
                            except TimeoutError as exc:
                                raise V2ModelError(
                                    "model_total_timeout",
                                    retryable=timeout_stage == "attempt_budget",
                                    failure_stage=timeout_stage,
                                    elapsed_ms=round(
                                        (time.monotonic() - attempt_started_at) * 1000
                                    ),
                                ) from exc
                        except V2ModelError as exc:
                            # Validation errors are raised after the client has
                            # returned a decision object. Never carry that invalid
                            # object across an automatic or operator-triggered retry.
                            model_decision = None
                            disposition = model_failure_disposition(exc)
                            remaining = model_deadline - time.monotonic()
                            delay_seconds = _model_retry_delay_seconds(
                                disposition=disposition,
                                exc=exc,
                                cycle_attempt_no=cycle_attempt_no,
                                policy=retry_policy,
                            )
                            required_retry_window = (
                                retry_policy.attempt_total_seconds
                                if disposition.category == "timeout"
                                else 0.0
                            )
                            retryable = (
                                disposition.retryable
                                and cycle_attempt_no
                                < min(retry_policy.max_attempts, disposition.max_attempts)
                                and remaining > delay_seconds + required_retry_window
                            )
                            self._repository.append_event(
                                game_id=claim.game_id,
                                event_type="model_request_failed",
                                payload=_model_failure_payload(
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
                                    attempt_budget_ms=round(
                                        retry_policy.attempt_total_seconds * 1000
                                    ),
                                    action_budget_ms=round(
                                        retry_policy.action_total_seconds * 1000
                                    ),
                                    action_elapsed_ms=round(
                                        (time.monotonic() - model_started_at) * 1000
                                    ),
                                    action_remaining_ms=max(
                                        0,
                                        round((model_deadline - time.monotonic()) * 1000),
                                    ),
                                ),
                            )
                            model_failure_recorded = True
                            previous_attempt_id = model_attempt_id
                            if retryable:
                                next_attempt_id = attempt_ids[cycle_attempt_index + 1]
                                self._repository.append_event(
                                    game_id=claim.game_id,
                                    event_type="model_retry_scheduled",
                                    payload={
                                        "action_id": claim.action_id,
                                        "attempt_id": model_attempt_id,
                                        "next_attempt_id": next_attempt_id,
                                        "attempt_no": model_attempt_no,
                                        "next_attempt_no": model_attempt_no + 1,
                                        "cycle_attempt_no": cycle_attempt_no,
                                        "retry_cycle": retry_cycle,
                                        "max_attempts": retry_policy.max_attempts,
                                        "failure_code": exc.code,
                                        "delay_ms": round(delay_seconds * 1000),
                                        "retry_after_ms": (
                                            round(exc.retry_after_seconds * 1000)
                                            if exc.retry_after_seconds is not None
                                            else None
                                        ),
                                        "action_remaining_ms": max(
                                            0,
                                            round((model_deadline - time.monotonic()) * 1000),
                                        ),
                                    },
                                )
                                await _sleep_with_cancellation(
                                    delay_seconds,
                                    check_cancellation=check_cancellation,
                                )
                                continue
                            technical_outcome = _technical_exhaustion_outcome(
                                spec=spec,
                                exc=exc,
                                attempt_id=model_attempt_id,
                            )
                            if technical_outcome is not None:
                                technical_decision, event_type = technical_outcome
                                self._repository.append_event(
                                    game_id=claim.game_id,
                                    event_type=event_type,
                                    payload={
                                        "action_id": claim.action_id,
                                        "attempt_id": model_attempt_id,
                                        "action_type": spec.action_type,
                                        "failure_code": exc.code,
                                        "failure_category": disposition.category,
                                        "raw_response_preserved": isinstance(
                                            exc,
                                            V2QualityError,
                                        )
                                        and exc.raw_response is not None,
                                    },
                                )
                                self._repository.complete_silent_action(
                                    claim=claim,
                                    next_live_state=spec.success_live_state,
                                    next_phase_state=spec.success_phase_state,
                                    best_effort=spec.best_effort,
                                )
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
                                return V2ActionResult(decision=technical_decision)
                            if (
                                not spec.best_effort
                                and not spec.isolated_failure
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
                                    ),
                                    broadcaster=broadcaster,
                                    audience=spec.audience,
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
                    raise V2ModelError("model_attempt_cycle_incomplete")
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
                passive_observations = observe_model_speech(
                    sanitized_speech,
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
                raw_decision_note = model_decision.decision_note
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
                self._repository.append_event(
                    game_id=claim.game_id,
                    event_type="model_first_token_received",
                    payload={
                        "action_id": claim.action_id,
                        "attempt_id": model_attempt_id,
                        "provider_request_id": model_decision.provider_request_id,
                        "first_token_ms": model_decision.first_token_ms,
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
                self._repository.append_event(
                    game_id=claim.game_id,
                    event_type="model_response_received",
                    payload={
                        "action_id": claim.action_id,
                        "attempt_id": model_attempt_id,
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
                        "first_token_ms": model_decision.first_token_ms,
                        "completed_ms": model_decision.completed_ms,
                    },
                )
                if model_decision.repair_kind is not None:
                    self._repository.append_event(
                        game_id=claim.game_id,
                        event_type="model_response_repair_applied",
                        payload={
                            "action_id": claim.action_id,
                            "attempt_id": model_attempt_id,
                            "repair_kind": model_decision.repair_kind,
                            "raw_response_preserved": True,
                        },
                    )
                self._repository.resolve_model_action_recovery(
                    action_id=claim.action_id,
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
                model_request_completed = True
                normalized_target = resolved_target
                normalization_reason: str | None = None
                if spec.decision_contract.kind != "target":
                    if original_target is not None:
                        normalized_target = None
                        normalization_reason = "targetless_action"
                elif original_target is not None and resolved_target is None:
                    if spec.decision_contract.target_mode == "required":
                        raise V2RepositoryError(
                            "required model target became invalid after validation"
                        )
                    normalized_target = None
                    normalization_reason = "target_not_allowed"
                elif normalized_target is None:
                    if spec.decision_contract.target_mode == "required":
                        raise V2RepositoryError(
                            "required model target disappeared after validation"
                        )
                elif normalized_target not in (spec.allowed_target_ids or ()):
                    if spec.decision_contract.target_mode == "required":
                        raise V2RepositoryError(
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
                self._repository.complete_silent_action(
                    claim=claim,
                    next_live_state=spec.success_live_state,
                    next_phase_state=spec.success_phase_state,
                    best_effort=spec.best_effort,
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
                return V2ActionResult(decision=model_decision)
            presentation_id = f"v2_pres_{uuid4().hex[:16]}"
            speech_id = f"v2_speech_{uuid4().hex[:16]}"
            tts_enabled = bool(getattr(self._tts_client, "enabled", True))
            voice_asset_id = f"v2_voice_{uuid4().hex[:16]}" if tts_enabled else None
            identity = self._repository.open_presentation(
                claim=claim,
                presentation_id=presentation_id,
                speech_id=speech_id,
                voice_asset_id=voice_asset_id,
                subtitle_text=speech_text,
                sample_rate=self._sample_rate,
                actor_kind=spec.actor_kind,
                actor_id=spec.actor_id,
                audience=spec.audience,
            )
            await broadcaster.set_current(identity, 0, audience=spec.audience)
            await broadcaster.broadcast_json(presentation_opened(identity), audience=spec.audience)
            await broadcaster.broadcast_json(segment_committed(identity), audience=spec.audience)
            if not spec.best_effort:
                await broadcaster.broadcast_json(
                    live_state(
                        game_id=claim.game_id,
                        run_id=claim.run_id,
                        state="broadcasting",
                    ),
                    audience=spec.audience,
                )
            if not tts_enabled:
                self._repository.append_event(
                    game_id=claim.game_id,
                    event_type="tts_skipped",
                    payload={
                        "action_id": claim.action_id,
                        "reason_code": "tts_disabled",
                        "delivery_mode": "text_only",
                    },
                )
                self._repository.complete_text_action(
                    identity=identity,
                    next_live_state=spec.success_live_state,
                    next_phase_state=spec.success_phase_state,
                    best_effort=spec.best_effort,
                )
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
                return V2ActionResult(decision=model_decision)
            if identity.voice_asset_id is None:
                raise V2RepositoryError("enabled TTS action has no voice asset")
            tts_attempt_id = f"v2_tts_{uuid4().hex[:16]}"
            self._repository.append_event(
                game_id=claim.game_id,
                event_type="tts_stream_started",
                payload={
                    "action_id": claim.action_id,
                    "attempt_id": tts_attempt_id,
                    "sentence_ms": sentence_ms,
                    "speaker": speaker,
                    "dialect": spec.dialect,
                    "judge_configuration_version": (
                        judge_configuration.version if judge_configuration is not None else None
                    ),
                },
            )
            recorder = V2VoiceRecorder(
                root=self._voice_root,
                storage_key=identity.storage_key,
                sample_rate=self._sample_rate,
            )
            tts_started = time.monotonic()
            official_end: float | None = None
            sample_cursor = 0
            chunk_index = 0
            first_chunk = True
            async for pcm in self._tts_client.synthesize(
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
                            payload={
                                "action_id": claim.action_id,
                                "attempt_id": tts_attempt_id,
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
                raise V2TtsError("tts_empty_audio")
            check_cancellation()
            self._repository.mark_finalizing(
                game_id=claim.game_id,
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
            recorder = None
            if recorded.sample_count != sample_cursor:
                raise V2VoiceRecordingError("recorded sample count differs from broadcast")
            self._repository.mark_voice_ready(
                identity=identity,
                sample_count=recorded.sample_count,
                duration_ms=recorded.duration_ms,
                pcm_sha256=recorded.pcm_sha256,
                size_bytes=recorded.size_bytes,
            )
            remaining = official_end - time.monotonic()
            while remaining > 0:
                await asyncio.sleep(min(remaining, 0.1))
                check_cancellation()
                remaining = official_end - time.monotonic()
            check_cancellation()
            self._repository.complete_action(
                identity=identity,
                final_chunk_index=chunk_index - 1,
                final_sample_cursor=sample_cursor,
                next_live_state=spec.success_live_state,
                next_phase_state=spec.success_phase_state,
                best_effort=spec.best_effort,
            )
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
            return V2ActionResult(decision=model_decision)
        except asyncio.CancelledError:
            if recorder is not None:
                recorder.abort()
            raise
        except Exception as exc:
            if recorder is not None:
                recorder.abort()
            failure_kind, failure_code = _failure(exc)
            if (
                model_attempt_id is not None
                and not model_request_completed
                and not model_failure_recorded
            ):
                try:
                    failure_payload: dict[str, Any] = {
                        "action_id": claim.action_id,
                        "attempt_id": model_attempt_id,
                        "attempt_no": model_attempt_no,
                        "max_attempts": self._model_retry_policy.max_attempts,
                        "failure_kind": failure_kind,
                        "failure_code": failure_code,
                        "retryable": False,
                        "terminal": True,
                    }
                    if isinstance(exc, V2QualityError) and exc.raw_response is not None:
                        failure_payload["raw_response"] = exc.raw_response
                    self._repository.append_event(
                        game_id=claim.game_id,
                        event_type="model_request_failed",
                        payload=failure_payload,
                    )
                except Exception:
                    logger.exception("Live V2 could not persist model request failure")
            logger.warning(
                "Live V2 judge sentence failed",
                extra={
                    "game_id": claim.game_id,
                    "action_id": claim.action_id,
                    "action_type": spec.action_type,
                    "failure_kind": failure_kind,
                    "failure_code": failure_code,
                },
            )
            try:
                self._repository.fail_action(
                    claim=claim,
                    failure_kind=failure_kind,
                    failure_code=failure_code,
                    identity=identity,
                    best_effort=spec.best_effort,
                )
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
                    audience="all",
                )
                await broadcaster.set_current(None, 0, audience=spec.audience)
            return None


_OPENING_SPEECH = V2SpeechSpec(
    action_type="judge_opening_speech",
    phase_id="opening",
    required_phase_state="opening_ready",
    objective="播报本场直播的固定法官开场词",
    success_live_state="ready",
    success_phase_state="opening_speech_closed",
)

_NIGHTFALL_ANNOUNCEMENT = V2SpeechSpec(
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
    spec: V2SpeechSpec,
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
        **({"batch_id": spec.batch_id} if spec.batch_id is not None else {}),
        **(spec.context or {}),
    }


def _action_model_parameters(
    spec: V2SpeechSpec,
) -> tuple[dict[str, Any], str]:
    return dict(spec.model_parameters or {}), "model_configuration"


def _output_contract(spec: V2SpeechSpec) -> dict[str, Any]:
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
            raise V2LiveProtocolError("target contract requires a target mode")
        if contract.target_mode == "required" and not spec.allowed_target_ids:
            raise V2LiveProtocolError("required target contract requires allowed targets")
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
        raise V2LiveProtocolError("boolean contract requires a semantic field")
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


def _can_pause_for_model_failure(exc: V2ModelError) -> bool:
    return model_failure_disposition(exc).pausable


def _validate_model_target_decision(
    decision: V2ModelDecision,
    *,
    spec: V2SpeechSpec,
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
        raise V2QualityError(
            "model_decision_required_target_missing",
            raw_response=decision.raw_response,
        )


def _model_action_recovery_snapshot(
    *,
    spec: V2SpeechSpec,
    target: V2ModelTarget,
    request_payload: dict[str, Any],
    model_context: dict[str, Any],
    failure_category: str,
    attempt_no: int,
    retry_cycle: int,
) -> dict[str, Any]:
    canonical_request = json.dumps(
        request_payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return {
        "action_type": spec.action_type,
        "actor_id": spec.actor_id,
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


def _technical_exhaustion_outcome(
    *,
    spec: V2SpeechSpec,
    exc: V2ModelError,
    attempt_id: str,
) -> tuple[V2ModelDecision, str] | None:
    if not model_failure_disposition(exc).pausable:
        return None
    if spec.action_type in _TECHNICAL_SKIP_ACTION_TYPES and spec.decision_contract.kind == "speech":
        return (
            V2ModelDecision(
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
            V2ModelDecision(
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


def _model_failure_payload(
    *,
    action_id: str,
    attempt_id: str,
    attempt_no: int,
    max_attempts: int,
    retry_cycle: int,
    cycle_attempt_no: int,
    exc: V2ModelError,
    failure_category: str,
    retryable: bool,
    action_recoverable: bool,
    terminal: bool,
    attempt_budget_ms: int,
    action_budget_ms: int,
    action_elapsed_ms: int,
    action_remaining_ms: int,
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
        "failure_stage": exc.failure_stage,
        "exception_type": exc.exception_type,
        "errno": exc.errno,
        "http_status": exc.http_status,
        "provider_request_id": exc.provider_request_id,
        "first_token_seen": exc.first_token_seen,
        "response_headers_seen": exc.response_headers_seen,
        "elapsed_ms": exc.elapsed_ms,
        "retry_after_ms": (
            round(exc.retry_after_seconds * 1000) if exc.retry_after_seconds is not None else None
        ),
    }
    if isinstance(exc, V2QualityError) and exc.raw_response is not None:
        payload["raw_response"] = exc.raw_response
    return {key: value for key, value in payload.items() if value is not None}


def _model_retry_delay_seconds(
    *,
    disposition: V2FailureDisposition,
    exc: V2ModelError,
    cycle_attempt_no: int,
    policy: V2ModelRetryPolicy,
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
    if isinstance(exc, V2JudgeTemplateError):
        return "quality", "judge_template_invalid"
    if isinstance(exc, V2QualityError):
        return "quality", exc.code
    if isinstance(exc, V2ModelError):
        return "model", exc.code
    if isinstance(exc, V2TtsError):
        return "tts", exc.code
    if isinstance(exc, V2VoiceRecordingError):
        return "recording", "voice_recording_failed"
    if isinstance(exc, V2LiveProtocolError):
        return "protocol", str(exc)
    if isinstance(exc, V2RepositoryError):
        return "protocol", "repository_state_conflict"
    return "protocol", "unexpected_action_failure"
