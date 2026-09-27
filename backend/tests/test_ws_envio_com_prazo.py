"""Um cliente que não lê não trava a entrega dos outros (auditoria 2026-09-26, A4).

O `broadcast` enviava a cada socket em sequência, sem prazo, numa tarefa que
atende todos os espaços. Um celular que parou de ler segurava os eventos de
todo mundo. Aqui o socket travado é um `send_json` que nunca termina.
"""
import asyncio
import time

import pytest

from app.ws.manager import ConnectionManager


class _Socket:
    def __init__(self, travado: bool = False):
        self.travado = travado
        self.recebidos: list[dict] = []
        self.fechado_com: int | None = None

    async def send_json(self, mensagem: dict) -> None:
        if self.travado:
            await asyncio.sleep(3600)
        self.recebidos.append(mensagem)

    async def close(self, code: int = 1000) -> None:
        self.fechado_com = code


@pytest.mark.asyncio
async def test_socket_travado_nao_atrasa_os_outros_e_sai_da_sala():
    manager = ConnectionManager()
    manager.ENVIO_TIMEOUT_S = 0.2
    travado, saudavel = _Socket(travado=True), _Socket()
    # A sala é um `set` (sem ordem): no laço sequencial antigo, o travado segurava
    # o broadcast inteiro de qualquer jeito — antes ou depois do saudável.
    manager.connect(1, travado, user_id=10)
    manager.connect(1, saudavel, user_id=11)

    inicio = time.monotonic()
    # Prazo no próprio teste: com o envio antigo o broadcast esperava o socket
    # travado para sempre, e o teste penduraria o CI em vez de falhar.
    await asyncio.wait_for(manager.broadcast(1, {"type": "transaction.created", "seq": 7}), timeout=3)
    duracao = time.monotonic() - inicio

    assert saudavel.recebidos == [{"type": "transaction.created", "seq": 7}]
    assert duracao < 1.0, f"o broadcast levou {duracao:.2f}s"
    # O travado sai da sala e é fechado com um código que o cliente reconecta.
    assert travado not in manager.rooms.get(1, set())
    assert travado.fechado_com == 1013


@pytest.mark.asyncio
async def test_saudaveis_recebem_e_continuam_na_sala():
    manager = ConnectionManager()
    a, b = _Socket(), _Socket()
    manager.connect(2, a, user_id=1)
    manager.connect(2, b, user_id=2)
    await manager.broadcast(2, {"seq": 1})
    await manager.broadcast(2, {"seq": 2})
    assert a.recebidos == b.recebidos == [{"seq": 1}, {"seq": 2}]
    assert manager.rooms[2] == {a, b}
