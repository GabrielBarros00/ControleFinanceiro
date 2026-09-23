"""Trilha operacional das chamadas MCP (`mcptoolcall`) + log estruturado.

Grava numa sessão PRÓPRIA e curta, depois do resultado: a chamada que falhou
também precisa aparecer (é exatamente a que se quer investigar), e a transação
da tool já foi desfeita nesse caso. Best-effort — uma falha aqui nunca derruba a
resposta ao agente.

O que NÃO entra: argumentos, valores, títulos, tokens. Tool, resultado, código
de erro, duração, IDs afetados e o `request_id` de correlação bastam para
responder "quem fez o quê pela IA e quando"; o conteúdo da mudança está no
`AuditLog` da entidade, com `origin="mcp:<cliente>"`.
"""
from __future__ import annotations

from typing import Optional

import structlog

from app.db import session as db_session
from app.mcp.identity import McpIdentity
from app.models.mcp import McpToolCall

logger = structlog.get_logger("app.mcp")


def record(
    *,
    identity: Optional[McpIdentity],
    tool: str,
    kind: str,
    outcome: str,
    error_code: Optional[str],
    duration_ms: int,
    entity_type: Optional[str] = None,
    entity_ids: Optional[list[int]] = None,
    space_id: Optional[int] = None,
    replayed: bool = False,
) -> None:
    logger.info(
        "mcp_tool_call",
        tool=tool,
        kind=kind,
        outcome=outcome,
        error_code=error_code,
        duration_ms=duration_ms,
        user_id=identity.user_id if identity else None,
        client=identity.client_name if identity else None,
        request_id=identity.request_id if identity else None,
        replayed=replayed,
    )
    if identity is None:
        return
    try:
        with db_session.session_scope() as sessao:
            sessao.add(McpToolCall(
                user_id=identity.user_id,
                grant_id=identity.grant_id,
                client_name=identity.client_name[:120],
                client_info=identity.client_info[:120] if identity.client_info else None,
                tool=tool,
                op_type=kind,
                outcome=outcome,
                error_code=error_code,
                duration_ms=duration_ms,
                request_id=identity.request_id[:64],
                space_id=space_id,
                entity_type=entity_type,
                entity_ids=entity_ids[:50] if entity_ids else None,
                replayed=replayed,
            ))
            sessao.commit()
    except Exception:  # noqa: BLE001 — auditoria operacional nunca derruba a tool
        logger.warning("mcp_tool_call_nao_gravado", tool=tool, exc_info=True)
