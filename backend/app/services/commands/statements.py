"""Comandos da FATURA do cartão pessoal (ADR 0021/0024).

Movidos de `api/routes/me_cards.py` sem mudança de regra (ADR 0035): só o
`commit` saiu — quem chama (rota REST ou pipeline do MCP) comanda a transação.
"""
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Optional

from fastapi import HTTPException
from sqlmodel import Session, select

from app.domain.access_policy import assert_owns
from app.domain.account_policy import AccountCurrencyMismatch, assert_conta_na_moeda
from app.domain.dates import civil_day
from app.models.credit_card import CardStatement, CreditCard, StatementPayment, StatementStatus
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


# --- Pagamento registrado DEPOIS do fato (extrato importado, agente) — ADR 0037 ----------------

def fechar_se_o_ciclo_acabou(session: Session, stmt: CardStatement, referencia: date) -> bool:
    """Fatura ainda `open` com o fechamento em `referencia` ou antes: fecha.

    Pagar exige a fatura fechada (`CreditCardService.pay_statement`). Na tela,
    fechar é um clique separado; quem registra o pagamento depois do fato (a
    linha do extrato, o "paguei a fatura" dito ao agente) já diz que o ciclo
    acabou. Antes do fechamento, não: pagamento antecipado de fatura em curso
    fica para a tela, onde a pessoa vê o total ainda mudando.
    """
    if stmt.status != StatementStatus.open or civil_day(stmt.closing_date) > referencia:
        return False
    try:
        CreditCardService.close_statement(session, stmt)
    except StatementStateError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return True


def fatura_do_pagamento(session: Session, card: CreditCard, quando: date) -> Optional[CardStatement]:
    """A fatura que um pagamento feito em `quando` quita: a de fechamento mais
    recente até essa data que ainda tem saldo. None = nada a pagar nesse cartão."""
    candidatas = [
        f for f in session.exec(
            select(CardStatement)
            .where(
                CardStatement.card_id == card.id,
                CardStatement.status.in_([StatementStatus.closed, StatementStatus.open]),
            )
            .order_by(CardStatement.month)
        ).all()
        if civil_day(f.closing_date) <= quando
    ]
    if not candidatas:
        return None
    saldos = CreditCardService.balances(session, card, candidatas)
    com_saldo = [f for f in candidatas if saldos[f.id] > 0]
    return com_saldo[-1] if com_saldo else None


def estornar_pagamento(session: Session, user_id: int, payment_id: int) -> StatementPayment:
    """Estorna UM pagamento (o "Reabrir" da tela estorna todos os da fatura).

    Para desfazer a importação de um extrato: os outros pagamentos da mesma
    fatura não vieram do extrato e ficam. Fatura `paid` volta a `closed`, porque
    o saldo deixa de ser zero; `closed` continua `closed`. Idempotente.
    """
    pagamento = session.get(StatementPayment, payment_id)
    if pagamento is None:
        raise HTTPException(status_code=404, detail="Pagamento não encontrado")
    stmt = session.get(CardStatement, pagamento.statement_id)
    card = session.get(CreditCard, stmt.card_id) if stmt else None
    if card is None:
        raise HTTPException(status_code=404, detail="Pagamento não encontrado")
    _get_card_or_404(session, card.id, user_id)
    if pagamento.deleted_at is not None:
        return pagamento
    agora = datetime.now(UTC)
    pagamento.deleted_at = agora
    session.add(pagamento)
    if stmt.status == StatementStatus.paid:
        stmt.status = StatementStatus.closed
        stmt.paid_at = None
    stmt.updated_at = agora
    session.add(stmt)
    session.flush()
    return pagamento

