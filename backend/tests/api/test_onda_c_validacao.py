"""Correções financeiras e de validação da Onda C."""
from datetime import date, datetime, UTC
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.core.jwt import create_access_token
from app.main import app
from app.models.category import Category
from app.models.estimate import MonthlyEstimate
from app.models.exchange_rate import ExchangeRate
from app.models.income import Income
from app.models.recurring import RecurringExpense
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMembership, WorkspaceRole
from app.services.currency_service import CurrencyService
from app.services.forecast_service import ForecastService
from app.services.report_service import ReportService


@pytest.fixture(autouse=True)
def sem_rede(monkeypatch):
    def _boom(*args, **kwargs):
        raise AssertionError("caminho de leitura foi à rede")

    monkeypatch.setattr(CurrencyService, "get_rate_sync", _boom)


@pytest.fixture
def ws(db_session: Session):
    user = User(name="G", email="ondac@t.com", password_hash="h")
    workspace = Workspace(name="WS-C")
    db_session.add_all([user, workspace])
    db_session.flush()
    db_session.add(WorkspaceMembership(
        workspace_id=workspace.id, user_id=user.id, role=WorkspaceRole.owner
    ))
    db_session.commit()
    token = create_access_token({"sub": str(user.id)})
    return {
        "user": user,
        "ws": workspace,
        "headers": {"Cookie": "access_token=" + token},
    }


# --- C1: previsão converte moeda estrangeira -------------------------------


def test_previsao_converte_recorrencia_estrangeira(db_session: Session, ws):
    """`USD 100` entrava na projeção como `R$ 100` (≈5x menor) — e errava para
    MENOS, que é o lado perigoso num app de orçamento."""
    hoje = date.today()
    db_session.add(RecurringExpense(
        title="Assinatura", base_amount=Decimal("100.00"), currency="USD",
        day_of_month=28, workspace_id=ws["ws"].id,
        created_by_user_id=ws["user"].id, payer_user_id=ws["user"].id,
    ))
    for dia in range(1, 29):
        db_session.add(ExchangeRate(
            currency="USD", rate_date=date(hoje.year, hoje.month, dia),
            rate=Decimal("5.000000"), source="ptax",
        ))
    db_session.commit()

    proj = ForecastService.get_monthly_projection(db_session, ws["ws"].id, hoje)
    if hoje.day < 28:
        assert proj["fixed_costs_pending"] == Decimal("500.00")


def test_previsao_exclui_recorrencia_sem_cotacao(db_session: Session, ws):
    hoje = date.today()
    db_session.add(RecurringExpense(
        title="Assinatura", base_amount=Decimal("100.00"), currency="JPY",
        day_of_month=28, workspace_id=ws["ws"].id,
        created_by_user_id=ws["user"].id, payer_user_id=ws["user"].id,
    ))
    db_session.commit()

    proj = ForecastService.get_monthly_projection(db_session, ws["ws"].id, hoje)
    assert proj["fixed_costs_pending"] == Decimal("0.00")
    if hoje.day < 28:
        assert proj["excluded_foreign_count"] >= 1


# --- C2: moeda da renda no resumo ------------------------------------------


def test_resumo_ignora_renda_fora_da_moeda_base(db_session: Session, ws):
    """A renda era o ÚNICO somatório sem o filtro de moeda (ADR 0006)."""
    agora = datetime.now(UTC)
    db_session.add(Income(
        title="BRL", amount=Decimal("1000.00"), currency="BRL",
        received_at=agora, workspace_id=ws["ws"].id, user_id=ws["user"].id,
    ))
    db_session.add(Income(
        title="USD legada", amount=Decimal("500.00"), currency="USD",
        received_at=agora, workspace_id=ws["ws"].id, user_id=ws["user"].id,
    ))
    db_session.commit()

    resumo = ReportService.get_summary(
        db_session, ws["ws"].id, date.today(), user_id=ws["user"].id
    )
    assert resumo["total_income"] == Decimal("1000.00")
    assert resumo["my_income"] == Decimal("1000.00")


# --- C3: orçamento chaveado por category_id --------------------------------


def test_orcamento_idempotente_por_category_id(db_session: Session, ws, override_get_session):
    """A idempotência chaveava pelo RÓTULO de texto: com texto igual, duas
    categorias diferentes colapsavam num orçamento só."""
    a = Category(workspace_id=ws["ws"].id, name="Alimentação")
    b = Category(workspace_id=ws["ws"].id, name="Transporte")
    db_session.add_all([a, b])
    db_session.commit()

    base = "/api/v1/workspaces/" + str(ws["ws"].id) + "/analytics/estimates"
    with TestClient(app) as client:
        for cat, valor in [(a, "100"), (a, "150"), (b, "200")]:
            resposta = client.post(base, headers=ws["headers"], json={
                "category": "rotulo igual para os dois",  # o texto NÃO é a chave
                "category_id": cat.id,
                "amount": valor,
                "month": "2026-08",
            })
            assert resposta.status_code == 200, resposta.text

    linhas = db_session.exec(
        select(MonthlyEstimate).where(MonthlyEstimate.month == "2026-08")
    ).all()
    assert len(linhas) == 2, "categorias distintas não podem virar um orçamento só"
    por_categoria = {e.category_id: e.amount for e in linhas}
    assert por_categoria[a.id] == Decimal("150")  # o 2º POST atualizou o 1º


# --- C4/C5: tetos de valor e texto ------------------------------------------


@pytest.mark.parametrize("payload,caso", [
    ({"title": "x", "amount": "1e30", "received_at": "2026-08-01T12:00:00"}, "valor"),
    ({"title": "x" * 5000, "amount": "10", "received_at": "2026-08-01T12:00:00"}, "titulo"),
])
def test_renda_recusa_valor_e_texto_fora_do_limite(ws, payload, caso, override_get_session):
    """Sem teto, 1e30 estourava NUMERIC(20,2) → 500 no Postgres, enquanto o
    SQLite de dev aceitava calado. Erro de cliente tem de ser 422."""
    url = "/api/v1/workspaces/" + str(ws["ws"].id) + "/income/"
    with TestClient(app) as client:
        resposta = client.post(url, headers=ws["headers"], json=payload)
    assert resposta.status_code == 422, caso


# --- C8: mês inválido é erro, não "sem filtro" ------------------------------


@pytest.mark.parametrize("rota", [
    "income/", "analytics/summary", "debts/monthly", "liabilities/overview",
])
@pytest.mark.parametrize("mes", ["lixo", "2026-13", "2026"])
def test_mes_invalido_devolve_400(ws, rota, mes, override_get_session):
    """`/income` engolia o erro e devolvia o histórico INTEIRO como se fosse o
    mês pedido; as outras três já devolviam 400."""
    url = "/api/v1/workspaces/" + str(ws["ws"].id) + "/" + rota
    with TestClient(app) as client:
        resposta = client.get(url, headers=ws["headers"], params={"month": mes})
    assert resposta.status_code == 400


def test_income_nao_devolve_tudo_com_mes_invalido(db_session: Session, ws, override_get_session):
    db_session.add(Income(
        title="Antiga", amount=Decimal("999.00"), currency="BRL",
        received_at=datetime(2020, 1, 5, tzinfo=UTC),
        workspace_id=ws["ws"].id, user_id=ws["user"].id,
    ))
    db_session.commit()

    url = "/api/v1/workspaces/" + str(ws["ws"].id) + "/income/"
    with TestClient(app) as client:
        resposta = client.get(url, headers=ws["headers"], params={"month": "agosto"})
    assert resposta.status_code == 400


# --- C11: max_uses do convite por link --------------------------------------


@pytest.mark.parametrize("max_uses", [0, -1])
def test_convite_por_link_recusa_max_uses_invalido(ws, max_uses, override_get_session):
    """`max_uses=0` criava um link JÁ esgotado (o gate é `uses >= max_uses`)."""
    url = "/api/v1/workspaces/" + str(ws["ws"].id) + "/invites/link"
    with TestClient(app) as client:
        resposta = client.post(
            url, headers=ws["headers"], json={"role": "member", "max_uses": max_uses}
        )
    assert resposta.status_code == 422
