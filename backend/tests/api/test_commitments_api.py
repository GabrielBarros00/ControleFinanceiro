"""Compromissos PESSOAIS: faturas e financiamentos, separados por prazo (ADR 0021).

Substitui `test_liabilities_api.py`, que testava um "panorama de endividamento do
workspace" com quebra por pessoa. Esse painel deixou de existir: cartão e
financiamento são de quem assinou, e somar a dívida de várias pessoas num total
de casa era um número que ninguém precisava pagar.

O que este arquivo protege, além do escopo, é a **separação por prazo**. O
"Total a pagar" antigo somava a próxima fatura do cartão com o principal INTEIRO
em aberto de cada financiamento — juntando o que vence em cinco dias com o que
vence em quinze anos. Um número assim não responde nem "quanto preciso ter em
caixa este mês" nem "quanto devo ao todo".
"""
import calendar
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from app.main import app
from app.models.credit_card import CardStatement, CreditCard, StatementStatus
from app.models.financing import AmortizationInstallment, Financing
from app.models.transaction import Transaction

client = TestClient(app)

# UTC, a mesma referência que `is_overdue` e `get_commitments` usam. Com
# `date.today()` (local) o fixture ficava frágil em fuso negativo: perto da meia-
# noite UTC já era o dia seguinte, e a fatura montada para "vencer hoje"
# aparecia como vencida.
HOJE = datetime.now(UTC).date()
FIM_DO_MES = date(HOJE.year, HOJE.month, calendar.monthrange(HOJE.year, HOJE.month)[1])


def _me(setup_data, caminho: str, headers_key: str = "headers1"):
    return client.get(f"/api/v1/me{caminho}", headers=setup_data[headers_key])


@pytest.fixture(name="compromissos")
def compromissos_fixture(db_session: Session, setup_data, override_get_session):
    """Do u1: um cartão com fatura vencida e outra a vencer, mais um financiamento
    com uma parcela atrasada, uma neste mês e uma futura."""
    u1 = setup_data["u1"]
    card = CreditCard(
        name="Nubank", limit=Decimal("5000.00"), closing_day=10, due_day=20,
        currency="BRL", owner_user_id=u1.id,
    )
    fin = Financing(
        title="Carro", total_amount=Decimal("36000.00"), interest_rate=Decimal("0.01"),
        start_date=HOJE - timedelta(days=90), installments_count=36,
        currency="BRL", owner_user_id=u1.id,
    )
    db_session.add_all([card, fin])
    db_session.commit()
    db_session.refresh(card)
    db_session.refresh(fin)

    # Fatura VENCIDA (fechada, vencimento no passado) com uma compra dentro
    vencida = CardStatement(
        card_id=card.id, month="2026-01", status=StatementStatus.closed,
        closing_date=datetime(2026, 1, 10, tzinfo=UTC),
        due_date=datetime(2026, 1, 20, tzinfo=UTC),
        total_amount=Decimal("300.00"),
    )
    # Fatura ABERTA vencendo ainda neste mês. O vencimento é o ÚLTIMO dia do mês:
    # qualquer data fixa (hoje, hoje+N) ou vira "vencida" numa rodada perto da
    # virada, ou escapa do mês quando o teste roda no fim dele.
    do_mes = CardStatement(
        card_id=card.id, month=HOJE.strftime("%Y-%m"), status=StatementStatus.open,
        closing_date=datetime.combine(HOJE, datetime.min.time()),
        due_date=datetime.combine(FIM_DO_MES, datetime.min.time()),
    )
    db_session.add_all([vencida, do_mes])
    db_session.commit()
    db_session.refresh(do_mes)

    db_session.add(Transaction(
        title="Compra", total_amount=Decimal("200.00"), currency="BRL",
        transaction_date=datetime.combine(HOJE, datetime.min.time()),
        billing_month=HOJE.strftime("%Y-%m"), status="confirmed",
        workspace_id=setup_data["ws1"].id, created_by_user_id=u1.id,
        statement_id=do_mes.id,
    ))
    db_session.add_all([
        AmortizationInstallment(
            financing_id=fin.id, installment_number=1,
            due_date=HOJE - timedelta(days=40),
            principal_amount=Decimal("900.00"), interest_amount=Decimal("100.00"),
            total_amount=Decimal("1000.00"), remaining_balance=Decimal("35100.00"),
        ),
        AmortizationInstallment(
            financing_id=fin.id, installment_number=2, due_date=HOJE,
            principal_amount=Decimal("900.00"), interest_amount=Decimal("100.00"),
            total_amount=Decimal("1000.00"), remaining_balance=Decimal("34200.00"),
        ),
        AmortizationInstallment(
            financing_id=fin.id, installment_number=3,
            due_date=HOJE + timedelta(days=60),
            principal_amount=Decimal("900.00"), interest_amount=Decimal("100.00"),
            total_amount=Decimal("1000.00"), remaining_balance=Decimal("33300.00"),
        ),
    ])
    db_session.commit()
    setup_data["card"] = card
    setup_data["fin"] = fin
    return setup_data


def test_vazio_nao_quebra(setup_data, override_get_session):
    corpo = _me(setup_data, "/commitments").json()
    assert corpo["cards"] == []
    assert corpo["financings"] == []
    assert Decimal(str(corpo["outstanding_total"])) == Decimal("0.00")


def test_prazos_ficam_separados(compromissos):
    """O ponto do endpoint: cinco números em vez de um `total` que mistura tudo."""
    corpo = _me(compromissos, "/commitments").json()

    # Vencido: a fatura fechada de janeiro + a parcela de 40 dias atrás
    assert Decimal(str(corpo["overdue"])) == Decimal("1300.00")
    # A vencer neste mês: a fatura aberta (200) + a parcela de hoje (1000)
    assert Decimal(str(corpo["due_this_month"])) == Decimal("1200.00")
    # Próximas: a parcela de daqui a 60 dias, com data e número
    assert [p["installment_number"] for p in corpo["next_installments"]] == [3]
    # Comprometimento mensal: a próxima parcela de cada financiamento ativo
    assert Decimal(str(corpo["monthly_commitment"])) == Decimal("1000.00")


def test_saldo_devedor_usa_o_principal(compromissos):
    """Saldo devedor é o PRINCIPAL em aberto: juros são custo futuro, não dívida
    de hoje. Somar a parcela cheia inflaria o que a pessoa deve."""
    corpo = _me(compromissos, "/commitments").json()
    # 3 parcelas × 900 de principal + 300 da fatura vencida + 200 da aberta
    assert Decimal(str(corpo["outstanding_total"])) == Decimal("3200.00")


def test_toda_fatura_em_aberto_conta(compromissos):
    """Duas faturas não pagas são duas obrigações. A versão anterior mostrava só
    a "que pede atenção" e escondia a segunda."""
    corpo = _me(compromissos, "/commitments").json()
    assert len(corpo["cards"]) == 2
    assert [c["is_overdue"] for c in corpo["cards"]] == [True, False]


def test_compromisso_de_outra_pessoa_nao_aparece(compromissos):
    """O u2 divide o workspace com o u1 e não vê nada disso."""
    corpo = _me(compromissos, "/commitments", headers_key="headers2").json()
    assert corpo["cards"] == []
    assert corpo["financings"] == []
    assert Decimal(str(corpo["outstanding_total"])) == Decimal("0.00")
