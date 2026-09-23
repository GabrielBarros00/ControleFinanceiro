"""`ToolSpec`: a definição ÚNICA de cada tool.

Daqui saem três coisas que não podem divergir: o que o SDK anuncia em
`tools/list`, o que o pipeline aplica em `tools/call` (escopo, custo,
idempotência) e o `docs/mcp/TOOLS.md` (gerado por `app.mcp.docs`).

**Schemas próprios, não inferidos da assinatura.** Cada tool declara um modelo de
entrada (Pydantic, `extra="forbid"`) e um de saída. O SDK recebe o JSON Schema já
pronto e um "pass-through" dos argumentos: quem valida é o pipeline, que então
devolve o erro no envelope estruturado em vez da mensagem crua do Pydantic.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any, Callable, Literal, Optional, TYPE_CHECKING

from pydantic import BaseModel, ConfigDict

if TYPE_CHECKING:
    from sqlmodel import Session

    from app.mcp.identity import McpIdentity
    from app.models.user import User

Kind = Literal["read", "write", "destructive"]


class ToolInput(BaseModel):
    """Base de toda entrada: nada fora do schema passa, e texto vem aparado."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class NoInput(ToolInput):
    """Tool sem parâmetros (`{"type":"object","additionalProperties":false}`)."""


@dataclass
class ToolCall:
    session: "Session"
    identity: "McpIdentity"
    user: "User"
    args: Any
    spec: "ToolSpec"


@dataclass
class ToolOutput:
    structured: BaseModel
    #: Uma ou duas frases em pt-BR para o modelo (e para clientes sem UI).
    summary: str
    entity_type: Optional[str] = None
    entity_ids: list[int] = field(default_factory=list)
    space_id: Optional[int] = None
    #: Referências gravadas na chave de idempotência (nunca o conteúdo).
    result_ref: Optional[dict] = None
    #: Efeitos que só podem acontecer DEPOIS do commit (ex.: liberar blobs).
    after_commit: list[Callable[[], None]] = field(default_factory=list)
    #: `_meta` só para a UI (o modelo não vê): links, contexto de exibição.
    widget: Optional[dict] = None
    replayed: bool = False


Handler = Callable[[ToolCall], ToolOutput]
Replayer = Callable[[ToolCall, dict], ToolOutput]


@dataclass(frozen=True)
class ToolSpec:
    name: str
    title: str
    description: str
    input_model: type[BaseModel]
    output_model: type[BaseModel]
    handler: Handler
    scope: str
    kind: Kind
    read_only: bool
    destructive: bool
    idempotent: bool
    open_world: bool = False
    #: Unidades do balde por minuto (leitura 1, busca/relatório 2, escrita 3, massa 5).
    cost: int = 1
    #: Exige `idempotency_key` e grava `mcpoperation` na mesma transação.
    idempotency_key: bool = False
    replay: Optional[Replayer] = None
    #: URI `ui://` do componente MCP Apps que renderiza o resultado.
    ui: Optional[str] = None
    #: Pode ser chamada de dentro do componente (ex.: botão "Confirmar").
    app_callable: bool = False
    invoking: Optional[str] = None
    invoked: Optional[str] = None
    meta: dict = field(default_factory=dict)
    examples: tuple = ()

    def annotations(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "readOnlyHint": self.read_only,
            "destructiveHint": self.destructive,
            "idempotentHint": self.idempotent,
            "openWorldHint": self.open_world,
        }

    def tool_meta(self) -> dict[str, Any]:
        """`_meta` do descritor: padrão MCP Apps + aliases de compatibilidade."""
        meta: dict[str, Any] = {
            # Espelho em `_meta` do `securitySchemes` (OpenAI): clientes que só
            # leem `_meta` descobrem que a tool exige OAuth e qual escopo.
            "securitySchemes": [{"type": "oauth2", "scopes": [self.scope]}],
        }
        ui: dict[str, Any] = {}
        if self.ui:
            ui["resourceUri"] = self.ui
            meta["openai/outputTemplate"] = self.ui
        if self.app_callable:
            ui["visibility"] = ["model", "app"]
            meta["openai/widgetAccessible"] = True
        if ui:
            meta["ui"] = ui
        if self.invoking:
            meta["openai/toolInvocation/invoking"] = self.invoking[:64]
        if self.invoked:
            meta["openai/toolInvocation/invoked"] = self.invoked[:64]
        meta.update(self.meta)
        return meta


REGISTRY: dict[str, ToolSpec] = {}


def tool(**kwargs: Any) -> Callable[[Handler], Handler]:
    """Registra a função como tool. A ordem de registro é a ordem do `tools/list`."""

    def decorator(fn: Handler) -> Handler:
        spec = ToolSpec(handler=fn, **kwargs)
        anterior = REGISTRY.get(spec.name)
        # Reimportar o MESMO módulo (import que falhou no meio e foi refeito)
        # substitui; dois módulos com o mesmo nome de tool é erro de autoria.
        if anterior is not None and (anterior.handler.__module__, anterior.handler.__qualname__) != (
            fn.__module__, fn.__qualname__
        ):
            raise ValueError(f"tool duplicada: {spec.name}")
        REGISTRY[spec.name] = spec
        return fn

    return decorator


def _inline_refs(schema: dict[str, Any]) -> dict[str, Any]:
    """Resolve `$ref` → `$defs` em linha.

    A spec 2026-07-28 aceita `$ref`, mas clientes da geração 2025 nem sempre
    resolvem — e o que um cliente não resolve vira "argumento sem schema" para o
    modelo. Os modelos daqui não são recursivos, então a expansão termina.
    """
    definicoes = schema.get("$defs", {})

    def expande(no: Any) -> Any:
        if isinstance(no, dict):
            if "$ref" in no and isinstance(no["$ref"], str) and no["$ref"].startswith("#/$defs/"):
                nome = no["$ref"].split("/")[-1]
                alvo = copy.deepcopy(definicoes[nome])
                extras = {k: v for k, v in no.items() if k != "$ref"}
                resolvido = expande(alvo)
                resolvido.update(extras)
                return resolvido
            return {k: expande(v) for k, v in no.items() if k != "$defs"}
        if isinstance(no, list):
            return [expande(v) for v in no]
        return no

    return expande(schema)


def input_schema(spec: ToolSpec) -> dict[str, Any]:
    esquema = _inline_refs(spec.input_model.model_json_schema())
    esquema.setdefault("type", "object")
    esquema.setdefault("additionalProperties", False)
    esquema.pop("title", None)
    return esquema


def output_schema(spec: ToolSpec) -> dict[str, Any]:
    esquema = _inline_refs(spec.output_model.model_json_schema(mode="serialization"))
    esquema.pop("title", None)
    return esquema
