import asyncio
import logging
from typing import Dict, List, Optional, Set

from fastapi import WebSocket

logger = logging.getLogger("app.ws")

WS_FORBIDDEN = 4403


class ConnectionManager:
    """Gerencia conexões WebSocket por workspace (in-process).

    IMPORTANTE: este manager só funciona com UM processo uvicorn
    (--workers 1). Para escalar horizontalmente seria necessário um
    broker externo (ex: Redis pub/sub) — o seam é broadcast().
    """

    def __init__(self) -> None:
        self.rooms: Dict[int, Set[WebSocket]] = {}
        self.socket_users: Dict[WebSocket, int] = {}
        self.loop: Optional[asyncio.AbstractEventLoop] = None
        self.queue: Optional[asyncio.Queue] = None
        self._consumer_task: Optional[asyncio.Task] = None

    # --- ciclo de vida (chamado no lifespan do app) ---

    def startup(self) -> None:
        self.loop = asyncio.get_running_loop()
        self.queue = asyncio.Queue()
        self._consumer_task = self.loop.create_task(self._consume())

    async def shutdown(self) -> None:
        if self._consumer_task:
            self._consumer_task.cancel()
            self._consumer_task = None
        self.loop = None
        self.queue = None
        # As SALAS também. Este objeto é um singleton de módulo, e antes o
        # shutdown zerava só o loop e a fila — `rooms` e `socket_users` ficavam
        # com os sockets de um ciclo de vida que já acabou.
        #
        # Em produção isso é inócuo (o processo está morrendo junto). Em teste
        # cada `TestClient(app)` sobe e desce o lifespan e o singleton
        # atravessa; como o banco renasce a cada caso e os ids se repetem, um
        # socket órfão cairia exatamente na sala do teste seguinte.
        #
        # É DEFESA, não a cura de um defeito observado: no fechamento ordenado o
        # `finally` do handler já chama `disconnect` e a sala esvazia sozinha.
        # Não confunda com uma explicação do flake de
        # `test_two_clients_receive_seq_consistent_events` — foi por ali que
        # cheguei aqui, mas a ligação NÃO foi demonstrada.
        self.rooms.clear()
        self.socket_users.clear()

    # --- conexões ---

    def connect(self, workspace_id: int, websocket: WebSocket, user_id: int) -> None:
        self.rooms.setdefault(workspace_id, set()).add(websocket)
        self.socket_users[websocket] = user_id

    def disconnect(self, workspace_id: int, websocket: WebSocket) -> None:
        room = self.rooms.get(workspace_id)
        if room:
            room.discard(websocket)
            if not room:
                self.rooms.pop(workspace_id, None)
        self.socket_users.pop(websocket, None)

    # --- publicação ---

    def enqueue_from_thread(self, events: List[dict]) -> None:
        """Chamado do threadpool (rotas sync) após o commit da transação."""
        if self.loop is None or self.queue is None:
            return  # app sem lifespan (ex: testes REST puros) — sem entrega
        self.loop.call_soon_threadsafe(self._enqueue_many, events)

    def _enqueue_many(self, events: List[dict]) -> None:
        for event in events:
            self.queue.put_nowait(event)

    async def _consume(self) -> None:
        while True:
            event = await self.queue.get()
            try:
                await self.broadcast(event["workspace_id"], event)
                await self._enforce_access(event)
            except Exception:
                logger.exception("Erro ao transmitir evento WS")

    async def broadcast(self, workspace_id: int, message: dict) -> None:
        for websocket in list(self.rooms.get(workspace_id, ())):
            try:
                await websocket.send_json(message)
            except Exception:
                self.disconnect(workspace_id, websocket)

    async def _enforce_access(self, event: dict) -> None:
        """Revoga conexões que perderam acesso: membro removido (o próprio
        evento chega antes do close) e workspace excluído."""
        event_type = event.get("type", "")
        workspace_id = event.get("workspace_id")

        if event_type == "member.removed":
            removed_user_id = (event.get("resource") or {}).get("id")
            for websocket in list(self.rooms.get(workspace_id, ())):
                if self.socket_users.get(websocket) == removed_user_id:
                    await self._close_socket(workspace_id, websocket)

        elif event_type == "workspace.deleted":
            for websocket in list(self.rooms.get(workspace_id, ())):
                await self._close_socket(workspace_id, websocket)

    async def _close_socket(self, workspace_id: int, websocket: WebSocket) -> None:
        try:
            await websocket.close(code=WS_FORBIDDEN)
        except Exception:
            pass
        self.disconnect(workspace_id, websocket)


manager = ConnectionManager()
