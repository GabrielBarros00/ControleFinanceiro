from typing import Optional, Tuple

import asyncio
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlmodel import select
from starlette.concurrency import run_in_threadpool

from app.core.jwt import decode_token
from app.db.session import session_scope
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMembership
from app.ws.manager import manager

router = APIRouter(tags=["ws"])

# Mesmo logger do `manager.py`: o que acontece com um socket é uma história só.
logger = logging.getLogger("app.ws")

# Códigos de fechamento customizados:
# 4401 = não autenticado/token expirado (cliente deve dar refresh e reconectar)
# 4403 = sem permissão no workspace (cliente deve parar de tentar)
WS_UNAUTHORIZED = 4401
WS_FORBIDDEN = 4403
# 1011 é do PADRÃO WebSocket (RFC 6455), não customizado: "o servidor encontrou
# uma condição inesperada". O cliente deve tentar reconectar — ao contrário do
# 4403, que manda parar.
WS_INTERNAL_ERROR = 1011

PING_INTERVAL_SECONDS = 30


def _authorize(workspace_id: int, token: Optional[str]) -> Tuple[Optional[int], bool]:
    """Valida cookie + membership e devolve (user_id, tem_acesso).

    Roda numa sessão CURTA, aberta e fechada aqui dentro. Antes a sessão vinha
    de `Depends(get_session)` e só era liberada quando o socket caía — ou seja,
    uma conexão do pool ficava presa por aba aberta. Com o pool padrão (5 + 10
    overflow) bastavam ~15 abas para esgotar o pool e travar a API INTEIRA, não
    só o WebSocket.

    (None, False) = não autenticado; (user_id, False) = autenticado sem acesso
    ao workspace.
    """
    if not token:
        return None, False
    try:
        payload = decode_token(token)
        if payload.get("token_type") != "access":
            return None, False
        user_id = int(payload.get("sub"))
    except Exception:
        return None, False

    with session_scope() as session:
        user = session.get(User, user_id)
        # Conta desativada/excluída não abre socket (mesma regra do
        # get_current_user e do login)
        if not user or user.deleted_at is not None or not user.is_active:
            return None, False

        workspace = session.get(Workspace, workspace_id)
        membership = session.exec(
            select(WorkspaceMembership).where(
                WorkspaceMembership.workspace_id == workspace_id,
                WorkspaceMembership.user_id == user.id,
            )
        ).first()
        if not workspace or workspace.deleted_at is not None or not membership:
            return user.id, False

        return user.id, True


def _current_seq(workspace_id: int) -> Optional[int]:
    """Seq atual do workspace, lido DEPOIS de o socket entrar na sala.

    None = o workspace deixou de existir entre a autorização e esta leitura.
    """
    with session_scope() as session:
        workspace = session.get(Workspace, workspace_id)
        if not workspace or workspace.deleted_at is not None:
            return None
        return workspace.event_seq


@router.websocket("/ws/workspaces/{workspace_id}")
async def workspace_events(websocket: WebSocket, workspace_id: int):
    await websocket.accept()

    # Autenticação pelo cookie (o handshake WS envia cookies same-origin).
    # run_in_threadpool: o acesso ao banco é síncrono e não pode bloquear o
    # event loop no handshake de cada conexão.
    user_id, has_access = await run_in_threadpool(
        _authorize, workspace_id, websocket.cookies.get("access_token")
    )
    if user_id is None:
        await websocket.close(code=WS_UNAUTHORIZED)
        return
    if not has_access:
        await websocket.close(code=WS_FORBIDDEN)
        return

    # A ORDEM AQUI É O CONTRATO: entrar na sala ANTES de ler o seq que vai no
    # `hello`. Antes era o contrário (lia o seq, mandava o hello, entrava na
    # sala) e toda mutação commitada nessa janela era publicada para uma sala
    # que ainda não continha este socket — evento perdido, e perdido em
    # SILÊNCIO: o cliente recebia `hello` com o seq já contando o evento e se
    # considerava em dia. Trocar de workspace batia nisso quase sempre (o
    # switcher refaz as queries na hora e o handshake leva centenas de ms), o
    # que aparecia como "o socket novo recebe o hello e nenhum evento depois".
    #
    # Nesta ordem, todo evento com seq > `current_seq` cai numa sala que já tem
    # este socket. O preço é que um evento publicado entre a entrada na sala e a
    # leitura do seq pode chegar ANTES do `hello` (seq <= hello.seq) — previsto
    # no contrato do cliente, que trata o `hello` como marco de sincronismo e
    # nunca regride o seq visto.
    manager.connect(workspace_id, websocket, user_id)

    try:
        # Daqui para frente NÃO fica sessão de banco aberta: cada leitura abre e
        # fecha a sua, e o socket vive só com valores em memória.
        current_seq = await run_in_threadpool(_current_seq, workspace_id)
        if current_seq is None:
            await websocket.close(code=WS_FORBIDDEN)
            return

        await websocket.send_json({
            "v": 1,
            "type": "hello",
            "workspace_id": workspace_id,
            "seq": current_seq,
        })

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
        # Saída NORMAL: aba fechada, navegação, rede caindo. Não é erro.
        pass
    except Exception:
        # Engolir sem registrar deixava o socket morrer MUDO, e o silêncio era o
        # problema: um erro de verdade aqui dentro — um `OperationalError` do
        # banco sob concorrência, uma falha ao serializar — chega ao cliente como
        # um disconnect indistinguível de uma aba fechada. Em produção ninguém
        # fica sabendo; no CI vira um `WebSocketDisconnect` sem uma linha que
        # diga por quê (foi o que custou a investigação do flake de
        # `test_two_clients_receive_seq_consistent_events`).
        #
        # Continua NÃO relançando: derrubar este socket é a resposta certa, e um
        # erro numa conexão não deve virar 500 em lugar nenhum. O que muda é que
        # agora ele deixa rastro.
        logger.exception(
            "Erro no socket do workspace %s (user %s)", workspace_id, user_id
        )
        # E FECHAR. Sem isto o handler simplesmente retornava, e o socket ficava
        # pendurado: o cliente esperava para sempre uma mensagem que nunca viria
        # — não recebia evento, não recebia close, e nem sequer sabia que devia
        # reconectar. Só o heartbeat do navegador acabaria percebendo, minutos
        # depois. 1011 é o código padrão de "erro interno do servidor" e diz ao
        # cliente exatamente o que houve.
        try:
            await websocket.close(code=WS_INTERNAL_ERROR)
        except Exception:
            # O socket pode já estar morto (foi o erro que o matou). Aqui o
            # silêncio é legítimo: a exceção de verdade já foi registrada acima.
            pass
    finally:
        manager.disconnect(workspace_id, websocket)
