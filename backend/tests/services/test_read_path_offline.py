"""O caminho de LEITURA nunca vai à rede (A5).

`ensure_and_commit` roda em GET /transactions, /analytics/summary,
/analytics/reports e /income. Para um template em moeda estrangeira ele descia
até `CurrencyService`, que faz look-back de 5 dias contra uma fonte externa —
até ~50s presos dentro de um GET, com a disponibilidade da tela dependendo de
uma CDN de terceiro.

Estes testes fixam o contrato: no modo offline a rede é PROIBIDA, e a ausência
de taxa faz a ocorrência esperar o backfill em vez de nascer com valor inventado
ou derrubar a requisição.
"""
from datetime import date
from decimal import Decimal

import pytest
from sqlmodel import Session, select

from app.models.exchange_rate import ExchangeRate
from app.models.income import Income
from app.models.recurring import RecurringIncome
from app.models.transaction import Transaction
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMembership, WorkspaceRole
from app.services.currency_service import CurrencyService, ExchangeRateUnavailable
from app.services.exchange_rate_store import ExchangeRateStore
from app.services.recurring_service import RecurringMaterializationService


@pytest.fixture
def no_network(monkeypatch):
    """Qualquer ida à rede vira falha de teste explícita."""
    def _boom(*args, **kwargs):
        raise AssertionError("caminho de leitura tentou buscar cotação na rede")

    monkeypatch.setattr(CurrencyService, "get_rate_sync", _boom)


def _workspace(db_session: Session, tag: str):
    user = User(name="Gabriel", email=f"{tag}@t.com", password_hash="h")
    ws = Workspace(name=f"WS-{tag}")
    db_session.add_all([user, ws])
    db_session.flush()
    db_session.add(WorkspaceMembership(
        workspace_id=ws.id, user_id=user.id, role=WorkspaceRole.owner
    ))
    db_session.flush()
    return user, ws


def test_get_or_fetch_offline_nao_usa_a_rede(db_session: Session, no_network):
    db_session.add(ExchangeRate(
        currency="USD", rate_date=date(2026, 7, 10),
        rate=Decimal("5.400000"), source="ptax",
    ))
    db_session.flush()

    rate, source = ExchangeRateStore.get_or_fetch(
        db_session, "USD", date(2026, 7, 10), allow_fetch=False
    )
    assert rate == Decimal("5.400000")
    assert source == "ptax"


def test_get_or_fetch_offline_usa_taxa_anterior_como_fallback(db_session: Session, no_network):
    """Fim de semana/feriado não tem cotação: a mais recente anterior serve."""
    db_session.add(ExchangeRate(
        currency="USD", rate_date=date(2026, 7, 10),
        rate=Decimal("5.400000"), source="ptax",
    ))
    db_session.flush()

    rate, _ = ExchangeRateStore.get_or_fetch(
        db_session, "USD", date(2026, 7, 12), allow_fetch=False
    )
    assert rate == Decimal("5.400000")


def test_get_or_fetch_offline_sem_taxa_levanta(db_session: Session, no_network):
    with pytest.raises(ExchangeRateUnavailable):
        ExchangeRateStore.get_or_fetch(
            db_session, "USD", date(2026, 7, 10), allow_fetch=False
        )


def test_materializacao_de_leitura_nao_toca_a_rede(db_session: Session, no_network):
    """Renda recorrente em USD sem taxa no store: a leitura responde normalmente,
    a ocorrência apenas não é materializada ainda."""
    user, ws = _workspace(db_session, "offline1")
    db_session.add(RecurringIncome(
        title="Freela em dólar", base_amount=Decimal("1000.00"), currency="USD",
        day_of_month=5, workspace_id=ws.id, user_id=user.id,
    ))
    db_session.commit()

    result = RecurringMaterializationService.ensure_current_month(
        db_session, ws.id, date(2026, 7, 15)
    )
    db_session.commit()

    assert result == {"expenses": 0, "income": 0, "promoted": 0}
    assert db_session.exec(select(Income).where(Income.workspace_id == ws.id)).all() == []


def test_materializacao_de_leitura_usa_taxa_do_store(db_session: Session, no_network):
    """Com a taxa já no store (backfill), a leitura materializa sem rede."""
    user, ws = _workspace(db_session, "offline2")
    db_session.add(RecurringIncome(
        title="Freela em dólar", base_amount=Decimal("1000.00"), currency="USD",
        day_of_month=5, workspace_id=ws.id, user_id=user.id,
    ))
    db_session.add(ExchangeRate(
        currency="USD", rate_date=date(2026, 7, 5),
        rate=Decimal("5.000000"), source="ptax",
    ))
    db_session.commit()

    result = RecurringMaterializationService.ensure_current_month(
        db_session, ws.id, date(2026, 7, 15)
    )
    db_session.commit()

    assert result["income"] == 1
    inc = db_session.exec(select(Income).where(Income.workspace_id == ws.id)).one()
    assert inc.amount == Decimal("5000.00")
    assert inc.original_amount == Decimal("1000.00")
    assert inc.original_currency == "USD"


def test_materializacao_de_leitura_pula_despesa_sem_taxa(db_session: Session, no_network):
    """Mesma regra do lado da despesa: sem taxa, não nasce instância torta."""
    from app.models.recurring import RecurringExpense

    user, ws = _workspace(db_session, "offline3")
    db_session.add(RecurringExpense(
        title="Assinatura em dólar", base_amount=Decimal("50.00"), currency="USD",
        day_of_month=5, workspace_id=ws.id, created_by_user_id=user.id,
        payer_user_id=user.id,
    ))
    db_session.commit()

    result = RecurringMaterializationService.ensure_current_month(
        db_session, ws.id, date(2026, 7, 15)
    )
    db_session.commit()

    assert result["expenses"] == 0
    assert db_session.exec(
        select(Transaction).where(Transaction.workspace_id == ws.id)
    ).all() == []
