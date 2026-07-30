import pytest
from datetime import datetime, date, UTC
from decimal import Decimal
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.main import app
from app.core.jwt import create_access_token
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMembership
from app.models.transaction import Transaction
from app.models.income import Income
from app.models.financing import AmortizationInstallment

client = TestClient(app)


def _headers(user: User) -> dict:
    return {"Cookie": f"access_token={create_access_token({'sub': str(user.id)})}"}


@pytest.fixture
def ws_team(db_session: Session, override_get_session):
    users = {}
    for key, role in [("owner", "owner"), ("admin", "admin"), ("member", "member"), ("member2", "member")]:
        u = User(name=key, email=f"{key}@p3.com", password_hash="hash")
        db_session.add(u)
        db_session.commit()
        db_session.refresh(u)
        users[key] = u

    ws = Workspace(name="P3 WS", created_by_user_id=users["owner"].id)
    db_session.add(ws)
    db_session.commit()
    db_session.refresh(ws)

    for key, role in [("owner", "owner"), ("admin", "admin"), ("member", "member"), ("member2", "member")]:
        db_session.add(WorkspaceMembership(workspace_id=ws.id, user_id=users[key].id, role=role))
    db_session.commit()

    return {"ws": ws, "users": users, "db": db_session}


def _create_tx_via_api(ws_id: int, user: User, title="Compra", amount="100.00"):
    payload = {
        "title": title,
        "total_amount": amount,
        "transaction_date": datetime.now(UTC).isoformat(),
        "payers": [{"user_id": user.id, "amount": amount}],
        "splits": [{"user_id": user.id, "split_method": "equal", "input_value": "100"}],
    }
    res = client.post(f"/api/v1/workspaces/{ws_id}/transactions/", json=payload, headers=_headers(user))
    assert res.status_code == 200, res.text
    return res.json()


# --- Transaction DELETE (soft) ---

def test_member_deletes_own_transaction(ws_team):
    ws, users, db = ws_team["ws"], ws_team["users"], ws_team["db"]
    tx = _create_tx_via_api(ws.id, users["member"])

    res = client.delete(f"/api/v1/workspaces/{ws.id}/transactions/{tx['id']}", headers=_headers(users["member"]))
    assert res.status_code == 200

    db_tx = db.get(Transaction, tx["id"])
    assert db_tx.deleted_at is not None  # soft delete

    # Some da listagem
    res = client.get(f"/api/v1/workspaces/{ws.id}/transactions/", headers=_headers(users["member"]))
    assert all(t["id"] != tx["id"] for t in res.json()["items"])


def test_member_cannot_delete_others_transaction(ws_team):
    """404, não 403 (ADR 0018): o lançamento de outro member, que não envolve
    quem pede, é INVISÍVEL — e um 403 confirmaria que ele existe naquele id."""
    ws, users = ws_team["ws"], ws_team["users"]
    tx = _create_tx_via_api(ws.id, users["member"])
    res = client.delete(f"/api/v1/workspaces/{ws.id}/transactions/{tx['id']}", headers=_headers(users["member2"]))
    assert res.status_code == 404
    # E não aparece na listagem dele, que é o vazamento de fato
    lista = client.get(
        f"/api/v1/workspaces/{ws.id}/transactions/", headers=_headers(users["member2"])
    ).json()
    assert tx["id"] not in [t["id"] for t in lista["items"]]


def test_admin_can_delete_any_transaction(ws_team):
    ws, users = ws_team["ws"], ws_team["users"]
    tx = _create_tx_via_api(ws.id, users["member"])
    res = client.delete(f"/api/v1/workspaces/{ws.id}/transactions/{tx['id']}", headers=_headers(users["admin"]))
    assert res.status_code == 200


def test_deleted_transaction_out_of_debts(ws_team):
    ws, users = ws_team["ws"], ws_team["users"]
    # member paga 100, split igual entre member e member2 → member2 deve 50
    payload = {
        "title": "Jantar",
        "total_amount": "100.00",
        "transaction_date": datetime.now(UTC).isoformat(),
        "payers": [{"user_id": users["member"].id, "amount": "100.00"}],
        "splits": [
            {"user_id": users["member"].id, "split_method": "equal", "input_value": "50"},
            {"user_id": users["member2"].id, "split_method": "equal", "input_value": "50"},
        ],
    }
    res = client.post(f"/api/v1/workspaces/{ws.id}/transactions/", json=payload, headers=_headers(users["member"]))
    tx_id = res.json()["id"]

    res = client.get(f"/api/v1/workspaces/{ws.id}/debts", headers=_headers(users["member"]))
    assert len(res.json()) == 1

    client.delete(f"/api/v1/workspaces/{ws.id}/transactions/{tx_id}", headers=_headers(users["member"]))
    res = client.get(f"/api/v1/workspaces/{ws.id}/debts", headers=_headers(users["member"]))
    assert res.json() == []


# --- Income PUT/DELETE ---

def test_income_update_and_delete(ws_team):
    ws, users, db = ws_team["ws"], ws_team["users"], ws_team["db"]
    res = client.post(
        f"/api/v1/workspaces/{ws.id}/income/",
        json={"title": "Salário", "amount": "5000", "received_at": datetime.now(UTC).isoformat()},
        headers=_headers(users["member"]),
    )
    income_id = res.json()["id"]

    # Outro member não altera renda alheia — e nem sabe que ela existe (ADR 0018):
    # salário é o dado mais sensível do sistema, então responde 404
    res = client.put(
        f"/api/v1/workspaces/{ws.id}/income/{income_id}",
        json={"amount": "1"},
        headers=_headers(users["member2"]),
    )
    assert res.status_code == 404

    # Nem na listagem
    alheia = client.get(
        f"/api/v1/workspaces/{ws.id}/income/", headers=_headers(users["member2"])
    ).json()
    assert income_id not in [i["id"] for i in alheia]

    # Dono altera
    res = client.put(
        f"/api/v1/workspaces/{ws.id}/income/{income_id}",
        json={"amount": "6000"},
        headers=_headers(users["member"]),
    )
    assert res.status_code == 200
    assert Decimal(str(res.json()["amount"])) == Decimal("6000")

    # Admin NÃO manda em renda pessoal alheia (ADR 0019). Renda pessoal não
    # pertence ao workspace — o admin administra a casa, não o salário de quem
    # mora nela. Antes admin+ excluía qualquer renda, porque toda renda era do
    # workspace.
    res = client.delete(
        f"/api/v1/workspaces/{ws.id}/income/{income_id}", headers=_headers(users["admin"])
    )
    assert res.status_code == 404
    assert db.get(Income, income_id).deleted_at is None

    # O dono exclui a própria (soft)
    res = client.delete(
        f"/api/v1/workspaces/{ws.id}/income/{income_id}", headers=_headers(users["member"])
    )
    assert res.status_code == 200
    assert db.get(Income, income_id).deleted_at is not None


def test_admin_administra_renda_da_casa(ws_team):
    """A contrapartida: renda DA CASA (`scope="workspace"`) é do workspace, e aí o
    admin manda mesmo — é o aluguel do imóvel comum, não o salário de ninguém."""
    ws, users, db = ws_team["ws"], ws_team["users"], ws_team["db"]
    res = client.post(
        f"/api/v1/workspaces/{ws.id}/income/",
        json={
            "title": "Aluguel do imóvel",
            "amount": "2000",
            "received_at": datetime.now(UTC).isoformat(),
            "scope": "workspace",
        },
        headers=_headers(users["member"]),
    )
    assert res.status_code == 200
    assert res.json()["scope"] == "workspace"
    income_id = res.json()["id"]

    res = client.delete(
        f"/api/v1/workspaces/{ws.id}/income/{income_id}", headers=_headers(users["admin"])
    )
    assert res.status_code == 200
    assert db.get(Income, income_id).deleted_at is not None


# --- Credit cards PUT/DELETE + statements ---

def test_credit_card_update_delete_and_statements(ws_team):
    ws, users = ws_team["ws"], ws_team["users"]
    res = client.post(
        f"/api/v1/workspaces/{ws.id}/credit-cards/",
        json={"name": "Nubank", "limit": "3000", "closing_day": 10, "due_day": 20},
        headers=_headers(users["member"]),
    )
    card_id = res.json()["id"]

    res = client.put(
        f"/api/v1/workspaces/{ws.id}/credit-cards/{card_id}",
        json={"limit": "5000"},
        headers=_headers(users["member"]),
    )
    assert res.status_code == 200

    # Transação no cartão gera fatura automaticamente
    payload = {
        "title": "Streaming",
        "total_amount": "50.00",
        "transaction_date": datetime.now(UTC).isoformat(),
        "credit_card_id": card_id,
        "payers": [{"user_id": users["member"].id, "amount": "50.00"}],
        "splits": [{"user_id": users["member"].id, "split_method": "equal", "input_value": "100"}],
    }
    res = client.post(f"/api/v1/workspaces/{ws.id}/transactions/", json=payload, headers=_headers(users["member"]))
    assert res.status_code == 200

    res = client.get(f"/api/v1/workspaces/{ws.id}/credit-cards/{card_id}/statements", headers=_headers(users["member"]))
    assert res.status_code == 200
    statements = res.json()
    assert len(statements) == 1
    assert Decimal(str(statements[0]["computed_total"])) == Decimal("50.00")

    stmt_id = statements[0]["id"]
    res = client.get(
        f"/api/v1/workspaces/{ws.id}/credit-cards/{card_id}/statements/{stmt_id}",
        headers=_headers(users["member"]),
    )
    assert res.status_code == 200
    assert len(res.json()["transactions"]) == 1

    # Fatura em aberto trava a exclusão: o cartão sairia da tela deixando uma
    # dívida sem nenhum caminho para ser quitada (fechar/pagar exigem cartão vivo)
    res = client.delete(f"/api/v1/workspaces/{ws.id}/credit-cards/{card_id}", headers=_headers(users["member"]))
    assert res.status_code == 409
    assert "em aberto" in res.json()["error"]["message"]

    # Quitada a fatura, o delete soft passa e o cartão some da listagem
    client.post(
        f"/api/v1/workspaces/{ws.id}/credit-cards/{card_id}/statements/{stmt_id}/close",
        headers=_headers(users["member"]),
    )
    client.post(
        f"/api/v1/workspaces/{ws.id}/credit-cards/{card_id}/statements/{stmt_id}/pay",
        json={},
        headers=_headers(users["member"]),
    )
    res = client.delete(f"/api/v1/workspaces/{ws.id}/credit-cards/{card_id}", headers=_headers(users["member"]))
    assert res.status_code == 200
    res = client.get(f"/api/v1/workspaces/{ws.id}/credit-cards/", headers=_headers(users["member"]))
    assert all(c["id"] != card_id for c in res.json())


# --- Financing ---

def test_financing_full_flow(ws_team):
    ws, users, db = ws_team["ws"], ws_team["users"], ws_team["db"]
    res = client.post(
        f"/api/v1/workspaces/{ws.id}/financing",
        json={
            "title": "Carro",
            "total_amount": "12000",
            "interest_rate": "0.01",
            "start_date": str(date.today()),
            "installments_count": 12,
            "method": "SAC",
        },
        headers=_headers(users["member"]),
    )
    assert res.status_code == 200, res.text
    fin_id = res.json()["id"]

    # Cronograma persistido com 12 parcelas
    res = client.get(f"/api/v1/workspaces/{ws.id}/financing/{fin_id}/schedule", headers=_headers(users["member"]))
    assert res.status_code == 200
    schedule = res.json()
    assert len(schedule) == 12
    assert Decimal(str(schedule[0]["principal_amount"])) == Decimal("1000.00")
    assert Decimal(str(schedule[-1]["remaining_balance"])) == Decimal("0.00")

    # Simulação de quitação antecipada
    res = client.post(
        f"/api/v1/workspaces/{ws.id}/financing/{fin_id}/early-settlement",
        json={},
        headers=_headers(users["member"]),
    )
    assert res.status_code == 200
    sim = res.json()
    assert Decimal(str(sim["total_to_pay"])) < Decimal(str(sim["original_value"]))
    assert Decimal(str(sim["savings"])) > 0

    # Pagar uma parcela
    res = client.post(
        f"/api/v1/workspaces/{ws.id}/financing/{fin_id}/installments/1/pay",
        headers=_headers(users["member"]),
    )
    assert res.status_code == 200
    inst = db.exec(select(AmortizationInstallment).where(
        AmortizationInstallment.financing_id == fin_id,
        AmortizationInstallment.installment_number == 1,
    )).first()
    assert inst.is_paid is True

    # Pagar de novo → 400
    res = client.post(
        f"/api/v1/workspaces/{ws.id}/financing/{fin_id}/installments/1/pay",
        headers=_headers(users["member"]),
    )
    assert res.status_code == 400

    # Delete soft
    res = client.delete(f"/api/v1/workspaces/{ws.id}/financing/{fin_id}", headers=_headers(users["member"]))
    assert res.status_code == 200
    res = client.get(f"/api/v1/workspaces/{ws.id}/financing", headers=_headers(users["member"]))
    assert res.json() == []


def test_financing_price_settles_when_all_paid(ws_team):
    ws, users = ws_team["ws"], ws_team["users"]
    res = client.post(
        f"/api/v1/workspaces/{ws.id}/financing",
        json={
            "title": "Notebook",
            "total_amount": "3000",
            "interest_rate": "0.02",
            "start_date": str(date.today()),
            "installments_count": 2,
            "method": "PRICE",
        },
        headers=_headers(users["member"]),
    )
    fin_id = res.json()["id"]

    for n in (1, 2):
        res = client.post(
            f"/api/v1/workspaces/{ws.id}/financing/{fin_id}/installments/{n}/pay",
            headers=_headers(users["member"]),
        )
        assert res.status_code == 200

    res = client.get(f"/api/v1/workspaces/{ws.id}/financing/{fin_id}", headers=_headers(users["member"]))
    assert res.json()["status"] == "settled"


# --- Categorias ---

def test_workspace_creation_seeds_default_categories(db_session, override_get_session):
    u = User(name="Cat", email="cat@p3.com", password_hash="hash")
    db_session.add(u)
    db_session.commit()
    db_session.refresh(u)

    res = client.post("/api/v1/workspaces/", json={"name": "Casa"}, headers=_headers(u))
    ws_id = res.json()["id"]

    res = client.get(f"/api/v1/workspaces/{ws_id}/categories", headers=_headers(u))
    assert res.status_code == 200
    names = [c["name"] for c in res.json()]
    assert "Alimentação" in names
    assert len(names) == 9


def test_category_crud_and_isolation(ws_team):
    ws, users, db = ws_team["ws"], ws_team["users"], ws_team["db"]
    res = client.post(
        f"/api/v1/workspaces/{ws.id}/categories",
        json={"name": "Pets", "color": "#000000"},
        headers=_headers(users["member"]),
    )
    assert res.status_code == 200
    cat_id = res.json()["id"]

    res = client.put(
        f"/api/v1/workspaces/{ws.id}/categories/{cat_id}",
        json={"name": "Animais"},
        headers=_headers(users["member"]),
    )
    assert res.json()["name"] == "Animais"

    # Outro workspace não enxerga/edita
    other_ws = Workspace(name="Outro", created_by_user_id=users["owner"].id)
    db.add(other_ws)
    db.commit()
    db.refresh(other_ws)
    db.add(WorkspaceMembership(workspace_id=other_ws.id, user_id=users["owner"].id, role="owner"))
    db.commit()
    res = client.put(
        f"/api/v1/workspaces/{other_ws.id}/categories/{cat_id}",
        json={"name": "Hack"},
        headers=_headers(users["owner"]),
    )
    assert res.status_code == 404

    res = client.delete(f"/api/v1/workspaces/{ws.id}/categories/{cat_id}", headers=_headers(users["member"]))
    assert res.status_code == 200
    res = client.get(f"/api/v1/workspaces/{ws.id}/categories", headers=_headers(users["member"]))
    assert all(c["id"] != cat_id for c in res.json())


# --- Estimates PUT ---

def test_estimate_update(ws_team):
    ws, users = ws_team["ws"], ws_team["users"]
    res = client.post(
        f"/api/v1/workspaces/{ws.id}/analytics/estimates",
        json={"category": "Geral", "amount": "2000", "month": "2026-07"},
        headers=_headers(users["member"]),
    )
    est_id = res.json()["id"]

    res = client.put(
        f"/api/v1/workspaces/{ws.id}/analytics/estimates/{est_id}",
        json={"category": "Geral", "amount": "2500", "month": "2026-07"},
        headers=_headers(users["member"]),
    )
    assert res.status_code == 200
    assert Decimal(str(res.json()["amount"])) == Decimal("2500")


# --- Workspace PUT/DELETE ---

def test_workspace_update_requires_admin(ws_team):
    ws, users = ws_team["ws"], ws_team["users"]
    res = client.put(
        f"/api/v1/workspaces/{ws.id}",
        json={"name": "Novo Nome"},
        headers=_headers(users["member"]),
    )
    assert res.status_code == 403

    res = client.put(
        f"/api/v1/workspaces/{ws.id}",
        json={"name": "Novo Nome"},
        headers=_headers(users["admin"]),
    )
    assert res.status_code == 200
    assert res.json()["name"] == "Novo Nome"


def test_workspace_delete_owner_only(ws_team):
    ws, users = ws_team["ws"], ws_team["users"]
    res = client.delete(f"/api/v1/workspaces/{ws.id}", headers=_headers(users["admin"]))
    assert res.status_code == 403

    res = client.delete(f"/api/v1/workspaces/{ws.id}", headers=_headers(users["owner"]))
    assert res.status_code == 200

    # Workspace soft-deleted: acesso vira 404 e some da listagem
    res = client.get(f"/api/v1/workspaces/{ws.id}", headers=_headers(users["owner"]))
    assert res.status_code == 404
    res = client.get("/api/v1/workspaces/", headers=_headers(users["owner"]))
    assert all(w["id"] != ws.id for w in res.json())


# --- Integridade: editar total_amount sincroniza payers/splits ---

def test_update_total_amount_syncs_payer_and_split(ws_team):
    ws, users = ws_team["ws"], ws_team["users"]
    tx = _create_tx_via_api(ws.id, users["member"], title="Ajustável", amount="100.00")

    res = client.put(
        f"/api/v1/workspaces/{ws.id}/transactions/{tx['id']}",
        json={"total_amount": "150.00"},
        headers=_headers(users["member"]),
    )
    assert res.status_code == 200
    body = res.json()
    assert Decimal(str(body["total_amount"])) == Decimal("150.00")
    assert Decimal(str(body["payers"][0]["amount"])) == Decimal("150.00")
    assert Decimal(str(body["splits"][0]["computed_amount"])) == Decimal("150.00")

    # Dívidas continuam zeradas (pagador == devedor, valores sincronizados)
    res = client.get(f"/api/v1/workspaces/{ws.id}/debts", headers=_headers(users["member"]))
    assert res.json() == []


def test_update_total_amount_rejected_for_multi_split(ws_team):
    ws, users = ws_team["ws"], ws_team["users"]
    payload = {
        "title": "Dividida",
        "total_amount": "100.00",
        "transaction_date": datetime.now(UTC).isoformat(),
        "payers": [{"user_id": users["member"].id, "amount": "100.00"}],
        "splits": [
            {"user_id": users["member"].id, "split_method": "equal", "input_value": "50"},
            {"user_id": users["member2"].id, "split_method": "equal", "input_value": "50"},
        ],
    }
    res = client.post(f"/api/v1/workspaces/{ws.id}/transactions/", json=payload, headers=_headers(users["member"]))
    tx_id = res.json()["id"]

    res = client.put(
        f"/api/v1/workspaces/{ws.id}/transactions/{tx_id}",
        json={"total_amount": "200.00"},
        headers=_headers(users["member"]),
    )
    assert res.status_code == 400


# --- Recorrência: excluir template com instâncias geradas ---

def test_delete_recurring_with_instances_detaches_them(ws_team):
    ws, users, db = ws_team["ws"], ws_team["users"], ws_team["db"]
    from datetime import date as date_cls
    from app.services.recurring_service import RecurringService

    res = client.post(
        f"/api/v1/workspaces/{ws.id}/recurring",
        json={"title": "Streaming", "base_amount": "39.90", "day_of_month": 5},
        headers=_headers(users["member"]),
    )
    template_id = res.json()["id"]

    today = date_cls.today()
    instance = RecurringService.get_or_create_monthly_instance(db, template_id, today.year, today.month)
    assert instance is not None

    # Excluir o template não pode violar a FK nem apagar a instância
    res = client.delete(f"/api/v1/workspaces/{ws.id}/recurring/{template_id}", headers=_headers(users["member"]))
    assert res.status_code == 200

    db.expire_all()
    db_tx = db.get(Transaction, instance.id)
    assert db_tx is not None  # instância preservada
    assert db_tx.recurring_expense_id is None  # desvinculada


# --- Cartões: mass assignment bloqueado ---

def test_create_card_ignores_injected_fields(ws_team):
    ws, users = ws_team["ws"], ws_team["users"]
    res = client.post(
        f"/api/v1/workspaces/{ws.id}/credit-cards/",
        json={
            "name": "Injetado", "limit": "1000", "closing_day": 5, "due_day": 15,
            "id": 99999, "deleted_at": "2020-01-01T00:00:00", "workspace_id": 12345,
        },
        headers=_headers(users["member"]),
    )
    assert res.status_code == 200
    body = res.json()
    assert body["id"] != 99999
    assert body["workspace_id"] == ws.id
    assert body["deleted_at"] is None


# --- Imports: arquivo não-UTF-8 responde 400 (nunca 500) ---

def test_csv_upload_invalid_encoding_rejected(ws_team):
    import io
    ws, users = ws_team["ws"], ws_team["users"]
    binary = bytes([0xFF, 0xFE, 0x00, 0x01]) * 10
    res = client.post(
        f"/api/v1/workspaces/{ws.id}/imports/parse",
        files={"file": ("binario.csv", io.BytesIO(binary), "text/csv")},
        data={"date_column": "date", "description_column": "desc", "amount_column": "amt"},
        headers=_headers(users["member"]),
    )
    assert res.status_code == 400


# --- Categoria na edição de transação (upsert de item) ---

def test_update_transaction_category_upserts_item(ws_team):
    ws, users, db = ws_team["ws"], ws_team["users"], ws_team["db"]
    from app.models.category import Category
    cat = Category(workspace_id=ws.id, name="Lazer")
    db.add(cat)
    db.commit()
    db.refresh(cat)

    tx = _create_tx_via_api(ws.id, users["member"], title="Cinema")
    assert tx["items"] == []

    # Define a categoria via PUT → item único criado
    res = client.put(
        f"/api/v1/workspaces/{ws.id}/transactions/{tx['id']}",
        json={"category_id": cat.id},
        headers=_headers(users["member"]),
    )
    assert res.status_code == 200
    assert len(res.json()["items"]) == 1
    assert res.json()["items"][0]["category_id"] == cat.id

    # Troca a categoria → item atualizado (não duplica)
    cat2 = Category(workspace_id=ws.id, name="Saúde")
    db.add(cat2)
    db.commit()
    db.refresh(cat2)
    res = client.put(
        f"/api/v1/workspaces/{ws.id}/transactions/{tx['id']}",
        json={"category_id": cat2.id},
        headers=_headers(users["member"]),
    )
    assert len(res.json()["items"]) == 1
    assert res.json()["items"][0]["category_id"] == cat2.id


def test_update_transaction_rejects_foreign_category(ws_team):
    ws, users, db = ws_team["ws"], ws_team["users"], ws_team["db"]
    from app.models.category import Category
    other_ws = Workspace(name="Outro WS Cat", created_by_user_id=users["owner"].id)
    db.add(other_ws)
    db.commit()
    db.refresh(other_ws)
    foreign_cat = Category(workspace_id=other_ws.id, name="Alheia")
    db.add(foreign_cat)
    db.commit()
    db.refresh(foreign_cat)

    tx = _create_tx_via_api(ws.id, users["member"], title="Teste Cat")
    res = client.put(
        f"/api/v1/workspaces/{ws.id}/transactions/{tx['id']}",
        json={"category_id": foreign_cat.id},
        headers=_headers(users["member"]),
    )
    assert res.status_code == 400


# --- Auditoria de login/logout ---

def test_login_and_logout_are_audited(db_session, override_get_session):
    from app.core.security import get_password_hash
    from app.models.audit import AuditLog, ActionType

    user = User(name="Auditado", email="auditado@p3.com", password_hash=get_password_hash("senha123"))
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)

    client.cookies.clear()
    res = client.post("/api/v1/auth/login", json={"email": "auditado@p3.com", "password": "senha123"})
    assert res.status_code == 200

    login_log = db_session.exec(select(AuditLog).where(
        AuditLog.action == ActionType.login, AuditLog.user_id == user.id
    )).first()
    assert login_log is not None

    res = client.post("/api/v1/auth/logout")
    assert res.status_code == 200
    logout_log = db_session.exec(select(AuditLog).where(
        AuditLog.action == ActionType.logout, AuditLog.user_id == user.id
    )).first()
    assert logout_log is not None
    client.cookies.clear()


# --- Upload limit (CSV) ---

def test_csv_upload_over_limit_rejected(ws_team, monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, "UPLOAD_MAX_BYTES", 100)

    ws, users = ws_team["ws"], ws_team["users"]
    big_content = "date,desc,amt\n" + ("2026-05-01,Lunch,10.00\n" * 50)  # > 100 bytes
    import io
    res = client.post(
        f"/api/v1/workspaces/{ws.id}/imports/parse",
        files={"file": ("big.csv", io.BytesIO(big_content.encode()), "text/csv")},
        data={"date_column": "date", "description_column": "desc", "amount_column": "amt"},
        headers=_headers(users["member"]),
    )
    assert res.status_code == 413


# --- Exchange rate (BCB PTAX) ---

def test_exchange_rate_endpoint(ws_team, monkeypatch):
    from app.services.currency_service import CurrencyService

    monkeypatch.setattr(CurrencyService, "get_rate_sync", lambda *a, **k: (Decimal("5.4321"), "ptax"))

    ws, users = ws_team["ws"], ws_team["users"]
    res = client.get(
        f"/api/v1/workspaces/{ws.id}/analytics/exchange-rate?from_currency=USD",
        headers=_headers(users["member"]),
    )
    assert res.status_code == 200
    assert res.json()["rate"] == "5.4321"
    assert res.json()["to_currency"] == "BRL"
    assert res.json()["source"] == "ptax"


def test_exchange_rate_unavailable_returns_422(ws_team, monkeypatch):
    from datetime import date as date_cls
    from app.services.currency_service import CurrencyService, ExchangeRateUnavailable

    def failing_get_rate(*a, **k):
        raise ExchangeRateUnavailable("USD", date_cls.today())

    monkeypatch.setattr(CurrencyService, "get_rate_sync", failing_get_rate)

    ws, users = ws_team["ws"], ws_team["users"]
    res = client.get(
        f"/api/v1/workspaces/{ws.id}/analytics/exchange-rate?from_currency=USD",
        headers=_headers(users["member"]),
    )
    assert res.status_code == 422


# --- PATCH /auth/me ---

def test_update_profile_name(ws_team):
    users = ws_team["users"]
    res = client.patch(
        "/api/v1/auth/me",
        json={"name": "Nome Novo"},
        headers=_headers(users["member"]),
    )
    assert res.status_code == 200
    assert res.json()["name"] == "Nome Novo"
