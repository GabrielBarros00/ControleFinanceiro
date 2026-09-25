"""Estabelecimento (ADR 0038): onde a despesa foi feita, como vocabulário do espaço.

O título do lançamento é texto livre e o extrato o escreve de mil jeitos
("IFD*MC DONALDS 0231", "MCDONALDS", "McDonald's"). O estabelecimento dá um NOME
estável a eles: os apelidos são as grafias do extrato, e um lançamento cujo
título bate EXATAMENTE (normalizado) com um apelido se liga a ele sozinho. Com o
vínculo, "quanto gastei no McDonald's" deixa de depender de adivinhar títulos.

Vocabulário do espaço, como categoria e tag: nome único no espaço, exclusão
lógica, reativação pelo nome.
"""
from __future__ import annotations

import re
import unicodedata
from datetime import UTC, datetime
from typing import List, Optional

from sqlalchemy import JSON, Column, Index
from sqlmodel import Field, SQLModel


def normaliza_estabelecimento(texto: str) -> str:
    """A grafia que compara: sem acento, sem caixa, sem dígito, sem pontuação.

    Dígitos saem porque o extrato os acrescenta à toa (número da loja, da
    parcela, do terminal): "PADARIA PAO QUENTE 0123" e "PADARIA PAO QUENTE"
    são a mesma loja.
    """
    sem_acento = unicodedata.normalize("NFKD", texto or "").encode("ascii", "ignore").decode()
    limpo = re.sub(r"[^a-z ]", " ", sem_acento.lower())
    return " ".join(p for p in limpo.split() if len(p) > 1)


class Merchant(SQLModel, table=True):
    __table_args__ = (
        Index("uq_merchant_workspace_name", "workspace_id", "name", unique=True),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    workspace_id: int = Field(foreign_key="workspace.id", index=True)
    name: str = Field(max_length=120)
    #: Grafias do extrato, JÁ normalizadas (`normaliza_estabelecimento`). O nome
    #: também vincula, sem precisar estar aqui.
    aliases: List[str] = Field(default_factory=list, sa_column=Column(JSON, nullable=False, default=list))
    #: Categoria sugerida para o lançamento novo ligado a ele (só quando a pessoa
    #: não escolheu nenhuma).
    default_category_id: Optional[int] = Field(default=None, foreign_key="category.id")
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    deleted_at: Optional[datetime] = None

    def chaves(self) -> set[str]:
        """Tudo o que vincula um título a ele: o nome e os apelidos."""
        return {normaliza_estabelecimento(self.name), *self.aliases} - {""}
