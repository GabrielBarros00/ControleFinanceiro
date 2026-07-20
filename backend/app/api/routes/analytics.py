from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select
from typing import List, Any, Dict, Optional
from datetime import date

from app.db.session import get_session
from app.models.workspace import WorkspaceMembership, WorkspaceRole
from app.models.estimate import MonthlyEstimate
from app.schemas.estimate import MonthlyEstimateCreate, MonthlyEstimateRead
from app.domain.money import Currency
from app.services.currency_service import CurrencyService, ExchangeRateUnavailable
from app.services.forecast_service import ForecastService
from app.services.report_service import ReportService
from app.api.deps import get_workspace_membership, require_role
from app.services.event_service import publish_event

router = APIRouter(prefix="/workspaces/{workspace_id}/analytics", tags=["analytics"])


@router.get("/summary", response_model=Dict[str, Any])
def get_summary(
    workspace_id: int,
    month: Optional[str] = None,
    session: Session = Depends(get_session),
    membership: WorkspaceMembership = Depends(get_workspace_membership)
):
    if month:
        try:
            year_str, month_str = month.split("-")
            target_date = date(int(year_str), int(month_str), 1)
        except ValueError:
            raise HTTPException(status_code=400, detail="Formato de mês inválido. Use YYYY-MM")
    else:
        target_date = date.today()

    return ReportService.get_summary(session, workspace_id, target_date)


@router.get("/reports", response_model=Dict[str, Any])
def get_reports(
    workspace_id: int,
    session: Session = Depends(get_session),
    membership: WorkspaceMembership = Depends(get_workspace_membership)
):
    return {
        "monthly_history": ReportService.get_last_6_months(session, workspace_id),
        "current_summary": ReportService.get_summary(session, workspace_id, date.today())
    }


@router.get("/forecast", response_model=Dict[str, Any])
def get_forecast(
    workspace_id: int,
    month: Optional[str] = None, # YYYY-MM
    session: Session = Depends(get_session),
    membership: WorkspaceMembership = Depends(get_workspace_membership)
):
    if month:
        try:
            year_str, month_str = month.split("-")
            target_date = date(int(year_str), int(month_str), 1)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid month format. Use YYYY-MM")
    else:
        target_date = date.today()

    projection = ForecastService.get_monthly_projection(session, workspace_id, target_date)
    return projection


@router.get("/exchange-rate", response_model=Dict[str, Any])
async def get_exchange_rate(
    workspace_id: int,
    from_currency: Currency,
    to_currency: Currency = Currency.BRL,
    membership: WorkspaceMembership = Depends(get_workspace_membership),
):
    """Taxa de câmbio oficial (BCB PTAX). Nunca 500: indisponível responde 422."""
    try:
        rate = await CurrencyService.get_rate(from_currency, to_currency)
    except ExchangeRateUnavailable as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return {
        "from_currency": from_currency.value,
        "to_currency": to_currency.value,
        "rate": str(rate),
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
