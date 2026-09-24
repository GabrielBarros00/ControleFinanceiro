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
from sqlalchemy import func, update
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.api.routes.auth import get_current_user
from app.db.session import get_session
from app.domain.access_policy import personal_scope
from app.domain.query_policy import resolve_personal_currency
from app.models.financing import (
    AmortizationInstallment,
    AmortizationMethod,
    Financing,
    FinancingStatus,
)
from app.models.transaction import (
    Transaction,
)
from app.models.user import User
from app.schemas.common import DESCRIPTION_MAX, InstallmentPaidRead, MAX_MONEY, OptionalCurrencyCode, StatusRead, TITLE_MAX
from app.schemas.financing import EarlySettlementRead, InstallmentPayRequest
from app.services.commands import financing as fin_cmd
from app.services.commands.financing import (
    get_financing_or_404 as _get_financing_or_404,
)
from app.services.financing_service import AmortizationError, FinancingService
from app.domain.dates import today_local

router = APIRouter(prefix="/me/financing", tags=["me-financing"])


def _cronograma_de(financing: "Financing") -> list:
    """Gera as parcelas, traduzindo a recusa do domínio em 422.

    `AmortizationError` é `ValueError`, e sem este `except` ele caía no handler
    genérico como **500** — que é o que a rota respondia para uma taxa de 0,5 ao
    mês em 360x. Entrada absurda merece "não dá, e por quê"; 500 é o servidor
    dizendo que o problema é dele.
    """
    try:
        return FinancingService.calculate_amortization_schedule(
            total_amount=financing.total_amount,
            interest_rate=financing.interest_rate,
            installments_count=financing.installments_count,
            start_date=financing.start_date,
            method=financing.method,
        )
    except AmortizationError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


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


_SCHEDULE_KEYS = {"total_amount", "interest_rate", "start_date", "installments_count", "method"}


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

    for installment in _cronograma_de(financing):
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


@router.post("/{financing_id}/early-settlement", response_model=EarlySettlementRead)
def simulate_early_settlement(
    financing_id: int,
    data: EarlySettlementRequest,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    financing = _get_financing_or_404(session, financing_id, current_user.id)
    settlement_date = data.settlement_date or today_local()

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
        for parcela in _cronograma_de(financing):
            parcela.financing_id = financing.id
            session.add(parcela)

    session.commit()
    session.refresh(financing)
    return financing


class QuitarAnterioresRequest(BaseModel):
    """Marca como pagas as parcelas que venceram ANTES de uma data."""

    #: Tudo que vence antes disto e segue em aberto passa a pago. Omitido = hoje.
    ate: Optional[date] = None


class QuitarAnterioresRead(BaseModel):
    quitadas: int
    #: Quantas continuam em aberto — a resposta que diz se sobrou algo.
    em_aberto: int


@router.post("/{financing_id}/installments/settle-past", response_model=QuitarAnterioresRead)
def settle_past_installments(
    financing_id: int,
    body: QuitarAnterioresRequest = QuitarAnterioresRequest(),
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """"Este contrato começou antes de eu cadastrá-lo, e essas parcelas eu já paguei."

    ## Por que esta rota existe

    O app gera o cronograma inteiro no cadastro, e toda parcela nasce
    `is_paid=False`. Quem registra um financiamento que **já existia** fica, no
    mesmo instante, com meses de parcelas "em aberto" que na vida real foram
    pagas — e ninguém volta para marcar doze delas uma a uma.

    O efeito disso vazava para três telas (projeção do Seu mês, Compromissos e
    Relatórios). `projection_service` passou a separar vencido de a vencer, o que
    corrige o **efeito**; esta rota corrige a **causa**.

    ## O que ela deliberadamente NÃO faz

    **Não cria despesa nem movimento de caixa.** Marcar como paga aqui é dizer
    "isto aconteceu antes de o app existir para mim" — inventar lançamentos
    retroativos reescreveria o extrato e o resultado de meses fechados, que é
    exatamente o que o ADR 0023 proíbe. Por isso também não recebe `workspace_id`
    nem conta: quem quer a parcela lançada como despesa usa a rota de pagar
    parcela, uma a uma, que é onde essa decisão cabe.

    **Não toca no futuro.** O corte é estrito (`due_date < ate`), então a parcela
    que vence hoje continua em aberto — ela ainda vai ser paga.

    ## Idempotência

    O `UPDATE` filtra por `is_paid=False`, então chamar duas vezes quita zero na
    segunda. É o que permite a interface oferecer o botão sem medo de repetição.
    """
    financing = _get_financing_or_404(session, financing_id, current_user.id)
    if financing.status != FinancingStatus.active:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Financiamento não está ativo (status: "
                f"{getattr(financing.status, 'value', financing.status)}) — "
                "não é possível quitar parcelas."
            ),
        )

    corte = body.ate or today_local()
    quitadas = session.execute(
        update(AmortizationInstallment)
        .where(AmortizationInstallment.financing_id == financing.id)
        .where(AmortizationInstallment.is_paid.is_(False))
        .where(AmortizationInstallment.due_date < corte)
        # `paid_at` recebe o VENCIMENTO de cada parcela, não a data de hoje: elas
        # foram pagas no passado, e carimbar todas com hoje inventaria um dia em
        # que doze parcelas teriam sido quitadas de uma vez.
        #
        # `paid_outside_app=True` é o que sustenta a promessa do docstring. Sem
        # ele, `is_paid=True` sem despesa vinculada é exatamente o gatilho da
        # fonte 4 do `CashFlowService`, e cada parcela quitada aqui virava uma
        # saída de caixa no mês em que venceu — meses fechados, reescritos.
        .values(
            is_paid=True,
            paid_at=AmortizationInstallment.due_date,
            paid_outside_app=True,
        )
    ).rowcount
    session.commit()

    em_aberto = session.exec(
        select(func.count())
        .select_from(AmortizationInstallment)
        .where(AmortizationInstallment.financing_id == financing.id)
        .where(AmortizationInstallment.is_paid.is_(False))
    ).one()
    return QuitarAnterioresRead(quitadas=quitadas or 0, em_aberto=em_aberto)


@router.post("/{financing_id}/installments/{installment_number}/pay", response_model=InstallmentPaidRead)
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
    transaction_id = fin_cmd.pay_installment(
        session, current_user.id, financing_id, installment_number, body
    )

    try:
        session.commit()
    except IntegrityError:
        # `uq_transaction_financing_installment` (segunda linha de defesa da
        # reivindicação atômica lá em cima). Se um caminho futuro criar a despesa
        # sem passar pela reivindicação, o banco recusa — e a resposta é 409, não
        # o 500 que um IntegrityError vazado produziria.
        session.rollback()
        raise HTTPException(
            status_code=409,
            detail="Esta parcela já tem uma despesa lançada.",
        )
    return {"status": "ok", "transaction_id": transaction_id}


@router.post("/{financing_id}/installments/{installment_number}/unpay", response_model=StatusRead)
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
    fin_cmd.unpay_installment(session, current_user.id, financing_id, installment_number)
    session.commit()
    return {"status": "ok"}


@router.delete("/{financing_id}", response_model=StatusRead)
def delete_financing(
    financing_id: int,
    # Cancelamento DELIBERADO de um financiamento com parcelas em aberto. Sem
    # ele a rota recusa (409). Não é burocracia: a diferença entre "arquivei um
    # contrato encerrado" e "apaguei uma dívida de quinze anos por engano" não
    # está no verbo HTTP, e o app não tem como adivinhar qual dos dois é.
    cancel_open_installments: bool = False,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Arquiva o financiamento. O histórico de caixa continua de pé.

    Duas correções aqui. A primeira é que **não havia guarda nenhuma**: um
    financiamento ativo com quinze anos de parcelas em aberto sumia num DELETE, e
    a dívida ia junto — sem nenhuma tela por onde ser quitada, exatamente o que o
    guard do cartão (`me_cards.py:188`) já impedia do outro lado.

    A segunda é que arquivar deixou de reescrever o passado: o `CashFlowService`
    não filtra mais `Financing.deleted_at`, então as parcelas já pagas continuam
    no fluxo de caixa dos meses delas. O cancelamento é auditável porque as
    parcelas não pagas continuam gravadas como não pagas — o que ficou por pagar
    é reconstituível, em vez de sumir junto com o cadastro.
    """
    financing = _get_financing_or_404(session, financing_id, current_user.id)

    if financing.status == FinancingStatus.active and not cancel_open_installments:
        abertas = session.exec(
            select(AmortizationInstallment).where(
                AmortizationInstallment.financing_id == financing.id,
                AmortizationInstallment.is_paid.is_(False),
            )
        ).all()
        if abertas:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"Este financiamento tem {len(abertas)} parcela(s) em aberto. "
                    "Quite-as antes de arquivar — ou confirme o cancelamento, se "
                    "o contrato foi encerrado fora do app."
                ),
            )

    financing.deleted_at = datetime.now(UTC)
    session.add(financing)
    session.commit()
    return {"status": "ok"}
