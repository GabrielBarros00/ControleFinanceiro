import calendar
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP
from types import SimpleNamespace
from typing import List, Optional, Tuple

import structlog
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, func, select

from fastapi import HTTPException

from app.core.config import settings
from app.domain.query_policy import BASE_CURRENCY, workspace_base_currency
from app.models.category import Category
from app.models.credit_card import (
    CardStatement,
    CreditCard,
    StatementPayment,
    StatementStatus,
)
from app.models.income import Income
from app.models.recurring import (
    RecurrenceFrequency,
    RecurringExpense,
    RecurringIncome,
)
from app.models.workspace import WorkspaceRole, role_level
from app.models.transaction import (
    Transaction,
    TransactionItem,
    TransactionStatus,
    SplitMethod,
    SplitMode,
    PaymentMethod,
)
from app.schemas.transaction import TransactionPayerBase, TransactionSplitBase
from app.services.base_conversion import apply_statement_leg
from app.services.credit_card_service import CreditCardService
from app.services.transaction_service import (
    persist_transaction_children,
    delete_transaction_children,
    convert_division_to_base,
)
from app.services.currency_service import ExchangeRateUnavailable
from app.services.exchange_rate_store import ExchangeRateStore
from app.domain.dates import civil_instant, local_day, today_local
from app.domain.settlement import resolve_settled_at

logger = structlog.get_logger("app.recurring")

# Escopo da edição de um template sobre as instâncias já materializadas
EDIT_SCOPES = ("none", "future", "all")

# Escopo da MATERIALIZAÇÃO quando o template começa numa data retroativa:
# past = gera desde o mês da start_date; current = só o mês corrente (padrão);
# future = nem o mês corrente (empurra start_date para a próxima ocorrência).
MATERIALIZE_SCOPES = ("past", "current", "future")

# Teto de meses que um backfill retroativo pode criar de uma vez
BACKFILL_MAX_MONTHS = 24


def _ate_o_fim(template, occs: List[date]) -> List[date]:
    """Teto da série: nada depois de `end_date` (ADR 0030).

    Espelho exato do piso de `start_date`, e aplicado nos DOIS caminhos de
    `occurrences_in_month` — o preset e o "a cada N", que retorna antes. Aplicá-lo
    só num deles daria uma mensalidade que respeita o fim quando é mensal e o
    ignora quando é "a cada 2 meses".

    `getattr` com default porque a função também serve `RecurringIncome` e
    objetos de planejamento (`SimpleNamespace`), e um deles pode não ter o campo.
    """
    fim = getattr(template, "end_date", None)
    if fim is None:
        return occs
    return [o for o in occs if o <= fim]


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


def _statement_for(
    db: Session, template: RecurringExpense, occ: date
) -> Tuple[Optional[int], bool]:
    """Fatura da ocorrência quando o template está preso a um cartão.

    Sem isto a assinatura no cartão nascia fora de qualquer fatura: aparecia no
    extrato mas não no statement nem no limite comprometido. Cada ocorrência é
    roteada pela SUA data — dezembro cai na fatura de dezembro (ADR 0002).

    Devolve `(statement_id, criada_agora)`. O segundo item é o que autoriza
    `_descartar_fatura_vazia` a desfazer a fatura se a ocorrência for descartada
    logo em seguida — só se pode apagar o que esta chamada acabou de criar.
    """
    if template.credit_card_id is None:
        return None, False
    card = db.get(CreditCard, template.credit_card_id)
    # O gate é a PROPRIEDADE (ADR 0021): o cartão tem de ser de quem paga a
    # recorrência — o pagador declarado, ou quem a cadastrou quando não há um.
    # A checagem antiga era `card.workspace_id != template.workspace_id`.
    dono_esperado = template.payer_user_id or template.created_by_user_id
    if not card or card.deleted_at or card.owner_user_id != dono_esperado:
        # A ocorrência ainda nasce — o gasto existe —, mas FORA de qualquer
        # fatura: não entra no limite comprometido nem no total do cartão. A
        # rota de escrita já valida a propriedade (`api/routes/recurring.py`),
        # então chegar aqui significa que algo mudou depois (cartão apagado,
        # pagador trocado). Antes isso era um `return None` mudo, e a fatura
        # simplesmente não fechava com o extrato sem nenhum rastro.
        logger.warning(
            "recorrencia.sem_fatura",
            recurring_id=template.id,
            credit_card_id=template.credit_card_id,
            dono_esperado=dono_esperado,
            motivo="cartão inexistente, apagado ou de outra pessoa",
        )
        return None, False
    # `occ` direto: a ocorrência JÁ é um dia de calendário. Embrulhá-la em
    # meia-noite UTC a transformava num instante que, lido no fuso do app, é o
    # dia ANTERIOR — a ocorrência do dia de fechamento ia para a fatura errada.
    #
    # `strict_shift=False` (ADR 0032): esta função roda dentro da materialização
    # PREGUIÇOSA, que é disparada por rotas de LEITURA. Um deslocamento
    # inalcançável — a fatura de destino já fechou — não pode virar 409 num GET
    # de extrato; a ocorrência cai no alvo natural, que é o mesmo tratamento que
    # o cartão apagado já recebe logo acima. Quem escreve (formulário, edição)
    # continua estrito e recebe o erro na cara.
    statement, criada = CreditCardService.get_or_create_statement_tracked(
        db, card, occ, shift=template.statement_shift, strict_shift=False
    )
    return statement.id, criada


def _descartar_fatura_vazia(
    db: Session, statement_id: Optional[int], *, criada: bool
) -> None:
    """Desfaz a fatura que uma ocorrência DESCARTADA acabou de criar.

    `_statement_for` roda antes de a ocorrência estar garantida, e
    `get_or_create_statement` já faz `add` + `flush`. Quando a ocorrência é
    descartada depois disso (sem cotação para a perna de fatura, snapshot de
    divisão inválido), a fatura fica pendurada na sessão — e o `commit` do LOTE,
    disparado por qualquer outra ocorrência que tenha dado certo, a confirma. O
    resultado é uma fatura aberta e vazia no cartão, que não altera valor nenhum
    mas suja a navegação e sugere um gasto que não existe.

    Duas travas, porque o `DELETE` aqui é FÍSICO e as duas faltavam:

    1. **`criada`** — só se apaga a fatura que ESTA materialização acabou de
       criar. Fatura vazia e aberta não é sinônimo de lixo: quem abre a tela do
       cartão faz `ensure_current_statement` criar a do ciclo corrente de
       propósito, justamente para o mês sem gastos não exibir a fatura do mês
       passado como se fosse a atual. Pelos critérios de conteúdo ela é
       indistinguível do que se quer apagar aqui.
    2. **Referência é referência, viva ou não.** As duas consultas filtravam por
       `deleted_at IS NULL`, e lançamento excluído é SOFT: continua no banco com
       o `statement_id` preenchido. Bastava alguém criar uma compra no cartão e
       excluí-la para a fatura parecer vazia enquanto ainda era apontada. No
       Postgres a FK barra o `DELETE` (`ForeignKeyViolation`, absorvida lá em
       cima como se fosse colisão de concorrência); no SQLite, que roda sem
       `PRAGMA foreign_keys`, ele PASSA — apaga uma fatura legítima e deixa o
       `statement_id` da linha excluída apontando para o nada.

    Só há duas FKs para `cardstatement` (`Transaction.statement_id` e
    `StatementPayment.statement_id`), e são exatamente estas duas consultas.
    """
    if statement_id is None or not criada:
        return
    statement = db.get(CardStatement, statement_id)
    if statement is None or statement.status != StatementStatus.open:
        return
    tem_linha = db.exec(
        select(Transaction.id)
        .where(Transaction.statement_id == statement_id)
        .limit(1)
    ).first()
    if tem_linha is not None:
        return
    tem_pagamento = db.exec(
        select(StatementPayment.id)
        .where(StatementPayment.statement_id == statement_id)
        .limit(1)
    ).first()
    if tem_pagamento is not None:
        return
    db.delete(statement)
    db.flush()


def _moeda_do_usuario(db, user_id: int) -> str:
    """Moeda de relatório do usuário — destino de conversão do que é PESSOAL.

    O que pertence à pessoa não tem workspace de onde herdar a moeda-base, e usar
    a base de quem por acaso disparou a leitura faria o MESMO salário valer números
    diferentes conforme a tela aberta (ADR 0019).
    """
    from app.models.user import User

    usuario = db.get(User, user_id)
    return (usuario.report_currency if usuario and usuario.report_currency else BASE_CURRENCY)


def _conversao_para(
    db, destino, base_amount, currency, occ_date, payment_method=None, *, allow_fetch=True
):
    """Converte para uma moeda de DESTINO qualquer na data da ocorrência.

    Núcleo compartilhado por `_recurring_conversion` (destino = base do workspace)
    e pela materialização de renda pessoal (destino = moeda de relatório do dono).
    """
    if not currency or currency == destino:
        return base_amount, None, Decimal("0"), None, Decimal("1")
    # rate_between: a taxa precisa ser moeda→DESTINO, e o store só guarda X→BRL
    rate, source = ExchangeRateStore.rate_between(
        db, currency, destino, occ_date, allow_fetch=allow_fetch
    )
    iof = (
        settings.IOF_INTERNATIONAL_CARD_RATE
        if payment_method in (PaymentMethod.credit_card, PaymentMethod.debit_card)
        else Decimal("0")
    )
    factor = rate * (Decimal("1") + iof)
    converted = (base_amount * factor).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return converted, rate, iof, source, factor


def _recurring_conversion(
    db, workspace_id, base_amount, currency, occ_date, payment_method, *, allow_fetch=True
):
    """Converte o valor de um template recorrente para a MOEDA-BASE DO WORKSPACE
    na data da OCORRÊNCIA — cada materialização usa a taxa daquele dia
    (recorrência estrangeira re-converte todo mês). IOF só em despesa no cartão
    (renda não tem). Devolve (converted, rate, iof, source, factor); rate=None se
    já for base.

    `allow_fetch=False` proíbe ir à rede: é o modo do caminho de LEITURA, onde
    uma busca de cotação bloquearia o GET (ver ExchangeRateStore.get_or_fetch)."""
    return _conversao_para(
        db,
        workspace_base_currency(db, workspace_id),
        base_amount,
        currency,
        occ_date,
        payment_method,
        allow_fetch=allow_fetch,
    )


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
            return _ate_o_fim(
                template,
                RecurringService._interval_occurrences(
                    template, year, month, interval, last_day
                ),
            )

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
        return _ate_o_fim(template, occs)

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

    @staticmethod
    def count_occurrences(template, ate: Optional[date] = None) -> Optional[int]:
        """Quantas ocorrências a série tem até `ate` (padrão: `end_date`).

        `None` quando não há fim — série infinita não se conta, e devolver zero
        ali diria "acabou".

        Usada para o "87 de 144" da lista (ADR 0030) e para converter "por N
        ocorrências" em `end_date` no servidor. **É a mesma
        `occurrences_in_month` que a materialização usa** — contar com uma
        aritmética própria faria a promessa da tela ("faltam 87") divergir do que
        de fato será gerado no mês 88.

        Teto de `BACKFILL_MAX_MONTHS * 12` meses varridos: uma mensalidade de 12
        anos são 144 meses, e o limite protege contra um `end_date` absurdo
        (ano 9999) transformando a contagem numa varredura sem fim.
        """
        fim = ate or getattr(template, "end_date", None)
        if fim is None:
            return None
        inicio = getattr(template, "start_date", None) or fim
        teto = BACKFILL_MAX_MONTHS * 12
        meses = _iter_months(inicio, fim, limit=teto)
        # Varredura TRUNCADA devolve `None`, não um total parcial: uma série de
        # setenta anos exibiria "288 de 288" e diria que acabou. `None` já
        # significa "não sei contar" para quem lê (é a resposta da série sem
        # fim), e a tela omite o contador em vez de mentir.
        if len(meses) >= teto:
            return None
        return sum(
            len(RecurringService.occurrences_in_month(template, ano, mes))
            for ano, mes in meses
        )

    @staticmethod
    def end_date_after(template, ocorrencias: int) -> Optional[date]:
        """A data da N-ésima ocorrência — "por 144 vezes" vira `end_date`.

        A conversão mora no SERVIDOR de propósito: o cliente teria de reimplementar
        `occurrences_in_month` (com o "a cada N ancorado", o dia limitado ao fim
        do mês e o piso de `start_date`) para chegar à mesma data, e duas
        implementações da mesma aritmética divergem — é a lição do dedup por
        `occurrence_date`.

        `None` se a série acabar antes de `ocorrencias` dentro do horizonte.
        """
        if ocorrencias < 1:
            return None
        inicio = getattr(template, "start_date", None) or today_local()
        vistas = 0
        # Sem `end_date` ainda: varre a partir do início até achar a N-ésima.
        for ano, mes in _iter_months(
            inicio, date(inicio.year + 50, 12, 1), limit=BACKFILL_MAX_MONTHS * 25
        ):
            for occ in RecurringService.occurrences_in_month(template, ano, mes):
                vistas += 1
                if vistas == ocorrencias:
                    return occ
        return None

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
            converted, rate, iof, source, factor = _recurring_conversion(
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

        # Fora do construtor porque o `criada` viaja junto: é ele que autoriza os
        # dois descartes abaixo a apagar a fatura fisicamente.
        statement_id, fatura_criada = _statement_for(db, template, occ)

        tx = Transaction(
            title=template.title,
            description=template.description,
            total_amount=converted,
            currency=base_currency if is_foreign else template.currency,
            payment_method=template.payment_method,
            credit_card_id=template.credit_card_id,
            statement_id=statement_id,
            # A instância herda o deslocamento do template (ADR 0032) e o guarda
            # na própria linha: sem isso, editar a data desta ocorrência pela
            # tela de lançamentos rerrotearia a fatura com deslocamento zero e
            # desfaria calada a correção que o template declara.
            statement_shift=template.statement_shift if template.credit_card_id else 0,
            # `civil_instant`, não `datetime(y, m, d)`: a ocorrência é uma DATA
            # de calendário ("todo dia 1"), e meia-noite UTC a joga para o dia 31
            # do mês anterior em qualquer fuso negativo — a despesa do dia 1º
            # saía do mês enquanto o `billing_month` da linha ao lado dizia o
            # contrário.
            transaction_date=civil_instant(occ),
            billing_month=billing_month,
            occurrence_date=occ,
            # A recorrência é o caso que o ADR 0029 veio fechar: a conta de luz
            # do dia 10 nascia e o caixa a debitava no mesmo instante, paga ou
            # não — ninguém a digitou, então ninguém afirmou que pagou. Ela nasce
            # A PAGAR, a menos que o template diga que o banco debita sozinho
            # (`auto_settle`) ou que o espaço não controle pagamento.
            #
            # `explicit` é informado SEMPRE, e é o que impede o palpite pela data
            # de agir aqui: a ocorrência do dia 1º já venceu, e o padrão a daria
            # por paga — que é exatamente o defeito de origem.
            settled_at=resolve_settled_at(
                db, template.workspace_id,
                transaction_date=civil_instant(occ),
                credit_card_id=template.credit_card_id,
                explicit=template.auto_settle,
            ),
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
        # Perna de fatura (ADR 0024) na moeda do cartão. A recorrência não podia
        # ficar de fora: uma assinatura mensal no cartão é justamente o lançamento
        # que ninguém relança à mão, então o buraco na fatura só cresceria.
        # `allow_fetch=False` no caminho de leitura é a mesma política da perna
        # contábil — sem cotação, a ocorrência espera o backfill.
        card = db.get(CreditCard, template.credit_card_id) if template.credit_card_id else None
        try:
            apply_statement_leg(db, tx, card, allow_fetch=allow_fetch)
        except HTTPException:
            logger.warning(
                "recurring_skip_sem_taxa_fatura",
                template_id=template.id,
                workspace_id=template.workspace_id,
                card_currency=card.currency if card else None,
                occurrence=occ.isoformat(),
            )
            # A fatura foi criada lá em cima, na montagem do lançamento. Sem esta
            # linha ela sobrevive à desistência e é confirmada pelo commit do
            # lote — fatura aberta e vazia, de um mês em que nada foi lançado.
            _descartar_fatura_vazia(db, tx.statement_id, criada=fatura_criada)
            return None
        db.add(tx)
        db.flush()

        payer_user, splits = RecurringService._participants(template)
        if payer_user is None or not splits:
            # Legado: sem pagador não dá para montar divisão — instância "nua"
            return tx

        payers = [TransactionPayerBase(user_id=payer_user, amount=converted)]
        if is_foreign:
            div = convert_division_to_base(factor=factor, base_total=converted, payers=payers, splits=splits, items=None, adjustments=None)
            payers, splits = div["payers"], div["splits"]
        try:
            persist_transaction_children(
                db,
                template.workspace_id,
                tx,
                total_amount=converted,
                split_mode=SplitMode.transaction,
                payers=payers,
                splits=splits,
                items=None,
            )
        except ValueError as exc:
            # Snapshot inválido (ex.: membro saiu): desiste desta ocorrência.
            #
            # O descarte continua sendo o comportamento certo AQUI — a
            # materialização é preguiçosa e roda dentro de rotas de LEITURA, onde
            # estourar deixaria o extrato inacessível por causa de um template
            # quebrado. O que não podia continuar era o silêncio absoluto: o
            # aluguel parava de aparecer e ninguém ficava sabendo.
            #
            # A prevenção mora na saída do membro (`_ensure_no_active_recurring`,
            # em `api/routes/members.py`), que recusa remover quem ainda é
            # pagador ou participante de recorrência ativa. Este log é a rede
            # para o que escapar dela.
            logger.warning(
                "recorrencia.ocorrencia_descartada",
                recurring_id=template.id,
                workspace_id=template.workspace_id,
                occurrence=str(occ),
                motivo=str(exc),
            )
            db.delete(tx)
            db.flush()
            # A fatura da ocorrência descartada some junto: apagar só a transação
            # deixava a fatura vazia para o commit do lote confirmar. O `delete`
            # vem ANTES de propósito — enquanto a linha existir ela é uma
            # referência, e a fatura (com razão) não pode ser apagada.
            _descartar_fatura_vazia(db, statement_id, criada=fatura_criada)
            return None

        RecurringService._apply_category(db, template, tx, amount=converted)
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
        db: Session, workspace_id: int, today: date, *,
        allow_fetch: bool = True, template_id: Optional[int] = None,
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

        stmt = (
            select(RecurringExpense)
            .where(RecurringExpense.workspace_id == workspace_id)
            .where(RecurringExpense.is_active.is_(True))
        )
        # template_id restringe ao template editado: sem isso, salvar UMA
        # recorrência varria e materializava TODAS as do workspace.
        if template_id is not None:
            stmt = stmt.where(RecurringExpense.id == template_id)
        templates = db.exec(stmt).all()
        if not templates:
            return 0

        # Inclui excluídas de propósito: tombstone bloqueia recriação.
        #
        # `occurrence_date` e não `transaction_date.date()`: a coluna é a data
        # CANÔNICA da ocorrência (é ela que a unique `uq_recurring_occurrence`
        # protege), enquanto `transaction_date` é um instante que o usuário pode
        # ter editado depois. Derivar a chave do instante fazia o dedup deixar de
        # reconhecer a própria instância assim que alguém corrigia a data dela —
        # e a materialização seguinte criava uma segunda.
        existing = db.exec(
            select(Transaction.recurring_expense_id, Transaction.occurrence_date)
            .where(Transaction.workspace_id == workspace_id)
            .where(Transaction.billing_month == billing_month)
            .where(Transaction.recurring_expense_id.is_not(None))
        ).all()
        existing_dates = {(rid, occ) for rid, occ in existing if occ is not None}
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

        Caminho LEGADO, mantido para quem chama a API sem `apply_to` (ADR 0030).
        A tela hoje monta a lista pelo `plan` e manda os ids escolhidos; aqui o
        escopo continua sendo por faixa de mês, e **a data não se move** — que é
        justamente o que a revisão veio resolver.
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
            today = today_local()
            stmt = stmt.where(Transaction.billing_month >= f"{today.year:04d}-{today.month:02d}")

        unpaid_txs = db.exec(stmt).all()
        if not unpaid_txs:
            return

        RecurringService._reaplica(db, template, unpaid_txs)

    @staticmethod
    def _reaplica(db: Session, template: RecurringExpense, alvos: List[Transaction]) -> None:
        """Reaplica o template a um conjunto EXPLÍCITO de instâncias.

        Extraído de `sync_unpaid_instances` quando a revisão (ADR 0030) passou a
        escolher as instâncias uma a uma: as duas precisam reaplicar do mesmo
        jeito, senão salvar pela tela nova e pela API antiga produziria estados
        diferentes a partir do mesmo template.

        Quem escolhe os alvos é o chamador. Este método NÃO filtra status — a
        trava de "paga não se toca" mora em quem monta a lista (`plan`, e o
        `WHERE` de `sync_unpaid_instances`).
        """
        payer_user, splits = RecurringService._participants(template)
        base_currency = workspace_base_currency(db, template.workspace_id)
        # Uma vez só, fora do laço: `credit_card_id` é do TEMPLATE, então é o
        # mesmo cartão para todas as instâncias.
        card = (
            db.get(CreditCard, template.credit_card_id)
            if template.credit_card_id is not None
            else None
        )
        for tx in alvos:
            # Re-converte cada instância na SUA data (meses diferentes, taxas diferentes)
            # `local_day` pelo mesmo motivo da renda recorrente: a reconversão e
            # a materialização precisam concordar sobre QUE DIA é a ocorrência,
            # senão editar o template move o valor sem que nada de valor mude.
            occ = local_day(tx.transaction_date)
            converted, rate, iof, source, factor = _recurring_conversion(
                db, template.workspace_id, template.base_amount, template.currency, occ, template.payment_method
            )
            is_foreign = rate is not None
            tx.title = template.title
            tx.description = template.description
            tx.total_amount = converted
            tx.currency = base_currency if is_foreign else template.currency
            tx.payment_method = template.payment_method
            # Trocar o cartão do template re-roteia a fatura das instâncias não
            # pagas; tirar o cartão as solta do statement.
            entrou_no_cartao = (
                tx.credit_card_id is None and template.credit_card_id is not None
            )
            saiu_do_cartao = (
                tx.credit_card_id is not None and template.credit_card_id is None
            )
            tx.credit_card_id = template.credit_card_id
            # A liquidação segue o cartão (ADR 0029), e SÓ na transição: quem
            # entra na fatura perde a liquidação própria (senão a saída conta duas
            # vezes); quem sai da fatura volta a tê-la. Fora dessas duas bordas o
            # campo não é tocado — ele é um fato de PAGAMENTO, e reaplicar o
            # template não pode desfazer um pagamento que aconteceu.
            if entrou_no_cartao:
                tx.settled_at = None
            elif saiu_do_cartao:
                tx.settled_at = resolve_settled_at(
                    db, template.workspace_id,
                    transaction_date=tx.transaction_date,
                    explicit=template.auto_settle,
                )
            # O flag de "nasceu agora" não interessa aqui: este é o caminho de
            # ESCRITA, a instância existe e nada será descartado.
            tx.statement_shift = template.statement_shift if template.credit_card_id else 0
            tx.statement_id, _ = _statement_for(db, template, occ)
            tx.original_amount = template.base_amount if is_foreign else None
            tx.original_currency = template.currency if is_foreign else None
            tx.exchange_rate = rate if is_foreign else None
            tx.iof_rate = iof if is_foreign else None
            tx.rate_source = source if is_foreign else None
            # A perna de FATURA (ADR 0024) tem de acompanhar. Sem isto, editar o
            # valor de uma assinatura em cartão de moeda diferente movia só a
            # perna contábil: o lançamento virava R$ 200 e a fatura continuava
            # cobrando os US$ 20,70 do valor antigo, com o limite disponível
            # preso ao número velho. Trocar o CARTÃO era pior — a instância
            # migrava para a fatura nova carregando a perna monetária da antiga,
            # e caía fora do total dela (`excluded_from_total_count`).
            #
            # Depois de `original_*`/`statement_id`, porque `apply_statement_leg`
            # reconstitui a moeda de ENTRADA a partir deles. Sem cartão ou sem
            # fatura ele zera os três campos, que é o certo para quem acabou de
            # tirar o cartão do template.
            #
            # A 422 por falta de cotação PROPAGA de propósito: aqui é caminho de
            # escrita interativo (PUT), a rota comita no fim, e desfazer tudo é
            # melhor que gravar metade da edição. No caminho de LEITURA
            # (`_create_instance`) ela é capturada e a ocorrência espera.
            apply_statement_leg(db, tx, card)
            db.add(tx)
            # Recria os filhos no valor novo (senão payer/split divergem do total)
            if payer_user is not None and splits:
                delete_transaction_children(db, tx.id)
                p = [TransactionPayerBase(user_id=payer_user, amount=converted)]
                s = splits
                if is_foreign:
                    div = convert_division_to_base(factor=factor, base_total=converted, payers=p, splits=s, items=None, adjustments=None)
                    p, s = div["payers"], div["splits"]
                try:
                    persist_transaction_children(
                        db,
                        template.workspace_id,
                        tx,
                        total_amount=converted,
                        split_mode=SplitMode.transaction,
                        payers=p,
                        splits=s,
                        items=None,
                    )
                except ValueError:
                    pass
                RecurringService._apply_category(db, template, tx, amount=converted)
        db.flush()

    # ---- Planejar, revisar, aplicar (ADR 0030) -------------------------------

    @staticmethod
    def _template_futuro(template: RecurringExpense, changes: Optional[dict]):
        """Uma cópia do template com `changes` aplicados, **sem tocar no banco**.

        `SimpleNamespace` e não `RecurringExpense(...)`: instanciar o model dentro
        de uma sessão aberta o deixa pendurado no `autoflush` do SQLModel, e a
        próxima consulta do planejador o gravaria — um template fantasma criado
        por uma operação que se chama *preview*. `occurrences_in_month` já é duck
        typing (serve despesa e renda), então um objeto com os campos basta.
        """
        campos = (
            "frequency", "interval", "start_date", "end_date", "day_of_month",
            "day_of_week", "month_of_year", "created_at",
        )
        base = {campo: getattr(template, campo, None) for campo in campos}
        base.update({k: v for k, v in (changes or {}).items() if k in campos})
        return SimpleNamespace(**base)

    @staticmethod
    def _meses_do_plano(
        db: Session, template_id: int, desde: date, hoje: date
    ) -> List[Tuple[int, int]]:
        """Os meses que a revisão percorre: de `desde` até o último que importa.

        O fim é o mais distante entre o mês corrente e o do último lançamento
        VIVO da recorrência — um template com parcelas já materializadas à frente
        (por backfill, ou por outra pessoa) precisa aparecer inteiro na revisão,
        senão a tela promete mexer em "deste mês em diante" e deixa o futuro
        intocado.
        """
        ultimo = db.exec(
            select(func.max(Transaction.billing_month))
            .where(Transaction.recurring_expense_id == template_id)
            .where(Transaction.deleted_at.is_(None))
        ).one()
        fim = date(hoje.year, hoje.month, 1)
        if ultimo:
            ano, mes = int(ultimo[:4]), int(ultimo[5:7])
            if (ano, mes) > (fim.year, fim.month):
                fim = date(ano, mes, 1)
        return _iter_months(date(desde.year, desde.month, 1), fim, limit=BACKFILL_MAX_MONTHS)

    @staticmethod
    def plan(
        db: Session,
        template: RecurringExpense,
        *,
        changes: Optional[dict] = None,
        since: Optional[date] = None,
        action: str = "update",
    ) -> List[dict]:
        """O que vai acontecer com cada lançamento — **sem escrever nada**.

        É a peça central do ADR 0030. A edição de recorrência tinha um `<select>`
        de escopo no rodapé do formulário que não dizia quantos nem quais
        lançamentos seriam atingidos, e que **não movia a data**: mudar "todo dia
        5" para "todo dia 20" deixava os lançamentos já criados no dia 5, para
        sempre. Excluir ou desativar o template não mexia em nada.

        Agora a tela pergunta, mostra e deixa escolher — e o que ela mostra sai
        DESTA função, a mesma que `apply` executa. É isso que impede a promessa e
        a ação de divergirem.

        `action`:
        - `update`     — o template continua vivo com `changes` aplicados;
        - `deactivate` — ele para de gerar: nenhuma ocorrência é esperada;
        - `delete`     — idem, e o template some depois.

        Cada item traz `action` (`update` | `move` | `cancel` | `create` |
        `none`), o motivo do congelamento quando houver, e o diff campo a campo.
        Nunca vai à rede: isto roda num POST de preview, e uma busca de cotação
        bloquearia a resposta (mesma política de `_create_instance`).
        """
        hoje = today_local()
        desde = since or date(hoje.year, hoje.month, 1)
        futuro = RecurringService._template_futuro(template, changes)
        para_gerar = action == "update" and (changes or {}).get(
            "is_active", template.is_active
        )

        instancias = db.exec(
            select(Transaction)
            .where(Transaction.recurring_expense_id == template.id)
            .where(Transaction.deleted_at.is_(None))
            .order_by(Transaction.occurrence_date, Transaction.id)
        ).all()
        por_mes: dict[str, List[Transaction]] = {}
        for tx in instancias:
            por_mes.setdefault(tx.billing_month or "", []).append(tx)

        plano: List[dict] = []
        for ano, mes in RecurringService._meses_do_plano(db, template.id, desde, hoje):
            chave = f"{ano:04d}-{mes:02d}"
            esperadas = (
                RecurringService.occurrences_in_month(futuro, ano, mes)
                if para_gerar
                else []
            )
            existentes = por_mes.get(chave, [])

            congeladas = [t for t in existentes if _congelada(t)]
            vivas = [t for t in existentes if not _congelada(t)]
            for tx in congeladas:
                plano.append(_item(tx, "none", motivo=_motivo_congelada(tx)))

            # As ocorrências que as congeladas já ocupam saem do conjunto
            # esperado: a de 5/8 já foi paga, e "criar a de 5/8" seria um
            # duplicado que a unique recusaria de qualquer forma.
            ocupadas = {t.occurrence_date for t in congeladas if t.occurrence_date}
            livres = [o for o in esperadas if o not in ocupadas]

            # O caso de UMA para UMA é MOVER, não cancelar e recriar: mover
            # preserva anexos, tags e a identidade do lançamento. Fora dele, o
            # pareamento não é óbvio (semanal virando diário, por exemplo) e o
            # diff de conjunto é a leitura honesta.
            if len(vivas) == 1 and len(livres) == 1:
                tx = vivas[0]
                nova = livres[0]
                if tx.occurrence_date != nova:
                    plano.append(_item(tx, "move", nova_data=nova))
                else:
                    plano.append(_item(tx, "update"))
                continue

            datas_livres = set(livres)
            for tx in vivas:
                if tx.occurrence_date in datas_livres:
                    datas_livres.discard(tx.occurrence_date)
                    plano.append(_item(tx, "update"))
                else:
                    plano.append(_item(tx, "cancel"))
            # Criar só do mês corrente em diante: preencher mês fechado é
            # materialização retroativa, e ela tem pergunta própria no formulário
            # (`materialize=past`) — fazer as duas coisas na mesma tela deixaria
            # a pessoa sem saber qual respondeu.
            if (ano, mes) >= (hoje.year, hoje.month):
                for occ in sorted(datas_livres):
                    plano.append({
                        "transaction_id": None,
                        "occurrence_date": occ,
                        "billing_month": chave,
                        "status": None,
                        "action": "create",
                        "frozen_reason": None,
                        "title": template.title,
                        "amount": None,
                        "changes": {},
                    })

        RecurringService._preenche_diff(db, template, plano, changes)
        return plano

    @staticmethod
    def _preenche_diff(
        db: Session,
        template: RecurringExpense,
        plano: List[dict],
        changes: Optional[dict],
    ) -> None:
        """Anexa a cada item o que MUDA nele — título, valor e data.

        Só os três: são os que a pessoa reconhece na linha. Divisão, categoria e
        forma de pagamento acompanham sempre que a instância é reaplicada, e
        listá-las campo a campo transformaria a revisão numa tabela de diferenças
        em vez de uma lista de lançamentos.

        `allow_fetch=False`: preview não sai para a internet. Sem cotação o valor
        novo vem `None` e a tela mostra um traço — melhor do que inventar número
        numa tela cuja função é dizer o que vai acontecer.
        """
        titulo_novo = (changes or {}).get("title", template.title)
        for item in plano:
            if item["action"] in ("none", "cancel"):
                continue
            # A data EFETIVA, que num `move` é a de destino: a reaplicação
            # converte na data em que a ocorrência vai ficar, e prever pela
            # antiga mostraria na tela um valor que não é o que será gravado —
            # visível em recorrência estrangeira, onde a cotação muda no mês.
            occ = item.get("new_occurrence_date") or item["occurrence_date"]
            try:
                convertido, *_ = _recurring_conversion(
                    db, template.workspace_id,
                    (changes or {}).get("base_amount", template.base_amount),
                    (changes or {}).get("currency", template.currency),
                    occ, template.payment_method, allow_fetch=False,
                )
            except ExchangeRateUnavailable:
                convertido = None
            diff = {}
            if item["action"] == "create":
                item["amount"] = convertido
                item["title"] = titulo_novo
                continue
            if convertido is not None and convertido != item["amount"]:
                diff["amount"] = {"from": item["amount"], "to": convertido}
            if titulo_novo != item["title"]:
                diff["title"] = {"from": item["title"], "to": titulo_novo}
            if item.get("new_occurrence_date") is not None:
                diff["date"] = {
                    "from": item["occurrence_date"],
                    "to": item["new_occurrence_date"],
                }
            item["changes"] = diff

    @staticmethod
    def apply_plan(
        db: Session,
        template: RecurringExpense,
        plano: List[dict],
        *,
        apply_to: Optional[List[int]] = None,
        create_occurrences: Optional[List[date]] = None,
    ) -> dict:
        """Executa o plano nos itens ESCOLHIDOS. Não faz commit (ADR 0010).

        `apply_to` é a lista de ids que a pessoa marcou; `create_occurrences`, as
        datas das linhas que ainda não existem (elas não têm id). Ausentes,
        nada acontece — a revisão é opt-in por linha, e um default "aplica tudo"
        traria de volta a ação invisível que o ADR 0030 veio remover.

        Cada instância é tocada num savepoint: mover `occurrence_date` pode
        colidir com a unique `uq_recurring_occurrence` (uma instância excluída
        deixa tombstone e ocupa a vaga), e quem colide desiste sozinho em vez de
        derrubar o lote inteiro. O mesmo desenho de `_create_instance_safe`.
        """
        escolhidos = set(apply_to or [])
        datas = set(create_occurrences or [])
        resultado = {"updated": 0, "moved": 0, "cancelled": 0, "created": 0, "skipped": 0}

        reaplicar: List[Transaction] = []
        for item in plano:
            acao = item["action"]
            if acao == "create":
                if item["occurrence_date"] not in datas:
                    continue
                criada = RecurringService._create_instance_safe(
                    db, template, item["occurrence_date"], item["billing_month"],
                    TransactionStatus.confirmed
                    if item["occurrence_date"] <= today_local()
                    else TransactionStatus.pending,
                )
                resultado["created" if criada else "skipped"] += 1
                continue

            if item["transaction_id"] not in escolhidos or acao == "none":
                continue
            tx = db.get(Transaction, item["transaction_id"])
            if tx is None or tx.deleted_at is not None or _congelada(tx):
                resultado["skipped"] += 1
                continue

            if acao == "cancel":
                # Cancelar, não excluir: o status é terminal, mantém o rastro e
                # — por conservar a linha — segura a vaga na unique, então
                # reativar o template não recria a ocorrência que a pessoa
                # acabou de dispensar.
                tx.status = TransactionStatus.cancelled
                db.add(tx)
                resultado["cancelled"] += 1
                continue

            if acao == "move":
                nova = item["new_occurrence_date"]
                try:
                    with db.begin_nested():
                        tx.occurrence_date = nova
                        # `civil_instant`: a ocorrência é um DIA de calendário, e
                        # meia-noite UTC a joga para o dia anterior em fuso
                        # negativo (ADR 0025). `billing_month` não muda — a nova
                        # data vem de `occurrences_in_month` do MESMO mês.
                        tx.transaction_date = civil_instant(nova)
                        db.add(tx)
                        db.flush()
                except IntegrityError:
                    # A vaga já é de outra linha (viva ou tombstone).
                    resultado["skipped"] += 1
                    continue
                resultado["moved"] += 1

            reaplicar.append(tx)
            if acao == "update":
                resultado["updated"] += 1

        if reaplicar:
            RecurringService._reaplica(db, template, reaplicar)
        return resultado


def _congelada(tx: Transaction) -> bool:
    """Lançamento que a revisão não toca: pago ou cancelado.

    Paga é imutável até ser reaberta (ADR 0003) e cancelada é terminal. As duas
    aparecem na lista, desabilitadas e com o motivo — omiti-las faria a contagem
    da tela não bater com o que a pessoa vê no extrato.
    """
    return tx.status in (TransactionStatus.paid, TransactionStatus.cancelled)


def _motivo_congelada(tx: Transaction) -> str:
    return (
        "já paga — não será alterada"
        if tx.status == TransactionStatus.paid
        else "cancelada"
    )


def _item(
    tx: Transaction,
    acao: str,
    *,
    motivo: Optional[str] = None,
    nova_data: Optional[date] = None,
) -> dict:
    return {
        "transaction_id": tx.id,
        "occurrence_date": tx.occurrence_date or local_day(tx.transaction_date),
        "new_occurrence_date": nova_data,
        "billing_month": tx.billing_month,
        "status": tx.status,
        "action": acao,
        "frozen_reason": motivo,
        "title": tx.title,
        "amount": tx.total_amount,
        "changes": {},
    }


class RecurringIncomeService:
    """Materializa rendas recorrentes em entradas Income mensais. Espelha
    RecurringService.generate_due_instances, mas renda não tem divisão/pagador —
    reusa RecurringService.occurrences_in_month para o calendário."""

    @staticmethod
    def generate_due_income(
        db: Session,
        user_id: int,
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

        O recorte é o DONO e mais nada (ADR 0021): renda não tem workspace, então
        não há um "workspace de origem" a partir do qual materializar. Antes o
        escopo era `workspace OU (pessoal E meu)`, e a metade `workspace` só existia
        para a renda da casa que deixou de existir.

        year/month materializam um mês específico (backfill retroativo);
        template_id restringe a um template. Dedup por (recurring_income,
        occurrence) — instância excluída deixa tombstone e não ressuscita.
        Não faz commit (ADR 0010).
        """
        year = year or today.year
        month = month or today.month
        billing_month = f"{year:04d}-{month:02d}"

        stmt = select(RecurringIncome).where(RecurringIncome.is_active.is_(True))
        if template_id is not None:
            stmt = stmt.where(RecurringIncome.id == template_id)
        else:
            stmt = stmt.where(RecurringIncome.user_id == user_id)
        templates = db.exec(stmt).all()
        if not templates:
            return 0

        # Dedup pelos IDS DOS TEMPLATES. Inclui excluídas de propósito: o
        # tombstone é o que bloqueia a recriação do que o usuário apagou.
        ids_templates = [t.id for t in templates]
        existing = db.exec(
            select(Income.recurring_income_id, Income.received_at)
            .where(Income.recurring_income_id.in_(ids_templates))
            .where(Income.billing_month == billing_month)
        ).all()
        existing_dates = {(rid, dt.date()) for rid, dt in existing}
        existing_templates = {rid for rid, _ in existing}

        per_occurrence = (RecurrenceFrequency.daily, RecurrenceFrequency.weekly)

        created = 0
        for template in templates:
            for occ in RecurringService.occurrences_in_month(template, year, month):
                if template.frequency in per_occurrence:
                    if (template.id, occ) in existing_dates:
                        continue
                elif template.id in existing_templates:
                    continue

                # A moeda de destino é a de RELATÓRIO DO DONO
                # (`User.report_currency`), nunca a base de um workspace:
                # converter pela base de quem por acaso disparou a leitura fazia o
                # MESMO salário virar valores diferentes conforme a tela aberta.
                destino = _moeda_do_usuario(db, template.user_id)
                try:
                    converted, rate, _iof, source, _factor = _conversao_para(
                        db, destino, template.base_amount, template.currency, occ,
                        allow_fetch=allow_fetch,
                    )
                except ExchangeRateUnavailable:
                    # Sem taxa para a data: espera o backfill em vez de inventar valor
                    logger.warning(
                        "recurring_income_skip_sem_taxa",
                        template_id=template.id, user_id=template.user_id,
                        currency=template.currency, occurrence=occ.isoformat(),
                    )
                    continue
                estrangeira = rate is not None
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
                            amount=converted,
                            currency=destino if estrangeira else template.currency,
                            original_amount=template.base_amount if estrangeira else None,
                            original_currency=template.currency if estrangeira else None,
                            exchange_rate=rate if estrangeira else None,
                            rate_source=source if estrangeira else None,
                            category=template.category,
                            # Mesma âncora da despesa (ver `_materialize`): o
                            # salário "todo dia 1" é data civil. Com meia-noite,
                            # `/me/income?month=` — que filtra por
                            # `month_bounds_utc` — devolvia a renda de agosto
                            # dentro de julho, e o mês de agosto vinha vazio.
                            received_at=civil_instant(occ),
                            user_id=template.user_id,
                            recurring_income_id=template.id,
                            billing_month=billing_month,
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
        # Mesma regra da materialização: destino é a moeda de relatório do dono.
        destino = _moeda_do_usuario(db, template.user_id)
        for inc in rows:
            # `local_day`: a cotação da reconversão tem de ser a MESMA que a
            # materialização usou. Lendo em UTC, uma ocorrência gravada às 22h
            # pegava o câmbio do dia seguinte e o valor mudava sozinho ao editar
            # o template.
            occ = local_day(inc.received_at)
            converted, rate, _iof, source, _factor = _conversao_para(
                db, destino, template.base_amount, template.currency, occ,
            )
            estrangeira = rate is not None
            inc.title = template.title
            inc.description = template.description
            inc.amount = converted
            inc.currency = destino if estrangeira else template.currency
            inc.category = template.category
            inc.original_amount = template.base_amount if estrangeira else None
            inc.original_currency = template.currency if estrangeira else None
            inc.exchange_rate = rate if estrangeira else None
            inc.rate_source = source if estrangeira else None
            db.add(inc)


class RecurringMaterializationService:
    """Materialização preguiçosa (lazy accrual) das recorrências vencidas do mês
    corrente. Chamada nas rotas de LEITURA (Início, Rendas, Lançamentos) para que
    tudo que é recorrente apareça sozinho, sem depender do botão "Lançar
    pendentes". Idempotente (dedup por tombstone) e restrita ao mês de `today`,
    então nunca cria retroativo em mês fechado."""

    @staticmethod
    def ensure_current_month(db: Session, workspace_id: int, today: date) -> dict:
        """Só DESPESA: a renda recorrente é pessoal e não passa por workspace
        nenhum (ADR 0021) — ela é materializada por `ensure_income_and_commit`,
        chamada nas rotas `/me`."""
        # allow_fetch=False: este é o caminho de LEITURA (GET). Buscar cotação
        # aqui bloqueava a resposta por até ~50s contra uma fonte externa.
        exp = RecurringService.generate_due_instances(
            db, workspace_id, today, allow_fetch=False
        )
        promovidas = RecurringService.promote_due_instances(db, workspace_id, today)
        return {"expenses": exp, "promoted": promovidas}

    # ---- Escopo retroativo (start_date no passado) ---------------------------

    @staticmethod
    def apply_scope(
        db: Session,
        workspace_id: Optional[int],
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
        today = today or today_local()
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
                # Renda: o recorte é o dono do template, não `workspace_id` (que
                # vem `None` das rotas pessoais).
                created += RecurringIncomeService.generate_due_income(
                    db, template.user_id, today,
                    year=year, month=month, template_id=template.id,
                )
            elif (year, month) == (today.year, today.month):
                created += RecurringService.generate_due_instances(
                    db, workspace_id, today, template_id=template.id
                )
            else:
                created += RecurringService.backfill_month(db, template.id, year, month)
        return created

    #: Papel abaixo do qual a leitura NÃO materializa (ver ensure_and_commit)
    _MIN_ROLE = WorkspaceRole.member

    @staticmethod
    def _tem_template_ativo(db: Session, workspace_id: int) -> bool:
        """Existe alguma recorrência de DESPESA ativa a materializar? Consulta
        barata (EXISTS por índice) antes de qualquer escrita.

        Série ENCERRADA não conta (ADR 0030): uma mensalidade que terminou em
        2038 continua com `is_active=True` — ninguém volta para desligá-la —, e
        sem este filtro ela pagaria as consultas de dedup e um commit por
        requisição, para sempre, sem nunca gerar nada.
        """
        hoje = today_local()
        despesa = db.exec(
            select(RecurringExpense.id)
            .where(RecurringExpense.workspace_id == workspace_id)
            .where(RecurringExpense.is_active.is_(True))
            .where(
                (RecurringExpense.end_date.is_(None))
                | (RecurringExpense.end_date >= hoje)
            )
            .limit(1)
        ).first()
        return despesa is not None

    @staticmethod
    def ensure_income_and_commit(
        db: Session, user_id: int, today: Optional[date] = None
    ) -> int:
        """Materialização preguiçosa da renda recorrente PESSOAL (ADR 0021).

        Par de `ensure_and_commit` para o lado pessoal: chamada nas rotas de
        leitura de `/me`, sem workspace nenhum no caminho. Antes isto viajava de
        carona na materialização do workspace, e a carona era a razão de o
        salário só aparecer depois de abrir a tela de um workspace — num usuário
        recém-criado, nenhuma.

        Best-effort e sem eventos, pelas mesmas razões de `ensure_and_commit`.
        """
        today = today or today_local()
        try:
            ativo = db.exec(
                select(RecurringIncome.id)
                .where(RecurringIncome.user_id == user_id)
                .where(RecurringIncome.is_active.is_(True))
                .limit(1)
            ).first()
            if ativo is None:
                return 0
            criadas = RecurringIncomeService.generate_due_income(
                db, user_id, today, allow_fetch=False
            )
            if criadas:
                db.commit()
            return criadas
        except Exception:
            db.rollback()
            logger.exception("materializacao_renda_falhou", user_id=user_id)
            return 0

    @staticmethod
    def ensure_and_commit(
        db: Session,
        workspace_id: int,
        today: Optional[date] = None,
        *,
        role=None,
    ) -> dict:
        """Conveniência para o caminho de leitura: materializa e comita. Best-effort
        — nunca propaga erro para não derrubar um GET (a materialização é acessória
        à resposta). Não emite eventos: o próprio refetch já traz os dados novos e
        publicar aqui provocaria tempestade de refetch (WS/seq).

        Cuida só da DESPESA recorrente, que é do workspace; a renda tem o caminho
        próprio em `ensure_income_and_commit` (ADR 0021).

        Dois curto-circuitos, ambos ANTES de escrever qualquer coisa:

        1. **`viewer` não materializa.** Um papel explicitamente somente-leitura
           não pode provocar INSERT + COMMIT. Quem tem escrita no workspace
           materializa na primeira tela que abrir, então nada se perde — só deixa
           de acontecer no acesso de quem não deveria escrever.
        2. **Sem template ativo, nem tenta.** A materialização roda no topo de 4
           rotas de listagem; a esmagadora maioria dos workspaces não tem nada a
           materializar na maioria dos GETs, e mesmo assim pagava as consultas de
           dedup e um commit por requisição.
        """
        vazio = {"expenses": 0, "promoted": 0}
        if role is not None and role_level(role) < role_level(
            RecurringMaterializationService._MIN_ROLE
        ):
            return vazio
        try:
            if not RecurringMaterializationService._tem_template_ativo(db, workspace_id):
                return vazio
            result = RecurringMaterializationService.ensure_current_month(
                db, workspace_id, today or today_local()
            )
            # Nada mudou: o commit era puro custo (a sessão está limpa)
            if any(result.values()):
                db.commit()
            return result
        except Exception:
            db.rollback()
            # Best-effort NÃO pode ser silencioso: sem este log, qualquer falha
            # (snapshot inválido, taxa ausente, IntegrityError) desaparecia sem
            # rastro e o usuário só via "a recorrência não apareceu".
            logger.exception("materializacao_falhou", workspace_id=workspace_id)
            return vazio
