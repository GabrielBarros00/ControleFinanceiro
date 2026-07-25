from passlib.context import CryptContext

# Usamos pbkdf2_sha256 como primário para evitar bugs de compatibilidade do bcrypt 4.0+ com passlib
# Mantemos o bcrypt na lista para permitir a verificação de contas existentes
pwd_context = CryptContext(schemes=["pbkdf2_sha256", "bcrypt"], deprecated="auto")

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verifica se a senha em texto plano corresponde ao hash."""
    return pwd_context.verify(plain_password, hashed_password)

def get_password_hash(password: str) -> str:
    """Gera o hash da senha usando bcrypt."""
    return pwd_context.hash(password)


# Hash descartável usado para gastar o MESMO tempo de verificação quando o email
# não existe. Sem isso o login responde na hora para email inexistente e devagar
# para email real — a diferença enumera as contas cadastradas.
_DUMMY_HASH = pwd_context.hash("senha-inexistente-para-igualar-o-tempo")


def spend_dummy_verification() -> None:
    """Queima o tempo de um verify() para o login não vazar timing."""
    pwd_context.verify("qualquer-coisa", _DUMMY_HASH)
