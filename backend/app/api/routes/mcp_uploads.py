"""Envio de anexo pelo link do MCP (ADR 0035) — ver `app/mcp/uploads.py`.

Rota sem cookie e sem sessão: quem autoriza é o token de uso único no cabeçalho
`Authorization`, emitido por `attachments_upload_link` para UM lançamento. Tudo é
conferido de novo aqui, no momento do envio: o token (existe, é deste tipo, não
expirou), a concessão OAuth (não revogada), a conta (ativa), o papel no espaço
(membro para cima) e a visibilidade do lançamento (ADR 0018).
"""
from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, File, Header, HTTPException, Request, UploadFile
from pydantic import BaseModel
from sqlalchemy import update
from sqlmodel import Session

from app.api.deps import get_workspace_membership
from app.core.config import settings
from app.core.context import set_current_user_id, set_request_origin
from app.core.rate_limit import RateLimiter
from app.db.session import get_session
from app.domain.access_policy import get_visible_transaction
from app.mcp import uploads
from app.models.mcp import McpConfirmation
from app.models.workspace import WorkspaceRole, role_level
from app.services.commands import attachments as cmd_anexos

router = APIRouter(prefix="/mcp", tags=["mcp"])

#: Por IP: o token já é segredo de 256 bits e de uso único; o teto só impede que
#: alguém use a rota para martelar o disco com tentativas.
upload_limiter = RateLimiter(max_requests=30, window_seconds=60)


class AnexoEnviado(BaseModel):
    attachment_id: int
    transaction_id: int
    filename: str
    content_type: str
    size_bytes: int
    #: true = este link já tinha sido usado; nada foi anexado de novo.
    replayed: bool = False


@router.post("/uploads", response_model=AnexoEnviado)
async def enviar_anexo_pelo_link(
    request: Request,
    file: UploadFile = File(...),
    authorization: str | None = Header(None),
    session: Session = Depends(get_session),
):
    if settings.RATE_LIMIT_ENABLED:
        upload_limiter.check(f"up:{request.client.host if request.client else 'unknown'}")
    envio = uploads.confere(session, uploads.token_do_cabecalho(authorization))
    registro = envio.registro
    if registro.used_at is not None:
        # Reenvio do mesmo link (queda de rede depois do sucesso): o resultado
        # de antes, e nada anexado duas vezes.
        if registro.result:
            return AnexoEnviado(**{**registro.result, "replayed": True})
        raise HTTPException(status_code=409, detail="Este link de envio está sendo usado agora.")

    try:
        membership = get_workspace_membership(envio.workspace_id, session=session, current_user=envio.user)
    except HTTPException:
        raise HTTPException(status_code=404, detail="Lançamento não encontrado.")
    if role_level(membership.role) < role_level(WorkspaceRole.member):
        raise HTTPException(status_code=403, detail="Seu papel neste espaço não permite anexar arquivos.")
    get_visible_transaction(session, envio.workspace_id, envio.transaction_id, membership)

    # Auditoria "via IA", como no pipeline das tools.
    set_current_user_id(envio.user.id)
    set_request_origin(f"mcp:{envio.grant.client_name}"[:80])
    try:
        anexo = await cmd_anexos.add_attachment(
            session, envio.workspace_id, envio.transaction_id, file, uploaded_by_user_id=envio.user.id
        )
        # Uso único por UPDATE condicional (`corridas-so-aparecem-no-postgres`):
        # dois envios simultâneos do mesmo link não anexam duas vezes. Marcado só
        # DEPOIS de o arquivo passar pelas regras: um arquivo recusado não gasta o link.
        marcado = session.execute(
            update(McpConfirmation)
            .where(McpConfirmation.id == registro.id, McpConfirmation.used_at.is_(None))
            .values(used_at=datetime.now(UTC))
        ).rowcount
        if marcado != 1:
            session.rollback()
            raise HTTPException(status_code=409, detail="Este link de envio já foi usado.")
        resultado = {
            "attachment_id": anexo.id,
            "transaction_id": anexo.transaction_id,
            "filename": anexo.filename,
            "content_type": anexo.content_type,
            "size_bytes": anexo.size_bytes,
        }
        session.execute(
            update(McpConfirmation).where(McpConfirmation.id == registro.id).values(result=resultado)
        )
        session.commit()
    finally:
        set_current_user_id(None)
        set_request_origin(None)
    return AnexoEnviado(**resultado)
