"""O aviso de vencimento (ADR 0033).

O que estes testes protegem, em ordem de gravidade:

1. **O dedupe.** O job roda todo dia. Sem a restrição de unicidade ele reavisaria
   a mesma conta todos os dias até ela ser paga — que é exatamente como uma
   funcionalidade útil vira spam e acaba desligada, levando junto o aviso que
   importava.
2. **As três fontes.** Avisar só conta a pagar deixaria a FATURA DO CARTÃO calada,
   que é a conta que mais dói esquecer.
3. **O marco certo no dia certo**, inclusive nas bordas (`due` ganha de `before`).
"""
from datetime import date, datetime, timedelta, UTC
from decimal import Decimal

import pytest
from sqlmodel import Session, select

from app.models.credit_card import CardStatement, CreditCard, StatementStatus
from app.models.due_reminder import DueReminder, ReminderMilestone, ReminderSource
from app.models.financing import (
    AmortizationInstallment, AmortizationMethod, Financing,
)
from app.models.notification import Notification, NotificationType
from app.models.transaction import Transaction, TransactionPayer, TransactionStatus
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMembership, WorkspaceRole
from app.services import due_reminder_service as svc
from app.services.credit_card_service import CreditCardService

HOJE = date(2026, 9, 10)


@pytest.fixture(name="pessoa")
def pessoa_fixture(db_session: Session):
    user = User(name="Dono", email="dono@aviso.example.com", password_hash="h")
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)

    ws = Workspace(name="Casa", created_by_user_id=user.id)
    db_session.add(ws)
    db_session.commit()
    db_session.refresh(ws)
    db_session.add(
        WorkspaceMembership(workspace_id=ws.id, user_id=user.id, role=WorkspaceRole.owner)
    )
    db_session.commit()
    return {"user": user, "ws": ws}


def _conta_a_pagar(db: Session, pessoa, *, vence: date, titulo="Aluguel") -> Transaction:
    """Lançamento em aberto, fora do cartão — uma conta a pagar de verdade.

    Meio-dia: `transaction_date` é um INSTANTE, e o vencimento é
    `local_day()` dele. Gravar meia-noite crua faz o dia civil escorregar para o
    anterior no fuso do app — a armadilha do ADR 0025.
    """
    tx = Transaction(
        title=titulo,
        total_amount=Decimal("100.00"),
        currency="BRL",
        status=TransactionStatus.confirmed,
        billing_month=vence.strftime("%Y-%m"),
        workspace_id=pessoa["ws"].id,
        created_by_user_id=pessoa["user"].id,
        transaction_date=datetime(vence.year, vence.month, vence.day, 12, 0, tzinfo=UTC),
        settled_at=None,
    )
    db.add(tx)
    db.commit()
    db.refresh(tx)
    db.add(
        TransactionPayer(
            transaction_id=tx.id, user_id=pessoa["user"].id, amount=Decimal("100.00")
        )
    )
    db.commit()
    return tx


def _fatura(db: Session, pessoa, *, vence: date) -> CardStatement:
    """Fatura gravada como a PRODUÇÃO grava: dia civil + meia-noite crua.

    A fixture nascera com meio-dia, e era a única razão de a coleta passar verde:
    `credit_card_service._statement_dates` combina a data com `datetime.min.time()`,
    e é justamente essa meia-noite que escorregava um dia para trás quando lida
    como instante. Fixture que não imita o produtor real não protege ninguém.
    """
    cartao = CreditCard(
        name="Nubank", owner_user_id=pessoa["user"].id,
        limit=Decimal("1000.00"), closing_day=1, due_day=10, currency="BRL",
    )
    db.add(cartao)
    db.commit()
    db.refresh(cartao)
    fatura = CardStatement(
        card_id=cartao.id, month=vence.strftime("%Y-%m"),
        closing_date=datetime.combine(date(vence.year, vence.month, 1), datetime.min.time()),
        due_date=datetime.combine(vence, datetime.min.time()),
        status=StatementStatus.closed, total_amount=Decimal("300.00"),
    )
    db.add(fatura)
    db.commit()
    db.refresh(fatura)
    return fatura


def _parcela(db: Session, pessoa, *, vence: date) -> AmortizationInstallment:
    fin = Financing(
        title="Apartamento", owner_user_id=pessoa["user"].id,
        total_amount=Decimal("100000.00"), interest_rate=Decimal("0.01"),
        installments_count=120, method=AmortizationMethod.PRICE,
        start_date=date(2026, 1, 1), currency="BRL",
    )
    db.add(fin)
    db.commit()
    db.refresh(fin)
    parcela = AmortizationInstallment(
        financing_id=fin.id, installment_number=9, due_date=vence,
        principal_amount=Decimal("500.00"), interest_amount=Decimal("100.00"),
        total_amount=Decimal("600.00"), remaining_balance=Decimal("99500.00"),
        is_paid=False,
    )
    db.add(parcela)
    db.commit()
    db.refresh(parcela)
    return parcela


# --------------------------------------------------------------------------
# Os marcos
# --------------------------------------------------------------------------

def _v(vence: date) -> svc.Vencimento:
    return svc.Vencimento(
        source=ReminderSource.payable, source_id=1, due_date=vence,
        titulo="X", valor=Decimal("1"), moeda="BRL",
    )


@pytest.mark.parametrize(
    "vence, esperado",
    [
        (HOJE, ReminderMilestone.due),
        (HOJE - timedelta(days=1), ReminderMilestone.overdue),
        (HOJE + timedelta(days=1), ReminderMilestone.eve),
        (HOJE + timedelta(days=3), ReminderMilestone.before),
        (HOJE + timedelta(days=2), None),   # entre os marcos: nada
        (HOJE - timedelta(days=2), None),   # atraso já avisado ontem
        (HOJE + timedelta(days=30), None),  # longe demais
    ],
)
def test_marco_do_dia(vence, esperado):
    assert svc.marco_de(_v(vence), HOJE, dias_antes=3) is esperado


def test_a_sequencia_prometida_e_tres_um_e_no_dia():
    """O que o produto promete com o padrão: D-3, D-1 e no dia.

    Escrito como sequência, e não como três asserções soltas, porque o defeito
    que importa aqui é um BURACO — um dia da série que para de avisar sem que
    nenhum caso isolado fique vermelho.
    """
    serie = {
        dias: svc.marco_de(_v(HOJE + timedelta(days=dias)), HOJE, dias_antes=3)
        for dias in range(0, 5)
    }
    assert serie == {
        0: ReminderMilestone.due,
        1: ReminderMilestone.eve,
        2: None,
        3: ReminderMilestone.before,
        4: None,
    }


def test_no_dia_ganha_de_antes_quando_a_antecedencia_e_zero():
    """Com `dias_antes=0` os dois testes casariam. "Vence em 0 dias" seria pior
    do que não avisar, então `due` tem de vir primeiro."""
    assert svc.marco_de(_v(HOJE), HOJE, dias_antes=0) is ReminderMilestone.due


def test_vespera_ganha_de_antes_quando_a_antecedencia_e_um():
    """Antecedência de 1 dia cai em cima da véspera. Se `before` vencesse a
    disputa, o mesmo dia teria dois marcos — e marco entra na chave do dedupe,
    então seriam DOIS avisos na mesma manhã."""
    assert svc.marco_de(_v(HOJE + timedelta(days=1)), HOJE, dias_antes=1) is ReminderMilestone.eve


# --------------------------------------------------------------------------
# As três fontes
# --------------------------------------------------------------------------

def test_coleta_as_tres_fontes(db_session: Session, pessoa):
    _conta_a_pagar(db_session, pessoa, vence=HOJE)
    _fatura(db_session, pessoa, vence=HOJE)
    _parcela(db_session, pessoa, vence=HOJE)

    fontes = {v.source for v in svc.coletar(db_session, pessoa["user"].id, HOJE)}
    assert fontes == {
        ReminderSource.payable, ReminderSource.statement, ReminderSource.financing
    }, "a fatura do cartão é a conta que mais dói esquecer e não pode ficar de fora"


def test_fatura_do_dia_10_nao_avisa_no_dia_9(db_session: Session, pessoa):
    """A regressão: o cartão configurado para vencer dia 10 recebia "vence hoje"
    no dia 9.

    A fatura é construída pelo PRODUTOR REAL (`get_or_create_statement`) de
    propósito. O defeito vivia exatamente na diferença entre o que o serviço
    grava — dia civil combinado com meia-noite — e o que a coleta lia, tratando
    essa meia-noite como instante UTC e recuando um dia no fuso de São Paulo.
    Um `CardStatement` montado à mão com outra hora não reproduz nada.
    """
    cartao = CreditCard(
        name="Nubank", owner_user_id=pessoa["user"].id,
        limit=Decimal("1000.00"), closing_day=1, due_day=10, currency="BRL",
    )
    db_session.add(cartao)
    db_session.commit()
    db_session.refresh(cartao)

    fatura = CreditCardService.get_or_create_statement(
        db_session, cartao, datetime(2026, 9, 3, 12, 0, tzinfo=UTC)
    )
    fatura.status = StatementStatus.closed
    fatura.total_amount = Decimal("300.00")
    db_session.add(fatura)
    db_session.commit()

    dia_10 = fatura.due_date.date()
    assert dia_10.day == 10, "o cartão foi configurado para vencer dia 10"
    dia_9 = dia_10 - timedelta(days=1)

    def marcos(hoje: date) -> list[ReminderMilestone]:
        return [
            svc.marco_de(v, hoje, dias_antes=3)
            for v in svc.coletar(db_session, pessoa["user"].id, hoje)
            if v.source is ReminderSource.statement
        ]

    assert marcos(dia_9) == [ReminderMilestone.eve], "no dia 9 a fatura é véspera"
    assert marcos(dia_10) == [ReminderMilestone.due], "'vence hoje' é no dia 10"


def test_conta_ja_liquidada_nao_e_avisada(db_session: Session, pessoa):
    tx = _conta_a_pagar(db_session, pessoa, vence=HOJE)
    tx.settled_at = datetime.now(UTC)
    db_session.add(tx)
    db_session.commit()

    assert svc.coletar(db_session, pessoa["user"].id, HOJE) == []


def test_fatura_paga_nao_e_avisada(db_session: Session, pessoa):
    fatura = _fatura(db_session, pessoa, vence=HOJE)
    fatura.status = StatementStatus.paid
    db_session.add(fatura)
    db_session.commit()

    assert svc.coletar(db_session, pessoa["user"].id, HOJE) == []


def test_parcela_paga_nao_e_avisada(db_session: Session, pessoa):
    parcela = _parcela(db_session, pessoa, vence=HOJE)
    parcela.is_paid = True
    db_session.add(parcela)
    db_session.commit()

    assert svc.coletar(db_session, pessoa["user"].id, HOJE) == []


def test_conta_de_outra_pessoa_nao_e_avisada(db_session: Session, pessoa):
    """O recorte é o PAGADOR (ADR 0018): a conta de outra pessoa não é minha."""
    outra = User(name="Outra", email="outra@aviso.example.com", password_hash="h")
    db_session.add(outra)
    db_session.commit()
    db_session.refresh(outra)

    _conta_a_pagar(db_session, pessoa, vence=HOJE)
    assert svc.coletar(db_session, outra.id, HOJE) == []


# --------------------------------------------------------------------------
# O dedupe — o motivo de a tabela existir
# --------------------------------------------------------------------------

def test_nao_avisa_a_mesma_conta_duas_vezes(db_session: Session, pessoa):
    _conta_a_pagar(db_session, pessoa, vence=HOJE)

    primeira = svc.processar_usuario(db_session, pessoa["user"], HOJE)
    db_session.commit()
    segunda = svc.processar_usuario(db_session, pessoa["user"], HOJE)
    db_session.commit()

    assert primeira == 1
    assert segunda == 0, (
        "rodar o job de novo no mesmo dia reavisaria a mesma conta — é assim que "
        "a funcionalidade vira spam e a pessoa a desliga"
    )
    avisos = db_session.exec(select(Notification).where(
        Notification.type == NotificationType.due_reminder
    )).all()
    assert len(avisos) == 1


def test_a_mesma_conta_avisa_de_novo_em_marco_diferente(db_session: Session, pessoa):
    """Quatro marcos por conta é o TETO, não um só."""
    _conta_a_pagar(db_session, pessoa, vence=HOJE)

    svc.processar_usuario(db_session, pessoa["user"], HOJE)          # 'due'
    db_session.commit()
    svc.processar_usuario(db_session, pessoa["user"], HOJE + timedelta(days=1))  # 'overdue'
    db_session.commit()

    marcos = {
        r.milestone for r in db_session.exec(select(DueReminder)).all()
    }
    assert marcos == {ReminderMilestone.due, ReminderMilestone.overdue}


def test_a_conta_avisa_tres_dias_antes_na_vespera_e_no_dia(db_session: Session, pessoa):
    """A promessa do produto, rodando o job dia a dia como ele roda de verdade.

    Cinco execuções, quatro avisos, e o dia 2 CALADO — o silêncio faz parte da
    promessa tanto quanto os avisos: é ele que separa "três lembretes" de "um
    lembrete por dia até você pagar", que é como o canal acaba desligado.
    """
    vence = HOJE + timedelta(days=3)
    _conta_a_pagar(db_session, pessoa, vence=vence)

    saiu = {}
    for dias in range(3, -2, -1):  # D-3, D-2, D-1, no dia, D+1
        hoje = vence - timedelta(days=dias)
        saiu[dias] = svc.processar_usuario(db_session, pessoa["user"], hoje)
        db_session.commit()

    assert saiu == {3: 1, 2: 0, 1: 1, 0: 1, -1: 1}

    marcos = [
        r.milestone
        for r in db_session.exec(select(DueReminder).order_by(DueReminder.id)).all()
    ]
    assert marcos == [
        ReminderMilestone.before,
        ReminderMilestone.eve,
        ReminderMilestone.due,
        ReminderMilestone.overdue,
    ]


def test_conta_que_mudou_de_data_volta_a_avisar(db_session: Session, pessoa):
    """A data entra na CHAVE de propósito: uma conta que se moveu merece aviso
    novo. Sem isso, corrigir a data seria tratado como "já avisei"."""
    tx = _conta_a_pagar(db_session, pessoa, vence=HOJE)
    svc.processar_usuario(db_session, pessoa["user"], HOJE)
    db_session.commit()

    nova = HOJE + timedelta(days=7)
    tx.transaction_date = datetime(nova.year, nova.month, nova.day, 12, 0, tzinfo=UTC)
    db_session.add(tx)
    db_session.commit()

    # No dia do novo vencimento, avisa de novo.
    assert svc.processar_usuario(db_session, pessoa["user"], nova) == 1


# --------------------------------------------------------------------------
# O agrupamento
# --------------------------------------------------------------------------

def test_cinco_contas_viram_UM_aviso(db_session: Session, pessoa):
    for i in range(5):
        _conta_a_pagar(db_session, pessoa, vence=HOJE, titulo=f"Conta {i}")

    quantas = svc.processar_usuario(db_session, pessoa["user"], HOJE)
    db_session.commit()

    assert quantas == 5, "as cinco contam para o dedupe"
    avisos = db_session.exec(select(Notification).where(
        Notification.type == NotificationType.due_reminder
    )).all()
    assert len(avisos) == 1, (
        "cinco notificações de uma vez fazem a pessoa desligar o canal — e aí ela "
        "perde a sexta, que podia ser a que importava"
    )
    assert "5" in avisos[0].title


def test_valor_nao_vai_no_aviso_por_padrao(db_session: Session, pessoa):
    """A exposição é a TELA DE BLOQUEIO, não a rede (ADR 0018/0033)."""
    _conta_a_pagar(db_session, pessoa, vence=HOJE)
    svc.processar_usuario(db_session, pessoa["user"], HOJE)
    db_session.commit()

    aviso = db_session.exec(select(Notification).where(
        Notification.type == NotificationType.due_reminder
    )).first()
    assert "100" not in (aviso.body or ""), "o valor não pode vazar na tela de bloqueio"


def test_valor_aparece_quando_a_pessoa_pede(db_session: Session, pessoa):
    pessoa["user"].notify_show_amount = True
    db_session.add(pessoa["user"])
    db_session.commit()

    _conta_a_pagar(db_session, pessoa, vence=HOJE)
    svc.processar_usuario(db_session, pessoa["user"], HOJE)
    db_session.commit()

    aviso = db_session.exec(select(Notification).where(
        Notification.type == NotificationType.due_reminder
    )).first()
    assert "100" in (aviso.body or "")


def test_antecedencia_da_pessoa_e_respeitada(db_session: Session, pessoa):
    pessoa["user"].notify_days_before = 7
    db_session.add(pessoa["user"])
    db_session.commit()

    _conta_a_pagar(db_session, pessoa, vence=HOJE + timedelta(days=7))

    assert svc.processar_usuario(db_session, pessoa["user"], HOJE) == 1
    db_session.commit()
    # Com o padrão de 3 dias não teria avisado hoje.
    assert svc.marco_de(_v(HOJE + timedelta(days=7)), HOJE, dias_antes=3) is None
