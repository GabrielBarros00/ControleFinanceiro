"""O pacote de plugin (integrations/controle-financeiro-plugin) não pode apodrecer.

Skill que manda chamar uma tool que foi renomeada vira instrução quebrada dentro
do ChatGPT/Codex, e nada no app acusaria. Aqui: manifestos válidos, assets que
existem, e toda tool citada nas skills existe no registro.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from app.mcp.registry import REGISTRY
from app.mcp.server import get_server

PACOTE = Path(__file__).resolve().parents[3] / "integrations" / "controle-financeiro-plugin"


def test_manifestos_validos_e_assets_existem():
    plugin = json.loads((PACOTE / "plugin.json").read_text(encoding="utf-8"))
    mcp = json.loads((PACOTE / "mcp.json").read_text(encoding="utf-8"))
    assert plugin["name"] == "controle-financeiro"
    interface = plugin["extensions"]["com.openai"]["interface"]
    for chave in ("logo", "composerIcon"):
        assert (PACOTE / interface[chave]).is_file(), interface[chave]
    servidor = mcp["mcpServers"]["controle-financeiro"]
    assert servidor["type"] == "streamable-http" and servidor["url"].startswith("https://")
    assert servidor["url"].endswith("/mcp")
    # Nenhuma credencial no pacote.
    tudo = json.dumps(plugin) + json.dumps(mcp)
    assert not re.search(r"cfm_|Bearer|token|secret", tudo, re.IGNORECASE)


def test_skills_citam_so_tools_que_existem():
    get_server()
    skills = sorted((PACOTE / "skills").glob("*/SKILL.md"))
    assert len(skills) == 3
    padrao_tool = re.compile(r"`([a-z]+_[a-z_]+)`")
    for arquivo in skills:
        texto = arquivo.read_text(encoding="utf-8").replace("\r\n", "\n")  # checkout com autocrlf
        frente = re.match(r"^---\nname: ([a-z-]+)\ndescription: (.+?)\n---\n", texto, re.S)
        assert frente, f"{arquivo}: frontmatter inválido"
        assert frente.group(1) == arquivo.parent.name
        citadas = {t for t in padrao_tool.findall(texto) if t in REGISTRY or t.split("_")[0] in {
            "transactions", "statements", "reports", "debts", "payables", "income", "imports", "accounts",
            "settlements", "budgets", "recurring", "profile", "spaces", "people", "categories", "cards", "transfers"}}
        assert citadas, f"{arquivo}: não cita nenhuma tool"
        desconhecidas = citadas - set(REGISTRY)
        assert not desconhecidas, f"{arquivo}: cita tools que não existem: {desconhecidas}"
