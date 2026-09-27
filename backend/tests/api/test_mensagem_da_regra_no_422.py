"""A regra de negócio recusada chega à tela com a frase dela (auditoria 2026-09-26, C11).

Regras escritas como validador do schema respondem 422. O envelope punha a frase
da regra em `details` e um texto genérico em `message` — e `message` é o único
campo que a tela lê (`frontend/src/lib/api-error.ts`). Quem tentava parcelar no
Pix via "Ocorreu um erro de validação nos dados enviados." e não sabia o que
mudar.
"""
import pytest
from fastapi.testclient import TestClient

from app.main import app

GENERICA = "Ocorreu um erro de validação nos dados enviados."


@pytest.fixture(name="client")
def client_fixture(override_get_session):
    return TestClient(app)


def _lanca(client, setup_data, **extra):
    ws, u1 = setup_data["ws1"], setup_data["u1"]
    corpo = {
        "title": "Geladeira", "total_amount": "3000.00",
        "transaction_date": "2026-09-20T12:00:00Z",
        "payers": [{"user_id": u1.id, "amount": "3000.00"}],
        "splits": [{"user_id": u1.id, "split_method": "equal", "input_value": "0"}],
        **extra,
    }
    return client.post(f"/api/v1/workspaces/{ws.id}/transactions/", json=corpo, headers=setup_data["headers1"])


def test_regra_do_modelo_vira_a_mensagem(client, setup_data):
    r = _lanca(client, setup_data, installments_count=3, payment_method="pix")
    assert r.status_code == 422, r.text
    erro = r.json()["error"]
    assert erro["code"] == "VALIDATION_ERROR"
    assert erro["message"] == "Parcelamento exige pagamento no cartão de crédito"
    # Nos detalhes também sem o prefixo em inglês do Pydantic.
    assert all(not v.startswith("Value error") for v in erro["details"].values())


def test_erro_do_proprio_pydantic_continua_com_a_mensagem_generica(client, setup_data):
    # Campo que falta: a mensagem do Pydantic é em inglês ("Field required") e
    # não serve para a tela — vale o texto genérico, com o campo nos detalhes.
    ws = setup_data["ws1"]
    r = client.post(f"/api/v1/workspaces/{ws.id}/transactions/", json={"title": "Sem valor"},
                    headers=setup_data["headers1"])
    assert r.status_code == 422
    erro = r.json()["error"]
    assert erro["message"] == GENERICA
    assert "total_amount" in erro["details"]
