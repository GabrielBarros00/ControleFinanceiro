from datetime import datetime, UTC
from decimal import Decimal
from enum import Enum
from typing import Optional

from sqlalchemy import Column, String
from sqlmodel import SQLModel, Field

from app.domain.dates import local_day


class ImportRowStatus(str, Enum):
    imported = "imported"    # virou transação
    ignored = "ignored"      # o usuário escolheu não importar
    duplicate = "duplicate"  # fingerprint já importado antes (idempotente)
    skipped = "skipped"      # inválida (valor/data)


#: `ImportBatch.kind`: despesas de um espaço (ADR 0008) ou extrato de uma conta (ADR 0037).
KIND_EXPENSES = "expenses"
KIND_ACCOUNT = "account"

#: `ImportRow.classification` num extrato de conta (ADR 0037).
CLASSIFICATIONS = ("expense", "income", "transfer", "statement_payment")


class ImportBatch(SQLModel, table=True):
    """Um lote de importação de CSV (ADR 0008): guarda o resultado por linha
    para auditoria e para tornar a reimportação idempotente.

    Extrato de conta (ADR 0037): `kind='account'`, `account_id` preenchido e SEM
    espaço — o lote é da pessoa; cada linha de despesa leva o próprio espaço."""
    id: Optional[int] = Field(default=None, primary_key=True)
    workspace_id: Optional[int] = Field(default=None, foreign_key="workspace.id", index=True)
    kind: str = Field(
        default=KIND_EXPENSES,
        sa_column=Column(String(16), nullable=False, server_default=KIND_EXPENSES),
    )
    account_id: Optional[int] = Field(default=None, foreign_key="paymentaccount.id", index=True)
    filename: Optional[str] = None
    created_by_user_id: Optional[int] = Field(default=None, foreign_key="user.id")
    total_rows: int = Field(default=0)
    imported_count: int = Field(default=0)
    ignored_count: int = Field(default=0)
    duplicate_count: int = Field(default=0)
    skipped_count: int = Field(default=0)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ImportRow(SQLModel, table=True):
    """Decisão e resultado de uma linha do lote. O fingerprint (workspace, data,
    centavos, título) é o que garante idempotência: reimportar não duplica."""
    id: Optional[int] = Field(default=None, primary_key=True)
    batch_id: int = Field(foreign_key="importbatch.id", index=True)
    #: O espaço da DESPESA. Nulo nas linhas de extrato de conta que não são
    #: despesa (renda, transferência, pagamento de fatura são da pessoa).
    workspace_id: Optional[int] = Field(default=None, foreign_key="workspace.id", index=True)
    account_id: Optional[int] = Field(default=None, foreign_key="paymentaccount.id", index=True)
    #: 'in' (entrou na conta) ou 'out' (saiu). Nulo nos lotes de despesa.
    direction: Optional[str] = Field(default=None, max_length=3)
    classification: Optional[str] = Field(default=None, max_length=20)
    #: O id que o banco dá à linha (quando dá): deduplica melhor que a impressão digital.
    external_id: Optional[str] = Field(default=None, max_length=120, index=True)
    line: Optional[int] = None
    title: str
    amount: Decimal = Field(decimal_places=2, max_digits=20)
    transaction_date: datetime
    fingerprint: str = Field(index=True)
    status: ImportRowStatus
    transaction_id: Optional[int] = Field(default=None, foreign_key="transaction.id")
    income_id: Optional[int] = Field(default=None, foreign_key="income.id")
    transfer_id: Optional[int] = Field(default=None, foreign_key="accounttransfer.id")
    statement_payment_id: Optional[int] = Field(default=None, foreign_key="statementpayment.id")
    reason: Optional[str] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


def compute_fingerprint(workspace_id: int, when: datetime, amount: Decimal, title: str) -> str:
    """Chave de deduplicação: mesma data (dia), valor em centavos e título.

    O dia é o LOCAL. Com `when.date()` a chave saía do dia em UTC, e a mesma
    linha de extrato produzia fingerprints diferentes conforme a hora gravada —
    a idempotência do ADR 0008 dependia de todo mundo ancorar a data igual.
    Continua compatível com o que já está gravado: para as linhas de import a
    âncora cai no meio do dia, e meio-dia ±12h não troca de data.
    """
    cents = int((amount * 100).to_integral_value())
    return f"{workspace_id}:{local_day(when).isoformat()}:{cents}:{title.strip().lower()}"


def compute_account_fingerprint(account_id: int, when: datetime, direction: str, amount: Decimal, title: str) -> str:
    """A chave de uma linha de extrato de CONTA (ADR 0037): conta, dia local,
    sentido, centavos e título. O sentido entra porque a mesma quantia pode sair
    e voltar no mesmo dia (uma compra estornada) — duas linhas, não duplicata."""
    cents = int((amount * 100).to_integral_value())
    return f"acc{account_id}:{local_day(when).isoformat()}:{direction}:{cents}:{title.strip().lower()}"
