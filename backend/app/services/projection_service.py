"""Quanto eu devo ter no fim do mês (ADR 0034).

    saldo projetado = saldo atual + o que ainda entra − o que ainda sai

O valor da conta está em **não contar nada duas vezes**, e é aí que uma projeção
ingênua erra. As três parcelas de saída se sobrepõem em três lugares diferentes:

1. **Compra no cartão × fatura.** A compra é obrigação, mas quem se paga é a
   fatura. `PayablesService` já exclui `credit_card_id IS NOT NULL`, então somar o
   saldo das faturas por cima não repete nada — e é a maior saída do mês de muita
   gente, que o pedido pediu explicitamente para incluir.
2. **Parcela de financiamento × despesa vinculada.** Pagar a parcela informando um
   workspace cria uma `Transaction`; enquanto ela existe e está em aberto, é ELA
   que aparece em Contas a pagar, e a parcela tem de ser suprimida. É a mesma regra
   de `CashFlowService._parcelas`, com o filtro de liquidação invertido.
3. **Fatura já paga em parte.** O que entra é o SALDO da fatura
   (`effective_total − pago`), não o total dela.

A entrada é só renda prevista — o que já caiu está dentro do saldo atual, e somá-lo
de novo é a forma mais direta de inflar a projeção.

**A projeção não é orçamento.** Ela não estima o gasto variável do resto do mês
(isso é `ForecastService`, e é do workspace). Aqui só entra compromisso CONHECIDO,
com data e valor. Um número que mistura o que se sabe com o que se estima não
responde nem "quanto vou ter" nem "quanto costumo gastar".
"""
import calendar
from datetime import date
from decimal import Decimal
from typing import Any, Dict, List, Optional

from sqlmodel import Session, select

from app.domain.dates import civil_instant, month_bounds_utc, month_key, today_local
from app.domain.query_policy import PAYABLE_STATUSES
from app.models.credit_card import CardStatement, CreditCard, StatementStatus
from app.models.financing import AmortizationInstallment, Financing, FinancingStatus
from app.models.income import Income
from app.models.transaction import Transaction
from app.services.credit_card_service import CreditCardService
from app.services.money_conversion import ZERO, converte
from app.services.payables_service import PayablesService


class ProjectionService:
    @staticmethod
    def ate_o_fim_do_mes(
        db: Session,
        user_id: int,
        target_month: date,
        destino: str,
        saldo_atual: Optional[Decimal],
    ) -> Dict[str, Any]:
        """`{month, receivable_total, payable_total, projected_balance, breakdown}`.

        `saldo_atual = None` (nenhuma conta configurada) devolve `projected_balance`
        também `None`: projetar a partir de um saldo desconhecido produziria um
        número com cara de resposta. As parcelas continuam sendo devolvidas — "a
        receber" e "a pagar" são úteis por si mesmas.
        """
        hoje = today_local()
        ultimo = calendar.monthrange(target_month.year, target_month.month)[1]
        fim_do_mes = date(target_month.year, target_month.month, ultimo)
        _inicio, fim_utc = month_bounds_utc(date(target_month.year, target_month.month, 1))

        linhas: List[Dict[str, Any]] = []

        # --- Entradas previstas -------------------------------------------------
        a_receber, n_receber = ProjectionService._a_receber(
            db, user_id, destino, fim_utc, hoje
        )
        if n_receber:
            linhas.append({
                "kind": "income", "label": "Rendas a receber",
                "amount": a_receber, "count": n_receber,
            })

        # --- Saídas conhecidas --------------------------------------------------
        pendencias = PayablesService.totals(db, user_id, target_month, destino)
        contas = pendencias["payables_total"]
        if pendencias["payables_count"]:
            linhas.append({
                "kind": "payables", "label": "Contas a pagar",
                "amount": contas, "count": pendencias["payables_count"],
            })

        faturas, n_faturas = ProjectionService._faturas(
            db, user_id, destino, fim_do_mes, hoje
        )
        if n_faturas:
            linhas.append({
                "kind": "statements", "label": "Faturas de cartão",
                "amount": faturas, "count": n_faturas,
            })

        parcelas, n_parcelas = ProjectionService._parcelas(
            db, user_id, destino, fim_do_mes, hoje
        )
        if n_parcelas:
            linhas.append({
                "kind": "financing", "label": "Parcelas de financiamento",
                "amount": parcelas, "count": n_parcelas,
            })

        a_pagar = contas + faturas + parcelas
        projetado = (
            saldo_atual + a_receber - a_pagar if saldo_atual is not None else None
        )
        return {
            "month": month_key(target_month),
            "receivable_total": a_receber,
            "payable_total": a_pagar,
            "projected_balance": projetado,
            "breakdown": linhas,
        }

    # ------------------------------------------------------------------
    @staticmethod
    def _a_receber(db: Session, user_id: int, destino: str, fim_utc, hoje: date) -> tuple:
        """Renda prevista: existe, não foi cancelada e ainda não caiu.

        O teto é o fim do mês pedido — o salário de novembro não ajuda a fechar
        setembro. O piso é `None` de propósito: uma renda de agosto que ainda não
        caiu continua sendo dinheiro a receber em setembro, e escondê-la porque a
        competência é antiga é o mesmo erro que esconder conta atrasada.
        """
        linhas = db.exec(
            select(Income.amount, Income.currency, Income.received_at)
            .where(Income.user_id == user_id)
            .where(Income.deleted_at.is_(None))
            .where(Income.cancelled_at.is_(None))
            .where(Income.settled_at.is_(None))
            .where(Income.received_at <= fim_utc)
        ).all()
        total = ZERO
        contadas = 0
        for valor, moeda, _quando in linhas:
            convertido = converte(db, valor or ZERO, moeda, destino, hoje)
            if convertido is None:
                continue
            total += convertido
            contadas += 1
        return total, contadas

    @staticmethod
    def _faturas(db: Session, user_id: int, destino: str, fim_do_mes: date, hoje: date) -> tuple:
        """Saldo das faturas não pagas que vencem até o fim do mês (ou já venceram).

        **Saldo, não total**: `CreditCardService.statement_balance` desconta o que
        já foi pago, e uma fatura paga pela metade só tira do caixa o que falta.
        """
        cartoes = db.exec(
            select(CreditCard)
            .where(CreditCard.owner_user_id == user_id)
            .where(CreditCard.deleted_at.is_(None))
        ).all()
        total = ZERO
        contadas = 0
        for card in cartoes:
            # O teto do vencimento entra no SQL, e não num `continue` depois: sem
            # ele a consulta trazia TODA fatura não paga da vida do cartão e o
            # `statement_balance` — que é uma consulta por fatura — rodava para
            # cada uma antes de o filtro descartá-la.
            faturas = db.exec(
                select(CardStatement)
                .where(CardStatement.card_id == card.id)
                .where(CardStatement.status != StatementStatus.paid)
                .where(CardStatement.due_date <= civil_instant(fim_do_mes))
            ).all()
            for stmt in faturas:
                saldo = CreditCardService.statement_balance(db, stmt)
                if saldo <= ZERO:
                    continue
                convertido = converte(db, saldo, card.currency, destino, hoje)
                if convertido is None:
                    continue
                total += convertido
                contadas += 1
        return total, contadas

    @staticmethod
    def _parcelas(db: Session, user_id: int, destino: str, fim_do_mes: date, hoje: date) -> tuple:
        """Parcelas em aberto que vencem até o fim do mês, SEM despesa que já as conte.

        A dedup espelha `CashFlowService._parcelas` com o filtro invertido: lá a
        parcela é suprimida quando existe despesa vinculada **liquidada**; aqui,
        quando existe despesa vinculada **em aberto** — porque essa despesa já
        aparece em Contas a pagar e somar as duas pediria o mesmo dinheiro duas
        vezes.
        """
        ja_lancada = (
            select(Transaction.id)
            .where(Transaction.financing_installment_id == AmortizationInstallment.id)
            .where(Transaction.deleted_at.is_(None))
            .where(Transaction.status.in_(PAYABLE_STATUSES))
            .exists()
        )
        linhas = db.exec(
            select(
                AmortizationInstallment.total_amount,
                Financing.currency,
                AmortizationInstallment.due_date,
            )
            .join(Financing, Financing.id == AmortizationInstallment.financing_id)
            .where(Financing.owner_user_id == user_id)
            .where(Financing.deleted_at.is_(None))
            .where(Financing.status == FinancingStatus.active)
            .where(AmortizationInstallment.is_paid.is_(False))
            .where(AmortizationInstallment.due_date <= fim_do_mes)
            .where(~ja_lancada)
        ).all()
        total = ZERO
        contadas = 0
        for valor, moeda, _vence in linhas:
            convertido = converte(db, valor or ZERO, moeda, destino, hoje)
            if convertido is None:
                continue
            total += convertido
            contadas += 1
        return total, contadas
