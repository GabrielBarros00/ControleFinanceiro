"""Confirmação SERVER-SIDE das ações em massa.

"O usuário confirmou" dito pelo modelo não é mecanismo de segurança: o modelo
pode ter sido induzido por um texto armazenado, ou simplesmente errar. Então a
ação em massa só executa com um token que o SERVIDOR emitiu numa prévia:

- a prévia (`transactions_bulk_preview`) calcula o conjunto EXATO de ids, o total
  e uma amostra, e emite `cfm_cf_…` — uso único, 10 minutos, amarrado ao usuário,
  à concessão OAuth e à ação;
- a execução recebe só o token (nunca uma lista de ids nova) e age no máximo
  sobre o conjunto guardado; o que deixou de ser elegível nesse meio-tempo
  (apagado, pago, tornado invisível) é recusado por inteiro, porque o que a
  pessoa viu já não é o que aconteceria.

O banco guarda o SHA-256 do token, nunca o token. O consumo é um `UPDATE`
condicional (`used_at IS NULL`): dois envios simultâneos do mesmo token não
executam duas vezes (`corridas-so-aparecem-no-postgres`).
"""
from __future__ import annotations

from datetime import datetime, timedelta, UTC
from typing import Any, Optional

from sqlalchemy import update
from sqlmodel import select

from app.mcp.errors import ErrorCode, McpToolError
from app.mcp.registry import ToolCall
from app.models.mcp import McpConfirmation
from app.services.oauth.crypto import CONFIRMATION_PREFIX, new_secret, sha256_hex

TTL = timedelta(minutes=10)


def _agora() -> datetime:
    return datetime.now(UTC)


def _aware(momento: datetime) -> datetime:
    return momento if momento.tzinfo else momento.replace(tzinfo=UTC)


def issue(
    call: ToolCall, action: str, target_ids: list[int], params: Optional[dict[str, Any]] = None,
    *, prefixo: str = CONFIRMATION_PREFIX,
) -> tuple[str, datetime]:
    token = new_secret(prefixo)
    expira = _agora() + TTL
    call.session.add(McpConfirmation(
        token_hash=sha256_hex(token),
        user_id=call.identity.user_id,
        grant_id=call.identity.grant_id,
        action=action,
        target_ids=sorted(set(target_ids)),
        params=params or {},
        expires_at=expira,
    ))
    call.session.flush()
    return token, expira


def _invalido() -> McpToolError:
    # Mesma resposta para "não existe", "é de outra pessoa" e "é de outra
    # ação": o token não serve, e o motivo não ajuda quem o forjou.
    return McpToolError(
        ErrorCode.VALIDATION_ERROR,
        "confirmation_token inválido. Gere uma nova prévia com transactions_bulk_preview.",
    )


def consume(call: ToolCall, token: str, action: str) -> McpConfirmation:
    """Reserva o token para esta execução (na transação da chamada).

    Já usado → devolve o registro com `result` preenchido, e quem chama responde
    o MESMO resultado (retry de rede não vira erro nem segunda execução).
    """
    registro = call.session.exec(
        select(McpConfirmation).where(McpConfirmation.token_hash == sha256_hex(token))
    ).first()
    if (
        registro is None
        or registro.user_id != call.identity.user_id
        or registro.grant_id != call.identity.grant_id
        or registro.action != action
    ):
        raise _invalido()
    if registro.used_at is not None:
        if registro.result is not None:
            return registro
        raise McpToolError(ErrorCode.CONFLICT, "Esta confirmação já está sendo executada.")
    if _aware(registro.expires_at) <= _agora():
        raise McpToolError(
            ErrorCode.VALIDATION_ERROR,
            "A prévia expirou (vale 10 minutos). Gere uma nova com transactions_bulk_preview e confirme de novo.",
        )
    reservado = call.session.execute(
        update(McpConfirmation)
        .where(McpConfirmation.id == registro.id, McpConfirmation.used_at.is_(None))
        .values(used_at=_agora())
    )
    if reservado.rowcount != 1:
        raise McpToolError(ErrorCode.CONFLICT, "Esta confirmação já foi usada.")
    call.session.refresh(registro)
    return registro


def store_result(call: ToolCall, registro: McpConfirmation, result: dict[str, Any]) -> None:
    registro.result = result
    call.session.add(registro)
    call.session.flush()
