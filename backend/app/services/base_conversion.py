"""Conversão para a moeda-base do workspace na ENTRADA (ADR 0015).

Morava em `api/routes/transactions.py` como `_compute_base_conversion`, e o preço
apareceu quando o pagamento de parcela de financiamento precisou da mesma regra:
`me_financing` teria de importar de uma ROTA. Em vez disso a regra desceu para cá
e `transactions.py` passou a importá-la — a rota continua sendo a dona da
tradução para HTTP, o cálculo é de serviço.

O que essa duplicação já custou: `me_financing.pay_installment` escrevia
`currency=financing.currency` cru na `Transaction`. Como toda agregação de
workspace filtra `Transaction.currency == base`, uma parcela em USD paga num
workspace BRL virava uma despesa que **nenhuma tela somava** — sem erro, sem
aviso, com `original_amount` vazio.

A conversão da DIVISÃO (pagadores, splits, itens, ajustes) continua em
`transaction_service.convert_division_to_base`: ela é sobre ratear centavos
exatos, não sobre achar a taxa.
"""
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Dict, Optional, Union

from fastapi import HTTPException
from sqlmodel import Session

from app.core.config import settings
from app.domain.dates import local_day
from app.domain.query_policy import workspace_base_currency
from app.models.transaction import PaymentMethod
from app.services.currency_service import ExchangeRateUnavailable
from app.services.exchange_rate_store import ExchangeRateStore


def compute_base_conversion(
    session: Session,
    workspace_id: int,
    *,
    currency: Optional[str],
    total_amount: Decimal,
    transaction_date: Union[datetime, date],
    payment_method: Optional[PaymentMethod],
) -> Optional[Dict]:
    """Fator de conversão para a moeda-base do workspace: taxa do dia × (1 + IOF
    no cartão). `None` quando já é a base; 422 quando falta cotação.

    `payment_method=None` (parcela de financiamento, por exemplo) não leva IOF —
    ele é imposto de compra internacional no cartão, não de qualquer despesa em
    moeda estrangeira.
    """
    base = workspace_base_currency(session, workspace_id)
    if not currency or currency == base:
        return None

    # `local_day`: a cotação é do DIA em que a compra aconteceu para quem a fez.
    # Lendo o instante em UTC, uma compra das 22h de 31 de julho em São Paulo
    # buscava a taxa de 1º de agosto — e o valor em moeda-base ficava gravado com
    # o câmbio de um dia em que a compra ainda não existia.
    occ = local_day(transaction_date)
    try:
        # rate_between (não get_or_fetch): a taxa tem que ser moeda→BASE. O store
        # só guarda X→BRL, então num workspace não-BRL a taxa direta estava errada.
        rate, source = ExchangeRateStore.rate_between(session, currency, base, occ)
    except ExchangeRateUnavailable as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    # IOF só em compra internacional no cartão (crédito/débito)
    iof = (
        settings.IOF_INTERNATIONAL_CARD_RATE
        if payment_method in (PaymentMethod.credit_card, PaymentMethod.debit_card)
        else Decimal("0")
    )
    factor = rate * (Decimal("1") + iof)
    base_total = (total_amount * factor).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    return {
        "base_currency": base,
        "base_total": base_total,
        "factor": factor,
        "meta": {
            "original_amount": total_amount,
            "original_currency": currency,
            "exchange_rate": rate,
            "iof_rate": iof,
            "rate_source": source,
        },
    }


def compute_statement_conversion(
    session: Session,
    card,
    *,
    currency: Optional[str],
    total_amount: Decimal,
    transaction_date: Union[datetime, date],
    allow_fetch: bool = True,
) -> Dict:
    """A compra na moeda do CARTÃO — a perna de fatura do ADR 0024.

    Irmã de `compute_base_conversion`, e deliberadamente separada dela: as duas
    respondem perguntas diferentes sobre o mesmo lançamento. A contábil é "quanto
    isto vale no orçamento desta casa"; esta é "quanto o banco vai cobrar na
    fatura". Elas coincidem quando a moeda do cartão é a moeda-base do workspace,
    e é por isso que a divergência passou tanto tempo invisível.

    Diferente da contábil, esta NUNCA devolve `None`: todo lançamento com cartão
    precisa de um valor de fatura, mesmo (principalmente) quando não há conversão
    nenhuma. Sem valor, a linha volta a ficar fora do total — que é o defeito.

    **IOF.** Aqui ele incide quando a compra é internacional PARA O CARTÃO
    (`currency != card.currency`), que é quem de fato paga o imposto na conversão.
    A perna contábil continua aplicando o dela pela moeda-base do workspace; nos
    cenários multimoeda os dois critérios divergem, e isso está registrado como
    questão em aberto no ADR 0024 em vez de resolvido por baixo do pano — mexer
    no critério contábil mudaria valores já gravados.

    `allow_fetch=False` proíbe ir à rede atrás de cotação que falte: a taxa sai do
    store ou a chamada levanta 422. É o que o caminho de LEITURA quer (a
    materialização preguiçosa roda em GET e não pode virar uma chamada HTTP por
    ocorrência) e o que um backfill quer (uma rodada não pode depender da rede
    linha a linha; o que faltar vira lista para o operador).
    """
    destino = (card.currency or "").upper()
    origem = (currency or destino).upper()

    # Mesma moeda dos dois lados: não houve conversão, então não há taxa e **não
    # há IOF**. O imposto é de compra internacional; cobrá-lo aqui inventaria
    # 3,5% em cima de uma compra que o banco cobrou pelo valor cheio.
    if origem == destino:
        return {
            "statement_amount": total_amount,
            "statement_currency": destino,
            "statement_exchange_rate": Decimal("1"),
        }

    # `local_day` pelo mesmo motivo da perna contábil: a cotação é a do dia em que
    # a compra aconteceu para quem a fez.
    occ = local_day(transaction_date)
    try:
        rate, _source = ExchangeRateStore.rate_between(
            session, origem, destino, occ, allow_fetch=allow_fetch
        )
    except ExchangeRateUnavailable as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    iof = settings.IOF_INTERNATIONAL_CARD_RATE
    factor = rate * (Decimal("1") + iof)
    return {
        "statement_amount": (total_amount * factor).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        ),
        "statement_currency": destino,
        "statement_exchange_rate": factor,
    }


def apply_statement_leg(session: Session, tx, card, *, allow_fetch: bool = True) -> None:
    """Recalcula a perna de fatura a partir do estado PERSISTIDO do lançamento.

    Existe porque os caminhos de EDIÇÃO não têm mais a moeda de entrada em mãos:
    quando chegam ao ponto de gravar, `currency`/`total_amount` já são a perna
    contábil. Mas a de entrada nunca se perde de verdade — está congelada em
    `original_*` quando houve conversão, e é a própria perna contábil quando não
    houve. Reconstituí-la aqui evita que cada rota de edição carregue o par de
    valores pré-conversão por conta própria (e esqueça num dos ramos).

    Sem cartão, os três campos voltam a `None`: tirar o cartão de um lançamento
    tem de tirá-lo da fatura junto, senão o total continua somando uma compra que
    não está mais lá.

    `allow_fetch` repassa para `compute_statement_conversion` — ver lá.
    """
    if card is None or tx.statement_id is None:
        tx.statement_amount = None
        tx.statement_currency = None
        tx.statement_exchange_rate = None
        return

    meta = compute_statement_conversion(
        session, card,
        currency=tx.original_currency or tx.currency,
        total_amount=(
            tx.original_amount if tx.original_amount is not None else tx.total_amount
        ),
        transaction_date=tx.transaction_date,
        allow_fetch=allow_fetch,
    )
    tx.statement_amount = meta["statement_amount"]
    tx.statement_currency = meta["statement_currency"]
    tx.statement_exchange_rate = meta["statement_exchange_rate"]
