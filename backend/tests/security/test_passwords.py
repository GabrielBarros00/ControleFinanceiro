import pytest
from app.core.security import verify_password, get_password_hash
from app.models.user import User
from app.schemas.user import UserResponse
from pydantic import ValidationError
from datetime import datetime, UTC

def test_password_hashing():
    password = "secret-password"
    hashed = get_password_hash(password)
    assert hashed != password
    assert verify_password(password, hashed) is True
    assert not verify_password("wrong-password", hashed)

def test_user_model_serialization():
    # O modelo de resposta nunca deve incluir o hash da senha
    user_data = {
        "id": 1,
        "name": "Gabriel",
        "email": "gabriel@example.com",
        "password_hash": "hashed_value_that_should_be_hidden",
        "is_active": True,
        "needs_onboarding": False,
        "platform_role": "user",
        "created_at": datetime.now(UTC)
    }
    
    # UserResponse deve ignorar campos extras ou não ter password_hash definido
    user_res = UserResponse(**user_data)
    serialized = user_res.model_dump()
    assert "password_hash" not in serialized
    assert serialized["name"] == "Gabriel"

def test_user_model_invalid_email():
    # SQLModel/Pydantic v2 validação em tempo de atribuição/init
    with pytest.raises(ValidationError):
        User(name="Gabriel", email="invalid-email", password_hash="hash")
