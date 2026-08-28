"""Avisa quem tem conta chegando no vencimento (ADR 0033).

Uso (da raiz do backend, com o .env carregado):
    python scripts/avisar_vencimentos.py             # respeita a hora do aviso
    python scripts/avisar_vencimentos.py --agora     # ignora a hora (teste)
    python scripts/avisar_vencimentos.py --dia 2026-09-01   # finge outro dia

## Por que ele roda de HORA em hora e desiste sozinho

O ramo diário do serviço `cron` dispara "24h depois que o contêiner subiu" — ou
seja, numa hora que depende de quando houve o último deploy. Para expurgo tanto
faz. Para notificação não: "sua conta vence hoje" às 3 da manhã acorda a pessoa e
queima o canal para sempre.

Então o laço do compose chama isto a cada hora e QUEM decide é o script: fora da
`DUE_REMINDER_HOUR` (hora local, no `APP_TIMEZONE`), ele sai sem tocar no banco.

Rodar duas vezes na mesma hora — restart, deploy, laço adiantado — é seguro: a
restrição de unicidade de `duereminder` é quem garante isso, não este arquivo.
"""
import argparse
import sys
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import structlog  # noqa: E402
from sqlmodel import Session  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.db.engine import engine  # noqa: E402
from app.domain.dates import app_tz, today_local  # noqa: E402

logger = structlog.get_logger("avisar_vencimentos")


def main() -> int:
    parser = argparse.ArgumentParser(description="Aviso de vencimento (ADR 0033)")
    parser.add_argument(
        "--agora", action="store_true",
        help="roda mesmo fora da hora configurada (para teste manual)",
    )
    parser.add_argument(
        "--dia", type=str, default=None,
        help="finge que hoje é esta data (AAAA-MM-DD), para teste",
    )
    args = parser.parse_args()

    agora_local = datetime.now(app_tz())
    if not args.agora and agora_local.hour != settings.DUE_REMINDER_HOUR:
        # Silencioso de propósito: isto acontece 23 vezes por dia, e logar em
        # cada uma afogaria o log do serviço no ruído de não fazer nada.
        return 0

    hoje = date.fromisoformat(args.dia) if args.dia else today_local()

    # Importado aqui, e não no topo: o módulo puxa metade dos models, e num
    # processo que sai em 5ms nas 23 horas em que não faz nada isso é trabalho
    # jogado fora.
    from app.services.due_reminder_service import processar_todos  # noqa: E402

    with Session(engine) as db:
        resumo = processar_todos(db, hoje)

    logger.info("aviso_de_vencimento", dia=str(hoje), **resumo)
    print(
        f"[aviso] {hoje}: {resumo['avisadas']} pessoa(s) avisada(s), "
        f"{resumo['obrigacoes']} obrigação(ões), de {resumo['pessoas']} conta(s)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
