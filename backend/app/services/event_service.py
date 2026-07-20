from datetime import datetime, UTC
from typing import Optional

from sqlalchemy import event as sa_event
from sqlalchemy import update
from sqlmodel import Session

from app.models.sync_event import SyncEvent
from app.models.workspace import Workspace
from app.ws.manager import manager

_PENDING_KEY = "pending_ws_events"
_listeners_registered = False


def publish_event(
    session: Session,
    workspace_id: int,
    event_type: str,
    resource_type: Optional[str] = None,
    resource_id: Optional[int] = None,
    actor_user_id: Optional[int] = None,
) -> int:
    """Aloca o próximo seq do workspace e registra o evento NA MESMA transação.

    O envelope só é transmitido via WebSocket após o commit (listener
    after_commit) — dado não commitado nunca é broadcast. Retorna o seq.

    O bump do seq usa UPDATE ... RETURNING via Core: atômico e sem passar
    pelos mapper events (não gera AuditLog espúrio).
    """
    seq = session.execute(
        update(Workspace)
        .where(Workspace.id == workspace_id)
        .values(event_seq=Workspace.event_seq + 1)
        .returning(Workspace.event_seq)
    ).scalar_one()

    session.add(SyncEvent(
        workspace_id=workspace_id,
        seq=seq,
        event_type=event_type,
        resource_type=resource_type,
        resource_id=resource_id,
        actor_user_id=actor_user_id,
    ))

    envelope = {
        "v": 1,
        "workspace_id": workspace_id,
        "seq": seq,
        "type": event_type,
        "resource": {"type": resource_type, "id": resource_id},
        "actor_user_id": actor_user_id,
        "ts": datetime.now(UTC).isoformat(),
    }
    session.info.setdefault(_PENDING_KEY, []).append(envelope)
    return seq


def register_event_listeners() -> None:
    """Registra o listener after_commit que entrega os envelopes ao manager."""
    global _listeners_registered
    if _listeners_registered:
        return
    _listeners_registered = True

    @sa_event.listens_for(Session, "after_commit")
    def _deliver_after_commit(session):
        pending = session.info.pop(_PENDING_KEY, None)
        if pending:
            manager.enqueue_from_thread(pending)

    @sa_event.listens_for(Session, "after_rollback")
    def _drop_after_rollback(session):
        session.info.pop(_PENDING_KEY, None)
