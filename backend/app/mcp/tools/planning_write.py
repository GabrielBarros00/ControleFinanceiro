"""Planejamento: despesas recorrentes, metas do mês e categorias (escopo `planning.write`).

Mudam o FUTURO (o que vai ser lançado, quanto se pretende gastar, como se
classifica), não o que já aconteceu — por isso vivem num escopo separado das
escritas de lançamento.
"""
from __future__ import annotations

from typing import List, Literal, Optional

from pydantic import BaseModel, Field, model_validator
from sqlmodel import select

from app.domain.dates import today_local
from app.mcp import resolve, versioning
from app.mcp.dates import CivilDate, MonthKey
from app.mcp.errors import ErrorCode, McpToolError
from app.mcp.money import MoneyIn, MoneyInOrZero, MoneyOut, fmt_brl
from app.mcp.ui import WIDGET_URI as WIDGET
from app.mcp.registry import ToolCall, ToolInput, ToolOutput, tool
from app.mcp.schemas import Ref
from app.mcp.serializers import app_url
from app.mcp.tools.obligations import (
    RecurringOut,
    own_recurring_income,
    recurring_expense_out,
    recurring_income_out,
    visible_recurring,
)
from app.mcp.tools.transactions import PaymentMethodIn
from app.mcp.versioning import ExpectedVersion
from app.mcp.writes import DivisionIn, IdempotencyKey, build_division, membership_for_write
from app.models.category import Category
from app.models.recurring import RecurrenceFrequency, RecurringExpense, RecurringIncome
from app.models.transaction import STATEMENT_SHIFT_MAX, STATEMENT_SHIFT_MIN, PaymentMethod, Transaction
from app.models.workspace import Workspace
from app.schemas.category import CategoryCreate, CategoryUpdate
from app.schemas.common import DESCRIPTION_MAX, NAME_MAX, TITLE_MAX
from app.schemas.estimate import MonthlyEstimateCreate
from app.schemas.income import RecurringIncomeCreate, RecurringIncomeUpdate
from app.schemas.recurring import RecurringCreate, RecurringSplitEntry, RecurringUpdate
from app.schemas.tag import TagCreate, TagUpdate
from app.services.commands import income as inc_cmd
from app.services.commands import planning as plan_cmd
from app.services.commands import recurring as rec_cmd
from app.services.oauth import scopes as escopos

FrequencyIn = Literal["daily", "weekly", "monthly", "yearly"]


def _snapshot(call: ToolCall, ws_id: int, d: DivisionIn, amount) -> tuple[Optional[int], Optional[list[RecurringSplitEntry]]]:
    """Divisão da recorrência no formato do template (pagador + snapshot da divisão)."""
    if not d.mentions_division():
        return None, None
    divisao = build_division(call.session, ws_id, call.identity.user_id, d, amount)
    entradas = [
        RecurringSplitEntry(user_id=s.user_id, split_method=s.split_method, input_value=s.input_value)
        for s in divisao.splits
    ]
    return divisao.payer.id, entradas


class RecurringResult(BaseModel):
    recurring: RecurringOut
    previous: Optional[RecurringOut] = None
    changed: List[str] = Field(default_factory=list)
    replayed: bool = False


def _out(call: ToolCall, t: RecurringExpense) -> RecurringOut:
    espaco = call.session.get(Workspace, t.workspace_id)
    return recurring_expense_out(call, t, Ref(id=espaco.id, name=espaco.name), today_local())


def _frase(r: RecurringOut) -> str:
    cada = {"daily": "dia", "weekly": "semana", "monthly": "mês", "yearly": "ano"}[r.frequency]
    intervalo = f"a cada {r.interval} {cada}s" if r.interval > 1 else f"todo {cada}"
    fim = f", até {r.end_date.strftime('%d/%m/%Y')}" if r.end_date else ""
    return f"{r.title}: {fmt_brl(r.amount, r.currency)} {intervalo}{fim} ({r.space.name if r.space else ''})."


class _RecurringFields(ToolInput):
    frequency: Optional[FrequencyIn] = None
    interval: Optional[int] = Field(None, ge=1, le=60, description="A cada N períodos (1 = todo período).")
    day_of_month: Optional[int] = Field(None, ge=1, le=31, description="Dia do mês (mensal/anual).")
    day_of_week: Optional[int] = Field(None, ge=0, le=6, description="Dia da semana (semanal): 0 = segunda … 6 = domingo.")
    month_of_year: Optional[int] = Field(None, ge=1, le=12, description="Mês do ano (anual).")
    start_date: Optional[CivilDate] = Field(None, description="Primeira ocorrência a partir de.")
    end_date: Optional[CivilDate] = Field(None, description="Última data possível (use isto OU end_after_occurrences).")
    end_after_occurrences: Optional[int] = Field(None, ge=1, le=600, description="Termina depois de N ocorrências.")
    category: Optional[str] = Field(None, max_length=120)
    category_id: Optional[int] = None
    card: Optional[str] = Field(None, max_length=120, description="Cartão seu em que a cobrança cai.")
    card_id: Optional[int] = None
    payment_method: Optional[PaymentMethodIn] = None
    auto_settle: Optional[bool] = Field(None, description="Débito automático: cada ocorrência já nasce paga.")
    statement_shift: Optional[int] = Field(None, ge=STATEMENT_SHIFT_MIN, le=STATEMENT_SHIFT_MAX)
    description: Optional[str] = Field(None, max_length=DESCRIPTION_MAX)

    @model_validator(mode="after")
    def _pares_recorrencia(self):
        for a, b in (("category", "category_id"), ("card", "card_id")):
            if getattr(self, a) is not None and getattr(self, b) is not None:
                raise ValueError(f"informe {a} ou {b}, não os dois")
        if self.end_date is not None and self.end_after_occurrences is not None:
            raise ValueError("informe end_date OU end_after_occurrences")
        return self


def _sem_conta(d: DivisionIn) -> None:
    if d.account is not None or d.account_id is not None:
        raise McpToolError(
            ErrorCode.VALIDATION_ERROR,
            "Despesa recorrente não guarda conta de origem pela IA; `account` vale para renda recorrente (kind=income).",
        )

# --- renda recorrente (kind=income) -------------------------------------------------------

_SO_DESPESA = (
    ("space", "space"), ("space_id", "space"), ("card", "card"), ("card_id", "card"),
    ("payment_method", "payment_method"), ("statement_shift", "statement_shift"),
    ("paid_by", "paid_by"), ("paid_by_id", "paid_by"), ("split_with", "split_with"),
    ("split_with_ids", "split_with"), ("split", "split"), ("remove_card", "remove_card"),
    ("category_id", "category_id (renda usa `category` em texto)"),
)


def _recusa_campos_de_despesa(a) -> None:
    """Renda é pessoal (ADR 0021): sem espaço, divisão, cartão ou forma de pagamento."""
    usados = sorted({rotulo for campo, rotulo in _SO_DESPESA if getattr(a, campo, None) not in (None, False)})
    if usados:
        raise McpToolError(
            ErrorCode.VALIDATION_ERROR,
            f"Renda recorrente é só sua (sem espaço, divisão ou cartão): tire {', '.join(usados)}. "
            "Use `account` para dizer em qual conta o dinheiro cai.",
        )


def _conta_da_renda(call: ToolCall, a) -> Optional[int]:
    if a.account is None and a.account_id is None:
        return None
    return resolve.resolve_account(call.session, call.identity.user_id, account_id=a.account_id, account=a.account).id


def _out_income(call: ToolCall, r: RecurringIncome) -> RecurringOut:
    return recurring_income_out(call, r, today_local())


def _frase_renda(r: RecurringOut) -> str:
    cada = {"daily": "dia", "weekly": "semana", "monthly": "mês", "yearly": "ano"}[r.frequency]
    intervalo = f"a cada {r.interval} {cada}s" if r.interval > 1 else f"todo {cada}"
    return f"Renda {r.title}: {fmt_brl(r.amount, r.currency)} {intervalo}."


def _create_income(call: ToolCall, a: "RecurringCreateIn") -> ToolOutput:
    _recusa_campos_de_despesa(a)
    entrada = RecurringIncomeCreate(
        title=a.title,
        description=a.description,
        base_amount=a.amount,
        currency=a.currency.upper() if a.currency else None,
        category=a.category,
        frequency=RecurrenceFrequency(a.frequency or "monthly"),
        interval=a.interval or 1,
        start_date=a.start_date,
        end_date=a.end_date,
        day_of_month=a.day_of_month or (a.start_date.day if a.start_date else today_local().day),
        day_of_week=a.day_of_week,
        month_of_year=a.month_of_year,
        auto_confirm=True if a.auto_settle is None else a.auto_settle,
        account_id=_conta_da_renda(call, a),
    )
    if a.end_after_occurrences is not None:
        raise McpToolError(ErrorCode.VALIDATION_ERROR, "Para renda recorrente, informe o fim por `end_date`.")
    r = inc_cmd.create_recurring_income(call.session, call.identity.user_id, entrada, a.materialize)
    call.session.flush()
    saida = _out_income(call, r)
    return ToolOutput(
        structured=RecurringResult(recurring=saida),
        summary="Renda recorrente criada. " + _frase_renda(saida),
        entity_type="recurring_income",
        entity_ids=[r.id],
        result_ref={"recurring_id": r.id, "kind": "income"},
    )


def _update_income(call: ToolCall, a: "RecurringUpdateIn") -> ToolOutput:
    _recusa_campos_de_despesa(a)
    r = own_recurring_income(call, a.recurring_id)
    antes = _out_income(call, r)
    versioning.check(a.expected_version, antes.version, what="A recorrência")
    dados: dict = {}
    for campo, destino in (("title", "title"), ("description", "description"), ("interval", "interval"),
                           ("day_of_month", "day_of_month"), ("day_of_week", "day_of_week"),
                           ("month_of_year", "month_of_year"), ("start_date", "start_date"),
                           ("end_date", "end_date"), ("category", "category")):
        valor = getattr(a, campo)
        if valor is not None:
            dados[destino] = valor
    if a.end_after_occurrences is not None:
        raise McpToolError(ErrorCode.VALIDATION_ERROR, "Para renda recorrente, informe o fim por `end_date`.")
    if a.amount is not None:
        dados["base_amount"] = a.amount
    if a.frequency is not None:
        dados["frequency"] = RecurrenceFrequency(a.frequency)
    if a.active is not None:
        dados["is_active"] = a.active
    if a.auto_settle is not None:
        dados["auto_confirm"] = a.auto_settle
    if a.remove_category:
        dados["category"] = None
    conta = _conta_da_renda(call, a)
    if conta is not None:
        dados["account_id"] = conta
    atualizado = inc_cmd.update_recurring_income(
        call.session, call.identity.user_id, r.id, RecurringIncomeUpdate(**dados),
    )
    call.session.flush()
    depois = _out_income(call, atualizado)
    a_json, d_json = antes.model_dump(mode="json"), depois.model_dump(mode="json")
    mudou = [k for k in d_json if k != "version" and a_json.get(k) != d_json.get(k)]
    return ToolOutput(
        structured=RecurringResult(recurring=depois, previous=antes, changed=mudou),
        summary=(f"Renda recorrente atualizada ({', '.join(mudou)}). " if mudou else "Nada mudou. ") + _frase_renda(depois),
        entity_type="recurring_income",
        entity_ids=[r.id],
    )



# --- recurring_create -----------------------------------------------------------------

class _RecurringCreateCore(ToolInput):
    idempotency_key: IdempotencyKey
    kind: Literal["expense", "income"] = Field(
        "expense", description="expense = despesa que se repete; income = renda que se repete (salário).",
    )
    title: str = Field(min_length=1, max_length=TITLE_MAX)
    amount: MoneyIn = Field(description="Valor de cada ocorrência.")
    space: Optional[str] = Field(None, max_length=120)
    space_id: Optional[int] = None
    currency: Optional[str] = Field(None, pattern=r"^[A-Za-z]{3}$")
    materialize: Literal["past", "current", "future"] = Field(
        "current",
        description="Com início no passado: `past` lança também as ocorrências passadas; `current` a partir do mês atual; `future` só as próximas.",
    )


class RecurringCreateIn(DivisionIn, _RecurringFields, _RecurringCreateCore):
    @model_validator(mode="after")
    def _espaco(self):
        if self.space is not None and self.space_id is not None:
            raise ValueError("informe space ou space_id, não os dois")
        return self


def _replay_recurring(call: ToolCall, ref: dict) -> ToolOutput:
    if ref.get("kind") == "income":
        saida = _out_income(call, own_recurring_income(call, int(ref["recurring_id"])))
        return ToolOutput(
            structured=RecurringResult(recurring=saida, replayed=True),
            summary="Esta renda recorrente já tinha sido criada (mesma idempotency_key). " + _frase_renda(saida),
            entity_type="recurring_income",
            entity_ids=[saida.id],
        )
    t = call.session.get(RecurringExpense, int(ref["recurring_id"]))
    if t is None:
        raise McpToolError(ErrorCode.CONFLICT, "Operação já processada com esta idempotency_key.")
    membership = membership_for_write(call, t.workspace_id)
    t = rec_cmd._get_recurring_or_404(call.session, t.workspace_id, t.id, membership)
    saida = _out(call, t)
    return ToolOutput(
        structured=RecurringResult(recurring=saida, replayed=True),
        summary="Esta recorrência já tinha sido criada (mesma idempotency_key). " + _frase(saida),
        entity_type="recurring",
        entity_ids=[t.id],
        space_id=t.workspace_id,
    )


@tool(
    name="recurring_create",
    title="Criar recorrência",
    description=(
        "Cria uma despesa que se repete (aluguel, assinatura, academia) ou, com `kind=income`, uma renda "
        "que se repete (salário): o app lança cada ocorrência sozinho, com a mesma divisão, categoria e "
        "cartão (renda: a conta onde cai, em `account`).\n"
        "Use quando: o usuário disser \"todo mês pago R$ 49,90 de streaming no Nubank\", \"o aluguel "
        "de R$ 2.000 vence dia 5, metade do João\", \"meu salário é R$ 4.000 todo dia 5\".\n"
        "Não use quando: for uma compra parcelada (transactions_create com installments) ou um gasto/"
        "renda única (transactions_create / income_create).\n"
        "Mensal por padrão; `interval` = a cada N períodos; fim por data ou por nº de ocorrências."
    ),
    input_model=RecurringCreateIn,
    output_model=RecurringResult,
    scope=escopos.PLANNING_WRITE,
    kind="write",
    read_only=False,
    destructive=False,
    idempotent=True,
    cost=3,
    idempotency_key=True,
    replay=_replay_recurring,
    invoking="Criando a recorrência…",
    invoked="Recorrência criada",
    examples=(
        {"idempotency_key": "f1a2b3c4-0001", "title": "Streaming", "amount": "49.90", "card": "Nubank", "day_of_month": 12},
        {"idempotency_key": "f1a2b3c4-0002", "title": "Aluguel", "amount": "2000.00", "day_of_month": 5, "split_with": ["João"], "payment_method": "pix"},
        {"idempotency_key": "f1a2b3c4-0003", "kind": "income", "title": "Salário", "amount": "4000.00", "day_of_month": 5, "account": "Itaú"},
    ),
    ui=WIDGET,
    app_callable=True,
    meta={"openai/widgetDescription": "O componente mostra o resultado com as ações possíveis (desfazer, editar). Confirme em uma frase, sem repetir os números."},
)
def recurring_create(call: ToolCall) -> ToolOutput:
    a: RecurringCreateIn = call.args
    me = call.identity.user_id
    if a.kind == "income":
        return _create_income(call, a)
    _sem_conta(a)
    ref = resolve.resolve_space(call.session, me, space_id=a.space_id, space=a.space)
    if ref is None:
        nomes, ids = a.people_named()
        ref = resolve.choose_space_for_people(call.session, me, nomes, ids)
    membership = membership_for_write(call, ref.id)
    categoria = resolve.resolve_category(call.session, ref.id, category_id=a.category_id, category=a.category)
    cartao = resolve.resolve_card(call.session, me, card_id=a.card_id, card=a.card)
    pagador, snapshot = _snapshot(call, ref.id, a, a.amount)
    metodo = PaymentMethod.credit_card if cartao else (PaymentMethod(a.payment_method) if a.payment_method else None)
    entrada = RecurringCreate(
        title=a.title,
        description=a.description,
        base_amount=a.amount,
        frequency=RecurrenceFrequency(a.frequency or "monthly"),
        interval=a.interval or 1,
        start_date=a.start_date,
        end_date=a.end_date,
        end_after_occurrences=a.end_after_occurrences,
        day_of_month=a.day_of_month or (a.start_date.day if a.start_date else today_local().day),
        day_of_week=a.day_of_week,
        month_of_year=a.month_of_year,
        currency=a.currency.upper() if a.currency else None,
        payment_method=metodo,
        auto_settle=bool(a.auto_settle),
        credit_card_id=cartao.id if cartao else None,
        statement_shift=a.statement_shift or 0,
        category_id=categoria.id if categoria else None,
        payer_user_id=pagador,
        split_snapshot=snapshot,
    )
    t = rec_cmd.create_recurring(call.session, ref.id, entrada, membership, a.materialize)
    call.session.flush()
    saida = _out(call, t)
    return ToolOutput(
        structured=RecurringResult(recurring=saida),
        summary="Recorrência criada. " + _frase(saida),
        entity_type="recurring",
        entity_ids=[t.id],
        space_id=ref.id,
        result_ref={"recurring_id": t.id, "kind": "expense"},
    )


# --- recurring_update -----------------------------------------------------------------

class _RecurringUpdateCore(ToolInput):
    recurring_id: int
    kind: Literal["expense", "income"] = Field("expense", description="income = renda recorrente.")
    title: Optional[str] = Field(None, min_length=1, max_length=TITLE_MAX)
    amount: Optional[MoneyIn] = None
    active: Optional[bool] = Field(None, description="false = pausar (para de lançar); true = retomar.")
    remove_card: bool = Field(False, description="true = a cobrança deixa de ser no cartão.")
    remove_category: bool = False
    apply_to: Literal["none", "future", "all"] = Field(
        "future",
        description=(
            "O que acontece com ocorrências JÁ lançadas e ainda não pagas: `future` (padrão) ajusta as "
            "futuras; `all` ajusta todas as não pagas; `none` só muda daqui para frente."
        ),
    )


class RecurringUpdateIn(DivisionIn, _RecurringFields, _RecurringUpdateCore):
    expected_version: ExpectedVersion = None

    @model_validator(mode="after")
    def _algo(self):
        if self.remove_card and (self.card is not None or self.card_id is not None):
            raise ValueError("remove_card não combina com card/card_id")
        if self.remove_category and (self.category is not None or self.category_id is not None):
            raise ValueError("remove_category não combina com category/category_id")
        mudancas = self.model_dump(exclude_unset=True, exclude={"recurring_id", "apply_to", "kind", "expected_version"})
        if not self.remove_card:
            mudancas.pop("remove_card", None)
        if not self.remove_category:
            mudancas.pop("remove_category", None)
        if not mudancas:
            raise ValueError("nada para alterar: informe ao menos um campo")
        return self


@tool(
    name="recurring_update",
    title="Editar recorrência",
    description=(
        "Altera uma despesa recorrente (ou, com `kind=income`, uma renda recorrente): valor, dia, "
        "frequência, fim, categoria, cartão, divisão, conta da renda, ou pausa/retoma (`active`). "
        "Ocorrências já pagas nunca mudam; as não pagas seguem `apply_to`.\n"
        "Use quando: \"o streaming subiu para R$ 55\", \"pare de lançar a academia\", \"o aluguel "
        "agora vence dia 10\". Pegue o id em recurring_list.\n"
        "Não use quando: quiser mudar uma única ocorrência (transactions_update nela)."
    ),
    input_model=RecurringUpdateIn,
    output_model=RecurringResult,
    scope=escopos.PLANNING_WRITE,
    kind="write",
    read_only=False,
    destructive=True,
    idempotent=True,
    cost=3,
    invoking="Atualizando a recorrência…",
    invoked="Recorrência atualizada",
    examples=({"recurring_id": 7, "amount": "55.00"}, {"recurring_id": 7, "active": False}),
    ui=WIDGET,
    app_callable=True,
    meta={"openai/widgetDescription": "O componente mostra o resultado com as ações possíveis (desfazer, editar). Confirme em uma frase, sem repetir os números."},
)
def recurring_update(call: ToolCall) -> ToolOutput:
    a: RecurringUpdateIn = call.args
    me = call.identity.user_id
    if a.kind == "income":
        return _update_income(call, a)
    _sem_conta(a)
    ws_id = call.session.exec(select(RecurringExpense.workspace_id).where(RecurringExpense.id == a.recurring_id)).first()
    if ws_id is None:
        raise McpToolError(ErrorCode.NOT_FOUND, "Recorrência não encontrada.", details={"recurring_id": a.recurring_id})
    try:
        membership = membership_for_write(call, ws_id)
    except McpToolError as exc:
        if exc.code == ErrorCode.NOT_FOUND:
            raise McpToolError(ErrorCode.NOT_FOUND, "Recorrência não encontrada.", details={"recurring_id": a.recurring_id})
        raise
    t = rec_cmd._get_recurring_or_404(call.session, ws_id, a.recurring_id, membership)
    antes = _out(call, t)
    versioning.check(a.expected_version, antes.version, what="A recorrência")

    dados: dict = {}
    for campo, destino in (("title", "title"), ("description", "description"), ("interval", "interval"),
                           ("day_of_month", "day_of_month"), ("day_of_week", "day_of_week"),
                           ("month_of_year", "month_of_year"), ("start_date", "start_date"),
                           ("end_date", "end_date"), ("end_after_occurrences", "end_after_occurrences"),
                           ("auto_settle", "auto_settle"), ("statement_shift", "statement_shift")):
        valor = getattr(a, campo)
        if valor is not None:
            dados[destino] = valor
    if a.amount is not None:
        dados["base_amount"] = a.amount
    if a.frequency is not None:
        dados["frequency"] = RecurrenceFrequency(a.frequency)
    if a.active is not None:
        dados["is_active"] = a.active
    if a.remove_category:
        dados["category_id"] = None
    elif a.category is not None or a.category_id is not None:
        dados["category_id"] = resolve.resolve_category(call.session, ws_id, category_id=a.category_id, category=a.category).id
    if a.remove_card:
        dados["credit_card_id"] = None
        if a.payment_method is None and t.payment_method == PaymentMethod.credit_card:
            raise McpToolError(ErrorCode.VALIDATION_ERROR, "Ao tirar do cartão, informe a nova forma de pagamento (payment_method).")
    elif a.card is not None or a.card_id is not None:
        dados["credit_card_id"] = resolve.resolve_card(call.session, me, card_id=a.card_id, card=a.card).id
        dados["payment_method"] = PaymentMethod.credit_card
    if a.payment_method is not None and "payment_method" not in dados:
        dados["payment_method"] = PaymentMethod(a.payment_method)
    if a.mentions_division():
        pagador, snapshot = _snapshot(call, ws_id, a, a.amount or t.base_amount)
        dados["payer_user_id"] = pagador
        dados["split_snapshot"] = snapshot

    atualizado = rec_cmd.update_recurring(
        call.session, ws_id, t.id, RecurringUpdate(**dados), membership, scope=a.apply_to,
    )
    call.session.flush()
    depois = _out(call, atualizado)
    a_json, d_json = antes.model_dump(mode="json"), depois.model_dump(mode="json")
    mudou = [k for k in d_json if k != "version" and a_json.get(k) != d_json.get(k)]
    if "split_snapshot" in dados and "split" not in mudou:
        mudou.append("split")
    return ToolOutput(
        structured=RecurringResult(recurring=depois, previous=antes, changed=mudou),
        summary=(f"Recorrência atualizada ({', '.join(mudou)}). " if mudou else "Nada mudou. ") + _frase(depois),
        entity_type="recurring",
        entity_ids=[t.id],
        space_id=ws_id,
    )


# --- recurring_delete ------------------------------------------------------------------------

class RecurringDeleteIn(ToolInput):
    recurring_id: int = Field(ge=1)
    kind: Literal["expense", "income"] = "expense"
    cancel_open_occurrences: bool = Field(
        False,
        description=(
            "Só despesa: true = cancela também as ocorrências JÁ lançadas deste mês em diante que ainda "
            "não foram pagas. false (padrão) = o que já foi lançado fica como está."
        ),
    )
    expected_version: ExpectedVersion = None


class RecurringDeleteOut(BaseModel):
    deleted: RecurringOut = Field(description="Como a recorrência estava (para refazer, se preciso).")
    cancelled_occurrences: List[int] = Field(default_factory=list, description="Lançamentos cancelados junto.")


@tool(
    name="recurring_delete",
    title="Excluir recorrência",
    description=(
        "Exclui uma despesa ou renda recorrente: o app para de lançar novas ocorrências. O que já foi "
        "lançado continua (e continua contando), salvo `cancel_open_occurrences=true`, que cancela as "
        "ocorrências deste mês em diante ainda não pagas. Não tem desfazer: para só interromper, "
        "prefira pausar (recurring_update com active=false).\n"
        "Use quando: o usuário pedir para excluir/apagar de vez uma recorrência (confirme qual).\n"
        "Não use quando: quiser pausar, mudar o valor ou o fim (recurring_update)."
    ),
    input_model=RecurringDeleteIn,
    output_model=RecurringDeleteOut,
    scope=escopos.PLANNING_WRITE,
    kind="destructive",
    read_only=False,
    destructive=True,
    idempotent=True,
    cost=3,
    invoking="Excluindo a recorrência…",
    invoked="Recorrência excluída",
    examples=({"recurring_id": 7}, {"recurring_id": 3, "kind": "income"}),
    ui=WIDGET,
    app_callable=True,
    meta={"openai/widgetDescription": "O componente mostra o resultado com as ações possíveis (desfazer, editar). Confirme em uma frase, sem repetir os números."},
)
def recurring_delete(call: ToolCall) -> ToolOutput:
    a: RecurringDeleteIn = call.args
    me = call.identity.user_id
    if a.kind == "income":
        if a.cancel_open_occurrences:
            raise McpToolError(ErrorCode.VALIDATION_ERROR, "cancel_open_occurrences vale só para despesa recorrente.")
        r = own_recurring_income(call, a.recurring_id)
        antes = _out_income(call, r)
        versioning.check(a.expected_version, antes.version, what="A recorrência")
        inc_cmd.delete_recurring_income(call.session, me, r.id)
        return ToolOutput(
            structured=RecurringDeleteOut(deleted=antes),
            summary=f"Renda recorrente {antes.title} excluída. As rendas já lançadas continuam.",
            entity_type="recurring_income",
            entity_ids=[r.id],
        )
    t, ref = visible_recurring(call, a.recurring_id)
    membership = membership_for_write(call, ref.id)
    antes = _out(call, t)
    versioning.check(a.expected_version, antes.version, what="A recorrência")
    alvos: list[int] = []
    if a.cancel_open_occurrences:
        mes = today_local().strftime("%Y-%m")
        alvos = list(call.session.exec(
            select(Transaction.id).where(
                Transaction.recurring_expense_id == t.id,
                Transaction.deleted_at.is_(None),
                Transaction.billing_month >= mes,
                Transaction.settled_at.is_(None),
            )
        ).all())
    cancelados = rec_cmd.delete_recurring(call.session, ref.id, t.id, membership, alvos)
    return ToolOutput(
        structured=RecurringDeleteOut(deleted=antes, cancelled_occurrences=cancelados),
        summary=f"Recorrência {antes.title} excluída"
        + (f"; {len(cancelados)} ocorrência(s) em aberto cancelada(s)." if cancelados else "; o que já foi lançado continua."),
        entity_type="recurring",
        entity_ids=[t.id] + cancelados,
        space_id=ref.id,
    )


# --- budgets_set ------------------------------------------------------------------------

class BudgetSetIn(ToolInput):
    space: Optional[str] = Field(None, max_length=120)
    space_id: Optional[int] = None
    category: Optional[str] = Field(None, max_length=120, description="Categoria da meta (existente no espaço).")
    category_id: Optional[int] = None
    amount: MoneyInOrZero = Field(description="Quanto se pretende gastar no mês nessa categoria.")
    month: Optional[MonthKey] = Field(None, description="Mês da meta (YYYY-MM). Omitido = mês atual.")
    scope: Optional[Literal["personal", "space"]] = Field(
        None,
        description=(
            "`personal` = sua meta (compara com a SUA parte); `space` = meta da casa (total do espaço). "
            "Obrigatório em espaço com mais de uma pessoa."
        ),
    )
    note: Optional[str] = Field(None, max_length=DESCRIPTION_MAX)

    @model_validator(mode="after")
    def _pares(self):
        if (self.category is None) == (self.category_id is None):
            raise ValueError("informe category OU category_id")
        if self.space is not None and self.space_id is not None:
            raise ValueError("informe space ou space_id, não os dois")
        return self


class BudgetSetOut(BaseModel):
    id: int
    space: Ref
    category: Ref
    month: str
    scope: str
    amount: MoneyOut
    created: bool = Field(description="false = a meta já existia e foi atualizada.")
    app_url: str


@tool(
    name="budgets_set",
    title="Definir meta do mês",
    description=(
        "Cria ou atualiza a meta de gasto (orçamento) de uma categoria num mês. Chamar de novo com "
        "o mesmo espaço/categoria/mês/escopo só atualiza o valor.\n"
        "Use quando: \"quero gastar no máximo R$ 800 com mercado este mês\".\n"
        "Não use quando: quiser ver as metas e o quanto já foi gasto (budgets_list)."
    ),
    input_model=BudgetSetIn,
    output_model=BudgetSetOut,
    scope=escopos.PLANNING_WRITE,
    kind="write",
    read_only=False,
    destructive=True,
    idempotent=True,
    cost=3,
    invoking="Salvando a meta…",
    invoked="Meta salva",
    examples=({"category": "Mercado", "amount": "800.00", "scope": "personal"},),
    ui=WIDGET,
    app_callable=True,
    meta={"openai/widgetDescription": "O componente mostra o resultado com as ações possíveis (desfazer, editar). Confirme em uma frase, sem repetir os números."},
)
def budgets_set(call: ToolCall) -> ToolOutput:
    a: BudgetSetIn = call.args
    me = call.identity.user_id
    ref = resolve.require_space(call.session, me, space_id=a.space_id, space=a.space)
    membership = membership_for_write(call, ref.id)
    if a.scope is None and not ref.is_personal:
        raise McpToolError(
            ErrorCode.VALIDATION_ERROR,
            f"O espaço {ref.workspace.name} é compartilhado: pergunte se a meta é pessoal (scope=personal) "
            "ou da casa (scope=space).",
        )
    categoria = resolve.resolve_category(call.session, ref.id, category_id=a.category_id, category=a.category)
    mes = a.month or today_local().strftime("%Y-%m")
    meta, criada = plan_cmd.create_estimate(call.session, ref.id, MonthlyEstimateCreate(
        category=categoria.name,
        category_id=categoria.id,
        amount=a.amount,
        month=mes,
        description=a.note,
        scope="personal" if a.scope == "personal" else "workspace",
    ), membership)
    call.session.flush()
    saida = BudgetSetOut(
        id=meta.id, space=Ref(id=ref.id, name=ref.workspace.name), category=Ref(id=categoria.id, name=categoria.name),
        month=mes, scope="personal" if meta.owner_user_id is not None else "space", amount=meta.amount,
        created=criada, app_url=app_url(f"/w/{ref.id}/reports"),
    )
    return ToolOutput(
        structured=saida,
        summary=f"Meta {'criada' if criada else 'atualizada'}: {categoria.name} {fmt_brl(meta.amount)} em {mes} ({ref.workspace.name}).",
        entity_type="estimate",
        entity_ids=[meta.id],
        space_id=ref.id,
    )


# --- categories_create -------------------------------------------------------------------

class CategoryCreateIn(ToolInput):
    kind: Literal["category", "tag"] = Field("category", description="category (padrão) ou tag.")
    space: Optional[str] = Field(None, max_length=120)
    space_id: Optional[int] = None
    name: str = Field(min_length=1, max_length=NAME_MAX)
    color: Optional[str] = Field(None, pattern=r"^#[0-9A-Fa-f]{6}$", description="Cor em hex, ex.: #22C55E.")

    @model_validator(mode="after")
    def _par(self):
        if self.space is not None and self.space_id is not None:
            raise ValueError("informe space ou space_id, não os dois")
        return self


class CategoryOut(BaseModel):
    id: int
    name: str
    space: Ref
    kind: str = "category"


@tool(
    name="categories_create",
    title="Criar categoria ou tag",
    description=(
        "Cria uma categoria (ou, com `kind=tag`, uma tag) num espaço. Se já existir uma com o mesmo "
        "nome (ignorando acento e maiúsculas), devolve ALREADY_EXISTS com o id dela — use a existente.\n"
        "Use quando: o usuário pedir uma categoria/tag que não existe (confira antes com categories_list).\n"
        "Não use quando: ela já existir, mesmo escrita diferente; para renomear/excluir (categories_update)."
    ),
    input_model=CategoryCreateIn,
    output_model=CategoryOut,
    scope=escopos.PLANNING_WRITE,
    kind="write",
    read_only=False,
    destructive=False,
    idempotent=True,
    cost=3,
    invoking="Criando a categoria…",
    invoked="Categoria criada",
    examples=({"name": "Pets", "space": "Casa"}, {"kind": "tag", "name": "Trabalho"}),
    ui=WIDGET,
    app_callable=True,
    meta={"openai/widgetDescription": "O componente mostra o resultado com as ações possíveis (desfazer, editar). Confirme em uma frase, sem repetir os números."},
)
def categories_create(call: ToolCall) -> ToolOutput:
    a: CategoryCreateIn = call.args
    ref = resolve.require_space(call.session, call.identity.user_id, space_id=a.space_id, space=a.space)
    membership = membership_for_write(call, ref.id)
    alvo = resolve.norm(a.name)
    if a.kind == "tag":
        for existente in resolve.space_tags(call.session, ref.id):
            if resolve.norm(existente.name) == alvo:
                raise McpToolError(
                    ErrorCode.ALREADY_EXISTS,
                    f"A tag '{existente.name}' já existe em {ref.workspace.name}.",
                    details={"tag_id": existente.id, "name": existente.name, "space_id": ref.id},
                )
        tag = plan_cmd.create_tag(call.session, ref.id, TagCreate(name=a.name, color=a.color), membership)
        return ToolOutput(
            structured=CategoryOut(id=tag.id, name=tag.name, space=Ref(id=ref.id, name=ref.workspace.name), kind="tag"),
            summary=f"Tag '{tag.name}' criada em {ref.workspace.name}.",
            entity_type="tag",
            entity_ids=[tag.id],
            space_id=ref.id,
        )
    for existente in resolve.space_categories(call.session, ref.id):
        if resolve.norm(existente.name) == alvo:
            raise McpToolError(
                ErrorCode.ALREADY_EXISTS,
                f"A categoria '{existente.name}' já existe em {ref.workspace.name}.",
                details={"category_id": existente.id, "name": existente.name, "space_id": ref.id},
            )
    categoria: Category = plan_cmd.create_category(
        call.session, ref.id, CategoryCreate(name=a.name, color=a.color), membership
    )
    return ToolOutput(
        structured=CategoryOut(id=categoria.id, name=categoria.name, space=Ref(id=ref.id, name=ref.workspace.name)),
        summary=f"Categoria '{categoria.name}' criada em {ref.workspace.name}.",
        entity_type="category",
        entity_ids=[categoria.id],
        space_id=ref.id,
    )


# --- categories_update ---------------------------------------------------------------------

class CategoryUpdateIn(ToolInput):
    kind: Literal["category", "tag"] = "category"
    space: Optional[str] = Field(None, max_length=120)
    space_id: Optional[int] = None
    name: Optional[str] = Field(None, max_length=NAME_MAX, description="Nome ATUAL da categoria/tag.")
    id: Optional[int] = Field(None, ge=1)
    new_name: Optional[str] = Field(None, min_length=1, max_length=NAME_MAX, description="Nome novo (renomear).")
    color: Optional[str] = Field(None, pattern=r"^#[0-9A-Fa-f]{6}$")
    delete: bool = Field(
        False,
        description=(
            "true = excluir. Categoria excluída some das listas (os lançamentos antigos a mantêm); "
            "tag excluída sai de todos os lançamentos."
        ),
    )

    @model_validator(mode="after")
    def _coerente(self):
        if (self.name is None) == (self.id is None):
            raise ValueError("informe name (o atual) OU id")
        if self.space is not None and self.space_id is not None:
            raise ValueError("informe space ou space_id, não os dois")
        if self.delete and (self.new_name is not None or self.color is not None):
            raise ValueError("delete não combina com new_name/color")
        if not self.delete and self.new_name is None and self.color is None:
            raise ValueError("nada para alterar: informe new_name, color ou delete=true")
        return self


class CategoryUpdateOut(BaseModel):
    kind: str
    id: int
    name: str
    previous_name: str
    space: Ref
    deleted: bool = False


@tool(
    name="categories_update",
    title="Renomear ou excluir categoria/tag",
    description=(
        "Renomeia, muda a cor ou exclui uma categoria ou tag de um espaço (`kind`). Nome novo que já "
        "exista volta erro.\n"
        "Use quando: \"renomeie Restaurantes para Alimentação fora\", \"apague a tag viagem-2024\".\n"
        "Não use quando: quiser criar (categories_create) ou trocar a categoria de lançamentos "
        "(transactions_update / transactions_bulk_preview)."
    ),
    input_model=CategoryUpdateIn,
    output_model=CategoryUpdateOut,
    scope=escopos.PLANNING_WRITE,
    kind="write",
    read_only=False,
    destructive=True,
    idempotent=True,
    cost=3,
    invoking="Atualizando…",
    invoked="Atualizado",
    examples=({"name": "Restaurantes", "new_name": "Alimentação fora", "space": "Casa"}, {"kind": "tag", "name": "viagem-2024", "delete": True}),
    ui=WIDGET,
    app_callable=True,
    meta={"openai/widgetDescription": "O componente mostra o resultado com as ações possíveis (desfazer, editar). Confirme em uma frase, sem repetir os números."},
)
def categories_update(call: ToolCall) -> ToolOutput:
    a: CategoryUpdateIn = call.args
    ref = resolve.require_space(call.session, call.identity.user_id, space_id=a.space_id, space=a.space)
    membership = membership_for_write(call, ref.id)
    espaco = Ref(id=ref.id, name=ref.workspace.name)
    if a.kind == "tag":
        tags = resolve.space_tags(call.session, ref.id)
        if a.id is not None:
            alvo = next((t for t in tags if t.id == a.id), None)
            if alvo is None:
                raise McpToolError(ErrorCode.NOT_FOUND, "Tag não encontrada neste espaço.", details={"id": a.id})
        else:
            escolhida = resolve.pick("tag", a.name, [resolve.Match(t.id, t.name) for t in tags], id_param="id")
            alvo = next(t for t in tags if t.id == escolhida.id)
        anterior = alvo.name
        if a.delete:
            plan_cmd.delete_tag(call.session, ref.id, alvo.id, membership)
            return ToolOutput(
                structured=CategoryUpdateOut(kind="tag", id=alvo.id, name=anterior, previous_name=anterior, space=espaco, deleted=True),
                summary=f"Tag '{anterior}' excluída de {ref.workspace.name} (e dos lançamentos).",
                entity_type="tag", entity_ids=[alvo.id], space_id=ref.id,
            )
        dados = {k: v for k, v in (("name", a.new_name), ("color", a.color)) if v is not None}
        tag = plan_cmd.update_tag(call.session, ref.id, alvo.id, TagUpdate(**dados), membership)
        return ToolOutput(
            structured=CategoryUpdateOut(kind="tag", id=tag.id, name=tag.name, previous_name=anterior, space=espaco),
            summary=f"Tag '{anterior}' atualizada para '{tag.name}'.",
            entity_type="tag", entity_ids=[tag.id], space_id=ref.id,
        )
    alvo = resolve.resolve_category(call.session, ref.id, category_id=a.id, category=a.name)
    anterior = alvo.name
    if a.delete:
        plan_cmd.delete_category(call.session, ref.id, alvo.id, membership)
        return ToolOutput(
            structured=CategoryUpdateOut(kind="category", id=alvo.id, name=anterior, previous_name=anterior, space=espaco, deleted=True),
            summary=f"Categoria '{anterior}' excluída de {ref.workspace.name}. Os lançamentos antigos continuam com ela.",
            entity_type="category", entity_ids=[alvo.id], space_id=ref.id,
        )
    dados = {k: v for k, v in (("name", a.new_name), ("color", a.color)) if v is not None}
    categoria = plan_cmd.update_category(call.session, ref.id, alvo.id, CategoryUpdate(**dados), membership)
    return ToolOutput(
        structured=CategoryUpdateOut(kind="category", id=categoria.id, name=categoria.name, previous_name=anterior, space=espaco),
        summary=f"Categoria '{anterior}' atualizada para '{categoria.name}'.",
        entity_type="category", entity_ids=[categoria.id], space_id=ref.id,
    )
