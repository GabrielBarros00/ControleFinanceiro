from datetime import datetime, UTC
from typing import Optional
from decimal import Decimal
from sqlalchemy import Index
from sqlmodel import SQLModel, Field, UniqueConstraint

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
    # NULL = renda PESSOAL (global): não pertence a workspace nenhum, aparece como
    # "minha renda" em todos os meus workspaces e é registrada uma única vez
    # (ADR 0019). Preenchido = renda DA CASA daquele workspace (aluguel de imóvel
    # compartilhado, receita conjunta).
    #
    # Antes era NOT NULL, e por isso o salário tinha de ser recadastrado em cada
    # workspace: quem criava um workspace novo via a própria renda zerada.
    workspace_id: Optional[int] = Field(default=None, foreign_key="workspace.id", index=True)
    # Dono/destinatário — é a identidade GLOBAL da renda, o que permite somá-la
    # por pessoa através dos workspaces.
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


class IncomeWorkspaceShare(SQLModel, table=True):
    """Renda PESSOAL que o dono decidiu somar ao orçamento de um workspace (ADR 0019).

    Compartilhar é ato explícito e reversível: por padrão a renda é privada e só
    entra no recorte pessoal do dono. Sem esta tabela, "renda global" significaria
    ou expor o salário de todo mundo em todo workspace, ou nunca poder compor a
    renda da casa — os dois extremos errados.

    A unique impede a linha duplicada que faria a renda ser contada duas vezes no
    total da casa.
    """
    __table_args__ = (
        UniqueConstraint("income_id", "workspace_id", name="uq_income_share_income_workspace"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    income_id: int = Field(foreign_key="income.id", index=True)
    workspace_id: int = Field(foreign_key="workspace.id", index=True)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
