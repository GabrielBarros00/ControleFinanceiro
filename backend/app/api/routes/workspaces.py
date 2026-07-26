from datetime import datetime, UTC
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select, func

from app.db.session import get_session
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMembership, WorkspaceRole
from app.schemas.workspace import WorkspaceCreate, WorkspaceRead, WorkspaceUpdate
from app.api.routes.auth import get_current_user
from app.api.deps import get_workspace_membership, require_role
from app.services.base_currency_service import BaseCurrencyService, MissingRates
from app.services.category_service import seed_default_categories
from app.services.event_service import publish_event

router = APIRouter(prefix="/workspaces", tags=["workspaces"])


def _build_read(
    workspace: Workspace, owner_name: Optional[str], member_count: int
) -> WorkspaceRead:
    return WorkspaceRead(
        id=workspace.id,
        name=workspace.name,
        description=workspace.description,
        base_currency=workspace.base_currency,
        created_at=workspace.created_at,
        updated_at=workspace.updated_at,
        owner_user_id=workspace.created_by_user_id,
        owner_name=owner_name,
        member_count=member_count,
    )


def _to_read(session: Session, workspace: Workspace) -> WorkspaceRead:
    """Enriquece o workspace com o dono (created_by) e o total de membros, para
    o switcher mostrar de quem é o workspace quando compartilhado."""
    owner_name = None
    if workspace.created_by_user_id:
        owner = session.get(User, workspace.created_by_user_id)
        owner_name = owner.name if owner else None
    member_count = session.exec(
        select(func.count(WorkspaceMembership.id)).where(
            WorkspaceMembership.workspace_id == workspace.id
        )
    ).one()
    return _build_read(workspace, owner_name, member_count)


def _to_read_many(session: Session, workspaces: List[Workspace]) -> List[WorkspaceRead]:
    """Versão em lote: 2 queries no total em vez de 2 POR workspace (N+1)."""
    if not workspaces:
        return []
    ws_ids = [w.id for w in workspaces]
    owner_ids = {w.created_by_user_id for w in workspaces if w.created_by_user_id}

    owner_names = {}
    if owner_ids:
        owner_names = {
            u.id: u.name
            for u in session.exec(select(User).where(User.id.in_(owner_ids))).all()
        }
    counts = dict(session.exec(
        select(WorkspaceMembership.workspace_id, func.count(WorkspaceMembership.id))
        .where(WorkspaceMembership.workspace_id.in_(ws_ids))
        .group_by(WorkspaceMembership.workspace_id)
    ).all())

    return [
        _build_read(w, owner_names.get(w.created_by_user_id), counts.get(w.id, 0))
        for w in workspaces
    ]


@router.post("/", response_model=WorkspaceRead)
def create_workspace(
    *,
    session: Session = Depends(get_session),
    workspace_in: WorkspaceCreate,
    current_user: User = Depends(get_current_user)
):
    workspace = Workspace(
        name=workspace_in.name,
        description=workspace_in.description,
        created_by_user_id=current_user.id
    )
    session.add(workspace)
    session.commit()
    session.refresh(workspace)

    membership = WorkspaceMembership(
        workspace_id=workspace.id,
        user_id=current_user.id,
        role=WorkspaceRole.owner
    )
    session.add(membership)
    seed_default_categories(session, workspace.id)
    session.commit()

    return _to_read(session, workspace)


@router.get("/", response_model=List[WorkspaceRead])
def list_workspaces(
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user)
):
    statement = (
        select(Workspace)
        .join(WorkspaceMembership)
        .where(
            WorkspaceMembership.user_id == current_user.id,
            Workspace.deleted_at.is_(None),
        )
    )
    workspaces = session.exec(statement).all()
    return _to_read_many(session, list(workspaces))


@router.get("/{workspace_id}", response_model=WorkspaceRead)
def get_workspace(
    workspace_id: int,
    session: Session = Depends(get_session),
    membership: WorkspaceMembership = Depends(get_workspace_membership),
):
    return _to_read(session, session.get(Workspace, workspace_id))


@router.put("/{workspace_id}", response_model=WorkspaceRead)
def update_workspace(
    workspace_id: int,
    workspace_in: WorkspaceUpdate,
    session: Session = Depends(get_session),
    membership: WorkspaceMembership = Depends(require_role(WorkspaceRole.admin)),
):
    workspace = session.get(Workspace, workspace_id)
    update_data = workspace_in.model_dump(exclude_unset=True)
    currency_changed = (
        "base_currency" in update_data
        and update_data["base_currency"] != workspace.base_currency
    )

    # Trocar a moeda-base RECONVERTE o histórico (A6). Sem isto os valores
    # continuavam gravados na moeda antiga e, como toda agregação filtra por
    # `currency == base_currency`, dívidas/relatórios/faturas/previsão iam a
    # ZERO de uma vez — o workspace parecia vazio. A conversão roda ANTES de
    # gravar a moeda nova e é tudo-ou-nada: falta de taxa aborta com 422 e o
    # `session.rollback()` garante que nada ficou pela metade.
    if currency_changed:
        try:
            BaseCurrencyService.convert_workspace(
                session, workspace_id, update_data["base_currency"]
            )
        except MissingRates as exc:
            session.rollback()
            raise HTTPException(
                status_code=422,
                detail=(
                    "Não foi possível trocar a moeda-base: falta cotação para "
                    f"{len(exc.missing)} data(s) do histórico ({', '.join(exc.missing[:5])}"
                    f"{'…' if len(exc.missing) > 5 else ''}). "
                    "Rode o backfill de câmbio e tente de novo."
                ),
            )

    for key, value in update_data.items():
        setattr(workspace, key, value)
    workspace.updated_at = datetime.now(UTC)
    session.add(workspace)
    publish_event(session, workspace_id, "workspace.updated", "workspace", workspace_id, membership.user_id)
    # Trocar a moeda-base muda TODA agregação (dívidas, relatórios, faturas,
    # endividamento): sem um evento próprio as telas abertas seguiriam com os
    # números da moeda antiga até um refetch manual.
    if currency_changed:
        publish_event(
            session, workspace_id, "workspace.currency_changed", "workspace", workspace_id, membership.user_id
        )
    session.commit()
    session.refresh(workspace)
    return _to_read(session, workspace)


@router.get("/{workspace_id}/base-currency/preview", response_model=Dict[str, Any])
def preview_base_currency_change(
    workspace_id: int,
    to: str,
    session: Session = Depends(get_session),
    membership: WorkspaceMembership = Depends(require_role(WorkspaceRole.admin)),
):
    """Dry-run da troca de moeda-base: quantas linhas seriam reconvertidas e que
    cotações faltam. A UI usa isto para avisar ANTES de confirmar — a troca é
    uma reescrita de todo o histórico financeiro do workspace."""
    to = to.strip().upper()
    if len(to) != 3 or not to.isalpha():
        raise HTTPException(status_code=400, detail="Moeda inválida: use um código ISO de 3 letras")
    report = BaseCurrencyService.plan_conversion(session, workspace_id, to)
    return report.as_dict()


@router.delete("/{workspace_id}")
def delete_workspace(
    workspace_id: int,
    session: Session = Depends(get_session),
    membership: WorkspaceMembership = Depends(require_role(WorkspaceRole.owner)),
):
    workspace = session.get(Workspace, workspace_id)
    workspace.deleted_at = datetime.now(UTC)
    session.add(workspace)
    publish_event(session, workspace_id, "workspace.deleted", "workspace", workspace_id, membership.user_id)
    session.commit()
    return {"status": "ok"}
