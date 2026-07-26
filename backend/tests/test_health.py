import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.db.session import get_session

@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c

def test_health_check(client):
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    # The version might change, so we check status ok
    assert response.json()["status"] == "ok"


def test_health_check_toca_o_banco(client):
    """O healthcheck precisa provar que o banco responde, não só que o processo
    está de pé — senão o container fica `healthy` com o Postgres fora do ar."""
    body = client.get("/api/v1/health").json()
    assert body["database"] == "ok"


def test_health_check_degrada_quando_o_banco_cai():
    """Banco indisponível → 503, para o orquestrador reiniciar/despriorizar o
    container em vez de mandar tráfego para uma instância quebrada."""
    class _BrokenSession:
        def exec(self, *args, **kwargs):
            raise RuntimeError("connection refused")

    app.dependency_overrides[get_session] = lambda: _BrokenSession()
    try:
        with TestClient(app) as client:
            response = client.get("/api/v1/health")
        assert response.status_code == 503
        body = response.json()
        assert body["status"] == "degraded"
        assert body["database"] == "unavailable"
    finally:
        app.dependency_overrides.clear()
