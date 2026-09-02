from datetime import datetime, date, UTC
from enum import Enum
from typing import Optional, List, TYPE_CHECKING
from decimal import Decimal
from sqlalchemy import JSON, Boolean, Column, Integer, false, true
from sqlmodel import SQLModel, Field, Relationship

from app.models.transaction import PaymentMethod

if TYPE_CHECKING:
    from app.models.transaction import Transaction

class RecurrenceFrequency(str, Enum):
    daily = "daily"
    weekly = "weekly"
    monthly = "monthly"
    yearly = "yearly"

class RecurringExpenseBase(SQLModel):
    title: str = Field(index=True)
    description: Optional[str] = None
    base_amount: Decimal = Field(decimal_places=2, max_digits=20)
    frequency: RecurrenceFrequency = Field(default=RecurrenceFrequency.monthly)
    # interval > 1 = "a cada N períodos" (personalizado); ancorado em start_date.
    # interval == 1 = preset (Diário/Semanal/Mensal/Anual), fase por day_of_* (legado).
    interval: int = Field(default=1, ge=1)
    start_date: Optional[date] = Field(default=None)
    # Fim da série (ADR 0030). `None` = sem fim, que era a ÚNICA opção antes:
    # uma mensalidade de faculdade paga por doze anos virava recorrência infinita
    # — sem "faltam 87 de 144", com a previsão projetando para sempre, e sem
    # parar de gerar sozinha no mês em que ela realmente acaba.
    end_date: Optional[date] = Field(default=None)
    day_of_month: int = Field(ge=1, le=31)  # monthly/yearly (preset)
    day_of_week: Optional[int] = Field(default=None, ge=0, le=6)  # weekly preset (0=segunda)
    month_of_year: Optional[int] = Field(default=None, ge=1, le=12)  # yearly preset
    is_active: bool = Field(default=True)

class RecurringExpense(RecurringExpenseBase, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    workspace_id: int = Field(foreign_key="workspace.id", index=True)
    created_by_user_id: Optional[int] = Field(default=None, foreign_key="user.id")

    # Snapshot completo (ADR 0012): a instância materializada nasce COMPLETA
    # (pagador + divisão + categoria + método + moeda), então entra em
    # dívidas/relatórios como qualquer despesa — sem isso a recorrência gerava
    # transação nua (REC-001).
    currency: str = Field(default="BRL")
    payment_method: Optional[PaymentMethod] = Field(default=None)
    # "Pagamento automático" (ADR 0029): débito em conta, Pix automático, qualquer
    # arranjo em que o dinheiro sai sozinho na data. A instância materializada
    # nasce LIQUIDADA e nunca aparece em Contas a pagar.
    #
    # Falso por padrão porque é o caso que o app errava: a materialização
    # preguiçosa criava a conta de luz no dia 10 e o caixa a debitava no mesmo
    # instante, tivesse ela sido paga ou não. Sem esta coluna, ligar o controle de
    # pagamento no espaço obrigaria a pessoa a confirmar todo mês o que o banco já
    # debita sozinho.
    auto_settle: bool = Field(
        default=False,
        sa_column=Column(Boolean, nullable=False, server_default=false()),
    )
    # Cartão da despesa fixa: sem ele, "assinatura no cartão" nascia solta e nunca
    # entrava numa fatura — a materialização roteia a instância para o statement
    # do ciclo da ocorrência (CreditCardService.get_or_create_statement).
    credit_card_id: Optional[int] = Field(default=None, foreign_key="creditcard.id")
    # Deslocamento de fatura do template (ADR 0032), herdado por toda ocorrência.
    # Uma assinatura cobrada perto do fechamento cai na fatura seguinte TODO mês
    # — é característica do cobrador, não acidente de um mês. Sem isto, a
    # correção teria de ser refeita à mão em cada instância materializada, e a
    # materialização é preguiçosa: a ocorrência do mês que vem nasceria errada de
    # novo, sozinha, quando alguém abrisse uma tela de leitura.
    statement_shift: int = Field(
        default=0,
        sa_column=Column(Integer, nullable=False, server_default="0"),
    )
    category_id: Optional[int] = Field(default=None, foreign_key="category.id")
    payer_user_id: Optional[int] = Field(default=None, foreign_key="user.id")
    # De qual conta a ocorrência sai (ADR 0034). O `split_snapshot` guarda só
    # user_id/método/valor, então sem esta coluna toda instância materializada
    # nascia sem conta e o débito automático não movia saldo nenhum — justamente
    # o caso em que a pessoa MENOS vai abrir o lançamento para declarar a conta.
    # Vale só quando `payer_user_id` é o dono da conta, e é validado na escrita.
    account_id: Optional[int] = Field(default=None, foreign_key="paymentaccount.id")
    # Lista de {user_id, split_method, input_value}; None → divisão 100% ao pagador
    split_snapshot: Optional[list] = Field(default=None, sa_column=Column(JSON))

    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    transactions: List["Transaction"] = Relationship(back_populates="recurring_expense")


class RecurringIncomeBase(SQLModel):
    title: str = Field(index=True)
    description: Optional[str] = None
    base_amount: Decimal = Field(decimal_places=2, max_digits=20)
    currency: str = Field(default="BRL")
    category: Optional[str] = Field(default=None, index=True)  # ex.: "Salário"
    frequency: RecurrenceFrequency = Field(default=RecurrenceFrequency.monthly)
    interval: int = Field(default=1, ge=1)  # "a cada N" períodos (N>1 = personalizado)
    start_date: Optional[date] = Field(default=None)  # âncora do intervalo (N>1)
    end_date: Optional[date] = Field(default=None)  # fim da série; None = sem fim
    day_of_month: int = Field(default=1, ge=1, le=31)  # monthly/yearly (preset)
    day_of_week: Optional[int] = Field(default=None, ge=0, le=6)  # weekly preset (0=segunda)
    month_of_year: Optional[int] = Field(default=None, ge=1, le=12)  # yearly preset
    is_active: bool = Field(default=True)


class RecurringIncome(RecurringIncomeBase, table=True):
    """Template de renda recorrente. Materializa entradas Income mensais
    (RecurringIncomeService.generate_due_income), espelhando RecurringExpense
    mas sem divisão/pagador (renda é pessoal)."""
    id: Optional[int] = Field(default=None, primary_key=True)
    # Sem workspace (ADR 0021): o salário é da pessoa e o template vale em todos
    # os workspaces dela. Cada ocorrência materializada nasce igualmente pessoal.
    user_id: int = Field(foreign_key="user.id", index=True)

    # Espelho do `auto_settle` da despesa, com o padrão INVERTIDO — e de propósito
    # (ADR 0034). Renda recorrente é tipicamente salário: chegou a data, entrou. Com
    # o padrão em falso, atualizar o app faria todo mundo ter de confirmar à mão o
    # que sempre contou sozinho, e o `cash_in` de quem não confirmasse iria a zero.
    #
    # Desligar é para renda INCERTA — freelance, aluguel recebido, comissão: aí a
    # ocorrência fica em "A receber" e vira "atrasada" quando a data passa, até
    # alguém apertar "Recebi". Ligado ou não, a ocorrência NUNCA nasce recebida
    # antes da data: `resolve_income_settled_at` é o ponto único que decide.
    auto_confirm: bool = Field(
        default=True,
        sa_column=Column(Boolean, nullable=False, server_default=true()),
    )
    # Conta em que a ocorrência cai quando é confirmada (ADR 0034). `None` = não
    # declarada: a renda conta no caixa, mas não move saldo de conta nenhuma.
    account_id: Optional[int] = Field(default=None, foreign_key="paymentaccount.id")

    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
