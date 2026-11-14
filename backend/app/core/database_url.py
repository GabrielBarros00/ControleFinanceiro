"""Escolha explícita do driver PostgreSQL, inclusive para URLs legadas."""


def normalizar_url_banco(url: str) -> str:
    """Mantém credenciais/opções intactas e usa Psycopg 3 (ADR 0043)."""
    for prefixo in ("postgresql://", "postgres://", "postgresql+psycopg2://"):
        if url.startswith(prefixo):
            return "postgresql+psycopg://" + url[len(prefixo):]
    return url
