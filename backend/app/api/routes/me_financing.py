"""Financiamento PESSOAL e o cronograma de amortização (ADR 0021).

A dívida é de quem assinou o contrato. Antes o financiamento morava num workspace
e `FinancingWorkspaceShare` o oferecia a outros — o caso do imóvel do casal,
financiado no nome de um. O compartilhamento saiu junto com os demais: ele
vinculava o recurso a um ESPAÇO, quando o que o caso pede é co-propriedade entre
PESSOAS (ver `docs/estudo-recursos-compartilhados.md`).

**Pagar a parcela** deixou de criar despesa automaticamente num workspace. O
pagamento é do dono, e antes a despesa gerada nascia com pagador e divisão 100%
dele — ou seja, nunca foi um mecanismo de rateio, só um registro de caixa que por
acaso morava na casa dos outros. Agora o corpo do POST aceita `workspace_id`
opcional: informado, a despesa é criada lá (e pode ser dividida como qualquer
outra); omitido, a parcela só é marcada como paga.
"""
from datetime import datetime, date, UTC
from decimal import Decimal
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlmodel import Session, select

from app.api.routes.auth import get_current_user
from app.db.session import get_session
from app.domain.access_policy import assert_owns, personal_scope
from app.domain.query_policy import resolve_personal_currency
from app.models.financing import (
    AmortizationInstallment,
    AmortizationMethod,
    Financing,
    FinancingStatus,
)
from app.models.transaction import (
    SplitMethod,
    Transaction,
    TransactionPayer,
    TransactionSplit,
    TransactionStatus,
)
from app.models.user import User
from app.models.workspace import WorkspaceMembership
from app.schemas.common import DESCRIPTION_MAX, MAX_MONEY, OptionalCurrencyCode, TITLE_MAX
from app.services.event_service import publish_event
from app.services.financing_service import FinancingService

router = APIRouter(prefix="/me/financing", tags=["me-financing"])


def _colecao(metodo: str, caminho: str, **kwargs):
    """Registra a rota de coleção COM e SEM barra final, sem redirecionar.

    O redirecionamento automático de barra do Starlette responde 307, e nesse
    salto o **cookie de sessão não acompanha** — a URL com a barra "errada"
    devolvia 401 em vez de funcionar. Registrar os dois caminhos elimina o
    redirecionamento em vez de tentar sobreviver a ele.
    """
    def decorador(func):
        for p in (caminho, caminho + "/"):
            getattr(router, metodo)(
                p, **({**kwargs, "include_in_schema": False} if p.endswith("/") else kwargs)
            )(func)
        return func
    return decorador


class FinancingCreate(BaseModel):
    title: str = Field(min_length=1, max_length=TITLE_MAX)
    description: Optional[str] = Field(default=None, max_length=DESCRIPTION_MAX)
    total_amount: Decimal = Field(gt=0, le=MAX_MONEY)
    interest_rate: Decimal = Field(ge=0)  # taxa MENSAL, ex: 0.01 = 1% a.m.
    start_date: date
    installments_count: int = Field(ge=1, le=600)
    method: AmortizationMethod = AmortizationMethod.SAC
    # None = "não informada" → a rota resolve para a moeda de relatório do dono
    currency: OptionalCurrencyCode = None


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


class EarlySettlementRequest(BaseModel):
    settlement_date: Optional[date] = None


class InstallmentPayRequest(BaseModel):
    """Onde registrar a despesa do pagamento, se em algum lugar.

    `None` = só marca a parcela como paga (o compromisso é pessoal e o caixa dele
    aparece em `/me/commitments`). Um workspace = cria também a despesa lá, para
    quem quer a parcela visível — e divisível — no orçamento da casa.
    """
    workspace_id: Optional[int] = None


# Campos cuja mudança obriga a recalcular o cronograma inteiro
_SCHEDULE_KEYS = {"total_amount", "interest_rate", "start_date", "installments_count", "method"}


def _get_financing_or_404(session: Session, financing_id: int, user_id: int) -> Financing:
    financing = session.get(Financing, financing_id)
    if not financing or financing.deleted_at:
        raise HTTPException(status_code=404, detail="Financiamento não encontrado")
    assert_owns(financing.owner_user_id, user_id, detail="Financiamento não encontrado")
    return financing


def _assert_member(session: Session, workspace_id: int, user_id: int) -> None:
    membro = session.exec(
        select(WorkspaceMembership).where(
            WorkspaceMembership.workspace_id == workspace_id,
            WorkspaceMembership.user_id == user_id,
        )
    ).first()
    if not membro:
        raise HTTPException(status_code=400, detail="Você não participa deste workspace")


@_colecao("post", "", response_model=Financing)
def create_financing(
    financing_in: FinancingCreate,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    data = financing_in.model_dump()
    data["currency"] = resolve_personal_currency(session, current_user.id, financing_in.currency)
    financing = Financing(**data, owner_user_id=current_user.id)
    session.add(financing)
    # flush (não commit): financiamento e cronograma persistem JUNTOS —
    # falha na geração das parcelas não deixa financiamento órfão (ADR 0010)
    session.flush()

    for installment in FinancingService.calculate_amortization_schedule(
        total_amount=financing.total_amount,
        interest_rate=financing.interest_rate,
        installments_count=financing.installments_count,
        start_date=financing.start_date,
        method=financing.method,
    ):
        installment.financing_id = financing.id
        session.add(installment)
    session.commit()
    session.refresh(financing)
    return financing


@_colecao("get", "", response_model=List[Financing])
def list_financing(
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    return session.exec(
        select(Financing).where(
            personal_scope(Financing.owner_user_id, current_user.id),
            Financing.deleted_at.is_(None),
        )
    ).all()


@router.get("/{financing_id}", response_model=Financing)
def get_financing(
    financing_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    return _get_financing_or_404(session, financing_id, current_user.id)


@router.get("/{financing_id}/schedule", response_model=List[AmortizationInstallment])
def get_financing_schedule(
    financing_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    financing = _get_financing_or_404(session, financing_id, current_user.id)
    return session.exec(
        select(AmortizationInstallment)
        .where(AmortizationInstallment.financing_id == financing.id)
        .order_by(AmortizationInstallment.installment_number)
    ).all()


@router.post("/{financing_id}/early-settlement")
def simulate_early_settlement(
    financing_id: int,
    data: EarlySettlementRequest,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    financing = _get_financing_or_404(session, financing_id, current_user.id)
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


@router.put("/{financing_id}", response_model=Financing)
def update_financing(
    financing_id: int,
    data: FinancingUpdate,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Alterar valor/taxa/prazo/método regenera o cronograma, então é recusado se
    já houver parcela paga (o pagamento virou registro real e o plano não pode
    mudar debaixo dele)."""
    financing = _get_financing_or_404(session, financing_id, current_user.id)

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
        # apagar a parcela violaria a FK no Postgres.
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

    session.commit()
    session.refresh(financing)
    return financing


@router.post("/{financing_id}/installments/{installment_number}/pay")
def pay_installment(
    financing_id: int,
    installment_number: int,
    # Corpo OPCIONAL: um POST sem nada marca a parcela como paga, que é o caso
    # comum (o compromisso é pessoal). Só quem quer a despesa lançada num
    # workspace precisa dizer qual.
    body: InstallmentPayRequest = InstallmentPayRequest(),
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    financing = _get_financing_or_404(session, financing_id, current_user.id)
    # Só financiamento ATIVO é dívida contratada. Um `simulated` é plano: pagar
    # parcela dele registrava gasto real a partir de uma simulação.
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

    transaction_id = None
    if body.workspace_id is not None:
        _assert_member(session, body.workspace_id, current_user.id)
        due = installment.due_date
        payment_tx = Transaction(
            title=f"{financing.title} — Parcela {installment_number}/{financing.installments_count}",
            total_amount=installment.total_amount,
            transaction_date=datetime(due.year, due.month, due.day, tzinfo=UTC),
            billing_month=f"{due.year:04d}-{due.month:02d}",
            currency=financing.currency,
            workspace_id=body.workspace_id,
            created_by_user_id=current_user.id,
            status=TransactionStatus.confirmed,
            # Identidade da parcela: é por aqui que o estorno reencontra a despesa.
            # Pelo título, renomear o financiamento deixava a despesa órfã.
            financing_installment_id=installment.id,
        )
        session.add(payment_tx)
        session.flush()
        session.add(TransactionPayer(
            transaction_id=payment_tx.id, user_id=current_user.id,
            amount=installment.total_amount,
        ))
        session.add(TransactionSplit(
            transaction_id=payment_tx.id, user_id=current_user.id,
            split_method=SplitMethod.equal, input_value=Decimal("100"),
            computed_amount=installment.total_amount,
        ))
        transaction_id = payment_tx.id
        publish_event(
            session, body.workspace_id, "transaction.created", "transaction",
            payment_tx.id, current_user.id,
        )

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

    session.commit()
    return {"status": "ok", "transaction_id": transaction_id}


@router.post("/{financing_id}/installments/{installment_number}/unpay")
def unpay_installment(
    financing_id: int,
    installment_number: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Estorna o pagamento de uma parcela.

    `is_paid` era irreversível: um clique errado não tinha desfazer, e a despesa
    gerada ficava para sempre no caixa. Aqui a parcela volta a aberta, a despesa
    correspondente (se houve) é soft-deletada e o financiamento sai de `settled`.
    """
    financing = _get_financing_or_404(session, financing_id, current_user.id)

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

    # O vínculo é por ID (`financing_installment_id`): pelo título, renomear o
    # financiamento fazia o estorno não achar nada — a despesa ficava para sempre
    # no caixa com a parcela já reaberta — e uma despesa manual homônima era
    # apagada junto.
    geradas = list(session.exec(
        select(Transaction).where(
            Transaction.financing_installment_id == installment.id,
            Transaction.deleted_at.is_(None),
        )
    ).all())
    workspaces_afetados = set()
    for tx in geradas:
        tx.deleted_at = datetime.now(UTC)
        session.add(tx)
        workspaces_afetados.add(tx.workspace_id)

    if financing.status == FinancingStatus.settled:
        financing.status = FinancingStatus.active
        session.add(financing)

    for workspace_id in sorted(workspaces_afetados):
        publish_event(
            session, workspace_id, "transaction.bulk_updated", "transaction",
            None, current_user.id,
        )
    session.commit()
    return {"status": "ok"}


@router.delete("/{financing_id}")
def delete_financing(
    financing_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    financing = _get_financing_or_404(session, financing_id, current_user.id)
    financing.deleted_at = datetime.now(UTC)
    session.add(financing)
    session.commit()
    return {"status": "ok"}
