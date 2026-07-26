from datetime import datetime, UTC
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.schemas.common import DESCRIPTION_MAX, MAX_MONEY, NAME_MAX
from sqlmodel import Session, select

from app.db.session import get_session
from app.models.workspace import WorkspaceMembership, WorkspaceRole
from app.models.credit_card import CreditCard, CardStatement, StatementStatus
from app.models.payment_account import PaymentAccount
from app.models.transaction import Transaction
from app.api.deps import get_workspace_membership, require_role
from app.services.credit_card_service import CreditCardService, StatementStateError
from app.services.event_service import publish_event

router = APIRouter(prefix="/workspaces/{workspace_id}/credit-cards", tags=["credit-cards"])


class CreditCardCreate(BaseModel):
    """Schema explícito de criação — evita mass assignment de id/deleted_at."""
    name: str = Field(min_length=1, max_length=NAME_MAX)
    limit: Decimal = Field(gt=0, le=MAX_MONEY)
    closing_day: int = Field(ge=1, le=31)
    due_day: int = Field(ge=1, le=31)
    currency: str = "BRL"


class CreditCardUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=NAME_MAX)
    limit: Optional[Decimal] = Field(default=None, gt=0, le=MAX_MONEY)
    closing_day: Optional[int] = Field(default=None, ge=1, le=31)
    due_day: Optional[int] = Field(default=None, ge=1, le=31)


class StatementPayRequest(BaseModel):
    account_id: Optional[int] = None
    amount: Optional[Decimal] = Field(default=None, gt=0, le=MAX_MONEY)
    paid_at: Optional[datetime] = None
    note: Optional[str] = Field(default=None, max_length=DESCRIPTION_MAX)


def _get_card_or_404(session: Session, workspace_id: int, card_id: int) -> CreditCard:
    card = session.get(CreditCard, card_id)
    if not card or card.workspace_id != workspace_id or card.deleted_at:
        raise HTTPException(status_code=404, detail="Cartão não encontrado")
    return card


def _get_statement_or_404(session: Session, card: CreditCard, statement_id: int) -> CardStatement:
    stmt = session.get(CardStatement, statement_id)
    if not stmt or stmt.card_id != card.id:
        raise HTTPException(status_code=404, detail="Fatura não encontrada")
    return stmt


def _is_overdue(stmt: CardStatement) -> bool:
    """Vencida = não paga e passou do vencimento (derivado, não persistido —
    evita depender de um job para carimbar status)."""
    if stmt.status == StatementStatus.paid:
        return False
    return datetime.now(UTC).date() > stmt.due_date.date()


def _serialize_statement(session: Session, stmt: CardStatement) -> dict:
    return {
        **stmt.model_dump(),
        "computed_total": CreditCardService.effective_total(session, stmt),
        "is_overdue": _is_overdue(stmt),
    }


def _serialize_card(session: Session, card: CreditCard) -> dict:
    committed = CreditCardService.card_committed(session, card)
    return {
        **card.model_dump(),
        "committed_amount": committed,
        "available_limit": CreditCardService.available_limit(committed, card),
    }


@router.get("/")
def list_credit_cards(
    workspace_id: int,
    session: Session = Depends(get_session),
    membership: WorkspaceMembership = Depends(get_workspace_membership)
):
    cards = session.exec(
        select(CreditCard).where(
            CreditCard.workspace_id == workspace_id,
            CreditCard.deleted_at.is_(None),
        )
    ).all()
    return [_serialize_card(session, card) for card in cards]


@router.post("/")
def create_credit_card(
    workspace_id: int,
    card_in: CreditCardCreate,
    session: Session = Depends(get_session),
    membership: WorkspaceMembership = Depends(require_role(WorkspaceRole.member))
):
    card = CreditCard(**card_in.model_dump(), workspace_id=workspace_id)
    session.add(card)
    session.flush()
    publish_event(session, workspace_id, "credit_card.created", "credit_card", card.id, membership.user_id)
    session.commit()
    session.refresh(card)
    return _serialize_card(session, card)


@router.put("/{card_id}")
def update_credit_card(
    workspace_id: int,
    card_id: int,
    card_in: CreditCardUpdate,
    session: Session = Depends(get_session),
    membership: WorkspaceMembership = Depends(require_role(WorkspaceRole.member))
):
    card = _get_card_or_404(session, workspace_id, card_id)
    for key, value in card_in.model_dump(exclude_unset=True).items():
        setattr(card, key, value)
    card.updated_at = datetime.now(UTC)
    session.add(card)
    publish_event(session, workspace_id, "credit_card.updated", "credit_card", card.id, membership.user_id)
    session.commit()
    session.refresh(card)
    return _serialize_card(session, card)


@router.delete("/{card_id}")
def delete_credit_card(
    workspace_id: int,
    card_id: int,
    session: Session = Depends(get_session),
    membership: WorkspaceMembership = Depends(require_role(WorkspaceRole.member))
):
    card = _get_card_or_404(session, workspace_id, card_id)
    card.deleted_at = datetime.now(UTC)
    session.add(card)
    publish_event(session, workspace_id, "credit_card.deleted", "credit_card", card.id, membership.user_id)
    session.commit()
    return {"status": "ok"}


@router.get("/{card_id}/statements")
def list_statements(
    workspace_id: int,
    card_id: int,
    session: Session = Depends(get_session),
    membership: WorkspaceMembership = Depends(get_workspace_membership)
):
    card = _get_card_or_404(session, workspace_id, card_id)
    # Materializa a fatura do ciclo corrente antes de listar: um mês sem compras
    # não gerava fatura e a tela abria no mês anterior como se fosse o atual.
    # Best-effort — nunca derruba o GET (a criação é acessória à leitura).
    current_month = None
    try:
        current_month = CreditCardService.ensure_current_statement(session, card).month
        session.commit()
    except Exception:
        session.rollback()
    statements = session.exec(
        select(CardStatement)
        .where(CardStatement.card_id == card.id)
        .order_by(CardStatement.month.desc())
    ).all()
    # is_current marca o ciclo aberto de hoje. A tela não pode deduzir isso de
    # "a mais recente": uma compra lançada com data futura cria uma fatura à
    # frente, e ela não é a fatura atual.
    return [
        {**_serialize_statement(session, s), "is_current": s.month == current_month}
        for s in statements
    ]


@router.get("/{card_id}/statements/{statement_id}")
def get_statement(
    workspace_id: int,
    card_id: int,
    statement_id: int,
    session: Session = Depends(get_session),
    membership: WorkspaceMembership = Depends(get_workspace_membership)
):
    card = _get_card_or_404(session, workspace_id, card_id)
    stmt = _get_statement_or_404(session, card, statement_id)

    transactions = session.exec(
        select(Transaction).where(
            Transaction.statement_id == stmt.id,
            Transaction.deleted_at.is_(None),
        ).order_by(Transaction.transaction_date.desc())
    ).all()

    return {
        **_serialize_statement(session, stmt),
        "transactions": transactions,
    }


# ---- Ciclo da fatura (ADR 0011) --------------------------------------------


@router.post("/{card_id}/statements/{statement_id}/close")
def close_statement(
    workspace_id: int,
    card_id: int,
    statement_id: int,
    session: Session = Depends(get_session),
    membership: WorkspaceMembership = Depends(require_role(WorkspaceRole.member)),
):
    card = _get_card_or_404(session, workspace_id, card_id)
    stmt = _get_statement_or_404(session, card, statement_id)
    try:
        CreditCardService.close_statement(session, stmt)
    except StatementStateError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    publish_event(session, workspace_id, "credit_card.statement_closed", "card_statement", stmt.id, membership.user_id)
    session.commit()
    session.refresh(stmt)
    return _serialize_statement(session, stmt)


@router.post("/{card_id}/statements/{statement_id}/pay")
def pay_statement(
    workspace_id: int,
    card_id: int,
    statement_id: int,
    body: StatementPayRequest,
    session: Session = Depends(get_session),
    membership: WorkspaceMembership = Depends(require_role(WorkspaceRole.member)),
):
    card = _get_card_or_404(session, workspace_id, card_id)
    stmt = _get_statement_or_404(session, card, statement_id)

    account = None
    if body.account_id is not None:
        account = session.get(PaymentAccount, body.account_id)
        if not account or account.workspace_id != workspace_id or account.deleted_at:
            raise HTTPException(status_code=400, detail="Conta inválida para este workspace")
        if not account.active:
            raise HTTPException(status_code=400, detail="Conta inativa não pode originar pagamento")

    try:
        CreditCardService.pay_statement(
            session,
            stmt,
            workspace_id=workspace_id,
            account=account,
            amount=body.amount,
            paid_at=body.paid_at,
            note=body.note,
            user_id=membership.user_id,
        )
    except StatementStateError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    publish_event(session, workspace_id, "credit_card.statement_paid", "card_statement", stmt.id, membership.user_id)
    session.commit()
    session.refresh(stmt)
    return _serialize_statement(session, stmt)


@router.post("/{card_id}/statements/{statement_id}/reopen")
def reopen_statement(
    workspace_id: int,
    card_id: int,
    statement_id: int,
    session: Session = Depends(get_session),
    membership: WorkspaceMembership = Depends(require_role(WorkspaceRole.member)),
):
    card = _get_card_or_404(session, workspace_id, card_id)
    stmt = _get_statement_or_404(session, card, statement_id)
    try:
        CreditCardService.reopen_statement(session, stmt)
    except StatementStateError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    publish_event(session, workspace_id, "credit_card.statement_reopened", "card_statement", stmt.id, membership.user_id)
    session.commit()
    session.refresh(stmt)
    return _serialize_statement(session, stmt)
