from datetime import date
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session

from app.api.deps import get_workspace_membership
from app.db.session import get_session
from app.models.workspace import WorkspaceMembership
from app.services.liability_service import LiabilityService

router = APIRouter(prefix="/workspaces/{workspace_id}/liabilities", tags=["liabilities"])


@router.get("/overview", response_model=Dict[str, Any])
def get_liabilities_overview(
    workspace_id: int,
    month: Optional[str] = None,  # YYYY-MM; default: mês atual
    session: Session = Depends(get_session),
    membership: WorkspaceMembership = Depends(get_workspace_membership),
):
    """Panorama de endividamento: financiamentos + faturas de cartão, com total
    devedor, o que vence no mês selecionado e a parte de cada pessoa."""
    if month is None:
        month = date.today().strftime("%Y-%m")
    else:
        try:
            year_str, month_str = month.split("-")
            date(int(year_str), int(month_str), 1)
        except ValueError:
            raise HTTPException(status_code=400, detail="Formato de mês inválido. Use YYYY-MM")
    return LiabilityService.get_overview(session, workspace_id, month)
