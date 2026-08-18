import hashlib
import secrets
from datetime import timedelta
from typing import List, Optional
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, HTTPException, status, Request, Response, Cookie
from fastapi.responses import RedirectResponse
from sqlmodel import Session, select
from app.core.config import settings
from app.db.session import get_session
from app.models.user import PlatformRole, User
from datetime import datetime, UTC
from app.models.workspace import (
    FinancialAccess,
    Workspace,
    WorkspaceMembership,
    WorkspaceRole,
    WorkspaceInvite,
    InviteStatus,
    role_level,
)
from app.domain.query_policy import resolve_personal_currency
from app.schemas.user import UserResponse
from app.core.security import (
    verify_password,
    verify_and_upgrade_password,
    get_password_hash,
    spend_dummy_verification,
)
from app.core.jwt import create_access_token, create_purpose_token, decode_token
from app.core.cookies import (
    set_auth_cookies,
    clear_auth_cookies,
    set_oauth_state_cookie,
    clear_oauth_state_cookie,
)
from app.services.session_service import (
    start_session,
    rotate_session,
    revoke_session,
    revoke_all_user_sessions,
    SessionError,
)
from app.core.context import set_current_user_id
from app.core.rate_limit import rate_limit_account, rate_limit_auth
from app.models.audit import ActionType
from app.services.audit_service import AuditService
from app.services.email_service import EmailService
from app.services.category_service import seed_default_categories
from app.services.event_service import publish_event
from app.services.membership_service import ensure_membership
from app.models.notification import NotificationType
from app.services.notification_service import notify
from app.services import app_settings
from app.services.registration_service import assert_pode_cadastrar, consome_convite
from pydantic import BaseModel, Field

from app.schemas.common import NormalizedEmail, NormalizedEmailStr, normalize_email

from app.models.income import Income
from app.models.credit_card import CreditCard
from decimal import Decimal

router = APIRouter(prefix="/auth", tags=["auth"])

# Sentinela para contas criadas via OAuth (sem senha local). Nunca é um hash válido.
OAUTH_PASSWORD_SENTINEL = "!oauth-google"

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"


def _password_fingerprint(password_hash: str) -> str:
    """Fingerprint do hash atual — invalida tokens de reset após a troca de senha."""
    return hashlib.sha256(password_hash.encode()).hexdigest()[:16]


ACCOUNT_DISABLED_DETAIL = "Conta desativada"


def _ensure_account_enabled(user: User) -> None:
    """Recusa emitir sessão para conta desativada/excluída (mesma regra do
    get_current_user, aplicada também na PORTA DE ENTRADA)."""
    if user.deleted_at is not None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=ACCOUNT_DISABLED_DETAIL,
        )


def _user_workspace_ids(db: Session, user_id: int) -> List[int]:
    """Workspaces em que o usuário é membro — alvo dos eventos de perfil."""
    return list(db.exec(
        select(WorkspaceMembership.workspace_id).where(
            WorkspaceMembership.user_id == user_id
        )
    ).all())


def _setup_default_workspace(db: Session, user: User) -> Workspace:
    """Cria o workspace pessoal padrão com papel de owner para um usuário novo.

    Só `flush` — o commit é do chamador (ADR 0010). Antes eram DOIS commits aqui
    (mais um no `register` e outro em `_resolve_pending_invites`): se o seed de
    categorias falhasse, o usuário ficava criado e sem workspace, e não havia
    rollback capaz de desfazer o cadastro.
    """
    # "Meu espaço", e não mais "Meu Workspace": a interface passou a chamar o
    # contêiner de ESPAÇO em todo lugar, e a camada que não pertence a espaço
    # nenhum (ADR 0021) passou a se chamar "Pessoal". O nome antigo colidia de
    # frente com a antiga seção "Meu" — a pessoa via "Meu" na barra lateral e
    # "Meu Workspace" no seletor querendo dizer coisas OPOSTAS: um é o que não
    # tem espaço, o outro é um espaço.
    #
    # Só vale para contas NOVAS. Renomear as existentes seria reescrever um dado
    # que a pessoa pode ter mudado à mão, e o nome é editável em Configurações.
    workspace = Workspace(
        name="Meu espaço",
        description="Espaço pessoal criado automaticamente",
        created_by_user_id=user.id
    )
    db.add(workspace)
    db.flush()

    membership = WorkspaceMembership(
        user_id=user.id,
        workspace_id=workspace.id,
        role=WorkspaceRole.owner,
        financial_access=FinancialAccess.full_workspace,
    )
    db.add(membership)
    seed_default_categories(db, workspace.id)
    db.flush()
    return workspace


def _resolve_pending_invites(
    db: Session, user: User, accept_token: Optional[str] = None
) -> None:
    """Resolve os convites por e-mail pendentes de um usuário RECÉM-CRIADO.

    Só entra no workspace do convite cujo **token acompanhou o cadastro** — é o
    link que `create_invite` monta (`/register?invite=<token>`), ou seja, a
    pessoa clicou no convite e ele é o consentimento. Os demais convites
    pendentes para o mesmo e-mail viram NOTIFICAÇÃO, para aceitar ou recusar
    depois.

    Antes, cadastrar-se aceitava TODOS os convites pendentes para aquele e-mail.
    Quem se cadastrasse por conta própria caía dentro do workspace de um
    desconhecido que soubesse seu endereço — e passava a ver (e a ser visto nas)
    finanças de outra família sem ter aceitado nada. A E15 já tinha corrigido
    isso para quem JÁ tinha conta (`members.create_invite`); o caminho de
    registro tinha ficado para trás.
    """
    now = datetime.now(UTC)
    invites = db.exec(
        select(WorkspaceInvite).where(
            WorkspaceInvite.email == user.email,
            WorkspaceInvite.status == InviteStatus.pending,
        )
    ).all()
    if not invites:
        return

    for invite in invites:
        expires_at = invite.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=UTC)
        if expires_at < now:
            continue

        if accept_token and invite.token == accept_token:
            if ensure_membership(
                db,
                invite.workspace_id,
                user.id,
                invite.role,
                financial_access=invite.financial_access,
            ):
                publish_event(db, invite.workspace_id, "member.added", "member", user.id, user.id)
            invite.status = InviteStatus.accepted
            db.add(invite)
            continue

        workspace = db.get(Workspace, invite.workspace_id)
        inviter = db.get(User, invite.invited_by_user_id) if invite.invited_by_user_id else None
        notify(
            db,
            user_id=user.id,
            type=NotificationType.workspace_invite,
            title=(
                f"{inviter.name} convidou você para \"{workspace.name}\""
                if inviter and workspace
                else "Você tem um convite para um workspace"
            ),
            body=(
                # A coluna é String(20): vindo do banco, `role` pode ser str crua
                # em vez do enum — daí o getattr em vez de `.value` direto.
                f"Você foi convidado como {getattr(invite.role, 'value', invite.role)}. "
                "Aceite para começar a ver e lançar as despesas compartilhadas."
            ),
            workspace_id=invite.workspace_id,
            workspace_name=workspace.name if workspace else None,
            invite_token=invite.token,
        )
    db.flush()

async def get_current_user(
    access_token: Optional[str] = Cookie(None),
    db: Session = Depends(get_session)
) -> User:
    if not access_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Não autenticado"
        )
    try:
        payload = decode_token(access_token)
        if payload.get("token_type") != "access":
            raise ValueError("Tipo de token inválido")
        user_id_str: str = payload.get("sub")
        if user_id_str is None:
            raise ValueError("Token sem sub")
        user_id = int(user_id_str)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token inválido ou expirado"
        )
    
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Usuário não encontrado"
        )
    # Conta desativada/excluída perde acesso imediatamente (não espera o token expirar)
    if user.deleted_at is not None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Conta desativada"
        )

    # Set the user ID in the context for automated auditing
    set_current_user_id(user.id)

    return user

class LoginRequest(BaseModel):
    email: NormalizedEmailStr
    password: str = Field(..., max_length=72)

class RegisterRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    email: NormalizedEmail
    password: str = Field(..., min_length=6, max_length=72)
    # Token do link `/register?invite=<token>`: é o CONSENTIMENTO de entrar
    # naquele workspace. Sem ele, convites pendentes viram só notificação.
    invite_token: Optional[str] = None

class OnboardingRequest(BaseModel):
    # Opcional: o onboarding cria a RENDA e o CARTÃO da pessoa, então o destino
    # natural é o workspace pessoal dela. Sem o campo, a rota resolve sozinha —
    # ver _resolve_onboarding_workspace.
    workspace_id: Optional[int] = None
    salary: Decimal
    credit_card_name: Optional[str] = None
    credit_card_limit: Optional[Decimal] = None
    credit_card_closing_day: Optional[int] = Field(None, ge=1, le=31)


def _resolve_onboarding_workspace(db: Session, user: User, requested_id: Optional[int]) -> int:
    """Workspace de destino do onboarding: SEMPRE um do qual o usuário é owner.

    Ser membro não basta. Quem se cadastra por um convite
    (`/register?invite=<token>`) nasce com DOIS workspaces — o pessoal e o
    compartilhado — e o cliente mandava o `currentWorkspaceId`, escolhido como
    `workspaces[0]` de uma listagem sem ordenação. Ou seja: a primeira tela do
    app podia gravar o salário da pessoa dentro do workspace de outra família,
    de forma não determinística.
    """
    memberships = db.exec(
        select(WorkspaceMembership)
        .where(WorkspaceMembership.user_id == user.id)
        .order_by(WorkspaceMembership.workspace_id)
    ).all()

    if requested_id is not None:
        alvo = next((m for m in memberships if m.workspace_id == requested_id), None)
        if not alvo:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Você não é membro deste workspace"
            )
        if role_level(alvo.role) < role_level(WorkspaceRole.owner):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    "O onboarding cria a sua renda e o seu cartão — use o seu "
                    "próprio workspace, não um compartilhado."
                ),
            )
        return requested_id

    proprio = next(
        (m for m in memberships if role_level(m.role) >= role_level(WorkspaceRole.owner)),
        None,
    )
    if not proprio:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Nenhum workspace próprio para concluir o onboarding"
        )
    return proprio.workspace_id


@router.post("/onboarding")
async def finish_onboarding(
    data: OnboardingRequest,
    db: Session = Depends(get_session),
    current_user: User = Depends(get_current_user)
):
    # 0. Renda e cartão do onboarding são PESSOAIS (ADR 0021): não vão para
    # workspace nenhum, então não há IDOR de workspace a evitar aqui nem evento a
    # publicar — o canal de tempo real é por sala de workspace e isto não é dado
    # de workspace. `data.workspace_id` continua sendo validado por compatibilidade
    # com o formulário atual, que ainda o envia.
    if data.workspace_id is not None:
        _resolve_onboarding_workspace(db, current_user, data.workspace_id)
    # Moeda ausente = a de RELATÓRIO do usuário (nunca "BRL" fixo). Antes vinha da
    # moeda-base do workspace, e o mesmo cadastro nascia em moedas diferentes
    # conforme o workspace por onde o onboarding passasse.
    moeda = resolve_personal_currency(db, current_user.id, None)

    # 1. Create Income (Salary) — pular a etapa não cria renda de valor zero
    if data.salary and data.salary > 0:
        db.add(Income(
            title="Salário Mensal",
            amount=data.salary,
            currency=moeda,
            category="Salary",
            user_id=current_user.id,
        ))

    # 2. Create Credit Card (Optional)
    if data.credit_card_name and data.credit_card_limit:
        db.add(CreditCard(
            name=data.credit_card_name,
            limit=data.credit_card_limit,
            closing_day=data.credit_card_closing_day or 5,
            due_day=((data.credit_card_closing_day or 5) + 10) % 31 or 1,
            currency=moeda,
            owner_user_id=current_user.id,
        ))

    # 3. Mark as onboarded
    current_user.needs_onboarding = False
    db.add(current_user)

    db.commit()
    return {"status": "ok"}

@router.get("/registration-policy")
def registration_policy(db: Session = Depends(get_session)):
    """Se o site aceita cadastro — PÚBLICO, e de propósito (ADR 0026).

    Existe para a tela de cadastro poder dizer "é só por convite" ANTES de a
    pessoa preencher nome, e-mail e senha duas vezes para só então descobrir.
    Também é o que permite a tela de login esconder o link "criar conta" quando
    não há cadastro a fazer.

    Não vaza nada: é exatamente a informação que qualquer pessoa obtém tentando
    se cadastrar uma vez. O que NÃO sai daqui é quem pode convidar, quantos
    convites existem ou qualquer outra configuração — só a porta da frente.

    `primeiro_acesso` é o que torna o deploy novo utilizável PELO NAVEGADOR. A
    janela de bootstrap sempre existiu no `POST /register`, mas a tela escondia o
    formulário sempre que o modo exigia convite — e num site recém-instalado
    ninguém tem convite, nem existe quem o emita. O resultado era o primeiro
    acesso documentado no SETUP.md ser impossível pela interface. O campo não
    revela o endereço do administrador nem permite que outra pessoa entre: quem
    decide continua sendo `_e_o_bootstrap`, que compara o e-mail submetido com o
    `SUPERADMIN_EMAIL`.
    """
    from app.services.app_settings import RegistrationMode
    from app.services.registration_service import janela_de_bootstrap_aberta

    modo = app_settings.get(db, "registration_mode")
    return {
        "mode": modo,
        "aceita_cadastro": modo != RegistrationMode.closed,
        "exige_convite": modo == RegistrationMode.invite_only,
        "primeiro_acesso": janela_de_bootstrap_aberta(db),
    }


@router.post("/register", response_model=UserResponse, dependencies=[Depends(rate_limit_auth)])
async def register(
    register_data: RegisterRequest,
    db: Session = Depends(get_session)
):
    # Portão de cadastro (ADR 0026): aberto, por convite ou fechado. Vem ANTES da
    # checagem de e-mail duplicado de propósito — com o cadastro fechado, quem não
    # tem convite não deve conseguir descobrir quais endereços já existem
    # provocando mensagens de erro diferentes.
    convite, e_bootstrap = assert_pode_cadastrar(
        db, register_data.email, register_data.invite_token
    )

    # Check if user already exists
    existing_user = db.exec(select(User).where(User.email == register_data.email)).first()
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Este email já está cadastrado"
        )

    # Create user — commit ÚNICO no fim (ADR 0010): usuário, workspace pessoal,
    # categorias padrão e a resolução dos convites nascem juntos ou não nascem.
    user = User(
        name=register_data.name,
        email=register_data.email,
        password_hash=get_password_hash(register_data.password),
        # A primeira conta do site, quando é a do `SUPERADMIN_EMAIL`, já nasce
        # com o papel. O `lifespan` também promove a cada boot, mas esperar o
        # próximo reinício deixaria a pessoa sem tela de Admin justamente no
        # momento em que ela precisa configurar o site.
        platform_role=PlatformRole.superadmin if e_bootstrap else PlatformRole.user,
    )
    db.add(user)
    db.flush()

    _setup_default_workspace(db, user)
    _resolve_pending_invites(db, user, accept_token=register_data.invite_token)
    if convite is not None:
        consome_convite(db, convite, user)

    db.commit()
    db.refresh(user)
    return user

@router.post("/login", dependencies=[Depends(rate_limit_auth)])
async def login(
    response: Response,
    login_data: LoginRequest,
    db: Session = Depends(get_session)
):
    # Segundo balde, por CONTA: o balde por IP é contornável com
    # X-Forwarded-For forjado (ver rate_limit_account).
    rate_limit_account(db, login_data.email, "/auth/login")
    user = db.exec(select(User).where(User.email == login_data.email)).first()
    if not user:
        # Gasta o mesmo tempo de um verify() real: email inexistente respondia
        # na hora e email cadastrado demorava, o que enumerava as contas
        spend_dummy_verification()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Email ou senha incorretos"
        )
    if user.password_hash.startswith("!"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Esta conta usa login com Google. Use o botão 'Entrar com Google'."
        )
    ok, upgraded_hash = verify_and_upgrade_password(login_data.password, user.password_hash)
    if not ok:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Email ou senha incorretos"
        )
    # Conta desativada/excluída não emite sessão: antes o login devolvia 200 com
    # cookies e só as requisições SEGUINTES é que davam 401 (get_current_user)
    _ensure_account_enabled(user)

    # Migração transparente do hash legado (pbkdf2/bcrypt → argon2id): acontece
    # no login, sem pedir nada ao usuário. O commit vem do log_action abaixo.
    if upgraded_hash:
        user.password_hash = upgraded_hash
        db.add(user)

    access_token = create_access_token(data={"sub": str(user.id)})
    refresh_token = start_session(db, user.id)  # sessão persistida (SEC-004)

    set_auth_cookies(response, access_token, refresh_token)
    # log_action commita a sessão (a RefreshSession recém-criada persiste junto)
    AuditService.log_action(db, ActionType.login, user_id=user.id, resource_type="User", resource_id=user.id)

    return {"message": "Login realizado com sucesso"}

@router.get("/me", response_model=UserResponse)
async def get_me(current_user: User = Depends(get_current_user)):
    return current_user


class ProfileUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=100)


@router.patch("/me", response_model=UserResponse)
async def update_me(
    data: ProfileUpdate,
    db: Session = Depends(get_session),
    current_user: User = Depends(get_current_user)
):
    renamed = data.name is not None and data.name != current_user.name
    if data.name is not None:
        current_user.name = data.name
    current_user.updated_at = datetime.now(UTC)
    db.add(current_user)
    # O nome aparece na lista de membros, no extrato e no acerto de dívidas de
    # TODOS os workspaces do usuário — quem estiver com a tela aberta precisa
    # ver a troca na hora (inclusive as outras abas de quem renomeou).
    if renamed:
        for workspace_id in _user_workspace_ids(db, current_user.id):
            publish_event(
                db, workspace_id, "member.updated", "member", current_user.id, current_user.id
            )
    db.commit()
    db.refresh(current_user)
    return current_user

@router.post("/logout")
async def logout(
    response: Response,
    db: Session = Depends(get_session),
    access_token: Optional[str] = Cookie(None),
    refresh_token: Optional[str] = Cookie(None),
):
    # Revoga a sessão de refresh (SEC-004): o token copiado deixa de valer
    revoke_session(db, refresh_token)
    db.commit()
    # Auditoria de logout (best-effort: cookie pode já estar expirado)
    try:
        if access_token:
            payload = decode_token(access_token)
            if payload.get("token_type") == "access" and payload.get("sub"):
                user_id = int(payload["sub"])
                AuditService.log_action(db, ActionType.logout, user_id=user_id, resource_type="User", resource_id=user_id)
    except Exception:
        pass
    clear_auth_cookies(response)
    return {"message": "Logout realizado com sucesso"}


@router.post("/refresh")
async def refresh_session(
    response: Response,
    refresh_token: Optional[str] = Cookie(None),
    db: Session = Depends(get_session)
):
    """Renova a sessão a partir do cookie refresh_token, reemitindo ambos os cookies."""
    if not refresh_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Sessão expirada"
        )

    # Rotação + detecção de reuso (SEC-004): reapresentar um token já rotacionado
    # revoga a família inteira (persistida no commit abaixo, mesmo no erro)
    try:
        user_id, new_refresh = rotate_session(db, refresh_token)
    except SessionError:
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Sessão expirada"
        )

    user = db.get(User, user_id)
    if not user or user.deleted_at is not None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Sessão expirada"
        )

    new_access = create_access_token(data={"sub": str(user.id)})
    set_auth_cookies(response, new_access, new_refresh)
    db.commit()
    return {"message": "Sessão renovada"}


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(..., max_length=72)
    new_password: str = Field(..., min_length=6, max_length=72)


@router.post("/change-password")
async def change_password(
    response: Response,
    data: ChangePasswordRequest,
    db: Session = Depends(get_session),
    current_user: User = Depends(get_current_user)
):
    if current_user.password_hash.startswith("!"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Esta conta usa login com Google e não tem senha local."
        )
    if not verify_password(data.current_password, current_user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Senha atual incorreta"
        )
    current_user.password_hash = get_password_hash(data.new_password)
    db.add(current_user)

    # Trocar a senha derruba TODAS as sessões (SEC-004/ADR 0013): um refresh
    # token copiado valia os 7 dias inteiros mesmo depois da troca. Em seguida
    # emitimos uma sessão nova para quem trocou — quem age não é deslogado.
    revoke_all_user_sessions(db, current_user.id)
    new_access = create_access_token(data={"sub": str(current_user.id)})
    new_refresh = start_session(db, current_user.id)
    set_auth_cookies(response, new_access, new_refresh)

    db.commit()
    return {"message": "Senha alterada com sucesso"}


class ForgotPasswordRequest(BaseModel):
    email: NormalizedEmail


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str = Field(..., min_length=6, max_length=72)


@router.post("/forgot-password", dependencies=[Depends(rate_limit_auth)])
def forgot_password(
    data: ForgotPasswordRequest,
    db: Session = Depends(get_session)
):
    """Sempre retorna 200 para não revelar quais emails estão cadastrados."""
    rate_limit_account(db, data.email, "/auth/forgot-password")
    user = db.exec(select(User).where(User.email == data.email)).first()
    if user and user.deleted_at is None and not user.password_hash.startswith("!"):
        token = create_purpose_token(
            {"sub": str(user.id), "pwf": _password_fingerprint(user.password_hash)},
            purpose="password_reset",
            expires_delta=timedelta(minutes=settings.RESET_TOKEN_EXPIRES_MINUTES),
        )
        reset_link = f"{settings.FRONTEND_URL}/reset-password?token={token}"
        EmailService.send_password_reset(user.email, reset_link)

    return {"message": "Se o email estiver cadastrado, enviaremos as instruções de recuperação."}


@router.post("/reset-password", dependencies=[Depends(rate_limit_auth)])
def reset_password(
    response: Response,
    data: ResetPasswordRequest,
    db: Session = Depends(get_session)
):
    invalid = HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="Link de recuperação inválido ou expirado"
    )
    try:
        payload = decode_token(data.token)
        if payload.get("token_type") != "password_reset":
            raise ValueError("Tipo de token inválido")
        user_id = int(payload.get("sub"))
    except Exception:
        raise invalid

    user = db.get(User, user_id)
    # O fingerprint garante uso único: após a troca, o hash muda e o token morre.
    if not user or user.deleted_at is not None or _password_fingerprint(user.password_hash) != payload.get("pwf"):
        raise invalid

    user.password_hash = get_password_hash(data.new_password)
    db.add(user)

    # Recuperação de conta é o caso em que a sessão do atacante PRECISA cair:
    # revoga tudo e limpa os cookies deste navegador (o fluxo termina no login).
    revoke_all_user_sessions(db, user.id)
    clear_auth_cookies(response)

    db.commit()
    return {"message": "Senha redefinida com sucesso"}


def _google_configured() -> bool:
    return bool(
        settings.GOOGLE_CLIENT_ID
        and settings.GOOGLE_CLIENT_SECRET
        and settings.GOOGLE_REDIRECT_URI
    )


def _fetch_google_user(code: str) -> dict:
    """Troca o authorization code por tokens e busca o perfil do usuário no Google."""
    token_res = httpx.post(
        GOOGLE_TOKEN_URL,
        data={
            "code": code,
            "client_id": settings.GOOGLE_CLIENT_ID,
            "client_secret": settings.GOOGLE_CLIENT_SECRET,
            "redirect_uri": settings.GOOGLE_REDIRECT_URI,
            "grant_type": "authorization_code",
        },
        timeout=15,
    )
    token_res.raise_for_status()
    access_token = token_res.json()["access_token"]

    info_res = httpx.get(
        GOOGLE_USERINFO_URL,
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=15,
    )
    info_res.raise_for_status()
    return info_res.json()


@router.get("/google/login")
def google_login(response: Response, invite: Optional[str] = None):
    if not _google_configured():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Login com Google não está configurado"
        )
    # Nonce no state E num cookie HttpOnly: o callback só é aceito no navegador
    # que começou o login (senão o atacante inicia o fluxo na conta dele e
    # induz a vítima a completar o callback — login CSRF)
    nonce = secrets.token_urlsafe(24)
    # O convite viaja DENTRO do state (ADR 0026). O Google não devolve query
    # string nossa no callback — só `code` e `state` —, então sem carregá-lo aqui
    # o token se perderia no salto e quem foi convidado não conseguiria entrar
    # pelo botão do Google. O state é assinado, então o token não pode ser
    # trocado no caminho.
    state = create_purpose_token(
        {"nonce": nonce, "invite": invite}, purpose="oauth_state",
        expires_delta=timedelta(minutes=10),
    )
    params = urlencode({
        "client_id": settings.GOOGLE_CLIENT_ID,
        "redirect_uri": settings.GOOGLE_REDIRECT_URI,
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "access_type": "online",
        "prompt": "select_account",
    })
    redirect = RedirectResponse(f"{GOOGLE_AUTH_URL}?{params}")
    # RedirectResponse próprio: o cookie precisa ir NELE, não no `response` da
    # dependency (que não é o objeto devolvido)
    set_oauth_state_cookie(redirect, nonce)
    return redirect


@router.get("/google/callback")
def google_callback(
    request: Request,
    code: Optional[str] = None,
    state: Optional[str] = None,
    error: Optional[str] = None,
    oauth_state: Optional[str] = Cookie(None),
    db: Session = Depends(get_session)
):
    def fail(reason: str) -> RedirectResponse:
        res = RedirectResponse(f"{settings.FRONTEND_URL}/login?error={reason}")
        clear_oauth_state_cookie(res)
        return res

    # MESMO BALDE do `/auth/register`, e por dentro em vez de como dependency:
    # esta rota é uma NAVEGAÇÃO do navegador, e um 429 em JSON cru apareceria na
    # barra de endereços — a mesma razão pela qual o portão de cadastro, mais
    # abaixo, também recua para `fail()`.
    #
    # Faz falta desde o ADR 0026: enquanto o callback só autenticava quem já
    # tinha conta, o teto por IP do `register` bastava; agora as duas rotas fazem
    # nascer usuário, e deixar uma sem balde é a assimetria que o portão existe
    # para não ter.
    try:
        rate_limit_auth(request, db)
    except HTTPException:
        return fail("muitas_tentativas")

    if not _google_configured():
        return fail("google_nao_configurado")
    if error or not code or not state:
        return fail("google_cancelado")

    try:
        payload = decode_token(state)
        if payload.get("token_type") != "oauth_state":
            raise ValueError("State inválido")
        # O nonce do state tem que casar com o cookie deste navegador
        nonce = payload.get("nonce")
        if not nonce or not oauth_state or not secrets.compare_digest(nonce, oauth_state):
            raise ValueError("Nonce do state não confere com o navegador")
        invite_token = payload.get("invite")
    except Exception:
        return fail("google_state_invalido")

    try:
        info = _fetch_google_user(code)
    except Exception:
        return fail("google_falha_autenticacao")

    # O Google pode devolver o e-mail com a caixa que o usuário digitou no
    # cadastro dele — normaliza para casar com a conta local.
    email = normalize_email(info.get("email"))
    if not email or info.get("email_verified") is False:
        return fail("google_email_nao_verificado")

    user = db.exec(select(User).where(User.email == email)).first()
    if not user:
        # MESMO PORTÃO do `/auth/register` (ADR 0026). Sem esta chamada o OAuth
        # seria a porta dos fundos do cadastro: um site em `invite_only` — ou até
        # em `closed` — continuaria criando conta para qualquer pessoa que
        # tivesse um Google e alcançasse a URL, que é exatamente o defeito que o
        # portão existe para fechar. Autenticar com o Google prova QUEM é a
        # pessoa; não responde se ela pode existir neste site.
        try:
            convite, e_bootstrap = assert_pode_cadastrar(db, email, invite_token)
        except HTTPException:
            # O callback é uma navegação do navegador, não uma chamada de API:
            # devolver 403 aqui mostraria JSON cru na barra de endereços. A tela
            # de login sabe traduzir o código.
            return fail("cadastro_por_convite")

        user = User(
            name=info.get("name") or email.split("@")[0],
            email=email,
            password_hash=OAUTH_PASSWORD_SENTINEL,
            # Mesma janela de bootstrap do cadastro local: o `SUPERADMIN_EMAIL`
            # pode ser um endereço do Google, e obrigá-lo a criar senha local só
            # para nascer superadmin seria uma exigência sem motivo.
            platform_role=PlatformRole.superadmin if e_bootstrap else PlatformRole.user,
        )
        db.add(user)
        db.flush()
        _setup_default_workspace(db, user)
        # O token vale como consentimento aqui pelo mesmo motivo que vale no
        # cadastro local: ele veio do link do convite, que o navegador levou até
        # `/auth/google/login?invite=<token>`. Sem passá-lo, quem clicasse no
        # convite de um workspace e entrasse pelo botão do Google terminaria num
        # espaço vazio, sem entender por que não estava na casa que o chamou.
        # Sem token, nada é aceito automaticamente — os pendentes viram
        # notificação, como sempre.
        _resolve_pending_invites(db, user, accept_token=invite_token)
        if convite is not None:
            try:
                consome_convite(db, convite, user)
            except HTTPException:
                # `consome_convite` também RECUSA: é ele quem barra quem perdeu a
                # corrida pelo último uso do convite. Pelo mesmo motivo do
                # `assert_pode_cadastrar` acima, aqui a recusa vira redirect com
                # código — e sem o commit, a conta recém-criada não chega a
                # existir.
                return fail("cadastro_por_convite")
        db.commit()
        db.refresh(user)
    elif user.deleted_at is not None or not user.is_active:
        # Mesma regra do login local: conta desativada não recebe sessão
        return fail("conta_desativada")

    redirect = RedirectResponse(settings.FRONTEND_URL)
    access_token = create_access_token(data={"sub": str(user.id)})
    refresh_token = start_session(db, user.id)  # sessão persistida (SEC-004)
    set_auth_cookies(redirect, access_token, refresh_token)
    clear_oauth_state_cookie(redirect)  # nonce é de uso único
    AuditService.log_action(db, ActionType.login, user_id=user.id, resource_type="User", resource_id=user.id)
    return redirect
