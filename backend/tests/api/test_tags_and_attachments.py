"""Tags (CRUD + vínculo/filtro) e anexos (upload/download com validações)."""
from fastapi.testclient import TestClient

from app.main import app
from app.core.config import settings

client = TestClient(app)

PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"0" * 64


def _create_tag(ws_id, headers, name="Viagem", color="#f59e0b"):
    resp = client.post(f"/api/v1/workspaces/{ws_id}/tags", json={"name": name, "color": color}, headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()


def _create_tx(ws_id, u_id, headers, **overrides):
    payload = {
        "title": "Despesa",
        "total_amount": 50.0,
        "transaction_date": "2026-07-18T12:00:00",
        "payers": [{"user_id": u_id, "amount": 50.0}],
        "splits": [{"user_id": u_id, "split_method": "equal", "input_value": 0}],
    }
    payload.update(overrides)
    resp = client.post(f"/api/v1/workspaces/{ws_id}/transactions/", json=payload, headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()


# ---------------- tags ----------------

def test_tag_crud_and_unique_name(setup_data, override_get_session):
    ws1 = setup_data["ws1"]
    headers = setup_data["headers1"]

    tag = _create_tag(ws1.id, headers)
    assert tag["name"] == "Viagem"

    # Nome duplicado no mesmo workspace
    resp = client.post(f"/api/v1/workspaces/{ws1.id}/tags", json={"name": "Viagem"}, headers=headers)
    assert resp.status_code == 400

    # Rename
    resp = client.put(f"/api/v1/workspaces/{ws1.id}/tags/{tag['id']}", json={"name": "Férias"}, headers=headers)
    assert resp.status_code == 200
    assert resp.json()["name"] == "Férias"

    resp = client.get(f"/api/v1/workspaces/{ws1.id}/tags", headers=headers)
    assert [t["name"] for t in resp.json()] == ["Férias"]


def test_transaction_tags_roundtrip_and_filter(setup_data, override_get_session):
    ws1, u1 = setup_data["ws1"], setup_data["u1"]
    headers = setup_data["headers1"]

    tag_a = _create_tag(ws1.id, headers, name="Casa")
    tag_b = _create_tag(ws1.id, headers, name="Lazer")

    tx = _create_tx(ws1.id, u1.id, headers, title="Cinema", tag_ids=[tag_b["id"]])
    assert [t["name"] for t in tx["tags"]] == ["Lazer"]

    _create_tx(ws1.id, u1.id, headers, title="Aluguel", tag_ids=[tag_a["id"]])

    # Filtro por tag
    resp = client.get(f"/api/v1/workspaces/{ws1.id}/transactions/?tag_id={tag_b['id']}", headers=headers)
    items = resp.json()["items"]
    assert len(items) == 1
    assert items[0]["title"] == "Cinema"

    # Update parcial substitui as tags
    resp = client.put(
        f"/api/v1/workspaces/{ws1.id}/transactions/{tx['id']}",
        json={"tag_ids": [tag_a["id"], tag_b["id"]]},
        headers=headers,
    )
    assert resp.status_code == 200
    assert {t["name"] for t in resp.json()["tags"]} == {"Casa", "Lazer"}

    # Limpar tags
    resp = client.put(
        f"/api/v1/workspaces/{ws1.id}/transactions/{tx['id']}",
        json={"tag_ids": []},
        headers=headers,
    )
    assert resp.json()["tags"] == []


def test_transaction_rejects_foreign_tag(setup_data, override_get_session):
    ws1, u1, ws2 = setup_data["ws1"], setup_data["u1"], setup_data["ws2"]
    # Tag do ws2 (criada pelo u2)
    foreign = _create_tag(ws2.id, setup_data["headers2"], name="Alheia")

    payload = {
        "title": "Despesa",
        "total_amount": 50.0,
        "transaction_date": "2026-07-18T12:00:00",
        "payers": [{"user_id": u1.id, "amount": 50.0}],
        "splits": [{"user_id": u1.id, "split_method": "equal", "input_value": 0}],
        "tag_ids": [foreign["id"]],
    }
    resp = client.post(f"/api/v1/workspaces/{ws1.id}/transactions/", json=payload, headers=setup_data["headers1"])
    assert resp.status_code == 400


def test_deleted_tag_leaves_transactions(setup_data, override_get_session):
    ws1, u1 = setup_data["ws1"], setup_data["u1"]
    headers = setup_data["headers1"]

    tag = _create_tag(ws1.id, headers, name="Temporária")
    tx = _create_tx(ws1.id, u1.id, headers, tag_ids=[tag["id"]])

    resp = client.delete(f"/api/v1/workspaces/{ws1.id}/tags/{tag['id']}", headers=headers)
    assert resp.status_code == 200

    resp = client.get(f"/api/v1/workspaces/{ws1.id}/transactions/{tx['id']}", headers=headers)
    assert resp.json()["tags"] == []


# ---------------- attachments ----------------

def test_attachment_upload_download_delete(setup_data, override_get_session):
    ws1, u1 = setup_data["ws1"], setup_data["u1"]
    headers = setup_data["headers1"]
    tx = _create_tx(ws1.id, u1.id, headers)

    resp = client.post(
        f"/api/v1/workspaces/{ws1.id}/transactions/{tx['id']}/attachments",
        files={"file": ("recibo.png", PNG_BYTES, "image/png")},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    att = resp.json()
    assert att["filename"] == "recibo.png"
    assert att["size_bytes"] == len(PNG_BYTES)

    resp = client.get(f"/api/v1/workspaces/{ws1.id}/transactions/{tx['id']}/attachments", headers=headers)
    assert len(resp.json()) == 1

    resp = client.get(f"/api/v1/workspaces/{ws1.id}/attachments/{att['id']}", headers=headers)
    assert resp.status_code == 200
    assert resp.content == PNG_BYTES
    assert resp.headers["content-type"].startswith("image/png")

    resp = client.delete(f"/api/v1/workspaces/{ws1.id}/attachments/{att['id']}", headers=headers)
    assert resp.status_code == 200
    resp = client.get(f"/api/v1/workspaces/{ws1.id}/attachments/{att['id']}", headers=headers)
    assert resp.status_code == 404


def test_attachment_rejects_bad_type_and_empty(setup_data, override_get_session):
    ws1, u1 = setup_data["ws1"], setup_data["u1"]
    headers = setup_data["headers1"]
    tx = _create_tx(ws1.id, u1.id, headers)
    url = f"/api/v1/workspaces/{ws1.id}/transactions/{tx['id']}/attachments"

    resp = client.post(url, files={"file": ("virus.exe", b"MZ...", "application/x-msdownload")}, headers=headers)
    assert resp.status_code == 400

    resp = client.post(url, files={"file": ("vazio.png", b"", "image/png")}, headers=headers)
    assert resp.status_code == 400


def test_attachment_rejeita_conteudo_que_nao_bate_com_tipo(setup_data, override_get_session):
    """SEC-003: Content-Type declarado não basta — magic bytes precisam bater."""
    ws1, u1 = setup_data["ws1"], setup_data["u1"]
    headers = setup_data["headers1"]
    tx = _create_tx(ws1.id, u1.id, headers)
    url = f"/api/v1/workspaces/{ws1.id}/transactions/{tx['id']}/attachments"

    # HTML disfarçado de PNG
    resp = client.post(
        url,
        files={"file": ("falso.png", b"<html><script>alert(1)</script></html>", "image/png")},
        headers=headers,
    )
    assert resp.status_code == 400
    assert "não corresponde" in resp.json()["error"]["message"]

    # PDF verdadeiro passa
    resp = client.post(
        url,
        files={"file": ("nota.pdf", b"%PDF-1.7 conteudo", "application/pdf")},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text


def test_attachment_guarda_sha256(db_session, setup_data, override_get_session):
    import hashlib
    from app.models.attachment import Attachment

    ws1, u1 = setup_data["ws1"], setup_data["u1"]
    headers = setup_data["headers1"]
    tx = _create_tx(ws1.id, u1.id, headers)

    resp = client.post(
        f"/api/v1/workspaces/{ws1.id}/transactions/{tx['id']}/attachments",
        files={"file": ("recibo.png", PNG_BYTES, "image/png")},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    att = db_session.get(Attachment, resp.json()["id"])
    assert att.sha256 == hashlib.sha256(PNG_BYTES).hexdigest()


def test_attachment_respects_size_limit(setup_data, override_get_session, monkeypatch):
    ws1, u1 = setup_data["ws1"], setup_data["u1"]
    headers = setup_data["headers1"]
    tx = _create_tx(ws1.id, u1.id, headers)

    monkeypatch.setattr(settings, "UPLOAD_MAX_BYTES", 10)
    resp = client.post(
        f"/api/v1/workspaces/{ws1.id}/transactions/{tx['id']}/attachments",
        files={"file": ("grande.png", PNG_BYTES, "image/png")},
        headers=headers,
    )
    assert resp.status_code == 400
    assert "limite" in resp.json()["error"]["message"]


def test_attachment_isolated_by_workspace(setup_data, override_get_session):
    ws1, u1 = setup_data["ws1"], setup_data["u1"]
    headers1 = setup_data["headers1"]
    tx = _create_tx(ws1.id, u1.id, headers1)

    resp = client.post(
        f"/api/v1/workspaces/{ws1.id}/transactions/{tx['id']}/attachments",
        files={"file": ("recibo.png", PNG_BYTES, "image/png")},
        headers=headers1,
    )
    att_id = resp.json()["id"]

    # u2 (membro só do ws2) não alcança o anexo
    ws2 = setup_data["ws2"]
    resp = client.get(f"/api/v1/workspaces/{ws2.id}/attachments/{att_id}", headers=setup_data["headers2"])
    assert resp.status_code == 404


def test_excluir_despesa_libera_a_cota_dos_anexos(db_session, setup_data, override_get_session):
    """Anexo de despesa excluída não pode ficar ocupando a cota do workspace.

    A exclusão de despesa é SOFT e o anexo não tinha soft delete nem cascade: o
    recibo virava inalcançável pela UI (list/download passam por
    `_get_transaction_or_404`, que dá 404 na despesa apagada) e MESMO ASSIM
    continuava somando em `_ensure_quota` — espaço perdido para sempre, sem
    nenhuma tela por onde liberá-lo.
    """
    from app.models.attachment import Attachment
    from sqlmodel import select

    ws1, u1 = setup_data["ws1"], setup_data["u1"]
    headers = setup_data["headers1"]
    tx = _create_tx(ws1.id, u1.id, headers)

    resp = client.post(
        f"/api/v1/workspaces/{ws1.id}/transactions/{tx['id']}/attachments",
        files={"file": ("recibo.png", PNG_BYTES, "image/png")},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text

    resp = client.delete(f"/api/v1/workspaces/{ws1.id}/transactions/{tx['id']}", headers=headers)
    assert resp.status_code == 200, resp.text

    db_session.expire_all()
    restantes = db_session.exec(
        select(Attachment).where(Attachment.workspace_id == ws1.id)
    ).all()
    assert restantes == [], "anexo órfão continuou ocupando a cota do workspace"


def test_excluir_grupo_de_parcelas_libera_os_anexos(db_session, setup_data, override_get_session):
    from app.models.attachment import Attachment
    from app.models.credit_card import CreditCard
    from sqlmodel import select

    ws1, u1 = setup_data["ws1"], setup_data["u1"]
    headers = setup_data["headers1"]

    card = CreditCard(name="Cartão", limit=5000, closing_day=5, due_day=15, owner_user_id=u1.id)
    db_session.add(card)
    db_session.commit()
    db_session.refresh(card)

    tx = _create_tx(
        ws1.id, u1.id, headers,
        total_amount=300.0,
        payers=[{"user_id": u1.id, "amount": 300.0, "payment_method": "credit_card"}],
        credit_card_id=card.id,
        payment_method="credit_card",
        installments_count=3,
    )
    resp = client.post(
        f"/api/v1/workspaces/{ws1.id}/transactions/{tx['id']}/attachments",
        files={"file": ("nota.png", PNG_BYTES, "image/png")},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text

    resp = client.delete(
        f"/api/v1/workspaces/{ws1.id}/transactions/{tx['id']}/installment-group", headers=headers
    )
    assert resp.status_code == 200, resp.text

    db_session.expire_all()
    restantes = db_session.exec(
        select(Attachment).where(Attachment.workspace_id == ws1.id)
    ).all()
    assert restantes == []
