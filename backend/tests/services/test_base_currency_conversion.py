"""Troca de moeda-base com reconversão do histórico (A6).

Antes, trocar a moeda-base deixava todo valor gravado na moeda antiga enquanto
as agregações passavam a filtrar pela nova — dívidas, relatórios, faturas e
previsão iam a ZERO de uma vez e o workspace parecia vazio.

O risco da correção é outro: converter cada linha isoladamente quebraria
`soma(pagadores) == total`, `soma(splits) == total` e `soma(itens) + ajustes ==
total`, que é justamente o que o ADR 0001 protege. Por isso a maior parte destes
testes é sobre INVARIANTE, não sobre o valor convertido.
"""
from datetime import date, datetime, UTC
from decimal import Decimal

import pytest
from sqlmodel import Session, select

from app.models.exchange_rate import ExchangeRate
from app.models.income import Income
from app.models.transaction import (
    SplitMethod,
    SplitMode,
    Transaction,
    TransactionAdjustment,
    TransactionItem,
    TransactionItemShare,
    TransactionPayer,
    TransactionSplit,
    TransactionStatus,
)
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMembership, WorkspaceRole
from app.services.base_currency_service import BaseCurrencyService, MissingRates
from app.services.debt_service import DebtService

OCC = datetime(2026, 7, 10, tzinfo=UTC)


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """A reconversão NUNCA pode ir à rede: são centenas de datas distintas num
    histórico real, e isso dentro de um PUT. A fonte é o store local."""
    from app.services.currency_service import CurrencyService

    def _boom(*args, **kwargs):
        raise AssertionError("conversão de moeda-base tentou buscar cotação na rede")

    monkeypatch.setattr(CurrencyService, "get_rate_sync", _boom)


def _seed_rate(db: Session, on: date, rate: str = "5.00") -> None:
    db.add(ExchangeRate(
        currency="USD", rate_date=on, rate=Decimal(rate), source="ptax",
    ))


def _workspace(db: Session, tag: str, n_users: int = 2):
    users = []
    for i in range(n_users):
        u = User(name=f"U{i}", email=f"{tag}{i}@t.com", password_hash="h")
        db.add(u)
        users.append(u)
    ws = Workspace(name=f"WS-{tag}", base_currency="BRL")
    db.add(ws)
    db.flush()
    for u in users:
        db.add(WorkspaceMembership(
            workspace_id=ws.id, user_id=u.id, role=WorkspaceRole.owner
        ))
    db.flush()
    # Cotações das datas usadas pelos testes (inclui hoje: cartões e templates)
    _seed_rate(db, OCC.date())
    _seed_rate(db, date.today())
    db.flush()
    return users, ws


def _tx(db: Session, ws_id: int, total: str, **kw) -> Transaction:
    tx = Transaction(
        title="Compra", total_amount=Decimal(total), currency="BRL",
        transaction_date=OCC, billing_month="2026-07",
        workspace_id=ws_id, status=TransactionStatus.confirmed, **kw,
    )
    db.add(tx)
    db.flush()
    return tx


# --- invariantes ------------------------------------------------------------


def test_divisao_pela_despesa_continua_fechando(db_session: Session):
    """soma(pagadores) == total e soma(splits) == total, com resto de centavo."""
    users, ws = _workspace(db_session, "bc1", n_users=3)
    # 100,00 / 3 = 33,34 + 33,33 + 33,33 — o caso que o arredondamento quebra
    tx = _tx(db_session, ws.id, "100.00")
    db_session.add(TransactionPayer(transaction_id=tx.id, user_id=users[0].id, amount=Decimal("100.00")))
    for u, amount in zip(users, ["33.34", "33.33", "33.33"]):
        db_session.add(TransactionSplit(
            transaction_id=tx.id, user_id=u.id, split_method=SplitMethod.equal,
            input_value=Decimal("0"), computed_amount=Decimal(amount),
        ))
    db_session.commit()

    BaseCurrencyService.convert_workspace(db_session, ws.id, "USD")
    db_session.commit()
    db_session.refresh(tx)

    payers = db_session.exec(select(TransactionPayer).where(TransactionPayer.transaction_id == tx.id)).all()
    splits = db_session.exec(select(TransactionSplit).where(TransactionSplit.transaction_id == tx.id)).all()

    assert tx.total_amount == Decimal("20.00")  # 100 BRL / 5,00
    assert tx.currency == "USD"
    assert sum(p.amount for p in payers) == tx.total_amount
    assert sum(s.computed_amount for s in splits) == tx.total_amount


def test_divisao_por_item_com_ajuste_continua_fechando(db_session: Session):
    """soma(itens) + ajustes == total, e soma(shares) == valor do item."""
    users, ws = _workspace(db_session, "bc2", n_users=2)
    tx = _tx(db_session, ws.id, "90.00", split_mode=SplitMode.item)
    db_session.add(TransactionPayer(transaction_id=tx.id, user_id=users[0].id, amount=Decimal("90.00")))
    db_session.add(TransactionAdjustment(
        transaction_id=tx.id, amount=Decimal("-10.00"),
    ))
    for pos, amount in enumerate(["70.00", "30.00"]):
        item = TransactionItem(
            transaction_id=tx.id, title=f"Item {pos}", amount=Decimal(amount), position=pos,
        )
        db_session.add(item)
        db_session.flush()
        half = (Decimal(amount) / 2).quantize(Decimal("0.01"))
        for u in users:
            db_session.add(TransactionItemShare(
                item_id=item.id, user_id=u.id, split_method=SplitMethod.equal,
                input_value=Decimal("0"), computed_amount=half,
            ))
    for u, amount in zip(users, ["45.00", "45.00"]):
        db_session.add(TransactionSplit(
            transaction_id=tx.id, user_id=u.id, split_method=SplitMethod.fixed,
            input_value=Decimal(amount), computed_amount=Decimal(amount),
        ))
    db_session.commit()

    BaseCurrencyService.convert_workspace(db_session, ws.id, "USD")
    db_session.commit()
    db_session.refresh(tx)

    items = db_session.exec(select(TransactionItem).where(TransactionItem.transaction_id == tx.id)).all()
    adjustments = db_session.exec(
        select(TransactionAdjustment).where(TransactionAdjustment.transaction_id == tx.id)
    ).all()
    splits = db_session.exec(select(TransactionSplit).where(TransactionSplit.transaction_id == tx.id)).all()

    assert tx.total_amount == Decimal("18.00")  # 90 / 5
    assert sum(i.amount for i in items) + sum(a.amount for a in adjustments) == tx.total_amount
    assert sum(s.computed_amount for s in splits) == tx.total_amount
    for item in items:
        shares = db_session.exec(
            select(TransactionItemShare).where(TransactionItemShare.item_id == item.id)
        ).all()
        assert sum(s.computed_amount for s in shares) == item.amount
    # Valor fixo passa a refletir o computado (senão o form reabriria divergente)
    for split in splits:
        assert split.input_value == split.computed_amount


def test_totais_nao_zeram_apos_a_troca(db_session: Session):
    """O bug original: depois da troca, as agregações continuavam vendo os dados."""
    users, ws = _workspace(db_session, "bc3", n_users=2)
    tx = _tx(db_session, ws.id, "100.00")
    db_session.add(TransactionPayer(transaction_id=tx.id, user_id=users[0].id, amount=Decimal("100.00")))
    for u in users:
        db_session.add(TransactionSplit(
            transaction_id=tx.id, user_id=u.id, split_method=SplitMethod.equal,
            input_value=Decimal("0"), computed_amount=Decimal("50.00"),
        ))
    db_session.commit()

    antes = DebtService.get_workspace_debts(db_session, ws.id)
    assert antes and antes[0]["amount"] == Decimal("50.00")

    BaseCurrencyService.convert_workspace(db_session, ws.id, "USD")
    ws.base_currency = "USD"
    db_session.add(ws)
    db_session.commit()

    depois = DebtService.get_workspace_debts(db_session, ws.id)
    assert depois, "as dívidas sumiram após a troca de moeda-base"
    assert depois[0]["amount"] == Decimal("10.00")  # 50 / 5


def test_item_com_quantidade_mantem_o_valor_da_linha(db_session: Session):
    """Item `3 × 10,00` não pode virar o preço de UM depois da conversão.

    A normalização para `1 × valor-da-linha` é correta (a fatia convertida
    raramente é múltipla exata da quantidade), mas o valor da linha é a fonte de
    verdade: recalculá-lo a partir de `amount / quantity` encolhia o item e
    quebrava `soma(itens) == total` e o rateio das shares.
    """
    users, ws = _workspace(db_session, "bc9", n_users=2)
    tx = _tx(db_session, ws.id, "90.00", split_mode=SplitMode.item)
    db_session.add(TransactionPayer(
        transaction_id=tx.id, user_id=users[0].id, amount=Decimal("90.00")
    ))
    # 3 × 20,00 = 60,00 e 1 × 30,00 = 30,00
    for pos, (qtd, unit, total) in enumerate([("3", "20.00", "60.00"), ("1", "30.00", "30.00")]):
        item = TransactionItem(
            transaction_id=tx.id, title=f"Item {pos}", position=pos,
            amount=Decimal(total), quantity=Decimal(qtd), unit_amount=Decimal(unit),
        )
        db_session.add(item)
        db_session.flush()
        metade = (Decimal(total) / 2).quantize(Decimal("0.01"))
        for u in users:
            db_session.add(TransactionItemShare(
                item_id=item.id, user_id=u.id, split_method=SplitMethod.equal,
                input_value=Decimal("0"), computed_amount=metade,
            ))
    for u in users:
        db_session.add(TransactionSplit(
            transaction_id=tx.id, user_id=u.id, split_method=SplitMethod.fixed,
            input_value=Decimal("45.00"), computed_amount=Decimal("45.00"),
        ))
    db_session.commit()

    BaseCurrencyService.convert_workspace(db_session, ws.id, "USD")
    db_session.commit()
    db_session.refresh(tx)

    items = db_session.exec(
        select(TransactionItem)
        .where(TransactionItem.transaction_id == tx.id)
        .order_by(TransactionItem.position)
    ).all()

    assert tx.total_amount == Decimal("18.00")  # 90 / 5
    # 60 e 30 viram 12 e 6 — e NÃO 4 e 6 (o bug dividia o primeiro por quantity)
    assert [i.amount for i in items] == [Decimal("12.00"), Decimal("6.00")]
    assert sum(i.amount for i in items) == tx.total_amount
    # Linha normalizada: 1 × valor-da-linha
    for item in items:
        assert item.quantity == Decimal("1")
        assert item.unit_amount == item.amount
        shares = db_session.exec(
            select(TransactionItemShare).where(TransactionItemShare.item_id == item.id)
        ).all()
        assert sum(s.computed_amount for s in shares) == item.amount


# --- proveniência e round-trip ---------------------------------------------


def test_lancamento_estrangeiro_volta_ao_valor_original(db_session: Session):
    """Compra que era USD 20 @ 5,00 (gravada como BRL 100) volta a USD 20 exatos
    quando a moeda-base VIRA USD — sem perder centavo no caminho de volta."""
    users, ws = _workspace(db_session, "bc4", n_users=1)
    tx = _tx(
        db_session, ws.id, "100.00",
        original_amount=Decimal("20.00"), original_currency="USD",
        exchange_rate=Decimal("5.00"), rate_source="ptax",
    )
    db_session.add(TransactionPayer(transaction_id=tx.id, user_id=users[0].id, amount=Decimal("100.00")))
    db_session.add(TransactionSplit(
        transaction_id=tx.id, user_id=users[0].id, split_method=SplitMethod.equal,
        input_value=Decimal("0"), computed_amount=Decimal("100.00"),
    ))
    db_session.commit()

    BaseCurrencyService.convert_workspace(db_session, ws.id, "USD")
    db_session.commit()
    db_session.refresh(tx)

    assert tx.total_amount == Decimal("20.00")
    assert tx.currency == "USD"
    # A proveniência deixou de fazer sentido: o valor já ESTÁ na moeda original
    assert tx.original_currency is None
    assert tx.exchange_rate is None


def test_renda_tambem_e_convertida(db_session: Session):
    users, ws = _workspace(db_session, "bc5", n_users=1)
    db_session.add(Income(
        title="Salário", amount=Decimal("5000.00"), currency="BRL",
        received_at=OCC, workspace_id=ws.id, user_id=users[0].id,
    ))
    db_session.commit()

    BaseCurrencyService.convert_workspace(db_session, ws.id, "USD")
    db_session.commit()

    income = db_session.exec(select(Income).where(Income.workspace_id == ws.id)).one()
    assert income.amount == Decimal("1000.00")
    assert income.currency == "USD"


def test_conta_de_pagamento_acompanha_a_moeda_base(db_session: Session):
    """A conta não tem saldo, mas tem o RÓTULO da moeda — e ele ficava para trás.

    A criação já respeita `resolve_currency` (nasce na base), então depois da
    troca a conta era a única coisa da tela ainda dizendo a moeda antiga.
    """
    from app.models.payment_account import PaymentAccount

    users, ws = _workspace(db_session, "bc-acc", n_users=1)
    db_session.add(PaymentAccount(
        name="Corrente", currency="BRL", workspace_id=ws.id, owner_user_id=users[0].id
    ))
    db_session.commit()

    relatorio = BaseCurrencyService.convert_workspace(db_session, ws.id, "USD")
    db_session.commit()

    conta = db_session.exec(
        select(PaymentAccount).where(PaymentAccount.workspace_id == ws.id)
    ).one()
    assert conta.currency == "USD"
    assert relatorio.as_dict()["accounts"] == 1


# --- tudo ou nada -----------------------------------------------------------


def test_falta_de_cotacao_aborta_sem_escrever(db_session: Session):
    """Meia conversão deixaria o workspace sem interpretação: é tudo ou nada."""
    users, ws = _workspace(db_session, "bc6", n_users=1)
    # Lançamento numa data MUITO anterior, fora da janela de fallback do store
    tx = Transaction(
        title="Antigo", total_amount=Decimal("100.00"), currency="BRL",
        transaction_date=datetime(2020, 1, 15, tzinfo=UTC), billing_month="2020-01",
        workspace_id=ws.id, status=TransactionStatus.confirmed,
    )
    db_session.add(tx)
    db_session.commit()

    with pytest.raises(MissingRates) as exc:
        BaseCurrencyService.convert_workspace(db_session, ws.id, "USD")
    assert exc.value.missing

    db_session.rollback()
    db_session.refresh(tx)
    assert tx.total_amount == Decimal("100.00")
    assert tx.currency == "BRL"


def test_dry_run_nao_escreve(db_session: Session):
    users, ws = _workspace(db_session, "bc7", n_users=1)
    tx = _tx(db_session, ws.id, "100.00")
    db_session.commit()

    report = BaseCurrencyService.plan_conversion(db_session, ws.id, "USD")
    db_session.commit()
    db_session.refresh(tx)

    assert report.transactions == 1
    assert report.from_currency == "BRL"
    assert report.to_currency == "USD"
    assert tx.total_amount == Decimal("100.00"), "dry-run não pode escrever"


def test_mesma_moeda_e_no_op(db_session: Session):
    _users, ws = _workspace(db_session, "bc8", n_users=1)
    report = BaseCurrencyService.plan_conversion(db_session, ws.id, "BRL")
    assert report.transactions == 0
    assert report.missing_rates == []
