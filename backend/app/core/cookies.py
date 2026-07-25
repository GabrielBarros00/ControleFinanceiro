from fastapi import Response
from app.core.config import settings

def set_auth_cookies(response: Response, access_token: str, refresh_token: str):
    """Define os cookies de autenticação HttpOnly."""
    response.set_cookie(
        key="access_token",
        value=access_token,
        httponly=True,
        secure=settings.COOKIE_SECURE,
        samesite=settings.COOKIE_SAMESITE,
        max_age=settings.ACCESS_TOKEN_EXPIRES_MINUTES * 60
    )
    response.set_cookie(
        key="refresh_token",
        value=refresh_token,
        httponly=True,
        secure=settings.COOKIE_SECURE,
        samesite=settings.COOKIE_SAMESITE,
        max_age=settings.REFRESH_TOKEN_EXPIRES_DAYS * 24 * 60 * 60
    )

def clear_auth_cookies(response: Response):
    """Remove os cookies de autenticação (mesmos atributos do set para o browser casar o cookie)."""
    for key in ("access_token", "refresh_token"):
        response.delete_cookie(
            key=key,
            httponly=True,
            secure=settings.COOKIE_SECURE,
            samesite=settings.COOKIE_SAMESITE,
        )


# Nonce do fluxo OAuth: o `state` só vale se casar com este cookie, o que
# amarra o callback AO NAVEGADOR que iniciou o login. Sem isso um atacante
# gera um state válido no próprio navegador e induz a vítima a completar o
# callback com o code dele — login CSRF (a vítima acaba dentro da conta alheia).
OAUTH_STATE_COOKIE = "oauth_state"


def set_oauth_state_cookie(response: Response, nonce: str) -> None:
    response.set_cookie(
        key=OAUTH_STATE_COOKIE,
        value=nonce,
        httponly=True,
        secure=settings.COOKIE_SECURE,
        # 'lax' deixa o cookie acompanhar o redirect de volta do Google (GET
        # top-level); 'strict' o suprimiria e quebraria o login.
        samesite="lax",
        max_age=600,
    )


def clear_oauth_state_cookie(response: Response) -> None:
    response.delete_cookie(
        key=OAUTH_STATE_COOKIE,
        httponly=True,
        secure=settings.COOKIE_SECURE,
        samesite="lax",
    )
