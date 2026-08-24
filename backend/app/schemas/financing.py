"""Contrato tipado da simulação de quitação antecipada.

A rota não declarava `response_model`, e o `api.gen.ts` recebia `unknown` — para
uma tela que mostra ao usuário quanto ele PAGA e quanto ECONOMIZA se quitar hoje.
Um campo renomeado no backend viraria `undefined` na tela, com o TypeScript verde.

**Decimal, não float** (`docs/API.md`): valores saem como string decimal.
"""
from decimal import Decimal

from pydantic import BaseModel


class EarlySettlementRead(BaseModel):
    """Quitar hoje: quanto sai, quanto valeria e quanto sobra no bolso."""
    #: Valor PRESENTE das parcelas restantes — o que se paga hoje.
    total_to_pay: Decimal
    #: Soma nominal das mesmas parcelas, se levadas até o fim.
    original_value: Decimal
    #: `original_value - total_to_pay` — os juros que deixam de correr.
    savings: Decimal
    installments_settled: int
