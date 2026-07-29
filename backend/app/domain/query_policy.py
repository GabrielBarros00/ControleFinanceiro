"""Política única de status e moeda para consultas financeiras (ADR 0003/0006).

Toda agregação (dívidas, relatórios, forecast, total de fatura) usa ESTES
conjuntos — nunca filtros locais divergentes. É o que garante uma única
definição de "total do mês" no sistema inteiro.
"""
from typing import Optional

from app.models.transaction import TransactionStatus

# Realizado: entra em dívidas, relatórios e faturas
REALIZED_STATUSES = (
    TransactionStatus.confirmed,
    TransactionStatus.paid,
)

# Previsão: realizado + pendente (draft e cancelled nunca entram em nada)
FORECAST_STATUSES = (
    TransactionStatus.pending,
    TransactionStatus.confirmed,
    TransactionStatus.paid,
)

# Moeda-base PADRÃO. Desde a Onda 5 é configurável por workspace
# (Workspace.base_currency); este valor é só o fallback. Transações em outra
# moeda ficam FORA das agregações até existir taxa histórica congelada (ADR 0006).
BASE_CURRENCY = "BRL"


def workspace_base_currency(session, workspace_id: int) -> str:
    """Moeda-base do workspace (fallback BRL). Fonte única para todas as
    agregações — dívidas, relatórios, forecast e faturas usam a MESMA moeda."""
    from app.models.workspace import Workspace

    ws = session.get(Workspace, workspace_id)
    return (ws.base_currency if ws and ws.base_currency else BASE_CURRENCY)


class InvalidCurrencyCode(ValueError):
    """Código de moeda fora do formato ISO-4217 alfabético (3 letras)."""


def normalize_currency_code(value) -> str:
    """`" usd "` → `"USD"`; qualquer outra coisa levanta `InvalidCurrencyCode`.

    Duas razões para existir, as duas com histórico:

    1. O código desce até a URL da fonte de câmbio de mercado
       (`.../v1/currencies/{codigo}.json`). Sem validar, um parâmetro de query
       escolhia o CAMINHO de uma requisição que o servidor faz para fora.
    2. Um código inventado (`"NOTACURRENCY"`) era aceito e PERSISTIDO. Como toda
       agregação filtra `currency == base_currency`, o registro sumia de dívidas,
       relatórios, fatura e previsão sem nenhum aviso — o mesmo modo de falha do
       `"BRL"` literal que a auditoria anterior já tinha caçado.

    Primitiva pura (sem I/O): é usada pelo schema de entrada (vira 422 na borda),
    por `resolve_currency` e pelo `CurrencyService` (defesa em profundidade).
    """
    codigo = str(value or "").strip().upper()
    if len(codigo) != 3 or not codigo.isalpha() or not codigo.isascii():
        raise InvalidCurrencyCode(
            f"Moeda inválida: '{value}' — use um código ISO de 3 letras (ex.: USD)"
        )
    return codigo


def resolve_currency(session, workspace_id: int, currency: Optional[str]) -> str:
    """Moeda de um registro NOVO: a informada, senão a moeda-base do workspace.

    Os schemas de criação traziam `currency = "BRL"` fixo. Num workspace em outra
    moeda isso era duas falhas de uma vez: o import/bulk gravava tudo como "BRL"
    e as linhas sumiam de TODA agregação (que filtra `currency == base`); e o
    formulário, que manda "BRL" por default, fazia o backend tratar a despesa
    como estrangeira e "converter" com taxa 1.

    Também normaliza a caixa: a comparação com a base é igualdade de string, e um
    `"brl"` minúsculo cairia fora dos totais sem nenhum sinal.
    """
    bruta = (currency or "").strip()
    if not bruta:
        return workspace_base_currency(session, workspace_id)
    return normalize_currency_code(bruta)
