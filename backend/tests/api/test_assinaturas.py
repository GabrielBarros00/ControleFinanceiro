"""Assinaturas (ADR 0039): a recorrência que é Netflix, academia, domínio."""
from datetime import timedelta

from fastapi.testclient import TestClient
from sqlmodel import select

from app.domain.dates import today_local
from app.main import app
from app.models.transaction import Transaction

client = TestClient(app)


def _url(ws, extra=""):
    return f"/api/v1/workspaces/{ws}/recurring{extra}"


def _cria(ws, h, **corpo):
    hoje = today_local()
    base = {"title": "Assinatura", "base_amount": "50.00", "day_of_month": hoje.day, "start_date": hoje.isoformat()}
    r = client.post(_url(ws, "?materialize=current"), json={**base, **corpo}, headers=h)
    assert r.status_code == 200, r.text
    return r.json()


def test_assinatura_guarda_plano_teste_e_observacoes(db_session, setup_data, override_get_session):
    ws, h = setup_data["ws1"].id, setup_data["headers1"]
    fim_do_teste = today_local() + timedelta(days=20)
    a = _cria(ws, h, title="Netflix", is_subscription=True, plan="Premium", trial_ends_on=fim_do_teste.isoformat(),
              notes="4 telas, 4K")
    lido = client.get(_url(ws, f"/{a['id']}"), headers=h).json()
    assert (lido["is_subscription"], lido["plan"], lido["trial_ends_on"], lido["notes"]) == (
        True, "Premium", fim_do_teste.isoformat(), "4 telas, 4K")
    # Recorrência comum continua comum.
    assert _cria(ws, h, title="Aluguel")["is_subscription"] is False


def test_teste_gratis_sem_inicio_comeca_a_cobrar_no_fim_do_teste(db_session, setup_data, override_get_session):
    ws, h = setup_data["ws1"].id, setup_data["headers1"]
    hoje = today_local()
    fim_do_teste = hoje + timedelta(days=40)
    r = client.post(_url(ws, "?materialize=current"), headers=h, json={
        "title": "Streaming", "base_amount": "30.00", "day_of_month": fim_do_teste.day,
        "is_subscription": True, "trial_ends_on": fim_do_teste.isoformat(),
    })
    assert r.status_code == 200, r.text
    assert r.json()["start_date"] == fim_do_teste.isoformat()
    assert r.json()["next_occurrence"] == fim_do_teste.isoformat()
    # Nada cobrado durante o teste.
    assert db_session.exec(select(Transaction).where(Transaction.recurring_expense_id == r.json()["id"])).all() == []


def test_equivalente_mensal_soma_periodos_diferentes(db_session, setup_data, override_get_session):
    ws, h = setup_data["ws1"].id, setup_data["headers1"]
    hoje = today_local()
    anual = _cria(ws, h, title="Domínio", base_amount="120.00", frequency="yearly", month_of_year=hoje.month)
    semanal = _cria(ws, h, title="Feira", base_amount="30.00", frequency="weekly", day_of_week=hoje.weekday())
    trimestral = _cria(ws, h, title="Revista", base_amount="90.00", interval=3)
    mensal = _cria(ws, h, title="Academia", base_amount="99.90")
    assert [x["monthly_equivalent"] for x in (anual, semanal, trimestral, mensal)] == ["10.00", "130.00", "30.00", "99.90"]


def test_a_sua_parte_por_mes_segue_a_divisao(db_session, setup_data, override_get_session):
    ws, h = setup_data["ws1"].id, setup_data["headers1"]
    u1, u2 = setup_data["u1"].id, setup_data["u2"].id
    from app.models.workspace import FinancialAccess, WorkspaceMembership, WorkspaceRole

    db_session.add(WorkspaceMembership(workspace_id=ws, user_id=u2, role=WorkspaceRole.member,
                                       financial_access=FinancialAccess.full_workspace))
    db_session.commit()
    a = _cria(ws, h, title="Spotify Família", base_amount="40.00", is_subscription=True,
              split_snapshot=[{"user_id": u1, "split_method": "equal"}, {"user_id": u2, "split_method": "equal"}])
    assert (a["monthly_equivalent"], a["my_monthly_equivalent"]) == ("40.00", "20.00")


def test_pausada_nao_tem_proxima_cobranca(db_session, setup_data, override_get_session):
    ws, h = setup_data["ws1"].id, setup_data["headers1"]
    a = _cria(ws, h, title="Academia", is_subscription=True)
    assert a["next_occurrence"] is not None
    r = client.put(_url(ws, f"/{a['id']}"), json={"is_active": False}, headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["next_occurrence"] is None


def test_editar_apaga_plano_e_ignora_nulo_na_marca(db_session, setup_data, override_get_session):
    ws, h = setup_data["ws1"].id, setup_data["headers1"]
    a = _cria(ws, h, title="Netflix", is_subscription=True, plan="Básico")
    r = client.put(_url(ws, f"/{a['id']}"), json={"plan": None, "is_subscription": None}, headers=h)
    assert r.status_code == 200, r.text
    assert (r.json()["plan"], r.json()["is_subscription"]) == (None, True)
    r = client.put(_url(ws, f"/{a['id']}"), json={"is_subscription": False}, headers=h)
    assert r.json()["is_subscription"] is False


def test_provedor_e_o_estabelecimento(db_session, setup_data, override_get_session):
    ws, h = setup_data["ws1"].id, setup_data["headers1"]
    m = client.post(f"/api/v1/workspaces/{ws}/merchants", json={"name": "Netflix", "aliases": ["NETFLIX.COM"]}, headers=h).json()
    # Pelo título, como o lançamento novo; pelo nome, acha ou cria.
    assert _cria(ws, h, title="NETFLIX.COM", is_subscription=True)["merchant_id"] == m["id"]
    outra = _cria(ws, h, title="Música", is_subscription=True, merchant_name="Deezer")
    assert outra["merchant_id"] not in (None, m["id"])
    r = client.put(_url(ws, f"/{outra['id']}"), json={"merchant_name": "netflix.com"}, headers=h)
    assert r.json()["merchant_id"] == m["id"]
    alheio = client.post(f"/api/v1/workspaces/{setup_data['ws2'].id}/merchants", json={"name": "X"},
                         headers=setup_data["headers2"]).json()
    assert client.put(_url(ws, f"/{outra['id']}"), json={"merchant_id": alheio["id"]}, headers=h).status_code == 404


def test_observacoes_nao_vao_para_as_ocorrencias(db_session, setup_data, override_get_session):
    ws, h = setup_data["ws1"].id, setup_data["headers1"]
    a = _cria(ws, h, title="Academia", is_subscription=True, notes="Inclui piscina", description="Mensalidade")
    ocorrencias = db_session.exec(select(Transaction).where(Transaction.recurring_expense_id == a["id"])).all()
    assert ocorrencias and all(t.description == "Mensalidade" for t in ocorrencias)
