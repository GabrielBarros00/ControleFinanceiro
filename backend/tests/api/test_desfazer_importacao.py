"""Desfazer importação (ADR 0036).

A importação cria dezenas de lançamentos de uma vez; importar no espaço errado ou
com o mapeamento de colunas trocado custava excluir um a um. Desfazer exclui o
que o lote criou e ainda existe, com as MESMAS regras da exclusão (permissão,
trava de paga, anexos), tudo ou nada — e depois dele o arquivo pode ser
importado de novo.
"""
from fastapi.testclient import TestClient
from sqlmodel import select

from app.main import app
from app.models.attachment import Attachment
from app.models.transaction import Transaction, TransactionStatus
from app.models.workspace import WorkspaceMembership, WorkspaceRole

client = TestClient(app)

LINHAS = [
    {"line": 2, "title": "Mercado", "total_amount": 50.0, "transaction_date": "2026-03-01T00:00:00"},
    {"line": 3, "title": "Farmácia", "total_amount": 30.0, "transaction_date": "2026-03-02T00:00:00"},
    {"line": 4, "title": "Padaria", "total_amount": 12.5, "transaction_date": "2026-03-03T00:00:00", "decision": "ignore"},
]


def _commit(ws_id, headers, rows=LINHAS, filename="extrato.csv"):
    r = client.post(f"/api/v1/workspaces/{ws_id}/imports/commit", json={"filename": filename, "rows": rows}, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def _desfazer(ws_id, batch_id, headers, **corpo):
    return client.post(f"/api/v1/workspaces/{ws_id}/imports/{batch_id}/undo", json=corpo, headers=headers)


def _vivos(db, ws_id):
    return sorted(t.title for t in db.exec(
        select(Transaction).where(Transaction.workspace_id == ws_id, Transaction.deleted_at.is_(None))
    ).all())


def test_lista_as_importacoes_com_quanto_ainda_existe(db_session, setup_data, override_get_session):
    ws, h = setup_data["ws1"], setup_data["headers1"]
    primeiro = _commit(ws.id, h, filename="marco.csv")
    segundo = _commit(ws.id, h, rows=[{"title": "Luz", "total_amount": 90.0, "transaction_date": "2026-04-01T00:00:00"}], filename="abril.csv")

    lista = client.get(f"/api/v1/workspaces/{ws.id}/imports", headers=h).json()
    assert [b["id"] for b in lista] == [segundo["batch_id"], primeiro["batch_id"]]
    marco = lista[1]
    assert (marco["filename"], marco["total_rows"], marco["imported"], marco["ignored"], marco["live_transactions"], marco["attachments"]) == (
        "marco.csv", 3, 2, 1, 2, 0,
    )
    # A mesma coleção com barra no fim (a armadilha do 307 perde o cookie).
    assert client.get(f"/api/v1/workspaces/{ws.id}/imports/", headers=h).status_code == 200


def test_detalhe_mostra_o_desfecho_de_cada_linha(db_session, setup_data, override_get_session):
    ws, h = setup_data["ws1"], setup_data["headers1"]
    lote = _commit(ws.id, h)["batch_id"]
    detalhe = client.get(f"/api/v1/workspaces/{ws.id}/imports/{lote}", headers=h).json()
    assert [(r["line"], r["status"], r["transaction_alive"]) for r in detalhe["rows"]] == [
        (2, "imported", True), (3, "imported", True), (4, "ignored", False),
    ]


def test_desfazer_exclui_o_que_o_lote_criou_e_o_arquivo_volta_a_importar(db_session, setup_data, override_get_session):
    ws, h = setup_data["ws1"], setup_data["headers1"]
    lote = _commit(ws.id, h)["batch_id"]
    assert _vivos(db_session, ws.id) == ["Farmácia", "Mercado"]

    r = _desfazer(ws.id, lote, h)
    assert r.status_code == 200, r.text
    assert r.json() == {"batch_id": lote, "deleted": 2, "attachments_removed": 0}
    assert _vivos(db_session, ws.id) == []
    resumo = client.get(f"/api/v1/workspaces/{ws.id}/imports", headers=h).json()[0]
    assert (resumo["imported"], resumo["live_transactions"]) == (2, 0)

    # Depois de desfeita, o MESMO arquivo importa de novo (antes a linha ficava
    # "já importada" para sempre, embora a prévia a mostrasse como nova).
    de_novo = _commit(ws.id, h)
    assert (de_novo["imported"], de_novo["duplicate"]) == (2, 0)
    assert _vivos(db_session, ws.id) == ["Farmácia", "Mercado"]


def test_desfazer_de_novo_nao_faz_nada(db_session, setup_data, override_get_session):
    ws, h = setup_data["ws1"], setup_data["headers1"]
    lote = _commit(ws.id, h)["batch_id"]
    assert _desfazer(ws.id, lote, h).json()["deleted"] == 2
    segundo = _desfazer(ws.id, lote, h)
    assert segundo.status_code == 200 and segundo.json()["deleted"] == 0


def test_reimportar_com_o_lancamento_vivo_continua_sem_duplicar(db_session, setup_data, override_get_session):
    """A idempotência do ADR 0008 continua: só o que foi excluído volta."""
    ws, h = setup_data["ws1"], setup_data["headers1"]
    _commit(ws.id, h)
    mercado = db_session.exec(select(Transaction).where(Transaction.title == "Mercado")).one()
    r = client.delete(f"/api/v1/workspaces/{ws.id}/transactions/{mercado.id}", headers=h)
    assert r.status_code == 200, r.text

    de_novo = _commit(ws.id, h)
    assert (de_novo["imported"], de_novo["duplicate"]) == (1, 1)
    assert _vivos(db_session, ws.id) == ["Farmácia", "Mercado"]


def test_lancamento_pago_barra_o_desfazer_inteiro(db_session, setup_data, override_get_session):
    ws, h = setup_data["ws1"], setup_data["headers1"]
    lote = _commit(ws.id, h)["batch_id"]
    farmacia = db_session.exec(select(Transaction).where(Transaction.title == "Farmácia")).one()
    farmacia.status = TransactionStatus.paid
    db_session.add(farmacia)
    db_session.commit()

    r = _desfazer(ws.id, lote, h)
    assert r.status_code == 409, r.text
    # A rota só faz o commit no fim (ADR 0010); com o erro, a sessão da requisição
    # fecha sem commit. Na suíte o teste e a rota dividem a MESMA sessão, então o
    # fim da requisição é reproduzido aqui — sem isso o Mercado, excluído antes
    # de a Farmácia recusar, pareceria ter saído.
    db_session.rollback()
    # Tudo ou nada: o Mercado, que podia sair, também ficou.
    assert _vivos(db_session, ws.id) == ["Farmácia", "Mercado"]


def test_com_anexo_so_desfaz_com_confirmacao(db_session, setup_data, override_get_session):
    ws, h = setup_data["ws1"], setup_data["headers1"]
    lote = _commit(ws.id, h)["batch_id"]
    mercado = db_session.exec(select(Transaction).where(Transaction.title == "Mercado")).one()
    db_session.add(Attachment(
        workspace_id=ws.id, transaction_id=mercado.id, filename="nota.pdf", content_type="application/pdf",
        size_bytes=1024, storage_key="k/nota.pdf", uploaded_by_user_id=setup_data["u1"].id,
    ))
    db_session.commit()
    assert client.get(f"/api/v1/workspaces/{ws.id}/imports", headers=h).json()[0]["attachments"] == 1

    recusa = _desfazer(ws.id, lote, h)
    assert recusa.status_code == 409
    assert "1 recibo" in recusa.json()["error"]["message"]
    db_session.rollback()  # o fim da requisição sem commit (ver o teste da paga)
    assert _vivos(db_session, ws.id) == ["Farmácia", "Mercado"]

    ok = _desfazer(ws.id, lote, h, confirm_attachments=True)
    assert ok.status_code == 200, ok.text
    assert ok.json() == {"batch_id": lote, "deleted": 2, "attachments_removed": 1}


def test_a_importacao_de_outra_pessoa_nao_aparece_nem_se_desfaz(db_session, setup_data, override_get_session):
    ws, h1, h2 = setup_data["ws1"], setup_data["headers1"], setup_data["headers2"]
    db_session.add(WorkspaceMembership(workspace_id=ws.id, user_id=setup_data["u2"].id, role=WorkspaceRole.member))
    db_session.commit()
    lote = _commit(ws.id, h1)["batch_id"]

    assert client.get(f"/api/v1/workspaces/{ws.id}/imports", headers=h2).json() == []
    assert client.get(f"/api/v1/workspaces/{ws.id}/imports/{lote}", headers=h2).status_code == 404
    assert _desfazer(ws.id, lote, h2).status_code == 404
    db_session.rollback()
    assert _vivos(db_session, ws.id) == ["Farmácia", "Mercado"]


def test_importacao_de_outro_espaco_responde_404(db_session, setup_data, override_get_session):
    ws1, ws2, h1, h2 = setup_data["ws1"], setup_data["ws2"], setup_data["headers1"], setup_data["headers2"]
    lote = _commit(ws2.id, h2)["batch_id"]
    # Pelo espaço de outra pessoa: nem é membro.
    assert client.get(f"/api/v1/workspaces/{ws2.id}/imports/{lote}", headers=h1).status_code in (403, 404)
    # Pelo próprio espaço, com o id de um lote alheio.
    assert client.get(f"/api/v1/workspaces/{ws1.id}/imports/{lote}", headers=h1).status_code == 404
    assert _desfazer(ws1.id, lote, h1).status_code == 404
