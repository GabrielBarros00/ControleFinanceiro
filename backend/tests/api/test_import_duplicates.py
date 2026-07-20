"""Import CSV: marcação de possíveis duplicatas (data + valor + título)."""
import datetime
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.main import app
from app.models.transaction import Transaction

client = TestClient(app)


def test_parse_marks_duplicates(db_session: Session, setup_data, override_get_session):
    ws1, u1 = setup_data["ws1"], setup_data["u1"]

    db_session.add(Transaction(
        title="Uber",
        total_amount=Decimal("25.50"),
        transaction_date=datetime.datetime(2026, 5, 10, 14, 30),
        billing_month="2026-05",
        workspace_id=ws1.id,
        created_by_user_id=u1.id,
    ))
    db_session.commit()

    csv_content = (
        "data,descricao,valor\n"
        "2026-05-10,Uber,-25.50\n"
        "2026-05-11,Ifood,-30.00\n"
    )
    resp = client.post(
        f"/api/v1/workspaces/{ws1.id}/imports/parse",
        files={"file": ("extrato.csv", csv_content.encode("utf-8"), "text/csv")},
        data={
            "date_column": "data",
            "description_column": "descricao",
            "amount_column": "valor",
            "date_format": "%Y-%m-%d",
            "delimiter": ",",
            "decimal_separator": ".",
            "invert_amount": "true",
        },
        headers=setup_data["headers1"],
    )
    assert resp.status_code == 200, resp.text
    rows = resp.json()["rows"]
    assert len(rows) == 2

    by_title = {r["title"]: r for r in rows}
    assert by_title["Uber"]["duplicate"] is True
    assert by_title["Ifood"]["duplicate"] is False


def test_bulk_preenche_billing_month_e_reporta_motivos(
    db_session: Session, setup_data, override_get_session
):
    """IMP-001: sem billing_month a transação importada some do histórico
    filtrado por mês; linhas puladas trazem o motivo."""
    ws1 = setup_data["ws1"]

    resp = client.post(
        f"/api/v1/workspaces/{ws1.id}/transactions/bulk",
        json=[
            {"title": "Uber", "total_amount": "25.50", "transaction_date": "2026-05-10T14:30:00"},
            {"title": "Negativa", "total_amount": "-3.00", "transaction_date": "2026-05-10T14:30:00"},
            {"title": "Sem número", "total_amount": "abc", "transaction_date": "2026-05-10T14:30:00"},
        ],
        headers=setup_data["headers1"],
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["created"] == 1
    assert data["skipped"] == 2
    reasons = {d["title"]: d["reason"] for d in data["skipped_details"]}
    assert "positivo" in reasons["Negativa"]
    assert "número" in reasons["Sem número"]

    tx = db_session.exec(
        select(Transaction).where(Transaction.title == "Uber")
    ).first()
    assert tx.billing_month == "2026-05"

    # Aparece no histórico filtrado pelo mês
    resp = client.get(
        f"/api/v1/workspaces/{ws1.id}/transactions/?month=2026-05",
        headers=setup_data["headers1"],
    )
    titles = [t["title"] for t in resp.json()["items"]]
    assert "Uber" in titles
