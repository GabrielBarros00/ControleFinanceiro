"""A URI guardada no descritor da tool continua legível depois de atualizar o widget."""
import pytest

from app.mcp.server import widget_html
from app.mcp.ui import WIDGET_URI, WIDGET_VERSION
from tests.mcp.conftest import issue_token, rpc


@pytest.mark.parametrize("protocolo", ["2025-11-25", "2026-07-28"])
@pytest.mark.parametrize("versao", range(1, WIDGET_VERSION + 1))
def test_widget_de_descritor_em_cache_continua_disponivel(mcp_client, db_session, duo, protocolo, versao):
    token = issue_token(db_session, duo["alice"])
    uri = f"ui://controle-financeiro/widget-v{versao}.html"
    resposta = rpc(mcp_client, token, "resources/read", {"uri": uri}, version=protocolo)
    assert resposta.status_code == 200, resposta.text
    corpo = resposta.json()
    assert "error" not in corpo, corpo
    conteudo = corpo["result"]["contents"][0]
    assert conteudo["uri"] == uri
    assert conteudo["mimeType"] == "text/html;profile=mcp-app"
    assert conteudo["text"] == widget_html()
    assert '<div id="root">' in conteudo["text"]
    # A mesma política de isolamento, inclusive quando o descritor é antigo.
    assert conteudo["_meta"]["ui"]["csp"] == {"connectDomains": [], "resourceDomains": []}


@pytest.mark.parametrize("uri", [
    "ui://controle-financeiro/widget-v0.html",
    f"ui://controle-financeiro/widget-v{WIDGET_VERSION + 1}.html",
    "ui://outro-app/widget-v8.html",
    "ui://controle-financeiro/widget-v08.html",
    "ui://controle-financeiro/segredo.html",
])
def test_compatibilidade_nao_aceita_recurso_que_nunca_foi_publicado(mcp_client, db_session, duo, uri):
    token = issue_token(db_session, duo["alice"])
    corpo = rpc(mcp_client, token, "resources/read", {"uri": uri}, version="2025-11-25").json()
    assert corpo["error"]["code"] == -32602


def test_recurso_antigo_continua_exigindo_autenticacao(mcp_client):
    resposta = rpc(mcp_client, None, "resources/read", {"uri": "ui://controle-financeiro/widget-v8.html"})
    assert resposta.status_code == 401


def test_tools_so_anunciam_o_widget_atual(mcp_client, db_session, duo):
    token = issue_token(db_session, duo["alice"])
    tools = rpc(mcp_client, token, "tools/list").json()["result"]["tools"]
    visuais = [t for t in tools if t.get("_meta", {}).get("ui", {}).get("resourceUri")]
    assert visuais
    for tool in visuais:
        assert tool["_meta"]["ui"]["resourceUri"] == WIDGET_URI
        assert tool["_meta"]["openai/outputTemplate"] == WIDGET_URI
