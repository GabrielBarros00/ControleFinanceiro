from app.core.config import Settings

STRONG_SECRET = "a" * 48


def test_settings_defaults(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite:///test.db")
    monkeypatch.setenv("SECRET_KEY", "test-secret")
    # O conftest exporta APP_ENV=test para a suíte — aqui queremos o DEFAULT
    monkeypatch.delenv("APP_ENV", raising=False)

    settings = Settings(_env_file=None)
    assert settings.APP_ENV == "development"
    assert settings.APP_VERSION == "4.0.0"
    assert settings.DATABASE_URL == "sqlite:///test.db"
    assert settings.SECRET_KEY == "test-secret"
    assert settings.ACCESS_TOKEN_EXPIRES_MINUTES == 30
    assert settings.REFRESH_TOKEN_EXPIRES_DAYS == 7
    assert settings.COOKIE_SECURE is False
    assert settings.COOKIE_SAMESITE == "lax"
    assert settings.RATE_LIMIT_ENABLED is True
    assert settings.UPLOAD_MAX_BYTES == 5242880


def test_settings_override(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@localhost/db")
    monkeypatch.setenv("SECRET_KEY", STRONG_SECRET)
    monkeypatch.setenv("COOKIE_SECURE", "True")
    monkeypatch.setenv("ALLOWED_HOSTS", "app.example.com")

    settings = Settings(_env_file=None)
    assert settings.APP_ENV == "production"
    assert settings.DATABASE_URL == "postgresql://user:pass@localhost/db"
    assert settings.SECRET_KEY == STRONG_SECRET
    assert settings.COOKIE_SECURE is True
