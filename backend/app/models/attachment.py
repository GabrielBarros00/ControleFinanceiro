from datetime import datetime, UTC
from typing import Optional
from sqlalchemy import Column, LargeBinary
from sqlmodel import SQLModel, Field


class Attachment(SQLModel, table=True):
    """Recibo/nota anexado a uma transação.

    O conteúdo vive FORA do banco (ADR 0007): aqui ficam metadados, o `sha256` e
    a `storage_key` que o `AttachmentStorage` resolve. Blob no banco fazia o dump
    do Postgres crescer com recibos — dado grande, imutável e que ninguém
    consulta — e obrigava a carregar o arquivo inteiro em memória para servir.
    """

    id: Optional[int] = Field(default=None, primary_key=True)
    workspace_id: int = Field(foreign_key="workspace.id", index=True)
    transaction_id: int = Field(foreign_key="transaction.id", index=True)
    filename: str
    content_type: str
    size_bytes: int
    # Integridade + endereçamento: a storage_key é derivada dele (SEC-003)
    sha256: Optional[str] = Field(default=None, max_length=64)
    # Caminho relativo do objeto no armazenamento. Indexado porque a exclusão
    # precisa saber se outra linha ainda aponta para o mesmo arquivo (o
    # armazenamento é endereçado por conteúdo e dedupica dentro do workspace).
    storage_key: Optional[str] = Field(default=None, max_length=128, index=True)
    # LEGADO: anexos anteriores à migração para volume ainda têm os bytes aqui.
    # `scripts/migrate_attachments_to_disk.py` esvazia esta coluna; a leitura cai
    # nela quando `storage_key` é nulo.
    data: Optional[bytes] = Field(default=None, sa_column=Column(LargeBinary, nullable=True))
    uploaded_by_user_id: Optional[int] = Field(default=None, foreign_key="user.id")

    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
