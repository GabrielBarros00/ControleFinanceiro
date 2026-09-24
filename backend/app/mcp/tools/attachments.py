"""`attachments_upload_link`: anexar um arquivo do computador pelo terminal.

O arquivo não passa pela conversa: a tool devolve um link de uso único e o
comando `curl` que o manda do disco direto para o app (ver `app/mcp/uploads.py`).
Serve aos agentes que têm terminal — Claude Code, Codex, Gemini CLI. Nos apps de
chat na web não há como executar o comando; lá o anexo se envia pela tela.
"""
from __future__ import annotations

import base64
from datetime import datetime
from typing import List, Optional

from mcp_types import BlobResourceContents, EmbeddedResource, ImageContent
from pydantic import BaseModel, ConfigDict, Field

from app.core.config import settings
from app.domain.dates import local_day, to_local
from app.mcp import confirmation, uploads
from app.mcp.errors import ErrorCode, McpToolError
from app.mcp.ui import WIDGET_URI as WIDGET
from app.mcp.registry import ToolCall, ToolInput, ToolOutput, tool
from app.mcp.schemas import AttachmentOut, Ref
from app.mcp.tools.transactions import visible_transaction
from app.mcp.writes import membership_for_write
from app.services import app_settings
from app.models.attachment import Attachment
from app.models.transaction import Transaction
from app.models.user import User
from app.services.attachment_storage import free_keys
from app.services.commands import attachments as cmd_anexos
from app.services.commands.attachments import ALLOWED_CONTENT_TYPES, read_attachment_bytes
from app.services.remote_file import RemoteFileError, fetch_file
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


# --- attachments_get ---------------------------------------------------------------------

def _anexo_visivel(call: ToolCall, attachment_id: int) -> tuple[Attachment, Transaction]:
    """O anexo, se o LANÇAMENTO dele é visível para esta pessoa (ADR 0018); senão NOT_FOUND."""
    anexo = call.session.get(Attachment, attachment_id)
    if anexo is None:
        raise McpToolError(ErrorCode.NOT_FOUND, "Anexo não encontrado.", details={"attachment_id": attachment_id})
    try:
        tx = visible_transaction(call, anexo.transaction_id)
    except McpToolError:
        raise McpToolError(ErrorCode.NOT_FOUND, "Anexo não encontrado.", details={"attachment_id": attachment_id})
    if tx.workspace_id != anexo.workspace_id:
        raise McpToolError(ErrorCode.NOT_FOUND, "Anexo não encontrado.", details={"attachment_id": attachment_id})
    return anexo, tx


def _meta_do_anexo(call: ToolCall, a: Attachment) -> AttachmentOut:
    autor = call.session.get(User, a.uploaded_by_user_id) if a.uploaded_by_user_id else None
    return AttachmentOut(
        id=a.id, filename=a.filename, content_type=a.content_type, size_bytes=a.size_bytes,
        uploaded_by=Ref(id=autor.id, name=autor.name) if autor else None,
        uploaded_on=local_day(a.created_at) if a.created_at else None,
    )


class AttachmentGetIn(ToolInput):
    attachment_id: int = Field(ge=1, description="O id do anexo (em `files` de transactions_get).")


class AttachmentGetOut(BaseModel):
    attachment: AttachmentOut
    transaction_id: int
    delivered: bool = Field(description="true = o conteúdo (imagem/PDF) veio junto nesta resposta.")
    note: Optional[str] = None


@tool(
    name="attachments_get",
    title="Ler anexo (recibo)",
    description=(
        "Entrega o CONTEÚDO de um anexo de lançamento (foto do recibo, nota fiscal em PDF) para você "
        "ler — por exemplo, para extrair os itens da nota e registrá-los com transactions_update "
        "(`items`). Arquivos grandes demais voltam só com os dados e o link do app.\n"
        "Use quando: o usuário pedir para ler, conferir ou detalhar o recibo de um lançamento (pegue "
        "o id em `files` de transactions_get).\n"
        "Não use quando: só precisar saber se há anexo (transactions_get já diz)."
    ),
    input_model=AttachmentGetIn,
    output_model=AttachmentGetOut,
    scope=escopos.FINANCE_READ,
    kind="read",
    read_only=True,
    destructive=False,
    idempotent=True,
    cost=3,
    invoking="Abrindo o anexo…",
    invoked="Anexo aberto",
    app_callable=True,
)
def attachments_get(call: ToolCall) -> ToolOutput:
    a: AttachmentGetIn = call.args
    anexo, tx = _anexo_visivel(call, a.attachment_id)
    dados = _meta_do_anexo(call, anexo)
    extra: list = []
    nota = None
    if anexo.size_bytes > settings.MCP_ATTACHMENT_TO_MODEL_MAX_BYTES:
        nota = "Arquivo grande demais para entregar na conversa; abra no app."
    else:
        conteudo = read_attachment_bytes(anexo)
        if conteudo is None:
            nota = "O conteúdo deste anexo não está disponível no armazenamento."
        else:
            b64 = base64.b64encode(conteudo).decode("ascii")
            if anexo.content_type.startswith("image/"):
                extra.append(ImageContent(type="image", data=b64, mime_type=anexo.content_type))
            else:
                extra.append(EmbeddedResource(type="resource", resource=BlobResourceContents(
                    uri=f"attachment://controle-financeiro/{anexo.id}/{anexo.filename}",
                    mime_type=anexo.content_type, blob=b64,
                )))
    saida = AttachmentGetOut(attachment=dados, transaction_id=tx.id, delivered=bool(extra), note=nota)
    return ToolOutput(
        structured=saida,
        summary=(
            f"Anexo \"{anexo.filename}\" do lançamento \"{tx.title}\""
            + (" (conteúdo a seguir)." if extra else f": {nota}")
        ),
        entity_type="attachment",
        entity_ids=[anexo.id],
        space_id=tx.workspace_id,
        extra_content=extra,
    )


# --- attachments_delete ----------------------------------------------------------------------

class AttachmentDeleteIn(ToolInput):
    attachment_id: int = Field(ge=1)


class AttachmentDeleteOut(BaseModel):
    deleted: AttachmentOut
    transaction_id: int


@tool(
    name="attachments_delete",
    title="Excluir anexo",
    description=(
        "Apaga um anexo (recibo) de um lançamento, para sempre — não há como desfazer. Membro apaga os "
        "próprios anexos; administrador do espaço, qualquer um.\n"
        "Use quando: o usuário pedir para remover um recibo anexado por engano (confirme qual, pelo "
        "nome do arquivo).\n"
        "Não use quando: quiser excluir o lançamento (transactions_delete)."
    ),
    input_model=AttachmentDeleteIn,
    output_model=AttachmentDeleteOut,
    scope=escopos.TRANSACTIONS_WRITE,
    kind="destructive",
    read_only=False,
    destructive=True,
    idempotent=True,
    cost=3,
    invoking="Apagando o anexo…",
    invoked="Anexo apagado",
    ui=WIDGET,
    app_callable=True,
    meta={"openai/widgetDescription": "O componente mostra o resultado com as ações possíveis (desfazer, editar). Confirme em uma frase, sem repetir os números."},
)
def attachments_delete(call: ToolCall) -> ToolOutput:
    a: AttachmentDeleteIn = call.args
    anexo, tx = _anexo_visivel(call, a.attachment_id)
    membership = membership_for_write(call, tx.workspace_id)
    dados = _meta_do_anexo(call, anexo)
    liberar = cmd_anexos.delete_attachment(call.session, tx.workspace_id, anexo.id, membership)
    return ToolOutput(
        structured=AttachmentDeleteOut(deleted=dados, transaction_id=tx.id),
        summary=f"Anexo \"{dados.filename}\" apagado do lançamento \"{tx.title}\".",
        entity_type="attachment",
        entity_ids=[dados.id],
        space_id=tx.workspace_id,
        after_commit=[lambda: free_keys(liberar)] if liberar else [],
    )


# --- attachments_add (arquivo posto na conversa do ChatGPT) --------------------------------

class ChatFile(BaseModel):
    """O arquivo como o app de chat o entrega (`openai/fileParams`)."""

    model_config = ConfigDict(extra="forbid")

    download_url: str = Field(max_length=4096, description="URL temporária entregue pelo app de chat.")
    file_id: str = Field(max_length=200)
    mime_type: Optional[str] = Field(None, max_length=100)
    file_name: Optional[str] = Field(None, max_length=255)


class AttachmentAddIn(ToolInput):
    transaction_id: int = Field(ge=1)
    file: ChatFile


class AttachmentAddOut(BaseModel):
    attachment: AttachmentOut
    transaction_id: int


@tool(
    name="attachments_add",
    title="Anexar arquivo da conversa",
    description=(
        "Anexa a um lançamento um arquivo que o usuário colocou NESTA conversa (foto do recibo, nota "
        "em PDF) — no ChatGPT, que entrega o arquivo à tool. JPG, PNG, WebP ou PDF.\n"
        "Use quando: o usuário mandar o recibo na conversa e pedir para anexá-lo a um lançamento.\n"
        "Não use quando: o arquivo estiver no computador do usuário e você rodar num terminal "
        "(attachments_upload_link); ou o app de chat não entregar arquivos a tools — aí o anexo é pela "
        "tela do lançamento."
    ),
    input_model=AttachmentAddIn,
    output_model=AttachmentAddOut,
    scope=escopos.TRANSACTIONS_WRITE,
    kind="write",
    read_only=False,
    destructive=False,
    idempotent=True,
    cost=3,
    invoking="Anexando…",
    invoked="Anexado",
    meta={"openai/widgetDescription": "O componente mostra o resultado com as ações possíveis (desfazer, editar). Confirme em uma frase, sem repetir os números.", "openai/fileParams": ["file"]},
    ui=WIDGET,
    app_callable=True,
)
def attachments_add(call: ToolCall) -> ToolOutput:
    a: AttachmentAddIn = call.args
    tx = visible_transaction(call, a.transaction_id)
    membership_for_write(call, tx.workspace_id)
    try:
        conteudo, tipo_do_servidor = fetch_file(
            a.file.download_url,
            allowed_hosts=settings.mcp_file_url_hosts_list,
            max_bytes=app_settings.get(call.session, "upload_max_bytes"),
        )
    except RemoteFileError as exc:
        raise McpToolError(ErrorCode.VALIDATION_ERROR, f"Não foi possível anexar: {exc}.")
    tipo = (a.file.mime_type or tipo_do_servidor or "").split(";")[0].strip().lower()
    anexo = cmd_anexos.store_attachment(
        call.session, tx.workspace_id, tx.id,
        data=conteudo, filename=a.file.file_name or "anexo", content_type=tipo,
        uploaded_by_user_id=call.identity.user_id,
    )
    return ToolOutput(
        structured=AttachmentAddOut(attachment=_meta_do_anexo(call, anexo), transaction_id=tx.id),
        summary=f"Arquivo \"{anexo.filename}\" anexado ao lançamento \"{tx.title}\".",
        entity_type="attachment",
        entity_ids=[anexo.id],
        space_id=tx.workspace_id,
    )
