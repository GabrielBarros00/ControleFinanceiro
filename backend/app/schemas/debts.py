"""Contrato tipado de "quem deve a quem" — o balanço e o ledger do mês da CASA.

As duas rotas devolviam `Dict[str, Any]`, e o preço estava escrito no próprio
frontend: `use-monthly-debts.ts` declarava cinco interfaces à mão com o aviso
"valores vêm da rota Dict[str, Any] (jsonable_encoder → número), mas coagimos com
Number() para ser robusto a número OU string" — ou seja, o cliente não sabia o
formato do que recebia. E as duas declarações manuais divergiam entre si:
`DebtsPage.tsx` dizia `amount: string`, `use-monthly-debts.ts` dizia `number`.

Com schema, o formato passa a ser **string decimal** (Pydantic serializa
`Decimal` assim), que é o que `docs/API.md` já exige de todo valor monetário —
essas rotas é que estavam fora da regra, emitindo float pelo `jsonable_encoder`.

**Os tipos vêm de `schemas/overview.py`, não são redefinidos aqui.** A camada
global (ADR 0027) já modelava este mesmo ledger, e `WorkspaceMonthlyLedger` diz
em voz alta que é "o mesmo payload de `/{ws}/debts/monthly`, campo a campo
idêntico de propósito". Duplicar as classes produziria dois schemas homônimos no
OpenAPI, que o gerador desambigua como `app__schemas__debts__LedgerMember` — e o
frontend voltaria a ter duas formas de ler a mesma coisa, que é exatamente o
defeito original.

**Recorte, não filtro tardio.** O ledger é calculado INTEIRO e recortado na
saída (ADR 0018): filtrar antes mudaria o pareamento guloso e daria valor errado.
Por isso não há campos "opcionais por acesso" — o que a pessoa não pode ver
simplesmente não vem na lista.
"""
from decimal import Decimal
from typing import List

from pydantic import BaseModel

from app.schemas.overview import (
    DebtRow,
    LedgerExpense,
    LedgerMember,
    LedgerSettlement,
    LedgerTotals,
)

#: Uma dívida já simplificada: A paga B, um valor só. Mesma linha que o
#: `DebtService` devolve nas duas camadas.
DebtRead = DebtRow

__all__ = [
    "DebtRead",
    "LedgerExpense",
    "LedgerMember",
    "LedgerSettlement",
    "LedgerTotals",
    "MonthlyLedgerRead",
]


class MonthlyLedgerRead(BaseModel):
    """O mês fechado da casa: quem pagou, quem deve, o que já foi acertado.

    Parcelas aparecem só no mês delas (o recorte é por `billing_month`). É o
    payload que `WorkspaceMonthlyLedger` espelha na camada global, mais os
    campos que só a tela global precisa (nome da casa, papel, `people`).
    """
    month: str
    base_currency: str
    members: List[LedgerMember] = []
    #: Já descontados os acertos com este `billing_month` — por isso zera quando
    #: o mês é quitado, ao contrário do balanço global de `/debts`.
    net_debts: List[DebtRow] = []
    expenses: List[LedgerExpense] = []
    #: Acompanha o que está LISTADO em `settlements`, não o total da casa: senão
    #: a tela mostra "acertado R$ X" com uma lista que não soma X.
    settled_total: Decimal
    settlements: List[LedgerSettlement] = []
    totals: LedgerTotals
