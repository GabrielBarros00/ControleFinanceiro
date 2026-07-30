from typing import Literal, Optional
from datetime import datetime
from decimal import Decimal
from pydantic import BaseModel, Field

from app.schemas.common import DESCRIPTION_MAX, MAX_MONEY, OptionalCurrencyCode, TITLE_MAX

class IncomeBase(BaseModel):
    title: str = Field(min_length=1, max_length=TITLE_MAX)
    description: Optional[str] = Field(default=None, max_length=DESCRIPTION_MAX)
    amount: Decimal
    # Default de LEITURA apenas (IncomeRead herda daqui e a coluna é NOT NULL).
    # Em qualquer schema de ENTRADA sobrescreva com `Optional[str] = None` e
    # resolva na rota com `resolve_currency` — ver IncomeCreate. Um "BRL" fixo na
    # entrada faz um workspace em outra moeda tratar toda renda como estrangeira.
    currency: str = "BRL"
    received_at: datetime
    category: Optional[str] = None

class IncomeCreate(IncomeBase):
    amount: Decimal = Field(gt=0, le=MAX_MONEY)
    # None = "não informada" → a rota resolve para a moeda-base do workspace
    currency: OptionalCurrencyCode = None
    # Escopo (ADR 0019). `personal` é o DEFAULT porque é a verdade do caso comum:
    # salário é da pessoa e vale em todos os workspaces dela. `workspace` é a
    # exceção — renda que pertence à casa (aluguel de imóvel do casal).
    scope: Literal["personal", "workspace"] = "personal"
    # Workspaces com que a renda pessoal é compartilhada, ou seja, para cujo
    # orçamento ela CONTRIBUI. Vazio = privada (o default seguro).
    shared_with_workspace_ids: list[int] = Field(default_factory=list)

class IncomeUpdate(BaseModel):
    scope: Optional[Literal["personal", "workspace"]] = None
    shared_with_workspace_ids: Optional[list[int]] = None
    title: Optional[str] = Field(default=None, min_length=1, max_length=TITLE_MAX)
    description: Optional[str] = Field(default=None, max_length=DESCRIPTION_MAX)
    amount: Optional[Decimal] = Field(default=None, gt=0, le=MAX_MONEY)
    currency: OptionalCurrencyCode = None
    received_at: Optional[datetime] = None
    category: Optional[str] = None

class IncomeRead(IncomeBase):
    id: int
    # None = renda PESSOAL (não pertence a workspace nenhum) — ADR 0019
    workspace_id: Optional[int] = None
    user_id: int
    # Derivados na rota, para a tela não precisar inferir do `workspace_id`
    scope: Literal["personal", "workspace"] = "personal"
    shared_with_workspace_ids: list[int] = Field(default_factory=list)
    recurring_income_id: Optional[int] = None
    billing_month: Optional[str] = None
    original_amount: Optional[Decimal] = None
    original_currency: Optional[str] = None
    exchange_rate: Optional[Decimal] = None
    rate_source: Optional[str] = None
    created_at: datetime
    updated_at: datetime
