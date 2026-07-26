"""Expurgo das tabelas de crescimento monotônico.

Nenhuma delas tinha rotina de limpeza, e todas crescem sozinhas:

- `auditlog`   — uma linha por escrita de QUALQUER modelo;
- `syncevent`  — uma linha por evento de tempo real;
- `refreshsession` — uma linha a cada refresh (~a cada 30 min por usuário ativo).

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

from sqlalchemy import func  # noqa: E402
from sqlmodel import Session, select  # noqa: E402

from app.db.engine import engine  # noqa: E402
from app.models.audit import AuditLog  # noqa: E402
from app.models.refresh_session import RefreshSession  # noqa: E402
from app.models.sync_event import SyncEvent  # noqa: E402
from app.services.session_service import purge_expired_sessions  # noqa: E402

DEFAULT_DAYS = 180


def _count_older(session: Session, model, column, cutoff) -> int:
    return session.exec(select(func.count(model.id)).where(column < cutoff)).one()


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
        print(f"  auditlog       : {audit}")
        print(f"  syncevent      : {events}")
        print(f"  refreshsession : {sessions}")

        if dry_run:
            return 0

        for row in session.exec(select(AuditLog).where(AuditLog.created_at < cutoff)).all():
            session.delete(row)
        for row in session.exec(select(SyncEvent).where(SyncEvent.created_at < cutoff)).all():
            session.delete(row)
        purge_expired_sessions(session, older_than_days=days)
        session.commit()

    print("Concluído.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
