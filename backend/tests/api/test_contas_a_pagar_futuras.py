"""A conta futura conhecida é obrigação hoje (ADR 0034).

O defeito que abre esta onda, nas palavras do dono:

> Em 28/08 cadastro uma despesa recorrente, vencimento todo dia 18. Em setembro
> deveria existir uma obrigação em 18/09 — e ela deveria ficar visível
> antecipadamente em Contas a Pagar, mesmo antes do vencimento.

Duas causas somadas: a materialização cobria só o mês corrente, e `PayablesService`
filtrava `REALIZED_STATUSES`, que não inclui `pending`. A ocorrência existia e era
invisível como dívida.

**O teste mais importante do arquivo é `test_liquidar_pendente_promove_e_vira_caixa`.**
Contas a pagar passou a usar `PAYABLE_STATUSES` e o caixa continua em
`REALIZED_STATUSES`: sem a promoção ao liquidar, a despesa paga sairia da lista e
não entraria no caixa — o dinheiro sumiria dos dois lados, em silêncio.
"""
from datetime import date, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from app.core.jwt import create_access_token
from app.domain.dates import civil_instant, month_key, today_local
from app.main import app
from app.models.transaction import Transaction, TransactionStatus
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMembership, WorkspaceRole

client = TestClient(app)

HOJE = today_local()
ONTEM = HOJE - timedelta(days=1)


@pytest.fixture(name="cena")
def cena_fixture(db_session: Session, override_get_session):
    user = User(name="Dona", email="futuras@t.com", password_hash="h", report_currency="BRL")
    db_session.add(user)
    ws = Workspace(name="Casa", base_currency="BRL")
    db_session.add(ws)
    db_session.flush()
    db_session.add(
        WorkspaceMembership(workspace_id=ws.id, user_id=user.id, role=WorkspaceRole.owner)
    )
    db_session.commit()
    db_session.refresh(user)
    token = create_access_token(data={"sub": str(user.id)})
    return {
        "db": db_session,
        "user_id": user.id,
        "ws_id": ws.id,
        "headers": {"Cookie": f"access_token={token}"},
    }


def _lanca(cena, dia: date, titulo="Energia", valor="350.00", **extra):
    """Um boleto com vencimento em `dia`, criado pela API (decide `settled_at`)."""
    r = client.post(
        f"/api/v1/workspaces/{cena['ws_id']}/transactions/",
        json={
            "title": titulo,
            "total_amount": valor,
            "transaction_date": civil_instant(dia).isoformat(),
            "billing_month": month_key(dia),
            "payment_method": "boleto",
            "payers": [{"user_id": cena["user_id"], "amount": valor}],
            "splits": [
                {"user_id": cena["user_id"], "split_method": "fixed", "input_value": valor}
            ],
            **extra,
        },
        headers=cena["headers"],
    )
    assert r.status_code == 200, r.text
    return r.json()


def _pendencias(cena, month=None):
    url = "/api/v1/me/payables" + (f"?month={month}" if month else "")
    r = client.get(url, headers=cena["headers"])
    assert r.status_code == 200, r.text
    return r.json()


def _pending(cena, dia: date, titulo="Energia", valor="350.00"):
    """Uma ocorrência como a recorrência a materializa: `pending`, não liquidada.

    Construída direto no banco porque é o que a materialização faz — e é
    justamente esse conjunto de linhas que a tela não enxergava.
    """
    from app.models.transaction import TransactionPayer, TransactionSplit

    tx = Transaction(
        title=titulo, total_amount=Decimal(valor), currency="BRL",
        transaction_date=civil_instant(dia), billing_month=month_key(dia),
        status=TransactionStatus.pending, settled_at=None,
        workspace_id=cena["ws_id"], created_by_user_id=cena["user_id"],
    )
    cena["db"].add(tx)
    cena["db"].flush()
    cena["db"].add(TransactionPayer(
        transaction_id=tx.id, user_id=cena["user_id"], amount=Decimal(valor)
    ))
    cena["db"].add(TransactionSplit(
        transaction_id=tx.id, user_id=cena["user_id"],
        split_method="fixed", input_value=Decimal(valor),
        computed_amount=Decimal(valor),
    ))
    cena["db"].commit()
    cena["db"].refresh(tx)
    return tx


# ---------------------------------------------------------------------------
# 1. `pending` é obrigação


def test_ocorrencia_futura_pendente_aparece_em_contas_a_pagar(cena):
    """O defeito de origem: ela existia e não era dívida para o sistema."""
    dia_18 = date(HOJE.year, HOJE.month, 18)
    _pending(cena, dia_18)

    corpo = _pendencias(cena)
    assert [e["title"] for e in corpo["entries"]] == ["Energia"]
    assert Decimal(corpo["total"]) == Decimal("350.00")


def test_pendente_nao_contamina_o_realizado(cena):
    """"Não resolva isso adicionando `pending` em `REALIZED_STATUSES`."

    O consumo, o relatório e a dívida entre membros continuam vendo só o realizado.
    """
    _pending(cena, date(HOJE.year, HOJE.month, 18))

    visao = client.get("/api/v1/me/overview", headers=cena["headers"]).json()
    assert Decimal(visao["consumption"]) == Decimal("0.00")
    assert Decimal(visao["paid_in_transactions"]) == Decimal("0.00")
    assert Decimal(visao["cash_out"]) == Decimal("0.00")
    # ...e ao mesmo tempo é obrigação:
    assert Decimal(visao["payables_total"]) == Decimal("350.00")


def test_chegar_o_vencimento_nao_significa_pago(cena):
    """§12: "Chegar na data de vencimento NÃO significa automaticamente que o
    dinheiro saiu. Esse ponto é fundamental."."""
    tx = _pending(cena, ONTEM)

    corpo = _pendencias(cena)
    linha = next(e for e in corpo["entries"] if e["transaction_id"] == tx.id)
    assert linha["due_state"] == "overdue"
    assert linha["days_until_due"] == -1
    assert Decimal(corpo["overdue_total"]) == Decimal("350.00")

    visao = client.get("/api/v1/me/overview", headers=cena["headers"]).json()
    assert Decimal(visao["cash_out"]) == Decimal("0.00"), "vencer não é pagar"


def test_estados_de_vencimento(cena):
    _pending(cena, ONTEM, titulo="Atrasada")
    _pending(cena, HOJE, titulo="Hoje")
    if HOJE.day < 28:
        _pending(cena, date(HOJE.year, HOJE.month, 28), titulo="Futura")

    por_titulo = {e["title"]: e for e in _pendencias(cena)["entries"]}
    assert por_titulo["Atrasada"]["due_state"] == "overdue"
    assert por_titulo["Hoje"]["due_state"] == "due_today"
    assert por_titulo["Hoje"]["days_until_due"] == 0
    if "Futura" in por_titulo:
        assert por_titulo["Futura"]["due_state"] == "upcoming"


# ---------------------------------------------------------------------------
# 2. A conta do começo do mês seguinte (§21)


def test_conta_do_mes_seguinte_aparece_em_proximas(cena):
    """"Hoje é 28/08. Existe despesa recorrente todo dia 01. O usuário precisa
    enxergar 'Aluguel — vence 01/09' ANTES da virada de mês."."""
    primeiro_do_proximo = (HOJE.replace(day=1) + timedelta(days=32)).replace(day=1)
    _pending(cena, primeiro_do_proximo, titulo="Aluguel", valor="2000.00")

    corpo = _pendencias(cena)
    assert [e["title"] for e in corpo["entries"]] == [], "não é deste mês"
    assert [e["title"] for e in corpo["upcoming"]] == ["Aluguel"]
    assert Decimal(corpo["total"]) == Decimal("0.00"), (
        "o total do mês não pode inflar com a conta do mês que vem"
    )


def test_proximas_nao_vai_alem_do_mes_seguinte(cena):
    """O horizonte da lista é o mesmo da materialização — mostrar mais prometeria
    uma lista que nem sempre existe."""
    daqui_a_tres_meses = (HOJE.replace(day=1) + timedelta(days=100)).replace(day=1)
    _pending(cena, daqui_a_tres_meses, titulo="Longe")

    assert [e["title"] for e in _pendencias(cena)["upcoming"]] == []


# ---------------------------------------------------------------------------
# 3. O teste que protege o ponto mais perigoso da onda


def test_liquidar_pendente_promove_e_vira_caixa(cena):
    """Sem a promoção `pending → confirmed`, o dinheiro sumiria dos dois lados.

    A lista usa `PAYABLE_STATUSES` e o caixa usa `REALIZED_STATUSES`. Liquidar
    uma `pending` a tira da primeira; só a promoção a coloca no segundo.
    """
    tx = _pending(cena, HOJE, valor="350.00")

    r = client.post(
        f"/api/v1/workspaces/{cena['ws_id']}/payables/settle",
        json={"transaction_ids": [tx.id], "settled": True, "settled_on": HOJE.isoformat()},
        headers=cena["headers"],
    )
    assert r.status_code == 200, r.text
    assert r.json()["updated"] == 1

    cena["db"].expire_all()
    depois = cena["db"].get(Transaction, tx.id)
    assert depois.status == TransactionStatus.confirmed, "a promoção aconteceu"
    assert depois.settled_at is not None

    visao = client.get("/api/v1/me/overview", headers=cena["headers"]).json()
    assert Decimal(visao["cash_out"]) == Decimal("350.00"), (
        "a saída tem de aparecer no caixa EXATAMENTE uma vez"
    )
    assert Decimal(visao["payables_total"]) == Decimal("0.00"), "saiu da fila"


def test_liquidar_com_conta_move_o_saldo_uma_vez_so(cena):
    conta = client.post(
        "/api/v1/me/payment-accounts",
        json={"name": "Nubank", "type": "checking", "currency": "BRL"},
        headers=cena["headers"],
    ).json()
    client.put(
        f"/api/v1/me/payment-accounts/{conta['id']}/opening-balance",
        json={"amount": "1000.00", "as_of": ONTEM.isoformat()},
        headers=cena["headers"],
    )
    tx = _pending(cena, HOJE, valor="350.00")

    client.post(
        f"/api/v1/workspaces/{cena['ws_id']}/payables/settle",
        json={
            "transaction_ids": [tx.id], "settled": True,
            "settled_on": HOJE.isoformat(), "account_id": conta["id"],
        },
        headers=cena["headers"],
    )

    corpo = client.get("/api/v1/me/balance", headers=cena["headers"]).json()
    assert Decimal(corpo["total"]) == Decimal("650.00")
    assert corpo["unassigned_movements"] == 0


def test_liquidar_com_conta_de_outra_moeda_e_recusado(cena):
    """A invariante do ADR 0034 vale também na porta mais usada do app."""
    conta = client.post(
        "/api/v1/me/payment-accounts",
        json={"name": "Wise", "type": "checking", "currency": "USD"},
        headers=cena["headers"],
    ).json()
    tx = _pending(cena, HOJE)

    r = client.post(
        f"/api/v1/workspaces/{cena['ws_id']}/payables/settle",
        json={
            "transaction_ids": [tx.id], "settled": True, "account_id": conta["id"],
        },
        headers=cena["headers"],
    )
    assert r.status_code == 400
    assert "USD" in r.json()["error"]["message"]

    cena["db"].expire_all()
    assert cena["db"].get(Transaction, tx.id).settled_at is None, (
        "a recusa não pode deixar metade do lote gravada"
    )


def test_boleto_futuro_nao_pendente_continua_valendo(cena):
    """O caminho do ADR 0029 não regrediu: o boleto que a PESSOA cadastrou para o
    dia 28 nasce `confirmed` e não liquidado, e continua sendo conta a pagar."""
    if HOJE.day >= 28:
        pytest.skip("sem dia futuro dentro do mês corrente")
    criado = _lanca(cena, date(HOJE.year, HOJE.month, 28))
    assert criado["status"] == "confirmed"
    assert criado["settled_at"] is None

    corpo = _pendencias(cena)
    assert [e["title"] for e in corpo["entries"]] == ["Energia"]
