"""Administração do SITE (ADR 0026).

Tudo aqui é metadado: contagem, tamanho, data, papel, configuração. Nenhuma rota
deste módulo devolve valor de lançamento, saldo, limite de cartão ou salário de
outra pessoa, e `tests/security/test_admin_sem_vazamento_financeiro.py` existe
para reprovar quem tentar. O superadministrador opera o servidor; a vida
financeira de cada um continua sendo dela (ADRs 0018 e 0021).

As travas de papel são a outra metade do arquivo, e vieram de cicatriz: na Onda
10 um rebaixamento de admin AMPLIAVA a visão de quem era rebaixado. Toda mudança
de papel aqui passa por `_assert_pode_mexer_em`, que responde a duas perguntas
separadas — "quem manda em quem" e "o site continua administrável depois disto".
"""
from datetime import datetime, UTC
from typing import Any, Dict, List, Optional

import structlog
from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import update
from sqlmodel import Session, select

from app.api.deps import require_platform_role
from app.api.routes.auth import get_current_user
from app.core.config import settings
from app.db.session import get_session
from app.models.audit import ActionType, AuditLog
from app.models.refresh_session import RefreshSession
from app.models.registration_invite import RegistrationInvite
from app.models.user import PlatformRole, User, platform_level
from app.models.workspace import InviteStatus
from app.services import admin_metrics, app_settings, registration_service
from app.services.audit_service import AuditService
from app.services.email_service import EmailService

logger = structlog.get_logger("app.admin")

router = APIRouter(prefix="/admin", tags=["admin"])

AdminDep = Depends(require_platform_role(PlatformRole.admin))


def _colecao(alvo: APIRouter, metodo: str, caminho: str, **kwargs):
    """Registra a rota de coleção COM e SEM barra final, sem redirecionar.

    Mesmo motivo dos outros roteadores de coleção (`me_accounts`, `me_cards`,
    `me_financing`, `me_income`): o redirecionamento automático do Starlette
    responde 307, e nesse salto o **cookie de sessão não acompanha** — a URL com
    a barra "errada" devolve 401 em vez de funcionar.
    """
    def decorador(func):
        for p in (caminho, caminho + "/"):
            getattr(alvo, metodo)(
                p, **({**kwargs, "include_in_schema": False} if p.endswith("/") else kwargs)
            )(func)
        return func
    return decorador


# --------------------------------------------------------------------------
# Trilha
# --------------------------------------------------------------------------

def _registra(
    db: Session,
    request: Request,
    ator: User,
    acao: ActionType,
    recurso: str,
    recurso_id: Optional[int],
    detalhes: Dict[str, Any],
) -> None:
    """Toda ação administrativa entra na trilha.

    Sem exceção e sem depender de o chamador lembrar: poder que não deixa rastro
    é o que transforma uma conta comprometida numa investigação sem respostas.
    """
    AuditService.log_action(
        db,
        action=acao,
        user_id=ator.id,
        resource_type=recurso,
        resource_id=recurso_id,
        new_values=detalhes,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )


# --------------------------------------------------------------------------
# Visão geral, saúde e auditoria
# --------------------------------------------------------------------------

@router.get("/overview")
def overview(
    db: Session = Depends(get_session),
    _: User = AdminDep,
) -> Dict[str, Any]:
    return admin_metrics.visao_geral(db)


@router.get("/health")
def health(
    db: Session = Depends(get_session),
    _: User = AdminDep,
) -> Dict[str, Any]:
    return admin_metrics.saude(db)


class AuditRead(BaseModel):
    id: int
    action: ActionType
    resource_type: Optional[str]
    resource_id: Optional[int]
    user_id: Optional[int]
    workspace_id: Optional[int]
    ip_address: Optional[str]
    created_at: datetime


@router.get("/audit", response_model=List[AuditRead])
def audit_global(
    db: Session = Depends(get_session),
    _: User = AdminDep,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    action: Optional[ActionType] = None,
    resource_type: Optional[str] = None,
    user_id: Optional[int] = None,
):
    """Trilha do site inteiro.

    O `/workspaces/{id}/audit` que já existia responde por uma casa e exige ser
    admin DELA. Este responde pelo servidor — login, mudança de papel, alteração
    de configuração — e é o único lugar onde essas linhas aparecem.

    `old_values`/`new_values` NÃO saem aqui: são JSON livre gravado pelos
    listeners a partir do recurso auditado, e num lançamento isso inclui o valor.
    A trilha administrativa mostra QUEM fez O QUÊ em QUE recurso; o conteúdo do
    que mudou continua atrás da porta do workspace.
    """
    stmt = select(AuditLog).order_by(AuditLog.created_at.desc())
    if action:
        stmt = stmt.where(AuditLog.action == action)
    if resource_type:
        stmt = stmt.where(AuditLog.resource_type == resource_type)
    if user_id:
        stmt = stmt.where(AuditLog.user_id == user_id)
    return db.exec(stmt.limit(limit).offset(offset)).all()


# --------------------------------------------------------------------------
# Usuários
# --------------------------------------------------------------------------

@router.get("/users")
def list_users(
    db: Session = Depends(get_session),
    _: User = AdminDep,
    busca: Optional[str] = Query(None, max_length=100),
    incluir_removidos: bool = False,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> Dict[str, Any]:
    return admin_metrics.lista_de_usuarios(
        db, busca=busca, incluir_removidos=incluir_removidos, limite=limit, offset=offset
    )


class UserPatch(BaseModel):
    is_active: Optional[bool] = None
    platform_role: Optional[PlatformRole] = None


def _get_alvo(db: Session, user_id: int) -> User:
    alvo = db.get(User, user_id)
    if alvo is None:
        raise HTTPException(status_code=404, detail="Usuário não encontrado")
    return alvo


def _conta_superadmins(db: Session, exceto: Optional[int] = None) -> int:
    """Quantos superadministradores ativos existem — SERIALIZANDO a contagem.

    Sem o `UPDATE` abaixo isto era um SELECT solto antes de um UPDATE, e dois
    rebaixamentos simultâneos de superadmins DIFERENTES passavam os dois: cada
    requisição contava o outro, cada uma via um restante, e o site terminava sem
    superadministrador nenhum — o estado exato que `_assert_pode_mexer_em` existe
    para impedir, com a saída sendo SQL dentro do container.

    **Por que um `UPDATE` que não muda nada.** É a mesma trava do
    `CreditCardService.pay_statement`: a PRIMEIRA escrita da operação, tocando as
    linhas que a decisão vai ler. `SELECT ... FOR UPDATE` seria mais direto e é o
    que a leitura sugere, mas o dialeto SQLite o ignora em silêncio — a proteção
    sumiria em dev e no leg SQLite do CI, e sobraria só no Postgres. Um `UPDATE`
    condicional sobre o alvo também não resolveria: a condição "existe outro
    superadmin" seria avaliada contra o snapshot commitado, onde o outro AINDA é
    superadmin. É a diferença entre um contador (que o incremento atômico
    resolve) e uma invariante sobre VÁRIAS linhas.

    A trava cobre TODAS as linhas de superadmin, e o `exceto` é aplicado depois,
    em Python, de propósito: travar já excluindo o alvo faz cada requisição
    travar um conjunto DIFERENTE (a de A tranca B, a de B tranca A), os conjuntos
    não se cruzam e nada é serializado. Travando o conjunto inteiro, a segunda
    requisição espera a primeira e relê — no READ COMMITTED o Postgres reavalia a
    linha depois do lock — enxergando então o rebaixamento que acabou de
    acontecer.

    `updated_at` das outras linhas muda de carona. Não é exibido em lugar nenhum
    (nem em `admin_metrics`, nem no `UserRead`, nem na tela), e o `UPDATE` via
    Core não passa pelos mapper events, então também não gera AuditLog espúrio —
    o mesmo cuidado do `publish_event`.
    """
    condicoes = (
        User.platform_role == PlatformRole.superadmin,
        User.deleted_at.is_(None),
        User.is_active.is_(True),
    )
    db.execute(update(User).where(*condicoes).values(updated_at=datetime.now(UTC)))
    ids = db.exec(select(User.id).where(*condicoes)).all()
    return len([i for i in ids if i != exceto])


def _assert_pode_mexer_em(db: Session, ator: User, alvo: User, *, removendo_poder: bool) -> None:
    """As duas perguntas que toda ação sobre um usuário precisa responder.

    **1. Quem manda em quem.** Um `admin` não age sobre um `superadmin`. Sem esta
    linha, qualquer admin rebaixaria o dono do site e assumiria o lugar — a
    escalada de privilégio mais direta que existe, e ela caberia num único PATCH.

    **2. O site continua administrável.** Rebaixar, desativar ou excluir o ÚLTIMO
    superadmin ativo deixa o sistema sem ninguém que possa promover alguém: a
    configuração vira imutável, o cadastro por convite não tem quem emita
    convite, e a saída seria SQL na mão dentro do container. Vale inclusive
    quando o ator é o próprio alvo — "eu sei o que estou fazendo" é exatamente o
    que a pessoa pensa antes de se trancar do lado de fora.
    """
    e_superadmin_alvo = alvo.platform_role == PlatformRole.superadmin

    if e_superadmin_alvo and ator.platform_role != PlatformRole.superadmin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Apenas um superadministrador pode alterar outro superadministrador.",
        )

    if removendo_poder and e_superadmin_alvo and _conta_superadmins(db, exceto=alvo.id) == 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Este é o último superadministrador ativo. Promova outra pessoa "
                "antes de rebaixar, desativar ou remover esta conta — sem "
                "superadministrador o site não pode mais ser configurado."
            ),
        )


@router.patch("/users/{user_id}")
def patch_user(
    user_id: int,
    dados: UserPatch,
    request: Request,
    db: Session = Depends(get_session),
    ator: User = AdminDep,
) -> Dict[str, Any]:
    alvo = _get_alvo(db, user_id)

    # Promover a superadmin é privilégio de superadmin: um admin que pudesse
    # criar superadmins seria, na prática, superadmin.
    if dados.platform_role == PlatformRole.superadmin and ator.platform_role != PlatformRole.superadmin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Apenas um superadministrador pode promover outro superadministrador.",
        )

    desativando = dados.is_active is False
    # Desativar a PRÓPRIA conta é o único ato aqui que não tem volta pelas mãos
    # de quem o pratica: a sessão cai junto e o login seguinte é recusado por
    # conta inativa, então a saída passa a depender de outro administrador — ou
    # de SQL no container, se não houver outro. Rebaixar a si mesmo continua
    # permitido (a trava do último superadmin cobre o caso perigoso): quem se
    # rebaixa segue usando o sistema, só perde a área administrativa.
    if desativando and alvo.id == ator.id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Você não pode desativar a própria conta: perderia o acesso na "
                "mesma hora e dependeria de outro administrador para voltar."
            ),
        )

    perdendo_papel = (
        dados.platform_role is not None
        and platform_level(dados.platform_role) < platform_level(alvo.platform_role)
    )
    _assert_pode_mexer_em(db, ator, alvo, removendo_poder=perdendo_papel or desativando)

    antes = {"is_active": alvo.is_active, "platform_role": alvo.platform_role}
    if dados.is_active is not None:
        alvo.is_active = dados.is_active
    if dados.platform_role is not None:
        alvo.platform_role = dados.platform_role
    db.add(alvo)

    # Desativar sem derrubar a sessão não desativa nada: o refresh token vale por
    # dias e o access token continua sendo aceito até expirar. A conta "inativa"
    # seguiria usando o sistema normalmente até o navegador ser fechado.
    if desativando:
        _revoga_sessoes(db, alvo)

    db.commit()
    db.refresh(alvo)
    _registra(
        db, request, ator, ActionType.update, "User", alvo.id,
        {"antes": antes, "depois": {"is_active": alvo.is_active, "platform_role": alvo.platform_role}},
    )
    return {
        "id": alvo.id,
        "name": alvo.name,
        "email": alvo.email,
        "is_active": alvo.is_active,
        "platform_role": alvo.platform_role,
    }


def _revoga_sessoes(db: Session, alvo: User) -> int:
    """Revoga as sessões vivas. Só `flush` — o commit é do chamador."""
    agora = datetime.now(UTC)
    sessoes = db.exec(
        select(RefreshSession).where(
            RefreshSession.user_id == alvo.id,
            RefreshSession.revoked_at.is_(None),
        )
    ).all()
    for sessao in sessoes:
        sessao.revoked_at = agora
        db.add(sessao)
    db.flush()
    return len(sessoes)


@router.post("/users/{user_id}/revoke-sessions")
def revoke_sessions(
    user_id: int,
    request: Request,
    db: Session = Depends(get_session),
    ator: User = AdminDep,
) -> Dict[str, Any]:
    """Derruba todas as sessões de alguém — o botão de "perdi o notebook"."""
    alvo = _get_alvo(db, user_id)
    # Não é remoção de poder: a pessoa continua com o papel e pode entrar de
    # novo. Só exige a hierarquia, para um admin não incomodar um superadmin.
    _assert_pode_mexer_em(db, ator, alvo, removendo_poder=False)

    quantas = _revoga_sessoes(db, alvo)
    db.commit()
    _registra(db, request, ator, ActionType.update, "RefreshSession", alvo.id,
              {"revogadas": quantas, "user_id": alvo.id})
    return {"revogadas": quantas}


@router.delete("/users/{user_id}")
def delete_user(
    user_id: int,
    request: Request,
    db: Session = Depends(get_session),
    ator: User = AdminDep,
) -> Dict[str, Any]:
    """Exclusão LÓGICA (`deleted_at`), nunca física.

    O registro continua sendo referência de FK para lançamentos, anexos,
    memberships e linhas de auditoria. Apagar a linha de verdade quebraria a
    trilha — que existe justamente para sobreviver ao recurso auditado — e, no
    Postgres, esbarraria nas FKs antes disso.
    """
    alvo = _get_alvo(db, user_id)
    if alvo.id == ator.id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Você não pode remover a própria conta por aqui.",
        )
    _assert_pode_mexer_em(db, ator, alvo, removendo_poder=True)

    alvo.deleted_at = datetime.now(UTC)
    alvo.is_active = False
    db.add(alvo)
    _revoga_sessoes(db, alvo)
    db.commit()
    _registra(db, request, ator, ActionType.delete, "User", alvo.id, {"email": alvo.email})
    return {"status": "removido", "id": alvo.id}


# --------------------------------------------------------------------------
# Configuração
# --------------------------------------------------------------------------

class SettingsPut(BaseModel):
    valores: Dict[str, Any]


@router.get("/settings")
def get_settings(
    db: Session = Depends(get_session),
    _: User = AdminDep,
) -> Dict[str, Any]:
    """Valores vigentes + de onde cada um vem.

    `sobrescrito` é o que a tela precisa para não mentir: sem ele, um número que
    ainda acompanha o `.env` aparece igual a um gravado no banco, e o operador
    muda a variável de ambiente esperando efeito que não vem.
    """
    efetivos = app_settings.get_all(db)
    return {
        "valores": efetivos,
        "chaves": [
            {
                "nome": chave.nome,
                "descricao": chave.descricao,
                "origem_ambiente": chave.env,
                "sobrescrito": app_settings.is_overridden(db, chave.nome),
            }
            for chave in app_settings.CHAVES.values()
        ],
        "limite_nginx_bytes": app_settings.NGINX_BODY_LIMIT_BYTES,
    }


@router.put("/settings")
def put_settings(
    dados: SettingsPut,
    request: Request,
    db: Session = Depends(get_session),
    ator: User = AdminDep,
) -> Dict[str, Any]:
    """Grava configurações. Tudo ou nada.

    Validar todas antes de escrever qualquer uma evita o estado meio-aplicado:
    um formulário com seis campos em que o quarto é inválido não pode deixar os
    três primeiros gravados e o resto não — o operador leria a mensagem de erro e
    concluiria, errado, que nada mudou.
    """
    desconhecidas = set(dados.valores) - set(app_settings.CHAVES)
    if desconhecidas:
        raise HTTPException(
            status_code=422,
            detail=f"Configuração desconhecida: {', '.join(sorted(desconhecidas))}",
        )

    erros = {}
    for chave, valor in dados.valores.items():
        try:
            app_settings.CHAVES[chave].valida(valor)
        except ValueError as exc:
            erros[chave] = str(exc)
    if erros:
        raise HTTPException(status_code=422, detail={"campos": erros})

    antes = {chave: app_settings.get(db, chave) for chave in dados.valores}
    for chave, valor in dados.valores.items():
        app_settings.set_value(db, chave, valor, user_id=ator.id)
    db.commit()
    # Segunda invalidação, e ela é a que fecha a corrida: `set_value` invalida
    # ANTES do commit, e nessa janela uma requisição concorrente lê o valor
    # antigo do banco e o cacheia — onde ficaria até o processo reiniciar.
    # Depois do commit a leitura seguinte é garantidamente a nova.
    app_settings.invalidate_cache()

    _registra(db, request, ator, ActionType.update, "AppSetting", None,
              {"antes": antes, "depois": dados.valores})
    return {"valores": app_settings.get_all(db)}


class TestEmail(BaseModel):
    para: EmailStr


@router.post("/settings/test-email")
def test_email(
    dados: TestEmail,
    _: User = AdminDep,
) -> Dict[str, Any]:
    """Dispara um e-mail de teste e devolve o erro NA TELA.

    Até aqui, descobrir que o SMTP estava mal configurado exigia provocar um
    convite de verdade e ler `docker compose logs backend` — quem não tem acesso
    ao host simplesmente não descobria, e o sintoma era "o convite não chegou",
    indistinguível de spam.
    """
    if not settings.SMTP_HOST:
        return {
            "enviado": False,
            "configurado": False,
            "detalhe": (
                "SMTP não configurado: os links de convite e de recuperação de "
                "senha aparecem no log do backend."
            ),
        }
    try:
        EmailService.send(
            dados.para,
            "Teste de configuração — Controle Financeiro",
            "Se você recebeu este e-mail, o envio está funcionando.",
            raise_on_error=True,
        )
        return {"enviado": True, "configurado": True, "detalhe": None}
    except Exception as exc:
        logger.warning("teste_de_email_falhou", erro=str(exc))
        return {"enviado": False, "configurado": True, "detalhe": str(exc)}


# --------------------------------------------------------------------------
# Convites de cadastro
# --------------------------------------------------------------------------

class InviteCreate(BaseModel):
    email: Optional[EmailStr] = None
    max_uses: Optional[int] = Field(None, ge=1, le=1000)


class InviteRead(BaseModel):
    id: int
    email: Optional[str]
    token: str
    status: InviteStatus
    expires_at: datetime
    max_uses: Optional[int]
    uses: int
    created_by_user_id: Optional[int]
    accepted_by_user_id: Optional[int]
    created_at: datetime
    link: str


def _para_leitura(convite: RegistrationInvite) -> Dict[str, Any]:
    """Materializa o convite num dicionário ANTES de qualquer commit posterior.

    `AuditService.log_action` faz `commit()`, e o commit EXPIRA todas as
    instâncias da sessão. Chamar isto depois de auditar devolvia um corpo com
    `link` e mais nada — os outros campos viravam `Field required` na validação
    da resposta. Por isso todo chamador monta a leitura primeiro e registra a
    trilha depois.
    """
    return {
        "id": convite.id,
        "email": convite.email,
        "token": convite.token,
        "status": convite.status,
        "expires_at": convite.expires_at,
        "max_uses": convite.max_uses,
        "uses": convite.uses,
        "created_by_user_id": convite.created_by_user_id,
        "accepted_by_user_id": convite.accepted_by_user_id,
        "created_at": convite.created_at,
        "link": registration_service.link_do_convite(convite),
    }


@_colecao(router, "get", "/registration-invites", response_model=List[InviteRead])
def list_invites(
    db: Session = Depends(get_session),
    _: User = AdminDep,
    apenas_pendentes: bool = False,
    limit: int = Query(100, ge=1, le=500),
):
    stmt = select(RegistrationInvite).order_by(RegistrationInvite.created_at.desc())
    if apenas_pendentes:
        stmt = stmt.where(RegistrationInvite.status == InviteStatus.pending)
    return [_para_leitura(c) for c in db.exec(stmt.limit(limit)).all()]


@_colecao(router, "post", "/registration-invites", response_model=InviteRead, status_code=201)
def create_invite(
    dados: InviteCreate,
    request: Request,
    db: Session = Depends(get_session),
    ator: User = AdminDep,
):
    convite = registration_service.cria_convite(
        db, ator, email=dados.email, max_uses=dados.max_uses
    )
    db.commit()
    db.refresh(convite)
    resposta = _para_leitura(convite)

    if dados.email:
        EmailService.send_registration_invite(
            dados.email, ator.name, resposta["link"]
        )
    _registra(db, request, ator, ActionType.create, "RegistrationInvite", resposta["id"],
              {"email": dados.email, "max_uses": dados.max_uses})
    return resposta


@router.delete("/registration-invites/{invite_id}")
def revoke_invite(
    invite_id: int,
    request: Request,
    db: Session = Depends(get_session),
    ator: User = AdminDep,
) -> Dict[str, Any]:
    convite = db.get(RegistrationInvite, invite_id)
    if convite is None:
        raise HTTPException(status_code=404, detail="Convite não encontrado")
    convite.status = InviteStatus.revoked
    db.add(convite)
    db.commit()
    _registra(db, request, ator, ActionType.delete, "RegistrationInvite", invite_id, {})
    return {"status": "revogado", "id": invite_id}


# --------------------------------------------------------------------------
# Convite emitido por usuário COMUM — fora do prefixo /admin de propósito
# --------------------------------------------------------------------------

me_invites_router = APIRouter(prefix="/me/registration-invites", tags=["admin"])


@_colecao(me_invites_router, "get", "", response_model=List[InviteRead])
def meus_convites(
    db: Session = Depends(get_session),
    atual: User = Depends(get_current_user),
):
    convites = db.exec(
        select(RegistrationInvite)
        .where(RegistrationInvite.created_by_user_id == atual.id)
        .order_by(RegistrationInvite.created_at.desc())
        .limit(50)
    ).all()
    return [_para_leitura(c) for c in convites]


@_colecao(me_invites_router, "post", "", response_model=InviteRead, status_code=201)
def convidar(
    request: Request,
    dados: InviteCreate = Body(default_factory=InviteCreate),
    db: Session = Depends(get_session),
    atual: User = Depends(get_current_user),
):
    """Quem já está dentro chama alguém.

    Sujeito a `who_can_invite` e à cota mensal (ADR 0026) — sem a cota, o
    "cadastro por convite" seria cadastro aberto com um passo a mais para quem
    quisesse abusar. `max_uses` é ignorado aqui de propósito: convite de link
    com muitos usos é ferramenta de administrador.
    """
    registration_service.assert_pode_convidar(db, atual)
    convite = registration_service.cria_convite(db, atual, email=dados.email)
    db.commit()
    db.refresh(convite)
    resposta = _para_leitura(convite)

    if dados.email:
        EmailService.send_registration_invite(dados.email, atual.name, resposta["link"])
    _registra(db, request, atual, ActionType.create, "RegistrationInvite",
              resposta["id"], {"email": dados.email})
    return resposta
