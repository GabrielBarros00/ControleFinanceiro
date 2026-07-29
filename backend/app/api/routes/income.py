from datetime import datetime, UTC
from decimal import Decimal, ROUND_HALF_UP
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from app.db.session import get_session
from app.domain.dates import InvalidMonth, month_bounds, parse_month
from app.domain.query_policy import resolve_currency, workspace_base_currency
from app.models.workspace import WorkspaceMembership, WorkspaceRole, role_level
from app.models.income import Income
from app.schemas.income import IncomeCreate, IncomeRead, IncomeUpdate
from app.api.deps import get_workspace_membership, require_role
from app.services.currency_service import ExchangeRateUnavailable
from app.services.exchange_rate_store import ExchangeRateStore
from app.services.event_service import publish_event
from app.services.recurring_service import RecurringMaterializationService

router = APIRouter(prefix="/workspaces/{workspace_id}/income", tags=["income"])


def _convert_income_fields(
    session: Session, workspace_id: int, amount: Decimal, currency: Optional[str], received_at: datetime
) -> dict:
    """Renda em moeda estrangeira → moeda-base do workspace na data de recebimento
    (sem IOF). Devolve os campos a gravar (amount e currency na base + original_*);
    {} se já for base."""
    base = workspace_base_currency(session, workspace_id)
    if not currency or currency == base:
        return {}
    occ = received_at.date() if hasattr(received_at, "date") else received_at
    try:
        # rate_between: a taxa precisa ser moeda→BASE, e o store só guarda X→BRL
        rate, source = ExchangeRateStore.rate_between(session, currency, base, occ)
    except ExchangeRateUnavailable as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    converted = (amount * rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return {
        "amount": converted,
        "currency": base,
        "original_amount": amount,
        "original_currency": currency,
        "exchange_rate": rate,
        "rate_source": source,
    }


def _get_income_or_404(session: Session, workspace_id: int, income_id: int) -> Income:
    income = session.get(Income, income_id)
    if not income or income.workspace_id != workspace_id or income.deleted_at:
        raise HTTPException(status_code=404, detail="Renda não encontrada")
    return income


def _check_income_ownership(membership: WorkspaceMembership, income: Income):
    if (
        role_level(membership.role) < role_level(WorkspaceRole.admin)
        and income.user_id != membership.user_id
    ):
        raise HTTPException(status_code=403, detail="Você só pode alterar as próprias rendas")


@router.post("/", response_model=IncomeRead)
def create_income(
    workspace_id: int,
    *,
    session: Session = Depends(get_session),
    income_in: IncomeCreate,
    membership: WorkspaceMembership = Depends(require_role(WorkspaceRole.member))
):
    data = income_in.model_dump()
    # Moeda ausente = a do workspace (nunca "BRL" fixo — ver resolve_currency)
    data["currency"] = resolve_currency(session, workspace_id, income_in.currency)
    # Renda estrangeira: converte para a moeda-base na entrada, guardando o original
    data.update(_convert_income_fields(session, workspace_id, income_in.amount, data["currency"], income_in.received_at))
    db_income = Income(
        **data,
        workspace_id=workspace_id,
        user_id=membership.user_id
    )
    session.add(db_income)
    session.flush()
    publish_event(session, workspace_id, "income.created", "income", db_income.id, membership.user_id)
    session.commit()
    session.refresh(db_income)
    return db_income


@router.get("/", response_model=List[IncomeRead])
def list_income(
    workspace_id: int,
    session: Session = Depends(get_session),
    membership: WorkspaceMembership = Depends(get_workspace_membership),
    month: Optional[str] = None,  # YYYY-MM: recorta pela competência (received_at)
):
    # Materializa recorrências vencidas só quando o mês pedido é o corrente: a
    # materialização é sempre restrita ao mês de hoje, então em mês fechado seria
    # trabalho perdido (e não casaria com o filtro). Sem mês = comportamento antigo.
    now = datetime.now(UTC)
    current_month = f"{now.year:04d}-{now.month:02d}"
    if month is None or month == current_month:
        RecurringMaterializationService.ensure_and_commit(session, workspace_id)

    statement = select(Income).where(
        Income.workspace_id == workspace_id,
        Income.deleted_at.is_(None),
    )

    # Filtro por mês pela DATA DE RECEBIMENTO — mesma competência do
    # ReportService.get_summary (o "Sua receita" do Início). received_at é a fonte
    # de verdade da renda; a avulsa não tem billing_month.
    if month:
        # Mês inválido é ERRO, não "sem filtro". Antes o except engolia e a rota
        # devolvia o histórico INTEIRO como se fosse o mês pedido — com o total
        # do cabeçalho errado e nenhum sinal para o usuário.
        try:
            ref = parse_month(month)
        except InvalidMonth as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        start, end = month_bounds(ref)
        statement = statement.where(
            Income.received_at >= start,
            Income.received_at <= end,
        )

    statement = statement.order_by(Income.received_at.desc())
    incomes = session.exec(statement).all()
    return incomes


@router.put("/{income_id}", response_model=IncomeRead)
def update_income(
    workspace_id: int,
    income_id: int,
    income_in: IncomeUpdate,
    session: Session = Depends(get_session),
    membership: WorkspaceMembership = Depends(require_role(WorkspaceRole.member))
):
    income = _get_income_or_404(session, workspace_id, income_id)
    _check_income_ownership(membership, income)

    fields_set = income_in.model_dump(exclude_unset=True)
    for key, value in fields_set.items():
        setattr(income, key, value)

    # Moeda: só re-converte se o PUT mexeu em valor OU moeda. Um PUT parcial que
    # NÃO toca em amount/currency preserva o original congelado — senão editar só
    # o título apagaria a proveniência ("era USD 100 @ 5,00"). Pela UI o form
    # sempre reenvia amount+currency do original, então o round-trip segue igual;
    # edição efetiva em BRL (currency=base) limpa o original.
    if "amount" in fields_set or "currency" in fields_set:
        conv = _convert_income_fields(session, workspace_id, income.amount, income.currency, income.received_at)
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
    publish_event(session, workspace_id, "income.updated", "income", income.id, membership.user_id)
    session.commit()
    session.refresh(income)
    return income


@router.delete("/{income_id}")
def delete_income(
    workspace_id: int,
    income_id: int,
    session: Session = Depends(get_session),
    membership: WorkspaceMembership = Depends(require_role(WorkspaceRole.member))
):
    income = _get_income_or_404(session, workspace_id, income_id)
    _check_income_ownership(membership, income)

    income.deleted_at = datetime.now(UTC)
    session.add(income)
    publish_event(session, workspace_id, "income.deleted", "income", income.id, membership.user_id)
    session.commit()
    return {"status": "ok"}
