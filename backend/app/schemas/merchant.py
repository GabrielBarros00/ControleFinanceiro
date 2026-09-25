"""Entrada e saída do estabelecimento (ADR 0038)."""
from decimal import Decimal
from typing import List, Optional

from pydantic import BaseModel, Field


class MerchantCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    #: Grafias do extrato ("IFD*MC DONALDS"); o servidor normaliza.
    aliases: List[str] = Field(default_factory=list, max_length=50)
    default_category_id: Optional[int] = None


class MerchantUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=120)
    #: Substitui a lista inteira.
    aliases: Optional[List[str]] = Field(default=None, max_length=50)
    #: `null` explícito tira a categoria padrão.
    default_category_id: Optional[int] = None


class MerchantMerge(BaseModel):
    #: O estabelecimento que fica; este some e passa lançamentos e apelidos a ele.
    into_id: int


class MerchantRead(BaseModel):
    id: int
    name: str
    aliases: List[str] = []
    default_category_id: Optional[int] = None
    #: Lançamentos ligados a ele que VOCÊ vê (só na lista).
    transaction_count: int = 0


class MerchantSpendingRead(BaseModel):
    """Uma linha do gasto por estabelecimento no mês (sem vínculo = `id` nulo)."""
    id: Optional[int] = None
    name: str
    currency: str
    total: Decimal
    my_share: Decimal
    count: int


class MerchantBrief(BaseModel):
    """O estabelecimento de um lançamento, na leitura."""
    id: int
    name: str
