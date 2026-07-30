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

    assert settings.rule_set_catalog_source == "database"
    assert settings.ark_tts_enabled is False
    assert settings.ark_tts_api_key == ""
    assert settings.ark_tts_resource_id == "seed-tts-2.0"
    assert settings.ark_tts_ws_url == "wss://openspeech.bytedance.com/api/v3/plan/tts/bidirection"
    assert settings.ark_tts_audio_format == "pcm"
    assert settings.ark_tts_sample_rate == 24000
    assert settings.ark_tts_judge_asset_audio_format == "mp3"
    assert settings.ark_tts_judge_asset_sample_rate == 24000
    assert settings.live_v2_model_first_token_seconds == 20.0
    assert settings.live_v2_model_attempt_total_seconds == 60.0
    assert settings.live_v2_model_action_total_seconds == 90.0
    assert settings.live_v2_model_max_attempts == 2
    assert settings.live_v2_model_retry_base_delay_seconds == 0.3
    assert settings.live_v2_model_retry_jitter_seconds == 0.3
    assert settings.judge_voice_worker_poll_seconds == 2.0
    assert settings.judge_voice_worker_heartbeat_seconds == 10.0
    assert settings.judge_voice_worker_probe_max_age_seconds == 45.0
    assert settings.live_run_lease_seconds == 15.0
    assert settings.live_run_heartbeat_seconds == 3.0
    assert settings.live_run_event_poll_seconds == 0.25
    assert settings.live_run_reaper_poll_seconds == 5.0
    assert settings.live_run_reaper_stale_grace_seconds == 30.0
    assert settings.live_run_reaper_backoff_seconds == 30.0
    assert settings.live_run_reaper_max_attempts == 3
    assert settings.live_run_reaper_heartbeat_seconds == 10.0
    assert settings.live_run_reaper_probe_max_age_seconds == 45.0


def test_settings_accepts_legacy_v2_attempt_budget_env(monkeypatch) -> None:
    monkeypatch.delenv("LIVE_V2_MODEL_ATTEMPT_TOTAL_SECONDS", raising=False)
    monkeypatch.setenv("LIVE_V2_MODEL_TOTAL_SECONDS", "17")
    monkeypatch.setenv("LIVE_V2_MODEL_ACTION_TOTAL_SECONDS", "20")

    settings = Settings(_env_file=None)

    assert settings.live_v2_model_attempt_total_seconds == 17.0
    assert settings.live_v2_model_action_total_seconds == 20.0


def test_settings_rejects_v2_action_budget_shorter_than_attempt(monkeypatch) -> None:
    monkeypatch.setenv("LIVE_V2_MODEL_ATTEMPT_TOTAL_SECONDS", "31")
    monkeypatch.setenv("LIVE_V2_MODEL_ACTION_TOTAL_SECONDS", "30")

    with pytest.raises(ValidationError, match="ACTION_TOTAL_SECONDS"):
        Settings(_env_file=None)


def test_settings_accepts_static_rule_catalog_only_for_staging(monkeypatch) -> None:
    monkeypatch.setenv("APP_ENVIRONMENT", "staging")
    monkeypatch.setenv("RULE_SET_CATALOG_SOURCE", "static")

    settings = Settings(_env_file=None)

    assert settings.rule_set_catalog_source == "static"


@pytest.mark.parametrize("environment", ["development", "test"])
def test_settings_rejects_static_rule_catalog_outside_staging(
    environment: str,
) -> None:
    with pytest.raises(ValidationError, match="RULE_SET_CATALOG_SOURCE"):
        Settings(
            _env_file=None,
            app_environment=environment,
            rule_set_catalog_source="static",
        )


def test_settings_rejects_static_rule_catalog_in_safe_production() -> None:
    with pytest.raises(ValidationError, match="RULE_SET_CATALOG_SOURCE"):
        Settings(
            _env_file=None,
            app_environment="production",
            rule_set_catalog_source="static",
            cors_origins=["https://admin.example"],
            public_cors_origins=["https://mobile.example"],
            admin_oidc_enabled=True,
            admin_oidc_issuer_url="https://identity.example",
            admin_oidc_client_id="admin-web",
            admin_oidc_client_secret="client-secret",
            admin_oidc_redirect_uri=("https://api.example/api/v1/admin/oidc/callback"),
            admin_oidc_web_base_url="https://admin.example",
        )


def test_settings_rejects_unknown_rule_catalog_source() -> None:
    with pytest.raises(ValidationError, match="rule_set_catalog_source"):
        Settings(_env_file=None, rule_set_catalog_source="fallback")


def test_settings_rejects_live_run_heartbeat_not_shorter_than_lease(
    monkeypatch,
) -> None:
    monkeypatch.setenv("LIVE_RUN_LEASE_SECONDS", "10")
    monkeypatch.setenv("LIVE_RUN_HEARTBEAT_SECONDS", "10")

    with pytest.raises(ValidationError, match="must be shorter"):
        Settings(_env_file=None)


def test_settings_rejects_reaper_heartbeat_not_shorter_than_probe_window(
    monkeypatch,
) -> None:
    monkeypatch.setenv("LIVE_RUN_REAPER_HEARTBEAT_SECONDS", "45")
    monkeypatch.setenv("LIVE_RUN_REAPER_PROBE_MAX_AGE_SECONDS", "45")

    with pytest.raises(ValidationError, match="REAPER_HEARTBEAT_SECONDS"):
        Settings(_env_file=None)


def test_settings_rejects_voice_worker_heartbeat_not_shorter_than_probe_window(
    monkeypatch,
) -> None:
    monkeypatch.setenv("JUDGE_VOICE_WORKER_HEARTBEAT_SECONDS", "45")
    monkeypatch.setenv("JUDGE_VOICE_WORKER_PROBE_MAX_AGE_SECONDS", "45")

    with pytest.raises(ValidationError, match="JUDGE_VOICE_WORKER_HEARTBEAT_SECONDS"):
        Settings(_env_file=None)


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
    assert settings.legacy_judge_voice_generation_enabled is False
    assert settings.werewolf_speech_quality_retry_enabled is True
    assert settings.werewolf_action_budgets_enabled is True


def test_settings_reject_legacy_player_profile_content_writes_in_production(
    monkeypatch,
) -> None:
    monkeypatch.setenv("APP_ENVIRONMENT", "production")
    monkeypatch.setenv("LEGACY_PLAYER_PROFILE_CONTENT_WRITES_ENABLED", "true")

    with pytest.raises(ValidationError, match="cannot be enabled in production"):
        Settings(_env_file=None)


def test_settings_reject_legacy_judge_voice_generation_in_production(
    monkeypatch,
) -> None:
    monkeypatch.setenv("APP_ENVIRONMENT", "production")
    monkeypatch.setenv("LEGACY_JUDGE_VOICE_GENERATION_ENABLED", "true")

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


def test_settings_require_distinct_session_cookie_names(monkeypatch) -> None:
    monkeypatch.setenv("ADMIN_SESSION_COOKIE_NAME", "shared_session")
    monkeypatch.setenv("PUBLIC_SESSION_COOKIE_NAME", "shared_session")

    with pytest.raises(ValidationError, match="cookie names must be different"):
        Settings(_env_file=None)


def test_settings_reject_public_cookie_colliding_with_oidc_binding(monkeypatch) -> None:
    monkeypatch.setenv("ADMIN_SESSION_COOKIE_NAME", "admin_session")
    monkeypatch.setenv("PUBLIC_SESSION_COOKIE_NAME", "admin_session_oidc")

    with pytest.raises(ValidationError, match="cookie names must be different"):
        Settings(_env_file=None)


def test_settings_require_https_cors_origins_in_production(monkeypatch) -> None:
    monkeypatch.setenv("APP_ENVIRONMENT", "production")
    monkeypatch.setenv("CORS_ORIGINS", "http://admin.example")
    monkeypatch.setenv("PUBLIC_CORS_ORIGINS", "https://mobile.example")

    with pytest.raises(ValidationError, match="CORS_ORIGINS must use HTTPS"):
        Settings(_env_file=None)


def test_settings_accept_safe_production_configuration(monkeypatch) -> None:
    monkeypatch.setenv("APP_ENVIRONMENT", "production")
    monkeypatch.setenv("CORS_ORIGINS", "https://admin.example,https://mobile.example")
    monkeypatch.setenv("PUBLIC_CORS_ORIGINS", "https://mobile.example")
    monkeypatch.setenv("ADMIN_OIDC_ENABLED", "true")
    monkeypatch.setenv("ADMIN_OIDC_ISSUER_URL", "https://identity.example")
    monkeypatch.setenv("ADMIN_OIDC_CLIENT_ID", "admin-web")
    monkeypatch.setenv("ADMIN_OIDC_CLIENT_SECRET", "client-secret")
    monkeypatch.setenv(
        "ADMIN_OIDC_REDIRECT_URI",
        "https://api.example/api/v1/admin/oidc/callback",
    )
    monkeypatch.setenv("ADMIN_OIDC_WEB_BASE_URL", "https://admin.example")

    settings = Settings(_env_file=None)

    assert settings.app_environment == "production"


def test_settings_require_oidc_in_production(monkeypatch) -> None:
    monkeypatch.setenv("APP_ENVIRONMENT", "production")
    monkeypatch.setenv("CORS_ORIGINS", "https://admin.example")
    monkeypatch.setenv("PUBLIC_CORS_ORIGINS", "https://mobile.example")

    with pytest.raises(ValidationError, match="ADMIN_OIDC_ENABLED"):
        Settings(_env_file=None)


def test_settings_require_complete_oidc_configuration(monkeypatch) -> None:
    monkeypatch.setenv("ADMIN_OIDC_ENABLED", "true")

    with pytest.raises(ValidationError, match="ADMIN_OIDC_ISSUER_URL"):
        Settings(_env_file=None)
