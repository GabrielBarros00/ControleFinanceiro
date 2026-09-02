"""Renda prevista × renda recebida (ADR 0034).

O caso do §22 do pedido, ponta a ponta: salário de R$ 6.000 no ÚLTIMO DIA DO MÊS.

> Durante setembro: deve aparecer como esperado, deve entrar na projeção, e **não**
> deve entrar no saldo real antes de recebido. Depois de recebido em 30/09: aumenta
> o saldo da conta, permanece no saldo em outubro, e não precisa ser artificialmente
> classificado como renda de outubro.

Antes desta onda `Income` tinha uma data só e nenhum estado: o salário do dia 30 ou
não existia até o dia 30, ou já contava como recebido no dia 1º. Não havia terceira
opção — e a que o app fazia era a segunda.
"""
from datetime import date, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from app.core.jwt import create_access_token
from app.domain.dates import HORIZONTE_MESES, civil_instant, month_key, today_local
from app.main import app
from app.models.user import User

client = TestClient(app)

HOJE = today_local()
ONTEM = HOJE - timedelta(days=1)
# Uma data que ainda não chegou DENTRO do mês corrente. Dia 28 dá margem em
# qualquer mês; se hoje já passou do 28, usa amanhã (que pode cair no mês seguinte,
# e o teste que depende do mês corrente é explícito sobre isso).
FUTURO = date(HOJE.year, HOJE.month, 28) if HOJE.day < 28 else HOJE + timedelta(days=1)


@pytest.fixture(name="pessoa")
def pessoa_fixture(db_session: Session, override_get_session):
    user = User(name="Dona", email="prevista@t.com", password_hash="h", report_currency="BRL")
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    token = create_access_token(data={"sub": str(user.id)})
    return {
        "db": db_session,
        "user_id": user.id,
        "headers": {"Cookie": f"access_token={token}"},
    }


def _conta(pessoa, nome="Nubank"):
    r = client.post(
        "/api/v1/me/payment-accounts",
        json={"name": nome, "type": "checking", "currency": "BRL"},
        headers=pessoa["headers"],
    )
    assert r.status_code == 200, r.text
    return r.json()


def _renda(pessoa, quando, valor="6000.00", **extra):
    r = client.post(
        "/api/v1/me/income",
        json={
            "title": "Salário", "amount": valor,
            "received_at": civil_instant(quando).isoformat(), **extra,
        },
        headers=pessoa["headers"],
    )
    assert r.status_code == 200, r.text
    return r.json()


def _overview(pessoa, month=None):
    url = "/api/v1/me/overview" + (f"?month={month}" if month else "")
    r = client.get(url, headers=pessoa["headers"])
    assert r.status_code == 200, r.text
    return r.json()


def _saldo(pessoa):
    r = client.get("/api/v1/me/balance", headers=pessoa["headers"])
    assert r.status_code == 200, r.text
    return r.json()


# ---------------------------------------------------------------------------
# 1. Os quatro estados


def test_renda_futura_nasce_prevista(pessoa):
    renda = _renda(pessoa, FUTURO)
    assert renda["status"] == "expected"
    assert renda["settled_at"] is None


def test_renda_passada_nasce_recebida(pessoa):
    """Quem lança a renda de ontem está anotando o que aconteceu."""
    renda = _renda(pessoa, ONTEM)
    assert renda["status"] == "received"
    assert renda["settled_at"] is not None


def test_renda_vencida_e_nao_recebida_fica_atrasada(pessoa):
    renda = _renda(pessoa, ONTEM, received=False)
    assert renda["status"] == "overdue"


def test_cancelar_e_diferente_de_excluir(pessoa):
    """A linha continua visível, explicando o que houve — e continua ocupando a
    vaga da ocorrência, para a materialização não recriá-la."""
    renda = _renda(pessoa, FUTURO)
    r = client.post(
        f"/api/v1/me/income/{renda['id']}/cancel", headers=pessoa["headers"]
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "cancelled"

    lista = client.get("/api/v1/me/income", headers=pessoa["headers"]).json()
    assert [i["status"] for i in lista] == ["cancelled"], "cancelada não some da tela"


# ---------------------------------------------------------------------------
# 2. Prevista não é caixa, mas é competência


def test_renda_prevista_nao_entra_no_caixa_mas_entra_no_resultado(pessoa):
    """A distinção que o §3 do pedido pede: competência ≠ caixa.

    O salário de 30/09 é renda de SETEMBRO (competência) mesmo antes de cair, e
    não é dinheiro que entrou (caixa) antes de cair.
    """
    _renda(pessoa, FUTURO)
    visao = _overview(pessoa, month=month_key(FUTURO))

    assert Decimal(visao["income"]) == Decimal("6000.00"), (
        "competência: a renda é do mês, recebida ou não"
    )
    assert Decimal(visao["cash_in"]) == Decimal("0.00"), (
        "caixa: nada entrou ainda"
    )
    assert Decimal(visao["cash_in_breakdown"]["income"]) == Decimal("0.00")


def test_renda_prevista_nao_entra_no_saldo_mas_entra_na_projecao(pessoa):
    conta = _conta(pessoa)
    client.put(
        f"/api/v1/me/payment-accounts/{conta['id']}/opening-balance",
        json={"amount": "1000.00", "as_of": ONTEM.isoformat()},
        headers=pessoa["headers"],
    )
    _renda(pessoa, FUTURO)

    corpo = _saldo(pessoa)
    assert Decimal(corpo["total"]) == Decimal("1000.00"), "prevista não é saldo"
    assert Decimal(corpo["receivable_total"]) == Decimal("6000.00")
    assert Decimal(corpo["projected_balance"]) == Decimal("7000.00")


def test_receber_move_o_saldo_da_conta(pessoa):
    conta = _conta(pessoa)
    client.put(
        f"/api/v1/me/payment-accounts/{conta['id']}/opening-balance",
        json={"amount": "1000.00", "as_of": ONTEM.isoformat()},
        headers=pessoa["headers"],
    )
    renda = _renda(pessoa, FUTURO)

    r = client.post(
        f"/api/v1/me/income/{renda['id']}/receive",
        json={"received_on": HOJE.isoformat(), "account_id": conta["id"]},
        headers=pessoa["headers"],
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "received"

    corpo = _saldo(pessoa)
    assert Decimal(corpo["total"]) == Decimal("7000.00")
    assert Decimal(corpo["receivable_total"]) == Decimal("0.00"), (
        "recebida sai de 'a receber' — senão contaria duas vezes na projeção"
    )
    assert Decimal(corpo["projected_balance"]) == Decimal("7000.00")


def test_receber_nao_move_a_competencia(pessoa):
    """"Não quero mover artificialmente o salário de setembro para outubro apenas
    porque ele financia as contas de outubro" (§3)."""
    renda = _renda(pessoa, FUTURO)
    depois = client.post(
        f"/api/v1/me/income/{renda['id']}/receive",
        json={"received_on": (FUTURO + timedelta(days=2)).isoformat()},
        headers=pessoa["headers"],
    ).json()

    assert depois["received_at"][:10] == FUTURO.isoformat(), (
        "a competência não se move quando o dinheiro atrasa"
    )
    assert depois["settled_at"][:10] == (FUTURO + timedelta(days=2)).isoformat()


def test_desfazer_recebimento_devolve_a_prevista(pessoa):
    renda = _renda(pessoa, ONTEM)
    r = client.post(
        f"/api/v1/me/income/{renda['id']}/unreceive", headers=pessoa["headers"]
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "overdue"
    assert r.json()["settled_at"] is None


def test_cancelada_nao_entra_em_lugar_nenhum(pessoa):
    renda = _renda(pessoa, FUTURO)
    client.post(f"/api/v1/me/income/{renda['id']}/cancel", headers=pessoa["headers"])

    visao = _overview(pessoa, month=month_key(FUTURO))
    assert Decimal(visao["income"]) == Decimal("0.00")
    assert Decimal(_saldo(pessoa)["receivable_total"]) == Decimal("0.00")


# ---------------------------------------------------------------------------
# 3. O salário do último dia do mês, com recorrência (§22)


def _template(pessoa, dia=31, auto_confirm=True, **extra):
    r = client.post(
        "/api/v1/me/recurring-income",
        json={
            "title": "Salário", "base_amount": "6000.00", "currency": "BRL",
            "frequency": "monthly", "day_of_month": dia,
            "auto_confirm": auto_confirm, **extra,
        },
        headers=pessoa["headers"],
    )
    assert r.status_code == 200, r.text
    return r.json()


def test_salario_do_ultimo_dia_aparece_como_previsto_durante_o_mes(pessoa):
    """Dia 31 vira o ÚLTIMO DIA VÁLIDO do mês (30 em setembro, 28/29 em fevereiro).

    E o ponto do teste: ele existe desde o dia 1º, visível, sem ser dinheiro em
    mãos. "Não quero que o salário fique invisível de 01/09 até 29/09. Mas também
    não quero que o sistema diga em 01/09 que os R$ 6.000 já foram recebidos."
    """
    import calendar

    _template(pessoa, dia=31)
    lista = client.get("/api/v1/me/income", headers=pessoa["headers"]).json()
    ultimo = calendar.monthrange(HOJE.year, HOJE.month)[1]
    deste_mes = [i for i in lista if i["billing_month"] == month_key(HOJE)]

    assert len(deste_mes) == 1, "a ocorrência do mês existe desde já"
    assert deste_mes[0]["received_at"][:10] == date(
        HOJE.year, HOJE.month, ultimo
    ).isoformat(), "dia 31 vira o último dia VÁLIDO do mês"

    # Se hoje ainda não é o último dia do mês, ela tem de estar prevista.
    if HOJE.day < ultimo:
        assert deste_mes[0]["status"] == "expected"
        assert deste_mes[0]["settled_at"] is None


def test_auto_confirm_desligado_deixa_a_ocorrencia_a_receber(pessoa):
    """Renda incerta — freela, aluguel — não se declara recebida sozinha."""
    _template(pessoa, dia=1, auto_confirm=False)
    lista = client.get("/api/v1/me/income", headers=pessoa["headers"]).json()
    assert len(lista) == HORIZONTE_MESES + 1
    assert all(i["settled_at"] is None for i in lista)
    assert all(i["status"] in ("expected", "overdue") for i in lista)


def test_auto_confirm_ligado_confirma_a_ocorrencia_ja_vencida(pessoa):
    _template(pessoa, dia=1, auto_confirm=True)
    lista = client.get("/api/v1/me/income", headers=pessoa["headers"]).json()
    deste_mes = [i for i in lista if i["billing_month"] == month_key(HOJE)]
    assert len(deste_mes) == 1
    assert deste_mes[0]["status"] == "received", (
        "dia 1º já passou (ou é hoje) e o template diz que cai sozinho"
    )
    # A do mês SEGUINTE não pode nascer recebida: `auto_confirm` nunca vence a
    # data. É o "não diga em 01/09 que os R$ 6.000 já foram recebidos".
    do_proximo = [i for i in lista if i["billing_month"] != month_key(HOJE)]
    assert all(i["status"] == "expected" for i in do_proximo)


def test_materializar_duas_vezes_nao_duplica(pessoa):
    """A unique de ocorrência é a barreira real, não a consulta prévia.

    O horizonte cria uma ocorrência por mês (a deste e a do mês seguinte); o que
    o teste afirma é que reabrir a tela não acrescenta nenhuma.
    """
    _template(pessoa, dia=1)
    primeira = client.get("/api/v1/me/income", headers=pessoa["headers"]).json()
    for _ in range(3):
        client.get("/api/v1/me/income", headers=pessoa["headers"])
    depois = client.get("/api/v1/me/income", headers=pessoa["headers"]).json()

    assert len(primeira) == HORIZONTE_MESES + 1, "uma por mês do horizonte"
    assert len(depois) == len(primeira)
    meses = [i["billing_month"] for i in depois]
    assert len(set(meses)) == len(meses), "duas ocorrências no mesmo mês"


def test_renda_recebida_continua_no_saldo_no_mes_seguinte(pessoa):
    """O caso central do §22: o dinheiro de setembro financia outubro.

    Saldo é contínuo — não existe "reset" na virada do mês. O que muda de mês é a
    COMPETÊNCIA, e ela fica onde estava.
    """
    conta = _conta(pessoa)
    client.put(
        f"/api/v1/me/payment-accounts/{conta['id']}/opening-balance",
        json={"amount": "0.00", "as_of": (HOJE - timedelta(days=60)).isoformat()},
        headers=pessoa["headers"],
    )
    mes_passado = (HOJE.replace(day=1) - timedelta(days=1))
    renda = _renda(pessoa, mes_passado)
    client.post(
        f"/api/v1/me/income/{renda['id']}/receive",
        json={"received_on": mes_passado.isoformat(), "account_id": conta["id"]},
        headers=pessoa["headers"],
    )

    # Competência: a renda é do mês PASSADO, nos dois sentidos.
    assert Decimal(_overview(pessoa, month=month_key(mes_passado))["income"]) == Decimal("6000.00")
    assert Decimal(_overview(pessoa, month=month_key(HOJE))["income"]) == Decimal("0.00")

    # Saldo: continua lá, sem ter sido reclassificado.
    assert Decimal(_saldo(pessoa)["total"]) == Decimal("6000.00")
