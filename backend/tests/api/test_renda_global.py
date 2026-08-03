"""Renda é da PESSOA e segue a pessoa entre workspaces (ADR 0019 → ADR 0021).

O sintoma relatado pelo dono: *"a renda não está global — criei um novo workspace
e não contou"*. A causa era `Income.workspace_id NOT NULL` + o `my_income` do
`ReportService` filtrando por workspace: o salário pertencia a um espaço de
colaboração, então cada workspace novo começava com receita zerada e exigia
recadastrar o mesmo salário — que depois divergia na primeira correção.

**O requisito não mudou; o lugar de prová-lo mudou.** A Onda 4 tinha resolvido
metade: a renda virou global, mas continuou sendo cadastrada e exibida dentro do
workspace, e o resumo dele passou a devolver um `my_income` global ao lado de um
`my_expenses` local. Subtrair um do outro (`my_net`) produzia uma "sobra"
diferente e maior em cada workspace, cada uma ignorando o que a pessoa gastou nos
outros.

Na Onda 5 a renda saiu do workspace de vez: mora em `/me/income`, é expressa na
moeda de relatório do dono, e o resultado do mês existe num lugar só —
`/me/overview`, onde o denominador é o consumo somado de TODOS os workspaces.
Este arquivo é o gate dessa correção.
"""
from datetime import UTC, datetime, time
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.core.jwt import create_access_token
from app.domain.dates import today_local
from app.main import app
from app.models.income import Income
from app.models.user import User

client = TestClient(app)

# Mês de CALENDÁRIO LOCAL, não o do relógio UTC: em fuso negativo os dois
# discordam das 21h à meia-noite, e o teste pedia à API um mês em que a renda
# recém-criada — datada pelo calendário do usuário — ainda não existe.
MES = today_local().strftime("%Y-%m")
# Dia 15 do mês LOCAL, ao meio-dia UTC (= 9h em São Paulo, o mesmo dia nos dois
# calendários). Ancorar em `datetime.now(UTC)` colocava a renda no mês seguinte
# quando o teste rodava depois das 21h do último dia do mês.
QUANDO = datetime.combine(today_local().replace(day=15), time(12, 0), tzinfo=UTC)


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
    res = client.post("/api/v1/me/income", json=payload, headers=pessoa["headers"])
    assert res.status_code == 200, res.text
    return res.json()


def _novo_workspace(pessoa, nome="Casa nova"):
    res = client.post("/api/v1/workspaces/", json={"name": nome}, headers=pessoa["headers"])
    assert res.status_code == 200, res.text
    return res.json()["id"]


def _overview(pessoa):
    res = client.get(f"/api/v1/me/overview?month={MES}", headers=pessoa["headers"])
    assert res.status_code == 200, res.text
    return res.json()


def _resumo(pessoa, workspace_id):
    res = client.get(
        f"/api/v1/workspaces/{workspace_id}/analytics/summary?month={MES}",
        headers=pessoa["headers"],
    )
    assert res.status_code == 200, res.text
    return res.json()


def _lanca(pessoa, workspace_id, valor):
    res = client.post(
        f"/api/v1/workspaces/{workspace_id}/transactions/",
        json={
            "title": "Despesa",
            "total_amount": valor,
            "transaction_date": QUANDO.isoformat(),
            "payers": [{"user_id": pessoa["user"].id, "amount": valor}],
            "splits": [{
                "user_id": pessoa["user"].id,
                "split_method": "fixed",
                "input_value": valor,
            }],
        },
        headers=pessoa["headers"],
    )
    assert res.status_code == 200, res.text
    return res.json()


# ---------------------------------------------------------------------------
# O requisito do dono: cadastrar uma vez, valer em todo lugar
# ---------------------------------------------------------------------------

def test_salario_cadastrado_uma_vez_sobrevive_a_workspace_novo(pessoa):
    """Cadastro o salário UMA vez; crio um workspace novo; a renda continua lá.

    Antes o `my_income` do workspace novo vinha zerado e o dono precisava
    recadastrar o salário. Agora a pergunta "quanto eu ganhei" não passa por
    workspace nenhum, então criar um não muda a resposta.
    """
    _cria_salario(pessoa)
    assert Decimal(str(_overview(pessoa)["income"])) == Decimal("9000.00")

    _novo_workspace(pessoa)

    assert Decimal(str(_overview(pessoa)["income"])) == Decimal("9000.00"), (
        "criar um workspace não pode mexer na renda da pessoa"
    )


def test_renda_nao_pertence_a_workspace_nenhum(pessoa, db_session):
    criada = _cria_salario(pessoa)
    assert "workspace_id" not in criada, "renda não tem workspace (ADR 0021)"
    assert "scope" not in criada, "não existe mais renda 'da casa'"
    assert db_session.get(Income, criada["id"]).user_id == pessoa["user"].id


def test_a_renda_aparece_na_listagem_pessoal(pessoa):
    criada = _cria_salario(pessoa)
    lista = client.get("/api/v1/me/income", headers=pessoa["headers"]).json()
    assert criada["id"] in [i["id"] for i in lista]


def test_editar_o_salario_vale_em_todo_lugar(pessoa):
    """O ganho real de não ter cópias: corrigir num lugar corrige em todos."""
    criada = _cria_salario(pessoa)
    _novo_workspace(pessoa)

    res = client.put(
        f"/api/v1/me/income/{criada['id']}",
        json={"amount": "10000.00"},
        headers=pessoa["headers"],
    )
    assert res.status_code == 200, res.text
    assert Decimal(str(_overview(pessoa)["income"])) == Decimal("10000.00")


# ---------------------------------------------------------------------------
# O que a Onda 5 corrigiu: renda não entra em número de workspace
# ---------------------------------------------------------------------------

def test_resumo_do_workspace_nao_tem_renda_nem_resultado(pessoa):
    """A correção do "Sobra do mês" enganoso.

    `my_net` era `my_income` (global) − `my_expenses` (deste workspace). Com
    salário de 9.000 e 1.150 de despesa na Casa, o Painel anunciava 7.850 de
    sobra — ignorando os 500 gastos noutro workspace. Em um terceiro workspace o
    MESMO salário seria combinado com outro subconjunto de despesas e daria uma
    terceira "sobra". Nenhuma delas era o resultado da pessoa.
    """
    _cria_salario(pessoa)
    resumo = _resumo(pessoa, pessoa["ws1"])

    for campo in ("my_income", "my_net", "total_income", "net_savings"):
        assert campo not in resumo, (
            f"{campo} mistura escopo pessoal com o do workspace — ver ADR 0021"
        )


def test_o_resultado_desconta_o_gasto_de_todos_os_workspaces(pessoa):
    """O cenário exato do relatório de auditoria, com o número certo no fim.

    Renda 9.000; minha parte de 1.150 na Casa e 500 na outra. O resultado correto
    é 7.350 — e é o que `/me/overview` devolve, porque soma o consumo de TODOS os
    workspaces antes de subtrair.
    """
    _cria_salario(pessoa)
    ws2 = _novo_workspace(pessoa, "Viagem")
    _lanca(pessoa, pessoa["ws1"], "1150.00")
    _lanca(pessoa, ws2, "500.00")

    corpo = _overview(pessoa)
    assert Decimal(str(corpo["consumption"])) == Decimal("1650.00")
    assert Decimal(str(corpo["result"])) == Decimal("7350.00"), (
        "o resultado tem de descontar o gasto de TODOS os workspaces"
    )


def test_o_painel_do_workspace_fala_do_workspace(pessoa):
    """O que sobra no Painel depois da mudança: gasto da casa, minha parte, o que
    eu paguei e o acerto — números que só dependem deste workspace."""
    _cria_salario(pessoa)
    _lanca(pessoa, pessoa["ws1"], "1150.00")

    resumo = _resumo(pessoa, pessoa["ws1"])
    assert Decimal(str(resumo["total_expenses"])) == Decimal("1150.00")
    assert Decimal(str(resumo["my_expenses"])) == Decimal("1150.00")
    assert Decimal(str(resumo["paid_by_me"])) == Decimal("1150.00")
    assert Decimal(str(resumo["my_balance"])) == Decimal("0.00")


def test_renda_pessoal_nao_aparece_para_o_outro_membro(pessoa, db_session):
    """Global para MIM não significa público para a casa."""
    from app.models.workspace import WorkspaceMembership, WorkspaceRole

    _cria_salario(pessoa)
    outro = User(name="Outro", email="outro@renda.com", password_hash="h")
    db_session.add(outro)
    db_session.commit()
    db_session.refresh(outro)
    db_session.add(WorkspaceMembership(
        workspace_id=pessoa["ws1"], user_id=outro.id, role=WorkspaceRole.admin
    ))
    db_session.commit()

    lista = client.get("/api/v1/me/income", headers=_h(outro)).json()
    assert lista == [], "admin do workspace não vê o salário de quem participa"


# ---------------------------------------------------------------------------
# Recorrência
# ---------------------------------------------------------------------------

def test_salario_recorrente_materializa_sem_passar_por_workspace(pessoa):
    """O caminho que o dono usa de verdade: salário RECORRENTE.

    A materialização preguiçosa era escopada por workspace e rodava nas rotas de
    leitura DELE — num workspace recém-criado não havia template nenhum, o
    curto-circuito devolvia False e o salário global nunca era gerado ali. Agora
    ela roda na leitura de `/me/income`, que é onde a renda vive.
    """
    hoje = today_local()
    res = client.post(
        "/api/v1/me/recurring-income",
        json={
            "title": "Salário mensal",
            "base_amount": "9000.00",
            "frequency": "monthly",
            "day_of_month": hoje.day,
        },
        headers=pessoa["headers"],
    )
    assert res.status_code == 200, res.text

    lista = client.get("/api/v1/me/income", headers=pessoa["headers"]).json()
    assert [i["title"] for i in lista] == ["Salário mensal"]
    assert Decimal(str(_overview(pessoa)["income"])) == Decimal("9000.00")
