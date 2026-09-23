"""Estado do servidor MCP (ADR 0035): auditoria, idempotência e confirmação.

- `McpToolCall` — uma linha por chamada de tool. É a trilha OPERACIONAL ("qual
  agente fez o quê, quando, com que resultado e em quanto tempo") e a fonte das
  métricas do Admin. Não guarda argumentos nem valores: só o nome da tool, o
  resultado, o código de erro e os IDs afetados. A trilha de DADOS continua sendo
  o `AuditLog`, que agora carrega `origin="mcp:<cliente>"` na mesma transação da
  mudança.
- `McpOperation` — a chave de idempotência de uma escrita. Gravada na MESMA
  transação da entidade criada: ou as duas existem, ou nenhuma — um retry depois
  de timeout devolve o que já foi feito em vez de lançar a compra de novo. Guarda
  só referências (tipo + IDs); o replay re-renderiza o estado atual.
- `McpConfirmation` — o token de uma ação em massa pré-visualizada. Amarra o
  conjunto EXATO de IDs mostrados à pessoa: a execução nunca alcança um
  lançamento que não estava na prévia. Uso único por UPDATE condicional.
"""
from datetime import datetime, UTC
from typing import Optional

from sqlalchemy import Column, Index, String, UniqueConstraint
from sqlmodel import JSON, Field, SQLModel


def _agora() -> datetime:
    return datetime.now(UTC)


class McpToolCall(SQLModel, table=True):
    __tablename__ = "mcptoolcall"
    __table_args__ = (Index("ix_mcptoolcall_user_criado", "user_id", "created_at"),)

    id: Optional[int] = Field(default=None, primary_key=True)
    created_at: datetime = Field(default_factory=_agora, index=True)
    user_id: Optional[int] = Field(default=None, foreign_key="user.id")
    grant_id: Optional[int] = Field(default=None, foreign_key="oauthgrant.id", index=True)
    client_name: Optional[str] = Field(default=None, sa_column=Column(String(120), nullable=True))
    #: `clientInfo` que o cliente declarou (nome/versão) — dado do cliente, só exibição.
    client_info: Optional[str] = Field(default=None, sa_column=Column(String(120), nullable=True))
    tool: str = Field(sa_column=Column(String(64), nullable=False, index=True))
    #: `read` | `write` | `destructive`
    op_type: str = Field(sa_column=Column(String(16), nullable=False))
    #: `ok` | `error`
    outcome: str = Field(sa_column=Column(String(16), nullable=False))
    error_code: Optional[str] = Field(default=None, sa_column=Column(String(40), nullable=True))
    duration_ms: int = Field(default=0)
    request_id: Optional[str] = Field(default=None, sa_column=Column(String(64), nullable=True))
    space_id: Optional[int] = Field(default=None)
    entity_type: Optional[str] = Field(default=None, sa_column=Column(String(32), nullable=True))
    entity_ids: Optional[list] = Field(default=None, sa_column=Column(JSON, nullable=True))
    replayed: bool = Field(default=False)


class McpOperation(SQLModel, table=True):
    __tablename__ = "mcpoperation"
    __table_args__ = (
        UniqueConstraint("user_id", "tool", "idempotency_key", name="uq_mcpoperation_user_tool_key"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id", index=True)
    tool: str = Field(sa_column=Column(String(64), nullable=False))
    idempotency_key: str = Field(sa_column=Column(String(128), nullable=False))
    #: SHA-256 dos argumentos canônicos (sem a própria chave): a mesma chave com
    #: outro conteúdo é CONFLICT, nunca replay.
    request_hash: str = Field(sa_column=Column(String(64), nullable=False))
    grant_id: Optional[int] = Field(default=None, foreign_key="oauthgrant.id")
    #: Referências do resultado (`{"kind": ..., "ids": [...]}`), nunca o conteúdo.
    result_ref: Optional[dict] = Field(default=None, sa_column=Column(JSON, nullable=True))
    created_at: datetime = Field(default_factory=_agora)
    expires_at: datetime = Field(index=True)


class McpConfirmation(SQLModel, table=True):
    __tablename__ = "mcpconfirmation"

    id: Optional[int] = Field(default=None, primary_key=True)
    token_hash: str = Field(sa_column=Column(String(64), nullable=False, unique=True, index=True))
    user_id: int = Field(foreign_key="user.id", index=True)
    grant_id: Optional[int] = Field(default=None, foreign_key="oauthgrant.id")
    #: `bulk_delete` | `bulk_categorize`
    action: str = Field(sa_column=Column(String(24), nullable=False))
    #: IDs exatos mostrados na prévia, ordenados.
    target_ids: list = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    params: Optional[dict] = Field(default=None, sa_column=Column(JSON, nullable=True))
    expires_at: datetime = Field(index=True)
    used_at: Optional[datetime] = Field(default=None)
    #: Resultado da execução — um segundo envio do mesmo token devolve isto.
    result: Optional[dict] = Field(default=None, sa_column=Column(JSON, nullable=True))
    created_at: datetime = Field(default_factory=_agora)
