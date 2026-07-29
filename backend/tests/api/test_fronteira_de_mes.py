"""Uma única definição de "mês" — a virada do mês não pode separar as telas.

Havia DUAS: Relatórios/Início/Previsão recortavam por uma janela sobre
`transaction_date` (um INSTANTE gravado em UTC) e Lançamentos/Dívidas por
`billing_month` (o mês de calendário LOCAL que o cliente manda).

O formulário manda o instante real quando a data é hoje
(`new Date().toISOString()`) e o `billing_month` derivado da data local. Em
Brasília (UTC−3), uma despesa lançada às 22h do dia 31 de julho grava
`transaction_date = 2026-08-01T01:00Z` e `billing_month = "2026-07"`: ela
aparecia no extrato de julho (e com a data "31/07" na tela, porque o front
converte de volta para local) e nos Relatórios de AGOSTO. A mesma despesa, na
mesma sessão, em dois meses diferentes — sem nenhum sinal de que isso aconteceu.

O teste fixa exatamente esse instante e exige que as quatro leituras concordem.
"""
from datetime import datetime, UTC
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from app.core.jwt import create_access_token
from app.main import app
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMembership, WorkspaceRole

# 31/07/2026 22:00 em Brasília == 01/08/2026 01:00 UTC.
# É o que o formulário grava ao lançar "hoje" numa noite de fim de mês.
INSTANTE_UTC = datetime(2026, 8, 1, 1, 0, tzinfo=UTC)
MES_LOCAL = "2026-07"


@pytest.fixture(name="client")
def client_fixture(override_get_session):
    return TestClient(app)


@pytest.fixture(name="ws")
def ws_fixture(db_session: Session):
    user = User(name="Dono", email="fronteira@t.com", password_hash="h")
    db_session.add(user)
    workspace = Workspace(name="WS-fronteira", base_currency="BRL")
    db_session.add(workspace)
    db_session.flush()
    db_session.add(WorkspaceMembership(
        workspace_id=workspace.id, user_id=user.id, role=WorkspaceRole.owner
    ))
    db_session.commit()
    token = create_access_token(data={"sub": str(user.id)})
    return {
        "id": workspace.id,
        "user_id": user.id,
        "headers": {"Cookie": f"access_token={token}"},
    }


def _lancar(client, ws) -> int:
    res = client.post(
        f"/api/v1/workspaces/{ws['id']}/transactions/",
        json={
            "title": "Compra da virada",
            "total_amount": "150.00",
            # O instante já está no mês seguinte em UTC...
            "transaction_date": INSTANTE_UTC.isoformat(),
            # ...mas o mês de competência é o local, como o formulário manda
            "billing_month": MES_LOCAL,
            "payers": [{"user_id": ws["user_id"], "amount": "150.00"}],
            "splits": [{"user_id": ws["user_id"], "split_method": "equal", "input_value": "0"}],
        },
        headers=ws["headers"],
    )
    assert res.status_code == 200, res.text
    return res.json()["id"]


def test_despesa_da_virada_cai_no_mesmo_mes_em_todas_as_telas(client, ws):
    _lancar(client, ws)
    h = ws["headers"]
    base = f"/api/v1/workspaces/{ws['id']}"

    extrato = client.get(f"{base}/transactions/?month={MES_LOCAL}", headers=h)
    assert extrato.status_code == 200, extrato.text
    assert extrato.json()["total"] == 1
    assert Decimal(str(extrato.json()["total_amount"])) == Decimal("150.00")

    resumo = client.get(f"{base}/analytics/summary?month={MES_LOCAL}", headers=h)
    assert resumo.status_code == 200, resumo.text
    assert Decimal(resumo.json()["total_expenses"]) == Decimal("150.00")
    assert Decimal(resumo.json()["my_expenses"]) == Decimal("150.00")

    dividas = client.get(f"{base}/debts/monthly?month={MES_LOCAL}", headers=h)
    assert dividas.status_code == 200, dividas.text
    assert Decimal(str(dividas.json()["totals"]["total"])) == Decimal("150.00")

    previsao = client.get(f"{base}/analytics/forecast?month={MES_LOCAL}", headers=h)
    assert previsao.status_code == 200, previsao.text
    assert Decimal(previsao.json()["actual_spent"]) == Decimal("150.00")


def test_despesa_da_virada_nao_vaza_para_o_mes_seguinte(client, ws):
    """O outro lado da mesma moeda: agosto não pode herdar a despesa de julho."""
    _lancar(client, ws)
    h = ws["headers"]
    base = f"/api/v1/workspaces/{ws['id']}"

    resumo = client.get(f"{base}/analytics/summary?month=2026-08", headers=h)
    assert resumo.status_code == 200, resumo.text
    assert Decimal(resumo.json()["total_expenses"]) == Decimal("0")

    extrato = client.get(f"{base}/transactions/?month=2026-08", headers=h)
    assert extrato.json()["total"] == 0


def test_billing_month_e_derivado_quando_ausente(db_session: Session, ws):
    """Invariante estrutural: nenhuma Transaction nasce sem `billing_month`.

    A coluna é nullable e agora é o recorte de TODA agregação — uma linha sem ela
    sumiria de dívidas, relatórios, previsão e extrato de uma vez. Os caminhos de
    criação preenchem, mas isso é disciplina de quem escreve o código; o listener
    de mapper transforma em garantia.
    """
    from app.models.transaction import Transaction, TransactionStatus

    tx = Transaction(
        title="Sem competência",
        total_amount=Decimal("10.00"),
        currency="BRL",
        transaction_date=INSTANTE_UTC,
        workspace_id=ws["id"],
        status=TransactionStatus.confirmed,
    )
    assert tx.billing_month is None
    db_session.add(tx)
    db_session.commit()
    db_session.refresh(tx)
    # Sem valor explícito, deriva da data (UTC — é tudo que o servidor conhece)
    assert tx.billing_month == "2026-08"


def test_historico_de_6_meses_usa_o_mesmo_mes(client, ws):
    """As barras de Relatórios liam a mesma janela por instante — a despesa da
    virada aparecia na barra de agosto enquanto o resumo ao lado dizia julho."""
    _lancar(client, ws)
    relatorios = client.get(
        f"/api/v1/workspaces/{ws['id']}/analytics/reports?month={MES_LOCAL}",
        headers=ws["headers"],
    )
    assert relatorios.status_code == 200, relatorios.text
    barras = {b["month"]: Decimal(b["expenses"]) for b in relatorios.json()["monthly_history"]}
    assert barras[MES_LOCAL] == Decimal("150.00")
    assert "2026-08" not in barras  # a janela termina no mês pedido
