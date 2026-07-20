from datetime import datetime
from pydantic import BaseModel, EmailStr, ConfigDict

class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    email: EmailStr
    is_active: bool
    needs_onboarding: bool
    created_at: datetime
