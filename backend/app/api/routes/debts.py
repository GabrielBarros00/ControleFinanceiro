from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session
from typing import List, Optional

from app.db.session import get_session
from app.domain.access_policy import has_full_access
from app.domain.dates import InvalidMonth, parse_month
from app.models.workspace import WorkspaceMembership
from app.schemas.debts import DebtRead, DebtsByMonthRead, MonthlyLedgerRead
from app.services.debt_service import DebtService
from app.api.deps import get_workspace_membership

router = APIRouter(prefix="/workspaces/{workspace_id}/debts", tags=["debts"])


@router.get("", response_model=List[DebtRead])
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


@router.get("/by-month", response_model=DebtsByMonthRead)
def get_debts_by_month(
    workspace_id: int,
    session: Session = Depends(get_session),
    membership: WorkspaceMembership = Depends(get_workspace_membership)
):
    """De quais meses vem o saldo acumulado de quem pediu.

    O saldo de `/debts` é cumulativo: R$ 320 pode ser a soma de três meses que
    ninguém fechou, e a tela mostrava só o total — que se lê como uma cobrança do
    mês corrente. Aqui a soma aparece aberta, e ela fecha (ver o serviço).

    `user_id` é sempre o de quem pediu (o saldo é dele); `viewer_user_id` é o
    recorte do ADR 0018 sobre as linhas de cada mês.
    """
    return DebtService.get_balance_by_month(
        session,
        workspace_id,
        membership.user_id,
        viewer_user_id=None if has_full_access(membership) else membership.user_id,
    )


@router.get("/monthly", response_model=MonthlyLedgerRead)
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
