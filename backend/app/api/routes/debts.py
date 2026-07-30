from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session
from typing import List, Dict, Any, Optional

from app.db.session import get_session
from app.domain.access_policy import has_full_access
from app.domain.dates import InvalidMonth, parse_month
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
    # Sem acesso completo, só as dívidas em que eu sou uma das pontas (ADR 0018).
    # O ledger é calculado INTEIRO e recortado na saída — filtrar antes mudaria o
    # pareamento guloso e daria valor errado.
    return DebtService.get_workspace_debts(
        session,
        workspace_id,
        viewer_user_id=None if has_full_access(membership) else membership.user_id,
    )


@router.get("/monthly", response_model=Dict[str, Any])
def get_monthly_debts(
    workspace_id: int,
    month: Optional[str] = None,  # YYYY-MM; default: mês atual
    session: Session = Depends(get_session),
    membership: WorkspaceMembership = Depends(get_workspace_membership)
):
    """Dívidas do mês selecionado (por billing_month): quem pagou, quanto cada
    um deve e se a despesa está paga. Parcelas aparecem só no mês delas."""
    try:
        ref = parse_month(month)
    except InvalidMonth as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return DebtService.get_monthly_ledger(
        session,
        workspace_id,
        ref.strftime("%Y-%m"),
        viewer_user_id=None if has_full_access(membership) else membership.user_id,
    )
