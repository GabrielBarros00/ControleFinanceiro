"""A moeda de relatório vem na sessão (auditoria 2026-09-26, P6).

Toda tela pessoal formata dinheiro na moeda de relatório da pessoa, e a tela a
lia do `/me/overview` inteiro — 64 consultas, ~95 ms — só por um campo. Ela é
atributo do usuário: sai no `/auth/me`, que o bootstrap já busca.
"""
import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture(name="client")
def client_fixture(override_get_session):
    return TestClient(app)


def test_auth_me_traz_a_moeda_e_acompanha_a_troca(client, setup_data):
    headers = setup_data["headers1"]
    assert client.get("/api/v1/auth/me", headers=headers).json()["report_currency"] == "BRL"

    r = client.patch("/api/v1/me/report-currency", json={"report_currency": "USD"}, headers=headers)
    assert r.status_code == 200, r.text

    assert client.get("/api/v1/auth/me", headers=headers).json()["report_currency"] == "USD"
