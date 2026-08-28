"""O aviso de vencimento: quem varre, quem decide e quem entrega (ADR 0033).

## As três obrigações

Notificar só conta a pagar entregaria algo que PARECE completo e não é: o
`payables_service` exclui compra no cartão de propósito — quem se paga é a
fatura, e ela vive em Compromissos. A fatura do cartão é a conta que mais dói
esquecer, e ficaria calada. Por isso são três fontes, cada uma com a data que
realmente tem:

| Fonte | Vencimento |
|---|---|
| conta a pagar | `local_day(transaction_date)` — a mesma de `_vencimento()` |
| fatura de cartão | `CardStatement.due_date` (data real) |
| parcela de financiamento | `AmortizationInstallment.due_date` (data real) |

A conta a pagar usa a data do lançamento porque é a única que ela tem. Para um
boleto lançado no dia em que chegou, essa data é a da CHEGADA, não a do
vencimento — a ressalva está no ADR e some quando existir `due_date` no
lançamento.

## Por que a varredura é por pessoa, e não uma consulta global

Cada fonte tem um recorte de dono diferente (`TransactionPayer.user_id`,
`CreditCard.owner_user_id`, `Financing.owner_user_id`), e a conta a pagar ainda
precisa do escopo de espaços (`workspaces_do_usuario`) para respeitar o ADR 0018.
Uma consulta global teria de reimplementar os três recortes — e divergir deles é
como uma tela passa a somar um conjunto e outra, outro. Varrer por pessoa reusa
`_consulta_base()` do próprio `payables_service`, que é a definição ÚNICA de
"pendência". A escala deste app (dezenas de contas, não milhões) paga isso com
folga.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import List, Optional, Sequence

import structlog
from sqlmodel import Session, select

from app.domain.dates import local_day, today_local
from app.domain.query_policy import workspaces_do_usuario
from app.models.credit_card import CardStatement, CreditCard, StatementStatus
from app.models.due_reminder import DueReminder, ReminderMilestone, ReminderSource
from app.models.financing import AmortizationInstallment, Financing
from app.models.notification import NotificationType
from app.models.transaction import Transaction, TransactionPayer
from app.models.user import User
from app.services import notification_service, push_service
from app.services.payables_service import _consulta_base

logger = structlog.get_logger(__name__)

# Teto da antecedência que a pessoa pode escolher. A janela de coleta usa este
# valor para varrer uma vez só, em vez de uma vez por preferência distinta.
MAX_DIAS_ANTES = 15


@dataclass(frozen=True)
class Vencimento:
    """Uma obrigação com data, já normalizada — a fonte não importa daqui para frente."""

    source: ReminderSource
    source_id: int
    due_date: date
    titulo: str
    valor: Decimal
    moeda: str


def _janela(hoje: date) -> tuple[date, date]:
    """As datas que podem disparar algum marco hoje.

    `hoje - 1` é o atraso (D+1) e `hoje + MAX_DIAS_ANTES` é o aviso mais adiantado
    que alguém pode ter pedido. Nada fora disso interessa nesta execução.
    """
    return hoje - timedelta(days=1), hoje + timedelta(days=MAX_DIAS_ANTES)


def coletar_contas_a_pagar(db: Session, user_id: int, inicio: date, fim: date) -> List[Vencimento]:
    espacos = [ws.id for ws in workspaces_do_usuario(db, user_id)]
    if not espacos:
        return []

    linhas = db.exec(
        _consulta_base()
        .where(TransactionPayer.user_id == user_id)
        .where(Transaction.workspace_id.in_(espacos))
    ).all()

    achados: List[Vencimento] = []
    for tx, valor in linhas:
        # O filtro de data acontece em Python, e não no SQL, porque o vencimento
        # é `local_day(transaction_date)` — um dia CIVIL no fuso do app. Comparar
        # o instante cru contra uma data no banco erra por até um dia inteiro nas
        # bordas, que é justamente onde o aviso importa (ADR 0025).
        vence = local_day(tx.transaction_date)
        if inicio <= vence <= fim:
            achados.append(
                Vencimento(
                    source=ReminderSource.payable,
                    source_id=tx.id,
                    due_date=vence,
                    titulo=tx.title,
                    valor=valor,
                    moeda=tx.currency,
                )
            )
    return achados


def coletar_faturas(db: Session, user_id: int, inicio: date, fim: date) -> List[Vencimento]:
    linhas = db.exec(
        select(CardStatement, CreditCard)
        .join(CreditCard, CreditCard.id == CardStatement.card_id)
        .where(CreditCard.owner_user_id == user_id)
        .where(CreditCard.deleted_at.is_(None))
        # `paid` sai: fatura paga não é obrigação. `open` e `closed` ficam — uma
        # fatura aberta continua vencendo na data dela.
        .where(CardStatement.status != StatementStatus.paid)
    ).all()

    achados: List[Vencimento] = []
    for statement, cartao in linhas:
        vence = local_day(statement.due_date)
        if inicio <= vence <= fim:
            achados.append(
                Vencimento(
                    source=ReminderSource.statement,
                    source_id=statement.id,
                    due_date=vence,
                    titulo=f"Fatura {cartao.name}",
                    valor=statement.total_amount,
                    moeda=cartao.currency,
                )
            )
    return achados


def coletar_financiamentos(db: Session, user_id: int, inicio: date, fim: date) -> List[Vencimento]:
    linhas = db.exec(
        select(AmortizationInstallment, Financing)
        .join(Financing, Financing.id == AmortizationInstallment.financing_id)
        .where(Financing.owner_user_id == user_id)
        .where(AmortizationInstallment.is_paid.is_(False))
        .where(AmortizationInstallment.due_date >= inicio)
        .where(AmortizationInstallment.due_date <= fim)
    ).all()

    return [
        Vencimento(
            source=ReminderSource.financing,
            source_id=parcela.id,
            # Já é `date` na coluna: aqui não há instante para converter.
            due_date=parcela.due_date,
            titulo=f"{financiamento.title} — parcela {parcela.installment_number}",
            valor=parcela.total_amount,
            moeda=financiamento.currency,
        )
        for parcela, financiamento in linhas
    ]


def coletar(db: Session, user_id: int, hoje: date) -> List[Vencimento]:
    inicio, fim = _janela(hoje)
    return [
        *coletar_contas_a_pagar(db, user_id, inicio, fim),
        *coletar_faturas(db, user_id, inicio, fim),
        *coletar_financiamentos(db, user_id, inicio, fim),
    ]


def marco_de(vencimento: Vencimento, hoje: date, dias_antes: int) -> Optional[ReminderMilestone]:
    """Qual marco esta obrigação dispara HOJE — ou nenhum.

    A ordem do teste importa quando `dias_antes` é 0 ou 1: "no dia" ganha do
    "antes", porque avisar "vence em 0 dias" seria pior do que não avisar.
    """
    if vencimento.due_date == hoje:
        return ReminderMilestone.due
    if vencimento.due_date == hoje - timedelta(days=1):
        return ReminderMilestone.overdue
    if vencimento.due_date == hoje + timedelta(days=dias_antes):
        return ReminderMilestone.before
    return None


def _ja_avisados(
    db: Session, user_id: int, candidatos: Sequence[tuple[Vencimento, ReminderMilestone]]
) -> set[tuple[str, int, str, date]]:
    """Quais dos candidatos já têm linha de aviso — a consulta que evita o spam."""
    if not candidatos:
        return set()
    existentes = db.exec(
        select(
            DueReminder.source, DueReminder.source_id,
            DueReminder.milestone, DueReminder.due_date,
        )
        .where(DueReminder.user_id == user_id)
        .where(DueReminder.due_date.in_([v.due_date for v, _ in candidatos]))
    ).all()
    return {
        (
            s.value if hasattr(s, "value") else str(s),
            sid,
            m.value if hasattr(m, "value") else str(m),
            d,
        )
        for s, sid, m, d in existentes
    }


def _texto(
    novos: Sequence[tuple[Vencimento, ReminderMilestone]],
    hoje: date,
    mostrar_valor: bool,
) -> tuple[str, str]:
    """Título e corpo do aviso, já agrupados.

    Cinco contas vencendo não são cinco notificações. Uma pessoa que recebe cinco
    avisos de uma vez desliga o canal, e aí perde o sexto — que podia ser o que
    importava.
    """
    quantos = len(novos)
    marcos = {m for _, m in novos}

    if quantos == 1:
        vencimento, marco = novos[0]
        quando = {
            ReminderMilestone.due: "vence hoje",
            ReminderMilestone.overdue: "venceu ontem e continua em aberto",
        }.get(marco)
        if quando is None:
            # `hoje` recebido, e NUNCA `date.today()`: aquele é o dia do relógio
            # do servidor (UTC no contêiner), e o calendário deste app é o
            # `APP_TIMEZONE`. Às 22h de Brasília os dois discordam, e o aviso
            # sairia com "vence em 2 dias" no dia em que vence amanhã.
            dias = (vencimento.due_date - hoje).days
            quando = "vence amanhã" if dias == 1 else f"vence em {dias} dias"
        titulo = f"{vencimento.titulo} {quando}"
        corpo = (
            f"{vencimento.moeda} {vencimento.valor:.2f}".replace(".", ",")
            if mostrar_valor
            else "Toque para ver os detalhes."
        )
        return titulo, corpo

    if marcos == {ReminderMilestone.overdue}:
        titulo = f"{quantos} contas venceram e continuam em aberto"
    elif marcos == {ReminderMilestone.due}:
        titulo = f"{quantos} contas vencem hoje"
    else:
        titulo = f"{quantos} contas precisam da sua atenção"

    nomes = ", ".join(v.titulo for v, _ in novos[:3])
    if quantos > 3:
        nomes += f" e mais {quantos - 3}"
    return titulo, nomes


def processar_usuario(db: Session, user: User, hoje: date) -> int:
    """Avisa UMA pessoa. Devolve quantas obrigações entraram no aviso.

    Não faz commit (ADR 0010) — quem chama decide o lote.
    """
    vencimentos = coletar(db, user.id, hoje)
    if not vencimentos:
        return 0

    dias_antes = max(1, min(user.notify_days_before, MAX_DIAS_ANTES))
    candidatos = [
        (v, marco)
        for v in vencimentos
        if (marco := marco_de(v, hoje, dias_antes)) is not None
    ]
    if not candidatos:
        return 0

    ja = _ja_avisados(db, user.id, candidatos)
    novos = [
        (v, m)
        for v, m in candidatos
        if (v.source.value, v.source_id, m.value, v.due_date) not in ja
    ]
    if not novos:
        return 0

    # Grava o dedupe ANTES de entregar. Se a entrega falhar, a pessoa perde UM
    # aviso; se a ordem fosse inversa e o commit falhasse depois da entrega, ela
    # receberia o mesmo aviso todo dia — o defeito pior dos dois.
    for vencimento, marco in novos:
        db.add(
            DueReminder(
                user_id=user.id,
                source=vencimento.source,
                source_id=vencimento.source_id,
                milestone=marco,
                due_date=vencimento.due_date,
            )
        )
    db.flush()

    titulo, corpo = _texto(novos, hoje, user.notify_show_amount)

    # O sino SEMPRE. Não depende de permissão, de navegador nem de iPhone — é o
    # registro durável, e é o que funciona para quem nunca ativar push.
    notification_service.notify(
        db, user_id=user.id, type=NotificationType.due_reminder, title=titulo, body=corpo
    )

    push_service.enviar_para_usuario(
        db,
        user.id,
        json.dumps(
            {"titulo": titulo, "corpo": corpo, "url": "/me/payables"},
            ensure_ascii=False,
        ).encode("utf-8"),
    )

    return len(novos)


def processar_todos(db: Session, hoje: Optional[date] = None) -> dict:
    """Varre todo mundo. Devolve um resumo para o log do job."""
    hoje = hoje or today_local()
    pessoas = db.exec(
        select(User).where(User.deleted_at.is_(None)).where(User.is_active.is_(True))
    ).all()

    avisadas = 0
    obrigacoes = 0
    for user in pessoas:
        try:
            quantas = processar_usuario(db, user, hoje)
        except Exception as erro:
            # Uma pessoa com dado estranho não pode calar o aviso de todas as
            # outras. O rollback é do escopo dela.
            db.rollback()
            logger.error("aviso_falhou", user_id=user.id, erro=str(erro))
            continue
        if quantas:
            avisadas += 1
            obrigacoes += quantas
            db.commit()

    return {"pessoas": len(pessoas), "avisadas": avisadas, "obrigacoes": obrigacoes}
