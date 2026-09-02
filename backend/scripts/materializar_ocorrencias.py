"""Materializa recorrências e promove o que a data alcançou (ADR 0034).

Roda de hora em hora no serviço `cron` do Compose. Existe porque a materialização
preguiçosa — que roda quando alguém abre uma tela — **não pode ser o mecanismo
principal**:

- a conta do dia 1º do mês seguinte só passava a existir quando alguém abrisse o
  app já em setembro, e aí ela venceu no mesmo dia em que apareceu;
- o aviso de vencimento (`avisar_vencimentos.py`) não tem sobre o que avisar se a
  ocorrência ainda não foi criada — por isso este script roda ANTES dele no laço;
- num mês em que ninguém abre o app, o histórico simplesmente não acontece.

A materialização preguiçosa continua existindo, com o MESMO horizonte, como rede
de segurança: um app que se comporta diferente conforme o cron esteja rodando é
impossível de depurar.

**Idempotente pelo banco, não por consulta.** As uniques `uq_recurring_occurrence`
e `uq_recurring_income_occurrence` são a barreira real; `_create_instance_safe`
absorve a colisão num savepoint. Rodar duas vezes seguidas — ou junto com uma
requisição de leitura — não duplica nada. A promoção é `UPDATE ... WHERE` condicional,
que deixa o banco decidir quem promoveu.

**Uma falha não derruba o laço.** O `try/except` é POR ESPAÇO e POR PESSOA, com
`rollback` do escopo e log estruturado: um template com moeda sem cotação não pode
impedir a materialização das outras 40 casas.

Uso:

    python scripts/materializar_ocorrencias.py            # o horizonte padrão
    python scripts/materializar_ocorrencias.py --dry-run  # não grava nada
    python scripts/materializar_ocorrencias.py --horizonte 2
    python scripts/materializar_ocorrencias.py --user 7   # diagnóstico
    python scripts/materializar_ocorrencias.py --workspace 3

Sai com 0 quando tudo correu, 1 quando ao menos um escopo falhou — para o operador
poder encadear no cron e receber e-mail só no que importa.
"""
import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import structlog  # noqa: E402
from sqlmodel import Session, select  # noqa: E402

from app.db.engine import engine  # noqa: E402
from app.domain.dates import HORIZONTE_MESES, today_local  # noqa: E402
from app.models.user import User  # noqa: E402
from app.models.workspace import Workspace  # noqa: E402
from app.services.recurring_service import (  # noqa: E402
    RecurringIncomeService,
    RecurringService,
)

logger = structlog.get_logger("materializar_ocorrencias")


def _resumo() -> dict:
    return {
        "espacos": 0, "pessoas": 0,
        "despesas_criadas": 0, "rendas_criadas": 0,
        "despesas_promovidas": 0, "rendas_promovidas": 0,
        "falhas": 0,
    }


def _despesas(db: Session, hoje, horizonte: int, dry_run: bool, alvo, resumo: dict) -> None:
    """Um workspace por vez, com o erro isolado no escopo dele."""
    consulta = select(Workspace).where(Workspace.deleted_at.is_(None))
    if alvo is not None:
        consulta = consulta.where(Workspace.id == alvo)

    for ws in db.exec(consulta).all():
        resumo["espacos"] += 1
        try:
            criadas = RecurringService.generate_due_instances(
                db, ws.id, hoje,
                # `allow_fetch=True`: aqui NÃO é caminho de leitura. O cron pode
                # ir buscar cotação sem prender ninguém numa tela — é exatamente
                # o trabalho que tiramos do GET.
                allow_fetch=True,
                horizonte_meses=horizonte,
            )
            promovidas = RecurringService.promote_due_instances(db, ws.id, hoje)
            if dry_run:
                db.rollback()
            else:
                db.commit()
            resumo["despesas_criadas"] += criadas
            resumo["despesas_promovidas"] += promovidas
        except Exception:
            db.rollback()
            resumo["falhas"] += 1
            logger.exception("materializacao_falhou", escopo="despesa", workspace_id=ws.id)


def _rendas(db: Session, hoje, horizonte: int, dry_run: bool, alvo, resumo: dict) -> None:
    """Uma pessoa por vez — renda não tem workspace (ADR 0021)."""
    consulta = select(User).where(User.deleted_at.is_(None))
    if alvo is not None:
        consulta = consulta.where(User.id == alvo)

    for user in db.exec(consulta).all():
        resumo["pessoas"] += 1
        try:
            criadas = RecurringIncomeService.generate_due_income(
                db, user.id, hoje, allow_fetch=True, horizonte_meses=horizonte,
            )
            promovidas = RecurringIncomeService.promote_due_income(db, user.id, hoje)
            if dry_run:
                db.rollback()
            else:
                db.commit()
            resumo["rendas_criadas"] += criadas
            resumo["rendas_promovidas"] += promovidas
        except Exception:
            db.rollback()
            resumo["falhas"] += 1
            logger.exception("materializacao_falhou", escopo="renda", user_id=user.id)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--horizonte", type=int, default=HORIZONTE_MESES,
        help="quantos meses ALÉM do corrente materializar (padrão: %(default)s)",
    )
    parser.add_argument("--dry-run", action="store_true", help="não grava nada")
    parser.add_argument("--user", type=int, help="só esta pessoa (diagnóstico)")
    parser.add_argument("--workspace", type=int, help="só este espaço (diagnóstico)")
    args = parser.parse_args()

    inicio = time.monotonic()
    hoje = today_local()
    resumo = _resumo()

    with Session(engine) as db:
        # Despesa antes de renda por nenhuma razão forte — mas a ORDEM é fixa para
        # o log ser comparável entre execuções.
        if args.user is None:
            _despesas(db, hoje, args.horizonte, args.dry_run, args.workspace, resumo)
        if args.workspace is None:
            _rendas(db, hoje, args.horizonte, args.dry_run, args.user, resumo)

    resumo["duracao_ms"] = round((time.monotonic() - inicio) * 1000)
    # UM log de resumo, e exceções detalhadas acima. Uma linha por ocorrência
    # criada seria ruído: o caso comum é "nada a fazer", 24 vezes por dia.
    logger.info(
        "materializacao_concluida",
        hoje=hoje.isoformat(), horizonte=args.horizonte, dry_run=args.dry_run,
        **resumo,
    )
    print(
        f"{'[dry-run] ' if args.dry_run else ''}"
        f"{resumo['espacos']} espaço(s), {resumo['pessoas']} pessoa(s): "
        f"{resumo['despesas_criadas']} despesa(s) e {resumo['rendas_criadas']} renda(s) "
        f"criadas, {resumo['despesas_promovidas'] + resumo['rendas_promovidas']} "
        f"promovida(s), {resumo['falhas']} falha(s) em {resumo['duracao_ms']}ms"
    )
    return 1 if resumo["falhas"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
