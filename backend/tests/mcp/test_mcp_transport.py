"""Transporte MCP: autenticação no portão, Origin, eras do protocolo, descoberta."""
from app.core.config import settings
from app.services.oauth import scopes as escopos
from tests.mcp.conftest import call_tool, err, issue_token, ok, rpc


def test_sem_token_responde_401_com_resource_metadata_e_scope(mcp_client, duo):
    r = rpc(mcp_client, None, "tools/list")
    assert r.status_code == 401
    desafio = r.headers["www-authenticate"]
    assert desafio.startswith("Bearer ")
    assert f'resource_metadata="{settings.oauth_issuer}/.well-known/oauth-protected-resource/mcp"' in desafio
    assert f'scope="{" ".join(escopos.ALL_SCOPES)}"' in desafio
    assert "error=" not in desafio  # sem credencial não há "erro de token"


def test_token_invalido_responde_401_invalid_token(mcp_client, duo):
    r = rpc(mcp_client, "cfm_at_" + "x" * 43, "tools/list")
    assert r.status_code == 401
    assert 'error="invalid_token"' in r.headers["www-authenticate"]


def test_token_de_sessao_do_app_nao_serve_no_mcp(mcp_client, duo):
    """O JWT do cookie do app não é token MCP (audiência diferente)."""
    from app.core.jwt import create_access_token

    jwt_do_app = create_access_token(data={"sub": str(duo["alice"].id)})
    assert rpc(mcp_client, jwt_do_app, "tools/list").status_code == 401


def test_origin_estranha_recebe_403(mcp_client, db_session, duo):
    token = issue_token(db_session, duo["alice"])
    r = rpc(mcp_client, token, "tools/list", extra_headers={"Origin": "https://evil.example"})
    assert r.status_code == 403


def test_origin_do_proprio_site_passa(mcp_client, db_session, duo):
    token = issue_token(db_session, duo["alice"])
    r = rpc(mcp_client, token, "tools/list", extra_headers={"Origin": settings.oauth_issuer})
    assert r.status_code == 200


def test_tools_list_moderno_deterministico_e_completo(mcp_client, db_session, duo):
    token = issue_token(db_session, duo["alice"])
    a = rpc(mcp_client, token, "tools/list").json()["result"]["tools"]
    b = rpc(mcp_client, token, "tools/list").json()["result"]["tools"]
    assert [t["name"] for t in a] == [t["name"] for t in b]
    nomes = {t["name"] for t in a}
    assert {"profile_get", "spaces_list", "accounts_list"} <= nomes
    for t in a:
        anot = t["annotations"]
        assert set(anot) >= {"readOnlyHint", "destructiveHint", "idempotentHint", "openWorldHint"}
        assert t["inputSchema"]["type"] == "object"
        assert t["inputSchema"].get("additionalProperties") is False
        assert "outputSchema" in t


def test_cliente_legado_2025_11_25_funciona(mcp_client, db_session, duo):
    token = issue_token(db_session, duo["alice"])
    init = rpc(
        mcp_client, token, "initialize",
        {"protocolVersion": "2025-11-25", "capabilities": {}, "clientInfo": {"name": "legado", "version": "1"}},
        version="2025-11-25",
    )
    assert init.status_code == 200, init.text
    assert init.json()["result"]["serverInfo"]["name"] == "controle-financeiro"
    chamada = rpc(
        mcp_client, token, "tools/call", {"name": "profile_get", "arguments": {}}, id=2, version="2025-11-25"
    )
    assert chamada.status_code == 200
    assert chamada.json()["result"]["structuredContent"]["name"] == "Alice Souza"


def test_server_discover(mcp_client, db_session, duo):
    token = issue_token(db_session, duo["alice"])
    r = rpc(mcp_client, token, "server/discover")
    corpo = r.json()["result"]
    assert "2026-07-28" in corpo["supportedVersions"]
    assert corpo["capabilities"]["extensions"]["io.modelcontextprotocol/ui"] == {}
    assert "profile_get" in corpo["instructions"]


def test_barra_final_nao_redireciona(mcp_client, db_session, duo):
    token = issue_token(db_session, duo["alice"])
    r = mcp_client.post(
        "/mcp/",
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json, text/event-stream",
                 "MCP-Protocol-Version": "2025-11-25"},
        follow_redirects=False,
    )
    assert r.status_code == 200


def test_tool_desconhecida_e_erro_de_protocolo(mcp_client, db_session, duo):
    token = issue_token(db_session, duo["alice"])
    r = rpc(mcp_client, token, "tools/call", {"name": "execute_sql", "arguments": {}})
    corpo = r.json()
    assert "error" in corpo or corpo["result"].get("isError")


def test_profile_get_devolve_identidade_do_token(mcp_client, db_session, duo):
    token = issue_token(db_session, duo["alice"])
    perfil = ok(call_tool(mcp_client, token, "profile_get"))
    assert perfil["name"] == "Alice Souza"
    assert perfil["id"] == duo["alice"].public_id
    assert perfil["timezone"] == settings.APP_TIMEZONE
    assert perfil["connection"]["scopes"] == list(escopos.ALL_SCOPES)


def test_argumento_extra_e_recusado(mcp_client, db_session, duo):
    token = issue_token(db_session, duo["alice"])
    erro = err(call_tool(mcp_client, token, "profile_get", {"user_id": duo["bob"].id}))
    assert erro["code"] == "VALIDATION_ERROR"


def test_conexao_revogada_perde_acesso_na_hora(mcp_client, db_session, duo):
    from sqlmodel import select
    from app.models.oauth import OAuthGrant
    from app.services.oauth import tokens

    token = issue_token(db_session, duo["alice"])
    assert rpc(mcp_client, token, "tools/list").status_code == 200
    concessao = db_session.exec(select(OAuthGrant).where(OAuthGrant.user_id == duo["alice"].id)).first()
    tokens.revoke_grant(db_session, concessao, "user")
    db_session.commit()
    assert rpc(mcp_client, token, "tools/list").status_code == 401


def test_conta_desativada_perde_acesso(mcp_client, db_session, duo):
    token = issue_token(db_session, duo["alice"])
    duo["alice"].is_active = False
    db_session.add(duo["alice"])
    db_session.commit()
    assert rpc(mcp_client, token, "tools/list").status_code == 401


def test_corpo_grande_demais_e_recusado_antes_de_tudo(mcp_client, db_session, duo):
    token = issue_token(db_session, duo["alice"])
    r = mcp_client.post(
        "/mcp", content=b"x" * (1024 * 1024 + 1),
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json",
                 "Accept": "application/json, text/event-stream"},
    )
    assert r.status_code == 413


def test_request_id_nao_vem_do_cliente(mcp_client, db_session, duo):
    from sqlmodel import select

    from app.models.mcp import McpToolCall

    token = issue_token(db_session, duo["alice"])
    rpc(mcp_client, token, "tools/call", {"name": "spaces_list", "arguments": {}},
        extra_headers={"X-Request-ID": "escolhido-pelo-cliente"})
    linha = db_session.exec(select(McpToolCall)).one()
    assert linha.request_id != "escolhido-pelo-cliente"
