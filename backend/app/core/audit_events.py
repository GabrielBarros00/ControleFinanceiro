from datetime import datetime, date
from decimal import Decimal
from enum import Enum
from sqlalchemy import event
from sqlalchemy.orm import Mapper
from app.models.audit import AuditLog, ActionType
from app.models.sync_event import SyncEvent
from app.core.context import get_current_user_id
from typing import Any, Dict

# Modelos de infraestrutura que não devem gerar trilha de auditoria
_AUDIT_EXCLUDED = (AuditLog, SyncEvent)

# Colunas com material sensível que nunca devem ser copiadas para a trilha de
# auditoria (o hash de senha é credencial — não pertence a um log de auditoria).
_SENSITIVE_COLUMNS = frozenset({"password_hash"})


def _workspace_id_of(target: Any):
    """workspace_id do alvo para a trilha (AUD-001). Para o próprio Workspace, é
    o id; demais modelos expõem workspace_id; User e afins ficam sem."""
    if target.__class__.__name__ == "Workspace":
        return getattr(target, "id", None)
    return getattr(target, "workspace_id", None)


def get_model_changes(target: Any) -> Dict[str, Any]:
    """
    Extracts current values of a model instance and serializes complex types.
    """
    changes = {}
    for column in target.__table__.columns:
        if column.name in _SENSITIVE_COLUMNS:
            continue
        val = getattr(target, column.name)
        if isinstance(val, (datetime, date)):
            val = val.isoformat()
        elif isinstance(val, Decimal):
            val = str(val)
        elif isinstance(val, Enum):
            val = val.value
        elif isinstance(val, bytes):
            # Blobs (ex: Attachment.data) não pertencem à trilha de auditoria
            val = f"<{len(val)} bytes>"
        changes[column.name] = val
    return changes

def register_audit_listeners():
    """
    Registers SQLAlchemy event listeners for automated auditing.
    """
    
    @event.listens_for(Mapper, "after_insert")
    def after_insert(mapper, connection, target):
        if isinstance(target, _AUDIT_EXCLUDED):
            return
        
        user_id = get_current_user_id()
        resource_type = target.__class__.__name__
        resource_id = getattr(target, "id", None)
        new_values = get_model_changes(target)
        
        # Create audit log entry using a new connection to avoid session conflicts
        connection.execute(
            AuditLog.__table__.insert().values(
                action=ActionType.create,
                user_id=user_id,
                resource_type=resource_type,
                resource_id=resource_id,
                workspace_id=_workspace_id_of(target),
                new_values=new_values,
                # ip_address/user_agent could be added here if passed via context
            )
        )

    @event.listens_for(Mapper, "after_update")
    def after_update(mapper, connection, target):
        if isinstance(target, _AUDIT_EXCLUDED):
            return
        
        user_id = get_current_user_id()
        resource_type = target.__class__.__name__
        resource_id = getattr(target, "id", None)
        
        # For simplicity in this first version, we log the state after update
        # A more advanced version would compare old vs new
        new_values = get_model_changes(target)
        
        connection.execute(
            AuditLog.__table__.insert().values(
                action=ActionType.update,
                user_id=user_id,
                resource_type=resource_type,
                resource_id=resource_id,
                workspace_id=_workspace_id_of(target),
                new_values=new_values,
            )
        )

    @event.listens_for(Mapper, "after_delete")
    def after_delete(mapper, connection, target):
        if isinstance(target, _AUDIT_EXCLUDED):
            return
        
        user_id = get_current_user_id()
        resource_type = target.__class__.__name__
        resource_id = getattr(target, "id", None)
        
        connection.execute(
            AuditLog.__table__.insert().values(
                action=ActionType.delete,
                user_id=user_id,
                resource_type=resource_type,
                resource_id=resource_id,
                workspace_id=_workspace_id_of(target),
            )
        )
