import secrets
from datetime import datetime, UTC
from enum import Enum
from typing import Optional, List

from sqlalchemy import Boolean, Column, Index, Integer, String, true
from sqlmodel import SQLModel, Field, Relationship


class WorkspaceRole(str, Enum):
    owner = "owner"
    admin = "admin"
    member = "member"
    viewer = "viewer"


class FinancialAccess(str, Enum):
    """O que o membro pode VER — ortogonal ao papel, que diz o que ele pode FAZER.

    Mora aqui, junto de `WorkspaceRole`, porque é valor PERSISTIDO: a política que
    o interpreta (`app.domain.access_policy`) importa os models, então definir o
    enum lá tornaria o import circular. Semântica e regras: ADR 0018.
    """

    involved_only = "involved_only"      # só o que me envolve
    full_workspace = "full_workspace"    # números da casa inteira


_ROLE_LEVELS = {"viewer": 0, "member": 1, "admin": 2, "owner": 3}


def role_level(role) -> int:
    """Nível hierárquico de um papel (aceita enum ou string vinda do banco)."""
    value = role.value if isinstance(role, WorkspaceRole) else str(role)
    return _ROLE_LEVELS.get(value, -1)


class InviteStatus(str, Enum):
    pending = "pending"
    accepted = "accepted"
    revoked = "revoked"


class Workspace(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True)
    description: Optional[str] = None
    # Quem CRIOU — registro histórico, não o dono atual (ADR 0028).
    #
    # Nunca é reescrito, nem pela transferência de propriedade: quem criou
    # continua tendo criado. O DONO é a membership com `role=owner`, que é a
    # mesma linha que autoriza excluir o workspace — usar esta coluna para
    # exibir "de quem é" foi a divergência que o ADR 0028 fechou.
    created_by_user_id: Optional[int] = Field(default=None, foreign_key="user.id")
    # Moeda-base das agregações (ADR 0006): transações em outra moeda ficam FORA
    # dos totais até existir taxa histórica congelada
    base_currency: str = Field(
        default="BRL",
        sa_column=Column(String(3), nullable=False, server_default="BRL"),
    )
    # Sequência monotônica de eventos de sincronização (WebSocket/resync)
    event_seq: int = Field(
        default=0,
        sa_column=Column(Integer, nullable=False, server_default="0"),
    )
    # "Controlar o pagamento das contas" (ADR 0029): quando ligado, o lançamento
    # fora do cartão só vira SAÍDA DE CAIXA depois de marcado como pago — e até
    # lá aparece em Contas a pagar. Desligado, o comportamento é o antigo: o
    # dinheiro sai na data do lançamento.
    #
    # É opção do ESPAÇO, e não da pessoa, porque a resposta muda com o combinado
    # da casa: quem lança tudo depois de pagar não quer a etapa a mais; quem
    # cadastra o boleto quando ele chega precisa dela. Ligado por padrão — o
    # `server_default` vale para os espaços que já existem, que continuam
    # idênticos porque a migração preenche `settled_at` de todo o histórico.
    settlement_tracking: bool = Field(
        default=True,
        sa_column=Column(Boolean, nullable=False, server_default=true()),
    )

    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    deleted_at: Optional[datetime] = Field(default=None)

    memberships: List["WorkspaceMembership"] = Relationship(back_populates="workspace")


class WorkspaceMembership(SQLModel, table=True):
    # uq(workspace, user): um usuário tem UM papel por workspace. Três caminhos
    # inserem membership (registro com convite pendente, convite a usuário
    # existente e aceite de link) e todos faziam select-then-insert: sob
    # concorrência nascia linha duplicada, que inflava member_count e — pior —
    # fazia get_workspace_membership resolver o PAPEL com .first(), de forma
    # não-determinística.
    __table_args__ = (
        Index("uq_membership_workspace_user", "workspace_id", "user_id", unique=True),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    workspace_id: int = Field(foreign_key="workspace.id")
    user_id: int = Field(foreign_key="user.id")
    role: WorkspaceRole = Field(
        default=WorkspaceRole.member,
        sa_column=Column(String(20), nullable=False, server_default="member"),
    )
    # Visibilidade dos dados financeiros, separada do papel (ADR 0018). O
    # server_default é o valor FECHADO: linha nova — venha de convite, registro,
    # aceite de link ou import — nasce privada, e abrir é ato explícito. Owner e
    # admin têm acesso completo pelo cargo (ver `access_policy.effective_access`),
    # independente do que estiver gravado aqui.
    financial_access: FinancialAccess = Field(
        default=FinancialAccess.involved_only,
        sa_column=Column(String(20), nullable=False, server_default="involved_only"),
    )

    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    workspace: Workspace = Relationship(back_populates="memberships")


class WorkspaceInvite(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    workspace_id: int = Field(foreign_key="workspace.id", index=True)
    # email=None indica convite por link (qualquer usuário logado pode aceitar)
    email: Optional[str] = Field(default=None, index=True)
    role: WorkspaceRole = Field(
        default=WorkspaceRole.member,
        sa_column=Column(String(20), nullable=False, server_default="member"),
    )
    # Acesso financeiro que o convidado receberá ao aceitar (ADR 0018): a decisão
    # é de quem convida e viaja NO convite — decidir no aceite deixaria a escolha
    # com o convidado.
    financial_access: FinancialAccess = Field(
        default=FinancialAccess.involved_only,
        sa_column=Column(String(20), nullable=False, server_default="involved_only"),
    )
    token: str = Field(
        default_factory=lambda: secrets.token_urlsafe(32),
        unique=True,
        index=True,
    )
    invited_by_user_id: Optional[int] = Field(default=None, foreign_key="user.id")
    status: InviteStatus = Field(
        default=InviteStatus.pending,
        sa_column=Column(String(20), nullable=False, server_default="pending"),
    )
    expires_at: datetime
    max_uses: Optional[int] = Field(default=None)  # apenas convites por link
    uses: int = Field(default=0)

    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
