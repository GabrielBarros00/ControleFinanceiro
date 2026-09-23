"""Chave de idempotência das escritas: um retry não vira compra duplicada.

Cliente e agente repetem chamada — timeout, resposta perdida, o próprio modelo
tentando de novo. Toda escrita que CRIA algo exige `idempotency_key` (UUID novo
por intenção do usuário, repetido só no retry da mesma intenção) e passa por
aqui:

1. A chave é reservada (`INSERT` em `mcpoperation`) ANTES do comando, na mesma
   transação. Duas chamadas simultâneas com a mesma chave: no Postgres a segunda
   espera o índice único e cai em `IntegrityError` quando a primeira comita —
   então devolve o resultado da primeira.
2. O comando roda; as referências do resultado entram na mesma linha.
3. Um único commit leva as duas coisas juntas. Falhou? Rollback de tudo, e a
   chave fica livre para o retry legítimo.

Mesma chave com argumentos DIFERENTES não é retry: é `CONFLICT`. E não há
deduplicação por conteúdo — duas compras iguais de verdade, com chaves
diferentes, são duas compras.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, UTC
from typing import Any

from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError
from sqlmodel import select

from app.mcp.errors import ErrorCode, McpToolError
from app.mcp.registry import ToolCall, ToolOutput
from app.models.mcp import McpOperation

TTL = timedelta(days=7)


def _agora() -> datetime:
    return datetime.now(UTC)


def _aware(momento: datetime) -> datetime:
    return momento if momento.tzinfo else momento.replace(tzinfo=UTC)


def request_hash(args: BaseModel) -> str:
    dados: Any = args.model_dump(mode="json", exclude={"idempotency_key"})
    canonico = json.dumps(dados, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonico.encode("utf-8")).hexdigest()


def _existente(call: ToolCall, chave: str):
    return call.session.exec(
        select(McpOperation).where(
            McpOperation.user_id == call.identity.user_id,
            McpOperation.tool == call.spec.name,
            McpOperation.idempotency_key == chave,
        )
    ).first()


def _replay(call: ToolCall, operacao: McpOperation, assinatura: str) -> ToolOutput:
    if operacao.request_hash != assinatura:
        raise McpToolError(
            ErrorCode.CONFLICT,
            "Esta idempotency_key já foi usada com outros dados. Gere uma chave nova "
            "para uma operação nova; repita a mesma chave só ao reenviar a MESMA chamada.",
        )
    if call.spec.replay is None or not operacao.result_ref:
        raise McpToolError(ErrorCode.CONFLICT, "Operação já processada com esta idempotency_key.")
    saida = call.spec.replay(call, operacao.result_ref)
    saida.replayed = True
    return saida


def execute(call: ToolCall) -> ToolOutput:
    chave = getattr(call.args, "idempotency_key", None)
    if not chave:
        raise McpToolError(ErrorCode.VALIDATION_ERROR, "idempotency_key é obrigatória nesta operação.")
    assinatura = request_hash(call.args)

    existente = _existente(call, chave)
    if existente is not None:
        if _aware(existente.expires_at) > _agora():
            return _replay(call, existente, assinatura)
        call.session.delete(existente)
        call.session.flush()

    operacao = McpOperation(
        user_id=call.identity.user_id,
        tool=call.spec.name,
        idempotency_key=chave,
        request_hash=assinatura,
        grant_id=call.identity.grant_id,
        expires_at=_agora() + TTL,
    )
    call.session.add(operacao)
    try:
        call.session.flush()
    except IntegrityError:
        # Corrida com a mesma chave: a outra chamada comitou primeiro.
        call.session.rollback()
        vencedora = _existente(call, chave)
        if vencedora is None:
            raise McpToolError(ErrorCode.CONFLICT, "Operação concorrente com a mesma chave; tente de novo.")
        return _replay(call, vencedora, assinatura)

    saida = call.spec.handler(call)
    operacao.result_ref = saida.result_ref or {}
    call.session.add(operacao)
    call.session.flush()
    return saida
