import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.main import app
from app.core.config import Settings, settings
from app.core.rate_limit import account_limiter, auth_limiter

client = TestClient(app)


# --- Validação de configuração de produção ---

def _prod_settings(**overrides):
    base = dict(
        APP_ENV="production",
        DATABASE_URL="postgresql://u:p@db/app",
        SECRET_KEY="x" * 48,
        COOKIE_SECURE=True,
        ALLOWED_HOSTS="app.example.com",
        _env_file=None,
    )
    base.update(overrides)
    return Settings(**base)


def test_production_settings_valid():
    s = _prod_settings()
    assert s.APP_ENV == "production"


def test_production_rejects_wildcard_allowed_hosts():
    with pytest.raises(ValidationError):
        _prod_settings(ALLOWED_HOSTS="*")
    with pytest.raises(ValidationError):
        _prod_settings(ALLOWED_HOSTS="")


def test_production_rejects_default_secret():
    with pytest.raises(ValidationError):
        _prod_settings(SECRET_KEY="change-me-in-production-0123456789abcdef")


def test_production_rejects_short_secret():
    with pytest.raises(ValidationError):
        _prod_settings(SECRET_KEY="curta")


def test_production_requires_secure_cookies():
    with pytest.raises(ValidationError):
        _prod_settings(COOKIE_SECURE=False)


def test_production_requires_postgres():
    with pytest.raises(ValidationError):
        _prod_settings(DATABASE_URL="sqlite:///./dev.db")


def test_development_allows_relaxed_config():
    s = Settings(
        APP_ENV="development",
        DATABASE_URL="sqlite:///./dev.db",
        SECRET_KEY="dev",
        _env_file=None,
    )
    assert s.APP_ENV == "development"


def test_cors_origins_parsing():
    s = Settings(
        APP_ENV="development",
        DATABASE_URL="sqlite:///./dev.db",
        SECRET_KEY="dev",
        CORS_ORIGINS="https://a.com, https://b.com",
        _env_file=None,
    )
    assert s.cors_origins_list == ["https://a.com", "https://b.com"]


# --- Rate limiting ---

def test_login_rate_limited_por_ip(db_session, override_get_session, monkeypatch):
    """O balde por IP+rota, com e-mails DIFERENTES a cada tentativa.

    Repetir o mesmo e-mail mediria o balde por CONTA, que é menor e estoura
    antes — o teste passaria sem nunca exercitar o de IP.

    O teto vem do objeto, não de um número repetido aqui: ele é configurável
    (`RATE_LIMIT_AUTH_PER_MINUTE`), e um teste que fixa "5" reprova por
    configuração em vez de por defeito.
    """
    monkeypatch.setattr(settings, "RATE_LIMIT_ENABLED", True)
    auth_limiter.reset()
    account_limiter.reset()
    client.cookies.clear()

    for i in range(auth_limiter.max_requests):
        res = client.post("/api/v1/auth/login", json={"email": f"x{i}@y.com", "password": "errada1"})
        assert res.status_code == 401

    res = client.post("/api/v1/auth/login", json={"email": "ultimo@y.com", "password": "errada1"})
    assert res.status_code == 429


def test_login_rate_limited_por_conta(db_session, override_get_session, monkeypatch):
    """O balde por CONTA — o que barra força bruta contra um alvo.

    Ele precisa ser o MENOR dos dois: um IP é barato (VPN, 4G, botnet) e o teto
    dele tem de ser generoso porque é compartilhado por gente legítima atrás do
    mesmo Wi-Fi/CGNAT. Se o teto por conta passasse o de IP, quem ataca uma conta
    específica passaria a ser limitado só pelo balde que troca de graça.
    """
    monkeypatch.setattr(settings, "RATE_LIMIT_ENABLED", True)
    auth_limiter.reset()
    account_limiter.reset()
    client.cookies.clear()

    assert account_limiter.max_requests < auth_limiter.max_requests

    for _ in range(account_limiter.max_requests):
        res = client.post("/api/v1/auth/login", json={"email": "alvo@y.com", "password": "errada1"})
        assert res.status_code == 401

    res = client.post("/api/v1/auth/login", json={"email": "alvo@y.com", "password": "errada1"})
    assert res.status_code == 429


def test_rate_limit_disabled_via_setting(db_session, override_get_session, monkeypatch):
    monkeypatch.setattr(settings, "RATE_LIMIT_ENABLED", False)
    auth_limiter.reset()
    account_limiter.reset()
    client.cookies.clear()

    for _ in range(auth_limiter.max_requests + account_limiter.max_requests + 1):
        res = client.post("/api/v1/auth/login", json={"email": "x@y.com", "password": "errada1"})
        assert res.status_code == 401


# --- Middlewares ---

def test_security_headers_present():
    res = client.get("/api/v1/health")
    assert res.headers["X-Content-Type-Options"] == "nosniff"
    assert res.headers["X-Frame-Options"] == "DENY"
    assert res.headers["Referrer-Policy"] == "same-origin"
    assert "X-Request-ID" in res.headers


def test_request_id_propagated():
    res = client.get("/api/v1/health", headers={"X-Request-ID": "meu-id-123"})
    assert res.headers["X-Request-ID"] == "meu-id-123"
