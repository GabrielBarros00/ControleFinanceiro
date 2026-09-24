"""Comandos da FATURA do cartão pessoal (ADR 0021/0024).

Movidos de `api/routes/me_cards.py` sem mudança de regra (ADR 0035): só o
`commit` saiu — quem chama (rota REST ou pipeline do MCP) comanda a transação.
"""
from datetime import datetime
from decimal import Decimal
from typing import Optional

from fastapi import HTTPException
from sqlmodel import Session

from app.domain.access_policy import assert_owns
from app.domain.account_policy import AccountCurrencyMismatch, assert_conta_na_moeda
from app.models.credit_card import CardStatement, CreditCard
from app.models.payment_account import PaymentAccount
from app.services.credit_card_service import CreditCardService, StatementStateError


def _get_card_or_404(session: Session, card_id: int, user_id: int) -> CreditCard:
    card = session.get(CreditCard, card_id)
    if not card or card.deleted_at:
        raise HTTPException(status_code=404, detail="Cartão não encontrado")
    assert_owns(card.owner_user_id, user_id, detail="Cartão não encontrado")
    return card


def _get_statement_or_404(session: Session, card: CreditCard, statement_id: int) -> CardStatement:
    stmt = session.get(CardStatement, statement_id)
    if not stmt or stmt.card_id != card.id:
        raise HTTPException(status_code=404, detail="Fatura não encontrada")
    return stmt


def pay_statement(
    session: Session,
    user_id: int,
    card_id: int,
    statement_id: int,
    *,
    account_id: Optional[int] = None,
    amount: Optional[Decimal] = None,
    paid_at: Optional[datetime] = None,
    note: Optional[str] = None,
) -> CardStatement:
    card = _get_card_or_404(session, card_id, user_id)
    stmt = _get_statement_or_404(session, card, statement_id)

    account = None
    if account_id is not None:
        account = session.get(PaymentAccount, account_id)
        # A conta de origem tem de ser DO DONO do cartão. Antes a checagem era
        # `account.workspace_id != workspace_id`, que num modelo de recurso
        # pessoal não quer dizer nada.
        if not account or account.deleted_at or account.owner_user_id != user_id:
            raise HTTPException(status_code=400, detail="Conta inválida")
        if not account.active:
            raise HTTPException(status_code=400, detail="Conta inativa não pode originar pagamento")
        # O pagamento é somado ao saldo da conta na moeda do CARTÃO (é assim que
        # `CashFlowService._pagamentos_de_fatura` o expressa). Conta em outra moeda
        # somaria moedas diferentes no saldo, em silêncio (ADR 0034).
        try:
            assert_conta_na_moeda(account, card.currency)
        except AccountCurrencyMismatch as exc:
            # 400 como os dois gates de conta logo acima, e não o 422 de validação:
            # o corpo é válido, a combinação é que não é.
            raise HTTPException(status_code=400, detail=str(exc))

    try:
        CreditCardService.pay_statement(
            session,
            stmt,
            account=account,
            amount=amount,
            paid_at=paid_at,
            note=note,
            user_id=user_id,
        )
    except StatementStateError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return stmt


def reopen_statement(session: Session, user_id: int, card_id: int, statement_id: int) -> CardStatement:
    """Desfaz um passo do ciclo (paga → fechada, fechada → aberta), estornando
    os pagamentos. Movido de `api/routes/me_cards.py` sem mudança de regra."""
    card = _get_card_or_404(session, card_id, user_id)
    stmt = _get_statement_or_404(session, card, statement_id)
    try:
        CreditCardService.reopen_statement(session, stmt)
    except StatementStateError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return stmt
