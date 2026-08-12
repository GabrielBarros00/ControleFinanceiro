"""Os dois defeitos da amortização encontrados na auditoria, pela API de verdade.

`interest_rate` não tem teto no schema e `installments_count` vai até 600: o par
extremo era aceito e chegava inteiro ao cálculo. Os dois casos abaixo foram
CONFERIDOS falhando antes da correção — 500 num, parcela negativa no outro.
"""
from decimal import Decimal

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)
# Sem `raise_server_exceptions`, o TestClient relança a exceção do servidor e o
# teste morre com o traceback em vez de mostrar o STATUS que o navegador veria.
cliente_http = TestClient(app, raise_server_exceptions=False)


def _corpo(**kw):
    corpo = {
        "title": "Auditoria",
        "total_amount": 250000.0,
        "interest_rate": 0.01,
        "installments_count": 12,
        "start_date": "2026-01-15",
        "method": "PRICE",
    }
    corpo.update(kw)
    return corpo


def test_taxa_que_nao_amortiza_responde_422_e_nao_500(
    db_session, setup_data, override_get_session
):
    """R$ 12.345,67 a 0,5 a.m. em 360x devolvia **HTTP 500**.

    A PMT arredondada não cobria os juros do período, a amortização ficava
    negativa, o saldo crescia composto e o `Decimal` estourava
    (`InvalidOperation`) lá pela centésima parcela.
    """
    res = cliente_http.post(
        "/api/v1/me/financing",
        json=_corpo(total_amount=12345.67, interest_rate=0.5, installments_count=360),
        headers=setup_data["headers1"],
    )
    assert res.status_code == 422, f"esperado 422, veio {res.status_code}"


def test_prazo_longo_demais_nao_gera_parcela_negativa(
    db_session, setup_data, override_get_session
):
    """R$ 10,00 em 600x (SAC) terminava com uma parcela de `-1,98`.

    A cota era `round(10/600) = 0,02`, e 599 × 0,02 = R$ 11,98 já passava do
    total: a última parcela recebia o saldo restante, que a essa altura era
    negativo. O saldo exibido saía como `0,00` (`max(0, saldo)`), então a tela
    mostrava uma parcela de valor negativo com saldo zerado.
    """
    headers = setup_data["headers1"]
    res = client.post(
        "/api/v1/me/financing",
        json=_corpo(total_amount=10.0, installments_count=600,
                    interest_rate=0.01, method="SAC"),
        headers=headers,
    )
    assert res.status_code == 200, res.status_code
    fin_id = res.json()["id"]

    sched = client.get(f"/api/v1/me/financing/{fin_id}/schedule", headers=headers)
    assert sched.status_code == 200, sched.status_code
    parcelas = sched.json()

    negativas = [p for p in parcelas if Decimal(str(p["principal_amount"])) < 0]
    assert not negativas, (
        f"{len(negativas)} parcela(s) com amortização NEGATIVA — ex.: "
        f"#{negativas[0]['installment_number']} = {negativas[0]['principal_amount']}"
    )
    # E o cronograma continua fechando no total exato.
    soma = sum(Decimal(str(p["principal_amount"])) for p in parcelas)
    assert soma == Decimal("10.00"), f"amortizações somam {soma}, não 10.00"


def test_parcela_abaixo_de_um_centavo_e_recusada(
    db_session, setup_data, override_get_session
):
    """R$ 1,00 em 600x não tem cronograma: daria menos de um centavo por mês."""
    res = cliente_http.post(
        "/api/v1/me/financing",
        json=_corpo(total_amount=1.0, installments_count=600, method="SAC"),
        headers=setup_data["headers1"],
    )
    assert res.status_code == 422, f"esperado 422, veio {res.status_code}"
