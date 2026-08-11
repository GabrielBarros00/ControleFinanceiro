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
