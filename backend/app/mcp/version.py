"""Versão do servidor MCP (semver próprio, independente do app — ADR 0035 §9).

Mora num módulo sem dependências para as tools (`profile_get`) poderem citá-la
sem importar o `server.py`, que importa as tools.

- MAIOR: uma tool publicada mudou de forma incompatível (nome nunca muda: a nova
  vira `_v2` e a antiga fica marcada como obsoleta por ≥ 90 dias).
- MENOR: tool nova, ou campo novo opcional.
- CORREÇÃO: comportamento corrigido sem mudar contrato.
"""
SERVER_VERSION = "1.6.0"
