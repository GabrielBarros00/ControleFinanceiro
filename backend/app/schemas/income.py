from typing import Optional
from datetime import date, datetime
from decimal import Decimal
from pydantic import BaseModel, Field, model_validator

from app.domain.income_settlement import income_status
from app.schemas.common import DESCRIPTION_MAX, MAX_MONEY, OptionalCurrencyCode, TITLE_MAX

class IncomeBase(BaseModel):
    title: str = Field(min_length=1, max_length=TITLE_MAX)
    description: Optional[str] = Field(default=None, max_length=DESCRIPTION_MAX)
    amount: Decimal
    # Default de LEITURA apenas (IncomeRead herda daqui e a coluna é NOT NULL).
    # Em qualquer schema de ENTRADA sobrescreva com `Optional[str] = None` e
    # resolva na rota com `resolve_personal_currency` — ver IncomeCreate. Um "BRL"
    # fixo na entrada faz a renda de quem relata noutra moeda nascer estrangeira.
    currency: str = "BRL"
    received_at: datetime
    category: Optional[str] = None

class IncomeCreate(IncomeBase):
    amount: Decimal = Field(gt=0, le=MAX_MONEY)
    # None = "não informada" → a rota resolve para `User.report_currency` (ADR 0021)
    currency: OptionalCurrencyCode = None
    # Em qual conta o dinheiro caiu (ADR 0034). Opcional: registrar a renda sem
    # dizer onde ela caiu continua sendo legítimo — só não move saldo.
    account_id: Optional[int] = None
    # "Já recebi?" — vence o palpite pela data em `resolve_income_settled_at`.
    # `None` deixa a regra decidir: data passada = recebida, futura = prevista.
    received: Optional[bool] = None

class IncomeUpdate(BaseModel):
    title: Optional[str] = Field(default=None, min_length=1, max_length=TITLE_MAX)
    description: Optional[str] = Field(default=None, max_length=DESCRIPTION_MAX)
    amount: Optional[Decimal] = Field(default=None, gt=0, le=MAX_MONEY)
    currency: OptionalCurrencyCode = None
    received_at: Optional[datetime] = None
    category: Optional[str] = None
    account_id: Optional[int] = None


class IncomeReceiveRequest(BaseModel):
    """Confirmação de recebimento: quando caiu e em qual conta (ADR 0034)."""
    #: Dia CIVIL do recebimento. Ausente = hoje. Vira instante por `civil_instant`,
    #: nunca por `datetime.combine` — meia-noite local ancorada em UTC jogaria o
    #: recebimento do dia 1º para o caixa do mês anterior.
    received_on: Optional[date] = None
    account_id: Optional[int] = None

class IncomeRead(IncomeBase):
    id: int
    # Renda é sempre pessoal (ADR 0021): não há `workspace_id` nem `scope` — os
    # dois existiam para a "renda da casa", que sem rateio creditava o valor
    # inteiro a quem cadastrou.
    user_id: int
    recurring_income_id: Optional[int] = None
    billing_month: Optional[str] = None
    original_amount: Optional[Decimal] = None
    original_currency: Optional[str] = None
    exchange_rate: Optional[Decimal] = None
    rate_source: Optional[str] = None

    # --- Caixa e estado (ADR 0034) --------------------------------------------
    #: Quando o dinheiro CAIU. `None` = a receber. `received_at`, apesar do nome,
    #: é a competência — quando era para entrar.
    settled_at: Optional[datetime] = None
    cancelled_at: Optional[datetime] = None
    account_id: Optional[int] = None
    #: `expected | received | overdue | cancelled`, DERIVADO das colunas acima por
    #: `domain/income_settlement.income_status`. Não é coluna: guardá-lo ao lado
    #: das duas datas daria dois registros do mesmo fato, e eles divergiriam na
    #: primeira escrita que esquecesse um dos dois.
    status: str = "received"

    created_at: datetime
    updated_at: datetime

    @model_validator(mode="after")
    def _deriva_status(self):
        """Calcula `status` a partir das datas, em TODA serialização.

        Aqui, e não em cada rota: `IncomeRead` sai de cinco lugares diferentes, e um
        deles esquecer de preencher o campo devolveria "received" (o default) para
        uma renda que ninguém recebeu — o pior valor possível para errar.
        """
        object.__setattr__(
            self,
            "status",
            income_status(
                settled_at=self.settled_at,
                cancelled_at=self.cancelled_at,
                received_at=self.received_at,
            ),
        )
        return self
