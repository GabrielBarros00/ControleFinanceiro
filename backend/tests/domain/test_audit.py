from sqlmodel import Session, select
from app.models.audit import AuditLog, ActionType
from app.models.user import User
from app.services.audit_service import AuditService

def test_create_audit_log(db_session: Session):
    # Setup: Usuário falso
    user = User(name="Auditor", email="audit@test.com", password_hash="hash")
    db_session.add(user)
    db_session.commit()

    # Act: Registrar um log de criação de transação
    AuditService.log_action(
        db=db_session,
        user_id=user.id,
        action=ActionType.create,
        resource_type="Transaction",
        resource_id=10,
        new_values={"total_amount": "100.00", "title": "Mercado"}
    )

    # Assert
    log = db_session.exec(select(AuditLog).where(AuditLog.resource_type == "Transaction")).first()
    assert log is not None
    assert log.user_id == user.id
    assert log.action == ActionType.create
    assert log.resource_type == "Transaction"
    assert log.resource_id == 10
    assert log.new_values == {"total_amount": "100.00", "title": "Mercado"}
    assert log.old_values is None

def test_update_audit_log(db_session: Session):
    # Setup
    user = User(name="Auditor2", email="audit2@test.com", password_hash="hash")
    db_session.add(user)
    db_session.commit()

    # Act
    AuditService.log_action(
        db=db_session,
        user_id=user.id,
        action=ActionType.update,
        resource_type="Transaction",
        resource_id=10,
        old_values={"total_amount": "100.00"},
        new_values={"total_amount": "150.00"}
    )

    # Assert
    logs = db_session.exec(select(AuditLog).where(AuditLog.action == ActionType.update)).all()
    assert len(logs) == 1
    log = logs[0]
    assert log.old_values["total_amount"] == "100.00"
    assert log.new_values["total_amount"] == "150.00"
