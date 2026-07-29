from datetime import datetime, UTC
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.schemas.common import DESCRIPTION_MAX, MAX_MONEY, NAME_MAX, OptionalCurrencyCode
from sqlmodel import Session, select

from app.db.session import get_session
from app.domain.query_policy import resolve_currency
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
    # None = "não informada" → a rota resolve para a moeda-base do workspace
    currency: OptionalCurrencyCode = None


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


def _serialize_statement(session: Session, stmt: CardStatement) -> dict:
    return {
        **stmt.model_dump(),
        "computed_total": CreditCardService.effective_total(session, stmt),
        "is_overdue": CreditCardService.is_overdue(stmt),
    }


def _serialize_card(session: Session, card: CreditCard) -> dict:
    overview = CreditCardService.card_overview(session, card)
    committed = overview["committed"]
    attention: Optional[CardStatement] = overview["attention"]
    return {
        **card.model_dump(),
        "committed_amount": committed,
        "available_limit": CreditCardService.available_limit(committed, card),
        # Fatura que pede atenção (a não paga mais antiga com valor): permite à
        # tela avisar "fechada", "vence em N dias" ou "vencida" por cartão, sem
        # precisar carregar as faturas de cada um.
        "next_due": None if attention is None else {
            "statement_id": attention.id,
            "month": attention.month,
            "status": attention.status,
            "closing_date": attention.closing_date,
            "due_date": attention.due_date,
            "amount": overview["attention_total"],
            "is_overdue": CreditCardService.is_overdue(attention),
        },
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
    data = card_in.model_dump()
    # Moeda ausente = a do workspace (nunca "BRL" fixo — ver resolve_currency)
    data["currency"] = resolve_currency(session, workspace_id, card_in.currency)
    card = CreditCard(**data, workspace_id=workspace_id)
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
    update_data = card_in.model_dump(exclude_unset=True)
    ciclo_mudou = any(
        campo in update_data and update_data[campo] != getattr(card, campo)
        for campo in ("closing_day", "due_day")
    )
    for key, value in update_data.items():
        setattr(card, key, value)
    card.updated_at = datetime.now(UTC)
    session.add(card)
    # Mudar os dias do ciclo tem que valer para a fatura em aberto: as datas
    # dela eram congeladas na criação, então corrigir o vencimento no cadastro
    # não mudava nada na tela — e o aviso continuava anunciando a data antiga.
    if ciclo_mudou:
        session.flush()
        CreditCardService.resync_open_statement_dates(session, card)
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

    # Fatura em aberto trava a exclusão. O soft delete só escondia o cartão: as
    # faturas não pagas continuavam existindo e ficavam INALCANÇÁVEIS (fechar/
    # pagar/reabrir passam por _get_card_or_404, que recusa cartão excluído).
    # Pior, a dívida sobrevivia só de um lado — a previsão somava a fatura e o
    # Endividamento não —, e não havia tela por onde resolver. Quitar antes é a
    # condição para o cartão sair sem deixar dívida órfã.
    overview = CreditCardService.card_overview(session, card)
    abertas = [
        s for s in overview["statements"]
        if s.status != StatementStatus.paid
        and CreditCardService.effective_total(session, s) > 0
    ]
    if abertas:
        meses = ", ".join(s.month for s in abertas[:3])
        reticencias = "…" if len(abertas) > 3 else ""
        raise HTTPException(
            status_code=409,
            detail=(
                f"Há {len(abertas)} fatura(s) em aberto neste cartão ({meses}{reticencias}). "
                "Pague-as (ou reabra e zere) antes de excluir — senão a dívida ficaria "
                "sem nenhuma tela por onde ser quitada."
            ),
        )

    card.deleted_at = datetime.now(UTC)
    session.add(card)
    publish_event(session, workspace_id, "credit_card.deleted", "credit_card", card.id, membership.user_id)
    session.commit()
    return {"status": "ok"}


@router.get("/{card_id}/statement-for")
def statement_for_date(
    workspace_id: int,
    card_id: int,
    on: datetime,
    session: Session = Depends(get_session),
    membership: WorkspaceMembership = Depends(get_workspace_membership),
):
    """Em qual fatura cairia uma compra neste cartão nesta data (ADR 0002).

    A fatura é derivada no SERVIDOR, e a regra não é óbvia: a partir do dia de
    fechamento a compra vai para o mês seguinte, e se essa fatura já estiver
    fechada/paga ela rola para frente. O formulário não mostrava nada disso — o
    usuário só descobria depois de salvar, e "por que minha compra de hoje está
    na fatura de setembro?" não tinha resposta na tela.

    Somente LEITURA: não cria fatura (senão digitar no formulário criaria faturas
    vazias). O `GET` não muda estado, então não precisa de papel de escrita.
    """
    card = _get_card_or_404(session, workspace_id, card_id)
    return CreditCardService.preview_statement_target(session, card, on)


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
