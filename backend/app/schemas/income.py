from typing import Optional
from datetime import date, datetime
from decimal import Decimal
from pydantic import ConfigDict, BaseModel, Field, model_validator

from app.domain.income_settlement import income_status
from app.models.recurring import RecurrenceFrequency
from app.schemas.common import DESCRIPTION_MAX, MAX_MONEY, NAME_MAX, OptionalCurrencyCode, TITLE_MAX

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
    # Campo desconhecido é RECUSADO (422), não ignorado: a importação de extrato
    # mandava `category_id` que o schema não tinha, o Pydantic o jogava fora calado e
    # a despesa ficava sem categoria (auditoria 2026-09-26, C1/A1).
    model_config = ConfigDict(extra="forbid")
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
    # Campo desconhecido é RECUSADO (422), não ignorado: a importação de extrato
    # mandava `category_id` que o schema não tinha, o Pydantic o jogava fora calado e
    # a despesa ficava sem categoria (auditoria 2026-09-26, C1/A1).
    model_config = ConfigDict(extra="forbid")
    title: Optional[str] = Field(default=None, min_length=1, max_length=TITLE_MAX)
    description: Optional[str] = Field(default=None, max_length=DESCRIPTION_MAX)
    amount: Optional[Decimal] = Field(default=None, gt=0, le=MAX_MONEY)
    currency: OptionalCurrencyCode = None
    received_at: Optional[datetime] = None
    category: Optional[str] = None
    account_id: Optional[int] = None


class IncomeReceiveRequest(BaseModel):
    """Confirmação de recebimento: quando caiu e em qual conta (ADR 0034)."""
    # Campo desconhecido é RECUSADO (422), não ignorado: a importação de extrato
    # mandava `category_id` que o schema não tinha, o Pydantic o jogava fora calado e
    # a despesa ficava sem categoria (auditoria 2026-09-26, C1/A1).
    model_config = ConfigDict(extra="forbid")
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


class RecurringIncomeCreate(BaseModel):
    # Campo desconhecido é RECUSADO (422), não ignorado: a importação de extrato
    # mandava `category_id` que o schema não tinha, o Pydantic o jogava fora calado e
    # a despesa ficava sem categoria (auditoria 2026-09-26, C1/A1).
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=TITLE_MAX)
    description: Optional[str] = Field(default=None, max_length=DESCRIPTION_MAX)
    base_amount: Decimal = Field(gt=0, le=MAX_MONEY)
    # None = "não informada" → a rota resolve para a moeda de relatório do dono
    currency: OptionalCurrencyCode = None
    category: Optional[str] = Field(default=None, max_length=NAME_MAX)
    frequency: RecurrenceFrequency = RecurrenceFrequency.monthly
    interval: int = Field(default=1, ge=1)
    start_date: Optional[date] = None
    # Fim da série (ADR 0030) — espelho do que a despesa recorrente ganhou. Uma
    # bolsa de dois anos e um aluguel recebido por prazo determinado têm fim, e
    # sem a coluna eles projetavam renda para sempre na previsão.
    end_date: Optional[date] = None
    # "Depois de N ocorrências" (ADR 0030), como na despesa recorrente: o editor
    # de recorrência é o mesmo e oferece a opção, mas o campo não existia aqui —
    # era descartado calado, e a renda "por 12 meses" nunca terminava. Achado ao
    # ligar o `extra="forbid"` (auditoria 2026-09-26, A1). Vira `end_date`.
    end_after_occurrences: Optional[int] = Field(default=None, ge=1, le=600)
    day_of_month: int = Field(default=1, ge=1, le=31)
    day_of_week: Optional[int] = Field(default=None, ge=0, le=6)
    month_of_year: Optional[int] = Field(default=None, ge=1, le=12)
    is_active: bool = True
    # Ligado por padrão (ADR 0034): renda recorrente é tipicamente salário, e o
    # comportamento de sempre foi "chegou a data, entrou". Desligue para renda
    # incerta — freela, aluguel recebido —, que aí a ocorrência fica em "A receber".
    auto_confirm: bool = True
    account_id: Optional[int] = None


class RecurringIncomeUpdate(BaseModel):
    # Campo desconhecido é RECUSADO (422), não ignorado: a importação de extrato
    # mandava `category_id` que o schema não tinha, o Pydantic o jogava fora calado e
    # a despesa ficava sem categoria (auditoria 2026-09-26, C1/A1).
    model_config = ConfigDict(extra="forbid")
    title: Optional[str] = Field(default=None, min_length=1, max_length=TITLE_MAX)
    description: Optional[str] = Field(default=None, max_length=DESCRIPTION_MAX)
    base_amount: Optional[Decimal] = Field(default=None, gt=0, le=MAX_MONEY)
    currency: OptionalCurrencyCode = None
    category: Optional[str] = Field(default=None, max_length=NAME_MAX)
    frequency: Optional[RecurrenceFrequency] = None
    interval: Optional[int] = Field(default=None, ge=1)
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    # "Depois de N ocorrências" (ADR 0030), como na despesa recorrente: o editor
    # de recorrência é o mesmo e oferece a opção, mas o campo não existia aqui —
    # era descartado calado, e a renda "por 12 meses" nunca terminava. Achado ao
    # ligar o `extra="forbid"` (auditoria 2026-09-26, A1). Vira `end_date`.
    end_after_occurrences: Optional[int] = Field(default=None, ge=1, le=600)
    day_of_month: Optional[int] = Field(default=None, ge=1, le=31)
    day_of_week: Optional[int] = Field(default=None, ge=0, le=6)
    month_of_year: Optional[int] = Field(default=None, ge=1, le=12)
    is_active: Optional[bool] = None
    auto_confirm: Optional[bool] = None
    account_id: Optional[int] = None
