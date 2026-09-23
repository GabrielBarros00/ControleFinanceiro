"""Authorization server OAuth 2.1 dos clientes MCP (ADR 0035).

Dois grupos de rota, com contratos diferentes de propósito:

- **Protocolo** (`/authorize`, `/token`, `/register`, `/revoke`) — falado por
  ChatGPT, Claude, Codex, Gemini... Respostas no formato das RFCs (6749, 7591,
  7009), NÃO no envelope do app: cliente OAuth decide pelo campo `error`. Fora do
  OpenAPI porque o frontend não as consome, e com corpo `form-urlencoded` no
  `/token` e no `/revoke` (RFC 6749 §4.1.3 — o Claude manda exatamente isso).
- **Consentimento** (`/consent*`) — falado pelo SPA, com a sessão por cookie do
  próprio app. É aqui que o login existente é reaproveitado: não há tela de senha
  nova, a pessoa entra como sempre entrou (senha ou Google) e aprova.
"""
import base64
from typing import List, Optional
from urllib.parse import unquote

import structlog
from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel, Field
from sqlmodel import Session

from app.api.routes.auth import get_current_user
from app.core.config import settings
from app.core.rate_limit import rate_limit_oauth
from app.db.session import get_session
from app.models.user import User
from app.services.oauth import authorization, clients, scopes as escopos, tokens
from app.services.oauth.errors import OAuthError

logger = structlog.get_logger("app.oauth")

router = APIRouter(prefix="/oauth", tags=["oauth"])

#: Resposta de token nunca vai para cache (RFC 6749 §5.1).
_SEM_CACHE = {"Cache-Control": "no-store", "Pragma": "no-cache"}


def _habilitado() -> None:
    if not settings.MCP_ENABLED:
        raise HTTPException(status_code=404, detail="Não encontrado")


def _oauth_error(exc: OAuthError) -> JSONResponse:
    headers = dict(_SEM_CACHE)
    if exc.status_code == 401:
        headers["WWW-Authenticate"] = 'Basic realm="oauth"'
    return JSONResponse(status_code=exc.status_code, content=exc.body(), headers=headers)


def _limite(request: Request, *, registration: bool = False) -> Optional[JSONResponse]:
    try:
        rate_limit_oauth(request, registration=registration)
    except HTTPException:
        return JSONResponse(
            status_code=429,
            content={
                "error": "temporarily_unavailable",
                "error_description": "Muitas tentativas. Aguarde um minuto e tente novamente.",
            },
            headers={**_SEM_CACHE, "Retry-After": "60"},
        )
    return None


def _consent_url(**params: str) -> str:
    from urllib.parse import urlencode

    return f"{settings.oauth_issuer}/oauth/consent?{urlencode(params)}"


# --- Protocolo ------------------------------------------------------------------

@router.get("/authorize", include_in_schema=False)
def authorize(request: Request, session: Session = Depends(get_session)):
    """Valida o pedido e entrega a pessoa à tela de consentimento do SPA.

    Nunca mostra HTML próprio e nunca decide sozinho: o que sai daqui é um
    redirect para `/oauth/consent` com o pedido assinado (ou com o erro, quando o
    redirect do cliente não é confiável), ou o redirect de erro do RFC para o
    cliente quando o redirect dele já foi validado.
    """
    _habilitado()
    bloqueio = _limite(request)
    if bloqueio is not None:
        return bloqueio
    params = dict(request.query_params)
    try:
        cliente, pedido = authorization.validate_authorize(session, params)
    except authorization.FatalAuthorizeError as exc:
        session.rollback()
        logger.info("oauth_authorize_rejeitado", erro=exc.error)
        return RedirectResponse(_consent_url(error=exc.error, error_description=exc.description), status_code=302)
    except authorization.RedirectableError as exc:
        # O cliente CIMD pode ter sido (re)validado nesta chamada — vale guardar.
        session.commit()
        logger.info("oauth_authorize_erro_redirecionado", erro=exc.error)
        return RedirectResponse(exc.location(), status_code=302)
    session.commit()
    return RedirectResponse(_consent_url(request=authorization.issue_request_handle(pedido)), status_code=302)


def _credenciais_basic(request: Request) -> tuple[Optional[str], Optional[str], bool]:
    cabecalho = request.headers.get("authorization") or ""
    if not cabecalho.lower().startswith("basic "):
        return None, None, False
    try:
        bruto = base64.b64decode(cabecalho[6:].strip()).decode("utf-8")
        client_id, _, segredo = bruto.partition(":")
        return unquote(client_id), unquote(segredo), True
    except Exception:
        raise OAuthError("invalid_client", "cabeçalho Basic malformado", 401)


def _cliente_da_requisicao(
    session: Session, request: Request, client_id: Optional[str], client_secret: Optional[str]
):
    basic_id, basic_secret, via_basic = _credenciais_basic(request)
    if via_basic:
        if client_id and client_id != basic_id:
            raise OAuthError("invalid_request", "client_id divergente do cabeçalho Basic")
        if client_secret:
            raise OAuthError("invalid_request", "use UM método de autenticação do cliente")
        return clients.authenticate_client(
            session, client_id=basic_id, client_secret=basic_secret, via_basic=True
        )
    return clients.authenticate_client(
        session, client_id=client_id, client_secret=client_secret, via_basic=False
    )


@router.post("/token", include_in_schema=False)
def token(
    request: Request,
    grant_type: Optional[str] = Form(None),
    code: Optional[str] = Form(None),
    redirect_uri: Optional[str] = Form(None),
    code_verifier: Optional[str] = Form(None),
    refresh_token: Optional[str] = Form(None),
    scope: Optional[str] = Form(None),
    resource: Optional[str] = Form(None),
    client_id: Optional[str] = Form(None),
    client_secret: Optional[str] = Form(None),
    session: Session = Depends(get_session),
):
    _habilitado()
    bloqueio = _limite(request)
    if bloqueio is not None:
        return bloqueio
    tipo = (request.headers.get("content-type") or "").split(";")[0].strip().lower()
    if tipo != "application/x-www-form-urlencoded":
        return _oauth_error(OAuthError(
            "invalid_request", "o corpo deve ser application/x-www-form-urlencoded"
        ))
    try:
        cliente = _cliente_da_requisicao(session, request, client_id, client_secret)
        if grant_type == "authorization_code":
            par = authorization.exchange_code(
                session, client=cliente, code=code, redirect_uri=redirect_uri,
                code_verifier=code_verifier, resource=resource,
            )
        elif grant_type == "refresh_token":
            par = tokens.refresh(
                session, client=cliente, refresh_token=refresh_token, scope=scope, resource=resource,
            )
        elif not grant_type:
            raise OAuthError("invalid_request", "grant_type é obrigatório")
        else:
            raise OAuthError("unsupported_grant_type", "grant_type aceito: authorization_code ou refresh_token")
    except OAuthError as exc:
        # Commit mesmo no erro: reuso de código/refresh REVOGA a conexão, e essa
        # revogação precisa sobreviver à resposta de erro que a denuncia.
        session.commit()
        logger.info("oauth_token_recusado", erro=exc.error, grant_type=grant_type)
        return _oauth_error(exc)
    session.commit()
    logger.info("oauth_token_emitido", grant_type=grant_type, client=cliente.client_name)
    return JSONResponse(content=par.body(), headers=_SEM_CACHE)


@router.post("/register", include_in_schema=False)
async def register(request: Request, session: Session = Depends(get_session)):
    """Registro dinâmico (RFC 7591). JSON, ao contrário do /token (§3.1)."""
    _habilitado()
    bloqueio = _limite(request, registration=True)
    if bloqueio is not None:
        return bloqueio
    try:
        metadados = await request.json()
    except Exception:
        return _oauth_error(OAuthError("invalid_client_metadata", "o corpo deve ser JSON"))
    from starlette.concurrency import run_in_threadpool

    def _registra():
        cliente, segredo = clients.register_dcr(session, metadados)
        session.commit()
        session.refresh(cliente)
        return clients.registration_response(cliente, segredo)

    try:
        corpo = await run_in_threadpool(_registra)
    except OAuthError as exc:
        session.rollback()
        return _oauth_error(exc)
    logger.info("oauth_cliente_registrado", nome=corpo.get("client_name"))
    return JSONResponse(status_code=201, content=corpo, headers=_SEM_CACHE)


@router.post("/revoke", include_in_schema=False)
def revoke(
    request: Request,
    token: Optional[str] = Form(None),
    token_type_hint: Optional[str] = Form(None),  # noqa: ARG001 — aceito e ignorado (RFC 7009 §2.1)
    client_id: Optional[str] = Form(None),
    client_secret: Optional[str] = Form(None),
    session: Session = Depends(get_session),
):
    _habilitado()
    bloqueio = _limite(request)
    if bloqueio is not None:
        return bloqueio
    try:
        cliente = _cliente_da_requisicao(session, request, client_id, client_secret)
        tokens.revoke_token(session, client=cliente, token=token)
    except OAuthError as exc:
        session.rollback()
        return _oauth_error(exc)
    session.commit()
    # 200 SEMPRE (RFC 7009 §2.2): responder diferente para token inexistente
    # diria a quem testa tokens quais existem.
    return JSONResponse(content={}, headers=_SEM_CACHE)


# --- Consentimento (SPA) -----------------------------------------------------------

class ConsentScopeRead(BaseModel):
    scope: str
    label: str
    description: str
    required: bool


class ConsentClientRead(BaseModel):
    #: Como o APLICATIVO se apresenta — dado não confiável, rotulado como tal na tela.
    name: str
    #: `cimd` (identificado por URL) | `dcr` (registrado dinamicamente)
    kind: str
    #: Host do documento CIMD (quem é o cliente, verificado por HTTPS).
    client_host: Optional[str] = None
    #: Para onde o código vai — o dado que a pessoa precisa ver (MCP spec).
    redirect_host: str
    #: Redirect só em localhost: app no próprio computador (terminal/IDE).
    loopback_only: bool


class ConsentAccountRead(BaseModel):
    name: str
    email: str


class ConsentRequestRead(BaseModel):
    client: ConsentClientRead
    account: ConsentAccountRead
    scopes: List[ConsentScopeRead]


class ConsentDecisionRequest(BaseModel):
    request: str = Field(min_length=1, max_length=8192)
    scopes: List[str] = Field(default_factory=list, max_length=len(escopos.ALL_SCOPES))


class ConsentDenyRequest(BaseModel):
    request: str = Field(min_length=1, max_length=8192)


class ConsentDecisionRead(BaseModel):
    redirect_to: str


def _pedido_ou_400(handle: str) -> authorization.AuthorizationRequest:
    try:
        return authorization.read_request_handle(handle)
    except OAuthError as exc:
        raise HTTPException(status_code=400, detail=exc.description)


@router.get("/consent", response_model=ConsentRequestRead)
def consent_details(
    request: str = Query(..., min_length=1, max_length=8192),
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """O que a tela de consentimento mostra: quem pede, para onde vai, o quê."""
    _habilitado()
    pedido = _pedido_ou_400(request)
    try:
        cliente = clients.get_client(session, pedido.client_id)
    except OAuthError as exc:
        raise HTTPException(status_code=400, detail=exc.description)
    from urllib.parse import urlsplit

    redirect_host = urlsplit(pedido.redirect_uri).hostname or pedido.redirect_uri
    return ConsentRequestRead(
        client=ConsentClientRead(
            name=cliente.client_name,
            kind=cliente.kind,
            client_host=urlsplit(cliente.client_id).hostname if cliente.kind == "cimd" else None,
            redirect_host=redirect_host,
            loopback_only=all(clients.is_loopback(u) for u in cliente.redirect_uris),
        ),
        account=ConsentAccountRead(name=current_user.name, email=current_user.email),
        scopes=[
            ConsentScopeRead(
                scope=s,
                label=escopos.info(s).label,
                description=escopos.info(s).description,
                required=escopos.info(s).required,
            )
            for s in pedido.scopes
        ],
    )


@router.post("/consent/approve", response_model=ConsentDecisionRead)
def consent_approve(
    body: ConsentDecisionRequest,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    _habilitado()
    pedido = _pedido_ou_400(body.request)
    try:
        destino = authorization.approve(
            session, pedido=pedido, user=current_user, approved_scopes=body.scopes,
        )
    except OAuthError as exc:
        session.rollback()
        raise HTTPException(status_code=400, detail=exc.description)
    session.commit()
    logger.info("oauth_consentimento_aprovado", user_id=current_user.id, client=pedido.client_id[:80])
    return ConsentDecisionRead(redirect_to=destino)


@router.post("/consent/deny", response_model=ConsentDecisionRead)
def consent_deny(
    body: ConsentDenyRequest,
    current_user: User = Depends(get_current_user),
):
    _habilitado()
    pedido = _pedido_ou_400(body.request)
    logger.info("oauth_consentimento_negado", user_id=current_user.id)
    return ConsentDecisionRead(redirect_to=authorization.deny(pedido))
