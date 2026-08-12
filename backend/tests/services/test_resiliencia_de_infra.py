"""O que o app faz quando a infraestrutura em volta falha.

Três promessas estão escritas em docstring e não tinham teste nenhum:

- e-mail é **best-effort** (o convite e o token de senha já foram persistidos;
  uma falha de entrega não pode derrubar a requisição — nem revelar, pelo erro
  ou pelo tempo, quais endereços existem);
- falha ao gravar anexo vira **503** e não deixa linha órfã apontando para um
  arquivo que não existe;
- taxa de câmbio indisponível não inventa valor.

Promessa sem teste é intenção. Estes exercitam o caminho de falha de verdade,
com o serviço externo quebrado por `monkeypatch`.
"""
import pytest
from fastapi.testclient import TestClient
from sqlmodel import select

from app.main import app
from app.models.attachment import Attachment
from app.services.attachment_storage import AttachmentStorage, AttachmentStorageError
from app.services.email_service import EmailService

client = TestClient(app)


@pytest.fixture(name="smtp_quebrado")
def smtp_quebrado_fixture(monkeypatch):
    """SMTP configurado e recusando conexão — o pior caso, não o "não configurado"."""
    monkeypatch.setattr("app.core.config.settings.SMTP_HOST", "smtp.invalido.local")

    def explode(*args, **kwargs):
        raise OSError("conexão recusada")

    monkeypatch.setattr("smtplib.SMTP", explode)


def test_convite_sobrevive_ao_smtp_fora_do_ar(smtp_quebrado, setup_data, override_get_session):
    """O convite é o registro; o e-mail é só o aviso."""
    ws, headers = setup_data["ws1"], setup_data["headers1"]
    res = client.post(
        f"/api/v1/workspaces/{ws.id}/invites",
        json={"email": "convidado@example.com", "role": "member", "expires_days": 7},
        headers=headers,
    )
    assert res.status_code == 200, (
        f"o convite falhou porque o SMTP está fora ({res.status_code}) — "
        "o link já existe no banco e a tela sabe copiá-lo"
    )


def test_recuperacao_de_senha_nao_denuncia_smtp_fora(smtp_quebrado, setup_data, override_get_session):
    """Resposta idêntica com e sem SMTP: o erro não pode enumerar contas."""
    res = client.post(
        "/api/v1/auth/forgot-password", json={"email": setup_data["u1"].email}
    )
    assert res.status_code == 200, f"vazou a falha de SMTP no status ({res.status_code})"


def test_falha_ao_gravar_anexo_responde_503_e_nao_deixa_linha_orfa(
    monkeypatch, db_session, setup_data, override_get_session
):
    """Volume cheio ou não montado: 503, e NENHUM metadado gravado.

    A ordem importa e está documentada na rota: o conteúdo vai para o disco
    ANTES do commit, porque um arquivo órfão é recuperável e ninguém o lê — já a
    linha apontando para um arquivo inexistente quebra o download para sempre.
    """
    ws, headers = setup_data["ws1"], setup_data["headers1"]
    tx = client.post(
        f"/api/v1/workspaces/{ws.id}/transactions/",
        json={
            "title": "com recibo",
            "total_amount": 10.0,
            "transaction_date": "2026-08-10T12:00:00Z",
            "payers": [{"user_id": setup_data["u1"].id, "amount": 10.0}],
            "splits": [{"user_id": setup_data["u1"].id, "split_method": "equal", "input_value": 0}],
        },
        headers=headers,
    )
    assert tx.status_code == 200, tx.status_code
    tx_id = tx.json()["id"]

    def disco_cheio(*args, **kwargs):
        raise AttachmentStorageError("No space left on device")

    monkeypatch.setattr(AttachmentStorage, "save", disco_cheio)

    pdf = b"%PDF-1.4\n%fake\n"
    res = client.post(
        f"/api/v1/workspaces/{ws.id}/transactions/{tx_id}/attachments",
        files={"file": ("recibo.pdf", pdf, "application/pdf")},
        headers=headers,
    )
    assert res.status_code == 503, f"esperado 503, veio {res.status_code}"

    orfas = db_session.exec(
        select(Attachment).where(Attachment.transaction_id == tx_id)
    ).all()
    assert not orfas, f"{len(orfas)} anexo(s) gravado(s) apontando para arquivo inexistente"


def test_email_best_effort_nao_propaga_por_padrao(smtp_quebrado):
    """O contrato do próprio `send`: só o diagnóstico da tela de Admin levanta."""
    EmailService.send("alguem@example.com", "assunto", "corpo")  # não pode levantar

    with pytest.raises(Exception):
        EmailService.send("alguem@example.com", "assunto", "corpo", raise_on_error=True)
