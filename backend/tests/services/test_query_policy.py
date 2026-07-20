"""Política única de status/moeda nas agregações (ADR 0003/0006).

- draft/cancelled não entram em NADA;
- pending entra só na previsão;
- moeda fora da base (BRL) fica fora das agregações;
- estimativa soft-deletada não soma no orçamento do forecast.
"""
from datetime import datetime, date, UTC
from decimal import Decimal

from sqlmodel import Session

from app.models.estimate import MonthlyEstimate
from app.models.transaction import (
    Transaction,
    TransactionPayer,
    TransactionSplit,
    TransactionStatus,
    SplitMethod,
)
from app.services.debt_service import DebtService
from app.services.forecast_service import ForecastService
from app.services.report_service import ReportService

TX_DATE = datetime(2026, 6, 10, 12, 0, tzinfo=UTC)


def _make_tx(db, ws_id, payer_id, ower_id, total, status, currency="BRL"):
    tx = Transaction(
        title=f"Tx {status}",
        total_amount=Decimal(total),
        transaction_date=TX_DATE,
        billing_month="2026-06",
        workspace_id=ws_id,
        status=status,
        currency=currency,
    )
    db.add(tx)
    db.flush()
    db.add(TransactionPayer(transaction_id=tx.id, user_id=payer_id, amount=Decimal(total)))
    db.add(TransactionSplit(
        transaction_id=tx.id, user_id=ower_id, split_method=SplitMethod.fixed,
        input_value=Decimal(total), computed_amount=Decimal(total),
    ))
    db.commit()
    return tx


def test_dividas_ignoram_draft_pending_cancelled_e_moeda_estrangeira(
    db_session: Session, setup_data
):
    ws, u1, u2 = setup_data["ws1"], setup_data["u1"], setup_data["u2"]

    _make_tx(db_session, ws.id, u1.id, u2.id, "100.00", TransactionStatus.confirmed)
    _make_tx(db_session, ws.id, u1.id, u2.id, "50.00", TransactionStatus.draft)
    _make_tx(db_session, ws.id, u1.id, u2.id, "40.00", TransactionStatus.pending)
    _make_tx(db_session, ws.id, u1.id, u2.id, "30.00", TransactionStatus.cancelled)
    _make_tx(db_session, ws.id, u1.id, u2.id, "20.00", TransactionStatus.confirmed, currency="USD")

    debts = DebtService.get_workspace_debts(db_session, ws.id)
    # Só a confirmada em BRL conta: u2 deve exatamente 100 a u1
    assert debts == [
        {"debtor_id": u2.id, "creditor_id": u1.id, "amount": Decimal("100.00")}
    ]


def test_relatorio_realizado_exclui_pending(db_session: Session, setup_data):
    ws, u1, u2 = setup_data["ws1"], setup_data["u1"], setup_data["u2"]

    _make_tx(db_session, ws.id, u1.id, u2.id, "100.00", TransactionStatus.confirmed)
    _make_tx(db_session, ws.id, u1.id, u2.id, "40.00", TransactionStatus.pending)
    _make_tx(db_session, ws.id, u1.id, u2.id, "30.00", TransactionStatus.paid)

    summary = ReportService.get_summary(db_session, ws.id, date(2026, 6, 1))
    assert summary["total_expenses"] == 130.0  # confirmed + paid; pending fora


def test_forecast_inclui_pending_e_exclui_draft(db_session: Session, setup_data):
    ws, u1, u2 = setup_data["ws1"], setup_data["u1"], setup_data["u2"]

    _make_tx(db_session, ws.id, u1.id, u2.id, "100.00", TransactionStatus.confirmed)
    _make_tx(db_session, ws.id, u1.id, u2.id, "40.00", TransactionStatus.pending)
    _make_tx(db_session, ws.id, u1.id, u2.id, "50.00", TransactionStatus.draft)
    _make_tx(db_session, ws.id, u1.id, u2.id, "30.00", TransactionStatus.cancelled)

    projection = ForecastService.get_monthly_projection(db_session, ws.id, date(2026, 6, 1))
    assert projection["actual_spent"] == Decimal("140.00")  # confirmed + pending


def test_forecast_ignora_estimativa_soft_deletada(db_session: Session, setup_data):
    ws, u1 = setup_data["ws1"], setup_data["u1"]

    db_session.add(MonthlyEstimate(
        workspace_id=ws.id, user_id=u1.id, category="Mercado",
        amount=Decimal("500.00"), month="2026-06",
    ))
    db_session.add(MonthlyEstimate(
        workspace_id=ws.id, user_id=u1.id, category="Extinta",
        amount=Decimal("999.00"), month="2026-06",
        deleted_at=datetime.now(UTC),
    ))
    db_session.commit()

    projection = ForecastService.get_monthly_projection(db_session, ws.id, date(2026, 6, 1))
    assert projection["total_budget"] == Decimal("500.00")
