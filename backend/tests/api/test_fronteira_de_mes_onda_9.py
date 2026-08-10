"""O outro lado da virada do mês: a DATA CIVIL do dia 1º.

`test_fronteira_de_mes_onda_8.py` cobriu o instante que atravessa a meia-noite —
31/07 às 22h em São Paulo, gravado como `2026-08-01T01:00Z` — e exigiu que tudo
respondesse JULHO. Este arquivo cobre o caso simétrico, que passou inteiro pela
suíte de 2.348 testes: uma data de CALENDÁRIO ("todo dia 1") gravada como
instante.

Por que ninguém pegou. Havia duas famílias de teste e o bug morava entre elas:

- os testes de fronteira usavam sempre **01:00Z**, nunca 00:00Z — e com 01:00Z o
  comportamento certo é justamente cair no mês anterior, então eles passavam;
- os testes de recorrência no dia 1º existiam (`test_recurring_income.py`), mas
  conferiam o resultado por `select(Income)` ou por `billing_month` — a coluna
  que já estava CERTA. Nenhum deles pedia a renda de volta pelo filtro de mês,
  que é onde as duas fontes de verdade discordavam.

O sintoma: a renda de agosto tinha `billing_month = "2026-08"` gravado e mesmo
assim `/me/income?month=2026-08` vinha vazio, `/me/overview` mostrava renda zero
e o caixa não registrava a entrada. O dinheiro existia no banco e não existia em
nenhuma tela.
"""
from datetime import date, datetime, time
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.core.jwt import create_access_token
from app.domain.dates import civil_instant, local_day
from app.main import app
from app.models.income import Income
from app.models.recurring import (
    RecurrenceFrequency,
    RecurringExpense,
    RecurringIncome,
)
from app.models.transaction import Transaction
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMembership, WorkspaceRole
from app.services.recurring_service import (
    RecurringIncomeService,
    RecurringService,
)

client = TestClient(app)

AGOSTO = "2026-08"
DIA_1 = date(2026, 8, 1)
# Um dia qualquer de agosto, depois do dia 1º: é quando a materialização roda.
HOJE = date(2026, 8, 10)


@pytest.fixture(name="cena")
def cena_fixture(db_session: Session, override_get_session):
    user = User(name="Dona", email="onda9-dia1@t.com", password_hash="h")
    db_session.add(user)
    ws = Workspace(name="Casa", base_currency="BRL")
    db_session.add(ws)
    db_session.flush()
    db_session.add(
        WorkspaceMembership(workspace_id=ws.id, user_id=user.id, role=WorkspaceRole.owner)
    )
    db_session.commit()
    token = create_access_token(data={"sub": str(user.id)})
    return {
        "ws_id": ws.id,
        "user_id": user.id,
        "headers": {"Cookie": f"access_token={token}"},
    }


def test_civil_instant_e_local_day_sao_par():
    """O helper: escrever e ler uma data civil tem de devolver a mesma data.

    Meia-noite é o contraexemplo — é por isso que `civil_instant` existe.
    """
    instante = civil_instant(DIA_1)
    assert local_day(instante) == DIA_1
    # `.date()` também: meio-dia ±12h não troca de dia em fuso nenhum, então um
    # leitor que erre o helper ainda acerta a data.
    assert instante.date() == DIA_1
    # E a armadilha que isto substitui:
    assert local_day(datetime(2026, 8, 1, 0, 0)) == date(2026, 7, 31)


def test_renda_recorrente_do_dia_1_aparece_no_proprio_mes(db_session, cena):
    """O achado. Materializada no dia 1º, some do mês inteiro.

    Gravada à meia-noite, a renda de agosto era lida como 31 de julho e o filtro
    de `/me/income` (que recorta por `month_bounds_utc`) a devolvia em JULHO —
    enquanto o `billing_month` da mesma linha dizia agosto.
    """
    db_session.add(RecurringIncome(
        title="Salário", base_amount=Decimal("1000.00"), day_of_month=1,
        start_date=DIA_1, user_id=cena["user_id"],
    ))
    db_session.commit()

    assert RecurringIncomeService.generate_due_income(db_session, cena["user_id"], HOJE) == 1
    db_session.commit()

    inc = db_session.exec(select(Income).where(Income.user_id == cena["user_id"])).one()
    assert inc.billing_month == AGOSTO
    assert local_day(inc.received_at) == DIA_1, "a data lida tem de ser o dia 1º de agosto"

    agosto = client.get(f"/api/v1/me/income?month={AGOSTO}", headers=cena["headers"])
    assert agosto.status_code == 200
    assert [r["title"] for r in agosto.json()] == ["Salário"], (
        "a renda do dia 1º tem de estar no mês dela"
    )

    julho = client.get("/api/v1/me/income?month=2026-07", headers=cena["headers"])
    assert julho.json() == [], "e não pode vazar para o mês anterior"


def test_overview_e_caixa_do_dia_1_contam_a_renda(db_session, cena):
    """A mesma linha, pelas outras duas telas que a liam pelo instante."""
    db_session.add(RecurringIncome(
        title="Salário", base_amount=Decimal("1000.00"), day_of_month=1,
        start_date=DIA_1, user_id=cena["user_id"],
    ))
    db_session.commit()
    RecurringIncomeService.generate_due_income(db_session, cena["user_id"], HOJE)
    db_session.commit()

    overview = client.get(f"/api/v1/me/overview?month={AGOSTO}", headers=cena["headers"])
    assert overview.status_code == 200
    assert Decimal(overview.json()["income"]) == Decimal("1000.00")

    ledger = client.get(f"/api/v1/me/ledger?month={AGOSTO}", headers=cena["headers"])
    assert ledger.status_code == 200
    dados = ledger.json()
    assert Decimal(dados["cash_in"]) == Decimal("1000.00")
    assert [linha["occurred_on"] for linha in dados["entries"]] == ["2026-08-01"]


def test_despesa_recorrente_do_dia_1_fica_no_mes(db_session, cena):
    """O lado da despesa: `transaction_date` na mesma armadilha.

    Aqui `billing_month` mascarava metade do estrago — as agregações de despesa
    recortam por ele —, mas o extrato e o caixa leem o instante, e mostravam a
    conta do dia 1º de agosto como movimento de 31 de julho.
    """
    db_session.add(RecurringExpense(
        title="Aluguel", base_amount=Decimal("2000.00"), day_of_month=1,
        start_date=DIA_1, frequency=RecurrenceFrequency.monthly,
        workspace_id=cena["ws_id"], created_by_user_id=cena["user_id"],
    ))
    db_session.commit()

    assert RecurringService.generate_due_instances(db_session, cena["ws_id"], HOJE) == 1
    db_session.commit()

    tx = db_session.exec(
        select(Transaction).where(Transaction.workspace_id == cena["ws_id"])
    ).one()
    assert tx.billing_month == AGOSTO
    assert tx.occurrence_date == DIA_1
    assert local_day(tx.transaction_date) == DIA_1


def test_materializacao_do_dia_1_nao_duplica(db_session, cena):
    """O dedup tem de continuar reconhecendo a própria instância.

    Ele passou a comparar por `occurrence_date` (a data canônica) em vez de
    `transaction_date.date()`; se a chave escorregasse, a segunda passagem
    criaria uma cópia — e o mês do dono dobraria de tamanho sozinho.
    """
    db_session.add(RecurringExpense(
        title="Aluguel", base_amount=Decimal("2000.00"), day_of_month=1,
        start_date=DIA_1, frequency=RecurrenceFrequency.monthly,
        workspace_id=cena["ws_id"], created_by_user_id=cena["user_id"],
    ))
    db_session.commit()

    RecurringService.generate_due_instances(db_session, cena["ws_id"], HOJE)
    db_session.commit()
    assert RecurringService.generate_due_instances(db_session, cena["ws_id"], HOJE) == 0
    db_session.commit()

    linhas = db_session.exec(
        select(Transaction).where(Transaction.workspace_id == cena["ws_id"])
    ).all()
    assert len(linhas) == 1


def test_dedup_sobrevive_a_edicao_da_data_materializada(db_session, cena):
    """Editar a data da instância não pode fazer o dedup perdê-la de vista.

    Com a chave derivada de `transaction_date`, corrigir "paguei no dia 3, não no
    dia 1" fazia a materialização seguinte não reconhecer mais a linha e criar uma
    segunda ocorrência do mesmo mês. `occurrence_date` é imune: ela descreve a
    ocorrência, não o instante em que o dinheiro se moveu.
    """
    db_session.add(RecurringExpense(
        title="Aluguel", base_amount=Decimal("2000.00"), day_of_month=1,
        start_date=DIA_1, frequency=RecurrenceFrequency.monthly,
        workspace_id=cena["ws_id"], created_by_user_id=cena["user_id"],
    ))
    db_session.commit()
    RecurringService.generate_due_instances(db_session, cena["ws_id"], HOJE)
    db_session.commit()

    tx = db_session.exec(
        select(Transaction).where(Transaction.workspace_id == cena["ws_id"])
    ).one()
    tx.transaction_date = civil_instant(date(2026, 8, 3))
    db_session.add(tx)
    db_session.commit()

    assert RecurringService.generate_due_instances(db_session, cena["ws_id"], HOJE) == 0
    db_session.commit()
    linhas = db_session.exec(
        select(Transaction).where(Transaction.workspace_id == cena["ws_id"])
    ).all()
    assert len(linhas) == 1


def test_linha_de_csv_do_dia_1_entra_na_competencia_certa(db_session, cena):
    """O terceiro produtor de data civil: o extrato importado.

    `strptime` de um formato só-data devolve meia-noite; carimbá-la como UTC
    fazia "01/08" nascer com competência de julho.
    """
    csv = "data,descricao,valor\n2026-08-01,Mercado,150.00\n"
    parse = client.post(
        f"/api/v1/workspaces/{cena['ws_id']}/imports/parse",
        headers=cena["headers"],
        files={"file": ("extrato.csv", csv, "text/csv")},
        data={
            "date_column": "data", "description_column": "descricao",
            "amount_column": "valor", "date_format": "%Y-%m-%d",
        },
    )
    assert parse.status_code == 200, parse.text
    linhas = parse.json()["rows"]
    assert len(linhas) == 1

    commit = client.post(
        f"/api/v1/workspaces/{cena['ws_id']}/imports/commit",
        headers=cena["headers"],
        json={"filename": "extrato.csv", "rows": [{
            "line": linhas[0]["line"],
            "title": linhas[0]["title"],
            "total_amount": str(linhas[0]["total_amount"]),
            "transaction_date": linhas[0]["transaction_date"],
            "decision": "import",
        }]},
    )
    assert commit.status_code == 200, commit.text

    tx = db_session.exec(
        select(Transaction).where(Transaction.workspace_id == cena["ws_id"])
    ).one()
    assert tx.billing_month == AGOSTO
    assert local_day(tx.transaction_date) == DIA_1
    assert tx.transaction_date.time() != time.min, "data civil não pode ficar na meia-noite"


def test_commit_com_meia_noite_crua_nao_perde_o_mes(db_session, cena):
    """A rede do `/commit`: um cliente que monte o corpo à mão manda a data sem
    hora, que é como o extrato do banco a mostra."""
    commit = client.post(
        f"/api/v1/workspaces/{cena['ws_id']}/imports/commit",
        headers=cena["headers"],
        json={"filename": "manual.csv", "rows": [{
            "line": 2, "title": "Mercado", "total_amount": "150.00",
            "transaction_date": "2026-08-01T00:00:00", "decision": "import",
        }]},
    )
    assert commit.status_code == 200, commit.text

    tx = db_session.exec(
        select(Transaction).where(Transaction.workspace_id == cena["ws_id"])
    ).one()
    assert tx.billing_month == AGOSTO
    assert local_day(tx.transaction_date) == DIA_1
