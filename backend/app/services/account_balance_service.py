"""Quanto dinheiro existe em cada conta, e por quê (ADR 0034).

O app sabia responder "de quem é o gasto" (competência) e "quando o dinheiro se
moveu" (caixa). Não sabia "quanto eu tenho". O ADR 0022 registrou a ausência como
decisão consciente — *"saldo por conta exige saldo inicial e conciliação, outra
decisão, se algum dia"* — e este módulo é esse dia.

**Não há ledger novo.** O `CashFlowService` já é o ledger: seis fontes derivadas das
tabelas de origem, linha a linha, com data efetiva. Replicar esses movimentos numa
tabela de saldo daria duas fontes para o mesmo fato, e o saldo passaria a depender
de qual delas fosse lida. O que se acrescenta são as três coisas que **não têm
origem em tabela nenhuma** — abertura, ajuste e transferência —, guardadas em
`AccountEntry`/`AccountTransfer`.

A fórmula:

    saldo(conta) =  abertura
                  + Σ ajustes
                  + Σ transferências recebidas − Σ enviadas
                  + Σ entradas de caixa − Σ saídas
                  ... contando só o que ocorreu A PARTIR da data da abertura.

**O corte pela data da abertura é o que torna a migração honesta.** "Em 01/09 eu
tinha R$ 8.350,42" já contém tudo que aconteceu antes de 01/09; somar o histórico
por cima dobraria cada lançamento antigo. A consequência é que um movimento anterior
à abertura não mexe no saldo — o que é certo, mas seria mudo. Por isso ele é
CONTADO: `movements_before_opening` existe para a pessoa que lança em janeiro o
extrato de dezembro entender por que o número não se moveu.

**O saldo não é reproduzível como o de um banco.** Ele é função do estado ATUAL de
seis tabelas mutáveis: desmarcar o pagamento de uma conta tira a saída do saldo,
corrigir uma data a move de mês. O extrato explica o saldo de hoje; ele não é um
registro imutável de um fechamento. Dizer isso é melhor do que fingir o contrário.

**Nada daqui é fonte do `CashFlowService`.** Transferência entre contas minhas não é
entrada nem saída de caixa (infla os dois lados, e o `net_cash` só acerta por
acidente), e ajuste não é renda. Os dois movem SALDO, que é outra pergunta.
`tests/test_caixa_sem_saldo.py` é o portão mecânico dessa separação.
"""
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional

from sqlmodel import Session, select

from app.domain.dates import local_day
from app.models.account_ledger import AccountEntry, AccountEntryKind, AccountTransfer
from app.models.payment_account import PaymentAccount
from app.services.cashflow_service import CashFlowService, CashMovement
from app.services.money_conversion import ZERO, converte

#: Origens que só existem no saldo — nunca no `CashFlowService`. Valores estáveis:
#: viajam na API do extrato da conta.
SOURCE_OPENING_BALANCE = "opening_balance"
SOURCE_ADJUSTMENT = "adjustment"
SOURCE_TRANSFER_IN = "transfer_in"
SOURCE_TRANSFER_OUT = "transfer_out"

LEDGER_ONLY_SOURCES = (
    SOURCE_OPENING_BALANCE,
    SOURCE_ADJUSTMENT,
    SOURCE_TRANSFER_IN,
    SOURCE_TRANSFER_OUT,
)

#: Janela "tudo": o saldo não tem mês. Instantes ingênuos, como as colunas.
_DESDE_SEMPRE = datetime(1, 1, 1)
_ATE_SEMPRE = datetime(9999, 12, 31, 23, 59, 59)


@dataclass
class AccountBalance:
    """O saldo de uma conta, com o rastro de como ele foi calculado.

    `balance` é `None` — e não zero — quando a conta não tem saldo inicial. Um zero
    ali seria um número errado apresentado com a mesma confiança de um certo, e o
    §6 do pedido é explícito: a atualização não inventa saldo nenhum.
    """

    account_id: int
    name: str
    type: str
    currency: str
    active: bool
    is_default: bool
    opening_amount: Optional[Decimal]
    opening_on: Optional[date]
    balance: Optional[Decimal]
    #: Quantos movimentos entraram na conta desde a abertura. Exposto de propósito:
    #: um saldo errado tem de ser diagnosticável sem abrir o banco.
    movements_counted: int


class AccountBalanceService:
    # ---- Leitura -------------------------------------------------------------

    @staticmethod
    def contas_da_pessoa(db: Session, user_id: int) -> List[PaymentAccount]:
        return db.exec(
            select(PaymentAccount)
            .where(PaymentAccount.owner_user_id == user_id)
            .where(PaymentAccount.deleted_at.is_(None))
            .order_by(PaymentAccount.name)
        ).all()

    @staticmethod
    def aberturas(db: Session, account_ids: List[int]) -> Dict[int, AccountEntry]:
        """A abertura viva de cada conta. No máximo uma por conta — a unique
        parcial `uq_accountentry_abertura` é quem garante isso."""
        if not account_ids:
            return {}
        linhas = db.exec(
            select(AccountEntry)
            .where(AccountEntry.account_id.in_(account_ids))
            .where(AccountEntry.kind == AccountEntryKind.opening_balance)
            .where(AccountEntry.deleted_at.is_(None))
        ).all()
        return {e.account_id: e for e in linhas}

    @staticmethod
    def movimentos_de_caixa(
        db: Session,
        user_id: int,
        *,
        desde: Optional[datetime] = None,
        ate: Optional[datetime] = None,
    ) -> List[CashMovement]:
        """As seis fontes de caixa da pessoa, sem recorte de conta e SEM conversão.

        Uma varredura só, para quem precisa tanto das linhas atribuídas quanto das
        que não têm conta (o contador de anomalia). Chamar duas vezes materializava
        o histórico inteiro em dobro.

        `converter=False` porque o saldo soma `amount` direto: pela invariante do
        ADR 0034 todo movimento atribuído a uma conta já está na moeda dela, e
        converter para um destino qualquer seria consulta ao store por par
        (moeda, dia) do histórico inteiro, para nada.
        """
        return CashFlowService.list_movements(
            db, user_id, "BRL", desde or _DESDE_SEMPRE, ate or _ATE_SEMPRE,
            converter=False,
        )

    @staticmethod
    def movimentos(
        db: Session,
        user_id: int,
        account_ids: List[int],
        *,
        desde: Optional[datetime] = None,
        ate: Optional[datetime] = None,
        caixa: Optional[List[CashMovement]] = None,
    ) -> List[CashMovement]:
        """Todas as linhas que mexem no saldo destas contas, já ordenadas.

        As seis fontes de caixa saem do `CashFlowService` — as MESMAS consultas
        que desenham o extrato do mês, com os mesmos filtros de status, soft delete
        e cartão. Reescrevê-las aqui era o caminho curto para o saldo e o caixa
        discordarem sobre o que conta, que é o defeito clássico desta tela.

        `caixa` permite reaproveitar uma varredura já feita (ver `balances`).
        """
        if not account_ids:
            return []
        alvo = set(account_ids)
        if caixa is None:
            caixa = AccountBalanceService.movimentos_de_caixa(
                db, user_id, desde=desde, ate=ate
            )
        linhas = [m for m in caixa if m.account_id in alvo]
        linhas += AccountBalanceService._entradas(db, account_ids, desde, ate)
        linhas += AccountBalanceService._transferencias(db, account_ids, desde, ate)
        linhas.sort(key=lambda m: (m.occurred_on, m.source, m.reference_id or 0))
        return linhas

    @staticmethod
    def _entradas(
        db: Session,
        account_ids: List[int],
        desde: Optional[datetime],
        ate: Optional[datetime],
    ) -> List[CashMovement]:
        """Abertura e ajuste: as linhas que não vêm de tabela de origem nenhuma."""
        consulta = (
            select(AccountEntry)
            .where(AccountEntry.account_id.in_(account_ids))
            .where(AccountEntry.deleted_at.is_(None))
        )
        if desde is not None:
            consulta = consulta.where(AccountEntry.occurred_at >= desde)
        if ate is not None:
            consulta = consulta.where(AccountEntry.occurred_at <= ate)
        return [
            CashMovement(
                source=(
                    SOURCE_OPENING_BALANCE
                    if e.kind == AccountEntryKind.opening_balance
                    else SOURCE_ADJUSTMENT
                ),
                # `amount` já vem COM SINAL; a direção é redundante e existe só
                # para a tela pintar a linha.
                direction="in" if (e.amount or ZERO) >= ZERO else "out",
                occurred_on=local_day(e.occurred_at),
                currency="",  # preenchido por quem monta (é a moeda da conta)
                amount=e.amount or ZERO,
                converted=None,
                reference_id=e.id,
                title=e.description
                or (
                    "Saldo inicial"
                    if e.kind == AccountEntryKind.opening_balance
                    else "Ajuste de saldo"
                ),
                account_id=e.account_id,
            )
            for e in db.exec(consulta).all()
        ]

    @staticmethod
    def _transferencias(
        db: Session,
        account_ids: List[int],
        desde: Optional[datetime],
        ate: Optional[datetime],
    ) -> List[CashMovement]:
        """As duas pernas da transferência, cada uma na moeda da SUA conta.

        Uma linha na tabela vira até dois movimentos aqui — um por conta envolvida
        —, e é isso que faz a transferência entre duas contas minhas se anular no
        total sem nunca aparecer como entrada ou saída de caixa.
        """
        alvo = set(account_ids)
        consulta = select(AccountTransfer).where(AccountTransfer.deleted_at.is_(None))
        consulta = consulta.where(
            AccountTransfer.from_account_id.in_(account_ids)
            | AccountTransfer.to_account_id.in_(account_ids)
        )
        if desde is not None:
            consulta = consulta.where(AccountTransfer.occurred_at >= desde)
        if ate is not None:
            consulta = consulta.where(AccountTransfer.occurred_at <= ate)

        movimentos: List[CashMovement] = []
        for t in db.exec(consulta).all():
            dia = local_day(t.occurred_at)
            if t.from_account_id in alvo:
                movimentos.append(
                    CashMovement(
                        source=SOURCE_TRANSFER_OUT, direction="out", occurred_on=dia,
                        currency="", amount=-(t.from_amount or ZERO), converted=None,
                        reference_id=t.id, title=t.note or "Transferência enviada",
                        account_id=t.from_account_id,
                    )
                )
            if t.to_account_id in alvo:
                movimentos.append(
                    CashMovement(
                        source=SOURCE_TRANSFER_IN, direction="in", occurred_on=dia,
                        currency="", amount=(t.to_amount or ZERO), converted=None,
                        reference_id=t.id, title=t.note or "Transferência recebida",
                        account_id=t.to_account_id,
                    )
                )
        return movimentos

    # ---- Saldo ---------------------------------------------------------------

    @staticmethod
    def _sinal(mov: CashMovement) -> Decimal:
        """O quanto este movimento soma ao saldo, com sinal.

        Abertura, ajuste e transferência já trazem o valor assinado (podem ser
        negativos por natureza); as seis fontes de caixa trazem valor positivo e a
        direção separada. Uma função só decide, para nenhum chamador ter de lembrar
        de qual convenção é qual.
        """
        valor = mov.amount or ZERO
        if mov.source in LEDGER_ONLY_SOURCES:
            return valor
        return valor if mov.direction == "in" else -valor

    @staticmethod
    def balances(db: Session, user_id: int) -> Dict[str, Any]:
        """Saldo de cada conta da pessoa + o total na moeda de relatório.

        Uma varredura só do ledger, agrupada em memória: seis consultas de caixa
        mais duas do ledger próprio, independentemente de quantas contas existam.
        A alternativa — um laço chamando o cálculo por conta — daria 8×N.
        """
        from app.domain.query_policy import user_report_currency

        contas = AccountBalanceService.contas_da_pessoa(db, user_id)
        ids = [c.id for c in contas]
        aberturas = AccountBalanceService.aberturas(db, ids)
        # UMA varredura do caixa, reaproveitada pelas duas leituras abaixo.
        caixa = AccountBalanceService.movimentos_de_caixa(db, user_id)
        movimentos = AccountBalanceService.movimentos(db, user_id, ids, caixa=caixa)

        # Movimento de caixa SEM conta declarada: não mexe em saldo nenhum, e é
        # legítimo. O que não pode é ser mudo — este é o contador que a tela mostra
        # para a pessoa poder atribuir o que faltou. Só a partir da abertura mais
        # antiga: antes dela nenhum movimento contaria de qualquer forma, e avisar
        # sobre eles seria pedir uma ação que não muda nada.
        corte_geral = min(
            (local_day(e.occurred_at) for e in aberturas.values()), default=None
        )
        sem_conta = 0
        if corte_geral is not None:
            sem_conta = sum(
                1
                for m in caixa
                if m.account_id is None and m.occurred_on >= corte_geral
            )

        por_conta: Dict[int, List[CashMovement]] = {}
        for m in movimentos:
            por_conta.setdefault(m.account_id, []).append(m)

        saldos: List[AccountBalance] = []
        antes_da_abertura = 0
        for conta in contas:
            abertura = aberturas.get(conta.id)
            linhas = por_conta.get(conta.id, [])
            if abertura is None:
                # Sem abertura não há saldo — e não há corte, então nem faz sentido
                # contar "movimento anterior". A conta aparece pedindo o número.
                saldos.append(AccountBalance(
                    account_id=conta.id, name=conta.name, type=conta.type.value,
                    currency=conta.currency, active=conta.active,
                    is_default=conta.is_default,
                    opening_amount=None, opening_on=None, balance=None,
                    movements_counted=0,
                ))
                continue

            corte = local_day(abertura.occurred_at)
            total = ZERO
            contados = 0
            for m in linhas:
                if m.occurred_on < corte:
                    # Já está DENTRO do saldo informado — contá-lo o dobraria.
                    antes_da_abertura += 1
                    continue
                if m.source == SOURCE_OPENING_BALANCE:
                    continue  # somado abaixo, uma vez só
                total += AccountBalanceService._sinal(m)
                contados += 1

            saldos.append(AccountBalance(
                account_id=conta.id, name=conta.name, type=conta.type.value,
                currency=conta.currency, active=conta.active,
                is_default=conta.is_default,
                opening_amount=abertura.amount, opening_on=corte,
                balance=(abertura.amount or ZERO) + total,
                movements_counted=contados,
            ))

        destino = user_report_currency(db, user_id)
        total_geral, excluidos = AccountBalanceService._total(db, saldos, destino)

        return {
            "currency": destino,
            "total": total_geral,
            "accounts": [s.__dict__ for s in saldos],
            "excluded_foreign_count": excluidos,
            "unassigned_movements": sem_conta,
            "movements_before_opening": antes_da_abertura,
            "accounts_without_opening": sum(1 for s in saldos if s.balance is None),
        }

    @staticmethod
    def _total(db: Session, saldos: List[AccountBalance], destino: str) -> tuple:
        """Soma os saldos na moeda de relatório: `(total, quantos ficaram de fora)`.

        **Pela cotação de HOJE, não pela data de cada movimento.** Saldo é estoque,
        não fluxo: somar movimento a movimento pela taxa do dia de cada um daria um
        "saldo a custo histórico" que banco nenhum mostra e que ninguém consegue
        conferir. A verdade de cada conta é o número na moeda dela; o total é
        conveniência, e a tela o rotula como tal.

        O que não converte não vira zero (ADR 0006) — fica de fora e é contado.
        `None` no total inteiro quando NENHUMA conta tem saldo configurado, porque
        aí não há total, e não um total de zero.
        """
        from app.domain.dates import today_local

        hoje = today_local()
        com_saldo = [s for s in saldos if s.balance is not None]
        if not com_saldo:
            return None, 0
        total = ZERO
        excluidos = 0
        for s in com_saldo:
            convertido = converte(db, s.balance, s.currency, destino, hoje)
            if convertido is None:
                excluidos += 1
            else:
                total += convertido
        return total, excluidos

    # ---- Extrato -------------------------------------------------------------

    @staticmethod
    def statement(
        db: Session,
        user_id: int,
        conta: PaymentAccount,
        *,
        desde: Optional[datetime] = None,
        ate: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        """O extrato da conta com SALDO CORRENTE linha a linha.

        É a resposta da última pergunta do pedido — *"por que o saldo atual é
        exatamente esse valor?"*. Cada linha traz o quanto somou e quanto o saldo
        passou a ser depois dela, então o número do topo é rastreável até a
        abertura sem ninguém ter de refazer conta.

        O saldo corrente parte SEMPRE da abertura, mesmo quando a janela pedida
        começa depois: um extrato de setembro que começasse do zero mostraria uma
        coluna de saldo que não é o saldo.

        **Sem abertura não há coluna de saldo.** `running_balance` vem `None` em
        toda linha, e não uma soma a partir de zero: um extrato que começa em
        "R$ 0,00" AFIRMA que a conta estava zerada, e ninguém disse isso. É o
        mesmo falso zero que a tela de Contas evita ao pedir o saldo inicial em
        vez de exibir um número — os movimentos continuam listados, porque eles
        aconteceram; o que não se sabe é o saldo.
        """
        abertura = AccountBalanceService.aberturas(db, [conta.id]).get(conta.id)
        todos = AccountBalanceService.movimentos(db, user_id, [conta.id], ate=ate)

        corte = local_day(abertura.occurred_at) if abertura else None
        inicio_janela = local_day(desde) if desde else None

        corrente = ZERO
        linhas: List[Dict[str, Any]] = []
        for m in todos:
            if corte is not None and m.occurred_on < corte:
                continue
            corrente += AccountBalanceService._sinal(m)
            if inicio_janela is not None and m.occurred_on < inicio_janela:
                # Fora da janela pedida, mas JÁ somado ao corrente: é assim que a
                # primeira linha exibida mostra o saldo certo.
                continue
            linhas.append({
                "occurred_on": m.occurred_on,
                "source": m.source,
                "title": m.title,
                "amount": AccountBalanceService._sinal(m),
                "running_balance": corrente if abertura else None,
                "reference_id": m.reference_id,
                "workspace_id": m.workspace_id,
            })

        return {
            "account_id": conta.id,
            "account_name": conta.name,
            "currency": conta.currency,
            "opening_amount": abertura.amount if abertura else None,
            "opening_on": corte,
            "balance": corrente if abertura else None,
            "entries": linhas,
        }

    # ---- Escrita -------------------------------------------------------------

    @staticmethod
    def saldo_em(db: Session, user_id: int, conta: PaymentAccount, quando: date) -> Optional[Decimal]:
        """O saldo da conta ao FIM do dia `quando` — a base do ajuste.

        `None` quando não há abertura: sem ponto de partida não há saldo a conciliar,
        e o app pede o saldo inicial em vez de inventar um.
        """
        abertura = AccountBalanceService.aberturas(db, [conta.id]).get(conta.id)
        if abertura is None:
            return None
        corte = local_day(abertura.occurred_at)
        total = ZERO
        for m in AccountBalanceService.movimentos(db, user_id, [conta.id]):
            if m.occurred_on < corte or m.occurred_on > quando:
                continue
            if m.source == SOURCE_OPENING_BALANCE:
                continue
            total += AccountBalanceService._sinal(m)
        return (abertura.amount or ZERO) + total

    @staticmethod
    def tem_movimento(db: Session, account_id: int) -> bool:
        """A conta já foi usada em algum movimento? (barreira de exclusão/moeda)

        Consulta de existência, não de soma: o chamador só quer saber se mexer no
        cadastro reescreveria história.
        """
        from app.models.credit_card import StatementPayment
        from app.models.financing import AmortizationInstallment
        from app.models.income import Income
        from app.models.settlement import Settlement
        from app.models.transaction import TransactionPayer

        checagens = (
            select(TransactionPayer.id).where(TransactionPayer.account_id == account_id),
            select(StatementPayment.id).where(StatementPayment.account_id == account_id),
            select(Income.id).where(Income.account_id == account_id),
            select(AmortizationInstallment.id).where(
                AmortizationInstallment.account_id == account_id
            ),
            select(Settlement.id).where(
                (Settlement.from_account_id == account_id)
                | (Settlement.to_account_id == account_id)
            ),
            select(AccountEntry.id).where(AccountEntry.account_id == account_id),
            select(AccountTransfer.id).where(
                (AccountTransfer.from_account_id == account_id)
                | (AccountTransfer.to_account_id == account_id)
            ),
        )
        return any(db.exec(c.limit(1)).first() is not None for c in checagens)

    @staticmethod
    def define_abertura(
        db: Session,
        conta: PaymentAccount,
        *,
        amount: Decimal,
        as_of: date,
        user_id: int,
    ) -> AccountEntry:
        """Cria ou reescreve a abertura da conta. Não faz commit (ADR 0010).

        Reescrever é permitido — quem digitou o saldo errado no primeiro dia tem de
        poder corrigir — e é auditável pelos listeners de mapper, que gravam o
        `AuditLog` do UPDATE sozinhos. O que NÃO se faz por aqui é conciliar: para
        "o banco mostra outro número hoje" existe o ajuste, que cria uma linha
        datada em vez de mudar o passado.
        """
        from app.domain.dates import civil_instant

        atual = AccountBalanceService.aberturas(db, [conta.id]).get(conta.id)
        quando = civil_instant(as_of)
        if atual is not None:
            atual.amount = amount
            atual.occurred_at = quando
            atual.updated_at = datetime.now(UTC)
            db.add(atual)
            return atual
        nova = AccountEntry(
            account_id=conta.id,
            kind=AccountEntryKind.opening_balance,
            amount=amount,
            occurred_at=quando,
            description="Saldo inicial",
            created_by_user_id=user_id,
        )
        db.add(nova)
        return nova
