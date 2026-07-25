import calendar
from datetime import datetime, date, UTC
from decimal import Decimal
from typing import Optional

from sqlmodel import Session, select, func

from app.domain.query_policy import REALIZED_STATUSES, workspace_base_currency
from app.models.credit_card import (
    CreditCard,
    CardStatement,
    StatementPayment,
    StatementStatus,
)
from app.models.payment_account import PaymentAccount
from app.models.transaction import Transaction


def _safe_date(year: int, month: int, day: int) -> date:
    """Cria a data limitando o dia ao último dia do mês (dia 31 em fevereiro etc.)."""
    last_day = calendar.monthrange(year, month)[1]
    return date(year, month, min(day, last_day))


def _advance_month(year: int, month: int) -> tuple[int, int]:
    return (year + 1, 1) if month == 12 else (year, month + 1)


def _statement_dates(card: CreditCard, year: int, month: int) -> tuple[datetime, datetime]:
    """closing_date/due_date da fatura {year}-{month} a partir dos dias do cartão."""
    closing_date = _safe_date(year, month, card.closing_day)
    if card.due_day > card.closing_day:
        due_date = _safe_date(year, month, card.due_day)
    else:
        due_year, due_month = _advance_month(year, month)
        due_date = _safe_date(due_year, due_month, card.due_day)
    return (
        datetime.combine(closing_date, datetime.min.time()),
        datetime.combine(due_date, datetime.min.time()),
    )


class StatementStateError(ValueError):
    """Transição inválida do ciclo da fatura (o chamador traduz para 409)."""


class CreditCardService:
    @staticmethod
    def get_or_create_statement(
        db: Session,
        card: CreditCard,
        transaction_date: datetime,
    ) -> CardStatement:
        """Fatura correta para uma transação (ADR 0002).

        A partir do dia de fechamento, roteia para a fatura do mês certo; se essa
        fatura já estiver FECHADA/PAGA (imutável), rola para frente até achar uma
        aberta — cobrança que chega depois do fechamento cai na próxima fatura
        (ADR 0011), nunca reabre um mês já faturado.
        """
        t_date = transaction_date.date()

        # A partir do fechamento, a compra pertence à fatura do mês seguinte
        if t_date.day >= card.closing_day:
            year, month = _advance_month(t_date.year, t_date.month)
        else:
            year, month = t_date.year, t_date.month

        while True:
            statement_month = f"{year}-{month:02d}"
            statement = db.exec(
                select(CardStatement)
                .where(CardStatement.card_id == card.id)
                .where(CardStatement.month == statement_month)
            ).first()

            if statement is None:
                closing_dt, due_dt = _statement_dates(card, year, month)
                statement = CardStatement(
                    card_id=card.id,
                    month=statement_month,
                    closing_date=closing_dt,
                    due_date=due_dt,
                    status=StatementStatus.open,
                )
                db.add(statement)
                # flush, NUNCA commit (ADR 0010): o chamador comanda a transação
                db.flush()
                return statement

            if statement.status == StatementStatus.open:
                return statement

            # Fechada/paga é imutável: tenta o próximo mês
            year, month = _advance_month(year, month)

    @staticmethod
    def ensure_current_statement(db: Session, card: CreditCard, today: Optional[date] = None) -> CardStatement:
        """Garante que a fatura do ciclo CORRENTE exista (materialização preguiçosa).

        Sem isso a fatura só nascia quando chegava uma compra, então um mês sem
        gastos deixava a tela do cartão mostrando a fatura do mês passado como se
        fosse a atual. É a mesma fatura para onde uma compra de hoje iria.
        """
        ref = today or datetime.now(UTC).date()
        return CreditCardService.get_or_create_statement(
            db, card, datetime.combine(ref, datetime.min.time())
        )

    # ---- Totais e limite ----------------------------------------------------

    @staticmethod
    def compute_statement_total(db: Session, statement_id: int) -> Decimal:
        """Soma server-side das transações realizadas da fatura (fonte de verdade
        enquanto aberta). Ignora rascunho/cancelada e moeda diferente da base
        do workspace (ADR 0006)."""
        stmt = db.get(CardStatement, statement_id)
        base_currency = "BRL"
        if stmt:
            card = db.get(CreditCard, stmt.card_id)
            if card:
                base_currency = workspace_base_currency(db, card.workspace_id)
        total = db.exec(
            select(func.sum(Transaction.total_amount)).where(
                Transaction.statement_id == statement_id,
                Transaction.deleted_at.is_(None),
                Transaction.status.in_(REALIZED_STATUSES),
                Transaction.currency == base_currency,
            )
        ).one()
        return total or Decimal("0.00")

    @staticmethod
    def effective_total(db: Session, statement: CardStatement) -> Decimal:
        """Aberta → total calculado; fechada/paga → total CONGELADO no fechamento."""
        if statement.status == StatementStatus.open:
            return CreditCardService.compute_statement_total(db, statement.id)
        return statement.total_amount

    @staticmethod
    def card_committed(db: Session, card: CreditCard) -> Decimal:
        """Limite comprometido: soma das faturas ainda NÃO pagas (aberta usa total
        calculado; fechada usa o congelado). Fatura paga libera o limite."""
        statements = db.exec(
            select(CardStatement).where(CardStatement.card_id == card.id)
        ).all()
        committed = Decimal("0.00")
        for stmt in statements:
            if stmt.status == StatementStatus.paid:
                continue
            committed += CreditCardService.effective_total(db, stmt)
        return committed

    @staticmethod
    def available_limit(committed: Decimal, card: CreditCard) -> Decimal:
        return card.limit - committed

    # ---- Máquina de estados (ADR 0011) --------------------------------------

    @staticmethod
    def close_statement(db: Session, statement: CardStatement) -> CardStatement:
        if statement.status != StatementStatus.open:
            raise StatementStateError("Só é possível fechar uma fatura aberta")
        statement.status = StatementStatus.closed
        statement.closed_at = datetime.now(UTC)
        # Congela o valor faturado: edições posteriores nas transações não mudam
        # o que foi cobrado (o histórico do mês fica estável)
        statement.total_amount = CreditCardService.compute_statement_total(db, statement.id)
        statement.updated_at = datetime.now(UTC)
        db.add(statement)
        db.flush()
        return statement

    @staticmethod
    def pay_statement(
        db: Session,
        statement: CardStatement,
        *,
        workspace_id: int,
        account: Optional[PaymentAccount],
        amount: Optional[Decimal],
        paid_at: Optional[datetime],
        note: Optional[str],
        user_id: Optional[int],
    ) -> StatementPayment:
        if statement.status != StatementStatus.closed:
            raise StatementStateError("Feche a fatura antes de pagá-la")
        pay_amount = amount if amount is not None else statement.total_amount
        if pay_amount <= 0:
            raise StatementStateError("Valor do pagamento deve ser positivo")

        payment = StatementPayment(
            workspace_id=workspace_id,
            statement_id=statement.id,
            account_id=account.id if account else None,
            amount=pay_amount,
            paid_at=paid_at or datetime.now(UTC),
            note=note,
            created_by_user_id=user_id,
        )
        db.add(payment)
        statement.status = StatementStatus.paid
        statement.paid_at = payment.paid_at
        statement.updated_at = datetime.now(UTC)
        db.add(statement)
        db.flush()
        return payment

    @staticmethod
    def reopen_statement(db: Session, statement: CardStatement) -> CardStatement:
        """Desfaz um passo do ciclo: paga→fechada (estorna o pagamento) ou
        fechada→aberta (volta a somar em tempo real)."""
        now = datetime.now(UTC)
        if statement.status == StatementStatus.paid:
            for payment in db.exec(
                select(StatementPayment).where(
                    StatementPayment.statement_id == statement.id,
                    StatementPayment.deleted_at.is_(None),
                )
            ).all():
                payment.deleted_at = now
                db.add(payment)
            statement.status = StatementStatus.closed
            statement.paid_at = None
        elif statement.status == StatementStatus.closed:
            statement.status = StatementStatus.open
            statement.closed_at = None
        else:
            raise StatementStateError("Fatura já está aberta")
        statement.updated_at = now
        db.add(statement)
        db.flush()
        return statement
