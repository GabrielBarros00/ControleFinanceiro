"""Erros das tools, num envelope estável que o modelo consegue ler e corrigir.

Toda falha de uma tool sai como *tool execution error* (`isError: true`) com o
mesmo formato — `{"error": {"code", "message", "details", "retryable", ...}}` —
e nunca com stack trace, SQL ou texto de exceção interna. Os códigos são
contrato público (TOOLS.md): renomear um é quebra de compatibilidade.
"""
from __future__ import annotations

from enum import Enum
from typing import Any, Optional

from fastapi import HTTPException
from pydantic import ValidationError


class ErrorCode(str, Enum):
    NOT_FOUND = "NOT_FOUND"
    AMBIGUOUS = "AMBIGUOUS"
    VALIDATION_ERROR = "VALIDATION_ERROR"
    AUTHENTICATION_REQUIRED = "AUTHENTICATION_REQUIRED"
    PERMISSION_DENIED = "PERMISSION_DENIED"
    CONFLICT = "CONFLICT"
    RATE_LIMITED = "RATE_LIMITED"
    ALREADY_EXISTS = "ALREADY_EXISTS"
    BUSINESS_RULE_VIOLATION = "BUSINESS_RULE_VIOLATION"
    INTERNAL_ERROR = "INTERNAL_ERROR"


#: Falhas que podem dar certo se repetidas sem mudar nada.
_RETRYABLE = {ErrorCode.RATE_LIMITED, ErrorCode.INTERNAL_ERROR}


class McpToolError(Exception):
    def __init__(
        self,
        code: ErrorCode,
        message: str,
        *,
        details: Optional[dict[str, Any]] = None,
        candidates: Optional[list[dict[str, Any]]] = None,
        required_scopes: Optional[list[str]] = None,
        retry_after: Optional[int] = None,
    ):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}
        self.candidates = candidates
        self.required_scopes = required_scopes
        self.retry_after = retry_after

    def payload(self) -> dict[str, Any]:
        corpo: dict[str, Any] = {
            "code": self.code.value,
            "message": self.message,
            "details": self.details,
            "retryable": self.code in _RETRYABLE,
        }
        if self.candidates is not None:
            corpo["candidates"] = self.candidates
        if self.required_scopes:
            corpo["required_scopes"] = self.required_scopes
        if self.retry_after is not None:
            corpo["retry_after_seconds"] = self.retry_after
        return corpo


def not_found(message: str, **kw: Any) -> McpToolError:
    return McpToolError(ErrorCode.NOT_FOUND, message, **kw)


def validation(message: str, **kw: Any) -> McpToolError:
    return McpToolError(ErrorCode.VALIDATION_ERROR, message, **kw)


def business(message: str, **kw: Any) -> McpToolError:
    return McpToolError(ErrorCode.BUSINESS_RULE_VIOLATION, message, **kw)


def from_http_exception(exc: HTTPException) -> McpToolError:
    """Traduz a exceção de uma regra do app (a mesma que o REST devolve).

    A mensagem da regra é pt-BR e escrita para o usuário final — é o texto que o
    SPA mostra num toast —, então passa adiante como está. 5xx nunca passa.
    """
    detalhe = exc.detail if isinstance(exc.detail, str) else "Operação recusada."
    status = exc.status_code
    if status == 400:
        return McpToolError(ErrorCode.BUSINESS_RULE_VIOLATION, detalhe)
    if status == 401:
        return McpToolError(ErrorCode.AUTHENTICATION_REQUIRED, "Autenticação necessária.")
    if status == 403:
        return McpToolError(ErrorCode.PERMISSION_DENIED, detalhe)
    if status == 404:
        return McpToolError(ErrorCode.NOT_FOUND, detalhe)
    if status == 409:
        return McpToolError(ErrorCode.CONFLICT, detalhe)
    if status in (413, 422):
        return McpToolError(ErrorCode.VALIDATION_ERROR, detalhe)
    if status == 429:
        return McpToolError(ErrorCode.RATE_LIMITED, detalhe, retry_after=60)
    if 400 <= status < 500:
        return McpToolError(ErrorCode.BUSINESS_RULE_VIOLATION, detalhe)
    return McpToolError(ErrorCode.INTERNAL_ERROR, "Erro interno ao executar a operação.")


def from_validation_error(exc: ValidationError) -> McpToolError:
    """Campos e motivos — nunca os valores recebidos (são dados do usuário)."""
    campos: dict[str, str] = {}
    for erro in exc.errors(include_input=False, include_url=False):
        caminho = ".".join(str(p) for p in erro.get("loc", ())) or "(entrada)"
        campos[caminho] = erro.get("msg", "inválido")
    return McpToolError(
        ErrorCode.VALIDATION_ERROR,
        "Parâmetros inválidos: " + "; ".join(f"{k}: {v}" for k, v in list(campos.items())[:8]),
        details={"fields": campos},
    )
