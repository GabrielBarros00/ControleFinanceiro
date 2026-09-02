"""Caixa EFETIVO da pessoa no mês: o dinheiro que de fato entrou e saiu (ADR 0022).

O app chamava de "Saída de caixa" a soma dos `TransactionPayer` do mês de
faturamento. Não é caixa — é o que a pessoa **assumiu** nos lançamentos. A
diferença aparece no caso mais comum que existe:

    compra de R$ 300 no cartão em julho, fatura paga em 10 de agosto

Pelo número antigo, julho registrava R$ 300 "saídos do seu bolso" com o dinheiro
ainda na conta; agosto, quando ele realmente saiu, não registrava nada. O
pagamento da fatura não entrava em lugar nenhum do sistema — nem o acerto enviado a
outro membro, nem a parcela de financiamento paga fora de um workspace. Uma aba
chamada "Fluxo de Caixa" desenhava tudo menos fluxo de caixa.

**As seis fontes**, cada uma com a sua data efetiva e a sua moeda:

| Direção | Fonte                                          | Data                | Moeda            |
|---------|------------------------------------------------|---------------------|------------------|
| saída   | `TransactionPayer` de lançamento **sem cartão** | `settled_at`        | do lançamento    |
| saída   | `StatementPayment` de fatura de cartão meu      | `paid_at`           | do cartão        |
| saída   | `Settlement` que eu enviei                      | `settled_at`        | base do workspace|
| saída   | parcela de financiamento meu, paga              | `paid_at`           | do financiamento |
| entrada | `Income`                                        | `received_at`       | da renda         |
| entrada | `Settlement` que eu recebi                      | `settled_at`        | base do workspace|

**Lançamento no cartão não é saída de caixa.** Ele já será contado quando a fatura
for paga — e é por isso que o filtro é `credit_card_id IS NULL`. Pagamento parcial
de fatura entra naturalmente: cada `StatementPayment` é uma linha.

**Lançamento não liquidado também não é (ADR 0029).** `settled_at` é a data em que
o dinheiro saiu de fato; `NULL` significa "ainda não saiu". Antes esta data não
existia e a fonte 1 usava `transaction_date`, afirmando que toda despesa fora do
cartão saía do bolso no momento em que era registrada — o boleto que vence dia 10
debitava o caixa no dia 10, pago ou não. O que está `NULL` fica em Contas a pagar
(`PayablesService`) até alguém confirmar o pagamento.

**Sem contagem dobrada com o financiamento.** Pagar uma parcela informando um
workspace cria uma `Transaction` ligada por `Transaction.financing_installment_id`.
Quando essa despesa CONTA (viva e realizada), é ela que entra pela fonte 1 e a
parcela é ignorada; quando não existe — ou foi cancelada —, a parcela conta
sozinha. Sem a segunda metade da regra, cancelar a despesa vinculada fazia a saída
sumir dos dois lados: a transação caía pelo status e a parcela caía por "existe uma
transação".

**Este módulo produz LINHAS, não somas.** `list_movements` devolve cada movimento
com a sua data efetiva, e `get_month` agrega por cima. Três coisas dependem disso:

1. **Câmbio pela data efetiva.** A versão anterior convertia tudo pela cotação do
   dia 1º do mês — USD 100 pagos no dia 25 com dólar a 6 entravam como se fossem 5.
   O contrato do ADR 0022 sempre disse "cada uma com a sua data efetiva"; a
   implementação é que somava primeiro e convertia depois.
2. **Detalhe que fecha com o total.** `cash_out_breakdown` sai das mesmas linhas
   que `cash_out`, então não há como divergirem.
3. **O extrato global** é esta lista, filtrada.

**Arquivar não reescreve o passado.** As consultas NÃO filtram
`CreditCard.deleted_at` nem `Financing.deleted_at`: o fato é o pagamento, o
cadastro é só rótulo. Com o filtro, excluir um cartão apagava retroativamente do
fluxo de caixa toda fatura que ele já tinha pago — o mesmo modelo que
`PaymentAccount` acertou ao deixar o histórico apontando para a linha morta.

**Isto não substitui `consumption`.** Consumo é competência ("quanto do gasto foi
meu") e caixa é o movimento do dinheiro; `result = renda − consumo` continua sendo o
resultado do mês. São perguntas diferentes e agora têm nomes diferentes — o número
antigo sobrevive como `paid_in_transactions`, que é o que ele sempre foi.
"""
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional

from sqlmodel import Session, select

from app.domain.dates import local_day
from app.domain.query_policy import REALIZED_STATUSES, workspace_base_currency
from app.models.credit_card import CardStatement, CreditCard, StatementPayment
from app.models.financing import AmortizationInstallment, Financing
from app.models.income import Income
from app.models.settlement import Settlement
from app.models.transaction import Transaction, TransactionPayer
from app.services.money_conversion import ZERO, ConversorPorData

#: As seis fontes do ADR 0022. Valores estáveis: viajam na API do extrato.
SOURCE_TRANSACTION = "transaction"
SOURCE_STATEMENT_PAYMENT = "statement_payment"
SOURCE_SETTLEMENT_SENT = "settlement_sent"
SOURCE_SETTLEMENT_RECEIVED = "settlement_received"
SOURCE_FINANCING_INSTALLMENT = "financing_installment"
SOURCE_INCOME = "income"

CASH_SOURCES = (
    SOURCE_TRANSACTION,
    SOURCE_STATEMENT_PAYMENT,
    SOURCE_SETTLEMENT_SENT,
    SOURCE_SETTLEMENT_RECEIVED,
    SOURCE_FINANCING_INSTALLMENT,
    SOURCE_INCOME,
)

#: De qual chave do breakdown cada fonte de SAÍDA faz parte.
_SAIDA_PARA_BREAKDOWN = {
    SOURCE_TRANSACTION: "transactions",
    SOURCE_STATEMENT_PAYMENT: "statement_payments",
    SOURCE_SETTLEMENT_SENT: "settlements_sent",
    SOURCE_FINANCING_INSTALLMENT: "financing_installments",
}


@dataclass
class CashMovement:
    """Um movimento de caixa: quanto, quando de verdade, em que moeda e de onde.

    `converted` é `None` quando não havia cotação para a data efetiva. Não vira
    zero (ADR 0006): quem consome soma o que converteu e CONTA o que ficou de
    fora, para a tela poder avisar.
    """

    source: str
    direction: str  # 'in' | 'out'
    occurred_on: date
    currency: str
    amount: Decimal
    converted: Optional[Decimal]
    reference_id: Optional[int] = None
    title: Optional[str] = None
    workspace_id: Optional[int] = None
    card_id: Optional[int] = None
    financing_id: Optional[int] = None
    counterparty_id: Optional[int] = None
    #: De/para qual `PaymentAccount` o dinheiro se moveu (ADR 0034). `None` = não
    #: declarada — o movimento continua sendo caixa e continua no extrato, mas não
    #: move saldo de conta nenhuma. Não é falha: registrar a despesa sem dizer de
    #: onde saiu sempre foi legítimo. O que não pode é o buraco ser mudo, e por isso
    #: a tela de Contas mostra quantos movimentos estão assim.
    account_id: Optional[int] = None


def _dia(momento: Optional[datetime]) -> date:
    """Data efetiva de um instante, no fuso do aplicativo.

    `local_day` e não `.date()`: a janela do mês já vem de `month_bounds_utc`, e
    a discordância entre as duas aparecia na borda. Um movimento gravado como
    `2026-08-01T01:00Z` (22h de 31 de julho em São Paulo) ERA selecionado para
    julho pela janela e depois exibido como 01/08 — um extrato de julho com uma
    linha de agosto. E como `occurred_on` também é a data que
    `ConversorPorData` usa, a cotação vinha do dia errado junto.

    `None` só acontece em linha corrompida.
    """
    if momento is None:
        return date.min
    return local_day(momento)


class CashFlowService:
    # ---- O ledger -----------------------------------------------------------

    @staticmethod
    def list_movements(
        db: Session,
        user_id: int,
        destino: str,
        inicio: datetime,
        fim: datetime,
        *,
        sources: Optional[List[str]] = None,
        workspace_id: Optional[int] = None,
        converter: bool = True,
    ) -> List[CashMovement]:
        """Os movimentos de caixa da pessoa na janela, já convertidos para
        `destino` pela data efetiva de cada um.

        `sources`/`workspace_id` existem para o extrato global; `get_month` chama
        sem filtro e agrega. Uma implementação só para as duas telas — o detalhe
        que não fecha com o total é o defeito clássico deste tipo de relatório.

        `converter=False` devolve `converted=None` em toda linha e não toca no
        store de câmbio. É para o SALDO POR CONTA (ADR 0034), que soma `amount`
        direto: pela invariante de moeda, todo movimento atribuído a uma conta já
        está na moeda dela, e converter para um destino qualquer seria trabalho
        jogado fora — sobre o histórico INTEIRO, que é a janela do saldo.
        """
        conv = ConversorPorData(db, destino) if converter else None
        pedidas = set(sources) if sources else set(CASH_SOURCES)
        movimentos: List[CashMovement] = []

        if SOURCE_TRANSACTION in pedidas:
            movimentos += CashFlowService._lancamentos(db, user_id, inicio, fim, workspace_id)
        if SOURCE_STATEMENT_PAYMENT in pedidas and workspace_id is None:
            movimentos += CashFlowService._pagamentos_de_fatura(db, user_id, inicio, fim)
        if SOURCE_SETTLEMENT_SENT in pedidas:
            movimentos += CashFlowService._acertos(
                db, user_id, inicio, fim, enviados=True, workspace_id=workspace_id
            )
        if SOURCE_SETTLEMENT_RECEIVED in pedidas:
            movimentos += CashFlowService._acertos(
                db, user_id, inicio, fim, enviados=False, workspace_id=workspace_id
            )
        if SOURCE_FINANCING_INSTALLMENT in pedidas and workspace_id is None:
            movimentos += CashFlowService._parcelas(db, user_id, inicio, fim)
        if SOURCE_INCOME in pedidas and workspace_id is None:
            movimentos += CashFlowService._rendas(db, user_id, inicio, fim)

        if conv is not None:
            for mov in movimentos:
                mov.converted = conv(mov.amount or ZERO, mov.currency, mov.occurred_on)

        movimentos.sort(key=lambda m: (m.occurred_on, m.source, m.reference_id or 0))
        return movimentos

    # ---- Agregação ----------------------------------------------------------

    @staticmethod
    def get_month(
        db: Session,
        user_id: int,
        target_month: date,
        destino: str,
        inicio: datetime,
        fim: datetime,
    ) -> Dict[str, Any]:
        """Entradas e saídas de caixa da pessoa no mês, na moeda `destino`.

        `inicio`/`fim` vêm de quem chama porque `OverviewService` já os calcula
        para o mesmo mês — recalcular aqui abriria espaço para as duas janelas
        divergirem numa borda de mês. `target_month` sobrevive na assinatura por
        compatibilidade: a janela é que manda.
        """
        movimentos = CashFlowService.list_movements(db, user_id, destino, inicio, fim)

        excluidos = 0
        entrada = ZERO
        saida = ZERO
        renda_total = ZERO
        entrada_acertos = ZERO
        saidas = {chave: ZERO for chave in _SAIDA_PARA_BREAKDOWN.values()}

        for mov in movimentos:
            if mov.converted is None:
                excluidos += 1
                continue
            if mov.direction == "in":
                entrada += mov.converted
                if mov.source == SOURCE_INCOME:
                    renda_total += mov.converted
                else:
                    entrada_acertos += mov.converted
            else:
                saida += mov.converted
                saidas[_SAIDA_PARA_BREAKDOWN[mov.source]] += mov.converted

        return {
            "income": renda_total,
            "cash_in": entrada,
            "cash_out": saida,
            "net_cash": entrada - saida,
            # De onde veio o número: sem isto "saiu R$ 4.200" não é auditável pelo
            # usuário, que não tem como saber se a fatura entrou ou não. Vem das
            # MESMAS linhas do total, então não há como divergir dele.
            "cash_out_breakdown": {
                "transactions": saidas["transactions"],
                "statement_payments": saidas["statement_payments"],
                "settlements_sent": saidas["settlements_sent"],
                "financing_installments": saidas["financing_installments"],
            },
            "cash_in_breakdown": {
                "income": renda_total,
                "settlements_received": entrada_acertos,
            },
            "excluded_foreign_count": excluidos,
        }

    # ---- As seis fontes -----------------------------------------------------

    @staticmethod
    def _lancamentos(
        db: Session,
        user_id: int,
        inicio: datetime,
        fim: datetime,
        workspace_id: Optional[int] = None,
    ) -> List[CashMovement]:
        """Saída 1: o que saiu do bolso em lançamento FORA do cartão.

        `credit_card_id IS NULL` é o discriminador: a compra no cartão só vira
        caixa quando a fatura é paga (fonte 2).

        **A data é `settled_at`, não `transaction_date` (ADR 0029).** Enquanto
        era a data do lançamento, esta consulta afirmava que todo boleto, Pix,
        dinheiro e transferência saía do bolso no instante em que a despesa era
        registrada — `payment_method` não entrava aqui em lugar nenhum, e a conta
        de luz materializada pela recorrência no dia 10 debitava o caixa no dia
        10, paga ou não. Agora o boleto de julho pago em 14 de agosto é gasto de
        julho (competência, `billing_month`) e dinheiro que saiu em agosto.

        A JANELA também muda junto, e tinha de mudar: filtrar por
        `transaction_date` e exibir `settled_at` produziria um extrato de agosto
        com a linha ausente e um de julho com uma linha datada de agosto — a
        mesma incoerência que `_dia` existe para evitar. Como `occurred_on`
        alimenta o `ConversorPorData`, a cotação passa a ser a do dia do
        PAGAMENTO, que é quando o dinheiro de fato virou moeda.

        `settled_at IS NULL` é o que ainda não foi pago: fica fora do caixa e
        aparece em Contas a pagar (`PayablesService`, que é esta mesma consulta
        com o filtro invertido — as duas não têm como divergir).
        """
        consulta = (
            select(
                TransactionPayer.amount,
                Transaction.currency,
                Transaction.settled_at,
                Transaction.id,
                Transaction.title,
                Transaction.workspace_id,
                TransactionPayer.account_id,
            )
            .join(Transaction, Transaction.id == TransactionPayer.transaction_id)
            .where(TransactionPayer.user_id == user_id)
            .where(Transaction.credit_card_id.is_(None))
            .where(Transaction.settled_at.is_not(None))
            .where(Transaction.settled_at >= inicio)
            .where(Transaction.settled_at <= fim)
            .where(Transaction.deleted_at.is_(None))
            .where(Transaction.status.in_(REALIZED_STATUSES))
        )
        if workspace_id is not None:
            consulta = consulta.where(Transaction.workspace_id == workspace_id)
        return [
            CashMovement(
                source=SOURCE_TRANSACTION,
                direction="out",
                occurred_on=_dia(quando),
                currency=moeda,
                amount=valor or ZERO,
                converted=None,
                reference_id=tx_id,
                title=titulo,
                workspace_id=ws_id,
                account_id=conta_id,
            )
            for valor, moeda, quando, tx_id, titulo, ws_id, conta_id in db.exec(consulta).all()
        ]

    @staticmethod
    def _pagamentos_de_fatura(
        db: Session, user_id: int, inicio: datetime, fim: datetime
    ) -> List[CashMovement]:
        """Saída 2: pagamento de fatura, na moeda do CARTÃO.

        Sem filtro de `CreditCard.deleted_at` de propósito — ver o cabeçalho do
        módulo. O cartão arquivado continua explicando o pagamento que já
        aconteceu; escondê-lo reescrevia meses fechados.
        """
        linhas = db.exec(
            select(
                StatementPayment.amount,
                CreditCard.currency,
                StatementPayment.paid_at,
                StatementPayment.id,
                CreditCard.id,
                CreditCard.name,
                CardStatement.month,
                StatementPayment.account_id,
            )
            .join(CardStatement, CardStatement.id == StatementPayment.statement_id)
            .join(CreditCard, CreditCard.id == CardStatement.card_id)
            .where(CreditCard.owner_user_id == user_id)
            .where(StatementPayment.paid_at >= inicio)
            .where(StatementPayment.paid_at <= fim)
            .where(StatementPayment.deleted_at.is_(None))
        ).all()
        return [
            CashMovement(
                source=SOURCE_STATEMENT_PAYMENT,
                direction="out",
                occurred_on=_dia(quando),
                currency=moeda,
                amount=valor or ZERO,
                converted=None,
                reference_id=pag_id,
                title=f"{nome} — fatura de {mes}",
                card_id=card_id,
                account_id=conta_id,
            )
            for valor, moeda, quando, pag_id, card_id, nome, mes, conta_id in linhas
        ]

    @staticmethod
    def _acertos(
        db: Session,
        user_id: int,
        inicio: datetime,
        fim: datetime,
        enviados: bool,
        workspace_id: Optional[int] = None,
    ) -> List[CashMovement]:
        """Fonte 3: acertos entre membros — dinheiro que muda de mão de verdade.

        O valor está na moeda-base do workspace em que o acerto foi registrado.
        `workspace_base_currency` é resolvido por workspace (poucos), não por
        linha.
        """
        coluna = Settlement.from_user_id if enviados else Settlement.to_user_id
        outro = Settlement.to_user_id if enviados else Settlement.from_user_id
        # Cada lado carrega a SUA conta. A do credor só ele pode declarar — quem
        # registra o acerto é o devedor, e a conta bancária alheia não é informação
        # dele (a mesma regra do gate 3 de `_validate_payer_accounts`).
        conta = Settlement.from_account_id if enviados else Settlement.to_account_id
        consulta = (
            select(
                Settlement.amount,
                Settlement.workspace_id,
                Settlement.settled_at,
                Settlement.id,
                outro,
                conta,
            )
            .where(coluna == user_id)
            .where(Settlement.settled_at >= inicio)
            .where(Settlement.settled_at <= fim)
            .where(Settlement.deleted_at.is_(None))
        )
        if workspace_id is not None:
            consulta = consulta.where(Settlement.workspace_id == workspace_id)

        moedas: Dict[int, str] = {}
        movimentos = []
        for valor, ws_id, quando, acerto_id, outro_id, conta_id in db.exec(consulta).all():
            if ws_id not in moedas:
                moedas[ws_id] = workspace_base_currency(db, ws_id)
            movimentos.append(
                CashMovement(
                    source=SOURCE_SETTLEMENT_SENT if enviados else SOURCE_SETTLEMENT_RECEIVED,
                    direction="out" if enviados else "in",
                    occurred_on=_dia(quando),
                    currency=moedas[ws_id],
                    amount=valor or ZERO,
                    converted=None,
                    reference_id=acerto_id,
                    title="Acerto enviado" if enviados else "Acerto recebido",
                    workspace_id=ws_id,
                    counterparty_id=outro_id,
                    account_id=conta_id,
                )
            )
        return movimentos

    @staticmethod
    def _parcelas(
        db: Session, user_id: int, inicio: datetime, fim: datetime
    ) -> List[CashMovement]:
        """Saída 4: parcela de financiamento paga SEM despesa que já a conte.

        A deduplicação exige que a transação vinculada esteja viva, **realizada
        e liquidada** — exatamente as três condições da fonte 1. Antes bastava
        existir: cancelar a despesa a tirava do caixa pelo status e ainda assim
        suprimia a parcela, e a saída sumia inteira. `settled_at` (ADR 0029) é a
        terceira condição pelo mesmo motivo: desmarcar o pagamento da despesa
        vinculada a tira da fonte 1, e sem este termo ela continuaria suprimindo
        a parcela — a saída sumiria dos dois lados de novo.

        Sem filtro de `Financing.deleted_at` — ver o cabeçalho do módulo.
        """
        ja_lancada = (
            select(Transaction.id)
            .where(Transaction.financing_installment_id == AmortizationInstallment.id)
            .where(Transaction.deleted_at.is_(None))
            .where(Transaction.status.in_(REALIZED_STATUSES))
            .where(Transaction.settled_at.is_not(None))
            .exists()
        )
        linhas = db.exec(
            select(
                AmortizationInstallment.total_amount,
                Financing.currency,
                AmortizationInstallment.paid_at,
                AmortizationInstallment.id,
                AmortizationInstallment.installment_number,
                Financing.id,
                Financing.title,
                AmortizationInstallment.account_id,
            )
            .join(Financing, Financing.id == AmortizationInstallment.financing_id)
            .where(Financing.owner_user_id == user_id)
            .where(AmortizationInstallment.is_paid.is_(True))
            .where(AmortizationInstallment.paid_at >= inicio)
            .where(AmortizationInstallment.paid_at <= fim)
            .where(~ja_lancada)
        ).all()
        return [
            CashMovement(
                source=SOURCE_FINANCING_INSTALLMENT,
                direction="out",
                occurred_on=_dia(quando),
                currency=moeda,
                amount=valor or ZERO,
                converted=None,
                reference_id=parcela_id,
                title=f"{titulo} — parcela {numero}",
                financing_id=fin_id,
                account_id=conta_id,
            )
            for valor, moeda, quando, parcela_id, numero, fin_id, titulo, conta_id in linhas
        ]

    @staticmethod
    def _rendas(
        db: Session, user_id: int, inicio: datetime, fim: datetime
    ) -> List[CashMovement]:
        """Entrada 1: renda RECEBIDA. Sem workspace — renda é pessoal (ADR 0021).

        **A data é `settled_at`, não `received_at` (ADR 0034).** Enquanto havia uma
        data só, o salário do dia 30 materializado no dia 1º já contava como caixa
        do dia 30 desde o começo do mês — e uma renda que nunca chegou continuava
        contada. `received_at` virou a COMPETÊNCIA ("quando era para entrar") e
        `settled_at` é o caixa ("quando entrou"); `NULL` é a renda prevista, que
        aparece em "A receber" e na projeção.

        A JANELA muda junto, e tinha de mudar — é a mesma razão da fonte 1: filtrar
        por uma data e exibir outra produziria um extrato de outubro sem a linha e
        um de setembro com uma linha datada de outubro. E como `occurred_on`
        alimenta o `ConversorPorData`, a cotação passa a ser a do dia em que o
        dinheiro de fato virou moeda.

        Cancelada não entra por construção: cancelar deixa `settled_at` nulo.
        """
        linhas = db.exec(
            select(
                Income.amount,
                Income.currency,
                Income.settled_at,
                Income.id,
                Income.title,
                Income.account_id,
            )
            .where(Income.user_id == user_id)
            .where(Income.settled_at.is_not(None))
            .where(Income.settled_at >= inicio)
            .where(Income.settled_at <= fim)
            .where(Income.deleted_at.is_(None))
        ).all()
        return [
            CashMovement(
                source=SOURCE_INCOME,
                direction="in",
                occurred_on=_dia(quando),
                currency=moeda,
                amount=valor or ZERO,
                converted=None,
                reference_id=renda_id,
                title=titulo,
                account_id=conta_id,
            )
            for valor, moeda, quando, renda_id, titulo, conta_id in linhas
        ]

    # ---- Rótulos ------------------------------------------------------------

    @staticmethod
    def resolve_labels(db: Session, movimentos: List[CashMovement]) -> Dict[str, Dict[int, str]]:
        """Nomes de workspace/contraparte para o extrato, em lote.

        Fora das seis consultas de propósito: `get_month` não desenha nome
        nenhum, e juntar `Workspace` e `User` em toda fonte seria custo puro no
        caminho que mais roda (`get_series` chama `get_month` 12 vezes).
        """
        from app.models.user import User
        from app.models.workspace import Workspace

        ws_ids = {m.workspace_id for m in movimentos if m.workspace_id is not None}
        user_ids = {m.counterparty_id for m in movimentos if m.counterparty_id is not None}

        workspaces: Dict[int, str] = {}
        if ws_ids:
            workspaces = {
                w_id: nome
                for w_id, nome in db.exec(
                    select(Workspace.id, Workspace.name).where(Workspace.id.in_(ws_ids))
                ).all()
            }
        usuarios: Dict[int, str] = {}
        if user_ids:
            usuarios = {
                u_id: nome
                for u_id, nome in db.exec(
                    select(User.id, User.name).where(User.id.in_(user_ids))
                ).all()
            }
        return {"workspaces": workspaces, "users": usuarios}
