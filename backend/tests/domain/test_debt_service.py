from decimal import Decimal
from datetime import datetime
from sqlmodel import Session
from app.models.transaction import (
    Transaction,
    TransactionPayer,
    TransactionSplit,
    SplitMethod,
    TransactionStatus,
)
from app.models.workspace import Workspace
from app.models.user import User
from app.models.settlement import Settlement
from app.services.debt_service import DebtService

def test_calculate_net_debts_simple(db_session: Session):
    # Setup: Gabriel e João num Workspace
    u1 = User(name="Gabriel", email="g@test.com", password_hash="h")
    u2 = User(name="Joao", email="j@test.com", password_hash="h")
    ws = Workspace(name="WS")
    db_session.add_all([u1, u2, ws])
    db_session.flush()

    # Transação: Gabriel pagou R$ 100,00. Split 50/50.
    # Resultado esperado: João deve R$ 50,00 para Gabriel.
    tx = Transaction(title="Jantar", total_amount=Decimal("100.00"), workspace_id=ws.id)
    db_session.add(tx)
    db_session.flush()

    p1 = TransactionPayer(transaction_id=tx.id, user_id=u1.id, amount=Decimal("100.00"))
    s1 = TransactionSplit(transaction_id=tx.id, user_id=u1.id, split_method=SplitMethod.fixed, input_value=Decimal("50.00"), computed_amount=Decimal("50.00"))
    s2 = TransactionSplit(transaction_id=tx.id, user_id=u2.id, split_method=SplitMethod.fixed, input_value=Decimal("50.00"), computed_amount=Decimal("50.00"))
    
    db_session.add_all([p1, s1, s2])
    db_session.commit()

    # Act
    debts = DebtService.get_workspace_debts(db_session, ws.id)

    # Assert
    # O formato esperado é uma lista de devedores e quanto devem para quem
    # Joao -> Gabriel: 50.00
    assert len(debts) == 1
    debt = debts[0]
    assert debt["debtor_id"] == u2.id
    assert debt["creditor_id"] == u1.id
    assert debt["amount"] == Decimal("50.00")

def test_calculate_net_debts_complex(db_session: Session):
    # Cenário: Gabriel paga R$ 100 (50/50). João paga R$ 40 (50/50).
    # Gabriel deve 20 p/ João. João deve 50 p/ Gabriel.
    # Resultado Líquido: João deve 30 p/ Gabriel.
    u1 = User(name="Gabriel", email="g2@test.com", password_hash="h")
    u2 = User(name="Joao", email="j2@test.com", password_hash="h")
    ws = Workspace(name="WS2")
    db_session.add_all([u1, u2, ws])
    db_session.flush()

    # TX 1 (Gabriel pagou 100)
    tx1 = Transaction(title="TX1", total_amount=Decimal("100.00"), workspace_id=ws.id)
    db_session.add(tx1)
    db_session.flush()
    db_session.add(TransactionPayer(transaction_id=tx1.id, user_id=u1.id, amount=Decimal("100.00")))
    db_session.add(TransactionSplit(transaction_id=tx1.id, user_id=u1.id, computed_amount=Decimal("50.00"), input_value=Decimal("50"), split_method="fixed"))
    db_session.add(TransactionSplit(transaction_id=tx1.id, user_id=u2.id, computed_amount=Decimal("50.00"), input_value=Decimal("50"), split_method="fixed"))

    # TX 2 (João pagou 40)
    tx2 = Transaction(title="TX2", total_amount=Decimal("40.00"), workspace_id=ws.id)
    db_session.add(tx2)
    db_session.flush()
    db_session.add(TransactionPayer(transaction_id=tx2.id, user_id=u2.id, amount=Decimal("40.00")))
    db_session.add(TransactionSplit(transaction_id=tx2.id, user_id=u1.id, computed_amount=Decimal("20.00"), input_value=Decimal("20"), split_method="fixed"))
    db_session.add(TransactionSplit(transaction_id=tx2.id, user_id=u2.id, computed_amount=Decimal("20.00"), input_value=Decimal("20"), split_method="fixed"))
    
    db_session.commit()

    debts = DebtService.get_workspace_debts(db_session, ws.id)

    # João deve 30 para Gabriel
    assert len(debts) == 1
    assert debts[0]["debtor_id"] == u2.id
    assert debts[0]["creditor_id"] == u1.id
    assert debts[0]["amount"] == Decimal("30.00")


def _make_installment(db_session, ws_id, u1, u2, i, billing_month, status=TransactionStatus.confirmed):
    """Uma parcela i/3 de R$100 dividida 50/50, u1 paga tudo, no seu billing_month."""
    tx = Transaction(
        title=f"Geladeira ({i}/3)", total_amount=Decimal("100.00"),
        workspace_id=ws_id, billing_month=billing_month, status=status,
        installment_no=i, installments_of=3,
        transaction_date=datetime(2026, i, 10),
    )
    db_session.add(tx)
    db_session.flush()
    db_session.add(TransactionPayer(transaction_id=tx.id, user_id=u1.id, amount=Decimal("100.00")))
    db_session.add(TransactionSplit(transaction_id=tx.id, user_id=u1.id, split_method=SplitMethod.fixed, input_value=Decimal("50.00"), computed_amount=Decimal("50.00")))
    db_session.add(TransactionSplit(transaction_id=tx.id, user_id=u2.id, split_method=SplitMethod.fixed, input_value=Decimal("50.00"), computed_amount=Decimal("50.00")))
    return tx


def test_monthly_ledger_installments_per_month(db_session: Session):
    """Parcela 3x aparece SÓ no mês dela — é a 'dívida por mês' (issue 1)."""
    u1 = User(name="Gabriel", email="g3@test.com", password_hash="h")
    u2 = User(name="Joao", email="j3@test.com", password_hash="h")
    ws = Workspace(name="WS3")
    db_session.add_all([u1, u2, ws])
    db_session.flush()

    for i, bm in enumerate(["2026-01", "2026-02", "2026-03"], start=1):
        _make_installment(db_session, ws.id, u1, u2, i, bm)
    db_session.commit()

    jan = DebtService.get_monthly_ledger(db_session, ws.id, "2026-01")
    assert len(jan["expenses"]) == 1
    exp = jan["expenses"][0]
    assert exp["installment_no"] == 1
    assert exp["installments_of"] == 3
    assert exp["is_paid"] is False
    assert jan["totals"]["total"] == Decimal("100.00")
    assert jan["totals"]["open"] == Decimal("100.00")

    # No mês, u2 deve 50 a u1 (não os 150 do total)
    assert len(jan["net_debts"]) == 1
    assert jan["net_debts"][0]["debtor_id"] == u2.id
    assert jan["net_debts"][0]["creditor_id"] == u1.id
    assert jan["net_debts"][0]["amount"] == Decimal("50.00")

    members = {m["user_id"]: m for m in jan["members"]}
    assert members[u1.id]["paid"] == Decimal("100.00")
    assert members[u1.id]["owed"] == Decimal("50.00")
    assert members[u1.id]["balance"] == Decimal("50.00")
    assert members[u2.id]["balance"] == Decimal("-50.00")

    feb = DebtService.get_monthly_ledger(db_session, ws.id, "2026-02")
    assert len(feb["expenses"]) == 1
    assert feb["expenses"][0]["installment_no"] == 2

    # Mês sem despesa: retrato vazio
    empty = DebtService.get_monthly_ledger(db_session, ws.id, "2026-09")
    assert empty["expenses"] == []
    assert empty["net_debts"] == []
    assert empty["totals"]["total"] == Decimal("0.00")


def test_monthly_ledger_paid_status(db_session: Session):
    """Status 'paid' vira 'Paga' e entra no total pago do mês."""
    u1 = User(name="A", email="a4@test.com", password_hash="h")
    u2 = User(name="B", email="b4@test.com", password_hash="h")
    ws = Workspace(name="WS4")
    db_session.add_all([u1, u2, ws])
    db_session.flush()

    tx = _make_installment(db_session, ws.id, u1, u2, 1, "2026-05", status=TransactionStatus.paid)
    db_session.commit()

    may = DebtService.get_monthly_ledger(db_session, ws.id, "2026-05")
    assert may["expenses"][0]["is_paid"] is True
    assert may["totals"]["paid"] == Decimal("100.00")
    assert may["totals"]["open"] == Decimal("0.00")


def test_monthly_ledger_settlement_zeroes_month(db_session: Session):
    """Acerto vinculado ao mês (billing_month) quita a dívida daquele mês."""
    u1 = User(name="A", email="a5@test.com", password_hash="h")
    u2 = User(name="B", email="b5@test.com", password_hash="h")
    ws = Workspace(name="WS5")
    db_session.add_all([u1, u2, ws])
    db_session.flush()

    _make_installment(db_session, ws.id, u1, u2, 1, "2026-06")
    db_session.commit()

    before = DebtService.get_monthly_ledger(db_session, ws.id, "2026-06")
    assert len(before["net_debts"]) == 1
    assert before["net_debts"][0]["amount"] == Decimal("50.00")
    assert before["settled_total"] == Decimal("0.00")

    # u2 paga os 50 a u1, marcado para 2026-06 → mês quita
    db_session.add(Settlement(
        workspace_id=ws.id, from_user_id=u2.id, to_user_id=u1.id,
        amount=Decimal("50.00"), billing_month="2026-06",
    ))
    db_session.commit()

    after = DebtService.get_monthly_ledger(db_session, ws.id, "2026-06")
    assert after["net_debts"] == []
    assert after["settled_total"] == Decimal("50.00")
    assert len(after["settlements"]) == 1
    assert after["settlements"][0]["from_user_id"] == u2.id
    assert after["settlements"][0]["to_user_id"] == u1.id


def test_monthly_ledger_ignores_settlement_of_other_scope(db_session: Session):
    """Acerto global (billing_month=None) ou de outro mês não mexe no mês visto."""
    u1 = User(name="A", email="a6@test.com", password_hash="h")
    u2 = User(name="B", email="b6@test.com", password_hash="h")
    ws = Workspace(name="WS6")
    db_session.add_all([u1, u2, ws])
    db_session.flush()

    _make_installment(db_session, ws.id, u1, u2, 1, "2026-06")
    db_session.add(Settlement(workspace_id=ws.id, from_user_id=u2.id, to_user_id=u1.id, amount=Decimal("50.00"), billing_month=None))
    db_session.add(Settlement(workspace_id=ws.id, from_user_id=u2.id, to_user_id=u1.id, amount=Decimal("50.00"), billing_month="2026-07"))
    db_session.commit()

    jun = DebtService.get_monthly_ledger(db_session, ws.id, "2026-06")
    assert jun["settled_total"] == Decimal("0.00")
    assert len(jun["net_debts"]) == 1
    assert jun["net_debts"][0]["amount"] == Decimal("50.00")
