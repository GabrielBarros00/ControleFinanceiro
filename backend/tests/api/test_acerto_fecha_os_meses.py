"""O acerto do saldo acumulado fecha os meses que ele pagou.

## O relato

"Quando alguém registra um acerto em Seus Acertos › Resumo, ele não desconta o
valor devido: o mês continua lá, como 0 pago. Só desconta do total."

Reproduzido: duas despesas rateadas, uma em julho (R$ 200, dívida de 100) e
outra em agosto (R$ 120, dívida de 60). Registrando R$ 160 pelo Resumo, o saldo
acumulado vai a zero **e os dois meses continuam devendo 100 e 60**. A mesma
tela diz, ao mesmo tempo, que está tudo quitado e que há dois meses pendentes.

## Por que isso acontecia

`billing_month` é o que amarra um acerto a um mês. O acerto registrado a partir
do saldo acumulado não tem mês — ele nasce global —, então caía num balde
`unassigned` que abatia o total e não tocava mês nenhum.

O modelo não estava errado: um pagamento contra o acumulado **não é** de um mês
específico. O que faltava era dizer o que ele paga — e a resposta é a de
qualquer dívida: **o mais antigo primeiro**. Quem paga R$ 160 de uma dívida
formada por julho (100) e agosto (60) quitou os dois, nessa ordem.

A alocação é feita na LEITURA, e não gravando N acertos: um pagamento continua
sendo um registro só — o que permite desfazê-lo com um toque — e a distribuição
se refaz sozinha se alguém lançar uma despesa retroativa depois.
"""
import datetime
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from app.core.jwt import create_access_token
from app.main import app
from app.models.settlement import Settlement
from app.models.transaction import Transaction, TransactionPayer, TransactionSplit
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMembership, WorkspaceRole

client = TestClient(app)


def _instante(mes: str, dia: int = 10) -> datetime.datetime:
    ano, m = mes.split("-")
    return datetime.datetime(int(ano), int(m), dia, 12, 0, tzinfo=datetime.UTC)


@pytest.fixture(name="casa")
def casa_fixture(db_session: Session, override_get_session):
    """Ana adianta duas despesas rateadas 50/50 com o Bruno, em meses diferentes.

        julho:  R$ 200 → Bruno deve 100
        agosto: R$ 120 → Bruno deve  60
        ------------------------------------
        acumulado: Bruno deve 160
    """
    ana = User(name="Ana", email="ana@acerto.com", password_hash="h")
    bruno = User(name="Bruno", email="bruno@acerto.com", password_hash="h")
    ws = Workspace(name="Casa", base_currency="BRL")
    db_session.add_all([ana, bruno, ws])
    db_session.commit()
    db_session.add_all([
        WorkspaceMembership(workspace_id=ws.id, user_id=ana.id, role=WorkspaceRole.owner),
        WorkspaceMembership(workspace_id=ws.id, user_id=bruno.id, role=WorkspaceRole.member),
    ])

    for mes, valor in (("2026-07", "200.00"), ("2026-08", "120.00")):
        tx = Transaction(
            title=f"Mercado {mes}", total_amount=Decimal(valor), currency="BRL",
            transaction_date=_instante(mes), billing_month=mes, status="confirmed",
            workspace_id=ws.id, created_by_user_id=ana.id,
            settled_at=_instante(mes),
        )
        db_session.add(tx)
        db_session.commit()
        db_session.refresh(tx)
        metade = Decimal(valor) / 2
        db_session.add_all([
            TransactionPayer(transaction_id=tx.id, user_id=ana.id, amount=Decimal(valor)),
            TransactionSplit(transaction_id=tx.id, user_id=ana.id,
                             input_value=metade, computed_amount=metade),
            TransactionSplit(transaction_id=tx.id, user_id=bruno.id,
                             input_value=metade, computed_amount=metade),
        ])
    db_session.commit()

    return {
        "db": db_session, "ws": ws, "ana": ana, "bruno": bruno,
        "h": {"Cookie": f"access_token={create_access_token({'sub': str(ana.id)})}"},
    }


def _acertar(casa, valor: str, billing_month=None):
    corpo = {
        "from_user_id": casa["bruno"].id,
        "to_user_id": casa["ana"].id,
        "amount": valor,
    }
    if billing_month:
        corpo["billing_month"] = billing_month
    r = client.post(
        f"/api/v1/workspaces/{casa['ws'].id}/settlements", json=corpo, headers=casa["h"],
    )
    assert r.status_code == 200, r.text
    return r.json()


def _mes(casa, mes: str):
    r = client.get(
        f"/api/v1/workspaces/{casa['ws'].id}/debts/monthly?month={mes}", headers=casa["h"],
    )
    assert r.status_code == 200, r.text
    return r.json()


def _devido_no_mes(casa, mes: str) -> Decimal:
    return sum(
        (Decimal(str(d["amount"])) for d in _mes(casa, mes)["net_debts"]),
        Decimal("0"),
    )


def _por_mes(casa):
    r = client.get(f"/api/v1/workspaces/{casa['ws'].id}/debts/by-month", headers=casa["h"])
    assert r.status_code == 200, r.text
    return r.json()


# --------------------------------------------------------------------------- #
# O defeito relatado
# --------------------------------------------------------------------------- #

def test_o_acerto_do_acumulado_fecha_o_mes_mais_antigo(casa):
    _acertar(casa, "100.00")

    assert _devido_no_mes(casa, "2026-07") == Decimal("0"), (
        "paguei o valor exato de julho pelo Resumo e julho continua devendo — "
        "a tela diz que está quitado e que o mês está pendente ao mesmo tempo"
    )
    assert _devido_no_mes(casa, "2026-08") == Decimal("60.00"), (
        "agosto foi quitado junto, sem que o dinheiro desse para ele"
    )


def test_o_acerto_maior_atravessa_para_o_mes_seguinte(casa):
    """R$ 160 é julho inteiro mais agosto inteiro."""
    _acertar(casa, "160.00")

    assert _devido_no_mes(casa, "2026-07") == Decimal("0")
    assert _devido_no_mes(casa, "2026-08") == Decimal("0")


def test_o_acerto_parcial_deixa_o_resto_no_mes(casa):
    """R$ 130 fecha julho (100) e abate 30 de agosto — sobram 30."""
    _acertar(casa, "130.00")

    assert _devido_no_mes(casa, "2026-07") == Decimal("0")
    assert _devido_no_mes(casa, "2026-08") == Decimal("30.00"), (
        "o troco do mês anterior não pingou em agosto"
    )


def test_a_soma_por_mes_continua_fechando_com_o_total(casa):
    """A identidade que `get_balance_by_month` promete: o acumulado é a soma
    dos meses. Se a alocação mexer num lado e não no outro, a tela passa a
    mostrar um total que não bate com as linhas logo abaixo dele."""
    _acertar(casa, "130.00")

    corpo = _por_mes(casa)
    soma = (
        sum((Decimal(str(m["balance"])) for m in corpo["months"]), Decimal("0"))
        + Decimal(str(corpo["older"]["balance"]))
        + Decimal(str(corpo["unassigned"]))
    )
    assert soma == Decimal(str(corpo["balance"])), (
        f"a soma dos meses ({soma}) não fecha com o acumulado ({corpo['balance']})"
    )


def test_nao_sobra_saldo_orfao_quando_tudo_e_alocado(casa):
    """`unassigned` era onde o acerto do Resumo ficava preso. Alocado, ele
    deixa de existir como linha órfã — senão a tela mostra "sem mês: −160"
    ao lado de dois meses devendo, que é o retrato do defeito."""
    _acertar(casa, "160.00")

    assert Decimal(str(_por_mes(casa)["unassigned"])) == Decimal("0")


def test_pagar_mais_do_que_se_deve_e_recusado(casa):
    """Escrevi este teste esperando que o excedente virasse crédito — e a rota
    RECUSA a operação, com o valor da dívida na mensagem. É melhor assim: um
    acerto maior que a dívida é quase sempre dedo errado, e transformá-lo em
    crédito calado inverteria a direção do saldo sem ninguém pedir.

    Fica registrado porque a alocação depende dessa garantia: ela nunca precisa
    lidar com sobra maior que a dívida conhecida.
    """
    r = client.post(
        f"/api/v1/workspaces/{casa['ws'].id}/settlements",
        json={
            "from_user_id": casa["bruno"].id,
            "to_user_id": casa["ana"].id,
            "amount": "200.00",
        },
        headers=casa["h"],
    )

    assert r.status_code == 400, r.text
    assert "160.00" in r.text, (
        f"a recusa não diz qual é a dívida atual: {r.text}"
    )


# --------------------------------------------------------------------------- #
# CONTRAPESOS — sem eles, "zerar tudo" passaria em todos os testes acima
# --------------------------------------------------------------------------- #

def test_controle_sem_acerto_os_meses_continuam_devendo(casa):
    assert _devido_no_mes(casa, "2026-07") == Decimal("100.00")
    assert _devido_no_mes(casa, "2026-08") == Decimal("60.00")


def test_controle_o_acerto_do_mes_continua_valendo_so_para_ele(casa):
    """O acerto COM `billing_month` não virou alocação automática: ele quita o
    mês que a pessoa escolheu, e só ele."""
    _acertar(casa, "60.00", billing_month="2026-08")

    assert _devido_no_mes(casa, "2026-08") == Decimal("0")
    assert _devido_no_mes(casa, "2026-07") == Decimal("100.00"), (
        "o acerto de agosto vazou para julho"
    )


def test_controle_acerto_de_outro_par_nao_alcanca_este(casa, db_session: Session):
    """A alocação é POR PAR de pessoas. Um acerto entre outras duas não pode
    abater a dívida do Bruno."""
    carla = User(name="Carla", email="carla@acerto.com", password_hash="h")
    db_session.add(carla)
    db_session.commit()
    db_session.add(WorkspaceMembership(
        workspace_id=casa["ws"].id, user_id=carla.id, role=WorkspaceRole.member,
    ))
    db_session.add(Settlement(
        workspace_id=casa["ws"].id, from_user_id=carla.id, to_user_id=casa["ana"].id,
        amount=Decimal("100.00"), created_by_user_id=casa["ana"].id,
    ))
    db_session.commit()

    assert _devido_no_mes(casa, "2026-07") == Decimal("100.00"), (
        "o acerto da Carla abateu a dívida do Bruno"
    )


def test_controle_acerto_desfeito_devolve_a_divida(casa):
    """Desfazer é o caminho de correção (não há edição de acerto): a dívida do
    mês tem de voltar exatamente como estava."""
    criado = _acertar(casa, "100.00")
    assert _devido_no_mes(casa, "2026-07") == Decimal("0")

    r = client.delete(
        f"/api/v1/workspaces/{casa['ws'].id}/settlements/{criado['id']}", headers=casa["h"],
    )
    assert r.status_code == 200, r.text

    assert _devido_no_mes(casa, "2026-07") == Decimal("100.00")
