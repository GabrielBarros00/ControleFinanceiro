"""Emissão e validação de JWT (HS256).

Usa PyJWT. O `python-jose`, usado antes, está praticamente sem manutenção e
acumula CVEs — entre elas confusão de algoritmo (aceitar um token assinado com
algoritmo diferente do esperado) e "JWT bomb". Aqui o algoritmo é SEMPRE
explícito na verificação, que é a defesa contra a primeira.
"""
from datetime import datetime, timedelta, UTC
from typing import Optional, Any, Dict

import jwt
from jwt import InvalidTokenError

from app.core.config import settings

ALGORITHM = "HS256"


def create_access_token(data: Dict[str, Any], expires_delta: Optional[timedelta] = None) -> str:
    """Cria um token JWT de acesso."""
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(UTC) + expires_delta
    else:
        expire = datetime.now(UTC) + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRES_MINUTES)

    to_encode.update({"exp": expire, "token_type": "access"})
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=ALGORITHM)


def create_refresh_token(data: Dict[str, Any], expires_delta: Optional[timedelta] = None) -> str:
    """Cria um token JWT de atualização (refresh)."""
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(UTC) + expires_delta
    else:
        expire = datetime.now(UTC) + timedelta(days=settings.REFRESH_TOKEN_EXPIRES_DAYS)

    to_encode.update({"exp": expire, "token_type": "refresh"})
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=ALGORITHM)


def create_purpose_token(data: Dict[str, Any], purpose: str, expires_delta: timedelta) -> str:
    """Cria um token JWT de propósito específico (ex: reset de senha, state OAuth)."""
    to_encode = data.copy()
    expire = datetime.now(UTC) + expires_delta
    to_encode.update({"exp": expire, "token_type": purpose})
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=ALGORITHM)


def decode_token(token: str) -> Dict[str, Any]:
    """Decodifica um token JWT e valida a assinatura.

    `algorithms` fixo em HS256: sem essa lista o verificador aceitaria o
    algoritmo declarado no próprio token, que é o vetor clássico de confusão de
    algoritmo. Levanta `InvalidTokenError` (e subclasses, como
    `ExpiredSignatureError`) — os chamadores já tratam qualquer exceção como
    token inválido.
    """
    return jwt.decode(token, settings.SECRET_KEY, algorithms=[ALGORITHM])


__all__ = [
    "ALGORITHM",
    "InvalidTokenError",
    "create_access_token",
    "create_refresh_token",
    "create_purpose_token",
    "decode_token",
]
