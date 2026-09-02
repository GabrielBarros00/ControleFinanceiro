"""Tripwire: nenhum caminho de criação de `Income` esquece o `settled_at`.

Irmão de `test_liquidacao_ponto_unico.py`, e pelo mesmo motivo. `Income.settled_at`
é o dia em que o dinheiro CAIU (ADR 0034); `received_at`, apesar do nome, virou a
competência — quando era para cair. O modo de falha é silencioso nos dois sentidos:

- um caminho que esquece de liquidar cria uma renda que some do `cash_in` e do
  saldo, e fica presa em "a receber" sem que ninguém tenha deixado de receber nada.
  Foi o que a migração desta onda teria feito com o histórico inteiro se não fosse o
  backfill;
- um que liquida sempre reintroduz o defeito de origem, em que o salário do dia 30
  materializado no dia 1º já contava como dinheiro em mãos desde o começo do mês.

Nenhum dos dois quebra um teste existente — o número simplesmente fica errado.

**Nota sobre a forma da chamada.** A varredura casa por substring no trecho fonte, e
por isso um construtor no formato `Income(**data, ...)` passaria em falso: a string
`settled_at` nunca apareceria ali, ainda que a chave estivesse dentro do dicionário.
`me_income.create_income` constrói com `settled_at=` explícito exatamente por isso —
e o teste abaixo verifica que nenhuma construção usa `**` sem também nomear a
decisão, para a brecha não voltar por descuido.
"""
import ast
from pathlib import Path

APP = Path(__file__).resolve().parents[1] / "app"

#: Como um caminho de criação declara a decisão. Qualquer um destes basta.
_FORMAS_DE_DECIDIR = ("resolve_income_settled_at", "settled_at")


def _construcoes_de_income():
    """`(arquivo, linha, fonte, tem_kwargs)` de cada `Income(...)` em `app/`.

    AST e não regex: `Income(` aparece em anotação de tipo e em nome de outra
    classe (`RecurringIncome`, `IncomeCreate`), e nenhum desses é uma construção
    da tabela.
    """
    for arquivo in sorted(APP.rglob("*.py")):
        texto = arquivo.read_text(encoding="utf-8")
        try:
            arvore = ast.parse(texto)
        except SyntaxError:  # pragma: no cover - arquivo quebrado falha em outro lugar
            continue
        fonte = texto.splitlines()
        for no in ast.walk(arvore):
            if not isinstance(no, ast.Call):
                continue
            if not isinstance(no.func, ast.Name) or no.func.id != "Income":
                continue
            trecho = "\n".join(fonte[no.lineno - 1 : no.end_lineno])
            tem_kwargs = any(k.arg is None for k in no.keywords)
            yield arquivo.relative_to(APP.parent), no.lineno, trecho, tem_kwargs


def test_toda_renda_nova_decide_o_recebimento():
    construcoes = list(_construcoes_de_income())
    assert construcoes, (
        "a varredura não encontrou nenhuma construção de Income — "
        "o teste está olhando para o lugar errado e não protege nada"
    )

    sem_decisao = [
        f"{arquivo}:{linha}"
        for arquivo, linha, trecho, _ in construcoes
        if not any(forma in trecho for forma in _FORMAS_DE_DECIDIR)
    ]

    assert not sem_decisao, (
        "Renda criada sem decidir o recebimento (ADR 0034):\n  "
        + "\n  ".join(sem_decisao)
        + "\n\nPasse `settled_at=resolve_income_settled_at(...)` — o ponto único em"
        "\n`app/domain/income_settlement.py` — ou um valor explícito quando a"
        "\nresposta for constante."
    )


def test_a_decisao_e_visivel_mesmo_com_kwargs_desempacotados():
    """`Income(**data)` esconderia a decisão da varredura acima.

    Não é hipótese: `create_income` monta os campos num dicionário e o
    desempacota. Se `settled_at` entrasse por dentro do `data`, o gate acima
    continuaria verde para sempre enquanto o valor pudesse estar ausente — um
    portão que aprova tudo é pior que portão nenhum, porque dá a impressão de
    proteção.
    """
    cegas = [
        f"{arquivo}:{linha}"
        for arquivo, linha, trecho, tem_kwargs in _construcoes_de_income()
        if tem_kwargs and not any(forma in trecho for forma in _FORMAS_DE_DECIDIR)
    ]
    assert not cegas, (
        "Construção de Income com `**` e sem nomear a decisão:\n  "
        + "\n  ".join(cegas)
        + "\n\nNomeie `settled_at=` na chamada, ainda que o resto venha de um dict."
    )
