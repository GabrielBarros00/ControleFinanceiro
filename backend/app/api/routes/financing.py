from datetime import datetime, date, UTC
from decimal import Decimal
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlmodel import Session, select

from app.api.deps import get_workspace_membership, require_role
from app.db.session import get_session
from app.models.financing import (
    Financing,
    AmortizationInstallment,
    AmortizationMethod,
    FinancingStatus,
)
from app.models.transaction import (
    Transaction,
    TransactionPayer,
    TransactionSplit,
    TransactionStatus,
    SplitMethod,
)
from app.models.workspace import WorkspaceMembership, WorkspaceRole
from app.services.event_service import publish_event
from app.services.financing_service import FinancingService

router = APIRouter(prefix="/workspaces/{workspace_id}/financing", tags=["financing"])


class FinancingCreate(BaseModel):
    title: str
    description: Optional[str] = None
    total_amount: Decimal
    interest_rate: Decimal = Field(ge=0)  # taxa MENSAL, ex: 0.01 = 1% a.m.
    start_date: date
    installments_count: int
    method: AmortizationMethod = AmortizationMethod.SAC


class EarlySettlementRequest(BaseModel):
    settlement_date: Optional[date] = None


def _get_financing_or_404(session: Session, workspace_id: int, financing_id: int) -> Financing:
    financing = session.get(Financing, financing_id)
    if not financing or financing.workspace_id != workspace_id or financing.deleted_at:
        raise HTTPException(status_code=404, detail="Financiamento não encontrado")
    return financing


@router.post("", response_model=Financing)
def create_financing(
    workspace_id: int,
    financing_in: FinancingCreate,
    session: Session = Depends(get_session),
    membership: WorkspaceMembership = Depends(require_role(WorkspaceRole.member)),
):
    if financing_in.installments_count < 1 or financing_in.installments_count > 600:
        raise HTTPException(status_code=400, detail="Número de parcelas deve ser entre 1 e 600")
    if financing_in.total_amount <= 0:
        raise HTTPException(status_code=400, detail="Valor total deve ser maior que zero")

    financing = Financing(
        **financing_in.model_dump(),
        workspace_id=workspace_id,
        created_by_user_id=membership.user_id,
    )
    session.add(financing)
    # flush (não commit): financiamento e cronograma persistem JUNTOS —
    # falha na geração das parcelas não deixa financiamento órfão (ADR 0010)
    session.flush()

    # Gera e persiste o cronograma de amortização
    schedule = FinancingService.calculate_amortization_schedule(
        total_amount=financing.total_amount,
        interest_rate=financing.interest_rate,
        installments_count=financing.installments_count,
        start_date=financing.start_date,
        method=financing.method,
    )
    for installment in schedule:
        installment.financing_id = financing.id
        session.add(installment)
    publish_event(session, workspace_id, "financing.created", "financing", financing.id, membership.user_id)
    session.commit()
    session.refresh(financing)
    return financing


@router.get("", response_model=List[Financing])
def list_financing(
    workspace_id: int,
    session: Session = Depends(get_session),
    membership: WorkspaceMembership = Depends(get_workspace_membership),
):
    return session.exec(
        select(Financing).where(
            Financing.workspace_id == workspace_id,
            Financing.deleted_at.is_(None),
        )
    ).all()


@router.get("/{financing_id}", response_model=Financing)
def get_financing(
    workspace_id: int,
    financing_id: int,
    session: Session = Depends(get_session),
    membership: WorkspaceMembership = Depends(get_workspace_membership),
):
    return _get_financing_or_404(session, workspace_id, financing_id)


@router.get("/{financing_id}/schedule", response_model=List[AmortizationInstallment])
def get_financing_schedule(
    workspace_id: int,
    financing_id: int,
    session: Session = Depends(get_session),
    membership: WorkspaceMembership = Depends(get_workspace_membership),
):
    financing = _get_financing_or_404(session, workspace_id, financing_id)
    return session.exec(
        select(AmortizationInstallment)
        .where(AmortizationInstallment.financing_id == financing.id)
        .order_by(AmortizationInstallment.installment_number)
    ).all()


@router.post("/{financing_id}/early-settlement")
def simulate_early_settlement(
    workspace_id: int,
    financing_id: int,
    data: EarlySettlementRequest,
    session: Session = Depends(get_session),
    membership: WorkspaceMembership = Depends(get_workspace_membership),
):
    financing = _get_financing_or_404(session, workspace_id, financing_id)
    settlement_date = data.settlement_date or date.today()

    remaining = session.exec(
        select(AmortizationInstallment)
        .where(
            AmortizationInstallment.financing_id == financing.id,
            AmortizationInstallment.is_paid.is_(False),
            AmortizationInstallment.due_date > settlement_date,
        )
        .order_by(AmortizationInstallment.installment_number)
    ).all()

    return FinancingService.simulate_early_settlement(
        remaining_installments=remaining,
        settlement_date=settlement_date,
        monthly_interest_rate=financing.interest_rate,
    )


@router.post("/{financing_id}/installments/{installment_number}/pay")
def pay_installment(
    workspace_id: int,
    financing_id: int,
    installment_number: int,
    session: Session = Depends(get_session),
    membership: WorkspaceMembership = Depends(require_role(WorkspaceRole.member)),
):
    financing = _get_financing_or_404(session, workspace_id, financing_id)
    installment = session.exec(
        select(AmortizationInstallment).where(
            AmortizationInstallment.financing_id == financing.id,
            AmortizationInstallment.installment_number == installment_number,
        )
    ).first()
    if not installment:
        raise HTTPException(status_code=404, detail="Parcela não encontrada")
    if installment.is_paid:
        raise HTTPException(status_code=400, detail="Parcela já está paga")

    installment.is_paid = True
    installment.paid_at = datetime.now(UTC)
    session.add(installment)

    # Pagar a parcela vira uma DESPESA real (o cronograma é só plano; o gasto
    # entra no caixa/relatórios quando pago). Pagador e divisão = dono do
    # financiamento, então aparece como saída dele (dívida líquida zero).
    owner_id = financing.created_by_user_id
    due = installment.due_date
    payment_tx = Transaction(
        title=f"{financing.title} — Parcela {installment_number}/{financing.installments_count}",
        total_amount=installment.total_amount,
        transaction_date=datetime(due.year, due.month, due.day, tzinfo=UTC),
        billing_month=f"{due.year:04d}-{due.month:02d}",
        currency=financing.currency,
        workspace_id=workspace_id,
        created_by_user_id=owner_id,
        status=TransactionStatus.confirmed,
    )
    session.add(payment_tx)
    session.flush()
    session.add(TransactionPayer(
        transaction_id=payment_tx.id, user_id=owner_id, amount=installment.total_amount,
    ))
    session.add(TransactionSplit(
        transaction_id=payment_tx.id, user_id=owner_id,
        split_method=SplitMethod.equal, input_value=Decimal("100"),
        computed_amount=installment.total_amount,
    ))

    # Se todas pagas, o financiamento é quitado
    unpaid = session.exec(
        select(AmortizationInstallment).where(
            AmortizationInstallment.financing_id == financing.id,
            AmortizationInstallment.is_paid.is_(False),
            AmortizationInstallment.id != installment.id,
        )
    ).first()
    if not unpaid:
        financing.status = FinancingStatus.settled
        session.add(financing)

    publish_event(session, workspace_id, "financing.updated", "financing", financing.id, membership.user_id)
    # Uma parcela paga também é uma transação nova → invalida caixa/relatórios
    publish_event(session, workspace_id, "transaction.created", "transaction", payment_tx.id, membership.user_id)
    session.commit()
    return {"status": "ok", "transaction_id": payment_tx.id}


@router.delete("/{financing_id}")
def delete_financing(
    workspace_id: int,
    financing_id: int,
    session: Session = Depends(get_session),
    membership: WorkspaceMembership = Depends(require_role(WorkspaceRole.member)),
):
    financing = _get_financing_or_404(session, workspace_id, financing_id)
    financing.deleted_at = datetime.now(UTC)
    session.add(financing)
    publish_event(session, workspace_id, "financing.deleted", "financing", financing.id, membership.user_id)
    session.commit()
    return {"status": "ok"}
