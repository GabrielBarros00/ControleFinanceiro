"""Movimentos de CAIXA: pagar fatura, transferir entre contas e conciliar saldo.

São as escritas que mexem no saldo das contas (ADR 0034), por isso ficam sob o
escopo próprio `accounts.write` — dá para conectar um agente que registra
despesas sem dar a ele o poder de mover dinheiro entre contas.

Todas criam algo novo, então todas exigem `idempotency_key`: um "pague a fatura"
repetido por timeout não pode virar dois pagamentos.
"""
from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import List, Optional

from fastapi import HTTPException
from pydantic import BaseModel, Field, model_validator
from sqlmodel import select

from app.domain.dates import civil_instant, local_day, today_local
from app.mcp import resolve
from app.mcp.dates import CivilDate, MonthKey
from app.mcp.errors import ErrorCode, McpToolError
from app.mcp.money import MoneyIn, MoneyOut, SignedMoneyIn, fmt_brl
from app.mcp.ui import WIDGET_URI as WIDGET
from app.mcp.registry import ToolCall, ToolInput, ToolOutput, tool
from app.mcp.schemas import Ref
from app.mcp.serializers import app_url, civil
from app.mcp.tools.ledger import TransferOut, transfer_out
from app.mcp.tools.statements import PaymentLine, card_or_only, payment_lines
from app.mcp.writes import IdempotencyKey
from app.models.account_ledger import AccountEntry, AccountTransfer
from app.models.credit_card import CardStatement, CreditCard, StatementPayment, StatementStatus
from app.models.payment_account import PaymentAccount
from app.schemas.balance import AdjustmentRequest, TransferCreate
from app.schemas.common import DESCRIPTION_MAX
from app.services.commands import accounts as acc_cmd
from app.services.commands import statements as stmt_cmd
from app.services.credit_card_service import CreditCardService
from app.services.oauth import scopes as escopos


def _conta(call: ToolCall, account_id: Optional[int], account: Optional[str], campo: str) -> PaymentAccount:
    conta = resolve.resolve_account(call.session, call.identity.user_id, account_id=account_id, account=account)
    if conta is None:
        raise McpToolError(ErrorCode.VALIDATION_ERROR, f"Informe {campo} (nome da conta) ou {campo}_id.")
    return conta


# --- statements_pay --------------------------------------------------------------

class PayIn(ToolInput):
    idempotency_key: IdempotencyKey
    card: Optional[str] = Field(None, max_length=120, description="Cartão (nome). Omitido: seu único cartão.")
    card_id: Optional[int] = None
    month: Optional[MonthKey] = Field(
        None, description="Mês da fatura (YYYY-MM). Omitido: a única fatura fechada com saldo em aberto.",
    )
    amount: Optional[MoneyIn] = Field(None, description="Valor pago. Omitido = o saldo inteiro da fatura.")
    account: Optional[str] = Field(None, max_length=120, description="Conta de onde saiu o dinheiro.")
    account_id: Optional[int] = None
    paid_on: Optional[CivilDate] = Field(None, description="Dia do pagamento. Omitido = hoje.")
    note: Optional[str] = Field(None, max_length=DESCRIPTION_MAX)


class PayOut(BaseModel):
    card: Ref
    month: str
    payment_id: int
    amount_paid: MoneyOut
    currency: str
    status: str = Field(description="closed (ainda há saldo) | paid (quitada).")
    total: MoneyOut
    paid: MoneyOut
    balance: MoneyOut
    due_date: dt.date
    account: Optional[Ref] = None
    closed_now: bool = Field(False, description="true = a fatura estava aberta com o ciclo já encerrado e foi fechada agora.")
    replayed: bool = False
    app_url: str


def _fecha_se_o_ciclo_acabou(call: ToolCall, fatura: CardStatement, cartao) -> bool:
    """Fatura ainda `open` com o fechamento no passado: fecha antes de pagar.

    No app, fechar é um clique separado; pelo agente, "paguei a fatura" já diz que
    o ciclo acabou. Fechar ANTES da data não — pagamento antecipado de fatura em
    curso fica para o app, onde a pessoa vê o total ainda mudando.
    """
    if fatura.status != StatementStatus.open:
        return False
    fechamento = civil(fatura.closing_date)
    if fechamento > today_local():
        raise McpToolError(
            ErrorCode.BUSINESS_RULE_VIOLATION,
            f"A fatura {fatura.month} do {cartao.name} ainda está em curso (fecha em "
            f"{fechamento.strftime('%d/%m/%Y')}). Pagamento antecipado deve ser registrado no app.",
        )
    try:
        return stmt_cmd.fechar_se_o_ciclo_acabou(call.session, fatura, today_local())
    except HTTPException as exc:
        raise McpToolError(ErrorCode.CONFLICT, str(exc.detail))


def _fatura_a_pagar(call: ToolCall, cartao, mes: Optional[str]) -> CardStatement:
    if mes:
        fatura = call.session.exec(
            select(CardStatement).where(CardStatement.card_id == cartao.id, CardStatement.month == mes)
        ).first()
        if fatura is None:
            raise McpToolError(ErrorCode.NOT_FOUND, f"Não há fatura de {mes} no {cartao.name}.", details={"month": mes})
        return fatura
    hoje = today_local()
    candidatas = [
        f for f in call.session.exec(
            select(CardStatement)
            .where(
                CardStatement.card_id == cartao.id,
                CardStatement.status.in_([StatementStatus.closed, StatementStatus.open]),
            )
            .order_by(CardStatement.month)
        ).all()
        if f.status == StatementStatus.closed or civil(f.closing_date) <= hoje
    ]
    saldos = CreditCardService.balances(call.session, cartao, candidatas)
    fechadas = [f for f in candidatas if saldos[f.id] > 0]
    if len(fechadas) == 1:
        return fechadas[0]
    if not fechadas:
        raise McpToolError(
            ErrorCode.NOT_FOUND,
            f"O {cartao.name} não tem fatura com ciclo encerrado e saldo a pagar (a do ciclo em curso só depois de fechar).",
        )
    raise McpToolError(
        ErrorCode.AMBIGUOUS,
        "Há mais de uma fatura fechada em aberto. Pergunte ao usuário qual pagar e informe `month`.",
        candidates=[
            {"id": f.id, "name": f.month, "balance": str(saldos[f.id]),
             "due_date": civil(f.due_date).isoformat()}
            for f in fechadas
        ],
        details={"kind": "fatura", "id_param": "month"},
    )


def _pay_out(call: ToolCall, fatura: CardStatement, pagamento: StatementPayment, *, replayed: bool = False) -> PayOut:
    cartao = call.session.get(CreditCard, fatura.card_id)
    conta = call.session.get(PaymentAccount, pagamento.account_id) if pagamento.account_id else None
    return PayOut(
        card=Ref(id=cartao.id, name=cartao.name),
        month=fatura.month,
        payment_id=pagamento.id,
        amount_paid=pagamento.amount,
        currency=cartao.currency,
        status=getattr(fatura.status, "value", fatura.status),
        total=CreditCardService.effective_total(call.session, fatura),
        paid=CreditCardService.paid_amount(call.session, fatura),
        balance=CreditCardService.statement_balance(call.session, fatura),
        due_date=civil(fatura.due_date),
        account=Ref(id=conta.id, name=conta.name) if conta else None,
        replayed=replayed,
        app_url=app_url("/me/cards"),
    )


def _replay_pay(call: ToolCall, ref: dict) -> ToolOutput:
    pagamento = call.session.get(StatementPayment, int(ref["payment_id"]))
    fatura = call.session.get(CardStatement, pagamento.statement_id) if pagamento else None
    if pagamento is None or fatura is None:
        raise McpToolError(ErrorCode.CONFLICT, "Operação já processada com esta idempotency_key.")
    # Mesmo dono: o cartão da fatura tem de ser de quem chama.
    card_or_only(call, fatura.card_id, None)
    saida = _pay_out(call, fatura, pagamento, replayed=True)
    return ToolOutput(
        structured=saida,
        summary=f"Este pagamento já tinha sido registrado (mesma idempotency_key). Saldo da fatura: {fmt_brl(saida.balance, saida.currency)}.",
        entity_type="statement",
        entity_ids=[fatura.id],
    )


@tool(
    name="statements_pay",
    title="Pagar fatura do cartão",
    description=(
        "Registra o pagamento (total ou parcial) de uma fatura do cartão de crédito cujo ciclo já "
        "fechou, com a conta de onde o dinheiro saiu. Não é despesa: as compras já estão na fatura.\n"
        "Use quando: o usuário disser que pagou a fatura (\"paguei a fatura do Nubank\", \"paguei "
        "R$ 500 da fatura de setembro pelo Itaú\").\n"
        "Não use quando: for uma compra no cartão (transactions_create) ou a fatura ainda estiver "
        "em curso (antes da data de fechamento). Fatura com o ciclo encerrado e ainda aberta no app "
        "é fechada e paga na mesma operação.\n"
        "Sem `amount`, paga o saldo inteiro. Pagamento acima do saldo é recusado."
    ),
    input_model=PayIn,
    output_model=PayOut,
    scope=escopos.ACCOUNTS_WRITE,
    kind="write",
    read_only=False,
    destructive=False,
    idempotent=True,
    cost=3,
    idempotency_key=True,
    replay=_replay_pay,
    invoking="Registrando o pagamento…",
    invoked="Pagamento registrado",
    examples=({"idempotency_key": "c7d1e2f3-0001", "card": "Nubank", "month": "2026-09", "account": "Itaú"},),
    ui=WIDGET,
    app_callable=True,
    meta={"openai/widgetDescription": "O componente mostra o resultado com as ações possíveis (desfazer, editar). Confirme em uma frase, sem repetir os números."},
)
def statements_pay(call: ToolCall) -> ToolOutput:
    a: PayIn = call.args
    me = call.identity.user_id
    cartao = card_or_only(call, a.card_id, a.card)
    fatura = _fatura_a_pagar(call, cartao, a.month)
    conta = resolve.resolve_account(call.session, me, account_id=a.account_id, account=a.account)
    fechou_agora = _fecha_se_o_ciclo_acabou(call, fatura, cartao)
    stmt_cmd.pay_statement(
        call.session, me, cartao.id, fatura.id,
        account_id=conta.id if conta else None,
        amount=a.amount,
        paid_at=civil_instant(a.paid_on) if a.paid_on else None,
        note=a.note,
    )
    call.session.flush()
    pagamento = call.session.exec(
        select(StatementPayment)
        .where(StatementPayment.statement_id == fatura.id)
        .order_by(StatementPayment.id.desc())
    ).first()
    call.session.refresh(fatura)
    saida = _pay_out(call, fatura, pagamento)
    saida.closed_now = fechou_agora
    resumo = ("Fatura fechada (o ciclo já tinha terminado) e " if fechou_agora else "") + (
        f"pagamento de {fmt_brl(saida.amount_paid, saida.currency)} registrado na fatura {saida.month} do "
        f"{cartao.name}. Saldo restante: {fmt_brl(saida.balance, saida.currency)}."
    )
    return ToolOutput(
        structured=saida,
        summary=resumo,
        entity_type="statement",
        entity_ids=[fatura.id],
        result_ref={"payment_id": pagamento.id},
    )


# --- transfers_create -------------------------------------------------------------

class TransferIn(ToolInput):
    idempotency_key: IdempotencyKey
    from_account: Optional[str] = Field(None, max_length=120, description="Conta de origem (nome).")
    from_account_id: Optional[int] = None
    to_account: Optional[str] = Field(None, max_length=120, description="Conta de destino (nome).")
    to_account_id: Optional[int] = None
    amount: MoneyIn = Field(description="Valor que SAIU da conta de origem.")
    to_amount: Optional[MoneyIn] = Field(
        None, description="Só entre moedas diferentes: quanto ENTROU no destino (o app não converte sozinho).",
    )
    date: Optional[CivilDate] = Field(None, description="Dia da transferência. Omitido = hoje.")
    note: Optional[str] = Field(None, max_length=DESCRIPTION_MAX)

    @model_validator(mode="after")
    def _pares(self):
        for a, b in (("from_account", "from_account_id"), ("to_account", "to_account_id")):
            if getattr(self, a) is not None and getattr(self, b) is not None:
                raise ValueError(f"informe {a} ou {b}, não os dois")
        return self


_transfer_out = transfer_out


def _replay_transfer(call: ToolCall, ref: dict) -> ToolOutput:
    t = call.session.get(AccountTransfer, int(ref["transfer_id"]))
    if t is None or t.created_by_user_id != call.identity.user_id:
        raise McpToolError(ErrorCode.CONFLICT, "Operação já processada com esta idempotency_key.")
    saida = _transfer_out(call, t, replayed=True)
    return ToolOutput(
        structured=saida,
        summary="Esta transferência já tinha sido registrada (mesma idempotency_key); nada novo foi feito.",
        entity_type="transfer",
        entity_ids=[t.id],
    )


@tool(
    name="transfers_create",
    title="Transferir entre contas",
    description=(
        "Registra dinheiro que passou de uma conta sua para outra conta sua (ex.: da conta corrente "
        "para a poupança). Não é despesa nem renda: só move saldo.\n"
        "Use quando: o usuário disser que transferiu/moveu dinheiro entre as próprias contas.\n"
        "Não use quando: pagar alguém (transactions_create), quitar dívida com outra pessoa "
        "(settlements_create) ou pagar fatura (statements_pay).\n"
        "Contas em moedas diferentes exigem `to_amount` (quanto entrou): o app não inventa câmbio."
    ),
    input_model=TransferIn,
    output_model=TransferOut,
    scope=escopos.ACCOUNTS_WRITE,
    kind="write",
    read_only=False,
    destructive=False,
    idempotent=True,
    cost=3,
    idempotency_key=True,
    replay=_replay_transfer,
    invoking="Registrando a transferência…",
    invoked="Transferência registrada",
    examples=({"idempotency_key": "c7d1e2f3-0002", "from_account": "Itaú", "to_account": "Poupança", "amount": "500.00"},),
    ui=WIDGET,
    app_callable=True,
    meta={"openai/widgetDescription": "O componente mostra o resultado com as ações possíveis (desfazer, editar). Confirme em uma frase, sem repetir os números."},
)
def transfers_create(call: ToolCall) -> ToolOutput:
    a: TransferIn = call.args
    origem = _conta(call, a.from_account_id, a.from_account, "from_account")
    destino = _conta(call, a.to_account_id, a.to_account, "to_account")
    transferencia, _, _ = acc_cmd.create_transfer(call.session, call.identity.user_id, TransferCreate(
        from_account_id=origem.id,
        to_account_id=destino.id,
        from_amount=a.amount,
        to_amount=a.to_amount,
        occurred_on=a.date,
        note=a.note,
    ))
    saida = _transfer_out(call, transferencia)
    return ToolOutput(
        structured=saida,
        summary=(
            f"Transferência de {fmt_brl(saida.from_amount, saida.from_currency)} de {origem.name} para "
            f"{destino.name} em {saida.date.strftime('%d/%m/%Y')}."
        ),
        entity_type="transfer",
        entity_ids=[transferencia.id],
        result_ref={"transfer_id": transferencia.id},
    )


# --- accounts_adjust_balance ----------------------------------------------------------

class AdjustIn(ToolInput):
    idempotency_key: IdempotencyKey
    account: Optional[str] = Field(None, max_length=120, description="Conta (nome).")
    account_id: Optional[int] = None
    real_balance: SignedMoneyIn = Field(description="O saldo REAL que o banco mostra (não a diferença).")
    date: Optional[CivilDate] = Field(None, description="Dia a que o saldo real se refere. Omitido = hoje.")
    note: Optional[str] = Field(None, max_length=DESCRIPTION_MAX, description="Motivo (aparece no extrato).")

    @model_validator(mode="after")
    def _par(self):
        if self.account is not None and self.account_id is not None:
            raise ValueError("informe account ou account_id, não os dois")
        return self


class AdjustOut(BaseModel):
    id: int
    account: Ref
    currency: str
    date: dt.date
    previous_balance: MoneyOut = Field(description="Saldo que o app calculava antes do ajuste.")
    new_balance: MoneyOut
    adjustment: MoneyOut = Field(description="Diferença lançada como linha de ajuste no extrato.")
    replayed: bool = False


def _replay_adjust(call: ToolCall, ref: dict) -> ToolOutput:
    entrada = call.session.get(AccountEntry, int(ref["entry_id"]))
    conta = call.session.get(PaymentAccount, entrada.account_id) if entrada else None
    if entrada is None or conta is None or conta.owner_user_id != call.identity.user_id:
        raise McpToolError(ErrorCode.CONFLICT, "Operação já processada com esta idempotency_key.")
    novo = Decimal(call.args.real_balance)
    saida = AdjustOut(
        id=entrada.id, account=Ref(id=conta.id, name=conta.name), currency=conta.currency,
        date=local_day(entrada.occurred_at), previous_balance=novo - entrada.amount, new_balance=novo,
        adjustment=entrada.amount, replayed=True,
    )
    return ToolOutput(
        structured=saida,
        summary="Este ajuste já tinha sido registrado (mesma idempotency_key); nada novo foi feito.",
        entity_type="account",
        entity_ids=[conta.id],
    )


@tool(
    name="accounts_adjust_balance",
    title="Conciliar saldo da conta",
    description=(
        "Acerta o saldo de uma conta com o que o banco mostra: você informa o saldo REAL e o app "
        "lança a diferença como uma linha de ajuste datada (não é renda nem despesa e não reescreve "
        "o passado).\n"
        "Use quando: o usuário disser \"o banco mostra R$ 4.900, o app diz outra coisa\" ou pedir para "
        "conciliar o saldo. Confira antes com accounts_list e mostre a diferença ao usuário.\n"
        "Não use quando: faltar lançar despesas/rendas específicas — registre-as, que o saldo fecha sozinho."
    ),
    input_model=AdjustIn,
    output_model=AdjustOut,
    scope=escopos.ACCOUNTS_WRITE,
    kind="write",
    read_only=False,
    destructive=False,
    idempotent=True,
    cost=3,
    idempotency_key=True,
    replay=_replay_adjust,
    invoking="Conciliando o saldo…",
    invoked="Saldo conciliado",
    examples=({"idempotency_key": "c7d1e2f3-0003", "account": "Itaú", "real_balance": "4900.00"},),
    ui=WIDGET,
    app_callable=True,
    meta={"openai/widgetDescription": "O componente mostra o resultado com as ações possíveis (desfazer, editar). Confirme em uma frase, sem repetir os números."},
)
def accounts_adjust_balance(call: ToolCall) -> ToolOutput:
    a: AdjustIn = call.args
    conta = _conta(call, a.account_id, a.account, "account")
    feito = acc_cmd.adjust_balance(call.session, call.identity.user_id, conta.id, AdjustmentRequest(
        real_balance=a.real_balance, occurred_on=a.date or today_local(), note=a.note,
    ))
    saida = AdjustOut(
        id=feito["id"], account=Ref(id=conta.id, name=conta.name), currency=conta.currency,
        date=feito["occurred_on"], previous_balance=feito["previous_balance"], new_balance=feito["new_balance"],
        adjustment=feito["amount"],
    )
    return ToolOutput(
        structured=saida,
        summary=(
            f"Saldo de {conta.name} ajustado de {fmt_brl(saida.previous_balance, conta.currency)} para "
            f"{fmt_brl(saida.new_balance, conta.currency)} (ajuste de {fmt_brl(saida.adjustment, conta.currency)})."
        ),
        entity_type="account",
        entity_ids=[conta.id],
        result_ref={"entry_id": feito["id"]},
    )


# --- transfers_delete --------------------------------------------------------------------

class TransferDeleteIn(ToolInput):
    transfer_id: int = Field(ge=1)


class TransferDeleteOut(BaseModel):
    deleted: TransferOut = Field(description="Como a transferência estava (para refazer com transfers_create, se preciso).")


@tool(
    name="transfers_delete",
    title="Desfazer transferência",
    description=(
        "Desfaz uma transferência entre suas contas: as duas pernas (saída e entrada) somem juntas, e "
        "os saldos voltam ao que eram.\n"
        "Use quando: o usuário disser que uma transferência estava errada ou foi registrada duas vezes "
        "(pegue o id em transfers_list e confirme qual).\n"
        "Não use quando: quiser corrigir o valor — desfaça e registre de novo (transfers_create)."
    ),
    input_model=TransferDeleteIn,
    output_model=TransferDeleteOut,
    scope=escopos.ACCOUNTS_WRITE,
    kind="destructive",
    read_only=False,
    destructive=True,
    idempotent=True,
    cost=3,
    invoking="Desfazendo a transferência…",
    invoked="Transferência desfeita",
    examples=({"transfer_id": 5},),
    ui=WIDGET,
    app_callable=True,
    meta={"openai/widgetDescription": "O componente mostra o resultado com as ações possíveis (desfazer, editar). Confirme em uma frase, sem repetir os números."},
)
def transfers_delete(call: ToolCall) -> ToolOutput:
    a: TransferDeleteIn = call.args
    t = call.session.get(AccountTransfer, a.transfer_id)
    origem = call.session.get(PaymentAccount, t.from_account_id) if t else None
    if t is None or t.deleted_at is not None or origem is None or origem.owner_user_id != call.identity.user_id:
        raise McpToolError(ErrorCode.NOT_FOUND, "Transferência não encontrada.", details={"transfer_id": a.transfer_id})
    antes = transfer_out(call, t)
    acc_cmd.delete_transfer(call.session, call.identity.user_id, t.id)
    return ToolOutput(
        structured=TransferDeleteOut(deleted=antes),
        summary=(
            f"Transferência desfeita: {fmt_brl(antes.from_amount, antes.from_currency)} de "
            f"{antes.from_account.name} para {antes.to_account.name} em {antes.date.strftime('%d/%m/%Y')}."
        ),
        entity_type="transfer",
        entity_ids=[t.id],
    )


# --- statements_reopen --------------------------------------------------------------------

class ReopenIn(ToolInput):
    card: Optional[str] = Field(None, max_length=120, description="Cartão (nome). Omitido: seu único cartão.")
    card_id: Optional[int] = None
    month: MonthKey = Field(description="Mês da fatura (YYYY-MM).")


class ReopenOut(BaseModel):
    card: Ref
    month: str
    previous_status: str
    status: str = Field(description="closed (paga → fechada, pagamentos estornados) | open (fechada → aberta).")
    reversed_payments: List[PaymentLine] = Field(description="Pagamentos estornados (o dinheiro volta às contas).")
    balance: MoneyOut
    currency: str


@tool(
    name="statements_reopen",
    title="Estornar pagamento de fatura",
    description=(
        "Estorna os pagamentos de uma fatura, como o botão \"Reabrir\" do app: os pagamentos somem, o "
        "dinheiro volta às contas e a fatura volta um passo (paga → fechada; fechada com pagamento "
        "parcial → aberta). Sem pagamento na fatura, não faz nada.\n"
        "Use quando: o usuário disser que um pagamento de fatura foi registrado errado ou em dobro.\n"
        "Não use quando: quiser pagar (statements_pay) ou só ver os pagamentos (statements_get)."
    ),
    input_model=ReopenIn,
    output_model=ReopenOut,
    scope=escopos.ACCOUNTS_WRITE,
    kind="destructive",
    read_only=False,
    destructive=True,
    idempotent=True,
    cost=3,
    invoking="Estornando…",
    invoked="Fatura reaberta",
    examples=({"card": "Nubank", "month": "2026-09"},),
    ui=WIDGET,
    app_callable=True,
    meta={"openai/widgetDescription": "O componente mostra o resultado com as ações possíveis (desfazer, editar). Confirme em uma frase, sem repetir os números."},
)
def statements_reopen(call: ToolCall) -> ToolOutput:
    a: ReopenIn = call.args
    cartao = card_or_only(call, a.card_id, a.card)
    fatura = call.session.exec(
        select(CardStatement).where(CardStatement.card_id == cartao.id, CardStatement.month == a.month)
    ).first()
    if fatura is None:
        raise McpToolError(ErrorCode.NOT_FOUND, f"Não há fatura de {a.month} no {cartao.name}.", details={"month": a.month})
    antes = getattr(fatura.status, "value", fatura.status)
    estornados = payment_lines(call, fatura)
    # Só estorna o que existe: sem pagamento vivo, repetir a chamada (retry de rede)
    # não pode andar mais um passo no ciclo e reabrir a fatura.
    if not estornados:
        return ToolOutput(
            structured=ReopenOut(
                card=Ref(id=cartao.id, name=cartao.name), month=fatura.month, previous_status=antes, status=antes,
                reversed_payments=[], balance=CreditCardService.statement_balance(call.session, fatura),
                currency=cartao.currency,
            ),
            summary=f"A fatura {fatura.month} do {cartao.name} não tem pagamento a estornar.",
            entity_type="statement",
            entity_ids=[fatura.id],
        )
    try:
        stmt_cmd.reopen_statement(call.session, call.identity.user_id, cartao.id, fatura.id)
    except HTTPException as exc:
        raise McpToolError(ErrorCode.CONFLICT, str(exc.detail))
    call.session.flush()
    saida = ReopenOut(
        card=Ref(id=cartao.id, name=cartao.name),
        month=fatura.month,
        previous_status=antes,
        status=getattr(fatura.status, "value", fatura.status),
        reversed_payments=estornados,
        balance=CreditCardService.statement_balance(call.session, fatura),
        currency=cartao.currency,
    )
    resumo = f"Fatura {fatura.month} do {cartao.name}: {antes} → {saida.status}"
    if estornados:
        total = sum((p.amount for p in estornados), Decimal("0"))
        resumo += f"; {len(estornados)} pagamento(s) estornado(s) ({fmt_brl(total, cartao.currency)})"
    return ToolOutput(
        structured=saida,
        summary=resumo + ".",
        entity_type="statement",
        entity_ids=[fatura.id],
    )
