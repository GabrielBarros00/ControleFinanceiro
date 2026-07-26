from typing import Optional, Tuple

import asyncio

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlmodel import select
from starlette.concurrency import run_in_threadpool

from app.core.jwt import decode_token
from app.db.session import session_scope
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


def _authorize(workspace_id: int, token: Optional[str]) -> Tuple[Optional[int], Optional[int]]:
    """Valida cookie + membership e devolve (user_id, event_seq).

    Roda numa sessão CURTA, aberta e fechada aqui dentro. Antes a sessão vinha
    de `Depends(get_session)` e só era liberada quando o socket caía — ou seja,
    uma conexão do pool ficava presa por aba aberta. Com o pool padrão (5 + 10
    overflow) bastavam ~15 abas para esgotar o pool e travar a API INTEIRA, não
    só o WebSocket.

    (None, None) = não autenticado; (user_id, None) = autenticado sem acesso ao
    workspace.
    """
    if not token:
        return None, None
    try:
        payload = decode_token(token)
        if payload.get("token_type") != "access":
            return None, None
        user_id = int(payload.get("sub"))
    except Exception:
        return None, None

    with session_scope() as session:
        user = session.get(User, user_id)
        # Conta desativada/excluída não abre socket (mesma regra do
        # get_current_user e do login)
        if not user or user.deleted_at is not None or not user.is_active:
            return None, None

        workspace = session.get(Workspace, workspace_id)
        membership = session.exec(
            select(WorkspaceMembership).where(
                WorkspaceMembership.workspace_id == workspace_id,
                WorkspaceMembership.user_id == user.id,
            )
        ).first()
        if not workspace or workspace.deleted_at is not None or not membership:
            return user.id, None

        return user.id, workspace.event_seq


@router.websocket("/ws/workspaces/{workspace_id}")
async def workspace_events(websocket: WebSocket, workspace_id: int):
    await websocket.accept()

    # Autenticação pelo cookie (o handshake WS envia cookies same-origin).
    # run_in_threadpool: o acesso ao banco é síncrono e não pode bloquear o
    # event loop no handshake de cada conexão.
    user_id, current_seq = await run_in_threadpool(
        _authorize, workspace_id, websocket.cookies.get("access_token")
    )
    if user_id is None:
        await websocket.close(code=WS_UNAUTHORIZED)
        return
    if current_seq is None:
        await websocket.close(code=WS_FORBIDDEN)
        return

    # Daqui para frente NÃO há sessão de banco aberta: a conexão do pool já foi
    # devolvida e o socket vive só com valores em memória.
    await websocket.send_json({
        "v": 1,
        "type": "hello",
        "workspace_id": workspace_id,
        "seq": current_seq,
    })
    manager.connect(workspace_id, websocket, user_id)

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
