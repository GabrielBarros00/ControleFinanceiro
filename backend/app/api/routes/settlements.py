from typing import List

from fastapi import APIRouter, Depends

from app.schemas.common import StatusRead
from sqlmodel import Session, select

from app.db.session import get_session
from app.domain.access_policy import participant_scope
from app.models.settlement import Settlement
from app.models.workspace import WorkspaceMembership, WorkspaceRole
from app.api.deps import get_workspace_membership, require_role
from app.schemas.settlement import SettlementCreate, SettlementRead
from app.services.commands import settlements as st_cmd

router = APIRouter(prefix="/workspaces/{workspace_id}/settlements", tags=["settlements"])

__all__ = ["SettlementCreate", "SettlementRead", "router"]


@router.post("", response_model=SettlementRead)
def create_settlement(
    workspace_id: int,
    settlement_in: SettlementCreate,
    session: Session = Depends(get_session),
    membership: WorkspaceMembership = Depends(require_role(WorkspaceRole.member)),
):
    acerto = st_cmd.create_settlement(session, workspace_id, settlement_in, membership)
    session.commit()
    session.refresh(acerto)
    return acerto


@router.get("", response_model=List[SettlementRead])
def list_settlements(
    workspace_id: int,
    session: Session = Depends(get_session),
    membership: WorkspaceMembership = Depends(get_workspace_membership),
):
    return session.exec(
        select(Settlement)
        .where(Settlement.workspace_id == workspace_id)
        .where(Settlement.deleted_at.is_(None))
        # Acerto tem DOIS lados: vejo aquele em que eu pago ou recebo (ADR 0018)
        .where(participant_scope(
            (Settlement.from_user_id, Settlement.to_user_id), membership
        ))
        .order_by(Settlement.settled_at.desc())
    ).all()


@router.delete("/{settlement_id}", response_model=StatusRead)
def delete_settlement(
    workspace_id: int,
    settlement_id: int,
    session: Session = Depends(get_session),
    membership: WorkspaceMembership = Depends(require_role(WorkspaceRole.member)),
):
    resultado = st_cmd.delete_settlement(session, workspace_id, settlement_id, membership)
    session.commit()
    return resultado
