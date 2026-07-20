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
