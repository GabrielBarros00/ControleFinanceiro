"""Contrato tipado da simulação de quitação antecipada.

A rota não declarava `response_model`, e o `api.gen.ts` recebia `unknown` — para
uma tela que mostra ao usuário quanto ele PAGA e quanto ECONOMIZA se quitar hoje.
Um campo renomeado no backend viraria `undefined` na tela, com o TypeScript verde.

**Decimal, não float** (`docs/API.md`): valores saem como string decimal.
"""
from datetime import datetime
from decimal import Decimal
from typing import Optional

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


class InstallmentPayRequest(BaseModel):
    """Onde e QUANDO registrar a despesa do pagamento.

    `workspace_id=None` = só marca a parcela como paga (o compromisso é pessoal e
    o caixa dele aparece em `/me/commitments`). Um workspace = cria também a
    despesa lá, para quem quer a parcela visível — e divisível — no orçamento da
    casa.

    `paid_at` é a data EFETIVA do pagamento, e omitido vale agora. Ela existe
    porque a despesa vinculada nascia com a data de VENCIMENTO da parcela: uma
    parcela que vence em setembro e é paga em agosto zerava o caixa de agosto e
    fazia a saída aparecer em setembro — um mês em que o dinheiro não saiu.
    """
    workspace_id: Optional[int] = None
    paid_at: Optional[datetime] = None
    #: De qual conta a parcela saiu (ADR 0034). Opcional, como no pagamento de
    #: conta: sem ela o movimento continua sendo caixa, só não move saldo.
    account_id: Optional[int] = None


# Campos cuja mudança obriga a recalcular o cronograma inteiro
