import calendar
from datetime import date, datetime, timedelta, UTC
from decimal import Decimal, ROUND_HALF_UP
from typing import List, Optional, Tuple

import structlog
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.core.config import settings
from app.domain.query_policy import workspace_base_currency
from app.models.category import Category
from app.models.credit_card import CreditCard
from app.models.income import Income
from app.models.recurring import RecurringExpense, RecurringIncome, RecurrenceFrequency
from app.models.transaction import (
    Transaction,
    TransactionItem,
    TransactionStatus,
    SplitMethod,
    SplitMode,
    PaymentMethod,
)
from app.schemas.transaction import TransactionPayerBase, TransactionSplitBase
from app.services.credit_card_service import CreditCardService
from app.services.transaction_service import (
    persist_transaction_children,
    delete_transaction_children,
    convert_division_to_base,
)
from app.services.currency_service import ExchangeRateUnavailable
from app.services.exchange_rate_store import ExchangeRateStore

logger = structlog.get_logger("app.recurring")

# Escopo da edição de um template sobre as instâncias já materializadas
EDIT_SCOPES = ("none", "future", "all")

# Escopo da MATERIALIZAÇÃO quando o template começa numa data retroativa:
# past = gera desde o mês da start_date; current = só o mês corrente (padrão);
# future = nem o mês corrente (empurra start_date para a próxima ocorrência).
MATERIALIZE_SCOPES = ("past", "current", "future")

# Teto de meses que um backfill retroativo pode criar de uma vez
BACKFILL_MAX_MONTHS = 24


def _iter_months(start: date, end: date, limit: int = BACKFILL_MAX_MONTHS):
    """(ano, mês) de `start` até `end` inclusive, do mais antigo ao mais novo."""
    out: List[Tuple[int, int]] = []
    y, m = start.year, start.month
    while (y, m) <= (end.year, end.month) and len(out) < limit:
        out.append((y, m))
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def _first_occurrence_after(template, ref: date, horizon: int = 36) -> Optional[date]:
    """1ª ocorrência depois do mês de `ref`.

    Usada por scope='future': vira a nova start_date. Como a data devolvida É uma
    ocorrência da série antiga, a fase de "a cada N" (ancorada em start_date)
    fica preservada — não basta usar "dia 1 do mês que vem".
    """
    y, m = (ref.year + 1, 1) if ref.month == 12 else (ref.year, ref.month + 1)
    for _ in range(horizon):
        for occ in RecurringService.occurrences_in_month(template, y, m):
            if occ > ref:
                return occ
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return None


def _statement_for(db: Session, template: RecurringExpense, occ: date) -> Optional[int]:
    """Fatura da ocorrência quando o template está preso a um cartão.

    Sem isto a assinatura no cartão nascia fora de qualquer fatura: aparecia no
    extrato mas não no statement nem no limite comprometido. Cada ocorrência é
    roteada pela SUA data — dezembro cai na fatura de dezembro (ADR 0002).
    """
    if template.credit_card_id is None:
        return None
    card = db.get(CreditCard, template.credit_card_id)
    if not card or card.workspace_id != template.workspace_id or card.deleted_at:
        return None
    statement = CreditCardService.get_or_create_statement(
        db, card, datetime(occ.year, occ.month, occ.day, tzinfo=UTC)
    )
    return statement.id


def _recurring_conversion(
    db, workspace_id, base_amount, currency, occ_date, payment_method, *, allow_fetch=True
):
    """Converte o valor de um template recorrente para a moeda-base (BRL) na data
    da OCORRÊNCIA — cada materialização usa a taxa daquele dia (recorrência
    estrangeira re-converte todo mês). IOF só em despesa no cartão (renda não tem).
    Devolve (brl, rate, iof, source, factor); rate=None se já for base.

    `allow_fetch=False` proíbe ir à rede: é o modo do caminho de LEITURA, onde
    uma busca de cotação bloquearia o GET (ver ExchangeRateStore.get_or_fetch)."""
    base = workspace_base_currency(db, workspace_id)
    if not currency or currency == base:
        return base_amount, None, Decimal("0"), None, Decimal("1")
    rate, source = ExchangeRateStore.get_or_fetch(
        db, currency, occ_date, allow_fetch=allow_fetch
    )
    iof = (
        settings.IOF_INTERNATIONAL_CARD_RATE
        if payment_method in (PaymentMethod.credit_card, PaymentMethod.debit_card)
        else Decimal("0")
    )
    factor = rate * (Decimal("1") + iof)
    brl = (base_amount * factor).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return brl, rate, iof, source, factor


class RecurringService:
    @staticmethod
    def occurrences_in_month(template, year: int, month: int) -> List[date]:
        """Datas em que o template ocorre no mês.

        interval == 1 → preset "phase-free" (legado): diário = todo dia; semanal =
        day_of_week; mensal = day_of_month; anual = month_of_year + day_of_month.
        interval > 1 → "a cada N períodos" ancorado em start_date (fallback
        created_at): o dia/semana/mês/ano deriva da âncora. Serve tanto
        RecurringExpense quanto RecurringIncome (duck typing dos mesmos campos).
        """
        last_day = calendar.monthrange(year, month)[1]
        interval = getattr(template, "interval", 1) or 1

        if interval > 1:
            return RecurringService._interval_occurrences(template, year, month, interval, last_day)

        if template.frequency == RecurrenceFrequency.daily:
            occs = [date(year, month, day) for day in range(1, last_day + 1)]
        elif template.frequency == RecurrenceFrequency.weekly:
            occs = (
                []
                if template.day_of_week is None
                else [
                    date(year, month, day)
                    for day in range(1, last_day + 1)
                    if date(year, month, day).weekday() == template.day_of_week
                ]
            )
        elif template.frequency == RecurrenceFrequency.yearly and template.month_of_year != month:
            occs = []
        else:
            # monthly (e yearly no mês certo): dia limitado ao fim do mês
            occs = [date(year, month, min(template.day_of_month, last_day))]

        # Piso: a recorrência (preset) só vale a partir de start_date, quando
        # definido. Templates antigos têm start_date=None → filtro é no-op.
        start = getattr(template, "start_date", None)
        if start is not None:
            occs = [o for o in occs if o >= start]
        return occs

    @staticmethod
    def _interval_occurrences(template, year: int, month: int, interval: int, last_day: int) -> List[date]:
        """Ocorrências de "a cada N períodos" no mês, ancoradas em start_date."""
        anchor = getattr(template, "start_date", None)
        if anchor is None:
            created = getattr(template, "created_at", None)
            anchor = created.date() if created is not None else date(year, month, 1)

        month_start = date(year, month, 1)
        month_end = date(year, month, last_day)
        if anchor > month_end:
            return []

        freq = template.frequency

        # Diário/semanal: passo fixo em dias a partir da âncora
        if freq in (RecurrenceFrequency.daily, RecurrenceFrequency.weekly):
            step = interval if freq == RecurrenceFrequency.daily else interval * 7
            if anchor >= month_start:
                first = anchor
            else:
                gap = (month_start - anchor).days
                k = -(-gap // step)  # ceil(gap/step): 1ª ocorrência >= início do mês
                first = anchor + timedelta(days=k * step)
            out: List[date] = []
            d = first
            while d <= month_end:
                out.append(d)
                d += timedelta(days=step)
            return out

        # Mensal: mesmo dia da âncora, a cada N meses alinhados à âncora
        if freq == RecurrenceFrequency.monthly:
            anchor_mi = anchor.year * 12 + (anchor.month - 1)
            target_mi = year * 12 + (month - 1)
            if target_mi < anchor_mi or (target_mi - anchor_mi) % interval != 0:
                return []
            occ = date(year, month, min(anchor.day, last_day))
            return [occ] if occ >= anchor else []

        # Anual: mesmo mês/dia da âncora, a cada N anos alinhados à âncora
        if freq == RecurrenceFrequency.yearly:
            if month != anchor.month or year < anchor.year or (year - anchor.year) % interval != 0:
                return []
            occ = date(year, month, min(anchor.day, last_day))
            return [occ] if occ >= anchor else []

        return []

    # ---- Materialização COMPLETA (ADR 0012) ---------------------------------

    @staticmethod
    def _participants(
        template: RecurringExpense,
    ) -> Tuple[Optional[int], List[TransactionSplitBase]]:
        """Pagador + divisão a partir do snapshot; default = 100% ao pagador."""
        payer_user = template.payer_user_id or template.created_by_user_id
        if template.split_snapshot:
            splits = [
                TransactionSplitBase(
                    user_id=int(s["user_id"]),
                    split_method=SplitMethod(s.get("split_method", "equal")),
                    input_value=Decimal(str(s.get("input_value", "0"))),
                )
                for s in template.split_snapshot
            ]
        elif payer_user is not None:
            splits = [
                TransactionSplitBase(
                    user_id=payer_user, split_method=SplitMethod.equal, input_value=Decimal("0")
                )
            ]
        else:
            splits = []
        return payer_user, splits

    @staticmethod
    def _create_instance(
        db: Session,
        template: RecurringExpense,
        occ: date,
        billing_month: str,
        status: TransactionStatus = TransactionStatus.confirmed,
        *,
        allow_fetch: bool = True,
    ) -> Optional[Transaction]:
        """Cria a transação da ocorrência COMPLETA (pagador+divisão+categoria).

        Retorna None se não há pagador válido (template sem criador/pagador —
        cai no caminho legado nu, evitado na prática), se a divisão do snapshot
        for inválida (membro que saiu do workspace), ou se não houver taxa de
        câmbio disponível para a data (a ocorrência espera o backfill em vez de
        nascer com um valor inventado)."""
        # Moeda estrangeira: converte na data da ocorrência (re-converte todo mês)
        try:
            brl, rate, iof, source, factor = _recurring_conversion(
                db, template.workspace_id, template.base_amount, template.currency, occ,
                template.payment_method, allow_fetch=allow_fetch,
            )
        except ExchangeRateUnavailable:
            logger.warning(
                "recurring_skip_sem_taxa",
                template_id=template.id,
                workspace_id=template.workspace_id,
                currency=template.currency,
                occurrence=occ.isoformat(),
            )
            return None
        is_foreign = rate is not None
        base_currency = workspace_base_currency(db, template.workspace_id)

        tx = Transaction(
            title=template.title,
            description=template.description,
            total_amount=brl,
            currency=base_currency if is_foreign else template.currency,
            payment_method=template.payment_method,
            credit_card_id=template.credit_card_id,
            statement_id=_statement_for(db, template, occ),
            transaction_date=datetime(occ.year, occ.month, occ.day, tzinfo=UTC),
            billing_month=billing_month,
            occurrence_date=occ,
            workspace_id=template.workspace_id,
            created_by_user_id=template.created_by_user_id,
            recurring_expense_id=template.id,
            status=status,
            original_amount=template.base_amount if is_foreign else None,
            original_currency=template.currency if is_foreign else None,
            exchange_rate=rate if is_foreign else None,
            iof_rate=iof if is_foreign else None,
            rate_source=source if is_foreign else None,
        )
        db.add(tx)
        db.flush()

        payer_user, splits = RecurringService._participants(template)
        if payer_user is None or not splits:
            # Legado: sem pagador não dá para montar divisão — instância "nua"
            return tx

        payers = [TransactionPayerBase(user_id=payer_user, amount=brl)]
        if is_foreign:
            div = convert_division_to_base(factor=factor, brl_total=brl, payers=payers, splits=splits, items=None, adjustments=None)
            payers, splits = div["payers"], div["splits"]
        try:
            persist_transaction_children(
                db,
                template.workspace_id,
                tx,
                total_amount=brl,
                split_mode=SplitMode.transaction,
                payers=payers,
                splits=splits,
                items=None,
            )
        except ValueError:
            # Snapshot inválido (ex.: membro saiu): desiste desta ocorrência
            db.delete(tx)
            db.flush()
            return None

        RecurringService._apply_category(db, template, tx, amount=brl)
        return tx

    @staticmethod
    def _apply_category(
        db: Session, template: RecurringExpense, tx: Transaction, amount: Optional[Decimal] = None
    ) -> None:
        if template.category_id is None:
            return
        category = db.get(Category, template.category_id)
        if not category or category.workspace_id != template.workspace_id or category.deleted_at:
            return
        db.add(TransactionItem(
            transaction_id=tx.id,
            title=template.title,
            amount=amount if amount is not None else template.base_amount,
            category_id=template.category_id,
        ))

    @staticmethod
    def promote_due_instances(db: Session, workspace_id: int, today: date) -> int:
        """Vira para `confirmed` as instâncias recorrentes que nasceram `pending`
        (data futura) e cuja data já chegou.

        `pending` é estado de SISTEMA — a UI nunca o define, só o exibe — então
        promover é seguro: só reencontra o que esta própria materialização criou.
        Sem isso a conta do dia 30 ficaria fora dos totais realizados para sempre.
        """
        rows = db.exec(
            select(Transaction)
            .where(Transaction.workspace_id == workspace_id)
            .where(Transaction.recurring_expense_id.is_not(None))
            .where(Transaction.status == TransactionStatus.pending)
            .where(Transaction.deleted_at.is_(None))
            .where(Transaction.occurrence_date.is_not(None))
            .where(Transaction.occurrence_date <= today)
        ).all()
        for tx in rows:
            tx.status = TransactionStatus.confirmed
            db.add(tx)
        return len(rows)

    @staticmethod
    def generate_due_instances(
        db: Session, workspace_id: int, today: date, *, allow_fetch: bool = True
    ) -> int:
        """Materializa as instâncias do MÊS CORRENTE INTEIRO.

        Ocorrência já vencida (<= hoje) nasce `confirmed`; ocorrência ainda por
        vir no mês nasce `pending` — assim a conta do dia 30 já aparece como "a
        pagar" no dia 1, sem entrar em nenhum total realizado (`pending` está
        fora de REALIZED_STATUSES, então dívidas, relatórios e fatura não mudam).
        `promote_due_instances` vira para `confirmed` quando a data chega.

        Dedup por (recurring, occurrence_date) — a instância excluída deixa
        tombstone e não ressuscita. Não faz commit (ADR 0010).
        """
        billing_month = f"{today.year:04d}-{today.month:02d}"

        templates = db.exec(
            select(RecurringExpense)
            .where(RecurringExpense.workspace_id == workspace_id)
            .where(RecurringExpense.is_active.is_(True))
        ).all()
        if not templates:
            return 0

        # Inclui excluídas de propósito: tombstone bloqueia recriação
        existing = db.exec(
            select(Transaction.recurring_expense_id, Transaction.transaction_date)
            .where(Transaction.workspace_id == workspace_id)
            .where(Transaction.billing_month == billing_month)
            .where(Transaction.recurring_expense_id.is_not(None))
        ).all()
        existing_dates = {(rid, dt.date()) for rid, dt in existing}
        existing_templates = {rid for rid, _ in existing}

        per_occurrence = (RecurrenceFrequency.daily, RecurrenceFrequency.weekly)

        created = 0
        for template in templates:
            for occ in RecurringService.occurrences_in_month(template, today.year, today.month):
                if template.frequency in per_occurrence:
                    if (template.id, occ) in existing_dates:
                        continue
                elif template.id in existing_templates:
                    continue

                status = (
                    TransactionStatus.confirmed if occ <= today else TransactionStatus.pending
                )
                if RecurringService._create_instance_safe(
                    db, template, occ, billing_month, status, allow_fetch=allow_fetch
                ):
                    created += 1
        return created

    @staticmethod
    def _create_instance_safe(
        db: Session,
        template: RecurringExpense,
        occ: date,
        billing_month: str,
        status: TransactionStatus = TransactionStatus.confirmed,
        *,
        allow_fetch: bool = True,
    ) -> Optional[Transaction]:
        """`_create_instance` num savepoint, absorvendo a colisão de concorrência.

        O dedup dos chamadores é lê-depois-escreve e não sobrevive a duas
        requisições simultâneas — e a materialização roda a partir de ROTAS DE
        LEITURA. A unique `uq_recurring_occurrence` é a barreira real; aqui quem
        perde a corrida apenas desiste desta ocorrência, sem derrubar o lote nem
        virar 500.
        """
        try:
            with db.begin_nested():
                return RecurringService._create_instance(
                    db, template, occ, billing_month, status, allow_fetch=allow_fetch
                )
        except IntegrityError:
            return None

    @staticmethod
    def backfill_month(db: Session, template_id: int, year: int, month: int) -> int:
        """Materializa um mês PASSADO de um template (start_date retroativo).

        Mesmo dedup/tombstone da geração normal; mês passado nasce sempre
        `confirmed` (todas as ocorrências já venceram). Não faz commit.
        """
        template = db.get(RecurringExpense, template_id)
        if not template or not template.is_active:
            return 0
        billing_month = f"{year:04d}-{month:02d}"

        existing = db.exec(
            select(Transaction.transaction_date)
            .where(Transaction.recurring_expense_id == template_id)
            .where(Transaction.billing_month == billing_month)
        ).all()
        if existing and template.frequency not in (
            RecurrenceFrequency.daily, RecurrenceFrequency.weekly
        ):
            return 0
        existing_dates = {dt.date() for dt in existing}

        created = 0
        for occ in RecurringService.occurrences_in_month(template, year, month):
            if occ in existing_dates:
                continue
            if RecurringService._create_instance_safe(
                db, template, occ, billing_month, TransactionStatus.confirmed
            ):
                created += 1
        return created

    @staticmethod
    def get_or_create_monthly_instance(
        db: Session, template_id: int, year: int, month: int
    ) -> Optional[Transaction]:
        """Instância do mês para a despesa recorrente (materialização completa).
        Instância excluída (tombstone) NÃO ressuscita: retorna None."""
        billing_month = f"{year:04d}-{month:02d}"

        existing_tx = db.exec(
            select(Transaction)
            .where(Transaction.recurring_expense_id == template_id)
            .where(Transaction.billing_month == billing_month)
        ).first()
        if existing_tx:
            return None if existing_tx.deleted_at is not None else existing_tx

        template = db.get(RecurringExpense, template_id)
        if not template or not template.is_active:
            raise ValueError("Despesa recorrente não encontrada ou inativa")

        last_day = calendar.monthrange(year, month)[1]
        occ = date(year, month, min(template.day_of_month, last_day))
        return RecurringService._create_instance(db, template, occ, billing_month)

    @staticmethod
    def sync_unpaid_instances(db: Session, template_id: int, scope: str = "future"):
        """Reaplica o template às instâncias NÃO pagas (título, valor, divisão,
        categoria), recriando os filhos para manter as somas consistentes.

        scope: 'none' (nada), 'future' (mês corrente em diante), 'all' (todas
        as não pagas). Pagas/canceladas ficam congeladas.
        """
        if scope == "none":
            return
        template = db.get(RecurringExpense, template_id)
        if not template:
            return

        stmt = (
            select(Transaction)
            .where(Transaction.recurring_expense_id == template_id)
            .where(Transaction.status.in_([
                TransactionStatus.draft, TransactionStatus.pending, TransactionStatus.confirmed,
            ]))
            .where(Transaction.deleted_at.is_(None))
        )
        if scope == "future":
            today = date.today()
            stmt = stmt.where(Transaction.billing_month >= f"{today.year:04d}-{today.month:02d}")

        unpaid_txs = db.exec(stmt).all()
        if not unpaid_txs:
            return

        payer_user, splits = RecurringService._participants(template)
        base_currency = workspace_base_currency(db, template.workspace_id)
        for tx in unpaid_txs:
            # Re-converte cada instância na SUA data (meses diferentes, taxas diferentes)
            occ = tx.transaction_date.date() if hasattr(tx.transaction_date, "date") else tx.transaction_date
            brl, rate, iof, source, factor = _recurring_conversion(
                db, template.workspace_id, template.base_amount, template.currency, occ, template.payment_method
            )
            is_foreign = rate is not None
            tx.title = template.title
            tx.description = template.description
            tx.total_amount = brl
            tx.currency = base_currency if is_foreign else template.currency
            tx.payment_method = template.payment_method
            # Trocar o cartão do template re-roteia a fatura das instâncias não
            # pagas; tirar o cartão as solta do statement.
            tx.credit_card_id = template.credit_card_id
            tx.statement_id = _statement_for(db, template, occ)
            tx.original_amount = template.base_amount if is_foreign else None
            tx.original_currency = template.currency if is_foreign else None
            tx.exchange_rate = rate if is_foreign else None
            tx.iof_rate = iof if is_foreign else None
            tx.rate_source = source if is_foreign else None
            db.add(tx)
            # Recria os filhos no valor novo (senão payer/split divergem do total)
            if payer_user is not None and splits:
                delete_transaction_children(db, tx.id)
                p = [TransactionPayerBase(user_id=payer_user, amount=brl)]
                s = splits
                if is_foreign:
                    div = convert_division_to_base(factor=factor, brl_total=brl, payers=p, splits=s, items=None, adjustments=None)
                    p, s = div["payers"], div["splits"]
                try:
                    persist_transaction_children(
                        db,
                        template.workspace_id,
                        tx,
                        total_amount=brl,
                        split_mode=SplitMode.transaction,
                        payers=p,
                        splits=s,
                        items=None,
                    )
                except ValueError:
                    pass
                RecurringService._apply_category(db, template, tx, amount=brl)
        db.flush()


class RecurringIncomeService:
    """Materializa rendas recorrentes em entradas Income mensais. Espelha
    RecurringService.generate_due_instances, mas renda não tem divisão/pagador —
    reusa RecurringService.occurrences_in_month para o calendário."""

    @staticmethod
    def generate_due_income(
        db: Session,
        workspace_id: int,
        today: date,
        *,
        year: Optional[int] = None,
        month: Optional[int] = None,
        template_id: Optional[int] = None,
        allow_fetch: bool = True,
    ) -> int:
        """Cria as rendas recorrentes do MÊS INTEIRO (não só as já vencidas).

        A renda de julho é renda de julho mesmo que o salário caia no dia 30:
        o app é de competência (billing_month), então esperar a data chegar fazia
        a receita do mês aparecer zerada até o fim do mês. Diferente da despesa,
        Income não tem status — a data futura em `received_at` já se explica
        sozinha na lista ("recebe 30/07").

        year/month materializam um mês específico (backfill retroativo);
        template_id restringe a um template. Dedup por (recurring_income,
        occurrence) — instância excluída deixa tombstone e não ressuscita.
        Não faz commit (ADR 0010).
        """
        year = year or today.year
        month = month or today.month
        billing_month = f"{year:04d}-{month:02d}"

        stmt = (
            select(RecurringIncome)
            .where(RecurringIncome.workspace_id == workspace_id)
            .where(RecurringIncome.is_active.is_(True))
        )
        if template_id is not None:
            stmt = stmt.where(RecurringIncome.id == template_id)
        templates = db.exec(stmt).all()
        if not templates:
            return 0

        # Inclui excluídas de propósito: tombstone bloqueia recriação
        existing = db.exec(
            select(Income.recurring_income_id, Income.received_at)
            .where(Income.workspace_id == workspace_id)
            .where(Income.billing_month == billing_month)
            .where(Income.recurring_income_id.is_not(None))
        ).all()
        existing_dates = {(rid, dt.date()) for rid, dt in existing}
        existing_templates = {rid for rid, _ in existing}

        per_occurrence = (RecurrenceFrequency.daily, RecurrenceFrequency.weekly)
        base_currency = workspace_base_currency(db, workspace_id)

        created = 0
        for template in templates:
            for occ in RecurringService.occurrences_in_month(template, year, month):
                if template.frequency in per_occurrence:
                    if (template.id, occ) in existing_dates:
                        continue
                elif template.id in existing_templates:
                    continue

                # Renda estrangeira: converte na data da ocorrência (sem IOF)
                try:
                    brl, rate, _iof, source, _factor = _recurring_conversion(
                        db, template.workspace_id, template.base_amount,
                        template.currency, occ, None, allow_fetch=allow_fetch,
                    )
                except ExchangeRateUnavailable:
                    # Sem taxa para a data: espera o backfill em vez de inventar valor
                    logger.warning(
                        "recurring_income_skip_sem_taxa",
                        template_id=template.id, workspace_id=workspace_id,
                        currency=template.currency, occurrence=occ.isoformat(),
                    )
                    continue
                is_foreign = rate is not None
                # Savepoint por ocorrência: o dedup acima é lê-depois-escreve e não
                # sobrevive a duas requisições simultâneas (a materialização roda em
                # ROTAS DE LEITURA). A unique uq_recurring_income_occurrence é a
                # barreira real; aqui só absorvemos a colisão de quem perdeu a corrida,
                # sem derrubar as demais ocorrências do lote.
                try:
                    with db.begin_nested():
                        db.add(Income(
                            title=template.title,
                            description=template.description,
                            amount=brl,
                            currency=base_currency if is_foreign else template.currency,
                            category=template.category,
                            received_at=datetime(occ.year, occ.month, occ.day, tzinfo=UTC),
                            workspace_id=template.workspace_id,
                            user_id=template.user_id,
                            recurring_income_id=template.id,
                            billing_month=billing_month,
                            original_amount=template.base_amount if is_foreign else None,
                            original_currency=template.currency if is_foreign else None,
                            exchange_rate=rate if is_foreign else None,
                            rate_source=source if is_foreign else None,
                        ))
                except IntegrityError:
                    # Outra requisição materializou esta mesma ocorrência primeiro
                    continue
                created += 1
        return created

    @staticmethod
    def sync_current_month_income(db: Session, template: RecurringIncome, today: date) -> None:
        """Reaplica título/valor/moeda/categoria à(s) entrada(s) Income do mês
        CORRENTE geradas por este template. Meses anteriores (fechados) ficam
        congelados — só o mês visualizado pra frente acompanha a edição. Não
        faz commit (ADR 0010)."""
        billing_month = f"{today.year:04d}-{today.month:02d}"
        rows = db.exec(
            select(Income)
            .where(Income.recurring_income_id == template.id)
            .where(Income.billing_month == billing_month)
            .where(Income.deleted_at.is_(None))
        ).all()
        base_currency = workspace_base_currency(db, template.workspace_id)
        for inc in rows:
            occ = inc.received_at.date() if hasattr(inc.received_at, "date") else inc.received_at
            brl, rate, _iof, source, _factor = _recurring_conversion(
                db, template.workspace_id, template.base_amount, template.currency, occ, None
            )
            is_foreign = rate is not None
            inc.title = template.title
            inc.amount = brl
            inc.currency = base_currency if is_foreign else template.currency
            inc.category = template.category
            inc.original_amount = template.base_amount if is_foreign else None
            inc.original_currency = template.currency if is_foreign else None
            inc.exchange_rate = rate if is_foreign else None
            inc.rate_source = source if is_foreign else None
            db.add(inc)


class RecurringMaterializationService:
    """Materialização preguiçosa (lazy accrual) das recorrências vencidas do mês
    corrente. Chamada nas rotas de LEITURA (Início, Rendas, Lançamentos) para que
    tudo que é recorrente apareça sozinho, sem depender do botão "Lançar
    pendentes". Idempotente (dedup por tombstone) e restrita ao mês de `today`,
    então nunca cria retroativo em mês fechado."""

    @staticmethod
    def ensure_current_month(db: Session, workspace_id: int, today: date) -> dict:
        # allow_fetch=False: este é o caminho de LEITURA (GET). Buscar cotação
        # aqui bloqueava a resposta por até ~50s contra uma fonte externa.
        exp = RecurringService.generate_due_instances(
            db, workspace_id, today, allow_fetch=False
        )
        RecurringService.promote_due_instances(db, workspace_id, today)
        inc = RecurringIncomeService.generate_due_income(
            db, workspace_id, today, allow_fetch=False
        )
        return {"expenses": exp, "income": inc}

    # ---- Escopo retroativo (start_date no passado) ---------------------------

    @staticmethod
    def apply_scope(
        db: Session,
        workspace_id: int,
        template,
        scope: str,
        *,
        is_income: bool,
        today: Optional[date] = None,
    ) -> int:
        """Materializa o template conforme o escopo escolhido para start_date
        retroativa. Devolve quantas instâncias criou. Não faz commit (ADR 0010).

        past    → desde o mês da start_date até o corrente (teto de 24 meses)
        current → só o mês corrente (padrão; é o que a leitura preguiçosa faria)
        future  → nada agora, e empurra start_date para a próxima ocorrência,
                  senão a materialização preguiçosa recriaria o mês corrente
                  na primeira tela aberta.
        """
        today = today or date.today()
        if scope not in MATERIALIZE_SCOPES:
            raise ValueError(f"scope deve ser um de {list(MATERIALIZE_SCOPES)}")

        if scope == "future":
            nxt = _first_occurrence_after(template, date(today.year, today.month, 1))
            if nxt is not None:
                template.start_date = nxt
                db.add(template)
            return 0

        if scope == "current":
            months = [(today.year, today.month)]
        else:
            start = template.start_date or date(today.year, today.month, 1)
            months = _iter_months(start, today)

        created = 0
        for year, month in months:
            if is_income:
                created += RecurringIncomeService.generate_due_income(
                    db, workspace_id, today, year=year, month=month, template_id=template.id
                )
            elif (year, month) == (today.year, today.month):
                created += RecurringService.generate_due_instances(db, workspace_id, today)
            else:
                created += RecurringService.backfill_month(db, template.id, year, month)
        return created

    @staticmethod
    def ensure_and_commit(db: Session, workspace_id: int, today: Optional[date] = None) -> dict:
        """Conveniência para o caminho de leitura: materializa e comita. Best-effort
        — nunca propaga erro para não derrubar um GET (a materialização é acessória
        à resposta). Não emite eventos: o próprio refetch já traz os dados novos e
        publicar aqui provocaria tempestade de refetch (WS/seq)."""
        try:
            result = RecurringMaterializationService.ensure_current_month(
                db, workspace_id, today or date.today()
            )
            db.commit()
            return result
        except Exception:
            db.rollback()
            return {"expenses": 0, "income": 0}
