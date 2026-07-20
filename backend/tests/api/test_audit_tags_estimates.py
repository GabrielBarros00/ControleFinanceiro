"""Auditoria por workspace (AUD-001), tags reativáveis (TAG-001) e estimates
com FK de categoria (BUD-001)."""
from fastapi.testclient import TestClient

from app.main import app
from app.models.workspace import WorkspaceMembership, WorkspaceRole

client = TestClient(app)


def _tx_payload(user_id):
    return {
        "title": "Compra",
        "total_amount": 20.0,
        "transaction_date": "2026-03-01T12:00:00",
        "payers": [{"user_id": user_id, "amount": 20.0}],
        "splits": [{"user_id": user_id, "split_method": "equal", "input_value": 0}],
    }


def test_auditoria_por_workspace_admin_only(db_session, setup_data, override_get_session):
    ws, u1 = setup_data["ws1"], setup_data["u1"]
    # gera trilha
    client.post(f"/api/v1/workspaces/{ws.id}/transactions/", json=_tx_payload(u1.id), headers=setup_data["headers1"])

    res = client.get(f"/api/v1/workspaces/{ws.id}/audit", headers=setup_data["headers1"])
    assert res.status_code == 200, res.text
    entries = res.json()
    assert any(e["resource_type"] == "Transaction" and e["workspace_id"] == ws.id for e in entries)

    # member (não admin) não consulta a trilha
    db_session.add(WorkspaceMembership(workspace_id=ws.id, user_id=setup_data["u2"].id, role=WorkspaceRole.member))
    db_session.commit()
    res = client.get(f"/api/v1/workspaces/{ws.id}/audit", headers=setup_data["headers2"])
    assert res.status_code == 403


def test_tag_reativavel(db_session, setup_data, override_get_session):
    ws, headers = setup_data["ws1"], setup_data["headers1"]
    created = client.post(f"/api/v1/workspaces/{ws.id}/tags", json={"name": "Mercado"}, headers=headers).json()
    tag_id = created["id"]
    client.delete(f"/api/v1/workspaces/{ws.id}/tags/{tag_id}", headers=headers)

    # Recriar com o mesmo nome REATIVA a antiga (não bloqueia para sempre)
    again = client.post(f"/api/v1/workspaces/{ws.id}/tags", json={"name": "Mercado"}, headers=headers)
    assert again.status_code == 200, again.text
    assert again.json()["id"] == tag_id


def test_estimate_categoria_invalida(db_session, setup_data, override_get_session):
    ws, headers = setup_data["ws1"], setup_data["headers1"]
    res = client.post(
        f"/api/v1/workspaces/{ws.id}/analytics/estimates",
        json={"category": "Comida", "amount": 100.0, "month": "2026-03", "category_id": 99999},
        headers=headers,
    )
    assert res.status_code == 400
