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


def _enxuga(no: Any, *, colapsa_nulo: bool) -> Any:
    """Tira do schema o que o Pydantic gera e ninguém lê.

    O catálogo (`tools/list`) entra no contexto do modelo em TODA conversa, e
    media ~200 mil caracteres. Sai:

    - o `title` automático de cada campo ("Space Id"), que só repete o nome;
    - em schema de ENTRADA, `anyOf: [X, {"type": "null"}]` com `default: null`
      vira só `X`. O campo é opcional, então omitir já é o nulo, e o pipeline
      valida com o modelo Pydantic, que segue aceitando `null`. A descrição do
      CAMPO prevalece sobre a do tipo, que era repetida em cada data.

    Em schema de SAÍDA o nulo fica: a resposta traz `null` de verdade, e o cliente
    valida o `structuredContent` contra o `outputSchema`.
    """
    if isinstance(no, list):
        return [_enxuga(v, colapsa_nulo=colapsa_nulo) for v in no]
    if not isinstance(no, dict):
        return no
    no = {k: v for k, v in no.items() if k != "title"}
    if colapsa_nulo:
        ramos = no.get("anyOf")
        if (
            isinstance(ramos, list) and len(ramos) == 2 and {"type": "null"} in ramos
            and no.get("default") is None
        ):
            valor = next(r for r in ramos if r != {"type": "null"})
            externo = {k: v for k, v in no.items() if k not in ("anyOf", "default")}
            interno = {
                k: v for k, v in valor.items()
                if k != "title" and not ("description" in externo and k == "description")
            }
            no = {**interno, **externo}
        elif "default" in no and no["default"] is None:
            no.pop("default")
    saida: dict[str, Any] = {}
    for chave, valor in no.items():
        if chave == "properties" and isinstance(valor, dict):
            # As CHAVES aqui são nomes de campo (há um campo chamado `title`).
            saida[chave] = {nome: _enxuga(esq, colapsa_nulo=colapsa_nulo) for nome, esq in valor.items()}
        else:
            saida[chave] = _enxuga(valor, colapsa_nulo=colapsa_nulo)
    return saida


def input_schema(spec: ToolSpec) -> dict[str, Any]:
    esquema = _enxuga(_inline_refs(spec.input_model.model_json_schema()), colapsa_nulo=True)
    esquema.setdefault("type", "object")
    esquema.setdefault("additionalProperties", False)
    # A docstring da classe de entrada é nota de quem programa, não do modelo:
    # o que ele precisa saber está na descrição da tool.
    esquema.pop("description", None)
    return esquema


def output_schema(spec: ToolSpec) -> dict[str, Any]:
    esquema = _enxuga(_inline_refs(spec.output_model.model_json_schema(mode="serialization")), colapsa_nulo=False)
    esquema.pop("description", None)
    return esquema
