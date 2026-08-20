from datetime import date, datetime
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session, select
from app.db.session import get_session
from app.domain.access_policy import assert_can_read, assert_can_write, shared_or_mine_scope
from app.domain.query_policy import resolve_currency
from app.domain.recurrence_rules import validate_frequency_fields as _validate_frequency_fields
from app.models.category import Category
from app.models.credit_card import CreditCard
from app.models.workspace import WorkspaceMembership, WorkspaceRole
from app.models.recurring import (
    RecurrenceFrequency,
    RecurringExpense,
    RecurringExpenseBase,
)
from app.models.transaction import Transaction, PaymentMethod, SplitMethod, TransactionStatus
from app.api.deps import get_workspace_membership, require_role
from app.services.event_service import publish_event
from app.services.recurring_service import (
    EDIT_SCOPES,
    MATERIALIZE_SCOPES,
    RecurringMaterializationService,
    RecurringService,
)
from pydantic import BaseModel, Field

from app.schemas.common import CreatedCountRead, DESCRIPTION_MAX, MAX_MONEY, OptionalCurrencyCode, StatusRead, TITLE_MAX
from app.domain.dates import today_local
from decimal import Decimal

router = APIRouter(prefix="/workspaces/{workspace_id}/recurring", tags=["recurring"])


class RecurringSplitEntry(BaseModel):
    user_id: int
    split_method: SplitMethod = SplitMethod.equal
    input_value: Decimal = Field(default=Decimal("0"), ge=0, le=MAX_MONEY)


class RecurringCreate(BaseModel):
    title: str = Field(min_length=1, max_length=TITLE_MAX)
    description: Optional[str] = Field(default=None, max_length=DESCRIPTION_MAX)
    base_amount: Decimal = Field(gt=0, le=MAX_MONEY)
    frequency: RecurrenceFrequency = RecurrenceFrequency.monthly
    interval: int = Field(default=1, ge=1)
    start_date: Optional[date] = None
    # Fim da série (ADR 0030). `end_after_occurrences` é a mesma coisa dita de
    # outro jeito ("por 144 vezes") e o servidor a converte em `end_date`; só
    # esta última é persistida, para não haver duas verdades sobre quando acaba.
    end_date: Optional[date] = None
    end_after_occurrences: Optional[int] = Field(default=None, ge=1, le=600)
    day_of_month: int = Field(default=1, ge=1, le=31)
    day_of_week: Optional[int] = Field(default=None, ge=0, le=6)
    month_of_year: Optional[int] = Field(default=None, ge=1, le=12)
    # Snapshot (ADR 0012): materializa despesa completa em vez de nua
    # None = "não informada" → a rota resolve para a moeda-base do workspace
    currency: OptionalCurrencyCode = None
    payment_method: Optional[PaymentMethod] = None
    # "Pagamento automático" (ADR 0029): débito em conta, Pix automático. A
    # ocorrência nasce liquidada e não entra em Contas a pagar.
    auto_settle: bool = False
    credit_card_id: Optional[int] = None
    category_id: Optional[int] = None
    payer_user_id: Optional[int] = None
    split_snapshot: Optional[List[RecurringSplitEntry]] = None


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


class RecurringUpdate(BaseModel):
    title: Optional[str] = Field(default=None, min_length=1, max_length=TITLE_MAX)
    description: Optional[str] = Field(default=None, max_length=DESCRIPTION_MAX)
    base_amount: Optional[Decimal] = Field(default=None, gt=0, le=MAX_MONEY)
    frequency: Optional[RecurrenceFrequency] = None
    interval: Optional[int] = Field(default=None, ge=1)
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    end_after_occurrences: Optional[int] = Field(default=None, ge=1, le=600)
    day_of_month: Optional[int] = Field(default=None, ge=1, le=31)
    day_of_week: Optional[int] = Field(default=None, ge=0, le=6)
    month_of_year: Optional[int] = Field(default=None, ge=1, le=12)
    is_active: Optional[bool] = None
    currency: OptionalCurrencyCode = None
    payment_method: Optional[PaymentMethod] = None
    auto_settle: Optional[bool] = None
    credit_card_id: Optional[int] = None
    category_id: Optional[int] = None
    payer_user_id: Optional[int] = None
    split_snapshot: Optional[List[RecurringSplitEntry]] = None


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


def _get_recurring_or_404(
    session: Session, workspace_id: int, recurring_id: int, membership: WorkspaceMembership
) -> RecurringExpense:
    db_recurring = session.get(RecurringExpense, recurring_id)
    if not db_recurring or db_recurring.workspace_id != workspace_id:
        raise HTTPException(status_code=404, detail="Despesa recorrente não encontrada")
    # Template sem criador é da casa e todos veem; com criador, só o dono
    if db_recurring.created_by_user_id is not None:
        assert_can_read(
            db_recurring.created_by_user_id,
            membership,
            detail="Despesa recorrente não encontrada",
        )
    return db_recurring


def _check_ownership(membership: WorkspaceMembership, template: RecurringExpense) -> None:
    """Member mexe só no que é dele; admin+ mexe em tudo.

    Mesmo gate de transações, rendas, acertos e anexos — a recorrência era a
    única entidade em que qualquer member editava ou apagava template alheio.
    """
    assert_can_write(
        template.created_by_user_id,
        membership,
        detail="Você só pode alterar as próprias despesas recorrentes",
        # Template sem criador é o gasto fixo da casa (aluguel, luz), não autoria
        # perdida de um lançamento pessoal
        null_is_shared=True,
    )


def _validate_snapshot(
    session: Session,
    workspace_id: int,
    category_id: Optional[int],
    payer_user_id: Optional[int],
    split_snapshot: Optional[List[RecurringSplitEntry]],
    credit_card_id: Optional[int] = None,
    payment_method: Optional[PaymentMethod] = None,
    *,
    actor_user_id: Optional[int] = None,
) -> None:
    if category_id is not None:
        category = session.get(Category, category_id)
        if not category or category.workspace_id != workspace_id or category.deleted_at:
            raise HTTPException(status_code=400, detail="Categoria inválida para este workspace")
    if credit_card_id is not None:
        card = session.get(CreditCard, credit_card_id)
        # Cartão é pessoal (ADR 0021): tem de ser de quem vai pagar a recorrência
        # — o pagador declarado, ou quem está cadastrando quando não há um.
        dono_esperado = payer_user_id if payer_user_id is not None else actor_user_id
        if not card or card.deleted_at or card.owner_user_id != dono_esperado:
            raise HTTPException(status_code=400, detail="Cartão de crédito inválido")
        # Mesma regra da despesa avulsa: cartão só faz sentido no crédito, senão
        # a instância cairia numa fatura sem ter sido comprada no cartão
        if payment_method != PaymentMethod.credit_card:
            raise HTTPException(
                status_code=400,
                detail="Cartão de crédito só se aplica à forma de pagamento 'credit_card'",
            )
    member_ids = set(session.exec(
        select(WorkspaceMembership.user_id).where(WorkspaceMembership.workspace_id == workspace_id)
    ).all())
    users = set()
    if payer_user_id is not None:
        users.add(payer_user_id)
    for entry in split_snapshot or []:
        users.add(entry.user_id)
    outsiders = users - member_ids
    if outsiders:
        raise HTTPException(
            status_code=400,
            detail=f"Usuário(s) {sorted(outsiders)} não pertence(m) a este workspace",
        )


def _snapshot_json(split_snapshot: Optional[List[RecurringSplitEntry]]):
    if not split_snapshot:
        return None
    return [e.model_dump(mode="json") for e in split_snapshot]


def _resolve_end_date(data: dict, template) -> None:
    """"Por N ocorrências" vira `end_date`, in place (ADR 0030).

    A conversão precisa do template com os campos JÁ atualizados — o fim de "por
    144 vezes" depende da frequência, do intervalo e do dia, e todos podem estar
    mudando na mesma requisição. Por isso roda depois dos `setattr`/da montagem.

    Persistimos só `end_date`: guardar as duas formas criaria duas verdades sobre
    quando a série acaba, e elas divergiriam na primeira edição de frequência.
    """
    quantas = data.pop("end_after_occurrences", None)
    if quantas is None:
        return
    fim = RecurringService.end_date_after(template, quantas)
    if fim is None:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Não foi possível calcular o fim para {quantas} ocorrências — "
                "revise a data de início e a frequência"
            ),
        )
    data["end_date"] = fim


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
    if materialize not in MATERIALIZE_SCOPES:
        raise HTTPException(status_code=400, detail=f"materialize deve ser um de {list(MATERIALIZE_SCOPES)}")
    _validate_frequency_fields(
        recurring_in.frequency, recurring_in.day_of_week, recurring_in.month_of_year,
        recurring_in.interval, recurring_in.start_date, recurring_in.end_date,
    )
    _validate_snapshot(
        session, workspace_id,
        recurring_in.category_id, recurring_in.payer_user_id, recurring_in.split_snapshot,
        recurring_in.credit_card_id, recurring_in.payment_method,
        actor_user_id=membership.user_id,
    )
    data = recurring_in.model_dump(exclude={"split_snapshot"})
    # Moeda ausente = a do workspace (nunca "BRL" fixo — ver resolve_currency)
    data["currency"] = resolve_currency(session, workspace_id, recurring_in.currency)
    # "Por N ocorrências" → `end_date`. Antes do construtor: o campo de entrada
    # não é coluna, e passá-lo adiante estouraria com argumento desconhecido.
    _resolve_end_date(data, recurring_in)
    db_recurring = RecurringExpense(
        **data,
        split_snapshot=_snapshot_json(recurring_in.split_snapshot),
        workspace_id=workspace_id,
        created_by_user_id=membership.user_id,
    )
    session.add(db_recurring)
    session.flush()
    RecurringMaterializationService.apply_scope(
        session, workspace_id, db_recurring, materialize, is_income=False
    )
    publish_event(session, workspace_id, "recurring.created", "recurring", db_recurring.id, membership.user_id)
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
    if scope not in EDIT_SCOPES:
        raise HTTPException(status_code=400, detail=f"scope deve ser um de {list(EDIT_SCOPES)}")
    if materialize not in MATERIALIZE_SCOPES:
        raise HTTPException(status_code=400, detail=f"materialize deve ser um de {list(MATERIALIZE_SCOPES)}")
    db_recurring = _get_recurring_or_404(session, workspace_id, recurring_id, membership)
    _check_ownership(membership, db_recurring)

    update_data = recurring_in.model_dump(exclude_unset=True)
    snapshot_provided = "split_snapshot" in update_data
    update_data.pop("split_snapshot", None)
    # `end_after_occurrences` sai daqui e não vira atributo: ele não é coluna, e
    # o `setattr` abaixo gravaria um campo fantasma no objeto do ORM — aceito
    # pelo SQLModel, jamais persistido, e sem erro.
    quantas = update_data.pop("end_after_occurrences", None)
    for key, value in update_data.items():
        setattr(db_recurring, key, value)
    if snapshot_provided:
        db_recurring.split_snapshot = _snapshot_json(recurring_in.split_snapshot)
    if quantas is not None:
        # Depois dos `setattr`: o fim de "por 144 vezes" depende da frequência,
        # do intervalo e do dia, e os três podem estar mudando nesta requisição.
        resolvido = {"end_after_occurrences": quantas}
        _resolve_end_date(resolvido, db_recurring)
        db_recurring.end_date = resolvido["end_date"]

    # Estado FINAL precisa ser coerente (frequência × campos auxiliares + snapshot)
    _validate_frequency_fields(
        db_recurring.frequency, db_recurring.day_of_week, db_recurring.month_of_year,
        db_recurring.interval, db_recurring.start_date, db_recurring.end_date,
    )
    _validate_snapshot(
        session, workspace_id,
        db_recurring.category_id, db_recurring.payer_user_id, recurring_in.split_snapshot,
        db_recurring.credit_card_id, db_recurring.payment_method,
        actor_user_id=db_recurring.created_by_user_id or membership.user_id,
    )

    session.add(db_recurring)
    session.flush()
    if apply_to is not None or create_occurrence is not None:
        # Caminho da REVISÃO (ADR 0030): a pessoa viu a lista e marcou o que
        # ajustar. O plano é recalculado aqui a partir do template JÁ atualizado
        # — `plan` sem `changes`, porque os `setattr` acima já o deixaram no
        # estado futuro. Recalcular (em vez de confiar no que a tela mandou) é o
        # que impede que uma lista velha, aberta há dez minutos, mova um
        # lançamento que outra pessoa pagou nesse meio-tempo: as travas de
        # congelamento correm de novo, agora contra o banco.
        plano = RecurringService.plan(session, db_recurring, since=since)
        RecurringService.apply_plan(
            session, db_recurring, plano,
            apply_to=apply_to, create_occurrences=create_occurrence,
        )
    else:
        # Propaga a mudança às instâncias não pagas conforme o escopo (ADR 0012).
        # Caminho legado: sem revisão, a data continua congelada.
        RecurringService.sync_unpaid_instances(session, db_recurring.id, scope)
    # ...e materializa o que ainda falta conforme o escopo de datas escolhido
    RecurringMaterializationService.apply_scope(
        session, workspace_id, db_recurring, materialize, is_income=False
    )
    publish_event(session, workspace_id, "recurring.updated", "recurring", db_recurring.id, membership.user_id)
    # Instâncias podem ter mudado → invalida caixa/relatórios também
    publish_event(session, workspace_id, "transaction.bulk_updated", "transaction", None, membership.user_id)
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
