"""A tela "Integrações com IA" (ADR 0035): status do MCP, conexões e atividade.

Escopo PESSOAL — tudo aqui é da conta logada: as conexões de IA dela e o que
esses aplicativos fizeram em nome dela. Não há dado de outra pessoa nem de
workspace, então o gate é a sessão, sem `require_role`.

Nenhum token aparece aqui, nunca: a conexão é identificada pelo id da concessão,
e "Desconectar" revoga a concessão inteira (todos os tokens dela) na hora.
"""
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlmodel import Session, select

from app.api.routes.auth import get_current_user
from app.core.config import settings
from app.db.session import get_session
from app.models.mcp import McpToolCall
from app.models.user import User
from app.schemas.common import StatusRead
from app.services.oauth import grants as conexoes, scopes as escopos

router = APIRouter(prefix="/me/ai-integrations", tags=["ai-integrations"])


class AiScopeRead(BaseModel):
    scope: str
    label: str
    description: str
    required: bool


class AiAccountRead(BaseModel):
    name: str
    email: str
    public_id: str


class AiConnectionRead(BaseModel):
    grant_id: int
    client_name: str
    #: `cimd` (aplicativo identificado por URL) | `dcr` (registrado dinamicamente)
    client_kind: str
    client_host: Optional[str] = None
    redirect_host: Optional[str] = None
    scopes: List[str]
    created_at: datetime
    last_used_at: Optional[datetime] = None
    #: `active` | `expired` — expirada: o aplicativo precisa se reconectar
    status: str


class AiIntegrationsRead(BaseModel):
    enabled: bool
    mcp_url: str
    transport: str
    authentication: str
    server_name: str
    server_version: str
    environment: str
    account: AiAccountRead
    scopes: List[AiScopeRead]
    connections: List[AiConnectionRead]
    last_used_at: Optional[datetime] = None


class AiActivityRead(BaseModel):
    id: int
    tool: str
    title: str
    kind: str
    outcome: str
    error_code: Optional[str] = None
    client_name: Optional[str] = None
    created_at: datetime
    duration_ms: int
    replayed: bool


def _colecao(metodo: str, caminho: str, **kwargs):
    """Coleção COM e SEM barra final, sem 307 (o salto perde o cookie)."""
    def decorador(func):
        for p in (caminho, caminho + "/"):
            getattr(router, metodo)(
                p, **({**kwargs, "include_in_schema": False} if p.endswith("/") else kwargs)
            )(func)
        return func
    return decorador


@_colecao("get", "", response_model=AiIntegrationsRead)
def get_ai_integrations(
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    from app.mcp.server import SERVER_NAME, SERVER_VERSION

    lista = conexoes.list_connections(session, current_user.id)
    ultimos = [c.last_used_at for c in lista if c.last_used_at]
    return AiIntegrationsRead(
        enabled=settings.MCP_ENABLED,
        mcp_url=settings.mcp_resource_url,
        transport="streamable-http",
        authentication="OAuth 2.1 (Authorization Code + PKCE)",
        server_name=SERVER_NAME,
        server_version=SERVER_VERSION,
        environment=settings.APP_ENV,
        account=AiAccountRead(name=current_user.name, email=current_user.email, public_id=current_user.public_id),
        scopes=[
            AiScopeRead(scope=s.scope, label=s.label, description=s.description, required=s.required)
            for s in escopos.SCOPES
        ],
        connections=[
            AiConnectionRead(
                grant_id=c.grant_id,
                client_name=c.client_name,
                client_kind=c.client_kind,
                client_host=c.client_host,
                redirect_host=c.redirect_host,
                scopes=c.scopes,
                created_at=c.created_at,
                last_used_at=c.last_used_at,
                status=c.status,
            )
            for c in lista
        ],
        last_used_at=max(ultimos) if ultimos else None,
    )


@router.get("/activity", response_model=List[AiActivityRead])
def get_ai_activity(
    limit: int = Query(20, ge=1, le=100),
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """O que os aplicativos de IA fizeram em nome da pessoa, mais recente primeiro.

    Só metadado — tool, resultado, quando —, nunca argumentos ou valores.
    """
    from app.mcp.registry import REGISTRY
    import app.mcp.tools  # noqa: F401 — títulos das tools

    linhas = session.exec(
        select(McpToolCall)
        .where(McpToolCall.user_id == current_user.id)
        .order_by(McpToolCall.created_at.desc(), McpToolCall.id.desc())
        .limit(limit)
    ).all()
    return [
        AiActivityRead(
            id=chamada.id,
            tool=chamada.tool,
            title=REGISTRY[chamada.tool].title if chamada.tool in REGISTRY else chamada.tool,
            kind=chamada.op_type,
            outcome=chamada.outcome,
            error_code=chamada.error_code,
            client_name=chamada.client_name,
            created_at=chamada.created_at,
            duration_ms=chamada.duration_ms,
            replayed=chamada.replayed,
        )
        for chamada in linhas
    ]


@router.delete("/connections/{grant_id}", response_model=StatusRead)
def revoke_ai_connection(
    grant_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Desconecta o aplicativo: a próxima chamada dele já recebe 401."""
    if not conexoes.revoke_connection(session, current_user.id, grant_id):
        raise HTTPException(status_code=404, detail="Conexão não encontrada")
    session.commit()
    return {"status": "ok"}
