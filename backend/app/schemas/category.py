"""Entrada de categoria do espaço.

Morava em `api/routes/categories.py` até o ADR 0035 (o comando de criação é
compartilhado com o MCP e um serviço não importa de rota). Mesmo nome, então o
OpenAPI não muda.
"""
from typing import Optional

from pydantic import ConfigDict, BaseModel, Field

from app.schemas.common import NAME_MAX


class CategoryCreate(BaseModel):
    # Campo desconhecido é RECUSADO (422), não ignorado: a importação de extrato
    # mandava `category_id` que o schema não tinha, o Pydantic o jogava fora calado e
    # a despesa ficava sem categoria (auditoria 2026-09-26, C1/A1).
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=NAME_MAX)
    color: Optional[str] = None
    icon: Optional[str] = None


class CategoryUpdate(BaseModel):
    # Campo desconhecido é RECUSADO (422), não ignorado: a importação de extrato
    # mandava `category_id` que o schema não tinha, o Pydantic o jogava fora calado e
    # a despesa ficava sem categoria (auditoria 2026-09-26, C1/A1).
    model_config = ConfigDict(extra="forbid")
    name: Optional[str] = Field(default=None, min_length=1, max_length=NAME_MAX)
    color: Optional[str] = None
    icon: Optional[str] = None
