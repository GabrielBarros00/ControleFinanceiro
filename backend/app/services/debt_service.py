from decimal import Decimal
from typing import List, Dict, Any, Optional
from sqlmodel import Session, or_, select, func
from app.domain.query_policy import REALIZED_STATUSES, workspace_base_currency
from app.models.settlement import Settlement
from app.models.transaction import (
    Transaction,
    TransactionPayer,
    TransactionSplit,
    TransactionStatus,
)

ZERO = Decimal("0.00")

#: Quantos meses a origem do saldo detalha antes de agrupar o resto em `older`.
#: Três anos de dívida em aberto já é patológico; o que não pode é a lista
#: truncar em silêncio e a conta parar de fechar (ver `get_balance_by_month`).
MESES_NA_ORIGEM = 36


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
    def get_balance_by_month(
        db: Session,
        workspace_id: int,
        user_id: int,
        viewer_user_id: Optional[int] = None,
        limite: int = MESES_NA_ORIGEM,
    ) -> Dict[str, Any]:
        """De quais MESES vem o saldo acumulado de `user_id` nesta casa.

        `get_workspace_debts` responde "quanto" e `get_monthly_ledger` responde
        "como foi agosto"; faltava a ponte entre os dois. Sem ela, quem abre
        Acertos vê um "saldo geral a acertar" de R$ 320 e conclui que precisa
        pagar isso no mês corrente — quando o valor pode ser a soma de três meses
        que ninguém fechou.

        A conta FECHA, e é essa a razão de o método existir:

            balance == Σ months[].balance + older.balance + unassigned

        Ela vale porque o listener de `models/transaction.py` preenche
        `billing_month` a partir de `transaction_date`, então `billing_month`
        particiona todo lançamento e todo acerto do workspace. O que não tem mês
        — acerto global (o registrado a partir do saldo acumulado, sem
        `billing_month`) e eventual linha legada anterior ao listener — cai em
        `unassigned` em vez de sumir. Meses além de `limite` viram `older` pelo
        mesmo motivo: truncar em silêncio devolveria um número plausível e
        errado.

        **Duas pessoas diferentes nos dois parâmetros, de propósito.** `user_id`
        é de quem é o saldo (sempre quem pediu — a pergunta é "de onde vem o
        MEU"); `viewer_user_id` é o recorte do ADR 0018 aplicado a `net_debts`,
        e continua sendo `None` para quem tem acesso completo.

        Não é `get_monthly_ledger` num laço: são cinco consultas agrupadas para o
        histórico inteiro, contra 3+N por mês visitado.
        """
        base_currency = workspace_base_currency(db, workspace_id)

        # Os MESMOS filtros de `get_workspace_debts`. Qualquer divergência aqui
        # (um status a mais, a moeda de fora) quebra a identidade acima — e ela
        # quebraria em silêncio, porque os dois números são plausíveis.
        # `select_from` explícito: a primeira coluna do SELECT é
        # `Transaction.billing_month`, então sem ele o SQLAlchemy inferiria
        # `Transaction` como origem e o `.join(Transaction)` viraria auto-join.
        def _do_workspace(stmt, origem):
            return (
                stmt.select_from(origem)
                .join(Transaction)
                .where(Transaction.workspace_id == workspace_id)
                .where(Transaction.deleted_at.is_(None))
                .where(Transaction.status.in_(REALIZED_STATUSES))
                .where(Transaction.currency == base_currency)
            )

        # saldos[mês][pessoa] — a chave `None` é o balde "sem mês".
        saldos: Dict[Optional[str], Dict[int, Decimal]] = {}

        def _acumula(mes: Optional[str], uid: int, valor: Decimal) -> None:
            pessoas = saldos.setdefault(mes, {})
            pessoas[uid] = pessoas.get(uid, ZERO) + valor

        pagos = db.exec(
            _do_workspace(
                select(
                    Transaction.billing_month,
                    TransactionPayer.user_id,
                    func.sum(TransactionPayer.amount),
                ),
                TransactionPayer,
            ).group_by(Transaction.billing_month, TransactionPayer.user_id)
        ).all()
        for mes, uid, total in pagos:
            _acumula(mes, uid, total)

        devidos = db.exec(
            _do_workspace(
                select(
                    Transaction.billing_month,
                    TransactionSplit.user_id,
                    func.sum(TransactionSplit.computed_amount),
                ),
                TransactionSplit,
            ).group_by(Transaction.billing_month, TransactionSplit.user_id)
        ).all()
        for mes, uid, total in devidos:
            _acumula(mes, uid, -total)

        # Acerto: quem pagou reduz a dívida (saldo sobe), quem recebeu reduz o
        # crédito (saldo desce) — mesmo ajuste de `get_workspace_debts`.
        for coluna, sinal in ((Settlement.from_user_id, 1), (Settlement.to_user_id, -1)):
            linhas = db.exec(
                select(Settlement.billing_month, coluna, func.sum(Settlement.amount))
                .where(Settlement.workspace_id == workspace_id)
                .where(Settlement.deleted_at.is_(None))
                .group_by(Settlement.billing_month, coluna)
            ).all()
            for mes, uid, total in linhas:
                _acumula(mes, uid, sinal * total)

        # Quanto JÁ foi acertado em cada mês, contando só o que me envolve — é o
        # "R$ 40,00 já acertados" que a linha do mês mostra. Sem o recorte, um
        # acerto entre terceiros apareceria como se fosse abatimento meu.
        acertado_por_mes: Dict[Optional[str], Decimal] = {
            mes: total
            for mes, total in db.exec(
                select(Settlement.billing_month, func.sum(Settlement.amount))
                .where(Settlement.workspace_id == workspace_id)
                .where(Settlement.deleted_at.is_(None))
                .where(
                    or_(
                        Settlement.from_user_id == user_id,
                        Settlement.to_user_id == user_id,
                    )
                )
                .group_by(Settlement.billing_month)
            ).all()
        }

        # O total vem da MESMA fonte que a quebra, somando inclusive os meses
        # que não entram na lista (saldo zero) e o balde sem mês. É por
        # construção o saldo de `get_workspace_debts`, e o teste confere isso.
        saldo_total = sum(
            (pessoas.get(user_id, ZERO) for pessoas in saldos.values()), ZERO
        )

        meses: List[Dict[str, Any]] = []
        for mes in sorted((m for m in saldos if m is not None), reverse=True):
            pessoas = saldos[mes]
            meu = pessoas.get(user_id, ZERO)
            if meu == 0:
                # Mês quitado (ou em que não entrei) não é origem de saldo
                # nenhum. Contribui zero, então some da lista sem afetar a conta.
                continue
            meses.append({
                "month": mes,
                "balance": meu,
                # O pareamento é do mês, calculado sobre TODOS os saldos e
                # recortado depois (ver `_only_involving`).
                "net_debts": _only_involving(
                    DebtService._settle_balances(pessoas), viewer_user_id
                ),
                "settled": acertado_por_mes.get(mes, ZERO),
            })

        antigos = meses[limite:]
        meses = meses[:limite]

        return {
            "base_currency": base_currency,
            "balance": saldo_total,
            "months": meses,
            "older": {
                "count": len(antigos),
                "balance": sum((m["balance"] for m in antigos), ZERO),
            },
            # Com sinal: acerto global em que EU paguei sobe meu saldo, em que eu
            # recebi desce. É a linha "sem mês" da tela.
            "unassigned": saldos.get(None, {}).get(user_id, ZERO),
        }

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
