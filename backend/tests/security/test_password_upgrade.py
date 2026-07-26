"""Hash de senha e JWT depois da troca de stack (B2).

Dois problemas atacados aqui:

- O primário era `pbkdf2_sha256` com os rounds PADRÃO do passlib (~29 mil),
  contra os 600 mil que o OWASP recomenda — hash ~20x mais barato de quebrar
  offline. Agora o primário é argon2id, e quem tem hash antigo é migrado no
  login, sem pedir nada ao usuário.
- O JWT era emitido/validado por `python-jose`, sem manutenção e com CVE de
  confusão de algoritmo. Agora é PyJWT com `algorithms=` explícito.
"""
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from passlib.context import CryptContext
from sqlmodel import Session, select

from app.core.jwt import ALGORITHM, create_access_token, decode_token
from app.core.security import (
    get_password_hash,
    pwd_context,
    verify_and_upgrade_password,
    verify_password,
)
from app.main import app
from app.models.user import User

# Contexto que produz EXATAMENTE o hash legado que está gravado no banco hoje
_legacy = CryptContext(schemes=["pbkdf2_sha256"], pbkdf2_sha256__default_rounds=29000)


# --- senha ------------------------------------------------------------------


def test_hash_novo_usa_argon2():
    assert get_password_hash("segredo123").startswith("$argon2id$")


def test_verifica_hash_legado_pbkdf2():
    """Contas antigas continuam entrando — migração não pode deslogar ninguém."""
    legacy_hash = _legacy.hash("segredo123")
    assert verify_password("segredo123", legacy_hash) is True
    assert verify_password("errada", legacy_hash) is False


def test_hash_legado_e_marcado_para_atualizacao():
    legacy_hash = _legacy.hash("segredo123")
    assert pwd_context.needs_update(legacy_hash) is True
    assert pwd_context.needs_update(get_password_hash("segredo123")) is False


def test_verify_and_upgrade_devolve_hash_argon2():
    legacy_hash = _legacy.hash("segredo123")
    ok, novo = verify_and_upgrade_password("segredo123", legacy_hash)
    assert ok is True
    assert novo is not None and novo.startswith("$argon2id$")
    # O hash novo continua validando a mesma senha
    assert verify_password("segredo123", novo) is True


def test_verify_and_upgrade_nao_regrava_hash_atual():
    atual = get_password_hash("segredo123")
    ok, novo = verify_and_upgrade_password("segredo123", atual)
    assert ok is True
    assert novo is None


def test_senha_errada_nao_gera_rehash():
    """Senha errada não pode custar um hash novo — seria trabalho grátis para
    quem estiver tentando força bruta."""
    legacy_hash = _legacy.hash("segredo123")
    ok, novo = verify_and_upgrade_password("errada", legacy_hash)
    assert ok is False
    assert novo is None


def test_login_migra_o_hash_legado(db_session: Session, override_get_session):
    """O caminho de ponta a ponta: entrar com conta antiga troca o hash no banco."""
    user = User(
        name="Legado", email="legado@t.com",
        password_hash=_legacy.hash("segredo123"),
    )
    db_session.add(user)
    db_session.commit()

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/auth/login",
            json={"email": "legado@t.com", "password": "segredo123"},
        )
    assert response.status_code == 200

    db_session.expire_all()
    migrado = db_session.exec(select(User).where(User.email == "legado@t.com")).one()
    assert migrado.password_hash.startswith("$argon2id$")


# --- JWT --------------------------------------------------------------------


def test_token_ida_e_volta():
    token = create_access_token({"sub": "42"})
    payload = decode_token(token)
    assert payload["sub"] == "42"
    assert payload["token_type"] == "access"


def test_token_expirado_e_recusado():
    import jwt as pyjwt

    token = create_access_token({"sub": "42"}, expires_delta=timedelta(seconds=-1))
    with pytest.raises(pyjwt.ExpiredSignatureError):
        decode_token(token)


def test_assinatura_invalida_e_recusada():
    import jwt as pyjwt

    forjado = pyjwt.encode({"sub": "42"}, "outra-chave-longa-o-suficiente-para-hmac", algorithm=ALGORITHM)
    with pytest.raises(pyjwt.InvalidTokenError):
        decode_token(forjado)


def test_algoritmo_none_e_recusado():
    """Confusão de algoritmo: token com `alg: none` não pode passar. É a classe
    de CVE que motivou sair do python-jose."""
    import jwt as pyjwt

    forjado = pyjwt.encode({"sub": "42"}, key="", algorithm="none")
    with pytest.raises(pyjwt.InvalidTokenError):
        decode_token(forjado)
