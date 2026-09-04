"""A projeção separa o que VENCE do que JÁ VENCEU (ADR 0034, revisto).

## O defeito que este arquivo tranca

As três fontes de "a pagar" da projeção somavam tudo com vencimento **até** o fim
do mês, sem piso inferior — e "não paga" é o estado padrão de toda parcela que o
app gera sozinho. Medido num cenário banal (conta com R$ 10.000, **um**
financiamento começado há 12 meses, nada marcado como pago), a primeira tela do
app dizia:

    A pagar        −R$ 43.140,00   ("obrigações conhecidas até o fim do mês")
    Saldo projetado −R$ 33.140,00

quando o certo era uma parcela (~R$ 3.595) e um saldo projetado POSITIVO.

## Por que a correção não é "ignorar o atraso"

Porque o próprio serviço já argumenta o contrário, e com razão: o comentário de
`_a_receber` diz que esconder uma renda antiga que não caiu "é o mesmo erro que
esconder conta atrasada". Concordo — dívida vencida não pode sumir da tela.

O que estava errado não era o total: era **não dar para distinguir**. Um número
chamado "até o fim do mês" que embute doze meses de atraso não responde nem
"quanto vou ter no fim do mês" nem "quanto eu devo". Então a correção é separar,
não descartar:

- `payable_total`  → só o que vence de hoje até o fim do mês;
- `overdue_total`  → o que já venceu, em linha própria;
- `projected_balance` → usa só o primeiro, e passa a significar "se eu pagar o
  que vence este mês, quanto sobra".

Nada é escondido: a tela de Contas a pagar já fazia essa separação
(`overdue_total` × `due_this_month_total`), e a projeção passa a falar a mesma
língua da tela vizinha.
"""
from datetime import timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.core.jwt import create_access_token
from app.domain.dates import today_local
from app.main import app
from app.models.financing import AmortizationInstallment
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMembership, WorkspaceRole

client = TestClient(app)

HOJE = today_local()


@pytest.fixture(name="cena")
def cena_fixture(db_session: Session, override_get_session):
    user = User(name="Paula", email="projecao@t.com", password_hash="h", report_currency="BRL")
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


def _saldo(cena):
    r = client.get("/api/v1/me/balance", headers=cena["headers"])
    assert r.status_code == 200, r.text
    return r.json()


def _linha(corpo, kind):
    """A linha do detalhamento, ou `None`. O detalhamento é o que torna o total
    auditável pela pessoa — sem ele, "a pagar: 43.140" é um número para acreditar."""
    return next(
        (linha for linha in corpo.get("breakdown", []) if linha["kind"] == kind),
        None,
    )


def _financiamento(cena, *, vencimentos: list):
    """Contrato com o cronograma REESCRITO para datas conhecidas.

    Por que reescrever em vez de escolher um `start_date` esperto: a primeira
    parcela vence `start_date + 1 mês` (`financing_service.py:109`), então "qual
    parcela cai dentro deste mês" depende do dia de hoje. Um teste que dependa
    disso passa em 4 de setembro e falha em 29 — e o projeto já tem registro de
    testes que apodreceram por calendário.

    Aqui as datas são ditas, não deduzidas: cada item de `vencimentos` é um
    deslocamento em dias a partir de HOJE (negativo = vencida).
    """
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
    financiamento = r.json()

    db = cena["db"]
    parcelas = db.exec(
        select(AmortizationInstallment)
        .where(AmortizationInstallment.financing_id == financiamento["id"])
        .order_by(AmortizationInstallment.installment_number)
    ).all()
    # As que não recebem data conhecida vão para LONGE, para não entrarem em
    # janela nenhuma e não poluírem as contagens.
    for i, parcela in enumerate(parcelas):
        parcela.due_date = (
            HOJE + timedelta(days=vencimentos[i]) if i < len(vencimentos)
            else HOJE + timedelta(days=3650)
        )
        db.add(parcela)
    db.commit()
    return financiamento


# --------------------------------------------------------------------------- #
# O caso que motivou o arquivo
#
# Cenário fixo em todos: TRÊS parcelas vencidas (40, 25 e 10 dias atrás), UMA
# vencendo daqui a 2 dias, e o resto num futuro distante. Datas ditas, não
# deduzidas — ver `_financiamento`.
# --------------------------------------------------------------------------- #

CENARIO = [-40, -25, -10, +2]


def test_parcelas_vencidas_nao_entram_no_a_pagar_do_mes(cena):
    """Três parcelas atrasadas e uma a vencer: o 'a pagar' do mês conta UMA."""
    _financiamento(cena, vencimentos=CENARIO)

    corpo = _saldo(cena)
    financiamento = _linha(corpo, "financing")

    assert financiamento is not None, "a linha de financiamento sumiu do detalhamento"
    assert financiamento["count"] == 1, (
        "o 'a pagar' do mês está contando parcelas de meses passados: "
        f"{financiamento['count']} parcelas onde vence 1. "
        "Um contrato antigo recém-cadastrado faz a primeira tela anunciar uma "
        "dívida do tamanho do atraso inteiro."
    )


def test_o_atraso_aparece_em_linha_propria(cena):
    """O vencido não some — ele ganha nome.

    Contrapeso do teste anterior: sozinho, aquele seria satisfeito por uma
    correção que simplesmente APAGA o atraso da tela, que é pior que o defeito
    original.
    """
    _financiamento(cena, vencimentos=CENARIO)

    corpo = _saldo(cena)

    assert "overdue_total" in corpo, "a projeção não expõe o que já venceu"
    assert Decimal(str(corpo["overdue_total"])) > 0, (
        "três parcelas em aberto de meses passados e o total vencido é zero — "
        "o atraso foi descartado em vez de separado"
    )
    vencido = _linha(corpo, "overdue")
    assert vencido is not None, "o detalhamento não nomeia o atraso"
    assert vencido["count"] == 3, f"esperava 3 parcelas vencidas, veio {vencido['count']}"


def test_nada_se_perde_na_separacao(cena):
    """O que saiu de "a pagar" tem de estar em "vencido" — a soma se conserva.

    É o teste que impede a correção de virar perda: separar não é descartar.
    """
    _financiamento(cena, vencimentos=CENARIO)

    corpo = _saldo(cena)
    do_mes = _linha(corpo, "financing")
    vencido = _linha(corpo, "overdue")

    assert do_mes["count"] + vencido["count"] == len(CENARIO), (
        "as quatro parcelas dentro da janela não estão todas representadas: "
        f"{do_mes['count']} no mês + {vencido['count']} vencidas"
    )


def test_saldo_projetado_considera_so_o_mes(cena):
    """Com saldo em conta, o projetado não pode virar negativo por causa do atraso.

    É a leitura que a pessoa faz da tela: "quanto eu vou ter no fim do mês".
    """
    conta = client.post(
        "/api/v1/me/payment-accounts",
        json={"name": "Conta", "type": "checking", "currency": "BRL"},
        headers=cena["headers"],
    ).json()
    client.put(
        f"/api/v1/me/payment-accounts/{conta['id']}/opening-balance",
        json={"amount": "100000.00", "as_of": HOJE.isoformat()},
        headers=cena["headers"],
    )
    _financiamento(cena, vencimentos=CENARIO)

    corpo = _saldo(cena)
    projetado = Decimal(str(corpo["projected_balance"]))
    a_pagar = Decimal(str(corpo["payable_total"]))
    vencido = Decimal(str(corpo["overdue_total"]))

    assert projetado == Decimal("100000.00") - a_pagar, (
        f"o saldo projetado ({projetado}) não é 'saldo − o que vence no mês' — "
        f"o atraso ({vencido}) está sendo descontado como se fosse deste mês"
    )


# --------------------------------------------------------------------------- #
# CONTROLE POSITIVO
#
# Sem estes, a correção poderia ser "não conte nada" e os testes acima passariam.
# --------------------------------------------------------------------------- #

def test_controle_parcela_do_mes_continua_contando(cena):
    """Uma parcela vencendo daqui a dois dias continua no 'a pagar'."""
    _financiamento(cena, vencimentos=[+2])

    corpo = _saldo(cena)
    financiamento = _linha(corpo, "financing")

    assert financiamento is not None, (
        "a parcela que vence NESTE mês sumiu do 'a pagar' — a correção virou "
        "exclusão cega"
    )
    assert financiamento["count"] == 1
    assert Decimal(str(corpo["payable_total"])) > 0


def test_controle_sem_atraso_nao_inventa_linha_de_vencido(cena):
    """Quem está em dia não vê aviso de atraso."""
    _financiamento(cena, vencimentos=[+2])

    corpo = _saldo(cena)

    assert Decimal(str(corpo["overdue_total"])) == 0
    assert _linha(corpo, "overdue") is None, (
        "apareceu linha de vencido para quem não deve nada — o aviso perde o "
        "sentido se ele aparece sempre"
    )
