"""Anexar arquivo a um lançamento — o corpo da rota REST, compartilhado com o MCP.

O envio pela tela (`POST /workspaces/{ws}/transactions/{id}/attachments`) e o
envio por link do MCP (`POST /api/v1/mcp/uploads`, token no cabeçalho, ADR 0035) passam por
aqui: os mesmos tipos, a mesma conferência pelo CONTEÚDO do arquivo, a mesma cota
com trava e o mesmo armazenamento (ADR 0007/0016). Quem chama confere antes a
visibilidade e o papel, e comanda o commit (ADR 0010).
"""
from __future__ import annotations

import hashlib

import structlog
from fastapi import HTTPException, UploadFile
from sqlmodel import Session, func, select

from app.db.locks import trava_workspace
from app.models.attachment import Attachment
from app.services import app_settings, upload_validation
from app.services.attachment_storage import AttachmentStorage, AttachmentStorageError
from app.services.event_service import publish_event

logger = structlog.get_logger("app.attachments")

# Recibos: imagens comuns e PDF — executáveis/HTML nunca
ALLOWED_CONTENT_TYPES = {
    "image/jpeg",
    "image/png",
    "image/webp",
    "application/pdf",
}


def ensure_quota(session: Session, workspace_id: int, incoming_bytes: int) -> None:
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


async def add_attachment(
    session: Session,
    workspace_id: int,
    transaction_id: int,
    file: UploadFile,
    uploaded_by_user_id: int,
) -> Attachment:
    """Valida, grava o conteúdo e cria a linha do anexo (flush, sem commit)."""
    content_type = (file.content_type or "").lower()
    if content_type not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(
            status_code=400,
            detail="Tipo de arquivo não permitido: use JPG, PNG, WebP ou PDF",
        )

    data = await upload_validation.read_limited(file, app_settings.get(session, "upload_max_bytes"))
    if len(data) == 0:
        raise HTTPException(status_code=400, detail="Arquivo vazio")
    if not upload_validation.content_matches_type(content_type, data):
        raise HTTPException(
            status_code=400,
            detail="Conteúdo do arquivo não corresponde ao tipo declarado",
        )
    # ANTES da soma da cota (ver `db/locks.py`): `ensure_quota` lê os bytes já
    # usados e o `if` decide, mas o INSERT vem depois — oito envios simultâneos
    # leem o mesmo total e passam todos. Medido antes da correção: 2,4 MB
    # gravados numa cota de 1 MB. A trava fica aqui, e não dentro de
    # `ensure_quota`, porque a função também é chamada em leitura e travar numa
    # consulta seria surpresa.
    trava_workspace(session, workspace_id)
    ensure_quota(session, workspace_id, len(data))

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
        uploaded_by_user_id=uploaded_by_user_id,
    )
    session.add(attachment)
    session.flush()
    publish_event(session, workspace_id, "attachment.created", "attachment", attachment.id, uploaded_by_user_id)
    return attachment
