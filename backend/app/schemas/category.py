"""Entrada de categoria do espaço.

Morava em `api/routes/categories.py` até o ADR 0035 (o comando de criação é
compartilhado com o MCP e um serviço não importa de rota). Mesmo nome, então o
OpenAPI não muda.
"""
from typing import Optional

from pydantic import BaseModel, Field

from app.schemas.common import NAME_MAX


class CategoryCreate(BaseModel):
    name: str = Field(min_length=1, max_length=NAME_MAX)
    color: Optional[str] = None
    icon: Optional[str] = None


class CategoryUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=NAME_MAX)
    color: Optional[str] = None
    icon: Optional[str] = None
