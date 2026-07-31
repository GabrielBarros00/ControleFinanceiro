"""Visão GLOBAL e pessoal: `/me/*` (ADR 0020).

O Início era a dashboard de um workspace disfarçada de tela pessoal — lia o
`currentWorkspaceId` do navegador e misturava "minha parte" com "toda a casa".
Quem participa de dois workspaces não tinha onde perguntar "quanto eu ganhei,
consumi e tenho a pagar NO TOTAL".

O foco aqui são os quatro números que o app confundia num só, e o de que mais
sentia falta: **saída de caixa** não existia em lugar nenhum do sistema.
"""
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlmodel import select

from app.core.jwt import create_access_token
from app.main import app
from app.models.user import User

client = TestClient(app)

MES = datetime.now(UTC).strftime("%Y-%m")
QUANDO = datetime.now(UTC).replace(day=10, hour=12, minute=0, second=0, microsecond=0)


def _h(user: User) -> dict:
    return {"Cookie": f"access_token={create_access_token({'sub': str(user.id)})}"}


def _registra(db_session, nome, email):
    res = client.post(
        "/api/v1/auth/register",
        json={"name": nome, "email": email, "password": "senha123"},
    )
    assert res.status_code == 200, res.text
    user = db_session.exec(select(User).where(User.email == email)).first()
    headers = _h(user)
    ws = client.get("/api/v1/workspaces/", headers=headers).json()[0]["id"]
    return {"user": user, "headers": headers, "ws": ws}


@pytest.fixture(name="duas_casas")
def duas_casas_fixture(db_session, override_get_session):
    """Uma pessoa com DOIS workspaces — o cenário que o Início não sabia somar."""
    a = _registra(db_session, "Gabriel", "global1@ov.com")
    ws2 = client.post(
        "/api/v1/workspaces/", json={"name": "Viagem"}, headers=a["headers"]
    ).json()["id"]
    return {**a, "ws2": ws2}


def _overview(ctx, **params):
    res = client.get(
        "/api/v1/me/overview",
        params={"month": MES, **params},
        headers=ctx["headers"],
    )
    assert res.status_code == 200, res.text
    return res.json()


def _despesa(ctx, workspace_id, total, pago_por_mim, minha_parte, titulo="Despesa"):
    """Cria despesa controlando SEPARADAMENTE quanto eu paguei e quanto consumi."""
    outro_id = ctx["user"].id  # workspace de um membro só: tudo é meu
    payload = {
        "title": titulo,
        "total_amount": total,
        "transaction_date": QUANDO.isoformat(),
        "billing_month": MES,
        "payers": [{"user_id": outro_id, "amount": pago_por_mim}],
        "splits": [
            {"user_id": outro_id, "split_method": "fixed", "input_value": minha_parte}
        ],
    }
    res = client.post(
        f"/api/v1/workspaces/{workspace_id}/transactions/",
        json=payload,
        headers=ctx["headers"],
    )
    assert res.status_code == 200, res.text
    return res.json()


# ---------------------------------------------------------------------------
# A soma dos workspaces
# ---------------------------------------------------------------------------

def test_renda_pessoal_entra_uma_vez_no_global(duas_casas):
    """A renda é da pessoa: some UMA vez, não uma por workspace."""
    client.post(
        "/api/v1/me/income/",
        json={"title": "Salário", "amount": "9000.00", "received_at": QUANDO.isoformat()},
        headers=duas_casas["headers"],
    )
    corpo = _overview(duas_casas)
    assert Decimal(str(corpo["income"])) == Decimal("9000.00")


def test_consumo_soma_os_dois_workspaces(duas_casas):
    _despesa(duas_casas, duas_casas["ws"], "300.00", "300.00", "300.00", "Casa")
    _despesa(duas_casas, duas_casas["ws2"], "200.00", "200.00", "200.00", "Viagem")

    corpo = _overview(duas_casas)
    assert Decimal(str(corpo["consumption"])) == Decimal("500.00")
    assert {w["workspace_name"] for w in corpo["by_workspace"]} >= {"Viagem"}


def test_resultado_e_renda_menos_consumo(duas_casas):
    """"Resultado do mês" — o número que o Início chamava de "Seu saldo"."""
    client.post(
        "/api/v1/me/income/",
        json={"title": "Salário", "amount": "5000.00", "received_at": QUANDO.isoformat()},
        headers=duas_casas["headers"],
    )
    _despesa(duas_casas, duas_casas["ws"], "1200.00", "1200.00", "1200.00")

    corpo = _overview(duas_casas)
    assert Decimal(str(corpo["result"])) == Decimal("3800.00")


# ---------------------------------------------------------------------------
# Consumo × saída de caixa — a distinção que não existia
# ---------------------------------------------------------------------------

def test_consumo_e_caixa_sao_numeros_diferentes(db_session, override_get_session):
    """Paguei 1000 numa despesa de que consumi 400: consumo e caixa divergem.

    Este é o número que faltava no app inteiro. Sem ele não há como dizer
    "adiantei 600 e tenho a receber" — só existia "gastei", que confundia as
    duas coisas.
    """
    dono = _registra(db_session, "Dono", "caixa_dono@ov.com")
    colega = _registra(db_session, "Colega", "caixa_colega@ov.com")

    # Colega entra no workspace do dono
    convite = client.post(
        f"/api/v1/workspaces/{dono['ws']}/invites",
        json={"email": "caixa_colega@ov.com", "role": "member"},
        headers=dono["headers"],
    )
    assert convite.status_code == 200, convite.text
    avisos = client.get("/api/v1/notifications", headers=colega["headers"]).json()
    token = next(n["invite_token"] for n in avisos["items"] if n.get("invite_token"))
    aceite = client.post(f"/api/v1/invites/accept/{token}", headers=colega["headers"])
    assert aceite.status_code == 200, aceite.text

    # Dono paga 1000; a divisão dá 400 para ele e 600 para o colega
    res = client.post(
        f"/api/v1/workspaces/{dono['ws']}/transactions/",
        json={
            "title": "Mercado",
            "total_amount": "1000.00",
            "transaction_date": QUANDO.isoformat(),
            "billing_month": MES,
            "payers": [{"user_id": dono["user"].id, "amount": "1000.00"}],
            "splits": [
                {"user_id": dono["user"].id, "split_method": "fixed", "input_value": "400.00"},
                {"user_id": colega["user"].id, "split_method": "fixed", "input_value": "600.00"},
            ],
        },
        headers=dono["headers"],
    )
    assert res.status_code == 200, res.text

    corpo = _overview(dono)
    assert Decimal(str(corpo["consumption"])) == Decimal("400.00"), "minha parte"
    assert Decimal(str(corpo["paid_in_transactions"])) == Decimal("1000.00"), (
        "o que assumi nos lançamentos"
    )
    # Despesa à vista: o que foi assumido E o caixa coincidem. Só divergem quando
    # há cartão no meio (ADR 0022) — ver tests/services/test_caixa_efetivo.py.
    assert Decimal(str(corpo["cash_out"])) == Decimal("1000.00"), "saiu do bolso agora"
    assert Decimal(str(corpo["to_receive"])) == Decimal("600.00"), "adiantei, tenho a receber"
    assert Decimal(str(corpo["to_pay"])) == Decimal("0.00")

    # E do outro lado, o colega deve
    do_colega = _overview(colega)
    assert Decimal(str(do_colega["consumption"])) == Decimal("600.00")
    assert Decimal(str(do_colega["paid_in_transactions"])) == Decimal("0.00")
    assert Decimal(str(do_colega["cash_out"])) == Decimal("0.00")
    assert Decimal(str(do_colega["to_pay"])) == Decimal("600.00")


def test_resultado_usa_consumo_e_nao_caixa(db_session, override_get_session):
    """Adiantar dinheiro por outro NÃO é gasto meu — é crédito a receber.

    Se o resultado descontasse a saída de caixa, quem paga a conta do restaurante
    e é reembolsado apareceria no vermelho todo mês.
    """
    dono = _registra(db_session, "Dono", "res_dono@ov.com")
    colega = _registra(db_session, "Colega", "res_colega@ov.com")
    client.post(
        f"/api/v1/workspaces/{dono['ws']}/invites",
        json={"email": "res_colega@ov.com", "role": "member"},
        headers=dono["headers"],
    )
    avisos = client.get("/api/v1/notifications", headers=colega["headers"]).json()
    token = next(n["invite_token"] for n in avisos["items"] if n.get("invite_token"))
    client.post(f"/api/v1/invites/accept/{token}", headers=colega["headers"])

    client.post(
        "/api/v1/me/income/",
        json={"title": "Salário", "amount": "5000.00", "received_at": QUANDO.isoformat()},
        headers=dono["headers"],
    )
    client.post(
        f"/api/v1/workspaces/{dono['ws']}/transactions/",
        json={
            "title": "Jantar",
            "total_amount": "1000.00",
            "transaction_date": QUANDO.isoformat(),
            "billing_month": MES,
            "payers": [{"user_id": dono["user"].id, "amount": "1000.00"}],
            "splits": [
                {"user_id": dono["user"].id, "split_method": "fixed", "input_value": "400.00"},
                {"user_id": colega["user"].id, "split_method": "fixed", "input_value": "600.00"},
            ],
        },
        headers=dono["headers"],
    )

    corpo = _overview(dono)
    # 5000 − 400 (consumo), NÃO 5000 − 1000 (caixa)
    assert Decimal(str(corpo["result"])) == Decimal("4600.00")


# ---------------------------------------------------------------------------
# Regras de agregação
# ---------------------------------------------------------------------------

def test_saldos_nao_se_compensam_entre_workspaces(db_session, override_get_session):
    """Dever numa casa e ter a receber noutra não é estar quitado: são pessoas e
    acordos diferentes. Por isso `by_workspace` mantém as pontas separadas."""
    dono = _registra(db_session, "Dono", "comp_dono@ov.com")
    corpo = _overview(dono)
    assert isinstance(corpo["by_workspace"], list)
    for linha in corpo["by_workspace"]:
        assert {"workspace_id", "workspace_name", "to_pay", "to_receive"} <= set(linha)


def test_overview_nao_exige_workspace_no_caminho(duas_casas):
    """A rota é pessoal: não há `workspace_id` para escolher errado."""
    res = client.get("/api/v1/me/overview", headers=duas_casas["headers"])
    assert res.status_code == 200


def test_overview_exige_sessao():
    assert client.get("/api/v1/me/overview").status_code == 401


def test_moeda_de_relatorio_e_do_usuario(duas_casas):
    """Somar workspaces com bases diferentes exige uma moeda de destino declarada
    (ADR 0006) — e ela é do usuário, não de um workspace."""
    corpo = _overview(duas_casas)
    assert corpo["currency"] == "BRL"

    res = client.patch(
        "/api/v1/me/report-currency",
        json={"report_currency": "USD"},
        headers=duas_casas["headers"],
    )
    assert res.status_code == 200
    assert res.json()["report_currency"] == "USD"
    assert _overview(duas_casas)["currency"] == "USD"


def test_atividade_recente_atravessa_workspaces(duas_casas):
    _despesa(duas_casas, duas_casas["ws"], "50.00", "50.00", "50.00", "Café")
    _despesa(duas_casas, duas_casas["ws2"], "80.00", "80.00", "80.00", "Hotel")

    res = client.get("/api/v1/me/activity", headers=duas_casas["headers"])
    assert res.status_code == 200
    titulos = {linha["title"] for linha in res.json()}
    assert {"Café", "Hotel"} <= titulos
    # E cada linha diz de qual casa veio, senão a lista global é ambígua
    assert all(linha["workspace_name"] for linha in res.json())


def test_atividade_nao_traz_lancamento_alheio(db_session, override_get_session):
    """A visão global usa a MESMA definição de envolvimento da política de
    privacidade (ADR 0018) — não é uma segunda porta para o dado do outro."""
    dono = _registra(db_session, "Dono", "at_dono@ov.com")
    colega = _registra(db_session, "Colega", "at_colega@ov.com")
    client.post(
        f"/api/v1/workspaces/{dono['ws']}/invites",
        json={"email": "at_colega@ov.com", "role": "member"},
        headers=dono["headers"],
    )
    avisos = client.get("/api/v1/notifications", headers=colega["headers"]).json()
    token = next(n["invite_token"] for n in avisos["items"] if n.get("invite_token"))
    client.post(f"/api/v1/invites/accept/{token}", headers=colega["headers"])

    _despesa(dono, dono["ws"], "300.00", "300.00", "300.00", "Terapia do dono")

    do_colega = client.get("/api/v1/me/activity", headers=colega["headers"]).json()
    assert "Terapia do dono" not in {linha["title"] for linha in do_colega}
