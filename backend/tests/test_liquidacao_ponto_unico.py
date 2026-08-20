"""Tripwire: nenhum caminho de criação de `Transaction` esquece o `settled_at`.

Mesmo espírito de `test_read_policy_coverage.py` e `test_model_registry.py`: uma
varredura que impede o esquecimento de reabrir um problema já resolvido.

Por que existe. `settled_at` é a data em que o dinheiro saiu (ADR 0029), e o modo
de falha é **silencioso nos dois sentidos**:

- um caminho que esquece de liquidar cria uma despesa que some do caixa e aparece
  em Contas a pagar sem que ninguém tenha deixado de pagar nada — foi o que a
  importação de CSV faria com seis meses de extrato;
- um que liquida sempre reintroduz o defeito de origem, em que o boleto do dia 30
  debitava o caixa no dia 30 tivesse sido pago ou não.

Nenhum dos dois quebra um teste existente: o número simplesmente fica errado. Por
isso a regra é estrutural — **quem constrói uma `Transaction` decide, e a decisão
é visível na chamada**. `resolve_settled_at` é a forma normal de decidir; um
literal explícito também vale, para os pontos em que a resposta é constante.

Acrescentar um caminho novo custa uma linha. Esquecê-lo custa um número errado que
ninguém percebe.
"""
import ast
from pathlib import Path

APP = Path(__file__).resolve().parents[1] / "app"

#: Como um caminho de criação declara a decisão. Qualquer um destes basta.
_FORMAS_DE_DECIDIR = ("resolve_settled_at", "settled_at")


def _construcoes_de_transaction():
    """`(arquivo, linha, fonte)` de cada `Transaction(...)` construída em `app/`.

    AST e não regex: `Transaction(` aparece em anotação de tipo, em `isinstance`
    e em comentário, e nenhum desses é uma construção.
    """
    for arquivo in sorted(APP.rglob("*.py")):
        try:
            arvore = ast.parse(arquivo.read_text(encoding="utf-8"))
        except SyntaxError:  # pragma: no cover - arquivo quebrado falha em outro lugar
            continue
        fonte = arquivo.read_text(encoding="utf-8").splitlines()
        for no in ast.walk(arvore):
            if not isinstance(no, ast.Call):
                continue
            if not isinstance(no.func, ast.Name) or no.func.id != "Transaction":
                continue
            trecho = "\n".join(fonte[no.lineno - 1 : no.end_lineno])
            yield arquivo.relative_to(APP.parent), no.lineno, trecho


def test_toda_transacao_nova_decide_a_liquidacao():
    construcoes = list(_construcoes_de_transaction())
    assert construcoes, (
        "a varredura não encontrou nenhuma construção de Transaction — "
        "o teste está olhando para o lugar errado e não protege nada"
    )

    sem_decisao = [
        f"{arquivo}:{linha}"
        for arquivo, linha, trecho in construcoes
        if not any(forma in trecho for forma in _FORMAS_DE_DECIDIR)
    ]

    assert not sem_decisao, (
        "Lançamento criado sem decidir a liquidação (ADR 0029):\n  "
        + "\n  ".join(sem_decisao)
        + "\n\nPasse `settled_at=resolve_settled_at(...)` — o ponto único em"
        "\n`app/domain/settlement.py` — ou um valor explícito quando a resposta"
        "\nfor constante (import é fato consumado, pagamento de parcela também)."
    )
