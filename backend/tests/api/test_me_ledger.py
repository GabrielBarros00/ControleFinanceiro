"""Extrato global: as linhas que compõem o caixa do mês.

O ponto do endpoint é fechar com `/me/overview`. Ele NÃO é uma segunda consulta
parecida — é o mesmo `CashFlowService.list_movements` que alimenta os totais,
devolvendo as linhas em vez de somá-las. Estes testes fixam justamente isso: se
algum dia o extrato divergir do total, foi porque alguém duplicou a regra.
"""
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from app.core.jwt import create_access_token
from app.main import app
from app.models.credit_card import CardStatement, CreditCard, StatementPayment, StatementStatus
from app.models.income import Income
from app.models.settlement import Settlement
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMembership, WorkspaceRole

client = TestClient(app)

MES = "2026-07"
DIA_10 = datetime(2026, 7, 10, 12, 0)
DIA_20 = datetime(2026, 7, 20, 12, 0)


@pytest.fixture(name="cena")
def cena_fixture(db_session: Session, override_get_session):
    user = User(name="Dona", email="ledger@t.com", password_hash="h")
    outro = User(name="Vizinho", email="ledger-outro@t.com", password_hash="h")
    db_session.add_all([user, outro])
    ws = Workspace(name="Casa", base_currency="BRL")
    db_session.add(ws)
    db_session.flush()
    db_session.add_all([
        WorkspaceMembership(workspace_id=ws.id, user_id=user.id, role=WorkspaceRole.owner),
        WorkspaceMembership(workspace_id=ws.id, user_id=outro.id, role=WorkspaceRole.member),
    ])

    # Renda (entrada)
    db_session.add(Income(
        title="Salário", amount=Decimal("5000.00"), currency="BRL",
        # `settled_at` é o que torna a renda um movimento de CAIXA (ADR 0034);
        # `received_at` sozinho é competência, e renda prevista não entra no
        # extrato porque nada se moveu ainda.
        received_at=DIA_10, settled_at=DIA_10, user_id=user.id,
    ))
    # Pagamento de fatura (saída)
    card = CreditCard(
        name="Nubank", limit=Decimal("5000.00"), closing_day=25, due_day=5,
        currency="BRL", owner_user_id=user.id,
    )
    db_session.add(card)
    db_session.flush()
    statement = CardStatement(
        card_id=card.id, month=MES, status=StatementStatus.paid,
        closing_date=datetime(2026, 7, 25), due_date=datetime(2026, 8, 5),
        total_amount=Decimal("300.00"),
    )
    db_session.add(statement)
    db_session.flush()
    db_session.add(StatementPayment(
        statement_id=statement.id, amount=Decimal("300.00"), paid_at=DIA_20,
    ))
    # Acerto enviado (saída)
    db_session.add(Settlement(
        workspace_id=ws.id, from_user_id=user.id, to_user_id=outro.id,
        amount=Decimal("120.00"), settled_at=DIA_20,
    ))
    db_session.commit()

    token = create_access_token(data={"sub": str(user.id)})
    return {
        "ws_id": ws.id,
        "user_id": user.id,
        "outro_id": outro.id,
        "card_id": card.id,
        "headers": {"Cookie": f"access_token={token}"},
    }


def _ledger(cena, **params):
    query = "&".join(f"{k}={v}" for k, v in {"month": MES, **params}.items())
    res = client.get(f"/api/v1/me/ledger?{query}", headers=cena["headers"])
    assert res.status_code == 200, res.text
    return res.json()


def test_extrato_lista_as_seis_fontes_com_a_data_efetiva(cena):
    corpo = _ledger(cena)
    origens = {e["source"] for e in corpo["entries"]}
    assert origens == {"income", "statement_payment", "settlement_sent"}

    renda = next(e for e in corpo["entries"] if e["source"] == "income")
    assert renda["direction"] == "in"
    assert renda["occurred_on"] == "2026-07-10"
    assert Decimal(renda["converted_amount"]) == Decimal("5000.00")

    fatura = next(e for e in corpo["entries"] if e["source"] == "statement_payment")
    assert fatura["direction"] == "out"
    assert fatura["card_id"] == cena["card_id"]


def test_extrato_fecha_com_os_totais_da_visao_global(cena):
    """A razão de existir: detalhe e total saem da mesma consulta."""
    corpo = _ledger(cena)
    overview = client.get(
        f"/api/v1/me/overview?month={MES}", headers=cena["headers"]
    ).json()

    assert Decimal(corpo["cash_in"]) == Decimal(overview["cash_in"])
    assert Decimal(corpo["cash_out"]) == Decimal(overview["cash_out"])
    assert Decimal(corpo["net_cash"]) == Decimal(overview["net_cash"])

    # E a soma das LINHAS bate com o total agregado.
    saida = sum(
        Decimal(e["converted_amount"])
        for e in corpo["entries"]
        if e["direction"] == "out" and e["converted_amount"] is not None
    )
    assert saida == Decimal(overview["cash_out"])


def test_filtro_por_origem(cena):
    corpo = _ledger(cena, source="income")
    assert {e["source"] for e in corpo["entries"]} == {"income"}
    assert corpo["total"] == 1
    assert Decimal(corpo["cash_out"]) == Decimal("0.00")


def test_filtro_por_contraparte_e_por_cartao(cena):
    por_pessoa = _ledger(cena, counterparty_id=cena["outro_id"])
    assert {e["source"] for e in por_pessoa["entries"]} == {"settlement_sent"}
    assert por_pessoa["entries"][0]["counterparty_name"] == "Vizinho"

    por_cartao = _ledger(cena, card_id=cena["card_id"])
    assert {e["source"] for e in por_cartao["entries"]} == {"statement_payment"}


def test_origem_invalida_e_recusada(cena):
    res = client.get(
        f"/api/v1/me/ledger?month={MES}&source=inventada", headers=cena["headers"]
    )
    assert res.status_code == 400
    assert "inventada" in res.json()["error"]["message"]


def test_paginacao_preserva_o_total(cena):
    corpo = _ledger(cena, limit=1)
    assert len(corpo["entries"]) == 1
    # `total` é antes da paginação: a UI precisa saber que há mais.
    assert corpo["total"] == 3


def test_extrato_de_outra_pessoa_nao_vaza(cena, db_session):
    """O recorte é `user_id`, nunca workspace: a renda do vizinho não aparece."""
    db_session.add(Income(
        title="Salário do vizinho", amount=Decimal("9000.00"), currency="BRL",
        received_at=DIA_10, settled_at=DIA_10, user_id=cena["outro_id"],
    ))
    db_session.commit()

    corpo = _ledger(cena)
    titulos = {e["title"] for e in corpo["entries"]}
    assert "Salário do vizinho" not in titulos
    assert Decimal(corpo["cash_in"]) == Decimal("5000.00")


def test_mes_sem_movimento_devolve_extrato_vazio(cena):
    corpo = _ledger(cena, month="2026-03")
    assert corpo["entries"] == []
    assert corpo["total"] == 0
    assert Decimal(corpo["net_cash"]) == Decimal("0.00")


def test_data_efetiva_respeita_o_mes_local(db_session, cena):
    """31/07 22:00 em São Paulo é 01/08 01:00Z — e pertence a JULHO."""
    db_session.add(Income(
        title="Renda da virada", amount=Decimal("10.00"), currency="BRL",
        received_at=datetime(2026, 8, 1, 1, 0, tzinfo=UTC).replace(tzinfo=None),
        settled_at=datetime(2026, 8, 1, 1, 0, tzinfo=UTC).replace(tzinfo=None),
        user_id=cena["user_id"],
    ))
    db_session.commit()

    julho = _ledger(cena)
    assert "Renda da virada" in {e["title"] for e in julho["entries"]}
    agosto = _ledger(cena, month="2026-08")
    assert "Renda da virada" not in {e["title"] for e in agosto["entries"]}


def test_ordem_e_do_mais_recente_para_o_mais_antigo(cena):
    corpo = _ledger(cena)
    datas = [date.fromisoformat(e["occurred_on"]) for e in corpo["entries"]]
    assert datas == sorted(datas, reverse=True)
