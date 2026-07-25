"""Escopo `materialize` (start_date retroativa) e categoria no modelo recorrente.

A data de início anterior ao mês corrente é ambígua — quem cadastra um salário
que começou em abril pode querer o histórico, só o mês atual ou só daqui pra
frente. A API pergunta via `?materialize=past|current|future`.
"""
from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.main import app
from app.core.jwt import create_access_token
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMembership
from app.models.credit_card import CardStatement
from app.models.income import Income
from app.models.recurring import RecurringIncome
from app.models.transaction import Transaction, TransactionItem

client = TestClient(app)


def _headers(user: User) -> dict:
    return {"Cookie": f"access_token={create_access_token({'sub': str(user.id)})}"}


def _shift_month(ref: date, months: int) -> date:
    """Mesmo dia, N meses atrás/à frente (dia 15 existe em todo mês)."""
    total = ref.year * 12 + (ref.month - 1) + months
    return date(total // 12, total % 12 + 1, ref.day)


@pytest.fixture
def solo(db_session: Session, override_get_session):
    user = User(name="Scope", email="scope@mat.com", password_hash="hash")
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    ws = Workspace(name="Scope WS", created_by_user_id=user.id)
    db_session.add(ws)
    db_session.commit()
    db_session.refresh(ws)
    db_session.add(WorkspaceMembership(workspace_id=ws.id, user_id=user.id, role="owner"))
    db_session.commit()
    return {"user": user, "ws": ws, "db": db_session}


def _create_income_template(solo, *, months_back: int, materialize: str | None = None):
    """Renda mensal dia 15 começando `months_back` meses atrás."""
    start = _shift_month(date.today().replace(day=15), -months_back)
    res = client.post(
        f"/api/v1/workspaces/{solo['ws'].id}/recurring-income",
        json={
            "title": "Salário",
            "base_amount": "5000.00",
            "day_of_month": 15,
            "start_date": start.isoformat(),
        },
        params={"materialize": materialize} if materialize else None,
        headers=_headers(solo["user"]),
    )
    assert res.status_code == 200, res.text
    return res.json(), start


def _income_months(db: Session, ws_id: int) -> set[str]:
    rows = db.exec(select(Income).where(Income.workspace_id == ws_id)).all()
    return {r.billing_month for r in rows}


# --- Escopo da materialização com start_date retroativa ---------------------

def test_escopo_past_lanca_o_historico(solo):
    _create_income_template(solo, months_back=3, materialize="past")

    meses = _income_months(solo["db"], solo["ws"].id)
    esperado = {
        _shift_month(date.today().replace(day=15), -n).strftime("%Y-%m")
        for n in range(0, 4)  # 3 meses atrás até o corrente
    }
    assert meses == esperado


def test_escopo_current_ignora_os_meses_anteriores(solo):
    _create_income_template(solo, months_back=3, materialize="current")

    assert _income_months(solo["db"], solo["ws"].id) == {date.today().strftime("%Y-%m")}


def test_escopo_future_nao_lanca_e_empurra_a_data_de_inicio(solo):
    """`future` precisa mover start_date: senão a materialização preguiçosa da
    próxima tela aberta recriaria o mês corrente que o usuário dispensou."""
    body, start = _create_income_template(solo, months_back=3, materialize="future")

    assert _income_months(solo["db"], solo["ws"].id) == set()
    nova_start = date.fromisoformat(body["start_date"])
    assert nova_start > date.today()
    assert nova_start.day == 15


def test_escopo_padrao_e_o_mes_corrente(solo):
    # Sem o parâmetro: comportamento conservador (não inventa histórico)
    _create_income_template(solo, months_back=2)

    assert _income_months(solo["db"], solo["ws"].id) == {date.today().strftime("%Y-%m")}


def test_escopo_invalido_rejeitado(solo):
    res = client.post(
        f"/api/v1/workspaces/{solo['ws'].id}/recurring-income",
        json={"title": "X", "base_amount": "10.00", "day_of_month": 1},
        params={"materialize": "tudo"},
        headers=_headers(solo["user"]),
    )
    assert res.status_code == 400


def test_editar_data_para_tras_com_escopo_past(solo):
    """Cenário do dono: cria hoje e depois corrige a data de início para trás."""
    hoje = date.today().replace(day=15)
    res = client.post(
        f"/api/v1/workspaces/{solo['ws'].id}/recurring-income",
        json={"title": "Salário", "base_amount": "5000.00", "day_of_month": 15,
              "start_date": hoje.isoformat()},
        headers=_headers(solo["user"]),
    )
    rec_id = res.json()["id"]
    assert _income_months(solo["db"], solo["ws"].id) == {date.today().strftime("%Y-%m")}

    res = client.put(
        f"/api/v1/workspaces/{solo['ws'].id}/recurring-income/{rec_id}",
        json={"start_date": _shift_month(hoje, -2).isoformat()},
        params={"materialize": "past"},
        headers=_headers(solo["user"]),
    )
    assert res.status_code == 200, res.text
    assert len(_income_months(solo["db"], solo["ws"].id)) == 3  # 2 anteriores + corrente


# --- Categoria no modelo de despesa recorrente ------------------------------

def test_categoria_do_modelo_vai_para_o_lancamento(solo):
    """Sem isso a despesa fixa nasce sem categoria e some dos gráficos."""
    ws, user = solo["ws"], solo["user"]
    cat_id = client.post(
        f"/api/v1/workspaces/{ws.id}/categories",
        json={"name": "Moradia"},
        headers=_headers(user),
    ).json()["id"]

    res = client.post(
        f"/api/v1/workspaces/{ws.id}/recurring",
        json={
            "title": "Aluguel",
            "base_amount": "1200.00",
            "day_of_month": 1,
            "category_id": cat_id,
        },
        headers=_headers(user),
    )
    assert res.status_code == 200, res.text
    assert res.json()["category_id"] == cat_id

    tx = solo["db"].exec(
        select(Transaction).where(Transaction.workspace_id == ws.id)
    ).one()
    item = solo["db"].exec(
        select(TransactionItem).where(TransactionItem.transaction_id == tx.id)
    ).one()
    # O relatório por categoria soma TransactionItem.category_id
    assert item.category_id == cat_id


def test_categoria_de_outro_workspace_rejeitada(solo, db_session):
    """Categoria de fora do workspace é barrada na borda — nada é criado."""
    ws, user = solo["ws"], solo["user"]
    outro = Workspace(name="Outro", created_by_user_id=user.id)
    db_session.add(outro)
    db_session.commit()
    db_session.refresh(outro)
    db_session.add(WorkspaceMembership(workspace_id=outro.id, user_id=user.id, role="owner"))
    db_session.commit()
    cat_id = client.post(
        f"/api/v1/workspaces/{outro.id}/categories",
        json={"name": "Alheia"},
        headers=_headers(user),
    ).json()["id"]

    res = client.post(
        f"/api/v1/workspaces/{ws.id}/recurring",
        json={"title": "Aluguel", "base_amount": "1200.00", "day_of_month": 1,
              "category_id": cat_id},
        headers=_headers(user),
    )
    assert res.status_code == 400
    assert db_session.exec(
        select(Transaction).where(Transaction.workspace_id == ws.id)
    ).all() == []


# --- Cartão de crédito no modelo recorrente ---------------------------------

def _create_card(ws_id: int, user: User) -> int:
    # Barra final obrigatória: sem ela o 307 do FastAPI descarta o Cookie → 401
    res = client.post(
        f"/api/v1/workspaces/{ws_id}/credit-cards/",
        json={"name": "Nubank", "limit": "5000.00", "closing_day": 20, "due_day": 28},
        headers=_headers(user),
    )
    assert res.status_code == 200, res.text
    return res.json()["id"]


def test_recorrente_no_cartao_entra_na_fatura(solo):
    """Assinatura no cartão precisa cair num statement — senão aparece no extrato
    mas some da fatura e do limite comprometido."""
    ws, user = solo["ws"], solo["user"]
    card_id = _create_card(ws.id, user)

    res = client.post(
        f"/api/v1/workspaces/{ws.id}/recurring",
        json={"title": "Streaming", "base_amount": "39.90", "day_of_month": 5,
              "payment_method": "credit_card", "credit_card_id": card_id},
        headers=_headers(user),
    )
    assert res.status_code == 200, res.text
    assert res.json()["credit_card_id"] == card_id

    tx = solo["db"].exec(select(Transaction).where(Transaction.workspace_id == ws.id)).one()
    assert tx.credit_card_id == card_id
    assert tx.statement_id is not None

    stmt = solo["db"].get(CardStatement, tx.statement_id)
    assert stmt.card_id == card_id


def test_cartao_sem_credito_rejeitado(solo):
    """Pix com cartão preso rotearia para uma fatura sem ter sido comprado nela."""
    ws, user = solo["ws"], solo["user"]
    card_id = _create_card(ws.id, user)

    res = client.post(
        f"/api/v1/workspaces/{ws.id}/recurring",
        json={"title": "Aluguel", "base_amount": "1200.00", "day_of_month": 5,
              "payment_method": "pix", "credit_card_id": card_id},
        headers=_headers(user),
    )
    assert res.status_code == 400
    assert solo["db"].exec(select(Transaction).where(Transaction.workspace_id == ws.id)).all() == []


def test_cartao_de_outro_workspace_rejeitado(solo, db_session):
    ws, user = solo["ws"], solo["user"]
    outro = Workspace(name="Outro WS", created_by_user_id=user.id)
    db_session.add(outro)
    db_session.commit()
    db_session.refresh(outro)
    db_session.add(WorkspaceMembership(workspace_id=outro.id, user_id=user.id, role="owner"))
    db_session.commit()
    alheio = _create_card(outro.id, user)

    res = client.post(
        f"/api/v1/workspaces/{ws.id}/recurring",
        json={"title": "Streaming", "base_amount": "39.90", "day_of_month": 5,
              "payment_method": "credit_card", "credit_card_id": alheio},
        headers=_headers(user),
    )
    assert res.status_code == 400


def test_trocar_o_cartao_re_roteia_instancias_nao_pagas(solo):
    ws, user = solo["ws"], solo["user"]
    card_a, card_b = _create_card(ws.id, user), _create_card(ws.id, user)

    rec_id = client.post(
        f"/api/v1/workspaces/{ws.id}/recurring",
        json={"title": "Streaming", "base_amount": "39.90", "day_of_month": 5,
              "payment_method": "credit_card", "credit_card_id": card_a},
        headers=_headers(user),
    ).json()["id"]

    res = client.put(
        f"/api/v1/workspaces/{ws.id}/recurring/{rec_id}",
        json={"credit_card_id": card_b},
        headers=_headers(user),
    )
    assert res.status_code == 200, res.text

    tx = solo["db"].exec(select(Transaction).where(Transaction.workspace_id == ws.id)).one()
    solo["db"].refresh(tx)
    assert tx.credit_card_id == card_b
    assert solo["db"].get(CardStatement, tx.statement_id).card_id == card_b


def test_recorrente_com_data_retroativa_lanca_historico(solo):
    """`past` na despesa: os meses anteriores nascem confirmados (já venceram)."""
    ws, user = solo["ws"], solo["user"]
    start = _shift_month(date.today().replace(day=1), -2)
    res = client.post(
        f"/api/v1/workspaces/{ws.id}/recurring",
        json={"title": "Internet", "base_amount": "100.00", "day_of_month": 1,
              "start_date": start.isoformat()},
        params={"materialize": "past"},
        headers=_headers(user),
    )
    assert res.status_code == 200, res.text

    txs = solo["db"].exec(select(Transaction).where(Transaction.workspace_id == ws.id)).all()
    assert {t.billing_month for t in txs} == {
        _shift_month(date.today().replace(day=1), -n).strftime("%Y-%m") for n in range(0, 3)
    }
