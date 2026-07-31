"""Dívida em moeda estrangeira não pode SUMIR quando falta cotação (ADR 0006).

A auditoria externa reproduziu: dívida aberta de USD 100 de um mês anterior,
visão global em BRL, mês corrente sem lançamento novo, cotação indisponível. O
retorno era `to_pay = 0`, o workspace com `to_pay = 0` e — o pior —
`excluded_foreign_count = 0`. A pessoa devia e o app dizia que não devia nada,
sem um aviso sequer.

A causa era `_converte(...) or ZERO` nos dois saldos: o `or` transformava o `None`
(que significa "não sei converter") em zero (que significa "é zero") e ainda pulava
o incremento de `excluidos`. Como o mês corrente não tinha lançamento, `consumo` e
`caixa` valiam 0 e convertiam trivialmente — então a guarda que existia logo acima
não pegava o caso.

Omitir um valor avisando é a política do ADR 0006. Dizer "você não deve nada" a
quem deve é outra coisa.
"""
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from sqlmodel import Session

from app.models.transaction import (
    SplitMethod,
    Transaction,
    TransactionPayer,
    TransactionSplit,
)
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMembership, WorkspaceRole
from app.services.overview_service import OverviewService

HOJE = datetime.now(UTC)
MES_ATUAL = date(HOJE.year, HOJE.month, 1)


@pytest.fixture(name="divida_em_dolar")
def divida_em_dolar_fixture(db_session: Session):
    """Workspace com base USD, dívida de um mês ANTERIOR, e nada no mês corrente.

    O mês anterior é o ponto: com lançamento no mês corrente, `consumo` seria
    diferente de zero e a guarda que já existia pegaria o caso. É justamente o mês
    vazio que expunha o buraco.
    """
    alice = User(name="Alice", email="alice-usd@test.com", password_hash="h",
                 report_currency="BRL")
    bob = User(name="Bob", email="bob-usd@test.com", password_hash="h")
    ws = Workspace(name="Viagem", base_currency="USD")
    db_session.add_all([alice, bob, ws])
    db_session.commit()
    db_session.refresh(alice)
    db_session.refresh(bob)
    db_session.refresh(ws)

    for quem in (alice, bob):
        db_session.add(WorkspaceMembership(
            workspace_id=ws.id, user_id=quem.id, role=WorkspaceRole.owner
        ))

    anterior = date(2026, 1, 1)
    tx = Transaction(
        title="Hotel", total_amount=Decimal("100.00"), currency="USD",
        transaction_date=datetime(2026, 1, 15, tzinfo=UTC),
        billing_month="2026-01", workspace_id=ws.id, created_by_user_id=bob.id,
    )
    db_session.add(tx)
    db_session.flush()
    # Bob pagou tudo; a parte é toda da Alice → Alice deve USD 100 a Bob.
    db_session.add(TransactionPayer(
        transaction_id=tx.id, user_id=bob.id, amount=Decimal("100.00")
    ))
    db_session.add(TransactionSplit(
        transaction_id=tx.id, user_id=alice.id, split_method=SplitMethod.fixed,
        input_value=Decimal("100.00"), computed_amount=Decimal("100.00"),
    ))
    db_session.commit()
    return {"alice": alice, "bob": bob, "ws": ws, "mes_da_divida": anterior}


def test_divida_sem_cotacao_e_contada_como_excluida(db_session, divida_em_dolar):
    """Sem taxa USD→BRL no store, o workspace inteiro fica de fora — E APARECE
    na contagem. Antes: `to_pay = 0` com `excluded_foreign_count = 0`."""
    resultado = OverviewService.get_overview(
        db_session, divida_em_dolar["alice"].id, MES_ATUAL, currency="BRL"
    )

    assert resultado["excluded_foreign_count"] >= 1, (
        "a dívida sumiu sem deixar rastro na contagem"
    )
    assert resultado["by_workspace"] == [], (
        "o workspace entrou na lista anunciando 'a pagar 0'"
    )


def test_com_cotacao_a_divida_aparece_convertida(db_session, divida_em_dolar):
    """O outro lado da mesma regra: havendo taxa, o valor entra normalmente.

    Confirma que o teste acima falha por FALTA DE COTAÇÃO e não porque a dívida
    deixou de ser calculada.
    """
    from app.models.exchange_rate import ExchangeRate

    # O store é consultado com allow_fetch=False; a taxa precisa estar gravada.
    # `currency` é a moeda de ORIGEM — o destino do store é sempre BRL.
    db_session.add(ExchangeRate(
        currency="USD", rate_date=MES_ATUAL, rate=Decimal("5.00"), source="market",
    ))
    db_session.commit()

    resultado = OverviewService.get_overview(
        db_session, divida_em_dolar["alice"].id, MES_ATUAL, currency="BRL"
    )

    assert resultado["excluded_foreign_count"] == 0
    assert resultado["to_pay"] == Decimal("500.00")
    assert len(resultado["by_workspace"]) == 1
    assert resultado["by_workspace"][0]["to_pay"] == Decimal("500.00")
