"""O log fora da produção não pode parar nem derrubar o backend.

O `e2e-windows` caía de vez em quando em testes diferentes, com o backend
inteiro parado ~30 s. A cadeia, achada pelo log dos servidores no CI:

1. uma falha "best-effort" (a materialização preguiçosa da recorrência) chamava
   `logger.exception`;
2. com o `rich` instalado (vem com o pip-audit), o `ConsoleRenderer` desenhava o
   traceback com as variáveis locais de cada frame, e as molduras dele (╭─│) não
   existem no cp1252 do pipe no Windows: o log levantava `UnicodeEncodeError`, e
   a falha tratada virava 500;
3. o handler do 500 é `async` e loga de novo, agora DENTRO do event loop: o
   desenho levava dezenas de segundos num runner lento, e tudo esperava.

Produção usa `JSONRenderer` e não passa por nada disso.
"""
import io
import sys

import pytest
import structlog

from app.core.config import settings
from app.main import log_nunca_quebra_por_codificacao

MOLDURAS_DO_RICH = "╭╮╰╯│─"


@pytest.mark.skipif(settings.is_deployed, reason="em produção o log é JSON")
def test_traceback_do_log_de_dev_e_simples_sem_rich():
    renderer = structlog.get_config()["processors"][-1]
    assert isinstance(renderer, structlog.dev.ConsoleRenderer)

    def falha(dado_grande):
        raise ValueError("materialização falhou → aqui")

    try:
        falha(list(range(10_000)))
    except ValueError:
        exc_info = sys.exc_info()

    saida = renderer(None, "error", {"event": "materializacao_falhou", "exc_info": exc_info})

    assert "materialização falhou → aqui" in saida
    assert "Traceback (most recent call last)" in saida
    presentes = [c for c in MOLDURAS_DO_RICH if c in saida]
    assert not presentes, f"traceback desenhado pelo rich (molduras {presentes})"
    # O rich mostra os locais de cada frame; o traceback simples, não.
    assert "9999" not in saida


def test_saida_cp1252_nao_quebra_o_log():
    fluxo = io.TextIOWrapper(io.BytesIO(), encoding="cp1252", errors="strict", newline="\n")
    with pytest.raises(UnicodeEncodeError):
        fluxo.write("falhou → aqui\n")
        fluxo.flush()

    log_nunca_quebra_por_codificacao(fluxo)
    fluxo.write("falhou → aqui\n")
    fluxo.flush()
    assert fluxo.buffer.getvalue().endswith(b"falhou \\u2192 aqui\n")


def test_saida_sem_reconfigure_e_ignorada():
    """A captura do pytest (e outros substitutos da saída) não tem `reconfigure`."""
    log_nunca_quebra_por_codificacao(io.StringIO(), object())
