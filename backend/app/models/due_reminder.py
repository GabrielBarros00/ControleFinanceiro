"""O registro de "já avisei isto" (ADR 0033).

Esta tabela não guarda informação nova sobre dinheiro: tudo o que ela diz pode
ser recalculado. Ela existe por UM motivo, e vale escrevê-lo porque a tentação de
apagá-la num refactor é real — o job de aviso roda todo dia, e sem estado ele
reavisaria a mesma conta todos os dias até ela ser paga. É exatamente assim que
uma funcionalidade útil vira spam e acaba desligada.
"""
from datetime import date, datetime, UTC
from enum import Enum
from typing import Optional

from sqlalchemy import Column, Date, String, UniqueConstraint
from sqlmodel import SQLModel, Field


class ReminderSource(str, Enum):
    """De onde vem a obrigação avisada.

    Três, e não uma: notificar só `payable` entregaria algo que PARECE completo e
    não é, porque o `payables_service` exclui compra no cartão de propósito (quem
    se paga é a fatura). A conta que mais dói esquecer ficaria calada.
    """

    payable = "payable"          # lançamento em aberto (vence pela data do lançamento)
    statement = "statement"      # fatura de cartão (due_date real)
    financing = "financing"      # parcela de financiamento (due_date real)


class ReminderMilestone(str, Enum):
    """Quão perto o aviso foi disparado.

    Três marcos são o TETO por conta e por pessoa. Cada aviso a mais é fadiga, e
    fadiga transforma notificação em ruído que a pessoa desliga — perdendo junto
    o aviso que importava.
    """

    before = "before"      # D-N (N configurável pela pessoa)
    due = "due"            # no dia
    overdue = "overdue"    # D+1, uma única vez


class DueReminder(SQLModel, table=True):
    """Uma linha = "esta pessoa já foi avisada desta conta, neste marco"."""

    __table_args__ = (
        # O que impede a repetição. E é também o que torna seguro rodar o job
        # mais de uma vez no mesmo dia (restart de contêiner, deploy): a segunda
        # execução esbarra aqui e não escreve nada, sem precisar de trava.
        UniqueConstraint(
            "user_id", "source", "source_id", "milestone", "due_date",
            name="uq_duereminder_marco",
        ),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id", index=True)

    # String e não Enum nativo: valor novo num enum do Postgres exige `ALTER TYPE`
    # à mão, e nem o `create_all` da suíte nem o `alembic check` enxergam a
    # divergência. É a convenção que `User.platform_role` já documenta.
    source: ReminderSource = Field(sa_column=Column(String(20), nullable=False))
    source_id: int = Field(index=True)
    milestone: ReminderMilestone = Field(sa_column=Column(String(20), nullable=False))

    # A data de vencimento entra na CHAVE, e isso é deliberado: se a pessoa
    # corrigir a data da conta, o par muda e o aviso volta a valer. Uma conta que
    # se moveu merece ser avisada de novo — a chave sem a data trataria a
    # correção como "já avisei".
    due_date: date = Field(sa_column=Column(Date, nullable=False))

    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
