import hashlib
from datetime import datetime
from typing import List, Optional
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Response
from pydantic import BaseModel
from sqlmodel import Session, select

from app.core.config import settings
from app.db.session import get_session
from app.models.attachment import Attachment
from app.models.transaction import Transaction
from app.models.workspace import WorkspaceMembership, WorkspaceRole, role_level
from app.api.deps import get_workspace_membership, require_role
from app.services.event_service import publish_event

router = APIRouter(prefix="/workspaces/{workspace_id}", tags=["attachments"])

# Recibos: imagens comuns e PDF — executáveis/HTML nunca
ALLOWED_CONTENT_TYPES = {
    "image/jpeg",
    "image/png",
    "image/webp",
    "application/pdf",
}

_READ_CHUNK = 64 * 1024

# Assinaturas de conteúdo (magic bytes): o Content-Type declarado pelo cliente
# não basta — o CONTEÚDO precisa bater com o tipo (SEC-003)
_MAGIC_PREFIXES = {
    "image/jpeg": (b"\xff\xd8\xff",),
    "image/png": (b"\x89PNG\r\n\x1a\n",),
    "application/pdf": (b"%PDF-",),
}


def _content_matches_type(content_type: str, data: bytes) -> bool:
    if content_type == "image/webp":
        return data[:4] == b"RIFF" and data[8:12] == b"WEBP"
    return any(data.startswith(p) for p in _MAGIC_PREFIXES.get(content_type, ()))


async def _read_limited(file: UploadFile, max_bytes: int) -> bytes:
    """Lê em chunks e interrompe assim que o limite estoura — sem carregar
    um arquivo arbitrariamente grande na memória antes de validar."""
    chunks = []
    size = 0
    while True:
        chunk = await file.read(_READ_CHUNK)
        if not chunk:
            break
        size += len(chunk)
        if size > max_bytes:
            max_mb = max_bytes // (1024 * 1024)
            raise HTTPException(status_code=400, detail=f"Arquivo excede o limite de {max_mb} MB")
        chunks.append(chunk)
    return b"".join(chunks)


class AttachmentRead(BaseModel):
    id: int
    transaction_id: int
    filename: str
    content_type: str
    size_bytes: int
    uploaded_by_user_id: Optional[int]
    created_at: datetime


def _get_transaction_or_404(session: Session, workspace_id: int, transaction_id: int) -> Transaction:
    tx = session.get(Transaction, transaction_id)
    if not tx or tx.workspace_id != workspace_id or tx.deleted_at:
        raise HTTPException(status_code=404, detail="Transaction not found")
    return tx


@router.post("/transactions/{transaction_id}/attachments", response_model=AttachmentRead)
async def upload_attachment(
    workspace_id: int,
    transaction_id: int,
    file: UploadFile = File(...),
    session: Session = Depends(get_session),
    membership: WorkspaceMembership = Depends(require_role(WorkspaceRole.member)),
):
    _get_transaction_or_404(session, workspace_id, transaction_id)

    content_type = (file.content_type or "").lower()
    if content_type not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(
            status_code=400,
            detail="Tipo de arquivo não permitido: use JPG, PNG, WebP ou PDF",
        )

    data = await _read_limited(file, settings.UPLOAD_MAX_BYTES)
    if len(data) == 0:
        raise HTTPException(status_code=400, detail="Arquivo vazio")
    if not _content_matches_type(content_type, data):
        raise HTTPException(
            status_code=400,
            detail="Conteúdo do arquivo não corresponde ao tipo declarado",
        )

    attachment = Attachment(
        workspace_id=workspace_id,
        transaction_id=transaction_id,
        filename=file.filename or "anexo",
        content_type=content_type,
        size_bytes=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
        data=data,
        uploaded_by_user_id=membership.user_id,
    )
    session.add(attachment)
    session.flush()
    publish_event(session, workspace_id, "attachment.created", "attachment", attachment.id, membership.user_id)
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
    _get_transaction_or_404(session, workspace_id, transaction_id)
    return session.exec(
        select(Attachment)
        .where(Attachment.transaction_id == transaction_id)
        .order_by(Attachment.created_at)
    ).all()


@router.get("/attachments/{attachment_id}")
def download_attachment(
    workspace_id: int,
    attachment_id: int,
    session: Session = Depends(get_session),
    membership: WorkspaceMembership = Depends(get_workspace_membership),
):
    attachment = session.get(Attachment, attachment_id)
    if not attachment or attachment.workspace_id != workspace_id:
        raise HTTPException(status_code=404, detail="Attachment not found")

    filename = quote(attachment.filename)
    return Response(
        content=attachment.data,
        media_type=attachment.content_type,
        headers={
            "Content-Disposition": f"inline; filename*=UTF-8''{filename}",
            # Blindagem: o conteúdo é de usuário — nunca interpretar como HTML
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.delete("/attachments/{attachment_id}")
def delete_attachment(
    workspace_id: int,
    attachment_id: int,
    session: Session = Depends(get_session),
    membership: WorkspaceMembership = Depends(require_role(WorkspaceRole.member)),
):
    attachment = session.get(Attachment, attachment_id)
    if not attachment or attachment.workspace_id != workspace_id:
        raise HTTPException(status_code=404, detail="Attachment not found")

    # Member remove apenas os próprios anexos; admin+ remove qualquer um
    if (
        role_level(membership.role) < role_level(WorkspaceRole.admin)
        and attachment.uploaded_by_user_id not in (None, membership.user_id)
    ):
        raise HTTPException(status_code=403, detail="Você só pode remover os próprios anexos")

    session.delete(attachment)
    publish_event(session, workspace_id, "attachment.deleted", "attachment", attachment_id, membership.user_id)
    session.commit()
    return {"status": "ok"}
