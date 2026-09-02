"""A virada do mês nos caminhos que a Onda 7 deixou passar.

`test_fronteira_de_mes_caixa.py` fixou em que MÊS cada movimento cai. Uma
auditoria mostrou que acertar a seleção não bastava: vários caminhos continuavam
lendo a data de um instante em UTC, e o resultado era um app que selecionava o
movimento para julho e depois o exibia, cotava e faturava como agosto.

Todos os casos usam o mesmo instante — 31/07/2026 às 22h em São Paulo, gravado
como `2026-08-01T01:00Z` — e exigem que a resposta diga JULHO.

O que cada um cobre, e o que estava errado antes:

- **Extrato global**: `occurred_on` vinha de `momento.date()`, então o extrato de
  julho trazia uma linha datada de 01/08. A mesma data alimenta o conversor de
  câmbio, então a cotação também era a do dia errado.
- **Página Rendas**: a listagem recortava com `month_bounds` ingênuo enquanto
  `/me/overview` já usava `month_bounds_utc` — a renda aparecia numa tela e
  faltava na outra, cada uma parecendo certa sozinha.
- **Parcela de financiamento**: `billing_month` saía do ano/mês em UTC, e a
  despesa nascia com competência de agosto — invisível em todas as telas, que
  pedem julho.
- **Roteamento de fatura**: a compra era atribuída ao ciclo pelo dia em UTC, e
  cruzava o dia de fechamento um dia antes do que devia.
"""
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.core.jwt import create_access_token
from app.domain.dates import local_day, month_key_local
from app.main import app
from app.models.credit_card import CreditCard
from app.models.financing import (
    AmortizationInstallment,
    AmortizationMethod,
    Financing,
    FinancingStatus,
)
from app.models.income import Income
from app.models.transaction import Transaction
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMembership, WorkspaceRole
from app.services.credit_card_service import CreditCardService

client = TestClient(app)

# 31/07/2026 22:00 em Brasília == 01/08/2026 01:00 UTC.
INSTANTE_UTC = datetime(2026, 8, 1, 1, 0, tzinfo=UTC)
INSTANTE_NAIVE = INSTANTE_UTC.replace(tzinfo=None)
JULHO = "2026-07"


@pytest.fixture(name="cena")
def cena_fixture(db_session: Session, override_get_session):
    user = User(name="Dona", email="onda8-fuso@t.com", password_hash="h")
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


def test_local_day_le_o_instante_no_fuso_do_app():
    """O helper em si: instante convertido, data de calendário intacta."""
    assert local_day(INSTANTE_UTC) == date(2026, 7, 31)
    assert local_day(INSTANTE_NAIVE) == date(2026, 7, 31)
    # `date` puro atravessa — é o que impede a varredura de estragar as datas de
    # calendário (vencimento, cronograma, linha de CSV).
    assert local_day(date(2026, 8, 1)) == date(2026, 8, 1)


def test_extrato_mostra_a_data_local_do_movimento(db_session, cena):
    """Selecionava para julho e exibia 01/08 — um extrato de julho com uma linha
    de agosto, que é como o usuário descobre que o sistema não fecha."""
    db_session.add(Income(
        title="Salário", amount=Decimal("5000.00"), currency="BRL",
        # `settled_at` é a data de CAIXA (ADR 0034) e é ela que o extrato usa —
        # aqui vale o mesmo instante da virada, que é o ponto do teste.
        received_at=INSTANTE_NAIVE, settled_at=INSTANTE_NAIVE,
        user_id=cena["user_id"],
    ))
    db_session.commit()

    resp = client.get(f"/api/v1/me/ledger?month={JULHO}", headers=cena["headers"])
    assert resp.status_code == 200
    linhas = resp.json()["entries"]
    assert len(linhas) == 1, "a renda tem de estar no extrato de julho"
    assert linhas[0]["occurred_on"] == "2026-07-31"


def test_renda_da_virada_aparece_na_pagina_rendas_de_julho(db_session, cena):
    """A Visão global já a colocava em julho; a página Rendas não. Divergência
    entre duas telas do mesmo mês é pior que as duas erradas juntas."""
    db_session.add(Income(
        title="Salário", amount=Decimal("5000.00"), currency="BRL",
        received_at=INSTANTE_NAIVE, user_id=cena["user_id"],
    ))
    db_session.commit()

    julho = client.get(f"/api/v1/me/income?month={JULHO}", headers=cena["headers"])
    assert julho.status_code == 200
    assert [r["title"] for r in julho.json()] == ["Salário"]

    agosto = client.get("/api/v1/me/income?month=2026-08", headers=cena["headers"])
    assert agosto.json() == []


def test_parcela_paga_na_virada_tem_competencia_de_julho(db_session, cena):
    """`billing_month` derivado do ano/mês em UTC dava agosto — e a despesa
    sumia de Lançamentos, Dívidas e Relatórios, que todos pedem julho."""
    financing = Financing(
        title="Imóvel", total_amount=Decimal("1000.00"), interest_rate=Decimal("0.01"),
        start_date=date(2026, 1, 1), installments_count=10,
        method=AmortizationMethod.SAC, status=FinancingStatus.active,
        currency="BRL", owner_user_id=cena["user_id"],
    )
    db_session.add(financing)
    db_session.flush()
    db_session.add(AmortizationInstallment(
        financing_id=financing.id, installment_number=1, due_date=date(2026, 8, 10),
        principal_amount=Decimal("100.00"), interest_amount=Decimal("10.00"),
        total_amount=Decimal("110.00"), remaining_balance=Decimal("900.00"),
    ))
    db_session.commit()

    resp = client.post(
        f"/api/v1/me/financing/{financing.id}/installments/1/pay",
        json={"workspace_id": cena["ws_id"], "paid_at": INSTANTE_UTC.isoformat()},
        headers=cena["headers"],
    )
    assert resp.status_code == 200, resp.text

    tx = db_session.exec(
        select(Transaction).where(Transaction.id == resp.json()["transaction_id"])
    ).one()
    assert tx.billing_month == JULHO
    assert month_key_local(INSTANTE_UTC) == JULHO


def test_preview_e_lancamento_concordam_no_dia_do_fechamento(db_session, cena):
    """O preview anuncia o destino que o POST vai gravar — ou não serve.

    O formulário tem um `<input type="date">` e manda `YYYY-MM-DD` para
    `/statement-for`, enquanto o POST manda um instante ancorado ao meio-dia
    local. Com o parâmetro tipado como `datetime`, `YYYY-MM-DD` virava meia-noite
    NAIVE, que o roteamento lê como instante UTC e resolve para o dia ANTERIOR:
    no dia exato do fechamento o preview dizia uma fatura e o lançamento caía em
    outra.
    """
    card = CreditCard(
        name="Itaú", limit=Decimal("5000.00"), closing_day=25, due_day=5,
        currency="BRL", owner_user_id=cena["user_id"],
    )
    db_session.add(card)
    db_session.commit()
    db_session.refresh(card)

    preview = client.get(
        f"/api/v1/me/credit-cards/{card.id}/statement-for?on=2026-03-25",
        headers=cena["headers"],
    )
    assert preview.status_code == 200, preview.text

    # O que o formulário manda no POST para o MESMO dia escolhido: meio-dia
    # local (15:00Z em São Paulo).
    instante_do_form = datetime(2026, 3, 25, 15, 0, tzinfo=UTC)
    ano, mes, _ = CreditCardService.resolve_statement_target(
        db_session, card, instante_do_form
    )

    assert preview.json()["month"] == f"{ano}-{mes:02d}" == "2026-04"


def test_compra_da_virada_vai_para_a_fatura_do_ciclo_local(db_session, cena):
    """Com fechamento no dia 1º, o dia LOCAL (31) e o dia UTC (1) caem em ciclos
    diferentes: pelo UTC a compra pulava um mês inteiro de fatura."""
    card = CreditCard(
        name="Nubank", limit=Decimal("5000.00"), closing_day=1, due_day=10,
        currency="BRL", owner_user_id=cena["user_id"],
    )
    db_session.add(card)
    db_session.commit()

    ano, mes, _ = CreditCardService.resolve_statement_target(
        db_session, card, INSTANTE_NAIVE
    )
    # 31/07 local >= dia 1 de fechamento → fatura de AGOSTO. Pelo UTC (01/08)
    # seria a de setembro.
    assert (ano, mes) == (2026, 8)

    preview = CreditCardService.preview_statement_target(db_session, card, INSTANTE_NAIVE)
    assert preview["month"] == "2026-08"
