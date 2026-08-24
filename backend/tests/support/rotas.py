"""Enumeração das rotas da API — o ÚNICO lugar que sabe onde o FastAPI as guarda.

Existe por causa de uma quebra SILENCIOSA, e é a parte silenciosa que justifica
o módulo.

Até o FastAPI 0.136, `include_router()` achatava as sub-rotas dentro de
`app.routes`, e as quatro varreduras do projeto repetiam o mesmo padrão:

    for rota in app.routes:
        if not isinstance(rota, APIRoute):
            continue

No 0.141 o `include_router()` deixou de achatar: ele anexa UM objeto
`_IncludedRouter` que resolve as sub-rotas na hora do match. O padrão acima
passou a enxergar **1 rota das 166** do app — e a que sobra é `/`.

Três das quatro varreduras tinham auto-verificação ("teste inútil", "a montagem
falhou", "não está medindo") e ficaram vermelhas na hora. A quarta — o gate do
307 em `tests/api/test_colecao_sem_barra.py` — ficou VERDE varrendo o vazio,
porque "nenhuma rota problemática" e "nenhuma rota" são a mesma asserção quando
ninguém olha o denominador. Um gate que o projeto criou depois de a armadilha
do 307 morder em produção passou a proteger exatamente uma rota, sem avisar.

Daí as duas decisões deste módulo:

1. `iter_route_contexts` é a travessia PÚBLICA do FastAPI — é a mesma que o
   `get_openapi()` dele usa para montar o schema. Não é atributo privado lido
   na marra, que quebraria de novo na próxima refatoração interna.
2. `_PISO` transforma a contagem em asserção. Uma varredura ainda pode ficar
   cega um dia; o que ela não pode é ficar cega em silêncio.
"""

from contextlib import contextmanager
from typing import Iterator

from fastapi import APIRouter
from fastapi.routing import APIRoute, RouteContext, iter_route_contexts

from app.main import app

# O app tem 166 rotas de API hoje. O piso existe para pegar COLAPSO (a travessia
# devolver 1, ou 3, como no 0.141), não para vigiar o número exato — remover
# meia dúzia de rotas é mudança normal e não deve reprovar ninguém. Se um dia o
# app encolher de verdade abaixo disto, baixe o piso no mesmo commit que remove
# as rotas, de propósito e por escrito.
_PISO = 150


def rotas_da_api() -> list[RouteContext]:
    """Toda rota de API do app, com o caminho EFETIVO (prefixos já aplicados).

    Devolve `RouteContext`, não `APIRoute`: é o que a travessia entrega e já
    expõe `.path`, `.path_format`, `.methods`, `.endpoint`, `.body_field` e
    `.dependant` com os mesmos nomes de antes — as varreduras seguem lendo os
    atributos que sempre leram.

    O filtro por `original_route` reproduz o `isinstance(rota, APIRoute)`
    antigo: fica de fora o que sempre ficou — `/openapi.json`, `/docs`,
    `/redoc` (que são `starlette.routing.Route`) e o WebSocket (que é
    `APIWebSocketRoute` e não tem método HTTP).
    """
    rotas = [
        contexto
        for contexto in iter_route_contexts(app.routes)
        if isinstance(contexto.original_route, APIRoute)
    ]

    assert len(rotas) >= _PISO, (
        f"a travessia devolveu só {len(rotas)} rotas (piso: {_PISO}) — as "
        "varreduras que dependem disto estariam medindo o vazio e passando. "
        "Quase sempre significa que o FastAPI mudou de novo onde guarda as "
        "rotas de um `include_router()`; conserte AQUI, não em cada teste."
    )
    return rotas


@contextmanager
def rota_temporaria(router: APIRouter) -> Iterator[None]:
    """Registra um router no app e o REMOVE ao sair, restaurando por snapshot.

    Quem precisa disto são os testes que provocam um 500 de propósito: só dá
    para observar o middleware de erro com um endpoint que estoura, e ele não
    pode sobrar no app depois.

    A limpeza anterior filtrava `app.router.routes` por `getattr(r, "path")`,
    e isso virou no-op no FastAPI 0.141: o que o `include_router()` anexa lá é
    um `_IncludedRouter`, que NÃO tem `.path` — o filtro não casava com nada,
    nada era removido e o endpoint-bomba vazava para o resto da sessão. Ficou
    escondido porque as varreduras (as únicas que chamam rota por rota) estavam
    cegas pelo mesmo motivo; consertar uma coisa sem a outra deixaria a suíte
    vermelha com um 500 vindo de um teste três arquivos acima.

    O snapshot não pergunta O QUE foi anexado, então não tem opinião sobre a
    representação interna do FastAPI — é o que o torna imune à próxima mudança.
    """
    antes = list(app.router.routes)
    app.include_router(router)
    try:
        yield
    finally:
        app.router.routes = antes
