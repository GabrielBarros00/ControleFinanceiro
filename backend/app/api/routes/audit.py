from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlmodel import Session, select

from app.db.session import get_session
from app.models.audit import AuditLog, ActionType
from app.models.workspace import WorkspaceMembership, WorkspaceRole
from app.api.deps import require_role

router = APIRouter(prefix="/workspaces/{workspace_id}/audit", tags=["audit"])


class AuditLogRead(BaseModel):
    id: int
    action: ActionType
    resource_type: Optional[str]
    resource_id: Optional[int]
    user_id: Optional[int]
    workspace_id: Optional[int]
    created_at: datetime


@router.get("", response_model=List[AuditLogRead])
def list_audit(
    workspace_id: int,
    session: Session = Depends(get_session),
    # Trilha de auditoria é sensível: só admin/owner consultam (AUD-001)
    membership: WorkspaceMembership = Depends(require_role(WorkspaceRole.admin)),
    limit: int = Query(50, ge=1, le=200),
    resource_type: Optional[str] = None,
):
    stmt = (
        select(AuditLog)
        .where(AuditLog.workspace_id == workspace_id)
        .order_by(AuditLog.created_at.desc())
        .limit(limit)
    )
    if resource_type:
        stmt = stmt.where(AuditLog.resource_type == resource_type)
    return session.exec(stmt).all()
