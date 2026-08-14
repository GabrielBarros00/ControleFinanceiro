import pytest

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
    monkeypatch.setenv("FRONTEND_URL", "https://app.example.com")
    monkeypatch.setenv("SUPERADMIN_EMAIL", "admin@example.com")

    settings = Settings(_env_file=None)
    assert settings.APP_ENV == "production"
    assert settings.DATABASE_URL == "postgresql://user:pass@localhost/db"
    assert settings.SECRET_KEY == STRONG_SECRET
    assert settings.COOKIE_SECURE is True


def test_app_env_invalido_nao_pula_validacoes_de_deploy(monkeypatch):
    monkeypatch.setenv("APP_ENV", "prodution")
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@db/app")
    monkeypatch.setenv("SECRET_KEY", STRONG_SECRET)

    with pytest.raises(ValueError, match="APP_ENV inválido"):
        Settings(_env_file=None)


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
    monkeypatch.setenv("FRONTEND_URL", "http://192.168.0.10")
    monkeypatch.setenv("SUPERADMIN_EMAIL", "admin@example.com")

    settings = Settings(_env_file=None)
    assert settings.is_deployed is True
    assert settings.COOKIE_SECURE is False


def test_deploy_recusa_sem_superadmin(monkeypatch):
    """Sem `SUPERADMIN_EMAIL` um deploy novo nasce inoperável (ADR 0026).

    O cadastro padrão é por convite, não há quem convide, e não há tela por onde
    abrir o cadastro — a única saída seria SQL na mão dentro do container. É a
    mesma família de defeito que as outras checagens de deploy cobrem: config
    aceita, app no ar, e o problema só aparece quando alguém tenta usar.
    """
    import pytest

    monkeypatch.setenv("APP_ENV", "staging")
    monkeypatch.setenv("DATABASE_URL", "sqlite:///test.db")
    monkeypatch.setenv("SECRET_KEY", STRONG_SECRET)
    monkeypatch.setenv("ALLOWED_HOSTS", "192.168.0.10")
    monkeypatch.setenv("FRONTEND_URL", "http://192.168.0.10")
    monkeypatch.delenv("SUPERADMIN_EMAIL", raising=False)

    with pytest.raises(ValueError, match="SUPERADMIN_EMAIL"):
        Settings(_env_file=None)


@pytest.mark.parametrize("valor", ["gabriel", "admin@localhost", "@dominio.com", "a b@x.com"])
def test_deploy_recusa_superadmin_que_nao_e_email(monkeypatch, valor):
    """Endereço que o CADASTRO recusaria é um superadministrador que nunca vai
    existir — e o erro só apareceria no primeiro `/register`, como um 422 sobre
    e-mail, sem nenhuma pista de que a causa é uma variável de ambiente.

    `admin@localhost` está na lista porque é o erro plausível: parece válido,
    passa num teste de `"@" in valor`, e o `EmailStr` do cadastro recusa.
    """
    monkeypatch.setenv("APP_ENV", "staging")
    monkeypatch.setenv("DATABASE_URL", "sqlite:///test.db")
    monkeypatch.setenv("SECRET_KEY", STRONG_SECRET)
    monkeypatch.setenv("ALLOWED_HOSTS", "192.168.0.10")
    monkeypatch.setenv("FRONTEND_URL", "http://192.168.0.10")
    monkeypatch.setenv("SUPERADMIN_EMAIL", valor)

    with pytest.raises(ValueError, match="SUPERADMIN_EMAIL"):
        Settings(_env_file=None)


def test_desenvolvimento_nao_exige_superadmin(monkeypatch):
    """Em dev, vazio é legítimo: significa "sem administração de plataforma"."""
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("DATABASE_URL", "sqlite:///test.db")
    monkeypatch.setenv("SECRET_KEY", "fraca")
    monkeypatch.delenv("SUPERADMIN_EMAIL", raising=False)

    assert Settings(_env_file=None).SUPERADMIN_EMAIL is None


def test_development_nao_e_deploy(monkeypatch):
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("DATABASE_URL", "sqlite:///test.db")
    monkeypatch.setenv("SECRET_KEY", "fraca")
    settings = Settings(_env_file=None)
    assert settings.is_deployed is False


def _production_settings(**overrides):
    valores = {
        "APP_ENV": "production",
        "DATABASE_URL": "postgresql://user:pass@db/app",
        "SECRET_KEY": STRONG_SECRET,
        "COOKIE_SECURE": True,
        "ALLOWED_HOSTS": "app.example.com",
        "FRONTEND_URL": "https://app.example.com",
        "SUPERADMIN_EMAIL": "admin@example.com",
        "_env_file": None,
    }
    valores.update(overrides)
    return Settings(**valores)


def test_producao_recusa_frontend_http_publico():
    with pytest.raises(ValueError, match="https://"):
        _production_settings(FRONTEND_URL="http://app.example.com")


def test_deploy_recusa_frontend_fora_de_allowed_hosts():
    with pytest.raises(ValueError, match="precisa constar em ALLOWED_HOSTS"):
        _production_settings(FRONTEND_URL="https://outro.example.com")


def test_producao_localhost_http_continua_valido_para_gate_do_compose():
    config = _production_settings(
        ALLOWED_HOSTS="localhost,127.0.0.1",
        FRONTEND_URL="http://localhost:8890/",
    )
    assert config.FRONTEND_URL == "http://localhost:8890"


def test_google_oauth_recusa_credenciais_parciais():
    with pytest.raises(ValueError, match="Google OAuth incompleto"):
        _production_settings(GOOGLE_CLIENT_ID="client-id")


def test_google_oauth_recusa_redirect_de_outro_deploy():
    with pytest.raises(ValueError, match="GOOGLE_REDIRECT_URI deve ser exatamente"):
        _production_settings(
            GOOGLE_CLIENT_ID="client-id",
            GOOGLE_CLIENT_SECRET="client-secret",
            GOOGLE_REDIRECT_URI="https://outro.example.com/api/v1/auth/google/callback",
        )


def test_google_oauth_completo_e_coerente_passa():
    config = _production_settings(
        GOOGLE_CLIENT_ID="client-id",
        GOOGLE_CLIENT_SECRET="client-secret",
        GOOGLE_REDIRECT_URI="https://app.example.com/api/v1/auth/google/callback",
    )
    assert config.GOOGLE_CLIENT_ID == "client-id"


def test_smtp_recusa_host_sem_remetente():
    with pytest.raises(ValueError, match="EMAIL_FROM é obrigatório"):
        _production_settings(SMTP_HOST="smtp.resend.com")


def test_smtp_recusa_credencial_parcial():
    with pytest.raises(ValueError, match="SMTP_USER e SMTP_PASSWORD"):
        _production_settings(SMTP_USER="resend")


def test_smtp_recusa_ssl_implicito_na_porta_465():
    with pytest.raises(ValueError, match="SSL implícito"):
        _production_settings(
            SMTP_HOST="smtp.resend.com",
            SMTP_PORT=465,
            SMTP_USER="resend",
            SMTP_PASSWORD="api-key",
            EMAIL_FROM="noreply@example.com",
        )


def test_smtp_resend_starttls_valido_passa():
    config = _production_settings(
        SMTP_HOST="smtp.resend.com",
        SMTP_PORT=587,
        SMTP_USER="resend",
        SMTP_PASSWORD="api-key",
        SMTP_TLS=True,
        EMAIL_FROM="noreply@example.com",
    )
    assert config.SMTP_PORT == 587


def test_smtp_aceita_nome_de_exibicao_no_remetente():
    sender = "Controle Financeiro <noreply@notify.capamericagod.com>"
    config = _production_settings(
        SMTP_HOST="smtp.resend.com",
        SMTP_PORT=587,
        SMTP_USER="resend",
        SMTP_PASSWORD="api-key",
        SMTP_TLS=True,
        EMAIL_FROM=sender,
    )
    assert config.EMAIL_FROM == sender


@pytest.mark.parametrize(
    "sender",
    [
        "primeiro@example.com, segundo@example.com",
        "Equipe: noreply@example.com;",
        "Controle Financeiro <noreply@example.com>\r\nBcc: atacante@example.com",
    ],
)
def test_smtp_recusa_remetente_ambiguo_ou_injecao_de_header(sender):
    with pytest.raises(ValueError, match="EMAIL_FROM inválido"):
        _production_settings(
            SMTP_HOST="smtp.resend.com",
            SMTP_PORT=587,
            SMTP_USER="resend",
            SMTP_PASSWORD="api-key",
            EMAIL_FROM=sender,
        )
