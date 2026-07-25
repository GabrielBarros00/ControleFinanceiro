from datetime import datetime, timedelta, UTC
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from app.api.deps import get_workspace_membership, require_role
from app.api.routes.auth import get_current_user
from app.core.config import settings
from app.db.session import get_session
from app.models.user import User
from app.models.workspace import (
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
from app.services.email_service import EmailService
from app.services.event_service import publish_event

router = APIRouter(prefix="/workspaces/{workspace_id}", tags=["members"])
invites_router = APIRouter(prefix="/invites", tags=["invites"])


def _as_aware(dt: datetime) -> datetime:
    return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt


def _is_expired(invite: WorkspaceInvite) -> bool:
    return _as_aware(invite.expires_at) < datetime.now(UTC)


def _member_read(membership: WorkspaceMembership, user: User) -> MemberRead:
    return MemberRead(
        user_id=user.id,
        role=membership.role,
        user_name=user.name,
        user_email=user.email,
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
    return [_member_read(m, u) for m, u in rows]


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

    target.role = data.role
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

    existing_user = session.exec(select(User).where(User.email == data.email)).first()
    if existing_user:
        already = session.exec(
            select(WorkspaceMembership).where(
                WorkspaceMembership.workspace_id == workspace_id,
                WorkspaceMembership.user_id == existing_user.id,
            )
        ).first()
        if already:
            raise HTTPException(status_code=400, detail="Este usuário já é membro do workspace")

        new_membership = WorkspaceMembership(
            workspace_id=workspace_id,
            user_id=existing_user.id,
            role=data.role,
        )
        session.add(new_membership)
        publish_event(session, workspace_id, "member.added", "member", existing_user.id, actor.user_id)
        session.commit()
        EmailService.send_workspace_invite(
            data.email, workspace.name, inviter.name,
            f"{settings.FRONTEND_URL}/",
        )
        return {"status": "member_added", "user_id": existing_user.id}

    pending = session.exec(
        select(WorkspaceInvite).where(
            WorkspaceInvite.workspace_id == workspace_id,
            WorkspaceInvite.email == data.email,
            WorkspaceInvite.status == InviteStatus.pending,
        )
    ).first()
    if pending and not _is_expired(pending):
        raise HTTPException(status_code=400, detail="Já existe um convite pendente para este email")

    invite = WorkspaceInvite(
        workspace_id=workspace_id,
        email=data.email,
        role=data.role,
        invited_by_user_id=actor.user_id,
        expires_at=datetime.now(UTC) + timedelta(days=7),
    )
    session.add(invite)
    session.flush()
    publish_event(session, workspace_id, "invite.created", "invite", invite.id, actor.user_id)
    session.commit()
    session.refresh(invite)
    EmailService.send_workspace_invite(
        data.email, workspace.name, inviter.name,
        f"{settings.FRONTEND_URL}/register?invite={invite.token}",
    )
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
    if data.expires_days < 1 or data.expires_days > 30:
        raise HTTPException(status_code=400, detail="Expiração deve ser entre 1 e 30 dias")

    invite = WorkspaceInvite(
        workspace_id=workspace_id,
        email=None,
        role=data.role,
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
    invite.status = InviteStatus.revoked
    session.add(invite)
    publish_event(session, workspace_id, "invite.revoked", "invite", invite.id, actor.user_id)
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

    already = session.exec(
        select(WorkspaceMembership).where(
            WorkspaceMembership.workspace_id == invite.workspace_id,
            WorkspaceMembership.user_id == current_user.id,
        )
    ).first()
    if already:
        raise HTTPException(status_code=400, detail="Você já é membro deste workspace")

    session.add(WorkspaceMembership(
        workspace_id=invite.workspace_id,
        user_id=current_user.id,
        role=invite.role,
    ))
    publish_event(session, invite.workspace_id, "member.added", "member", current_user.id, current_user.id)

    if invite.email is not None:
        invite.status = InviteStatus.accepted
    else:
        invite.uses += 1
        if invite.max_uses is not None and invite.uses >= invite.max_uses:
            invite.status = InviteStatus.accepted
    session.add(invite)
    # O convite mudou de estado (aceito / usos consumidos): a tela de convites
    # do admin precisa refletir isso na hora, não só a lista de membros
    publish_event(
        session, invite.workspace_id, "invite.accepted", "invite", invite.id, current_user.id
    )
    session.commit()

    return {"status": "ok", "workspace_id": invite.workspace_id}
