from datetime import datetime, UTC
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from app.db.session import get_session
from app.models.workspace import WorkspaceMembership, WorkspaceRole, role_level
from app.models.income import Income
from app.schemas.income import IncomeCreate, IncomeRead, IncomeUpdate
from app.api.deps import get_workspace_membership, require_role
from app.services.event_service import publish_event

router = APIRouter(prefix="/workspaces/{workspace_id}/income", tags=["income"])


def _get_income_or_404(session: Session, workspace_id: int, income_id: int) -> Income:
    income = session.get(Income, income_id)
    if not income or income.workspace_id != workspace_id or income.deleted_at:
        raise HTTPException(status_code=404, detail="Renda não encontrada")
    return income


def _check_income_ownership(membership: WorkspaceMembership, income: Income):
    if (
        role_level(membership.role) < role_level(WorkspaceRole.admin)
        and income.user_id != membership.user_id
    ):
        raise HTTPException(status_code=403, detail="Você só pode alterar as próprias rendas")


@router.post("/", response_model=IncomeRead)
def create_income(
    workspace_id: int,
    *,
    session: Session = Depends(get_session),
    income_in: IncomeCreate,
    membership: WorkspaceMembership = Depends(require_role(WorkspaceRole.member))
):
    db_income = Income(
        **income_in.model_dump(),
        workspace_id=workspace_id,
        user_id=membership.user_id
    )
    session.add(db_income)
    session.flush()
    publish_event(session, workspace_id, "income.created", "income", db_income.id, membership.user_id)
    session.commit()
    session.refresh(db_income)
    return db_income


@router.get("/", response_model=List[IncomeRead])
def list_income(
    workspace_id: int,
    session: Session = Depends(get_session),
    membership: WorkspaceMembership = Depends(get_workspace_membership)
):
    statement = select(Income).where(
        Income.workspace_id == workspace_id,
        Income.deleted_at.is_(None)
    )
    incomes = session.exec(statement).all()
    return incomes


@router.put("/{income_id}", response_model=IncomeRead)
def update_income(
    workspace_id: int,
    income_id: int,
    income_in: IncomeUpdate,
    session: Session = Depends(get_session),
    membership: WorkspaceMembership = Depends(require_role(WorkspaceRole.member))
):
    income = _get_income_or_404(session, workspace_id, income_id)
    _check_income_ownership(membership, income)

    for key, value in income_in.model_dump(exclude_unset=True).items():
        setattr(income, key, value)
    income.updated_at = datetime.now(UTC)
    session.add(income)
    publish_event(session, workspace_id, "income.updated", "income", income.id, membership.user_id)
    session.commit()
    session.refresh(income)
    return income


@router.delete("/{income_id}")
def delete_income(
    workspace_id: int,
    income_id: int,
    session: Session = Depends(get_session),
    membership: WorkspaceMembership = Depends(require_role(WorkspaceRole.member))
):
    income = _get_income_or_404(session, workspace_id, income_id)
    _check_income_ownership(membership, income)

    income.deleted_at = datetime.now(UTC)
    session.add(income)
    publish_event(session, workspace_id, "income.deleted", "income", income.id, membership.user_id)
    session.commit()
    return {"status": "ok"}
