"""Casos incomuns que causavam 500/corrupção antes da blindagem de validação."""
from datetime import datetime, UTC

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.main import app
from app.core.jwt import create_access_token
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMembership
from app.models.transaction import Transaction

client = TestClient(app)


def _headers(user: User) -> dict:
    return {"Cookie": f"access_token={create_access_token({'sub': str(user.id)})}"}


@pytest.fixture
def solo(db_session: Session, override_get_session):
    user = User(name="Edge", email="edge@case.com", password_hash="hash")
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    ws = Workspace(name="Edge WS", created_by_user_id=user.id)
    db_session.add(ws)
    db_session.commit()
    db_session.refresh(ws)
    db_session.add(WorkspaceMembership(workspace_id=ws.id, user_id=user.id, role="owner"))
    db_session.commit()
    return {"user": user, "ws": ws, "db": db_session}


def _tx_payload(user, amount="100.00", **overrides):
    payload = {
        "title": "Edge Tx",
        "total_amount": amount,
        "transaction_date": datetime.now(UTC).isoformat(),
        "payers": [{"user_id": user.id, "amount": amount}],
        "splits": [{"user_id": user.id, "split_method": "equal", "input_value": "0"}],
    }
    payload.update(overrides)
    return payload


# --- Valores negativos/zero são rejeitados na borda (422, nunca 500) ---

def test_negative_transaction_rejected(solo):
    res = client.post(
        f"/api/v1/workspaces/{solo['ws'].id}/transactions/",
        json=_tx_payload(solo["user"], amount="-50.00"),
        headers=_headers(solo["user"]),
    )
    assert res.status_code == 422


def test_zero_transaction_rejected(solo):
    res = client.post(
        f"/api/v1/workspaces/{solo['ws'].id}/transactions/",
        json=_tx_payload(solo["user"], amount="0.00"),
        headers=_headers(solo["user"]),
    )
    assert res.status_code == 422


def test_negative_income_rejected(solo):
    res = client.post(
        f"/api/v1/workspaces/{solo['ws'].id}/income/",
        json={"title": "Anti-renda", "amount": "-100", "received_at": datetime.now(UTC).isoformat()},
        headers=_headers(solo["user"]),
    )
    assert res.status_code == 422


def test_recurring_day_out_of_bounds_rejected(solo):
    res = client.post(
        f"/api/v1/workspaces/{solo['ws'].id}/recurring",
        json={"title": "Dia 45", "base_amount": "10", "day_of_month": 45},
        headers=_headers(solo["user"]),
    )
    assert res.status_code == 422


def test_estimate_invalid_month_rejected(solo):
    res = client.post(
        f"/api/v1/workspaces/{solo['ws'].id}/analytics/estimates",
        json={"category": "Geral", "amount": "100", "month": "2026-13"},
        headers=_headers(solo["user"]),
    )
    assert res.status_code == 422


# --- Divisões inválidas: 400 e SEM transação órfã ---

def test_percentage_not_100_returns_400_without_orphan(solo):
    db = solo["db"]
    payload = _tx_payload(solo["user"])
    payload["splits"] = [
        {"user_id": solo["user"].id, "split_method": "percentage", "input_value": "60"},
    ]  # 60% != 100%
    res = client.post(
        f"/api/v1/workspaces/{solo['ws'].id}/transactions/",
        json=payload,
        headers=_headers(solo["user"]),
    )
    assert res.status_code == 400

    orphans = db.exec(select(Transaction).where(Transaction.title == "Edge Tx")).all()
    assert orphans == []  # criação é atômica


def test_fixed_split_mismatch_returns_400(solo):
    payload = _tx_payload(solo["user"])
    payload["splits"] = [
        {"user_id": solo["user"].id, "split_method": "fixed", "input_value": "80"},
    ]  # 80 != 100
    res = client.post(
        f"/api/v1/workspaces/{solo['ws'].id}/transactions/",
        json=payload,
        headers=_headers(solo["user"]),
    )
    assert res.status_code == 400


# --- Cartão com fechamento dia 31 em fevereiro (antes: ValueError → 500) ---

def test_statement_closing_day_31_in_february(solo):
    res = client.post(
        f"/api/v1/workspaces/{solo['ws'].id}/credit-cards/",
        json={"name": "Dia 31", "limit": "1000", "closing_day": 31, "due_day": 10},
        headers=_headers(solo["user"]),
    )
    card_id = res.json()["id"]

    payload = _tx_payload(solo["user"], amount="10.00")
    payload["transaction_date"] = "2026-02-15T12:00:00"
    payload["credit_card_id"] = card_id
    res = client.post(
        f"/api/v1/workspaces/{solo['ws'].id}/transactions/",
        json=payload,
        headers=_headers(solo["user"]),
    )
    assert res.status_code == 200, res.text
    assert res.json()["statement_id"] is not None

    res = client.get(
        f"/api/v1/workspaces/{solo['ws'].id}/credit-cards/{card_id}/statements",
        headers=_headers(solo["user"]),
    )
    stmt = res.json()[0]
    assert stmt["month"] == "2026-02"
    assert stmt["closing_date"].startswith("2026-02-28")  # dia 31 limitado ao fim de fev


def test_card_day_out_of_bounds_rejected(solo):
    res = client.post(
        f"/api/v1/workspaces/{solo['ws'].id}/credit-cards/",
        json={"name": "Dia 45", "limit": "1000", "closing_day": 45, "due_day": 10},
        headers=_headers(solo["user"]),
    )
    assert res.status_code == 422


# --- Paginação e filtros com valores inválidos ---

def test_pagination_invalid_params_rejected(solo):
    ws, user = solo["ws"], solo["user"]
    assert client.get(f"/api/v1/workspaces/{ws.id}/transactions/?limit=0", headers=_headers(user)).status_code == 422
    assert client.get(f"/api/v1/workspaces/{ws.id}/transactions/?page=0", headers=_headers(user)).status_code == 422
    assert client.get(f"/api/v1/workspaces/{ws.id}/transactions/?limit=5000", headers=_headers(user)).status_code == 422


def test_summary_invalid_month_returns_400(solo):
    ws, user = solo["ws"], solo["user"]
    assert client.get(f"/api/v1/workspaces/{ws.id}/analytics/summary?month=lixo", headers=_headers(user)).status_code == 400
    assert client.get(f"/api/v1/workspaces/{ws.id}/analytics/summary?month=2026-99", headers=_headers(user)).status_code == 400


# --- Editar a data recalcula o mês de competência ---

def test_update_date_recomputes_billing_month(solo):
    res = client.post(
        f"/api/v1/workspaces/{solo['ws'].id}/transactions/",
        json=_tx_payload(solo["user"]) | {"transaction_date": "2026-07-10T12:00:00", "billing_month": "2026-07"},
        headers=_headers(solo["user"]),
    )
    tx_id = res.json()["id"]

    res = client.put(
        f"/api/v1/workspaces/{solo['ws'].id}/transactions/{tx_id}",
        json={"transaction_date": "2026-08-05T12:00:00"},
        headers=_headers(solo["user"]),
    )
    assert res.status_code == 200
    assert res.json()["billing_month"] == "2026-08"


# --- Bulk import pula linhas inválidas sem 500 ---

def test_bulk_import_skips_invalid_rows(solo):
    res = client.post(
        f"/api/v1/workspaces/{solo['ws'].id}/transactions/bulk",
        json=[
            {"title": "OK", "total_amount": "10.00", "transaction_date": "2026-07-01T00:00:00Z"},
            {"title": "Valor lixo", "total_amount": "abc", "transaction_date": "2026-07-01T00:00:00Z"},
            {"title": "Data lixo", "total_amount": "5.00", "transaction_date": "não-é-data"},
            {"title": "Zerada", "total_amount": "0.00"},
        ],
        headers=_headers(solo["user"]),
    )
    assert res.status_code == 200
    assert res.json()["created"] == 1
    assert res.json()["skipped"] == 3


# --- Conta desativada perde acesso imediatamente ---

def test_deactivated_user_rejected(solo):
    db = solo["db"]
    user = solo["user"]
    token = create_access_token({"sub": str(user.id)})

    user.is_active = False
    db.add(user)
    db.commit()

    res = client.get("/api/v1/auth/me", headers={"Cookie": f"access_token={token}"})
    assert res.status_code == 401
