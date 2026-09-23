"""Entrada e saída do acerto registrado DENTRO de um espaço.

Moraram em `api/routes/settlements.py` até o ADR 0035: o comando de criação
passou para `services/commands/settlements.py` (compartilhado com o MCP) e um
serviço não importa de rota. Mesmos nomes, então o OpenAPI não muda.
"""
from datetime import datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, Field

from app.schemas.common import DESCRIPTION_MAX, MAX_MONEY


class SettlementCreate(BaseModel):
    from_user_id: int
    to_user_id: int
    amount: Decimal = Field(gt=0, le=MAX_MONEY)
    note: Optional[str] = Field(default=None, max_length=DESCRIPTION_MAX)
    # YYYY-MM: quando vem do ledger mensal, quita a dívida daquele mês
    billing_month: Optional[str] = None
    settled_at: Optional[datetime] = None
    #: De qual conta o PAGADOR tirou o dinheiro (ADR 0034). Só o lado dele — a
    #: conta do credor é invisível para quem registra, e declará-la violaria a
    #: regra de `_validate_payer_accounts`: "você não pode declarar de qual conta
    #: de outra pessoa saiu o dinheiro". O credor tem porta própria em
    #: `PUT /me/settlements/{id}/account`.
    from_account_id: Optional[int] = None


class SettlementRead(BaseModel):
    id: int
    from_user_id: int
    to_user_id: int
    amount: Decimal
    note: Optional[str]
    billing_month: Optional[str]
    settled_at: datetime
    created_by_user_id: Optional[int]
