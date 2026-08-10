from sqlmodel import create_engine, Session, text
from app.core.config import settings

def test_engine_connection():
    # Usamos o engine real configurado (que deve ser SQLite para dev/test)
    engine = create_engine(settings.DATABASE_URL)
    try:
        with Session(engine) as session:
            result = session.exec(text("SELECT 1")).one()
            assert result[0] == 1
    finally:
        # Fechar a SESSÃO não fecha o POOL: o engine fica com a conexão viva até
        # o interpretador coletá-lo, sem passar por `close()` — um
        # `ResourceWarning: unclosed database` depois de uma suíte verde. Barulho
        # que não reprova nada e, por isso mesmo, esconde o próximo vazamento.
        engine.dispose()

def test_get_session_dependency():
    # Testar se a dependência do FastAPI funciona (simulação básica)
    from app.db.session import get_session
    
    session_generator = get_session()
    session = next(session_generator)
    assert isinstance(session, Session)
    # Tenta rodar algo
    assert session.exec(text("SELECT 1")).one()[0] == 1
    
    # Verifica se fecha corretamente (não deve explodir)
    try:
        next(session_generator)
    except StopIteration:
        pass
