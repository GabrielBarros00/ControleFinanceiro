from decimal import Decimal
from sqlmodel import Session
from app.models.transaction import Transaction, TransactionPayer, TransactionSplit, SplitMethod
from app.models.workspace import Workspace
from app.models.user import User
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
