"""Recorrência materializa despesa COMPLETA (REC-001, ADR 0012): pagador +
divisão + categoria, frequência diária, occurrence_date e escopos de edição."""
from datetime import date
from decimal import Decimal

from sqlmodel import select

from app.models.recurring import RecurringExpense, RecurrenceFrequency
from app.models.transaction import Transaction, TransactionStatus
from app.models.workspace import WorkspaceMembership, WorkspaceRole
from app.services.recurring_service import RecurringService
from app.services.debt_service import DebtService


def _template(db, ws_id, creator_id, **kw):
    kw.setdefault("frequency", RecurrenceFrequency.monthly)
    kw.setdefault("day_of_month", 5)
    t = RecurringExpense(
        title="Aluguel", base_amount=Decimal("100.00"),
        workspace_id=ws_id, created_by_user_id=creator_id, **kw,
    )
    db.add(t)
    db.commit()
    db.refresh(t)
    return t


def _instance(db, template_id):
    return db.exec(
        select(Transaction).where(Transaction.recurring_expense_id == template_id)
    ).first()


def test_instancia_nasce_completa(db_session, setup_data):
    ws, u1 = setup_data["ws1"], setup_data["u1"]
    t = _template(db_session, ws.id, u1.id)
    created = RecurringService.generate_due_instances(db_session, ws.id, date(2026, 3, 10), horizonte_meses=0)
    db_session.commit()

    assert created == 1
    tx = _instance(db_session, t.id)
    # NÃO é nua: tem pagador e divisão → entra em dívidas/relatórios
    assert len(tx.payers) == 1
    assert len(tx.splits) == 1
    assert tx.payers[0].user_id == u1.id
    assert tx.occurrence_date == date(2026, 3, 5)


def test_split_snapshot_entra_nas_dividas(db_session, setup_data):
    ws, u1, u2 = setup_data["ws1"], setup_data["u1"], setup_data["u2"]
    db_session.add(WorkspaceMembership(workspace_id=ws.id, user_id=u2.id, role=WorkspaceRole.member))
    db_session.commit()
    _template(
        db_session, ws.id, u1.id,
        payer_user_id=u1.id,
        split_snapshot=[
            {"user_id": u1.id, "split_method": "percentage", "input_value": "50"},
            {"user_id": u2.id, "split_method": "percentage", "input_value": "50"},
        ],
    )
    RecurringService.generate_due_instances(db_session, ws.id, date(2026, 3, 10), horizonte_meses=0)
    db_session.commit()

    debts = DebtService.get_workspace_debts(db_session, ws.id)
    assert any(
        d["debtor_id"] == u2.id and d["creditor_id"] == u1.id and d["amount"] == Decimal("50.00")
        for d in debts
    ), debts


def test_frequencia_diaria(db_session, setup_data):
    ws, u1 = setup_data["ws1"], setup_data["u1"]
    _template(db_session, ws.id, u1.id, frequency=RecurrenceFrequency.daily)
    created = RecurringService.generate_due_instances(db_session, ws.id, date(2026, 3, 4), horizonte_meses=0)
    db_session.commit()
    assert created == 31  # março inteiro
    # Re-rodar é idempotente (dedup por occurrence_date)
    again = RecurringService.generate_due_instances(db_session, ws.id, date(2026, 3, 4), horizonte_meses=0)
    db_session.commit()
    assert again == 0

    # Só os dias 1..4 já venceram; o resto do mês fica pendente (fora dos totais)
    txs = db_session.exec(select(Transaction).where(Transaction.workspace_id == ws.id)).all()
    assert sum(1 for t in txs if t.status == TransactionStatus.confirmed) == 4
    assert sum(1 for t in txs if t.status == TransactionStatus.pending) == 27


def test_escopo_all_reaplica_valor_e_divisao(db_session, setup_data):
    ws, u1 = setup_data["ws1"], setup_data["u1"]
    t = _template(db_session, ws.id, u1.id)
    RecurringService.generate_due_instances(db_session, ws.id, date(2026, 3, 10), horizonte_meses=0)
    db_session.commit()

    t.base_amount = Decimal("200.00")
    db_session.add(t)
    db_session.commit()
    RecurringService.sync_unpaid_instances(db_session, t.id, "all")
    db_session.commit()

    db_session.expire_all()
    tx = _instance(db_session, t.id)
    assert tx.total_amount == Decimal("200.00")
    assert tx.payers[0].amount == Decimal("200.00")
    assert tx.splits[0].computed_amount == Decimal("200.00")


def test_escopo_none_nao_altera(db_session, setup_data):
    ws, u1 = setup_data["ws1"], setup_data["u1"]
    t = _template(db_session, ws.id, u1.id)
    RecurringService.generate_due_instances(db_session, ws.id, date(2026, 3, 10), horizonte_meses=0)
    db_session.commit()

    t.base_amount = Decimal("999.00")
    db_session.add(t)
    db_session.commit()
    RecurringService.sync_unpaid_instances(db_session, t.id, "none")
    db_session.commit()

    db_session.expire_all()
    tx = _instance(db_session, t.id)
    assert tx.total_amount == Decimal("100.00")  # intocada


def test_tombstone_nao_ressuscita(db_session, setup_data):
    ws, u1 = setup_data["ws1"], setup_data["u1"]
    t = _template(db_session, ws.id, u1.id, frequency=RecurrenceFrequency.daily)
    RecurringService.generate_due_instances(db_session, ws.id, date(2026, 3, 3), horizonte_meses=0)
    db_session.commit()

    # Exclui uma ocorrência (tombstone): a linha permanece com deleted_at
    tx = _instance(db_session, t.id)
    from datetime import datetime, UTC
    tx.deleted_at = datetime.now(UTC)
    db_session.add(tx)
    db_session.commit()

    again = RecurringService.generate_due_instances(db_session, ws.id, date(2026, 3, 3), horizonte_meses=0)
    db_session.commit()
    assert again == 0  # nenhuma ressuscita (dedup inclui excluídas)
