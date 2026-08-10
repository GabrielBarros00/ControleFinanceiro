"""A troca da moeda-base tem de cotar pelo dia LOCAL do lançamento.

`_as_date` lia `transaction_date.date()` — o dia em UTC. Uma despesa das 22h de
31 de julho em São Paulo está gravada como `2026-08-01T01:00Z`, então a
reconversão do histórico ia buscar a cotação de 1º de AGOSTO. Com o câmbio
mudando de um dia para o outro, o valor convertido saía errado e ficava gravado —
não há segunda chance: `convert_workspace` reescreve o histórico.

O mesmo `_as_date` alimenta o dry-run, então o erro aparecia antes também: a
lista `missing_rates` pedia ao operador a cotação de um dia que não era o da
despesa.
"""
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from sqlmodel import Session, select

from app.models.exchange_rate import ExchangeRate
from app.models.transaction import Transaction, TransactionStatus
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMembership, WorkspaceRole
from app.services.base_currency_service import BaseCurrencyService

# 31/07/2026 às 22h em São Paulo. O dia local é 31/07; o dia em UTC, 01/08.
INSTANTE = datetime(2026, 8, 1, 1, 0, tzinfo=UTC).replace(tzinfo=None)
DIA_LOCAL = date(2026, 7, 31)
DIA_UTC = date(2026, 8, 1)


@pytest.fixture(name="cena")
def cena_fixture(db_session: Session):
    user = User(name="Dona", email="onda9-troca@t.com", password_hash="h")
    ws = Workspace(name="Casa", base_currency="BRL")
    db_session.add_all([user, ws])
    db_session.flush()
    db_session.add(
        WorkspaceMembership(workspace_id=ws.id, user_id=user.id, role=WorkspaceRole.owner)
    )

    # Cotações deliberadamente distantes: qualquer troca de dia salta à vista.
    # USD→BRL a 5,00 no dia 31; a 10,00 no dia 1º.
    db_session.add_all([
        ExchangeRate(currency="USD", rate_date=DIA_LOCAL, rate=Decimal("5.000000"), source="ptax"),
        ExchangeRate(currency="USD", rate_date=DIA_UTC, rate=Decimal("10.000000"), source="ptax"),
    ])
    db_session.add(Transaction(
        title="Mercado", total_amount=Decimal("100.00"), currency="BRL",
        transaction_date=INSTANTE, billing_month="2026-07",
        workspace_id=ws.id, created_by_user_id=user.id,
        status=TransactionStatus.confirmed,
    ))
    db_session.commit()
    return {"ws_id": ws.id, "user_id": user.id}


def test_reconversao_usa_a_cotacao_do_dia_local(db_session, cena):
    """R$ 100 pela taxa de 31/07 (5,00) são US$ 20 — não US$ 10."""
    BaseCurrencyService.convert_workspace(db_session, cena["ws_id"], "USD")
    db_session.commit()

    tx = db_session.exec(
        select(Transaction).where(Transaction.workspace_id == cena["ws_id"])
    ).one()
    assert tx.currency == "USD"
    assert tx.total_amount == Decimal("20.00"), (
        "cotado pelo dia UTC daria 10,00 — a taxa do dia seguinte ao da despesa"
    )


def test_dry_run_reclama_a_cotacao_do_dia_local(db_session, cena):
    """Sem a taxa do dia LOCAL, é ELA que o relatório tem de pedir.

    Pedindo a do dia em UTC, o operador rodava o backfill para a data errada, a
    troca continuava falhando e nada no relatório explicava por quê.
    """
    faltante = db_session.exec(
        select(ExchangeRate).where(ExchangeRate.rate_date == DIA_LOCAL)
    ).one()
    db_session.delete(faltante)
    db_session.commit()

    relatorio = BaseCurrencyService.plan_conversion(db_session, cena["ws_id"], "USD")

    assert relatorio.missing_rates, "a taxa do dia da despesa não existe: tem de ser reportada"
    assert any(DIA_LOCAL.isoformat() in item for item in relatorio.missing_rates)
    assert not any(DIA_UTC.isoformat() in item for item in relatorio.missing_rates), (
        "a cotação de 01/08 existe; pedi-la de novo mandaria o operador ao dia errado"
    )
