from __future__ import annotations

import asyncio
import inspect
import json
import logging
import re
import time
import uuid
from collections.abc import AsyncIterator
from contextlib import suppress
from dataclasses import dataclass
from typing import Any

import websockets

from app.werewolf import volcengine_tts_protocol as protocol

logger = logging.getLogger(__name__)

FAILURE_EVENTS = {
    protocol.EventType.ConnectionFailed,
    protocol.EventType.SessionCanceled,
    protocol.EventType.SessionFailed,
}
CONNECT_TIMEOUT_SECONDS = 8
EVENT_TIMEOUT_SECONDS = 8
FIRST_AUDIO_TIMEOUT_SECONDS = 12
AUDIO_IDLE_TIMEOUT_SECONDS = 8
TIMEOUT_ERROR_MESSAGE = "Volcengine TTS timed out"
TTS_NAMESPACE = "BidirectionalTTS"
TTS_USER_ID = "werewolf-arena-live"
CONTEXT_TEXTS_RESOURCE_ID = "seed-tts-2.0"
_PRESET_BIG_MODEL_SPEAKER_RE = re.compile(r"^[a-z0-9_]+_uranus_bigtts$")
_EXPLICIT_DIALECTS = {
    "sichuan": "sichuan",
    "shaanxi": "shaanxi",
    "northeast": "dongbei",
}


@dataclass(frozen=True)
class VolcengineTtsConfig:
    enabled: bool
    api_key: str
    resource_id: str
    ws_url: str
    player_speaker: str
    judge_speaker: str
    audio_format: str
    sample_rate: int

    @property
    def available(self) -> bool:
        return self.unavailable_reason is None

    @property
    def unavailable_reason(self) -> str | None:
        if not self.enabled:
            return "disabled"
        if (
            not self.api_key.strip()
            or not self.resource_id.strip()
            or not self.ws_url.strip()
            or not self.player_speaker.strip()
            or not self.judge_speaker.strip()
        ):
            return "misconfigured"
        return None

    @property
    def unavailable_message(self) -> str | None:
        if self.unavailable_reason == "disabled":
            return "语音服务未启用，请检查后端语音配置。"
        if self.unavailable_reason == "misconfigured":
            return "语音模型配置不完整，请检查 Ark API Key、资源 ID 和音色配置。"
        return None

    @property
    def unavailable_payload(self) -> dict[str, str]:
        reason = self.unavailable_reason or "unavailable"
        message = self.unavailable_message or "语音服务暂不可用，请稍后重试。"
        return {"type": "voice_unavailable", "reason": reason, "message": message}


@dataclass(frozen=True)
class TtsSubtitleCue:
    text: str
    start_ms: int
    end_ms: int


@dataclass(frozen=True)
class TtsSubtitleTiming:
    cues: tuple[TtsSubtitleCue, ...]


TtsSynthesisItem = bytes | TtsSubtitleTiming


def supports_tts_context_texts(*, resource_id: str, speaker: str) -> bool:
    """Return whether the current TTS resource and preset speaker support context_texts."""

    return (
        resource_id.strip().lower() == CONTEXT_TEXTS_RESOURCE_ID
        and _PRESET_BIG_MODEL_SPEAKER_RE.fullmatch(speaker.strip()) is not None
    )


def build_tts_headers(
    config: VolcengineTtsConfig,
    *,
    connect_id: str,
) -> dict[str, str]:
    return {
        "X-Api-Key": config.api_key,
        "X-Api-Resource-Id": config.resource_id,
        "X-Api-Connect-Id": connect_id,
        "X-Control-Require-Usage-Tokens-Return": "*",
    }


def build_tts_request(
    *,
    text: str,
) -> dict[str, Any]:
    return {
        "namespace": TTS_NAMESPACE,
        "req_params": {
            "text": text,
        },
    }


def build_tts_session_request(
    *,
    speaker: str,
    audio_format: str,
    sample_rate: int,
    context_texts: list[str] | tuple[str, ...] | None = None,
    dialect: str = "",
) -> dict[str, Any]:
    request = {
        "user": {"uid": TTS_USER_ID},
        "namespace": TTS_NAMESPACE,
        "req_params": {
            "speaker": speaker,
            "audio_params": {
                "enable_subtitle": True,
                "format": audio_format,
                "sample_rate": sample_rate,
            },
        },
    }
    safe_contexts = [
        text.strip()[:500]
        for text in context_texts or ()
        if isinstance(text, str) and text.strip()
    ][:1]
    additions: dict[str, Any] = {}
    if safe_contexts:
        additions["context_texts"] = safe_contexts
    normalized_dialect = dialect.strip().lower()
    if normalized_dialect:
        try:
            additions["explicit_dialect"] = _EXPLICIT_DIALECTS[normalized_dialect]
        except KeyError as exc:
            raise ValueError(f"Unsupported Volcengine TTS dialect: {dialect}") from exc
    if additions:
        request["req_params"]["additions"] = json.dumps(
            additions,
            ensure_ascii=False,
            separators=(",", ":"),
        )
    return request


def mime_type_for_format(audio_format: str) -> str:
    formats = {
        "mp3": "audio/mpeg",
        "wav": "audio/wav",
        "pcm": "audio/L16",
    }
    return formats.get(audio_format.lower(), "application/octet-stream")


class VolcengineTtsClient:
    def __init__(self, config: VolcengineTtsConfig) -> None:
        self.config = config

    async def synthesize(
        self,
        *,
        speaker: str,
        text_chunks: list[str],
        context_texts: list[str] | tuple[str, ...] | None = None,
        dialect: str = "",
    ) -> AsyncIterator[TtsSynthesisItem]:
        if not self.config.available:
            raise RuntimeError("Volcengine TTS is not configured")

        connect_id = str(uuid.uuid4())
        headers = build_tts_headers(self.config, connect_id=connect_id)
        logger.info("Opening Volcengine TTS session", extra={"connect_id": connect_id})

        websocket = await _await_with_timeout(
            websockets.connect(
                self.config.ws_url,
                additional_headers=headers,
                max_size=10 * 1024 * 1024,
            ),
            CONNECT_TIMEOUT_SECONDS,
        )
        session_id = str(uuid.uuid4())
        session_started = False
        session_finished = False
        try:
            await _await_with_timeout(
                protocol.start_connection(websocket),
                EVENT_TIMEOUT_SECONDS,
            )
            await _await_with_timeout(
                protocol.wait_for_event(
                    websocket,
                    protocol.MsgType.FullServerResponse,
                    protocol.EventType.ConnectionStarted,
                ),
                EVENT_TIMEOUT_SECONDS,
            )
            session_request = build_tts_session_request(
                speaker=speaker,
                audio_format=self.config.audio_format,
                sample_rate=self.config.sample_rate,
                context_texts=context_texts,
                dialect=dialect,
            )
            await _await_with_timeout(
                protocol.start_session(
                    websocket,
                    json.dumps(session_request, ensure_ascii=False).encode("utf-8"),
                    session_id,
                ),
                EVENT_TIMEOUT_SECONDS,
            )
            await _await_with_timeout(
                protocol.wait_for_event(
                    websocket,
                    protocol.MsgType.FullServerResponse,
                    protocol.EventType.SessionStarted,
                ),
                EVENT_TIMEOUT_SECONDS,
            )
            session_started = True

            for text in text_chunks:
                request = build_tts_request(text=text)
                await _await_with_timeout(
                    protocol.task_request(
                        websocket,
                        json.dumps(request, ensure_ascii=False).encode("utf-8"),
                        session_id,
                    ),
                    EVENT_TIMEOUT_SECONDS,
                )

            await _await_with_timeout(
                protocol.finish_session(websocket, session_id),
                EVENT_TIMEOUT_SECONDS,
            )

            first_audio_deadline = time.monotonic() + FIRST_AUDIO_TIMEOUT_SECONDS
            idle_deadline: float | None = None
            while True:
                if idle_deadline is None:
                    receive_timeout = _remaining_timeout(first_audio_deadline)
                else:
                    receive_timeout = _remaining_timeout(idle_deadline)
                message = await _await_with_timeout(
                    protocol.receive_message(websocket),
                    receive_timeout,
                )
                if message.type == protocol.MsgType.AudioOnlyServer:
                    yield message.payload
                    idle_deadline = time.monotonic() + AUDIO_IDLE_TIMEOUT_SECONDS
                    continue
                if message.type == protocol.MsgType.FullServerResponse:
                    if getattr(message, "event", None) in FAILURE_EVENTS:
                        raise RuntimeError(
                            protocol.volcengine_tts_error_message(
                                message,
                                prefix="Volcengine TTS returned a failure event",
                            )
                        )
                    if getattr(message, "event", None) == protocol.EventType.SessionFinished:
                        session_finished = True
                        break
                    if getattr(message, "event", None) == protocol.EventType.TTSSubtitle:
                        timing = parse_tts_subtitle_payload(message.payload)
                        if timing is not None:
                            yield timing
                        if idle_deadline is not None:
                            idle_deadline = time.monotonic() + AUDIO_IDLE_TIMEOUT_SECONDS
                        continue
                    continue
                if message.type == protocol.MsgType.Error:
                    raise RuntimeError(
                        protocol.volcengine_tts_error_message(
                            message,
                            prefix="Volcengine TTS returned an error",
                        )
                    )
                raise RuntimeError(f"Unexpected Volcengine TTS message: {message}")
        finally:
            if session_started and not session_finished:
                with suppress(Exception):
                    await _await_with_timeout(
                        protocol.cancel_session(websocket, session_id),
                        EVENT_TIMEOUT_SECONDS,
                    )
            with suppress(Exception):
                await _await_with_timeout(
                    protocol.finish_connection(websocket),
                    EVENT_TIMEOUT_SECONDS,
                )
            with suppress(Exception):
                await _close_websocket(websocket)


def parse_tts_subtitle_payload(payload: bytes) -> TtsSubtitleTiming | None:
    try:
        data = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        logger.warning("Ignoring malformed Volcengine TTS subtitle payload")
        return None

    if not isinstance(data, dict):
        return None

    nested_payload = data.get("payload")
    if isinstance(nested_payload, dict):
        data = nested_payload

    cues = tuple(_subtitle_cue_from_word(word) for word in _subtitle_words(data))
    cues = tuple(cue for cue in cues if cue is not None)
    if cues:
        return TtsSubtitleTiming(cues=cues)

    text = _subtitle_text(data)
    start_ms = _subtitle_timestamp_ms(data, ("start_ms", "startTime", "start_time", "beginTime"))
    end_ms = _subtitle_timestamp_ms(data, ("end_ms", "endTime", "end_time"))
    if text and start_ms is not None and end_ms is not None and end_ms > start_ms:
        return TtsSubtitleTiming(cues=(TtsSubtitleCue(text=text, start_ms=start_ms, end_ms=end_ms),))

    return None


def _subtitle_words(data: dict[str, Any]) -> list[Any]:
    words = data.get("words")
    return words if isinstance(words, list) else []


def _subtitle_cue_from_word(word: Any) -> TtsSubtitleCue | None:
    if not isinstance(word, dict):
        return None
    text = _subtitle_text(word)
    start_ms = _subtitle_timestamp_ms(word, ("start_ms", "startTime", "start_time", "beginTime"))
    end_ms = _subtitle_timestamp_ms(word, ("end_ms", "endTime", "end_time"))
    if not text or start_ms is None or end_ms is None or end_ms <= start_ms:
        return None
    return TtsSubtitleCue(text=text, start_ms=start_ms, end_ms=end_ms)


def _subtitle_text(data: dict[str, Any]) -> str:
    for key in ("text", "word"):
        value = data.get(key)
        if isinstance(value, str):
            return value.strip()
    return ""


def _subtitle_timestamp_ms(data: dict[str, Any], keys: tuple[str, ...]) -> int | None:
    for key in keys:
        value = data.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            continue
        if "ms" in key.lower():
            return max(0, int(round(value)))
        return max(0, int(round(float(value) * 1000)))
    return None


async def _await_with_timeout(awaitable: Any, timeout_seconds: float) -> Any:
    try:
        return await asyncio.wait_for(awaitable, timeout=timeout_seconds)
    except TimeoutError as exc:
        raise RuntimeError(TIMEOUT_ERROR_MESSAGE) from exc


def _remaining_timeout(deadline: float) -> float:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise RuntimeError(TIMEOUT_ERROR_MESSAGE)
    return remaining


async def _close_websocket(websocket: Any) -> None:
    close = getattr(websocket, "close", None)
    if close is None:
        return
    close_result = close()
    if inspect.isawaitable(close_result):
        await _await_with_timeout(close_result, EVENT_TIMEOUT_SECONDS)
