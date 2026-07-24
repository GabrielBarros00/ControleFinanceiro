from decimal import Decimal
from typing import List, Optional
from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
    )

    APP_ENV: str = "development"
    APP_VERSION: str = "4.0.0"

    DATABASE_URL: str
    SECRET_KEY: str

    ACCESS_TOKEN_EXPIRES_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRES_DAYS: int = 7

    COOKIE_SECURE: bool = False
    COOKIE_SAMESITE: str = "lax"

    # Origens permitidas para CORS (separadas por vírgula)
    CORS_ORIGINS: str = "http://localhost:5173,http://127.0.0.1:5173"

    # Hosts confiáveis (TrustedHost). "*" desliga a checagem; em produção o
    # operador deve restringir aos domínios reais (SEC-006).
    ALLOWED_HOSTS: str = "*"
    
    GOOGLE_CLIENT_ID: Optional[str] = None
    GOOGLE_CLIENT_SECRET: Optional[str] = None
    GOOGLE_REDIRECT_URI: Optional[str] = None

    EMAIL_FROM: Optional[str] = None
    SMTP_HOST: Optional[str] = None
    SMTP_PORT: int = 587
    SMTP_USER: Optional[str] = None
    SMTP_PASSWORD: Optional[str] = None
    SMTP_TLS: bool = True

    FRONTEND_URL: str = "http://localhost:5173"
    RESET_TOKEN_EXPIRES_MINUTES: int = 30

    RATE_LIMIT_ENABLED: bool = True
    UPLOAD_MAX_BYTES: int = 5242880  # 5MB

    # IOF sobre compras internacionais no cartão (crédito/débito). 3,5% desde
    # jul/2025 (Decreto 12.499/2025). É valor regulatório (muda por decreto),
    # por isso fica configurável e é congelado por lançamento.
    IOF_INTERNATIONAL_CARD_RATE: Decimal = Decimal("0.035")

    @property
    def cors_origins_list(self) -> List[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]

    @property
    def allowed_hosts_list(self) -> List[str]:
        return [h.strip() for h in self.ALLOWED_HOSTS.split(",") if h.strip()]

    @model_validator(mode="after")
    def _validate_production(self):
        """Recusa boot em produção com configuração insegura."""
        if self.APP_ENV == "production":
            if not self.SECRET_KEY or len(self.SECRET_KEY) < 32 or "change-me" in self.SECRET_KEY:
                raise ValueError(
                    "SECRET_KEY insegura para produção: use um valor aleatório com 32+ caracteres "
                    "(ex: python -c \"import secrets; print(secrets.token_urlsafe(48))\")"
                )
            if not self.COOKIE_SECURE:
                raise ValueError("COOKIE_SECURE deve ser True em produção")
            if not self.DATABASE_URL.startswith("postgresql"):
                raise ValueError("Produção requer PostgreSQL na DATABASE_URL")
            # TrustedHost: em produção o Host precisa ser fixado nos domínios reais.
            # "*" (padrão) ou vazio deixaria a API aceitar Host forjado (SEC-006).
            if not self.allowed_hosts_list or self.allowed_hosts_list == ["*"]:
                raise ValueError(
                    "ALLOWED_HOSTS deve ser restrito em produção (ex.: "
                    "ALLOWED_HOSTS=app.seudominio.com) — \"*\"/vazio desliga a "
                    "checagem de Host"
                )
        return self


settings = Settings()
