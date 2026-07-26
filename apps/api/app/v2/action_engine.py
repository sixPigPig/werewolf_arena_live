from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, replace
import hashlib
import json
import logging
from pathlib import Path
import time
from typing import Any, Protocol
from uuid import uuid4

from app.judge_configuration import RuntimeJudgeConfiguration
from app.v2.director_projection import project_director_scene
from app.v2.model_client import (
    V2ModelDecision,
    V2ModelError,
    V2ModelSpeech,
    V2QualityError,
)
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
    V2ActionRepository,
    V2PresentationIdentity,
    V2RepositoryError,
)
from app.v2.tts_client import V2TtsError
from app.v2.voice_recorder import V2VoiceRecorder, V2VoiceRecordingError


logger = logging.getLogger(__name__)


class V2ModelPort(Protocol):
    def resolve_model_id(self, model_id: str | None = None) -> str: ...

    def build_request_payload(
        self,
        *,
        action_context: dict[str, Any],
        decision: bool,
        model_id: str | None = None,
    ) -> dict[str, Any]: ...

    async def generate_judge_sentence(
        self,
        *,
        action_context: dict[str, Any],
        attempt_id: str,
        model_id: str | None = None,
        check_cancellation: Callable[[], None] | None = None,
    ) -> V2ModelSpeech: ...

    async def generate_action_decision(
        self,
        *,
        action_context: dict[str, Any],
        attempt_id: str,
        model_id: str | None = None,
        check_cancellation: Callable[[], None] | None = None,
    ) -> V2ModelDecision: ...


class V2TtsPort(Protocol):
    def synthesize(
        self,
        *,
        text: str,
        attempt_id: str,
        speaker: str | None = None,
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
    model_id: str | None = None
    activation_id: str | None = None
    output_kind: str = "public_speech"
    context: dict[str, Any] | None = None
    allowed_target_ids: tuple[str, ...] | None = None
    target_optional: bool = False


@dataclass(frozen=True)
class V2ActionResult:
    decision: V2ModelDecision | None = None


class V2ActionEngine:
    def __init__(
        self,
        *,
        repository: V2ActionRepository,
        model_client: V2ModelPort,
        tts_client: V2TtsPort,
        voice_root: Path,
        sample_rate: int,
        judge_configuration_provider: Callable[[], RuntimeJudgeConfiguration],
    ) -> None:
        self._repository = repository
        self._model_client = model_client
        self._tts_client = tts_client
        self._voice_root = voice_root
        self._sample_rate = sample_rate
        self._judge_configuration_provider = judge_configuration_provider

    def check_cancellation(self, game_id: str) -> None:
        self._repository.check_cancellation(game_id)

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
    ) -> V2ActionResult | None:
        action_id = f"v2_action_{uuid4().hex[:16]}"
        judge_configuration = None
        if spec.actor_kind == "judge":
            judge_configuration = self._judge_configuration_provider()
            model_id = judge_configuration.model_id
            speaker = judge_configuration.tts_speaker
        else:
            model_id = spec.model_id
            speaker = spec.speaker
        context = _action_context(game_id=game_id, action_id=action_id, spec=spec)
        if judge_configuration is not None:
            context["judge_configuration"] = {
                "model_provider": judge_configuration.model_provider,
                "model_id": judge_configuration.model_id,
                "tts_speaker": judge_configuration.tts_speaker,
                "version": judge_configuration.version,
            }
        claim = self._repository.claim_action(
            game_id=game_id,
            action_id=action_id,
            context=context,
            expected_phase_id=spec.phase_id,
            expected_phase_state=spec.required_phase_state,
            activation_id=spec.activation_id,
        )
        if claim is None:
            return None
        context["run_id"] = claim.run_id

        def check_cancellation() -> None:
            self._repository.check_cancellation(claim.game_id)

        identity: V2PresentationIdentity | None = None
        recorder: V2VoiceRecorder | None = None
        model_attempt_id: str | None = None
        model_request_completed = False
        try:
            check_cancellation()
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
            model_attempt_id = f"v2_model_{uuid4().hex[:16]}"
            selected_model_id = self._model_client.resolve_model_id(model_id)
            request_payload = self._model_client.build_request_payload(
                action_context=context,
                decision=decision,
                model_id=model_id,
            )
            self._repository.append_event(
                game_id=claim.game_id,
                event_type="model_request_started",
                payload={
                    "action_id": claim.action_id,
                    "attempt_id": model_attempt_id,
                    "request_kind": "decision" if decision else "speech",
                    "model_id": selected_model_id,
                    "model_provider": (
                        judge_configuration.model_provider
                        if judge_configuration is not None
                        else None
                    ),
                    "judge_configuration_version": (
                        judge_configuration.version if judge_configuration is not None else None
                    ),
                    "actor_kind": spec.actor_kind,
                    "actor_id": spec.actor_id,
                    "audience": spec.audience,
                    "request_payload": request_payload,
                },
            )
            model_decision: V2ModelDecision | None = None
            if decision:
                model_decision = await self._model_client.generate_action_decision(
                    action_context=context,
                    attempt_id=model_attempt_id,
                    model_id=model_id,
                    check_cancellation=check_cancellation,
                )
                original_target = model_decision.target_player_id
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
                                {
                                    "target_player_id": original_target,
                                    "speech": model_decision.speech,
                                },
                                ensure_ascii=False,
                            )
                        ),
                        "parsed_output": {
                            "target_player_id": original_target,
                            "speech": model_decision.speech,
                        },
                        "first_token_ms": model_decision.first_token_ms,
                        "completed_ms": model_decision.completed_ms,
                    },
                )
                model_request_completed = True
                normalized_target = original_target
                normalization_reason: str | None = None
                if spec.allowed_target_ids is None:
                    if normalized_target is not None:
                        normalized_target = None
                        normalization_reason = "targetless_action"
                elif normalized_target is None:
                    if not spec.target_optional:
                        normalized_target = _fallback_target(
                            action_id=claim.action_id,
                            allowed_target_ids=spec.allowed_target_ids,
                        )
                        normalization_reason = "required_target_missing"
                elif normalized_target not in spec.allowed_target_ids:
                    normalized_target = (
                        None
                        if spec.target_optional
                        else _fallback_target(
                            action_id=claim.action_id,
                            allowed_target_ids=spec.allowed_target_ids,
                        )
                    )
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
                            "original_target_player_id": original_target,
                            "normalized_target_player_id": normalized_target,
                            "reason": normalization_reason,
                        },
                    )
                speech_text = model_decision.speech
                sentence_ms = model_decision.completed_ms
            else:
                speech = await self._model_client.generate_judge_sentence(
                    action_context=context,
                    attempt_id=model_attempt_id,
                    model_id=model_id,
                    check_cancellation=check_cancellation,
                )
                self._repository.append_event(
                    game_id=claim.game_id,
                    event_type="model_first_token_received",
                    payload={
                        "action_id": claim.action_id,
                        "attempt_id": model_attempt_id,
                        "provider_request_id": speech.provider_request_id,
                        "first_token_ms": speech.first_token_ms,
                    },
                )
                self._repository.append_event(
                    game_id=claim.game_id,
                    event_type="model_response_received",
                    payload={
                        "action_id": claim.action_id,
                        "attempt_id": model_attempt_id,
                        "provider_request_id": speech.provider_request_id,
                        "raw_response": (
                            speech.raw_response if speech.raw_response is not None else speech.text
                        ),
                        "parsed_output": {"speech": speech.text},
                        "first_token_ms": speech.first_token_ms,
                        "completed_ms": speech.sentence_ms,
                    },
                )
                model_request_completed = True
                speech_text = speech.text
                sentence_ms = speech.sentence_ms
            check_cancellation()
            presentation_id = f"v2_pres_{uuid4().hex[:16]}"
            speech_id = f"v2_speech_{uuid4().hex[:16]}"
            voice_asset_id = f"v2_voice_{uuid4().hex[:16]}"
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
            await broadcaster.broadcast_json(
                live_state(
                    game_id=claim.game_id,
                    run_id=claim.run_id,
                    state="broadcasting",
                ),
                audience=spec.audience,
            )
            tts_attempt_id = f"v2_tts_{uuid4().hex[:16]}"
            self._repository.append_event(
                game_id=claim.game_id,
                event_type="tts_stream_started",
                payload={
                    "action_id": claim.action_id,
                    "attempt_id": tts_attempt_id,
                    "sentence_ms": sentence_ms,
                    "speaker": speaker,
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
            )
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
            if spec.success_live_state == "awaiting_observation":
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
            if model_attempt_id is not None and not model_request_completed:
                try:
                    self._repository.append_event(
                        game_id=claim.game_id,
                        event_type="model_request_failed",
                        payload={
                            "action_id": claim.action_id,
                            "attempt_id": model_attempt_id,
                            "failure_kind": failure_kind,
                            "failure_code": failure_code,
                        },
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
                )
            except Exception:
                logger.exception("Live V2 could not persist action failure")
            if identity is None:
                await broadcaster.broadcast_json(
                    live_state(
                        game_id=claim.game_id,
                        run_id=claim.run_id,
                        state="failed",
                        reason=failure_code,
                    ),
                    audience="all",
                )
            else:
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
    objective="生成本场直播的法官开场播报",
    success_live_state="ready",
    success_phase_state="opening_speech_closed",
)

_NIGHTFALL_ANNOUNCEMENT = V2SpeechSpec(
    action_type="judge_nightfall_announcement",
    phase_id="first_night",
    required_phase_state="nightfall_ready",
    objective="生成宣布本局进入首夜并提醒所有玩家闭眼的法官播报",
    success_live_state="awaiting_observation",
    success_phase_state="nightfall_announced",
)


def _action_context(
    *,
    game_id: str,
    action_id: str,
    spec: V2SpeechSpec,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "action_id": action_id,
        "action_type": spec.action_type,
        "game_id": game_id,
        "phase_id": spec.phase_id,
        "actor": {"kind": spec.actor_kind, "id": spec.actor_id},
        "objective": spec.objective,
        "output_contract": {
            "kind": spec.output_kind,
            "language": "zh-CN",
            "target_policy": (
                {"mode": "none", "allowed_target_ids": []}
                if spec.allowed_target_ids is None
                else {
                    "mode": "optional" if spec.target_optional else "required",
                    "allowed_target_ids": list(spec.allowed_target_ids),
                }
            ),
        },
        "influence": {
            "schema_version": 1,
            "status": "disabled",
            "captured_at": None,
            "strength": 0,
            "signals": [],
        },
        **(spec.context or {}),
    }


def _fallback_target(*, action_id: str, allowed_target_ids: tuple[str, ...]) -> str:
    if not allowed_target_ids:
        raise V2RepositoryError("required decision action has no allowed target")
    digest = hashlib.sha256(action_id.encode()).digest()
    return allowed_target_ids[int.from_bytes(digest[:8], "big") % len(allowed_target_ids)]


def _failure(exc: Exception) -> tuple[str, str]:
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
