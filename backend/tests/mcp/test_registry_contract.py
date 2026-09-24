"""Contrato do catálogo de tools — o que TODA tool tem de cumprir para entrar.

É a versão executável do checklist de qualidade: nome estável e aceito por todos
os clientes, título, descrição com "Use quando / Não use quando", as quatro
annotations explícitas e coerentes com o que a tool faz, schema de entrada
fechado (sem objeto genérico), schema de saída, escopo conhecido e idempotência
declarada nas escritas que criam.
"""
from __future__ import annotations

import json
import re

import pytest

from app.mcp.registry import REGISTRY, input_schema, output_schema
from app.mcp.server import WIDGET_URI, get_server
from app.services.oauth import scopes as escopos
from tests.mcp.conftest import issue_token, rpc

NOME = re.compile(r"^[a-z][a-z0-9_]{2,31}$")


@pytest.fixture(scope="module", autouse=True)
def _carrega():
    get_server()


def todas():
    get_server()
    return list(REGISTRY.values())


def test_catalogo_tem_as_39_tools():
    # 35 do plano + 3 de exibição (`*_show`), separadas das de dados para o
    # ChatGPT não desenhar um componente a cada consulta, + o link de envio de
    # anexo pelo terminal (`attachments_upload_link`).
    assert len(REGISTRY) == 39


@pytest.mark.parametrize("spec", todas(), ids=lambda s: s.name)
def test_identidade_e_texto(spec):
    assert NOME.match(spec.name), "nome aceito por Claude/Codex/Gemini: [a-z0-9_], até 32"
    assert spec.title and len(spec.title) <= 40
    assert "Use quando:" in spec.description and "Não use quando:" in spec.description
    assert len(spec.description) <= 1600, "descrição longa demais pesa em toda conversa"


@pytest.mark.parametrize("spec", todas(), ids=lambda s: s.name)
def test_annotations_coerentes(spec):
    a = spec.annotations()
    assert set(a) == {"title", "readOnlyHint", "destructiveHint", "idempotentHint", "openWorldHint"}
    assert all(isinstance(a[k], bool) for k in a if k != "title")
    assert a["openWorldHint"] is False  # domínio fechado: só o banco do app
    if spec.kind == "read":
        assert a["readOnlyHint"] is True and a["destructiveHint"] is False
        assert spec.scope == escopos.FINANCE_READ
    else:
        assert a["readOnlyHint"] is False
        assert spec.scope in escopos.ALL_SCOPES and spec.scope != escopos.FINANCE_READ
    if spec.kind == "destructive":
        assert a["destructiveHint"] is True
    # Tudo aqui é idempotente: leitura por natureza, criação por chave, edição
    # por ser "defina X", massa pelo token de uso único.
    assert a["idempotentHint"] is True


@pytest.mark.parametrize("spec", todas(), ids=lambda s: s.name)
def test_idempotencia_declarada_nas_criacoes(spec):
    props = input_schema(spec).get("properties", {})
    if spec.idempotency_key:
        assert "idempotency_key" in input_schema(spec)["required"]
        assert spec.replay is not None, "sem replay, o retry não tem o que devolver"
    else:
        assert "idempotency_key" not in props


def _objetos(no, caminho="$"):
    if isinstance(no, dict):
        if no.get("type") == "object" or "properties" in no:
            yield caminho, no
        for k, v in no.items():
            yield from _objetos(v, f"{caminho}.{k}")
    elif isinstance(no, list):
        for i, v in enumerate(no):
            yield from _objetos(v, f"{caminho}[{i}]")


@pytest.mark.parametrize("spec", todas(), ids=lambda s: s.name)
def test_schema_de_entrada_fechado(spec):
    esquema = input_schema(spec)
    assert esquema["type"] == "object"
    assert "$defs" not in str(esquema) and "$ref" not in str(esquema)
    for caminho, obj in _objetos(esquema):
        assert obj.get("additionalProperties") is False, f"{caminho} aceita campo extra"
        # A raiz pode ser vazia (tool sem parâmetro, `NoInput`); objeto ANINHADO não.
        assert caminho == "$" or obj.get("properties"), f"{caminho} é objeto genérico"
    for nome in esquema.get("properties", {}):
        assert nome not in {"user_id", "owner_user_id", "created_by_user_id", "sql", "query_sql", "where"}


#: O que o modelo lê do catálogo em TODA conversa: descrição + schema de entrada
#: das 38 tools (~56,6 mil caracteres hoje; eram ~80 mil antes de o schema perder
#: `title` automático e `anyOf` com nulo). Passar do teto é decisão consciente:
#: suba o número aqui, e diga no PR por que a tool nova vale os tokens.
TETO_DO_CATALOGO = 60_000


def test_catalogo_cabe_no_orcamento_de_contexto():
    visivel = sum(len(s.description) + len(json.dumps(input_schema(s), ensure_ascii=False)) for s in todas())
    assert visivel <= TETO_DO_CATALOGO, f"catálogo com {visivel:,} caracteres (teto {TETO_DO_CATALOGO:,})"


@pytest.mark.parametrize("spec", todas(), ids=lambda s: s.name)
def test_schema_de_entrada_sem_ruido(spec):
    texto = json.dumps(input_schema(spec), ensure_ascii=False)
    assert '"title": "' not in texto.replace('"title": {', ""), "title automático do Pydantic"
    assert '{"type": "null"}' not in texto, "anyOf com nulo: omitir o campo já é o nulo"
    assert '"default": null' not in texto


#: As palavras-chave do objeto `Schema` que a API do Gemini documenta
#: (ai.google.dev/api/generate-content), mais `additionalProperties`, que o Gemini
#: CLI tira antes de mandar. O Gemini CLI e o Antigravity passam o `inputSchema`
#: quase cru ao modelo (`parametersJsonSchema`): uma palavra-chave fora disto pode
#: ser recusada e derrubar o catálogo inteiro para quem usa Gemini, sem erro
#: nenhum do nosso lado. Claude, ChatGPT e Codex aceitam este subconjunto também.
PALAVRAS_DO_GEMINI = {
    "type", "format", "title", "description", "example", "nullable", "enum", "minItems", "maxItems",
    "minLength", "maxLength", "minimum", "maximum", "pattern", "minProperties", "maxProperties",
    "properties", "required", "items", "anyOf", "default", "propertyOrdering", "additionalProperties",
}


def _palavras(no, achadas: set):
    if isinstance(no, dict):
        for chave, valor in no.items():
            if chave == "properties" and isinstance(valor, dict):
                for esquema in valor.values():  # as chaves aqui são NOMES de campo
                    _palavras(esquema, achadas)
                continue
            achadas.add(chave)
            _palavras(valor, achadas)
    elif isinstance(no, list):
        for item in no:
            _palavras(item, achadas)
    return achadas


@pytest.mark.parametrize("spec", todas(), ids=lambda s: s.name)
def test_schema_de_entrada_so_com_palavras_que_o_gemini_aceita(spec):
    fora = _palavras(input_schema(spec), set()) - PALAVRAS_DO_GEMINI
    assert not fora, f"{spec.name}: {sorted(fora)} fora do schema documentado do Gemini"


@pytest.mark.parametrize("spec", todas(), ids=lambda s: s.name)
def test_schema_de_saida(spec):
    esquema = output_schema(spec)
    assert esquema.get("type") == "object" and esquema.get("properties")


@pytest.mark.parametrize("spec", todas(), ids=lambda s: s.name)
def test_meta_de_seguranca_e_ui(spec):
    meta = spec.tool_meta()
    assert meta["securitySchemes"] == [{"type": "oauth2", "scopes": [spec.scope]}]
    if spec.ui:
        assert spec.ui == WIDGET_URI
        assert meta["ui"]["resourceUri"] == WIDGET_URI and meta["openai/outputTemplate"] == WIDGET_URI
    if spec.app_callable:
        assert meta["ui"]["visibility"] == ["model", "app"]


def test_tools_list_publica_o_registro(mcp_client, db_session, duo):
    token = issue_token(db_session, duo["alice"])
    publicadas = rpc(mcp_client, token, "tools/list").json()["result"]["tools"]
    assert [t["name"] for t in publicadas] == list(REGISTRY)
    for t in publicadas:
        spec = REGISTRY[t["name"]]
        assert t["annotations"]["readOnlyHint"] == spec.read_only
        assert t["annotations"]["destructiveHint"] == spec.destructive
        assert t["inputSchema"] == input_schema(spec)
        assert t["outputSchema"] == output_schema(spec)
        assert t["_meta"]["securitySchemes"][0]["scopes"] == [spec.scope]


def test_nada_de_tool_generica():
    proibidas = {"execute_sql", "call_api", "execute_action", "run_query", "sql"}
    assert not proibidas & set(REGISTRY)


def test_tools_md_gerado_esta_em_dia():
    """`docs/mcp/TOOLS.md` é gerado do registro; mudou a tool, regenere o doc."""
    from app.mcp.docs import DESTINO, render

    assert DESTINO.read_text(encoding="utf-8") == render(), "rode `python -m app.mcp.docs` e comite"
