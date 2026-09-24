"""Relatórios e orçamento: `reports_summary`, `reports_show` (a mesma consulta,
desenhada no componente) e `budgets_list`.

Os números vêm dos MESMOS serviços das telas "Seu mês" (`OverviewService`) e
Relatórios (`ReportService`) — a IA e o app não têm como discordar sobre quanto a
pessoa gastou. Somente leitura (sem materialização preguiçosa).
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date
from decimal import Decimal
from typing import List, Literal, Optional

from pydantic import BaseModel, Field
from sqlmodel import or_, select

from app.domain.access_policy import has_full_access
from app.domain.dates import parse_month, today_local
from app.domain.query_policy import InvalidCurrencyCode, normalize_currency_code
from app.mcp import resolve
from app.mcp.dates import MonthKey
from app.mcp.errors import ErrorCode, McpToolError
from app.mcp.money import MoneyOut, fmt_brl
from app.mcp.ui import WIDGET_URI
from app.mcp.registry import ToolCall, ToolInput, ToolOutput, tool
from app.mcp.schemas import Ref
from app.mcp.serializers import app_url
from app.mcp.tools.transactions import ResolvedFilters, SearchFilters, build_filters
from app.models.estimate import MonthlyEstimate
from app.services import transaction_query
from app.services.oauth import scopes as escopos
from app.services.overview_service import OverviewService
from app.services.report_service import ReportService

WIDGET = WIDGET_URI
_LEITURA = dict(scope=escopos.FINANCE_READ, kind="read", read_only=True, destructive=False, idempotent=True)


def _mes(valor: Optional[str]) -> date:
    return parse_month(valor) if valor else date(today_local().year, today_local().month, 1)


def _moeda(valor: Optional[str]) -> Optional[str]:
    if not valor:
        return None
    try:
        return normalize_currency_code(valor)
    except InvalidCurrencyCode as exc:
        raise McpToolError(ErrorCode.VALIDATION_ERROR, str(exc))


class ReportsIn(ToolInput):
    month: Optional[MonthKey] = Field(None, description="Mês (YYYY-MM). Omitido: o mês atual.")
    months: int = Field(1, ge=1, le=12, description="Com N > 1, traz também a evolução dos últimos N meses (até o mês atual).")
    space: Optional[str] = Field(None, max_length=120, description="Restringe as categorias a um espaço.")
    space_id: Optional[int] = None
    category: Optional[str] = Field(None, max_length=120, description="Mostra só esta categoria.")
    currency: Optional[str] = Field(None, min_length=3, max_length=3, description="Moeda dos totais pessoais (ISO-4217).")


class CategoryAmount(BaseModel):
    category: str
    amount: MoneyOut
    currency: str


class SpaceSlice(BaseModel):
    space: Ref
    currency: str
    my_consumption: MoneyOut = Field(description="A sua parte das despesas deste espaço no mês.")
    house_total: Optional[MoneyOut] = Field(None, description="Total da casa (null = você não tem acesso completo).")
    to_pay: MoneyOut
    to_receive: MoneyOut


class MonthPoint(BaseModel):
    month: str
    income: MoneyOut
    consumption: MoneyOut
    result: MoneyOut
    cash_in: MoneyOut
    cash_out: MoneyOut


class ReportsOut(BaseModel):
    month: str
    currency: str
    income: MoneyOut = Field(description="Rendas do mês (competência).")
    consumption: MoneyOut = Field(description="O que VOCÊ consumiu (sua parte de todas as despesas).")
    result: MoneyOut = Field(description="Renda − consumo.")
    cash_in: MoneyOut = Field(description="Dinheiro que entrou de fato.")
    cash_out: MoneyOut = Field(description="Dinheiro que saiu de fato (inclui fatura paga, acertos, parcelas).")
    to_pay: MoneyOut = Field(description="O que você deve a outras pessoas (acertos).")
    to_receive: MoneyOut = Field(description="O que outras pessoas devem a você.")
    payables_total: MoneyOut = Field(description="Contas do mês ainda não pagas.")
    my_categories: List[CategoryAmount] = Field(description="Seu consumo por categoria, do maior para o menor.")
    spaces: List[SpaceSlice]
    series: Optional[List[MonthPoint]] = None
    excluded_foreign_count: int = Field(0, description="Lançamentos em moeda sem cotação, fora dos totais.")
    app_url: str


def _resumo(call: ToolCall, a: ReportsIn) -> ToolOutput:
    """O resumo do mês, compartilhado por `reports_summary` (dados) e `reports_show` (tela)."""
    me = call.identity.user_id
    mes = _mes(a.month)
    moeda = _moeda(a.currency)
    visao = OverviewService.get_overview(call.session, me, mes, currency=moeda)
    alvo = resolve.resolve_space(call.session, me, space_id=a.space_id, space=a.space)
    espacos = [alvo] if alvo else resolve.user_spaces(call.session, me)

    categorias: dict[tuple[str, str], Decimal] = defaultdict(Decimal)
    fatias: list[SpaceSlice] = []
    por_espaco = {s["workspace_id"]: s for s in visao.get("by_workspace", [])}
    for ref in espacos:
        resumo = ReportService.get_summary(
            call.session, ref.id, mes, user_id=me, full_access=has_full_access(ref.membership)
        )
        for linha in resumo.get("my_categories") or []:
            categorias[(linha["name"], resumo["base_currency"])] += Decimal(linha["value"])
        fatia = por_espaco.get(ref.id, {})
        fatias.append(SpaceSlice(
            space=Ref(id=ref.id, name=ref.workspace.name),
            currency=resumo["base_currency"],
            my_consumption=resumo.get("my_expenses") or Decimal("0"),
            house_total=resumo.get("total_expenses"),
            to_pay=fatia.get("to_pay", Decimal("0")),
            to_receive=fatia.get("to_receive", Decimal("0")),
        ))

    linhas = [CategoryAmount(category=n, amount=v, currency=c) for (n, c), v in categorias.items() if v]
    if a.category:
        achados = {m.name for m in resolve.find(a.category, [resolve.Match(i, x.category) for i, x in enumerate(linhas)])}
        linhas = [x for x in linhas if x.category in achados]
    linhas.sort(key=lambda x: x.amount, reverse=True)

    serie = None
    if a.months > 1:
        dados = OverviewService.get_series(call.session, me, months=a.months, currency=moeda)
        serie = [
            MonthPoint(
                month=p["month"], income=p["income"], consumption=p["consumption"], result=p["result"],
                cash_in=p["cash_in"], cash_out=p["cash_out"],
            )
            for p in dados["months"]
        ]

    saida = ReportsOut(
        month=visao["month"],
        currency=visao["currency"],
        income=visao["income"],
        consumption=visao["consumption"],
        result=visao["result"],
        cash_in=visao["cash_in"],
        cash_out=visao["cash_out"],
        to_pay=visao["to_pay"],
        to_receive=visao["to_receive"],
        payables_total=visao.get("payables_total", Decimal("0")),
        my_categories=linhas,
        spaces=fatias,
        series=serie,
        excluded_foreign_count=visao.get("excluded_foreign_count", 0),
        app_url=app_url("/overview", month=visao["month"]),
    )
    resumo = (
        f"{saida.month}: seu consumo {fmt_brl(saida.consumption, saida.currency)}, "
        f"renda {fmt_brl(saida.income, saida.currency)}, resultado {fmt_brl(saida.result, saida.currency)}."
    )
    if a.category:
        resumo += " " + ("; ".join(f"{x.category}: {fmt_brl(x.amount, x.currency)}" for x in linhas) or f"Nada em '{a.category}' no mês.")
    return ToolOutput(structured=saida, summary=resumo, widget={"view": "summary", "app_url": saida.app_url})


@tool(
    name="reports_summary",
    title="Resumo financeiro do mês",
    description=(
        "Resumo do mês da pessoa somando todos os espaços: renda, SEU consumo (sua parte das "
        "despesas), resultado, caixa (entrou/saiu), quanto deve e tem a receber, contas a pagar e "
        "o consumo por categoria. Com `months` > 1, traz a evolução mês a mês. Só dados; para "
        "DESENHAR o resumo na conversa, use reports_show.\n"
        "Use quando: 'quanto gastei com alimentação este mês?', 'como está meu mês?', 'gastei mais "
        "que em agosto?'.\n"
        "Não use quando: o usuário pedir para ver/mostrar o resumo (reports_show); precisar dos "
        "lançamentos individuais (transactions_search) ou da fatura (statements_get)."
    ),
    input_model=ReportsIn,
    output_model=ReportsOut,
    cost=2,
    invoking="Calculando o resumo…",
    invoked="Resumo pronto",
    **_LEITURA,
)
def reports_summary(call: ToolCall) -> ToolOutput:
    return _resumo(call, call.args)


class ReportsShowIn(ToolInput):
    month: Optional[MonthKey] = Field(None, description="Mês (YYYY-MM). Omitido: o mês atual.")
    space: Optional[str] = Field(None, max_length=120, description="Restringe as categorias a um espaço.")
    space_id: Optional[int] = None
    category: Optional[str] = Field(None, max_length=120, description="Mostra só esta categoria.")
    currency: Optional[str] = Field(None, min_length=3, max_length=3, description="Moeda dos totais pessoais (ISO-4217).")


@tool(
    name="reports_show",
    title="Mostrar resumo do mês na conversa",
    description=(
        "Desenha o resumo de UM mês como componente visual na conversa (renda, seu consumo, caixa, "
        "a pagar, resultado e consumo por categoria) e devolve os mesmos dados de reports_summary.\n"
        "Use quando: o usuário pedir para VER ou MOSTRAR o resumo ou o painel do mês ('mostre meu "
        "resumo de setembro'). Chame uma vez, com o mês final.\n"
        "Não use quando: precisar dos números para responder ou analisar, ou da evolução de vários "
        "meses (reports_summary): cada chamada desenha um componente novo na conversa."
    ),
    input_model=ReportsShowIn,
    output_model=ReportsOut,
    cost=2,
    ui=WIDGET,
    invoking="Montando o resumo…",
    invoked="Resumo na tela",
    meta={"openai/widgetDescription": (
        "O componente já mostra o resumo do mês: resultado, renda, consumo, caixa, a pagar e as "
        "maiores categorias. Não repita os números; destaque só o que importa para a pergunta."
    )},
    **_LEITURA,
)
def reports_show(call: ToolCall) -> ToolOutput:
    a: ReportsShowIn = call.args
    return _resumo(call, ReportsIn(
        month=a.month, months=1, space=a.space, space_id=a.space_id, category=a.category, currency=a.currency,
    ))


# --- budgets_list -----------------------------------------------------------------------

class BudgetsIn(ToolInput):
    month: Optional[MonthKey] = Field(None, description="Mês (YYYY-MM). Omitido: o mês atual.")
    space: Optional[str] = Field(None, max_length=120)
    space_id: Optional[int] = None


class BudgetOut(BaseModel):
    id: int
    space: Ref
    category: str
    scope: str = Field(description="workspace (meta da casa) | personal (sua meta pessoal)")
    planned: MoneyOut
    spent: Optional[MoneyOut] = Field(None, description="Gasto no mês (null = sem acesso ao total da casa).")
    remaining: Optional[MoneyOut] = None
    over_budget: Optional[bool] = None
    currency: str


class BudgetsOut(BaseModel):
    month: str
    budgets: List[BudgetOut]


@tool(
    name="budgets_list",
    title="Orçamentos do mês",
    description=(
        "Lista as metas de gasto (orçamentos) por categoria, com quanto já foi gasto e quanto resta. "
        "Meta pessoal compara com a SUA parte; meta da casa, com o total da casa.\n"
        "Use quando: 'quanto ainda posso gastar em mercado?', 'estourei algum orçamento?'.\n"
        "Não use quando: quiser definir uma meta (budgets_set)."
    ),
    input_model=BudgetsIn,
    output_model=BudgetsOut,
    cost=2,
    **_LEITURA,
)
def budgets_list(call: ToolCall) -> ToolOutput:
    a: BudgetsIn = call.args
    me = call.identity.user_id
    mes = _mes(a.month)
    chave = mes.strftime("%Y-%m")
    alvo = resolve.resolve_space(call.session, me, space_id=a.space_id, space=a.space)
    espacos = [alvo] if alvo else resolve.user_spaces(call.session, me)
    metas: list[BudgetOut] = []
    for ref in espacos:
        linhas = call.session.exec(
            select(MonthlyEstimate).where(
                MonthlyEstimate.workspace_id == ref.id,
                MonthlyEstimate.deleted_at.is_(None),
                MonthlyEstimate.month == chave,
                or_(MonthlyEstimate.owner_user_id.is_(None), MonthlyEstimate.owner_user_id == me),
            )
        ).all()
        if not linhas:
            continue
        acesso = has_full_access(ref.membership)
        resumo = ReportService.get_summary(call.session, ref.id, mes, user_id=me, full_access=acesso)
        meus = {resolve.norm(c["name"]): Decimal(c["value"]) for c in resumo.get("my_categories") or []}
        casa = {resolve.norm(c["name"]): Decimal(c["value"]) for c in resumo.get("categories") or []} if acesso else None
        for meta in linhas:
            pessoal = meta.owner_user_id is not None
            if pessoal:
                gasto = meus.get(resolve.norm(meta.category), Decimal("0"))
            else:
                gasto = casa.get(resolve.norm(meta.category), Decimal("0")) if casa is not None else None
            metas.append(BudgetOut(
                id=meta.id,
                space=Ref(id=ref.id, name=ref.workspace.name),
                category=meta.category,
                scope="personal" if pessoal else "workspace",
                planned=meta.amount,
                spent=gasto,
                remaining=(Decimal(meta.amount) - gasto) if gasto is not None else None,
                over_budget=(gasto > Decimal(meta.amount)) if gasto is not None else None,
                currency=resumo["base_currency"],
            ))
    estouradas = [m for m in metas if m.over_budget]
    resumo_txt = f"{len(metas)} meta(s) em {chave}"
    if estouradas:
        resumo_txt += "; acima do orçamento: " + ", ".join(m.category for m in estouradas)
    return ToolOutput(structured=BudgetsOut(month=chave, budgets=metas), summary=resumo_txt + ".")


# --- reports_breakdown ------------------------------------------------------------------

class BreakdownIn(SearchFilters):
    group_by: Literal["category", "tag", "person", "card", "account", "payment_method", "month", "space", "title"] = Field(
        description=(
            "Eixo: category, tag, person (quanto cabe a CADA pessoa), card, account (conta de onde saiu), "
            "payment_method, month (competência), space, title (título normalizado: aproxima o estabelecimento)."
        ),
    )
    basis: Literal["my_share", "total"] = Field(
        "my_share", description="my_share = a SUA parte (padrão); total = o valor cheio dos lançamentos.",
    )
    limit: int = Field(15, ge=1, le=50, description="Grupos por moeda; o resto vem somado em `others`.")


class BreakdownGroup(BaseModel):
    id: Optional[int] = None
    name: str
    currency: str
    amount: MoneyOut
    count: int = Field(description="Quantos lançamentos entraram neste grupo.")
    percent: str = Field(description="Participação no total da moeda (\"23.5\").")


class BreakdownOut(BaseModel):
    group_by: str
    basis: str
    groups: List[BreakdownGroup]
    others: List[BreakdownGroup] = Field(default_factory=list, description="Soma do que passou de `limit`, por moeda.")
    totals: dict[str, MoneyOut] = Field(description="Total do filtro por moeda (mesma base).")
    resolved: ResolvedFilters


@tool(
    name="reports_breakdown",
    title="Gastos agrupados",
    description=(
        "Soma os gastos do filtro por um eixo — categoria, tag, pessoa, cartão, conta, forma de "
        "pagamento, mês, espaço ou título (≈ estabelecimento) — direto do banco, com a sua parte ou o "
        "valor cheio. Aceita os mesmos filtros de transactions_search (período, texto, cartão, "
        "categoria, pessoa…).\n"
        "Use quando: 'quanto gastei em cada mercado nos últimos 6 meses?', 'quanto foi em cada cartão "
        "este ano?', 'quanto a Maria consumiu da casa?', séries por mês de uma categoria.\n"
        "Não use quando: quiser o resumo pronto do mês (reports_summary) ou os lançamentos um a um "
        "(transactions_search). Não pagine a busca para somar: use esta tool."
    ),
    input_model=BreakdownIn,
    output_model=BreakdownOut,
    cost=3,
    invoking="Somando…",
    invoked="Soma pronta",
    **_LEITURA,
)
def reports_breakdown(call: ToolCall) -> ToolOutput:
    a: BreakdownIn = call.args
    memberships, filtros, resolvido = build_filters(call, a)
    try:
        grupos = transaction_query.breakdown(
            call.session, memberships, filtros, me_id=call.identity.user_id, group_by=a.group_by, basis=a.basis,
        )
    except transaction_query.BreakdownTooLarge as exc:
        raise McpToolError(ErrorCode.VALIDATION_ERROR, str(exc))
    totais: dict[str, Decimal] = {}
    for g in grupos:
        totais[g.currency] = totais.get(g.currency, Decimal("0.00")) + g.amount
    saida_grupos: list[BreakdownGroup] = []
    outros: dict[str, list] = {}
    usados: dict[str, int] = {}
    for g in grupos:
        total_moeda = totais[g.currency]
        pct = format((g.amount * 100 / total_moeda).quantize(Decimal("0.1")), "f") if total_moeda else "0.0"
        if usados.get(g.currency, 0) < a.limit:
            usados[g.currency] = usados.get(g.currency, 0) + 1
            saida_grupos.append(BreakdownGroup(id=g.id, name=g.name, currency=g.currency, amount=g.amount, count=g.count, percent=pct))
        else:
            linha = outros.setdefault(g.currency, [Decimal("0.00"), 0])
            linha[0] += g.amount
            linha[1] += g.count
    saida = BreakdownOut(
        group_by=a.group_by,
        basis=a.basis,
        groups=saida_grupos,
        others=[
            BreakdownGroup(
                name="Outros", currency=m, amount=v[0], count=v[1],
                percent=format((v[0] * 100 / totais[m]).quantize(Decimal("0.1")), "f") if totais[m] else "0.0",
            )
            for m, v in outros.items()
        ],
        totals=totais,
        resolved=resolvido,
    )
    topo = ", ".join(f"{g.name} {fmt_brl(g.amount, g.currency)}" for g in saida_grupos[:3])
    return ToolOutput(
        structured=saida,
        summary=(
            f"{len(grupos)} grupo(s) por {a.group_by} ({'sua parte' if a.basis == 'my_share' else 'valor cheio'})"
            + (f"; maiores: {topo}." if topo else ".")
        ),
        widget={"view": "breakdown"},
    )
