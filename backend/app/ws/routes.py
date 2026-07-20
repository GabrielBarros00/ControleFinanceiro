import asyncio

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from sqlmodel import Session, select

from app.core.jwt import decode_token
from app.db.session import get_session
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMembership
from app.ws.manager import manager

router = APIRouter(tags=["ws"])

# Códigos de fechamento customizados:
# 4401 = não autenticado/token expirado (cliente deve dar refresh e reconectar)
# 4403 = sem permissão no workspace (cliente deve parar de tentar)
WS_UNAUTHORIZED = 4401
WS_FORBIDDEN = 4403

PING_INTERVAL_SECONDS = 30


@router.websocket("/ws/workspaces/{workspace_id}")
async def workspace_events(
    websocket: WebSocket,
    workspace_id: int,
    session: Session = Depends(get_session),
):
    await websocket.accept()

    # Autenticação pelo cookie (o handshake WS envia cookies same-origin)
    user = None
    token = websocket.cookies.get("access_token")
    if token:
        try:
            payload = decode_token(token)
            if payload.get("token_type") == "access":
                user = session.get(User, int(payload.get("sub")))
        except Exception:
            user = None
    if not user:
        await websocket.close(code=WS_UNAUTHORIZED)
        return

    workspace = session.get(Workspace, workspace_id)
    membership = session.exec(
        select(WorkspaceMembership).where(
            WorkspaceMembership.workspace_id == workspace_id,
            WorkspaceMembership.user_id == user.id,
        )
    ).first()
    if not workspace or workspace.deleted_at is not None or not membership:
        await websocket.close(code=WS_FORBIDDEN)
        return

    current_seq = workspace.event_seq
    # Obs.: a sessão da dependency é fechada pelo FastAPI quando o socket
    # desconecta. Com --workers 1 e poucas conexões simultâneas (escala
    # doméstica), segurar a sessão durante a conexão é aceitável.

    await websocket.send_json({
        "v": 1,
        "type": "hello",
        "workspace_id": workspace_id,
        "seq": current_seq,
    })
    manager.connect(workspace_id, websocket, user.id)

    try:
        while True:
            try:
                message = await asyncio.wait_for(
                    websocket.receive_text(), timeout=PING_INTERVAL_SECONDS
                )
                if message == "ping":
                    await websocket.send_json({"type": "pong"})
            except asyncio.TimeoutError:
                # Heartbeat: cliente considera a conexão morta se ficar mudo
                await websocket.send_json({"type": "ping"})
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        manager.disconnect(workspace_id, websocket)
