"""Troca da moeda-base do workspace COM reconversão do histórico.

O problema que isto resolve: todo valor é persistido na moeda-base (moeda
estrangeira é convertida na ENTRADA — ADR 0006 revisitado), e toda agregação
filtra `currency == workspace.base_currency`. Trocar a moeda-base sem mexer nos
dados fazia **nenhuma linha casar o filtro**: dívidas, relatórios, faturas,
previsão e endividamento iam a zero de uma vez e o app parecia vazio.

Aqui a troca converte o histórico inteiro, cada linha pela taxa da SUA data
(`transaction_date`, `received_at`, `due_date`…). Duas garantias inegociáveis:

1. **Nenhum valor é convertido isoladamente numa estrutura composta.** Converter
   pagador por pagador e split por split com arredondamento independente
   quebraria `soma(pagadores) == total` e `soma(splits) == total` — exatamente os
   invariantes que o ADR 0001 existe para proteger. O total é convertido e a
   divisão é RATEADA em centavos inteiros sobre ele (`_allocate_proportional`),
   então as somas continuam fechando por construção.

2. **Tudo ou nada.** Falta de taxa em qualquer data aborta a operação inteira
   (`MissingRates`), antes de escrever qualquer coisa. Meia conversão deixaria o
   workspace num estado sem interpretação possível.

`plan_conversion` é o dry-run que a UI usa para avisar antes de confirmar.
"""
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from typing import Dict, List, Optional, Sequence

from sqlmodel import Session, select

from app.models.credit_card import CardStatement, CreditCard, StatementPayment
from app.models.estimate import MonthlyEstimate
from app.models.financing import AmortizationInstallment, Financing
from app.models.income import Income
from app.models.payment_account import PaymentAccount
from app.models.recurring import RecurringExpense, RecurringIncome
from app.models.settlement import Settlement
from app.models.transaction import (
    SplitMethod,
    Transaction,
    TransactionAdjustment,
    TransactionItem,
    TransactionItemShare,
    TransactionPayer,
    TransactionSplit,
)
from app.services.currency_service import ExchangeRateUnavailable
from app.services.exchange_rate_store import ExchangeRateStore
from app.services.transaction_service import _allocate_proportional, _cents


class MissingRates(Exception):
    """Faltou taxa para uma ou mais datas — a troca é abortada inteira."""

    def __init__(self, missing: Sequence[str]):
        self.missing = list(missing)
        super().__init__(
            "Sem taxa de câmbio para: " + ", ".join(self.missing[:10])
            + ("…" if len(self.missing) > 10 else "")
        )


@dataclass
class ConversionReport:
    """O que a troca converteu (ou converteria, no dry-run)."""
    from_currency: str
    to_currency: str
    transactions: int = 0
    incomes: int = 0
    settlements: int = 0
    cards: int = 0
    statements: int = 0
    financings: int = 0
    estimates: int = 0
    recurring: int = 0
    accounts: int = 0
    missing_rates: List[str] = field(default_factory=list)

    def as_dict(self) -> Dict:
        return {
            "from_currency": self.from_currency,
            "to_currency": self.to_currency,
            "transactions": self.transactions,
            "incomes": self.incomes,
            "settlements": self.settlements,
            "cards": self.cards,
            "statements": self.statements,
            "financings": self.financings,
            "estimates": self.estimates,
            "recurring": self.recurring,
            "accounts": self.accounts,
            "missing_rates": self.missing_rates,
        }


def _as_date(value) -> date:
    return value.date() if hasattr(value, "date") else value


class _FactorResolver:
    """Fator OLD→NEW na data pedida, com cache por dia.

    A taxa cruzada vem de `ExchangeRateStore.rate_between` — a MESMA fonte que o
    caminho de entrada (criar/editar lançamento) usa, para migrar e lançar nunca
    discordarem. Datas sem taxa são coletadas em `missing` em vez de levantar na
    hora: assim o dry-run devolve a LISTA inteira do que falta, não só a primeira
    falha.

    O cache por dia importa: um histórico de 3 anos tem ~1000 datas distintas e
    sem ele cada linha repetiria a consulta.
    """

    def __init__(self, db: Session, old: str, new: str, *, allow_fetch: bool):
        self.db = db
        self.old = old.upper()
        self.new = new.upper()
        self.allow_fetch = allow_fetch
        self._cache: Dict[date, Optional[Decimal]] = {}
        self.missing: List[str] = []

    def factor(self, on) -> Optional[Decimal]:
        on = _as_date(on)
        if on in self._cache:
            return self._cache[on]

        try:
            value, _source = ExchangeRateStore.rate_between(
                self.db, self.old, self.new, on, allow_fetch=self.allow_fetch
            )
        except ExchangeRateUnavailable as exc:
            self._cache[on] = None
            # A exceção carrega QUAL moeda faltou — é o que o operador precisa
            # para saber o que mandar o backfill buscar.
            label = f"{on.isoformat()} ({exc.currency})"
            if label not in self.missing:
                self.missing.append(label)
            return None

        self._cache[on] = value
        return value


def _convert(amount: Optional[Decimal], factor: Decimal) -> Optional[Decimal]:
    if amount is None:
        return None
    return (amount * factor).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _reallocate(rows, value_of, set_value, target_cents: int) -> None:
    """Distribui `target_cents` entre `rows` na proporção dos valores atuais.

    É o mesmo princípio do ADR 0001 (piso + resto de 1 centavo por vez): a soma
    das partes fecha o alvo EXATAMENTE, então nenhum invariante de divisão se
    perde no arredondamento.
    """
    if not rows:
        return
    weights = {i: _cents(value_of(r)) for i, r in enumerate(rows)}
    if sum(weights.values()) <= 0:
        # Sem pesos (divisão degenerada): rateio igual defensivo
        weights = {i: 1 for i in range(len(rows))}
    alloc = _allocate_proportional(target_cents, weights)
    for i, row in enumerate(rows):
        set_value(row, Decimal(alloc[i]) / Decimal("100"))


class BaseCurrencyService:
    @staticmethod
    def plan_conversion(db: Session, workspace_id: int, new_currency: str) -> ConversionReport:
        """Dry-run: conta o que seria convertido e QUE TAXAS FALTAM. Não escreve."""
        return BaseCurrencyService._run(db, workspace_id, new_currency, apply=False)

    @staticmethod
    def convert_workspace(db: Session, workspace_id: int, new_currency: str) -> ConversionReport:
        """Converte o histórico inteiro. Levanta MissingRates ANTES de escrever.
        Não faz commit (ADR 0010): quem chama comanda a transação."""
        return BaseCurrencyService._run(db, workspace_id, new_currency, apply=True)

    # ---- implementação -----------------------------------------------------

    @staticmethod
    def _run(db: Session, workspace_id: int, new_currency: str, *, apply: bool) -> ConversionReport:
        from app.models.workspace import Workspace

        workspace = db.get(Workspace, workspace_id)
        old_currency = (workspace.base_currency if workspace else "BRL") or "BRL"
        new_currency = new_currency.upper()
        report = ConversionReport(from_currency=old_currency, to_currency=new_currency)
        if old_currency == new_currency:
            return report

        # allow_fetch=False nos DOIS modos: a conversão precisa de uma taxa por
        # data distinta do histórico. Buscar on-line aqui faria centenas de
        # requisições externas dentro de um PUT — o mesmo defeito que tiramos do
        # caminho de leitura. O store é a fonte; o que faltar vira MissingRates e
        # o operador roda `scripts/backfill_rates.py` antes de tentar de novo.
        resolver = _FactorResolver(db, old_currency, new_currency, allow_fetch=False)
        today = date.today()

        # Passo 1: resolver TODOS os fatores primeiro. Se faltar taxa, nada é
        # escrito — meia conversão deixaria o workspace sem interpretação.
        work = BaseCurrencyService._collect(db, workspace_id, old_currency, resolver, today)

        report.missing_rates = resolver.missing
        if resolver.missing:
            if apply:
                raise MissingRates(resolver.missing)
            return BaseCurrencyService._count(work, report)

        if not apply:
            return BaseCurrencyService._count(work, report)

        BaseCurrencyService._apply(db, work, new_currency)
        return BaseCurrencyService._count(work, report)

    @staticmethod
    def _collect(db, workspace_id, old_currency, resolver, today) -> Dict:
        """Carrega as linhas na moeda-base atual e resolve o fator de cada uma."""
        txs = db.exec(
            select(Transaction)
            .where(Transaction.workspace_id == workspace_id)
            .where(Transaction.currency == old_currency)
        ).all()
        tx_pairs = [(t, resolver.factor(t.transaction_date)) for t in txs]

        incomes = db.exec(
            select(Income)
            .where(Income.workspace_id == workspace_id)
            .where(Income.currency == old_currency)
        ).all()
        income_pairs = [(i, resolver.factor(i.received_at)) for i in incomes]

        settlements = db.exec(
            select(Settlement).where(Settlement.workspace_id == workspace_id)
        ).all()
        settlement_pairs = [(s, resolver.factor(s.settled_at)) for s in settlements]

        cards = db.exec(
            select(CreditCard)
            .where(CreditCard.workspace_id == workspace_id)
            .where(CreditCard.currency == old_currency)
        ).all()
        # Limite do cartão não tem data própria: usa a taxa de hoje
        card_pairs = [(c, resolver.factor(today)) for c in cards]

        card_ids = [c.id for c in cards]
        statements = []
        if card_ids:
            statements = db.exec(
                select(CardStatement).where(CardStatement.card_id.in_(card_ids))
            ).all()
        statement_pairs = [(s, resolver.factor(s.closing_date)) for s in statements]

        payments = db.exec(
            select(StatementPayment).where(StatementPayment.workspace_id == workspace_id)
        ).all()
        payment_pairs = [(p, resolver.factor(p.paid_at)) for p in payments]

        financings = db.exec(
            select(Financing)
            .where(Financing.workspace_id == workspace_id)
            .where(Financing.currency == old_currency)
        ).all()
        fin_pairs = [(f, resolver.factor(f.start_date)) for f in financings]
        fin_ids = [f.id for f in financings]
        installments = []
        if fin_ids:
            installments = db.exec(
                select(AmortizationInstallment)
                .where(AmortizationInstallment.financing_id.in_(fin_ids))
            ).all()
        inst_pairs = [(i, resolver.factor(i.due_date)) for i in installments]

        estimates = db.exec(
            select(MonthlyEstimate)
            .where(MonthlyEstimate.workspace_id == workspace_id)
        ).all()
        est_pairs = []
        for e in estimates:
            try:
                year, month = e.month.split("-")
                ref = date(int(year), int(month), 1)
            except (ValueError, AttributeError):
                ref = today
            est_pairs.append((e, resolver.factor(ref)))

        rec_exp = db.exec(
            select(RecurringExpense)
            .where(RecurringExpense.workspace_id == workspace_id)
            .where(RecurringExpense.currency == old_currency)
        ).all()
        rec_inc = db.exec(
            select(RecurringIncome)
            .where(RecurringIncome.workspace_id == workspace_id)
            .where(RecurringIncome.currency == old_currency)
        ).all()
        # Template não tem data de ocorrência: converte pela taxa de hoje
        rec_pairs = [(r, resolver.factor(today)) for r in list(rec_exp) + list(rec_inc)]

        # Conta de pagamento não guarda saldo — só o RÓTULO da moeda. Ficava para
        # trás na troca: a criação respeita `resolve_currency` (nasce na base) mas
        # a migração não mexia nela, então a conta seguia dizendo "BRL" numa tela
        # em que todo o resto já estava na moeda nova.
        accounts = db.exec(
            select(PaymentAccount)
            .where(PaymentAccount.workspace_id == workspace_id)
            .where(PaymentAccount.currency == old_currency)
        ).all()

        return {
            "transactions": tx_pairs,
            "incomes": income_pairs,
            "settlements": settlement_pairs,
            "cards": card_pairs,
            "statements": statement_pairs,
            "payments": payment_pairs,
            "financings": fin_pairs,
            "installments": inst_pairs,
            "estimates": est_pairs,
            "recurring": rec_pairs,
            "accounts": list(accounts),
        }

    @staticmethod
    def _count(work: Dict, report: ConversionReport) -> ConversionReport:
        report.transactions = len(work["transactions"])
        report.incomes = len(work["incomes"])
        report.settlements = len(work["settlements"])
        report.cards = len(work["cards"])
        report.statements = len(work["statements"])
        report.financings = len(work["financings"])
        report.estimates = len(work["estimates"])
        report.recurring = len(work["recurring"])
        report.accounts = len(work["accounts"])
        return report

    @staticmethod
    def _apply(db: Session, work: Dict, new_currency: str) -> None:
        for tx, factor in work["transactions"]:
            BaseCurrencyService._convert_transaction(db, tx, factor, new_currency)

        for income, factor in work["incomes"]:
            # Lançamento cuja proveniência JÁ era a nova moeda volta ao valor
            # original exato — round-trip sem perda de centavo.
            if income.original_currency == new_currency and income.original_amount is not None:
                income.amount = income.original_amount
                income.original_amount = None
                income.original_currency = None
                income.exchange_rate = None
                income.rate_source = None
            else:
                income.amount = _convert(income.amount, factor)
            income.currency = new_currency
            db.add(income)

        for settlement, factor in work["settlements"]:
            settlement.amount = _convert(settlement.amount, factor)
            db.add(settlement)

        for card, factor in work["cards"]:
            card.limit = _convert(card.limit, factor)
            card.currency = new_currency
            db.add(card)

        for statement, factor in work["statements"]:
            statement.total_amount = _convert(statement.total_amount, factor)
            db.add(statement)

        for payment, factor in work["payments"]:
            payment.amount = _convert(payment.amount, factor)
            db.add(payment)

        for financing, factor in work["financings"]:
            financing.total_amount = _convert(financing.total_amount, factor)
            financing.currency = new_currency
            db.add(financing)

        for inst, factor in work["installments"]:
            # Invariante da parcela: principal + juros == total. Converter as três
            # colunas isoladamente quebraria isso no arredondamento, então o total
            # é convertido e as duas partes são rateadas sobre ele.
            new_total = _convert(inst.total_amount, factor)
            weights = {0: _cents(inst.principal_amount), 1: _cents(inst.interest_amount)}
            if sum(weights.values()) <= 0:
                inst.principal_amount = new_total
                inst.interest_amount = Decimal("0.00")
            else:
                alloc = _allocate_proportional(_cents(new_total), weights)
                inst.principal_amount = Decimal(alloc[0]) / Decimal("100")
                inst.interest_amount = Decimal(alloc[1]) / Decimal("100")
            inst.total_amount = new_total
            inst.remaining_balance = _convert(inst.remaining_balance, factor)
            db.add(inst)

        for estimate, factor in work["estimates"]:
            estimate.amount = _convert(estimate.amount, factor)
            db.add(estimate)

        for template, factor in work["recurring"]:
            template.base_amount = _convert(template.base_amount, factor)
            template.currency = new_currency
            db.add(template)

        # Conta não tem valor a converter — só o rótulo acompanha a base
        for account in work["accounts"]:
            account.currency = new_currency
            db.add(account)

    @staticmethod
    def _convert_transaction(db: Session, tx: Transaction, factor: Decimal, new_currency: str) -> None:
        """Converte o total e RATEIA a divisão sobre ele (nunca converte peça a peça)."""
        if tx.original_currency == new_currency and tx.original_amount is not None:
            # A proveniência congelada já estava na moeda de destino: volta ao
            # valor original exato e a proveniência deixa de fazer sentido.
            new_total = tx.original_amount
            tx.original_amount = None
            tx.original_currency = None
            tx.exchange_rate = None
            tx.iof_rate = None
            tx.rate_source = None
        else:
            new_total = _convert(tx.total_amount, factor)

        total_cents = _cents(new_total)
        tx.total_amount = new_total
        tx.currency = new_currency
        db.add(tx)

        payers = db.exec(
            select(TransactionPayer).where(TransactionPayer.transaction_id == tx.id)
        ).all()
        _reallocate(payers, lambda p: p.amount, _set_payer_amount, total_cents)
        for p in payers:
            db.add(p)

        adjustments = db.exec(
            select(TransactionAdjustment).where(TransactionAdjustment.transaction_id == tx.id)
        ).all()
        adj_cents = 0
        for adj in adjustments:
            adj.amount = _convert(adj.amount, factor)
            adj_cents += _cents(adj.amount)
            db.add(adj)

        items = db.exec(
            select(TransactionItem)
            .where(TransactionItem.transaction_id == tx.id)
            .order_by(TransactionItem.position)
        ).all()
        if items:
            # Itens somam (total − ajustes): a mesma reconciliação do create
            _reallocate(items, lambda i: i.amount, _set_item_amount, total_cents - adj_cents)
            for item in items:
                # quantity × unitário deixa de fechar após a conversão (a fatia
                # convertida raramente é múltipla exata da quantidade), então a
                # linha é normalizada para 1 × valor-da-linha. O `amount` que
                # `_reallocate` acabou de gravar é a fonte de verdade e NÃO pode
                # ser recalculado a partir do unitário: dividi-lo pela quantidade
                # encolhia o item (3 × 10 virava o preço de UM), quebrando
                # `soma(itens) + ajustes == total` e o rateio das shares abaixo.
                if item.unit_amount is not None and item.quantity:
                    item.unit_amount = item.amount
                    item.quantity = Decimal("1")
                db.add(item)

                shares = db.exec(
                    select(TransactionItemShare).where(TransactionItemShare.item_id == item.id)
                ).all()
                _reallocate(shares, lambda s: s.computed_amount, _set_share_amount, _cents(item.amount))
                for share in shares:
                    if share.split_method == SplitMethod.fixed:
                        share.input_value = share.computed_amount
                    db.add(share)

        splits = db.exec(
            select(TransactionSplit).where(TransactionSplit.transaction_id == tx.id)
        ).all()
        _reallocate(splits, lambda s: s.computed_amount, _set_split_amount, total_cents)
        for split in splits:
            # equal/percentage são escala-invariantes: input_value não muda
            if split.split_method == SplitMethod.fixed:
                split.input_value = split.computed_amount
            db.add(split)


def _set_payer_amount(row, value: Decimal) -> None:
    row.amount = value


def _set_item_amount(row, value: Decimal) -> None:
    row.amount = value


def _set_share_amount(row, value: Decimal) -> None:
    row.computed_amount = value


def _set_split_amount(row, value: Decimal) -> None:
    row.computed_amount = value
