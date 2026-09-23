"""O pipeline de TODA chamada de tool. Nenhuma tool faz estas coisas sozinha.

    identidade (token) → escopo → teto de uso → validação da entrada →
    sessão + contexto de auditoria → [chave de idempotência] → handler →
    commit ÚNICO → efeitos pós-commit → resultado → trilha operacional

Regras que moram aqui e em mais nenhum lugar:

- **Escopo antes de tudo.** Sem o escopo da tool, nem a validação da entrada
  roda — e o erro diz qual escopo falta e carrega o desafio
  `WWW-Authenticate` que o ChatGPT usa para pedir a re-autorização.
- **Um commit por chamada** (ADR 0010). O handler só faz `flush`; se qualquer
  coisa falhar depois do primeiro flush, rollback de tudo — uma compra parcelada
  nunca fica com metade das parcelas.
- **Erro nunca vaza interno.** Regra de negócio (HTTPException/ValueError do
  app) sai com a mensagem pt-BR da própria regra; exceção inesperada sai como
  `INTERNAL_ERROR` genérico com `correlation_id`, e o traceback vai só para o log.
"""
from __future__ import annotations

import json
import time
from typing import Any

import structlog
from fastapi import HTTPException
from mcp_types import CallToolResult, TextContent
from pydantic import ValidationError
from sqlalchemy.exc import DataError, IntegrityError

from app.core.config import settings
from app.core.context import set_current_user_id, set_request_origin
from app.db import session as db_session
from app.mcp import audit, idempotency, rate_limit
from app.mcp.errors import (
    ErrorCode,
    McpToolError,
    from_http_exception,
    from_validation_error,
)
from app.mcp.identity import current_identity, peek_identity
from app.mcp.registry import ToolCall, ToolOutput, ToolSpec
from app.models.user import User

logger = structlog.get_logger("app.mcp")


def _texto(saida: ToolOutput, estruturado: dict[str, Any]) -> str:
    # Resumo legível + o JSON serializado: a spec pede o JSON em TextContent
    # para clientes que não leem `structuredContent`, e o modelo ganha a frase.
    corpo = json.dumps(estruturado, ensure_ascii=False, separators=(",", ":"))
    return f"{saida.summary}\n\n{corpo}"


def success_result(spec: ToolSpec, saida: ToolOutput) -> CallToolResult:
    estruturado = saida.structured.model_dump(mode="json", by_alias=True)
    meta: dict[str, Any] = {}
    if spec.ui and saida.widget:
        meta.update(saida.widget)
    if saida.replayed:
        meta["controle-financeiro/replayed"] = True
    return CallToolResult(
        content=[TextContent(type="text", text=_texto(saida, estruturado))],
        structured_content=estruturado,
        _meta=meta or None,
    )


def error_result(erro: McpToolError) -> CallToolResult:
    corpo = {"error": erro.payload()}
    meta = None
    if erro.code == ErrorCode.PERMISSION_DENIED and erro.required_scopes:
        # Desafio RFC 6750 dentro do resultado: é o que o ChatGPT lê para abrir
        # o fluxo de re-autorização com o escopo que faltou.
        escopo = " ".join(erro.required_scopes)
        meta = {
            "mcp/www_authenticate": [
                f'Bearer resource_metadata="{settings.oauth_issuer}/.well-known/oauth-protected-resource/mcp", '
                f'error="insufficient_scope", scope="{escopo}", '
                f'error_description="This connection lacks the required scope."'
            ]
        }
    return CallToolResult(
        content=[TextContent(type="text", text=f"{erro.message}\n\n{json.dumps(corpo, ensure_ascii=False)}")],
        is_error=True,
        _meta=meta,
    )


def _mensagem_de_regra(exc: Exception) -> str:
    texto = str(exc).strip() or "Operação recusada pelas regras do app."
    return texto.removeprefix("Value error, ")[:400]


def _traduz(exc: Exception, correlation_id: str) -> McpToolError:
    if isinstance(exc, McpToolError):
        return exc
    if isinstance(exc, HTTPException):
        return from_http_exception(exc)
    if isinstance(exc, ValidationError):
        # Validação de um schema INTERNO do app (ex.: TransactionCreate): são as
        # regras de negócio escritas como validadores — a mensagem é da regra.
        mensagens = [_mensagem_de_regra(Exception(e.get("msg", ""))) for e in exc.errors(include_input=False)]
        return McpToolError(ErrorCode.BUSINESS_RULE_VIOLATION, "; ".join(mensagens)[:600] or "Dados recusados.")
    if isinstance(exc, IntegrityError):
        return McpToolError(ErrorCode.CONFLICT, "A operação conflita com um registro existente. Tente de novo.")
    if isinstance(exc, (DataError, OverflowError)):
        return McpToolError(ErrorCode.VALIDATION_ERROR, "Identificador ou valor numérico fora da faixa aceita.")
    if isinstance(exc, ValueError):
        return McpToolError(ErrorCode.BUSINESS_RULE_VIOLATION, _mensagem_de_regra(exc))
    logger.exception("mcp_tool_erro_inesperado", correlation_id=correlation_id)
    return McpToolError(
        ErrorCode.INTERNAL_ERROR,
        "Erro interno ao executar a operação. Nada foi alterado.",
        details={"correlation_id": correlation_id},
    )


def _carrega_usuario(sessao, user_id: int) -> User:
    user = sessao.get(User, user_id)
    if user is None or user.deleted_at is not None or not user.is_active:
        raise McpToolError(ErrorCode.AUTHENTICATION_REQUIRED, "Conta indisponível. Reconecte o aplicativo.")
    return user


def run(spec: ToolSpec, arguments: dict[str, Any]) -> CallToolResult:
    """Executa a tool (síncrono — o SDK chama numa thread de trabalho)."""
    inicio = time.perf_counter()
    identidade = peek_identity()
    saida: ToolOutput | None = None
    erro: McpToolError | None = None
    try:
        identidade = current_identity()
        if not identidade.has(spec.scope):
            raise McpToolError(
                ErrorCode.PERMISSION_DENIED,
                f"Esta conexão não tem a permissão '{spec.scope}'. Reconecte o aplicativo "
                "concedendo essa permissão na tela de autorização.",
                required_scopes=[spec.scope],
            )
        rate_limit.check(
            identidade.user_id, identidade.client_pk, cost=spec.cost, is_write=spec.kind != "read"
        )
        try:
            args = spec.input_model.model_validate(arguments or {})
        except ValidationError as exc:
            raise from_validation_error(exc)

        with db_session.session_scope() as sessao:
            set_current_user_id(identidade.user_id)
            set_request_origin(identidade.origin)
            try:
                chamada = ToolCall(
                    session=sessao,
                    identity=identidade,
                    user=_carrega_usuario(sessao, identidade.user_id),
                    args=args,
                    spec=spec,
                )
                saida = idempotency.execute(chamada) if spec.idempotency_key else spec.handler(chamada)
                sessao.commit()
            except BaseException:
                sessao.rollback()
                raise
            finally:
                set_current_user_id(None)
                set_request_origin(None)

        for acao in saida.after_commit:
            try:
                acao()
            except Exception:  # noqa: BLE001 — o dado já está gravado; limpeza é best-effort
                logger.warning("mcp_pos_commit_falhou", tool=spec.name, exc_info=True)
        return success_result(spec, saida)
    except Exception as exc:  # noqa: BLE001 — todo erro vira resultado estruturado
        erro = _traduz(exc, identidade.request_id if identidade else "sem-identidade")
        return error_result(erro)
    finally:
        audit.record(
            identity=identidade,
            tool=spec.name,
            kind=spec.kind,
            outcome="error" if erro else "ok",
            error_code=erro.code.value if erro else None,
            duration_ms=int((time.perf_counter() - inicio) * 1000),
            entity_type=saida.entity_type if saida else None,
            entity_ids=saida.entity_ids if saida else None,
            space_id=saida.space_id if saida else None,
            replayed=bool(saida and saida.replayed),
        )
