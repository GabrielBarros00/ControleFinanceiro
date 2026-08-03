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

    occ = transaction_date.date() if hasattr(transaction_date, "date") else transaction_date
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
