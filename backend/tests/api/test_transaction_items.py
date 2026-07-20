from sqlmodel import Session
from datetime import datetime
from app.models.transaction import SplitMethod
from app.schemas.transaction import TransactionCreate, TransactionPayerBase, TransactionSplitBase, TransactionItemCreate
from app.api.routes.transactions import create_transaction
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMembership

def test_create_transaction_with_items(db_session: Session):
    # Setup
    user = User(name="Item Tester", email="items@test.com", password_hash="hash")
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    
    workspace = Workspace(name="Item WS")
    db_session.add(workspace)
    db_session.commit()
    db_session.refresh(workspace)
    
    membership = WorkspaceMembership(workspace_id=workspace.id, user_id=user.id, role="owner")
    db_session.add(membership)
    db_session.commit()
    
    tx_in = TransactionCreate(
        title="Supermarket",
        total_amount=100.00,
        transaction_date=datetime.now(),
        payers=[TransactionPayerBase(user_id=user.id, amount=100.00)],
        splits=[TransactionSplitBase(user_id=user.id, split_method=SplitMethod.equal, input_value=100.00)],
        items=[
            TransactionItemCreate(title="Milk", amount=40.00),
            TransactionItemCreate(title="Bread", amount=60.00)
        ]
    )
    
    # Act
    tx = create_transaction(workspace_id=workspace.id, session=db_session, transaction_in=tx_in, membership=membership)
    
    # Assert
    assert tx.title == "Supermarket"
    assert len(tx.items) == 2
    assert tx.items[0].title == "Milk"
    assert tx.items[1].amount == 60.00
