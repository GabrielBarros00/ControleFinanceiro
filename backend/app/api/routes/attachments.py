from datetime import datetime
from typing import List, Optional
from urllib.parse import quote

import structlog
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Response
from pydantic import BaseModel
from sqlmodel import Session, select

from app.schemas.common import StatusRead
from app.db.session import get_session
from app.models.attachment import Attachment
from app.models.transaction import Transaction
from app.models.workspace import WorkspaceMembership, WorkspaceRole
from app.api.deps import get_workspace_membership, require_role
from app.domain.access_policy import get_visible_transaction
from app.services import upload_validation
from app.services.attachment_storage import (
    free_keys,
)
from app.services.commands import attachments as cmd_anexos

logger = structlog.get_logger("app.attachments")

router = APIRouter(prefix="/workspaces/{workspace_id}", tags=["attachments"])

# Tipos, cota e o corpo do envio moram no comando compartilhado com o envio por
# link do MCP (ADR 0035). Reexportados aqui para quem já os importava da rota.
ALLOWED_CONTENT_TYPES = cmd_anexos.ALLOWED_CONTENT_TYPES
_ensure_quota = cmd_anexos.ensure_quota
_content_matches_type = upload_validation.content_matches_type
_read_limited = upload_validation.read_limited


class AttachmentRead(BaseModel):
    id: int
    transaction_id: int
    filename: str
    content_type: str
    size_bytes: int
    uploaded_by_user_id: Optional[int]
    created_at: datetime


def _get_transaction_or_404(
    session: Session,
    workspace_id: int,
    transaction_id: int,
    membership: WorkspaceMembership,
) -> Transaction:
    """Anexo herda a visibilidade do LANÇAMENTO (ADR 0018).

    Antes resolvia só por workspace, e com isso o recibo de uma despesa alheia —
    o arquivo, não só o metadado — era servido a qualquer membro.
    """
    return get_visible_transaction(session, workspace_id, transaction_id, membership)


@router.post("/transactions/{transaction_id}/attachments", response_model=AttachmentRead)
async def upload_attachment(
    workspace_id: int,
    transaction_id: int,
    file: UploadFile = File(...),
    session: Session = Depends(get_session),
    membership: WorkspaceMembership = Depends(require_role(WorkspaceRole.member)),
):
    _get_transaction_or_404(session, workspace_id, transaction_id, membership)
    attachment = await cmd_anexos.add_attachment(
        session, workspace_id, transaction_id, file, uploaded_by_user_id=membership.user_id
    )
    session.commit()
    session.refresh(attachment)
    return attachment


@router.get("/transactions/{transaction_id}/attachments", response_model=List[AttachmentRead])
def list_attachments(
    workspace_id: int,
    transaction_id: int,
    session: Session = Depends(get_session),
    membership: WorkspaceMembership = Depends(get_workspace_membership),
):
    _get_transaction_or_404(session, workspace_id, transaction_id, membership)
    return session.exec(
        select(Attachment)
        .where(Attachment.transaction_id == transaction_id)
        .order_by(Attachment.created_at)
    ).all()


read_attachment_bytes = cmd_anexos.read_attachment_bytes


@router.get("/attachments/{attachment_id}")
def download_attachment(
    workspace_id: int,
    attachment_id: int,
    session: Session = Depends(get_session),
    membership: WorkspaceMembership = Depends(get_workspace_membership),
):
    attachment = session.get(Attachment, attachment_id)
    if not attachment or attachment.workspace_id != workspace_id:
        raise HTTPException(status_code=404, detail="Anexo não encontrado")

    # O ARQUIVO só sai se o lançamento for visível. Este era o vazamento de pior
    # consequência: bastava o id do anexo para baixar o recibo de outro membro.
    _get_transaction_or_404(session, workspace_id, attachment.transaction_id, membership)

    content = read_attachment_bytes(attachment)
    if content is None:
        # A linha existe mas o objeto não está no volume (não montado, restore
        # parcial). 500 mandaria o usuário caçar um bug que é de operação; a
        # mensagem explícita, somada ao log de erro, aponta para o lugar certo.
        logger.error(
            "anexo_conteudo_indisponivel",
            attachment_id=attachment.id,
            workspace_id=workspace_id,
            storage_key=attachment.storage_key,
        )
        raise HTTPException(
            status_code=404,
            detail="Conteúdo do anexo indisponível — verifique o armazenamento de anexos.",
        )

    filename = quote(attachment.filename)
    return Response(
        content=content,
        media_type=attachment.content_type,
        headers={
            "Content-Disposition": f"inline; filename*=UTF-8''{filename}",
            # Blindagem: o conteúdo é de usuário — nunca interpretar como HTML
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.delete("/attachments/{attachment_id}", response_model=StatusRead)
def delete_attachment(
    workspace_id: int,
    attachment_id: int,
    session: Session = Depends(get_session),
    membership: WorkspaceMembership = Depends(require_role(WorkspaceRole.member)),
):
    liberar = cmd_anexos.delete_attachment(session, workspace_id, attachment_id, membership)
    session.commit()
    free_keys(liberar)
    return {"status": "ok"}
