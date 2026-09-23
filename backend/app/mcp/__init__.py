"""Servidor MCP do Controle Financeiro (ADR 0035).

Mapa do pacote:

- `server.py` — a instância `MCPServer` (SDK oficial `mcp`), instruções e registro.
- `asgi.py` — o portão HTTP em `/mcp`: bearer → identidade, Origin, 401 com
  `resource_metadata`, e a montagem por lifespan.
- `registry.py` — `ToolSpec`: a fonte ÚNICA de cada tool (nome, schemas,
  annotations, escopo, UI). O SDK e o `TOOLS.md` são gerados daqui.
- `invoke.py` — o pipeline de toda chamada: escopo, taxa, validação, sessão,
  auditoria, idempotência, commit único, erros estruturados.
- `tools/` — as tools, uma por intenção do usuário, chamando serviços e
  comandos que o app REST também usa. Nenhuma regra financeira mora aqui.
"""
