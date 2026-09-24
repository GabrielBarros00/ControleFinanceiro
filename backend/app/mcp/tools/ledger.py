"""Extrato: de onde veio cada número do saldo (`accounts_statement`, `transfers_list`).

O relatório de lacunas do ChatGPT pediu isto primeiro: o agente registrava
despesas, rendas, transferências, pagamentos de fatura e ajustes, e não tinha como
explicar como o saldo da conta chegou ao valor atual. O app já tem as duas
respostas, e elas são reaproveitadas sem regra nova:

- **Com conta**: `AccountBalanceService.statement`, o extrato da tela Contas, com
  SALDO CORRENTE linha a linha a partir da abertura (sem abertura, sem saldo: um
  extrato que começa em R$ 0,00 afirmaria que a conta estava zerada).
- **Sem conta**: `OverviewService.get_ledger`, o caixa do mês — as linhas que
  compõem o "entrou/saiu" do Seu mês, na moeda de relatório.
"""
from __future__ import annotations

import datetime as dt
from typing import List, Literal, Optional

from pydantic import BaseModel, Field, model_validator
from sqlmodel import select

from app.domain.dates import local_day, month_bounds_utc, parse_month, today_local
from app.mcp import resolve
from app.mcp.dates import MonthKey
from app.mcp.errors import ErrorCode, McpToolError
from app.mcp.money import MoneyOut, fmt_brl
from app.mcp.registry import ToolCall, ToolInput, ToolOutput, tool
from app.mcp.schemas import Ref
from app.mcp.serializers import app_url
from app.models.account_ledger import AccountTransfer
from app.models.payment_account import PaymentAccount
from app.models.workspace import Workspace
from app.services import transaction_query
from app.services.account_balance_service import AccountBalanceService
from app.services.cashflow_service import CASH_SOURCES
from app.services.oauth import scopes as escopos
from app.services.overview_service import OverviewService

_LEITURA = dict(scope=escopos.FINANCE_READ, kind="read", read_only=True, destructive=False, idempotent=True)


class LedgerLine(BaseModel):
    date: dt.date
    source: str = Field(
        description=(
            "Origem: transaction (despesa), income (renda), statement_payment (pagamento de fatura), "
            "settlement_sent/settlement_received (acerto), financing_installment, transfer_in/"
            "transfer_out, adjustment (conciliação), opening (saldo inicial)."
        ),
    )
    title: Optional[str] = None
    amount: MoneyOut = Field(description="COM SINAL: positivo entrou, negativo saiu.")
    currency: str
    running_balance: Optional[MoneyOut] = Field(None, description="Saldo DEPOIS desta linha (só no extrato de conta com saldo inicial).")
    converted_amount: Optional[MoneyOut] = Field(None, description="No caixa do mês: o valor na moeda de relatório.")
    space: Optional[Ref] = None
    counterparty: Optional[str] = None
    reference_id: Optional[int] = Field(None, description="Id do registro de origem (lançamento, renda, transferência…).")


class AccountStatementIn(ToolInput):
    account: Optional[str] = Field(None, max_length=120, description="Conta (nome). Omitida: o caixa do mês, de todas as contas.")
    account_id: Optional[int] = None
    month: Optional[MonthKey] = Field(None, description="Mês (YYYY-MM). Omitido: conta = o extrato inteiro; caixa = o mês atual.")
    sources: Optional[List[Literal[
        "transaction", "statement_payment", "settlement_sent", "settlement_received", "financing_installment", "income",
    ]]] = Field(None, max_length=6, description="Só no caixa do mês: filtra as origens.")
    limit: int = Field(30, ge=1, le=100)
    cursor: Optional[str] = Field(None, max_length=512, description="`next_cursor` da página anterior.")

    @model_validator(mode="after")
    def _coerente(self):
        if self.account is not None and self.account_id is not None:
            raise ValueError("informe account ou account_id, não os dois")
        if self.sources and (self.account is not None or self.account_id is not None):
            raise ValueError("`sources` vale só para o caixa do mês (sem conta)")
        return self


class AccountStatementOut(BaseModel):
    mode: str = Field(description="account = extrato de uma conta; cash = caixa do mês (todas as contas).")
    account: Optional[Ref] = None
    month: Optional[str] = None
    currency: str
    opening_amount: Optional[MoneyOut] = None
    opening_on: Optional[dt.date] = None
    balance: Optional[MoneyOut] = Field(None, description="Conta: saldo atual (depois da última linha). Sem saldo inicial = null.")
    cash_in: Optional[MoneyOut] = None
    cash_out: Optional[MoneyOut] = None
    net_cash: Optional[MoneyOut] = None
    entries: List[LedgerLine] = Field(description="Mais recentes primeiro.")
    total_count: int
    next_cursor: Optional[str] = None
    app_url: str


def _pagina(cursor: Optional[str], impressao: str) -> int:
    try:
        return transaction_query.decode_cursor(cursor, impressao) if cursor else 0
    except transaction_query.InvalidCursor as exc:
        raise McpToolError(ErrorCode.VALIDATION_ERROR, str(exc))


def _nomes_de_espacos(call: ToolCall, ids) -> dict[int, str]:
    ids = {i for i in ids if i}
    if not ids:
        return {}
    return dict(call.session.exec(select(Workspace.id, Workspace.name).where(Workspace.id.in_(ids))).all())


@tool(
    name="accounts_statement",
    title="Extrato da conta",
    description=(
        "Explica o saldo: com `account`, o extrato daquela conta com o SALDO CORRENTE linha a linha "
        "(despesas, rendas, pagamentos de fatura, acertos, transferências, ajustes); sem conta, o caixa "
        "do mês (tudo que entrou e saiu, em todas as contas). Paginado, mais recentes primeiro.\n"
        "Use quando: 'por que meu saldo no Itaú é esse?', 'o que saiu da conta este mês?', conciliar "
        "com o extrato do banco.\n"
        "Não use quando: quiser só os saldos atuais (accounts_list) ou só despesas com filtros "
        "(transactions_search)."
    ),
    input_model=AccountStatementIn,
    output_model=AccountStatementOut,
    cost=2,
    invoking="Lendo o extrato…",
    invoked="Extrato lido",
    **_LEITURA,
)
def accounts_statement(call: ToolCall) -> ToolOutput:
    a: AccountStatementIn = call.args
    me = call.identity.user_id
    conta = resolve.resolve_account(call.session, me, account_id=a.account_id, account=a.account, include_inactive=True)
    if conta is not None:
        desde = ate = None
        if a.month:
            desde, ate = month_bounds_utc(parse_month(a.month))
        extrato = AccountBalanceService.statement(call.session, me, conta, desde=desde, ate=ate)
        linhas = list(reversed(extrato["entries"]))
        impressao = f"acc:{conta.id}:{a.month or '*'}"
        inicio = _pagina(a.cursor, impressao)
        pagina = linhas[inicio:inicio + a.limit]
        espacos = _nomes_de_espacos(call, (e.get("workspace_id") for e in pagina))
        saida = AccountStatementOut(
            mode="account",
            account=Ref(id=conta.id, name=conta.name),
            month=a.month,
            currency=extrato["currency"],
            opening_amount=extrato["opening_amount"],
            opening_on=extrato["opening_on"],
            balance=extrato["balance"],
            entries=[
                LedgerLine(
                    date=e["occurred_on"], source=e["source"], title=e["title"], amount=e["amount"],
                    currency=extrato["currency"], running_balance=e["running_balance"],
                    space=Ref(id=e["workspace_id"], name=espacos.get(e["workspace_id"], "?")) if e.get("workspace_id") else None,
                    reference_id=e["reference_id"],
                )
                for e in pagina
            ],
            total_count=len(linhas),
            next_cursor=transaction_query.encode_cursor(inicio + a.limit, impressao) if inicio + a.limit < len(linhas) else None,
            app_url=app_url("/me/accounts"),
        )
        saldo = fmt_brl(extrato["balance"], extrato["currency"]) if extrato["balance"] is not None else "sem saldo inicial"
        return ToolOutput(
            structured=saida,
            summary=f"Extrato {conta.name}: {len(linhas)} movimento(s); saldo {saldo}.",
            entity_type="account",
            entity_ids=[conta.id],
            widget={"view": "account", "app_url": saida.app_url},
        )

    hoje = today_local()
    ref = parse_month(a.month) if a.month else dt.date(hoje.year, hoje.month, 1)
    impressao = f"cash:{ref.isoformat()}:{','.join(sorted(a.sources or []))}"
    inicio = _pagina(a.cursor, impressao)
    caixa = OverviewService.get_ledger(
        call.session, me, ref, sources=list(a.sources) if a.sources else list(CASH_SOURCES),
        limit=a.limit, offset=inicio,
    )
    saida = AccountStatementOut(
        mode="cash",
        month=caixa["month"],
        currency=caixa["currency"],
        cash_in=caixa["cash_in"],
        cash_out=caixa["cash_out"],
        net_cash=caixa["net_cash"],
        entries=[
            LedgerLine(
                date=e["occurred_on"], source=e["source"], title=e["title"],
                amount=e["amount"] if e["direction"] == "in" else -e["amount"],
                currency=e["currency"],
                converted_amount=(e["converted_amount"] if e["direction"] == "in" else -e["converted_amount"])
                if e["converted_amount"] is not None else None,
                space=Ref(id=e["workspace_id"], name=e["workspace_name"] or "?") if e["workspace_id"] else None,
                counterparty=e["counterparty_name"],
                reference_id=e["reference_id"],
            )
            for e in caixa["entries"]
        ],
        total_count=caixa["total"],
        next_cursor=transaction_query.encode_cursor(inicio + a.limit, impressao) if inicio + a.limit < caixa["total"] else None,
        app_url=app_url("/me/ledger", month=caixa["month"]),
    )
    return ToolOutput(
        structured=saida,
        summary=(
            f"Caixa de {caixa['month']}: entrou {fmt_brl(caixa['cash_in'], caixa['currency'])}, saiu "
            f"{fmt_brl(caixa['cash_out'], caixa['currency'])} ({caixa['total']} movimento(s))."
        ),
        widget={"view": "account", "app_url": saida.app_url},
    )


# --- transfers_list --------------------------------------------------------------------

class TransferOut(BaseModel):
    id: int
    from_account: Ref
    to_account: Ref
    from_amount: MoneyOut
    to_amount: MoneyOut
    from_currency: str
    to_currency: str
    exchange_rate: Optional[str] = None
    date: dt.date
    note: Optional[str] = None
    replayed: bool = False


def transfer_out(call: ToolCall, t: AccountTransfer, *, replayed: bool = False) -> TransferOut:
    origem = call.session.get(PaymentAccount, t.from_account_id)
    destino = call.session.get(PaymentAccount, t.to_account_id)
    return TransferOut(
        id=t.id,
        from_account=Ref(id=origem.id, name=origem.name),
        to_account=Ref(id=destino.id, name=destino.name),
        from_amount=t.from_amount,
        to_amount=t.to_amount,
        from_currency=origem.currency,
        to_currency=destino.currency,
        exchange_rate=str(t.exchange_rate) if t.exchange_rate is not None else None,
        date=local_day(t.occurred_at),
        note=t.note,
        replayed=replayed,
    )


class TransfersIn(ToolInput):
    month: Optional[MonthKey] = Field(None, description="Só as do mês (YYYY-MM). Omitido: as mais recentes.")
    account: Optional[str] = Field(None, max_length=120, description="Só as que envolvem esta conta.")
    account_id: Optional[int] = None
    limit: int = Field(20, ge=1, le=100)


class TransfersOut(BaseModel):
    transfers: List[TransferOut]


@tool(
    name="transfers_list",
    title="Transferências entre contas",
    description=(
        "Lista as transferências entre as suas contas (mais recentes primeiro), com o id de cada uma.\n"
        "Use quando: 'qual transferência fiz ontem?', ou antes de desfazer uma (transfers_delete).\n"
        "Não use quando: quiser o extrato completo de uma conta (accounts_statement)."
    ),
    input_model=TransfersIn,
    output_model=TransfersOut,
    **_LEITURA,
)
def transfers_list(call: ToolCall) -> ToolOutput:
    a: TransfersIn = call.args
    me = call.identity.user_id
    minhas = select(PaymentAccount.id).where(PaymentAccount.owner_user_id == me)
    consulta = select(AccountTransfer).where(
        AccountTransfer.deleted_at.is_(None),
        AccountTransfer.from_account_id.in_(minhas) | AccountTransfer.to_account_id.in_(minhas),
    )
    conta = resolve.resolve_account(call.session, me, account_id=a.account_id, account=a.account, include_inactive=True)
    if conta is not None:
        consulta = consulta.where(
            (AccountTransfer.from_account_id == conta.id) | (AccountTransfer.to_account_id == conta.id)
        )
    if a.month:
        inicio, fim = month_bounds_utc(parse_month(a.month))
        consulta = consulta.where(AccountTransfer.occurred_at >= inicio, AccountTransfer.occurred_at < fim)
    linhas = call.session.exec(
        consulta.order_by(AccountTransfer.occurred_at.desc(), AccountTransfer.id.desc()).limit(a.limit)
    ).all()
    saida = TransfersOut(transfers=[transfer_out(call, t) for t in linhas])
    return ToolOutput(
        structured=saida,
        summary=f"{len(linhas)} transferência(s).",
        entity_type="transfer",
        entity_ids=[t.id for t in linhas],
    )
