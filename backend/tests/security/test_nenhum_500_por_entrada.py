"""Entrada válida-mas-extrema deve virar 4xx — nunca 500.

Um 500 é o servidor dizendo "o problema é meu". Quando ele vem de um número que
a pessoa digitou, o problema é de validação: dá para derrubar a requisição — e
sujar o log de erro — preenchendo um formulário.

A auditoria encontrou um caso real assim: taxa de 0,5 ao mês em 360 parcelas
estourava o `Decimal` na geração do cronograma (`InvalidOperation` → 500).

**O corpo é montado a partir do OpenAPI**, e não chutado. A primeira versão
deste teste mandava um corpo único com todos os campos suspeitos de uma vez —
e não pegava nada, porque um `title` de 500 caracteres já era recusado com 422
antes de qualquer número chegar ao cálculo. Aqui cada requisição leva um corpo
VÁLIDO segundo o schema, com UM campo numérico levado ao extremo por vez: é a
única forma de o valor extremo chegar ao domínio.
"""
from typing import Any, Dict

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from app.core.jwt import create_access_token
from app.main import app
from app.models.user import User
from app.models.workspace import (
    FinancialAccess, Workspace, WorkspaceMembership, WorkspaceRole,
)

cliente = TestClient(app, raise_server_exceptions=False)

#: Valores extremos aplicados a UM campo numérico por vez.
EXTREMOS = ["0", "-1", "0.0000001", "999999", "99999999999999999999"]


def _resolve(schema: Dict[str, Any], spec: Dict[str, Any]) -> Dict[str, Any]:
    if "$ref" in schema:
        nome = schema["$ref"].split("/")[-1]
        return spec.get("components", {}).get("schemas", {}).get(nome, {})
    for chave in ("anyOf", "allOf", "oneOf"):
        if chave in schema:
            for alt in schema[chave]:
                if alt.get("type") != "null":
                    return _resolve(alt, spec)
    return schema


def _valor_valido(prop: Dict[str, Any], spec: Dict[str, Any]) -> Any:
    prop = _resolve(prop, spec)
    if "enum" in prop and prop["enum"]:
        return prop["enum"][0]
    tipo = prop.get("type")
    if tipo == "integer":
        return int(prop.get("minimum", 1)) or 1
    if tipo == "number":
        return 10
    if tipo == "boolean":
        return False
    if tipo == "array":
        return []
    if tipo == "object":
        return {}
    fmt = prop.get("format")
    if fmt == "date":
        return "2026-01-15"
    if fmt == "date-time":
        return "2026-01-15T12:00:00Z"
    if fmt == "email":
        return "alguem@example.com"
    return "ok"


def _corpo_base(rota: APIRoute, spec: Dict[str, Any]):
    """Corpo mínimo VÁLIDO segundo o schema, e a lista de campos numéricos."""
    caminho = spec["paths"].get(rota.path)
    if not caminho:
        return None, []
    for metodo in ("post", "put", "patch"):
        op = caminho.get(metodo)
        if not op or "requestBody" not in op:
            continue
        schema = op["requestBody"].get("content", {}).get("application/json", {}).get("schema")
        if not schema:
            continue
        schema = _resolve(schema, spec)
        props = schema.get("properties", {})
        if not props:
            continue
        obrigatorios = set(schema.get("required", []))
        corpo, numericos = {}, []
        for nome, prop in props.items():
            resolvido = _resolve(prop, spec)
            if resolvido.get("type") in ("integer", "number") or resolvido.get("anyOf"):
                if resolvido.get("type") in ("integer", "number"):
                    numericos.append(nome)
            if nome in obrigatorios:
                corpo[nome] = _valor_valido(prop, spec)
        # campos numéricos opcionais também entram: é onde moram taxa e prazo
        for nome, prop in props.items():
            if nome in corpo:
                continue
            if _resolve(prop, spec).get("type") in ("integer", "number"):
                corpo[nome] = _valor_valido(prop, spec)
                numericos.append(nome)
        return corpo, sorted(set(numericos))
    return None, []


@pytest.fixture(name="ator")
def ator_fixture(db_session, override_get_session):
    """A sessão vem no `request` do fixture para ser limpa ENTRE as chamadas."""
    user = User(name="Fuzz", email="fuzz@ex.com", password_hash="h")
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    ws = Workspace(name="WS", created_by_user_id=user.id)
    db_session.add(ws)
    db_session.commit()
    db_session.refresh(ws)
    db_session.add(WorkspaceMembership(
        workspace_id=ws.id, user_id=user.id, role=WorkspaceRole.owner,
        financial_access=FinancialAccess.full_workspace,
    ))
    db_session.commit()
    return {
        "ws_id": ws.id,
        "sessao": db_session,
        "cookies": {"access_token": create_access_token(data={"sub": str(user.id)})},
    }


def test_nenhuma_rota_de_escrita_responde_500(ator):
    spec = app.openapi()
    substituicoes = {
        "workspace_id": str(ator["ws_id"]), "transaction_id": "1", "card_id": "1",
        "financing_id": "1", "account_id": "1", "income_id": "1", "statement_id": "1",
        "installment_number": "1", "category_id": "1", "tag_id": "1", "user_id": "1",
        "settlement_id": "1", "batch_id": "1", "attachment_id": "1",
        "notification_id": "1", "estimate_id": "1", "recurring_id": "1",
        "token": "x", "key": "registration_mode", "invite_id": "1",
        "member_id": "1", "group_id": "1",
    }

    quebrou, chamadas, com_corpo = [], 0, 0
    for rota in app.routes:
        if not isinstance(rota, APIRoute):
            continue
        metodos = rota.methods & {"POST", "PUT", "PATCH"}
        if not metodos:
            continue
        url = rota.path
        for nome, valor in substituicoes.items():
            url = url.replace("{" + nome + "}", valor)
        if "{" in url:
            continue

        base, numericos = _corpo_base(rota, spec)
        if base is None:
            continue
        com_corpo += 1
        variantes = [base]
        for campo in numericos:
            for extremo in EXTREMOS:
                variantes.append({**base, campo: extremo})

        for metodo in sorted(metodos):
            for corpo in variantes:
                resp = cliente.request(metodo, url, json=corpo, cookies=ator["cookies"])
                chamadas += 1
                # EM PRODUÇÃO cada requisição abre a PRÓPRIA sessão; aqui a suíte
                # compartilha uma só (`override_get_session`). Sem este rollback,
                # o primeiro erro de integridade deixa a sessão marcada e TODAS as
                # chamadas seguintes viram `PendingRollbackError` — 106 "500" que
                # não existem no servidor de verdade. O rollback devolve ao teste
                # o isolamento que a produção já tem.
                ator["sessao"].rollback()
                if resp.status_code >= 500:
                    quebrou.append(f"{metodo} {url} {corpo} -> {resp.status_code}")

    assert com_corpo >= 20, f"só {com_corpo} rotas com corpo — a montagem falhou"
    assert chamadas > 300, f"só {chamadas} chamadas — a varredura não está medindo"
    assert not quebrou, f"{len(quebrou)} respostas 5xx: " + " | ".join(quebrou[:8])


# `int` do Python não tem teto; a coluna do banco tem (64 bits). Um id acima
# disso passava batido pelo Pydantic e estourava no driver.
ID_GRANDE = 99999999999999999999


def test_id_acima_de_64_bits_responde_422_e_nao_500(ator):
    """Nem no caminho, nem no corpo.

    `session.get(Model, id_gigante)` levanta antes de conseguir devolver `None`:
    `OverflowError` no SQLite, `DataError` no Postgres. Sem tratamento, os dois
    viravam 500 — o servidor assumindo a culpa por um número que o cliente
    digitou. Não é vazamento nem corrupção; é ruído de erro que qualquer pessoa
    dispara editando a barra de endereços.
    """
    ws_id, cookies = ator["ws_id"], ator["cookies"]
    alvos = [
        ("GET", f"/api/v1/workspaces/{ws_id}/transactions/{ID_GRANDE}"),
        ("GET", f"/api/v1/me/financing/{ID_GRANDE}"),
        ("DELETE", f"/api/v1/workspaces/{ws_id}/transactions/{ID_GRANDE}"),
    ]
    ruins = []
    for metodo, url in alvos:
        resp = cliente.request(metodo, url, cookies=cookies)
        ator["sessao"].rollback()
        if resp.status_code >= 500:
            ruins.append(f"{metodo} {url} -> {resp.status_code}")

    corpo = {"title": "ok", "base_amount": 10, "interval": 1, "category_id": ID_GRANDE}
    resp = cliente.post(
        f"/api/v1/workspaces/{ws_id}/recurring", json=corpo, cookies=cookies
    )
    ator["sessao"].rollback()
    if resp.status_code >= 500:
        ruins.append(f"POST .../recurring category_id -> {resp.status_code}")

    assert not ruins, "500 por identificador fora de faixa: " + "; ".join(ruins)
