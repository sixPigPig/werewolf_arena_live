from __future__ import annotations

import json
import logging
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

import websockets

from app.werewolf import volcengine_tts_protocol as protocol

logger = logging.getLogger(__name__)


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
        return self.enabled and bool(self.api_key.strip())


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
    speaker: str,
    text: str,
    audio_format: str,
    sample_rate: int,
) -> dict[str, Any]:
    return {
        "req_params": {
            "speaker": speaker,
            "text": text,
            "audio_params": {
                "format": audio_format,
                "sample_rate": sample_rate,
                "enable_timestamp": False,
            },
        }
    }


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
    ) -> AsyncIterator[bytes]:
        if not self.config.available:
            raise RuntimeError("Volcengine TTS is not configured")

        connect_id = str(uuid.uuid4())
        headers = build_tts_headers(self.config, connect_id=connect_id)
        logger.info("Opening Volcengine TTS session", extra={"connect_id": connect_id})

        async with websockets.connect(
            self.config.ws_url,
            additional_headers=headers,
            max_size=10 * 1024 * 1024,
        ) as websocket:
            session_id = str(uuid.uuid4())
            await protocol.start_connection(websocket)
            await protocol.wait_for_event(
                websocket,
                protocol.MsgType.FullServerResponse,
                protocol.EventType.ConnectionStarted,
            )
            await protocol.start_session(websocket, b"{}", session_id)
            await protocol.wait_for_event(
                websocket,
                protocol.MsgType.FullServerResponse,
                protocol.EventType.SessionStarted,
            )

            for text in text_chunks:
                request = build_tts_request(
                    speaker=speaker,
                    text=text,
                    audio_format=self.config.audio_format,
                    sample_rate=self.config.sample_rate,
                )
                await protocol.task_request(
                    websocket,
                    json.dumps(request, ensure_ascii=False).encode("utf-8"),
                    session_id,
                )

            await protocol.finish_session(websocket, session_id)

            while True:
                message = await protocol.receive_message(websocket)
                if message.type == protocol.MsgType.AudioOnlyServer:
                    yield message.payload
                    continue
                if message.type == protocol.MsgType.FullServerResponse:
                    if getattr(message, "event", None) == protocol.EventType.SessionFinished:
                        break
                    continue
                if message.type == protocol.MsgType.Error:
                    raise RuntimeError("Volcengine TTS returned an error")
                break

            await protocol.finish_connection(websocket)
