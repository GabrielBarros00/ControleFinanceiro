"""Quando uma renda foi RECEBIDA — ponto único de decisão (ADR 0034).

Espelho de `app/domain/settlement.py`, que faz o mesmo do lado da despesa desde o
ADR 0029. `Income.settled_at` é o dia em que o dinheiro caiu; `None` significa "ainda
não caiu" — a renda existe, aparece como prevista, entra na projeção, e **não** entra
no saldo nem no `cash_in`.

Antes desta separação `Income` tinha uma data só. O salário do dia 30 ou não existia
até o dia 30, ou já contava como recebido no dia 1º; não havia terceira opção, e a
primeira era a que o app fazia — a renda recorrente era materializada para o mês
inteiro e somava no caixa desde o primeiro dia.

A regra mora aqui, e não espalhada nos caminhos que constroem `Income`, pelo mesmo
motivo do ADR 0029: o modo de falha é silencioso **nos dois sentidos**. Um caminho que
esquece de liquidar some com a renda do caixa; um que liquida sempre reintroduz o
defeito que este módulo veio fechar. Nenhum dos dois quebra teste existente, e por isso
`tests/test_liquidacao_renda_ponto_unico.py` varre o AST de `app/` e falha quando uma
construção nova de `Income` não decide `settled_at`.
"""
from datetime import date, datetime
from typing import Optional

from app.domain.dates import local_day, today_local


def resolve_income_settled_at(
    *,
    received_at: datetime,
    explicit: Optional[bool] = None,
    hoje: Optional[date] = None,
) -> Optional[datetime]:
    """A data de recebimento com que a renda nasce, ou `None` (a receber).

    `hoje` existe para quem JÁ TEM uma referência de hoje na mão — a
    materialização recebe `today` como parâmetro, e deixá-la consultar o relógio
    de novo aqui criaria duas fontes de "hoje" dentro da mesma operação. É o mesmo
    modo de falha que `domain/dates` documenta: as duas discordam na virada do dia,
    e a ocorrência nasce recebida ou prevista conforme qual delas foi lida.

    As regras, nesta ordem — a ordem importa:

    1. **Data no futuro → `None`, sempre.** Vence até o `explicit`: nem o
       `auto_confirm` de um salário afirma que o dinheiro de 30/09 já entrou quando
       ainda é dia 1º. Esta é a regra que o pedido do dono resume em "NÃO aumentar
       saldo atual antes da data".
    2. **`explicit` informado** decide o resto. É o `auto_confirm` do template de
       renda recorrente (ligado por padrão: renda recorrente é tipicamente salário)
       e o "já recebi" de um formulário.
    3. **Padrão**: recebida, porque a data já chegou. Vale para o que uma PESSOA
       digitou — quem lança a renda de ontem está anotando o que aconteceu.

    A data de recebimento é `received_at`, não "agora": lançar hoje o salário de
    ontem tem de mover o caixa de ONTEM, senão o extrato de um mês fechado muda
    conforme a hora em que alguém lembrou de digitar.
    """
    if local_day(received_at) > (hoje or today_local()):
        return None
    if explicit is not None:
        return received_at if explicit else None
    return received_at


def income_status(
    *,
    settled_at: Optional[datetime],
    cancelled_at: Optional[datetime],
    received_at: datetime,
) -> str:
    """O estado que a tela mostra: `cancelled | received | overdue | expected`.

    DERIVADO, nunca armazenado. Guardar um enum ao lado das duas colunas daria dois
    registros do mesmo fato, e eles divergem na primeira escrita que esquecer um dos
    dois — o defeito que o projeto já pagou para aprender com `status`/`settled_at`.

    A ordem das perguntas é a ordem da precedência: uma renda cancelada continua com
    a data prevista, e uma recebida com atraso não é "atrasada", é recebida.
    """
    if cancelled_at is not None:
        return "cancelled"
    if settled_at is not None:
        return "received"
    if local_day(received_at) < today_local():
        return "overdue"
    return "expected"
