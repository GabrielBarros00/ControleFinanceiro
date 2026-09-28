"""A tela alcança o histórico e as exclusões, com os mesmos gates do MCP."""
from fastapi.testclient import TestClient

from app.main import app
from app.models.workspace import WorkspaceMembership, WorkspaceRole


client = TestClient(app)


def test_lancamento_excluido_aparece_na_lixeira_e_o_historico_continua_acessivel(
    db_session, setup_data, override_get_session,
):
    ws = setup_data["ws1"].id
    dono = setup_data["u1"].id
    base = f"/api/v1/workspaces/{ws}/transactions"
    cabecalho = setup_data["headers1"]
    criado = client.post(base + "/", json={
        "title": "Mercado", "total_amount": "80.00", "transaction_date": "2026-09-15T12:00:00",
        "payers": [{"user_id": dono, "amount": "80.00"}],
        "splits": [{"user_id": dono, "split_method": "equal", "input_value": 0}],
    }, headers=cabecalho)
    assert criado.status_code == 200, criado.text
    tx_id = criado.json()["id"]
    assert client.put(base + f"/{tx_id}", json={"title": "Mercado novo"}, headers=cabecalho).status_code == 200
    assert client.delete(base + f"/{tx_id}", headers=cabecalho).status_code == 200

    assert client.get(base + "/?month=2026-09", headers=cabecalho).json()["items"] == []
    excluidos = client.get(base + "/?month=2026-09&deleted=true", headers=cabecalho)
    assert excluidos.status_code == 200, excluidos.text
    assert [item["id"] for item in excluidos.json()["items"]] == [tx_id]
    assert excluidos.json()["total_amount"] == "0"

    historico = client.get(base + f"/{tx_id}/history", headers=cabecalho)
    assert historico.status_code == 200, historico.text
    assert [r["action"] for r in historico.json()["entries"]] == ["deleted", "updated", "created"]
    assert historico.json()["entries"][1]["changes"][0] == {
        "field": "title", "before": "Mercado", "after": "Mercado novo",
    }
    assert client.post(base + f"/{tx_id}/restore", headers=cabecalho).status_code == 200
    assert client.get(base + "/?month=2026-09&deleted=true", headers=cabecalho).json()["items"] == []
    assert client.get(base + f"/{tx_id}/history", headers=cabecalho).json()["entries"][0]["action"] == "restored"

    # Mesmo pertencendo ao espaço, quem não está envolvido não vê a linha nem
    # a contagem da lixeira, e o histórico responde 404.
    db_session.add(WorkspaceMembership(
        workspace_id=ws, user_id=setup_data["u2"].id, role=WorkspaceRole.member,
    ))
    db_session.commit()
    assert client.get(base + f"/{tx_id}/history", headers=setup_data["headers2"]).status_code == 404
    assert client.get(base + "/?month=2026-09&deleted=true", headers=setup_data["headers2"]).json()["total"] == 0


def test_renda_excluida_so_o_dono_lista_e_restaura(setup_data, override_get_session):
    base = "/api/v1/me/income"
    cabecalho = setup_data["headers1"]
    criado = client.post(base, json={
        "title": "Freela", "amount": "500.00", "received_at": "2026-09-15T12:00:00",
    }, headers=cabecalho)
    assert criado.status_code == 200, criado.text
    income_id = criado.json()["id"]
    assert client.delete(f"{base}/{income_id}", headers=cabecalho).status_code == 200

    assert client.get(base + "?month=2026-09", headers=cabecalho).json() == []
    excluidas = client.get(base + "?month=2026-09&deleted=true", headers=cabecalho)
    assert [item["id"] for item in excluidas.json()] == [income_id]
    assert client.get(base + "?month=2026-09&deleted=true", headers=setup_data["headers2"]).json() == []
    assert client.post(f"{base}/{income_id}/restore", headers=setup_data["headers2"]).status_code == 404

    restaurada = client.post(f"{base}/{income_id}/restore", headers=cabecalho)
    assert restaurada.status_code == 200, restaurada.text
    assert restaurada.json()["id"] == income_id
    assert client.get(base + "?month=2026-09&deleted=true", headers=cabecalho).json() == []
    assert [item["id"] for item in client.get(base + "?month=2026-09", headers=cabecalho).json()] == [income_id]
