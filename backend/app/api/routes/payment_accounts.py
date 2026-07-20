from datetime import datetime, UTC
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

from app.db.session import get_session
from app.models.payment_account import PaymentAccount, PaymentAccountType
from app.models.workspace import WorkspaceMembership, WorkspaceRole
from app.api.deps import get_workspace_membership, require_role
from app.services.event_service import publish_event

router = APIRouter(prefix="/workspaces/{workspace_id}/payment-accounts", tags=["payment-accounts"])


class PaymentAccountCreate(BaseModel):
    name: str
    type: PaymentAccountType = PaymentAccountType.checking
    currency: str = "BRL"
    owner_user_id: Optional[int] = None


class PaymentAccountUpdate(BaseModel):
    name: Optional[str] = None
    type: Optional[PaymentAccountType] = None
    active: Optional[bool] = None
    owner_user_id: Optional[int] = None


class PaymentAccountRead(BaseModel):
    id: int
    name: str
    type: PaymentAccountType
    currency: str
    active: bool
    owner_user_id: Optional[int]


def _get_account_or_404(session: Session, workspace_id: int, account_id: int) -> PaymentAccount:
    account = session.get(PaymentAccount, account_id)
    if not account or account.workspace_id != workspace_id or account.deleted_at:
        raise HTTPException(status_code=404, detail="Conta não encontrada")
    return account


def _ensure_owner_is_member(session: Session, workspace_id: int, owner_user_id: Optional[int]) -> None:
    if owner_user_id is None:
        return
    member = session.exec(
        select(WorkspaceMembership).where(
            WorkspaceMembership.workspace_id == workspace_id,
            WorkspaceMembership.user_id == owner_user_id,
        )
    ).first()
    if not member:
        raise HTTPException(status_code=400, detail="Dono da conta não pertence a este workspace")


@router.get("", response_model=List[PaymentAccountRead])
def list_payment_accounts(
    workspace_id: int,
    session: Session = Depends(get_session),
    membership: WorkspaceMembership = Depends(get_workspace_membership),
):
    return session.exec(
        select(PaymentAccount)
        .where(PaymentAccount.workspace_id == workspace_id)
        .where(PaymentAccount.deleted_at.is_(None))
        .order_by(PaymentAccount.name)
    ).all()


@router.post("", response_model=PaymentAccountRead)
def create_payment_account(
    workspace_id: int,
    account_in: PaymentAccountCreate,
    session: Session = Depends(get_session),
    membership: WorkspaceMembership = Depends(require_role(WorkspaceRole.member)),
):
    name = account_in.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Informe o nome da conta")
    _ensure_owner_is_member(session, workspace_id, account_in.owner_user_id)

    existing = session.exec(
        select(PaymentAccount).where(
            PaymentAccount.workspace_id == workspace_id,
            PaymentAccount.name == name,
        )
    ).first()
    if existing:
        if existing.deleted_at is None:
            raise HTTPException(status_code=400, detail="Já existe uma conta com esse nome")
        # Reativação: nome de conta excluída volta à vida com os dados novos —
        # a unique (workspace, name) nunca bloqueia recriação
        existing.deleted_at = None
        existing.active = True
        existing.type = account_in.type
        existing.currency = account_in.currency
        existing.owner_user_id = account_in.owner_user_id
        existing.updated_at = datetime.now(UTC)
        session.add(existing)
        account = existing
    else:
        account = PaymentAccount(
            name=name,
            type=account_in.type,
            currency=account_in.currency,
            owner_user_id=account_in.owner_user_id,
            workspace_id=workspace_id,
        )
        session.add(account)

    session.flush()
    publish_event(session, workspace_id, "payment_account.created", "payment_account", account.id, membership.user_id)
    session.commit()
    session.refresh(account)
    return account


@router.put("/{account_id}", response_model=PaymentAccountRead)
def update_payment_account(
    workspace_id: int,
    account_id: int,
    account_in: PaymentAccountUpdate,
    session: Session = Depends(get_session),
    membership: WorkspaceMembership = Depends(require_role(WorkspaceRole.member)),
):
    account = _get_account_or_404(session, workspace_id, account_id)
    update_data = account_in.model_dump(exclude_unset=True)

    if "name" in update_data:
        name = (update_data["name"] or "").strip()
        if not name:
            raise HTTPException(status_code=400, detail="Informe o nome da conta")
        clash = session.exec(
            select(PaymentAccount).where(
                PaymentAccount.workspace_id == workspace_id,
                PaymentAccount.name == name,
                PaymentAccount.id != account.id,
                PaymentAccount.deleted_at.is_(None),
            )
        ).first()
        if clash:
            raise HTTPException(status_code=400, detail="Já existe uma conta com esse nome")
        update_data["name"] = name

    if "owner_user_id" in update_data:
        _ensure_owner_is_member(session, workspace_id, update_data["owner_user_id"])

    for key, value in update_data.items():
        setattr(account, key, value)
    account.updated_at = datetime.now(UTC)
    session.add(account)
    publish_event(session, workspace_id, "payment_account.updated", "payment_account", account.id, membership.user_id)
    session.commit()
    session.refresh(account)
    return account


@router.delete("/{account_id}")
def delete_payment_account(
    workspace_id: int,
    account_id: int,
    session: Session = Depends(get_session),
    membership: WorkspaceMembership = Depends(require_role(WorkspaceRole.member)),
):
    """Soft delete: pagamentos antigos continuam apontando para a conta
    (histórico explicável); para sumir do formulário basta desativar."""
    account = _get_account_or_404(session, workspace_id, account_id)
    account.deleted_at = datetime.now(UTC)
    account.active = False
    session.add(account)
    publish_event(session, workspace_id, "payment_account.deleted", "payment_account", account.id, membership.user_id)
    session.commit()
    return {"status": "ok"}
