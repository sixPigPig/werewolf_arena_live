from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
import logging
from pathlib import Path
import time
from typing import Any, Protocol
from uuid import uuid4

from app.v2.model_client import V2ModelError, V2ModelSpeech, V2QualityError
from app.v2.protocol import (
    V2LiveProtocolError,
    audio_frame,
    live_state,
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
    async def generate_first_sentence(
        self,
        *,
        action_context: dict[str, Any],
        attempt_id: str,
    ) -> V2ModelSpeech: ...


class V2TtsPort(Protocol):
    def synthesize(
        self,
        *,
        text: str,
        attempt_id: str,
    ) -> AsyncIterator[bytes]: ...


class V2BroadcastPort(Protocol):
    async def broadcast_json(self, value: dict[str, Any]) -> None: ...

    async def broadcast_bytes(self, value: bytes) -> None: ...

    async def set_current(
        self,
        identity: V2PresentationIdentity | None,
        sample_cursor: int,
    ) -> None: ...


class V2ActionEngine:
    def __init__(
        self,
        *,
        repository: V2ActionRepository,
        model_client: V2ModelPort,
        tts_client: V2TtsPort,
        voice_root: Path,
        sample_rate: int,
    ) -> None:
        self._repository = repository
        self._model_client = model_client
        self._tts_client = tts_client
        self._voice_root = voice_root
        self._sample_rate = sample_rate

    async def run_first_judge_sentence(
        self,
        *,
        game_id: str,
        broadcaster: V2BroadcastPort,
    ) -> None:
        action_id = f"v2_action_{uuid4().hex[:16]}"
        context = _action_context(game_id=game_id, action_id=action_id)
        claim = self._repository.claim_action(
            game_id=game_id,
            action_id=action_id,
            context=context,
        )
        if claim is None:
            return
        context["run_id"] = claim.run_id
        identity: V2PresentationIdentity | None = None
        recorder: V2VoiceRecorder | None = None
        try:
            await broadcaster.broadcast_json(
                live_state(
                    game_id=claim.game_id,
                    run_id=claim.run_id,
                    state="generating",
                )
            )
            model_attempt_id = f"v2_model_{uuid4().hex[:16]}"
            self._repository.append_event(
                game_id=claim.game_id,
                event_type="model_request_started",
                payload={
                    "action_id": claim.action_id,
                    "attempt_id": model_attempt_id,
                },
            )
            speech = await self._model_client.generate_first_sentence(
                action_context=context,
                attempt_id=model_attempt_id,
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
            presentation_id = f"v2_pres_{uuid4().hex[:16]}"
            speech_id = f"v2_speech_{uuid4().hex[:16]}"
            voice_asset_id = f"v2_voice_{uuid4().hex[:16]}"
            identity = self._repository.open_presentation(
                claim=claim,
                presentation_id=presentation_id,
                speech_id=speech_id,
                voice_asset_id=voice_asset_id,
                subtitle_text=speech.text,
                sample_rate=self._sample_rate,
            )
            await broadcaster.set_current(identity, 0)
            await broadcaster.broadcast_json(presentation_opened(identity))
            await broadcaster.broadcast_json(segment_committed(identity))
            await broadcaster.broadcast_json(
                live_state(
                    game_id=claim.game_id,
                    run_id=claim.run_id,
                    state="broadcasting",
                )
            )
            tts_attempt_id = f"v2_tts_{uuid4().hex[:16]}"
            self._repository.append_event(
                game_id=claim.game_id,
                event_type="tts_stream_started",
                payload={
                    "action_id": claim.action_id,
                    "attempt_id": tts_attempt_id,
                    "sentence_ms": speech.sentence_ms,
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
                text=speech.text,
                attempt_id=tts_attempt_id,
            ):
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
                await broadcaster.broadcast_bytes(packet)
                now = time.monotonic()
                duration = sample_count / self._sample_rate
                official_end = max(official_end or now, now) + duration
                sample_cursor += sample_count
                await broadcaster.set_current(identity, sample_cursor)
                chunk_index += 1
            if first_chunk or official_end is None:
                raise V2TtsError("tts_empty_audio")
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
                )
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
            if remaining > 0:
                await asyncio.sleep(remaining)
            self._repository.complete_action(
                identity=identity,
                final_chunk_index=chunk_index - 1,
                final_sample_cursor=sample_cursor,
            )
            await broadcaster.broadcast_json(
                presentation_closed(
                    identity,
                    final_chunk_index=chunk_index - 1,
                    final_sample_cursor=sample_cursor,
                )
            )
            await broadcaster.set_current(None, sample_cursor)
            await broadcaster.broadcast_json(
                live_state(
                    game_id=claim.game_id,
                    run_id=claim.run_id,
                    state="awaiting_observation",
                )
            )
        except Exception as exc:
            if recorder is not None:
                recorder.abort()
            failure_kind, failure_code = _failure(exc)
            logger.warning(
                "Live V2 first sentence failed",
                extra={
                    "game_id": claim.game_id,
                    "action_id": claim.action_id,
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
                    )
                )
            else:
                await broadcaster.broadcast_json(
                    presentation_failed(
                        identity,
                        failure_kind=failure_kind,
                        failure_code=failure_code,
                    )
                )
                await broadcaster.set_current(None, 0)


def _action_context(*, game_id: str, action_id: str) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "action_id": action_id,
        "action_type": "judge_opening_speech",
        "game_id": game_id,
        "phase_id": "opening",
        "actor": {"kind": "judge", "id": "judge"},
        "objective": "生成本场直播的法官开场第一句话",
        "output_contract": {
            "kind": "public_speech",
            "language": "zh-CN",
            "sentence_count": 1,
        },
        "influence": {
            "schema_version": 1,
            "status": "disabled",
            "captured_at": None,
            "strength": 0,
            "signals": [],
        },
    }


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
