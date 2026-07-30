from decimal import Decimal
from typing import Any, Dict, List, Optional

from sqlmodel import Session, select, func

from app.domain.access_policy import (
    cards_of_workspace,
    financings_of_workspace,
    involvement_filter,
    owner_scope_for,
)
from app.domain.query_policy import REALIZED_STATUSES, workspace_base_currency
from app.models.credit_card import CreditCard, StatementStatus
from app.models.financing import (
    AmortizationInstallment,
    Financing,
    FinancingStatus,
)
from app.models.transaction import Transaction, TransactionSplit
from app.services.credit_card_service import CreditCardService

ZERO = Decimal("0.00")


class LiabilityService:
    """Panorama de endividamento: quanto o workspace deve a terceiros
    (financiamentos + faturas de cartão), no total, no mês e por pessoa.

    É um eixo DIFERENTE do acerto entre membros (DebtService): aqui a dívida é
    com o banco/cartão, não entre os membros. Responsável:
      - Financiamento tem dono único (created_by_user_id) — não é rateado.
      - Fatura de cartão é rateada pelos *splits* das compras (mesma noção de
        "minha parte" do resto do app).

    Só leitura/agregação — reusa card_committed/effective_total do serviço de
    cartão para não divergir do limite comprometido já mostrado nos cartões.
    """

    @staticmethod
    def get_overview(
        db: Session, workspace_id: int, month: str, viewer_user_id: Optional[int] = None
    ) -> Dict[str, Any]:
        """Panorama de endividamento da casa.

        `viewer_user_id` preenchido (sem acesso completo, ADR 0018): sobram os
        financiamentos dele e os cartões em que ele tem compra, e os totais passam
        a ser desse recorte — nunca o endividamento da casa inteira.
        """
        base_currency = workspace_base_currency(db, workspace_id)

        financing_outstanding, financing_due, by_person_financing, financings_out = (
            LiabilityService._financings(
                db, workspace_id, base_currency, month, viewer_user_id
            )
        )
        cards_committed, cards_due, by_person_cards, cards_out = (
            LiabilityService._cards(
                db, workspace_id, base_currency, month, viewer_user_id
            )
        )

        all_users = set(by_person_financing) | set(by_person_cards)
        if viewer_user_id is not None:
            # A quebra por pessoa é o "quanto cada um deve" da casa
            all_users &= {viewer_user_id}
        by_person = [
            {
                "user_id": uid,
                "financing": by_person_financing.get(uid, ZERO),
                "cards": by_person_cards.get(uid, ZERO),
                "total": by_person_financing.get(uid, ZERO) + by_person_cards.get(uid, ZERO),
            }
            for uid in all_users
        ]
        by_person.sort(key=lambda p: p["total"], reverse=True)

        return {
            "month": month,
            "base_currency": base_currency,
            "totals": {
                "financing_outstanding": financing_outstanding,
                "cards_committed": cards_committed,
                "grand_total": financing_outstanding + cards_committed,
            },
            "month_due": {
                "financing_due": financing_due,
                "cards_due": cards_due,
                "total": financing_due + cards_due,
            },
            "by_person": by_person,
            "financings": financings_out,
            "cards": cards_out,
        }

    @staticmethod
    def _financings(
        db: Session,
        workspace_id: int,
        base_currency: str,
        month: str,
        viewer_user_id: Optional[int] = None,
    ):
        """Saldo devedor = principal ainda não pago (juros futuros não são dívida
        até a parcela cair). Simulados/quitados ficam de fora. Cada financiamento
        vai inteiro para o dono."""
        financings = db.exec(
            select(Financing).where(
                # Deste workspace + os compartilhados com ele (ADR 0019): o
                # financiamento do imóvel do casal compõe o endividamento da casa
                # sem precisar de um segundo cadastro.
                financings_of_workspace(workspace_id),
                Financing.deleted_at.is_(None),
                Financing.status == FinancingStatus.active,
                Financing.currency == base_currency,
                # Mesmo recorte da listagem de financiamentos (ADR 0018)
                owner_scope_for(Financing.created_by_user_id, viewer_user_id),
            )
        ).all()

        insts_by_fin: Dict[int, List[AmortizationInstallment]] = {}
        fin_ids = [f.id for f in financings]
        if fin_ids:
            for inst in db.exec(
                select(AmortizationInstallment).where(
                    AmortizationInstallment.financing_id.in_(fin_ids)
                )
            ).all():
                insts_by_fin.setdefault(inst.financing_id, []).append(inst)

        total_outstanding = ZERO
        total_due = ZERO
        by_person: Dict[int, Decimal] = {}
        out: List[Dict[str, Any]] = []
        for f in financings:
            unpaid = [i for i in insts_by_fin.get(f.id, []) if not i.is_paid]
            outstanding = sum((i.principal_amount for i in unpaid), ZERO)
            due = sum(
                (i.total_amount for i in unpaid if i.due_date.strftime("%Y-%m") == month),
                ZERO,
            )
            next_due = min((i.due_date for i in unpaid), default=None)

            total_outstanding += outstanding
            total_due += due
            by_person[f.created_by_user_id] = (
                by_person.get(f.created_by_user_id, ZERO) + outstanding
            )
            out.append({
                "id": f.id,
                "title": f.title,
                "owner_id": f.created_by_user_id,
                "outstanding": outstanding,
                "month_due": due,
                "next_due_date": next_due,
                "installments_count": f.installments_count,
                "remaining_installments": len(unpaid),
            })

        out.sort(key=lambda x: x["outstanding"], reverse=True)
        return total_outstanding, total_due, by_person, out

    @staticmethod
    def _cards(
        db: Session,
        workspace_id: int,
        base_currency: str,
        month: str,
        viewer_user_id: Optional[int] = None,
    ):
        """Dívida do cartão = faturas ainda não pagas (card_committed já soma
        aberta=calculada + fechada=congelada). O que vence no mês são as faturas
        com due_date no mês. Por pessoa vem dos splits das compras — pode divergir
        alguns centavos do congelado numa fatura fechada e reeditada; o total
        autoritativo continua sendo o comprometido."""
        cards_stmt = select(CreditCard).where(
            # Cartão compartilhado entra UMA vez, no workspace que o compartilha —
            # antes, usar o mesmo cartão em dois lugares exigia dois cadastros e a
            # MESMA fatura era contada duas vezes aqui (ADR 0019).
            cards_of_workspace(workspace_id),
            CreditCard.deleted_at.is_(None),
        )
        if viewer_user_id is not None:
            # Mesmo recorte de `access_policy.card_scope`: o cartão em que eu tenho
            # compra. Sem isto o painel devolvia o limite comprometido de todos os
            # cartões da casa — inclusive os que a listagem de cartões já esconde.
            cards_stmt = cards_stmt.where(
                CreditCard.id.in_(
                    select(Transaction.credit_card_id)
                    .where(Transaction.workspace_id == workspace_id)
                    .where(Transaction.credit_card_id.is_not(None))
                    .where(involvement_filter(viewer_user_id))
                )
            )
        cards = db.exec(cards_stmt).all()

        total_committed = ZERO
        total_due = ZERO
        out: List[Dict[str, Any]] = []
        unpaid_statement_ids: List[int] = []
        for card in cards:
            # Uma passada só: `card_committed` já varre as faturas por dentro de
            # `card_overview`, e havia um segundo SELECT logo abaixo para os
            # mesmos dados — duas varreduras (e um SUM por fatura aberta) por
            # cartão só para montar este painel.
            overview = CreditCardService.card_overview(db, card)
            committed = overview["committed"]
            total_committed += committed

            card_due = ZERO
            for s in overview["statements"]:
                if s.status == StatementStatus.paid:
                    continue
                unpaid_statement_ids.append(s.id)
                if s.due_date.strftime("%Y-%m") == month:
                    card_due += CreditCardService.effective_total(db, s)
            total_due += card_due
            out.append({
                "id": card.id,
                "name": card.name,
                "committed": committed,
                "month_due": card_due,
            })

        by_person: Dict[int, Decimal] = {}
        if unpaid_statement_ids:
            rows = db.exec(
                select(
                    TransactionSplit.user_id,
                    func.sum(TransactionSplit.computed_amount),
                )
                .join(Transaction, Transaction.id == TransactionSplit.transaction_id)
                .where(
                    Transaction.statement_id.in_(unpaid_statement_ids),
                    Transaction.deleted_at.is_(None),
                    Transaction.status.in_(REALIZED_STATUSES),
                    Transaction.currency == base_currency,
                )
                .group_by(TransactionSplit.user_id)
            ).all()
            for uid, amount in rows:
                by_person[uid] = amount or ZERO

        out.sort(key=lambda x: x["committed"], reverse=True)
        return total_committed, total_due, by_person, out
