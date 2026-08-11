"""Convite de cadastro e o portão de quem pode criar conta (ADR 0026).

Vive num serviço, e não dentro da rota de registro, porque três caminhos
diferentes precisam das mesmas respostas: o `register` (o portão), a tela de
Admin (emitir e revogar) e a rota do usuário comum que convida alguém. Espalhar
a regra de expiração e de teto de uso por três lugares é como nasce o convite que
expira num e vale no outro.
"""
from datetime import datetime, timedelta, UTC
from typing import Optional, Tuple

from fastapi import HTTPException, status
from sqlmodel import Session, func, select

from app.core.config import settings
from app.models.registration_invite import RegistrationInvite
from app.models.user import PlatformRole, User, platform_level
from app.models.workspace import InviteStatus, WorkspaceInvite
from app.services import app_settings
from app.services.app_settings import RegistrationMode, WhoCanInvite


def _aware(momento: datetime) -> datetime:
    """O SQLite devolve datetime ingênuo; comparar com `now(UTC)` estouraria."""
    return momento if momento.tzinfo else momento.replace(tzinfo=UTC)


def _convite_de_cadastro_valido(db: Session, token: str, email: str) -> Optional[RegistrationInvite]:
    convite = db.exec(
        select(RegistrationInvite).where(RegistrationInvite.token == token)
    ).first()
    if convite is None or convite.status != InviteStatus.pending:
        return None
    if _aware(convite.expires_at) < datetime.now(UTC):
        return None
    # Convite nominal só vale para o endereço convidado — senão o link vazado num
    # grupo de mensagens vira cadastro aberto para quem o encontrar.
    if convite.email and convite.email.strip().lower() != email:
        return None
    if convite.max_uses is not None and convite.uses >= convite.max_uses:
        return None
    return convite


def _convite_de_workspace_valido(db: Session, token: str, email: str) -> bool:
    """Convite para uma casa também autoriza a criar conta.

    Quem foi chamado para dentro de um workspace obviamente pode existir no site;
    exigir um segundo convite, de outra espécie, para a mesma pessoa seria
    burocracia que só produz gente travada na tela de cadastro. O consentimento
    já está registrado — é o `WorkspaceInvite`.
    """
    convite = db.exec(
        select(WorkspaceInvite).where(WorkspaceInvite.token == token)
    ).first()
    if convite is None or convite.status != InviteStatus.pending:
        return False
    if _aware(convite.expires_at) < datetime.now(UTC):
        return False
    if convite.email and convite.email.strip().lower() != email:
        return False
    if convite.max_uses is not None and convite.uses >= convite.max_uses:
        return False
    return True


def _e_o_bootstrap(db: Session, email: str) -> bool:
    """O primeiro superadmin criando a própria conta.

    A janela é estreita de propósito e fecha sozinha: vale só para o e-mail do
    `SUPERADMIN_EMAIL` e só enquanto NÃO existir superadmin nenhum no banco.
    Depois que a conta nasce, o `lifespan` a promove e esta função passa a
    devolver `False` para sempre — inclusive para o mesmo e-mail.

    Sem ela, um deploy novo com cadastro por convite é um impasse: ninguém entra
    porque não há quem convide.
    """
    if not settings.SUPERADMIN_EMAIL:
        return False
    if settings.SUPERADMIN_EMAIL.strip().lower() != email:
        return False
    ja_existe = db.exec(
        select(User.id).where(User.platform_role == PlatformRole.superadmin).limit(1)
    ).first()
    return ja_existe is None


def assert_pode_cadastrar(
    db: Session, email: str, invite_token: Optional[str]
) -> Tuple[Optional[RegistrationInvite], bool]:
    """Portão do `POST /auth/register`.

    Devolve `(convite_de_cadastro, e_bootstrap)`. O convite volta para que o
    chamador o consuma DENTRO da mesma transação do cadastro (ADR 0010): marcar o
    convite como usado num commit e criar o usuário noutro deixaria, no caso de
    falha entre os dois, um convite queimado sem conta — e a pessoa sem como
    tentar de novo.
    """
    email = email.strip().lower()

    if _e_o_bootstrap(db, email):
        return None, True

    modo = app_settings.get(db, "registration_mode")
    if modo == RegistrationMode.open:
        # Mesmo com cadastro aberto, um token presente é consumido: veio de um
        # convite real e a contagem de usos precisa refletir a verdade.
        convite = _convite_de_cadastro_valido(db, invite_token, email) if invite_token else None
        return convite, False

    if modo == RegistrationMode.closed:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="O cadastro está fechado no momento.",
        )

    # invite_only
    if not invite_token:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="O cadastro é apenas por convite. Peça um convite a quem já usa o sistema.",
        )

    convite = _convite_de_cadastro_valido(db, invite_token, email)
    if convite is not None:
        return convite, False

    if _convite_de_workspace_valido(db, invite_token, email):
        return None, False

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Convite inválido, expirado ou já utilizado.",
    )


def consome_convite(db: Session, convite: RegistrationInvite, user: User) -> None:
    """Marca o uso. Só `flush` — o commit é do chamador (ADR 0010)."""
    convite.uses += 1
    if convite.accepted_by_user_id is None:
        convite.accepted_by_user_id = user.id
    # Convite nominal ou de link no último uso: encerra. `max_uses=None` num
    # convite nominal significa uso único — o e-mail já é o teto.
    if convite.max_uses is None or convite.uses >= convite.max_uses:
        convite.status = InviteStatus.accepted
    db.add(convite)
    db.flush()


def assert_pode_convidar(db: Session, autor: User) -> None:
    """Quem pode emitir convite de cadastro, e quantos."""
    quem = app_settings.get(db, "who_can_invite")
    e_admin = platform_level(autor.platform_role) >= platform_level(PlatformRole.admin)

    if quem == WhoCanInvite.admins_only and not e_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Apenas administradores podem convidar novas pessoas.",
        )

    # A cota vale para usuário comum. Um admin sem teto é o ponto: se ele quisesse
    # encher o site de contas, tem a tela de configuração para abrir o cadastro.
    if e_admin:
        return

    teto = app_settings.get(db, "user_invite_quota_per_month")
    desde = datetime.now(UTC) - timedelta(days=30)
    emitidos = db.exec(
        select(func.count(RegistrationInvite.id)).where(
            RegistrationInvite.created_by_user_id == autor.id,
            RegistrationInvite.created_at >= desde,
        )
    ).one()
    if emitidos >= teto:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Você já emitiu {teto} convites nos últimos 30 dias.",
        )


def cria_convite(
    db: Session,
    autor: User,
    email: Optional[str] = None,
    max_uses: Optional[int] = None,
) -> RegistrationInvite:
    """Cria o convite. Só `flush` — o commit é do chamador."""
    dias = app_settings.get(db, "invite_expiry_days")
    convite = RegistrationInvite(
        email=email.strip().lower() if email else None,
        created_by_user_id=autor.id,
        expires_at=datetime.now(UTC) + timedelta(days=dias),
        max_uses=max_uses,
    )
    db.add(convite)
    db.flush()
    db.refresh(convite)
    return convite


def link_do_convite(convite: RegistrationInvite) -> str:
    return f"{settings.FRONTEND_URL}/register?invite={convite.token}"
