"""Client ID Metadata Documents: o `client_id` é uma URL que o servidor busca.

Nenhum teste fala com a rede: o resolvedor de DNS e o transporte HTTP são
substituídos. O que se prova é que a busca só acontece para endereço PÚBLICO,
em https/443, sem seguir redirect, com teto de tamanho — e que o documento é
conferido antes de virar cliente.
"""
import json
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

from app.core.config import settings
from app.services.oauth import cimd_fetch, crypto
from tests.mcp.conftest import cookie_headers, make_user

URL = "https://claude.ai/oauth/claude-code-client-metadata"
DOC = {
    "client_id": URL,
    "client_name": "Claude Code",
    "client_uri": "https://claude.ai",
    "redirect_uris": ["http://localhost/callback", "http://127.0.0.1/callback"],
    "grant_types": ["authorization_code", "refresh_token"],
    "response_types": ["code"],
    "token_endpoint_auth_method": "none",
}


def _publico(host):
    return ["160.79.104.10"]


def _transporte(corpo=DOC, status=200, headers=None):
    def responde(request):
        return httpx.Response(
            status,
            content=json.dumps(corpo).encode() if isinstance(corpo, dict) else corpo,
            headers={"content-type": "application/json", **(headers or {})},
        )
    return httpx.MockTransport(responde)


# --- A busca em si -----------------------------------------------------------------

def test_busca_ok_com_ttl_do_cache_control():
    doc, ttl = cimd_fetch.fetch_client_metadata(
        URL, resolver=_publico, transport=_transporte(headers={"cache-control": "max-age=3600"})
    )
    assert doc["client_name"] == "Claude Code"
    assert ttl == 3600


def test_ttl_tem_piso_e_teto():
    _, ttl = cimd_fetch.fetch_client_metadata(URL, resolver=_publico, transport=_transporte(headers={"cache-control": "max-age=5"}))
    assert ttl == cimd_fetch.MIN_TTL_SECONDS
    _, ttl = cimd_fetch.fetch_client_metadata(URL, resolver=_publico, transport=_transporte(headers={"cache-control": "max-age=999999"}))
    assert ttl == cimd_fetch.MAX_TTL_SECONDS


@pytest.mark.parametrize("ip", [
    "127.0.0.1", "10.0.0.5", "172.16.3.4", "192.168.0.10", "169.254.169.254",
    "::1", "fd00::1", "0.0.0.0", "::ffff:127.0.0.1", "100.64.0.1",
])
def test_endereco_nao_publico_e_recusado_antes_de_conectar(ip):
    chamadas = []

    def transporte(request):
        chamadas.append(request)
        return httpx.Response(200, json=DOC)

    with pytest.raises(cimd_fetch.CimdFetchError):
        cimd_fetch.fetch_client_metadata(URL, resolver=lambda h: [ip], transport=httpx.MockTransport(transporte))
    assert chamadas == []


def test_um_ip_privado_entre_publicos_ja_recusa():
    with pytest.raises(cimd_fetch.CimdFetchError):
        cimd_fetch.fetch_client_metadata(URL, resolver=lambda h: ["160.79.104.10", "10.0.0.1"], transport=_transporte())


@pytest.mark.parametrize("url", [
    "http://claude.ai/oauth/meta",           # sem TLS
    "https://claude.ai:8443/oauth/meta",     # porta arbitrária
    "https://claude.ai/",                    # sem caminho
    "https://user:pw@claude.ai/meta",        # credenciais
    "https://claude.ai/meta#frag",           # fragmento
])
def test_forma_da_url(url):
    assert not cimd_fetch.valid_cimd_url(url)
    with pytest.raises(cimd_fetch.CimdFetchError):
        cimd_fetch.fetch_client_metadata(url, resolver=_publico, transport=_transporte())


def test_redirect_nao_e_seguido():
    transporte = httpx.MockTransport(lambda r: httpx.Response(302, headers={"location": "http://169.254.169.254/"}))
    with pytest.raises(cimd_fetch.CimdFetchError):
        cimd_fetch.fetch_client_metadata(URL, resolver=_publico, transport=transporte)


def test_documento_grande_demais():
    enorme = json.dumps({"x": "a" * (cimd_fetch.MAX_BYTES + 10)}).encode()
    with pytest.raises(cimd_fetch.CimdFetchError):
        cimd_fetch.fetch_client_metadata(URL, resolver=_publico, transport=_transporte(corpo=enorme))


def test_conteudo_nao_json():
    transporte = httpx.MockTransport(lambda r: httpx.Response(200, content=b"<html>", headers={"content-type": "text/html"}))
    with pytest.raises(cimd_fetch.CimdFetchError):
        cimd_fetch.fetch_client_metadata(URL, resolver=_publico, transport=transporte)


# --- O fluxo com cliente CIMD ---------------------------------------------------------

@pytest.fixture
def cimd(monkeypatch):
    documentos = {URL: dict(DOC)}

    def falsa(url, **_):
        if url not in documentos:
            raise cimd_fetch.CimdFetchError("não encontrado")
        return documentos[url], 600

    monkeypatch.setattr(cimd_fetch, "fetch_client_metadata", falsa)
    return documentos


def _autoriza(client, client_id, redirect):
    return client.get("/api/v1/oauth/authorize", params={
        "response_type": "code", "client_id": client_id, "redirect_uri": redirect,
        "code_challenge": crypto.pkce_s256("v" * 50), "code_challenge_method": "S256",
        "resource": settings.mcp_resource_url,
    }, follow_redirects=False)


def test_cliente_cimd_do_claude_code_completa_o_fluxo(mcp_client, db_session, cimd):
    alice = make_user(db_session, "Alice", "alice@example.com")
    r = _autoriza(mcp_client, URL, "http://localhost:51234/callback")
    handle = parse_qs(urlsplit(r.headers["location"]).query)["request"][0]
    detalhes = mcp_client.get("/api/v1/oauth/consent", params={"request": handle}, headers=cookie_headers(alice)).json()
    assert detalhes["client"]["kind"] == "cimd"
    assert detalhes["client"]["client_host"] == "claude.ai"
    assert detalhes["client"]["loopback_only"] is True
    aprovado = mcp_client.post(
        "/api/v1/oauth/consent/approve", json={"request": handle, "scopes": ["finance.read"]}, headers=cookie_headers(alice)
    ).json()["redirect_to"]
    codigo = parse_qs(urlsplit(aprovado).query)["code"][0]
    r = mcp_client.post("/api/v1/oauth/token", data={
        "grant_type": "authorization_code", "code": codigo, "redirect_uri": "http://localhost:51234/callback",
        "code_verifier": "v" * 50, "client_id": URL,
    })
    assert r.status_code == 200, r.text


def test_documento_com_client_id_divergente(mcp_client, cimd):
    cimd[URL]["client_id"] = "https://outro.example/meta"
    r = _autoriza(mcp_client, URL, "http://localhost:1/callback")
    assert urlsplit(r.headers["location"]).path == "/oauth/consent"
    assert "invalid_client" in r.headers["location"]


def test_documento_so_com_private_key_jwt_nao_e_atendivel(mcp_client, cimd):
    cimd[URL]["token_endpoint_auth_method"] = "private_key_jwt"
    r = _autoriza(mcp_client, URL, "http://localhost:1/callback")
    assert "invalid_client" in r.headers["location"]


def test_chatgpt_com_none_na_lista_vira_publico(mcp_client, db_session, cimd):
    """O CIMD do ChatGPT prefere private_key_jwt mas aceita none: fica none."""
    url = "https://chatgpt.com/oauth/client.json"
    cimd[url] = {
        "client_id": url, "client_name": "ChatGPT",
        "redirect_uris": ["https://chatgpt.com/connector_platform_oauth_redirect"],
        "token_endpoint_auth_method": "private_key_jwt",
        "token_endpoint_auth_methods_supported": ["none", "private_key_jwt"],
        "grant_types": ["authorization_code", "refresh_token"],
    }
    r = _autoriza(mcp_client, url, "https://chatgpt.com/connector_platform_oauth_redirect")
    assert "request=" in r.headers["location"]
    from sqlmodel import select
    from app.models.oauth import OAuthClient

    cliente = db_session.exec(select(OAuthClient).where(OAuthClient.client_id == url)).one()
    assert cliente.token_endpoint_auth_method == "none"


def test_redirect_fora_do_documento(mcp_client, cimd):
    r = _autoriza(mcp_client, URL, "https://atacante.example/cb")
    assert urlsplit(r.headers["location"]).path == "/oauth/consent"
    assert "error=" in r.headers["location"]
