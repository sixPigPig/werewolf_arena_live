import json
from functools import lru_cache
from typing import Annotated, Literal

from pydantic import AliasChoices, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = "Python React Web API"
    app_environment: Literal["development", "test", "staging", "production"] = "development"
    rule_set_catalog_source: Literal["static", "database"] = "database"
    api_v1_prefix: str = "/api/v1"
    cors_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: [
            "http://localhost:5174",
            "http://127.0.0.1:5174",
            "http://localhost:5175",
            "http://127.0.0.1:5175",
        ]
    )
    public_cors_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: [
            "http://localhost:5174",
            "http://127.0.0.1:5174",
        ]
    )
    database_url: str = "postgresql+psycopg://postgres:postgres@localhost:5432/app"
    admin_dev_auth_enabled: bool = False
    admin_dev_auth_email: str = "admin@example.test"
    admin_dev_auth_display_name: str = "Development Admin"
    admin_dev_auth_role: Literal["viewer", "content_editor", "operator", "super_admin"] = (
        "super_admin"
    )
    admin_session_cookie_name: str = "werewolf_admin_session"
    admin_session_cookie_secure: bool = True
    admin_session_ttl_seconds: int = Field(default=8 * 60 * 60, ge=300, le=7 * 24 * 60 * 60)
    admin_oidc_enabled: bool = False
    admin_oidc_issuer_url: str = ""
    admin_oidc_client_id: str = ""
    admin_oidc_client_secret: str = ""
    admin_oidc_redirect_uri: str = "http://127.0.0.1:8000/api/v1/admin/oidc/callback"
    admin_oidc_web_base_url: str = "http://127.0.0.1:5175"
    admin_oidc_client_auth_method: Literal["client_secret_basic", "client_secret_post"] = (
        "client_secret_basic"
    )
    admin_oidc_login_ttl_seconds: int = Field(default=600, ge=120, le=1800)
    public_session_cookie_name: str = "werewolf_public_session"
    public_session_cookie_secure: bool = True
    public_session_ttl_seconds: int = Field(
        default=30 * 24 * 60 * 60,
        ge=300,
        le=365 * 24 * 60 * 60,
    )
    legacy_player_profile_content_writes_enabled: bool = False
    legacy_judge_voice_generation_enabled: bool = False
    werewolf_lineup_quality_mode: Literal["observe", "repair", "enforce"] = "repair"
    werewolf_speech_quality_retry_enabled: bool = True
    werewolf_action_budgets_enabled: bool = True
    werewolf_required_action_request_seconds: float = Field(default=12.0, ge=0.1, le=300)
    werewolf_required_action_total_seconds: float = Field(default=15.0, ge=0.1, le=300)
    werewolf_required_action_batch_seconds: float = Field(default=15.0, ge=0.1, le=300)
    werewolf_optional_action_request_seconds: float = Field(default=10.0, ge=0.1, le=300)
    werewolf_optional_action_total_seconds: float = Field(default=12.0, ge=0.1, le=300)
    werewolf_optional_action_batch_seconds: float = Field(default=12.0, ge=0.1, le=300)
    werewolf_public_speech_first_token_seconds: float = Field(default=10.0, ge=0.1, le=300)
    werewolf_public_speech_total_seconds: float = Field(default=45.0, ge=0.1, le=300)
    werewolf_private_text_first_token_seconds: float = Field(default=8.0, ge=0.1, le=300)
    werewolf_private_text_total_seconds: float = Field(default=25.0, ge=0.1, le=300)
    werewolf_private_text_batch_seconds: float = Field(default=25.0, ge=0.1, le=300)
    werewolf_logs_dir: str = "logs"
    model_catalog_agent_plan: Literal[
        "agent-plan",
        "agent-plan-team",
        "coding-plan",
        "coding-plan-team",
    ] = "agent-plan"
    model_catalog_arkcli_path: str = "arkcli"
    model_catalog_sync_timeout_seconds: float = Field(default=20.0, ge=1.0, le=120.0)
    model_catalog_deepseek_timeout_seconds: float = Field(default=10.0, ge=1.0, le=60.0)
    ark_tts_enabled: bool = False
    ark_tts_api_key: str = ""
    ark_tts_resource_id: str = "seed-tts-2.0"
    ark_tts_ws_url: str = "wss://openspeech.bytedance.com/api/v3/plan/tts/bidirection"
    ark_tts_player_speaker: str = "zh_female_gaolengyujie_uranus_bigtts"
    ark_tts_judge_speaker: str = "zh_female_vv_uranus_bigtts"
    ark_tts_audio_format: str = "pcm"
    ark_tts_sample_rate: int = 24000
    ark_tts_judge_asset_audio_format: str = "mp3"
    ark_tts_judge_asset_sample_rate: int = 24000
    live_v2_agent_plan_api_key: str = Field(
        default="",
        validation_alias=AliasChoices(
            "LIVE_V2_AGENT_PLAN_API_KEY",
            "ARK_AGENT_PLAN_API_KEY",
            "ARK_API_KEY",
        ),
    )
    live_v2_agent_plan_base_url: str = Field(
        default="https://ark.cn-beijing.volces.com/api/plan/v3",
        validation_alias=AliasChoices(
            "LIVE_V2_AGENT_PLAN_BASE_URL",
            "ARK_AGENT_PLAN_BASE_URL",
        ),
    )
    live_v2_ark_api_key: str = Field(
        default="",
        validation_alias=AliasChoices(
            "LIVE_V2_ARK_API_KEY",
            "ARK_STANDARD_API_KEY",
        ),
    )
    live_v2_ark_base_url: str = Field(
        default="https://ark.cn-beijing.volces.com/api/v3",
        validation_alias=AliasChoices(
            "LIVE_V2_ARK_BASE_URL",
            "ARK_STANDARD_BASE_URL",
        ),
    )
    live_v2_ark_models: str = Field(
        default="",
        validation_alias=AliasChoices(
            "LIVE_V2_ARK_MODELS",
            "ARK_STANDARD_MODELS",
        ),
    )
    live_v2_deepseek_api_key: str = Field(
        default="",
        validation_alias=AliasChoices(
            "LIVE_V2_DEEPSEEK_API_KEY",
            "DEEPSEEK_API_KEY",
        ),
    )
    live_v2_deepseek_base_url: str = Field(
        default="https://api.deepseek.com",
        validation_alias=AliasChoices(
            "LIVE_V2_DEEPSEEK_BASE_URL",
            "DEEPSEEK_BASE_URL",
        ),
    )
    live_v2_agent_plan_max_in_flight: int = Field(default=3, ge=1, le=64)
    live_v2_ark_max_in_flight: int = Field(default=3, ge=1, le=1024)
    live_v2_deepseek_max_in_flight: int = Field(default=32, ge=1, le=2500)
    live_v2_agent_plan_supports_strict_json_schema: bool = False
    live_v2_ark_supports_strict_json_schema: bool = False
    live_v2_deepseek_supports_strict_json_schema: bool = False
    live_v2_model_first_token_seconds: float = Field(default=120.0, ge=0.1, le=600.0)
    live_v2_model_stream_idle_seconds: float = Field(default=90.0, ge=0.1, le=600.0)
    live_v2_model_attempt_total_seconds: float = Field(
        default=300.0,
        ge=0.1,
        le=900.0,
        validation_alias=AliasChoices(
            "LIVE_V2_MODEL_ATTEMPT_TOTAL_SECONDS",
            "LIVE_V2_MODEL_TOTAL_SECONDS",
        ),
    )
    live_v2_model_action_total_seconds: float = Field(default=620.0, ge=0.1, le=1800.0)
    live_v2_model_max_attempts: int = Field(default=3, ge=1, le=3)
    live_v2_model_retry_base_delay_seconds: float = Field(default=0.5, ge=0.0, le=5.0)
    live_v2_model_retry_jitter_seconds: float = Field(default=0.25, ge=0.0, le=5.0)
    live_v2_tts_enabled: bool = Field(
        default=False,
        validation_alias=AliasChoices("LIVE_V2_TTS_ENABLED", "ARK_TTS_ENABLED"),
    )
    live_v2_tts_api_key: str = Field(
        default="",
        validation_alias=AliasChoices("LIVE_V2_TTS_API_KEY", "ARK_TTS_API_KEY"),
    )
    live_v2_tts_resource_id: str = Field(
        default="seed-tts-2.0",
        validation_alias=AliasChoices("LIVE_V2_TTS_RESOURCE_ID", "ARK_TTS_RESOURCE_ID"),
    )
    live_v2_tts_ws_url: str = Field(
        default="wss://openspeech.bytedance.com/api/v3/plan/tts/bidirection",
        validation_alias=AliasChoices("LIVE_V2_TTS_WS_URL", "ARK_TTS_WS_URL"),
    )
    live_v2_tts_judge_speaker: str = Field(
        default="zh_female_vv_uranus_bigtts",
        validation_alias=AliasChoices(
            "LIVE_V2_TTS_JUDGE_SPEAKER",
            "ARK_TTS_JUDGE_SPEAKER",
        ),
    )
    live_v2_tts_sample_rate: int = Field(
        default=24000,
        ge=8000,
        le=48000,
        validation_alias=AliasChoices("LIVE_V2_TTS_SAMPLE_RATE", "ARK_TTS_SAMPLE_RATE"),
    )
    live_v2_tts_first_chunk_seconds: float = Field(default=12.0, ge=0.1, le=120.0)
    live_v2_tts_idle_seconds: float = Field(default=8.0, ge=0.1, le=120.0)
    live_v2_voice_storage_dir: str = "data/live-v2/voices"
    judge_voice_worker_poll_seconds: float = Field(default=2.0, ge=0.25, le=60.0)
    judge_voice_worker_heartbeat_seconds: float = Field(default=10.0, ge=1.0, le=60.0)
    judge_voice_worker_probe_max_age_seconds: float = Field(default=45.0, ge=5.0, le=300.0)
    live_voice_materializer_poll_seconds: float = Field(default=0.5, ge=0.1, le=60.0)
    live_voice_materializer_lease_seconds: float = Field(default=120.0, ge=10.0, le=600.0)
    live_voice_materializer_max_attempts: int = Field(default=4, ge=1, le=10)
    live_voice_materializer_backoff_seconds: float = Field(default=5.0, ge=1.0, le=3600.0)
    live_voice_materializer_heartbeat_seconds: float = Field(default=10.0, ge=1.0, le=60.0)
    live_voice_materializer_probe_max_age_seconds: float = Field(default=45.0, ge=5.0, le=300.0)
    quality_evaluation_enabled: bool = False
    quality_evaluation_version: str = "p3-v1"
    quality_evaluation_hmac_key: str = ""
    quality_evaluation_poll_seconds: float = Field(default=0.5, ge=0.1, le=60.0)
    quality_evaluation_lease_seconds: float = Field(default=120.0, ge=10.0, le=600.0)
    quality_evaluation_max_attempts: int = Field(default=5, ge=1, le=10)
    quality_evaluation_backoff_seconds: float = Field(default=5.0, ge=1.0, le=3600.0)
    quality_evaluation_heartbeat_seconds: float = Field(default=10.0, ge=1.0, le=60.0)
    quality_evaluation_probe_max_age_seconds: float = Field(default=45.0, ge=5.0, le=300.0)
    live_run_lease_seconds: float = Field(default=15.0, ge=5.0, le=120.0)
    live_run_heartbeat_seconds: float = Field(default=3.0, ge=0.5, le=30.0)
    live_run_event_poll_seconds: float = Field(default=0.25, ge=0.05, le=5.0)
    live_run_reaper_poll_seconds: float = Field(default=5.0, ge=1.0, le=60.0)
    live_run_reaper_stale_grace_seconds: float = Field(default=30.0, ge=0.0, le=600.0)
    live_run_reaper_backoff_seconds: float = Field(default=30.0, ge=5.0, le=3600.0)
    live_run_reaper_max_attempts: int = Field(default=3, ge=1, le=10)
    live_run_reaper_heartbeat_seconds: float = Field(default=10.0, ge=1.0, le=60.0)
    live_run_reaper_probe_max_age_seconds: float = Field(default=45.0, ge=5.0, le=300.0)

    @field_validator("cors_origins", "public_cors_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, value: str | list[str]) -> list[str]:
        if isinstance(value, str):
            stripped_value = value.strip()
            if stripped_value.startswith("["):
                return json.loads(stripped_value)

            return [origin.strip() for origin in value.split(",") if origin.strip()]

        return value

    @model_validator(mode="after")
    def enforce_admin_production_safety(self) -> "Settings":
        if self.rule_set_catalog_source == "static" and self.app_environment != "staging":
            raise ValueError("RULE_SET_CATALOG_SOURCE=static is allowed only in staging")
        if self.live_v2_model_action_total_seconds < self.live_v2_model_attempt_total_seconds:
            raise ValueError(
                "LIVE_V2_MODEL_ACTION_TOTAL_SECONDS must be at least "
                "LIVE_V2_MODEL_ATTEMPT_TOTAL_SECONDS"
            )
        if self.live_run_heartbeat_seconds >= self.live_run_lease_seconds:
            raise ValueError(
                "LIVE_RUN_HEARTBEAT_SECONDS must be shorter than LIVE_RUN_LEASE_SECONDS"
            )
        if self.live_run_reaper_heartbeat_seconds >= self.live_run_reaper_probe_max_age_seconds:
            raise ValueError(
                "LIVE_RUN_REAPER_HEARTBEAT_SECONDS must be shorter than "
                "LIVE_RUN_REAPER_PROBE_MAX_AGE_SECONDS"
            )
        if (
            self.judge_voice_worker_heartbeat_seconds
            >= self.judge_voice_worker_probe_max_age_seconds
        ):
            raise ValueError(
                "JUDGE_VOICE_WORKER_HEARTBEAT_SECONDS must be shorter than "
                "JUDGE_VOICE_WORKER_PROBE_MAX_AGE_SECONDS"
            )
        if (
            self.live_voice_materializer_heartbeat_seconds
            >= self.live_voice_materializer_probe_max_age_seconds
        ):
            raise ValueError(
                "LIVE_VOICE_MATERIALIZER_HEARTBEAT_SECONDS must be shorter than "
                "LIVE_VOICE_MATERIALIZER_PROBE_MAX_AGE_SECONDS"
            )
        if (
            self.live_voice_materializer_heartbeat_seconds
            >= self.live_voice_materializer_lease_seconds
        ):
            raise ValueError(
                "LIVE_VOICE_MATERIALIZER_HEARTBEAT_SECONDS must be shorter than "
                "LIVE_VOICE_MATERIALIZER_LEASE_SECONDS"
            )
        if self.quality_evaluation_heartbeat_seconds >= self.quality_evaluation_lease_seconds:
            raise ValueError(
                "QUALITY_EVALUATION_HEARTBEAT_SECONDS must be shorter than "
                "QUALITY_EVALUATION_LEASE_SECONDS"
            )
        if (
            self.quality_evaluation_heartbeat_seconds
            >= self.quality_evaluation_probe_max_age_seconds
        ):
            raise ValueError(
                "QUALITY_EVALUATION_HEARTBEAT_SECONDS must be shorter than "
                "QUALITY_EVALUATION_PROBE_MAX_AGE_SECONDS"
            )
        if self.quality_evaluation_enabled and not self.quality_evaluation_hmac_key.strip():
            raise ValueError(
                "QUALITY_EVALUATION_HMAC_KEY is required when quality evaluation is enabled"
            )
        auth_cookie_names = {
            self.admin_session_cookie_name,
            f"{self.admin_session_cookie_name}_csrf",
            f"{self.admin_session_cookie_name}_oidc",
            self.public_session_cookie_name,
            f"{self.public_session_cookie_name}_csrf",
        }
        if len(auth_cookie_names) != 5:
            raise ValueError("admin and public session cookie names must be different")
        if self.app_environment == "production" and self.admin_dev_auth_enabled:
            raise ValueError("ADMIN_DEV_AUTH_ENABLED cannot be enabled in production")
        if self.app_environment == "production" and not self.admin_session_cookie_secure:
            raise ValueError("ADMIN_SESSION_COOKIE_SECURE must be enabled in production")
        if self.app_environment == "production" and not self.public_session_cookie_secure:
            raise ValueError("PUBLIC_SESSION_COOKIE_SECURE must be enabled in production")
        if self.app_environment == "production" and "*" in self.cors_origins:
            raise ValueError("CORS_ORIGINS cannot contain '*' in production")
        if self.app_environment == "production" and "*" in self.public_cors_origins:
            raise ValueError("PUBLIC_CORS_ORIGINS cannot contain '*' in production")
        if (
            self.app_environment == "production"
            and self.legacy_player_profile_content_writes_enabled
        ):
            raise ValueError(
                "LEGACY_PLAYER_PROFILE_CONTENT_WRITES_ENABLED cannot be enabled in production"
            )
        if self.app_environment == "production" and self.legacy_judge_voice_generation_enabled:
            raise ValueError(
                "LEGACY_JUDGE_VOICE_GENERATION_ENABLED cannot be enabled in production"
            )
        if self.app_environment == "production" and any(
            not origin.startswith("https://") for origin in self.cors_origins
        ):
            raise ValueError("CORS_ORIGINS must use HTTPS in production")
        if self.app_environment == "production" and any(
            not origin.startswith("https://") for origin in self.public_cors_origins
        ):
            raise ValueError("PUBLIC_CORS_ORIGINS must use HTTPS in production")
        if self.app_environment == "production" and not self.admin_oidc_enabled:
            raise ValueError("ADMIN_OIDC_ENABLED must be enabled in production")
        if self.admin_oidc_enabled:
            required_values = {
                "ADMIN_OIDC_ISSUER_URL": self.admin_oidc_issuer_url,
                "ADMIN_OIDC_CLIENT_ID": self.admin_oidc_client_id,
                "ADMIN_OIDC_CLIENT_SECRET": self.admin_oidc_client_secret,
                "ADMIN_OIDC_REDIRECT_URI": self.admin_oidc_redirect_uri,
                "ADMIN_OIDC_WEB_BASE_URL": self.admin_oidc_web_base_url,
            }
            missing = [name for name, value in required_values.items() if not value.strip()]
            if missing:
                raise ValueError(f"{', '.join(missing)} required when OIDC is enabled")
        if self.app_environment == "production" and self.admin_oidc_enabled:
            oidc_urls = {
                "ADMIN_OIDC_ISSUER_URL": self.admin_oidc_issuer_url,
                "ADMIN_OIDC_REDIRECT_URI": self.admin_oidc_redirect_uri,
                "ADMIN_OIDC_WEB_BASE_URL": self.admin_oidc_web_base_url,
            }
            insecure = [
                name for name, value in oidc_urls.items() if not value.startswith("https://")
            ]
            if insecure:
                raise ValueError(f"{', '.join(insecure)} must use HTTPS in production")
        if self.admin_dev_auth_enabled and not self.admin_dev_auth_email.strip():
            raise ValueError("ADMIN_DEV_AUTH_EMAIL is required when development auth is enabled")
        if self.admin_dev_auth_enabled and not self.admin_dev_auth_display_name.strip():
            raise ValueError(
                "ADMIN_DEV_AUTH_DISPLAY_NAME is required when development auth is enabled"
            )
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
