import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session
from app.main import app
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMembership
from app.models.income import Income
from app.core.jwt import create_access_token

client = TestClient(app)

@pytest.fixture
def income_setup(db_session: Session):
    u1 = User(name="User 1", email="u1@income.com", password_hash="hash")
    u2 = User(name="User 2", email="u2@income.com", password_hash="hash")
    db_session.add_all([u1, u2])
    db_session.commit()
    db_session.refresh(u1)
    db_session.refresh(u2)
    
    ws1 = Workspace(name="WS 1", created_by_user_id=u1.id)
    db_session.add(ws1)
    db_session.commit()
    db_session.refresh(ws1)
    db_session.add(WorkspaceMembership(workspace_id=ws1.id, user_id=u1.id, role="owner"))
    db_session.commit()
    
    token1 = create_access_token(data={"sub": str(u1.id)})
    token2 = create_access_token(data={"sub": str(u2.id)})
    
    return {
        "u1": u1, "u2": u2, 
        "ws1": ws1, 
        "headers1": {"Cookie": f"access_token={token1}"},
        "headers2": {"Cookie": f"access_token={token2}"}
    }

def test_create_income_success(income_setup, override_get_session):
    income_setup["ws1"].id
    payload = {
        "title": "Salary",
        "amount": 5000.0,
        "category": "Salary",
        "received_at": "2026-05-10T10:00:00"
    }
    response = client.post("/api/v1/me/income/", json=payload, headers=income_setup["headers1"])
    assert response.status_code == 200
    assert response.json()["title"] == "Salary"

def test_renda_criada_pertence_a_quem_criou(income_setup, override_get_session):
    """Rota pessoal não tem "proibido": ela cria a renda DE QUEM PEDE (ADR 0021).

    Antes o u2 levava 403 por não ser membro do ws1 — o gate era o workspace da
    URL. Agora não há workspace na URL, e o isolamento é que a renda do u2 nasce
    dele e nunca aparece para o u1.
    """
    payload = {"title": "Do u2", "amount": 100, "received_at": "2026-05-10T10:00:00"}
    response = client.post("/api/v1/me/income", json=payload, headers=income_setup["headers2"])
    assert response.status_code == 200
    assert response.json()["user_id"] == income_setup["u2"].id

    do_u1 = client.get("/api/v1/me/income", headers=income_setup["headers1"]).json()
    assert response.json()["id"] not in [i["id"] for i in do_u1]

def test_list_income_success(db_session: Session, income_setup, override_get_session):
    income_setup["ws1"].id
    u1_id = income_setup["u1"].id
    
    # Create one income
    db_session.add(Income(title="I1", amount=100, category="C", user_id=u1_id))
    db_session.commit()
    
    response = client.get("/api/v1/me/income/", headers=income_setup["headers1"])
    assert response.status_code == 200
    assert len(response.json()) == 1

def test_list_income_de_outro_usuario_vem_vazia(income_setup, override_get_session):
    """O u2 não vê a renda do u1: a lista dele é a lista DELE."""
    response = client.get("/api/v1/me/income", headers=income_setup["headers2"])
    assert response.status_code == 200
    assert response.json() == []


def test_list_income_filtra_por_mes(db_session: Session, income_setup, override_get_session):
    from datetime import datetime
    income_setup["ws1"].id
    u1_id = income_setup["u1"].id
    db_session.add(Income(title="Maio", amount=100, user_id=u1_id,
                          received_at=datetime(2026, 5, 10, 12, 0, 0)))
    db_session.add(Income(title="Junho", amount=200, user_id=u1_id,
                          received_at=datetime(2026, 6, 10, 12, 0, 0)))
    db_session.commit()

    resp = client.get("/api/v1/me/income/?month=2026-05", headers=income_setup["headers1"])
    assert resp.status_code == 200
    assert [i["title"] for i in resp.json()] == ["Maio"]

    resp = client.get("/api/v1/me/income/?month=2026-06", headers=income_setup["headers1"])
    assert [i["title"] for i in resp.json()] == ["Junho"]

    # Sem mês: retorna tudo (compat. com o comportamento antigo)
    resp = client.get("/api/v1/me/income/", headers=income_setup["headers1"])
    assert len(resp.json()) == 2


def test_income_estrangeira_converte(db_session: Session, income_setup, override_get_session, monkeypatch):
    from decimal import Decimal
    from app.services import currency_service as cs
    monkeypatch.setattr(cs.CurrencyService, "get_rate_sync", lambda *a, **k: (Decimal("5.00"), "ptax"))
    income_setup["ws1"].id
    resp = client.post(
        "/api/v1/me/income/",
        json={"title": "Freela USD", "amount": 100.0, "currency": "USD", "received_at": "2026-05-10T10:00:00"},
        headers=income_setup["headers1"],
    )
    assert resp.status_code == 200, resp.text
    inc = resp.json()
    assert inc["amount"] == "500.00"  # 100 × 5, sem IOF (renda)
    assert inc["currency"] == "BRL"
    assert inc["original_currency"] == "USD"
    assert Decimal(inc["original_amount"]) == Decimal("100.00")
    assert Decimal(inc["exchange_rate"]) == Decimal("5.00")


def test_income_edicao_parcial_preserva_original(income_setup, override_get_session, monkeypatch):
    """Editar só o título de uma renda estrangeira NÃO apaga a proveniência: o PUT
    parcial que não toca em amount/currency preserva o original congelado."""
    from decimal import Decimal
    from app.services import currency_service as cs
    monkeypatch.setattr(cs.CurrencyService, "get_rate_sync", lambda *a, **k: (Decimal("5.00"), "ptax"))
    income_setup["ws1"].id
    resp = client.post(
        "/api/v1/me/income/",
        json={"title": "Freela USD", "amount": 100.0, "currency": "USD", "received_at": "2026-05-10T10:00:00"},
        headers=income_setup["headers1"],
    )
    income_id = resp.json()["id"]

    # PUT só com o título — sem amount/currency
    resp = client.put(
        f"/api/v1/me/income/{income_id}",
        json={"title": "Freela USD (renomeado)"},
        headers=income_setup["headers1"],
    )
    assert resp.status_code == 200, resp.text
    upd = resp.json()
    assert upd["title"] == "Freela USD (renomeado)"
    # BRL e proveniência preservados
    assert upd["amount"] == "500.00"
    assert upd["currency"] == "BRL"
    assert upd["original_currency"] == "USD"
    assert Decimal(upd["original_amount"]) == Decimal("100.00")
    assert Decimal(upd["exchange_rate"]) == Decimal("5.00")


def test_income_edicao_para_brl_limpa_original(income_setup, override_get_session, monkeypatch):
    """Trocar a renda estrangeira de volta para BRL (enviando currency) limpa o
    original congelado."""
    from decimal import Decimal
    from app.services import currency_service as cs
    monkeypatch.setattr(cs.CurrencyService, "get_rate_sync", lambda *a, **k: (Decimal("5.00"), "ptax"))
    income_setup["ws1"].id
    resp = client.post(
        "/api/v1/me/income/",
        json={"title": "Freela USD", "amount": 100.0, "currency": "USD", "received_at": "2026-05-10T10:00:00"},
        headers=income_setup["headers1"],
    )
    income_id = resp.json()["id"]

    resp = client.put(
        f"/api/v1/me/income/{income_id}",
        json={"amount": 300.0, "currency": "BRL"},
        headers=income_setup["headers1"],
    )
    assert resp.status_code == 200, resp.text
    upd = resp.json()
    assert upd["amount"] == "300.00"
    assert upd["currency"] == "BRL"
    assert upd["original_currency"] is None
    assert upd["original_amount"] is None
    assert upd["exchange_rate"] is None
