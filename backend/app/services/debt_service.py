from decimal import Decimal
from typing import List, Dict, Any
from sqlmodel import Session, select, func
from app.domain.query_policy import REALIZED_STATUSES, workspace_base_currency
from app.models.settlement import Settlement
from app.models.transaction import Transaction, TransactionPayer, TransactionSplit

class DebtService:
    @staticmethod
    def get_workspace_debts(db: Session, workspace_id: int) -> List[Dict[str, Any]]:
        """
        Calcula o balanço líquido de dívidas entre todos os usuários de um workspace.
        Retorna uma lista simplificada de quem deve quanto para quem.
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

        # 4. Resolver as dívidas (Simplificação de balanços)
        # Separar credores de devedores
        creditors = [(uid, bal) for uid, bal in balances.items() if bal > 0]
        debtors = [(uid, -bal) for uid, bal in balances.items() if bal < 0]

        # Ordenar para processar sistematicamente (opcional, mas ajuda na estabilidade)
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
