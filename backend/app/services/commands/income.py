"""Comandos de RENDA pessoal (ADR 0021/0034).

Movidos de `api/routes/me_income.py` sem mudança de regra (ADR 0035): só o
`commit` saiu — quem chama (rota REST ou pipeline do MCP) comanda a transação.
"""
from datetime import UTC, datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional

from fastapi import HTTPException
from sqlmodel import Session

from app.domain.access_policy import assert_owns
from app.domain.account_policy import AccountCurrencyMismatch, assert_conta_na_moeda
from app.domain.dates import civil_instant, local_day, today_local
from app.domain.income_settlement import resolve_income_settled_at
from app.domain.query_policy import resolve_personal_currency, user_report_currency
from app.models.income import Income
from app.models.payment_account import PaymentAccount
from app.schemas.income import IncomeCreate, IncomeReceiveRequest, IncomeUpdate
from app.services.currency_service import ExchangeRateUnavailable
from app.services.exchange_rate_store import ExchangeRateStore


def _convert_income_fields(
    session: Session, user_id: int, amount: Decimal, currency: Optional[str], received_at: datetime
) -> dict:
    """Renda em moeda estrangeira → moeda de relatório do dono, na data de
    recebimento (sem IOF — IOF é de compra no cartão). Devolve os campos a gravar;
    `{}` se já estiver na moeda de destino."""
    destino = user_report_currency(session, user_id)
    if not currency or currency == destino:
        return {}
    # `local_day`: a taxa é a do dia do RECEBIMENTO no fuso de quem recebeu. Lida
    # em UTC, uma renda das 22h do dia 31 pegava a cotação do dia seguinte.
    occ = local_day(received_at)
    try:
        # rate_between: a taxa precisa ser moeda→DESTINO, e o store só guarda X→BRL
        rate, source = ExchangeRateStore.rate_between(session, currency, destino, occ)
    except ExchangeRateUnavailable as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    converted = (amount * rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return {
        "amount": converted,
        "currency": destino,
        "original_amount": amount,
        "original_currency": currency,
        "exchange_rate": rate,
        "rate_source": source,
    }


def _get_income_or_404(session: Session, income_id: int, user_id: int) -> Income:
    income = session.get(Income, income_id)
    if not income or income.deleted_at:
        raise HTTPException(status_code=404, detail="Renda não encontrada")
    assert_owns(income.user_id, user_id, detail="Renda não encontrada")
    return income


def _valida_conta(
    session: Session, user_id: int, account_id: Optional[int], currency: str
) -> None:
    """A conta de destino tem de ser DA PESSOA, viva, ativa e na mesma moeda.

    Os mesmos gates de `_validate_payer_accounts` do lado da despesa, menos o de
    "quem declara": renda é estritamente pessoal, então quem declara é sempre o dono.
    """
    if account_id is None:
        return
    conta = session.get(PaymentAccount, account_id)
    if not conta or conta.deleted_at or conta.owner_user_id != user_id:
        raise HTTPException(status_code=400, detail="Conta inválida")
    if not conta.active:
        raise HTTPException(status_code=400, detail=f"Conta '{conta.name}' está desativada")
    try:
        assert_conta_na_moeda(conta, currency)
    except AccountCurrencyMismatch as exc:
        raise HTTPException(status_code=400, detail=str(exc))


def create_income(session: Session, user_id: int, income_in: IncomeCreate) -> Income:
    data = income_in.model_dump(exclude={"received"})
    data["currency"] = resolve_personal_currency(session, user_id, income_in.currency)
    data.update(
        _convert_income_fields(
            session, user_id, income_in.amount, data["currency"], income_in.received_at
        )
    )
    _valida_conta(session, user_id, data.get("account_id"), data["currency"])
    db_income = Income(
        **data,
        user_id=user_id,
        # Caixa (ADR 0034): quando o dinheiro caiu. `resolve_income_settled_at` é o
        # ponto ÚNICO que decide — ver `app/domain/income_settlement.py`.
        settled_at=resolve_income_settled_at(
            received_at=income_in.received_at, explicit=income_in.received
        ),
    )
    session.add(db_income)
    session.flush()
    return db_income


def update_income(session: Session, user_id: int, income_id: int, income_in: IncomeUpdate) -> Income:
    income = _get_income_or_404(session, income_id, user_id)

    fields_set = income_in.model_dump(exclude_unset=True)
    if "account_id" in fields_set:
        _valida_conta(session, user_id, fields_set["account_id"], income.currency)
    # A moeda/valor ORIGINAIS antes de o PUT sobrescrever os campos: uma renda
    # estrangeira já gravada tem `currency == destino` (a conversão acontece na
    # entrada) e guarda a proveniência em `original_*`. Sem ler isso ANTES, um
    # PUT que mexesse só na data reconverteria "de destino para destino" —
    # curto-circuito — e apagaria a proveniência.
    moeda_anterior = income.original_currency
    valor_anterior = income.original_amount

    for key, value in fields_set.items():
        setattr(income, key, value)

    # Re-converte quando o PUT mexeu em valor, moeda OU DATA. `received_at`
    # faltava: mover uma renda estrangeira para outro dia mantinha a cotação da
    # data antiga, e o valor em moeda-base ficava congelado num câmbio que não
    # era o do recebimento. Um PUT que não toca em nenhum dos três preserva o
    # original — senão editar só o título apagaria "era USD 100 @ 5,00".
    if {"amount", "currency", "received_at"} & fields_set.keys():
        # Moeda de ENTRADA: a que o PUT mandou; senão a original guardada (renda
        # estrangeira); senão a própria, que já é a de destino.
        moeda_entrada = fields_set.get("currency") or moeda_anterior or income.currency
        valor_entrada = income.amount
        if "amount" not in fields_set and valor_anterior is not None:
            valor_entrada = valor_anterior

        conv = _convert_income_fields(
            session, user_id, valor_entrada, moeda_entrada, income.received_at
        )
        if conv:
            for k, v in conv.items():
                setattr(income, k, v)
        else:
            income.original_amount = None
            income.original_currency = None
            income.exchange_rate = None
            income.rate_source = None

    income.updated_at = datetime.now(UTC)
    session.add(income)
    session.flush()
    return income


def receive_income(
    session: Session, user_id: int, income_id: int, body: IncomeReceiveRequest
) -> Income:
    """"Recebi": a renda prevista vira caixa, na data e na conta informadas.

    Idempotente por natureza — confirmar duas vezes reescreve a mesma data. O que
    ela NÃO faz é mexer em `received_at`: a competência da renda é de setembro
    mesmo que o salário caia em 2 de outubro, e mover a data de competência para
    "fazer bater" jogaria o resultado de setembro para outubro.
    """
    income = _get_income_or_404(session, income_id, user_id)
    if income.cancelled_at is not None:
        raise HTTPException(
            status_code=409,
            detail="Renda cancelada não pode ser recebida — reative-a antes",
        )
    conta = body.account_id if body.account_id is not None else income.account_id
    _valida_conta(session, user_id, conta, income.currency)

    # Data CIVIL — "recebi no dia 2" — então vira instante por `civil_instant`, e
    # não por `datetime.combine`: meia-noite local ancorada em UTC jogaria o
    # recebimento do dia 1º para o caixa do mês anterior.
    income.settled_at = civil_instant(body.received_on or today_local())
    income.account_id = conta
    income.updated_at = datetime.now(UTC)
    session.add(income)
    session.flush()
    return income


def unreceive_income(session: Session, user_id: int, income_id: int) -> Income:
    """Desfaz a confirmação: a renda volta a ser prevista.

    Existe pelo mesmo motivo que "reabrir despesa": confirmar a linha errada é um
    erro comum, e sem a volta a única saída seria excluir e recadastrar — o que
    perde a ligação com a recorrência e libera a vaga do tombstone.
    """
    income = _get_income_or_404(session, income_id, user_id)
    income.settled_at = None
    income.updated_at = datetime.now(UTC)
    session.add(income)
    session.flush()
    return income


def cancel_income(session: Session, user_id: int, income_id: int) -> Income:
    """A renda prevista que não veio — e não virá.

    Diferente de excluir: a linha continua visível como "cancelada" e continua
    ocupando a vaga da unique de ocorrência, então a materialização não recria o
    salário do mês em que a pessoa disse que ele não vem. Excluir também seguraria
    a vaga, mas some da tela — e uma renda que desaparece sem explicação é
    exatamente a experiência que esta onda existe para eliminar.
    """
    income = _get_income_or_404(session, income_id, user_id)
    income.cancelled_at = datetime.now(UTC)
    # Cancelada não é caixa: se estava confirmada, a entrada sai do saldo junto.
    income.settled_at = None
    income.updated_at = datetime.now(UTC)
    session.add(income)
    session.flush()
    return income
