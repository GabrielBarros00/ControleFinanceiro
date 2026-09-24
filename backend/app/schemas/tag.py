"""Entrada e saída de tag do espaço.

Moravam em `api/routes/tags.py` até o MCP ganhar a gestão de tags: o comando é
compartilhado e um serviço não importa de rota. Mesmos nomes, então o OpenAPI não
muda.
"""
from typing import Optional

from pydantic import BaseModel, Field

from app.schemas.common import NAME_MAX


class TagCreate(BaseModel):
    name: str = Field(min_length=1, max_length=NAME_MAX)
    color: Optional[str] = None


class TagUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=NAME_MAX)
    color: Optional[str] = None


class TagRead(BaseModel):
    id: int
    name: str
    color: Optional[str]
