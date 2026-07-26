from datetime import date, datetime, UTC
from decimal import Decimal
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.schemas.common import DESCRIPTION_MAX, MAX_MONEY, NAME_MAX, TITLE_MAX
from sqlmodel import Session, select

from app.db.session import get_session
from app.models.workspace import WorkspaceMembership, WorkspaceRole, role_level
from app.models.recurring import RecurringIncome, RecurrenceFrequency
from app.models.income import Income
from app.api.deps import get_workspace_membership, require_role
from app.services.event_service import publish_event
from app.services.recurring_service import (
    MATERIALIZE_SCOPES,
    RecurringIncomeService,
    RecurringMaterializationService,
)

router = APIRouter(prefix="/workspaces/{workspace_id}/recurring-income", tags=["recurring-income"])


class RecurringIncomeCreate(BaseModel):
    title: str = Field(min_length=1, max_length=TITLE_MAX)
    description: Optional[str] = Field(default=None, max_length=DESCRIPTION_MAX)
    base_amount: Decimal = Field(gt=0, le=MAX_MONEY)
    currency: str = "BRL"
    category: Optional[str] = Field(default=None, max_length=NAME_MAX)
    frequency: RecurrenceFrequency = RecurrenceFrequency.monthly
    interval: int = Field(default=1, ge=1)
    start_date: Optional[date] = None
    day_of_month: int = Field(default=1, ge=1, le=31)
    day_of_week: Optional[int] = Field(default=None, ge=0, le=6)
    month_of_year: Optional[int] = Field(default=None, ge=1, le=12)
    is_active: bool = True


class RecurringIncomeUpdate(BaseModel):
    title: Optional[str] = Field(default=None, min_length=1, max_length=TITLE_MAX)
    description: Optional[str] = Field(default=None, max_length=DESCRIPTION_MAX)
    base_amount: Optional[Decimal] = Field(default=None, gt=0, le=MAX_MONEY)
    currency: Optional[str] = None
    category: Optional[str] = Field(default=None, max_length=NAME_MAX)
    frequency: Optional[RecurrenceFrequency] = None
    interval: Optional[int] = Field(default=None, ge=1)
    start_date: Optional[date] = None
    day_of_month: Optional[int] = Field(default=None, ge=1, le=31)
    day_of_week: Optional[int] = Field(default=None, ge=0, le=6)
    month_of_year: Optional[int] = Field(default=None, ge=1, le=12)
    is_active: Optional[bool] = None


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


def _get_or_404(session: Session, workspace_id: int, recurring_id: int) -> RecurringIncome:
    rec = session.get(RecurringIncome, recurring_id)
    if not rec or rec.workspace_id != workspace_id:
        raise HTTPException(status_code=404, detail="Renda recorrente não encontrada")
    return rec


def _check_ownership(membership: WorkspaceMembership, rec: RecurringIncome) -> None:
    if (
        role_level(membership.role) < role_level(WorkspaceRole.admin)
        and rec.user_id != membership.user_id
    ):
        raise HTTPException(status_code=403, detail="Você só pode alterar as próprias rendas recorrentes")


@router.post("", response_model=RecurringIncome)
def create_recurring_income(
    workspace_id: int,
    recurring_in: RecurringIncomeCreate,
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
        recurring_in.interval, recurring_in.start_date,
    )
    db_rec = RecurringIncome(
        **recurring_in.model_dump(),
        workspace_id=workspace_id,
        created_by_user_id=membership.user_id,
        user_id=membership.user_id,
    )
    session.add(db_rec)
    session.flush()
    RecurringMaterializationService.apply_scope(
        session, workspace_id, db_rec, materialize, is_income=True
    )
    publish_event(session, workspace_id, "recurring_income.created", "recurring_income", db_rec.id, membership.user_id)
    session.commit()
    session.refresh(db_rec)
    return db_rec


@router.post("/generate")
def generate_recurring_income(
    workspace_id: int,
    session: Session = Depends(get_session),
    membership: WorkspaceMembership = Depends(require_role(WorkspaceRole.member)),
):
    """Materializa as rendas recorrentes vencidas do mês corrente (idempotente)."""
    created = RecurringIncomeService.generate_due_income(session, workspace_id, date.today())
    if created:
        publish_event(session, workspace_id, "income.bulk_created", "income", None, membership.user_id)
    session.commit()
    return {"created": created}


@router.get("", response_model=List[RecurringIncome])
def list_recurring_income(
    workspace_id: int,
    session: Session = Depends(get_session),
    membership: WorkspaceMembership = Depends(get_workspace_membership),
):
    return session.exec(
        select(RecurringIncome).where(RecurringIncome.workspace_id == workspace_id)
    ).all()


@router.put("/{recurring_id}", response_model=RecurringIncome)
def update_recurring_income(
    workspace_id: int,
    recurring_id: int,
    recurring_in: RecurringIncomeUpdate,
    session: Session = Depends(get_session),
    membership: WorkspaceMembership = Depends(require_role(WorkspaceRole.member)),
    materialize: str = Query(
        "current",
        description="Escopo da materialização com start_date retroativa: past | current | future",
    ),
):
    if materialize not in MATERIALIZE_SCOPES:
        raise HTTPException(status_code=400, detail=f"materialize deve ser um de {list(MATERIALIZE_SCOPES)}")
    db_rec = _get_or_404(session, workspace_id, recurring_id)
    _check_ownership(membership, db_rec)

    for key, value in recurring_in.model_dump(exclude_unset=True).items():
        setattr(db_rec, key, value)
    _validate_frequency_fields(
        db_rec.frequency, db_rec.day_of_week, db_rec.month_of_year,
        db_rec.interval, db_rec.start_date,
    )
    db_rec.updated_at = datetime.now(UTC)

    session.add(db_rec)
    session.flush()
    # A edição vale do mês visualizado pra frente: reaplica ao lançamento do mês
    # corrente; meses anteriores (fechados) ficam congelados.
    RecurringIncomeService.sync_current_month_income(session, db_rec, date.today())
    # ...e materializa o que ainda falta conforme o escopo escolhido (a data pode
    # ter mudado para trás/para frente, criando ou dispensando ocorrências).
    RecurringMaterializationService.apply_scope(
        session, workspace_id, db_rec, materialize, is_income=True
    )
    publish_event(session, workspace_id, "recurring_income.updated", "recurring_income", db_rec.id, membership.user_id)
    session.commit()
    session.refresh(db_rec)
    return db_rec


@router.delete("/{recurring_id}")
def delete_recurring_income(
    workspace_id: int,
    recurring_id: int,
    session: Session = Depends(get_session),
    membership: WorkspaceMembership = Depends(require_role(WorkspaceRole.member)),
):
    db_rec = _get_or_404(session, workspace_id, recurring_id)
    _check_ownership(membership, db_rec)

    # Desvincula rendas já geradas antes de excluir o template (evita violar FK)
    instances = session.exec(
        select(Income).where(Income.recurring_income_id == recurring_id)
    ).all()
    for inc in instances:
        inc.recurring_income_id = None
        session.add(inc)

    session.delete(db_rec)
    publish_event(session, workspace_id, "recurring_income.deleted", "recurring_income", recurring_id, membership.user_id)
    session.commit()
    return {"status": "ok"}
