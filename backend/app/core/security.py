"""Hash e verificação de senha.

Primário: **argon2id** (vencedor do Password Hashing Competition, recomendação
atual do OWASP). Antes o primário era `pbkdf2_sha256` com os rounds PADRÃO do
passlib (~29 mil) — a recomendação do OWASP para PBKDF2-HMAC-SHA256 é 600 mil,
ou seja, o hash era cerca de 20x mais barato de quebrar offline do que deveria.

`pbkdf2_sha256` e `bcrypt` seguem na lista apenas para VERIFICAR hashes já
gravados. Quem faz login com hash legado é migrado para argon2 de forma
transparente (`needs_rehash`), sem pedir nada ao usuário. Quando não restar hash
legado, passlib pode sair das dependências.
"""
from typing import Optional, Tuple

from passlib.context import CryptContext

pwd_context = CryptContext(
    schemes=["argon2", "pbkdf2_sha256", "bcrypt"],
    deprecated=["pbkdf2_sha256", "bcrypt"],
    # Parâmetros do argon2id: acima do mínimo do OWASP (19 MiB / t=2) com folga,
    # mantendo o login abaixo de ~300ms.
    argon2__type="ID",
    argon2__memory_cost=65536,   # 64 MiB
    argon2__time_cost=3,
    argon2__parallelism=2,
    # Se algum hash pbkdf2 antigo precisar ser REGRAVADO antes da migração para
    # argon2, que seja com custo decente.
    pbkdf2_sha256__default_rounds=600_000,
)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verifica se a senha em texto plano corresponde ao hash."""
    return pwd_context.verify(plain_password, hashed_password)


def verify_and_upgrade_password(
    plain_password: str, hashed_password: str
) -> Tuple[bool, Optional[str]]:
    """Verifica a senha e devolve `(ok, novo_hash_ou_None)`.

    O novo hash vem preenchido quando o hash guardado usa um esquema obsoleto
    (pbkdf2/bcrypt): o chamador grava e o usuário migra para argon2 sem notar.
    Só recalcula quando a senha CONFERE — senão daria para forçar trabalho de
    hashing com senha errada.
    """
    if not pwd_context.verify(plain_password, hashed_password):
        return False, None
    if pwd_context.needs_update(hashed_password):
        return True, pwd_context.hash(plain_password)
    return True, None


def get_password_hash(password: str) -> str:
    """Gera o hash da senha com o algoritmo primário (argon2id)."""
    return pwd_context.hash(password)


# Hash descartável usado para gastar o MESMO tempo de verificação quando o email
# não existe. Sem isso o login responde na hora para email inexistente e devagar
# para email real — a diferença enumera as contas cadastradas. Precisa usar o
# algoritmo PRIMÁRIO, senão o custo não bate com o de uma conta real.
_DUMMY_HASH = pwd_context.hash("senha-inexistente-para-igualar-o-tempo")


def spend_dummy_verification() -> None:
    """Queima o tempo de um verify() para o login não vazar timing."""
    pwd_context.verify("qualquer-coisa", _DUMMY_HASH)
