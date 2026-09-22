from datetime import datetime, UTC, date
from enum import Enum
from typing import Optional, List
from decimal import Decimal
from sqlalchemy import Index, text
from sqlmodel import SQLModel, Field, Relationship, UniqueConstraint

class AmortizationMethod(str, Enum):
    SAC = "SAC"
    PRICE = "PRICE"

class FinancingStatus(str, Enum):
    active = "active"
    settled = "settled"
    simulated = "simulated"

class FinancingBase(SQLModel):
    title: str = Field(index=True)
    description: Optional[str] = None
    total_amount: Decimal = Field(decimal_places=2, max_digits=20)
    # Taxa MENSAL (ex.: 0.01 = 1% a.m.) — é como FinancingService a aplica.
    interest_rate: Decimal = Field(decimal_places=6, max_digits=10)
    start_date: date
    installments_count: int = Field(ge=1)
    method: AmortizationMethod = Field(default=AmortizationMethod.SAC)
    status: FinancingStatus = Field(default=FinancingStatus.active)
    currency: str = Field(default="BRL")

class Financing(FinancingBase, table=True):
    """Financiamento de UMA pessoa (ADR 0021).

    Sem `workspace_id`: a dívida é de quem assinou o contrato e aparece nos
    Compromissos pessoais dele, em qualquer workspace de que participe. O
    `created_by_user_id` de antes descrevia autoria; aqui a coluna passa a
    declarar PROPRIEDADE, que é o que a política de leitura precisa saber.
    """
    id: Optional[int] = Field(default=None, primary_key=True)
    owner_user_id: int = Field(foreign_key="user.id", index=True)

    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    deleted_at: Optional[datetime] = Field(default=None)

    schedule: List["AmortizationInstallment"] = Relationship(back_populates="financing")

class AmortizationInstallmentBase(SQLModel):
    installment_number: int
    due_date: date
    principal_amount: Decimal = Field(decimal_places=2, max_digits=20)
    interest_amount: Decimal = Field(decimal_places=2, max_digits=20)
    total_amount: Decimal = Field(decimal_places=2, max_digits=20)
    remaining_balance: Decimal = Field(decimal_places=2, max_digits=20)
    is_paid: bool = Field(default=False)

class AmortizationInstallment(AmortizationInstallmentBase, table=True):
    __table_args__ = (
        UniqueConstraint("financing_id", "installment_number", name="uq_amortization_financing_number"),
        Index(
            "ix_amortizationinstallment_conta",
            "account_id",
            "paid_at",
            sqlite_where=text("account_id IS NOT NULL AND is_paid"),
            postgresql_where=text("account_id IS NOT NULL AND is_paid"),
        ),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    financing_id: int = Field(foreign_key="financing.id", index=True)
    paid_at: Optional[datetime] = None
    # O pagamento aconteceu ANTES de o app existir para esta pessoa (ADR 0023).
    #
    # `is_paid` sozinho não distingue dois fatos diferentes: "paguei e não lancei a
    # despesa" — que é saída de caixa de verdade, e entra no extrato pela fonte 4 —
    # de "este contrato já existia quando eu o cadastrei, e estas parcelas eu já
    # tinha pago". A segunda é a quitação em lote (`settle-past`), e contá-la como
    # caixa reescrevia o extrato e o resultado de meses FECHADOS: quitar doze
    # parcelas fazia aparecer uma saída retroativa em cada um dos doze meses.
    #
    # Por isso o marcador mora na parcela e não na rota: `CashFlowService._parcelas`
    # precisa saber, meses depois, que aquela linha nunca foi movimento de caixa
    # deste app. `unpay` o limpa junto com `is_paid` — reabrir a parcela desfaz
    # também a afirmação sobre a origem dela.
    paid_outside_app: bool = Field(default=False)
    # De qual conta a parcela saiu (ADR 0034). Mora AQUI e só aqui, mesmo quando o
    # pagamento também vira uma `Transaction` no workspace: nesse caso a rota COPIA
    # o valor para `TransactionPayer.account_id`, e a parcela deixa de ser fonte de
    # caixa (a dedup `~ja_lancada` a suprime). Gravar nos dois lugares como fontes
    # independentes daria duas verdades — e ao desmarcar o pagamento da despesa a
    # parcela voltaria carregando uma conta congelada que pode não ser a atual.
    account_id: Optional[int] = Field(default=None, foreign_key="paymentaccount.id")

    financing: Financing = Relationship(back_populates="schedule")
