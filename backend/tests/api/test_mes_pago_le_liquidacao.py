""""Pago" no mês tem de contar o que foi pago.

## O relato

"Quando registro um acerto no mês, ele não atualiza o valor Pago também."

Investigando, o acerto do mês funciona: ele zera `net_debts` e aparece em
`settled_total`. O que não muda **nunca** é o quadro "Pago" — e não muda para
ninguém, com acerto ou sem.

## A causa

`totals.paid` e o selo "Paga/Em aberto" de cada linha leem
`Transaction.status == paid`. Esse status existe no enum e no diagrama de
transições — e **nenhuma rota do app o grava**. A única coisa que vira `paid`
neste produto é FATURA (`StatementStatus.paid`), que é outro modelo.

Desde o ADR 0029, "pago" numa despesa é `settled_at`: a data em que o dinheiro
saiu. O ledger mensal ficou lendo o eixo antigo, então mostra "Pago R$ 0,00" e
"Em aberto R$ 320,00" num mês em que tudo foi pago à vista — e todo lançamento
com o selo "Em aberto", inclusive os quitados.

## A compra no cartão

Ela nunca tem `settled_at`: quem se paga é a fatura (ADR 0029 exclui a compra no
cartão do recorte "a pagar"). Chamá-la de "em aberto" seria trocar um número
errado por outro — ela ganha estado próprio.
"""
import datetime
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from app.core.jwt import create_access_token
from app.main import app
from app.models.credit_card import CreditCard
from app.models.transaction import Transaction, TransactionPayer, TransactionSplit
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMembership, WorkspaceRole

client = TestClient(app)

MES = "2026-07"
QUANDO = datetime.datetime(2026, 7, 10, 12, 0, tzinfo=datetime.UTC)


@pytest.fixture(name="casa")
def casa_fixture(db_session: Session, override_get_session):
    ana = User(name="Ana", email="ana@pago.com", password_hash="h")
    ws = Workspace(name="Casa", base_currency="BRL")
    db_session.add_all([ana, ws])
    db_session.commit()
    db_session.add(WorkspaceMembership(
        workspace_id=ws.id, user_id=ana.id, role=WorkspaceRole.owner,
    ))
    db_session.commit()

    def despesa(titulo, valor, *, liquidada, cartao_id=None):
        tx = Transaction(
            title=titulo, total_amount=Decimal(valor), currency="BRL",
            transaction_date=QUANDO, billing_month=MES, status="confirmed",
            workspace_id=ws.id, created_by_user_id=ana.id,
            settled_at=QUANDO if liquidada else None,
            credit_card_id=cartao_id,
        )
        db_session.add(tx)
        db_session.commit()
        db_session.refresh(tx)
        db_session.add_all([
            TransactionPayer(transaction_id=tx.id, user_id=ana.id, amount=Decimal(valor)),
            TransactionSplit(transaction_id=tx.id, user_id=ana.id,
                             input_value=Decimal(valor), computed_amount=Decimal(valor)),
        ])
        db_session.commit()
        return tx

    return {
        "db": db_session, "ws": ws, "ana": ana, "despesa": despesa,
        "h": {"Cookie": f"access_token={create_access_token({'sub': str(ana.id)})}"},
    }


def _mes(casa):
    r = client.get(
        f"/api/v1/workspaces/{casa['ws'].id}/debts/monthly?month={MES}", headers=casa["h"],
    )
    assert r.status_code == 200, r.text
    return r.json()


def test_pago_conta_a_despesa_liquidada(casa):
    casa["despesa"]("Mercado", "200.00", liquidada=True)
    casa["despesa"]("Boleto que ainda vou pagar", "120.00", liquidada=False)

    totais = _mes(casa)["totals"]

    assert Decimal(str(totais["paid"])) == Decimal("200.00"), (
        f'"Pago" veio {totais["paid"]} num mês com R$ 200 já pagos — ele está '
        "lendo o status morto em vez de `settled_at` (ADR 0029)"
    )
    assert Decimal(str(totais["open"])) == Decimal("120.00")
    assert Decimal(str(totais["total"])) == Decimal("320.00")


def test_o_selo_da_linha_acompanha(casa):
    casa["despesa"]("Mercado", "200.00", liquidada=True)
    casa["despesa"]("Boleto", "120.00", liquidada=False)

    por_titulo = {e["title"]: e for e in _mes(casa)["expenses"]}

    assert por_titulo["Mercado"]["is_paid"] is True, (
        "a despesa paga aparece como 'Em aberto' na lista do mês"
    )
    assert por_titulo["Boleto"]["is_paid"] is False


def test_a_compra_no_cartao_nao_e_em_aberto(casa):
    """Quem paga a compra no cartão é a FATURA — ela nunca tem `settled_at`.

    Sem estado próprio, ela ficaria para sempre no "Em aberto" do mês, e o
    número voltaria a ser tão errado quanto o que este arquivo corrige.
    """
    db = casa["db"]
    cartao = CreditCard(
        name="Nubank", limit=Decimal("5000.00"), closing_day=1, due_day=10,
        currency="BRL", owner_user_id=casa["ana"].id,
    )
    db.add(cartao)
    db.commit()
    db.refresh(cartao)
    casa["despesa"]("Assinatura", "50.00", liquidada=False, cartao_id=cartao.id)

    corpo = _mes(casa)
    linha = next(e for e in corpo["expenses"] if e["title"] == "Assinatura")

    assert linha["on_card"] is True, (
        "a compra no cartão não se identifica como tal, e cai no 'Em aberto'"
    )
    assert Decimal(str(corpo["totals"]["open"])) == Decimal("0"), (
        "a compra no cartão entrou no 'Em aberto' do mês — quem a paga é a fatura"
    )


def test_controle_mes_sem_nada_liquidado_continua_zerado(casa):
    """Sem isto, "somar tudo" passaria nos testes acima."""
    casa["despesa"]("Boleto", "120.00", liquidada=False)

    totais = _mes(casa)["totals"]
    assert Decimal(str(totais["paid"])) == Decimal("0")
    assert Decimal(str(totais["open"])) == Decimal("120.00")
