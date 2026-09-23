"""Totais e saldos de fatura EM LOTE: o mesmo número, com consultas fixas.

`effective_total` e `statement_balance` fazem um SUM por fatura. A visão do mês,
a projeção, o limite do cartão e as tools do MCP percorrem o histórico inteiro, e
o custo crescia com a idade do cartão: 18 meses de dois cartões davam ~70
consultas numa chamada só do `accounts_list`. As versões em lote
(`effective_totals`, `balances`) respondem com um GROUP BY.

Dois contratos:
1. o lote devolve EXATAMENTE o que o cálculo fatura a fatura devolve, inclusive nos
   casos que já custaram defeito (fechada com total congelado, pagamento parcial,
   compra fora da moeda do cartão);
2. o número de consultas não cresce com o número de faturas.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import event
from sqlalchemy.engine import Engine

from app.domain.dates import today_local
from app.models.credit_card import CardStatement, CreditCard, StatementPayment, StatementStatus
from app.models.transaction import Transaction, TransactionStatus
from app.models.user import User
from app.models.workspace import Workspace
from app.services.credit_card_service import CreditCardService
from app.services.overview_service import OverviewService
from app.services.projection_service import ProjectionService


def _base(db, email: str = "ana@example.com"):
    dono = User(name="Ana", email=email, password_hash="x", needs_onboarding=False)
    db.add(dono)
    db.commit()
    ws = Workspace(name="Casa", created_by_user_id=dono.id)
    cartao = CreditCard(name="Nubank", limit=Decimal("5000.00"), closing_day=3, due_day=10,
                        owner_user_id=dono.id, currency="BRL")
    db.add_all([ws, cartao])
    db.commit()
    return dono, ws, cartao


def _fatura(db, cartao, mes: str, status: StatementStatus, total_congelado: str = "0.00") -> CardStatement:
    ano, m = (int(p) for p in mes.split("-"))
    fechamento = datetime(ano, m, 3, 12, tzinfo=UTC)
    f = CardStatement(card_id=cartao.id, month=mes, closing_date=fechamento,
                      due_date=fechamento + timedelta(days=7), status=status,
                      total_amount=Decimal(total_congelado))
    db.add(f)
    db.commit()
    return f


def _compra(db, ws, dono, fatura, valor: str, *, moeda_da_fatura: str = "BRL",
            status: TransactionStatus = TransactionStatus.confirmed, apagada: bool = False):
    db.add(Transaction(
        workspace_id=ws.id, created_by_user_id=dono.id, title="compra", total_amount=Decimal(valor),
        currency="BRL", transaction_date=fatura.closing_date - timedelta(days=5), status=status,
        credit_card_id=fatura.card_id, statement_id=fatura.id, statement_amount=Decimal(valor),
        statement_currency=moeda_da_fatura, deleted_at=datetime.now(UTC) if apagada else None,
    ))


def _pagamento(db, fatura, valor: str, *, apagado: bool = False):
    db.add(StatementPayment(statement_id=fatura.id, amount=Decimal(valor), paid_at=datetime.now(UTC),
                            deleted_at=datetime.now(UTC) if apagado else None))


def test_lote_devolve_o_mesmo_que_fatura_a_fatura(db_session):
    db = db_session
    dono, ws, cartao = _base(db)
    aberta = _fatura(db, cartao, "2026-06", StatementStatus.open)
    _compra(db, ws, dono, aberta, "100.10")
    _compra(db, ws, dono, aberta, "50.05")
    _compra(db, ws, dono, aberta, "999.99", status=TransactionStatus.draft)      # não realizada
    _compra(db, ws, dono, aberta, "777.00", apagada=True)                        # apagada
    _compra(db, ws, dono, aberta, "33.00", moeda_da_fatura="USD")                # fora da moeda do cartão
    _pagamento(db, aberta, "20.00")
    fechada = _fatura(db, cartao, "2026-05", StatementStatus.closed, total_congelado="300.00")
    _compra(db, ws, dono, fechada, "999.00")          # depois do fechamento: o congelado manda
    _pagamento(db, fechada, "100.00")
    _pagamento(db, fechada, "50.00", apagado=True)
    paga = _fatura(db, cartao, "2026-04", StatementStatus.paid, total_congelado="80.00")
    _pagamento(db, paga, "80.00")
    sobrepaga = _fatura(db, cartao, "2026-03", StatementStatus.closed, total_congelado="10.00")
    _pagamento(db, sobrepaga, "15.00")
    vazia = _fatura(db, cartao, "2026-07", StatementStatus.open)
    db.commit()

    faturas = [aberta, fechada, paga, sobrepaga, vazia]
    totais = CreditCardService.effective_totals(db, cartao, faturas)
    saldos = CreditCardService.balances(db, cartao, faturas)
    for f in faturas:
        assert totais[f.id] == CreditCardService.effective_total(db, f), f.month
        assert saldos[f.id] == CreditCardService.statement_balance(db, f), f.month
    assert totais[aberta.id] == Decimal("150.15")
    assert saldos[aberta.id] == Decimal("130.15")
    assert totais[fechada.id] == Decimal("300.00") and saldos[fechada.id] == Decimal("200.00")
    assert saldos[paga.id] == Decimal("0.00") and saldos[sobrepaga.id] == Decimal("0.00")
    assert totais[vazia.id] == Decimal("0.00")


def _conta_consultas(fn):
    n = {"q": 0}

    def conta(*_a, **_k):
        n["q"] += 1

    event.listen(Engine, "before_cursor_execute", conta)
    try:
        fn()
    finally:
        event.remove(Engine, "before_cursor_execute", conta)
    return n["q"]


def _historico(db, meses: int):
    dono, ws, cartao = _base(db, email=f"ana{meses}@example.com")
    hoje = today_local()
    for i in range(meses):
        ano, mes = divmod(hoje.year * 12 + hoje.month - 1 - i, 12)
        f = _fatura(db, cartao, f"{ano:04d}-{mes + 1:02d}", StatementStatus.open)
        _compra(db, ws, dono, f, "10.00")
        _pagamento(db, f, "1.00")
    db.commit()
    return dono, cartao


def _consultas_por_chamada(db, meses: int) -> dict[str, int]:
    dono, cartao = _historico(db, meses)
    hoje = today_local()
    return {
        "card_overview": _conta_consultas(lambda: CreditCardService.card_overview(db, cartao)),
        "get_commitments": _conta_consultas(lambda: OverviewService.get_commitments(db, dono.id)),
        "projecao": _conta_consultas(
            lambda: ProjectionService.ate_o_fim_do_mes(db, dono.id, hoje.replace(day=1), "BRL", Decimal("0"))
        ),
    }


def test_consultas_nao_crescem_com_o_historico(db_session):
    # Duas pessoas, cada uma com o seu cartão: 3 faturas e 15 faturas.
    poucas = _consultas_por_chamada(db_session, 3)
    muitas = _consultas_por_chamada(db_session, 15)
    assert muitas == poucas, f"3 faturas: {poucas}; 15 faturas: {muitas}"
