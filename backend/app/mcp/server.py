"""A instância do servidor MCP (SDK oficial `mcp` 2.x) e o registro das tools.

Cada `ToolSpec` do `registry` vira um `Tool` do SDK com o schema JÁ PRONTO e um
"pass-through" dos argumentos: o SDK anuncia o schema e entrega o dicionário
cru; quem valida e executa é `invoke.run`, que devolve o erro no envelope
estruturado. O SDK continua cuidando do protocolo inteiro — versões 2025-11-25
e 2026-07-28, `server/discover`, cache hints, JSON-RPC.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

from mcp.server import MCPServer
from mcp.server.apps import APP_MIME_TYPE, Apps, TextResource
from mcp.server.mcpserver.tools import Tool
from mcp.server.mcpserver.utilities.func_metadata import ArgModelBase, FuncMetadata
from mcp_types import CallToolResult, Icon, ToolAnnotations
from pydantic import ConfigDict

from app.core.config import settings
from app.mcp import instructions, invoke, registry
from app.mcp.ui import WIDGET_URI
from app.mcp.version import SERVER_VERSION  # noqa: F401 (reexportado: docs e tela de integrações)

SERVER_NAME = "controle-financeiro"
# A versão do contrato das tools (semver) mora em `app/mcp/version.py`.
_WIDGET_FILE = Path(__file__).parent / "ui" / "widget.html"


class _RawArgs(ArgModelBase):
    model_config = ConfigDict(extra="allow")


class _PassThrough(FuncMetadata):
    """Entrega os argumentos crus; a validação é do pipeline (`invoke.run`)."""

    def validate_arguments(self, arguments_to_validate: dict[str, Any]) -> dict[str, Any]:
        return {"arguments": dict(arguments_to_validate or {})}


def _sdk_tool(spec: registry.ToolSpec) -> Tool:
    def runner(arguments: dict[str, Any]) -> CallToolResult:
        return invoke.run(spec, arguments)

    runner.__name__ = spec.name
    return Tool(
        fn=runner,
        name=spec.name,
        title=spec.title,
        description=spec.description,
        parameters=registry.input_schema(spec),
        fn_metadata=_PassThrough(arg_model=_RawArgs, output_schema=registry.output_schema(spec)),
        is_async=False,
        context_kwarg=None,
        annotations=ToolAnnotations(
            title=spec.title,
            read_only_hint=spec.read_only,
            destructive_hint=spec.destructive,
            idempotent_hint=spec.idempotent,
            open_world_hint=spec.open_world,
        ),
        meta=spec.tool_meta(),
    )


def widget_html() -> str:
    return _WIDGET_FILE.read_text(encoding="utf-8")


@lru_cache(maxsize=1)
def get_server() -> MCPServer:
    import app.mcp.tools  # noqa: F401 — registra as tools no REGISTRY

    apps = Apps()
    # `add_resource` direto (e não `add_html_resource`) para declarar, junto do
    # `_meta.ui` padrão, a chave LEGADA do ChatGPT. A referência da OpenAI: o
    # `openExternal` só libera sem aviso os domínios de
    # `openai/widgetCSP.redirect_domains`, e é por ele que sai o botão "Abrir no
    # Controle Financeiro". A CSP continua vazia: o componente não busca nada fora
    # (os dados chegam pelo resultado da tool e pela ponte do host).
    apps.add_resource(
        TextResource(
            uri=WIDGET_URI,
            name="controle-financeiro-widget",
            title="Controle Financeiro",
            description="Cartões de lançamento, fatura, resumo do mês e prévia de ações em massa.",
            mime_type=APP_MIME_TYPE,
            meta={
                "ui": {"csp": {"connectDomains": [], "resourceDomains": []}, "prefersBorder": True},
                "openai/widgetCSP": {
                    "connect_domains": [],
                    "resource_domains": [],
                    "redirect_domains": [settings.oauth_issuer],
                },
            },
            text=widget_html(),
        )
    )
    return MCPServer(
        name=SERVER_NAME,
        title="Controle Financeiro",
        description="Finanças pessoais e compartilhadas: lançamentos, faturas, contas, dívidas e relatórios.",
        instructions=instructions.TEXT,
        website_url=settings.oauth_issuer,
        icons=[Icon(src=f"{settings.oauth_issuer}/icon-192.png", mime_type="image/png", sizes=["192x192"])],
        version=SERVER_VERSION,
        tools=[_sdk_tool(spec) for spec in registry.REGISTRY.values()],
        extensions=[apps],
    )
