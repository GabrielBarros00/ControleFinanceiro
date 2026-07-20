"""CAT-001: nome de categoria único por workspace, com reativação da excluída."""
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def _base(ws_id: int) -> str:
    return f"/api/v1/workspaces/{ws_id}/categories"


def test_categoria_nome_unico_e_reativa(setup_data, override_get_session):
    ws = setup_data["ws1"]
    headers = setup_data["headers1"]
    base = _base(ws.id)

    r1 = client.post(base, json={"name": "Mercado"}, headers=headers)
    assert r1.status_code == 200, r1.text
    cid = r1.json()["id"]

    # Duplicata ativa é recusada
    r2 = client.post(base, json={"name": "Mercado"}, headers=headers)
    assert r2.status_code == 400

    # Excluir e recriar com o mesmo nome REATIVA a antiga (mesmo id)
    assert client.delete(f"{base}/{cid}", headers=headers).status_code == 200
    r3 = client.post(base, json={"name": "Mercado", "color": "#abcdef"}, headers=headers)
    assert r3.status_code == 200, r3.text
    assert r3.json()["id"] == cid
    assert r3.json()["color"] == "#abcdef"


def test_categoria_update_recusa_nome_duplicado(setup_data, override_get_session):
    ws = setup_data["ws1"]
    headers = setup_data["headers1"]
    base = _base(ws.id)

    client.post(base, json={"name": "Casa"}, headers=headers)
    other = client.post(base, json={"name": "Lazer"}, headers=headers).json()

    # Renomear "Lazer" para "Casa" (já existente) é recusado
    resp = client.put(f"{base}/{other['id']}", json={"name": "Casa"}, headers=headers)
    assert resp.status_code == 400
