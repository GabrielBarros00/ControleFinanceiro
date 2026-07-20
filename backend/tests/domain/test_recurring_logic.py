from decimal import Decimal
from datetime import date
from sqlmodel import Session
from app.models.transaction import TransactionStatus
from app.models.recurring import RecurringExpense
from app.services.recurring_service import RecurringService
from app.models.workspace import Workspace

def test_recurring_generation_and_sync(db_session: Session):
    # Setup: Workspace e Template
    ws = Workspace(name="Home")
    db_session.add(ws)
    db_session.flush()
    
    template = RecurringExpense(
        title="Internet",
        base_amount=Decimal("100.00"),
        day_of_month=10,
        workspace_id=ws.id
    )
    db_session.add(template)
    db_session.commit()
    
    # 1. Gerar transação para o mês atual
    today = date.today()
    tx = RecurringService.get_or_create_monthly_instance(db_session, template.id, today.year, today.month)
    
    assert tx.total_amount == Decimal("100.00")
    assert tx.status == TransactionStatus.confirmed
    
    # 2. Alterar o template (Live Update)
    # Como a transação não está paga e é do mês corrente, deve atualizar
    template.base_amount = Decimal("110.00")
    db_session.add(template)
    db_session.commit()
    
    RecurringService.sync_unpaid_instances(db_session, template.id)
    db_session.refresh(tx)
    assert tx.total_amount == Decimal("110.00")
    
    # 3. Marcar como paga (Freeze)
    tx.status = TransactionStatus.paid
    db_session.add(tx)
    db_session.commit()
    
    # 4. Alterar template novamente - Não deve mudar a transação paga
    template.base_amount = Decimal("120.00")
    db_session.add(template)
    db_session.commit()
    
    RecurringService.sync_unpaid_instances(db_session, template.id)
    db_session.refresh(tx)
    assert tx.total_amount == Decimal("110.00") # Manteve o valor de quando foi pago

def test_historical_immutability(db_session: Session):
    ws = Workspace(name="Home")
    db_session.add(ws)
    db_session.flush()
    
    template = RecurringExpense(title="Rent", base_amount=Decimal("1000.00"), day_of_month=1, workspace_id=ws.id)
    db_session.add(template)
    db_session.commit()
    
    # Transação do mês passado (não paga, mas vencida)
    tx_old = RecurringService.get_or_create_monthly_instance(db_session, template.id, 2024, 1)
    
    # Alterar template hoje
    template.base_amount = Decimal("1100.00")
    db_session.add(template)
    db_session.commit()
    
    RecurringService.sync_unpaid_instances(db_session, template.id)
    db_session.refresh(tx_old)
    
    # Como o mês já passou, deve estar congelada mesmo que não esteja paga (regra de histórico)
    assert tx_old.total_amount == Decimal("1000.00")
