from decimal import Decimal
from typing import List, Dict, Any, Optional
from sqlmodel import Session, select, func
from app.domain.query_policy import REALIZED_STATUSES, workspace_base_currency
from app.models.settlement import Settlement
from app.models.transaction import (
    Transaction,
    TransactionPayer,
    TransactionSplit,
    TransactionStatus,
)

def _only_involving(rows: List[Dict[str, Any]], user_id: Optional[int]) -> List[Dict[str, Any]]:
    """Recorta o pareamento de dívidas nas linhas em que `user_id` é uma das pontas.

    Filtra a SAÍDA, nunca a entrada. O pareamento em `_settle_balances` é guloso
    sobre o conjunto INTEIRO de saldos: tirar membros antes de parear produziria
    outro emparelhamento — e um valor devido diferente do real. Então calcula-se o
    ledger completo e só depois se esconde o que não é meu (ADR 0018).
    """
    if user_id is None:
        return rows
    return [r for r in rows if user_id in (r["debtor_id"], r["creditor_id"])]


class DebtService:
    @staticmethod
    def get_workspace_debts(
        db: Session, workspace_id: int, viewer_user_id: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """
        Calcula o balanço líquido de dívidas entre todos os usuários de um workspace.
        Retorna uma lista simplificada de quem deve quanto para quem.

        `viewer_user_id` preenchido (membro sem acesso completo) recorta o
        resultado nas dívidas em que ele é devedor ou credor.
        """
        base_currency = workspace_base_currency(db, workspace_id)
        # 1. Calcular quanto cada usuário PAGOU no workspace
        # Política única (ADR 0003/0006): só status realizados e moeda-base
        payers_stmt = (
            select(TransactionPayer.user_id, func.sum(TransactionPayer.amount).label("total_paid"))
            .join(Transaction)
            .where(Transaction.workspace_id == workspace_id)
            .where(Transaction.deleted_at.is_(None))
            .where(Transaction.status.in_(REALIZED_STATUSES))
            .where(Transaction.currency == base_currency)
            .group_by(TransactionPayer.user_id)
        )
        total_paid = {r[0]: r[1] for r in db.exec(payers_stmt).all()}

        # 2. Calcular quanto cada usuário DEVE (splits) no workspace
        splits_stmt = (
            select(TransactionSplit.user_id, func.sum(TransactionSplit.computed_amount).label("total_owed"))
            .join(Transaction)
            .where(Transaction.workspace_id == workspace_id)
            .where(Transaction.deleted_at.is_(None))
            .where(Transaction.status.in_(REALIZED_STATUSES))
            .where(Transaction.currency == base_currency)
            .group_by(TransactionSplit.user_id)
        )
        total_owed = {r[0]: r[1] for r in db.exec(splits_stmt).all()}

        # 3. Calcular o balanço líquido de cada usuário
        # Saldo = Pago - Devido
        # Saldo Positivo: O usuário tem crédito (precisa receber)
        # Saldo Negativo: O usuário tem débito (precisa pagar)
        # 2b. Acertos registrados: quem pagou um acerto reduz sua dívida
        # (saldo sobe); quem recebeu reduz seu crédito (saldo desce)
        settled_out_stmt = (
            select(Settlement.from_user_id, func.sum(Settlement.amount))
            .where(Settlement.workspace_id == workspace_id)
            .where(Settlement.deleted_at.is_(None))
            .group_by(Settlement.from_user_id)
        )
        settled_out = {r[0]: r[1] for r in db.exec(settled_out_stmt).all()}

        settled_in_stmt = (
            select(Settlement.to_user_id, func.sum(Settlement.amount))
            .where(Settlement.workspace_id == workspace_id)
            .where(Settlement.deleted_at.is_(None))
            .group_by(Settlement.to_user_id)
        )
        settled_in = {r[0]: r[1] for r in db.exec(settled_in_stmt).all()}

        all_users = (
            set(total_paid.keys()) | set(total_owed.keys())
            | set(settled_out.keys()) | set(settled_in.keys())
        )
        balances = {}
        for user_id in all_users:
            paid = total_paid.get(user_id, Decimal("0.00"))
            owed = total_owed.get(user_id, Decimal("0.00"))
            balances[user_id] = (
                paid - owed
                + settled_out.get(user_id, Decimal("0.00"))
                - settled_in.get(user_id, Decimal("0.00"))
            )

        # 4. Resolver as dívidas (simplificação de balanços) e recortar na visão
        # de quem pediu
        return _only_involving(DebtService._settle_balances(balances), viewer_user_id)

    @staticmethod
    def _settle_balances(balances: Dict[int, Decimal]) -> List[Dict[str, Any]]:
        """Simplifica saldos líquidos em quem-deve-quem (matching guloso).

        Saldo > 0 → credor (recebe); saldo < 0 → devedor (paga). Fonte única do
        pareamento — usada pelo balanço global (settlement-aware) e pelo ledger
        mensal, para os dois nunca divergirem.
        """
        creditors = [(uid, bal) for uid, bal in balances.items() if bal > 0]
        debtors = [(uid, -bal) for uid, bal in balances.items() if bal < 0]

        # Ordenar para processar sistematicamente (ajuda na estabilidade)
        creditors.sort(key=lambda x: x[1], reverse=True)
        debtors.sort(key=lambda x: x[1], reverse=True)

        final_debts = []
        i, j = 0, 0
        while i < len(debtors) and j < len(creditors):
            debtor_id, debt_amt = debtors[i]
            creditor_id, credit_amt = creditors[j]

            settled_amount = min(debt_amt, credit_amt)
            if settled_amount > 0:
                final_debts.append({
                    "debtor_id": debtor_id,
                    "creditor_id": creditor_id,
                    "amount": settled_amount.quantize(Decimal("0.01"))
                })

            debtors[i] = (debtor_id, debt_amt - settled_amount)
            creditors[j] = (creditor_id, credit_amt - settled_amount)

            if debtors[i][1] == 0:
                i += 1
            if creditors[j][1] == 0:
                j += 1

        return final_debts

    @staticmethod
    def get_monthly_ledger(
        db: Session, workspace_id: int, month: str, viewer_user_id: Optional[int] = None
    ) -> Dict[str, Any]:
        """Fotografia das dívidas de UM mês (por billing_month).

        Diferente do balanço global (settlement-aware), aqui é o retrato do mês:
        quem pagou, quanto cada um deve e o status de cada despesa. Parcelas
        aparecem só no seu mês — é o que dá a visão "dívida por mês". Acertos
        (settlements) são globais e não entram nesta conta.

        `viewer_user_id` preenchido (membro sem acesso completo, ADR 0018) recorta
        TUDO na visão dele: só as despesas em que ele entra, só a linha dele em
        `members`, só as dívidas e acertos que o envolvem — e `totals` passa a ser
        o total do que ele vê, para os números da tela fecharem entre si (mesmo
        princípio da soma do extrato em `transactions.list_transactions`).
        """
        base_currency = workspace_base_currency(db, workspace_id)

        txs = db.exec(
            select(Transaction)
            .where(Transaction.workspace_id == workspace_id)
            .where(Transaction.billing_month == month)
            .where(Transaction.deleted_at.is_(None))
            .where(Transaction.status.in_(REALIZED_STATUSES))
            .where(Transaction.currency == base_currency)
            .order_by(Transaction.transaction_date)
        ).all()
        tx_ids = [t.id for t in txs]

        payers_by_tx: Dict[int, List[TransactionPayer]] = {}
        splits_by_tx: Dict[int, List[TransactionSplit]] = {}
        paid_by_user: Dict[int, Decimal] = {}
        owed_by_user: Dict[int, Decimal] = {}

        if tx_ids:
            for p in db.exec(
                select(TransactionPayer).where(TransactionPayer.transaction_id.in_(tx_ids))
            ).all():
                payers_by_tx.setdefault(p.transaction_id, []).append(p)
                paid_by_user[p.user_id] = paid_by_user.get(p.user_id, Decimal("0.00")) + p.amount
            for s in db.exec(
                select(TransactionSplit).where(TransactionSplit.transaction_id.in_(tx_ids))
            ).all():
                splits_by_tx.setdefault(s.transaction_id, []).append(s)
                owed_by_user[s.user_id] = owed_by_user.get(s.user_id, Decimal("0.00")) + s.computed_amount

        all_users = set(paid_by_user) | set(owed_by_user)
        balances = {
            uid: paid_by_user.get(uid, Decimal("0.00")) - owed_by_user.get(uid, Decimal("0.00"))
            for uid in all_users
        }
        # A quebra por membro é o dado mais revelador do ledger ("quanto cada um
        # pagou e deve no mês"). Sem acesso completo, sobra a linha de quem pediu.
        visiveis = (
            sorted(all_users)
            if viewer_user_id is None
            else [uid for uid in sorted(all_users) if uid == viewer_user_id]
        )
        members = [
            {
                "user_id": uid,
                "paid": paid_by_user.get(uid, Decimal("0.00")),
                "owed": owed_by_user.get(uid, Decimal("0.00")),
                "balance": balances[uid],
            }
            for uid in visiveis
        ]

        # Acertos vinculados a ESTE mês (billing_month) abatem a dívida do mês.
        # Mesmo ajuste do balanço global (get_workspace_debts): quem pagou sobe,
        # quem recebeu desce — assim net_debts zera quando o mês é quitado.
        month_settlements = db.exec(
            select(Settlement)
            .where(Settlement.workspace_id == workspace_id)
            .where(Settlement.billing_month == month)
            .where(Settlement.deleted_at.is_(None))
        ).all()
        settled_total = Decimal("0.00")
        for s in month_settlements:
            balances[s.from_user_id] = balances.get(s.from_user_id, Decimal("0.00")) + s.amount
            balances[s.to_user_id] = balances.get(s.to_user_id, Decimal("0.00")) - s.amount
            settled_total += s.amount

        def _envolvido(t: Transaction) -> bool:
            """Envolvimento com os dados JÁ carregados — mesma definição de
            `access_policy.involvement_filter`, sem uma ida a mais ao banco."""
            if viewer_user_id is None:
                return True
            if t.created_by_user_id == viewer_user_id:
                return True
            if any(p.user_id == viewer_user_id for p in payers_by_tx.get(t.id, [])):
                return True
            return any(s.user_id == viewer_user_id for s in splits_by_tx.get(t.id, []))

        total = Decimal("0.00")
        paid_total = Decimal("0.00")
        expenses = []
        for t in txs:
            if not _envolvido(t):
                continue
            total += t.total_amount
            if t.status == TransactionStatus.paid:
                paid_total += t.total_amount
            expenses.append({
                "id": t.id,
                "title": t.title,
                "total_amount": t.total_amount,
                "status": t.status,
                "is_paid": t.status == TransactionStatus.paid,
                "transaction_date": t.transaction_date,
                "installment_no": t.installment_no,
                "installments_of": t.installments_of,
                "payers": [
                    {"user_id": p.user_id, "amount": p.amount}
                    for p in payers_by_tx.get(t.id, [])
                ],
                "splits": [
                    {"user_id": s.user_id, "computed_amount": s.computed_amount}
                    for s in splits_by_tx.get(t.id, [])
                ],
            })

        # Acertos: os de TODOS já entraram em `balances` acima (o pareamento
        # precisa deles), mas só aparecem os que me envolvem — e `settled_total`
        # acompanha o que está listado, senão a tela mostra "acertado R$ X" com
        # uma lista que não soma X.
        acertos_visiveis = [
            s for s in month_settlements
            if viewer_user_id is None
            or viewer_user_id in (s.from_user_id, s.to_user_id)
        ]
        if viewer_user_id is not None:
            settled_total = sum((s.amount for s in acertos_visiveis), Decimal("0.00"))

        return {
            "month": month,
            "base_currency": base_currency,
            "members": members,
            "net_debts": _only_involving(
                DebtService._settle_balances(balances), viewer_user_id
            ),
            "expenses": expenses,
            "settled_total": settled_total,
            "settlements": [
                {
                    "id": s.id,
                    "from_user_id": s.from_user_id,
                    "to_user_id": s.to_user_id,
                    "amount": s.amount,
                    "note": s.note,
                    "settled_at": s.settled_at,
                }
                for s in acertos_visiveis
            ],
            "totals": {
                "total": total,
                "paid": paid_total,
                "open": total - paid_total,
            },
        }
