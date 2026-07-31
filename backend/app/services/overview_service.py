"""Visão GLOBAL e pessoal: o mês da pessoa somando todos os workspaces (ADR 0020).

O "Início" era a dashboard de um workspace disfarçada de tela pessoal: lia o
`currentWorkspaceId` guardado no navegador e misturava "minha parte" com "toda a
casa". Quem participa de dois workspaces não tinha lugar nenhum que respondesse
"quanto eu ganhei, quanto consumi e quanto tenho a pagar **no total**".

Cinco números que o app confundia num só — e que aqui são explícitos:

| Número                | Fórmula                              | Pergunta que responde         |
|-----------------------|--------------------------------------|-------------------------------|
| **Consumo**           | Σ dos meus `TransactionSplit`        | quanto do gasto foi meu       |
| **Adiantado**         | Σ dos meus `TransactionPayer`        | quanto eu assumi nas despesas |
| **A pagar/receber**   | consumo − adiantado, por workspace   | quanto acerto com quem        |
| **Resultado**         | renda − consumo                      | sobrou ou faltou no mês       |
| **Caixa (in/out)**    | `CashFlowService` (ADR 0022)         | quando o dinheiro se moveu    |

O app só calculava consumo e resultado, e "Seu saldo" no Início era um nome errado
para o resultado do período (não é saldo bancário, e nunca foi).

**Adiantado ≠ caixa.** O campo hoje chamado `paid_in_transactions` já se chamou
`cash_out`, e o nome era falso: a compra no cartão entrava nele no mês do
lançamento, com o dinheiro ainda na conta, e o pagamento da fatura não entrava em
lugar nenhum. Ele é o número certo para o ACERTO (quem assumiu o quê) e continua
recortado por workspace; o caixa efetivo é global e vive no `CashFlowService`.

**Moeda:** somar workspaces com moedas-base diferentes viola o ADR 0006. O
destino é `User.report_currency`, e o que não converte fica de fora com contagem —
mesma política do `excluded_foreign_count`.

**Não se compensa dívida entre workspaces.** Dever 100 na casa e ter 100 a receber
no rateio da viagem não é o mesmo que estar quitado: são pessoas e acordos
diferentes. Os saldos são agrupados POR workspace, e o total é informativo.
"""
import calendar
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional

from sqlmodel import Session, func, select

from app.domain.access_policy import involvement_filter
from app.domain.dates import month_key
from app.domain.query_policy import REALIZED_STATUSES, workspace_base_currency
from app.models.credit_card import CreditCard, StatementStatus
from app.models.financing import AmortizationInstallment, Financing, FinancingStatus
from app.models.transaction import Transaction, TransactionPayer, TransactionSplit
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMembership
from app.services.cashflow_service import CashFlowService
from app.services.credit_card_service import CreditCardService
from app.services.debt_service import DebtService
from app.services.money_conversion import ZERO, converte


class OverviewService:
    @staticmethod
    def report_currency(db: Session, user_id: int) -> str:
        usuario = db.get(User, user_id)
        return (usuario.report_currency if usuario and usuario.report_currency else "BRL")

    @staticmethod
    def _converte(
        db: Session, valor: Decimal, de: str, para: str, quando: date
    ) -> Optional[Decimal]:
        """`None` quando não há taxa: o valor fica FORA da soma e é contado como
        excluído, em vez de entrar com uma conversão inventada (ADR 0006).

        A regra mora em `money_conversion.converte` desde que o caixa efetivo
        passou a usá-la; aqui fica o apelido, para as chamadas existentes.
        """
        return converte(db, valor, de, para, quando)

    @staticmethod
    def _workspaces_do_usuario(db: Session, user_id: int) -> List[Workspace]:
        ids = db.exec(
            select(WorkspaceMembership.workspace_id).where(
                WorkspaceMembership.user_id == user_id
            )
        ).all()
        if not ids:
            return []
        return db.exec(
            select(Workspace)
            .where(Workspace.id.in_(ids))
            .where(Workspace.deleted_at.is_(None))
            .order_by(Workspace.name)
        ).all()

    # ------------------------------------------------------------------
    @staticmethod
    def get_overview(
        db: Session, user_id: int, target_month: date, currency: Optional[str] = None
    ) -> Dict[str, Any]:
        """O mês da PESSOA, somando todos os workspaces dela."""
        destino = currency or OverviewService.report_currency(db, user_id)
        mes = month_key(target_month)
        primeiro = date(target_month.year, target_month.month, 1)
        ultimo_dia = calendar.monthrange(target_month.year, target_month.month)[1]
        inicio = datetime.combine(primeiro, datetime.min.time())
        fim = datetime.combine(
            date(target_month.year, target_month.month, ultimo_dia), datetime.max.time()
        )

        workspaces = OverviewService._workspaces_do_usuario(db, user_id)

        # --- Caixa efetivo e renda (ADR 0022) ----------------------------------
        # Renda sai daqui junto com o caixa porque é uma das seis fontes do
        # ledger: manter a mesma consulta em dois lugares era o caminho curto para
        # os dois números discordarem.
        fluxo = CashFlowService.get_month(db, user_id, target_month, destino, inicio, fim)
        renda_total = fluxo["income"]
        excluidos = fluxo["excluded_foreign_count"]

        # --- Consumo, adiantamento e acertos, workspace a workspace ------------
        consumo_total = ZERO
        adiantado_total = ZERO
        por_workspace: List[Dict[str, Any]] = []
        a_pagar_total = ZERO
        a_receber_total = ZERO

        for ws in workspaces:
            base = workspace_base_currency(db, ws.id)

            consumo = db.exec(
                select(func.coalesce(func.sum(TransactionSplit.computed_amount), 0))
                .join(Transaction, Transaction.id == TransactionSplit.transaction_id)
                .where(Transaction.workspace_id == ws.id)
                .where(Transaction.billing_month == mes)
                .where(Transaction.deleted_at.is_(None))
                .where(Transaction.status.in_(REALIZED_STATUSES))
                .where(Transaction.currency == base)
                .where(TransactionSplit.user_id == user_id)
            ).one() or ZERO

            # ADIANTADO NOS LANÇAMENTOS — o que eu assumi nas despesas desta casa.
            # Sem ele não dá para dizer "consumi 300 mas paguei 500, tenho 200 a
            # receber": o app só sabia falar de consumo.
            #
            # Este número CHAMAVA-SE `cash_out` e não era caixa (ADR 0022): a
            # compra no cartão entra aqui no mês do lançamento, com o dinheiro
            # ainda na conta, e o pagamento da fatura não entra em lugar nenhum.
            # Ele continua sendo o número certo PARA O ACERTO — que é sobre quem
            # assumiu o quê, não sobre quando o dinheiro saiu —, e por isso é o que
            # fecha `to_pay`/`to_receive` por workspace. O caixa de verdade é
            # global e vem do `CashFlowService`.
            adiantado = db.exec(
                select(func.coalesce(func.sum(TransactionPayer.amount), 0))
                .join(Transaction, Transaction.id == TransactionPayer.transaction_id)
                .where(Transaction.workspace_id == ws.id)
                .where(Transaction.billing_month == mes)
                .where(Transaction.deleted_at.is_(None))
                .where(Transaction.status.in_(REALIZED_STATUSES))
                .where(Transaction.currency == base)
                .where(TransactionPayer.user_id == user_id)
            ).one() or ZERO

            consumo_conv = OverviewService._converte(db, consumo, base, destino, primeiro)
            adiantado_conv = OverviewService._converte(db, adiantado, base, destino, primeiro)

            # Acerto entre pessoas: o ledger COMPLETO do workspace (o pareamento
            # precisa de todos os saldos) recortado nas linhas que me envolvem.
            saldos = DebtService.get_workspace_debts(db, ws.id, viewer_user_id=user_id)
            devo = sum(
                (d["amount"] for d in saldos if d["debtor_id"] == user_id), ZERO
            )
            recebo = sum(
                (d["amount"] for d in saldos if d["creditor_id"] == user_id), ZERO
            )
            devo_conv = OverviewService._converte(db, devo, base, destino, primeiro)
            recebo_conv = OverviewService._converte(db, recebo, base, destino, primeiro)

            # Sem cotação, o workspace INTEIRO fica de fora e é contado — inclusive
            # quando o que não converte é só o saldo. A versão anterior escrevia
            # `_converte(...) or ZERO` nos dois saldos, e o `or` engolia o `None`
            # sem incrementar `excluidos`: uma dívida em aberto de USD 100 de um mês
            # anterior, num mês corrente sem lançamento novo, virava `to_pay = 0`
            # com `excluded_foreign_count = 0`. Omitir um lançamento avisando é a
            # política do ADR 0006; dizer "você não deve nada" a quem deve é outra
            # coisa.
            if any(v is None for v in (consumo_conv, adiantado_conv, devo_conv, recebo_conv)):
                excluidos += 1
                continue

            consumo_total += consumo_conv
            adiantado_total += adiantado_conv
            a_pagar_total += devo_conv
            a_receber_total += recebo_conv

            # Workspace sem movimento nenhum não vira linha na tela: a seção "Por
            # workspace" listava TODAS as casas da pessoa, com zeros, e por isso o
            # estado vazio ("Nenhum movimento neste mês") era inalcançável para
            # quem tem mais de um workspace.
            if all(
                v == ZERO
                for v in (consumo_conv, adiantado_conv, devo_conv, recebo_conv)
            ):
                continue

            por_workspace.append({
                "workspace_id": ws.id,
                "workspace_name": ws.name,
                "base_currency": base,
                "consumption": consumo_conv,
                "paid_in_transactions": adiantado_conv,
                "to_pay": devo_conv,
                "to_receive": recebo_conv,
            })

        return {
            "month": mes,
            "currency": destino,
            # --- Competência: de quem é o gasto ---------------------------------
            "income": renda_total,
            "consumption": consumo_total,
            # O que eu assumi nos lançamentos. Era `cash_out` e não era caixa
            # (ADR 0022) — o nome novo diz o que o número sempre mediu.
            "paid_in_transactions": adiantado_total,
            # Resultado do mês: renda − CONSUMO (não − caixa). O que eu adiantei
            # por outra pessoa não é gasto meu; é crédito a receber.
            "result": renda_total - consumo_total,
            # --- Caixa: quando o dinheiro se moveu ------------------------------
            # Global, sem recorte por workspace: pagamento de fatura e parcela de
            # financiamento não moram em workspace nenhum, e forçá-los num
            # reintroduziria a premissa que o ADR 0021 removeu.
            "cash_in": fluxo["cash_in"],
            "cash_out": fluxo["cash_out"],
            "net_cash": fluxo["net_cash"],
            "cash_out_breakdown": fluxo["cash_out_breakdown"],
            "cash_in_breakdown": fluxo["cash_in_breakdown"],
            # --- Acerto entre pessoas -------------------------------------------
            "to_pay": a_pagar_total,
            "to_receive": a_receber_total,
            # Por workspace, NUNCA compensado entre eles: dever na casa e ter a
            # receber na viagem envolve pessoas e acordos diferentes.
            "by_workspace": por_workspace,
            "excluded_foreign_count": excluidos,
        }

    # ------------------------------------------------------------------
    @staticmethod
    def get_series(
        db: Session, user_id: int, months: int = 6, currency: Optional[str] = None
    ) -> Dict[str, Any]:
        """Os últimos `months` meses da PESSOA — o relatório que não existia.

        Relatórios sempre foram de um workspace: eles respondem "quanto esta casa
        gastou". Nenhuma tela respondia "como está o MEU ano" — renda contra
        consumo, resultado mês a mês, e quanto de mim foi para cada casa. Quem
        participa de dois workspaces tinha de somar de cabeça, e depois do ADR
        0021 (renda fora do workspace) nem isso era possível: os Relatórios não
        falam mais de renda.

        Reusa `get_overview` mês a mês em vez de reescrever as agregações: é a
        mesma definição de consumo, caixa e acerto, então as duas telas não têm
        como divergir. O custo é linear no número de meses, aceitável para 6–12
        num app de um worker.

        A participação por workspace é acumulada no PERÍODO: é ela que responde
        "quanto do meu ano foi para a Casa e quanto foi para a Viagem".
        """
        destino = currency or OverviewService.report_currency(db, user_id)
        hoje = datetime.now(UTC).date()

        serie: List[Dict[str, Any]] = []
        por_workspace: Dict[int, Dict[str, Any]] = {}
        totais = {
            "income": ZERO, "consumption": ZERO, "result": ZERO,
            "cash_in": ZERO, "cash_out": ZERO, "net_cash": ZERO,
        }
        excluidos = 0

        for passo in range(months - 1, -1, -1):
            ano, mes_num = hoje.year, hoje.month - passo
            while mes_num <= 0:
                mes_num += 12
                ano -= 1
            mes = OverviewService.get_overview(
                db, user_id, date(ano, mes_num, 1), currency=destino
            )
            serie.append({
                "month": mes["month"],
                "income": mes["income"],
                "consumption": mes["consumption"],
                "result": mes["result"],
                "cash_in": mes["cash_in"],
                "cash_out": mes["cash_out"],
                "net_cash": mes["net_cash"],
            })
            for chave in totais:
                totais[chave] += mes[chave]
            excluidos += mes["excluded_foreign_count"]

            for linha in mes["by_workspace"]:
                acumulado = por_workspace.setdefault(linha["workspace_id"], {
                    "workspace_id": linha["workspace_id"],
                    "workspace_name": linha["workspace_name"],
                    "consumption": ZERO,
                })
                acumulado["consumption"] += linha["consumption"]

        participacao = sorted(
            por_workspace.values(), key=lambda w: w["consumption"], reverse=True
        )
        return {
            "currency": destino,
            "months": serie,
            "totals": totais,
            "by_workspace": participacao,
            "excluded_foreign_count": excluidos,
        }

    # ------------------------------------------------------------------
    @staticmethod
    def get_commitments(db: Session, user_id: int, currency: Optional[str] = None) -> Dict[str, Any]:
        """Compromissos financeiros da PESSOA, **separados por prazo**.

        O "Total a pagar" antigo somava a próxima fatura do cartão com o principal
        INTEIRO em aberto de cada financiamento. Um número que junta o que vence em
        cinco dias com o que vence em quinze anos não responde a nenhuma pergunta:
        não é o que preciso ter em caixa este mês nem o quanto devo ao todo.

        Os cinco números que substituem aquele um:

        | Campo                | Responde                                          |
        |----------------------|---------------------------------------------------|
        | `overdue`            | o que já venceu e não foi pago                    |
        | `due_this_month`     | o que preciso pagar ainda neste mês               |
        | `next_installments`  | o que vem nos próximos meses, parcela a parcela   |
        | `outstanding_total`  | o tamanho da dívida (principal em aberto + fatura)|
        | `monthly_commitment` | quanto do meu mês já está comprometido            |

        O recorte é `owner_user_id == eu`, sem passar por workspace nenhum
        (ADR 0021) — antes o filtro era `workspace_id.in_(meus workspaces)` E o
        dono, e sair de um workspace tirava o próprio cartão da lista.
        """
        destino = currency or OverviewService.report_currency(db, user_id)
        # UTC, a mesma referência de `CreditCardService.is_overdue`. Com
        # `date.today()` (local) as duas classificações discordavam no fim do dia
        # em fuso negativo: a fatura era "vencida" para uma e "vence neste mês"
        # para a outra, e o mesmo valor entrava nos dois totais.
        hoje = datetime.now(UTC).date()
        fim_do_mes = date(
            hoje.year, hoje.month, calendar.monthrange(hoje.year, hoje.month)[1]
        )
        excluidos = 0

        def _conv(valor: Decimal, de: str) -> Optional[Decimal]:
            return OverviewService._converte(db, valor, de, destino, hoje)

        # --- Faturas de cartão -------------------------------------------------
        cartoes = db.exec(
            select(CreditCard)
            .where(CreditCard.owner_user_id == user_id)
            .where(CreditCard.deleted_at.is_(None))
        ).all()
        faturas: List[Dict[str, Any]] = []
        vencido = ZERO
        vence_no_mes = ZERO
        saldo_devedor = ZERO
        for card in cartoes:
            overview = CreditCardService.card_overview(db, card)
            # TODA fatura não paga com valor, não só a "que pede atenção": duas
            # faturas em aberto (a vencida e a do ciclo) são duas obrigações.
            for stmt in overview["statements"]:
                if stmt.status == StatementStatus.paid:
                    continue
                valor = CreditCardService.effective_total(db, stmt)
                if valor <= ZERO:
                    continue
                convertido = _conv(valor, card.currency)
                if convertido is None:
                    excluidos += 1
                    continue
                atrasada = CreditCardService.is_overdue(stmt)
                vencimento = stmt.due_date.date() if hasattr(stmt.due_date, "date") else stmt.due_date
                saldo_devedor += convertido
                if atrasada:
                    vencido += convertido
                elif vencimento <= fim_do_mes:
                    vence_no_mes += convertido
                faturas.append({
                    "card_id": card.id,
                    "card_name": card.name,
                    "statement_id": stmt.id,
                    "month": stmt.month,
                    "due_date": stmt.due_date,
                    "amount": convertido,
                    "is_overdue": atrasada,
                })

        # --- Financiamentos ----------------------------------------------------
        financiamentos = db.exec(
            select(Financing)
            .where(Financing.owner_user_id == user_id)
            .where(Financing.deleted_at.is_(None))
            .where(Financing.status == FinancingStatus.active)
        ).all()
        fins: List[Dict[str, Any]] = []
        proximas: List[Dict[str, Any]] = []
        comprometimento = ZERO
        for fin in financiamentos:
            em_aberto = db.exec(
                select(AmortizationInstallment)
                .where(AmortizationInstallment.financing_id == fin.id)
                .where(AmortizationInstallment.is_paid.is_(False))
                .order_by(AmortizationInstallment.due_date)
            ).all()
            if not em_aberto:
                continue
            # Saldo devedor = PRINCIPAL em aberto (o que se deve hoje); a parcela
            # inclui juros, que são custo futuro e não dívida atual.
            saldo = _conv(sum((i.principal_amount for i in em_aberto), ZERO), fin.currency)
            if saldo is None:
                excluidos += 1
                continue
            saldo_devedor += saldo

            for parcela in em_aberto:
                valor = _conv(parcela.total_amount, fin.currency)
                if valor is None:
                    continue
                if parcela.due_date < hoje:
                    vencido += valor
                elif parcela.due_date <= fim_do_mes:
                    vence_no_mes += valor
                else:
                    proximas.append({
                        "financing_id": fin.id,
                        "title": fin.title,
                        "installment_number": parcela.installment_number,
                        "due_date": parcela.due_date,
                        "amount": valor,
                    })
            # Comprometimento mensal: a próxima parcela de cada financiamento ativo
            # é o que se repete todo mês.
            proxima = _conv(em_aberto[0].total_amount, fin.currency)
            if proxima is not None:
                comprometimento += proxima

            fins.append({
                "financing_id": fin.id,
                "title": fin.title,
                "outstanding": saldo,
                "next_due_date": em_aberto[0].due_date,
                "remaining_installments": len(em_aberto),
            })

        faturas.sort(key=lambda f: f["due_date"])
        fins.sort(key=lambda f: f["outstanding"], reverse=True)
        proximas.sort(key=lambda p: p["due_date"])

        return {
            "currency": destino,
            "cards": faturas,
            "financings": fins,
            "overdue": vencido,
            "due_this_month": vence_no_mes,
            # Teto para a tela não virar um extrato: o resto está em Financiamentos.
            "next_installments": proximas[:12],
            "outstanding_total": saldo_devedor,
            "monthly_commitment": comprometimento,
            "excluded_foreign_count": excluidos,
        }

    # ------------------------------------------------------------------
    @staticmethod
    def get_activity(db: Session, user_id: int, limit: int = 10) -> List[Dict[str, Any]]:
        """Lançamentos recentes em que a pessoa está ENVOLVIDA, em qualquer
        workspace — mesma definição de envolvimento da política (ADR 0018)."""
        workspaces = OverviewService._workspaces_do_usuario(db, user_id)
        ids = [ws.id for ws in workspaces]
        if not ids:
            return []
        nomes = {ws.id: ws.name for ws in workspaces}

        linhas = db.exec(
            select(Transaction)
            .where(Transaction.workspace_id.in_(ids))
            .where(Transaction.deleted_at.is_(None))
            .where(involvement_filter(user_id))
            .order_by(Transaction.transaction_date.desc())
            .limit(limit)
        ).all()

        # A PARTE DA PESSOA em cada linha. A lista mostrava só `total_amount` — o
        # valor cheio da despesa — numa tela chamada "Onde você está envolvido",
        # que é justamente sobre a participação. Num rateio 50/50, o jantar de 200
        # aparecia como 200 para quem consumiu 100.
        #
        # `None` (e não zero) quando não há split do usuário: ele pode estar ali
        # por ter criado ou pago a despesa sem consumir nada, e zero diria que a
        # parte dele é zero em vez de "não se aplica".
        minhas_partes = {}
        if linhas:
            minhas_partes = dict(db.exec(
                select(TransactionSplit.transaction_id, TransactionSplit.computed_amount)
                .where(TransactionSplit.transaction_id.in_([t.id for t in linhas]))
                .where(TransactionSplit.user_id == user_id)
            ).all())

        return [
            {
                "id": t.id,
                "workspace_id": t.workspace_id,
                "workspace_name": nomes.get(t.workspace_id, ""),
                "title": t.title,
                "total_amount": t.total_amount,
                "my_share": minhas_partes.get(t.id),
                "currency": t.currency,
                "transaction_date": t.transaction_date,
                "status": t.status,
            }
            for t in linhas
        ]
