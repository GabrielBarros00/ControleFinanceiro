"""Estabelecimentos do espaço (ADR 0038). A regra mora em `services/commands/merchants.py`."""
from typing import List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlmodel import Session, select

from app.api.deps import get_workspace_membership, require_role
from app.db.session import get_session
from app.domain.access_policy import transaction_scope
from app.domain.dates import today_local
from app.models.transaction import Transaction
from app.models.workspace import WorkspaceMembership, WorkspaceRole
from app.schemas.common import StatusRead
from app.schemas.merchant import MerchantCreate, MerchantMerge, MerchantRead, MerchantSpendingRead, MerchantUpdate
from app.services import transaction_query
from app.services.commands import merchants as cmd

router = APIRouter(prefix="/workspaces/{workspace_id}/merchants", tags=["merchants"])


@router.get("", response_model=List[MerchantRead])
@router.get("/", response_model=List[MerchantRead], include_in_schema=False)
def list_merchants(
    workspace_id: int,
    session: Session = Depends(get_session),
    membership: WorkspaceMembership = Depends(get_workspace_membership),
):
    lista = cmd.list_merchants(session, workspace_id)
    # Quantos lançamentos cada um tem, contando só os que ESTA pessoa vê.
    contagem = dict(session.exec(
        select(Transaction.merchant_id, func.count(Transaction.id))
        .where(
            Transaction.workspace_id == workspace_id,
            Transaction.merchant_id.in_([m.id for m in lista] or [-1]),
            Transaction.deleted_at.is_(None),
            transaction_scope(membership),
        )
        .group_by(Transaction.merchant_id)
    ).all())
    return [MerchantRead(**m.model_dump(), transaction_count=contagem.get(m.id, 0)) for m in lista]


@router.get("/spending", response_model=List[MerchantSpendingRead])
def merchant_spending(
    workspace_id: int,
    month: Optional[str] = Query(None, pattern=r"^\d{4}-(0[1-9]|1[0-2])$"),
    session: Session = Depends(get_session),
    membership: WorkspaceMembership = Depends(get_workspace_membership),
):
    """Gasto do mês (competência) por estabelecimento: o valor cheio e a sua parte.

    A soma é a mesma do agrupamento do agente (`transaction_query.breakdown`):
    status realizados, por moeda, só o que esta pessoa vê.
    """
    filtros = transaction_query.TxFilters(month=month or today_local().strftime("%Y-%m"))

    def soma(base: Literal["total", "my_share"]):
        return transaction_query.breakdown(
            session, [membership], filtros, me_id=membership.user_id, group_by="merchant", basis=base,
        )

    try:
        total, minha = soma("total"), soma("my_share")
    except transaction_query.BreakdownTooLarge as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    parte = {(g.id, g.name, g.currency): g.amount for g in minha}
    # O que não tem estabelecimento vai por último, mesmo sendo o maior: ele é o
    # resto, não um lugar.
    total = sorted(total, key=lambda g: g.id is None)
    return [
        MerchantSpendingRead(
            id=g.id, name=g.name, currency=g.currency, total=g.amount, count=g.count,
            my_share=parte.get((g.id, g.name, g.currency), 0),
        )
        for g in total
    ]


@router.post("", response_model=MerchantRead)
@router.post("/", response_model=MerchantRead, include_in_schema=False)
def create_merchant(
    workspace_id: int,
    body: MerchantCreate,
    session: Session = Depends(get_session),
    membership: WorkspaceMembership = Depends(require_role(WorkspaceRole.member)),
):
    m = cmd.create_merchant(session, workspace_id, body, membership)
    session.commit()
    session.refresh(m)
    return m


@router.put("/{merchant_id}", response_model=MerchantRead)
def update_merchant(
    workspace_id: int,
    merchant_id: int,
    body: MerchantUpdate,
    session: Session = Depends(get_session),
    membership: WorkspaceMembership = Depends(require_role(WorkspaceRole.member)),
):
    m = cmd.update_merchant(session, workspace_id, merchant_id, body, membership)
    session.commit()
    session.refresh(m)
    return m


@router.post("/{merchant_id}/merge", response_model=MerchantRead)
def merge_merchant(
    workspace_id: int,
    merchant_id: int,
    body: MerchantMerge,
    session: Session = Depends(get_session),
    membership: WorkspaceMembership = Depends(require_role(WorkspaceRole.member)),
):
    m = cmd.merge_merchant(session, workspace_id, merchant_id, body, membership)
    session.commit()
    session.refresh(m)
    return m


@router.delete("/{merchant_id}", response_model=StatusRead)
def delete_merchant(
    workspace_id: int,
    merchant_id: int,
    session: Session = Depends(get_session),
    membership: WorkspaceMembership = Depends(require_role(WorkspaceRole.member)),
):
    cmd.delete_merchant(session, workspace_id, merchant_id, membership)
    session.commit()
    return {"status": "ok"}
