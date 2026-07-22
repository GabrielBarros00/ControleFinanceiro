from datetime import date
from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session
from typing import List, Dict, Any, Optional

from app.db.session import get_session
from app.models.workspace import WorkspaceMembership
from app.services.debt_service import DebtService
from app.api.deps import get_workspace_membership

router = APIRouter(prefix="/workspaces/{workspace_id}/debts", tags=["debts"])


@router.get("", response_model=List[Dict[str, Any]])
def get_debts(
    workspace_id: int,
    session: Session = Depends(get_session),
    membership: WorkspaceMembership = Depends(get_workspace_membership)
):
    return DebtService.get_workspace_debts(session, workspace_id)


@router.get("/monthly", response_model=Dict[str, Any])
def get_monthly_debts(
    workspace_id: int,
    month: Optional[str] = None,  # YYYY-MM; default: mês atual
    session: Session = Depends(get_session),
    membership: WorkspaceMembership = Depends(get_workspace_membership)
):
    """Dívidas do mês selecionado (por billing_month): quem pagou, quanto cada
    um deve e se a despesa está paga. Parcelas aparecem só no mês delas."""
    if month is None:
        month = date.today().strftime("%Y-%m")
    else:
        try:
            year_str, month_str = month.split("-")
            date(int(year_str), int(month_str), 1)
        except ValueError:
            raise HTTPException(status_code=400, detail="Formato de mês inválido. Use YYYY-MM")
    return DebtService.get_monthly_ledger(session, workspace_id, month)
