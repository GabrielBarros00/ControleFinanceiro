import calendar
from datetime import datetime, date, UTC
from decimal import Decimal
from typing import Optional, Union

from sqlalchemy import update
from sqlmodel import Session, select, func

from app.domain.dates import local_day, today_local
from app.domain.query_policy import REALIZED_STATUSES
from app.models.credit_card import (
    CreditCard,
    CardStatement,
    StatementPayment,
    StatementStatus,
)
from app.models.payment_account import PaymentAccount
from app.models.transaction import (
    STATEMENT_SHIFT_MAX,
    STATEMENT_SHIFT_MIN,
    Transaction,
)


def _safe_date(year: int, month: int, day: int) -> date:
    """Cria a data limitando o dia ao último dia do mês (dia 31 em fevereiro etc.)."""
    last_day = calendar.monthrange(year, month)[1]
    return date(year, month, min(day, last_day))


def _advance_month(year: int, month: int) -> tuple[int, int]:
    return (year + 1, 1) if month == 12 else (year, month + 1)


def _retreat_month(year: int, month: int) -> tuple[int, int]:
    return (year - 1, 12) if month == 1 else (year, month - 1)


def _shift_month(year: int, month: int, shift: int) -> tuple[int, int]:
    """Anda `shift` faturas a partir de (ano, mês). Negativo volta."""
    passo = _advance_month if shift > 0 else _retreat_month
    for _ in range(abs(shift)):
        year, month = passo(year, month)
    return year, month


def _statement_dates(card: CreditCard, year: int, month: int) -> tuple[datetime, datetime]:
    """closing_date/due_date da fatura {year}-{month} a partir dos dias do cartão."""
    closing_date = _safe_date(year, month, card.closing_day)
    if card.due_day > card.closing_day:
        due_date = _safe_date(year, month, card.due_day)
    else:
        due_year, due_month = _advance_month(year, month)
        due_date = _safe_date(due_year, due_month, card.due_day)
    return (
        datetime.combine(closing_date, datetime.min.time()),
        datetime.combine(due_date, datetime.min.time()),
    )


class StatementStateError(ValueError):
    """Transição inválida do ciclo da fatura (o chamador traduz para 409)."""


class CreditCardService:
    @staticmethod
    def natural_month(card: CreditCard, transaction_date: Union[datetime, date]) -> tuple[int, int]:
        """O mês da fatura pela REGRA do ciclo, antes de qualquer correção.

        Só a regra do dia de fechamento: sem o deslocamento declarado e sem a
        rolagem por fatura fechada. É a referência contra a qual as duas se
        medem — `rolled_forward` no preview e o próprio `statement_shift`, que
        por definição é a distância entre isto e o destino escolhido.
        """
        t_date = local_day(transaction_date)
        if t_date.day >= card.closing_day:
            return _advance_month(t_date.year, t_date.month)
        return t_date.year, t_date.month

    @staticmethod
    def resolve_statement_target(
        db: Session,
        card: CreditCard,
        transaction_date: Union[datetime, date],
        *,
        shift: int = 0,
    ) -> tuple[int, int, Optional[CardStatement]]:
        """Para qual fatura esta compra vai — SEM criar nada (ADR 0002).

        Devolve `(ano, mês, fatura_existente | None)` aplicando, nesta ordem, as
        três regras que o usuário não tem como adivinhar:

        1. a partir do dia de fechamento a compra pertence à fatura do mês
           SEGUINTE (`natural_month`);
        2. o deslocamento DECLARADO (`shift`, ADR 0032) — a correção de quem
           sabe que o emissor processou a compra noutro ciclo;
        3. se a fatura resultante já estiver fechada/paga (imutável), rola para
           frente até achar uma aberta.

        A ordem entre 2 e 3 importa e é esta: o deslocamento parte do alvo
        NATURAL, não do alvo já rolado. Invertê-la faria "+1" a partir de uma
        fatura que rolou dois meses cair três meses à frente do que o usuário
        pediu — o deslocamento é uma correção sobre a regra do ciclo, não sobre
        o acidente de a fatura estar fechada.

        Existe separado do `get_or_create_statement` para que a UI possa ANUNCIAR
        o destino enquanto o usuário preenche o formulário sem, com isso, criar
        faturas vazias a cada tecla. As duas rotinas compartilham esta função —
        duas cópias da regra de roteamento divergiriam na primeira mudança.

        **Aceita instante OU dia de calendário, e a diferença importa.** O
        formulário manda um INSTANTE (hoje = agora; retroativo = meio-dia local
        convertido para UTC), e lê-lo com `.date()` colocava uma compra das 22h
        do dia 30 no dia 31 — cruzando o fechamento e indo parar na fatura do mês
        seguinte. `local_day` resolve isso. Quem já tem um dia de calendário (a
        ocorrência de uma recorrência, o ciclo corrente, o preview do formulário)
        passa um `date` e ele atravessa intacto — construir meia-noite para
        "virar datetime" reintroduziria o erro pelo outro lado, retrocedendo um
        dia em fuso negativo.
        """
        year, month = _shift_month(*CreditCardService.natural_month(card, transaction_date), shift)

        while True:
            statement = CreditCardService.find_statement(db, card, year, month)

            if statement is None or statement.status == StatementStatus.open:
                return year, month, statement

            # Fechada/paga é imutável: tenta o próximo mês
            year, month = _advance_month(year, month)

    @staticmethod
    def find_statement(
        db: Session, card: CreditCard, year: int, month: int
    ) -> Optional[CardStatement]:
        """A fatura `{year}-{month}` deste cartão, ou `None`. Não cria nada."""
        return db.exec(
            select(CardStatement)
            .where(CardStatement.card_id == card.id)
            .where(CardStatement.month == f"{year}-{month:02d}")
        ).first()

    @staticmethod
    def assert_shift_reachable(
        db: Session,
        card: CreditCard,
        transaction_date: Union[datetime, date],
        shift: int,
    ) -> None:
        """Recusa um deslocamento que não pode ser honrado (ADR 0032).

        Sem isto, pedir "a fatura anterior" quando ela já está fechada cairia na
        rolagem para frente do `resolve_statement_target` e a compra voltaria,
        calada, para o alvo natural: o app diria "ok" e faria outra coisa. Um
        pedido EXPLÍCITO que não pode ser atendido tem de falhar alto.

        Só vale para `shift != 0`. Com deslocamento zero a rolagem continua sendo
        o comportamento correto e desejado — ela não é o resultado de um pedido
        do usuário, é a regra de imutabilidade da fatura fechada (ADR 0011)
        fazendo o seu trabalho.
        """
        if not shift:
            return
        year, month = _shift_month(*CreditCardService.natural_month(card, transaction_date), shift)
        statement = CreditCardService.find_statement(db, card, year, month)
        if statement is not None and statement.status != StatementStatus.open:
            rotulo = "paga" if statement.status == StatementStatus.paid else "fechada"
            raise StatementStateError(
                f"A fatura de {year}-{month:02d} já está {rotulo} e não aceita "
                "lançamentos novos. Reabra-a antes de mover esta compra para ela."
            )

    @staticmethod
    def get_or_create_statement_tracked(
        db: Session,
        card: CreditCard,
        transaction_date: Union[datetime, date],
        *,
        shift: int = 0,
        strict_shift: bool = True,
    ) -> tuple[CardStatement, bool]:
        """Como `get_or_create_statement`, mas diz se a fatura NASCEU agora.

        Quem materializa recorrência precisa desfazer a fatura que a própria
        chamada criou quando a ocorrência acaba descartada — e só essa. Sem o
        flag, o chamador não tem como distinguir a fatura recém-criada da que já
        estava no banco: `ensure_current_statement` cria de propósito a fatura
        VAZIA do ciclo corrente, e ela é indistinguível de lixo por qualquer
        critério de conteúdo (ver `_descartar_fatura_vazia` em
        `recurring_service.py`).

        `strict_shift=True` faz a guarda de `assert_shift_reachable` valer aqui
        dentro, e não em cada rota: o ponto de escrita é único, então esquecê-la
        num caminho novo deixa de ser possível. Quem desliga é a materialização
        preguiçosa da recorrência — ela roda dentro de rotas de LEITURA, e um
        deslocamento inalcançável ali derrubaria um GET com 409 em vez de apenas
        deixar a ocorrência cair no alvo natural (ver `_statement_for`).
        """
        if strict_shift:
            CreditCardService.assert_shift_reachable(db, card, transaction_date, shift)
        year, month, statement = CreditCardService.resolve_statement_target(
            db, card, transaction_date, shift=shift
        )
        if statement is not None:
            return statement, False

        closing_dt, due_dt = _statement_dates(card, year, month)
        statement = CardStatement(
            card_id=card.id,
            month=f"{year}-{month:02d}",
            closing_date=closing_dt,
            due_date=due_dt,
            status=StatementStatus.open,
        )
        db.add(statement)
        # flush, NUNCA commit (ADR 0010): o chamador comanda a transação
        db.flush()
        return statement, True

    @staticmethod
    def get_or_create_statement(
        db: Session,
        card: CreditCard,
        transaction_date: Union[datetime, date],
        *,
        shift: int = 0,
        strict_shift: bool = True,
    ) -> CardStatement:
        """Fatura correta para uma transação (ADR 0002), criando-a se ainda não
        existe. A regra de roteamento vive em `resolve_statement_target`."""
        return CreditCardService.get_or_create_statement_tracked(
            db, card, transaction_date, shift=shift, strict_shift=strict_shift
        )[0]

    @staticmethod
    def preview_statement_target(
        db: Session,
        card: CreditCard,
        transaction_date: Union[datetime, date],
        *,
        shift: int = 0,
    ) -> dict:
        """Destino da compra em formato de leitura, sem efeito colateral.

        Além do destino, devolve `options`: as faturas para as quais esta compra
        PODE ser movida, cada uma já com o `statement_shift` que a alcança. É o
        que permite à tela oferecer "em qual fatura entrou?" sem fazer aritmética
        de ciclo no cliente — que seria uma segunda cópia da regra do ADR 0002,
        divergindo do servidor na primeira mudança — e sem nunca mandar um
        `statement_id`, que continua proibido.
        """
        year, month, statement = CreditCardService.resolve_statement_target(
            db, card, transaction_date, shift=shift
        )
        closing_dt, due_dt = _statement_dates(card, year, month)

        # Mês "natural" pelo ciclo: só a regra do dia de fechamento, sem o
        # deslocamento e sem a rolagem. A diferença entre ele e o destino real é
        # exatamente o caso que surpreende quem digita.
        natural = CreditCardService.natural_month(card, transaction_date)
        # `rolled_forward` mede só a ROLAGEM (fatura fechada), nunca o
        # deslocamento pedido: comparar contra o natural cru marcaria todo
        # `shift != 0` como "rolou", e a tela avisaria "a fatura do mês já está
        # fechada" sobre uma compra que o próprio usuário mandou para frente.
        pedido = _shift_month(*natural, shift)

        return {
            "month": f"{year}-{month:02d}",
            "closing_date": statement.closing_date if statement else closing_dt,
            "due_date": statement.due_date if statement else due_dt,
            # False = a fatura ainda não existe (nasce no primeiro lançamento)
            "exists": statement is not None,
            "rolled_forward": (year, month) != pedido,
            "shift": shift,
            "days_to_closing": CreditCardService._days_to_closing(
                card, transaction_date, natural, (year, month), pedido
            ),
            "options": CreditCardService._shift_options(db, card, natural),
        }

    @staticmethod
    def _days_to_closing(
        card: CreditCard,
        transaction_date: Union[datetime, date],
        natural: tuple[int, int],
        destino: tuple[int, int],
        pedido: tuple[int, int],
    ) -> Optional[int]:
        """Quantos dias faltam para a fatura de destino fechar. `None` quando a
        pergunta não faz sentido.

        Serve ao aviso da janela de fechamento (ADR 0032): perto do fechamento, a
        chance de o emissor processar a compra já no ciclo seguinte é real, e é o
        único momento em que o app pode alertar ANTES do fato.

        `None` quando o destino não é o ciclo natural da compra — porque o
        usuário já deslocou, ou porque a fatura rolou por estar fechada. Nos dois
        casos o número compararia a data da compra com o fechamento de um ciclo a
        que ela não pertence: um valor com aparência de resposta e sem
        significado, que faria a tela avisar "faltam 2 dias para o fechamento"
        sobre uma compra já movida.

        Uma compra logo DEPOIS do fechamento devolve um número grande (ela abre o
        ciclo seguinte), e isso é correto: não há nada de anômalo nela, e a tela
        simplesmente não avisa. O aviso é unilateral por natureza — atraso de
        captura de 1 a 3 dias nunca atravessa um ciclo inteiro.
        """
        if destino != natural or pedido != natural:
            return None
        closing_dt, _ = _statement_dates(card, *natural)
        return (closing_dt.date() - local_day(transaction_date)).days

    @staticmethod
    def _shift_options(
        db: Session, card: CreditCard, natural: tuple[int, int]
    ) -> list[dict]:
        """As faturas alcançáveis a partir do alvo natural, com o shift de cada.

        `available=False` marca a fatura fechada/paga: ela aparece na lista de
        propósito, com o motivo, em vez de sumir. Some-la deixaria a tela sem
        explicação para a opção que o usuário procura e não encontra — e o caso
        é frequente, porque a divergência costuma ser descoberta justamente
        quando a fatura real chega, com o ciclo já fechado.
        """
        opcoes = []
        for shift in range(STATEMENT_SHIFT_MIN, STATEMENT_SHIFT_MAX + 1):
            year, month = _shift_month(*natural, shift)
            statement = CreditCardService.find_statement(db, card, year, month)
            closing_dt, due_dt = _statement_dates(card, year, month)
            aberta = statement is None or statement.status == StatementStatus.open
            opcoes.append({
                "shift": shift,
                "month": f"{year}-{month:02d}",
                "closing_date": statement.closing_date if statement else closing_dt,
                "due_date": statement.due_date if statement else due_dt,
                "exists": statement is not None,
                "available": aberta,
                "status": statement.status if statement else None,
            })
        return opcoes

    @staticmethod
    def ensure_current_statement(db: Session, card: CreditCard, today: Optional[date] = None) -> CardStatement:
        """Garante que a fatura do ciclo CORRENTE exista (materialização preguiçosa).

        Sem isso a fatura só nascia quando chegava uma compra, então um mês sem
        gastos deixava a tela do cartão mostrando a fatura do mês passado como se
        fosse a atual. É a mesma fatura para onde uma compra de hoje iria.
        """
        ref = today or today_local()
        # `ref` direto, sem `datetime.combine`: já é o dia de calendário certo.
        # Envelopá-lo em meia-noite o faria ser reinterpretado como instante UTC
        # e voltar um dia — no dia 1º do mês, o ciclo corrente seria o do mês
        # passado.
        return CreditCardService.get_or_create_statement(db, card, ref)

    # ---- Totais e limite ----------------------------------------------------

    @staticmethod
    def statement_population(statement_id: int, card: CreditCard):
        """Os critérios do que COMPÕE uma fatura, num lugar só.

        Existir como função é o ponto: o total e a listagem tinham cada um a sua
        cópia dos filtros, e elas divergiam em DOIS eixos — a listagem não
        filtrava status (rascunho e cancelada apareciam) nem moeda. A tela
        mostrava N linhas e o rodapé somava outro conjunto. Um item da fatura é
        agora, por definição, o que este predicado devolve.
        """
        return (
            Transaction.statement_id == statement_id,
            Transaction.deleted_at.is_(None),
            Transaction.status.in_(REALIZED_STATUSES),
            Transaction.statement_currency == card.currency,
        )

    @staticmethod
    def compute_statement_total(db: Session, statement_id: int) -> Decimal:
        """Soma server-side das transações realizadas da fatura (fonte de verdade
        enquanto aberta), na moeda do CARTÃO.

        Soma `statement_amount` — a perna de fatura do ADR 0024 —, não
        `total_amount`. A versão anterior somava a perna CONTÁBIL e filtrava
        `currency == card.currency`; como todo lançamento é gravado na moeda-base
        do WORKSPACE, um cartão em USD usado num workspace em BRL não casava com
        linha nenhuma e a fatura somava 0,00 para sempre. A compra aparecia na
        tela, não consumia limite, e o fechamento congelava o zero.

        O filtro por moeda continua — agora sobre `statement_currency`, que a
        entrada garante ser a do cartão. Ele deixou de ser uma regra de negócio e
        virou o que sempre deveria ter sido: uma rede contra linha legada, contada
        em `excluded_from_total_count` em vez de sumir calada.
        """
        stmt = db.get(CardStatement, statement_id)
        if not stmt:
            return Decimal("0.00")
        card = db.get(CreditCard, stmt.card_id)
        if not card:
            return Decimal("0.00")
        total = db.exec(
            select(func.sum(Transaction.statement_amount)).where(
                *CreditCardService.statement_population(statement_id, card)
            )
        ).one()
        return total or Decimal("0.00")

    @staticmethod
    def excluded_from_total_count(db: Session, statement_id: int, card: CreditCard) -> int:
        """Quantos lançamentos VIVOS da fatura ficam fora do total.

        Só linha legada (anterior ao ADR 0024, sem perna de fatura) cai aqui. Ela
        continua fora — reconverter histórico a posteriori inventaria um câmbio
        que ninguém cobrou —, mas o usuário passa a saber que existe, como já
        acontece no `excluded_foreign_count` da visão global e do caixa. Ficar em
        silêncio é o que fazia a fatura parecer certa estando errada.
        """
        total_vivas = db.exec(
            select(func.count()).select_from(Transaction).where(
                Transaction.statement_id == statement_id,
                Transaction.deleted_at.is_(None),
                Transaction.status.in_(REALIZED_STATUSES),
            )
        ).one()
        contadas = db.exec(
            select(func.count()).select_from(Transaction).where(
                *CreditCardService.statement_population(statement_id, card)
            )
        ).one()
        return int(total_vivas or 0) - int(contadas or 0)

    @staticmethod
    def excluded_counts(
        db: Session, statement_ids: list[int], card: CreditCard
    ) -> dict[int, int]:
        """`excluded_from_total_count` de VÁRIAS faturas, em duas consultas.

        A versão por fatura é correta e cara: a listagem do cartão serializa
        todas as faturas do histórico, e duas contagens por linha viram ~120
        consultas num cartão com 60 meses de vida — só para descobrir que a
        resposta é zero em todas. Mesma razão de existir de `_payments_by_statement`
        na rota: o que a listagem faz N vezes tem de caber num `GROUP BY`.

        Os predicados são os mesmos de `excluded_from_total_count`, e não uma
        segunda redação deles: `statement_population` continua sendo a definição
        única do que compõe a fatura.
        """
        if not statement_ids:
            return {}

        def _por_fatura(*extra):
            linhas = db.exec(
                select(Transaction.statement_id, func.count())
                .where(Transaction.statement_id.in_(statement_ids), *extra)
                .group_by(Transaction.statement_id)
            ).all()
            return {sid: int(n) for sid, n in linhas}

        vivas = _por_fatura(
            Transaction.deleted_at.is_(None),
            Transaction.status.in_(REALIZED_STATUSES),
        )
        contadas = _por_fatura(
            Transaction.deleted_at.is_(None),
            Transaction.status.in_(REALIZED_STATUSES),
            Transaction.statement_currency == card.currency,
        )
        return {sid: vivas.get(sid, 0) - contadas.get(sid, 0) for sid in statement_ids}

    @staticmethod
    def effective_total(db: Session, statement: CardStatement) -> Decimal:
        """Aberta → total calculado; fechada/paga → total CONGELADO no fechamento."""
        if statement.status == StatementStatus.open:
            return CreditCardService.compute_statement_total(db, statement.id)
        return statement.total_amount

    @staticmethod
    def paid_amount(db: Session, statement: CardStatement) -> Decimal:
        """Quanto já foi pago desta fatura, somando os pagamentos VIVOS.

        `CardStatement.payments` sempre foi uma lista — o schema já admitia N
        pagamentos —, mas ninguém somava: pagar R$ 1 de uma fatura de R$ 1.000
        marcava a fatura como quitada e liberava o limite inteiro.
        """
        total = db.exec(
            select(func.sum(StatementPayment.amount)).where(
                StatementPayment.statement_id == statement.id,
                StatementPayment.deleted_at.is_(None),
            )
        ).one()
        return total or Decimal("0.00")

    @staticmethod
    def statement_balance(db: Session, statement: CardStatement) -> Decimal:
        """O que ainda falta pagar: total efetivo − já pago.

        É este número — e não o total — que compromete limite e que o próximo
        pagamento pode quitar. Nunca é negativo: sobrepagamento é recusado na
        entrada (`pay_statement`), como manda o ADR 0009 para acertos.
        """
        saldo = CreditCardService.effective_total(db, statement) - CreditCardService.paid_amount(
            db, statement
        )
        return saldo if saldo > 0 else Decimal("0.00")

    @staticmethod
    def resync_open_statement_dates(db: Session, card: CreditCard) -> int:
        """Recalcula closing_date/due_date das faturas ABERTAS do cartão.

        Os dias do ciclo (`closing_day`/`due_day`) são editáveis, mas as datas da
        fatura eram congeladas na criação dela: corrigir o vencimento no cadastro
        não mudava a fatura em aberto, e o aviso do cartão seguia anunciando uma
        data que não existe mais. Num app de finanças, vencimento errado é fatura
        paga com atraso.

        Fechadas/pagas ficam como estão: são histórico do que foi cobrado.
        Devolve quantas faturas foram ajustadas. Não comita (ADR 0010).
        """
        abertas = db.exec(
            select(CardStatement)
            .where(CardStatement.card_id == card.id)
            .where(CardStatement.status == StatementStatus.open)
        ).all()

        ajustadas = 0
        for stmt in abertas:
            try:
                year, month = (int(p) for p in stmt.month.split("-"))
            except (ValueError, AttributeError):
                continue
            closing_dt, due_dt = _statement_dates(card, year, month)
            if stmt.closing_date == closing_dt and stmt.due_date == due_dt:
                continue
            stmt.closing_date = closing_dt
            stmt.due_date = due_dt
            stmt.updated_at = datetime.now(UTC)
            db.add(stmt)
            ajustadas += 1
        if ajustadas:
            db.flush()
        return ajustadas

    @staticmethod
    def is_overdue(statement: CardStatement, today: Optional[date] = None) -> bool:
        """Vencida = não paga e passou do vencimento. DERIVADO (não persistido):
        não depende de um job para carimbar status. Definição única — a rota e o
        resumo do cartão leem daqui."""
        if statement.status == StatementStatus.paid:
            return False
        # Dia de calendário LOCAL: o vencimento é uma data do contrato, não um
        # instante, e em UTC a fatura virava "vencida" três horas antes da
        # meia-noite de quem a olha.
        ref = today or today_local()
        return ref > statement.due_date.date()

    @staticmethod
    def card_committed(db: Session, card: CreditCard) -> Decimal:
        """Limite comprometido: soma do SALDO das faturas ainda não quitadas
        (aberta usa total calculado; fechada usa o congelado; de ambos desconta o
        que já foi pago). Quitar libera o limite; pagar parte libera a parte."""
        return CreditCardService.card_overview(db, card)["committed"]

    @staticmethod
    def card_overview(db: Session, card: CreditCard) -> dict:
        """Uma passada só pelas faturas do cartão devolvendo limite comprometido
        E a fatura que pede atenção.

        `attention` é a NÃO quitada mais antiga com SALDO > 0 — a de vencimento
        mais próximo, e por isso a que corre risco de atraso. `None` quando não há
        nada a pagar. A tela de cartões precisa disso para avisar de fatura
        fechada/vencendo/vencida sem buscar as faturas de cada cartão.

        Uma passada porque `effective_total` dispara um SUM por fatura aberta:
        calcular comprometido e alerta em varreduras separadas dobrava as
        consultas por cartão. Os pagamentos vêm numa consulta agrupada só, pelo
        mesmo motivo — chamar `paid_amount` por fatura seria um SELECT por linha.
        """
        statements = db.exec(
            select(CardStatement)
            .where(CardStatement.card_id == card.id)
            .order_by(CardStatement.month)
        ).all()

        pagos = CreditCardService._paid_by_statement(db, [s.id for s in statements])

        committed = Decimal("0.00")
        attention: Optional[CardStatement] = None
        attention_total = Decimal("0.00")
        for stmt in statements:
            # Sem atalho por `status == paid`: quem decide é o SALDO, e uma
            # fatura quitada tem saldo zero — o `continue` logo abaixo já a
            # descarta, sem consulta extra (`effective_total` de fatura não
            # aberta lê a coluna congelada). O atalho só mudava o resultado no
            # estado contraditório — `paid` com saldo devedor, que o backfill
            # de moeda já produziu —, e nele mudava para pior: a dívida sumia do
            # limite comprometido e o cartão anunciava um crédito que não tinha.
            #
            # SALDO, não total: com pagamento parcial a fatura segue `closed`, e
            # comprometer o valor cheio manteria preso um limite que já foi pago.
            saldo = CreditCardService.effective_total(db, stmt) - pagos.get(
                stmt.id, Decimal("0.00")
            )
            if saldo <= 0:
                continue
            committed += saldo
            if attention is None:
                attention = stmt
                attention_total = saldo

        return {
            "committed": committed,
            "attention": attention,
            "attention_total": attention_total,
            # As faturas já carregadas: quem precisa delas (panorama de
            # endividamento) reusa em vez de disparar um segundo SELECT.
            "statements": statements,
            # Saldo já pago por fatura, para quem serializa a lista não repetir
            # a consulta por linha.
            "paid_by_statement": pagos,
        }

    @staticmethod
    def _paid_by_statement(db: Session, statement_ids: list[int]) -> dict[int, Decimal]:
        """`{statement_id: total pago}` numa consulta só, para evitar N+1."""
        if not statement_ids:
            return {}
        linhas = db.exec(
            select(StatementPayment.statement_id, func.sum(StatementPayment.amount))
            .where(StatementPayment.statement_id.in_(statement_ids))
            .where(StatementPayment.deleted_at.is_(None))
            .group_by(StatementPayment.statement_id)
        ).all()
        return {sid: (total or Decimal("0.00")) for sid, total in linhas}

    @staticmethod
    def available_limit(committed: Decimal, card: CreditCard) -> Decimal:
        return card.limit - committed

    # ---- Máquina de estados (ADR 0011) --------------------------------------

    @staticmethod
    def close_statement(db: Session, statement: CardStatement) -> CardStatement:
        if statement.status != StatementStatus.open:
            raise StatementStateError("Só é possível fechar uma fatura aberta")
        statement.status = StatementStatus.closed
        statement.closed_at = datetime.now(UTC)
        # Congela o valor faturado: edições posteriores nas transações não mudam
        # o que foi cobrado (o histórico do mês fica estável)
        statement.total_amount = CreditCardService.compute_statement_total(db, statement.id)
        statement.updated_at = datetime.now(UTC)
        db.add(statement)
        db.flush()
        return statement

    @staticmethod
    def pay_statement(
        db: Session,
        statement: CardStatement,
        *,
        account: Optional[PaymentAccount],
        amount: Optional[Decimal],
        paid_at: Optional[datetime],
        note: Optional[str],
        user_id: Optional[int],
    ) -> StatementPayment:
        """Registra um pagamento (total ou parcial) e quita a fatura no zero.

        Antes, QUALQUER valor positivo marcava a fatura como paga: R$ 1 numa
        fatura de R$ 1.000 devolvia `status = paid`, liberava o limite inteiro e
        ainda impedia completar o pagamento, porque a fatura já não estava
        `closed`. Agora o saldo é cumulativo — a fatura continua `closed` até
        chegar a zero — e o sobrepagamento é recusado, pela mesma razão do
        ADR 0009 nos acertos: aceitar mais do que se deve inventa crédito.

        **A recusa só vale se for ATÔMICA.** Ler o saldo, validar e só então
        inserir deixava duas requisições simultâneas de R$ 700 numa fatura de
        R$ 1.000 passarem as duas: R$ 1.400 pagos, fatura `paid`, saldo zero. O
        `UPDATE` condicional abaixo é a PRIMEIRA escrita da operação justamente
        para serializar — e é `UPDATE`, não `SELECT ... FOR UPDATE`, porque o
        dialeto SQLite ignora o segundo em silêncio e dev/CI/`tests/concurrency`
        rodam em SQLite. Um `INSERT ... SELECT` com a validação no `WHERE`
        também não serviria: sob snapshot isolation a subconsulta não enxerga a
        escrita não commitada da concorrente.
        """
        if statement.status != StatementStatus.closed:
            raise StatementStateError("Feche a fatura antes de pagá-la")

        # Trava a fatura. No Postgres (READ COMMITTED) a transação concorrente
        # bloqueia aqui e REAVALIA o WHERE contra a versão já commitada — é isso
        # que serializa; `rowcount == 0` significa que outra requisição reabriu
        # ou quitou a fatura no meio do caminho.
        travou = db.execute(
            update(CardStatement)
            .where(CardStatement.id == statement.id)
            .where(CardStatement.status == StatementStatus.closed)
            .values(updated_at=datetime.now(UTC))
        ).rowcount
        if not travou:
            raise StatementStateError(
                "A fatura mudou de estado durante o pagamento. Recarregue e tente de novo."
            )
        # O UPDATE direto não passa pela sessão: sem expirar, o objeto em memória
        # seguiria com os valores lidos ANTES da trava.
        db.expire(statement)

        # Só agora — já serializado — o saldo é confiável. A fatura está
        # `closed`, então `effective_total` é o total CONGELADO: o único termo
        # que a concorrente poderia ter mudado é a soma dos pagamentos, e esta
        # consulta roda depois da trava.
        saldo = CreditCardService.statement_balance(db, statement)
        if saldo <= 0:
            raise StatementStateError("Esta fatura já está quitada")

        pay_amount = amount if amount is not None else saldo
        if pay_amount <= 0:
            raise StatementStateError("Valor do pagamento deve ser positivo")
        if pay_amount > saldo:
            card = db.get(CreditCard, statement.card_id)
            moeda = card.currency if card else ""
            raise StatementStateError(
                f"Valor excede o saldo da fatura ({moeda} {saldo})".strip()
            )

        payment = StatementPayment(
            statement_id=statement.id,
            account_id=account.id if account else None,
            amount=pay_amount,
            paid_at=paid_at or datetime.now(UTC),
            note=note,
            created_by_user_id=user_id,
        )
        db.add(payment)
        if pay_amount >= saldo:
            statement.status = StatementStatus.paid
            statement.paid_at = payment.paid_at
        statement.updated_at = datetime.now(UTC)
        db.add(statement)
        db.flush()
        return payment

    @staticmethod
    def reopen_statement(db: Session, statement: CardStatement) -> CardStatement:
        """Desfaz um passo do ciclo: paga→fechada ou fechada→aberta (volta a somar
        em tempo real). Os pagamentos são estornados nas DUAS transições.

        Com saldo cumulativo uma fatura `closed` também pode ter pagamentos
        parciais, e uma fatura aberta com pagamento seria contraditória — o total
        volta a ser recalculado em tempo real, então não há saldo a que o
        pagamento se refira.
        """
        now = datetime.now(UTC)
        if statement.status not in (StatementStatus.paid, StatementStatus.closed):
            raise StatementStateError("Fatura já está aberta")

        for payment in db.exec(
            select(StatementPayment).where(
                StatementPayment.statement_id == statement.id,
                StatementPayment.deleted_at.is_(None),
            )
        ).all():
            payment.deleted_at = now
            db.add(payment)

        if statement.status == StatementStatus.paid:
            statement.status = StatementStatus.closed
            statement.paid_at = None
        else:
            statement.status = StatementStatus.open
            statement.closed_at = None
        statement.updated_at = now
        db.add(statement)
        db.flush()
        return statement
