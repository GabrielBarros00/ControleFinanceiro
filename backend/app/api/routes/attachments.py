import hashlib
from datetime import datetime
from typing import List, Optional
from urllib.parse import quote

import structlog
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Response
from pydantic import BaseModel
from sqlmodel import Session, select, func

from app.db.locks import trava_workspace
from app.db.session import get_session
from app.models.attachment import Attachment
from app.models.transaction import Transaction
from app.models.workspace import WorkspaceMembership, WorkspaceRole
from app.api.deps import get_workspace_membership, require_role
from app.domain.access_policy import assert_can_write, get_visible_transaction
from app.services import app_settings
from app.services.attachment_storage import (
    AttachmentStorage,
    AttachmentStorageError,
    free_keys,
    keys_to_free,
)
from app.services.event_service import publish_event

logger = structlog.get_logger("app.attachments")

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


def _ensure_quota(session: Session, workspace_id: int, incoming_bytes: int) -> None:
    """Teto de armazenamento por workspace (ADR 0007).

    Vale independente de onde o conteúdo mora: sem quota, qualquer membro enche
    o volume subindo arquivos de 5 MB em sequência. A conta é pela soma dos
    `size_bytes` das linhas — o armazenamento dedupica por conteúdo, então dois
    envios do mesmo recibo ocupam um arquivo só e contam duas vezes na cota. A
    diferença é a favor do teto, e simplificar isso exigiria contar chaves
    distintas por workspace a cada upload.
    """
    used = session.exec(
        select(func.coalesce(func.sum(Attachment.size_bytes), 0)).where(
            Attachment.workspace_id == workspace_id
        )
    ).one()
    # Configurável em runtime pela tela de Admin (ADR 0026); sem linha gravada,
    # acompanha `ATTACHMENT_QUOTA_BYTES` do ambiente.
    limit = app_settings.get(session, "attachment_quota_bytes")
    if used + incoming_bytes > limit:
        limit_mb = limit // (1024 * 1024)
        used_mb = used // (1024 * 1024)
        raise HTTPException(
            status_code=413,
            detail=(
                f"Cota de anexos do workspace esgotada ({used_mb} MB de {limit_mb} MB). "
                "Remova anexos antigos para liberar espaço."
            ),
        )


@router.post("/transactions/{transaction_id}/attachments", response_model=AttachmentRead)
async def upload_attachment(
    workspace_id: int,
    transaction_id: int,
    file: UploadFile = File(...),
    session: Session = Depends(get_session),
    membership: WorkspaceMembership = Depends(require_role(WorkspaceRole.member)),
):
    _get_transaction_or_404(session, workspace_id, transaction_id, membership)

    content_type = (file.content_type or "").lower()
    if content_type not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(
            status_code=400,
            detail="Tipo de arquivo não permitido: use JPG, PNG, WebP ou PDF",
        )

    data = await _read_limited(file, app_settings.get(session, "upload_max_bytes"))
    if len(data) == 0:
        raise HTTPException(status_code=400, detail="Arquivo vazio")
    if not _content_matches_type(content_type, data):
        raise HTTPException(
            status_code=400,
            detail="Conteúdo do arquivo não corresponde ao tipo declarado",
        )
    # ANTES da soma da cota (ver `db/locks.py`): `_ensure_quota` lê os bytes já
    # usados e o `if` decide, mas o INSERT vem depois — oito envios simultâneos
    # leem o mesmo total e passam todos. Medido antes da correção: 2,4 MB
    # gravados numa cota de 1 MB. A trava fica aqui, e não dentro de
    # `_ensure_quota`, porque a função também é chamada em leitura e travar numa
    # consulta seria surpresa.
    trava_workspace(session, workspace_id)
    _ensure_quota(session, workspace_id, len(data))

    # Conteúdo vai para o armazenamento (ADR 0007); o banco fica com metadados +
    # hash + chave. Grava ANTES do commit: um arquivo órfão (se a transação
    # falhar depois) é recuperável e não é lido por ninguém; a linha apontando
    # para um arquivo que não existe, não.
    digest = hashlib.sha256(data).hexdigest()
    try:
        storage_key = AttachmentStorage.save(workspace_id, digest, data)
    except AttachmentStorageError as exc:
        logger.error("anexo_falha_ao_gravar", workspace_id=workspace_id, erro=str(exc))
        raise HTTPException(
            status_code=503,
            detail="Não foi possível armazenar o anexo agora. Tente novamente.",
        )

    attachment = Attachment(
        workspace_id=workspace_id,
        transaction_id=transaction_id,
        filename=file.filename or "anexo",
        content_type=content_type,
        size_bytes=len(data),
        sha256=digest,
        storage_key=storage_key,
        data=None,
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
    _get_transaction_or_404(session, workspace_id, transaction_id, membership)
    return session.exec(
        select(Attachment)
        .where(Attachment.transaction_id == transaction_id)
        .order_by(Attachment.created_at)
    ).all()


def read_attachment_bytes(attachment: Attachment) -> Optional[bytes]:
    """Conteúdo do anexo: do armazenamento (ADR 0007) ou da coluna LEGADA.

    O fallback existe porque a migração de schema não move os bytes — quem já
    tinha recibos continua servindo do banco até rodar
    `scripts/migrate_attachments_to_disk.py`.
    """
    if attachment.storage_key:
        return AttachmentStorage.read(attachment.storage_key)
    return attachment.data


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


@router.delete("/attachments/{attachment_id}")
def delete_attachment(
    workspace_id: int,
    attachment_id: int,
    session: Session = Depends(get_session),
    membership: WorkspaceMembership = Depends(require_role(WorkspaceRole.member)),
):
    attachment = session.get(Attachment, attachment_id)
    if not attachment or attachment.workspace_id != workspace_id:
        raise HTTPException(status_code=404, detail="Anexo não encontrado")

    # Invisível responde 404 antes de qualquer coisa: um 403 aqui confirmaria que
    # o anexo existe naquele id
    _get_transaction_or_404(session, workspace_id, attachment.transaction_id, membership)

    # Member remove apenas os próprios anexos; admin+ remove qualquer um
    assert_can_write(
        attachment.uploaded_by_user_id,
        membership,
        detail="Você só pode remover os próprios anexos",
    )

    # Quais objetos ficarão sem referência (o armazenamento dedupica por
    # conteúdo). Calculado ANTES de remover a linha; aplicado DEPOIS do commit.
    liberar = keys_to_free(session, [attachment])
    session.delete(attachment)
    publish_event(session, workspace_id, "attachment.deleted", "attachment", attachment_id, membership.user_id)
    session.commit()
    free_keys(liberar)
    return {"status": "ok"}
