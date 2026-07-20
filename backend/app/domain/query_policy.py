"""Política única de status e moeda para consultas financeiras (ADR 0003/0006).

Toda agregação (dívidas, relatórios, forecast, total de fatura) usa ESTES
conjuntos — nunca filtros locais divergentes. É o que garante uma única
definição de "total do mês" no sistema inteiro.
"""
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
