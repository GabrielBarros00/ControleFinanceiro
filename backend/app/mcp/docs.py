"""Gera `docs/mcp/TOOLS.md` e `docs/mcp/CAPABILITY_MAP.md` — nenhum dos dois é escrito à mão.

    python -m app.mcp.docs            # (re)escreve os arquivos
    python -m app.mcp.docs --check    # falha se algum estiver desatualizado (CI)

Mesma fonte do `tools/list`: se uma descrição, annotation ou schema muda no
código, o CI obriga o doc a acompanhar no mesmo PR.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from app.mcp.errors import ErrorCode
from app.mcp.registry import REGISTRY, ToolSpec, input_schema, output_schema
from app.mcp.server import SERVER_NAME, SERVER_VERSION, get_server
from app.services.oauth import scopes as escopos

DESTINO = Path(__file__).resolve().parents[3] / "docs" / "mcp" / "TOOLS.md"
DESTINO_MAPA = DESTINO.with_name("CAPABILITY_MAP.md")

_CLASSE = {"read": "Leitura", "write": "Escrita", "destructive": "Destrutiva"}


def _tipo(no: dict[str, Any]) -> str:
    if "anyOf" in no:
        tipos = [_tipo(x) for x in no["anyOf"] if x.get("type") != "null"]
        return " \\| ".join(tipos) if tipos else "null"
    if "enum" in no:
        return " \\| ".join(f"`{v}`" for v in no["enum"])
    t = no.get("type", "object")
    if t == "array":
        return f"lista de {_tipo(no.get('items', {}))}"
    if t == "string" and no.get("format") == "date":
        return "data `YYYY-MM-DD`"
    if t == "object":
        return "objeto"
    return t


def _limites(no: dict[str, Any]) -> str:
    alvo = no
    if "anyOf" in no:
        alvo = next((x for x in no["anyOf"] if x.get("type") != "null"), no)
    partes = []
    for chave, rotulo in (("minimum", "≥"), ("maximum", "≤"), ("minLength", "mín."), ("maxLength", "máx."),
                          ("minItems", "mín."), ("maxItems", "máx.")):
        if chave in alvo:
            partes.append(f"{rotulo} {alvo[chave]}")
    if "pattern" in alvo and alvo.get("type") == "string" and "format" not in alvo:
        partes.append(f"padrão `{alvo['pattern']}`")
    return ", ".join(partes)


def _ancora(spec: ToolSpec) -> str:
    """Âncora no estilo do GitHub para o título da seção."""
    texto = f"{spec.name} — {spec.title}".lower()
    return "".join(ch for ch in texto if ch.isalnum() or ch in " -_").replace(" ", "-")


def _parametros(esquema: dict[str, Any]) -> list[str]:
    props = esquema.get("properties", {})
    if not props:
        return ["_Sem parâmetros._", ""]
    obrigatorios = set(esquema.get("required", []))
    linhas = ["| Parâmetro | Tipo | Obrigatório | Descrição |", "|---|---|---|---|"]
    for nome, no in props.items():
        descricao = (no.get("description") or "").replace("\n", " ").replace("|", "\\|")
        limite = _limites(no)
        if limite:
            descricao = f"{descricao} ({limite})" if descricao else limite
        linhas.append(f"| `{nome}` | {_tipo(no)} | {'sim' if nome in obrigatorios else 'não'} | {descricao} |")
    linhas.append("")
    return linhas


def _secao(spec: ToolSpec) -> list[str]:
    a = spec.annotations()
    linhas = [
        f"### `{spec.name}` — {spec.title}",
        "",
        f"- **Classe:** {_CLASSE[spec.kind]} · **Escopo:** `{spec.scope}` · **Custo:** {spec.cost} unidade(s)",
        f"- **Annotations:** readOnlyHint={str(a['readOnlyHint']).lower()}, destructiveHint={str(a['destructiveHint']).lower()}, "
        f"idempotentHint={str(a['idempotentHint']).lower()}, openWorldHint={str(a['openWorldHint']).lower()}",
    ]
    if spec.idempotency_key:
        linhas.append("- **Idempotência:** `idempotency_key` obrigatória (replay devolve o mesmo resultado; outra carga com a mesma chave = `CONFLICT`).")
    if spec.ui:
        linhas.append(f"- **UI (MCP Apps):** `{spec.ui}`" + (" · chamável pelo componente" if spec.app_callable else ""))
    linhas += ["", spec.description.replace("\n", "\n\n"), "", "**Entrada**", ""]
    linhas += _parametros(input_schema(spec))
    saida = output_schema(spec).get("properties", {})
    linhas += ["**Saída (`structuredContent`)**: " + ", ".join(f"`{k}`" for k in saida), ""]
    for exemplo in spec.examples:
        linhas += ["Exemplo:", "", "```json", json.dumps(exemplo, ensure_ascii=False), "```", ""]
    return linhas


def render() -> str:
    get_server()
    linhas = [
        "# Tools do servidor MCP",
        "",
        "<!-- GERADO por `python -m app.mcp.docs` a partir de `backend/app/mcp/registry.py`. Não edite à mão. -->",
        "",
        f"Servidor `{SERVER_NAME}` versão `{SERVER_VERSION}` · {len(REGISTRY)} tools · endpoint `/mcp` (Streamable HTTP).",
        "",
        "Convenções que valem para todas: dinheiro em string decimal com ponto (`\"89.90\"`, até 2 casas, nunca arredondado); "
        "datas `YYYY-MM-DD` e meses `YYYY-MM` no fuso da conta (`profile_get.timezone`); nomes resolvidos no servidor "
        "(ambíguo → `AMBIGUOUS` com candidatos); nenhuma tool aceita `user_id` — a identidade vem do token.",
        "",
        "## Escopos",
        "",
        "| Escopo | Para quê | Obrigatório |",
        "|---|---|---|",
    ]
    for s in escopos.SCOPES:
        linhas.append(f"| `{s.scope}` | {s.description} | {'sim' if s.required else 'não'} |")
    linhas += ["", "## Códigos de erro", "", "Toda falha volta com `isError: true` e `{\"error\": {code, message, details, retryable}}`.", ""]
    linhas += [", ".join(f"`{c.value}`" for c in ErrorCode), ""]
    linhas += ["## Índice", "", "| Tool | Título | Classe | Escopo |", "|---|---|---|---|"]
    for spec in REGISTRY.values():
        linhas.append(f"| [`{spec.name}`](#{_ancora(spec)}) | {spec.title} | {_CLASSE[spec.kind]} | `{spec.scope}` |")
    linhas += ["", "## Referência", ""]
    for spec in REGISTRY.values():
        linhas += _secao(spec)
    return "\n".join(linhas).rstrip() + "\n"


def render_capability_map() -> str:
    """`CAPABILITY_MAP.md`: funcionalidade → regra → peça do app → tool → classe → escopo → risco → efeito."""
    from app.mcp.capability_map import FICHAS, ROTAS

    get_server()
    linhas = [
        "# Mapa de capacidades: app → MCP",
        "",
        "<!-- GERADO por `python -m app.mcp.docs` a partir de `backend/app/mcp/capability_map.py` e do registro. Não edite à mão. -->",
        "",
        "Duas visões do mesmo contrato. A primeira parte da **tool**: que regra do app ela aplica, qual peça do código "
        "executa, que permissão exige e o que acontece de lado. A segunda parte da **rota REST**: toda rota do app aparece, "
        "com a tool que a cobre ou o motivo de não haver uma. O teste `tests/mcp/test_capability_map.py` reprova rota nova "
        "sem decisão.",
        "",
        "Confirmação: `host` = o cliente pede confirmação por não ser `readOnlyHint` (ChatGPT e Claude fazem isso); "
        "`servidor` = token de prévia emitido pelo servidor, de uso único. Autorização efetiva = escopo OAuth ∩ papel no "
        "espaço ∩ `access_policy`.",
        "",
        "## Por tool",
        "",
        "| Tool | Classe | Escopo | Regra do app | Peça (serviço/comando) | Risco | Efeito colateral | Confirmação | Idempotência |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for spec in REGISTRY.values():
        f = FICHAS[spec.name]
        if spec.kind == "read":
            confirmacao = "—"
        elif spec.name in {"transactions_bulk_delete", "transactions_bulk_categorize"}:
            confirmacao = "servidor (token) + host"
        else:
            confirmacao = "host"
        if spec.idempotency_key:
            idem = "`idempotency_key`"
        elif spec.name.startswith("transactions_bulk_") and spec.kind != "read":
            idem = "token de uso único"
        elif spec.kind == "read":
            idem = "natural"
        else:
            idem = "por estado (definir X)"
        linhas.append(
            f"| `{spec.name}` | {_CLASSE[spec.kind]} | `{spec.scope}` | {f.regra} | `{f.peca}` | {f.risco} | {f.efeito} | {confirmacao} | {idem} |"
        )
    linhas += ["", "## Por rota REST", "", f"{len(ROTAS)} rotas.", "", "| Rota | Funcionalidade | Tool(s) | Observação |", "|---|---|---|---|"]
    for chave, rota in ROTAS.items():
        tools = ", ".join(f"`{t}`" for t in rota.tools) if rota.tools else "**não exposta**"
        nota = rota.nota.replace("|", "\\|")
        linhas.append(f"| `{chave}` | {rota.capacidade} | {tools} | {nota} |")
    return "\n".join(linhas).rstrip() + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="falha se algum doc gerado estiver desatualizado")
    args = parser.parse_args(argv)
    arquivos = {DESTINO: render(), DESTINO_MAPA: render_capability_map()}
    if args.check:
        velhos = [p for p, conteudo in arquivos.items() if (p.read_text(encoding="utf-8") if p.exists() else "") != conteudo]
        for p in velhos:
            print(f"{p} desatualizado: rode `python -m app.mcp.docs` e comite.", file=sys.stderr)
        if velhos:
            return 1
        print("TOOLS.md e CAPABILITY_MAP.md em dia.")
        return 0
    DESTINO.parent.mkdir(parents=True, exist_ok=True)
    for p, conteudo in arquivos.items():
        p.write_text(conteudo, encoding="utf-8", newline="\n")
        print(f"escrito {p}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
