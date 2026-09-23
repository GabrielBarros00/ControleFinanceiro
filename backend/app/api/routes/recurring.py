from datetime import date, datetime
from typing import List, Optional
from fastapi import APIRouter, Depends, Query
from sqlmodel import Session, select
from app.db.session import get_session
from app.domain.access_policy import shared_or_mine_scope
from app.models.workspace import WorkspaceMembership, WorkspaceRole
from app.models.recurring import (
    RecurringExpense,
    RecurringExpenseBase,
)
from app.models.transaction import (
    Transaction,
    PaymentMethod,
    TransactionStatus,
)
from app.api.deps import get_workspace_membership, require_role
from app.services.event_service import publish_event
from app.services.recurring_service import (
    RecurringService,
)
from pydantic import BaseModel, Field

from app.schemas.common import CreatedCountRead, StatusRead
from app.domain.dates import today_local
from decimal import Decimal
from app.schemas.recurring import RecurringCreate, RecurringUpdate

from app.services.commands import recurring as rec_cmd
from app.services.commands.recurring import (
    _check_ownership,
    _get_recurring_or_404,
)

router = APIRouter(prefix="/workspaces/{workspace_id}/recurring", tags=["recurring"])


class RecurringPlanItem(BaseModel):
    """Uma linha da revisão: o lançamento e o que vai acontecer com ele."""
    #: `None` nas ocorrências que ainda não existem (`action='create'`).
    transaction_id: Optional[int] = None
    occurrence_date: date
    #: Para onde a data vai, quando `action='move'`.
    new_occurrence_date: Optional[date] = None
    billing_month: Optional[str] = None
    status: Optional[str] = None
    #: `update` | `move` | `cancel` | `create` | `none`.
    action: str
    #: Por que este lançamento não será tocado (pago, cancelado).
    frozen_reason: Optional[str] = None
    title: str
    #: Valor atual; `None` quando a linha ainda não existe e não houve cotação.
    amount: Optional[Decimal] = None
    #: `{campo: {from, to}}` — só título, valor e data, que é o que se reconhece
    #: na linha. Divisão e categoria acompanham sempre.
    changes: dict = Field(default_factory=dict)


class RecurringPlanRead(BaseModel):
    items: List[RecurringPlanItem]


class RecurringRead(RecurringExpenseBase):
    """O template como a interface o lê — com o que a lista precisa mostrar.

    Herda de `RecurringExpenseBase` e **não** de `RecurringExpense`: o model de
    tabela carrega o `Relationship` `transactions`, e o Pydantic não sabe gerar
    schema para um `Mapped[List[Transaction]]` — o app nem sobe. A base traz os
    campos de calendário e valor; o resto é declarado abaixo.

    Os dois últimos são DERIVADOS (ADR 0030), não colunas: a contagem depende da
    frequência e do intervalo, então armazená-la exigiria recalcular a cada
    edição, e a cópia ficaria errada na primeira que alguém esquecesse.
    """
    id: int
    workspace_id: int
    created_by_user_id: Optional[int] = None
    currency: str = "BRL"
    payment_method: Optional[PaymentMethod] = None
    auto_settle: bool = False
    credit_card_id: Optional[int] = None
    statement_shift: int = 0
    category_id: Optional[int] = None
    payer_user_id: Optional[int] = None
    split_snapshot: Optional[List[dict]] = None
    created_at: datetime
    updated_at: datetime
    #: Quantas ocorrências a série tem ao todo. `None` = sem fim.
    occurrences_total: Optional[int] = None
    #: Quantas ainda faltam (hoje inclusive). `None` = sem fim.
    occurrences_remaining: Optional[int] = None


class RecurringPreviewRequest(BaseModel):
    """"O que acontece se eu salvar isto?" — sem salvar nada (ADR 0030).

    Depois de `RecurringUpdate` por necessidade: `changes` é o MESMO corpo do
    PUT — a revisão tem de planejar a partir da edição que está na tela, não do
    que já está no banco.
    """
    action: str = Field(default="update", pattern="^(update|deactivate|delete)$")
    changes: Optional[RecurringUpdate] = None
    #: "Aplicar a partir de" — 1º do mês corrente quando ausente.
    since: Optional[date] = None


def _to_read(template: RecurringExpense) -> dict:
    """O template com o que a lista precisa para dizer "87 de 144 restantes".

    Campos derivados e não colunas: a contagem depende da frequência e do
    intervalo, então armazená-la exigiria recalcular a cada edição — e a cópia
    ficaria errada na primeira que alguém esquecesse.
    """
    total = RecurringService.count_occurrences(template)
    hoje = today_local()
    restantes = (
        None
        if total is None
        else max(0, total - (RecurringService.count_occurrences(template, ate=hoje) or 0))
    )
    return {
        **template.model_dump(),
        "occurrences_total": total,
        "occurrences_remaining": restantes,
    }


@router.post("", response_model=RecurringRead)
def create_recurring(
    workspace_id: int,
    recurring_in: RecurringCreate,
    session: Session = Depends(get_session),
    membership: WorkspaceMembership = Depends(require_role(WorkspaceRole.member)),
    materialize: str = Query(
        "current",
        description="Escopo da materialização com start_date retroativa: past | current | future",
    ),
):
    db_recurring = rec_cmd.create_recurring(session, workspace_id, recurring_in, membership, materialize)
    session.commit()
    session.refresh(db_recurring)
    return _to_read(db_recurring)


@router.post("/generate", response_model=CreatedCountRead)
def generate_recurring_instances(
    workspace_id: int,
    session: Session = Depends(get_session),
    membership: WorkspaceMembership = Depends(require_role(WorkspaceRole.member))
):
    """Materializa as instâncias vencidas do mês corrente (idempotente)."""
    created = RecurringService.generate_due_instances(session, workspace_id, today_local())
    if created:
        publish_event(
            session, workspace_id, "transaction.bulk_created", "transaction", None, membership.user_id
        )
    session.commit()
    return {"created": created}


@router.get("", response_model=List[RecurringRead])
def list_recurring(
    workspace_id: int,
    session: Session = Depends(get_session),
    membership: WorkspaceMembership = Depends(get_workspace_membership)
):
    return [
        _to_read(t)
        for t in session.exec(
            select(RecurringExpense).where(
                RecurringExpense.workspace_id == workspace_id,
                # Recorrência sem criador é da casa (aluguel que todos rateiam);
                # com criador, só a minha (ADR 0018)
                shared_or_mine_scope(RecurringExpense.created_by_user_id, membership),
            )
        ).all()
    ]


@router.get("/{recurring_id}", response_model=RecurringRead)
def get_recurring(
    workspace_id: int,
    recurring_id: int,
    session: Session = Depends(get_session),
    membership: WorkspaceMembership = Depends(get_workspace_membership)
):
    return _to_read(_get_recurring_or_404(session, workspace_id, recurring_id, membership))


@router.post("/{recurring_id}/preview", response_model=RecurringPlanRead)
def preview_recurring(
    workspace_id: int,
    recurring_id: int,
    body: RecurringPreviewRequest,
    session: Session = Depends(get_session),
    membership: WorkspaceMembership = Depends(require_role(WorkspaceRole.member)),
):
    """O que acontece com cada lançamento se eu salvar isto (ADR 0030).

    **Não escreve nada.** É `POST` porque leva um corpo — a edição que está na
    tela —, não porque muda estado: a rota planeja a partir de `changes` e do
    template atual, e devolve a lista que a revisão desenha.

    A mesma função (`RecurringService.plan`) alimenta a escrita, e é isso que
    impede a tela de prometer uma coisa e o servidor fazer outra. O gate é o de
    ESCRITA (`require_role(member)` + `_check_ownership`): quem não pode editar o
    template também não tem por que saber quantos lançamentos ele gerou.
    """
    db_recurring = _get_recurring_or_404(session, workspace_id, recurring_id, membership)
    _check_ownership(membership, db_recurring)
    plano = RecurringService.plan(
        session,
        db_recurring,
        changes=body.changes.model_dump(exclude_unset=True) if body.changes else None,
        since=body.since,
        action=body.action,
    )
    return {"items": plano}


@router.put("/{recurring_id}", response_model=RecurringRead)
def update_recurring(
    workspace_id: int,
    recurring_id: int,
    recurring_in: RecurringUpdate,
    session: Session = Depends(get_session),
    membership: WorkspaceMembership = Depends(require_role(WorkspaceRole.member)),
    scope: str = Query(
        "future",
        description="Escopo da edição sobre instâncias não pagas: none | future | all",
    ),
    materialize: str = Query(
        "current",
        description="Escopo da materialização com start_date retroativa: past | current | future",
    ),
    apply_to: Optional[List[int]] = Query(
        None,
        description=(
            "Ids dos lançamentos escolhidos na revisão (ADR 0030). Informado, "
            "substitui `scope`: só estes são ajustados, e a data acompanha."
        ),
    ),
    create_occurrence: Optional[List[date]] = Query(
        None,
        description="Datas das ocorrências a criar, escolhidas na revisão.",
    ),
    since: Optional[date] = Query(
        None, description="'Aplicar a partir de' — recorta o plano da revisão."
    ),
):
    db_recurring = rec_cmd.update_recurring(
        session, workspace_id, recurring_id, recurring_in, membership,
        scope=scope, materialize=materialize, apply_to=apply_to,
        create_occurrence=create_occurrence, since=since,
    )
    session.commit()
    session.refresh(db_recurring)
    return _to_read(db_recurring)


@router.delete("/{recurring_id}", response_model=StatusRead)
def delete_recurring(
    workspace_id: int,
    recurring_id: int,
    session: Session = Depends(get_session),
    membership: WorkspaceMembership = Depends(require_role(WorkspaceRole.member)),
    cancel_instance: Optional[List[int]] = Query(
        None,
        description=(
            "Ids dos lançamentos JÁ GERADOS a cancelar junto (ADR 0030). "
            "Ausente, nenhum é tocado — o comportamento de sempre."
        ),
    ),
):
    """Exclui o template. Os lançamentos já gerados sobrevivem, salvo escolha.

    Excluir a recorrência nunca apagou lançamento nenhum, e a confirmação dizia
    isso numa linha em cinza — sem oferecer alternativa. Era a razão de "excluí a
    recorrência e nada mudou no Geral": de fato nada mudava, porque a despesa do
    mês corrente continuava lá, confirmada e contando.

    Agora a revisão lista o que existe e a pessoa escolhe. O que ela marcar é
    CANCELADO (status terminal, fora de toda agregação), não excluído: cancelar
    mantém o rastro do que já esteve no mês, e é a mesma decisão do cancelamento
    de parcelas futuras de uma compra parcelada.
    """
    db_recurring = _get_recurring_or_404(session, workspace_id, recurring_id, membership)
    _check_ownership(membership, db_recurring)

    # Desvincula instâncias já geradas antes de excluir o template — sem isso
    # a FK transaction.recurring_expense_id viola no Postgres (500)
    instances = session.exec(
        select(Transaction).where(Transaction.recurring_expense_id == recurring_id)
    ).all()
    escolhidos = set(cancel_instance or [])
    for tx in instances:
        # Cancela ANTES de desvincular: depois do `recurring_expense_id = None` a
        # linha deixa de ser identificável como ocorrência desta recorrência.
        # Paga não se toca (ADR 0003) — ela é pulada, não recusada, senão excluir
        # um template inteiro falharia por causa de um mês já quitado.
        if tx.id in escolhidos and tx.status not in (
            TransactionStatus.paid, TransactionStatus.cancelled
        ):
            tx.status = TransactionStatus.cancelled
        tx.recurring_expense_id = None
        session.add(tx)

    session.delete(db_recurring)
    publish_event(session, workspace_id, "recurring.deleted", "recurring", recurring_id, membership.user_id)
    if escolhidos:
        # Cancelar lançamento muda caixa, dívidas e relatórios — o evento de
        # recorrência sozinho não alcança quem está com o extrato aberto.
        publish_event(
            session, workspace_id, "transaction.bulk_updated",
            "transaction", None, membership.user_id,
        )
    session.commit()
    return {"status": "ok"}
