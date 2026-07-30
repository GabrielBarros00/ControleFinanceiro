"""Conta de pagamento PESSOAL — de onde o dinheiro sai (ADR 0004 + ADR 0021).

A conta acompanha o dono em todo workspace de que ele participa e não é visível a
mais ninguém. Antes ela morava num workspace com `owner_user_id` OPCIONAL, e o
`None` significava "conta da casa": o extrato bancário de uma pessoa virava um
recurso coletivo que qualquer `member` editava ou desativava.

O compartilhamento por workspace da Onda 2 tinha o mesmo defeito do cartão: a
conta aparecia na listagem do workspace de destino, mas `_validate_payer_accounts`
exigia `account.workspace_id == workspace_id` e recusava o pagamento. Visível e
inutilizável.
"""
from datetime import datetime, UTC
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlmodel import Session, select

from app.api.routes.auth import get_current_user
from app.db.session import get_session
from app.domain.access_policy import assert_owns, personal_scope
from app.domain.query_policy import resolve_personal_currency
from app.models.payment_account import PaymentAccount, PaymentAccountType
from app.models.user import User
from app.schemas.common import NAME_MAX, OptionalCurrencyCode

router = APIRouter(prefix="/me/payment-accounts", tags=["me-payment-accounts"])


def _colecao(metodo: str, caminho: str, **kwargs):
    """Registra a rota de coleção COM e SEM barra final, sem redirecionar.

    O redirecionamento automático de barra do Starlette responde 307, e nesse
    salto o **cookie de sessão não acompanha** — a URL com a barra "errada"
    devolvia 401 em vez de funcionar. Registrar os dois caminhos elimina o
    redirecionamento em vez de tentar sobreviver a ele.
    """
    def decorador(func):
        for p in (caminho, caminho + "/"):
            getattr(router, metodo)(
                p, **({**kwargs, "include_in_schema": False} if p.endswith("/") else kwargs)
            )(func)
        return func
    return decorador


class PaymentAccountCreate(BaseModel):
    name: str = Field(min_length=1, max_length=NAME_MAX)
    type: PaymentAccountType = PaymentAccountType.checking
    # None = "não informada" → a rota resolve para a moeda de relatório do dono
    currency: OptionalCurrencyCode = None


class PaymentAccountUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=NAME_MAX)
    type: Optional[PaymentAccountType] = None
    active: Optional[bool] = None


class PaymentAccountRead(BaseModel):
    id: int
    name: str
    type: PaymentAccountType
    currency: str
    active: bool
    owner_user_id: int


def _get_account_or_404(session: Session, account_id: int, user_id: int) -> PaymentAccount:
    account = session.get(PaymentAccount, account_id)
    if not account or account.deleted_at:
        raise HTTPException(status_code=404, detail="Conta não encontrada")
    assert_owns(account.owner_user_id, user_id, detail="Conta não encontrada")
    return account


@_colecao("get", "", response_model=List[PaymentAccountRead])
def list_payment_accounts(
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    return session.exec(
        select(PaymentAccount)
        .where(personal_scope(PaymentAccount.owner_user_id, current_user.id))
        .where(PaymentAccount.deleted_at.is_(None))
        .order_by(PaymentAccount.name)
    ).all()


@_colecao("post", "", response_model=PaymentAccountRead)
def create_payment_account(
    account_in: PaymentAccountCreate,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    name = account_in.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Informe o nome da conta")
    # Resolvida UMA vez: vale tanto para a conta nova quanto para a reativação.
    currency = resolve_personal_currency(session, current_user.id, account_in.currency)

    existing = session.exec(
        select(PaymentAccount).where(
            PaymentAccount.owner_user_id == current_user.id,
            PaymentAccount.name == name,
        )
    ).first()
    if existing:
        if existing.deleted_at is None:
            raise HTTPException(status_code=400, detail="Já existe uma conta com esse nome")
        # Reativação: nome de conta excluída volta à vida com os dados novos —
        # a unique (owner, name) nunca bloqueia recriação.
        existing.deleted_at = None
        existing.active = True
        existing.type = account_in.type
        existing.currency = currency
        existing.updated_at = datetime.now(UTC)
        session.add(existing)
        account = existing
    else:
        account = PaymentAccount(
            name=name,
            type=account_in.type,
            currency=currency,
            owner_user_id=current_user.id,
        )
        session.add(account)

    session.commit()
    session.refresh(account)
    return account


@router.put("/{account_id}", response_model=PaymentAccountRead)
def update_payment_account(
    account_id: int,
    account_in: PaymentAccountUpdate,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    account = _get_account_or_404(session, account_id, current_user.id)
    update_data = account_in.model_dump(exclude_unset=True)

    if "name" in update_data:
        name = (update_data["name"] or "").strip()
        if not name:
            raise HTTPException(status_code=400, detail="Informe o nome da conta")
        clash = session.exec(
            select(PaymentAccount).where(
                PaymentAccount.owner_user_id == current_user.id,
                PaymentAccount.name == name,
                PaymentAccount.id != account.id,
                PaymentAccount.deleted_at.is_(None),
            )
        ).first()
        if clash:
            raise HTTPException(status_code=400, detail="Já existe uma conta com esse nome")
        update_data["name"] = name

    for key, value in update_data.items():
        setattr(account, key, value)
    account.updated_at = datetime.now(UTC)
    session.add(account)
    session.commit()
    session.refresh(account)
    return account


@router.delete("/{account_id}")
def delete_payment_account(
    account_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Soft delete: pagamentos antigos continuam apontando para a conta
    (histórico explicável); para sumir do formulário basta desativar."""
    account = _get_account_or_404(session, account_id, current_user.id)
    account.deleted_at = datetime.now(UTC)
    account.active = False
    session.add(account)
    session.commit()
    return {"status": "ok"}
