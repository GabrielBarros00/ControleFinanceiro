from fastapi import Request, status
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from app.schemas.common import ErrorResponse, ErrorDetail

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
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
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

async def internal_server_error_handler(request: Request, exc: Exception):
    """Tratamento de erros inesperados (500)."""
    error_res = ErrorResponse(
        error=ErrorDetail(
            code="INTERNAL_SERVER_ERROR",
            message="Ocorreu um erro interno inesperado no servidor.",
            details={"error_type": type(exc).__name__}
        )
    )
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content=error_res.model_dump()
    )
