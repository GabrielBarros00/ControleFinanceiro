from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select
from typing import List, Any, Dict, Optional
from datetime import date

from app.db.session import get_session
from app.domain.dates import InvalidMonth, parse_month
from app.models.workspace import WorkspaceMembership, WorkspaceRole
from app.models.estimate import MonthlyEstimate
from app.schemas.estimate import MonthlyEstimateCreate, MonthlyEstimateRead
from app.domain.query_policy import workspace_base_currency
from app.services.currency_service import ExchangeRateUnavailable
from app.services.exchange_rate_store import ExchangeRateStore
from app.services.forecast_service import ForecastService
from app.services.report_service import ReportService
from app.services.recurring_service import RecurringMaterializationService
from app.api.deps import get_workspace_membership, require_role
from app.services.event_service import publish_event

router = APIRouter(prefix="/workspaces/{workspace_id}/analytics", tags=["analytics"])


def _parse_month(month: Optional[str]) -> date:
    """`YYYY-MM` → primeiro dia do mês; vazio → hoje. 400 no formato errado."""
    try:
        return parse_month(month)
    except InvalidMonth as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/summary", response_model=Dict[str, Any])
def get_summary(
    workspace_id: int,
    month: Optional[str] = None,
    session: Session = Depends(get_session),
    membership: WorkspaceMembership = Depends(get_workspace_membership)
):
    target_date = _parse_month(month)

    # Recorrências vencidas do mês corrente entram sozinhas (lazy accrual),
    # sempre no mês real — visualizar outro mês não materializa retroativo.
    RecurringMaterializationService.ensure_and_commit(session, workspace_id)
    return ReportService.get_summary(session, workspace_id, target_date, user_id=membership.user_id)


@router.get("/reports", response_model=Dict[str, Any])
def get_reports(
    workspace_id: int,
    month: Optional[str] = None,  # YYYY-MM
    session: Session = Depends(get_session),
    membership: WorkspaceMembership = Depends(get_workspace_membership)
):
    """Relatórios ancorados no mês pedido: as 6 barras terminam nele e o resumo
    é o dele. Sem o parâmetro, o mês corrente (comportamento antigo)."""
    target_date = _parse_month(month)
    RecurringMaterializationService.ensure_and_commit(session, workspace_id)
    return {
        "monthly_history": ReportService.get_last_6_months(
            session, workspace_id, user_id=membership.user_id, ref_month=target_date
        ),
        "current_summary": ReportService.get_summary(
            session, workspace_id, target_date, user_id=membership.user_id
        )
    }


@router.get("/forecast", response_model=Dict[str, Any])
def get_forecast(
    workspace_id: int,
    month: Optional[str] = None, # YYYY-MM
    session: Session = Depends(get_session),
    membership: WorkspaceMembership = Depends(get_workspace_membership)
):
    target_date = _parse_month(month)

    projection = ForecastService.get_monthly_projection(session, workspace_id, target_date)
    return projection


@router.get("/exchange-rate", response_model=Dict[str, Any])
def get_exchange_rate(
    workspace_id: int,
    from_currency: str,
    to_currency: Optional[str] = None,
    session: Session = Depends(get_session),
    membership: WorkspaceMembership = Depends(get_workspace_membership),
):
    """Taxa de câmbio de referência + fonte: PTAX (oficial) para as majores → BRL,
    senão fonte de mercado. Nunca 500: indisponível responde 422.

    Sem `to_currency`, o alvo é a MOEDA-BASE do workspace — não "BRL" fixo: este
    endpoint alimenta a dica "≈ tanto" do formulário, e num workspace em outra
    moeda a dica mostrava a conversão para um real que não é usado em lugar
    nenhum. Passa pelo `ExchangeRateStore` (mesma taxa cruzada que a criação do
    lançamento vai aplicar), então dica e valor gravado não divergem.
    """
    target = to_currency or workspace_base_currency(session, workspace_id)
    try:
        rate, source = ExchangeRateStore.rate_between(
            session, from_currency, target, date.today()
        )
    except ExchangeRateUnavailable as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    # O store grava a cotação buscada com `flush`, e `get_session` não comita: sem
    # este commit a taxa era descartada no fim do request e TODA sessão nova
    # repetia a chamada à fonte externa. Cotação de um dia passado é fato
    # imutável, e o `_save` é idempotente pela unique (moeda, data).
    session.commit()
    return {
        "from_currency": from_currency.upper(),
        "to_currency": target.upper(),
        "rate": str(rate),
        "source": source,
    }


def _validate_estimate_category(session: Session, workspace_id: int, category_id) -> None:
    if category_id is None:
        return
    from app.models.category import Category
    category = session.get(Category, category_id)
    if not category or category.workspace_id != workspace_id or category.deleted_at:
        raise HTTPException(status_code=400, detail="Categoria inválida para este workspace")


@router.post("/estimates", response_model=MonthlyEstimateRead)
def create_estimate(
    workspace_id: int,
    *,
    session: Session = Depends(get_session),
    estimate_in: MonthlyEstimateCreate,
    membership: WorkspaceMembership = Depends(require_role(WorkspaceRole.member))
):
    _validate_estimate_category(session, workspace_id, estimate_in.category_id)

    # Idempotente por (workspace, category_id, mês). A chave é o category_id (FK),
    # não o rótulo de texto: com o texto, um `category` vazio/constante colapsava
    # TODOS os orçamentos do mês num só, e dois textos diferentes para a mesma
    # categoria criavam duplicatas. O próprio model diz que category_id é "a
    # referência real desde a Onda 5" — a idempotência é que não tinha migrado.
    existing = session.exec(
        select(MonthlyEstimate)
        .where(MonthlyEstimate.workspace_id == workspace_id)
        .where(MonthlyEstimate.category_id == estimate_in.category_id)
        .where(MonthlyEstimate.month == estimate_in.month)
        .where(MonthlyEstimate.deleted_at.is_(None))
    ).first()
    if existing:
        for key, value in estimate_in.model_dump().items():
            setattr(existing, key, value)
        session.add(existing)
        publish_event(session, workspace_id, "estimate.updated", "estimate", existing.id, membership.user_id)
        session.commit()
        session.refresh(existing)
        return existing

    db_estimate = MonthlyEstimate(
        **estimate_in.model_dump(),
        workspace_id=workspace_id,
        user_id=membership.user_id
    )
    session.add(db_estimate)
    session.flush()
    publish_event(session, workspace_id, "estimate.created", "estimate", db_estimate.id, membership.user_id)
    session.commit()
    session.refresh(db_estimate)
    return db_estimate


@router.put("/estimates/{estimate_id}", response_model=MonthlyEstimateRead)
def update_estimate(
    workspace_id: int,
    estimate_id: int,
    *,
    session: Session = Depends(get_session),
    estimate_in: MonthlyEstimateCreate,
    membership: WorkspaceMembership = Depends(require_role(WorkspaceRole.member))
):
    estimate = session.get(MonthlyEstimate, estimate_id)
    if not estimate or estimate.workspace_id != workspace_id or estimate.deleted_at:
        raise HTTPException(status_code=404, detail="Estimativa não encontrada")

    _validate_estimate_category(session, workspace_id, estimate_in.category_id)
    for key, value in estimate_in.model_dump().items():
        setattr(estimate, key, value)
    session.add(estimate)
    publish_event(session, workspace_id, "estimate.updated", "estimate", estimate.id, membership.user_id)
    session.commit()
    session.refresh(estimate)
    return estimate


@router.get("/estimates", response_model=List[MonthlyEstimateRead])
def list_estimates(
    workspace_id: int,
    month: Optional[str] = None,
    session: Session = Depends(get_session),
    membership: WorkspaceMembership = Depends(get_workspace_membership)
):
    statement = (
        select(MonthlyEstimate)
        .where(MonthlyEstimate.workspace_id == workspace_id)
        .where(MonthlyEstimate.deleted_at.is_(None))
    )
    if month:
        statement = statement.where(MonthlyEstimate.month == month)

    estimates = session.exec(statement).all()
    return estimates


@router.delete("/estimates/{estimate_id}")
def delete_estimate(
    workspace_id: int,
    estimate_id: int,
    session: Session = Depends(get_session),
    membership: WorkspaceMembership = Depends(require_role(WorkspaceRole.member))
):
    from datetime import datetime, UTC
    estimate = session.get(MonthlyEstimate, estimate_id)
    if not estimate or estimate.workspace_id != workspace_id or estimate.deleted_at:
        raise HTTPException(status_code=404, detail="Estimativa não encontrada")

    estimate.deleted_at = datetime.now(UTC)
    session.add(estimate)
    publish_event(session, workspace_id, "estimate.deleted", "estimate", estimate_id, membership.user_id)
    session.commit()
    return {"status": "ok"}
