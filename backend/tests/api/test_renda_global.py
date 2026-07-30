"""Renda é da PESSOA e segue a pessoa entre workspaces (ADR 0019).

O sintoma relatado pelo dono: *"a renda não está global — criei um novo workspace
e não contou"*. A causa era `Income.workspace_id NOT NULL` + o `my_income` do
`ReportService` filtrando por workspace: o salário pertencia a um espaço de
colaboração, então cada workspace novo começava com receita zerada e exigia
recadastrar o mesmo salário — que depois divergia na primeira correção.

Este arquivo é o gate dessa correção. O teste central é
`test_salario_aparece_em_workspace_criado_depois`.
"""
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.core.jwt import create_access_token
from app.main import app
from app.models.income import Income
from app.models.user import User

client = TestClient(app)

MES = datetime.now(UTC).strftime("%Y-%m")
QUANDO = datetime.now(UTC).replace(day=15, hour=12, minute=0, second=0, microsecond=0)


def _h(user: User) -> dict:
    return {"Cookie": f"access_token={create_access_token({'sub': str(user.id)})}"}


@pytest.fixture(name="pessoa")
def pessoa_fixture(db_session, override_get_session):
    """Um usuário com o workspace pessoal que o registro cria."""
    res = client.post(
        "/api/v1/auth/register",
        json={"name": "Gabriel", "email": "global@renda.com", "password": "senha123"},
    )
    assert res.status_code == 200, res.text
    user = db_session.exec(
        __import__("sqlmodel").select(User).where(User.email == "global@renda.com")
    ).first()
    headers = _h(user)
    workspaces = client.get("/api/v1/workspaces/", headers=headers).json()
    return {"user": user, "headers": headers, "ws1": workspaces[0]["id"]}


def _cria_salario(pessoa, amount="9000.00", **extra):
    payload = {
        "title": "Salário",
        "amount": amount,
        "received_at": QUANDO.isoformat(),
        **extra,
    }
    res = client.post(
        f"/api/v1/workspaces/{pessoa['ws1']}/income/",
        json=payload,
        headers=pessoa["headers"],
    )
    assert res.status_code == 200, res.text
    return res.json()


def _novo_workspace(pessoa, nome="Casa nova"):
    res = client.post("/api/v1/workspaces/", json={"name": nome}, headers=pessoa["headers"])
    assert res.status_code == 200, res.text
    return res.json()["id"]


def _resumo(pessoa, workspace_id):
    res = client.get(
        f"/api/v1/workspaces/{workspace_id}/analytics/summary?month={MES}",
        headers=pessoa["headers"],
    )
    assert res.status_code == 200, res.text
    return res.json()


# ---------------------------------------------------------------------------
# O teste que prova a correção
# ---------------------------------------------------------------------------

def test_salario_aparece_em_workspace_criado_depois(pessoa):
    """Cadastro o salário UMA vez; crio um workspace novo; ele conta lá."""
    _cria_salario(pessoa)

    ws2 = _novo_workspace(pessoa)
    resumo = _resumo(pessoa, ws2)

    assert Decimal(str(resumo["my_income"])) == Decimal("9000.00"), (
        "o salário tem de seguir a pessoa para o workspace novo"
    )
    # E continua contando no workspace de origem — não é uma mudança de lugar
    assert Decimal(str(_resumo(pessoa, pessoa["ws1"])["my_income"])) == Decimal("9000.00")


def test_renda_pessoal_nasce_sem_workspace(pessoa, db_session):
    criada = _cria_salario(pessoa)
    assert criada["scope"] == "personal"
    assert criada["workspace_id"] is None
    assert db_session.get(Income, criada["id"]).workspace_id is None


def test_a_renda_aparece_na_listagem_do_workspace_novo(pessoa):
    criada = _cria_salario(pessoa)
    ws2 = _novo_workspace(pessoa)

    lista = client.get(
        f"/api/v1/workspaces/{ws2}/income/", headers=pessoa["headers"]
    ).json()
    assert criada["id"] in [i["id"] for i in lista], (
        "a tela de Rendas do workspace novo precisa mostrar o salário da pessoa"
    )


def test_editar_o_salario_vale_para_todos_os_workspaces(pessoa):
    """O ganho real de não ter cópias: corrigir num lugar corrige em todos."""
    criada = _cria_salario(pessoa)
    ws2 = _novo_workspace(pessoa)

    res = client.put(
        f"/api/v1/workspaces/{ws2}/income/{criada['id']}",
        json={"amount": "10000.00"},
        headers=pessoa["headers"],
    )
    assert res.status_code == 200, res.text

    for ws in (pessoa["ws1"], ws2):
        assert Decimal(str(_resumo(pessoa, ws)["my_income"])) == Decimal("10000.00")


# ---------------------------------------------------------------------------
# Renda pessoal NÃO é renda da casa até ser compartilhada
# ---------------------------------------------------------------------------

def test_renda_pessoal_nao_entra_no_total_da_casa(pessoa):
    """Global para MIM não significa público para a casa.

    Sem esta separação, tornar a renda global teria transformado "meu salário
    aparece em todo lugar" em "meu salário entra no orçamento de toda casa de que
    eu participo" — que é o vazamento que a Onda 1 fechou, reaberto por outra porta.
    """
    _cria_salario(pessoa)
    resumo = _resumo(pessoa, pessoa["ws1"])

    assert Decimal(str(resumo["my_income"])) == Decimal("9000.00")
    assert Decimal(str(resumo["total_income"])) == Decimal("0.00"), (
        "renda pessoal só compõe o total da casa depois de compartilhada"
    )


def test_compartilhar_faz_a_renda_entrar_no_total_da_casa(pessoa):
    criada = _cria_salario(pessoa)

    res = client.put(
        f"/api/v1/workspaces/{pessoa['ws1']}/income/{criada['id']}",
        json={"shared_with_workspace_ids": [pessoa["ws1"]]},
        headers=pessoa["headers"],
    )
    assert res.status_code == 200, res.text
    assert res.json()["shared_with_workspace_ids"] == [pessoa["ws1"]]

    resumo = _resumo(pessoa, pessoa["ws1"])
    assert Decimal(str(resumo["total_income"])) == Decimal("9000.00")


def test_descompartilhar_tira_do_total_da_casa(pessoa):
    """A lista enviada é o estado final — revogar é a mesma operação."""
    criada = _cria_salario(pessoa)
    ws = pessoa["ws1"]
    client.put(
        f"/api/v1/workspaces/{ws}/income/{criada['id']}",
        json={"shared_with_workspace_ids": [ws]},
        headers=pessoa["headers"],
    )
    assert Decimal(str(_resumo(pessoa, ws)["total_income"])) == Decimal("9000.00")

    client.put(
        f"/api/v1/workspaces/{ws}/income/{criada['id']}",
        json={"shared_with_workspace_ids": []},
        headers=pessoa["headers"],
    )
    assert Decimal(str(_resumo(pessoa, ws)["total_income"])) == Decimal("0.00")


def test_nao_compartilha_com_workspace_alheio(pessoa, db_session):
    """Escrita cruzada de workspace: mandar um id arbitrário no corpo faria minha
    renda aparecer no orçamento da casa de um desconhecido."""
    from app.models.workspace import Workspace

    alheio = Workspace(name="Casa de outro", base_currency="BRL")
    db_session.add(alheio)
    db_session.commit()
    db_session.refresh(alheio)

    criada = _cria_salario(pessoa)
    res = client.put(
        f"/api/v1/workspaces/{pessoa['ws1']}/income/{criada['id']}",
        json={"shared_with_workspace_ids": [alheio.id]},
        headers=pessoa["headers"],
    )
    assert res.status_code == 400


# ---------------------------------------------------------------------------
# Renda da casa continua existindo
# ---------------------------------------------------------------------------

def test_renda_da_casa_fica_no_workspace(pessoa):
    """`scope="workspace"` é a exceção deliberada: aluguel de imóvel comum
    pertence à casa e NÃO segue a pessoa para outro workspace."""
    criada = _cria_salario(pessoa, amount="2000.00", scope="workspace")
    assert criada["scope"] == "workspace"
    assert criada["workspace_id"] == pessoa["ws1"]

    # Entra no total da casa de origem, sem precisar compartilhar
    assert Decimal(str(_resumo(pessoa, pessoa["ws1"])["total_income"])) == Decimal("2000.00")

    # E não vaza para o workspace novo
    ws2 = _novo_workspace(pessoa)
    resumo2 = _resumo(pessoa, ws2)
    assert Decimal(str(resumo2["total_income"])) == Decimal("0.00")
    assert Decimal(str(resumo2["my_income"])) == Decimal("2000.00"), (
        "continua sendo renda DELE (Income.user_id), então o recorte pessoal a conta"
    )


def test_salario_recorrente_materializa_em_workspace_novo(pessoa, db_session):
    """O caminho que o dono usa de verdade: salário RECORRENTE.

    A materialização preguiçosa roda nas rotas de leitura e era escopada por
    workspace — num workspace recém-criado não há template nenhum, então o
    curto-circuito de `_tem_template_ativo` devolvia False e o salário global nunca
    era gerado ali. Este é o teste do sintoma exato relatado.
    """
    hoje = datetime.now(UTC)
    res = client.post(
        f"/api/v1/workspaces/{pessoa['ws1']}/recurring-income",
        json={
            "title": "Salário mensal",
            "base_amount": "9000.00",
            "frequency": "monthly",
            "day_of_month": hoje.day,
        },
        headers=pessoa["headers"],
    )
    assert res.status_code == 200, res.text
    assert res.json()["workspace_id"] is None, "salário recorrente nasce pessoal"

    ws2 = _novo_workspace(pessoa)
    resumo = _resumo(pessoa, ws2)
    assert Decimal(str(resumo["my_income"])) == Decimal("9000.00")
