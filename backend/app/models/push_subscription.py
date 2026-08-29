"""Inscrição de Web Push — um navegador que aceitou receber aviso (ADR 0033).

Uma linha aqui é um PAR (pessoa, navegador), não uma pessoa: quem usa o app no
celular e no PC tem duas, e ativar num aparelho não ativa no outro. É assim que o
padrão funciona — a inscrição pertence ao registro do service worker daquele
navegador — e é por isso que a tela de Configurações lista aparelhos, no plural.
"""
from datetime import datetime, UTC
from typing import Optional

from sqlalchemy import Column, String, Text
from sqlmodel import SQLModel, Field


class PushSubscription(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)

    # `endpoint` é a URL que o serviço de push (Google, Mozilla, Apple) deu a
    # ESTE navegador. É o identificador natural da inscrição, e por isso é único.
    #
    # A unicidade não é higiene: ela resolve o caso de duas pessoas usando o
    # mesmo navegador. Reinscrever devolve o MESMO endpoint, então a segunda a
    # ativar toma a linha da primeira — que é o comportamento correto. Sem isso,
    # a primeira continuaria recebendo as contas dela num aparelho que agora é de
    # outra pessoa (ADR 0018).
    #
    # `Text` e não `String(n)`: o endpoint do FCM já passa de 200 caracteres e o
    # tamanho é escolha do serviço de push, não nossa. Índice único sobre `text`
    # cabe no btree do Postgres com folga (limite ~2704 bytes).
    endpoint: str = Field(sa_column=Column(Text, nullable=False, unique=True, index=True))

    user_id: int = Field(foreign_key="user.id", index=True)

    # As duas chaves que o navegador gerou. Juntas elas cifram o payload de forma
    # que só AQUELE navegador consegue abrir — nem o serviço de push lê.
    p256dh: str = Field(sa_column=Column(String(255), nullable=False))
    auth: str = Field(sa_column=Column(String(255), nullable=False))

    # Só para a pessoa se reconhecer na lista ("Chrome no Android"). Nunca é
    # usado para decidir nada.
    user_agent: Optional[str] = Field(
        default=None, sa_column=Column(String(255), nullable=True)
    )

    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    # Quando o serviço de push aceitou o último envio. Serve para a tela dizer
    # "sem uso desde…" e para diagnosticar um aparelho que parou de receber sem
    # ter sido apagado (o serviço só responde 410 quando tem certeza).
    last_success_at: Optional[datetime] = Field(default=None)
