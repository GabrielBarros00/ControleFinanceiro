"""Bordas de integridade do caixa efetivo (ADR 0022).

Três defeitos que a auditoria encontrou, todos com a mesma origem: o caixa era um
punhado de agregações independentes, cada uma com o seu `SUM` e o seu filtro.

1. **Arquivar reescrevia o passado.** As consultas filtravam
   `CreditCard.deleted_at` / `Financing.deleted_at`, então excluir o cadastro
   apagava retroativamente pagamentos que já tinham acontecido.
2. **A dedup da parcela ignorava o status.** Cancelar a despesa vinculada tirava
   a saída dos DOIS lados — a transação pelo status, a parcela por "existe uma
   transação".
3. **O câmbio usava o dia 1º do mês.** USD 100 pagos no dia 25 entravam pela
   cotação do dia 1.
"""
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from sqlmodel import Session

from app.models.credit_card import CardStatement, CreditCard, StatementPayment, StatementStatus
from app.models.exchange_rate import ExchangeRate
from app.models.financing import (
    AmortizationInstallment,
    AmortizationMethod,
    Financing,
    FinancingStatus,
)
from app.models.transaction import (
    SplitMethod,
    Transaction,
    TransactionPayer,
    TransactionSplit,
    TransactionStatus,
)
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMembership, WorkspaceRole
from app.services.overview_service import OverviewService

JULHO = date(2026, 7, 1)
DIA_25 = datetime(2026, 7, 25, 15, 0)


@pytest.fixture(name="cena")
def cena_fixture(db_session: Session):
    user = User(name="Dona", email="caixa-integridade@t.com", password_hash="h")
    db_session.add(user)
    workspace = Workspace(name="WS-integridade", base_currency="BRL")
    db_session.add(workspace)
    db_session.flush()
    db_session.add(WorkspaceMembership(
        workspace_id=workspace.id, user_id=user.id, role=WorkspaceRole.owner
    ))
    db_session.commit()
    return {"ws_id": workspace.id, "user_id": user.id}


def _caixa(db_session, cena, moeda="BRL") -> dict:
    return OverviewService.get_overview(
        db_session, cena["user_id"], JULHO, currency=moeda, com_acertos=False
    )


def _cartao_com_fatura_paga(db_session, cena, moeda="BRL", valor="300.00", quando=DIA_25):
    card = CreditCard(
        name="Nubank", limit=Decimal("5000.00"), closing_day=25, due_day=5,
        currency=moeda, owner_user_id=cena["user_id"],
    )
    db_session.add(card)
    db_session.flush()
    statement = CardStatement(
        card_id=card.id, month="2026-07", status=StatementStatus.paid,
        closing_date=datetime(2026, 7, 25), due_date=datetime(2026, 8, 5),
        total_amount=Decimal(valor),
    )
    db_session.add(statement)
    db_session.flush()
    db_session.add(StatementPayment(
        statement_id=statement.id, amount=Decimal(valor), paid_at=quando,
    ))
    db_session.commit()
    return card


def _financiamento_com_parcela_paga(db_session, cena, valor="400.00"):
    financing = Financing(
        title="Imóvel", total_amount=Decimal("4000.00"), interest_rate=Decimal("0.01"),
        start_date=date(2026, 1, 1), installments_count=10,
        method=AmortizationMethod.SAC, status=FinancingStatus.active,
        currency="BRL", owner_user_id=cena["user_id"],
    )
    db_session.add(financing)
    db_session.flush()
    parcela = AmortizationInstallment(
        financing_id=financing.id, installment_number=1, due_date=date(2026, 7, 10),
        principal_amount=Decimal("350.00"), interest_amount=Decimal("50.00"),
        total_amount=Decimal(valor), remaining_balance=Decimal("3600.00"),
        is_paid=True, paid_at=DIA_25,
    )
    db_session.add(parcela)
    db_session.commit()
    return financing, parcela


# --- 1. Arquivar não reescreve o passado -----------------------------------


def test_arquivar_cartao_preserva_o_caixa_ja_registrado(db_session, cena):
    card = _cartao_com_fatura_paga(db_session, cena)
    antes = _caixa(db_session, cena)["cash_out_breakdown"]["statement_payments"]
    assert antes == Decimal("300.00")

    card.deleted_at = datetime.now(UTC)
    db_session.add(card)
    db_session.commit()

    depois = _caixa(db_session, cena)["cash_out_breakdown"]["statement_payments"]
    assert depois == Decimal("300.00"), "arquivar o cartão apagou um pagamento já feito"


def test_arquivar_financiamento_preserva_o_caixa_ja_registrado(db_session, cena):
    financing, _parcela = _financiamento_com_parcela_paga(db_session, cena)
    antes = _caixa(db_session, cena)["cash_out_breakdown"]["financing_installments"]
    assert antes == Decimal("400.00")

    financing.deleted_at = datetime.now(UTC)
    db_session.add(financing)
    db_session.commit()

    depois = _caixa(db_session, cena)["cash_out_breakdown"]["financing_installments"]
    assert depois == Decimal("400.00"), "arquivar o financiamento apagou uma parcela paga"


# --- 2. Dedup da parcela considera o status --------------------------------


def _despesa_vinculada(db_session, cena, parcela, status=TransactionStatus.confirmed,
                       settled_at=DIA_25):
    tx = Transaction(
        title="Parcela 1/10", total_amount=parcela.total_amount,
        transaction_date=DIA_25, billing_month="2026-07", currency="BRL",
        workspace_id=cena["ws_id"], created_by_user_id=cena["user_id"],
        status=status, financing_installment_id=parcela.id,
        # Liquidada por padrão, como a rota de pagar parcela a cria (ADR 0029).
        # `settled_at=None` é o caso da conta a pagar — ver o teste da parcela
        # que volta ao caixa quando a despesa vinculada não conta.
        settled_at=settled_at,
    )
    db_session.add(tx)
    db_session.flush()
    db_session.add(TransactionPayer(
        transaction_id=tx.id, user_id=cena["user_id"], amount=parcela.total_amount
    ))
    db_session.add(TransactionSplit(
        transaction_id=tx.id, user_id=cena["user_id"], split_method=SplitMethod.equal,
        input_value=Decimal("100"), computed_amount=parcela.total_amount,
    ))
    db_session.commit()
    return tx


def test_despesa_vinculada_viva_suprime_a_parcela(db_session, cena):
    """A regra do ADR 0022: quando a despesa conta, a parcela não conta."""
    _financing, parcela = _financiamento_com_parcela_paga(db_session, cena)
    _despesa_vinculada(db_session, cena, parcela)

    caixa = _caixa(db_session, cena)["cash_out_breakdown"]
    assert caixa["financing_installments"] == Decimal("0.00")
    assert caixa["transactions"] == Decimal("400.00")
    assert _caixa(db_session, cena)["cash_out"] == Decimal("400.00")


def test_cancelar_a_despesa_vinculada_devolve_a_parcela_ao_caixa(db_session, cena):
    """O defeito: a saída sumia dos dois lados.

    A transação cancelada cai do caixa pelo status, e a parcela caía porque a
    dedup só perguntava "existe uma transação vinculada?" — sem olhar se ela
    ainda representa uma saída.
    """
    _financing, parcela = _financiamento_com_parcela_paga(db_session, cena)
    tx = _despesa_vinculada(db_session, cena, parcela)

    tx.status = TransactionStatus.cancelled
    db_session.add(tx)
    db_session.commit()

    caixa = _caixa(db_session, cena)
    assert caixa["cash_out_breakdown"]["transactions"] == Decimal("0.00")
    assert caixa["cash_out_breakdown"]["financing_installments"] == Decimal("400.00")
    assert caixa["cash_out"] == Decimal("400.00"), "a saída desapareceu dos dois lados"


def test_despesa_vinculada_nao_liquidada_devolve_a_parcela_ao_caixa(db_session, cena):
    """A mesma armadilha do teste acima, pela porta que o ADR 0029 abriu.

    Desde a liquidação, a despesa vinculada só é saída de caixa quando tem
    `settled_at`. Se a dedup continuasse perguntando só por status, desmarcar o
    pagamento dela a tiraria da fonte 1 e ela ainda assim suprimiria a parcela —
    a saída sumiria dos dois lados de novo, agora sem ninguém ter cancelado nada.
    """
    _financing, parcela = _financiamento_com_parcela_paga(db_session, cena)
    _despesa_vinculada(db_session, cena, parcela, settled_at=None)

    caixa = _caixa(db_session, cena)
    assert caixa["cash_out_breakdown"]["transactions"] == Decimal("0.00")
    assert caixa["cash_out_breakdown"]["financing_installments"] == Decimal("400.00")
    assert caixa["cash_out"] == Decimal("400.00"), "a saída desapareceu dos dois lados"


# --- 3. Câmbio pela data EFETIVA -------------------------------------------


def test_conversao_usa_a_cotacao_do_dia_do_movimento(db_session, cena):
    """USD 100 pagos no dia 25, com o dólar a 5 no dia 1 e a 6 no dia 25.

    Convertendo pelo dia 1º (o que o caixa fazia) dá R$ 500; pela data efetiva,
    R$ 600. O contrato do ADR 0022 sempre foi "cada fonte com a sua data
    efetiva".
    """
    db_session.add_all([
        ExchangeRate(currency="USD", rate_date=date(2026, 7, 1),
                     rate=Decimal("5.000000"), source="ptax"),
        ExchangeRate(currency="USD", rate_date=date(2026, 7, 25),
                     rate=Decimal("6.000000"), source="ptax"),
    ])
    db_session.commit()

    _cartao_com_fatura_paga(db_session, cena, moeda="USD", valor="100.00", quando=DIA_25)

    caixa = _caixa(db_session, cena, moeda="BRL")
    assert caixa["cash_out_breakdown"]["statement_payments"] == Decimal("600.00")
    assert caixa["excluded_foreign_count"] == 0


def test_sem_cotacao_na_data_o_movimento_fica_de_fora_e_e_contado(db_session, cena):
    """A política do ADR 0006 continua valendo por linha: omitir E avisar."""
    _cartao_com_fatura_paga(db_session, cena, moeda="USD", valor="100.00", quando=DIA_25)

    caixa = _caixa(db_session, cena, moeda="BRL")
    assert caixa["cash_out_breakdown"]["statement_payments"] == Decimal("0.00")
    assert caixa["excluded_foreign_count"] == 1
