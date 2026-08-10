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


def test_fuso_invalido_derruba_o_boot(monkeypatch):
    """`APP_TIMEZONE` com erro de digitação NÃO pode cair em UTC em silêncio.

    O fuso define que dia é "hoje" e onde um mês começa. Degradando para UTC, o
    app subia inteiro com a competência de todo mundo deslocada em três horas —
    despesa da noite no mês errado, fatura vencida um dia antes, cotação do dia
    seguinte — e nada no sistema dizia que isso tinha acontecido.
    """
    import pytest

    monkeypatch.setenv("DATABASE_URL", "sqlite:///test.db")
    monkeypatch.setenv("SECRET_KEY", STRONG_SECRET)
    # Erro de digitação plausível — o underscore que falta. (`Sao_paulo`, com
    # 'p' minúsculo, NÃO serve como caso de teste: o `zoneinfo` resolve o nome
    # pelo sistema de arquivos, que é insensível a maiúsculas no Windows e
    # sensível no Linux — o mesmo .env passaria na máquina do dev e derrubaria o
    # container.)
    monkeypatch.setenv("APP_TIMEZONE", "America/SaoPaulo")

    with pytest.raises(ValueError, match="APP_TIMEZONE inválido"):
        Settings(_env_file=None)


def test_fuso_invalido_derruba_o_boot_tambem_em_desenvolvimento(monkeypatch):
    """Vale em TODO ambiente: com regras de calendário diferentes entre dev/CI e
    produção, o CI deixa de provar o que produção faz."""
    import pytest

    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("DATABASE_URL", "sqlite:///test.db")
    monkeypatch.setenv("SECRET_KEY", "test-secret")
    monkeypatch.setenv("APP_TIMEZONE", "Marte/Olympus_Mons")

    with pytest.raises(ValueError, match="APP_TIMEZONE inválido"):
        Settings(_env_file=None)


def test_fuso_valido_passa(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite:///test.db")
    monkeypatch.setenv("SECRET_KEY", STRONG_SECRET)
    monkeypatch.setenv("APP_TIMEZONE", "UTC")

    assert Settings(_env_file=None).APP_TIMEZONE == "UTC"


def test_staging_recusa_secret_fraca(monkeypatch):
    """`staging` é o modo de deploy que o SETUP.md recomenda para rede local —
    antes ele pulava TODA a validação porque ela só olhava para `production`."""
    import pytest

    monkeypatch.setenv("APP_ENV", "staging")
    monkeypatch.setenv("DATABASE_URL", "sqlite:///test.db")
    monkeypatch.setenv("SECRET_KEY", "change-me")
    monkeypatch.setenv("ALLOWED_HOSTS", "app.example.com")

    with pytest.raises(ValueError, match="SECRET_KEY insegura"):
        Settings(_env_file=None)


def test_staging_recusa_allowed_hosts_aberto(monkeypatch):
    import pytest

    monkeypatch.setenv("APP_ENV", "staging")
    monkeypatch.setenv("DATABASE_URL", "sqlite:///test.db")
    monkeypatch.setenv("SECRET_KEY", STRONG_SECRET)
    monkeypatch.setenv("ALLOWED_HOSTS", "*")

    with pytest.raises(ValueError, match="ALLOWED_HOSTS"):
        Settings(_env_file=None)


def test_staging_aceita_http_sem_tls(monkeypatch):
    """Só o requisito de HTTPS é relaxado em staging (rede local sem TLS):
    SQLite e COOKIE_SECURE=False passam, o resto continua exigido."""
    monkeypatch.setenv("APP_ENV", "staging")
    monkeypatch.setenv("DATABASE_URL", "sqlite:///test.db")
    monkeypatch.setenv("SECRET_KEY", STRONG_SECRET)
    monkeypatch.setenv("COOKIE_SECURE", "False")
    monkeypatch.setenv("ALLOWED_HOSTS", "192.168.0.10")

    settings = Settings(_env_file=None)
    assert settings.is_deployed is True
    assert settings.COOKIE_SECURE is False


def test_development_nao_e_deploy(monkeypatch):
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("DATABASE_URL", "sqlite:///test.db")
    monkeypatch.setenv("SECRET_KEY", "fraca")
    settings = Settings(_env_file=None)
    assert settings.is_deployed is False
