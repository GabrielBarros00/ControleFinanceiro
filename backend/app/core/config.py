from decimal import Decimal
from email.headerregistry import HeaderRegistry
from typing import List, Optional
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _endereco_unico(valor: str, *, cabecalho: str, campo: str) -> str:
    """Valida um endereço destinado a um cabeçalho e o devolve normalizado.

    `EMAIL_FROM` e `EMAIL_REPLY_TO` correm exatamente o mesmo risco e por isso
    passam pela mesma peneira: os dois vão para dentro de um cabeçalho da
    mensagem, e um `\\r\\n` no meio de qualquer um deles acrescenta cabeçalhos
    que ninguém escreveu — um `Bcc:` para o atacante, tipicamente. Dois
    endereços ou um grupo (`Equipe: a@x, b@y;`) também não servem: o provedor
    recusa, ou pior, entrega para quem não devia.
    """
    endereco = valor.strip()
    try:
        if "\r" in endereco or "\n" in endereco:
            raise ValueError("quebras de linha não são permitidas")

        header = HeaderRegistry()(cabecalho, endereco)
        if header.defects:
            raise ValueError(str(header.defects[0]))
        if len(header.addresses) != 1:
            raise ValueError("informe exatamente um endereço")
        if any(group.display_name is not None for group in header.groups):
            raise ValueError("grupos de endereços não são permitidos")

        from email_validator import EmailNotValidError, validate_email

        try:
            validate_email(
                header.addresses[0].addr_spec,
                check_deliverability=False,
            )
        except EmailNotValidError as exc:
            raise ValueError(str(exc)) from exc
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{campo} inválido: {valor!r} ({exc})") from exc
    return endereco


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
    # Para onde vai a resposta de quem aperta "responder". O `EMAIL_FROM` é um
    # `noreply@` num subdomínio de envio que não tem MX: resposta a ele morre no
    # DNS, e o destinatário nunca fica sabendo. Vazio omite o cabeçalho.
    EMAIL_REPLY_TO: Optional[str] = None
    SMTP_HOST: Optional[str] = None
    SMTP_PORT: int = 587
    SMTP_USER: Optional[str] = None
    SMTP_PASSWORD: Optional[str] = None
    SMTP_TLS: bool = True

    FRONTEND_URL: str = "http://localhost:5173"
    RESET_TOKEN_EXPIRES_MINUTES: int = 30

    # E-mail do primeiro superadministrador (ADR 0026). Duas coisas dependem
    # dele, e é a segunda que o torna obrigatório num deploy novo:
    #
    # 1. No startup, a conta com este e-mail é promovida a `superadmin`
    #    (idempotente — se já é, nada acontece).
    # 2. É a saída do impasse do banco vazio: com o cadastro em `invite_only`
    #    (o padrão), ninguém se cadastra sem convite e não existe ninguém para
    #    convidar. Este e-mail — e só ele, e só enquanto não houver superadmin
    #    nenhum — pode criar conta sem convite.
    #
    # Vazio é legítimo: significa "sem administração de plataforma", que é o
    # certo para dev e para a suíte. Só que, vazio, `REGISTRATION_MODE` também
    # precisa ser `open`, ou o site nasce inacessível.
    SUPERADMIN_EMAIL: Optional[str] = None

    # Quem pode criar conta, quando NÃO há valor gravado pela tela de Admin
    # (ADR 0026). `invite_only` é o padrão do produto: um deploy novo nasce
    # fechado, e abrir é decisão consciente.
    #
    # Existe como variável de ambiente — e não só como padrão no código — pelo
    # mesmo motivo dos outros limites configuráveis: ambientes que NÃO têm
    # administrador precisam declarar que a porta está aberta. É o caso do e2e,
    # que sobe um banco descartável sem ninguém dentro; sem isto, a primeira tela
    # da suíte seria um 403 de cadastro. Dev e produção continuam rodando o mesmo
    # código com a mesma regra — muda só o valor declarado, à vista.
    REGISTRATION_MODE: str = "invite_only"

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

    # --- Aviso de vencimento (ADR 0033) ---
    #
    # Chaves VAPID do Web Push. Um par por INSTALAÇÃO, gerado uma vez
    # (`python -m scripts.gerar_vapid`) e guardado no `.env`.
    #
    # Girar a chave INVALIDA todas as inscrições existentes — cada navegador
    # precisa se reinscrever —, então não é operação de rotina.
    #
    # Ausentes, a funcionalidade se desliga sozinha em vez de quebrar: o endpoint
    # de configuração responde `enabled: false`, a interface não oferece nada e o
    # job não tenta enviar push. Sino e e-mail seguem funcionando. É o que faz o
    # ambiente de desenvolvimento (que não terá chave) continuar utilizável.
    VAPID_PUBLIC_KEY: Optional[str] = None
    VAPID_PRIVATE_KEY: Optional[str] = None
    # Vai no JWT do VAPID como `sub`. O serviço de push usa isto para falar com o
    # responsável se esta origem passar a se comportar mal — é contato, não
    # autenticação. `mailto:` ou `https:`.
    VAPID_SUBJECT: str = "mailto:admin@localhost"

    # Hora LOCAL (APP_TIMEZONE) em que o aviso sai. O job roda de hora em hora e
    # ele mesmo desiste quando não é a hora — o ramo diário do `cron` dispara
    # "24h depois que o contêiner subiu", ou seja, numa hora que depende de
    # quando houve o último deploy. Para expurgo tanto faz; para notificação não:
    # "sua conta vence hoje" às 3 da manhã acorda a pessoa e queima o canal.
    DUE_REMINDER_HOUR: int = 9

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
    def _validate_app_env(self):
        """Um typo não pode transformar produção em ambiente relaxado."""
        aceitos = ("development", "test", "staging", "production")
        if self.APP_ENV not in aceitos:
            raise ValueError(
                f"APP_ENV inválido: {self.APP_ENV!r}. "
                f"Use um de: {', '.join(aceitos)}."
            )
        return self

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
    def _validate_registration_mode(self):
        """Recusa boot com `REGISTRATION_MODE` inválido — em QUALQUER ambiente.

        Um erro de digitação (`opne`, `invite-only`) não daria erro em lugar
        nenhum: o valor chegaria ao portão de cadastro, não casaria com `open`
        nem com `closed`, e seria tratado como "por convite". O site subiria
        fechado sem que ninguém tivesse pedido isso, e a variável no `.env` diria
        o contrário. Mesma família do `APP_TIMEZONE` — configuração que muda o
        comportamento sem emitir sinal.
        """
        aceitos = ("open", "invite_only", "closed")
        if self.REGISTRATION_MODE not in aceitos:
            raise ValueError(
                f"REGISTRATION_MODE inválido: {self.REGISTRATION_MODE!r}. "
                f"Use um de: {', '.join(aceitos)}."
            )
        return self

    @model_validator(mode="after")
    def _validate_urls_and_optional_integrations(self):
        """Recusa integrações pela metade e URLs que só falhariam no uso.

        Essas configurações são opcionais, mas, quando o operador começa a
        preenchê-las, degradar silenciosamente para "desativado" ou deixar o
        erro para o primeiro e-mail/login transforma um deploy verde em uma
        aplicação parcialmente quebrada.
        """
        frontend = self.FRONTEND_URL.strip().rstrip("/")
        try:
            parsed = urlsplit(frontend)
            # Acessar `.port` força a validação de porta fora de 1..65535.
            parsed.port
        except ValueError as exc:
            raise ValueError(f"FRONTEND_URL inválida: {self.FRONTEND_URL!r} ({exc})")

        if (
            parsed.scheme not in ("http", "https")
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.path
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError(
                "FRONTEND_URL deve ser apenas a origem pública, no formato "
                "https://app.seudominio.com (sem caminho, query ou credenciais)"
            )
        self.FRONTEND_URL = frontend

        google_credentials = bool(self.GOOGLE_CLIENT_ID or self.GOOGLE_CLIENT_SECRET)
        if google_credentials and not (
            self.GOOGLE_CLIENT_ID
            and self.GOOGLE_CLIENT_SECRET
            and self.GOOGLE_REDIRECT_URI
        ):
            raise ValueError(
                "Google OAuth incompleto: preencha GOOGLE_CLIENT_ID, "
                "GOOGLE_CLIENT_SECRET e GOOGLE_REDIRECT_URI juntos"
            )

        smtp_user = bool(self.SMTP_USER)
        smtp_password = bool(self.SMTP_PASSWORD)
        if smtp_user != smtp_password:
            raise ValueError(
                "SMTP incompleto: SMTP_USER e SMTP_PASSWORD devem ser "
                "preenchidos juntos"
            )
        if (smtp_user or smtp_password) and not self.SMTP_HOST:
            raise ValueError("SMTP_HOST é obrigatório quando há credenciais SMTP")
        if self.SMTP_HOST:
            if not self.EMAIL_FROM:
                raise ValueError(
                    "EMAIL_FROM é obrigatório quando SMTP_HOST está configurado"
                )
            # Nenhuma checagem de porta aqui: 465/2465 (SSL implícito) e as
            # portas de STARTTLS são todas aceitas, e `smtp_transport` decide o
            # modo pelo que o servidor anuncia. A recusa que existia neste ponto
            # rejeitava justamente as portas alternativas que um VPS com saída
            # bloqueada precisa usar.
            self.EMAIL_FROM = _endereco_unico(
                self.EMAIL_FROM, cabecalho="From", campo="EMAIL_FROM"
            )

        # Fora do `if SMTP_HOST`: preencher o endereço de resposta é opt-in, e
        # quem o preencheu quer saber do erro no boot — não meses depois, quando
        # o primeiro convite sair com um cabeçalho quebrado.
        if self.EMAIL_REPLY_TO:
            self.EMAIL_REPLY_TO = _endereco_unico(
                self.EMAIL_REPLY_TO, cabecalho="Reply-To", campo="EMAIL_REPLY_TO"
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

        frontend = urlsplit(self.FRONTEND_URL)
        hostname = (frontend.hostname or "").lower()

        def host_permitido(padrao: str) -> bool:
            padrao = padrao.lower()
            if padrao.startswith("*."):
                return hostname.endswith(padrao[1:]) and hostname != padrao[2:]
            return hostname == padrao

        if not any(host_permitido(host) for host in self.allowed_hosts_list):
            raise ValueError(
                f"o host de FRONTEND_URL ({hostname}) precisa constar em "
                "ALLOWED_HOSTS"
            )

        if (
            self.APP_ENV == "production"
            and frontend.scheme != "https"
            and hostname not in ("localhost", "127.0.0.1", "::1")
        ):
            raise ValueError("FRONTEND_URL deve usar https:// em produção")

        if self.GOOGLE_CLIENT_ID and self.GOOGLE_CLIENT_SECRET:
            redirect_esperado = f"{self.FRONTEND_URL}/api/v1/auth/google/callback"
            if self.GOOGLE_REDIRECT_URI != redirect_esperado:
                raise ValueError(
                    "GOOGLE_REDIRECT_URI deve ser exatamente "
                    f"{redirect_esperado!r} neste deploy"
                )

        # Sem superadmin, um deploy novo nasce inoperável: o cadastro é por
        # convite (padrão do ADR 0026), não há quem convide, e não há tela por
        # onde abrir o cadastro — a única saída seria `docker compose exec` com
        # SQL na mão. É o mesmo tipo de defeito que as checagens acima cobrem: a
        # configuração é aceita, o app sobe, e o problema só aparece quando
        # alguém tenta usar o sistema.
        if not self.SUPERADMIN_EMAIL:
            raise ValueError(
                f"SUPERADMIN_EMAIL é obrigatório em {modo}: é a conta que "
                "administra o site e a única que pode se cadastrar sem convite "
                "no primeiro acesso (ex.: SUPERADMIN_EMAIL=voce@dominio.com)"
            )
        # A checagem é a MESMA do cadastro (`EmailStr`), e não um `"@" in valor`,
        # porque um endereço que o cadastro recusa é um superadministrador que
        # nunca vai existir. Com a versão frouxa, `admin@localhost` passava aqui,
        # o app subia normalmente, e o erro só aparecia no primeiro `/register` —
        # como um 422 falando de e-mail inválido, sem nenhuma pista de que a
        # causa era uma variável de ambiente.
        from email_validator import EmailNotValidError, validate_email
        try:
            validate_email(self.SUPERADMIN_EMAIL, check_deliverability=False)
        except EmailNotValidError as exc:
            raise ValueError(
                f"SUPERADMIN_EMAIL inválido: {self.SUPERADMIN_EMAIL!r} ({exc}). "
                "Use um endereço completo, com domínio (ex.: voce@dominio.com)."
            )

        if self.APP_ENV == "production":
            if not self.COOKIE_SECURE:
                raise ValueError("COOKIE_SECURE deve ser True em produção")
            if not self.DATABASE_URL.startswith("postgresql"):
                raise ValueError("Produção requer PostgreSQL na DATABASE_URL")
        return self


settings = Settings()
