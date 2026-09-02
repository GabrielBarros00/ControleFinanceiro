"""Conta de pagamento PESSOAL — de onde o dinheiro sai (ADR 0004 + ADR 0021).

A conta acompanha o dono em todo workspace de que ele participa e não é visível a
mais ninguém. Antes ela morava num workspace com `owner_user_id` OPCIONAL, e o
`None` significava "conta da casa": o extrato bancário de uma pessoa virava um
recurso coletivo que qualquer `member` editava ou desativava.

O compartilhamento por workspace da Onda 2 tinha o mesmo defeito do cartão: a
conta aparecia na listagem do workspace de destino, mas `_validate_payer_accounts`
exigia `account.workspace_id == workspace_id` e recusava o pagamento. Visível e
inutilizável.
"""
from datetime import datetime, UTC
from decimal import Decimal
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlmodel import Session, select

from app.api.routes.auth import get_current_user
from app.db.session import get_session
from app.domain.access_policy import assert_owns, personal_scope
from app.domain.dates import (
    InvalidMonth,
    civil_instant,
    month_bounds_utc,
    parse_month,
    today_local,
)
from app.domain.query_policy import resolve_personal_currency
from app.models.account_ledger import AccountEntry, AccountEntryKind
from app.models.payment_account import PaymentAccount, PaymentAccountType
from app.models.user import User
from app.schemas.balance import (
    AccountStatementRead,
    AdjustmentRead,
    AdjustmentRequest,
    OpeningBalanceRequest,
)
from app.schemas.common import NAME_MAX, OptionalCurrencyCode, StatusRead
from app.services.account_balance_service import AccountBalanceService

router = APIRouter(prefix="/me/payment-accounts", tags=["me-payment-accounts"])


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


class PaymentAccountCreate(BaseModel):
    name: str = Field(min_length=1, max_length=NAME_MAX)
    type: PaymentAccountType = PaymentAccountType.checking
    # None = "não informada" → a rota resolve para a moeda de relatório do dono
    currency: OptionalCurrencyCode = None


class PaymentAccountUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=NAME_MAX)
    type: Optional[PaymentAccountType] = None
    active: Optional[bool] = None
    is_default: Optional[bool] = None


class PaymentAccountRead(BaseModel):
    id: int
    name: str
    type: PaymentAccountType
    currency: str
    active: bool
    owner_user_id: int
    #: A conta que o formulário já vem preenchendo. Não é enfeite: o saldo só
    #: existe para o movimento que declara conta, e um padrão bom é o que impede o
    #: contador de "movimentos sem conta" de crescer sozinho.
    is_default: bool = False


def _get_account_or_404(session: Session, account_id: int, user_id: int) -> PaymentAccount:
    account = session.get(PaymentAccount, account_id)
    if not account or account.deleted_at:
        raise HTTPException(status_code=404, detail="Conta não encontrada")
    assert_owns(account.owner_user_id, user_id, detail="Conta não encontrada")
    return account


@_colecao("get", "", response_model=List[PaymentAccountRead])
def list_payment_accounts(
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    return session.exec(
        select(PaymentAccount)
        .where(personal_scope(PaymentAccount.owner_user_id, current_user.id))
        .where(PaymentAccount.deleted_at.is_(None))
        .order_by(PaymentAccount.name)
    ).all()


@_colecao("post", "", response_model=PaymentAccountRead)
def create_payment_account(
    account_in: PaymentAccountCreate,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    name = account_in.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Informe o nome da conta")
    # Resolvida UMA vez: vale tanto para a conta nova quanto para a reativação.
    currency = resolve_personal_currency(session, current_user.id, account_in.currency)

    existing = session.exec(
        select(PaymentAccount).where(
            PaymentAccount.owner_user_id == current_user.id,
            PaymentAccount.name == name,
        )
    ).first()
    if existing:
        if existing.deleted_at is None:
            raise HTTPException(status_code=400, detail="Já existe uma conta com esse nome")
        # Reativação: nome de conta excluída volta à vida com os dados novos —
        # a unique (owner, name) nunca bloqueia recriação.
        existing.deleted_at = None
        existing.active = True
        existing.type = account_in.type
        # A MOEDA não volta a ser negociável se a conta já tem história (ADR 0034):
        # ela é a unidade de conta do saldo, e trocá-la aqui reinterpretaria em USD
        # movimentos que foram somados em BRL — sem nenhuma linha no extrato que
        # explicasse a mudança. Conta excluída sem uso nenhum pode mudar à vontade.
        if not AccountBalanceService.tem_movimento(session, existing.id):
            existing.currency = currency
        existing.updated_at = datetime.now(UTC)
        session.add(existing)
        account = existing
    else:
        account = PaymentAccount(
            name=name,
            type=account_in.type,
            currency=currency,
            owner_user_id=current_user.id,
        )
        session.add(account)

    session.commit()
    session.refresh(account)
    return account


@router.put("/{account_id}", response_model=PaymentAccountRead)
def update_payment_account(
    account_id: int,
    account_in: PaymentAccountUpdate,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    account = _get_account_or_404(session, account_id, current_user.id)
    update_data = account_in.model_dump(exclude_unset=True)

    if "name" in update_data:
        name = (update_data["name"] or "").strip()
        if not name:
            raise HTTPException(status_code=400, detail="Informe o nome da conta")
        clash = session.exec(
            select(PaymentAccount).where(
                PaymentAccount.owner_user_id == current_user.id,
                PaymentAccount.name == name,
                PaymentAccount.id != account.id,
                PaymentAccount.deleted_at.is_(None),
            )
        ).first()
        if clash:
            raise HTTPException(status_code=400, detail="Já existe uma conta com esse nome")
        update_data["name"] = name

    for key, value in update_data.items():
        setattr(account, key, value)
    account.updated_at = datetime.now(UTC)
    session.add(account)

    # Uma conta padrão por dono. Sem unique no banco de propósito: duas marcadas é
    # uma escolha ruim, não uma corrupção — e uma unique parcial aqui faria a
    # troca de padrão exigir duas escritas ordenadas para não colidir consigo mesma.
    if update_data.get("is_default"):
        for outra in session.exec(
            select(PaymentAccount)
            .where(PaymentAccount.owner_user_id == current_user.id)
            .where(PaymentAccount.id != account.id)
            .where(PaymentAccount.is_default.is_(True))
        ).all():
            outra.is_default = False
            session.add(outra)

    session.commit()
    session.refresh(account)
    return account


@router.delete("/{account_id}", response_model=StatusRead)
def delete_payment_account(
    account_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Soft delete: pagamentos antigos continuam apontando para a conta
    (histórico explicável); para sumir do formulário basta desativar.

    **Conta com saldo diferente de zero é recusada (ADR 0034).** Antes do saldo,
    excluir era só tirar da lista de origens; agora seria fazer um dinheiro que
    existe desaparecer da tela sem nenhum movimento que explicasse — e o total do
    topo mudaria sozinho. Mesmo desenho do 409 que impede excluir financiamento em
    aberto. Para zerar de forma explicável há o ajuste e a transferência.
    """
    account = _get_account_or_404(session, account_id, current_user.id)

    saldos = AccountBalanceService.balances(session, current_user.id)
    atual = next(
        (c for c in saldos["accounts"] if c["account_id"] == account.id), None
    )
    if atual and atual["balance"] is not None and atual["balance"] != Decimal("0.00"):
        raise HTTPException(
            status_code=409,
            detail=(
                f"A conta '{account.name}' tem saldo de "
                f"{atual['balance']} {account.currency}. Transfira o dinheiro para "
                "outra conta ou registre um ajuste antes de excluí-la — o saldo não "
                "pode sumir sem um movimento que explique."
            ),
        )

    account.deleted_at = datetime.now(UTC)
    account.active = False
    session.add(account)
    session.commit()
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Saldo: abertura, conciliação e extrato (ADR 0034)


@router.put("/{account_id}/opening-balance", response_model=PaymentAccountRead)
def set_opening_balance(
    account_id: int,
    body: OpeningBalanceRequest,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """"Em tal dia eu tinha tanto" — o ponto de partida contábil da conta.

    Não é renda, não é despesa, não entra em resultado de mês nenhum. A DATA é o
    que mais importa: o que aconteceu antes dela já está dentro do número
    informado, e por isso os movimentos anteriores deixam de contar (contá-los
    dobraria cada um).
    """
    account = _get_account_or_404(session, account_id, current_user.id)
    AccountBalanceService.define_abertura(
        session, account, amount=body.amount, as_of=body.as_of, user_id=current_user.id
    )
    session.commit()
    session.refresh(account)
    return account


@router.post("/{account_id}/adjustment", response_model=AdjustmentRead)
def adjust_balance(
    account_id: int,
    body: AdjustmentRequest,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Conciliação: o app diz 4.821,53 e o banco diz 4.900,00.

    O corpo traz o saldo REAL — é o número que a pessoa tem à mão —, e o servidor
    calcula a diferença. Pedir o delta faria as duas pontas divergirem na primeira
    conta feita de cabeça.

    O ajuste vira uma LINHA DATADA no extrato, com motivo. Ele não reescreve valor
    nenhum do passado: "se o usuário ajustar saldo hoje, não reescreva valores
    antigos para fazer o saldo fechar" (§29 do pedido). E não é renda nem despesa —
    não aparece em `cash_in`/`cash_out`, não muda consumo e não muda o resultado do
    mês.
    """
    account = _get_account_or_404(session, account_id, current_user.id)
    quando = body.occurred_on or today_local()

    anterior = AccountBalanceService.saldo_em(session, current_user.id, account, quando)
    if anterior is None:
        raise HTTPException(
            status_code=409,
            detail=(
                f"A conta '{account.name}' ainda não tem saldo inicial. Informe o "
                "saldo e a data dele antes de conciliar — sem ponto de partida não "
                "há diferença a calcular."
            ),
        )

    delta = body.real_balance - anterior
    if delta == Decimal("0.00"):
        raise HTTPException(
            status_code=422,
            detail="O saldo informado é igual ao calculado: não há o que ajustar",
        )

    entrada = AccountEntry(
        account_id=account.id,
        kind=AccountEntryKind.adjustment,
        amount=delta,
        occurred_at=civil_instant(quando),
        description=body.note or "Ajuste de saldo",
        created_by_user_id=current_user.id,
    )
    session.add(entrada)
    session.commit()
    session.refresh(entrada)
    return {
        "id": entrada.id,
        "account_id": account.id,
        "amount": delta,
        "occurred_on": quando,
        "description": entrada.description,
        "previous_balance": anterior,
        "new_balance": body.real_balance,
    }


@router.get("/{account_id}/statement", response_model=AccountStatementRead)
def account_statement(
    account_id: int,
    month: Optional[str] = None,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """O extrato da conta com SALDO CORRENTE linha a linha.

    É a resposta da última pergunta do pedido — *"por que o saldo atual é
    exatamente esse valor?"* —, e ela nunca é "porque alguém digitou": cada linha
    aponta para a sua origem (lançamento, fatura, acerto, parcela, ajuste,
    transferência), e o saldo do topo é a soma delas a partir da abertura.
    """
    account = _get_account_or_404(session, account_id, current_user.id)
    desde = ate = None
    if month:
        try:
            desde, ate = month_bounds_utc(parse_month(month))
        except InvalidMonth as exc:
            raise HTTPException(status_code=400, detail=str(exc))
    return AccountBalanceService.statement(
        session, current_user.id, account, desde=desde, ate=ate
    )
