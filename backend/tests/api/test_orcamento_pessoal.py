"""Orçamento com escopo: meta da CASA × meta PESSOAL de cada membro.

O Início comparava a despesa PESSOAL do usuário (soma dos splits dele) com o
orçamento da CASA (soma de TODOS os `MonthlyEstimate` do workspace). Num
workspace de duas pessoas com rateio igual, a barra marcava ~50% quando a casa
já tinha consumido 100% — e Relatórios, que compara casa com casa, mostrava
outro número para o MESMO orçamento.
"""
from datetime import datetime, UTC
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from app.core.jwt import create_access_token
from app.main import app
from app.models.category import Category
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMembership, WorkspaceRole

MES = "2026-07"
QUANDO = datetime(2026, 7, 10, 12, 0, tzinfo=UTC)


@pytest.fixture(name="client")
def client_fixture(override_get_session):
    return TestClient(app)


@pytest.fixture(name="casa")
def casa_fixture(db_session: Session):
    """Workspace com dois membros e uma categoria."""
    ana = User(name="Ana", email="ana@orc.com", password_hash="h")
    bia = User(name="Bia", email="bia@orc.com", password_hash="h")
    db_session.add_all([ana, bia])
    ws = Workspace(name="Casa", base_currency="BRL")
    db_session.add(ws)
    db_session.flush()
    for u, papel in ((ana, WorkspaceRole.owner), (bia, WorkspaceRole.member)):
        db_session.add(WorkspaceMembership(workspace_id=ws.id, user_id=u.id, role=papel))
    mercado = Category(name="Mercado", workspace_id=ws.id)
    db_session.add(mercado)
    db_session.commit()
    return {
        "ws": ws,
        "ana": ana,
        "bia": bia,
        "mercado": mercado,
        "h_ana": {"Cookie": f"access_token={create_access_token({'sub': str(ana.id)})}"},
        "h_bia": {"Cookie": f"access_token={create_access_token({'sub': str(bia.id)})}"},
    }


def _despesa_rateada(client, casa, total="1000.00", category_id=None):
    """Despesa paga pela Ana e dividida igualmente entre as duas."""
    ana, bia, ws = casa["ana"], casa["bia"], casa["ws"]
    payload = {
        "title": "Compra do mês",
        "total_amount": total,
        "transaction_date": QUANDO.isoformat(),
        "billing_month": MES,
        "payers": [{"user_id": ana.id, "amount": total}],
        "splits": [
            {"user_id": ana.id, "split_method": "equal", "input_value": "0"},
            {"user_id": bia.id, "split_method": "equal", "input_value": "0"},
        ],
    }
    if category_id:
        payload["items"] = [
            {"title": "Compra do mês", "amount": total, "category_id": category_id}
        ]
    res = client.post(
        f"/api/v1/workspaces/{ws.id}/transactions/", json=payload, headers=casa["h_ana"]
    )
    assert res.status_code == 200, res.text
    return res.json()


def _meta(client, casa, headers, *, scope, amount, category=None, category_id=None):
    return client.post(
        f"/api/v1/workspaces/{casa['ws'].id}/analytics/estimates",
        json={
            "category": category or "Geral",
            "category_id": category_id,
            "amount": amount,
            "month": MES,
            "scope": scope,
        },
        headers=headers,
    )


# --- escopo -----------------------------------------------------------------


def test_meta_da_casa_e_meta_pessoal_convivem(client, casa):
    """Mesma categoria, mesmo mês, escopos diferentes — a chave única inclui o dono."""
    da_casa = _meta(client, casa, casa["h_ana"], scope="workspace", amount="1000.00")
    assert da_casa.status_code == 200, da_casa.text
    assert da_casa.json()["scope"] == "workspace"
    assert da_casa.json()["owner_user_id"] is None

    minha = _meta(client, casa, casa["h_ana"], scope="personal", amount="500.00")
    assert minha.status_code == 200, minha.text
    assert minha.json()["scope"] == "personal"
    assert minha.json()["owner_user_id"] == casa["ana"].id

    # São duas linhas: definir a minha não sobrescreve a da casa
    assert da_casa.json()["id"] != minha.json()["id"]


def test_meta_pessoal_e_idempotente_por_dono(client, casa):
    primeira = _meta(client, casa, casa["h_ana"], scope="personal", amount="500.00")
    segunda = _meta(client, casa, casa["h_ana"], scope="personal", amount="700.00")
    assert primeira.json()["id"] == segunda.json()["id"]
    assert Decimal(segunda.json()["amount"]) == Decimal("700.00")


def test_meta_pessoal_de_outro_membro_nao_aparece(client, casa):
    """É o gasto que a pessoa planeja para si, não um número do workspace."""
    _meta(client, casa, casa["h_ana"], scope="personal", amount="500.00")
    _meta(client, casa, casa["h_bia"], scope="personal", amount="300.00")
    _meta(client, casa, casa["h_ana"], scope="workspace", amount="1000.00")

    lista = client.get(
        f"/api/v1/workspaces/{casa['ws'].id}/analytics/estimates?month={MES}",
        headers=casa["h_bia"],
    )
    assert lista.status_code == 200, lista.text
    donos = sorted(
        (e["owner_user_id"] for e in lista.json()), key=lambda v: (v is not None, v)
    )
    assert donos == [None, casa["bia"].id]  # a casa + a dela; nunca a da Ana


def test_meta_pessoal_de_outro_membro_nao_pode_ser_apagada(client, casa):
    """Nem por admin: papel manda no orçamento da casa, não na meta de alguém."""
    da_bia = _meta(client, casa, casa["h_bia"], scope="personal", amount="300.00")
    apagar = client.delete(
        f"/api/v1/workspaces/{casa['ws'].id}/analytics/estimates/{da_bia.json()['id']}",
        headers=casa["h_ana"],  # Ana é owner
    )
    assert apagar.status_code == 403, apagar.text


# --- os números que a tela lê -----------------------------------------------


def test_previsao_separa_meta_da_casa_da_meta_pessoal(client, casa):
    """`total_budget` continua sendo a casa (a previsão é projeção de CAIXA);
    `my_budget` é o que o Início compara com "sua despesa"."""
    _meta(client, casa, casa["h_ana"], scope="workspace", amount="1000.00")
    _meta(client, casa, casa["h_ana"], scope="personal", amount="500.00")
    _meta(client, casa, casa["h_bia"], scope="personal", amount="300.00")

    para_ana = client.get(
        f"/api/v1/workspaces/{casa['ws'].id}/analytics/forecast?month={MES}",
        headers=casa["h_ana"],
    ).json()
    assert Decimal(para_ana["total_budget"]) == Decimal("1000.00")
    assert Decimal(para_ana["my_budget"]) == Decimal("500.00")

    # Bia é `member` → involved_only (ADR 0018). A previsão é projeção de CAIXA DA
    # CASA inteira, então nada dela sai para quem não tem acesso completo: só a
    # meta PESSOAL, que é a que o Início compara com "sua despesa". `None` e não
    # zero — zero seria uma mentira aritmética.
    para_bia = client.get(
        f"/api/v1/workspaces/{casa['ws'].id}/analytics/forecast?month={MES}",
        headers=casa["h_bia"],
    ).json()
    assert para_bia["total_budget"] is None
    assert para_bia["actual_spent"] is None
    assert para_bia["projected_eom"] is None
    assert Decimal(para_bia["my_budget"]) == Decimal("300.00")

    # As DUAS respostas têm o mesmo conjunto de chaves — o que muda é o valor.
    # Esta asserção afirmava `projected_net is None`, um campo que a resposta de
    # acesso completo não devolve desde o ADR 0021 (renda saiu do workspace):
    # o teste pinava a existência de um vestígio, e era o único lugar que
    # notaria a divergência.
    assert set(para_bia) == set(para_ana), "a rota muda de formato conforme o acesso"


def test_minha_parte_por_categoria_fecha_com_minha_despesa(client, casa):
    """`my_categories` é o par de `categories` para a meta pessoal: a fatia do
    usuário, e não o valor cheio da casa."""
    _despesa_rateada(client, casa, total="1000.00", category_id=casa["mercado"].id)

    resumo = client.get(
        f"/api/v1/workspaces/{casa['ws'].id}/analytics/summary?month={MES}",
        headers=casa["h_ana"],
    ).json()

    assert Decimal(resumo["total_expenses"]) == Decimal("1000.00")
    assert Decimal(resumo["my_expenses"]) == Decimal("500.00")

    da_casa = {c["name"]: Decimal(c["value"]) for c in resumo["categories"]}
    minha = {c["name"]: Decimal(c["value"]) for c in resumo["my_categories"]}
    assert da_casa["Mercado"] == Decimal("1000.00")
    assert minha["Mercado"] == Decimal("500.00")
    # E a composição fecha com o total do próprio recorte
    assert sum(minha.values()) == Decimal(resumo["my_expenses"])


def test_minha_parte_sem_categoria_entra_como_sem_categoria(client, casa):
    _despesa_rateada(client, casa, total="1000.00")  # sem item/categoria

    resumo = client.get(
        f"/api/v1/workspaces/{casa['ws'].id}/analytics/summary?month={MES}",
        headers=casa["h_bia"],
    ).json()
    minha = {c["name"]: Decimal(c["value"]) for c in resumo["my_categories"]}
    assert minha == {"Sem categoria": Decimal("500.00")}


def test_minha_parte_por_item_usa_a_share_exata(client, casa):
    """No modo item a "minha parte da linha" é explícita — nada de rateio."""
    ana, bia, ws = casa["ana"], casa["bia"], casa["ws"]
    res = client.post(
        f"/api/v1/workspaces/{ws.id}/transactions/",
        json={
            "title": "Mercado dividido por item",
            "total_amount": "100.00",
            "transaction_date": QUANDO.isoformat(),
            "billing_month": MES,
            "split_mode": "item",
            "payers": [{"user_id": ana.id, "amount": "100.00"}],
            "splits": [],
            "items": [
                {
                    "title": "Só da Ana",
                    "amount": "70.00",
                    "category_id": casa["mercado"].id,
                    "shares": [{"user_id": ana.id, "split_method": "equal", "input_value": "0"}],
                },
                {
                    "title": "Só da Bia",
                    "amount": "30.00",
                    "category_id": casa["mercado"].id,
                    "shares": [{"user_id": bia.id, "split_method": "equal", "input_value": "0"}],
                },
            ],
        },
        headers=casa["h_ana"],
    )
    assert res.status_code == 200, res.text

    for headers, esperado in ((casa["h_ana"], "70.00"), (casa["h_bia"], "30.00")):
        resumo = client.get(
            f"/api/v1/workspaces/{ws.id}/analytics/summary?month={MES}", headers=headers
        ).json()
        minha = {c["name"]: Decimal(c["value"]) for c in resumo["my_categories"]}
        assert minha["Mercado"] == Decimal(esperado)
