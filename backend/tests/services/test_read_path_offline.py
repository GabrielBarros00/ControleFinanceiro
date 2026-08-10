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
        day_of_month=5, user_id=user.id,
    ))
    db_session.commit()

    criadas = RecurringMaterializationService.ensure_income_and_commit(
        db_session, user.id, date(2026, 7, 15)
    )

    assert criadas == 0
    assert db_session.exec(select(Income).where(Income.user_id == user.id)).all() == []


def test_materializacao_de_leitura_usa_taxa_do_store(db_session: Session, no_network):
    """Com a taxa já no store (backfill), a leitura materializa sem rede."""
    user, ws = _workspace(db_session, "offline2")
    db_session.add(RecurringIncome(
        title="Freela em dólar", base_amount=Decimal("1000.00"), currency="USD",
        day_of_month=5, user_id=user.id,
    ))
    db_session.add(ExchangeRate(
        currency="USD", rate_date=date(2026, 7, 5),
        rate=Decimal("5.000000"), source="ptax",
    ))
    db_session.commit()

    criadas = RecurringMaterializationService.ensure_income_and_commit(
        db_session, user.id, date(2026, 7, 15)
    )

    assert criadas == 1
    inc = db_session.exec(select(Income).where(Income.user_id == user.id)).one()
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


def test_ocorrencia_descartada_nao_deixa_fatura_vazia(db_session: Session, no_network):
    """A ocorrência descartada tem de levar a FATURA junto.

    `_statement_for` roda na montagem do lançamento, antes de a ocorrência estar
    garantida, e `get_or_create_statement` já faz `add` + `flush`. Quando a perna
    de fatura não encontrava cotação, a transação era abandonada mas a fatura
    ficava na sessão — e o commit do LOTE, disparado pela outra recorrência que
    deu certo, a confirmava. Sobrava uma fatura aberta e vazia no cartão: não
    muda valor nenhum, mas anuncia um mês de gastos que não existiu.

    O cenário é justamente o do lote MISTO: sozinha, a recorrência sem cotação
    não provocaria commit nenhum.
    """
    from app.models.credit_card import CardStatement, CreditCard
    from app.models.recurring import RecurringExpense

    user, ws = _workspace(db_session, "offline4")
    # Cartão em USD num workspace BRL: a perna contábil não precisa de cotação
    # (BRL→BRL), mas a de FATURA precisa (BRL→USD) e o store está vazio.
    card = CreditCard(
        name="Cartão gringo", limit=Decimal("5000.00"), closing_day=20, due_day=28,
        currency="USD", owner_user_id=user.id,
    )
    db_session.add(card)
    db_session.flush()

    db_session.add_all([
        RecurringExpense(
            title="Assinatura no cartão gringo", base_amount=Decimal("30.00"),
            currency="BRL", day_of_month=5, workspace_id=ws.id,
            created_by_user_id=user.id, payer_user_id=user.id,
            credit_card_id=card.id,
        ),
        # A que dá certo — é ela que faz o lote ser comitado.
        RecurringExpense(
            title="Aluguel", base_amount=Decimal("1000.00"), currency="BRL",
            day_of_month=5, workspace_id=ws.id, created_by_user_id=user.id,
            payer_user_id=user.id,
        ),
    ])
    db_session.commit()

    result = RecurringMaterializationService.ensure_current_month(
        db_session, ws.id, date(2026, 7, 15)
    )
    db_session.commit()

    assert result["expenses"] == 1, "só a válida materializa"
    titulos = [
        t.title for t in db_session.exec(
            select(Transaction).where(Transaction.workspace_id == ws.id)
        ).all()
    ]
    assert titulos == ["Aluguel"]
    assert db_session.exec(
        select(CardStatement).where(CardStatement.card_id == card.id)
    ).all() == [], "a fatura da ocorrência descartada não pode sobreviver ao commit"


def test_ocorrencia_com_snapshot_invalido_tambem_leva_a_fatura(db_session: Session, no_network):
    """O MESMO vazamento pela outra porta: divisão inválida.

    Este caminho já apagava a transação (`db.delete(tx)`) e esquecia a fatura —
    a auditoria só viu a porta da cotação, mas o descarte por snapshot inválido
    (participante que saiu do workspace) deixava o mesmo lixo para trás.
    """
    from app.models.credit_card import CardStatement, CreditCard
    from app.models.recurring import RecurringExpense

    user, ws = _workspace(db_session, "offline5")
    forasteiro = User(name="Ex-membro", email="saiu@t.com", password_hash="h")
    db_session.add(forasteiro)
    # Cartão na MOEDA do workspace: a perna de fatura resolve sem cotação, então
    # o que derruba a ocorrência é a divisão — não o câmbio.
    card = CreditCard(
        name="Cartão de casa", limit=Decimal("5000.00"), closing_day=20, due_day=28,
        currency="BRL", owner_user_id=user.id,
    )
    db_session.add(card)
    db_session.flush()

    db_session.add_all([
        RecurringExpense(
            title="Rateio com quem saiu", base_amount=Decimal("80.00"), currency="BRL",
            day_of_month=5, workspace_id=ws.id, created_by_user_id=user.id,
            payer_user_id=user.id, credit_card_id=card.id,
            split_snapshot=[
                {"user_id": forasteiro.id, "split_method": "equal", "input_value": "0"},
            ],
        ),
        RecurringExpense(
            title="Aluguel", base_amount=Decimal("1000.00"), currency="BRL",
            day_of_month=5, workspace_id=ws.id, created_by_user_id=user.id,
            payer_user_id=user.id,
        ),
    ])
    db_session.commit()

    result = RecurringMaterializationService.ensure_current_month(
        db_session, ws.id, date(2026, 7, 15)
    )
    db_session.commit()

    assert result["expenses"] == 1
    assert db_session.exec(
        select(CardStatement).where(CardStatement.card_id == card.id)
    ).all() == []
