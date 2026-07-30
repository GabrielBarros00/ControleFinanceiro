from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session

from app.api.deps import get_workspace_membership
from app.db.session import get_session
from app.domain.access_policy import has_full_access
from app.domain.dates import InvalidMonth, parse_month
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
    try:
        ref = parse_month(month)
    except InvalidMonth as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return LiabilityService.get_overview(
        session,
        workspace_id,
        ref.strftime("%Y-%m"),
        viewer_user_id=None if has_full_access(membership) else membership.user_id,
    )
