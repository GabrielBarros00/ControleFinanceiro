"""O que falta ao ledger para virar saldo: abertura, ajuste e transferência (ADR 0034).

O app já tem um ledger de movimentos — `CashFlowService`, seis fontes derivadas das
tabelas de origem, cada linha com a sua data efetiva e a sua moeda. Criar aqui uma
tabela que REPLICASSE esses movimentos daria duas fontes para o mesmo fato, e o saldo
passaria a depender de qual delas fosse lida. Por isso este módulo guarda **só o que
não tem origem em lugar nenhum**:

- **abertura** (`opening_balance`): "em 01/09 eu tinha R$ 8.350,42". Não é renda, não é
  despesa e não é resultado de mês nenhum — é o ponto de partida contábil, e é a data
  dele que define a partir de quando os movimentos passam a contar (o que veio antes já
  está DENTRO do número informado, e recontá-lo seria dobrá-lo);
- **ajuste** (`adjustment`): a diferença entre o que o app calcula e o que o banco
  mostra. Vira uma linha datada, com motivo, que o extrato explica — e não uma reescrita
  do passado para o saldo "fechar" (o histórico tem de continuar explicável);
- **transferência**: dinheiro que muda de conta sem entrar nem sair do bolso.

**A transferência é UMA linha com as duas pernas.** Duas linhas ligadas por um id
comum dependeriam de a aplicação lembrar de escrever as duas; com uma linha só, perna
órfã deixa de ser representável — a garantia é do esquema, não do cuidado de quem
programa. É o mesmo raciocínio do `CHECK` de conta diferente logo abaixo.

**Nada daqui é fonte do `CashFlowService`.** Transferência entre contas minhas não é
entrada nem saída de caixa (infla os dois lados e o `net_cash` acerta por acidente), e
ajuste não é renda. Eles movem SALDO, que é outra pergunta — ver `ACCOUNT_SOURCES`.
"""
from datetime import datetime, UTC
from decimal import Decimal
from enum import Enum
from typing import Optional

from sqlalchemy import CheckConstraint, Index, text
from sqlmodel import Field, SQLModel


class AccountEntryKind(str, Enum):
    opening_balance = "opening_balance"  # ponto de partida contábil da conta
    adjustment = "adjustment"            # conciliação com o extrato do banco


class AccountEntry(SQLModel, table=True):
    """Abertura ou ajuste de uma conta — as duas coisas que não vêm de outra tabela."""

    __table_args__ = (
        # UMA abertura viva por conta. Sem isto "a data do saldo inicial" não é bem
        # definida, e a regra que corta os movimentos anteriores a ela fica sem lado
        # direito: duas aberturas dariam dois saldos igualmente defensáveis.
        Index(
            "uq_accountentry_abertura",
            "account_id",
            unique=True,
            sqlite_where=text("kind = 'opening_balance' AND deleted_at IS NULL"),
            postgresql_where=text("kind = 'opening_balance' AND deleted_at IS NULL"),
        ),
        Index(
            "ix_accountentry_conta",
            "account_id",
            "occurred_at",
            sqlite_where=text("deleted_at IS NULL"),
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    account_id: int = Field(foreign_key="paymentaccount.id", index=True)
    kind: AccountEntryKind = Field(default=AccountEntryKind.adjustment)

    #: COM SINAL, como `TransactionAdjustment.amount`: positivo entra, negativo sai.
    #: Um par (valor absoluto, direção) exigiria que toda soma lembrasse do sinal.
    amount: Decimal = Field(decimal_places=2, max_digits=20)
    #: Instante da abertura/ajuste. Data civil escrita com `civil_instant` — meia-noite
    #: crua recuaria um dia em fuso negativo (ADR 0025).
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    description: Optional[str] = Field(default=None)

    created_by_user_id: Optional[int] = Field(default=None, foreign_key="user.id")
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    deleted_at: Optional[datetime] = Field(default=None)


class AccountTransfer(SQLModel, table=True):
    """Dinheiro que muda de conta. As duas pernas numa linha só.

    Moedas diferentes são declaradas, nunca convertidas em silêncio (ADR 0006/0015):
    quem transfere informa o valor que SAIU e o que ENTROU, e `exchange_rate` fica só
    como proveniência — validada contra os dois valores, para três campos não poderem
    discordar entre si.
    """

    __table_args__ = (
        CheckConstraint(
            "from_account_id != to_account_id", name="ck_accounttransfer_contas_distintas"
        ),
        Index(
            "ix_accounttransfer_origem",
            "from_account_id",
            "occurred_at",
            sqlite_where=text("deleted_at IS NULL"),
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index(
            "ix_accounttransfer_destino",
            "to_account_id",
            "occurred_at",
            sqlite_where=text("deleted_at IS NULL"),
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    from_account_id: int = Field(foreign_key="paymentaccount.id", index=True)
    to_account_id: int = Field(foreign_key="paymentaccount.id", index=True)

    from_amount: Decimal = Field(decimal_places=2, max_digits=20)
    to_amount: Decimal = Field(decimal_places=2, max_digits=20)
    #: `None` quando as duas contas estão na mesma moeda (aí os valores são iguais).
    exchange_rate: Optional[Decimal] = Field(default=None, decimal_places=6, max_digits=20)

    occurred_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    note: Optional[str] = Field(default=None)

    created_by_user_id: Optional[int] = Field(default=None, foreign_key="user.id")
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    deleted_at: Optional[datetime] = Field(default=None)
