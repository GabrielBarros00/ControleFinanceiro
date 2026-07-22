from datetime import datetime, UTC
from decimal import Decimal
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlmodel import Session, select

from app.db.session import get_session
from app.models.settlement import Settlement
from app.models.workspace import WorkspaceMembership, WorkspaceRole, role_level
from app.api.deps import get_workspace_membership, require_role
from app.services.debt_service import DebtService
from app.services.event_service import publish_event

router = APIRouter(prefix="/workspaces/{workspace_id}/settlements", tags=["settlements"])


class SettlementCreate(BaseModel):
    from_user_id: int
    to_user_id: int
    amount: Decimal = Field(gt=0)
    note: Optional[str] = None
    # YYYY-MM: quando vem do ledger mensal, quita a dívida daquele mês
    billing_month: Optional[str] = None
    settled_at: Optional[datetime] = None


class SettlementRead(BaseModel):
    id: int
    from_user_id: int
    to_user_id: int
    amount: Decimal
    note: Optional[str]
    billing_month: Optional[str]
    settled_at: datetime
    created_by_user_id: Optional[int]


def _ensure_members(session: Session, workspace_id: int, user_ids: set) -> None:
    members = set(session.exec(
        select(WorkspaceMembership.user_id).where(
            WorkspaceMembership.workspace_id == workspace_id
        )
    ).all())
    outsiders = user_ids - members
    if outsiders:
        raise HTTPException(
            status_code=400,
            detail=f"Usuário(s) {sorted(outsiders)} não pertence(m) a este workspace",
        )


@router.post("", response_model=SettlementRead)
def create_settlement(
    workspace_id: int,
    settlement_in: SettlementCreate,
    session: Session = Depends(get_session),
    membership: WorkspaceMembership = Depends(require_role(WorkspaceRole.member)),
):
    if settlement_in.from_user_id == settlement_in.to_user_id:
        raise HTTPException(status_code=400, detail="Pagador e recebedor devem ser pessoas diferentes")
    _ensure_members(session, workspace_id, {settlement_in.from_user_id, settlement_in.to_user_id})

    # Autorização (ADR 0009): member registra apenas acertos em que ELE é o
    # pagador; registrar por terceiros exige admin/owner
    if (
        role_level(membership.role) < role_level(WorkspaceRole.admin)
        and settlement_in.from_user_id != membership.user_id
    ):
        raise HTTPException(
            status_code=403,
            detail="Você só pode registrar acertos em que você é o pagador",
        )

    # Direção e teto (ADR 0009): o acerto segue a dívida líquida atual e não
    # pode excedê-la — sobrepagamento inverteria a relação (crédito artificial)
    debts = DebtService.get_workspace_debts(session, workspace_id)
    debt = next(
        (
            d for d in debts
            if d["debtor_id"] == settlement_in.from_user_id
            and d["creditor_id"] == settlement_in.to_user_id
        ),
        None,
    )
    if debt is None:
        raise HTTPException(
            status_code=400,
            detail="Não há dívida nessa direção para acertar",
        )
    if settlement_in.amount > debt["amount"]:
        raise HTTPException(
            status_code=400,
            detail=f"Valor excede a dívida atual (R$ {debt['amount']})",
        )

    db_settlement = Settlement(
        workspace_id=workspace_id,
        from_user_id=settlement_in.from_user_id,
        to_user_id=settlement_in.to_user_id,
        amount=settlement_in.amount,
        note=settlement_in.note,
        billing_month=settlement_in.billing_month,
        settled_at=settlement_in.settled_at or datetime.now(UTC),
        created_by_user_id=membership.user_id,
    )
    session.add(db_settlement)
    session.flush()
    publish_event(session, workspace_id, "settlement.created", "settlement", db_settlement.id, membership.user_id)
    session.commit()
    session.refresh(db_settlement)
    return db_settlement


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
        .order_by(Settlement.settled_at.desc())
    ).all()


@router.delete("/{settlement_id}")
def delete_settlement(
    workspace_id: int,
    settlement_id: int,
    session: Session = Depends(get_session),
    membership: WorkspaceMembership = Depends(require_role(WorkspaceRole.member)),
):
    db_settlement = session.get(Settlement, settlement_id)
    if not db_settlement or db_settlement.workspace_id != workspace_id or db_settlement.deleted_at:
        raise HTTPException(status_code=404, detail="Settlement not found")

    # Member desfaz apenas os próprios registros; admin+ desfaz qualquer um
    if (
        role_level(membership.role) < role_level(WorkspaceRole.admin)
        and db_settlement.created_by_user_id not in (None, membership.user_id)
    ):
        raise HTTPException(status_code=403, detail="Você só pode desfazer os próprios acertos")

    db_settlement.deleted_at = datetime.now(UTC)
    session.add(db_settlement)
    publish_event(session, workspace_id, "settlement.deleted", "settlement", settlement_id, membership.user_id)
    session.commit()
    return {"status": "ok"}
