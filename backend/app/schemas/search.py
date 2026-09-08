"""Contrato da busca global.

Um resultado de busca é heterogêneo por natureza — lançamento, renda, acerto e
cartão não têm os mesmos campos. Em vez de uma união de tipos (que o gerador de
TypeScript transformaria num `oneOf` desconfortável de consumir na tela), o
formato é **um tipo só com os campos opcionais**: quem desenha a lista mostra o
que existe e ignora o resto.

O `href` vem do SERVIDOR de propósito. É ele que sabe em qual espaço o
lançamento vive e, portanto, para onde a linha leva; deixar a tela montar a URL
significaria repetir esse conhecimento no front e deixá-lo desatualizar quando
uma rota mudar.
"""
from datetime import date
from decimal import Decimal
from typing import List, Optional

from pydantic import BaseModel


class SearchHit(BaseModel):
    """Uma linha do resultado, de qualquer tipo."""

    #: `transaction | income | settlement | card` — decide o ícone e o rótulo.
    kind: str
    id: int
    title: str
    amount: Optional[Decimal] = None
    currency: Optional[str] = None
    #: Dia de calendário do acontecimento; `None` em cartão, que não tem data.
    occurred_on: Optional[date] = None
    workspace_id: Optional[int] = None
    workspace_name: Optional[str] = None
    #: Para onde a linha leva. Montado no servidor (ver docstring do módulo).
    href: str


class SearchGroup(BaseModel):
    """Os resultados de um tipo, já com o rótulo que a tela mostra."""

    kind: str
    label: str
    items: List[SearchHit]


class SearchRead(BaseModel):
    query: str
    groups: List[SearchGroup]
    total: int
