from datetime import date
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session, select
from app.db.session import get_session
from app.models.category import Category
from app.models.workspace import WorkspaceMembership, WorkspaceRole
from app.models.recurring import RecurringExpense, RecurrenceFrequency
from app.models.transaction import Transaction, PaymentMethod, SplitMethod
from app.api.deps import get_workspace_membership, require_role
from app.services.event_service import publish_event
from app.services.recurring_service import RecurringService, EDIT_SCOPES
from pydantic import BaseModel, Field
from decimal import Decimal

router = APIRouter(prefix="/workspaces/{workspace_id}/recurring", tags=["recurring"])


class RecurringSplitEntry(BaseModel):
    user_id: int
    split_method: SplitMethod = SplitMethod.equal
    input_value: Decimal = Field(default=Decimal("0"), ge=0)


class RecurringCreate(BaseModel):
    title: str
    description: Optional[str] = None
    base_amount: Decimal = Field(gt=0)
    frequency: RecurrenceFrequency = RecurrenceFrequency.monthly
    interval: int = Field(default=1, ge=1)
    start_date: Optional[date] = None
    day_of_month: int = Field(default=1, ge=1, le=31)
    day_of_week: Optional[int] = Field(default=None, ge=0, le=6)
    month_of_year: Optional[int] = Field(default=None, ge=1, le=12)
    # Snapshot (ADR 0012): materializa despesa completa em vez de nua
    currency: str = "BRL"
    payment_method: Optional[PaymentMethod] = None
    category_id: Optional[int] = None
    payer_user_id: Optional[int] = None
    split_snapshot: Optional[List[RecurringSplitEntry]] = None


class RecurringUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    base_amount: Optional[Decimal] = Field(default=None, gt=0)
    frequency: Optional[RecurrenceFrequency] = None
    interval: Optional[int] = Field(default=None, ge=1)
    start_date: Optional[date] = None
    day_of_month: Optional[int] = Field(default=None, ge=1, le=31)
    day_of_week: Optional[int] = Field(default=None, ge=0, le=6)
    month_of_year: Optional[int] = Field(default=None, ge=1, le=12)
    is_active: Optional[bool] = None
    currency: Optional[str] = None
    payment_method: Optional[PaymentMethod] = None
    category_id: Optional[int] = None
    payer_user_id: Optional[int] = None
    split_snapshot: Optional[List[RecurringSplitEntry]] = None


def _validate_frequency_fields(
    frequency: RecurrenceFrequency,
    day_of_week: Optional[int],
    month_of_year: Optional[int],
    interval: int = 1,
    start_date: Optional[date] = None,
) -> None:
    # Personalizado (a cada N>1): tudo deriva de start_date, que passa a ser exigido
    if interval and interval > 1:
        if start_date is None:
            raise HTTPException(status_code=400, detail="Recorrência personalizada (a cada N) exige a data de início")
        return
    if frequency == RecurrenceFrequency.weekly and day_of_week is None:
        raise HTTPException(status_code=400, detail="Recorrência semanal exige o dia da semana")
    if frequency == RecurrenceFrequency.yearly and month_of_year is None:
        raise HTTPException(status_code=400, detail="Recorrência anual exige o mês do ano")


def _get_recurring_or_404(session: Session, workspace_id: int, recurring_id: int) -> RecurringExpense:
    db_recurring = session.get(RecurringExpense, recurring_id)
    if not db_recurring or db_recurring.workspace_id != workspace_id:
        raise HTTPException(status_code=404, detail="Recurring expense not found")
    return db_recurring


def _validate_snapshot(
    session: Session,
    workspace_id: int,
    category_id: Optional[int],
    payer_user_id: Optional[int],
    split_snapshot: Optional[List[RecurringSplitEntry]],
) -> None:
    if category_id is not None:
        category = session.get(Category, category_id)
        if not category or category.workspace_id != workspace_id or category.deleted_at:
            raise HTTPException(status_code=400, detail="Categoria inválida para este workspace")
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


@router.post("", response_model=RecurringExpense)
def create_recurring(
    workspace_id: int,
    recurring_in: RecurringCreate,
    session: Session = Depends(get_session),
    membership: WorkspaceMembership = Depends(require_role(WorkspaceRole.member))
):
    _validate_frequency_fields(
        recurring_in.frequency, recurring_in.day_of_week, recurring_in.month_of_year,
        recurring_in.interval, recurring_in.start_date,
    )
    _validate_snapshot(
        session, workspace_id,
        recurring_in.category_id, recurring_in.payer_user_id, recurring_in.split_snapshot,
    )
    data = recurring_in.model_dump(exclude={"split_snapshot"})
    db_recurring = RecurringExpense(
        **data,
        split_snapshot=_snapshot_json(recurring_in.split_snapshot),
        workspace_id=workspace_id,
        created_by_user_id=membership.user_id,
    )
    session.add(db_recurring)
    session.flush()
    publish_event(session, workspace_id, "recurring.created", "recurring", db_recurring.id, membership.user_id)
    session.commit()
    session.refresh(db_recurring)
    return db_recurring


@router.post("/generate")
def generate_recurring_instances(
    workspace_id: int,
    session: Session = Depends(get_session),
    membership: WorkspaceMembership = Depends(require_role(WorkspaceRole.member))
):
    """Materializa as instâncias vencidas do mês corrente (idempotente)."""
    created = RecurringService.generate_due_instances(session, workspace_id, date.today())
    if created:
        publish_event(
            session, workspace_id, "transaction.bulk_created", "transaction", None, membership.user_id
        )
    session.commit()
    return {"created": created}


@router.get("", response_model=List[RecurringExpense])
def list_recurring(
    workspace_id: int,
    session: Session = Depends(get_session),
    membership: WorkspaceMembership = Depends(get_workspace_membership)
):
    return session.exec(select(RecurringExpense).where(RecurringExpense.workspace_id == workspace_id)).all()


@router.get("/{recurring_id}", response_model=RecurringExpense)
def get_recurring(
    workspace_id: int,
    recurring_id: int,
    session: Session = Depends(get_session),
    membership: WorkspaceMembership = Depends(get_workspace_membership)
):
    return _get_recurring_or_404(session, workspace_id, recurring_id)


@router.put("/{recurring_id}", response_model=RecurringExpense)
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
):
    if scope not in EDIT_SCOPES:
        raise HTTPException(status_code=400, detail=f"scope deve ser um de {list(EDIT_SCOPES)}")
    db_recurring = _get_recurring_or_404(session, workspace_id, recurring_id)

    update_data = recurring_in.model_dump(exclude_unset=True)
    snapshot_provided = "split_snapshot" in update_data
    update_data.pop("split_snapshot", None)
    for key, value in update_data.items():
        setattr(db_recurring, key, value)
    if snapshot_provided:
        db_recurring.split_snapshot = _snapshot_json(recurring_in.split_snapshot)

    # Estado FINAL precisa ser coerente (frequência × campos auxiliares + snapshot)
    _validate_frequency_fields(
        db_recurring.frequency, db_recurring.day_of_week, db_recurring.month_of_year,
        db_recurring.interval, db_recurring.start_date,
    )
    _validate_snapshot(
        session, workspace_id,
        db_recurring.category_id, db_recurring.payer_user_id, recurring_in.split_snapshot,
    )

    session.add(db_recurring)
    session.flush()
    # Propaga a mudança às instâncias não pagas conforme o escopo (ADR 0012)
    RecurringService.sync_unpaid_instances(session, db_recurring.id, scope)
    publish_event(session, workspace_id, "recurring.updated", "recurring", db_recurring.id, membership.user_id)
    # Instâncias podem ter mudado → invalida caixa/relatórios também
    publish_event(session, workspace_id, "transaction.bulk_updated", "transaction", None, membership.user_id)
    session.commit()
    session.refresh(db_recurring)
    return db_recurring


@router.delete("/{recurring_id}")
def delete_recurring(
    workspace_id: int,
    recurring_id: int,
    session: Session = Depends(get_session),
    membership: WorkspaceMembership = Depends(require_role(WorkspaceRole.member))
):
    db_recurring = _get_recurring_or_404(session, workspace_id, recurring_id)

    # Desvincula instâncias já geradas antes de excluir o template — sem isso
    # a FK transaction.recurring_expense_id viola no Postgres (500)
    instances = session.exec(
        select(Transaction).where(Transaction.recurring_expense_id == recurring_id)
    ).all()
    for tx in instances:
        tx.recurring_expense_id = None
        session.add(tx)

    session.delete(db_recurring)
    publish_event(session, workspace_id, "recurring.deleted", "recurring", recurring_id, membership.user_id)
    session.commit()
    return {"status": "ok"}
