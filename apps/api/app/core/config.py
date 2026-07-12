import json
from functools import lru_cache
from typing import Annotated, Literal

from pydantic import Field, field_validator, model_validator
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
    legacy_player_profile_favorite_writes_enabled: bool = False
    legacy_judge_voice_generation_enabled: bool = False
    werewolf_logs_dir: str = "logs"
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
    judge_voice_worker_poll_seconds: float = Field(default=2.0, ge=0.25, le=60.0)
    judge_voice_worker_heartbeat_seconds: float = Field(default=10.0, ge=1.0, le=60.0)
    judge_voice_worker_probe_max_age_seconds: float = Field(default=45.0, ge=5.0, le=300.0)
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
        if (
            self.app_environment == "production"
            and self.legacy_player_profile_favorite_writes_enabled
        ):
            raise ValueError(
                "LEGACY_PLAYER_PROFILE_FAVORITE_WRITES_ENABLED cannot be enabled in production"
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
