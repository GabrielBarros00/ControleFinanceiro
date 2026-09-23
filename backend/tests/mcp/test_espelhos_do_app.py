"""Os valores que as tools aceitam acompanham os do app.

Os `Literal` das tools são escritos à mão (o schema JSON que o agente lê precisa
da lista explícita). Quando o app ganha um valor novo, por exemplo uma forma de
pagamento, a tool continuaria recusando esse valor sem avisar ninguém: o
agente ouviria "valor inválido" para algo que o app aceita. Os gates de rota
(`test_capability_map.py`) não enxergam isso, porque a rota é a mesma e só o
enum cresceu.

Quando este teste reprovar, atualize o `Literal` e a descrição da tool, e
confira se o comportamento novo precisa de mais alguma coisa no MCP (ver
"Mudou uma funcionalidade? Confira o MCP" no CONTRIBUTING.md).
"""
from __future__ import annotations

from enum import Enum
from typing import get_args

import pytest

from app.mcp.tools.planning_write import FrequencyIn, RecurringCreateIn
from app.mcp.tools.transactions import PaymentMethodIn, StatusIn
from app.models.recurring import RecurrenceFrequency
from app.models.transaction import PaymentMethod, TransactionStatus
from app.services.recurring_service import MATERIALIZE_SCOPES


def _valores(enum: type[Enum]) -> set[str]:
    return {m.value for m in enum}


@pytest.mark.parametrize(("espelho", "do_app"), [
    (PaymentMethodIn, _valores(PaymentMethod)),
    (StatusIn, _valores(TransactionStatus)),
    (FrequencyIn, _valores(RecurrenceFrequency)),
    (RecurringCreateIn.model_fields["materialize"].annotation, set(MATERIALIZE_SCOPES)),
], ids=["forma de pagamento", "status do lançamento", "frequência", "materialize da recorrência"])
def test_literal_da_tool_tem_exatamente_os_valores_do_app(espelho, do_app):
    da_tool = set(get_args(espelho))
    assert da_tool, "o espelho não é um Literal (a varredura ficaria cega)"
    assert da_tool == do_app, (
        f"a tool aceita {sorted(da_tool)} e o app aceita {sorted(do_app)}: "
        f"falta na tool {sorted(do_app - da_tool)}, sobra na tool {sorted(da_tool - do_app)}"
    )
