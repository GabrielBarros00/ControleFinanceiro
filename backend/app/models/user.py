from datetime import datetime, UTC
from typing import Optional
from sqlalchemy import Column, String
from sqlmodel import SQLModel, Field
from pydantic import EmailStr, ConfigDict

class UserBase(SQLModel):
    model_config = ConfigDict(validate_assignment=True)
    name: str = Field(index=True)
    email: EmailStr = Field(unique=True, index=True)
    is_active: bool = Field(default=True)

class User(UserBase, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    password_hash: str
    needs_onboarding: bool = Field(default=True)
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
