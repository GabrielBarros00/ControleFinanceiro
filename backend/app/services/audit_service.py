from typing import Optional, Dict, Any
from sqlmodel import Session
from app.models.audit import AuditLog, ActionType

class AuditService:
    @staticmethod
    def log_action(
        db: Session,
        action: ActionType,
        user_id: Optional[int] = None,
        resource_type: Optional[str] = None,
        resource_id: Optional[int] = None,
        old_values: Optional[Dict[str, Any]] = None,
        new_values: Optional[Dict[str, Any]] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None
    ) -> AuditLog:
        """
        Registra uma ação no log de auditoria.
        """
        log_entry = AuditLog(
            action=action,
            user_id=user_id,
            resource_type=resource_type,
            resource_id=resource_id,
            old_values=old_values,
            new_values=new_values,
            ip_address=ip_address,
            user_agent=user_agent
        )
        
        db.add(log_entry)
        db.commit()
        db.refresh(log_entry)
        
        return log_entry
