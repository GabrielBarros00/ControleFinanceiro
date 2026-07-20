import pytest
from fastapi.testclient import TestClient
from app.main import app

@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c

def test_health_check(client):
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    # The version might change, so we check status ok
    assert response.json()["status"] == "ok"
