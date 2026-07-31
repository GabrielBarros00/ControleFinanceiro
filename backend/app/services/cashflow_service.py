"""Caixa EFETIVO da pessoa no mês: o dinheiro que de fato entrou e saiu (ADR 0022).

O app chamava de "Saída de caixa" a soma dos `TransactionPayer` do mês de
faturamento. Não é caixa — é o que a pessoa **assumiu** nos lançamentos. A
diferença aparece no caso mais comum que existe:

    compra de R$ 300 no cartão em julho, fatura paga em 10 de agosto

Pelo número antigo, julho registrava R$ 300 "saídos do seu bolso" com o dinheiro
ainda na conta; agosto, quando ele realmente saiu, não registrava nada. O
pagamento da fatura não entrava em lugar nenhum do sistema — nem o acerto enviado a
outro membro, nem a parcela de financiamento paga fora de um workspace. Uma aba
chamada "Fluxo de Caixa" desenhava tudo menos fluxo de caixa.

**As seis fontes**, cada uma com a sua data efetiva e a sua moeda:

| Direção | Fonte                                          | Data                | Moeda            |
|---------|------------------------------------------------|---------------------|------------------|
| saída   | `TransactionPayer` de lançamento **sem cartão** | `transaction_date`  | do lançamento    |
| saída   | `StatementPayment` de fatura de cartão meu      | `paid_at`           | do cartão        |
| saída   | `Settlement` que eu enviei                      | `settled_at`        | base do workspace|
| saída   | parcela de financiamento meu, paga              | `paid_at`           | do financiamento |
| entrada | `Income`                                        | `received_at`       | da renda         |
| entrada | `Settlement` que eu recebi                      | `settled_at`        | base do workspace|

**Lançamento no cartão não é saída de caixa.** Ele já será contado quando a fatura
for paga — e é por isso que o filtro é `credit_card_id IS NULL`. Pagamento parcial
de fatura entra naturalmente: cada `StatementPayment` é uma linha.

**Sem contagem dobrada com o financiamento.** Pagar uma parcela informando um
workspace cria uma `Transaction` ligada por `Transaction.financing_installment_id`.
Quando essa despesa existe, é ela que conta (pela fonte 1) e a parcela é ignorada;
quando não existe — o caso do compromisso puramente pessoal —, a parcela conta
sozinha. Sem isso, quem lança a parcela no workspace pagaria duas vezes no gráfico.

**Isto não substitui `consumption`.** Consumo é competência ("quanto do gasto foi
meu") e caixa é o movimento do dinheiro; `result = renda − consumo` continua sendo o
resultado do mês. São perguntas diferentes e agora têm nomes diferentes — o número
antigo sobrevive como `paid_in_transactions`, que é o que ele sempre foi.
"""
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Dict, List, Tuple

from sqlmodel import Session, func, select

from app.domain.query_policy import REALIZED_STATUSES, workspace_base_currency
from app.models.credit_card import CardStatement, CreditCard, StatementPayment
from app.models.financing import AmortizationInstallment, Financing
from app.models.income import Income
from app.models.settlement import Settlement
from app.models.transaction import Transaction, TransactionPayer
from app.services.money_conversion import ZERO, converte


class CashFlowService:
    @staticmethod
    def get_month(
        db: Session,
        user_id: int,
        target_month: date,
        destino: str,
        inicio: datetime,
        fim: datetime,
    ) -> Dict[str, Any]:
        """Entradas e saídas de caixa da pessoa no mês, na moeda `destino`.

        `inicio`/`fim` vêm de quem chama porque `OverviewService` já os calcula
        para o mesmo mês — recalcular aqui abriria espaço para as duas janelas
        divergirem numa borda de mês.
        """
        primeiro = date(target_month.year, target_month.month, 1)
        excluidos = 0

        def somar(pares: List[Tuple[str, Decimal]]) -> Decimal:
            """Converte cada grupo (moeda, valor) e soma o que deu.

            O que não converte fica de fora e é CONTADO — nunca vira zero em
            silêncio (ADR 0006). Ver `money_conversion.converte`.
            """
            nonlocal excluidos
            total = ZERO
            for moeda, valor in pares:
                convertido = converte(db, valor or ZERO, moeda, destino, primeiro)
                if convertido is None:
                    excluidos += 1
                else:
                    total += convertido
            return total

        # --- Saída 1: o que saiu do bolso em lançamento FORA do cartão --------
        # `credit_card_id IS NULL` é o discriminador: a compra no cartão só vira
        # caixa quando a fatura é paga (fonte 2).
        pagos = db.exec(
            select(Transaction.currency, func.sum(TransactionPayer.amount))
            .join(Transaction, Transaction.id == TransactionPayer.transaction_id)
            .where(TransactionPayer.user_id == user_id)
            .where(Transaction.credit_card_id.is_(None))
            .where(Transaction.transaction_date >= inicio)
            .where(Transaction.transaction_date <= fim)
            .where(Transaction.deleted_at.is_(None))
            .where(Transaction.status.in_(REALIZED_STATUSES))
            .group_by(Transaction.currency)
        ).all()
        saida_lancamentos = somar(pagos)

        # --- Saída 2: pagamento de fatura -------------------------------------
        faturas = db.exec(
            select(CreditCard.currency, func.sum(StatementPayment.amount))
            .join(CardStatement, CardStatement.id == StatementPayment.statement_id)
            .join(CreditCard, CreditCard.id == CardStatement.card_id)
            .where(CreditCard.owner_user_id == user_id)
            .where(CreditCard.deleted_at.is_(None))
            .where(StatementPayment.paid_at >= inicio)
            .where(StatementPayment.paid_at <= fim)
            .where(StatementPayment.deleted_at.is_(None))
            .group_by(CreditCard.currency)
        ).all()
        saida_faturas = somar(faturas)

        # --- Saídas/entradas 3: acertos entre membros -------------------------
        # O acerto é dinheiro que muda de mão de verdade; o valor está na
        # moeda-base do workspace em que foi registrado.
        saida_acertos = somar(
            CashFlowService._acertos(db, user_id, inicio, fim, enviados=True)
        )
        entrada_acertos = somar(
            CashFlowService._acertos(db, user_id, inicio, fim, enviados=False)
        )

        # --- Saída 4: parcela de financiamento sem despesa correspondente -----
        ja_lancada = (
            select(Transaction.id)
            .where(Transaction.financing_installment_id == AmortizationInstallment.id)
            .where(Transaction.deleted_at.is_(None))
            .exists()
        )
        parcelas = db.exec(
            select(Financing.currency, func.sum(AmortizationInstallment.total_amount))
            .join(Financing, Financing.id == AmortizationInstallment.financing_id)
            .where(Financing.owner_user_id == user_id)
            .where(Financing.deleted_at.is_(None))
            .where(AmortizationInstallment.is_paid.is_(True))
            .where(AmortizationInstallment.paid_at >= inicio)
            .where(AmortizationInstallment.paid_at <= fim)
            .where(~ja_lancada)
            .group_by(Financing.currency)
        ).all()
        saida_parcelas = somar(parcelas)

        # --- Entrada 1: renda -------------------------------------------------
        # Linha a linha (não agrupada): a contagem de excluídos é por RENDA, que é
        # o que a tela informa — "3 rendas ficaram de fora", não "3 moedas".
        rendas = db.exec(
            select(Income.amount, Income.currency)
            .where(Income.user_id == user_id)
            .where(Income.received_at >= inicio)
            .where(Income.received_at <= fim)
            .where(Income.deleted_at.is_(None))
        ).all()
        renda_total = ZERO
        for valor, moeda in rendas:
            convertido = converte(db, valor, moeda, destino, primeiro)
            if convertido is None:
                excluidos += 1
            else:
                renda_total += convertido

        saida = saida_lancamentos + saida_faturas + saida_acertos + saida_parcelas
        entrada = renda_total + entrada_acertos

        return {
            "income": renda_total,
            "cash_in": entrada,
            "cash_out": saida,
            "net_cash": entrada - saida,
            # De onde veio o número: sem isto "saiu R$ 4.200" não é auditável pelo
            # usuário, que não tem como saber se a fatura entrou ou não.
            "cash_out_breakdown": {
                "transactions": saida_lancamentos,
                "statement_payments": saida_faturas,
                "settlements_sent": saida_acertos,
                "financing_installments": saida_parcelas,
            },
            "cash_in_breakdown": {
                "income": renda_total,
                "settlements_received": entrada_acertos,
            },
            "excluded_foreign_count": excluidos,
        }

    @staticmethod
    def _acertos(
        db: Session, user_id: int, inicio: datetime, fim: datetime, enviados: bool
    ) -> List[Tuple[str, Decimal]]:
        """Acertos do período agrupados por MOEDA (a base de cada workspace)."""
        coluna = Settlement.from_user_id if enviados else Settlement.to_user_id
        por_workspace = db.exec(
            select(Settlement.workspace_id, func.sum(Settlement.amount))
            .where(coluna == user_id)
            .where(Settlement.settled_at >= inicio)
            .where(Settlement.settled_at <= fim)
            .where(Settlement.deleted_at.is_(None))
            .group_by(Settlement.workspace_id)
        ).all()

        por_moeda: Dict[str, Decimal] = {}
        for workspace_id, valor in por_workspace:
            moeda = workspace_base_currency(db, workspace_id)
            por_moeda[moeda] = por_moeda.get(moeda, ZERO) + (valor or ZERO)
        return list(por_moeda.items())
