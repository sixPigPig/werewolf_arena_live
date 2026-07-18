import asyncio
import json
import logging
from dataclasses import replace
from types import SimpleNamespace

import pytest

from app.werewolf import volcengine_tts as tts
from app.werewolf import volcengine_tts_protocol as protocol
from app.werewolf.volcengine_tts import (
    TtsSubtitleCue,
    TtsSubtitleTiming,
    VolcengineTtsConfig,
    VolcengineTtsClient,
    build_tts_headers,
    build_tts_request,
    build_tts_session_request,
    mime_type_for_format,
    parse_tts_subtitle_payload,
    supports_tts_context_texts,
)


BASE_CONFIG = VolcengineTtsConfig(
    enabled=True,
    api_key="ark-key",
    resource_id="seed-tts-2.0",
    ws_url="wss://example.test",
    player_speaker="player",
    judge_speaker="judge",
    audio_format="mp3",
    sample_rate=24000,
)


class FakeConnection:
    def __init__(self, websocket: object) -> None:
        self.websocket = websocket

    def __await__(self):
        async def _connect() -> object:
            return self.websocket

        return _connect().__await__()

    async def __aenter__(self) -> object:
        return self.websocket

    async def __aexit__(
        self,
        exc_type: object,
        exc_value: object,
        traceback: object,
    ) -> None:
        return None


class FakeWebsocket:
    def __init__(self, frame: str | bytes) -> None:
        self.frame = frame

    async def recv(self) -> str | bytes:
        return self.frame


def _message(
    msg_type: protocol.MsgType,
    *,
    event: protocol.EventType = protocol.EventType.None_,
    payload: bytes = b"",
) -> SimpleNamespace:
    return SimpleNamespace(type=msg_type, event=event, payload=payload)


async def _collect_synthesis(
    client: VolcengineTtsClient,
    *,
    text_chunks: list[str] | None = None,
) -> list[bytes]:
    return [
        audio
        async for audio in client.synthesize(
            speaker="player",
            text_chunks=text_chunks or ["hello"],
        )
    ]


def _patch_uuids(monkeypatch: pytest.MonkeyPatch) -> None:
    ids = iter(["connect-1", "session-1"])
    monkeypatch.setattr(tts.uuid, "uuid4", lambda: next(ids))


def _patch_volcengine_session(
    monkeypatch: pytest.MonkeyPatch,
    messages: list[SimpleNamespace],
) -> tuple[list[tuple], list[tuple]]:
    calls: list[tuple] = []
    connect_calls: list[tuple] = []
    websocket = object()

    def connect(ws_url: str, **kwargs: object) -> FakeConnection:
        connect_calls.append((ws_url, kwargs))
        return FakeConnection(websocket)

    async def start_connection(websocket_arg: object) -> None:
        assert websocket_arg is websocket
        calls.append(("start_connection",))

    async def wait_for_event(
        websocket_arg: object,
        msg_type: protocol.MsgType,
        event_type: protocol.EventType,
    ) -> None:
        assert websocket_arg is websocket
        calls.append(("wait_for_event", msg_type, event_type))

    async def start_session(
        websocket_arg: object,
        payload: bytes,
        session_id: str,
    ) -> None:
        assert websocket_arg is websocket
        calls.append(("start_session", payload, session_id))

    async def task_request(
        websocket_arg: object,
        payload: bytes,
        session_id: str,
    ) -> None:
        assert websocket_arg is websocket
        calls.append(("task_request", json.loads(payload), session_id))

    async def finish_session(websocket_arg: object, session_id: str) -> None:
        assert websocket_arg is websocket
        calls.append(("finish_session", session_id))

    async def cancel_session(websocket_arg: object, session_id: str) -> None:
        assert websocket_arg is websocket
        calls.append(("cancel_session", session_id))

    async def finish_connection(websocket_arg: object) -> None:
        assert websocket_arg is websocket
        calls.append(("finish_connection",))

    async def receive_message(websocket_arg: object) -> SimpleNamespace:
        assert websocket_arg is websocket
        calls.append(("receive_message",))
        return messages.pop(0)

    monkeypatch.setattr(tts.websockets, "connect", connect)
    monkeypatch.setattr(tts.protocol, "start_connection", start_connection)
    monkeypatch.setattr(tts.protocol, "wait_for_event", wait_for_event)
    monkeypatch.setattr(tts.protocol, "start_session", start_session)
    monkeypatch.setattr(tts.protocol, "task_request", task_request)
    monkeypatch.setattr(tts.protocol, "finish_session", finish_session)
    monkeypatch.setattr(tts.protocol, "cancel_session", cancel_session)
    monkeypatch.setattr(tts.protocol, "finish_connection", finish_connection)
    monkeypatch.setattr(tts.protocol, "receive_message", receive_message)

    return calls, connect_calls


def test_build_tts_headers_uses_connect_id_and_resource_id() -> None:
    headers = build_tts_headers(BASE_CONFIG, connect_id="connect-1")

    assert headers == {
        "X-Api-Key": "ark-key",
        "X-Api-Resource-Id": "seed-tts-2.0",
        "X-Api-Connect-Id": "connect-1",
        "X-Control-Require-Usage-Tokens-Return": "*",
    }


def test_context_texts_capability_requires_seed_tts_2_preset_big_model_speaker() -> None:
    assert supports_tts_context_texts(
        resource_id="seed-tts-2.0",
        speaker="zh_female_gaolengyujie_uranus_bigtts",
    )
    assert not supports_tts_context_texts(
        resource_id="seed-tts-1.0",
        speaker="zh_female_gaolengyujie_uranus_bigtts",
    )
    assert not supports_tts_context_texts(
        resource_id="seed-tts-2.0",
        speaker="S_clone_voice_001",
    )


def test_build_tts_request_contains_namespace_and_text_only() -> None:
    request = build_tts_request(
        text="我先发言。",
    )

    assert request == {
        "namespace": "BidirectionalTTS",
        "req_params": {
            "text": "我先发言。",
        },
    }


def test_build_tts_session_request_enables_vendor_subtitle_timestamps() -> None:
    request = build_tts_session_request(
        speaker="player",
        audio_format="pcm",
        sample_rate=24000,
    )

    assert request["req_params"]["audio_params"]["enable_subtitle"] is True


def test_build_tts_session_request_adds_bounded_context_texts() -> None:
    request = build_tts_session_request(
        speaker="player",
        audio_format="pcm",
        sample_rate=24000,
        context_texts=["  克制地接话。  ", "", "坚定反问。"],
    )

    assert request["req_params"]["context_texts"] == [
        "克制地接话。",
        "坚定反问。",
    ]


def test_build_tts_session_request_omits_empty_context_texts() -> None:
    request = build_tts_session_request(
        speaker="player",
        audio_format="pcm",
        sample_rate=24000,
        context_texts=["", "   "],
    )

    assert "context_texts" not in request["req_params"]


def test_parse_tts_subtitle_payload_uses_vendor_word_timings() -> None:
    timing = parse_tts_subtitle_payload(
        json.dumps(
            {
                "phonemes": [],
                "text": "我先发言。",
                "words": [
                    {"text": "我", "startTime": 0.0, "endTime": 0.18},
                    {"text": "先", "startTime": 0.18, "endTime": 0.34},
                    {"text": "发言。", "startTime": 0.34, "endTime": 0.82},
                ],
            },
            ensure_ascii=False,
        ).encode("utf-8")
    )

    assert timing == TtsSubtitleTiming(
        cues=(
            TtsSubtitleCue(text="我", start_ms=0, end_ms=180),
            TtsSubtitleCue(text="先", start_ms=180, end_ms=340),
            TtsSubtitleCue(text="发言。", start_ms=340, end_ms=820),
        )
    )


def test_synthesize_yields_subtitle_timing_events(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_uuids(monkeypatch)
    _calls, _connect_calls = _patch_volcengine_session(
        monkeypatch,
        [
            _message(
                protocol.MsgType.FullServerResponse,
                event=protocol.EventType.TTSSubtitle,
                payload=b'{"words":[{"text":"A","startTime":0,"endTime":0.1}]}',
            ),
            _message(protocol.MsgType.AudioOnlyServer, payload=b"audio-1"),
            _message(
                protocol.MsgType.FullServerResponse,
                event=protocol.EventType.SessionFinished,
            ),
        ],
    )
    client = VolcengineTtsClient(BASE_CONFIG)

    items = asyncio.run(_collect_synthesis(client, text_chunks=["first chunk"]))

    assert items == [
        TtsSubtitleTiming(cues=(TtsSubtitleCue(text="A", start_ms=0, end_ms=100),)),
        b"audio-1",
    ]


def test_synthesize_happy_path_sends_documented_session_and_task_payloads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_uuids(monkeypatch)
    calls, _connect_calls = _patch_volcengine_session(
        monkeypatch,
        [
            _message(protocol.MsgType.AudioOnlyServer, payload=b"audio-1"),
            _message(
                protocol.MsgType.FullServerResponse,
                event=protocol.EventType.SessionFinished,
            ),
        ],
    )
    client = VolcengineTtsClient(BASE_CONFIG)

    audio = asyncio.run(_collect_synthesis(client, text_chunks=["first chunk", "second chunk"]))

    assert audio == [b"audio-1"]
    start_sessions = [call for call in calls if call[0] == "start_session"]
    assert len(start_sessions) == 1
    assert json.loads(start_sessions[0][1]) == {
        "user": {"uid": "werewolf-arena-live"},
        "namespace": "BidirectionalTTS",
        "req_params": {
            "speaker": "player",
            "audio_params": {
                "enable_subtitle": True,
                "format": "mp3",
                "sample_rate": 24000,
            },
        },
    }
    task_requests = [call for call in calls if call[0] == "task_request"]
    assert [request[1] for request in task_requests] == [
        {"namespace": "BidirectionalTTS", "req_params": {"text": "first chunk"}},
        {"namespace": "BidirectionalTTS", "req_params": {"text": "second chunk"}},
    ]


def test_mime_type_for_supported_formats() -> None:
    assert mime_type_for_format("mp3") == "audio/mpeg"
    assert mime_type_for_format("wav") == "audio/wav"
    assert mime_type_for_format("pcm") == "audio/L16"


def test_config_available_requires_enabled_credentials_resource_and_url() -> None:
    assert BASE_CONFIG.available
    assert not replace(BASE_CONFIG, enabled=False).available
    assert not replace(BASE_CONFIG, api_key="  ").available
    assert not replace(BASE_CONFIG, resource_id="  ").available
    assert not replace(BASE_CONFIG, ws_url="  ").available


def test_synthesize_happy_path_sends_lifecycle_events_and_yields_audio(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_uuids(monkeypatch)
    calls, connect_calls = _patch_volcengine_session(
        monkeypatch,
        [
            _message(
                protocol.MsgType.FullServerResponse,
                event=protocol.EventType.UsageResponse,
            ),
            _message(protocol.MsgType.AudioOnlyServer, payload=b"audio-1"),
            _message(
                protocol.MsgType.FullServerResponse,
                event=protocol.EventType.SessionFinished,
            ),
        ],
    )
    client = VolcengineTtsClient(BASE_CONFIG)

    audio = asyncio.run(_collect_synthesis(client, text_chunks=["first chunk", "second chunk"]))

    assert audio == [b"audio-1"]
    assert connect_calls == [
        (
            "wss://example.test",
            {
                "additional_headers": {
                    "X-Api-Key": "ark-key",
                    "X-Api-Resource-Id": "seed-tts-2.0",
                    "X-Api-Connect-Id": "connect-1",
                    "X-Control-Require-Usage-Tokens-Return": "*",
                },
                "max_size": 10 * 1024 * 1024,
            },
        )
    ]
    call_names = [call[0] for call in calls]
    assert call_names == [
        "start_connection",
        "wait_for_event",
        "start_session",
        "wait_for_event",
        "task_request",
        "task_request",
        "finish_session",
        "receive_message",
        "receive_message",
        "receive_message",
        "finish_connection",
    ]
    task_requests = [call for call in calls if call[0] == "task_request"]
    assert [request[1]["req_params"]["text"] for request in task_requests] == [
        "first chunk",
        "second chunk",
    ]
    assert all(request[2] == "session-1" for request in task_requests)


def test_synthesize_failure_event_raises_and_attempts_cleanup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_uuids(monkeypatch)
    calls, _connect_calls = _patch_volcengine_session(
        monkeypatch,
        [
            protocol.Message(
                type=protocol.MsgType.FullServerResponse,
                flag=protocol.MsgTypeFlagBits.WithEvent,
                event=protocol.EventType.SessionFailed,
                payload=b'{"text":"secret speech"}',
            )
        ],
    )
    client = VolcengineTtsClient(BASE_CONFIG)

    with pytest.raises(RuntimeError, match="SessionFailed") as exc_info:
        asyncio.run(_collect_synthesis(client))

    assert "secret speech" not in str(exc_info.value)
    call_names = [call[0] for call in calls]
    assert "finish_session" in call_names
    assert call_names[-2:] == ["cancel_session", "finish_connection"]


def test_synthesize_error_message_includes_error_code_without_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_uuids(monkeypatch)
    calls, _connect_calls = _patch_volcengine_session(
        monkeypatch,
        [
            protocol.Message(
                type=protocol.MsgType.Error,
                error_code=429,
                payload=b'{"text":"secret speech"}',
            )
        ],
    )
    client = VolcengineTtsClient(BASE_CONFIG)

    with pytest.raises(RuntimeError, match="429") as exc_info:
        asyncio.run(_collect_synthesis(client))

    assert "secret speech" not in str(exc_info.value)
    assert [call[0] for call in calls][-2:] == ["cancel_session", "finish_connection"]


def test_synthesize_unexpected_message_raises_and_attempts_cleanup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_uuids(monkeypatch)
    calls, _connect_calls = _patch_volcengine_session(
        monkeypatch,
        [
            protocol.Message(
                type=protocol.MsgType.FrontEndResultServer,
                flag=protocol.MsgTypeFlagBits.WithEvent,
                event=protocol.EventType.TTSResponse,
                session_id="session-1",
                payload=b'{"text":"secret speech"}',
            )
        ],
    )
    client = VolcengineTtsClient(BASE_CONFIG)

    with pytest.raises(RuntimeError, match="Unexpected Volcengine TTS message") as exc_info:
        asyncio.run(_collect_synthesis(client))

    error_text = str(exc_info.value)
    assert "FrontEndResultServer" in error_text
    assert "secret speech" not in error_text
    assert [call[0] for call in calls][-2:] == ["cancel_session", "finish_connection"]


def test_synthesize_unavailable_config_raises_before_connecting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connect_called = False

    def connect(*_args: object, **_kwargs: object) -> None:
        nonlocal connect_called
        connect_called = True

    monkeypatch.setattr(tts.websockets, "connect", connect)
    client = VolcengineTtsClient(replace(BASE_CONFIG, resource_id=""))

    with pytest.raises(RuntimeError, match="not configured"):
        asyncio.run(_collect_synthesis(client))

    assert not connect_called


def test_synthesize_lifecycle_timeout_raises_runtime_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_uuids(monkeypatch)
    calls, _connect_calls = _patch_volcengine_session(monkeypatch, [])

    async def wait_forever(
        _websocket: object,
        _msg_type: protocol.MsgType,
        _event_type: protocol.EventType,
    ) -> None:
        await asyncio.Event().wait()

    monkeypatch.setattr(tts.protocol, "wait_for_event", wait_forever)
    monkeypatch.setattr(tts, "EVENT_TIMEOUT_SECONDS", 0.01, raising=False)
    client = VolcengineTtsClient(BASE_CONFIG)

    with pytest.raises(RuntimeError, match="Volcengine TTS timed out"):
        asyncio.run(asyncio.wait_for(_collect_synthesis(client), timeout=0.25))

    assert calls == [("start_connection",), ("finish_connection",)]


def test_synthesize_timeout_not_masked_by_websocket_context_close(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_uuids(monkeypatch)
    calls: list[tuple] = []

    class ContextCloseRaisesWebsocket:
        def __await__(self):
            async def _connect() -> "ContextCloseRaisesWebsocket":
                return self

            return _connect().__await__()

        async def __aenter__(self) -> "ContextCloseRaisesWebsocket":
            return self

        async def __aexit__(
            self,
            exc_type: object,
            exc_value: object,
            traceback: object,
        ) -> None:
            calls.append(("context_close",))
            raise RuntimeError("websocket close masked primary timeout")

        async def close(self) -> None:
            calls.append(("close",))
            await asyncio.Event().wait()

    def connect(_ws_url: str, **_kwargs: object) -> ContextCloseRaisesWebsocket:
        return ContextCloseRaisesWebsocket()

    async def start_connection(_websocket: object) -> None:
        calls.append(("start_connection",))

    async def wait_forever(
        _websocket: object,
        _msg_type: protocol.MsgType,
        _event_type: protocol.EventType,
    ) -> None:
        calls.append(("wait_for_event",))
        await asyncio.Event().wait()

    async def finish_connection(_websocket: object) -> None:
        calls.append(("finish_connection",))

    monkeypatch.setattr(tts.websockets, "connect", connect)
    monkeypatch.setattr(tts.protocol, "start_connection", start_connection)
    monkeypatch.setattr(tts.protocol, "wait_for_event", wait_forever)
    monkeypatch.setattr(tts.protocol, "finish_connection", finish_connection)
    monkeypatch.setattr(tts, "EVENT_TIMEOUT_SECONDS", 0.01, raising=False)
    client = VolcengineTtsClient(BASE_CONFIG)

    with pytest.raises(RuntimeError, match="Volcengine TTS timed out"):
        asyncio.run(asyncio.wait_for(_collect_synthesis(client), timeout=0.25))

    assert [call[0] for call in calls] == [
        "start_connection",
        "wait_for_event",
        "finish_connection",
        "close",
    ]


def test_synthesize_first_audio_timeout_raises_runtime_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_uuids(monkeypatch)
    calls, _connect_calls = _patch_volcengine_session(monkeypatch, [])

    async def receive_message_forever(_websocket: object) -> SimpleNamespace:
        calls.append(("receive_message",))
        await asyncio.Event().wait()
        raise AssertionError("unreachable")

    monkeypatch.setattr(tts.protocol, "receive_message", receive_message_forever)
    monkeypatch.setattr(tts, "FIRST_AUDIO_TIMEOUT_SECONDS", 0.01, raising=False)
    client = VolcengineTtsClient(BASE_CONFIG)

    with pytest.raises(RuntimeError, match="Volcengine TTS timed out"):
        asyncio.run(asyncio.wait_for(_collect_synthesis(client), timeout=0.25))

    call_names = [call[0] for call in calls]
    assert call_names[-3:] == ["receive_message", "cancel_session", "finish_connection"]


def test_synthesize_task_request_timeout_bounds_cleanup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_uuids(monkeypatch)
    calls, _connect_calls = _patch_volcengine_session(monkeypatch, [])

    async def task_request_hangs(
        _websocket: object,
        _payload: bytes,
        session_id: str,
    ) -> None:
        calls.append(("task_request", session_id))
        await asyncio.Event().wait()

    async def cancel_session_hangs(_websocket: object, session_id: str) -> None:
        calls.append(("cancel_session", session_id))
        await asyncio.Event().wait()

    async def finish_connection_hangs(_websocket: object) -> None:
        calls.append(("finish_connection",))
        await asyncio.Event().wait()

    monkeypatch.setattr(tts.protocol, "task_request", task_request_hangs)
    monkeypatch.setattr(tts.protocol, "cancel_session", cancel_session_hangs)
    monkeypatch.setattr(tts.protocol, "finish_connection", finish_connection_hangs)
    monkeypatch.setattr(tts, "EVENT_TIMEOUT_SECONDS", 0.01, raising=False)
    client = VolcengineTtsClient(BASE_CONFIG)

    with pytest.raises(RuntimeError, match="Volcengine TTS timed out"):
        asyncio.run(asyncio.wait_for(_collect_synthesis(client), timeout=0.25))

    call_names = [call[0] for call in calls]
    assert call_names[-3:] == ["task_request", "cancel_session", "finish_connection"]


def test_synthesize_audio_idle_timeout_bounds_cleanup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_uuids(monkeypatch)
    calls, _connect_calls = _patch_volcengine_session(monkeypatch, [])
    messages = iter(
        [
            _message(protocol.MsgType.AudioOnlyServer, payload=b"audio-1"),
        ]
    )

    async def receive_message_then_hang(_websocket: object) -> SimpleNamespace:
        calls.append(("receive_message",))
        try:
            return next(messages)
        except StopIteration:
            await asyncio.Event().wait()
            raise AssertionError("unreachable")

    async def cancel_session_hangs(_websocket: object, _session_id: str) -> None:
        calls.append(("cancel_session", _session_id))
        await asyncio.Event().wait()

    async def finish_connection_hangs(_websocket: object) -> None:
        calls.append(("finish_connection",))
        await asyncio.Event().wait()

    monkeypatch.setattr(tts.protocol, "receive_message", receive_message_then_hang)
    monkeypatch.setattr(tts.protocol, "cancel_session", cancel_session_hangs)
    monkeypatch.setattr(tts.protocol, "finish_connection", finish_connection_hangs)
    monkeypatch.setattr(tts, "AUDIO_IDLE_TIMEOUT_SECONDS", 0.01, raising=False)
    monkeypatch.setattr(tts, "EVENT_TIMEOUT_SECONDS", 0.01, raising=False)
    client = VolcengineTtsClient(BASE_CONFIG)

    with pytest.raises(RuntimeError, match="Volcengine TTS timed out"):
        asyncio.run(asyncio.wait_for(_collect_synthesis(client), timeout=0.25))

    call_names = [call[0] for call in calls]
    assert call_names[-4:] == [
        "receive_message",
        "receive_message",
        "cancel_session",
        "finish_connection",
    ]


def test_protocol_message_str_redacts_payload_text() -> None:
    message = protocol.Message(
        type=protocol.MsgType.FullClientRequest,
        flag=protocol.MsgTypeFlagBits.WithEvent,
        event=protocol.EventType.TaskRequest,
        session_id="session-1",
        payload=b'{"text":"secret speech"}',
    )

    rendered = str(message)

    assert "secret speech" not in rendered
    assert "session-1" in rendered
    assert "TaskRequest" in rendered
    assert "PayloadSize:" in rendered


def test_protocol_receive_message_redacts_unexpected_text_frames(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.ERROR, logger=protocol.__name__)
    websocket = FakeWebsocket('{"text":"secret speech"}')

    with pytest.raises(ValueError, match="length=24") as exc_info:
        asyncio.run(protocol.receive_message(websocket))

    assert "text frame" in str(exc_info.value)
    assert "secret speech" not in str(exc_info.value)
    assert "secret speech" not in caplog.text
    assert "length=24" in caplog.text


def test_protocol_receive_message_redacts_malformed_binary_trailing_bytes(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.ERROR, logger=protocol.__name__)
    message = protocol.Message(
        type=protocol.MsgType.FullServerResponse,
        flag=protocol.MsgTypeFlagBits.NoSeq,
        payload=b"{}",
    )
    trailing_bytes = b'{"text":"secret speech"}'
    websocket = FakeWebsocket(message.marshal() + trailing_bytes)

    with pytest.raises(ValueError, match=f"length={len(trailing_bytes)}") as exc_info:
        asyncio.run(protocol.receive_message(websocket))

    assert "Unexpected data after message" in str(exc_info.value)
    assert "secret speech" not in str(exc_info.value)
    assert repr(trailing_bytes) not in str(exc_info.value)
    assert "secret speech" not in caplog.text
    assert repr(trailing_bytes) not in caplog.text


def test_protocol_wait_for_event_failure_includes_event_without_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def receive_message(_websocket: object) -> protocol.Message:
        return protocol.Message(
            type=protocol.MsgType.FullServerResponse,
            flag=protocol.MsgTypeFlagBits.WithEvent,
            event=protocol.EventType.ConnectionFailed,
            payload=b'{"text":"secret speech"}',
        )

    monkeypatch.setattr(protocol, "receive_message", receive_message)

    with pytest.raises(RuntimeError, match="ConnectionFailed") as exc_info:
        asyncio.run(
            protocol.wait_for_event(
                object(),
                protocol.MsgType.FullServerResponse,
                protocol.EventType.ConnectionStarted,
            )
        )

    assert "secret speech" not in str(exc_info.value)


def test_protocol_wait_for_event_error_includes_code_without_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def receive_message(_websocket: object) -> protocol.Message:
        return protocol.Message(
            type=protocol.MsgType.Error,
            error_code=503,
            payload=b'{"text":"secret speech"}',
        )

    monkeypatch.setattr(protocol, "receive_message", receive_message)

    with pytest.raises(RuntimeError, match="503") as exc_info:
        asyncio.run(
            protocol.wait_for_event(
                object(),
                protocol.MsgType.FullServerResponse,
                protocol.EventType.ConnectionStarted,
            )
        )

    assert "secret speech" not in str(exc_info.value)
