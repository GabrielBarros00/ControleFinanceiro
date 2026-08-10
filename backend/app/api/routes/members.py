from datetime import datetime, timedelta, UTC
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import update
from sqlmodel import Session, select

from app.api.deps import get_workspace_membership, require_role
from app.api.routes.auth import get_current_user
from app.core.config import settings
from app.db.session import get_session
from app.domain.access_policy import effective_access
from app.domain.query_policy import workspace_base_currency
from app.models.recurring import RecurringExpense
from app.models.user import User
from app.models.workspace import (
    FinancialAccess,
    Workspace,
    WorkspaceMembership,
    WorkspaceInvite,
    WorkspaceRole,
    InviteStatus,
    role_level,
)
from app.schemas.workspace import (
    MemberRead,
    MemberUpdate,
    InviteCreate,
    InviteLinkCreate,
    InviteRead,
    InviteLinkRead,
    InviteInfoRead,
)
from app.services.debt_service import DebtService
from app.services.email_service import EmailService
from app.services.event_service import publish_event
from app.models.notification import NotificationType
from app.services.membership_service import ensure_membership, find_membership
from app.services.notification_service import notify, resolve_invite_notifications

router = APIRouter(prefix="/workspaces/{workspace_id}", tags=["members"])
invites_router = APIRouter(prefix="/invites", tags=["invites"])


def _as_aware(dt: datetime) -> datetime:
    return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt


def _is_expired(invite: WorkspaceInvite) -> bool:
    return _as_aware(invite.expires_at) < datetime.now(UTC)


def _ensure_no_open_balance(session: Session, workspace_id: int, user_id: int) -> None:
    """Recusa a saída de quem ainda tem dívida/crédito em aberto.

    Antes a membership era simplesmente apagada e os splits/pagadores da pessoa
    ficavam órfãos: o nome sumia do extrato e das dívidas (vira um id sem
    rótulo) e QUALQUER edição completa daquelas despesas passava a falhar em
    `_ensure_members` com "usuário não pertence a este workspace" — sem caminho
    de saída pela UI. Acertar antes de sair é a condição para o histórico
    continuar interpretável.
    """
    saldos = DebtService.get_workspace_debts(session, workspace_id)
    pendente = next(
        (d for d in saldos if user_id in (d["debtor_id"], d["creditor_id"])), None
    )
    if pendente is None:
        return
    devedor = pendente["debtor_id"] == user_id
    # Moeda do workspace, não "R$" fixo (a base é configurável desde a Onda 5)
    moeda = workspace_base_currency(session, workspace_id)
    raise HTTPException(
        status_code=409,
        detail=(
            f"Ainda há acerto pendente de {moeda} {pendente['amount']} "
            + ("a pagar" if devedor else "a receber")
            + ". Registre o acerto antes de sair/remover — senão o histórico "
            "fica com lançamentos de alguém que não é mais membro."
        ),
    )


def _ensure_no_active_recurring(session: Session, workspace_id: int, user_id: int) -> None:
    """Recusa a saída de quem ainda é pagador ou participante de recorrência ativa.

    `_ensure_no_open_balance` cobria o passado (o que já foi lançado) e nada
    cobria o FUTURO. Uma recorrência ativa com o membro como pagador ou dentro do
    `split_snapshot` continuava tentando materializar depois da remoção; o
    snapshot passa a apontar para quem não é mais membro, a validação recusa, e a
    ocorrência é **descartada em silêncio** (`recurring_service`, no `except` que
    protege a materialização preguiçosa de derrubar uma rota de leitura).

    O efeito prático é o pior possível: o aluguel simplesmente para de aparecer, e
    ninguém recebe aviso nenhum — nem quem removeu, nem quem restou. Melhor
    recusar aqui e pedir a reassociação, que é uma edição de um minuto.
    """
    ativas = session.exec(
        select(RecurringExpense)
        .where(RecurringExpense.workspace_id == workspace_id)
        .where(RecurringExpense.is_active.is_(True))
    ).all()

    def _envolve(template: RecurringExpense) -> bool:
        if template.payer_user_id == user_id:
            return True
        for parte in template.split_snapshot or []:
            if isinstance(parte, dict) and parte.get("user_id") == user_id:
                return True
        return False

    envolvidas = [t for t in ativas if _envolve(t)]
    if not envolvidas:
        return

    nomes = ", ".join(f"'{t.title}'" for t in envolvidas[:3])
    resto = f" e mais {len(envolvidas) - 3}" if len(envolvidas) > 3 else ""
    raise HTTPException(
        status_code=409,
        detail=(
            f"Há {len(envolvidas)} recorrência(s) ativa(s) com esta pessoa como "
            f"pagador ou participante: {nomes}{resto}. Reassocie ou desative "
            "antes de remover — senão as próximas ocorrências param de ser "
            "geradas sem aviso."
        ),
    )


def _mask_email(email: str) -> str:
    """`gabriel@exemplo.com` → `g••••@exemplo.com`.

    Mantém a pista de qual conta é (útil para o dono reconhecer quem convidou)
    sem entregar o endereço inteiro.
    """
    usuario, _, dominio = email.partition("@")
    if not dominio:
        return "•••"
    visivel = usuario[:1] if usuario else ""
    return f"{visivel}{'•' * max(len(usuario) - 1, 3)}@{dominio}"


def _member_read(
    membership: WorkspaceMembership, user: User, *, reveal_email: bool = True
) -> MemberRead:
    return MemberRead(
        user_id=user.id,
        role=membership.role,
        # O acesso EFETIVO, não a coluna crua: owner/admin têm acesso completo pelo
        # cargo, e a tela de membros tem de mostrar o que vale de verdade — senão
        # exibiria "somente envolvido" para um admin que vê tudo.
        financial_access=effective_access(membership),
        user_name=user.name,
        # Viewer enxerga o NOME, não o endereço: o e-mail de todo mundo era
        # exposto ao papel de menor privilégio, e é ele quem alcança um
        # workspace compartilhado com menos escrutínio.
        user_email=user.email if reveal_email else _mask_email(user.email),
        joined_at=membership.created_at,
    )


# --- Membros ---

@router.get("/members", response_model=List[MemberRead])
def list_members(
    workspace_id: int,
    session: Session = Depends(get_session),
    membership: WorkspaceMembership = Depends(get_workspace_membership),
):
    rows = session.exec(
        select(WorkspaceMembership, User)
        .join(User, User.id == WorkspaceMembership.user_id)
        .where(WorkspaceMembership.workspace_id == workspace_id)
    ).all()
    # Viewer vê nome; e-mail completo só de member para cima (e o próprio sempre)
    pode_ver_email = role_level(membership.role) >= role_level(WorkspaceRole.member)
    return [
        _member_read(m, u, reveal_email=pode_ver_email or u.id == membership.user_id)
        for m, u in rows
    ]


@router.patch("/members/{user_id}", response_model=MemberRead)
def update_member_role(
    workspace_id: int,
    user_id: int,
    data: MemberUpdate,
    session: Session = Depends(get_session),
    actor: WorkspaceMembership = Depends(require_role(WorkspaceRole.admin)),
):
    if user_id == actor.user_id:
        raise HTTPException(status_code=400, detail="Você não pode alterar o próprio papel")
    if data.role == WorkspaceRole.owner:
        raise HTTPException(status_code=400, detail="Não é possível promover a owner")

    target = session.exec(
        select(WorkspaceMembership).where(
            WorkspaceMembership.workspace_id == workspace_id,
            WorkspaceMembership.user_id == user_id,
        )
    ).first()
    if not target:
        raise HTTPException(status_code=404, detail="Membro não encontrado")
    if target.role == WorkspaceRole.owner:
        raise HTTPException(status_code=403, detail="O papel do owner não pode ser alterado")
    # Admin só gerencia papéis abaixo do seu (owner gerencia todos os não-owner)
    if role_level(target.role) >= role_level(actor.role) or role_level(data.role) >= role_level(actor.role):
        raise HTTPException(status_code=403, detail="Permissão insuficiente para esta ação")

    era_admin = role_level(target.role) >= role_level(WorkspaceRole.admin)
    target.role = data.role
    if data.financial_access is not None:
        # Owner nunca perde a visão da casa. `effective_access` já garante isso na
        # leitura; recusar aqui evita gravar um estado que mente sobre si mesmo.
        if target.role == WorkspaceRole.owner:
            raise HTTPException(
                status_code=400,
                detail="O owner sempre tem acesso financeiro completo",
            )
        target.financial_access = data.financial_access
    elif era_admin and role_level(data.role) < role_level(WorkspaceRole.admin):
        # REBAIXAMENTO fecha a visibilidade. Enquanto a pessoa é admin, o valor
        # gravado na coluna é invisível — a leitura devolve o EFETIVO
        # (`full_workspace`, pelo cargo) e a tela nem mostra o seletor. Herdar
        # essa coluna em silêncio ao rebaixar significa que quem tira privilégios
        # pode estar ampliando o que a pessoa vê, sem escolher nada e sem saber.
        # A direção segura é a mesma do default de convite (ADR 0018): fecha, e
        # reabrir é ato explícito de um clique.
        target.financial_access = FinancialAccess.involved_only
    target.updated_at = datetime.now(UTC)
    session.add(target)
    publish_event(session, workspace_id, "member.updated", "member", user_id, actor.user_id)
    session.commit()
    session.refresh(target)
    user = session.get(User, user_id)
    return _member_read(target, user)


@router.delete("/members/{user_id}")
def remove_member(
    workspace_id: int,
    user_id: int,
    session: Session = Depends(get_session),
    actor: WorkspaceMembership = Depends(require_role(WorkspaceRole.admin)),
):
    if user_id == actor.user_id:
        raise HTTPException(status_code=400, detail="Use 'sair do workspace' para se remover")

    target = session.exec(
        select(WorkspaceMembership).where(
            WorkspaceMembership.workspace_id == workspace_id,
            WorkspaceMembership.user_id == user_id,
        )
    ).first()
    if not target:
        raise HTTPException(status_code=404, detail="Membro não encontrado")
    if target.role == WorkspaceRole.owner:
        raise HTTPException(status_code=403, detail="O owner não pode ser removido")
    if role_level(target.role) >= role_level(actor.role):
        raise HTTPException(status_code=403, detail="Permissão insuficiente para esta ação")
    _ensure_no_open_balance(session, workspace_id, user_id)
    _ensure_no_active_recurring(session, workspace_id, user_id)

    session.delete(target)
    publish_event(session, workspace_id, "member.removed", "member", user_id, actor.user_id)
    session.commit()
    return {"status": "ok"}


@router.post("/leave")
def leave_workspace(
    workspace_id: int,
    session: Session = Depends(get_session),
    membership: WorkspaceMembership = Depends(get_workspace_membership),
):
    if membership.role == WorkspaceRole.owner:
        raise HTTPException(
            status_code=400,
            detail="O owner não pode sair do próprio workspace. Exclua o workspace."
        )
    _ensure_no_open_balance(session, workspace_id, membership.user_id)
    _ensure_no_active_recurring(session, workspace_id, membership.user_id)
    session.delete(membership)
    publish_event(session, workspace_id, "member.removed", "member", membership.user_id, membership.user_id)
    session.commit()
    return {"status": "ok"}


# --- Convites ---

@router.post("/invites")
def create_invite(
    workspace_id: int,
    data: InviteCreate,
    session: Session = Depends(get_session),
    actor: WorkspaceMembership = Depends(require_role(WorkspaceRole.admin)),
):
    if role_level(data.role) >= role_level(actor.role):
        raise HTTPException(status_code=403, detail="Você só pode convidar com papel inferior ao seu")

    workspace = session.get(Workspace, workspace_id)
    inviter = session.get(User, actor.user_id)

    # Usuário JÁ CADASTRADO não é mais adicionado direto. Antes, convidar por
    # e-mail colocava a pessoa no workspace sem ela aceitar nada: quem soubesse
    # um e-mail dava a si mesmo uma plateia para as finanças alheias, e o
    # convidado passava a ver as de outra família sem saber. Agora o convite
    # espera aceite — e chega por e-mail E dentro do app (notificação).
    existing_user = session.exec(select(User).where(User.email == data.email)).first()
    if existing_user and find_membership(session, workspace_id, existing_user.id):
        raise HTTPException(status_code=400, detail="Este usuário já é membro do workspace")

    pendentes = session.exec(
        select(WorkspaceInvite).where(
            WorkspaceInvite.workspace_id == workspace_id,
            WorkspaceInvite.email == data.email,
            WorkspaceInvite.status == InviteStatus.pending,
        )
    ).all()
    if any(not _is_expired(p) for p in pendentes):
        raise HTTPException(status_code=400, detail="Já existe um convite pendente para este email")
    # Os expirados viram `revoked`. Ficavam para sempre como "pendente": a lista
    # do admin anunciava convites mortos como ativos, e a cada reenvio sobrava
    # mais uma linha. `_get_valid_invite` já os recusa — o estado é que mentia.
    for expirado in pendentes:
        expirado.status = InviteStatus.revoked
        session.add(expirado)
        resolve_invite_notifications(session, expirado.token)

    invite = WorkspaceInvite(
        workspace_id=workspace_id,
        email=data.email,
        role=data.role,
        financial_access=data.financial_access,
        invited_by_user_id=actor.user_id,
        # Honra o schema. Antes eram 7 dias fixos no braço e `expires_days` do
        # cliente era silenciosamente ignorado — só o convite por link respeitava.
        expires_at=datetime.now(UTC) + timedelta(days=data.expires_days),
    )
    session.add(invite)
    session.flush()

    # Notificação DENTRO do app para quem já tem conta. E-mail sozinho não
    # basta: muita gente não lê, e o convite ficava invisível.
    if existing_user:
        notify(
            session,
            user_id=existing_user.id,
            type=NotificationType.workspace_invite,
            title=f"{inviter.name} convidou você para \"{workspace.name}\"",
            body=(
                f"Você foi convidado como {data.role.value}. "
                "Aceite para começar a ver e lançar as despesas compartilhadas."
            ),
            workspace_id=workspace_id,
            workspace_name=workspace.name,
            invite_token=invite.token,
        )

    publish_event(session, workspace_id, "invite.created", "invite", invite.id, actor.user_id)
    session.commit()
    session.refresh(invite)
    # Quem já tem conta cai direto no aceite; quem não tem passa pelo registro
    destino = (
        f"{settings.FRONTEND_URL}/invite/{invite.token}"
        if existing_user
        else f"{settings.FRONTEND_URL}/register?invite={invite.token}"
    )
    EmailService.send_workspace_invite(data.email, workspace.name, inviter.name, destino)
    return {"status": "invite_sent", "invite": InviteRead.model_validate(invite, from_attributes=True)}


@router.post("/invites/link", response_model=InviteLinkRead)
def create_invite_link(
    workspace_id: int,
    data: InviteLinkCreate,
    session: Session = Depends(get_session),
    actor: WorkspaceMembership = Depends(require_role(WorkspaceRole.admin)),
):
    if role_level(data.role) >= role_level(actor.role):
        raise HTTPException(status_code=403, detail="Você só pode convidar com papel inferior ao seu")

    invite = WorkspaceInvite(
        workspace_id=workspace_id,
        email=None,
        role=data.role,
        financial_access=data.financial_access,
        invited_by_user_id=actor.user_id,
        expires_at=datetime.now(UTC) + timedelta(days=data.expires_days),
        max_uses=data.max_uses,
    )
    session.add(invite)
    session.flush()
    publish_event(session, workspace_id, "invite.created", "invite", invite.id, actor.user_id)
    session.commit()
    session.refresh(invite)

    return InviteLinkRead(
        **InviteRead.model_validate(invite, from_attributes=True).model_dump(),
        token=invite.token,
        url=f"{settings.FRONTEND_URL}/invite/{invite.token}",
    )


@router.get("/invites", response_model=List[InviteRead])
def list_invites(
    workspace_id: int,
    session: Session = Depends(get_session),
    actor: WorkspaceMembership = Depends(require_role(WorkspaceRole.admin)),
):
    invites = session.exec(
        select(WorkspaceInvite)
        .where(WorkspaceInvite.workspace_id == workspace_id)
        .order_by(WorkspaceInvite.created_at.desc())
    ).all()
    return invites


@router.delete("/invites/{invite_id}")
def revoke_invite(
    workspace_id: int,
    invite_id: int,
    session: Session = Depends(get_session),
    actor: WorkspaceMembership = Depends(require_role(WorkspaceRole.admin)),
):
    invite = session.get(WorkspaceInvite, invite_id)
    if not invite or invite.workspace_id != workspace_id:
        raise HTTPException(status_code=404, detail="Convite não encontrado")
    # Só convite PENDENTE pode ser revogado. Sem esta guarda, revogar um convite
    # já aceito reescrevia o histórico (a pessoa continua membro, mas a trilha
    # passa a dizer que o convite foi revogado) e revogar um já revogado devolvia
    # 200 como se algo tivesse acontecido. Mesma regra do `decline_invite` e do
    # `_get_valid_invite`.
    if invite.status != InviteStatus.pending:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Convite não está pendente (status: {getattr(invite.status, 'value', invite.status)}) "
                "— para tirar o acesso de quem já entrou, remova o membro."
            ),
        )
    invite.status = InviteStatus.revoked
    session.add(invite)
    publish_event(session, workspace_id, "invite.revoked", "invite", invite.id, actor.user_id)
    # O aviso no app tem que morrer junto com o convite. Sem isto, o convidado
    # continuava vendo o modal de convite pendente (que é a PRIMEIRA coisa do
    # app) com um botão "Aceitar" que só devolve 404 — e o contador de não lidas
    # nunca zerava, porque não havia ação capaz de resolver a notificação.
    resolve_invite_notifications(session, invite.token)
    session.commit()
    return {"status": "ok"}


# --- Aceite por token (fora do escopo de workspace) ---

def _get_valid_invite(session: Session, token: str) -> WorkspaceInvite:
    invite = session.exec(
        select(WorkspaceInvite).where(WorkspaceInvite.token == token)
    ).first()
    if not invite or invite.status != InviteStatus.pending:
        raise HTTPException(status_code=404, detail="Convite não encontrado ou já utilizado")
    if _is_expired(invite):
        raise HTTPException(status_code=410, detail="Convite expirado")
    if invite.max_uses is not None and invite.uses >= invite.max_uses:
        raise HTTPException(status_code=410, detail="Convite atingiu o limite de usos")
    return invite


@invites_router.get("/info/{token}", response_model=InviteInfoRead)
def invite_info(
    token: str,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    invite = session.exec(
        select(WorkspaceInvite).where(WorkspaceInvite.token == token)
    ).first()
    if not invite:
        raise HTTPException(status_code=404, detail="Convite não encontrado")

    workspace = session.get(Workspace, invite.workspace_id)
    inviter = session.get(User, invite.invited_by_user_id) if invite.invited_by_user_id else None

    valid = invite.status == InviteStatus.pending and not _is_expired(invite)
    reason = None
    if invite.status != InviteStatus.pending:
        reason = "Convite já utilizado ou revogado"
    elif _is_expired(invite):
        reason = "Convite expirado"
    elif invite.max_uses is not None and invite.uses >= invite.max_uses:
        valid = False
        reason = "Convite atingiu o limite de usos"
    elif invite.email and invite.email != current_user.email:
        valid = False
        reason = "Este convite foi enviado para outro email"

    return InviteInfoRead(
        workspace_name=workspace.name if workspace else "?",
        role=invite.role,
        invited_by=inviter.name if inviter else None,
        valid=valid,
        reason=reason,
    )


@invites_router.post("/accept/{token}")
def accept_invite(
    token: str,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    invite = _get_valid_invite(session, token)

    if invite.email and invite.email != current_user.email:
        raise HTTPException(status_code=403, detail="Este convite foi enviado para outro email")

    if not ensure_membership(
        session,
        invite.workspace_id,
        current_user.id,
        invite.role,
        financial_access=invite.financial_access,
    ):
        raise HTTPException(status_code=400, detail="Você já é membro deste workspace")

    publish_event(session, invite.workspace_id, "member.added", "member", current_user.id, current_user.id)

    if invite.email is not None:
        invite.status = InviteStatus.accepted
        session.add(invite)
    else:
        # Incremento ATÔMICO no banco (mesmo padrão do seq em publish_event).
        # Com `invite.uses += 1` em Python, dois aceites simultâneos liam o mesmo
        # valor e o link estourava o max_uses.
        novo_uso = session.execute(
            update(WorkspaceInvite)
            .where(WorkspaceInvite.id == invite.id)
            .values(uses=WorkspaceInvite.uses + 1)
            .returning(WorkspaceInvite.uses)
        ).scalar_one()
        session.refresh(invite)
        if invite.max_uses is not None and novo_uso >= invite.max_uses:
            invite.status = InviteStatus.accepted
            session.add(invite)
    # O convite mudou de estado (aceito / usos consumidos): a tela de convites
    # do admin precisa refletir isso na hora, não só a lista de membros
    publish_event(
        session, invite.workspace_id, "invite.accepted", "invite", invite.id, current_user.id
    )
    # O aviso cumpriu o papel: sem isto o contador de não lidas nunca zerava
    resolve_invite_notifications(session, invite.token)
    session.commit()

    return {"status": "ok", "workspace_id": invite.workspace_id}


@invites_router.post("/decline/{token}")
def decline_invite(
    token: str,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Recusa um convite. Existe porque o aviso precisa ter as DUAS saídas — sem
    recusar, a única forma de se livrar do convite era aceitá-lo."""
    invite = session.exec(
        select(WorkspaceInvite).where(WorkspaceInvite.token == token)
    ).first()
    if not invite or invite.status != InviteStatus.pending:
        raise HTTPException(status_code=404, detail="Convite não encontrado ou já utilizado")
    if invite.email and invite.email != current_user.email:
        raise HTTPException(status_code=403, detail="Este convite foi enviado para outro email")

    invite.status = InviteStatus.revoked
    session.add(invite)
    publish_event(
        session, invite.workspace_id, "invite.revoked", "invite", invite.id, current_user.id
    )
    resolve_invite_notifications(session, invite.token)
    session.commit()
    return {"status": "ok"}
