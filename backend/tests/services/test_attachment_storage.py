"""Conteúdo dos anexos fora do banco (ADR 0007).

O que precisa ser verdade, e por quê:

- O upload grava no ARMAZENAMENTO e a linha fica só com metadados + hash + chave
  (o dump do Postgres deixa de carregar recibos).
- Anexos legados, com bytes no banco, continuam servindo — a migração de schema
  não move conteúdo, então o fallback é o que evita janela de indisponibilidade.
- O armazenamento é endereçado por CONTEÚDO e dedupica: apagar um anexo não pode
  levar o arquivo de outro que aponta para a mesma chave.
- Objeto ausente no disco (volume não montado, restore parcial) responde 404
  explicável, não 500.
"""
import hashlib
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.core.config import settings
from app.main import app
from app.models.attachment import Attachment
from app.services.attachment_storage import AttachmentStorage

client = TestClient(app)

PNG = b"\x89PNG\r\n\x1a\n" + b"conteudo-do-recibo" * 4
OUTRO_PNG = b"\x89PNG\r\n\x1a\n" + b"outro-recibo" * 4


@pytest.fixture(name="tx")
def tx_fixture(setup_data, override_get_session):
    ws, u1, headers = setup_data["ws1"], setup_data["u1"], setup_data["headers1"]
    resp = client.post(
        f"/api/v1/workspaces/{ws.id}/transactions/",
        json={
            "title": "Mercado",
            "total_amount": 50.0,
            "transaction_date": "2026-07-18T12:00:00",
            "payers": [{"user_id": u1.id, "amount": 50.0}],
            "splits": [{"user_id": u1.id, "split_method": "equal", "input_value": 0}],
        },
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    return {"ws": ws, "headers": headers, "id": resp.json()["id"]}


def _upload(tx, conteudo=PNG, nome="recibo.png"):
    resp = client.post(
        f"/api/v1/workspaces/{tx['ws'].id}/transactions/{tx['id']}/attachments",
        files={"file": (nome, conteudo, "image/png")},
        headers=tx["headers"],
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_upload_grava_no_disco_e_nao_no_banco(db_session: Session, tx):
    att = _upload(tx)

    linha = db_session.get(Attachment, att["id"])
    assert linha.data is None, "os bytes continuaram no banco"
    assert linha.storage_key, "a linha ficou sem chave de armazenamento"
    assert linha.sha256 == hashlib.sha256(PNG).hexdigest()

    caminho = Path(settings.ATTACHMENT_STORAGE_DIR) / linha.storage_key
    assert caminho.is_file()
    assert caminho.read_bytes() == PNG
    # A chave isola por workspace e endereça pelo conteúdo
    assert linha.storage_key.startswith(f"{tx['ws'].id}/")
    assert linha.storage_key.endswith(linha.sha256)


def test_download_serve_do_disco(tx):
    att = _upload(tx)
    resp = client.get(
        f"/api/v1/workspaces/{tx['ws'].id}/attachments/{att['id']}", headers=tx["headers"]
    )
    assert resp.status_code == 200
    assert resp.content == PNG


def test_download_de_anexo_legado_ainda_funciona(db_session: Session, tx):
    """Linha anterior à migração: bytes no banco, sem storage_key."""
    legado = Attachment(
        workspace_id=tx["ws"].id,
        transaction_id=tx["id"],
        filename="antigo.png",
        content_type="image/png",
        size_bytes=len(PNG),
        sha256=hashlib.sha256(PNG).hexdigest(),
        storage_key=None,
        data=PNG,
    )
    db_session.add(legado)
    db_session.commit()
    db_session.refresh(legado)

    resp = client.get(
        f"/api/v1/workspaces/{tx['ws'].id}/attachments/{legado.id}", headers=tx["headers"]
    )
    assert resp.status_code == 200
    assert resp.content == PNG


def test_objeto_ausente_no_disco_responde_404_explicavel(db_session: Session, tx):
    """Volume não montado / restore parcial não pode virar 500 sem explicação."""
    att = _upload(tx)
    linha = db_session.get(Attachment, att["id"])
    (Path(settings.ATTACHMENT_STORAGE_DIR) / linha.storage_key).unlink()

    resp = client.get(
        f"/api/v1/workspaces/{tx['ws'].id}/attachments/{att['id']}", headers=tx["headers"]
    )
    assert resp.status_code == 404
    assert "indisponível" in resp.json()["error"]["message"]


def test_excluir_anexo_remove_o_arquivo(db_session: Session, tx):
    att = _upload(tx)
    linha = db_session.get(Attachment, att["id"])
    caminho = Path(settings.ATTACHMENT_STORAGE_DIR) / linha.storage_key
    assert caminho.is_file()

    resp = client.delete(
        f"/api/v1/workspaces/{tx['ws'].id}/attachments/{att['id']}", headers=tx["headers"]
    )
    assert resp.status_code == 200
    assert not caminho.exists(), "o arquivo ficou órfão no armazenamento"


def test_dedup_nao_apaga_o_arquivo_de_quem_ainda_usa(db_session: Session, tx):
    """Mesmo comprovante enviado duas vezes compartilha o objeto: apagar um não
    pode deixar o outro — ainda listado na UI — sem conteúdo."""
    primeiro = _upload(tx, PNG, "recibo.png")
    segundo = _upload(tx, PNG, "copia.png")

    a = db_session.get(Attachment, primeiro["id"])
    b = db_session.get(Attachment, segundo["id"])
    assert a.storage_key == b.storage_key, "o armazenamento não dedupicou"

    caminho = Path(settings.ATTACHMENT_STORAGE_DIR) / a.storage_key
    client.delete(
        f"/api/v1/workspaces/{tx['ws'].id}/attachments/{primeiro['id']}", headers=tx["headers"]
    )
    assert caminho.is_file(), "o arquivo do segundo anexo foi levado junto"

    resp = client.get(
        f"/api/v1/workspaces/{tx['ws'].id}/attachments/{segundo['id']}", headers=tx["headers"]
    )
    assert resp.status_code == 200
    assert resp.content == PNG

    # Só quando a última referência sai é que o objeto some
    client.delete(
        f"/api/v1/workspaces/{tx['ws'].id}/attachments/{segundo['id']}", headers=tx["headers"]
    )
    assert not caminho.exists()


def test_excluir_a_despesa_remove_os_arquivos(db_session: Session, tx):
    a = _upload(tx, PNG, "a.png")
    b = _upload(tx, OUTRO_PNG, "b.png")
    caminhos = [
        Path(settings.ATTACHMENT_STORAGE_DIR) / db_session.get(Attachment, x["id"]).storage_key
        for x in (a, b)
    ]

    resp = client.delete(
        f"/api/v1/workspaces/{tx['ws'].id}/transactions/{tx['id']}", headers=tx["headers"]
    )
    assert resp.status_code == 200, resp.text

    assert db_session.exec(select(Attachment)).all() == []
    for caminho in caminhos:
        assert not caminho.exists(), "o arquivo ficou ocupando o volume"


def test_chave_fora_da_raiz_e_recusada():
    """A chave é gerada aqui (int + hex), mas nada impede uma vinda do banco:
    ler `../../etc/passwd` tem que ser impossível, não improvável."""
    assert AttachmentStorage.read("../../../etc/passwd") is None
    assert AttachmentStorage.delete("../../../etc/passwd") is False


def test_gravacao_e_idempotente_por_conteudo():
    primeira = AttachmentStorage.save(1, hashlib.sha256(PNG).hexdigest(), PNG)
    segunda = AttachmentStorage.save(1, hashlib.sha256(PNG).hexdigest(), PNG)
    assert primeira == segunda
    assert AttachmentStorage.read(primeira) == PNG


def test_diretorio_sem_permissao_responde_503_e_nao_500(monkeypatch, tx):
    """Raiz não gravável é o modo de falha REAL em produção: volume nomeado nasce
    root e o container roda como appuser. O erro acontece no mkdir — que precisa
    estar dentro do try, senão sobe como OSError cru e o usuário vê 500 em vez da
    mensagem que a rota já sabe dar."""
    def _sem_permissao(*args, **kwargs):
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(Path, "mkdir", _sem_permissao)

    resp = client.post(
        f"/api/v1/workspaces/{tx['ws'].id}/transactions/{tx['id']}/attachments",
        files={"file": ("recibo.png", PNG, "image/png")},
        headers=tx["headers"],
    )
    assert resp.status_code == 503, resp.text
    assert "armazenar o anexo" in resp.json()["error"]["message"]
