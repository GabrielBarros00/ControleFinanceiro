"""A recorrência pode ter fim (ADR 0030).

O caso que trouxe isto: mensalidade de faculdade paga por dez, doze anos. A
recorrência só tinha `start_date`, então ela virava uma série INFINITA — sem
"faltam 87 de 144", com a previsão do mês projetando o gasto para sempre, e com o
template gerando muito depois de a última parcela ter sido paga, até alguém
lembrar de desativá-lo à mão.

`end_date` é o teto que faltava, espelho exato do piso que já existia. Estes
testes fixam as três coisas que ele precisa fazer: **parar de gerar**, **contar**
e **valer nos dois caminhos de calendário** (preset e "a cada N") — aplicá-lo só
num deles daria uma mensalidade que respeita o fim quando é mensal e o ignora
quando é "a cada 2 meses".
"""
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.core.jwt import create_access_token
from app.main import app
from app.models.recurring import RecurrenceFrequency, RecurringExpense
from app.models.transaction import Transaction
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMembership, WorkspaceRole
from app.services.recurring_service import RecurringService

client = TestClient(app)


@pytest.fixture(name="cena")
def cena_fixture(db_session: Session, override_get_session):
    user = User(name="Dona", email="fim@t.com", password_hash="h")
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
        "db": db_session,
    }


def _modelo(**campos):
    """Template mínimo para o calendário — `occurrences_in_month` é duck typing."""
    base = dict(
        frequency=RecurrenceFrequency.monthly, interval=1, day_of_month=5,
        day_of_week=None, month_of_year=None,
        start_date=date(2026, 1, 5), end_date=None,
    )
    base.update(campos)
    return SimpleNamespace(**base)


# --- 1. O teto para de gerar, nos dois caminhos ----------------------------


def test_ocorrencia_depois_do_fim_nao_e_gerada(cena):
    modelo = _modelo(end_date=date(2026, 3, 5))
    assert RecurringService.occurrences_in_month(modelo, 2026, 3) == [date(2026, 3, 5)]
    assert RecurringService.occurrences_in_month(modelo, 2026, 4) == []


def test_o_teto_vale_no_a_cada_N_tambem(cena):
    """O caminho "a cada N" retorna ANTES do filtro do preset.

    Aplicar o teto só num dos dois daria uma mensalidade que respeita o fim
    quando é mensal e o ignora quando é bimestral.
    """
    modelo = _modelo(interval=2, start_date=date(2026, 1, 5), end_date=date(2026, 3, 5))
    assert RecurringService.occurrences_in_month(modelo, 2026, 3) == [date(2026, 3, 5)]
    assert RecurringService.occurrences_in_month(modelo, 2026, 5) == []


def test_sem_fim_nada_muda(cena):
    """`None` é "sem fim" — o comportamento de sempre, e o de toda linha
    existente depois da migração."""
    modelo = _modelo()
    assert RecurringService.occurrences_in_month(modelo, 2030, 7) == [date(2030, 7, 5)]


# --- 2. A contagem: "87 de 144" --------------------------------------------


def test_conta_as_ocorrencias_da_serie(cena):
    """Doze mensalidades: a conta que a lista mostra."""
    modelo = _modelo(start_date=date(2026, 1, 5), end_date=date(2026, 12, 5))
    assert RecurringService.count_occurrences(modelo) == 12


def test_serie_infinita_nao_se_conta(cena):
    """`None`, e não zero: zero diria "acabou"."""
    assert RecurringService.count_occurrences(_modelo()) is None


def test_por_N_ocorrencias_vira_data_de_fim(cena):
    """"Por 144 vezes" é convertido no SERVIDOR, com a MESMA aritmética que
    materializa — reimplementá-la no cliente daria duas contas que divergem."""
    modelo = _modelo(start_date=date(2026, 1, 5))
    assert RecurringService.end_date_after(modelo, 12) == date(2026, 12, 5)
    assert RecurringService.end_date_after(modelo, 1) == date(2026, 1, 5)


def test_a_rota_aceita_por_N_ocorrencias_e_grava_a_data(cena):
    r = client.post(
        f"/api/v1/workspaces/{cena['ws_id']}/recurring",
        json={
            "title": "Faculdade",
            "base_amount": "1200.00",
            "frequency": "monthly",
            "day_of_month": 10,
            "start_date": "2026-08-10",
            "end_after_occurrences": 144,
            "payer_user_id": cena["user_id"],
        },
        headers=cena["headers"],
    )
    assert r.status_code == 200, r.text
    corpo = r.json()
    # 144 meses a partir de agosto de 2026 = julho de 2038.
    assert corpo["end_date"] == "2038-07-10"
    assert corpo["occurrences_total"] == 144
    # Só `end_date` é persistido: guardar as duas formas criaria duas verdades
    # sobre quando a série acaba.
    assert "end_after_occurrences" not in corpo


def test_a_lista_traz_quantas_faltam(cena):
    client.post(
        f"/api/v1/workspaces/{cena['ws_id']}/recurring",
        json={
            "title": "Faculdade", "base_amount": "1200.00", "frequency": "monthly",
            "day_of_month": 10, "start_date": "2026-08-10",
            "end_date": "2027-07-10", "payer_user_id": cena["user_id"],
        },
        headers=cena["headers"],
    )
    r = client.get(
        f"/api/v1/workspaces/{cena['ws_id']}/recurring", headers=cena["headers"]
    )
    assert r.status_code == 200, r.text
    item = r.json()[0]
    assert item["occurrences_total"] == 12
    # Sem este número a mensalidade de doze anos era indistinguível de uma
    # assinatura sem fim.
    assert item["occurrences_remaining"] is not None


# --- 3. Coerência e materialização -----------------------------------------


def test_fim_antes_do_inicio_e_recusado(cena):
    """Entrada contraditória, não série vazia por engano: aceitá-la criaria uma
    recorrência ativa que nunca gera nada e ninguém entende por quê."""
    r = client.post(
        f"/api/v1/workspaces/{cena['ws_id']}/recurring",
        json={
            "title": "Impossível", "base_amount": "10.00", "frequency": "monthly",
            "day_of_month": 1, "start_date": "2026-08-01", "end_date": "2026-01-01",
        },
        headers=cena["headers"],
    )
    assert r.status_code == 400
    assert "término" in r.json()["error"]["message"]


def test_a_renda_recorrente_tambem_tem_fim(cena):
    """Bolsa e aluguel recebido por prazo determinado acabam.

    Sem a coluna, os dois projetavam renda para sempre — o mesmo defeito do lado
    da despesa, com o sinal trocado.
    """
    r = client.post(
        "/api/v1/me/recurring-income",
        json={
            "title": "Bolsa", "base_amount": "2000.00", "frequency": "monthly",
            "day_of_month": 5, "start_date": "2026-08-05", "end_date": "2028-07-05",
        },
        headers=cena["headers"],
    )
    assert r.status_code == 200, r.text
    assert r.json()["end_date"] == "2028-07-05"

    modelo = _modelo(start_date=date(2026, 8, 5), end_date=date(2028, 7, 5))
    assert RecurringService.occurrences_in_month(modelo, 2028, 8) == []


def test_serie_encerrada_para_de_materializar(cena):
    """O template continua `is_active` — ninguém volta para desligá-lo — e mesmo
    assim não gera mais nada."""
    db = cena["db"]
    db.add(RecurringExpense(
        title="Curso (terminado)", base_amount=Decimal("300.00"), currency="BRL",
        frequency=RecurrenceFrequency.monthly, day_of_month=1,
        start_date=date(2020, 1, 1), end_date=date(2020, 12, 1),
        workspace_id=cena["ws_id"], created_by_user_id=cena["user_id"],
        payer_user_id=cena["user_id"],
    ))
    db.commit()

    r = client.get(
        f"/api/v1/workspaces/{cena['ws_id']}/transactions/", headers=cena["headers"]
    )
    assert r.status_code == 200, r.text
    assert db.exec(select(Transaction)).all() == []


def test_serie_longa_demais_nao_inventa_um_total(cena):
    """Varredura truncada devolve `None`, não um número parcial.

    Um `end_date` em 2099 daria "288 de 288" — a contagem exata do teto de
    varredura, apresentada como se fosse o total da série, dizendo que ela
    acabou. `None` já é a resposta de "não sei contar" (é a da série sem fim), e
    a tela omite o contador em vez de mentir.
    """
    modelo = _modelo(start_date=date(2026, 1, 5), end_date=date(2099, 1, 5))
    assert RecurringService.count_occurrences(modelo) is None
