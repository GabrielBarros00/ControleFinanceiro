from typing import Any, Dict, Optional
from pydantic import BaseModel, Field

class ErrorDetail(BaseModel):
    code: str = Field(..., description="Código estável de erro para tratamento lógico.")
    message: str = Field(..., description="Mensagem de erro legível para o usuário em PT-BR.")
    details: Optional[Dict[str, Any]] = Field(default_factory=dict, description="Detalhes adicionais do erro (ex: erros de validação por campo).")

class ErrorResponse(BaseModel):
    error: ErrorDetail
