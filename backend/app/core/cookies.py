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
