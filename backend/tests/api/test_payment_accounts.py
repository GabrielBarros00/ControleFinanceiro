"""Contas/carteiras (ADR 0004): CRUD, reativação e isolamento por workspace."""
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def _create(ws_id, headers, name="Nubank PJ", type_="checking", **over):
    payload = {"name": name, "type": type_, **over}
    return client.post("/api/v1/me/payment-accounts", json=payload, headers=headers)


def test_crud_de_contas(setup_data, override_get_session):
    ws1 = setup_data["ws1"]
    headers = setup_data["headers1"]

    resp = _create(ws1.id, headers, name="Carteira", type_="cash")
    assert resp.status_code == 200, resp.text
    account = resp.json()
    assert account["type"] == "cash"
    assert account["active"] is True

    resp = client.get("/api/v1/me/payment-accounts", headers=headers)
    assert [a["name"] for a in resp.json()] == ["Carteira"]

    resp = client.put(
        f"/api/v1/me/payment-accounts/{account['id']}",
        json={"name": "Carteira Física", "active": False},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["name"] == "Carteira Física"
    assert resp.json()["active"] is False

    resp = client.delete(f"/api/v1/me/payment-accounts/{account['id']}", headers=headers)
    assert resp.status_code == 200
    resp = client.get("/api/v1/me/payment-accounts", headers=headers)
    assert resp.json() == []


def test_nome_duplicado_e_reativacao(setup_data, override_get_session):
    ws1 = setup_data["ws1"]
    headers = setup_data["headers1"]

    first = _create(ws1.id, headers, name="Itaú").json()
    resp = _create(ws1.id, headers, name="Itaú")
    assert resp.status_code == 400
    assert "Já existe" in resp.json()["error"]["message"]

    # Excluir e recriar com o mesmo nome REATIVA (sem trava de soft delete)
    client.delete(f"/api/v1/me/payment-accounts/{first['id']}", headers=headers)
    resp = _create(ws1.id, headers, name="Itaú", type_="savings")
    assert resp.status_code == 200, resp.text
    assert resp.json()["id"] == first["id"]
    assert resp.json()["type"] == "savings"
    assert resp.json()["active"] is True


def test_dono_e_sempre_quem_criou(setup_data, override_get_session):
    """Não há mais como declarar dono: a conta é de quem a cria (ADR 0021).

    Antes `owner_user_id` vinha no corpo e a rota checava se essa pessoa era
    membro do workspace — um campo que só existia porque a conta morava lá.
    """
    resp = _create(setup_data["ws1"].id, setup_data["headers1"], owner_user_id=setup_data["u2"].id)
    assert resp.status_code == 200
    assert resp.json()["owner_user_id"] == setup_data["u1"].id


def test_isolamento_entre_pessoas(setup_data, override_get_session):
    _ws1, ws2 = setup_data["ws1"], setup_data["ws2"]
    account = _create(ws2.id, setup_data["headers2"], name="Conta WS2").json()

    # u1 não vê nem edita a conta do ws2
    resp = client.get("/api/v1/me/payment-accounts", headers=setup_data["headers1"])
    assert resp.json() == []
    resp = client.put(
        f"/api/v1/me/payment-accounts/{account['id']}",
        json={"name": "Invasão"},
        headers=setup_data["headers1"],
    )
    assert resp.status_code == 404
