from decimal import Decimal
from typing import List, Optional
from zoneinfo import ZoneInfo

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

    # Fuso do CALENDÁRIO do aplicativo: define que dia é "hoje" e onde um mês
    # começa e termina. Era um contrato implícito de ambiente — só existia como
    # `TZ` nos serviços do Compose, invisível para o `Settings` e ausente em
    # qualquer uvicorn rodado à mão (dev, CI, Playwright). O efeito é o clássico
    # de fuso negativo: das 21h à meia-noite em Brasília, `datetime.now(UTC)` já
    # é o dia seguinte enquanto `date.today()` ainda é hoje, e as duas
    # referências convivendo colocavam o mesmo movimento em dois meses.
    APP_TIMEZONE: str = "America/Sao_Paulo"

    DATABASE_URL: str
    SECRET_KEY: str

    # Pool de conexões (só vale para Postgres). pool_pre_ping descarta conexão
    # morta antes de usá-la — sem ele, um reinício do banco derrubava a API em
    # 500 até o pool reciclar sozinho.
    DB_POOL_SIZE: int = 10
    DB_MAX_OVERFLOW: int = 20
    DB_POOL_TIMEOUT_SECONDS: int = 30
    DB_POOL_RECYCLE_SECONDS: int = 1800
    # Log de TODO SQL executado, com parâmetros (e-mails, hashes). Fica desligado
    # por padrão até em dev: antes vinha ligado com APP_ENV=development.
    SQL_ECHO: bool = False

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
    # Tetos por minuto dos dois baldes de auth. Configuráveis porque o certo
    # depende do deploy: o balde por IP é COMPARTILHADO por todo mundo atrás do
    # mesmo Wi-Fi, empresa ou CGNAT, e um teto apertado demais tranca gente
    # legítima sem impedir ataque nenhum (o atacante troca de IP). Quem barra
    # força bruta num alvo é o de CONTA, que independe de quantos IPs existem.
    RATE_LIMIT_AUTH_PER_MINUTE: int = 20
    RATE_LIMIT_ACCOUNT_PER_MINUTE: int = 10
    UPLOAD_MAX_BYTES: int = 5242880  # 5MB
    # Teto de anexos por workspace (ADR 0007) — vale independente de onde o
    # conteúdo mora: sem quota um único membro enche o volume com arquivos de 5MB.
    ATTACHMENT_QUOTA_BYTES: int = 209715200  # 200MB
    # Diretório do CONTEÚDO dos anexos (ADR 0007): o banco guarda metadados +
    # sha256 + chave, os bytes ficam aqui. Em produção é um volume dedicado
    # (docker-compose), e ele PRECISA entrar na rotina de backup junto com o
    # dump do Postgres — são dois artefatos, não um.
    ATTACHMENT_STORAGE_DIR: str = "./attachments_data"
    # Teto de linhas por commit de importação: o corpo é JSON livre, então sem
    # limite um cliente pede a criação de milhões de transações numa transação só
    IMPORT_MAX_ROWS: int = 5000

    # Timeout por tentativa contra a fonte de câmbio. O PTAX faz look-back de 5
    # dias (fim de semana/feriado), então o pior caso é 5× este valor — com os
    # 10s antigos dava ~50s presos numa única requisição.
    EXCHANGE_RATE_TIMEOUT_SECONDS: float = 4.0

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

    @property
    def is_deployed(self) -> bool:
        """Roda servindo gente de verdade (produção OU staging).

        `staging` é o modo que o SETUP.md recomenda para deploy em rede local
        sem TLS — e antes ele pulava TODA a validação, que só olhava para
        `production`. Ou seja: o caminho de deploy documentado aceitava
        SECRET_KEY fraca, ALLOWED_HOSTS="*" e /docs no ar. Só o requisito de
        HTTPS (COOKIE_SECURE) é relaxado em staging; o resto vale para os dois.
        """
        return self.APP_ENV in ("production", "staging")

    @model_validator(mode="after")
    def _validate_timezone(self):
        """Recusa boot com `APP_TIMEZONE` que não existe — em QUALQUER ambiente.

        O fuso define que dia é "hoje" e onde um mês começa e termina. Um erro de
        digitação (`America/Sao_paulo`, `America/SaoPaulo`) caía em UTC
        silenciosamente: nada quebrava, o app subia, e todo mundo passava a ter a
        competência deslocada em três horas — despesa da noite no mês errado,
        fatura vencida um dia antes, cotação do dia seguinte. Um erro de
        configuração que muda o resultado financeiro sem emitir sinal é a pior
        combinação possível.

        Isto vale em dev e no CI também, não só em produção: se as regras de
        calendário divergirem entre os ambientes, o CI deixa de provar o que
        produção faz. O motivo original do fallback — Windows sem base de fusos —
        deixou de existir quando `tzdata` entrou no `requirements.txt`.
        """
        try:
            ZoneInfo(self.APP_TIMEZONE)
        except Exception as exc:
            raise ValueError(
                f"APP_TIMEZONE inválido: {self.APP_TIMEZONE!r} ({exc}). "
                "Use um nome da base IANA, como America/Sao_Paulo ou UTC."
            )
        return self

    @model_validator(mode="after")
    def _validate_deployment(self):
        """Recusa boot em produção/staging com configuração insegura."""
        if not self.is_deployed:
            return self

        modo = self.APP_ENV
        if not self.SECRET_KEY or len(self.SECRET_KEY) < 32 or "change-me" in self.SECRET_KEY:
            raise ValueError(
                f"SECRET_KEY insegura para {modo}: use um valor aleatório com 32+ caracteres "
                "(ex: python -c \"import secrets; print(secrets.token_urlsafe(48))\")"
            )
        # TrustedHost: o Host precisa ser fixado nos domínios reais.
        # "*" (padrão) ou vazio deixaria a API aceitar Host forjado (SEC-006).
        if not self.allowed_hosts_list or self.allowed_hosts_list == ["*"]:
            raise ValueError(
                f"ALLOWED_HOSTS deve ser restrito em {modo} (ex.: "
                "ALLOWED_HOSTS=app.seudominio.com) — \"*\"/vazio desliga a "
                "checagem de Host"
            )

        if self.APP_ENV == "production":
            if not self.COOKIE_SECURE:
                raise ValueError("COOKIE_SECURE deve ser True em produção")
            if not self.DATABASE_URL.startswith("postgresql"):
                raise ValueError("Produção requer PostgreSQL na DATABASE_URL")
        return self


settings = Settings()
