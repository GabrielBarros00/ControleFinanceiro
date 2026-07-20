import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMembership
from app.models.transaction import Transaction, TransactionPayer, TransactionSplit, SplitMethod
from sqlmodel import Session, select
from app.core.jwt import create_access_token
from decimal import Decimal
from datetime import datetime, UTC

client = TestClient(app)

@pytest.fixture
def auth_header(db_session: Session):
    user = User(name="User 1", email="user1@example.com", password_hash="hash")
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    
    token = create_access_token(data={"sub": str(user.id)})
    return {"Cookie": f"access_token={token}"}

@pytest.fixture
def other_user(db_session: Session):
    user = User(name="User 2", email="user2@example.com", password_hash="hash")
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user

@pytest.fixture
def test_workspace(db_session: Session, auth_header, other_user):
    # Get current user
    user1 = db_session.exec(select(User).where(User.email == "user1@example.com")).first()
    
    ws = Workspace(name="Debt WS", created_by_user_id=user1.id)
    db_session.add(ws)
    db_session.commit()
    db_session.refresh(ws)
    
    # Add both users to workspace
    m1 = WorkspaceMembership(workspace_id=ws.id, user_id=user1.id, role="owner")
    m2 = WorkspaceMembership(workspace_id=ws.id, user_id=other_user.id, role="owner")
    db_session.add_all([m1, m2])
    db_session.commit()
    
    return ws

def test_get_workspace_debts(db_session: Session, auth_header, test_workspace, other_user, override_get_session):
    user1 = db_session.exec(select(User).where(User.email == "user1@example.com")).first()
    
    # User 1 pays 100, split 50/50 with User 2
    tx = Transaction(
        title="Dinner",
        total_amount=Decimal("100.00"),
        transaction_date=datetime.now(UTC),
        workspace_id=test_workspace.id,
        created_by_user_id=user1.id,
        currency="BRL",
        status="confirmed"
    )
    db_session.add(tx)
    db_session.commit()
    db_session.refresh(tx)
    
    # Payer
    p1 = TransactionPayer(transaction_id=tx.id, user_id=user1.id, amount=Decimal("100.00"))
    db_session.add(p1)
    
    # Splits
    s1 = TransactionSplit(transaction_id=tx.id, user_id=user1.id, split_method=SplitMethod.equal, input_value=Decimal("0"), computed_amount=Decimal("50.00"))
    s2 = TransactionSplit(transaction_id=tx.id, user_id=other_user.id, split_method=SplitMethod.equal, input_value=Decimal("0"), computed_amount=Decimal("50.00"))
    db_session.add_all([s1, s2])
    db_session.commit()
    
    response = client.get(f"/api/v1/workspaces/{test_workspace.id}/debts", headers=auth_header)
    assert response.status_code == 200
    data = response.json()
    
    # User 2 should owe User 1 50.00
    assert len(data) == 1
    assert data[0]["debtor_id"] == other_user.id
    assert data[0]["creditor_id"] == user1.id
    assert Decimal(data[0]["amount"]) == Decimal("50.00")
