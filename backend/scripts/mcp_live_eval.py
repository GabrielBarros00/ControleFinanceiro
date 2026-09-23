"""Eval AO VIVO das tools MCP com um modelo de verdade (opcional; fora do CI).

Roda cada caso de `tests/mcp/evals/cases.yaml` num LLM com as 35 tools do
servidor, executando as chamadas no app em memória (banco SQLite temporário,
cenário igual ao das trajetórias-ouro), e pontua:

- seleção: usou todas as `expected_tools`? tocou alguma `forbidden_tools`?
- esforço: quantas chamadas, contra `max_calls`;
- ambiguidade: quando `must_ask_user`, terminou perguntando ao usuário?
- confirmação: em `requires_confirmation`, só executou a massa DEPOIS de o
  usuário (simulado) dizer "sim".

Uso (de dentro de backend/):
    pip install anthropic
    ANTHROPIC_API_KEY=... python scripts/mcp_live_eval.py [--model claude-opus-5-5] [--case gasolina-nubank]

Custa chamadas de API — por isso não roda no CI. O relatório sai em
`mcp_live_eval_report.json` no diretório atual.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

# O app lê o banco do ambiente na importação: aponta para um SQLite descartável
# ANTES de importar qualquer coisa do app.
_TMP = Path(tempfile.mkdtemp(prefix="mcp-live-eval-"))
os.environ["DATABASE_URL"] = f"sqlite:///{(_TMP / 'eval.db').as_posix()}"
os.environ.setdefault("SECRET_KEY", "eval-" + "x" * 40)
os.environ.setdefault("RATE_LIMIT_ENABLED", "false")

import yaml  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlmodel import Session, SQLModel  # noqa: E402

from app.db.engine import engine  # noqa: E402
from app.main import app  # noqa: E402
from app.mcp.instructions import TEXT as INSTRUCOES  # noqa: E402
from app.mcp.registry import REGISTRY, input_schema  # noqa: E402
from app.mcp.server import get_server  # noqa: E402
from tests.mcp.conftest import call_tool  # noqa: E402
from tests.mcp.evals.test_evals_golden import _semear, _setup_extra  # noqa: E402
from tests.mcp.scenario import monta  # noqa: E402

CASOS = yaml.safe_load((RAIZ / "tests" / "mcp" / "evals" / "cases.yaml").read_text(encoding="utf-8"))
SIM = "Sim, pode confirmar."


def _ferramentas() -> list[dict]:
    get_server()
    return [{"name": s.name, "description": s.description, "input_schema": input_schema(s)} for s in REGISTRY.values()]


def rodar_caso(cliente_llm, modelo: str, caso: dict) -> dict:
    SQLModel.metadata.drop_all(engine)
    SQLModel.metadata.create_all(engine)
    with TestClient(app) as http, Session(engine) as db:
        cen = monta(db, http)
        _semear(db, http, cen)
        token = _setup_extra(caso.get("setup"), db, cen)

        mensagens: list[dict] = [{"role": "user", "content": caso["prompt"]}]
        usadas: list[str] = []
        confirmou = False
        massa_antes_do_sim = False
        texto_final = ""
        for _ in range(caso["max_calls"] + 4):
            resposta = cliente_llm.messages.create(
                model=modelo, max_tokens=2048, system=INSTRUCOES, tools=_ferramentas(), messages=mensagens,
            )
            mensagens.append({"role": "assistant", "content": resposta.content})
            chamadas = [b for b in resposta.content if b.type == "tool_use"]
            if not chamadas:
                texto_final = "".join(b.text for b in resposta.content if b.type == "text")
                if caso.get("requires_confirmation") and not confirmou and "?" in texto_final:
                    confirmou = True
                    mensagens.append({"role": "user", "content": SIM})
                    continue
                break
            resultados = []
            for bloco in chamadas:
                usadas.append(bloco.name)
                if bloco.name in {"transactions_bulk_delete", "transactions_bulk_categorize"} and not confirmou:
                    massa_antes_do_sim = True
                r = call_tool(http, token, bloco.name, dict(bloco.input))
                resultados.append({
                    "type": "tool_result", "tool_use_id": bloco.id,
                    "content": r["content"][0]["text"], "is_error": bool(r.get("isError")),
                })
            mensagens.append({"role": "user", "content": resultados})

    faltou = sorted(set(caso["expected_tools"]) - set(usadas))
    proibidas = sorted(set(caso["forbidden_tools"]) & set(usadas))
    perguntou = "?" in texto_final
    aprovado = (
        not faltou and not proibidas and len(usadas) <= caso["max_calls"]
        and (perguntou if caso.get("must_ask_user") else True)
        and not massa_antes_do_sim
    )
    return {
        "id": caso["id"], "aprovado": aprovado, "tools": usadas, "faltou": faltou, "proibidas": proibidas,
        "chamadas": len(usadas), "max_calls": caso["max_calls"], "perguntou": perguntou,
        "massa_antes_do_sim": massa_antes_do_sim, "resposta_final": texto_final[:500],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--model", default=os.environ.get("MCP_EVAL_MODEL", "claude-opus-5-5"))
    parser.add_argument("--case", action="append", help="rodar só este caso (repetível)")
    args = parser.parse_args()
    try:
        import anthropic
    except ImportError:
        print("Instale o SDK: pip install anthropic", file=sys.stderr)
        return 2
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("Defina ANTHROPIC_API_KEY.", file=sys.stderr)
        return 2

    cliente = anthropic.Anthropic()
    casos = [c for c in CASOS if not args.case or c["id"] in args.case]
    relatorio = []
    for caso in casos:
        r = rodar_caso(cliente, args.model, caso)
        relatorio.append(r)
        marca = "ok " if r["aprovado"] else "FAIL"
        print(f"{marca} {r['id']:<32} {r['chamadas']}/{r['max_calls']} chamadas  {', '.join(r['tools'])}")
    aprovados = sum(r["aprovado"] for r in relatorio)
    print(f"\n{aprovados}/{len(relatorio)} aprovados com {args.model}")
    Path("mcp_live_eval_report.json").write_text(json.dumps(relatorio, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if aprovados == len(relatorio) else 1


if __name__ == "__main__":
    raise SystemExit(main())
