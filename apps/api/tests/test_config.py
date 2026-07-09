from app.core.config import Settings


def test_settings_accepts_plain_string_cors_origins_env(monkeypatch) -> None:
    monkeypatch.setenv(
        "CORS_ORIGINS",
        "http://localhost:5173,http://127.0.0.1:5173",
    )

    settings = Settings(_env_file=None)

    assert settings.cors_origins == [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ]


def test_settings_accepts_json_list_cors_origins_env(monkeypatch) -> None:
    monkeypatch.setenv(
        "CORS_ORIGINS",
        '["http://localhost:5173", "http://127.0.0.1:5173"]',
    )

    settings = Settings(_env_file=None)

    assert settings.cors_origins == [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ]


def test_settings_ignores_deepseek_env_values(tmp_path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "APP_NAME=Werewolf API\n"
        "DEEPSEEK_API_KEY=test-key\n"
        "DEEPSEEK_BASE_URL=https://api.deepseek.com\n"
        "DEEPSEEK_MODEL=deepseek-v4-flash\n",
        encoding="utf-8",
    )

    settings = Settings(_env_file=env_file)

    assert settings.app_name == "Werewolf API"


def test_settings_defaults_disable_tts() -> None:
    settings = Settings(_env_file=None)

    assert settings.ark_tts_enabled is False
    assert settings.ark_tts_api_key == ""
    assert settings.ark_tts_resource_id == "seed-tts-2.0"
    assert settings.ark_tts_ws_url == "wss://openspeech.bytedance.com/api/v3/plan/tts/bidirection"
    assert settings.ark_tts_audio_format == "pcm"
    assert settings.ark_tts_sample_rate == 24000
    assert settings.ark_tts_judge_asset_audio_format == "mp3"
    assert settings.ark_tts_judge_asset_sample_rate == 24000


def test_settings_reads_tts_env_values(monkeypatch) -> None:
    monkeypatch.setenv("ARK_TTS_ENABLED", "true")
    monkeypatch.setenv("ARK_TTS_API_KEY", "ark-test-key")
    monkeypatch.setenv("ARK_TTS_PLAYER_SPEAKER", "player-speaker")
    monkeypatch.setenv("ARK_TTS_JUDGE_SPEAKER", "judge-speaker")
    monkeypatch.setenv("ARK_TTS_SAMPLE_RATE", "16000")
    monkeypatch.setenv("ARK_TTS_JUDGE_ASSET_AUDIO_FORMAT", "wav")
    monkeypatch.setenv("ARK_TTS_JUDGE_ASSET_SAMPLE_RATE", "48000")

    settings = Settings(_env_file=None)

    assert settings.ark_tts_enabled is True
    assert settings.ark_tts_api_key == "ark-test-key"
    assert settings.ark_tts_player_speaker == "player-speaker"
    assert settings.ark_tts_judge_speaker == "judge-speaker"
    assert settings.ark_tts_sample_rate == 16000
    assert settings.ark_tts_judge_asset_audio_format == "wav"
    assert settings.ark_tts_judge_asset_sample_rate == 48000
