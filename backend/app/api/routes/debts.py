from fastapi import APIRouter, Depends
from sqlmodel import Session
from typing import List, Dict, Any

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
