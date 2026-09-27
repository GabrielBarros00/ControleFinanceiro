"""Nenhuma rota nem dependência `async` usa a sessão do banco no event loop.

Auditoria 2026-09-26, C7. Com UM worker (regra do projeto: o WebSocket é
in-process), o event loop é o servidor inteiro. Uma rota `async def` que usa a
`Session` síncrona — ou calcula argon2 — trava todas as outras requisições e o
WebSocket enquanto roda. Medido: 7 logins simultâneos deixavam o `/health` com p95
de ~1 s; com as rotas em `def` (pool de threads), 35–81 ms.

A regra que este teste cobra: numa função `async` (rota ou dependência), o
parâmetro `Session` só pode aparecer DENTRO de uma função aninhada (que vai para o
pool de threads) ou como argumento de `run_in_threadpool`. `def` é sempre seguro:
o FastAPI já o roda no pool.
"""
import ast
import inspect
import textwrap

from sqlmodel import Session

from tests.support.rotas import rotas_da_api

_NO_POOL = {"run_in_threadpool", "to_thread"}


def _usos_no_loop(funcao) -> list[str]:
    """Usos do parâmetro `Session` que rodariam no event loop."""
    parametros = [
        nome for nome, p in inspect.signature(funcao).parameters.items()
        if p.annotation is Session
    ]
    if not parametros:
        return []
    arvore = ast.parse(textwrap.dedent(inspect.getsource(funcao)))
    raiz = arvore.body[0]
    pais: dict[ast.AST, ast.AST] = {}
    for no in ast.walk(raiz):
        for filho in ast.iter_child_nodes(no):
            pais[filho] = no

    def protegido(no: ast.AST) -> bool:
        atual = pais.get(no)
        while atual is not None and atual is not raiz:
            if isinstance(atual, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
                return True
            if isinstance(atual, ast.Call):
                alvo = atual.func
                nome = alvo.attr if isinstance(alvo, ast.Attribute) else getattr(alvo, "id", "")
                if nome in _NO_POOL:
                    return True
            atual = pais.get(atual)
        return False

    return [
        f"{funcao.__module__}.{funcao.__qualname__}: `{no.id}` na linha "
        f"{inspect.getsourcelines(funcao)[1] + no.lineno - 1}"
        for no in ast.walk(raiz)
        if isinstance(no, ast.Name) and no.id in parametros and not protegido(no)
    ]


def _chamaveis_async() -> set:
    """Rotas e dependências (em qualquer profundidade) que são corrotinas."""
    achados = set()

    def visita(dependant):
        if dependant.call is not None and inspect.iscoroutinefunction(dependant.call):
            achados.add(dependant.call)
        for sub in dependant.dependencies:
            visita(sub)

    for rota in rotas_da_api():
        if inspect.iscoroutinefunction(rota.endpoint):
            achados.add(rota.endpoint)
        visita(rota.dependant)
    return achados


def test_nenhuma_funcao_async_usa_o_banco_no_event_loop():
    chamaveis = _chamaveis_async()
    nomes = {f.__qualname__ for f in chamaveis}
    # Denominador: sem ele, uma travessia cega passaria em silêncio. Estas duas
    # SÃO `async` de propósito, e com banco — têm de estar na amostra.
    assert {"get_current_user", "register"} <= nomes, nomes

    problemas = [uso for f in chamaveis for uso in _usos_no_loop(f)]
    assert problemas == [], (
        "Sessão do banco usada no event loop — com um worker só, isso trava o "
        "servidor inteiro. Troque a rota para `def`, ou leve o trecho para "
        "`run_in_threadpool`:\n" + "\n".join(problemas)
    )


def test_as_rotas_do_anexo_b_viraram_def():
    """12 das 13 rotas que a auditoria achou `async` com sessão síncrona. A 13ª,
    o registro OAuth, segue `async` (lê JSON livre) com o banco no pool."""
    alvos = {
        ("app.api.routes.attachments", "upload_attachment"),
        ("app.api.routes.auth", "finish_onboarding"), ("app.api.routes.auth", "register"),
        ("app.api.routes.auth", "login"), ("app.api.routes.auth", "update_me"),
        ("app.api.routes.auth", "upload_avatar"), ("app.api.routes.auth", "delete_avatar"),
        ("app.api.routes.auth", "get_avatar"), ("app.api.routes.auth", "logout"),
        ("app.api.routes.auth", "refresh_session"), ("app.api.routes.auth", "change_password"),
        ("app.api.routes.mcp_uploads", "enviar_anexo_pelo_link"),
    }
    vistos = {
        (r.endpoint.__module__, r.endpoint.__name__): inspect.iscoroutinefunction(r.endpoint)
        for r in rotas_da_api()
    }
    assert alvos <= vistos.keys(), alvos - vistos.keys()
    assert [a for a in sorted(alvos) if vistos[a]] == []


def test_o_detector_enxerga_o_uso_direto_e_aceita_o_pool():
    """Controle: sem esta prova, um erro no detector deixaria o teste de cima
    verde para sempre."""

    async def direto(session: Session):
        return session.get(object, 1)

    async def no_pool(session: Session):
        from starlette.concurrency import run_in_threadpool

        def _faz():
            session.commit()

        await run_in_threadpool(_faz)
        return await run_in_threadpool(session.get, object, 1)

    async def sem_sessao(x: int):
        return x

    assert len(_usos_no_loop(direto)) == 1
    assert _usos_no_loop(no_pool) == []
    assert _usos_no_loop(sem_sessao) == []
