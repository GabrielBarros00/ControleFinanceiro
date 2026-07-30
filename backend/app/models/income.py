from datetime import datetime, UTC
from typing import Optional
from decimal import Decimal
from sqlalchemy import Index
from sqlmodel import SQLModel, Field

class IncomeBase(SQLModel):
    title: str = Field(index=True)
    description: Optional[str] = None
    amount: Decimal = Field(decimal_places=2, max_digits=20)
    currency: str = Field(default="BRL")
    received_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    category: Optional[str] = Field(default=None, index=True) # e.g., "Salary", "Freelance"

class Income(IncomeBase, table=True):
    # uq(recurring_income, received_at): uma entrada por ocorrência da renda
    # recorrente — espelha uq_recurring_occurrence do lado da despesa. Sem isto o
    # dedup era só lê-depois-escreve em Python, e a materialização preguiçosa
    # (que roda em ROTAS DE LEITURA) duplicava o salário sob concorrência.
    # A entrada excluída mantém a linha (tombstone) e ocupa a vaga → a unique
    # bloqueia recriação por natureza. Renda avulsa tem recurring_income_id NULL
    # e não colide (NULLs são distintos na unique).
    __table_args__ = (
        Index("uq_recurring_income_occurrence", "recurring_income_id", "received_at", unique=True),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    # Dono/destinatário — a identidade da renda, e o ÚNICO recorte que existe
    # (ADR 0021). Renda não tem workspace: é da pessoa, aparece no painel pessoal
    # dela e é cadastrada uma única vez para todos os workspaces.
    #
    # `workspace_id` existiu em duas encarnações erradas. NOT NULL fazia o salário
    # ter de ser recadastrado em cada workspace novo. Depois, nullable, marcava
    # "renda DA CASA" — mas sem modelo de beneficiários ela era creditada 100% a
    # quem cadastrou no resultado pessoal, então o aluguel recebido pelo casal
    # aparecia inteiro para um só. Sem rateio, renda compartilhada mente; com
    # renda estritamente pessoal, não há o que ratear.
    user_id: int = Field(foreign_key="user.id", index=True)

    # Origem recorrente (quando materializada por RecurringIncome) + mês de
    # competência para dedup/tombstone. None = renda avulsa.
    recurring_income_id: Optional[int] = Field(default=None, foreign_key="recurringincome.id", index=True)
    billing_month: Optional[str] = Field(default=None, index=True)  # YYYY-MM

    # Conversão de moeda: renda estrangeira é convertida para BRL na entrada (sem
    # IOF — IOF é de compra no cartão). None = renda nativa em BRL.
    original_amount: Optional[Decimal] = Field(default=None, decimal_places=2, max_digits=20)
    original_currency: Optional[str] = Field(default=None)
    exchange_rate: Optional[Decimal] = Field(default=None, decimal_places=6, max_digits=20)
    rate_source: Optional[str] = Field(default=None)

    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    deleted_at: Optional[datetime] = Field(default=None)
