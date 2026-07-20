from sqlmodel import Session, select
from app.models.audit import AuditLog, ActionType
from app.models.workspace import Workspace
from app.core.context import set_current_user_id
from app.models.user import User


def _make_actor(db):
    user = User(name='Auditor', email='auditor@test.com', password_hash='hash')
    db.add(user)
    db.commit()
    db.refresh(user)
    set_current_user_id(user.id)
    return user

def test_auto_audit_on_insert(db_session: Session):
    """
    Test that creating a model instance automatically triggers an AuditLog entry.
    """
    # Setup: Set user context
    actor = _make_actor(db_session)

    # Act: Create a model
    ws = Workspace(name="Auto Audit WS", created_by_user_id=actor.id)
    db_session.add(ws)
    db_session.commit()
    db_session.refresh(ws)
    
    # Assert: Check if AuditLog was created
    # Note: We might need to wait or refresh if using async, but this is sync Session
    log = db_session.exec(select(AuditLog).where(AuditLog.resource_type == "Workspace")).first()
    
    assert log is not None
    assert log.action == ActionType.create
    assert log.user_id == actor.id
    assert log.resource_id == ws.id
    assert log.new_values["name"] == "Auto Audit WS"

def test_auto_audit_never_stores_password_hash(db_session: Session):
    """A trilha de auditoria não pode conter o hash de senha (credencial)."""
    _make_actor(db_session)

    new_user = User(name="Alvo", email="alvo@test.com", password_hash="segredo-hash")
    db_session.add(new_user)
    db_session.commit()
    db_session.refresh(new_user)

    log = db_session.exec(
        select(AuditLog)
        .where(AuditLog.resource_type == "User")
        .where(AuditLog.action == ActionType.create)
        .where(AuditLog.resource_id == new_user.id)
    ).first()

    assert log is not None
    assert "password_hash" not in log.new_values
    # Campos não sensíveis continuam auditados
    assert log.new_values["email"] == "alvo@test.com"


def test_auto_audit_on_update(db_session: Session):
    """
    Test that updating a model instance automatically triggers an AuditLog entry.
    """
    # Setup
    actor = _make_actor(db_session)
    ws = Workspace(name="Original Name", created_by_user_id=actor.id)
    db_session.add(ws)
    db_session.commit()
    db_session.refresh(ws)
    
    # Act: Update the model
    ws.name = "Updated Name"
    db_session.add(ws)
    db_session.commit()
    db_session.refresh(ws)
    
    # Assert
    logs = db_session.exec(
        select(AuditLog)
        .where(AuditLog.resource_type == "Workspace")
        .where(AuditLog.action == ActionType.update)
    ).all()
    
    assert len(logs) == 1
    assert logs[0].new_values["name"] == "Updated Name"

def test_auto_audit_on_delete(db_session: Session):
    """
    Test that deleting a model instance automatically triggers an AuditLog entry.
    """
    # Setup
    actor = _make_actor(db_session)
    ws = Workspace(name="To be deleted", created_by_user_id=actor.id)
    db_session.add(ws)
    db_session.commit()
    db_session.refresh(ws)
    ws_id = ws.id
    
    # Act: Delete the model
    db_session.delete(ws)
    db_session.commit()
    
    # Assert
    log = db_session.exec(
        select(AuditLog)
        .where(AuditLog.resource_type == "Workspace")
        .where(AuditLog.action == ActionType.delete)
    ).first()
    
    assert log is not None
    assert log.resource_id == ws_id
