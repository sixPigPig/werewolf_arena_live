from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
import json
import struct
from typing import Any
from uuid import uuid4

import websockets

from app.werewolf.volcengine_tts import build_tts_session_request


_FULL_CLIENT = 0x1
_FULL_SERVER = 0x9
_AUDIO_SERVER = 0xB
_ERROR = 0xF
_WITH_EVENT = 0x4
_START_CONNECTION = 1
_FINISH_CONNECTION = 2
_CONNECTION_STARTED = 50
_CONNECTION_FAILED = 51
_CONNECTION_FINISHED = 52
_START_SESSION = 100
_CANCEL_SESSION = 101
_FINISH_SESSION = 102
_SESSION_STARTED = 150
_SESSION_CANCELED = 151
_SESSION_FINISHED = 152
_SESSION_FAILED = 153
_TASK_REQUEST = 200


class V2TtsError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class _TtsFrame:
    message_type: int
    event: int | None
    payload: bytes
    error_code: int | None = None


class V2TtsClient:
    def __init__(
        self,
        *,
        enabled: bool,
        api_key: str,
        resource_id: str,
        ws_url: str,
        speaker: str,
        sample_rate: int,
        first_chunk_seconds: float,
        idle_seconds: float,
    ) -> None:
        self._enabled = enabled
        self._api_key = api_key.strip()
        self._resource_id = resource_id.strip()
        self._ws_url = ws_url.strip()
        self._speaker = speaker.strip()
        self._sample_rate = sample_rate
        self._first_chunk_seconds = first_chunk_seconds
        self._idle_seconds = idle_seconds

    async def synthesize(
        self,
        *,
        text: str,
        attempt_id: str,
        speaker: str | None = None,
        dialect: str | None = None,
        check_cancellation: Callable[[], None] | None = None,
    ) -> AsyncIterator[bytes]:
        _check(check_cancellation)
        selected_speaker = (speaker or self._speaker).strip()
        if not all(
            (
                self._enabled,
                self._api_key,
                self._resource_id,
                self._ws_url,
                selected_speaker,
            )
        ):
            raise V2TtsError("tts_not_configured")
        connection_id = str(uuid4())
        session_id = str(uuid4())
        websocket = None
        session_started = False
        session_finished = False
        try:
            websocket = await asyncio.wait_for(
                websockets.connect(
                    self._ws_url,
                    additional_headers={
                        "X-Api-Key": self._api_key,
                        "X-Api-Resource-Id": self._resource_id,
                        "X-Api-Connect-Id": connection_id,
                        "X-Control-Require-Usage-Tokens-Return": "*",
                    },
                    max_size=10 * 1024 * 1024,
                ),
                timeout=8.0,
            )
            await _send_event(websocket, _START_CONNECTION, b"{}")
            await _expect_event(
                websocket,
                _CONNECTION_STARTED,
                timeout=8.0,
                check_cancellation=check_cancellation,
            )
            session_request = build_tts_session_request(
                speaker=selected_speaker,
                audio_format="pcm",
                sample_rate=self._sample_rate,
                dialect=dialect or "",
            )
            session_request["user"]["uid"] = "werewolf-arena-live-v2"
            session_request["event"] = _START_SESSION
            session_request["req_params"]["audio_params"]["enable_subtitle"] = False
            session_payload = json.dumps(
                session_request,
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode()
            await _send_event(websocket, _START_SESSION, session_payload, session_id)
            await _expect_event(
                websocket,
                _SESSION_STARTED,
                timeout=8.0,
                check_cancellation=check_cancellation,
            )
            session_started = True
            task_payload = json.dumps(
                {
                    "event": _TASK_REQUEST,
                    "namespace": "BidirectionalTTS",
                    "req_params": {"text": text},
                    "request_id": attempt_id,
                },
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode()
            await _send_event(websocket, _TASK_REQUEST, task_payload, session_id)
            await _send_event(websocket, _FINISH_SESSION, b"{}", session_id)
            received_audio = False
            while True:
                _check(check_cancellation)
                timeout = self._idle_seconds if received_audio else self._first_chunk_seconds
                try:
                    frame = await _receive(
                        websocket,
                        timeout=timeout,
                        check_cancellation=check_cancellation,
                    )
                except V2TtsError as exc:
                    if exc.code != "tts_receive_timeout":
                        raise
                    code = "tts_audio_idle_timeout" if received_audio else "tts_first_audio_timeout"
                    raise V2TtsError(code) from exc
                if frame.message_type == _AUDIO_SERVER:
                    if frame.payload:
                        received_audio = True
                        yield frame.payload
                    continue
                if frame.message_type == _ERROR:
                    raise V2TtsError(f"tts_provider_error_{frame.error_code or 0}")
                if frame.message_type != _FULL_SERVER:
                    raise V2TtsError("tts_unexpected_frame")
                if frame.event in {_CONNECTION_FAILED, _SESSION_CANCELED, _SESSION_FAILED}:
                    raise V2TtsError(f"tts_failure_event_{frame.event}")
                if frame.event == _SESSION_FINISHED:
                    session_finished = True
                    break
            if not received_audio:
                raise V2TtsError("tts_empty_audio")
        except V2TtsError:
            raise
        except TimeoutError as exc:
            code = "tts_audio_idle_timeout" if session_started else "tts_connect_timeout"
            raise V2TtsError(code) from exc
        except (OSError, websockets.WebSocketException, ValueError) as exc:
            raise V2TtsError("tts_transport_failed") from exc
        finally:
            if websocket is not None:
                if session_started and not session_finished:
                    try:
                        await _send_event(websocket, _CANCEL_SESSION, b"{}", session_id)
                    except Exception:
                        pass
                try:
                    await _send_event(websocket, _FINISH_CONNECTION, b"{}")
                except Exception:
                    pass
                try:
                    await websocket.close()
                except Exception:
                    pass


async def _send_event(
    websocket: Any,
    event: int,
    payload: bytes,
    session_id: str | None = None,
) -> None:
    await websocket.send(_encode_event(event=event, payload=payload, session_id=session_id))


async def _expect_event(
    websocket: Any,
    event: int,
    *,
    timeout: float,
    check_cancellation: Callable[[], None] | None = None,
) -> _TtsFrame:
    frame = await _receive(
        websocket,
        timeout=timeout,
        check_cancellation=check_cancellation,
    )
    if frame.message_type == _ERROR:
        raise V2TtsError(f"tts_provider_error_{frame.error_code or 0}")
    if frame.message_type != _FULL_SERVER or frame.event != event:
        raise V2TtsError(f"tts_expected_event_{event}")
    return frame


async def _receive(
    websocket: Any,
    *,
    timeout: float,
    check_cancellation: Callable[[], None] | None = None,
) -> _TtsFrame:
    task = asyncio.create_task(websocket.recv())
    started = asyncio.get_running_loop().time()
    try:
        while True:
            remaining = timeout - (asyncio.get_running_loop().time() - started)
            if remaining <= 0:
                raise V2TtsError("tts_receive_timeout")
            done, _pending = await asyncio.wait(
                {task},
                timeout=min(remaining, 0.25),
            )
            if task in done:
                data = task.result()
                break
            _check(check_cancellation)
    finally:
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
    if not isinstance(data, bytes):
        raise V2TtsError("tts_text_frame_rejected")
    return _decode_frame(data)


def _check(check_cancellation: Callable[[], None] | None) -> None:
    if check_cancellation is not None:
        check_cancellation()


def _encode_event(*, event: int, payload: bytes, session_id: str | None) -> bytes:
    body = bytearray((0x11, (_FULL_CLIENT << 4) | _WITH_EVENT, 0x10, 0x00))
    body.extend(struct.pack(">i", event))
    if event not in {_START_CONNECTION, _FINISH_CONNECTION}:
        encoded_session = (session_id or "").encode()
        body.extend(struct.pack(">I", len(encoded_session)))
        body.extend(encoded_session)
    body.extend(struct.pack(">I", len(payload)))
    body.extend(payload)
    return bytes(body)


def _decode_frame(data: bytes) -> _TtsFrame:
    if len(data) < 8:
        raise ValueError("TTS frame is too short")
    header_size = (data[0] & 0x0F) * 4
    if header_size < 4 or len(data) < header_size:
        raise ValueError("TTS frame has invalid header")
    message_type = data[1] >> 4
    flags = data[1] & 0x0F
    cursor = header_size
    error_code: int | None = None
    if message_type in {_FULL_SERVER, _AUDIO_SERVER} and flags in {1, 3}:
        _, cursor = _read_i32(data, cursor)
    elif message_type == _ERROR:
        error_code, cursor = _read_u32(data, cursor)
    event: int | None = None
    if flags == _WITH_EVENT:
        event, cursor = _read_i32(data, cursor)
        if event not in {_CONNECTION_STARTED, _CONNECTION_FAILED, _CONNECTION_FINISHED}:
            _, cursor = _read_blob(data, cursor)
        elif event in {_CONNECTION_STARTED, _CONNECTION_FAILED, _CONNECTION_FINISHED}:
            _, cursor = _read_blob(data, cursor)
    payload, cursor = _read_blob(data, cursor)
    if cursor != len(data):
        raise ValueError("TTS frame has trailing bytes")
    return _TtsFrame(
        message_type=message_type,
        event=event,
        payload=payload,
        error_code=error_code,
    )


def _read_i32(data: bytes, cursor: int) -> tuple[int, int]:
    if cursor + 4 > len(data):
        raise ValueError("TTS frame is truncated")
    return struct.unpack_from(">i", data, cursor)[0], cursor + 4


def _read_u32(data: bytes, cursor: int) -> tuple[int, int]:
    if cursor + 4 > len(data):
        raise ValueError("TTS frame is truncated")
    return struct.unpack_from(">I", data, cursor)[0], cursor + 4


def _read_blob(data: bytes, cursor: int) -> tuple[bytes, int]:
    size, cursor = _read_u32(data, cursor)
    end = cursor + size
    if end > len(data):
        raise ValueError("TTS frame blob is truncated")
    return data[cursor:end], end
