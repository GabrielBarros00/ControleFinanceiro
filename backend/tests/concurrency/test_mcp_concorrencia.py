"""Invariantes da integração MCP sob concorrência REAL (ADR 0035).

Agente repete chamada — timeout, resposta perdida, dois cliques no botão do
componente. Cada proteção daqui é um "no máximo uma vez" que só se prova com
duas transações ao mesmo tempo, e as de MVCC só no Postgres (ver o cabeçalho de
`test_invariantes_sob_concorrencia.py`):

- a mesma `idempotency_key` em N chamadas simultâneas cria UMA despesa;
- o mesmo `confirmation_token` executa a exclusão em massa UMA vez;
- o mesmo refresh token gera UM par novo;
- o mesmo código de autorização vira UM token.
"""
from __future__ import annotations

import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager

import pytest
from sqlmodel import Session, select

from app.core.config import settings
from app.mcp import confirmation, invoke
from app.mcp.identity import McpIdentity, reset_identity, set_identity
from app.mcp.registry import REGISTRY, ToolCall
from app.mcp.server import get_server
from app.models.mcp import McpOperation
from app.models.oauth import OAuthClient, OAuthToken
from app.models.transaction import Transaction
from app.models.user import User
from app.models.workspace import FinancialAccess, Workspace, WorkspaceMembership, WorkspaceRole
from app.services.category_service import seed_default_categories
from app.services.oauth import authorization, crypto, scopes as escopos, tokens
from app.services.oauth.errors import OAuthError
from tests.concurrency.test_invariantes_sob_concorrencia import THREADS, engine_concorrente, precisa_de_mvcc  # noqa: F401

pytestmark = pytest.mark.concurrency


@pytest.fixture
def mundo(engine_concorrente, monkeypatch):  # noqa: F811 — fixture importada acima
    """Alice com um espaço pessoal e uma conexão OAuth; o pipeline usa ESTE banco."""
    get_server()

    @contextmanager
    def sessao():
        with Session(engine_concorrente) as s:
            yield s

    monkeypatch.setattr("app.db.session.session_scope", sessao)
    monkeypatch.setattr(settings, "RATE_LIMIT_ENABLED", False)
    with Session(engine_concorrente) as s:
        alice = User(name="Alice", email="alice-conc@example.com", password_hash="h", needs_onboarding=False)
        ws = Workspace(name="Meu espaço")
        s.add_all([alice, ws])
        s.flush()
        s.add(WorkspaceMembership(workspace_id=ws.id, user_id=alice.id, role=WorkspaceRole.owner,
                                  financial_access=FinancialAccess.full_workspace))
        seed_default_categories(s, ws.id)
        cliente = OAuthClient(client_id=f"cfm_dcr_conc_{uuid.uuid4().hex[:8]}", kind="dcr", client_name="Conc",
                              redirect_uris=["https://cliente.example/cb"],
                              grant_types=["authorization_code", "refresh_token"], token_endpoint_auth_method="none")
        s.add(cliente)
        s.flush()
        concessao = tokens.create_grant(s, user_id=alice.id, client=cliente, scopes=list(escopos.ALL_SCOPES),
                                        resource=settings.mcp_resource_url)
        par = tokens.issue_for_grant(s, concessao, list(escopos.ALL_SCOPES))
        s.commit()
        identidade = McpIdentity(
            user_id=alice.id, grant_id=concessao.id, client_pk=cliente.id, client_id=cliente.client_id,
            client_name="Conc", scopes=frozenset(escopos.ALL_SCOPES), request_id="conc",
        )
        return {"engine": engine_concorrente, "id": identidade, "ws_id": ws.id, "cliente_id": cliente.id,
                "refresh": par.refresh_token, "user_id": alice.id}


def _paralelo(fn, n: int = THREADS):
    barreira = threading.Barrier(n)

    def rodar():
        barreira.wait(timeout=30)
        return fn()

    with ThreadPoolExecutor(max_workers=n) as pool:
        return [f.result() for f in [pool.submit(rodar) for _ in range(n)]]


def _chama(identidade: McpIdentity, tool: str, args: dict):
    token = set_identity(identidade)
    try:
        return invoke.run(REGISTRY[tool], args)
    finally:
        reset_identity(token)


@precisa_de_mvcc
def test_mesma_chave_simultanea_cria_uma_despesa(mundo):
    args = {"idempotency_key": str(uuid.uuid4()), "title": "Café", "amount": "8.00"}
    resultados = _paralelo(lambda: _chama(mundo["id"], "transactions_create", args))
    ok = [r for r in resultados if not r.is_error]
    assert ok, [r.content[0].text for r in resultados]
    # Quem não criou devolveu o resultado de quem criou (replay) ou CONFLICT — nunca uma segunda despesa.
    for r in resultados:
        if r.is_error:
            assert '"CONFLICT"' in r.content[0].text
    with Session(mundo["engine"]) as s:
        assert len(s.exec(select(Transaction).where(Transaction.deleted_at.is_(None))).all()) == 1
        assert len(s.exec(select(McpOperation)).all()) == 1
    ids = {r.structured_content["transaction"]["id"] for r in ok}
    assert len(ids) == 1


@precisa_de_mvcc
def test_mesmo_token_de_confirmacao_executa_uma_vez(mundo):
    for i in range(3):
        _chama(mundo["id"], "transactions_create", {"idempotency_key": str(uuid.uuid4()), "title": f"Lanche {i}", "amount": "10.00"})
    previa = _chama(mundo["id"], "transactions_bulk_preview", {"action": "delete", "filters": {"text": "lanche"}})
    token = previa.structured_content["confirmation_token"]
    resultados = _paralelo(lambda: _chama(mundo["id"], "transactions_bulk_delete", {"confirmation_token": token}))
    executou = [r for r in resultados if not r.is_error and not r.structured_content.get("replayed")]
    assert len(executou) == 1, [r.content[0].text for r in resultados]
    with Session(mundo["engine"]) as s:
        assert s.exec(select(Transaction).where(Transaction.deleted_at.is_(None))).all() == []


@precisa_de_mvcc
def test_mesmo_refresh_simultaneo_gera_um_par(mundo):
    def trocar():
        with Session(mundo["engine"]) as s:
            cliente = s.get(OAuthClient, mundo["cliente_id"])
            try:
                par = tokens.refresh(s, client=cliente, refresh_token=mundo["refresh"], scope=None,
                                     resource=settings.mcp_resource_url)
                s.commit()
                return par
            except OAuthError as exc:
                s.commit()  # o reuso revoga a concessão, e essa revogação precisa valer
                return exc

    resultados = _paralelo(trocar)
    pares = [r for r in resultados if isinstance(r, tokens.TokenPair)]
    assert len(pares) <= 1, "o mesmo refresh token rendeu mais de um par"
    with Session(mundo["engine"]) as s:
        vivos = s.exec(select(OAuthToken).where(OAuthToken.kind == "refresh", OAuthToken.revoked_at.is_(None),
                                                OAuthToken.rotated_at.is_(None))).all()
        assert len(vivos) <= 1


def _espera_quem_trava(engine, quantos: int, prazo: float = 10.0) -> None:
    """Espera até `quantos` conexões estarem paradas esperando TRAVA no Postgres.

    Sem `sleep` às cegas: o teste só avança quando a transação que ele quer
    parada de fato está parada na trava.
    """
    fim = time.monotonic() + prazo
    while time.monotonic() < fim:
        with engine.connect() as c:
            n = c.exec_driver_sql(
                "SELECT count(*) FROM pg_stat_activity "
                "WHERE datname = current_database() AND wait_event_type = 'Lock'"
            ).scalar()
        if n >= quantos:
            return
        time.sleep(0.05)
    raise AssertionError(f"esperava {quantos} conexão(ões) presa(s) em trava")


@precisa_de_mvcc
def test_refresh_reusado_nao_trava_em_deadlock_com_quem_revoga(mundo, monkeypatch):
    """A ordem exata do deadlock que o CI pegou (PR #122 e push da onda 7):

    1. W gira o refresh e segura as travas até o commit;
    2. X, com o mesmo refresh, espera W no `UPDATE` do token e, quando W commita,
       o Postgres o deixa com a trava da linha do token mesmo sem atualizá-la
       (READ COMMITTED rechecando o WHERE); X vai revogar a concessão;
    3. Y chega depois, vê o token já girado e revoga direto: trava a concessão e
       quer os tokens — e o token está com X;
    4. X quer a concessão, que está com Y. Deadlock: um dos dois vira 500.

    Todo caminho tem de travar a CONCESSÃO antes de qualquer token.
    """
    original = tokens.revoke_grant
    x_parou, x_segue = threading.Event(), threading.Event()
    thread_x: dict = {}

    def revoga_pausando_x(session, grant, reason):
        if threading.current_thread() is thread_x.get("t"):
            x_parou.set()
            x_segue.wait(timeout=15)
        return original(session, grant, reason)

    monkeypatch.setattr(tokens, "revoke_grant", revoga_pausando_x)

    def renova(s):
        cliente = s.get(OAuthClient, mundo["cliente_id"])
        return tokens.refresh(s, client=cliente, refresh_token=mundo["refresh"], scope=None,
                              resource=settings.mcp_resource_url)

    resultados: dict = {}

    def roda(nome):
        with Session(mundo["engine"]) as s:
            try:
                resultados[nome] = renova(s)
                s.commit()
            except OAuthError as exc:
                s.commit()  # a revogação por reuso precisa valer
                resultados[nome] = exc
            except Exception as exc:  # o deadlock chega aqui
                s.rollback()
                resultados[nome] = exc

    with Session(mundo["engine"]) as w:
        assert isinstance(renova(w), tokens.TokenPair)
        x = threading.Thread(target=roda, args=("x",))
        thread_x["t"] = x
        x.start()
        _espera_quem_trava(mundo["engine"], 1)  # X parado atrás de W
        w.commit()
    assert x_parou.wait(timeout=15), "X não chegou à revogação"
    y = threading.Thread(target=roda, args=("y",))
    y.start()
    _espera_quem_trava(mundo["engine"], 1)  # Y parado (atrás de X, ou no token de X)
    x_segue.set()
    x.join(timeout=20)
    y.join(timeout=20)

    assert set(resultados) == {"x", "y"}, f"alguém não terminou: {resultados!r}"
    inesperados = {k: v for k, v in resultados.items() if not isinstance(v, OAuthError)}
    assert not inesperados, f"reuso do refresh virou erro de banco, não recusa: {inesperados!r}"
    with Session(mundo["engine"]) as s:
        vivos = s.exec(select(OAuthToken).where(OAuthToken.revoked_at.is_(None))).all()
        assert vivos == [], "o reuso tem de derrubar a conexão inteira"


@precisa_de_mvcc
def test_mesmo_codigo_simultaneo_vira_um_token(mundo):
    verificador = crypto.new_secret("v")
    with Session(mundo["engine"]) as s:
        pedido = authorization.AuthorizationRequest(
            client_id=s.get(OAuthClient, mundo["cliente_id"]).client_id,
            redirect_uri="https://cliente.example/cb", scopes=(escopos.FINANCE_READ,), state="x",
            code_challenge=crypto.pkce_s256(verificador), resource=settings.mcp_resource_url,
        )
        destino = authorization.approve(s, pedido=pedido, user=s.get(User, mundo["user_id"]),
                                        approved_scopes=[escopos.FINANCE_READ])
        s.commit()
    codigo = destino.split("code=")[1].split("&")[0]

    def trocar():
        with Session(mundo["engine"]) as s:
            cliente = s.get(OAuthClient, mundo["cliente_id"])
            try:
                par = authorization.exchange_code(s, client=cliente, code=codigo, redirect_uri="https://cliente.example/cb",
                                                  code_verifier=verificador, resource=settings.mcp_resource_url)
                s.commit()
                return par
            except OAuthError as exc:
                s.commit()
                return exc

    resultados = _paralelo(trocar)
    assert len([r for r in resultados if isinstance(r, tokens.TokenPair)]) <= 1


def test_confirmacao_nao_serve_para_outra_acao_nem_expirada(mundo, monkeypatch):
    """Sanidade sequencial (roda também no SQLite): o token é amarrado à ação."""
    from datetime import timedelta

    with Session(mundo["engine"]) as s:
        chamada = ToolCall(session=s, identity=mundo["id"], user=s.get(User, mundo["user_id"]), args=None,
                           spec=REGISTRY["transactions_bulk_delete"])
        token, _ = confirmation.issue(chamada, "bulk_delete", [1])
        s.commit()
        with pytest.raises(Exception):
            confirmation.consume(chamada, token, "bulk_categorize")
        monkeypatch.setattr(confirmation, "TTL", timedelta(seconds=-1))
        vencido, _ = confirmation.issue(chamada, "bulk_delete", [1])
        s.commit()
        with pytest.raises(Exception, match="expirou"):
            confirmation.consume(chamada, vencido, "bulk_delete")


@precisa_de_mvcc
def test_mesmo_token_de_categorizacao_executa_uma_vez(mundo, monkeypatch):
    """Aqui não há a rede do "conjunto mudou" da exclusão. O "uma vez" vem de duas
    travas do token: o UPDATE condicional (`used_at IS NULL`) e, para quem ficou
    esperando o lock da linha, o resultado já gravado que ele relê depois — as
    duas foram retiradas uma de cada vez e a invariante se manteve com a outra."""
    for i in range(3):
        _chama(mundo["id"], "transactions_create", {"idempotency_key": str(uuid.uuid4()), "title": f"Feira {i}", "amount": "10.00"})
    previa = _chama(mundo["id"], "transactions_bulk_preview", {
        "action": "categorize", "filters": {"text": "feira"}, "category": "Mercado",
    })
    token = previa.structured_content["confirmation_token"]
    # Alarga a janela: quem reservou o token segura a transação um instante,
    # para as outras threads lerem o token ainda "livre" e só então tentarem
    # reservá-lo. Sem isto a primeira terminava antes de as outras lerem, e a
    # corrida nem chegava a acontecer.
    from app.services.commands import transactions as tx_cmd

    original = tx_cmd.bulk_categorize

    def devagar(*a, **k):
        time.sleep(0.5)
        return original(*a, **k)

    monkeypatch.setattr(tx_cmd, "bulk_categorize", devagar)
    resultados = _paralelo(lambda: _chama(mundo["id"], "transactions_bulk_categorize", {"confirmation_token": token}))
    executou = [r for r in resultados if not r.is_error and not r.structured_content.get("replayed")]
    assert len(executou) == 1, [r.content[0].text for r in resultados]
    assert executou[0].structured_content["count"] == 3
