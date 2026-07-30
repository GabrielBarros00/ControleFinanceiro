"""Regressão: quota de anexos, gate de propriedade em recorrentes e teto do
acerto por mês."""
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app
from app.models.attachment import Attachment
from app.models.recurring import RecurringExpense
from app.models.transaction import Transaction
from app.models.user import User
from app.models.workspace import WorkspaceMembership, WorkspaceRole
from app.core.jwt import create_access_token

PNG_1PX = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06"
    b"\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05"
    b"\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
)


@pytest.fixture(name="client")
def client_fixture(override_get_session):
    return TestClient(app)


def _member(db, ws, name="Membro", email="membro@example.com", role=WorkspaceRole.member):
    user = User(name=name, email=email, password_hash="hash")
    db.add(user)
    db.commit()
    db.refresh(user)
    db.add(WorkspaceMembership(workspace_id=ws.id, user_id=user.id, role=role))
    db.commit()
    token = create_access_token(data={"sub": str(user.id)})
    return user, {"Cookie": f"access_token={token}"}


# --- Quota de anexos -------------------------------------------------------


def test_quota_de_anexos_bloqueia_upload(client, db_session, setup_data, monkeypatch):
    ws, u1 = setup_data["ws1"], setup_data["u1"]
    tx = Transaction(
        title="Com recibo", total_amount=Decimal("10.00"), billing_month="2026-07",
        workspace_id=ws.id, created_by_user_id=u1.id,
    )
    db_session.add(tx)
    db_session.commit()
    db_session.refresh(tx)

    # Cota minúscula: já quase cheia por um anexo existente
    monkeypatch.setattr(settings, "ATTACHMENT_QUOTA_BYTES", 100)
    db_session.add(Attachment(
        workspace_id=ws.id, transaction_id=tx.id, filename="antigo.png",
        content_type="image/png", size_bytes=95, data=b"x" * 95,
        uploaded_by_user_id=u1.id,
    ))
    db_session.commit()

    res = client.post(
        f"/api/v1/workspaces/{ws.id}/transactions/{tx.id}/attachments",
        files={"file": ("novo.png", PNG_1PX, "image/png")},
        headers=setup_data["headers1"],
    )
    assert res.status_code == 413
    assert "Cota de anexos" in res.json()["error"]["message"]


def test_upload_dentro_da_cota_passa(client, db_session, setup_data):
    ws, u1 = setup_data["ws1"], setup_data["u1"]
    tx = Transaction(
        title="Com recibo", total_amount=Decimal("10.00"), billing_month="2026-07",
        workspace_id=ws.id, created_by_user_id=u1.id,
    )
    db_session.add(tx)
    db_session.commit()
    db_session.refresh(tx)

    res = client.post(
        f"/api/v1/workspaces/{ws.id}/transactions/{tx.id}/attachments",
        files={"file": ("recibo.png", PNG_1PX, "image/png")},
        headers=setup_data["headers1"],
    )
    assert res.status_code == 200


# --- Propriedade de despesa recorrente -------------------------------------


def test_member_nao_edita_recorrente_alheia(client, db_session, setup_data):
    ws, dono = setup_data["ws1"], setup_data["u1"]
    _, headers_outro = _member(db_session, ws)

    template = RecurringExpense(
        title="Aluguel", base_amount=Decimal("1000.00"), day_of_month=5,
        workspace_id=ws.id, created_by_user_id=dono.id,
    )
    db_session.add(template)
    db_session.commit()
    db_session.refresh(template)

    # 404, não 403 (ADR 0018): o template TEM dono (created_by_user_id), então
    # para outro member ele é invisível. Recorrência sem dono seria da casa e
    # continuaria visível/editável por todos.
    res = client.put(
        f"/api/v1/workspaces/{ws.id}/recurring/{template.id}",
        json={"base_amount": "1.00"},
        headers=headers_outro,
    )
    assert res.status_code == 404

    res = client.delete(
        f"/api/v1/workspaces/{ws.id}/recurring/{template.id}", headers=headers_outro
    )
    assert res.status_code == 404

    # O dono continua podendo
    res = client.put(
        f"/api/v1/workspaces/{ws.id}/recurring/{template.id}",
        json={"base_amount": "1200.00"},
        headers=setup_data["headers1"],
    )
    assert res.status_code == 200


def test_admin_edita_recorrente_de_qualquer_um(client, db_session, setup_data):
    ws = setup_data["ws1"]
    autor, headers_autor = _member(db_session, ws, name="Autor", email="autor@example.com")

    res = client.post(
        f"/api/v1/workspaces/{ws.id}/recurring",
        json={"title": "Netflix", "base_amount": "55.90", "day_of_month": 10},
        headers=headers_autor,
    )
    assert res.status_code == 200
    template_id = res.json()["id"]

    # u1 é owner do ws1
    res = client.put(
        f"/api/v1/workspaces/{ws.id}/recurring/{template_id}",
        json={"base_amount": "59.90"},
        headers=setup_data["headers1"],
    )
    assert res.status_code == 200
