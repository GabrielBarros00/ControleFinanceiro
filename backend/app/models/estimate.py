from datetime import datetime, UTC
from typing import Optional
from decimal import Decimal
from sqlalchemy import Index
from sqlmodel import SQLModel, Field

class MonthlyEstimateBase(SQLModel):
    # category (texto) fica como rótulo legado; category_id (FK) é a referência
    # real desde a Onda 5 — orçamento por categoria de verdade (BUD-001)
    category: str = Field(index=True)
    amount: Decimal = Field(decimal_places=2, max_digits=20)
    month: str = Field(index=True) # Format YYYY-MM
    description: Optional[str] = None

class MonthlyEstimate(MonthlyEstimateBase, table=True):
    # Um orçamento por (workspace, DONO, categoria, mês). A idempotência da rota
    # chaveava pelo RÓTULO de texto, não pela FK — com texto vazio/constante
    # todos os orçamentos do mês viravam um só. O dono entrou na chave quando o
    # orçamento ganhou escopo: a meta da casa e a meta pessoal de cada membro
    # convivem na mesma categoria e no mesmo mês.
    __table_args__ = (
        Index(
            "uq_estimate_workspace_owner_category_month",
            "workspace_id", "owner_user_id", "category_id", "month",
            unique=True,
        ),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    workspace_id: int = Field(foreign_key="workspace.id", index=True)
    # Quem CRIOU (trilha). Não confundir com owner_user_id, que é o escopo.
    user_id: int = Field(foreign_key="user.id", index=True)
    # Escopo da meta: NULL = meta da CASA (o workspace inteiro); preenchido =
    # meta PESSOAL daquele membro, comparada contra a parte dele nos splits.
    #
    # O Início mostrava a despesa PESSOAL do usuário contra o orçamento da CASA:
    # num workspace de duas pessoas com rateio igual a barra marcava ~50% quando
    # a casa já tinha consumido 100% — e os Relatórios, que comparavam casa com
    # casa, mostravam outro número para o mesmo orçamento.
    owner_user_id: Optional[int] = Field(default=None, foreign_key="user.id", index=True)
    category_id: Optional[int] = Field(default=None, foreign_key="category.id", index=True)

    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    deleted_at: Optional[datetime] = Field(default=None)
