from contextlib import contextmanager
from typing import Generator, Iterator

from sqlmodel import Session

from app.db.engine import engine


def get_session() -> Generator[Session, None, None]:
    """
    Dependency do FastAPI para fornecer uma sessão de banco de dados.
    Garante que a sessão seja fechada após o uso.
    """
    with Session(engine) as session:
        yield session


@contextmanager
def session_scope() -> Iterator[Session]:
    """Sessão CURTA para quem não pode usar `Depends(get_session)`.

    O WebSocket é o caso: a dependency do FastAPI vive o tempo inteiro do
    endpoint, e um socket fica aberto enquanto a aba estiver aberta — ou seja,
    uma conexão do pool presa por aba. Com o pool padrão (5 + 10 overflow)
    bastavam ~15 abas para esgotar o pool e travar a API INTEIRA. Aqui a sessão
    é aberta, usada para autenticar e fechada imediatamente.

    É também o seam de teste do WebSocket (a suíte o substitui pela sessão do
    fixture, como faz com `get_session` via dependency_overrides).
    """
    with Session(engine) as session:
        yield session
