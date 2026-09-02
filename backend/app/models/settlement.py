from datetime import datetime, UTC
from typing import Optional
from decimal import Decimal
from sqlmodel import SQLModel, Field


class Settlement(SQLModel, table=True):
    """Acerto de dívida registrado: from_user pagou amount para to_user.

    Entra no DebtService como ajuste do saldo líquido — é o que faz as
    dívidas da DebtsPage zerarem de fato.
    """

    id: Optional[int] = Field(default=None, primary_key=True)
    workspace_id: int = Field(foreign_key="workspace.id", index=True)
    from_user_id: int = Field(foreign_key="user.id", index=True)  # quem pagou (devedor)
    to_user_id: int = Field(foreign_key="user.id", index=True)    # quem recebeu (credor)
    amount: Decimal = Field(decimal_places=2, max_digits=20)
    note: Optional[str] = None
    # Mês (YYYY-MM) que este acerto quita quando registrado a partir do ledger
    # mensal ("Dívidas do mês"). None = acerto global (só afeta o balanço geral).
    billing_month: Optional[str] = Field(default=None, index=True)
    settled_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    # De/para qual CONTA o acerto se moveu (ADR 0034). Duas colunas, e não uma,
    # porque **cada lado só pode ser preenchido pelo seu dono**: quem registra o
    # acerto é o pagador (`can_write(from_user_id, …)`), a conta do credor é
    # invisível para ele (`personal_scope`), e declará-la violaria a regra que o
    # projeto já escreveu em `_validate_payer_accounts` — "você não pode declarar de
    # qual conta de outra pessoa saiu o dinheiro".
    #
    # Por isso `to_account_id` tem porta própria: `PUT /me/settlements/{id}/account`,
    # onde o gate é `to_user_id == current_user.id`. Enquanto ninguém preenche, o
    # movimento existe no caixa e aparece no contador de "sem conta" — que é a
    # resposta honesta, e não um palpite sobre a conta alheia.
    from_account_id: Optional[int] = Field(default=None, foreign_key="paymentaccount.id")
    to_account_id: Optional[int] = Field(default=None, foreign_key="paymentaccount.id")

    created_by_user_id: Optional[int] = Field(default=None, foreign_key="user.id")

    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    deleted_at: Optional[datetime] = None
