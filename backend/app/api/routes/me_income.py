"""Renda PESSOAL, avulsa e recorrente — sem workspace no caminho (ADR 0021).

Renda é da pessoa. Sempre foi, mas o cadastro morava em
`/workspaces/{id}/income` e isso tinha duas consequências que a auditoria pegou:

1. **A moeda vinha do workspace aberto.** `resolve_currency(session, workspace_id, …)`
   fazia a MESMA renda pessoal nascer em USD ou em BRL conforme a tela por onde
   foi criada — e depois entrar ou sair dos totais conforme a moeda de quem
   estivesse olhando. Aqui a moeda é a de relatório do dono.
2. **Existia renda "da casa"** (`scope="workspace"`), que sem modelo de
   beneficiários era creditada 100% a quem cadastrou no resultado pessoal: o
   aluguel recebido pelo casal aparecia inteiro para um só. Sem rateio, renda
   compartilhada mente; renda estritamente pessoal não tem o que ratear.

O gate é `get_current_user` e o recorte é `Income.user_id`. Não há papel nem
`financial_access` que alcance a renda de outra pessoa — salário é o dado mais
sensível do sistema.
"""
from datetime import UTC, date, datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlmodel import Session, select

from app.api.routes.auth import get_current_user
from app.db.session import get_session
from app.domain.access_policy import assert_owns, personal_scope
from app.domain.dates import InvalidMonth, month_bounds, parse_month
from app.domain.query_policy import resolve_personal_currency, user_report_currency
from app.domain.recurrence_rules import validate_frequency_fields as _validate_frequency_fields
from app.models.income import Income
from app.models.recurring import RecurrenceFrequency, RecurringIncome
from app.models.user import User
from app.schemas.common import DESCRIPTION_MAX, MAX_MONEY, NAME_MAX, OptionalCurrencyCode, TITLE_MAX
from app.schemas.income import IncomeCreate, IncomeRead, IncomeUpdate
from app.services.currency_service import ExchangeRateUnavailable
from app.services.exchange_rate_store import ExchangeRateStore
from app.services.recurring_service import (
    MATERIALIZE_SCOPES,
    RecurringIncomeService,
    RecurringMaterializationService,
)

router = APIRouter(prefix="/me", tags=["me-income"])


def _colecao(metodo: str, caminho: str, **kwargs):
    """Registra a rota de coleção COM e SEM barra final, sem redirecionar.

    O redirecionamento automático de barra do Starlette responde 307 — e o 307 é
    uma armadilha conhecida deste projeto: o cliente refaz a requisição para a
    URL nova e o **cookie de sessão não acompanha**, então `/me/income/` devolvia
    401 enquanto `/me/income` devolvia 200. Registrar os dois caminhos elimina o
    redirecionamento em vez de tentar sobreviver a ele.
    """
    def decorador(func):
        for p in (caminho, caminho + "/"):
            getattr(router, metodo)(
                p, **({**kwargs, "include_in_schema": False} if p.endswith("/") else kwargs)
            )(func)
        return func
    return decorador


def _convert_income_fields(
    session: Session, user_id: int, amount: Decimal, currency: Optional[str], received_at: datetime
) -> dict:
    """Renda em moeda estrangeira → moeda de relatório do dono, na data de
    recebimento (sem IOF — IOF é de compra no cartão). Devolve os campos a gravar;
    `{}` se já estiver na moeda de destino."""
    destino = user_report_currency(session, user_id)
    if not currency or currency == destino:
        return {}
    occ = received_at.date() if hasattr(received_at, "date") else received_at
    try:
        # rate_between: a taxa precisa ser moeda→DESTINO, e o store só guarda X→BRL
        rate, source = ExchangeRateStore.rate_between(session, currency, destino, occ)
    except ExchangeRateUnavailable as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    converted = (amount * rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return {
        "amount": converted,
        "currency": destino,
        "original_amount": amount,
        "original_currency": currency,
        "exchange_rate": rate,
        "rate_source": source,
    }


def _get_income_or_404(session: Session, income_id: int, user_id: int) -> Income:
    income = session.get(Income, income_id)
    if not income or income.deleted_at:
        raise HTTPException(status_code=404, detail="Renda não encontrada")
    assert_owns(income.user_id, user_id, detail="Renda não encontrada")
    return income


# ---------------------------------------------------------------------------
# Renda avulsa
# ---------------------------------------------------------------------------

@_colecao("post", "/income", response_model=IncomeRead)
def create_income(
    *,
    session: Session = Depends(get_session),
    income_in: IncomeCreate,
    current_user: User = Depends(get_current_user),
):
    data = income_in.model_dump()
    data["currency"] = resolve_personal_currency(session, current_user.id, income_in.currency)
    data.update(
        _convert_income_fields(
            session, current_user.id, income_in.amount, data["currency"], income_in.received_at
        )
    )
    db_income = Income(**data, user_id=current_user.id)
    session.add(db_income)
    session.commit()
    session.refresh(db_income)
    return db_income


@_colecao("get", "/income", response_model=List[IncomeRead])
def list_income(
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
    month: Optional[str] = None,  # YYYY-MM: recorta pela competência (received_at)
):
    # Materializa recorrências vencidas só quando o mês pedido é o corrente: a
    # materialização é sempre restrita ao mês de hoje, então em mês fechado seria
    # trabalho perdido (e não casaria com o filtro).
    agora = datetime.now(UTC)
    mes_corrente = f"{agora.year:04d}-{agora.month:02d}"
    if month is None or month == mes_corrente:
        RecurringMaterializationService.ensure_income_and_commit(session, current_user.id)

    statement = select(Income).where(
        Income.deleted_at.is_(None),
        personal_scope(Income.user_id, current_user.id),
    )

    # Filtro por DATA DE RECEBIMENTO — mesma competência de `/me/overview`.
    if month:
        # Mês inválido é ERRO, não "sem filtro". Antes o except engolia e a rota
        # devolvia o histórico INTEIRO como se fosse o mês pedido.
        try:
            ref = parse_month(month)
        except InvalidMonth as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        inicio, fim = month_bounds(ref)
        statement = statement.where(Income.received_at >= inicio, Income.received_at <= fim)

    return session.exec(statement.order_by(Income.received_at.desc())).all()


@router.put("/income/{income_id}", response_model=IncomeRead)
def update_income(
    income_id: int,
    income_in: IncomeUpdate,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    income = _get_income_or_404(session, income_id, current_user.id)

    fields_set = income_in.model_dump(exclude_unset=True)
    for key, value in fields_set.items():
        setattr(income, key, value)

    # Moeda: só re-converte se o PUT mexeu em valor OU moeda. Um PUT parcial que
    # NÃO toca em amount/currency preserva o original congelado — senão editar só
    # o título apagaria a proveniência ("era USD 100 @ 5,00").
    if "amount" in fields_set or "currency" in fields_set:
        conv = _convert_income_fields(
            session, current_user.id, income.amount, income.currency, income.received_at
        )
        if conv:
            for k, v in conv.items():
                setattr(income, k, v)
        else:
            income.original_amount = None
            income.original_currency = None
            income.exchange_rate = None
            income.rate_source = None

    income.updated_at = datetime.now(UTC)
    session.add(income)
    session.commit()
    session.refresh(income)
    return income


@router.delete("/income/{income_id}")
def delete_income(
    income_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    income = _get_income_or_404(session, income_id, current_user.id)
    income.deleted_at = datetime.now(UTC)
    session.add(income)
    session.commit()
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Renda recorrente
# ---------------------------------------------------------------------------

class RecurringIncomeCreate(BaseModel):
    title: str = Field(min_length=1, max_length=TITLE_MAX)
    description: Optional[str] = Field(default=None, max_length=DESCRIPTION_MAX)
    base_amount: Decimal = Field(gt=0, le=MAX_MONEY)
    # None = "não informada" → a rota resolve para a moeda de relatório do dono
    currency: OptionalCurrencyCode = None
    category: Optional[str] = Field(default=None, max_length=NAME_MAX)
    frequency: RecurrenceFrequency = RecurrenceFrequency.monthly
    interval: int = Field(default=1, ge=1)
    start_date: Optional[date] = None
    day_of_month: int = Field(default=1, ge=1, le=31)
    day_of_week: Optional[int] = Field(default=None, ge=0, le=6)
    month_of_year: Optional[int] = Field(default=None, ge=1, le=12)
    is_active: bool = True


class RecurringIncomeUpdate(BaseModel):
    title: Optional[str] = Field(default=None, min_length=1, max_length=TITLE_MAX)
    description: Optional[str] = Field(default=None, max_length=DESCRIPTION_MAX)
    base_amount: Optional[Decimal] = Field(default=None, gt=0, le=MAX_MONEY)
    currency: OptionalCurrencyCode = None
    category: Optional[str] = Field(default=None, max_length=NAME_MAX)
    frequency: Optional[RecurrenceFrequency] = None
    interval: Optional[int] = Field(default=None, ge=1)
    start_date: Optional[date] = None
    day_of_month: Optional[int] = Field(default=None, ge=1, le=31)
    day_of_week: Optional[int] = Field(default=None, ge=0, le=6)
    month_of_year: Optional[int] = Field(default=None, ge=1, le=12)
    is_active: Optional[bool] = None


def _get_template_or_404(session: Session, recurring_id: int, user_id: int) -> RecurringIncome:
    rec = session.get(RecurringIncome, recurring_id)
    if not rec:
        raise HTTPException(status_code=404, detail="Renda recorrente não encontrada")
    assert_owns(rec.user_id, user_id, detail="Renda recorrente não encontrada")
    return rec


def _check_materialize(scope: str) -> None:
    if scope not in MATERIALIZE_SCOPES:
        raise HTTPException(
            status_code=400, detail=f"materialize deve ser um de {list(MATERIALIZE_SCOPES)}"
        )


@_colecao("post", "/recurring-income", response_model=RecurringIncome)
def create_recurring_income(
    recurring_in: RecurringIncomeCreate,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
    materialize: str = Query(
        "current",
        description="Escopo da materialização com start_date retroativa: past | current | future",
    ),
):
    _check_materialize(materialize)
    _validate_frequency_fields(
        recurring_in.frequency, recurring_in.day_of_week, recurring_in.month_of_year,
        recurring_in.interval, recurring_in.start_date,
    )
    data = recurring_in.model_dump()
    data["currency"] = resolve_personal_currency(session, current_user.id, recurring_in.currency)
    db_rec = RecurringIncome(**data, user_id=current_user.id)
    session.add(db_rec)
    session.flush()
    RecurringMaterializationService.apply_scope(
        session, None, db_rec, materialize, is_income=True
    )
    session.commit()
    session.refresh(db_rec)
    return db_rec


@_colecao("get", "/recurring-income", response_model=List[RecurringIncome])
def list_recurring_income(
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    return session.exec(
        select(RecurringIncome).where(
            personal_scope(RecurringIncome.user_id, current_user.id)
        )
    ).all()


@router.post("/recurring-income/generate")
def generate_recurring_income(
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Materializa as rendas recorrentes do mês corrente (idempotente)."""
    created = RecurringIncomeService.generate_due_income(
        session, current_user.id, date.today()
    )
    session.commit()
    return {"created": created}


@router.put("/recurring-income/{recurring_id}", response_model=RecurringIncome)
def update_recurring_income(
    recurring_id: int,
    recurring_in: RecurringIncomeUpdate,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
    materialize: str = Query(
        "current",
        description="Escopo da materialização com start_date retroativa: past | current | future",
    ),
):
    _check_materialize(materialize)
    db_rec = _get_template_or_404(session, recurring_id, current_user.id)

    for key, value in recurring_in.model_dump(exclude_unset=True).items():
        setattr(db_rec, key, value)
    _validate_frequency_fields(
        db_rec.frequency, db_rec.day_of_week, db_rec.month_of_year,
        db_rec.interval, db_rec.start_date,
    )
    db_rec.updated_at = datetime.now(UTC)
    session.add(db_rec)
    session.flush()
    # A edição vale do mês visualizado pra frente: reaplica ao lançamento do mês
    # corrente; meses anteriores (fechados) ficam congelados.
    RecurringIncomeService.sync_current_month_income(session, db_rec, date.today())
    RecurringMaterializationService.apply_scope(
        session, None, db_rec, materialize, is_income=True
    )
    session.commit()
    session.refresh(db_rec)
    return db_rec


@router.delete("/recurring-income/{recurring_id}")
def delete_recurring_income(
    recurring_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    db_rec = _get_template_or_404(session, recurring_id, current_user.id)

    # Desvincula rendas já geradas antes de excluir o template (evita violar FK)
    for inc in session.exec(
        select(Income).where(Income.recurring_income_id == recurring_id)
    ).all():
        inc.recurring_income_id = None
        session.add(inc)

    session.delete(db_rec)
    session.commit()
    return {"status": "ok"}
