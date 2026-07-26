"""Trilha de auditoria: segredos fora e payload sob controle (B7).

Os listeners são de Mapper e valem para TODO modelo. Duas consequências que
estavam abertas: colunas com segredo (token de convite, jti de sessão) eram
copiadas para `new_values`, e cada linha-filha de uma despesa gravava uma cópia
inteira de si mesma — uma despesa com 10 itens × 3 participantes gerava ~45
snapshots além da própria transação.
"""
from datetime import datetime, timedelta, UTC
from decimal import Decimal

from sqlmodel import Session, select

from app.core.audit_events import get_model_changes
from app.models.audit import AuditLog
from app.models.refresh_session import RefreshSession
from app.models.transaction import Transaction, TransactionSplit, SplitMethod
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceInvite, WorkspaceRole


def test_token_de_convite_nao_vai_para_a_trilha(db_session: Session):
    ws = Workspace(name="WS")
    db_session.add(ws)
    db_session.flush()
    invite = WorkspaceInvite(
        workspace_id=ws.id, email="x@t.com", role=WorkspaceRole.member,
        expires_at=datetime.now(UTC) + timedelta(days=7),
    )
    db_session.add(invite)
    db_session.commit()

    linhas = db_session.exec(
        select(AuditLog).where(AuditLog.resource_type == "WorkspaceInvite")
    ).all()
    assert linhas, "o convite deve continuar sendo auditado"
    for linha in linhas:
        assert "token" not in (linha.new_values or {}), "segredo de aceite vazou para a trilha"


def test_hash_de_senha_e_jti_ficam_de_fora():
    user = User(name="A", email="a@t.com", password_hash="hash-secreto")
    assert "password_hash" not in get_model_changes(user)

    sessao = RefreshSession(
        user_id=1, jti="jti-secreto", family_id="fam",
        expires_at=datetime.now(UTC) + timedelta(days=7),
    )
    assert "jti" not in get_model_changes(sessao)


def test_filha_e_auditada_sem_snapshot(db_session: Session):
    """A LINHA continua (delete_transaction_children conta com isso), mas sem a
    cópia da linha inteira — era o snapshot que pesava."""
    ws = Workspace(name="WS2")
    user = User(name="B", email="b@t.com", password_hash="h")
    db_session.add_all([ws, user])
    db_session.flush()
    tx = Transaction(
        title="Compra", total_amount=Decimal("10.00"), currency="BRL",
        workspace_id=ws.id, billing_month="2026-07",
    )
    db_session.add(tx)
    db_session.flush()
    db_session.add(TransactionSplit(
        transaction_id=tx.id, user_id=user.id, split_method=SplitMethod.equal,
        input_value=Decimal("0"), computed_amount=Decimal("10.00"),
    ))
    db_session.commit()

    split_logs = db_session.exec(
        select(AuditLog).where(AuditLog.resource_type == "TransactionSplit")
    ).all()
    assert split_logs, "a filha continua rastreada"
    assert all(log.new_values is None for log in split_logs)

    # A raiz mantém o snapshot completo: é por ela que se investiga
    tx_logs = db_session.exec(
        select(AuditLog).where(AuditLog.resource_type == "Transaction")
    ).all()
    assert tx_logs and tx_logs[0].new_values
    assert tx_logs[0].new_values["title"] == "Compra"
