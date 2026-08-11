import secrets
from datetime import datetime, UTC
from typing import Optional

from sqlalchemy import Column, String
from sqlmodel import SQLModel, Field

from app.models.workspace import InviteStatus


class RegistrationInvite(SQLModel, table=True):
    """Convite para CRIAR CONTA no site (ADR 0026).

    Distinto do `WorkspaceInvite`, e a distinção é a razão de existir uma tabela
    nova em vez de um campo a mais na antiga. São dois consentimentos diferentes:

    - `WorkspaceInvite` diz "entre na MINHA casa e veja estes números". Pressupõe
      que a pessoa já tem — ou terá — conta, e carrega `workspace_id`, `role` e
      `financial_access`, que só fazem sentido dentro de um workspace.
    - `RegistrationInvite` diz "você pode existir neste site". Não fala de
      workspace nenhum: quem entra por ele nasce com o workspace pessoal padrão,
      igual a quem se cadastrou sozinho quando o site era aberto.

    Enfiar os dois na mesma tabela obrigaria `workspace_id` a virar anulável, e
    daí em diante toda consulta de membro precisaria lembrar de filtrar as linhas
    que não são de workspace. É o mesmo erro que o ADR 0021 desfez em cartão e
    conta — "nulo significa outra coisa" é a modelagem que produz vazamento.

    O `status` é reusado de `workspace.InviteStatus`: pending/accepted/revoked
    querem dizer exatamente o mesmo aqui, e um segundo enum idêntico só criaria
    duas verdades para a mesma pergunta.
    """

    id: Optional[int] = Field(default=None, primary_key=True)
    # Nulo = convite por LINK (qualquer pessoa com a URL se cadastra, até o teto
    # de `max_uses`). Preenchido = convite nominal: só aquele e-mail o consome.
    email: Optional[str] = Field(default=None, index=True)
    token: str = Field(
        default_factory=lambda: secrets.token_urlsafe(32),
        unique=True,
        index=True,
    )
    created_by_user_id: Optional[int] = Field(default=None, foreign_key="user.id", index=True)
    status: InviteStatus = Field(
        default=InviteStatus.pending,
        sa_column=Column(String(20), nullable=False, server_default="pending"),
    )
    expires_at: datetime
    # Nulo = uso único. Só faz sentido em convite por link; num convite nominal o
    # e-mail já é o teto.
    max_uses: Optional[int] = Field(default=None)
    uses: int = Field(default=0)
    # Quem entrou pelo convite. Num convite de uso único é a resposta inteira; num
    # de link é só o primeiro — a contagem verdadeira é `uses`. Serve para a tela
    # de Admin responder "de quem veio esta pessoa" sem varrer a auditoria.
    accepted_by_user_id: Optional[int] = Field(default=None, foreign_key="user.id")

    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
