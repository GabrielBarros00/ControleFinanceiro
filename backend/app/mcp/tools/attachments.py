"""`attachments_upload_link`: anexar um arquivo do computador pelo terminal.

O arquivo não passa pela conversa: a tool devolve um link de uso único e o
comando `curl` que o manda do disco direto para o app (ver `app/mcp/uploads.py`).
Serve aos agentes que têm terminal — Claude Code, Codex, Gemini CLI. Nos apps de
chat na web não há como executar o comando; lá o anexo se envia pela tela.
"""
from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field

from app.core.config import settings
from app.domain.dates import to_local
from app.mcp import confirmation, uploads
from app.mcp.registry import ToolCall, ToolInput, ToolOutput, tool
from app.mcp.tools.transactions import visible_transaction
from app.mcp.writes import membership_for_write
from app.services import app_settings
from app.services.commands.attachments import ALLOWED_CONTENT_TYPES
from app.services.oauth import scopes as escopos
from app.services.oauth.crypto import UPLOAD_PREFIX


class UploadLinkIn(ToolInput):
    transaction_id: int = Field(ge=1)
    file_path: Optional[str] = Field(
        None, max_length=500,
        description="Caminho do arquivo no computador do usuário, só para montar o comando pronto.",
    )


class UploadLinkOut(BaseModel):
    transaction_id: int
    upload_url: str
    authorization: str = Field(description="Cabeçalho `Authorization` do envio. Vale UMA vez, por 10 minutos.")
    form_field: str = Field(description="Campo multipart do arquivo.")
    expires_at: datetime
    max_bytes: int
    accepted_types: List[str]
    command: str = Field(description="Comando pronto (curl). No PowerShell do Windows, use `curl.exe`.")


def _comando(url: str, token: str, caminho: Optional[str]) -> str:
    arquivo = (caminho or "<caminho-do-arquivo>").replace('"', "")
    return f'curl -sS -H "Authorization: Bearer {token}" -F "file=@{arquivo}" "{url}"'


@tool(
    name="attachments_upload_link",
    title="Link para anexar arquivo",
    description=(
        "Gera um link de envio de USO ÚNICO (10 minutos) para anexar a um lançamento um arquivo "
        "que está no computador do usuário (recibo, nota fiscal, comprovante: JPG, PNG, WebP ou "
        "PDF). O arquivo vai do terminal direto para o app, sem passar pela conversa. Devolve o "
        "comando `curl` pronto; rode-o e confira a resposta (`attachment_id`).\n"
        "Use quando: você roda num terminal com acesso aos arquivos do usuário (Claude Code, Codex, "
        "Gemini CLI) e ele pede para anexar um arquivo a um lançamento.\n"
        "Não use quando: não houver como executar comandos (ChatGPT e Claude na web): diga que o "
        "anexo se envia pela tela do lançamento no app. O link não lê nem apaga anexos."
    ),
    input_model=UploadLinkIn,
    output_model=UploadLinkOut,
    scope=escopos.TRANSACTIONS_WRITE,
    kind="write",
    read_only=False,
    destructive=False,
    idempotent=True,
    cost=3,
    invoking="Gerando o link de envio…",
    invoked="Link de envio pronto",
)
def attachments_upload_link(call: ToolCall) -> ToolOutput:
    a: UploadLinkIn = call.args
    tx = visible_transaction(call, a.transaction_id)
    # Mesmo portão do envio pela tela: membro do espaço, lançamento visível.
    membership_for_write(call, tx.workspace_id)
    token, expira = confirmation.issue(
        call, uploads.ACAO, [tx.id], {"workspace_id": tx.workspace_id}, prefixo=UPLOAD_PREFIX
    )
    url = f"{settings.oauth_issuer}{uploads.CAMINHO}"
    saida = UploadLinkOut(
        transaction_id=tx.id,
        upload_url=url,
        authorization=f"Bearer {token}",
        form_field="file",
        expires_at=expira,
        max_bytes=app_settings.get(call.session, "upload_max_bytes"),
        accepted_types=sorted(ALLOWED_CONTENT_TYPES),
        command=_comando(url, token, a.file_path),
    )
    return ToolOutput(
        structured=saida,
        summary=(
            f"Link de envio para \"{tx.title}\" pronto (uso único, vale até "
            f"{to_local(expira).strftime('%H:%M')}). Rode o comando `command` com o caminho do arquivo."
        ),
        entity_type="transaction",
        entity_ids=[tx.id],
        space_id=tx.workspace_id,
    )
