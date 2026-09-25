"""Descoberta: espaços, pessoas, categorias/tags, cartões e contas.

São as tools que o modelo usa para achar IDs quando um nome é ambíguo, e para
responder perguntas diretas ("quais cartões eu tenho?", "qual meu saldo?"). Tudo
somente leitura, sem materialização preguiçosa: o que se lê é o que está gravado.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import List, Optional

from pydantic import BaseModel, Field

from app.domain.access_policy import has_full_access
from app.domain.dates import today_local
from app.mcp import resolve
from app.mcp.money import MoneyOut, fmt_brl
from app.mcp.registry import NoInput, ToolCall, ToolInput, ToolOutput, tool
from app.mcp.schemas import Ref, SpaceOut
from app.mcp.serializers import civil
from app.schemas.balance import BalanceRead
from app.services.account_balance_service import AccountBalanceService
from app.services.credit_card_service import CreditCardService
from app.services.oauth import scopes as escopos
from app.services.projection_service import ProjectionService

_LEITURA = dict(
    scope=escopos.FINANCE_READ, kind="read", read_only=True, destructive=False, idempotent=True,
)


# --- spaces_list ----------------------------------------------------------------------

class SpacesOut(BaseModel):
    spaces: List[SpaceOut]


@tool(
    name="spaces_list",
    title="Listar espaços",
    description=(
        "Lista os espaços (grupos financeiros: pessoal, casa, viagem…) de que você participa, "
        "com moeda-base, seu papel e quantos membros há.\n"
        "Use quando: precisar escolher/confirmar em qual espaço registrar algo, ou o usuário "
        "perguntar em quais espaços participa.\n"
        "Não use quando: quiser as pessoas de um espaço (people_list) ou valores (reports_summary)."
    ),
    input_model=NoInput,
    output_model=SpacesOut,
    **_LEITURA,
)
def spaces_list(call: ToolCall) -> ToolOutput:
    espacos = resolve.user_spaces(call.session, call.identity.user_id)
    saida = SpacesOut(spaces=[
        SpaceOut(
            id=r.id,
            name=r.workspace.name,
            base_currency=r.workspace.base_currency,
            my_role=getattr(r.membership.role, "value", r.membership.role),
            full_access=has_full_access(r.membership),
            members=r.member_count,
            personal=r.is_personal,
        )
        for r in espacos
    ])
    return ToolOutput(structured=saida, summary=f"{len(espacos)} espaço(s).")


# --- people_list ----------------------------------------------------------------------

class PeopleIn(ToolInput):
    space: Optional[str] = Field(None, max_length=120, description="Nome do espaço (opcional).")
    space_id: Optional[int] = Field(None, description="ID do espaço (opcional).")
    query: Optional[str] = Field(None, min_length=1, max_length=80, description="Filtra pelo nome da pessoa.")


class PersonSpace(BaseModel):
    id: int
    name: str
    role: str


class PersonOut(BaseModel):
    id: int
    name: str
    is_me: bool
    spaces: List[PersonSpace]


class PeopleOut(BaseModel):
    people: List[PersonOut]


@tool(
    name="people_list",
    title="Listar pessoas",
    description=(
        "Lista as pessoas (membros) dos seus espaços, com o papel de cada uma. Só membros de um "
        "espaço podem entrar numa divisão de despesa.\n"
        "Use quando: o usuário citar alguém ('divide com o João') e for preciso confirmar quem é "
        "ou resolver um nome ambíguo; ou perguntar quem participa de um espaço.\n"
        "Não use quando: quiser saber quanto alguém deve (debts_summary)."
    ),
    input_model=PeopleIn,
    output_model=PeopleOut,
    **_LEITURA,
    app_callable=True,
)
def people_list(call: ToolCall) -> ToolOutput:
    a: PeopleIn = call.args
    alvo = resolve.resolve_space(call.session, call.identity.user_id, space_id=a.space_id, space=a.space)
    espacos = [alvo] if alvo else resolve.user_spaces(call.session, call.identity.user_id)
    pessoas: dict[int, PersonOut] = {}
    for ref in espacos:
        for m in resolve.space_members(call.session, ref.id):
            pessoa = pessoas.setdefault(
                m.id, PersonOut(id=m.id, name=m.name, is_me=m.id == call.identity.user_id, spaces=[])
            )
            pessoa.spaces.append(PersonSpace(id=ref.id, name=ref.workspace.name, role=m.extra["role"]))
    lista = list(pessoas.values())
    if a.query:
        achados = {m.id for m in resolve.find(a.query, [resolve.Match(p.id, p.name) for p in lista])}
        lista = [p for p in lista if p.id in achados]
    return ToolOutput(structured=PeopleOut(people=lista), summary=f"{len(lista)} pessoa(s).")


# --- categories_list ------------------------------------------------------------------

class CategoriesIn(ToolInput):
    space: Optional[str] = Field(None, max_length=120, description="Nome do espaço. Omitido: seu único espaço.")
    space_id: Optional[int] = None


class MerchantOut(BaseModel):
    id: int
    name: str
    aliases: List[str] = Field(default_factory=list, description="Grafias do extrato que vinculam sozinhas.")
    default_category: Optional[str] = None


class CategoriesOut(BaseModel):
    space: Ref
    categories: List[Ref]
    tags: List[Ref]
    merchants: List[MerchantOut] = Field(default_factory=list, description="Estabelecimentos (onde se compra).")


@tool(
    name="categories_list",
    title="Categorias, tags e estabelecimentos",
    description=(
        "Lista as categorias, as tags e os estabelecimentos (com apelidos) de um espaço (cada espaço tem os seus).\n"
        "Use quando: precisar escolher a categoria de um lançamento, resolver um nome de "
        "categoria ambíguo ou o usuário perguntar quais categorias existem.\n"
        "Não use quando: quiser o gasto por categoria (reports_summary)."
    ),
    input_model=CategoriesIn,
    output_model=CategoriesOut,
    **_LEITURA,
    app_callable=True,
)
def categories_list(call: ToolCall) -> ToolOutput:
    a: CategoriesIn = call.args
    ref = resolve.require_space(call.session, call.identity.user_id, space_id=a.space_id, space=a.space)
    categorias = resolve.space_categories(call.session, ref.id)
    nome_da_categoria = {c.id: c.name for c in categorias}
    saida = CategoriesOut(
        space=Ref(id=ref.id, name=ref.workspace.name),
        categories=[Ref(id=c.id, name=c.name) for c in categorias],
        tags=[Ref(id=t.id, name=t.name) for t in resolve.space_tags(call.session, ref.id)],
        merchants=[
            MerchantOut(id=m.id, name=m.name, aliases=list(m.aliases or []),
                        default_category=nome_da_categoria.get(m.default_category_id))
            for m in resolve.space_merchants(call.session, ref.id)
        ],
    )
    return ToolOutput(
        structured=saida,
        summary=(
            f"{len(saida.categories)} categoria(s), {len(saida.tags)} tag(s) e "
            f"{len(saida.merchants)} estabelecimento(s) em {ref.workspace.name}."
        ),
        space_id=ref.id,
    )


# --- cards_list -----------------------------------------------------------------------

class CurrentStatement(BaseModel):
    month: str = Field(description="Fatura do ciclo atual (YYYY-MM).")
    closing_date: date
    due_date: date
    amount: MoneyOut = Field(description="Total da fatura do ciclo atual até agora.")
    exists: bool = Field(description="False = ainda sem compras neste ciclo.")


class AttentionStatement(BaseModel):
    month: str
    due_date: date
    balance: MoneyOut = Field(description="Saldo em aberto da fatura mais antiga não quitada.")
    overdue: bool


class CardOut(BaseModel):
    id: int
    name: str
    currency: str
    limit: MoneyOut
    available_limit: MoneyOut
    closing_day: int
    due_day: int
    current_statement: CurrentStatement
    attention: Optional[AttentionStatement] = Field(None, description="Fatura a pagar que pede atenção.")


class CardsOut(BaseModel):
    cards: List[CardOut]


@tool(
    name="cards_list",
    title="Listar cartões",
    description=(
        "Lista seus cartões de crédito com limite disponível, dia de fechamento/vencimento, a "
        "fatura do ciclo atual e a fatura em aberto mais urgente.\n"
        "Use quando: o usuário perguntar sobre cartões/limite, ou for preciso achar o ID de um "
        "cartão citado por nome ambíguo.\n"
        "Não use quando: quiser as compras de uma fatura (statements_get)."
    ),
    input_model=NoInput,
    output_model=CardsOut,
    **_LEITURA,
    app_callable=True,
)
def cards_list(call: ToolCall) -> ToolOutput:
    hoje = today_local()
    cartoes = []
    for cartao in resolve.user_cards(call.session, call.identity.user_id):
        panorama = CreditCardService.card_overview(call.session, cartao)
        alvo = CreditCardService.preview_statement_target(call.session, cartao, hoje)
        atual = next((s for s in panorama["statements"] if s.month == alvo["month"]), None)
        total_atual = CreditCardService.effective_total(call.session, atual) if atual else Decimal("0")
        atencao = panorama["attention"]
        cartoes.append(CardOut(
            id=cartao.id,
            name=cartao.name,
            currency=cartao.currency,
            limit=cartao.limit,
            available_limit=CreditCardService.available_limit(panorama["committed"], cartao),
            closing_day=cartao.closing_day,
            due_day=cartao.due_day,
            current_statement=CurrentStatement(
                month=alvo["month"],
                closing_date=civil(alvo["closing_date"]),
                due_date=civil(alvo["due_date"]),
                amount=total_atual,
                exists=atual is not None,
            ),
            attention=AttentionStatement(
                month=atencao.month,
                due_date=civil(atencao.due_date),
                balance=panorama["attention_total"],
                overdue=CreditCardService.is_overdue(atencao, hoje),
            ) if atencao is not None else None,
        ))
    return ToolOutput(structured=CardsOut(cards=cartoes), summary=f"{len(cartoes)} cartão(ões).")


# --- accounts_list --------------------------------------------------------------------

class AccountOut(BaseModel):
    id: int
    name: str
    type: str
    currency: str
    balance: Optional[MoneyOut] = Field(None, description="Saldo atual; null = saldo inicial não configurado.")
    active: bool
    is_default: bool


class ProjectionItem(BaseModel):
    kind: str
    label: str
    amount: MoneyOut
    count: int


class AccountsOut(BaseModel):
    currency: str
    total: Optional[MoneyOut] = Field(None, description="Soma dos saldos na moeda de relatório.")
    accounts: List[AccountOut]
    month: str
    projected_balance: Optional[MoneyOut] = Field(None, description="Saldo previsto no fim do mês.")
    receivable_total: MoneyOut
    payable_total: MoneyOut
    overdue_total: MoneyOut
    projection: List[ProjectionItem]


@tool(
    name="accounts_list",
    title="Contas e saldo",
    description=(
        "Lista suas contas (corrente, poupança, carteira…) com o saldo atual de cada uma, o "
        "total e o saldo PREVISTO para o fim do mês (a receber − a pagar).\n"
        "Use quando: o usuário perguntar 'qual meu saldo', 'quanto vou ter no fim do mês', ou "
        "for preciso achar o ID de uma conta.\n"
        "Não use quando: quiser gastos do mês (reports_summary) ou contas a pagar em detalhe (payables_list)."
    ),
    input_model=NoInput,
    output_model=AccountsOut,
    **_LEITURA,
    app_callable=True,
)
def accounts_list(call: ToolCall) -> ToolOutput:
    hoje = today_local()
    saldos = AccountBalanceService.balances(call.session, call.identity.user_id)
    projecao = ProjectionService.ate_o_fim_do_mes(
        call.session, call.identity.user_id, date(hoje.year, hoje.month, 1), saldos["currency"], saldos["total"]
    )
    dados = BalanceRead.model_validate({**saldos, **projecao})
    saida = AccountsOut(
        currency=dados.currency,
        total=dados.total,
        accounts=[
            AccountOut(
                id=c.account_id, name=c.name, type=getattr(c.type, "value", c.type), currency=c.currency,
                balance=c.balance, active=c.active, is_default=c.is_default,
            )
            for c in dados.accounts
        ],
        month=dados.month,
        projected_balance=dados.projected_balance,
        receivable_total=dados.receivable_total,
        payable_total=dados.payable_total,
        overdue_total=dados.overdue_total,
        projection=[ProjectionItem(kind=x.kind, label=x.label, amount=x.amount, count=x.count) for x in dados.breakdown],
    )
    resumo = f"Saldo total {fmt_brl(saida.total, saida.currency)}"
    if saida.projected_balance is not None:
        resumo += f"; previsto no fim do mês: {fmt_brl(saida.projected_balance, saida.currency)}"
    return ToolOutput(structured=saida, summary=resumo + ".")
