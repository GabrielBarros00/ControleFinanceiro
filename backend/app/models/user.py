from datetime import datetime, UTC
from typing import Optional
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
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    deleted_at: Optional[datetime] = Field(default=None)
