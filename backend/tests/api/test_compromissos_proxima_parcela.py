"""Compromissos: "próxima parcela" é a próxima A PARTIR DE HOJE.

A tela lista financiamentos sob o título "Faturas e financiamentos **a vencer**", e
a data que ela mostrava vinha de `em_aberto[0]` — a parcela mais antiga que ninguém
marcou como paga. Num contrato cadastrado depois de já ter começado (o caso de quem
registra um financiamento que já existia), isso é uma data no passado: o catálogo de
telas do projeto mostrava **"próxima em 31/08/2025"** com mais de um ano de atraso.

Quem lê uma data velha embaixo de "a vencer" conclui que o app está errado. E
estava.

O atraso continua na tela — em `overdue_count` e no total `overdue` — mas ele deixa
de ocupar o lugar da próxima.
"""
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.core.jwt import create_access_token
from app.domain.dates import today_local
from app.main import app
from app.models.financing import AmortizationInstallment
from app.models.user import User

client = TestClient(app)

HOJE = today_local()


@pytest.fixture(name="cena")
def cena_fixture(db_session: Session, override_get_session):
    user = User(name="Caio", email="compromissos@t.com", password_hash="h", report_currency="BRL")
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return {
        "db": db_session,
        "headers": {"Cookie": f"access_token={create_access_token(data={'sub': str(user.id)})}"},
    }


def _financiamento(cena, *, vencimentos: list):
    """Cronograma com datas ditas, não deduzidas — a primeira parcela vence
    `start_date + 1 mês`, então deixar as datas por conta do serviço faria o
    resultado depender do dia em que o teste roda."""
    r = client.post(
        "/api/v1/me/financing",
        json={
            "title": "Apartamento",
            "total_amount": "300000.00",
            "interest_rate": "0.008",
            "start_date": HOJE.isoformat(),
            "installments_count": max(len(vencimentos), 2),
            "method": "SAC",
        },
        headers=cena["headers"],
    )
    assert r.status_code == 200, r.text
    fin = r.json()
    db = cena["db"]
    parcelas = db.exec(
        select(AmortizationInstallment)
        .where(AmortizationInstallment.financing_id == fin["id"])
        .order_by(AmortizationInstallment.installment_number)
    ).all()
    for i, parcela in enumerate(parcelas):
        parcela.due_date = (
            HOJE + timedelta(days=vencimentos[i]) if i < len(vencimentos)
            else HOJE + timedelta(days=3650)
        )
        db.add(parcela)
    db.commit()
    return fin


def _compromissos(cena):
    r = client.get("/api/v1/me/commitments", headers=cena["headers"])
    assert r.status_code == 200, r.text
    return r.json()


def test_proxima_parcela_nao_e_uma_data_no_passado(cena):
    """Três vencidas e uma a vencer: a "próxima" é a que ainda vai vencer."""
    _financiamento(cena, vencimentos=[-40, -25, -10, +5])

    fin = _compromissos(cena)["financings"][0]

    assert fin["next_due_date"] == (HOJE + timedelta(days=5)).isoformat(), (
        f"a tela diz 'próxima em {fin['next_due_date']}', que é anterior a hoje "
        f"({HOJE}) — é a parcela mais antiga em aberto ocupando o lugar da próxima"
    )


def test_o_atraso_continua_visivel_em_campo_proprio(cena):
    """Contrapeso: corrigir a data não pode esconder que há atraso."""
    _financiamento(cena, vencimentos=[-40, -25, -10, +5])

    fin = _compromissos(cena)["financings"][0]

    assert fin["overdue_count"] == 3, (
        f"esperava 3 parcelas vencidas, veio {fin['overdue_count']} — o atraso "
        "sumiu junto com a correção da data"
    )


def test_a_tela_expoe_o_valor_da_proxima_parcela(cena):
    """O número acionável de "a vencer" é a parcela, não o contrato inteiro.

    O destaque da linha era `outstanding` — o saldo devedor do contrato, que num
    imóvel é R$ 1.250.000 numa tela sobre o próximo vencimento.
    """
    _financiamento(cena, vencimentos=[+5])

    fin = _compromissos(cena)["financings"][0]

    assert fin.get("next_amount") is not None, "a próxima parcela não tem valor"
    assert float(fin["next_amount"]) < float(fin["outstanding"]), (
        "o valor da próxima parcela não pode ser o saldo devedor inteiro"
    )


def test_controle_quem_esta_em_dia_nao_tem_atraso(cena):
    """Sem parcela vencida, `overdue_count` é zero — o aviso não aparece sempre."""
    _financiamento(cena, vencimentos=[+5])

    fin = _compromissos(cena)["financings"][0]

    assert fin["overdue_count"] == 0
    assert fin["next_due_date"] == (HOJE + timedelta(days=5)).isoformat()
