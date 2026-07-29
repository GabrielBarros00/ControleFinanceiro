"""Expurgo das tabelas de crescimento monotônico.

Nenhuma delas tinha rotina de limpeza, e todas crescem sozinhas:

- `auditlog`   — uma linha por escrita de QUALQUER modelo;
- `syncevent`  — uma linha por evento de tempo real;
- `refreshsession` — uma linha a cada refresh (~a cada 30 min por usuário ativo);
- `importrow`/`importbatch` — uma linha por linha de CSV importada (o teto por
  lote é IMPORT_MAX_ROWS, então um único import já traz milhares).

Uso (da raiz do backend, com o .env carregado):
    python scripts/purge_old_records.py [dias]          # padrão: 180
    python scripts/purge_old_records.py 180 --dry-run

Rode mensalmente via cron:
    0 4 1 * *  cd /app/backend && python scripts/purge_old_records.py 180
"""
import sys
from datetime import datetime, timedelta, UTC
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import delete, func  # noqa: E402
from sqlmodel import Session, select  # noqa: E402

from app.db.engine import engine  # noqa: E402
from app.models.audit import AuditLog  # noqa: E402
from app.models.import_batch import ImportBatch, ImportRow  # noqa: E402
from app.models.refresh_session import RefreshSession  # noqa: E402
from app.models.sync_event import SyncEvent  # noqa: E402
from app.services.session_service import purge_expired_sessions  # noqa: E402

DEFAULT_DAYS = 180


def _count_older(session: Session, model, column, cutoff) -> int:
    return session.exec(select(func.count(model.id)).where(column < cutoff)).one()


def _delete_older(session: Session, model, column, cutoff) -> int:
    """DELETE em massa, no banco.

    Antes isto carregava TODAS as linhas antigas na memória do processo e
    chamava `session.delete()` uma a uma — nas mesmas tabelas que o cabeçalho
    deste arquivo descreve como de crescimento monotônico. Num banco com meses
    de uso, o expurgo era um SELECT de milhões de linhas seguido de milhões de
    DELETEs pelo ORM, dentro do container `cron`.

    Delete pelo Core é seguro AQUI (e não em `delete_transaction_children`, por
    exemplo) porque nenhuma destas tabelas gera trilha de auditoria: `AuditLog` e
    `SyncEvent` estão em `_AUDIT_EXCLUDED`, e as de importação são histórico
    operacional, não financeiro.
    """
    return session.execute(delete(model).where(column < cutoff)).rowcount


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    dry_run = "--dry-run" in sys.argv
    days = int(args[0]) if args else DEFAULT_DAYS
    cutoff = datetime.now(UTC) - timedelta(days=days)

    print(f"Expurgo de registros anteriores a {cutoff.date().isoformat()} ({days} dias)")
    if dry_run:
        print("  [dry-run] nada será apagado")

    with Session(engine) as session:
        audit = _count_older(session, AuditLog, AuditLog.created_at, cutoff)
        events = _count_older(session, SyncEvent, SyncEvent.created_at, cutoff)
        sessions = _count_older(
            session, RefreshSession, RefreshSession.expires_at, cutoff
        )
        lotes = _count_older(session, ImportBatch, ImportBatch.created_at, cutoff)
        linhas = _count_older(session, ImportRow, ImportRow.created_at, cutoff)
        print(f"  auditlog       : {audit}")
        print(f"  syncevent      : {events}")
        print(f"  refreshsession : {sessions}")
        print(f"  importbatch    : {lotes}")
        print(f"  importrow      : {linhas}")

        if dry_run:
            return 0

        _delete_older(session, AuditLog, AuditLog.created_at, cutoff)
        _delete_older(session, SyncEvent, SyncEvent.created_at, cutoff)
        # Filhas antes das mães: ImportRow referencia ImportBatch (FK no Postgres)
        _delete_older(session, ImportRow, ImportRow.created_at, cutoff)
        _delete_older(session, ImportBatch, ImportBatch.created_at, cutoff)
        purge_expired_sessions(session, older_than_days=days)
        session.commit()

    print("Concluído.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
