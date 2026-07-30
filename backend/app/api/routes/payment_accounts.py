from datetime import datetime, UTC
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.schemas.common import NAME_MAX, OptionalCurrencyCode
from sqlmodel import Session, select

from app.db.session import get_session
from app.domain.access_policy import (
    accounts_of_workspace,
    assert_can_read,
    assert_can_write,
    shared_or_mine_scope,
)
from app.domain.query_policy import resolve_currency
from app.models.payment_account import (
    PaymentAccount,
    PaymentAccountType,
    PaymentAccountWorkspaceShare,
)
from app.models.workspace import WorkspaceMembership, WorkspaceRole
from app.api.deps import get_workspace_membership, require_role
from app.services.event_service import publish_event
from app.services.sharing_service import set_shares, share_ids

router = APIRouter(prefix="/workspaces/{workspace_id}/payment-accounts", tags=["payment-accounts"])


class PaymentAccountCreate(BaseModel):
    name: str = Field(min_length=1, max_length=NAME_MAX)
    type: PaymentAccountType = PaymentAccountType.checking
    # None = "não informada" → a rota resolve para a moeda-base do workspace
    currency: OptionalCurrencyCode = None
    owner_user_id: Optional[int] = None


class PaymentAccountUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=NAME_MAX)
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


def _get_account_or_404(
    session: Session, workspace_id: int, account_id: int, membership: WorkspaceMembership
) -> PaymentAccount:
    account = session.exec(
        select(PaymentAccount).where(
            PaymentAccount.id == account_id,
            # Desta casa OU compartilhada com ela (ADR 0019)
            accounts_of_workspace(workspace_id),
            PaymentAccount.deleted_at.is_(None),
        )
    ).first()
    if not account:
        raise HTTPException(status_code=404, detail="Conta não encontrada")
    # `owner_user_id` existia desde sempre e nunca era consultado: qualquer member
    # lia E editava a conta bancária pessoal de outro. Dono NULL = conta da casa.
    if account.owner_user_id is not None:
        assert_can_read(account.owner_user_id, membership, detail="Conta não encontrada")
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
        # Deste workspace + as pessoais compartilhadas com ele (ADR 0019)
        .where(accounts_of_workspace(workspace_id))
        .where(PaymentAccount.deleted_at.is_(None))
        # Conta sem dono é da casa; com dono, só a minha (ADR 0018)
        .where(shared_or_mine_scope(PaymentAccount.owner_user_id, membership))
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
    # Moeda ausente = a do workspace (nunca "BRL" fixo — ver resolve_currency).
    # Resolvida UMA vez: vale tanto para a conta nova quanto para a reativação.
    currency = resolve_currency(session, workspace_id, account_in.currency)

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
        existing.currency = currency
        existing.owner_user_id = account_in.owner_user_id
        existing.updated_at = datetime.now(UTC)
        session.add(existing)
        account = existing
    else:
        account = PaymentAccount(
            name=name,
            type=account_in.type,
            currency=currency,
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
    account = _get_account_or_404(session, workspace_id, account_id, membership)
    # Não havia trava NENHUMA aqui: qualquer member reapontava (ou desativava) a
    # conta bancária pessoal de outro, e os pagamentos de fatura seguiam saindo
    # dela. Conta da casa (dono NULL) continua exigindo admin+.
    assert_can_write(
        account.owner_user_id,
        membership,
        detail="Você só pode alterar as próprias contas",
        null_is_shared=True,
    )
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
    account = _get_account_or_404(session, workspace_id, account_id, membership)
    assert_can_write(
        account.owner_user_id,
        membership,
        detail="Você só pode excluir as próprias contas",
        null_is_shared=True,
    )
    account.deleted_at = datetime.now(UTC)
    account.active = False
    session.add(account)
    publish_event(session, workspace_id, "payment_account.deleted", "payment_account", account.id, membership.user_id)
    session.commit()
    return {"status": "ok"}


@router.put("/{account_id}/shares")
def set_account_shares(
    workspace_id: int,
    account_id: int,
    workspace_ids: List[int],
    session: Session = Depends(get_session),
    membership: WorkspaceMembership = Depends(require_role(WorkspaceRole.member)),
):
    """Workspaces com que esta conta é compartilhada — a lista é o estado final."""
    account = _get_account_or_404(session, workspace_id, account_id, membership)
    assert_can_write(
        account.owner_user_id,
        membership,
        detail="Só o dono da conta pode compartilhá-la",
        null_is_shared=True,
    )
    set_shares(
        session,
        PaymentAccountWorkspaceShare,
        "account_id",
        account.id,
        workspace_ids,
        user_id=membership.user_id,
    )
    publish_event(
        session, workspace_id, "payment_account.updated", "payment_account",
        account.id, membership.user_id,
    )
    session.commit()
    return {"status": "ok", "shared_with_workspace_ids": workspace_ids}


@router.get("/{account_id}/shares", response_model=List[int])
def list_account_shares(
    workspace_id: int,
    account_id: int,
    session: Session = Depends(get_session),
    membership: WorkspaceMembership = Depends(get_workspace_membership),
):
    account = _get_account_or_404(session, workspace_id, account_id, membership)
    return share_ids(
        session,
        PaymentAccountWorkspaceShare,
        PaymentAccountWorkspaceShare.account_id,
        account.id,
    )
