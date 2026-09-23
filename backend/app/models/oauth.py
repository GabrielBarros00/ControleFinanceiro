"""Authorization server OAuth 2.1 embutido, para os clientes MCP (ADR 0035).

Quatro tabelas, cada uma respondendo uma pergunta:

- `OAuthClient` — QUEM está pedindo acesso: um app registrado por DCR (RFC 7591)
  ou identificado por um Client ID Metadata Document (CIMD, a URL https que é o
  próprio `client_id`). O nome e as URIs vêm do cliente e são DADO NÃO
  CONFIÁVEL: a tela de consentimento mostra o host do redirect justamente porque
  o nome pode mentir.
- `OAuthAuthorizationCode` — o código de uso único trocado por tokens. Guardado
  só como hash; o "uso único" é um UPDATE condicional (`used_at IS NULL`), não
  um SELECT seguido de UPDATE — duas trocas simultâneas não passam as duas.
- `OAuthGrant` — a CONEXÃO que a pessoa vê em "Integrações com IA": um cliente,
  uma pessoa, os escopos aprovados. Revogar a concessão derruba todos os tokens
  dela de uma vez.
- `OAuthToken` — access e refresh opacos, só o SHA-256 no banco (o token em si
  existe apenas na resposta do `/token`). Refresh rotaciona a cada uso; um
  refresh já rotacionado reapresentado é roubo e revoga a concessão inteira,
  como as sessões do app (ADR 0013).

Tudo em texto, sem Enum nativo do Postgres (ver `PlatformRole`): valor novo em
Enum exige `ALTER TYPE` à mão e nenhum gate enxerga a divergência.
"""
from datetime import datetime, UTC
from typing import Optional

from sqlalchemy import Column, Index, String, Text
from sqlmodel import JSON, Field, SQLModel


def _agora() -> datetime:
    return datetime.now(UTC)


class OAuthClient(SQLModel, table=True):
    __tablename__ = "oauthclient"

    id: Optional[int] = Field(default=None, primary_key=True)
    # DCR: identificador aleatório emitido aqui. CIMD: a URL https do documento.
    client_id: str = Field(sa_column=Column(String(512), nullable=False, unique=True, index=True))
    #: `dcr` | `cimd`
    kind: str = Field(sa_column=Column(String(8), nullable=False))
    client_name: str = Field(sa_column=Column(String(120), nullable=False))
    client_uri: Optional[str] = Field(default=None, sa_column=Column(String(512), nullable=True))
    redirect_uris: list = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    grant_types: list = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    #: `none` (cliente público, só PKCE) | `client_secret_basic` | `client_secret_post`
    token_endpoint_auth_method: str = Field(
        default="none", sa_column=Column(String(32), nullable=False, server_default="none")
    )
    client_secret_hash: Optional[str] = Field(default=None, sa_column=Column(String(64), nullable=True))
    #: `native` | `web` (OIDC DCR; a spec 2026-07-28 exige que o cliente informe)
    application_type: Optional[str] = Field(default=None, sa_column=Column(String(16), nullable=True))
    software_id: Optional[str] = Field(default=None, sa_column=Column(String(120), nullable=True))
    software_version: Optional[str] = Field(default=None, sa_column=Column(String(60), nullable=True))
    #: Validade do documento CIMD em cache (respeita Cache-Control, 5 min a 24 h).
    metadata_expires_at: Optional[datetime] = Field(default=None)
    created_at: datetime = Field(default_factory=_agora)
    updated_at: datetime = Field(default_factory=_agora)
    last_used_at: Optional[datetime] = Field(default=None)
    disabled_at: Optional[datetime] = Field(default=None)


class OAuthGrant(SQLModel, table=True):
    """A conexão de um cliente de IA com a conta de uma pessoa."""

    __tablename__ = "oauthgrant"
    __table_args__ = (Index("ix_oauthgrant_user_ativa", "user_id", "revoked_at"),)

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id", index=True)
    client_pk: int = Field(foreign_key="oauthclient.id", index=True)
    #: Cópia do nome na hora da conexão: é o que a pessoa aprovou, e o registro
    #: do cliente pode mudar depois (CIMD é re-buscado).
    client_name: str = Field(sa_column=Column(String(120), nullable=False))
    scopes: str = Field(sa_column=Column(String(512), nullable=False))
    resource: str = Field(sa_column=Column(String(512), nullable=False))
    created_at: datetime = Field(default_factory=_agora)
    last_used_at: Optional[datetime] = Field(default=None)
    revoked_at: Optional[datetime] = Field(default=None)
    #: `user` | `refresh_reuse` | `code_reuse` | `password_change` | `admin` | `client` | `account_disabled`
    revoked_reason: Optional[str] = Field(default=None, sa_column=Column(String(32), nullable=True))


class OAuthAuthorizationCode(SQLModel, table=True):
    __tablename__ = "oauthauthorizationcode"

    id: Optional[int] = Field(default=None, primary_key=True)
    code_hash: str = Field(sa_column=Column(String(64), nullable=False, unique=True, index=True))
    client_pk: int = Field(foreign_key="oauthclient.id", index=True)
    user_id: int = Field(foreign_key="user.id", index=True)
    redirect_uri: str = Field(sa_column=Column(Text, nullable=False))
    scopes: str = Field(sa_column=Column(String(512), nullable=False))
    resource: str = Field(sa_column=Column(String(512), nullable=False))
    code_challenge: str = Field(sa_column=Column(String(128), nullable=False))
    expires_at: datetime
    used_at: Optional[datetime] = Field(default=None)
    #: Concessão criada na troca — é o que o reuso do código revoga.
    grant_id: Optional[int] = Field(default=None, foreign_key="oauthgrant.id", index=True)
    created_at: datetime = Field(default_factory=_agora)


class OAuthToken(SQLModel, table=True):
    __tablename__ = "oauthtoken"

    id: Optional[int] = Field(default=None, primary_key=True)
    grant_id: int = Field(foreign_key="oauthgrant.id", index=True)
    #: `access` | `refresh`
    kind: str = Field(sa_column=Column(String(8), nullable=False))
    token_hash: str = Field(sa_column=Column(String(64), nullable=False, unique=True, index=True))
    scopes: str = Field(sa_column=Column(String(512), nullable=False))
    expires_at: datetime = Field(index=True)
    #: Refresh já trocado por outro. Reapresentado depois disto = roubo.
    rotated_at: Optional[datetime] = Field(default=None)
    revoked_at: Optional[datetime] = Field(default=None)
    created_at: datetime = Field(default_factory=_agora)
