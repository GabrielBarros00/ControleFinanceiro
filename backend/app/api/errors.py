import uuid

import structlog
from fastapi import Request, status
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from app.schemas.common import ErrorResponse, ErrorDetail

logger = structlog.get_logger("app.http")

# Starlette 0.47 renomeou HTTP_422_UNPROCESSABLE_ENTITY → HTTP_422_UNPROCESSABLE_CONTENT.
# Aceita as duas versões para não quebrar o handler de validação.
HTTP_422 = getattr(status, "HTTP_422_UNPROCESSABLE_CONTENT", None) or status.HTTP_422_UNPROCESSABLE_ENTITY

async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """Tratamento de erros de validação do Pydantic (422)."""
    details = {}
    for error in exc.errors():
        field = " -> ".join([str(loc) for m, loc in enumerate(error["loc"]) if loc != "body"])
        details[field] = error["msg"]
    
    error_res = ErrorResponse(
        error=ErrorDetail(
            code="VALIDATION_ERROR",
            message="Ocorreu um erro de validação nos dados enviados.",
            details=details
        )
    )
    return JSONResponse(
        status_code=HTTP_422,
        content=error_res.model_dump()
    )

async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    """Tratamento de exceções HTTP genéricas (404, 401, 403, etc)."""
    code_map = {
        400: "BAD_REQUEST",
        404: "NOT_FOUND",
        401: "UNAUTHORIZED",
        403: "FORBIDDEN",
        405: "METHOD_NOT_ALLOWED",
        409: "CONFLICT"
    }
    code = code_map.get(exc.status_code, "HTTP_ERROR")
    
    error_res = ErrorResponse(
        error=ErrorDetail(
            code=code,
            message=str(exc.detail),
            details={}
        )
    )
    return JSONResponse(
        status_code=exc.status_code,
        content=error_res.model_dump()
    )

# Cabeçalhos de segurança repetidos aqui de propósito: a resposta 500 é gerada
# pelo ServerErrorMiddleware do Starlette, que fica FORA de toda a pilha de
# middleware da aplicação — ela não passava pelo security_headers_middleware.
_SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "same-origin",
}


async def internal_server_error_handler(request: Request, exc: Exception):
    """Tratamento de erros inesperados (500).

    Loga aqui, com o request_id, porque o `request_logging_middleware` NÃO vê
    esta resposta: a exceção propaga por ele (o logger.info nunca executa) até o
    ServerErrorMiddleware. O resultado era um 500 sem linha estruturada, sem
    X-Request-ID e sem cabeçalhos de segurança — só o traceback cru do uvicorn,
    impossível de correlacionar com a requisição do usuário.
    """
    request_id = request.headers.get("x-request-id") or uuid.uuid4().hex[:12]
    logger.exception(
        "unhandled_exception",
        request_id=request_id,
        method=request.method,
        path=request.url.path,
        error_type=type(exc).__name__,
    )
    error_res = ErrorResponse(
        error=ErrorDetail(
            code="INTERNAL_SERVER_ERROR",
            message="Ocorreu um erro interno inesperado no servidor.",
            details={"error_type": type(exc).__name__}
        )
    )
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content=error_res.model_dump(),
        headers={**_SECURITY_HEADERS, "X-Request-ID": request_id},
    )
