"""O horizonte de materialização é regra de calendário (ADR 0034).

    mês corrente inteiro + mês seguinte inteiro

Em 28/08 vai até 30/09; em 1º/09 passa a ir até 31/10. Antes era só o mês
corrente, e a consequência prática está no §21 do pedido:

> Hoje é 28/08. Existe despesa recorrente todo dia 01. O usuário precisa enxergar
> "Aluguel — vence 01/09" ANTES da virada de mês. Não pode depender de ele entrar
> no sistema em 01/09 para descobrir isso.

E o §23: "todo dia 31" não pula fevereiro — ele vira o último dia VÁLIDO de cada
mês. Esta suíte trava as duas regras juntas, porque é a combinação delas que erra:
o horizonte novo passa a materializar meses que o teste antigo nunca alcançava.
"""
from datetime import date
from decimal import Decimal

import pytest
from sqlmodel import Session, select

from app.domain.dates import fim_do_horizonte, meses_do_horizonte
from app.models.recurring import RecurrenceFrequency, RecurringExpense, RecurringIncome
from app.models.income import Income
from app.models.transaction import Transaction, TransactionStatus
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMembership, WorkspaceRole
from app.services.recurring_service import RecurringIncomeService, RecurringService


@pytest.fixture(name="ws")
def ws_fixture(db_session: Session):
    user = User(name="Dona", email="horizonte@t.com", password_hash="h")
    espaco = Workspace(name="Casa", base_currency="BRL")
    db_session.add_all([user, espaco])
    db_session.flush()
    db_session.add(
        WorkspaceMembership(
            workspace_id=espaco.id, user_id=user.id, role=WorkspaceRole.owner
        )
    )
    db_session.commit()
    return {"db": db_session, "user_id": user.id, "ws_id": espaco.id}


def _template(ws, dia: int) -> RecurringExpense:
    t = RecurringExpense(
        title="Aluguel", base_amount=Decimal("2000.00"), currency="BRL",
        frequency=RecurrenceFrequency.monthly, day_of_month=dia,
        workspace_id=ws["ws_id"], created_by_user_id=ws["user_id"],
        payer_user_id=ws["user_id"],
    )
    ws["db"].add(t)
    ws["db"].commit()
    ws["db"].refresh(t)
    return t


def _ocorrencias(ws):
    return ws["db"].exec(
        select(Transaction)
        .where(Transaction.workspace_id == ws["ws_id"])
        .order_by(Transaction.occurrence_date)
    ).all()


# ---------------------------------------------------------------------------
# 1. A regra de calendário


def test_horizonte_e_por_mes_de_calendario_nao_por_dias():
    """Em 28/08 o horizonte vai até 30/09; em 01/09, até 31/10.

    "hoje + 30 dias" daria 27/09 no primeiro caso — e deixaria de fora justamente
    a última semana do mês, onde ficam salário e a maioria dos vencimentos.
    """
    assert fim_do_horizonte(date(2026, 8, 28)) == date(2026, 9, 30)
    assert fim_do_horizonte(date(2026, 9, 1)) == date(2026, 10, 31)
    assert fim_do_horizonte(date(2026, 9, 28)) == date(2026, 10, 31)
    assert fim_do_horizonte(date(2026, 12, 15)) == date(2027, 1, 31)


def test_meses_do_horizonte_atravessa_o_ano():
    assert meses_do_horizonte(date(2026, 12, 5)) == [date(2026, 12, 1), date(2027, 1, 1)]


# ---------------------------------------------------------------------------
# 2. A conta do dia 1º do mês seguinte (§21)


def test_aluguel_do_dia_primeiro_e_conhecido_antes_da_virada(ws):
    """O caso do pedido, com a data dele."""
    _template(ws, dia=1)
    criadas = RecurringService.generate_due_instances(
        ws["db"], ws["ws_id"], date(2026, 8, 28), allow_fetch=False
    )
    ws["db"].commit()

    assert criadas == 2, "agosto (já vencida) e setembro (a vencer)"
    datas = [t.occurrence_date for t in _ocorrencias(ws)]
    assert datas == [date(2026, 8, 1), date(2026, 9, 1)]

    setembro = _ocorrencias(ws)[1]
    assert setembro.status == TransactionStatus.pending, (
        "a de setembro ainda não venceu: é obrigação, não gasto realizado"
    )
    assert setembro.settled_at is None
    assert setembro.billing_month == "2026-09"


def test_rodar_de_novo_no_mesmo_mes_nao_duplica(ws):
    _template(ws, dia=18)
    RecurringService.generate_due_instances(
        ws["db"], ws["ws_id"], date(2026, 8, 28), allow_fetch=False
    )
    ws["db"].commit()
    de_novo = RecurringService.generate_due_instances(
        ws["db"], ws["ws_id"], date(2026, 8, 29), allow_fetch=False
    )
    ws["db"].commit()

    assert de_novo == 0, "o cron roda de hora em hora — tem de ser idempotente"
    assert len(_ocorrencias(ws)) == 2


def test_virar_o_mes_estende_o_horizonte_sem_recriar_o_passado(ws):
    """Em 01/09 outubro passa a ser conhecido, e agosto continua como estava."""
    _template(ws, dia=1)
    RecurringService.generate_due_instances(
        ws["db"], ws["ws_id"], date(2026, 8, 28), allow_fetch=False
    )
    ws["db"].commit()

    novas = RecurringService.generate_due_instances(
        ws["db"], ws["ws_id"], date(2026, 9, 1), allow_fetch=False
    )
    ws["db"].commit()

    assert novas == 1, "só outubro é novidade"
    datas = [t.occurrence_date for t in _ocorrencias(ws)]
    assert datas == [date(2026, 8, 1), date(2026, 9, 1), date(2026, 10, 1)]


def test_horizonte_zero_restringe_ao_mes_corrente(ws):
    """É o que a edição de um template usa: o escopo se chama "current"."""
    _template(ws, dia=1)
    criadas = RecurringService.generate_due_instances(
        ws["db"], ws["ws_id"], date(2026, 8, 28), allow_fetch=False,
        horizonte_meses=0,
    )
    ws["db"].commit()
    assert criadas == 1


# ---------------------------------------------------------------------------
# 3. "Todo dia 31" (§23)


@pytest.mark.parametrize(
    "hoje, esperadas",
    [
        # Fevereiro NÃO bissexto: 28. Março: 31.
        (date(2026, 2, 10), [date(2026, 2, 28), date(2026, 3, 31)]),
        # Fevereiro BISSEXTO (2028): 29.
        (date(2028, 2, 10), [date(2028, 2, 29), date(2028, 3, 31)]),
        # Abril tem 30; maio tem 31.
        (date(2026, 4, 10), [date(2026, 4, 30), date(2026, 5, 31)]),
        # Dois meses de 31 seguidos.
        (date(2026, 7, 10), [date(2026, 7, 31), date(2026, 8, 31)]),
        # Virada de ano.
        (date(2026, 12, 10), [date(2026, 12, 31), date(2027, 1, 31)]),
    ],
)
def test_dia_31_vira_o_ultimo_dia_valido_de_cada_mes(ws, hoje, esperadas):
    _template(ws, dia=31)
    RecurringService.generate_due_instances(
        ws["db"], ws["ws_id"], hoje, allow_fetch=False
    )
    ws["db"].commit()
    assert [t.occurrence_date for t in _ocorrencias(ws)] == esperadas


# ---------------------------------------------------------------------------
# 4. A renda segue o mesmo horizonte


def test_salario_do_ultimo_dia_do_mes_seguinte_ja_e_conhecido(ws):
    """O §22 combinado com o §21: em 28/08 o salário de 30/09 já existe, previsto."""
    ws["db"].add(RecurringIncome(
        title="Salário", base_amount=Decimal("6000.00"), currency="BRL",
        frequency=RecurrenceFrequency.monthly, day_of_month=31,
        user_id=ws["user_id"], auto_confirm=True,
    ))
    ws["db"].commit()

    criadas = RecurringIncomeService.generate_due_income(
        ws["db"], ws["user_id"], date(2026, 8, 28), allow_fetch=False
    )
    ws["db"].commit()
    assert criadas == 2

    rendas = ws["db"].exec(
        select(Income).order_by(Income.received_at)
    ).all()
    assert [r.billing_month for r in rendas] == ["2026-08", "2026-09"]
    # 31 de agosto existe; 31 de setembro não — vira 30.
    assert [r.received_at.date().day for r in rendas] in ([31, 30], [30, 29])

    assert all(r.settled_at is None for r in rendas), (
        "28/08 é anterior às duas datas: `auto_confirm` NUNCA vence a data"
    )


def test_promocao_de_renda_respeita_auto_confirm(ws):
    ws["db"].add_all([
        RecurringIncome(
            title="Salário", base_amount=Decimal("6000.00"), currency="BRL",
            frequency=RecurrenceFrequency.monthly, day_of_month=1,
            user_id=ws["user_id"], auto_confirm=True,
        ),
        RecurringIncome(
            title="Freela", base_amount=Decimal("800.00"), currency="BRL",
            frequency=RecurrenceFrequency.monthly, day_of_month=1,
            user_id=ws["user_id"], auto_confirm=False,
        ),
    ])
    ws["db"].commit()

    # Materializa em JULHO: a ocorrência de 01/08 nasce prevista nos dois casos,
    # porque `auto_confirm` nunca vence a data. É só na passagem do cron já em
    # agosto que a diferença entre os dois templates aparece.
    RecurringIncomeService.generate_due_income(
        ws["db"], ws["user_id"], date(2026, 7, 20), allow_fetch=False
    )
    ws["db"].commit()
    de_agosto = ws["db"].exec(
        select(Income).where(Income.billing_month == "2026-08")
    ).all()
    assert all(r.settled_at is None for r in de_agosto), "nenhuma nasce recebida"

    promovidas = RecurringIncomeService.promote_due_income(
        ws["db"], ws["user_id"], date(2026, 8, 15)
    )
    ws["db"].commit()

    assert promovidas == 1, "só o salário se confirma sozinho"
    por_titulo = {
        r.title: r
        for r in ws["db"].exec(
            select(Income).where(Income.billing_month == "2026-08")
        ).all()
    }
    assert por_titulo["Salário"].settled_at is not None
    assert por_titulo["Freela"].settled_at is None


def test_promover_duas_vezes_nao_muda_a_data(ws):
    """O cron roda de hora em hora: a segunda passagem não pode reescrever o
    caixa que a primeira gravou."""
    ws["db"].add(RecurringIncome(
        title="Salário", base_amount=Decimal("6000.00"), currency="BRL",
        frequency=RecurrenceFrequency.monthly, day_of_month=1,
        user_id=ws["user_id"], auto_confirm=True,
    ))
    ws["db"].commit()
    RecurringIncomeService.generate_due_income(
        ws["db"], ws["user_id"], date(2026, 7, 20), allow_fetch=False
    )
    RecurringIncomeService.promote_due_income(ws["db"], ws["user_id"], date(2026, 8, 15))
    ws["db"].commit()

    antes = ws["db"].exec(
        select(Income).where(Income.billing_month == "2026-08")
    ).one().settled_at

    de_novo = RecurringIncomeService.promote_due_income(
        ws["db"], ws["user_id"], date(2026, 8, 20)
    )
    ws["db"].commit()

    assert de_novo == 0
    depois = ws["db"].exec(
        select(Income).where(Income.billing_month == "2026-08")
    ).one().settled_at
    assert depois == antes, "a data de recebimento não pode andar sozinha"
