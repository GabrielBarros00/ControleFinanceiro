from datetime import datetime, UTC
from typing import Optional
from sqlalchemy import Column, LargeBinary
from sqlmodel import SQLModel, Field


class Attachment(SQLModel, table=True):
    """Recibo/nota anexado a uma transação.

    O conteúdo vive no próprio banco (LargeBinary): dispensa volume/S3 e o
    limite de settings.UPLOAD_MAX_BYTES mantém o tamanho sob controle.
    """

    id: Optional[int] = Field(default=None, primary_key=True)
    workspace_id: int = Field(foreign_key="workspace.id", index=True)
    transaction_id: int = Field(foreign_key="transaction.id", index=True)
    filename: str
    content_type: str
    size_bytes: int
    # Integridade/deduplicação futura; preenchido no upload (SEC-003)
    sha256: Optional[str] = Field(default=None, max_length=64)
    data: bytes = Field(sa_column=Column(LargeBinary, nullable=False))
    uploaded_by_user_id: Optional[int] = Field(default=None, foreign_key="user.id")

    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
