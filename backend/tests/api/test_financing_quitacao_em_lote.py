"""Quitar em lote as parcelas anteriores de um contrato antigo.

O app gera o cronograma inteiro no cadastro, e toda parcela nasce `is_paid=False`.
Quem registra um financiamento **que já existia** fica no mesmo instante com meses
de parcelas "em aberto" que na vida real foram pagas — e ninguém volta para marcar
doze delas uma a uma.

`projection_service` passou a separar vencido de a vencer, o que resolve o
**efeito** (a primeira tela deixou de anunciar dívida do tamanho do atraso). Esta
rota resolve a **causa**.

Os três limites que este arquivo tranca, e cada um por um motivo diferente:

1. **O futuro não é tocado** — senão a rota vira "quitar o contrato".
2. **Idempotente** — a interface oferece o botão sem medo de repetição.
3. **Não inventa caixa** — marcar como paga é dizer "aconteceu antes de o app
   existir para mim". Criar lançamento retroativo reescreveria extrato e
   resultado de meses fechados, que é o que o ADR 0023 proíbe.
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
    user = User(name="Lia", email="quitacao@t.com", password_hash="h", report_currency="BRL")
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return {
        "db": db_session,
        "headers": {"Cookie": f"access_token={create_access_token(data={'sub': str(user.id)})}"},
    }


def _financiamento(cena, *, vencimentos: list):
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


def _quitar(cena, financing_id, **corpo):
    return client.post(
        f"/api/v1/me/financing/{financing_id}/installments/settle-past",
        json=corpo,
        headers=cena["headers"],
    )


#: Meses que a varredura do caixa cobre: do mais antigo vencimento usado nos
#: testes até o mês que vem. `/me/ledger` responde UM mês por vez, e medir só o
#: corrente foi o defeito da primeira versão deste arquivo — ela enxergava uma
#: das três saídas criadas, e nenhuma nos dias do mês em que `HOJE-10` caía no
#: mês anterior. O teste passava por calendário, não por correção.
#:
#: A folga de um mês para trás não é enfeite: `paid_at` é gravado à meia-noite do
#: vencimento e o extrato agrupa por dia LOCAL, então a parcela que vence no dia
#: 1º aparece no último dia do mês anterior.
_JANELA = [-3, -2, -1, 0, 1]


def _meses_da_janela():
    meses = []
    for deslocamento in _JANELA:
        mes = HOJE.month + deslocamento
        ano = HOJE.year + (mes - 1) // 12
        meses.append(f"{ano:04d}-{(mes - 1) % 12 + 1:02d}")
    return meses


def _linhas_de_caixa(cena):
    """Todo movimento de caixa da janela, mês a mês."""
    linhas = []
    for mes in _meses_da_janela():
        resposta = client.get(f"/api/v1/me/ledger?month={mes}", headers=cena["headers"])
        assert resposta.status_code == 200, resposta.text
        linhas += resposta.json()["entries"]
    return linhas


def test_quita_as_vencidas_e_deixa_o_futuro_em_paz(cena):
    fin = _financiamento(cena, vencimentos=[-40, -25, -10, +5, +35])

    r = _quitar(cena, fin["id"])

    assert r.status_code == 200, r.text
    assert r.json()["quitadas"] == 3, (
        f"esperava 3 parcelas vencidas quitadas, veio {r.json()['quitadas']}"
    )

    db = cena["db"]
    futuras_pagas = db.exec(
        select(AmortizationInstallment)
        .where(AmortizationInstallment.financing_id == fin["id"])
        .where(AmortizationInstallment.due_date >= HOJE)
        .where(AmortizationInstallment.is_paid.is_(True))
    ).all()
    assert futuras_pagas == [], (
        "a rota quitou parcela que ainda vai vencer — ela vira 'quitar o contrato'"
    )


def test_a_parcela_que_vence_hoje_continua_em_aberto(cena):
    """O corte é estrito: hoje ainda vai ser pago."""
    fin = _financiamento(cena, vencimentos=[-10, 0])

    assert _quitar(cena, fin["id"]).json()["quitadas"] == 1


def test_e_idempotente(cena):
    """Chamar de novo não muda nada — é o que permite oferecer o botão."""
    fin = _financiamento(cena, vencimentos=[-40, -25, +5])

    primeira = _quitar(cena, fin["id"]).json()
    segunda = _quitar(cena, fin["id"]).json()

    assert primeira["quitadas"] == 2
    assert segunda["quitadas"] == 0
    assert primeira["em_aberto"] == segunda["em_aberto"]


def test_nao_inventa_movimento_de_caixa(cena):
    """Marcar como paga NÃO cria despesa: o passado não é reescrito (ADR 0023)."""
    fin = _financiamento(cena, vencimentos=[-40, -25, -10, +5])

    antes = _linhas_de_caixa(cena)
    _quitar(cena, fin["id"])
    depois = _linhas_de_caixa(cena)

    de_parcela = [linha for linha in depois if linha["source"] == "financing_installment"]
    assert de_parcela == [], (
        "a quitação em lote criou movimento de caixa — isso reescreve meses "
        f"fechados e é exatamente o que o ADR 0023 proíbe: {de_parcela}"
    )
    assert len(depois) == len(antes), (
        f"a quitação mexeu no caixa por outra fonte: {antes} -> {depois}"
    )


def test_a_parcela_paga_DE_VERDADE_continua_no_caixa(cena):
    """O controle do teste acima — sem ele, a varredura poderia estar cega.

    Um filtro largo demais (por exemplo, suprimir do caixa toda parcela sem
    despesa vinculada) deixaria o teste anterior verde e apagaria a fonte 4
    inteira: quem paga a parcela pelo app, sem lançar despesa em workspace
    nenhum, tem na parcela a única testemunha de que o dinheiro saiu.
    """
    fin = _financiamento(cena, vencimentos=[-10, +5])

    r = client.post(
        f"/api/v1/me/financing/{fin['id']}/installments/1/pay",
        json={},
        headers=cena["headers"],
    )
    assert r.status_code == 200, r.text

    de_parcela = [
        linha for linha in _linhas_de_caixa(cena)
        if linha["source"] == "financing_installment"
    ]
    assert len(de_parcela) == 1, (
        "pagar a parcela pelo app tem de sair no extrato — a varredura do teste "
        f"irmão está cega ou o filtro novo comeu a fonte 4: {de_parcela}"
    )


def test_estornar_devolve_a_parcela_ao_caixa(cena):
    """`unpay` limpa o marcador: ele é do fato antigo, não da parcela.

    Sem isso, uma parcela que veio da quitação em lote e depois fosse paga de
    verdade ficaria invisível no caixa para sempre.
    """
    fin = _financiamento(cena, vencimentos=[-10, +5])
    _quitar(cena, fin["id"])

    client.post(
        f"/api/v1/me/financing/{fin['id']}/installments/1/unpay",
        headers=cena["headers"],
    )
    client.post(
        f"/api/v1/me/financing/{fin['id']}/installments/1/pay",
        json={},
        headers=cena["headers"],
    )

    de_parcela = [
        linha for linha in _linhas_de_caixa(cena)
        if linha["source"] == "financing_installment"
    ]
    assert len(de_parcela) == 1, (
        f"a parcela paga depois do estorno não voltou ao caixa: {de_parcela}"
    )


def test_paid_at_guarda_o_vencimento_e_nao_hoje(cena):
    """Doze parcelas carimbadas com a data de hoje inventariam um dia em que
    tudo foi pago de uma vez."""
    fin = _financiamento(cena, vencimentos=[-40, -25])

    _quitar(cena, fin["id"])

    db = cena["db"]
    pagas = db.exec(
        select(AmortizationInstallment)
        .where(AmortizationInstallment.financing_id == fin["id"])
        .where(AmortizationInstallment.is_paid.is_(True))
    ).all()
    for parcela in pagas:
        marcado = parcela.paid_at.date() if hasattr(parcela.paid_at, "date") else parcela.paid_at
        assert marcado == parcela.due_date, (
            f"parcela que venceu em {parcela.due_date} foi carimbada como paga "
            f"em {marcado}"
        )


def test_a_projecao_se_acalma_depois_da_quitacao(cena):
    """O fecho do ciclo: quitar o passado tira o aviso de atraso da primeira tela."""
    fin = _financiamento(cena, vencimentos=[-40, -25, -10, +5])

    antes = client.get("/api/v1/me/balance", headers=cena["headers"]).json()
    assert float(antes["overdue_total"]) > 0

    _quitar(cena, fin["id"])

    depois = client.get("/api/v1/me/balance", headers=cena["headers"]).json()
    assert float(depois["overdue_total"]) == 0
    assert float(depois["payable_total"]) > 0, (
        "a parcela que ainda vai vencer sumiu junto com a quitação do passado"
    )
