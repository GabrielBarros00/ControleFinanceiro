from datetime import datetime, date, UTC
from decimal import Decimal
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.schemas.common import DESCRIPTION_MAX, MAX_MONEY, OptionalCurrencyCode, TITLE_MAX
from sqlmodel import Session, select

from app.api.deps import get_workspace_membership, require_role
from app.db.session import get_session
from app.domain.query_policy import resolve_currency
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
from app.models.workspace import WorkspaceMembership, WorkspaceRole, role_level
from app.services.event_service import publish_event
from app.services.financing_service import FinancingService

router = APIRouter(prefix="/workspaces/{workspace_id}/financing", tags=["financing"])


class FinancingCreate(BaseModel):
    title: str = Field(min_length=1, max_length=TITLE_MAX)
    description: Optional[str] = Field(default=None, max_length=DESCRIPTION_MAX)
    total_amount: Decimal = Field(gt=0, le=MAX_MONEY)
    interest_rate: Decimal = Field(ge=0)  # taxa MENSAL, ex: 0.01 = 1% a.m.
    start_date: date
    installments_count: int
    method: AmortizationMethod = AmortizationMethod.SAC
    # None = "não informada" → a rota resolve para a moeda-base do workspace.
    # O campo nem existia: o financiamento herdava o default "BRL" do model e,
    # num workspace em outra moeda, sumia do painel de Endividamento
    # (LiabilityService filtra `currency == base`) e a despesa gerada ao pagar a
    # parcela caía fora de dívidas, relatórios, previsão e fatura.
    currency: OptionalCurrencyCode = None


class EarlySettlementRequest(BaseModel):
    settlement_date: Optional[date] = None


class FinancingUpdate(BaseModel):
    """Edição do financiamento. Mexer em valor/taxa/prazo/método regenera o
    cronograma — por isso só é permitido enquanto nenhuma parcela foi paga."""
    title: Optional[str] = Field(default=None, min_length=1, max_length=TITLE_MAX)
    description: Optional[str] = Field(default=None, max_length=DESCRIPTION_MAX)
    total_amount: Optional[Decimal] = Field(default=None, gt=0, le=MAX_MONEY)
    interest_rate: Optional[Decimal] = Field(default=None, ge=0)
    start_date: Optional[date] = None
    installments_count: Optional[int] = Field(default=None, ge=1, le=600)
    method: Optional[AmortizationMethod] = None


# Campos cuja mudança obriga a recalcular o cronograma inteiro
_SCHEDULE_KEYS = {"total_amount", "interest_rate", "start_date", "installments_count", "method"}


def _get_financing_or_404(session: Session, workspace_id: int, financing_id: int) -> Financing:
    financing = session.get(Financing, financing_id)
    if not financing or financing.workspace_id != workspace_id or financing.deleted_at:
        raise HTTPException(status_code=404, detail="Financiamento não encontrado")
    return financing


def _check_ownership(membership: WorkspaceMembership, financing: Financing) -> None:
    """Member mexe só no que é dele; admin+ mexe em tudo.

    Mesmo gate de transações, rendas, acertos, anexos e recorrências — o
    financiamento era a única entidade em que qualquer member pagava (e gerava
    despesa no nome de) o financiamento de outro.
    """
    if (
        role_level(membership.role) < role_level(WorkspaceRole.admin)
        and financing.created_by_user_id not in (None, membership.user_id)
    ):
        raise HTTPException(
            status_code=403, detail="Você só pode alterar os próprios financiamentos"
        )


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

    data = financing_in.model_dump()
    # Moeda ausente = a do workspace (nunca "BRL" fixo — ver resolve_currency)
    data["currency"] = resolve_currency(session, workspace_id, financing_in.currency)
    financing = Financing(
        **data,
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
    _check_ownership(membership, financing)
    # Só financiamento ATIVO gera despesa. Um `simulated` é plano, não dívida
    # contratada: pagar parcela dele criava gasto real a partir de uma simulação
    # — e como o Endividamento filtra `status == active`, essa despesa nascia
    # fora do painel que deveria explicá-la.
    if financing.status != FinancingStatus.active:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Financiamento não está ativo (status: "
                f"{getattr(financing.status, 'value', financing.status)}) — "
                "não é possível pagar parcelas."
            ),
        )
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
        # Identidade da parcela: é por aqui que o estorno reencontra a despesa.
        # Pelo título, renomear o financiamento deixava a despesa órfã no caixa.
        financing_installment_id=installment.id,
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


@router.put("/{financing_id}", response_model=Financing)
def update_financing(
    workspace_id: int,
    financing_id: int,
    data: FinancingUpdate,
    session: Session = Depends(get_session),
    membership: WorkspaceMembership = Depends(require_role(WorkspaceRole.member)),
):
    """Edita o financiamento. Antes NÃO existia: um financiamento cadastrado
    errado só podia ser excluído e recriado, perdendo o histórico.

    Alterar valor/taxa/prazo/método regenera o cronograma, então é recusado se
    já houver parcela paga (o pagamento virou despesa real e o plano não pode
    mudar debaixo dela)."""
    financing = _get_financing_or_404(session, workspace_id, financing_id)
    _check_ownership(membership, financing)

    update_data = data.model_dump(exclude_unset=True)
    if not update_data:
        return financing

    regenerar = bool(_SCHEDULE_KEYS & update_data.keys())
    if regenerar:
        paga = session.exec(
            select(AmortizationInstallment).where(
                AmortizationInstallment.financing_id == financing.id,
                AmortizationInstallment.is_paid.is_(True),
            )
        ).first()
        if paga:
            raise HTTPException(
                status_code=409,
                detail=(
                    "Há parcelas pagas: estorne-as antes de alterar valor, taxa, "
                    "prazo ou método de amortização."
                ),
            )

    for key, value in update_data.items():
        setattr(financing, key, value)
    financing.updated_at = datetime.now(UTC)
    session.add(financing)

    if regenerar:
        antigas = list(session.exec(
            select(AmortizationInstallment).where(
                AmortizationInstallment.financing_id == financing.id
            )
        ).all())
        # Desvincula antes de apagar: uma parcela estornada mantém a despesa
        # como tombstone (soft delete), e a linha continua apontando para ela —
        # apagar a parcela violaria a FK no Postgres (mesmo cuidado do
        # delete_recurring). Só chega aqui se NÃO houver parcela paga.
        ids_antigos = [i.id for i in antigas]
        if ids_antigos:
            for tx in session.exec(
                select(Transaction).where(
                    Transaction.financing_installment_id.in_(ids_antigos)
                )
            ).all():
                tx.financing_installment_id = None
                session.add(tx)
            session.flush()
        for antiga in antigas:
            session.delete(antiga)
        session.flush()
        for parcela in FinancingService.calculate_amortization_schedule(
            total_amount=financing.total_amount,
            interest_rate=financing.interest_rate,
            installments_count=financing.installments_count,
            start_date=financing.start_date,
            method=financing.method,
        ):
            parcela.financing_id = financing.id
            session.add(parcela)

    publish_event(session, workspace_id, "financing.updated", "financing", financing.id, membership.user_id)
    session.commit()
    session.refresh(financing)
    return financing


@router.post("/{financing_id}/installments/{installment_number}/unpay")
def unpay_installment(
    workspace_id: int,
    financing_id: int,
    installment_number: int,
    session: Session = Depends(get_session),
    membership: WorkspaceMembership = Depends(require_role(WorkspaceRole.member)),
):
    """Estorna o pagamento de uma parcela.

    `is_paid` era irreversível: um clique errado não tinha desfazer, e a despesa
    gerada ficava para sempre no caixa. Aqui a parcela volta a aberta, a despesa
    correspondente é soft-deletada e o financiamento sai de `settled`."""
    financing = _get_financing_or_404(session, workspace_id, financing_id)
    _check_ownership(membership, financing)

    installment = session.exec(
        select(AmortizationInstallment).where(
            AmortizationInstallment.financing_id == financing.id,
            AmortizationInstallment.installment_number == installment_number,
        )
    ).first()
    if not installment:
        raise HTTPException(status_code=404, detail="Parcela não encontrada")
    if not installment.is_paid:
        raise HTTPException(status_code=400, detail="Parcela não está paga")

    installment.is_paid = False
    installment.paid_at = None
    session.add(installment)

    # A despesa gerada no pagamento sai do caixa junto. O vínculo é por ID
    # (`financing_installment_id`): pelo título, renomear o financiamento fazia
    # o estorno não achar nada — a despesa ficava para sempre no caixa com a
    # parcela já reaberta — e uma despesa manual homônima era apagada junto.
    geradas = list(session.exec(
        select(Transaction).where(
            Transaction.financing_installment_id == installment.id,
            Transaction.deleted_at.is_(None),
        )
    ).all())
    if not geradas:
        # Fallback só para linhas ANTERIORES à coluna de vínculo (elas não têm
        # como ser reencontradas de outro jeito). Restrito ao título exato que o
        # pagamento monta, como era antes.
        titulo = f"{financing.title} — Parcela {installment_number}/{financing.installments_count}"
        geradas = list(session.exec(
            select(Transaction).where(
                Transaction.workspace_id == workspace_id,
                Transaction.title == titulo,
                Transaction.financing_installment_id.is_(None),
                Transaction.deleted_at.is_(None),
            )
        ).all())
    for tx in geradas:
        tx.deleted_at = datetime.now(UTC)
        session.add(tx)

    if financing.status == FinancingStatus.settled:
        financing.status = FinancingStatus.active
        session.add(financing)

    publish_event(session, workspace_id, "financing.updated", "financing", financing.id, membership.user_id)
    publish_event(session, workspace_id, "transaction.bulk_updated", "transaction", None, membership.user_id)
    session.commit()
    return {"status": "ok"}


@router.delete("/{financing_id}")
def delete_financing(
    workspace_id: int,
    financing_id: int,
    session: Session = Depends(get_session),
    membership: WorkspaceMembership = Depends(require_role(WorkspaceRole.member)),
):
    financing = _get_financing_or_404(session, workspace_id, financing_id)
    _check_ownership(membership, financing)
    financing.deleted_at = datetime.now(UTC)
    session.add(financing)
    publish_event(session, workspace_id, "financing.deleted", "financing", financing.id, membership.user_id)
    session.commit()
    return {"status": "ok"}
