"""Contas a pagar: o lançamento que ainda não virou saída de caixa (ADR 0029/0034).

**Obrigação e caixa usam conjuntos de status DIFERENTES, e essa é a mudança do ADR
0034.** Aqui vale `PAYABLE_STATUSES`, que inclui `pending`; o caixa usa
`REALIZED_STATUSES`, que não. A conta de luz que a recorrência materializou para o
dia 18 é obrigação no dia 1º e não é gasto realizado — as duas coisas ao mesmo
tempo. A partição com o caixa continua de pé porque **liquidar promove `pending`
para `confirmed`** (ver `settle`): sem essa promoção a despesa paga sairia daqui e
não entraria no caixa, e o dinheiro sumiria dos dois lados.

**O mês pedido não é o horizonte.** `entries` traz o mês e o atrasado; `upcoming`
traz o que vence até o fim do MÊS SEGUINTE. Sem a segunda lista, o aluguel de 1º de
setembro só aparecia quando setembro chegasse — e quem olha a tela em 28 de agosto
precisa saber que ele vem.


**É a fonte 1 do `CashFlowService` com o filtro invertido.** Aquela consulta soma
o `TransactionPayer` da pessoa em lançamento vivo, realizado, fora do cartão e
**liquidado**; esta lista o mesmo conjunto com `settled_at IS NULL`. As duas juntas
particionam o mesmo universo, e é por isso que o total daqui vira exatamente o
`cash_out` de amanhã — o defeito clássico deste tipo de tela é o "a pagar" e o
"pago" saírem de consultas parecidas que discordam na borda.

**Por que o recorte é o PAGADOR, e não a divisão.** Consumo (`TransactionSplit`)
responde "de quem é o gasto"; quem tem de tirar o dinheiro do bolso é quem consta
em `TransactionPayer`. Num jantar rateado 50/50 que eu paguei, a conta a pagar é
minha e inteira — a parte do outro vira acerto, não conta a pagar dele.

**O que NÃO entra:**

- compra no cartão (`credit_card_id IS NOT NULL`) — quem se paga é a fatura, e ela
  já tem lugar próprio em Compromissos. Contá-la aqui pediria o mesmo dinheiro
  duas vezes;
- rascunho e cancelada (fora de `REALIZED_STATUSES`) — não são obrigação;
- parcela de financiamento sem despesa — mora em Compromissos, e tem botão próprio.

**Sem cotação, a linha aparece assim mesmo.** `converted` vem `None` e o chamador
conta (ADR 0006). Numa tela de obrigações, esconder o que não converteu é pior que
em qualquer outra: o valor continua sendo devido.
"""
from datetime import date, datetime
from typing import Any, Dict, List, Optional

from sqlmodel import Session, select

from app.domain.dates import (
    civil_instant,
    fim_do_horizonte,
    local_day,
    month_bounds_utc,
    month_key,
    today_local,
)
from app.domain.access_policy import can_write, involvement_filter, scope_transactions
from app.domain.account_policy import assert_conta_na_moeda
from app.domain.query_policy import PAYABLE_STATUSES, workspaces_do_usuario
from app.models.payment_account import PaymentAccount
from app.models.transaction import Transaction, TransactionPayer, TransactionStatus
from app.models.workspace import Workspace
from app.services.money_conversion import ZERO, ConversorPorData


def _consulta_base():
    """`SELECT` da conta a pagar com o valor que EU assumo, sem recorte de pessoa.

    Os quatro filtros ficam aqui porque as duas leituras do módulo — a pessoal e a
    do espaço — precisam concordar sobre o que é uma pendência; divergir faria uma
    tela somar um conjunto e a outra somar outro. E são os MESMOS quatro da fonte 1
    do `CashFlowService`, com `settled_at` invertido: as duas consultas particionam
    o mesmo universo.

    `select(Transaction, TransactionPayer.amount)` e **não**
    `select(Transaction).add_columns(...)`: com uma entidade só o SQLModel devolve
    um `SelectOfScalar`, e o `exec()` dele chama `.scalars()` — a coluna extra some
    em silêncio e o desempacotamento estoura lá adiante, longe da causa.
    """
    return (
        select(Transaction, TransactionPayer.amount)
        .join(TransactionPayer, TransactionPayer.transaction_id == Transaction.id)
        .where(Transaction.deleted_at.is_(None))
        # `PAYABLE_STATUSES` e não `REALIZED_STATUSES` (ADR 0034): a ocorrência
        # futura nasce `pending` e é obrigação hoje, sem ser gasto realizado.
        .where(Transaction.status.in_(PAYABLE_STATUSES))
        .where(Transaction.credit_card_id.is_(None))
        .where(Transaction.settled_at.is_(None))
    )


def _por_lancamento(linhas) -> List[tuple]:
    """Uma linha por LANÇAMENTO, somando os pagadores dele.

    A consulta junta `TransactionPayer`, e uma despesa com dois pagadores volta
    em duas linhas. Na leitura pessoal isso nunca acontece (há o filtro
    `user_id == eu`, e a dupla `(transação, pessoa)` é única); na do ESPAÇO, sim
    — e a mesma conta apareceria duas vezes na tela, com duas caixas de seleção
    para um único `settled_at`. Marcar uma e não a outra seria impossível de
    representar, e o total do topo contaria a despesa uma vez enquanto a lista a
    mostrava duas.

    Somar é a leitura certa aqui: o que a tela do espaço pergunta é "quanto esta
    conta ainda vai tirar do caixa da casa", e isso é o valor cheio da despesa,
    não a fatia de um dos pagadores.
    """
    agrupado: Dict[int, tuple] = {}
    for tx, valor in linhas:
        anterior = agrupado.get(tx.id)
        agrupado[tx.id] = (tx, (anterior[1] if anterior else ZERO) + (valor or ZERO))
    return list(agrupado.values())


def _estado(vence: date, hoje: date) -> str:
    """`overdue | due_today | upcoming` — DERIVADO, nunca armazenado.

    A tela precisa distinguir "vence hoje" de "vence em 12 dias": as duas são
    `is_overdue: false` e pedem ações diferentes. Guardar o estado numa coluna
    exigiria reescrevê-lo todo dia à meia-noite.
    """
    if vence < hoje:
        return "overdue"
    if vence == hoje:
        return "due_today"
    return "upcoming"


def _entrada(
    tx: Transaction,
    valor,
    convertido,
    vence: date,
    hoje: date,
    *,
    nomes: Dict[int, str],
    mes_pedido: str,
) -> Dict[str, Any]:
    """A linha da tela. Uma função só para a lista do mês e a de próximas não
    divergirem em campo nenhum — foram escritas juntas justamente por isso."""
    return {
        "transaction_id": tx.id,
        "workspace_id": tx.workspace_id,
        "workspace_name": nomes.get(tx.workspace_id, ""),
        "title": tx.title,
        "due_date": vence,
        "billing_month": tx.billing_month,
        "amount": valor or ZERO,
        "currency": tx.currency,
        "converted_amount": convertido,
        "payment_method": tx.payment_method,
        "is_overdue": vence < hoje,
        "due_state": _estado(vence, hoje),
        #: Negativo = já venceu. É o número que a tela transforma em "vence em 3
        #: dias" / "venceu há 2 dias" sem ter de refazer a conta no cliente, onde
        #: o fuso do navegador daria outra resposta perto da meia-noite.
        "days_until_due": (vence - hoje).days,
        # De onde a conta veio. A recorrência é a origem que mais aparece aqui —
        # e saber que a linha é automática muda o que a pessoa faz com ela
        # (marcar como paga vs. ir cobrar alguém).
        "recurring_expense_id": tx.recurring_expense_id,
        "installment_no": tx.installment_no,
        "installments_of": tx.installments_of,
        # Competência anterior ao mês pedido: a conta é arrastada de um mês
        # fechado. A tela agrupa por isso.
        "from_past_month": (tx.billing_month or mes_pedido) < mes_pedido,
    }


def _vencimento(tx: Transaction) -> date:
    """O dia em que a conta vence: a data do lançamento, lida no fuso do app.

    `local_day` e não `.date()` — o boleto do dia 1º gravado como
    `2026-08-01T03:00Z` é 1º de agosto em São Paulo, e lê-lo em UTC não muda nada;
    já o gravado às 22h do dia 31 (`2026-08-01T01:00Z`) é 31 de JULHO, e a lista
    diria que vence no mês seguinte.
    """
    return local_day(tx.transaction_date)


class PayablesService:
    # ---- Camada pessoal ------------------------------------------------------

    @staticmethod
    def list_payables(
        db: Session,
        user_id: int,
        target_month: date,
        destino: str,
        *,
        workspace_id: Optional[int] = None,
        incluir_atrasadas: bool = True,
    ) -> Dict[str, Any]:
        """O que EU ainda tenho a pagar no mês, somando todos os meus espaços.

        `incluir_atrasadas` traz também o que venceu em meses ANTERIORES e segue
        em aberto. Ligado por padrão, e é o comportamento que a tela quer: uma
        conta atrasada não deixa de ser devida na virada do mês, e escondê-la em
        agosto porque venceu em julho é a forma mais direta de alguém esquecer de
        pagá-la. Desligado, a resposta é estritamente o mês pedido.
        """
        espacos = workspaces_do_usuario(db, user_id)
        ids = [ws.id for ws in espacos]
        if workspace_id is not None:
            ids = [i for i in ids if i == workspace_id]
        if not ids:
            return PayablesService._vazio(destino, target_month)

        mes = month_key(target_month)
        do_usuario = (
            _consulta_base()
            .where(TransactionPayer.user_id == user_id)
            .where(Transaction.workspace_id.in_(ids))
        )
        # `billing_month` e não a janela por `transaction_date`: é a definição
        # ÚNICA de mês das agregações (ver `domain/dates.month_key`), e a tela põe
        # a conta ao lado do consumo do mesmo mês.
        consulta = do_usuario.where(
            Transaction.billing_month <= mes
            if incluir_atrasadas
            else Transaction.billing_month == mes
        )
        nomes = {ws.id: ws.name for ws in espacos}

        resultado = PayablesService._monta(
            db, destino, target_month, db.exec(consulta).all(),
            nomes=nomes, mes_pedido=mes,
        )
        resultado["upcoming"] = PayablesService._proximas(
            db, destino, target_month, do_usuario, nomes=nomes, mes_pedido=mes
        )
        return resultado

    # ---- Camada do espaço ----------------------------------------------------

    @staticmethod
    def list_workspace_payables(
        db: Session,
        workspace_id: int,
        target_month: date,
        destino: str,
        *,
        viewer_user_id: Optional[int] = None,
        incluir_atrasadas: bool = True,
    ) -> Dict[str, Any]:
        """As contas em aberto DESTE espaço, de quem quer que vá pagá-las.

        `viewer_user_id=None` significa acesso completo (a casa inteira); com um
        id, só o que envolve aquela pessoa (ADR 0018). Quem DECIDE isso é a rota,
        pelo mesmo desenho de `DebtService.get_workspace_debts`: a política mora
        na borda, onde o `membership` existe, e o serviço aplica o recorte que
        recebeu. Sem esse recorte, uma tela de pendências vazaria o que o extrato
        esconde — e vazaria justamente o que cada um deve pagar.
        """
        mes = month_key(target_month)
        do_espaco = _consulta_base().where(Transaction.workspace_id == workspace_id)
        if viewer_user_id is not None:
            do_espaco = do_espaco.where(involvement_filter(viewer_user_id))
        consulta = do_espaco.where(
            Transaction.billing_month <= mes
            if incluir_atrasadas
            else Transaction.billing_month == mes
        )

        ws = db.get(Workspace, workspace_id)
        nomes = {workspace_id: ws.name if ws else ""}
        resultado = PayablesService._monta(
            db, destino, target_month, db.exec(consulta).all(),
            nomes=nomes, mes_pedido=mes,
        )
        resultado["upcoming"] = PayablesService._proximas(
            db, destino, target_month, do_espaco, nomes=nomes, mes_pedido=mes
        )
        return resultado

    # ---- O número que o Seu mês mostra --------------------------------------

    @staticmethod
    def totals(
        db: Session, user_id: int, target_month: date, destino: str
    ) -> Dict[str, Any]:
        """`{total, count, overdue}` para o cartão do Seu mês.

        Chama a MESMA `list_payables` em vez de recontar: um total que não fecha
        com a lista que ele promete abrir é o defeito que o `cash_out_breakdown`
        do ADR 0022 já teve de resolver uma vez.
        """
        dados = PayablesService.list_payables(db, user_id, target_month, destino)
        return {
            "payables_total": dados["total"],
            "payables_count": len(dados["entries"]),
            "payables_overdue": dados["overdue_total"],
        }

    # ---- Montagem ------------------------------------------------------------

    @staticmethod
    def _vazio(destino: str, target_month: date) -> Dict[str, Any]:
        return {
            "currency": destino,
            "month": month_key(target_month),
            "total": ZERO,
            "overdue_total": ZERO,
            "due_this_month_total": ZERO,
            "entries": [],
            "upcoming": [],
            "excluded_foreign_count": 0,
        }

    @staticmethod
    def _proximas(
        db: Session,
        destino: str,
        target_month: date,
        consulta_sem_mes,
        *,
        nomes: Dict[int, str],
        mes_pedido: str,
    ) -> List[Dict[str, Any]]:
        """As obrigações de competência FUTURA que vencem até o fim do mês seguinte.

        Existe por causa do caso que abre o ADR 0034: em 28 de agosto, o aluguel de
        1º de setembro tem `billing_month = "2026-09"` e por isso ficava fora da
        lista de agosto — a pessoa só descobria a conta quando o mês virasse, que é
        tarde demais para uma conta que vence no dia 1º.

        Lista separada, e não misturada em `entries`, porque os totais do topo
        respondem "quanto ainda sai NESTE mês". Somar setembro ali inflaria o número
        que a pessoa usa para decidir se o dinheiro do mês fecha.

        O teto é `fim_do_horizonte` — a MESMA constante que a materialização usa.
        Mostrar mais do que se materializa prometeria uma lista que às vezes existe
        e às vezes não, conforme o cron tivesse rodado.
        """
        limite = fim_do_horizonte(target_month)

        linhas = db.exec(
            consulta_sem_mes.where(Transaction.billing_month > mes_pedido)
        ).all()

        entradas = []
        conv = ConversorPorData(db, destino)
        hoje = today_local()
        for tx, valor in _por_lancamento(linhas):
            vence = _vencimento(tx)
            if vence > limite:
                continue
            entradas.append(
                _entrada(tx, valor, conv(valor or ZERO, tx.currency, vence), vence, hoje,
                         nomes=nomes, mes_pedido=mes_pedido)
            )
        entradas.sort(key=lambda e: (e["due_date"], e["transaction_id"]))
        return entradas

    @staticmethod
    def _monta(
        db: Session,
        destino: str,
        target_month: date,
        linhas,
        *,
        nomes: Dict[int, str],
        mes_pedido: str,
    ) -> Dict[str, Any]:
        conv = ConversorPorData(db, destino)
        hoje = today_local()
        # Fim do mês PEDIDO, não de hoje: olhando agosto em setembro, "vence neste
        # mês" tem de continuar falando de agosto.
        _inicio, fim_utc = month_bounds_utc(date(target_month.year, target_month.month, 1))
        fim_do_mes = local_day(fim_utc)

        entradas: List[Dict[str, Any]] = []
        total = ZERO
        atrasado = ZERO
        no_mes = ZERO
        excluidos = 0

        for tx, valor in _por_lancamento(linhas):
            vence = _vencimento(tx)
            convertido = conv(valor or ZERO, tx.currency, vence)
            atrasada = vence < hoje
            if convertido is None:
                excluidos += 1
            else:
                total += convertido
                if atrasada:
                    atrasado += convertido
                elif vence <= fim_do_mes:
                    no_mes += convertido
            entradas.append(
                _entrada(tx, valor, convertido, vence, hoje,
                         nomes=nomes, mes_pedido=mes_pedido)
            )

        # Mais antigas primeiro: a fila de pagamento se lê por vencimento, ao
        # contrário do extrato (que é histórico e se lê do mais recente).
        entradas.sort(key=lambda e: (e["due_date"], e["transaction_id"]))

        return {
            "currency": destino,
            "month": month_key(target_month),
            "total": total,
            "overdue_total": atrasado,
            "due_this_month_total": no_mes,
            "entries": entradas,
            # Preenchida por quem chama (`list_payables` / `list_workspace_payables`)
            # — `_monta` não conhece a consulta sem recorte de mês.
            "upcoming": [],
            "excluded_foreign_count": excluidos,
        }

    # ---- Escrita -------------------------------------------------------------

    @staticmethod
    def settle(
        db: Session,
        workspace_id: int,
        membership,
        transaction_ids: List[int],
        *,
        settled: bool,
        settled_on: Optional[date] = None,
        account_id: Optional[int] = None,
    ) -> Dict[str, int]:
        """Marca (ou desmarca) o pagamento de vários lançamentos de uma vez.

        Devolve `{updated, skipped}`. Pular em vez de recusar é a mesma política
        de `BulkDeleteResult`/`InstallmentGroupCancelResult`: quem confirma cinco
        contas não pode ver a operação inteira falhar porque uma delas foi
        cancelada por outra pessoa entre a leitura da tela e o clique.

        `settled_on` é uma data CIVIL — "paguei no dia 14" —, então vira instante
        por `civil_instant`, não por `datetime.combine`. Meia-noite local ancorada
        em UTC jogaria o pagamento do dia 1º para o caixa do mês anterior.

        **Liquidar PROMOVE `pending` para `confirmed` (ADR 0034)**, e este é o
        ponto mais perigoso da onda inteira. A lista usa `PAYABLE_STATUSES` (que
        inclui `pending`) e o caixa usa `REALIZED_STATUSES` (que não): sem a
        promoção, confirmar o pagamento de uma ocorrência ainda não vencida a
        tiraria daqui **e** não a colocaria no caixa. O dinheiro sumiria dos dois
        lados, em silêncio, e o único sinal seria um saldo que não fecha.

        `account_id` diz de qual conta o dinheiro saiu — é aqui que a pessoa sabe
        disso, e até o ADR 0034 não havia onde dizer. É gravado na linha de
        `TransactionPayer` de quem está liquidando, e só nela: declarar a conta de
        outro pagador é informação que não é de quem clicou (ADR 0004).
        """
        if not transaction_ids:
            return {"updated": 0, "skipped": 0}

        quando: Optional[datetime] = (
            civil_instant(settled_on or today_local()) if settled else None
        )

        alvos = db.exec(
            scope_transactions(
                select(Transaction)
                .where(Transaction.id.in_(transaction_ids))
                .where(Transaction.workspace_id == workspace_id)
                .where(Transaction.deleted_at.is_(None)),
                membership,
            )
        ).all()

        atualizados = 0
        for tx in alvos:
            # As mesmas travas da lista, agora na escrita: rascunho e cancelada não
            # são obrigação, e compra no cartão se paga pela fatura. Sem elas, um id
            # forjado no corpo marcaria como paga uma compra de cartão e a saída
            # contaria duas vezes no caixa.
            if tx.status not in PAYABLE_STATUSES or tx.credit_card_id is not None:
                continue
            # Autoria (ADR 0018): `member` mexe no que é dele, `admin+` em tudo.
            if not can_write(tx.created_by_user_id, membership):
                continue
            if (tx.settled_at is not None) == settled:
                continue
            tx.settled_at = quando
            if settled and tx.status == TransactionStatus.pending:
                # A promoção descrita no docstring. Pagar é o ato que confirma a
                # despesa: ninguém paga uma conta que não reconhece.
                tx.status = TransactionStatus.confirmed
            db.add(tx)
            if settled and account_id is not None:
                PayablesService._grava_conta(db, tx, membership.user_id, account_id)
            atualizados += 1

        return {"updated": atualizados, "skipped": len(transaction_ids) - atualizados}

    @staticmethod
    def _grava_conta(db: Session, tx: Transaction, user_id: int, account_id: int) -> None:
        """Anota, na linha de pagador de QUEM LIQUIDOU, de qual conta saiu.

        Silencioso quando não há o que anotar — quem confirma o pagamento de uma
        despesa em que não é pagador (um `admin` fechando a conta da casa) está
        registrando o fato, não a origem do próprio dinheiro. Recusar a operação
        inteira por causa disso faria a confirmação em lote falhar por um detalhe
        opcional.

        A conta é validada aqui (dono, viva, ativa, moeda) e não na rota porque é
        aqui que se sabe qual é o pagador e qual a moeda do lançamento.
        """
        payer = db.exec(
            select(TransactionPayer)
            .where(TransactionPayer.transaction_id == tx.id)
            .where(TransactionPayer.user_id == user_id)
        ).first()
        if payer is None:
            return
        conta = db.get(PaymentAccount, account_id)
        if not conta or conta.deleted_at or conta.owner_user_id != user_id:
            raise ValueError("Conta inválida")
        if not conta.active:
            raise ValueError(f"Conta '{conta.name}' está desativada")
        assert_conta_na_moeda(conta, tx.currency)
        payer.account_id = account_id
        db.add(payer)
