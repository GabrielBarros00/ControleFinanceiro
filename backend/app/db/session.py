from typing import Generator
from sqlmodel import Session
from app.db.engine import engine

def get_session() -> Generator[Session, None, None]:
    """
    Dependency do FastAPI para fornecer uma sessão de banco de dados.
    Garante que a sessão seja fechada após o uso.
    """
    with Session(engine) as session:
        yield session
