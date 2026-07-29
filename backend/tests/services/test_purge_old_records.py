"""Expurgo das tabelas de crescimento monotônico (scripts/purge_old_records.py).

Duas garantias, as duas com histórico:

1. O expurgo apaga **no banco** (DELETE em massa), não carregando as linhas na
   memória do processo. Justamente nestas tabelas — uma linha de `auditlog` por
   escrita de qualquer modelo, uma de `syncevent` por evento de tempo real — o
   caminho antigo (SELECT tudo + `session.delete()` linha a linha) virava um
   SELECT de milhões de linhas dentro do container `cron`.
2. `importrow`/`importbatch` entram no expurgo. Um único import já traz
   `IMPORT_MAX_ROWS` linhas e nada nunca as removia.
"""
from datetime import datetime, timedelta, UTC
from decimal import Decimal

from sqlmodel import Session, select

from app.models.audit import AuditLog, ActionType
from app.models.import_batch import ImportBatch, ImportRow, ImportRowStatus
from app.models.sync_event import SyncEvent

from scripts.purge_old_records import _count_older, _delete_older


def _velho(dias: int) -> datetime:
    return datetime.now(UTC) - timedelta(days=dias)


def test_expurgo_remove_so_o_que_passou_do_corte(db_session: Session, seed_ws):
    ws_id = seed_ws["ws"].id
    corte = datetime.now(UTC) - timedelta(days=180)

    db_session.add_all([
        AuditLog(action=ActionType.create, resource_type="Transaction",
                 workspace_id=ws_id, created_at=_velho(300)),
        AuditLog(action=ActionType.create, resource_type="Transaction",
                 workspace_id=ws_id, created_at=_velho(10)),
        SyncEvent(workspace_id=ws_id, seq=1, event_type="transaction.created",
                  created_at=_velho(300)),
        SyncEvent(workspace_id=ws_id, seq=2, event_type="transaction.created",
                  created_at=_velho(10)),
    ])
    db_session.commit()

    # (O próprio fixture já cria linhas de auditoria RECENTES ao gravar
    #  User/Workspace — por isso as asserções são sobre o CORTE, não sobre o total.)
    assert _count_older(db_session, AuditLog, AuditLog.created_at, corte) == 1
    assert _count_older(db_session, SyncEvent, SyncEvent.created_at, corte) == 1

    assert _delete_older(db_session, AuditLog, AuditLog.created_at, corte) == 1
    assert _delete_older(db_session, SyncEvent, SyncEvent.created_at, corte) == 1
    db_session.commit()

    # Nada antigo sobrou...
    assert _count_older(db_session, AuditLog, AuditLog.created_at, corte) == 0
    assert _count_older(db_session, SyncEvent, SyncEvent.created_at, corte) == 0
    # ...e o recente sobreviveu: o expurgo não é "apague a trilha"
    assert db_session.exec(
        select(SyncEvent).where(SyncEvent.seq == 2)
    ).first() is not None
    assert len(db_session.exec(select(AuditLog)).all()) >= 1


def test_expurgo_alcanca_as_tabelas_de_importacao(db_session: Session, seed_ws):
    """Um import de 5.000 linhas deixava 5.001 linhas para sempre."""
    ws_id, user_id = seed_ws["ws"].id, seed_ws["user"].id
    corte = datetime.now(UTC) - timedelta(days=180)

    lote = ImportBatch(
        workspace_id=ws_id, filename="extrato.csv", created_by_user_id=user_id,
        total_rows=2, created_at=_velho(300),
    )
    db_session.add(lote)
    db_session.flush()
    db_session.add_all([
        ImportRow(batch_id=lote.id, workspace_id=ws_id, line=i, title=f"Linha {i}",
                  amount=Decimal("10.00"), transaction_date=_velho(300),
                  fingerprint=f"fp{i}", status=ImportRowStatus.imported,
                  created_at=_velho(300))
        for i in range(2)
    ])
    db_session.commit()

    assert _count_older(db_session, ImportRow, ImportRow.created_at, corte) == 2
    assert _count_older(db_session, ImportBatch, ImportBatch.created_at, corte) == 1

    # Filhas antes das mães: ImportRow referencia ImportBatch (FK no Postgres)
    _delete_older(db_session, ImportRow, ImportRow.created_at, corte)
    _delete_older(db_session, ImportBatch, ImportBatch.created_at, corte)
    db_session.commit()

    assert db_session.exec(select(ImportRow)).all() == []
    assert db_session.exec(select(ImportBatch)).all() == []
