"""Fixtures da integração MCP (ADR 0035).

`mcp_client` sobe o app COM lifespan (é lá que o gerenciador do servidor MCP
nasce). `mcp_token(user, scopes)` emite um access token pelos próprios serviços
do authorization server — rápido e sem atalho de segurança: é o mesmo caminho
que a troca de código percorre. O fluxo HTTP completo (DCR → authorize →
consentimento → token) tem teste próprio em `test_oauth_flow.py`.
"""
from __future__ import annotations

import itertools
import json
from typing import Any, Iterable, Optional

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.core.jwt import create_access_token
from app.main import app
from app.mcp import rate_limit as mcp_rate_limit
from app.models.user import User
from app.models.workspace import FinancialAccess, Workspace, WorkspaceMembership, WorkspaceRole
from app.services.category_service import seed_default_categories
from app.services.oauth import scopes as escopos, tokens
from app.models.oauth import OAuthClient
from app.core.rate_limit import oauth_limiter, oauth_registration_limiter

PROTOCOLO = "2026-07-28"
_ids = itertools.count(1)


@pytest.fixture(autouse=True)
def _zera_limites_mcp():
    mcp_rate_limit.reset()
    oauth_limiter.reset()
    oauth_registration_limiter.reset()
    yield
    mcp_rate_limit.reset()


@pytest.fixture
def mcp_client(override_get_session):
    with TestClient(app) as cliente:
        yield cliente


def make_user(db, name: str, email: str) -> User:
    user = User(name=name, email=email, password_hash="hash", needs_onboarding=False)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def make_space(db, owner: User, name: str, members: Iterable[tuple[User, WorkspaceRole]] = ()) -> Workspace:
    ws = Workspace(name=name, created_by_user_id=owner.id)
    db.add(ws)
    db.flush()
    db.add(WorkspaceMembership(
        workspace_id=ws.id, user_id=owner.id, role=WorkspaceRole.owner,
        financial_access=FinancialAccess.full_workspace,
    ))
    for membro, papel in members:
        db.add(WorkspaceMembership(workspace_id=ws.id, user_id=membro.id, role=papel))
    seed_default_categories(db, ws.id)
    db.commit()
    db.refresh(ws)
    return ws


def cookie_headers(user: User) -> dict:
    return {"Cookie": f"access_token={create_access_token(data={'sub': str(user.id)})}"}


def make_client(db, name: str = "Cliente de teste") -> OAuthClient:
    cliente = OAuthClient(
        client_id=f"cfm_dcr_teste_{next(_ids)}",
        kind="dcr",
        client_name=name,
        redirect_uris=["https://cliente.example/callback"],
        grant_types=["authorization_code", "refresh_token"],
        token_endpoint_auth_method="none",
    )
    db.add(cliente)
    db.commit()
    db.refresh(cliente)
    return cliente


def issue_token(db, user: User, scopes: Optional[Iterable[str]] = None, *, client: Optional[OAuthClient] = None) -> str:
    cliente = client or make_client(db)
    lista = list(scopes) if scopes is not None else list(escopos.ALL_SCOPES)
    concessao = tokens.create_grant(
        db, user_id=user.id, client=cliente, scopes=lista, resource=settings.mcp_resource_url
    )
    par = tokens.issue_for_grant(db, concessao, lista)
    db.commit()
    return par.access_token


def rpc(client: TestClient, token: Optional[str], method: str, params: Optional[dict] = None, *,
        id: int = 1, version: str = PROTOCOLO, extra_headers: Optional[dict] = None):
    cabecalhos = {"Accept": "application/json, text/event-stream"}
    if token:
        cabecalhos["Authorization"] = f"Bearer {token}"
    corpo_params: dict[str, Any] = dict(params or {})
    if version == PROTOCOLO:
        cabecalhos["MCP-Protocol-Version"] = version
        cabecalhos["Mcp-Method"] = method
        if method == "tools/call":
            cabecalhos["Mcp-Name"] = corpo_params["name"]
        elif method == "resources/read":
            cabecalhos["Mcp-Name"] = corpo_params["uri"]
        corpo_params["_meta"] = {
            "io.modelcontextprotocol/protocolVersion": version,
            "io.modelcontextprotocol/clientInfo": {"name": "pytest", "version": "1"},
            "io.modelcontextprotocol/clientCapabilities": {},
        }
    else:
        cabecalhos["MCP-Protocol-Version"] = version
    cabecalhos.update(extra_headers or {})
    return client.post("/mcp", json={"jsonrpc": "2.0", "id": id, "method": method, "params": corpo_params}, headers=cabecalhos)


def call_tool(client: TestClient, token: str, name: str, arguments: Optional[dict] = None) -> dict:
    """Resultado do `tools/call` (o objeto `result` do JSON-RPC)."""
    resposta = rpc(client, token, "tools/call", {"name": name, "arguments": arguments or {}})
    assert resposta.status_code == 200, resposta.text
    corpo = resposta.json()
    assert "result" in corpo, corpo
    return corpo["result"]


def ok(result: dict) -> dict:
    """`structuredContent` de um resultado de sucesso (falha o teste com o erro)."""
    assert not result.get("isError"), result["content"][0]["text"]
    return result["structuredContent"]


def err(result: dict) -> dict:
    """O envelope de erro de um resultado com `isError`."""
    assert result.get("isError"), result
    texto = result["content"][0]["text"]
    return json.loads(texto[texto.index("{"):])["error"]


@pytest.fixture
def duo(db_session):
    """Dois usuários que NÃO se conhecem, cada um com o próprio espaço (A×B)."""
    alice = make_user(db_session, "Alice Souza", "alice@example.com")
    bob = make_user(db_session, "Bob Lima", "bob@example.com")
    ws_a = make_space(db_session, alice, "Casa da Alice")
    ws_b = make_space(db_session, bob, "Casa do Bob")
    return {"alice": alice, "bob": bob, "ws_a": ws_a, "ws_b": ws_b}
