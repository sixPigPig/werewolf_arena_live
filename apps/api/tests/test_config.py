import pytest
from pydantic import ValidationError

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


def test_settings_parses_public_cors_origins_independently(monkeypatch) -> None:
    monkeypatch.setenv(
        "PUBLIC_CORS_ORIGINS",
        "https://mobile.example,https://mobile-preview.example",
    )

    settings = Settings(_env_file=None)

    assert settings.public_cors_origins == [
        "https://mobile.example",
        "https://mobile-preview.example",
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


def test_settings_disable_admin_development_auth_by_default() -> None:
    settings = Settings(_env_file=None)

    assert settings.admin_dev_auth_enabled is False
    assert settings.admin_session_cookie_secure is True
    assert settings.public_session_cookie_name == "werewolf_public_session"
    assert settings.public_session_cookie_secure is True
    assert settings.public_session_ttl_seconds == 30 * 24 * 60 * 60
    assert "http://localhost:5174" in settings.cors_origins
    assert "http://127.0.0.1:5174" in settings.cors_origins
    assert settings.public_cors_origins == [
        "http://localhost:5174",
        "http://127.0.0.1:5174",
    ]
    assert "http://localhost:5175" in settings.cors_origins
    assert "http://127.0.0.1:5175" in settings.cors_origins
    assert settings.legacy_player_profile_content_writes_enabled is False
    assert settings.legacy_player_profile_favorite_writes_enabled is False


def test_settings_reject_legacy_player_profile_content_writes_in_production(
    monkeypatch,
) -> None:
    monkeypatch.setenv("APP_ENVIRONMENT", "production")
    monkeypatch.setenv("LEGACY_PLAYER_PROFILE_CONTENT_WRITES_ENABLED", "true")

    with pytest.raises(ValidationError, match="cannot be enabled in production"):
        Settings(_env_file=None)


def test_settings_reject_legacy_player_profile_favorite_writes_in_production(
    monkeypatch,
) -> None:
    monkeypatch.setenv("APP_ENVIRONMENT", "production")
    monkeypatch.setenv("LEGACY_PLAYER_PROFILE_FAVORITE_WRITES_ENABLED", "true")

    with pytest.raises(ValidationError, match="cannot be enabled in production"):
        Settings(_env_file=None)


def test_settings_reject_development_auth_in_production(monkeypatch) -> None:
    monkeypatch.setenv("APP_ENVIRONMENT", "production")
    monkeypatch.setenv("ADMIN_DEV_AUTH_ENABLED", "true")

    with pytest.raises(ValidationError, match="cannot be enabled in production"):
        Settings(_env_file=None)


def test_settings_require_secure_admin_cookie_in_production(monkeypatch) -> None:
    monkeypatch.setenv("APP_ENVIRONMENT", "production")
    monkeypatch.setenv("ADMIN_SESSION_COOKIE_SECURE", "false")

    with pytest.raises(ValidationError, match="must be enabled in production"):
        Settings(_env_file=None)


def test_settings_require_secure_public_cookie_in_production(monkeypatch) -> None:
    monkeypatch.setenv("APP_ENVIRONMENT", "production")
    monkeypatch.setenv("PUBLIC_SESSION_COOKIE_SECURE", "false")

    with pytest.raises(ValidationError, match="must be enabled in production"):
        Settings(_env_file=None)


def test_settings_reject_wildcard_credentialed_cors_in_production(monkeypatch) -> None:
    monkeypatch.setenv("APP_ENVIRONMENT", "production")
    monkeypatch.setenv("CORS_ORIGINS", "*")

    with pytest.raises(ValidationError, match="cannot contain '\\*' in production"):
        Settings(_env_file=None)


def test_settings_reject_public_cors_wildcard_in_production(monkeypatch) -> None:
    monkeypatch.setenv("APP_ENVIRONMENT", "production")
    monkeypatch.setenv("PUBLIC_CORS_ORIGINS", "*")

    with pytest.raises(ValidationError, match="PUBLIC_CORS_ORIGINS cannot contain"):
        Settings(_env_file=None)
