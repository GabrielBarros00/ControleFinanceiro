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
from app.mcp import resolve
from app.mcp.dates import CivilDate, MonthKey
from app.mcp.errors import ErrorCode, McpToolError
from app.mcp.money import MoneyIn, MoneyInOrZero, MoneyOut, fmt_brl
from app.mcp.registry import ToolCall, ToolInput, ToolOutput, tool
from app.mcp.schemas import Ref
from app.mcp.serializers import app_url
from app.mcp.tools.obligations import RecurringOut, recurring_expense_out
from app.mcp.tools.transactions import PaymentMethodIn
from app.mcp.writes import DivisionIn, IdempotencyKey, build_division, membership_for_write
from app.models.category import Category
from app.models.recurring import RecurrenceFrequency, RecurringExpense
from app.models.transaction import STATEMENT_SHIFT_MAX, STATEMENT_SHIFT_MIN, PaymentMethod
from app.models.workspace import Workspace
from app.schemas.category import CategoryCreate
from app.schemas.common import DESCRIPTION_MAX, NAME_MAX, TITLE_MAX
from app.schemas.estimate import MonthlyEstimateCreate
from app.schemas.recurring import RecurringCreate, RecurringSplitEntry, RecurringUpdate
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
    return recurring_expense_out(t, Ref(id=espaco.id, name=espaco.name), today_local())


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
        raise McpToolError(ErrorCode.VALIDATION_ERROR, "Recorrência não guarda conta de origem; registre-a no app se precisar.")


# --- recurring_create -----------------------------------------------------------------

class _RecurringCreateCore(ToolInput):
    idempotency_key: IdempotencyKey
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
    title="Criar despesa recorrente",
    description=(
        "Cria uma despesa que se repete (aluguel, assinatura, academia): o app lança cada ocorrência "
        "sozinho, com a mesma divisão, categoria e cartão.\n"
        "Use quando: o usuário disser \"todo mês pago R$ 49,90 de streaming no Nubank\", \"o aluguel "
        "de R$ 2.000 vence dia 5, metade do João\".\n"
        "Não use quando: for uma compra parcelada (transactions_create com installments) ou uma "
        "despesa única. Renda recorrente é cadastrada no app.\n"
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
    ),
)
def recurring_create(call: ToolCall) -> ToolOutput:
    a: RecurringCreateIn = call.args
    me = call.identity.user_id
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
        result_ref={"recurring_id": t.id},
    )


# --- recurring_update -----------------------------------------------------------------

class _RecurringUpdateCore(ToolInput):
    recurring_id: int
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
    @model_validator(mode="after")
    def _algo(self):
        if self.remove_card and (self.card is not None or self.card_id is not None):
            raise ValueError("remove_card não combina com card/card_id")
        if self.remove_category and (self.category is not None or self.category_id is not None):
            raise ValueError("remove_category não combina com category/category_id")
        mudancas = self.model_dump(exclude_unset=True, exclude={"recurring_id", "apply_to"})
        if not self.remove_card:
            mudancas.pop("remove_card", None)
        if not self.remove_category:
            mudancas.pop("remove_category", None)
        if not mudancas:
            raise ValueError("nada para alterar: informe ao menos um campo")
        return self


@tool(
    name="recurring_update",
    title="Editar despesa recorrente",
    description=(
        "Altera uma despesa recorrente: valor, dia, frequência, fim, categoria, cartão, divisão, ou "
        "pausa/retoma (`active`). Ocorrências já pagas nunca mudam; as não pagas seguem `apply_to`.\n"
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
)
def recurring_update(call: ToolCall) -> ToolOutput:
    a: RecurringUpdateIn = call.args
    me = call.identity.user_id
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
    mudou = [k for k in d_json if a_json.get(k) != d_json.get(k)]
    if "split_snapshot" in dados:
        mudou.append("split")
    return ToolOutput(
        structured=RecurringResult(recurring=depois, previous=antes, changed=mudou),
        summary=(f"Recorrência atualizada ({', '.join(mudou)}). " if mudou else "Nada mudou. ") + _frase(depois),
        entity_type="recurring",
        entity_ids=[t.id],
        space_id=ws_id,
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


@tool(
    name="categories_create",
    title="Criar categoria",
    description=(
        "Cria uma categoria nova num espaço. Se já existir uma com o mesmo nome (ignorando acento e "
        "maiúsculas), devolve ALREADY_EXISTS com o id dela — use a existente.\n"
        "Use quando: o usuário pedir uma categoria que não existe (confira antes com categories_list).\n"
        "Não use quando: a categoria já existir, mesmo escrita diferente."
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
    examples=({"name": "Pets", "space": "Casa"},),
)
def categories_create(call: ToolCall) -> ToolOutput:
    a: CategoryCreateIn = call.args
    ref = resolve.require_space(call.session, call.identity.user_id, space_id=a.space_id, space=a.space)
    membership = membership_for_write(call, ref.id)
    alvo = resolve.norm(a.name)
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
