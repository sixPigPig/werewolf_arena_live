from app.werewolf.volcengine_tts import (
    VolcengineTtsConfig,
    build_tts_headers,
    build_tts_request,
    mime_type_for_format,
)


def test_build_tts_headers_uses_connect_id_and_resource_id() -> None:
    config = VolcengineTtsConfig(
        enabled=True,
        api_key="ark-key",
        resource_id="seed-tts-2.0",
        ws_url="wss://example.test",
        player_speaker="player",
        judge_speaker="judge",
        audio_format="mp3",
        sample_rate=24000,
    )

    headers = build_tts_headers(config, connect_id="connect-1")

    assert headers == {
        "X-Api-Key": "ark-key",
        "X-Api-Resource-Id": "seed-tts-2.0",
        "X-Api-Connect-Id": "connect-1",
        "X-Control-Require-Usage-Tokens-Return": "*",
    }


def test_build_tts_request_contains_speaker_text_and_audio_params() -> None:
    request = build_tts_request(
        speaker="player",
        text="我先发言。",
        audio_format="mp3",
        sample_rate=24000,
    )

    assert request == {
        "req_params": {
            "speaker": "player",
            "text": "我先发言。",
            "audio_params": {
                "format": "mp3",
                "sample_rate": 24000,
                "enable_timestamp": False,
            },
        }
    }


def test_mime_type_for_supported_formats() -> None:
    assert mime_type_for_format("mp3") == "audio/mpeg"
    assert mime_type_for_format("wav") == "audio/wav"
    assert mime_type_for_format("pcm") == "audio/L16"
