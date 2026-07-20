from fastapi.testclient import TestClient
from fastapi import HTTPException, status
from app.main import app

client = TestClient(app, raise_server_exceptions=False)

def test_validation_error_format():
    # Envia payload inválido para trigger de validation_exception_handler
    # O endpoint /api/v1/auth/login espera email e password
    response = client.post("/api/v1/auth/login", json={"email": "not-an-email"})
    assert response.status_code == 422
    data = response.json()
    assert data["error"]["code"] == "VALIDATION_ERROR"
    # Verifica se o loop de detalhes foi percorrido
    assert len(data["error"]["details"]) > 0

def test_unauthorized_error_format():
    # 401 unmapped or mapped
    response = client.get("/api/v1/auth/me") # Sem cookie
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHORIZED"

def test_http_error_unmapped():
    # Trigger 405 (Method Not Allowed) ou um erro customizado para testar o 'HTTP_ERROR' default
    @app.get("/trigger-418")
    def trigger_418():
        raise HTTPException(status_code=status.HTTP_418_IM_A_TEAPOT, detail="Teapot")
    
    response = client.get("/trigger-418")
    assert response.status_code == 418
    assert response.json()["error"]["code"] == "HTTP_ERROR"

def test_internal_server_error_format():
    # Simula um erro 500 real
    @app.get("/trigger-500")
    def trigger_500():
        raise RuntimeError("Panic!")
    
    response = client.get("/trigger-500")
    assert response.status_code == 500
    data = response.json()
    assert data["error"]["code"] == "INTERNAL_SERVER_ERROR"
    assert data["error"]["details"]["error_type"] == "RuntimeError"
