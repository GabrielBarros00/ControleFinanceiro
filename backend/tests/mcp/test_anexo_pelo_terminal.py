"""Anexar arquivo pelo terminal: `attachments_upload_link` + `POST /api/v1/mcp/uploads`.

O arquivo não passa pela conversa. A tool emite um link de uso único (`cfm_up_…`,
10 minutos, amarrado ao usuário, à concessão e ao lançamento), e o agente de
terminal manda o arquivo com `curl`. A rota confere tudo de novo NA HORA e grava
pelo MESMO comando da tela: tipos, conteúdo real, cota, auditoria "via IA".
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlmodel import select

from app.models.attachment import Attachment
from app.models.audit import AuditLog
from app.models.mcp import McpConfirmation
from app.models.oauth import OAuthGrant
from app.models.workspace import WorkspaceMembership, WorkspaceRole
from app.services.oauth import scopes as escopos
from tests.mcp.conftest import call_tool, err, issue_token, ok
from tests.mcp.scenario import cria_despesa, monta

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


@pytest.fixture
def c(db_session, mcp_client):
    return monta(db_session, mcp_client)


def _link(mcp_client, c, token=None, **extra) -> dict:
    tx = cria_despesa(mcp_client, c.alice, c.casa, title="Mercado", amount="80.00", day=c.hoje)
    return ok(call_tool(mcp_client, token or c.token, "attachments_upload_link", {"transaction_id": tx["id"], **extra}))


def _envia(mcp_client, autorizacao: str | None, conteudo=PNG, tipo="image/png", nome="recibo.png"):
    cabecalhos = {"Authorization": autorizacao} if autorizacao else {}
    return mcp_client.post("/api/v1/mcp/uploads", headers=cabecalhos, files={"file": (nome, conteudo, tipo)})


def test_do_link_ao_anexo(mcp_client, db_session, c):
    link = _link(mcp_client, c, file_path=r"C:\Users\ana\Downloads\recibo.png")
    # O token vai no cabeçalho, nunca na URL (a URL fica em log de app, nginx e proxy).
    assert link["upload_url"].endswith("/api/v1/mcp/uploads") and "cfm_up_" not in link["upload_url"]
    assert link["authorization"].startswith("Bearer cfm_up_")
    assert "curl" in link["command"] and link["authorization"] in link["command"]
    assert "recibo.png" in link["command"] and "image/png" in link["accepted_types"]

    r = _envia(mcp_client, link["authorization"])
    assert r.status_code == 200, r.text
    corpo = r.json()
    assert corpo["transaction_id"] == link["transaction_id"] and corpo["replayed"] is False
    anexo = db_session.get(Attachment, corpo["attachment_id"])
    assert anexo.uploaded_by_user_id == c.alice.id and anexo.size_bytes == len(PNG)
    # "via IA" na auditoria, como qualquer escrita do agente.
    trilha = db_session.exec(
        select(AuditLog).where(AuditLog.resource_type == "Attachment", AuditLog.resource_id == anexo.id)
    ).all()
    assert trilha and all(t.origin == "mcp:Cliente de teste" for t in trilha)
    tx = ok(call_tool(mcp_client, c.token, "transactions_get", {"transaction_id": link["transaction_id"]}))
    assert tx["transaction"]["attachments"] == 1


def test_reenvio_do_mesmo_link_nao_anexa_de_novo(mcp_client, db_session, c):
    link = _link(mcp_client, c)
    primeiro = _envia(mcp_client, link["authorization"]).json()
    de_novo = _envia(mcp_client, link["authorization"])
    assert de_novo.status_code == 200 and de_novo.json()["replayed"] is True
    assert de_novo.json()["attachment_id"] == primeiro["attachment_id"]
    total = db_session.exec(select(Attachment).where(Attachment.transaction_id == link["transaction_id"])).all()
    assert len(total) == 1


def test_arquivo_recusado_nao_gasta_o_link(mcp_client, db_session, c):
    link = _link(mcp_client, c)
    recusado = _envia(mcp_client, link["authorization"], conteudo=b"<html>oi</html>", tipo="text/html", nome="x.html")
    assert recusado.status_code == 400
    disfarcado = _envia(mcp_client, link["authorization"], conteudo=b"%PDF", tipo="image/png")
    assert disfarcado.status_code == 400  # o conteúdo não é PNG
    assert _envia(mcp_client, link["authorization"]).status_code == 200


@pytest.mark.parametrize("autorizacao", [
    None, "Bearer", "Bearer cfm_up_inventado", "Bearer cfm_cf_outro_tipo", "Basic cfm_up_x",
])
def test_sem_token_valido_a_rota_recusa(mcp_client, db_session, c, autorizacao):
    r = _envia(mcp_client, autorizacao)
    assert r.status_code == 401
    assert "Link de envio inválido ou expirado" in r.json()["error"]["message"]
    assert db_session.exec(select(Attachment)).all() == []


def test_registro_de_outra_acao_nao_serve_nem_com_o_prefixo_certo(mcp_client, db_session, c):
    # O prefixo `cfm_up_` já barra o token da prévia de massa (`cfm_cf_`). Esta é a
    # defesa de trás: um registro que não é de envio não autoriza envio.
    link = _link(mcp_client, c)
    registro = db_session.exec(select(McpConfirmation).where(McpConfirmation.action == "attachment_upload")).one()
    registro.action = "delete"
    db_session.add(registro)
    db_session.commit()
    assert _envia(mcp_client, link["authorization"]).status_code == 401
    assert db_session.exec(select(Attachment)).all() == []


def test_link_expirado_ou_de_conexao_revogada_nao_serve(mcp_client, db_session, c):
    expirado = _link(mcp_client, c)
    registro = db_session.exec(select(McpConfirmation).where(McpConfirmation.action == "attachment_upload")).one()
    registro.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    db_session.add(registro)
    db_session.commit()
    assert _envia(mcp_client, expirado["authorization"]).status_code == 401

    revogado = _link(mcp_client, c)
    for concessao in db_session.exec(select(OAuthGrant)).all():
        concessao.revoked_at = datetime.now(UTC)
        db_session.add(concessao)
    db_session.commit()
    assert _envia(mcp_client, revogado["authorization"]).status_code == 401


def test_papel_rebaixado_depois_do_link_nao_anexa(mcp_client, db_session, c):
    link = _link(mcp_client, c)
    vinculo = db_session.exec(
        select(WorkspaceMembership).where(WorkspaceMembership.workspace_id == c.casa.id,
                                          WorkspaceMembership.user_id == c.alice.id)
    ).one()
    vinculo.role = WorkspaceRole.viewer
    db_session.add(vinculo)
    db_session.commit()
    assert _envia(mcp_client, link["authorization"]).status_code == 403


def test_sem_escopo_de_escrita_nem_link(mcp_client, db_session, c):
    so_leitura = issue_token(db_session, c.alice, [escopos.FINANCE_READ])
    tx = cria_despesa(mcp_client, c.alice, c.casa, title="Mercado", amount="80.00", day=c.hoje)
    erro = err(call_tool(mcp_client, so_leitura, "attachments_upload_link", {"transaction_id": tx["id"]}))
    assert erro["code"] == "PERMISSION_DENIED"


def test_cota_do_espaco_vale_no_envio_pelo_terminal(mcp_client, db_session, c, monkeypatch):
    from app.services import app_settings

    original = app_settings.get
    monkeypatch.setattr(app_settings, "get", lambda s, k: 10 if k == "attachment_quota_bytes" else original(s, k))
    link = _link(mcp_client, c)
    r = _envia(mcp_client, link["authorization"])
    assert r.status_code == 413 and "Cota de anexos" in r.json()["error"]["message"]
