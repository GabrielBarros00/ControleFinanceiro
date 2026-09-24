"""`view_show`: desenha uma TELA na conversa (ADR 0035 §11).

As tools de dados devolvem só dados — o componente nelas fazia o ChatGPT criar um
iframe a cada consulta do agente (§8). Para o usuário VER algo, há tools de
exibição. Em vez de uma `*_show` por tela (dez tools a mais no catálogo que o
modelo lê em toda conversa), uma só: `view_show(view=…)`.

Ela não tem regra própria: monta a entrada da tool de dados correspondente e chama
o MESMO handler. O `_meta` leva a consulta (`query`), para o componente paginar,
trocar o mês ou expandir uma linha chamando a tool de dados — sem desenhar outro
componente.
"""
from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, model_validator

from app.mcp.dates import CivilDate, MonthKey
from app.mcp.registry import REGISTRY, ToolCall, ToolInput, ToolOutput, tool
from app.mcp.ui import WIDGET_URI
from app.services.oauth import scopes as escopos

View = Literal[
    "transactions", "account", "cash", "breakdown", "debts", "payables", "budgets",
    "recurring", "income", "financing", "history", "imports",
]

#: O que a TELA pede a mais que a tool de dados não traz por padrão.
_PADRAO_DA_TELA: dict[str, dict[str, Any]] = {
    "debts": {"include_history": True},
}

#: Tela → (tool de dados, campos da entrada de `view_show` que ela aceita).
_TELAS: dict[str, tuple[str, tuple[str, ...]]] = {
    "transactions": ("transactions_search", (
        "space", "space_id", "text", "date_from", "date_to", "month", "card", "category", "tag", "person",
        "uncategorized", "settled",
    )),
    "breakdown": ("reports_breakdown", (
        "space", "space_id", "text", "date_from", "date_to", "month", "card", "category", "tag", "person",
        "group_by", "basis",
    )),
    "account": ("accounts_statement", ("account", "account_id", "month")),
    "cash": ("accounts_statement", ("month",)),
    "debts": ("debts_summary", ("space", "space_id", "person", "month")),
    "payables": ("payables_list", ("space", "space_id", "month")),
    "budgets": ("budgets_list", ("space", "space_id", "month")),
    "recurring": ("recurring_list", ("space", "space_id", "kind")),
    "income": ("income_list", ("month",)),
    "financing": ("financings_list", ("financing",)),
    "history": ("transactions_history", ("transaction_id",)),
    "imports": ("imports_list", ("batch_id",)),
}


class ViewIn(ToolInput):
    view: View = Field(
        description=(
            "transactions (lista com filtros), breakdown (gastos agrupados), account (extrato de uma conta), "
            "cash (caixa do mês), debts, payables (a pagar), budgets (metas), recurring, income, financing, "
            "history (de um lançamento), imports."
        ),
    )
    space: Optional[str] = Field(None, max_length=120)
    space_id: Optional[int] = None
    month: Optional[MonthKey] = None
    text: Optional[str] = Field(None, min_length=1, max_length=80)
    date_from: Optional[CivilDate] = None
    date_to: Optional[CivilDate] = None
    card: Optional[str] = Field(None, max_length=120)
    category: Optional[str] = Field(None, max_length=120)
    tag: Optional[str] = Field(None, max_length=60)
    person: Optional[str] = Field(None, max_length=120)
    uncategorized: Optional[bool] = None
    settled: Optional[bool] = None
    group_by: Optional[Literal["category", "tag", "person", "card", "account", "payment_method", "month", "space", "title"]] = None
    basis: Optional[Literal["my_share", "total"]] = None
    account: Optional[str] = Field(None, max_length=120)
    account_id: Optional[int] = None
    kind: Optional[Literal["all", "expense", "income"]] = None
    financing: Optional[str] = Field(None, max_length=120)
    transaction_id: Optional[int] = Field(None, ge=1)
    batch_id: Optional[int] = Field(None, ge=1)

    @model_validator(mode="after")
    def _coerente(self):
        aceitos = set(_TELAS[self.view][1]) | {"view"}
        usados = {k for k, v in self.model_dump(exclude_none=True).items()}
        sobrando = sorted(usados - aceitos)
        if sobrando:
            raise ValueError(f"view={self.view} não usa {', '.join(sobrando)}")
        if self.view == "breakdown" and self.group_by is None:
            raise ValueError("view=breakdown precisa de group_by")
        if self.view == "history" and self.transaction_id is None:
            raise ValueError("view=history precisa de transaction_id")
        if self.view == "account" and self.account is None and self.account_id is None:
            raise ValueError("view=account precisa de account (ou use view=cash)")
        return self


class ViewOut(BaseModel):
    view: str
    source_tool: str = Field(description="A tool de dados cuja saída está em `data`.")
    data: dict[str, Any] = Field(description="A MESMA saída da tool de dados (ver `source_tool` em TOOLS.md).")


@tool(
    name="view_show",
    title="Mostrar na conversa",
    description=(
        "Desenha uma tela na conversa, com os mesmos números da tool de dados: lista de lançamentos "
        "filtrada (paginável, com edição), gastos agrupados, extrato de conta, caixa do mês, dívidas, "
        "a pagar, metas, recorrências, rendas, financiamento, histórico de um lançamento ou importações.\n"
        "Use quando: o usuário pedir para VER ou MOSTRAR uma dessas telas. Chame uma vez, no fim.\n"
        "Não use quando: precisar dos dados para responder ou analisar (use a tool de dados): cada "
        "chamada desenha um componente novo na conversa. Um lançamento: transactions_show; fatura: "
        "statements_show; resumo do mês: reports_show."
    ),
    input_model=ViewIn,
    output_model=ViewOut,
    scope=escopos.FINANCE_READ,
    kind="read",
    read_only=True,
    destructive=False,
    idempotent=True,
    cost=2,
    ui=WIDGET_URI,
    invoking="Montando a tela…",
    invoked="Tela pronta",
    meta={"openai/widgetDescription": (
        "O componente já mostra a tela pedida, com paginação e ações. Não repita os números; "
        "comente só o que o usuário perguntou."
    )},
)
def view_show(call: ToolCall) -> ToolOutput:
    a: ViewIn = call.args
    fonte, campos = _TELAS[a.view]
    spec = REGISTRY[fonte]
    entrada = {k: v for k, v in a.model_dump(mode="json", exclude_none=True).items() if k in campos}
    entrada.update(_PADRAO_DA_TELA.get(a.view, {}))
    sub = ToolCall(session=call.session, identity=call.identity, user=call.user,
                   args=spec.input_model.model_validate(entrada), spec=spec)
    saida = spec.handler(sub)
    dados = saida.structured.model_dump(mode="json", by_alias=True)
    extras: dict[str, Any] = {}
    if a.view == "transactions" and call.identity.has(escopos.TRANSACTIONS_WRITE):
        # O editor das linhas: o vocabulário de cada espaço presente na página.
        from app.mcp import ui_meta

        espacos = sorted({i["space"]["id"] for i in dados.get("items", [])})[:5]
        extras["forms"] = {str(e): ui_meta.form_for_space(call, e) for e in espacos}
    if a.view in ("account", "cash", "payables") and call.identity.has(escopos.ACCOUNTS_WRITE):
        from app.mcp import ui_meta

        extras["accounts"] = ui_meta.my_accounts(call)
    return ToolOutput(
        structured=ViewOut(view=a.view, source_tool=fonte, data=dados),
        summary=saida.summary,
        entity_type=saida.entity_type,
        entity_ids=saida.entity_ids,
        space_id=saida.space_id,
        widget={"view": a.view, "query": {"tool": fonte, "args": entrada}, **extras, **{
            k: v for k, v in (saida.widget or {}).items() if k == "app_url"
        }},
    )
