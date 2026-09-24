"""Primitivas do authorization server: segredos aleatórios, hash e PKCE.

Nada daqui guarda segredo em claro. O token/código/segredo existe só na resposta
HTTP que o entrega; o banco tem o SHA-256 dele. Segredo de 256 bits aleatórios
não precisa de sal nem de hash lento — não há dicionário para atacar.
"""
import base64
import hashlib
import hmac
import secrets

#: Prefixos identificáveis: um token vazado num log ou repositório é reconhecível
#: por scanner de segredo, e o prefixo diz de onde veio sem revelar nada.
ACCESS_PREFIX = "cfm_at_"
REFRESH_PREFIX = "cfm_rt_"
CODE_PREFIX = "cfm_ac_"
CLIENT_SECRET_PREFIX = "cfm_cs_"
CONFIRMATION_PREFIX = "cfm_cf_"
#: Link de envio de arquivo pelo terminal (`attachments_upload_link`).
UPLOAD_PREFIX = "cfm_up_"

_PKCE_CHARSET = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~")


def new_secret(prefix: str) -> str:
    return prefix + secrets.token_urlsafe(32)


def sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def same(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode("utf-8"), b.encode("utf-8"))


def valid_pkce_value(value: str | None) -> bool:
    """RFC 7636 §4.1: 43–128 caracteres do conjunto não reservado."""
    return bool(value) and 43 <= len(value) <= 128 and set(value) <= _PKCE_CHARSET


def pkce_s256(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def verify_pkce(verifier: str, challenge: str) -> bool:
    if not valid_pkce_value(verifier):
        return False
    return same(pkce_s256(verifier), challenge)
