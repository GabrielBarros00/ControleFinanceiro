from decimal import Decimal
from sqlmodel import Session
from app.models.transaction import Transaction, TransactionSplit, TransactionPayer, SplitMethod
from app.models.workspace import Workspace
from app.models.user import User

def test_create_transaction_with_splits_and_payers(db_session: Session):
    # Setup: Workspace, Usuário e Dados
    user = User(name="Gabriel", email="gabriel@test.com", password_hash="hash")
    ws = Workspace(name="Casa")
    db_session.add_all([user, ws])
    db_session.flush()
    
    # Act: Criar Transação de R$ 100.00
    tx = Transaction(
        title="Mercado",
        total_amount=Decimal("100.00"),
        workspace_id=ws.id,
        created_by_user_id=user.id
    )
    db_session.add(tx)
    db_session.flush()
    
    # Payer: Gabriel pagou tudo
    payer = TransactionPayer(
        transaction_id=tx.id,
        user_id=user.id,
        amount=Decimal("100.00")
    )
    
    # Split: Gabriel deve 60, Amigo deve 40
    split1 = TransactionSplit(
        transaction_id=tx.id,
        user_id=user.id,
        split_method=SplitMethod.fixed,
        input_value=Decimal("60.00"),
        computed_amount=Decimal("60.00")
    )
    
    db_session.add_all([payer, split1])
    db_session.commit()
    
    # Assert
    db_session.refresh(tx)
    assert len(tx.payers) == 1
    assert len(tx.splits) == 1
    assert tx.total_amount == Decimal("100.00")
    assert tx.payers[0].amount == Decimal("100.00")

def test_transaction_soft_delete(db_session: Session, seed_ws):
    tx = Transaction(title="Test", total_amount=Decimal("10.00"), workspace_id=seed_ws["ws"].id)
    db_session.add(tx)
    db_session.commit()
    
    # Simular soft delete
    from datetime import datetime, UTC
    tx.deleted_at = datetime.now(UTC)
    db_session.add(tx)
    db_session.commit()
    
    # Verificar
    db_session.refresh(tx)
    assert tx.deleted_at is not None
