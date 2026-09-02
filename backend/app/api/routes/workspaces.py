from datetime import datetime, UTC
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select, func

from app.schemas.common import StatusRead
from app.db.session import get_session
from app.models.user import User
from app.models.workspace import (
    FinancialAccess,
    Workspace,
    WorkspaceMembership,
    WorkspaceRole,
)
from app.schemas.workspace import (
    BaseCurrencyPreviewRead,
    WorkspaceCreate,
    WorkspaceRead,
    WorkspaceUpdate,
)
from app.api.routes.auth import get_current_user
from app.api.deps import get_workspace_membership, require_role
from app.domain.query_policy import InvalidCurrencyCode, normalize_currency_code
from app.services.base_currency_service import (
    AccountsInOldCurrency,
    BaseCurrencyService,
    MissingRates,
)
from app.services.category_service import seed_default_categories
from app.services.event_service import publish_event

router = APIRouter(prefix="/workspaces", tags=["workspaces"])


def _tambem_sem_barra(metodo: str, **kwargs):
    """Registra a coleção também SEM a barra final, fora do schema.

    O redirecionamento automático do Starlette responde 307, e nesse salto o
    **cookie de sessão não acompanha**: `POST .../{caminho}` (sem barra) chegava
    como 401 em vez de funcionar. É a mesma armadilha que `me_accounts`,
    `me_cards`, `me_financing`, `me_income` e `admin` já eliminaram com o
    `_colecao` deles — estas duas coleções, que são as mais usadas do app,
    tinham ficado de fora.

    Aqui o canônico é a forma COM barra (ao contrário do `_colecao`), e a nova
    entra com `include_in_schema=False`: é a que o `openapi.json` já documenta e
    contra a qual o frontend foi escrito, então manter o schema intacto evita
    regerar `api.gen.ts` por uma correção que não muda contrato nenhum.
    """
    def decorador(func):
        getattr(router, metodo)("", include_in_schema=False, **kwargs)(func)
        return func
    return decorador


def _build_read(
    workspace: Workspace,
    owner: Optional[tuple[int, str]],
    member_count: int,
) -> WorkspaceRead:
    return WorkspaceRead(
        id=workspace.id,
        name=workspace.name,
        description=workspace.description,
        base_currency=workspace.base_currency,
        settlement_tracking=workspace.settlement_tracking,
        created_at=workspace.created_at,
        updated_at=workspace.updated_at,
        owner_user_id=owner[0] if owner else None,
        owner_name=owner[1] if owner else None,
        member_count=member_count,
    )


# O dono sai da MEMBERSHIP `owner`, não de `created_by_user_id` (ADR 0028).
#
# Eram duas respostas para "de quem é este espaço": esta rota exibia quem criou,
# enquanto quem AUTORIZA (excluir o workspace, ser imune a rebaixamento) é o papel
# na membership. Coincidiam por construção no instante da criação e por mais nada —
# e desde que a propriedade passou a se transferir, quem criou pode não ser mais
# dono. `created_by_user_id` continua na tabela como registro histórico.
#
# Sem membership `owner` a resposta é `None`, e não o criador: cair no criador
# seria reintroduzir em silêncio exatamente a divergência que este ADR fecha.
def _owner_expr():
    return (
        select(
            WorkspaceMembership.workspace_id,
            User.id,
            User.name,
        )
        .join(User, User.id == WorkspaceMembership.user_id)
        .where(WorkspaceMembership.role == WorkspaceRole.owner.value)
    )


# `member_count` conta só quem PODE estar nisto: conta desativada ou soft-deletada
# não é uma das "3 pessoas" que a interface promete. O dono é exceção deliberada
# na EXIBIÇÃO (`_owner_expr` não filtra): "de quem é" tem resposta mesmo com o
# dono inativo — ele só não entra na contagem.
def _count_expr():
    return (
        select(WorkspaceMembership.workspace_id, func.count(WorkspaceMembership.id))
        .join(User, User.id == WorkspaceMembership.user_id)
        .where(User.is_active.is_(True), User.deleted_at.is_(None))
        .group_by(WorkspaceMembership.workspace_id)
    )


def _to_read(session: Session, workspace: Workspace) -> WorkspaceRead:
    """Enriquece o workspace com o dono e o total de membros ativos, para o
    switcher mostrar de quem é o workspace quando compartilhado."""
    linha = session.exec(
        _owner_expr().where(WorkspaceMembership.workspace_id == workspace.id)
    ).first()
    owner = (linha[1], linha[2]) if linha else None
    member_count = session.exec(
        _count_expr().where(WorkspaceMembership.workspace_id == workspace.id)
    ).first()
    return _build_read(workspace, owner, member_count[1] if member_count else 0)


def _to_read_many(session: Session, workspaces: List[Workspace]) -> List[WorkspaceRead]:
    """Versão em lote: 2 queries no total em vez de 2 POR workspace (N+1)."""
    if not workspaces:
        return []
    ws_ids = [w.id for w in workspaces]

    owners = {
        ws_id: (user_id, nome)
        for ws_id, user_id, nome in session.exec(
            _owner_expr().where(WorkspaceMembership.workspace_id.in_(ws_ids))
        ).all()
    }
    counts = dict(session.exec(
        _count_expr().where(WorkspaceMembership.workspace_id.in_(ws_ids))
    ).all())

    return [
        _build_read(w, owners.get(w.id), counts.get(w.id, 0))
        for w in workspaces
    ]


@_tambem_sem_barra("post", response_model=WorkspaceRead)
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
        created_by_user_id=current_user.id,
        # Ausente = o default do model (BRL). O código já vem normalizado e
        # validado como ISO-3 pelo `OptionalCurrencyCode` (422 na borda).
        **({"base_currency": workspace_in.base_currency} if workspace_in.base_currency else {}),
        # Idem para o controle de pagamento (ADR 0029): `None` cai no default do
        # model (ligado). `if ... is not None`, e não a forma curta de cima, porque
        # aqui `False` é uma resposta legítima — com `if valor` ela viraria "não
        # opinou" e o espaço nasceria com o controle ligado contra a escolha.
        **(
            {"settlement_tracking": workspace_in.settlement_tracking}
            if workspace_in.settlement_tracking is not None
            else {}
        ),
    )
    session.add(workspace)
    session.commit()
    session.refresh(workspace)

    membership = WorkspaceMembership(
        workspace_id=workspace.id,
        user_id=current_user.id,
        role=WorkspaceRole.owner,
        # Explícito para a linha não mentir sobre si mesma: `effective_access` já
        # daria acesso completo pelo cargo, mas o banco fica coerente com isso.
        financial_access=FinancialAccess.full_workspace,
    )
    session.add(membership)
    seed_default_categories(session, workspace.id)
    session.commit()

    return _to_read(session, workspace)


@_tambem_sem_barra("get", response_model=List[WorkspaceRead])
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
        # Ordem EXPLÍCITA: sem ela o banco devolvia na ordem que quisesse, e o
        # cliente escolhe o workspace ativo como `workspaces[0]`. Quem se cadastra
        # por convite nasce com dois (o pessoal e o compartilhado), então a tela
        # inicial abria num ou noutro de forma não determinística.
        .order_by(Workspace.id)
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
        except AccountsInOldCurrency as exc:
            # 409, e não 422: o pedido está bem formado e a cotação existe — o
            # estado atual é que não permite. É a mesma leitura do 409 que impede
            # deixar um espaço órfão de dono (ADR 0028).
            session.rollback()
            raise HTTPException(status_code=409, detail=str(exc))
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


@router.get("/{workspace_id}/base-currency/preview", response_model=BaseCurrencyPreviewRead)
def preview_base_currency_change(
    workspace_id: int,
    to: str,
    session: Session = Depends(get_session),
    membership: WorkspaceMembership = Depends(require_role(WorkspaceRole.admin)),
):
    """Dry-run da troca de moeda-base: quantas linhas seriam reconvertidas e que
    cotações faltam. A UI usa isto para avisar ANTES de confirmar — a troca é
    uma reescrita de todo o histórico financeiro do workspace."""
    try:
        to = normalize_currency_code(to)
    except InvalidCurrencyCode as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    report = BaseCurrencyService.plan_conversion(session, workspace_id, to)
    return report.as_dict()


@router.delete("/{workspace_id}", response_model=StatusRead)
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
