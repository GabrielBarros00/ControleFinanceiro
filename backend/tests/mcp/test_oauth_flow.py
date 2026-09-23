"""Authorization server OAuth 2.1 dos clientes MCP — o fluxo HTTP de ponta a ponta."""
from urllib.parse import parse_qs, urlsplit

import pytest
from sqlmodel import select

from app.core.config import settings
from app.models.oauth import OAuthClient, OAuthGrant
from app.services.oauth import crypto, scopes as escopos
from tests.mcp.conftest import cookie_headers, make_user, rpc

VERIFIER = "v" * 50
CHALLENGE = crypto.pkce_s256(VERIFIER)
REDIRECT = "https://cliente.example/callback"


def _registra(client, **extra):
    corpo = {
        "client_name": "Cliente Teste",
        "redirect_uris": [REDIRECT],
        "grant_types": ["authorization_code", "refresh_token"],
        "response_types": ["code"],
        "token_endpoint_auth_method": "none",
        **extra,
    }
    r = client.post("/api/v1/oauth/register", json=corpo)
    assert r.status_code == 201, r.text
    return r.json()


def _autoriza(client, client_id, *, redirect=REDIRECT, scope=None, state="xyz", challenge=CHALLENGE):
    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "state": state,
        "resource": settings.mcp_resource_url,
    }
    if scope is not None:
        params["scope"] = scope
    return client.get("/api/v1/oauth/authorize", params=params, follow_redirects=False)


def _handle(resposta) -> str:
    assert resposta.status_code == 302, resposta.text
    destino = urlsplit(resposta.headers["location"])
    assert destino.path == "/oauth/consent"
    return parse_qs(destino.query)["request"][0]


def _aprova(client, user, handle, scopes=None):
    corpo = {"request": handle, "scopes": scopes if scopes is not None else list(escopos.ALL_SCOPES)}
    r = client.post("/api/v1/oauth/consent/approve", json=corpo, headers=cookie_headers(user))
    assert r.status_code == 200, r.text
    return r.json()["redirect_to"]


def _troca(client, client_id, code, verifier=VERIFIER, redirect=REDIRECT):
    return client.post(
        "/api/v1/oauth/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect,
            "code_verifier": verifier,
            "client_id": client_id,
            "resource": settings.mcp_resource_url,
        },
    )


def _codigo(redirect_to: str) -> dict:
    return {k: v[0] for k, v in parse_qs(urlsplit(redirect_to).query).items()}


@pytest.fixture
def alice(db_session):
    return make_user(db_session, "Alice Souza", "alice@example.com")


def _fluxo_completo(client, user, scopes=None):
    cliente = _registra(client)
    handle = _handle(_autoriza(client, cliente["client_id"]))
    params = _codigo(_aprova(client, user, handle, scopes))
    r = _troca(client, cliente["client_id"], params["code"])
    assert r.status_code == 200, r.text
    return cliente, r.json()


# --- Descoberta ------------------------------------------------------------------

def test_metadados_do_recurso_protegido(mcp_client):
    for caminho in ("/.well-known/oauth-protected-resource/mcp", "/.well-known/oauth-protected-resource"):
        r = mcp_client.get(caminho)
        assert r.status_code == 200
        corpo = r.json()
        assert corpo["resource"] == settings.mcp_resource_url
        assert corpo["authorization_servers"] == [settings.oauth_issuer]
        assert corpo["scopes_supported"] == list(escopos.ALL_SCOPES)
        assert r.headers["access-control-allow-origin"] == "*"


def test_metadados_do_authorization_server(mcp_client):
    corpo = mcp_client.get("/.well-known/oauth-authorization-server").json()
    assert corpo["issuer"] == settings.oauth_issuer
    assert corpo["code_challenge_methods_supported"] == ["S256"]
    assert corpo["client_id_metadata_document_supported"] is True
    assert "none" in corpo["token_endpoint_auth_methods_supported"]
    assert corpo["authorization_response_iss_parameter_supported"] is True
    assert corpo["registration_endpoint"].endswith("/api/v1/oauth/register")
    assert "offline_access" not in corpo["scopes_supported"]


def test_openid_configuration_nao_existe(mcp_client):
    assert mcp_client.get("/.well-known/openid-configuration").status_code == 404


def test_preflight_cors_do_token_endpoint(mcp_client):
    r = mcp_client.options(
        "/api/v1/oauth/token",
        headers={"Origin": "http://localhost:6274", "Access-Control-Request-Method": "POST"},
    )
    assert r.status_code == 204
    assert r.headers["access-control-allow-origin"] == "*"
    assert "access-control-allow-credentials" not in r.headers


# --- Fluxo feliz ---------------------------------------------------------------------

def test_fluxo_completo_e_uso_do_token_no_mcp(mcp_client, alice):
    _cliente, tokens = _fluxo_completo(mcp_client, alice)
    assert tokens["token_type"] == "Bearer"
    assert tokens["access_token"].startswith("cfm_at_")
    assert tokens["refresh_token"].startswith("cfm_rt_")
    assert tokens["scope"] == " ".join(escopos.ALL_SCOPES)
    r = rpc(mcp_client, tokens["access_token"], "tools/call", {"name": "profile_get", "arguments": {}})
    assert r.json()["result"]["structuredContent"]["name"] == "Alice Souza"


def test_redirect_do_consentimento_leva_code_state_e_iss(mcp_client, alice):
    cliente = _registra(mcp_client)
    handle = _handle(_autoriza(mcp_client, cliente["client_id"]))
    params = _codigo(_aprova(mcp_client, alice, handle))
    assert params["state"] == "xyz"
    assert params["iss"] == settings.oauth_issuer
    assert params["code"].startswith("cfm_ac_")


def test_escopos_reduzidos_na_tela_limitam_o_token(mcp_client, alice):
    _cliente, tokens = _fluxo_completo(mcp_client, alice, scopes=[escopos.FINANCE_READ])
    assert tokens["scope"] == escopos.FINANCE_READ


def test_leitura_e_obrigatoria_no_consentimento(mcp_client, alice):
    cliente = _registra(mcp_client)
    handle = _handle(_autoriza(mcp_client, cliente["client_id"]))
    r = mcp_client.post(
        "/api/v1/oauth/consent/approve",
        json={"request": handle, "scopes": [escopos.TRANSACTIONS_WRITE]},
        headers=cookie_headers(alice),
    )
    assert r.status_code == 400


def test_consentimento_exige_login(mcp_client, alice):
    cliente = _registra(mcp_client)
    handle = _handle(_autoriza(mcp_client, cliente["client_id"]))
    r = mcp_client.post("/api/v1/oauth/consent/approve", json={"request": handle, "scopes": ["finance.read"]})
    assert r.status_code == 401


def test_detalhes_do_consentimento(mcp_client, alice):
    cliente = _registra(mcp_client)
    handle = _handle(_autoriza(mcp_client, cliente["client_id"]))
    r = mcp_client.get("/api/v1/oauth/consent", params={"request": handle}, headers=cookie_headers(alice))
    corpo = r.json()
    assert corpo["client"]["name"] == "Cliente Teste"
    assert corpo["client"]["redirect_host"] == "cliente.example"
    assert corpo["client"]["loopback_only"] is False
    assert corpo["account"]["email"] == "alice@example.com"
    assert [s["scope"] for s in corpo["scopes"]] == list(escopos.ALL_SCOPES)
    assert corpo["scopes"][0]["required"] is True


def test_negar_devolve_access_denied(mcp_client, alice):
    cliente = _registra(mcp_client)
    handle = _handle(_autoriza(mcp_client, cliente["client_id"]))
    r = mcp_client.post("/api/v1/oauth/consent/deny", json={"request": handle}, headers=cookie_headers(alice))
    params = _codigo(r.json()["redirect_to"])
    assert params["error"] == "access_denied"
    assert params["state"] == "xyz"
    assert params["iss"] == settings.oauth_issuer


# --- Validação do /authorize -----------------------------------------------------------

def test_redirect_nao_registrado_nao_redireciona_para_ele(mcp_client):
    cliente = _registra(mcp_client)
    r = _autoriza(mcp_client, cliente["client_id"], redirect="https://atacante.example/cb")
    destino = urlsplit(r.headers["location"])
    assert destino.netloc in ("", urlsplit(settings.oauth_issuer).netloc)
    assert destino.path == "/oauth/consent"
    assert "error=" in destino.query


def test_cliente_desconhecido_nao_redireciona(mcp_client):
    r = _autoriza(mcp_client, "cfm_dcr_nao_existe")
    assert urlsplit(r.headers["location"]).path == "/oauth/consent"
    assert "error=" in r.headers["location"]


def test_sem_pkce_volta_erro_para_o_cliente(mcp_client):
    cliente = _registra(mcp_client)
    r = mcp_client.get("/api/v1/oauth/authorize", params={
        "response_type": "code", "client_id": cliente["client_id"], "redirect_uri": REDIRECT, "state": "s",
    }, follow_redirects=False)
    destino = urlsplit(r.headers["location"])
    assert destino.netloc == "cliente.example"
    params = parse_qs(destino.query)
    assert params["error"] == ["invalid_request"]
    assert params["state"] == ["s"]


def test_pkce_plain_e_recusado(mcp_client):
    cliente = _registra(mcp_client)
    r = mcp_client.get("/api/v1/oauth/authorize", params={
        "response_type": "code", "client_id": cliente["client_id"], "redirect_uri": REDIRECT,
        "code_challenge": VERIFIER, "code_challenge_method": "plain",
    }, follow_redirects=False)
    assert parse_qs(urlsplit(r.headers["location"]).query)["error"] == ["invalid_request"]


def test_escopo_desconhecido(mcp_client):
    cliente = _registra(mcp_client)
    r = _autoriza(mcp_client, cliente["client_id"], scope="full_access")
    assert parse_qs(urlsplit(r.headers["location"]).query)["error"] == ["invalid_scope"]


def test_offline_access_e_aceito_e_ignorado(mcp_client, alice):
    cliente = _registra(mcp_client)
    handle = _handle(_autoriza(mcp_client, cliente["client_id"], scope="finance.read offline_access"))
    r = mcp_client.get("/api/v1/oauth/consent", params={"request": handle}, headers=cookie_headers(alice))
    assert [s["scope"] for s in r.json()["scopes"]] == ["finance.read"]


def test_resource_de_outro_servidor_e_invalid_target(mcp_client):
    cliente = _registra(mcp_client)
    r = mcp_client.get("/api/v1/oauth/authorize", params={
        "response_type": "code", "client_id": cliente["client_id"], "redirect_uri": REDIRECT,
        "code_challenge": CHALLENGE, "code_challenge_method": "S256", "resource": "https://outro.example/mcp",
    }, follow_redirects=False)
    assert parse_qs(urlsplit(r.headers["location"]).query)["error"] == ["invalid_target"]


def test_loopback_casa_em_qualquer_porta(mcp_client, alice):
    cliente = _registra(mcp_client, redirect_uris=["http://localhost/callback", "http://127.0.0.1/callback"])
    for redirect in ("http://localhost:3118/callback", "http://127.0.0.1:49152/callback"):
        handle = _handle(_autoriza(mcp_client, cliente["client_id"], redirect=redirect))
        params = _codigo(_aprova(mcp_client, alice, handle))
        assert _troca(mcp_client, cliente["client_id"], params["code"], redirect=redirect).status_code == 200


def test_loopback_nao_casa_caminho_diferente(mcp_client):
    cliente = _registra(mcp_client, redirect_uris=["http://localhost/callback"])
    r = _autoriza(mcp_client, cliente["client_id"], redirect="http://localhost:3000/outro")
    assert urlsplit(r.headers["location"]).path == "/oauth/consent"
    assert "error=" in r.headers["location"]


# --- /token ---------------------------------------------------------------------------

def test_code_verifier_errado(mcp_client, alice):
    cliente = _registra(mcp_client)
    params = _codigo(_aprova(mcp_client, alice, _handle(_autoriza(mcp_client, cliente["client_id"]))))
    r = _troca(mcp_client, cliente["client_id"], params["code"], verifier="w" * 50)
    assert r.status_code == 400
    assert r.json()["error"] == "invalid_grant"


def test_codigo_de_uso_unico_e_reuso_revoga_a_conexao(mcp_client, db_session, alice):
    cliente = _registra(mcp_client)
    params = _codigo(_aprova(mcp_client, alice, _handle(_autoriza(mcp_client, cliente["client_id"]))))
    primeiro = _troca(mcp_client, cliente["client_id"], params["code"])
    assert primeiro.status_code == 200
    segundo = _troca(mcp_client, cliente["client_id"], params["code"])
    assert segundo.json()["error"] == "invalid_grant"
    # O token emitido pela primeira troca morreu junto (o código pode ter vazado).
    r = rpc(mcp_client, primeiro.json()["access_token"], "tools/list")
    assert r.status_code == 401


def test_codigo_de_outro_cliente(mcp_client, alice):
    a = _registra(mcp_client)
    b = _registra(mcp_client)
    params = _codigo(_aprova(mcp_client, alice, _handle(_autoriza(mcp_client, a["client_id"]))))
    assert _troca(mcp_client, b["client_id"], params["code"]).json()["error"] == "invalid_grant"


def test_redirect_diferente_na_troca(mcp_client, alice):
    cliente = _registra(mcp_client, redirect_uris=[REDIRECT, "https://cliente.example/outro"])
    params = _codigo(_aprova(mcp_client, alice, _handle(_autoriza(mcp_client, cliente["client_id"]))))
    r = _troca(mcp_client, cliente["client_id"], params["code"], redirect="https://cliente.example/outro")
    assert r.json()["error"] == "invalid_grant"


def test_token_exige_form_urlencoded(mcp_client):
    r = mcp_client.post("/api/v1/oauth/token", json={"grant_type": "authorization_code"})
    assert r.status_code == 400
    assert r.json()["error"] == "invalid_request"


def test_grant_type_desconhecido(mcp_client):
    cliente = _registra(mcp_client)
    r = mcp_client.post("/api/v1/oauth/token", data={"grant_type": "password", "client_id": cliente["client_id"]})
    assert r.json()["error"] == "unsupported_grant_type"


def test_resposta_de_token_nao_vai_para_cache(mcp_client, alice):
    cliente = _registra(mcp_client)
    params = _codigo(_aprova(mcp_client, alice, _handle(_autoriza(mcp_client, cliente["client_id"]))))
    r = _troca(mcp_client, cliente["client_id"], params["code"])
    assert r.headers["cache-control"] == "no-store"


# --- Refresh ----------------------------------------------------------------------------

def _renova(client, client_id, refresh, **extra):
    return client.post("/api/v1/oauth/token", data={
        "grant_type": "refresh_token", "refresh_token": refresh, "client_id": client_id, **extra,
    })


def test_refresh_rotaciona(mcp_client, alice):
    cliente, tokens = _fluxo_completo(mcp_client, alice)
    r = _renova(mcp_client, cliente["client_id"], tokens["refresh_token"])
    assert r.status_code == 200
    novo = r.json()
    assert novo["refresh_token"] != tokens["refresh_token"]
    assert rpc(mcp_client, novo["access_token"], "tools/list").status_code == 200


def test_refresh_reutilizado_revoga_a_conexao_inteira(mcp_client, alice):
    cliente, tokens = _fluxo_completo(mcp_client, alice)
    novo = _renova(mcp_client, cliente["client_id"], tokens["refresh_token"]).json()
    reuso = _renova(mcp_client, cliente["client_id"], tokens["refresh_token"])
    assert reuso.status_code == 400 and reuso.json()["error"] == "invalid_grant"
    # Até o par LEGÍTIMO morre: não há como saber quem é o ladrão.
    assert rpc(mcp_client, novo["access_token"], "tools/list").status_code == 401
    assert _renova(mcp_client, cliente["client_id"], novo["refresh_token"]).json()["error"] == "invalid_grant"


def test_refresh_nao_amplia_escopo(mcp_client, alice):
    cliente, tokens = _fluxo_completo(mcp_client, alice, scopes=[escopos.FINANCE_READ])
    r = _renova(mcp_client, cliente["client_id"], tokens["refresh_token"], scope="finance.read transactions.write")
    assert r.json()["error"] == "invalid_scope"


def test_refresh_de_outro_cliente(mcp_client, alice):
    _cliente, tokens = _fluxo_completo(mcp_client, alice)
    outro = _registra(mcp_client)
    assert _renova(mcp_client, outro["client_id"], tokens["refresh_token"]).json()["error"] == "invalid_grant"


# --- Revogação --------------------------------------------------------------------------

def test_revogar_refresh_derruba_a_conexao(mcp_client, alice):
    cliente, tokens = _fluxo_completo(mcp_client, alice)
    r = mcp_client.post("/api/v1/oauth/revoke", data={"token": tokens["refresh_token"], "client_id": cliente["client_id"]})
    assert r.status_code == 200
    assert rpc(mcp_client, tokens["access_token"], "tools/list").status_code == 401


def test_revogar_token_inexistente_responde_200(mcp_client):
    cliente = _registra(mcp_client)
    r = mcp_client.post("/api/v1/oauth/revoke", data={"token": "qualquer", "client_id": cliente["client_id"]})
    assert r.status_code == 200


def test_troca_de_senha_derruba_conexoes_de_ia(mcp_client, db_session, alice):
    from app.core.security import get_password_hash

    alice.password_hash = get_password_hash("senha-antiga-123")
    db_session.add(alice)
    db_session.commit()
    _cliente, tokens = _fluxo_completo(mcp_client, alice)
    r = mcp_client.post(
        "/api/v1/auth/change-password",
        json={"current_password": "senha-antiga-123", "new_password": "senha-nova-456"},
        headers=cookie_headers(alice),
    )
    assert r.status_code == 200, r.text
    assert rpc(mcp_client, tokens["access_token"], "tools/list").status_code == 401


# --- DCR -------------------------------------------------------------------------------

def test_dcr_sem_redirect_e_recusado(mcp_client):
    r = mcp_client.post("/api/v1/oauth/register", json={"client_name": "X"})
    assert r.status_code == 400
    assert r.json()["error"] == "invalid_redirect_uri"


@pytest.mark.parametrize("uri", [
    "http://exemplo.com/cb",          # http fora de loopback
    "https://exemplo.com/cb#frag",    # fragmento
    "https://user:pw@exemplo.com/cb",  # credenciais
    "myapp://callback",               # esquema próprio
    "https://*.exemplo.com/cb",       # curinga
])
def test_dcr_redirect_invalido(mcp_client, uri):
    r = mcp_client.post("/api/v1/oauth/register", json={"redirect_uris": [uri], "token_endpoint_auth_method": "none"})
    assert r.status_code == 400


def test_dcr_confidencial_recebe_segredo_e_precisa_dele(mcp_client, alice, db_session):
    r = mcp_client.post("/api/v1/oauth/register", json={"redirect_uris": [REDIRECT]})
    corpo = r.json()
    assert corpo["token_endpoint_auth_method"] == "client_secret_basic"
    assert corpo["client_secret"].startswith("cfm_cs_")
    guardado = db_session.exec(select(OAuthClient).where(OAuthClient.client_id == corpo["client_id"])).one()
    assert guardado.client_secret_hash == crypto.sha256_hex(corpo["client_secret"])
    params = _codigo(_aprova(mcp_client, alice, _handle(_autoriza(mcp_client, corpo["client_id"]))))
    sem_segredo = _troca(mcp_client, corpo["client_id"], params["code"])
    assert sem_segredo.status_code == 401
    assert sem_segredo.json()["error"] == "invalid_client"


def test_dcr_nome_com_caracteres_de_controle_e_limpo(mcp_client):
    corpo = _registra(mcp_client, client_name="Claude\x00\x1b[31m")
    assert corpo["client_name"] == "Claude[31m"


# --- Tela: listar e desconectar ----------------------------------------------------------

def test_tela_lista_e_desconecta(mcp_client, db_session, alice):
    _cliente, tokens = _fluxo_completo(mcp_client, alice)
    tela = mcp_client.get("/api/v1/me/ai-integrations", headers=cookie_headers(alice)).json()
    assert tela["mcp_url"] == settings.mcp_resource_url
    assert len(tela["connections"]) == 1
    conexao = tela["connections"][0]
    assert conexao["status"] == "active"
    assert "access_token" not in str(tela) and tokens["access_token"] not in str(tela)
    r = mcp_client.delete(f"/api/v1/me/ai-integrations/connections/{conexao['grant_id']}", headers=cookie_headers(alice))
    assert r.status_code == 200
    assert rpc(mcp_client, tokens["access_token"], "tools/list").status_code == 401
    assert mcp_client.get("/api/v1/me/ai-integrations", headers=cookie_headers(alice)).json()["connections"] == []


def test_nao_desconecta_conexao_de_outra_pessoa(mcp_client, db_session, alice):
    bob = make_user(db_session, "Bob", "bob@example.com")
    _fluxo_completo(mcp_client, alice)
    concessao = db_session.exec(select(OAuthGrant).where(OAuthGrant.user_id == alice.id)).one()
    r = mcp_client.delete(f"/api/v1/me/ai-integrations/connections/{concessao.id}", headers=cookie_headers(bob))
    assert r.status_code == 404
