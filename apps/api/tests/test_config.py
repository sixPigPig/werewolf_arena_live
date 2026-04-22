from app.core.config import Settings


def test_settings_accepts_plain_string_cors_origins_env(monkeypatch) -> None:
    monkeypatch.setenv("CORS_ORIGINS", "http://localhost:5173")

    settings = Settings(_env_file=None)

    assert settings.cors_origins == ["http://localhost:5173"]
