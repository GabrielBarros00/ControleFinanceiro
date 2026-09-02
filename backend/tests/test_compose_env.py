"""O `docker-compose.yml` entrega ao container o que o código promete ler.

Este arquivo existe por causa de um defeito que já apareceu DUAS vezes no mesmo
formato, e que nenhuma outra rede pega:

- `SMTP_TLS` estava no `.env.example`, no `SETUP.md` e no `Settings` — e não era
  passado pelo compose. Quem precisava de `False` preenchia o campo e nada
  acontecia.
- As quatro chaves configuráveis em runtime (ADR 0026) nasceram com a mesma
  falha: o `app_settings` documenta uma cascata `AppSetting → .env → embutido`,
  mas o degrau do meio não existia no deploy — o container nunca recebia a
  variável e caía direto no padrão embutido.

É invisível para a suíte (que não sobe container), para o `alembic check`, para o
lint e para o smoke (que só olha o comportamento com os padrões). O sintoma é
sempre o mesmo e é o pior que uma configuração pode ter: ela é aceita, o app
sobe, e ela não faz nada.
"""
import re
from pathlib import Path

import pytest

from app.core.config import Settings
from app.services import app_settings

COMPOSE = Path(__file__).resolve().parents[2] / "docker-compose.yml"
ENV_EXAMPLE = Path(__file__).resolve().parents[2] / ".env.example"
SETUP = Path(__file__).resolve().parents[2] / "SETUP.md"

# Estes dois parâmetros pertencem exclusivamente ao profile `dev` do pgAdmin.
# Não entram no template de produção de propósito.
CHAVES_EXCLUSIVAS_DE_DEV = {"PGADMIN_EMAIL", "PGADMIN_PASSWORD"}

# Configurações operacionais que não passam pela tela de Administração. Todas
# devem concordar entre Settings, Compose e o template entregue ao operador.
CHAVES_AVANCADAS = (
    "ACCESS_TOKEN_EXPIRES_MINUTES",
    "REFRESH_TOKEN_EXPIRES_DAYS",
    "RESET_TOKEN_EXPIRES_MINUTES",
    "DB_POOL_SIZE",
    "DB_MAX_OVERFLOW",
    "DB_POOL_TIMEOUT_SECONDS",
    "DB_POOL_RECYCLE_SECONDS",
    "SQL_ECHO",
    "EXCHANGE_RATE_TIMEOUT_SECONDS",
    "IOF_INTERNATIONAL_CARD_RATE",
)


def _ambiente_do_servico(nome: str) -> dict[str, str]:
    """Bloco `environment:` de um serviço, sem depender de PyYAML.

    O arquivo é indentado com dois espaços e as chaves são `NOME: valor` — um
    parser de três linhas basta e não acrescenta dependência à suíte só para ler
    um arquivo que este projeto controla inteiro.
    """
    linhas = COMPOSE.read_text(encoding="utf-8").splitlines()
    dentro_do_servico = False
    dentro_do_bloco = False
    achados: dict[str, str] = {}

    for linha in linhas:
        if re.match(rf"^  {re.escape(nome)}:\s*$", linha):
            dentro_do_servico = True
            continue
        if dentro_do_servico and re.match(r"^  \S", linha):
            break  # começou outro serviço
        if not dentro_do_servico:
            continue
        if re.match(r"^    environment:\s*$", linha):
            dentro_do_bloco = True
            continue
        if dentro_do_bloco and re.match(r"^    \S", linha):
            dentro_do_bloco = False
        if not dentro_do_bloco:
            continue
        casa = re.match(r"^      ([A-Z][A-Z0-9_]*):\s*(.*)$", linha)
        if casa:
            achados[casa.group(1)] = casa.group(2).strip()
    return achados


def _valores_do_env_example() -> dict[str, str]:
    """Lê apenas atribuições do template, sem interpretar segredos ou shell."""
    achados: dict[str, str] = {}
    for linha in ENV_EXAMPLE.read_text(encoding="utf-8").splitlines():
        casa = re.match(r"^([A-Z][A-Z0-9_]*)=(.*)$", linha)
        if casa:
            assert casa.group(1) not in achados, (
                f"{casa.group(1)} aparece mais de uma vez no .env.example"
            )
            achados[casa.group(1)] = casa.group(2)
    return achados


CHAVES_DE_RUNTIME = sorted(
    chave.env for chave in app_settings.CHAVES.values() if chave.env
)


@pytest.mark.parametrize("variavel", CHAVES_DE_RUNTIME)
def test_chave_configuravel_chega_no_container(variavel):
    """Toda chave com `env=` precisa do degrau do meio da cascata.

    Sem a variável no compose, `AppSetting → .env → embutido` vira
    `AppSetting → embutido`: o operador edita o `.env`, reinicia, e o valor
    antigo continua valendo em silêncio.
    """
    ambiente = _ambiente_do_servico("backend")
    assert variavel in ambiente, (
        f"{variavel} é lida por app_settings mas não é passada ao container. "
        "Acrescente-a ao bloco `environment:` do serviço `backend`."
    )


@pytest.mark.parametrize("variavel", CHAVES_DE_RUNTIME)
def test_padrao_do_compose_bate_com_o_do_codigo(variavel):
    """O `${VAR:-padrão}` do compose e o padrão do `Settings` são o MESMO número.

    Duas fontes para o mesmo valor é uma armadilha aceita conscientemente (o
    compose não sabe ler o `Settings`), então o que resta é um teste que reprova
    a divergência. Sem ele, mudar o teto no Python deixaria o deploy com o
    antigo — e a única pista seria um número diferente do documentado.
    """
    bruto = _ambiente_do_servico("backend")[variavel]
    casa = re.match(r"^\$\{" + variavel + r":-(.*)\}$", bruto)
    assert casa, f"{variavel} deveria ser `${{{variavel}:-<padrão>}}`, veio {bruto!r}"

    no_compose = casa.group(1)
    # O default do CAMPO, não `getattr` numa instância: instanciar leria o
    # ambiente da máquina que roda a suíte, e o teste passaria ou falharia
    # conforme o `.env` de quem o executasse.
    no_codigo = Settings.model_fields[variavel].default
    assert str(no_codigo) == no_compose, (
        f"{variavel}: compose diz {no_compose!r} e config.py diz {no_codigo!r}"
    )
    assert _valores_do_env_example()[variavel] == no_compose, (
        f"{variavel}: .env.example diverge do padrão {no_compose!r} do deploy"
    )


@pytest.mark.parametrize("variavel", CHAVES_AVANCADAS)
def test_ajuste_avancado_chega_ao_backend_com_o_padrao_documentado(variavel):
    """Uma chave no template não pode ser decorativa nem divergir do código."""
    bruto = _ambiente_do_servico("backend")[variavel]
    casa = re.match(r"^\$\{" + variavel + r":-(.*)\}$", bruto)
    assert casa, f"{variavel} não é configurável pelo .env no backend: {bruto!r}"

    esperado = str(Settings.model_fields[variavel].default)
    assert casa.group(1) == esperado
    assert _valores_do_env_example()[variavel] == esperado


def test_todo_campo_configuravel_do_settings_chega_ao_backend():
    """Só a versão da release é interna; o restante deve chegar pelo Compose."""
    faltantes = set(Settings.model_fields) - set(_ambiente_do_servico("backend"))
    assert faltantes == {"APP_VERSION"}, (
        "Settings ganhou campo sem wiring no deploy. Passe-o no serviço backend "
        f"e documente-o no .env.example; campos faltantes: {sorted(faltantes)}"
    )


def test_env_example_cobre_todas_as_variaveis_do_compose_de_producao():
    """Nenhuma interpolação de produção pode depender de uma chave escondida."""
    texto = COMPOSE.read_text(encoding="utf-8")
    no_compose = set(re.findall(r"\$\{([A-Z][A-Z0-9_]*)", texto))
    no_template = set(_valores_do_env_example())

    assert CHAVES_EXCLUSIVAS_DE_DEV <= no_compose
    faltantes = no_compose - no_template - CHAVES_EXCLUSIVAS_DE_DEV
    assert not faltantes, (
        "variáveis usadas pelo Compose não aparecem no .env.example: "
        f"{sorted(faltantes)}"
    )

    # COMPOSE_PROFILES é lida pela CLI do Docker, não interpolada no YAML.
    sem_consumidor = no_template - no_compose - {"COMPOSE_PROFILES"}
    assert not sem_consumidor, (
        "variáveis do .env.example não são consumidas pelo deploy: "
        f"{sorted(sem_consumidor)}"
    )


def test_toda_variavel_do_env_example_pode_ser_encontrada_no_setup():
    """O nome completo precisa ser pesquisável; abreviação esconde configuração."""
    guia = SETUP.read_text(encoding="utf-8")
    ausentes = sorted(set(_valores_do_env_example()) - {
        chave for chave in _valores_do_env_example() if chave in guia
    })
    assert not ausentes, (
        "variáveis do .env.example ausentes do SETUP.md: "
        f"{ausentes}"
    )


def test_defaults_do_env_example_formam_um_settings_de_producao_valido():
    """Além de documentadas, strings, números, booleanos e fuso devem parsear."""
    kwargs = {
        chave: valor
        for chave, valor in _valores_do_env_example().items()
        if chave in Settings.model_fields
    }
    # Somente os campos marcados como obrigatórios recebem valores seguros de
    # validação; todo o restante vem literalmente do template versionado.
    kwargs.update(
        DATABASE_URL="postgresql://cf4:validation-only@db/controle_financeiro",
        SECRET_KEY="validation-only-0123456789abcdef",
        SUPERADMIN_EMAIL="admin@example.com",
        FRONTEND_URL="https://app.example.com",
        ALLOWED_HOSTS="app.example.com",
    )

    config = Settings(_env_file=None, **kwargs)
    assert config.APP_ENV == "production"
    assert config.COOKIE_SECURE is True
    assert config.IOF_INTERNATIONAL_CARD_RATE > 0


@pytest.mark.parametrize("diretorio", ("backend", "frontend"))
def test_contexto_docker_exclui_toda_a_familia_env(diretorio):
    """O .gitignore não protege o contexto enviado ao daemon/build remoto."""
    dockerignore = COMPOSE.parent / diretorio / ".dockerignore"
    regras = {
        linha.strip()
        for linha in dockerignore.read_text(encoding="utf-8").splitlines()
        if linha.strip() and not linha.lstrip().startswith("#")
    }
    assert ".env*" in regras, (
        f"{dockerignore} precisa excluir .env, .env.local, .env.production etc."
    )


@pytest.mark.parametrize(
    "variavel",
    (
        "APP_TIMEZONE",
        "DB_POOL_SIZE",
        "DB_MAX_OVERFLOW",
        "DB_POOL_TIMEOUT_SECONDS",
        "DB_POOL_RECYCLE_SECONDS",
        "SQL_ECHO",
        "EXCHANGE_RATE_TIMEOUT_SECONDS",
    ),
)
def test_cron_recebe_os_ajustes_operacionais_que_usa(variavel):
    """API e tarefas agendadas não podem obedecer a ambientes diferentes."""
    backend = _ambiente_do_servico("backend")
    cron = _ambiente_do_servico("cron")
    assert cron.get(variavel) == backend[variavel], (
        f"cron não recebe o mesmo {variavel} do backend"
    )


def test_variaveis_obrigatorias_nao_tem_padrao_silencioso():
    """`SECRET_KEY` e `SUPERADMIN_EMAIL` param o `up`, não assumem um valor.

    Um padrão aqui seria pior que a ausência: o stack subiria com uma chave
    conhecida ou sem administrador, e o operador só descobriria depois.
    """
    ambiente = _ambiente_do_servico("backend")
    for obrigatoria in ("SECRET_KEY", "SUPERADMIN_EMAIL", "POSTGRES_PASSWORD"):
        if obrigatoria in ambiente:
            assert ":?" in ambiente[obrigatoria], (
                f"{obrigatoria} precisa usar `${{{obrigatoria}:?mensagem}}` "
                "para o compose recusar subir sem ela"
            )


def test_cron_carrega_o_mesmo_settings_e_precisa_das_mesmas_obrigatorias():
    """O `cron` importa o `Settings` do backend — e morre no import sem elas."""
    ambiente = _ambiente_do_servico("cron")
    for obrigatoria in ("SECRET_KEY", "SUPERADMIN_EMAIL"):
        assert obrigatoria in ambiente, (
            f"o serviço `cron` valida {obrigatoria} no import e reiniciaria em laço"
        )


def test_todo_script_do_cron_existe():
    """O laço do `cron` chama scripts por NOME — e um rename passa em silêncio.

    O serviço não é um `cron` de verdade: é um `while true; sleep 3600` que roda
    `python scripts/X.py || true`. O `|| true` existe para uma falha não derrubar
    o laço, e é justamente ele que esconde o script que não existe mais: o
    container segue de pé, o log não acusa nada, e a materialização (ou o aviso de
    vencimento, ou o expurgo) simplesmente deixa de acontecer.

    Nenhuma outra rede pega isto: a suíte não sobe container, o lint não lê YAML e
    o smoke só olha o comportamento da API.
    """
    texto = COMPOSE.read_text(encoding="utf-8")
    # Só o bloco do serviço `cron` — o backend também menciona scripts.
    referenciados = set(re.findall(r"python\s+(scripts/[\w./-]+\.py)", texto))
    assert referenciados, "nenhum script encontrado no compose — a regex quebrou?"

    raiz = Path(__file__).resolve().parents[1]
    faltando = sorted(s for s in referenciados if not (raiz / s).is_file())
    assert not faltando, (
        f"o compose chama script(s) que não existem: {faltando}. "
        "Com o `|| true` do laço, isso falha em silêncio para sempre."
    )


def test_a_materializacao_roda_antes_do_aviso_de_vencimento():
    """Ordem no laço do cron (ADR 0034): avisar exige que a conta exista.

    `materializar_ocorrencias.py` é quem cria a ocorrência do mês; invertida a
    ordem, a conta do dia 1º só seria avisada no dia 2 — e a de 1º de janeiro,
    nunca, porque o aviso do dia 31 de dezembro não a encontraria.
    """
    texto = COMPOSE.read_text(encoding="utf-8")
    materializa = texto.find("scripts/materializar_ocorrencias.py")
    avisa = texto.find("scripts/avisar_vencimentos.py")
    assert materializa != -1 and avisa != -1
    assert materializa < avisa, (
        "o cron avisa sobre vencimento ANTES de materializar as ocorrências"
    )
