"""`profile_get` — qual conta está conectada, e o que a IA precisa saber para começar.

Além de identificar a conta (a OpenAI usa esta tool, marcada com
`_meta["openai/profile"]`, para distinguir contas quando a pessoa conecta mais de
uma), devolve o **dia de hoje e o fuso da conta**: é daqui que o modelo tira a
data para converter "hoje"/"ontem"/"mês passado" antes de chamar as outras tools
— o servidor nunca adivinha data.
"""
from __future__ import annotations

from datetime import date
from typing import List

from pydantic import BaseModel, Field

from app.core.config import settings
from app.domain.dates import today_local
from app.domain.query_policy import user_report_currency
from app.mcp.registry import NoInput, ToolCall, ToolOutput, tool
from app.mcp.version import SERVER_VERSION
from app.services.oauth import scopes as escopos


class ConnectionInfo(BaseModel):
    client: str = Field(description="Nome do aplicativo conectado, como ele se apresentou.")
    scopes: List[str] = Field(description="Permissões concedidas a esta conexão.")


class ProfileOut(BaseModel):
    id: str = Field(description="Identificador público, opaco e estável da conta.")
    name: str
    email: str
    nickname: str
    environment: str = Field(description="production | staging | development")
    timezone: str = Field(description="Fuso de TODAS as datas da conta (IANA).")
    today: date = Field(description="Hoje, no fuso da conta — use para resolver 'hoje', 'ontem', 'este mês'.")
    report_currency: str = Field(description="Moeda dos números pessoais (ISO-4217).")
    app_url: str
    connection: ConnectionInfo
    server_version: str = Field(description="Versão do servidor MCP (semver).")
    capabilities: List[str] = Field(
        description=(
            "O que este servidor sabe fazer além do básico (ex.: transaction_items, account_ledger, "
            "attachment_read, attachment_from_chat, history, versions, undo_import)."
        ),
    )


def _capacidades() -> List[str]:
    lista = [
        "transaction_items", "adjustments", "purchase_view", "versions", "history",
        "account_ledger", "transfers", "statement_reopen", "recurring_income", "recurring_get",
        "financing_installments", "attachment_read", "attachment_upload_terminal",
        "categories_tags_manage", "reports_breakdown", "bulk_update", "undo_import",
    ]
    if settings.mcp_file_url_hosts_list:
        lista.append("attachment_from_chat")
    return lista


@tool(
    name="profile_get",
    title="Conta conectada",
    description=(
        "Mostra qual conta do Controle Financeiro está conectada, as permissões desta "
        "conexão, o fuso horário e a data de HOJE da conta.\n"
        "Use quando: no início da conversa, para saber a data de hoje antes de interpretar "
        "'hoje/ontem/este mês', ou quando o usuário perguntar qual conta está conectada.\n"
        "Não use quando: precisar de dados financeiros — use as tools de consulta."
    ),
    input_model=NoInput,
    output_model=ProfileOut,
    scope=escopos.FINANCE_READ,
    kind="read",
    read_only=True,
    destructive=False,
    idempotent=True,
    meta={"openai/profile": True},
)
def profile_get(call: ToolCall) -> ToolOutput:
    user = call.user
    saida = ProfileOut(
        id=user.public_id,
        name=user.name,
        email=user.email,
        nickname=f"{user.name} — Controle Financeiro",
        environment=settings.APP_ENV,
        timezone=settings.APP_TIMEZONE,
        today=today_local(),
        report_currency=user_report_currency(call.session, user.id),
        app_url=settings.oauth_issuer,
        connection=ConnectionInfo(
            client=call.identity.client_name,
            scopes=sorted(call.identity.scopes, key=lambda s: escopos.ALL_SCOPES.index(s) if s in escopos.ALL_SCOPES else 99),
        ),
        server_version=SERVER_VERSION,
        capabilities=_capacidades(),
    )
    return ToolOutput(
        structured=saida,
        summary=f"Conta conectada: {user.name}. Hoje é {saida.today.isoformat()} ({settings.APP_TIMEZONE}).",
    )
