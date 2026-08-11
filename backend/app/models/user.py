from datetime import datetime, UTC
from enum import Enum
from typing import Optional
from sqlalchemy import Column, String
from sqlmodel import SQLModel, Field
from pydantic import EmailStr, ConfigDict


class PlatformRole(str, Enum):
    """Papel do usuário no SITE, ortogonal ao `WorkspaceRole` (ADR 0026).

    São dois eixos que nunca se cruzam, e confundi-los seria o pior desfecho
    possível deste model: `WorkspaceRole` diz o que a pessoa pode fazer DENTRO de
    uma casa (e chega a `owner`, que enxerga os números daquela casa);
    `PlatformRole` diz quem opera o SITE — quem convida, quem desativa conta,
    quem lê a trilha de auditoria. Um `superadmin` não ganha um centímetro de
    visão financeira sobre workspace nenhum: `access_policy` não consulta este
    campo, e é isso que mantém de pé o ADR 0018 (privacidade por membro) e o
    0021 (recurso pessoal sem workspace).

    Persistido como texto, não como Enum nativo do Postgres, seguindo
    `WorkspaceMembership.role`. Enum nativo exige `ALTER TYPE` à mão para cada
    valor novo, e nem o `alembic check` nem o `create_all` da suíte enxergam a
    divergência — foi exatamente assim que `daily` chegou quebrado em produção
    (ver a revisão e9b2c50d7a14).
    """

    user = "user"
    admin = "admin"
    superadmin = "superadmin"


_PLATFORM_LEVELS = {"user": 0, "admin": 1, "superadmin": 2}


def platform_level(role) -> int:
    """Nível hierárquico do papel de plataforma (aceita enum ou string do banco)."""
    value = role.value if isinstance(role, PlatformRole) else str(role)
    return _PLATFORM_LEVELS.get(value, -1)


class UserBase(SQLModel):
    model_config = ConfigDict(validate_assignment=True)
    name: str = Field(index=True)
    email: EmailStr = Field(unique=True, index=True)
    is_active: bool = Field(default=True)

class User(UserBase, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    password_hash: str
    needs_onboarding: bool = Field(default=True)
    # Papel no SITE (ADR 0026). `server_default` é o valor FECHADO: conta nova —
    # venha de cadastro, convite ou OAuth — nasce sem poder nenhum de plataforma,
    # e promover é ato explícito e auditado.
    platform_role: PlatformRole = Field(
        default=PlatformRole.user,
        sa_column=Column(String(20), nullable=False, server_default="user"),
    )
    # Moeda em que os números PESSOAIS do usuário são expressos (ADR 0019).
    #
    # Existe porque o que é da pessoa não tem workspace de onde herdar a
    # moeda-base: um salário pessoal converteria diferente conforme a tela aberta,
    # e a visão global soma workspaces que podem ter bases distintas — o que o
    # ADR 0006 proíbe fazer sem uma moeda de destino declarada.
    report_currency: str = Field(
        default="BRL",
        sa_column=Column(String(3), nullable=False, server_default="BRL"),
    )
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    deleted_at: Optional[datetime] = Field(default=None)
