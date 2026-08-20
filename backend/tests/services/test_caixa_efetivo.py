"""Caixa efetivo: o dinheiro que se moveu, não o que foi assumido (ADR 0022).

O app chamava de "Saída de caixa" a soma dos `TransactionPayer` do mês de
faturamento, e a auditoria externa mostrou que o nome era falso. O caso é o mais
comum que existe:

    compra de R$ 300 no cartão em julho, fatura paga em 10 de agosto

Pelo número antigo, julho registrava R$ 300 "saídos do seu bolso" com o dinheiro
ainda na conta, e agosto — quando ele saiu de fato — não registrava nada. Também
não entravam: acerto enviado a outro membro, e parcela de financiamento paga sem
lançamento em workspace.

Estes testes fixam as seis fontes e, principalmente, o que NÃO pode ser contado
duas vezes.
"""
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from sqlmodel import Session

from app.models.credit_card import (
    CardStatement,
    CreditCard,
    StatementPayment,
    StatementStatus,
)
from app.models.financing import (
    AmortizationInstallment,
    Financing,
    FinancingStatus,
)
from app.models.income import Income
from app.models.settlement import Settlement
from app.models.transaction import (
    SplitMethod,
    Transaction,
    TransactionPayer,
    TransactionSplit,
)
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMembership, WorkspaceRole
from app.services.cashflow_service import CashFlowService
from app.services.overview_service import OverviewService

JULHO = date(2026, 7, 1)
AGOSTO = date(2026, 8, 1)


def _janela(mes: date):
    """Início/fim do mês, como `OverviewService` os calcula."""
    proximo = date(mes.year + 1, 1, 1) if mes.month == 12 else date(mes.year, mes.month + 1, 1)
    ultimo = proximo - timedelta(days=1)
    return (
        datetime.combine(mes, datetime.min.time()),
        datetime.combine(ultimo, datetime.max.time()),
    )


def _caixa(db, user_id: int, mes: date):
    inicio, fim = _janela(mes)
    return CashFlowService.get_month(db, user_id, mes, "BRL", inicio, fim)


@pytest.fixture(name="cenario")
def cenario_fixture(db_session: Session):
    alice = User(name="Alice", email="alice-caixa@test.com", password_hash="h",
                 report_currency="BRL")
    bob = User(name="Bob", email="bob-caixa@test.com", password_hash="h")
    ws = Workspace(name="Casa", base_currency="BRL")
    db_session.add_all([alice, bob, ws])
    db_session.commit()
    for quem in (alice, bob):
        db_session.refresh(quem)
    db_session.refresh(ws)
    for quem, papel in ((alice, WorkspaceRole.owner), (bob, WorkspaceRole.member)):
        db_session.add(WorkspaceMembership(
            workspace_id=ws.id, user_id=quem.id, role=papel
        ))
    db_session.commit()
    return {"alice": alice, "bob": bob, "ws": ws}


# ---------------------------------------------------------------------------
# O caso da auditoria: cartão em julho, fatura em agosto

def test_compra_no_cartao_so_vira_caixa_quando_a_fatura_e_paga(db_session, cenario):
    alice, ws = cenario["alice"], cenario["ws"]
    cartao = CreditCard(
        name="Nubank", limit=Decimal("5000.00"), closing_day=10, due_day=20,
        currency="BRL", owner_user_id=alice.id,
    )
    db_session.add(cartao)
    db_session.commit()
    db_session.refresh(cartao)

    fatura = CardStatement(
        month="2026-07", closing_date=datetime(2026, 7, 10, tzinfo=UTC),
        due_date=datetime(2026, 8, 10, tzinfo=UTC), status=StatementStatus.closed,
        total_amount=Decimal("300.00"), card_id=cartao.id,
    )
    db_session.add(fatura)
    db_session.flush()

    compra = Transaction(
        title="Tênis", total_amount=Decimal("300.00"), currency="BRL",
        transaction_date=datetime(2026, 7, 5, tzinfo=UTC), billing_month="2026-07",
        workspace_id=ws.id, created_by_user_id=alice.id,
        credit_card_id=cartao.id, statement_id=fatura.id,
    )
    db_session.add(compra)
    db_session.flush()
    db_session.add(TransactionPayer(
        transaction_id=compra.id, user_id=alice.id, amount=Decimal("300.00")
    ))
    db_session.commit()

    julho = _caixa(db_session, alice.id, JULHO)
    assert julho["cash_out"] == Decimal("0.00"), (
        "a compra no cartão saiu do caixa antes de o dinheiro sair da conta"
    )

    # A fatura é paga em agosto — é AÍ que o dinheiro sai.
    db_session.add(StatementPayment(
        statement_id=fatura.id, amount=Decimal("300.00"),
        paid_at=datetime(2026, 8, 10, 9, 0, tzinfo=UTC),
    ))
    db_session.commit()

    agosto = _caixa(db_session, alice.id, AGOSTO)
    assert agosto["cash_out"] == Decimal("300.00")
    assert agosto["cash_out_breakdown"]["statement_payments"] == Decimal("300.00")
    assert agosto["cash_out_breakdown"]["transactions"] == Decimal("0.00")
    # E julho continua zerado depois do pagamento: o caixa é do mês em que se moveu.
    assert _caixa(db_session, alice.id, JULHO)["cash_out"] == Decimal("0.00")


def test_pagamento_parcial_de_fatura_entra_pelo_valor_pago(db_session, cenario):
    """Cada `StatementPayment` é uma linha — o parcial entra sem tratamento especial."""
    alice = cenario["alice"]
    cartao = CreditCard(
        name="Itaú", limit=Decimal("5000.00"), closing_day=10, due_day=20,
        currency="BRL", owner_user_id=alice.id,
    )
    db_session.add(cartao)
    db_session.commit()
    db_session.refresh(cartao)
    fatura = CardStatement(
        month="2026-08", closing_date=datetime(2026, 8, 10, tzinfo=UTC),
        due_date=datetime(2026, 8, 20, tzinfo=UTC), status=StatementStatus.closed,
        total_amount=Decimal("500.00"), card_id=cartao.id,
    )
    db_session.add(fatura)
    db_session.flush()
    db_session.add_all([
        StatementPayment(statement_id=fatura.id, amount=Decimal("200.00"),
                         paid_at=datetime(2026, 8, 15, tzinfo=UTC)),
        StatementPayment(statement_id=fatura.id, amount=Decimal("120.00"),
                         paid_at=datetime(2026, 8, 25, tzinfo=UTC)),
    ])
    db_session.commit()

    agosto = _caixa(db_session, alice.id, AGOSTO)
    assert agosto["cash_out"] == Decimal("320.00")


# ---------------------------------------------------------------------------
# Acerto entre membros

def test_acerto_enviado_e_recebido_movem_caixa_dos_dois_lados(db_session, cenario):
    """O acerto era invisível para o caixa nas DUAS pontas."""
    alice, bob, ws = cenario["alice"], cenario["bob"], cenario["ws"]
    db_session.add(Settlement(
        workspace_id=ws.id, from_user_id=bob.id, to_user_id=alice.id,
        amount=Decimal("150.00"), settled_at=datetime(2026, 8, 5, tzinfo=UTC),
    ))
    db_session.commit()

    de_bob = _caixa(db_session, bob.id, AGOSTO)
    assert de_bob["cash_out"] == Decimal("150.00")
    assert de_bob["cash_out_breakdown"]["settlements_sent"] == Decimal("150.00")

    de_alice = _caixa(db_session, alice.id, AGOSTO)
    assert de_alice["cash_in"] == Decimal("150.00")
    assert de_alice["cash_in_breakdown"]["settlements_received"] == Decimal("150.00")
    assert de_alice["cash_out"] == Decimal("0.00")


# ---------------------------------------------------------------------------
# Financiamento: a regra de não contar duas vezes

def _financiamento_com_parcela_paga(db_session, alice, com_lancamento_em=None):
    fin = Financing(
        title="Apartamento", total_amount=Decimal("100000.00"),
        interest_rate=Decimal("0.010000"), installments_count=120,
        start_date=date(2026, 1, 1), currency="BRL",
        owner_user_id=alice.id, status=FinancingStatus.active,
    )
    db_session.add(fin)
    db_session.commit()
    db_session.refresh(fin)
    parcela = AmortizationInstallment(
        financing_id=fin.id, installment_number=8, due_date=date(2026, 8, 1),
        principal_amount=Decimal("600.00"), interest_amount=Decimal("200.00"),
        total_amount=Decimal("800.00"), remaining_balance=Decimal("90000.00"),
        is_paid=True, paid_at=datetime(2026, 8, 3, tzinfo=UTC),
    )
    db_session.add(parcela)
    db_session.flush()

    if com_lancamento_em is not None:
        tx = Transaction(
            title="Apartamento — Parcela 8/120", total_amount=Decimal("800.00"),
            currency="BRL", transaction_date=datetime(2026, 8, 1, tzinfo=UTC),
            billing_month="2026-08", workspace_id=com_lancamento_em,
            created_by_user_id=alice.id, financing_installment_id=parcela.id,
            # Liquidada, como a rota de pagar parcela a cria (ADR 0029): esta
            # despesa NASCE de um pagamento. Sem a data, ela fica fora do caixa e
            # a parcela volta a contar sozinha — que é o comportamento certo para
            # uma conta a pagar, e o errado para o que este teste descreve.
            settled_at=datetime(2026, 8, 1, tzinfo=UTC),
        )
        db_session.add(tx)
        db_session.flush()
        db_session.add(TransactionPayer(
            transaction_id=tx.id, user_id=alice.id, amount=Decimal("800.00")
        ))
        db_session.add(TransactionSplit(
            transaction_id=tx.id, user_id=alice.id, split_method=SplitMethod.fixed,
            input_value=Decimal("800.00"), computed_amount=Decimal("800.00"),
        ))
    db_session.commit()
    return fin


def test_parcela_sem_lancamento_conta_como_caixa(db_session, cenario):
    """Compromisso puramente pessoal: não há despesa em workspace nenhum, então a
    parcela é a única testemunha de que o dinheiro saiu."""
    alice = cenario["alice"]
    _financiamento_com_parcela_paga(db_session, alice)

    agosto = _caixa(db_session, alice.id, AGOSTO)
    assert agosto["cash_out"] == Decimal("800.00")
    assert agosto["cash_out_breakdown"]["financing_installments"] == Decimal("800.00")


def test_parcela_com_lancamento_nao_conta_duas_vezes(db_session, cenario):
    """Pagar a parcela informando um workspace cria uma despesa; contar as duas
    faria o caixa do mês dobrar."""
    alice, ws = cenario["alice"], cenario["ws"]
    _financiamento_com_parcela_paga(db_session, alice, com_lancamento_em=ws.id)

    agosto = _caixa(db_session, alice.id, AGOSTO)
    assert agosto["cash_out"] == Decimal("800.00"), "a parcela foi contada duas vezes"
    # E conta pelo LANÇAMENTO, que é o registro de referência quando existe.
    assert agosto["cash_out_breakdown"]["transactions"] == Decimal("800.00")
    assert agosto["cash_out_breakdown"]["financing_installments"] == Decimal("0.00")


# ---------------------------------------------------------------------------
# Entradas e o resultado

def test_renda_e_entrada_de_caixa(db_session, cenario):
    alice = cenario["alice"]
    db_session.add(Income(
        title="Salário", amount=Decimal("9000.00"), currency="BRL",
        received_at=datetime(2026, 8, 5, tzinfo=UTC), user_id=alice.id,
    ))
    db_session.commit()

    agosto = _caixa(db_session, alice.id, AGOSTO)
    assert agosto["income"] == Decimal("9000.00")
    assert agosto["cash_in"] == Decimal("9000.00")
    assert agosto["net_cash"] == Decimal("9000.00")


def test_net_cash_e_entrada_menos_saida(db_session, cenario):
    alice, bob, ws = cenario["alice"], cenario["bob"], cenario["ws"]
    db_session.add(Income(
        title="Salário", amount=Decimal("5000.00"), currency="BRL",
        received_at=datetime(2026, 8, 5, tzinfo=UTC), user_id=alice.id,
    ))
    db_session.add(Settlement(
        workspace_id=ws.id, from_user_id=alice.id, to_user_id=bob.id,
        amount=Decimal("200.00"), settled_at=datetime(2026, 8, 7, tzinfo=UTC),
    ))
    db_session.commit()

    agosto = _caixa(db_session, alice.id, AGOSTO)
    assert agosto["cash_in"] == Decimal("5000.00")
    assert agosto["cash_out"] == Decimal("200.00")
    assert agosto["net_cash"] == Decimal("4800.00")


# ---------------------------------------------------------------------------
# Série pessoal: o relatório global (ADR 0020 + 0022)

def test_serie_nao_recalcula_o_ledger_de_acertos_por_mes(db_session, cenario, monkeypatch):
    """`get_series` chama `get_overview` uma vez por mês do período, e o ledger de
    dívidas é GLOBAL — não muda com o mês pedido.

    Recalculá-lo por mês multiplicava por 12 uma varredura do histórico inteiro
    do workspace, para descartar o resultado: a série não expõe a pagar/receber.
    Medido com 2.160 lançamentos em 2 workspaces, era a diferença entre 400 ms e
    200 ms — num backend de UM worker, onde isso bloqueia todos os outros.
    """
    from app.services import overview_service as mod

    chamadas = []
    original = mod.DebtService.get_workspace_debts

    def espiao(db, workspace_id, viewer_user_id=None):
        chamadas.append(workspace_id)
        return original(db, workspace_id, viewer_user_id=viewer_user_id)

    monkeypatch.setattr(mod.DebtService, "get_workspace_debts", espiao)

    mod.OverviewService.get_series(
        db_session, cenario["alice"].id, months=6, currency="BRL"
    )
    assert chamadas == [], "a série recalculou o ledger de acertos"

    # E o overview normal continua calculando — quem lê a pagar/receber é ele.
    mod.OverviewService.get_overview(
        db_session, cenario["alice"].id, AGOSTO, currency="BRL"
    )
    assert chamadas, "o overview parou de calcular os acertos"


def test_serie_devolve_um_ponto_por_mes_pedido(db_session, cenario):
    serie = OverviewService.get_series(
        db_session, cenario["alice"].id, months=6, currency="BRL"
    )
    assert len(serie["months"]) == 6
    # Do mais antigo para o mais recente: é a ordem em que o gráfico desenha.
    assert serie["months"] == sorted(serie["months"], key=lambda m: m["month"])
    assert set(serie["totals"]) == {
        "income", "consumption", "result", "cash_in", "cash_out", "net_cash",
    }


def test_duas_parcelas_no_mesmo_mes_so_a_sem_lancamento_conta(db_session, cenario):
    """As duas situações no MESMO conjunto de dados.

    Os testes acima cobrem os dois casos em fixtures separadas — e é por isso que
    este existe: um `EXISTS` mal correlacionado (que perguntasse "há ALGUMA
    despesa ligada a ALGUMA parcela?" em vez de "a esta") passaria nos dois
    isoladamente e falharia aqui, descartando as duas parcelas ou nenhuma.
    """
    alice, ws = cenario["alice"], cenario["ws"]
    fin = Financing(
        title="Carro", total_amount=Decimal("50000.00"),
        interest_rate=Decimal("0.010000"), installments_count=24,
        start_date=date(2026, 1, 1), currency="BRL",
        owner_user_id=alice.id, status=FinancingStatus.active,
    )
    db_session.add(fin)
    db_session.commit()
    db_session.refresh(fin)

    parcelas = []
    for numero, valor in ((8, Decimal("500.00")), (9, Decimal("300.00"))):
        p = AmortizationInstallment(
            financing_id=fin.id, installment_number=numero, due_date=date(2026, 8, numero),
            principal_amount=valor, interest_amount=Decimal("0.00"),
            total_amount=valor, remaining_balance=Decimal("10000.00"),
            is_paid=True, paid_at=datetime(2026, 8, numero, tzinfo=UTC),
        )
        db_session.add(p)
        parcelas.append(p)
    db_session.flush()

    # Só a PRIMEIRA virou despesa num workspace.
    tx = Transaction(
        title="Carro — Parcela 8/24", total_amount=Decimal("500.00"), currency="BRL",
        transaction_date=datetime(2026, 8, 8, tzinfo=UTC), billing_month="2026-08",
        workspace_id=ws.id, created_by_user_id=alice.id,
        financing_installment_id=parcelas[0].id,
        # Liquidada, como a rota de pagar parcela a cria (ADR 0029).
        settled_at=datetime(2026, 8, 8, tzinfo=UTC),
    )
    db_session.add(tx)
    db_session.flush()
    db_session.add(TransactionPayer(
        transaction_id=tx.id, user_id=alice.id, amount=Decimal("500.00")
    ))
    db_session.commit()

    agosto = _caixa(db_session, alice.id, AGOSTO)
    quebra = agosto["cash_out_breakdown"]
    # 500 pelo lançamento + 300 pela parcela solta. Nem 1.300 (dobrando a 8ª)
    # nem 500 (descartando a 9ª junto).
    assert quebra["transactions"] == Decimal("500.00")
    assert quebra["financing_installments"] == Decimal("300.00")
    assert agosto["cash_out"] == Decimal("800.00")
