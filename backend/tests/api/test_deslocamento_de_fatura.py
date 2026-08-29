"""Deslocamento de fatura declarado (ADR 0032).

A fatura de um cartão é composta pela data em que o EMISSOR processa a compra,
não pela data em que ela foi feita. Uma compra de 27/07 num cartão que fecha dia
28, capturada pelo estabelecimento em 30/07, entra na fatura de agosto — e o
atraso é do estabelecimento, não do cartão, então não há regra que o preveja.

Antes disto a única alavanca sobre o destino da fatura era a `transaction_date`.
Mexer nela arrastava junto três coisas que não têm nada a ver com o pedido:

- a COMPETÊNCIA (`billing_month`), que manda em dívidas, relatórios e no rateio;
- a data da cotação de câmbio numa compra estrangeira (`_full_edit` reconverte
  pela `transaction_date`, então a compra ganhava a PTAX do dia errado);
- a data exibida no extrato e na própria fatura.

O invariante que estes testes protegem é exatamente esse divórcio: **mover a
fatura não pode mover a competência.** Quase todo teste aqui confere o
`billing_month` junto do `statement_id`, porque uma implementação que movesse os
dois passaria por qualquer teste que olhasse só a fatura — e seria o defeito de
volta com outro nome.
"""
from datetime import date, datetime
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.core.jwt import create_access_token
from app.domain.dates import civil_instant
from app.main import app
from app.models.credit_card import CardStatement, CreditCard, StatementStatus
from app.models.recurring import RecurrenceFrequency, RecurringExpense
from app.models.transaction import Transaction
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMembership, WorkspaceRole
from app.services.credit_card_service import (
    CreditCardService,
    StatementStateError,
)
from app.services.recurring_service import RecurringService

client = TestClient(app)

# Cartão fecha dia 28 e vence dia 10 do mês seguinte.
FECHAMENTO = 28
# 27/07: véspera do fechamento — a janela em que o atraso de captura decide a
# fatura. Natural = julho; o emissor pode jogar para agosto.
VESPERA = date(2026, 7, 27)


@pytest.fixture(name="cena")
def cena_fixture(db_session: Session, override_get_session):
    user = User(name="Dona", email="adr32-shift@t.com", password_hash="h")
    db_session.add(user)
    ws = Workspace(name="Casa", base_currency="BRL")
    db_session.add(ws)
    db_session.flush()
    db_session.add(
        WorkspaceMembership(workspace_id=ws.id, user_id=user.id, role=WorkspaceRole.owner)
    )
    card = CreditCard(
        name="Cartão", limit=Decimal("5000.00"), closing_day=FECHAMENTO, due_day=10,
        currency="BRL", owner_user_id=user.id,
    )
    db_session.add(card)
    db_session.commit()
    db_session.refresh(card)
    token = create_access_token(data={"sub": str(user.id)})
    return {
        "ws_id": ws.id, "user_id": user.id, "card": card, "card_id": card.id,
        "db": db_session,
        "headers": {"Cookie": f"access_token={token}"},
    }


def _lancar(cena, *, shift=0, quando=VESPERA, valor="100.00", parcelas=None):
    corpo = {
        "title": "Restaurante", "total_amount": valor, "currency": "BRL",
        "transaction_date": civil_instant(quando).isoformat(),
        "payment_method": "credit_card", "credit_card_id": cena["card_id"],
        "statement_shift": shift,
        "payers": [{"user_id": cena["user_id"], "amount": valor}],
        "splits": [
            {"user_id": cena["user_id"], "split_method": "equal", "input_value": "0"}
        ],
    }
    if parcelas:
        corpo["installments_count"] = parcelas
    return client.post(
        f"/api/v1/workspaces/{cena['ws_id']}/transactions/",
        headers=cena["headers"], json=corpo,
    )


def _mes_da_fatura(cena, statement_id):
    return cena["db"].get(CardStatement, statement_id).month


def _fechar(cena, mes: str, *, paga=False):
    """Cria a fatura do mês já fechada (ou paga), para testar as guardas."""
    stmt = CardStatement(
        card_id=cena["card_id"], month=mes,
        closing_date=datetime(2026, 1, 1), due_date=datetime(2026, 1, 10),
        status=StatementStatus.paid if paga else StatementStatus.closed,
    )
    cena["db"].add(stmt)
    cena["db"].commit()
    return stmt


# ---- A aritmética do ciclo -------------------------------------------------


def test_shift_zero_e_o_comportamento_de_sempre(cena):
    """Guarda de regressão: sem deslocamento, nada muda.

    O valor default da coluna é `0` em toda linha existente, então este teste é o
    que garante que a migração não move fatura nenhuma do histórico.
    """
    _, _, _ = CreditCardService.resolve_statement_target(
        cena["db"], cena["card"], VESPERA
    )
    ano, mes, _ = CreditCardService.resolve_statement_target(
        cena["db"], cena["card"], VESPERA, shift=0
    )
    assert (ano, mes) == (2026, 7)


@pytest.mark.parametrize(
    "shift,esperado",
    [
        (0, (2026, 7)),
        (1, (2026, 8)),
        (2, (2026, 9)),
        (-1, (2026, 6)),
    ],
)
def test_deslocamento_anda_o_numero_de_faturas_pedido(cena, shift, esperado):
    ano, mes, _ = CreditCardService.resolve_statement_target(
        cena["db"], cena["card"], VESPERA, shift=shift
    )
    assert (ano, mes) == esperado


@pytest.mark.parametrize(
    "dia,shift,esperado",
    [
        # Dezembro +1 vira janeiro do ano seguinte...
        (date(2026, 12, 20), 1, (2027, 1)),
        # ...e janeiro −1 vira dezembro do anterior. A aritmética ingênua
        # (`month + shift`) devolveria mês 13 e mês 0 — nenhum dos dois existe.
        (date(2026, 1, 20), -1, (2025, 12)),
        # E a regra do fechamento continua valendo ANTES do deslocamento: dia 29
        # já é do ciclo de janeiro, então −1 volta para dezembro, não novembro.
        (date(2026, 12, 29), -1, (2026, 12)),
    ],
)
def test_deslocamento_atravessa_a_virada_do_ano(cena, dia, shift, esperado):
    ano, mes, _ = CreditCardService.resolve_statement_target(
        cena["db"], cena["card"], dia, shift=shift
    )
    assert (ano, mes) == esperado


def test_deslocamento_parte_do_natural_e_nao_do_alvo_ja_rolado(cena):
    """A ORDEM entre deslocar e rolar, que é a parte fácil de errar.

    Julho está fechada, então sem deslocamento a compra rolaria para agosto.
    Pedir "+1" a partir do natural é AGOSTO — não setembro. Aplicar o
    deslocamento depois da rolagem somaria os dois efeitos e mandaria a compra
    dois ciclos à frente do que o usuário pediu, sem nada na tela explicando o
    salto.
    """
    _fechar(cena, "2026-07")

    # Sem deslocamento: rola de julho (fechada) para agosto.
    assert CreditCardService.resolve_statement_target(
        cena["db"], cena["card"], VESPERA
    )[:2] == (2026, 8)
    # Com +1: parte do NATURAL (julho) e anda uma → agosto. O mesmo destino, por
    # um caminho diferente, e não setembro.
    assert CreditCardService.resolve_statement_target(
        cena["db"], cena["card"], VESPERA, shift=1
    )[:2] == (2026, 8)


# ---- A guarda do alvo fechado ---------------------------------------------


@pytest.mark.parametrize("paga", [False, True])
def test_deslocamento_para_fatura_fechada_e_recusado(cena, paga):
    """Pedido explícito que não pode ser atendido falha ALTO.

    Sem a guarda, o pedido cairia na rolagem para frente e a compra voltaria,
    calada, para o alvo natural: o app responderia 200 e faria outra coisa.
    """
    _fechar(cena, "2026-06", paga=paga)
    with pytest.raises(StatementStateError):
        CreditCardService.assert_shift_reachable(
            cena["db"], cena["card"], VESPERA, -1
        )


def test_shift_zero_nao_e_barrado_por_fatura_fechada(cena):
    """A rolagem continua sendo o comportamento correto no caminho implícito.

    Ela não é resultado de um pedido do usuário — é a imutabilidade da fatura
    fechada (ADR 0011) fazendo o trabalho dela. Barrá-la aqui quebraria o
    lançamento comum em todo cartão com fatura já fechada.
    """
    _fechar(cena, "2026-07")
    CreditCardService.assert_shift_reachable(cena["db"], cena["card"], VESPERA, 0)
    assert _lancar(cena).status_code == 200


def test_rota_traduz_alvo_fechado_para_409(cena):
    _fechar(cena, "2026-06")
    r = _lancar(cena, shift=-1)
    assert r.status_code == 409
    assert "fechada" in r.json()["error"]["message"]


@pytest.mark.parametrize("shift", [-2, 3, 12])
def test_deslocamento_fora_do_intervalo_e_recusado(cena, shift):
    """O intervalo estreito é a diferença entre corrigir processamento e jogar
    despesa para qualquer mês do futuro."""
    assert _lancar(cena, shift=shift).status_code == 422


def test_deslocamento_sem_cartao_e_recusado(cena):
    r = client.post(
        f"/api/v1/workspaces/{cena['ws_id']}/transactions/",
        headers=cena["headers"],
        json={
            "title": "Pix", "total_amount": "50.00", "currency": "BRL",
            "transaction_date": civil_instant(VESPERA).isoformat(),
            "payment_method": "pix", "statement_shift": 1,
            "payers": [{"user_id": cena["user_id"], "amount": "50.00"}],
            "splits": [
                {"user_id": cena["user_id"], "split_method": "equal", "input_value": "0"}
            ],
        },
    )
    assert r.status_code == 422


# ---- O invariante central: a competência NÃO se move -----------------------


def test_criar_com_deslocamento_move_a_fatura_e_nao_a_competencia(cena):
    """O teste que define a feature.

    A compra de 27/07 vai para a fatura de AGOSTO (o emissor processou tarde) e
    continua sendo despesa de JULHO — que é quando ela aconteceu, e o que dívidas
    e relatórios têm de enxergar.
    """
    natural = _lancar(cena, shift=0).json()
    deslocada = _lancar(cena, shift=1).json()

    assert _mes_da_fatura(cena, natural["statement_id"]) == "2026-07"
    assert _mes_da_fatura(cena, deslocada["statement_id"]) == "2026-08"
    # E o que NÃO pode ter mudado:
    assert natural["billing_month"] == deslocada["billing_month"] == "2026-07"
    assert natural["transaction_date"] == deslocada["transaction_date"]


def test_o_dinheiro_acompanha_a_fatura(cena):
    """Mover a compra tem de mover o valor cobrado, não só o vínculo.

    Sem isto o `statement_id` apontaria para agosto e o total de julho seguiria
    somando a compra — a divergência entre o total e as linhas que o ADR 0023
    fechou, reaberta pela porta nova.
    """
    _lancar(cena, shift=1, valor="250.00")
    julho = CreditCardService.find_statement(cena["db"], cena["card"], 2026, 7)
    agosto = CreditCardService.find_statement(cena["db"], cena["card"], 2026, 8)

    assert julho is None or CreditCardService.compute_statement_total(
        cena["db"], julho.id
    ) == Decimal("0.00")
    assert CreditCardService.compute_statement_total(
        cena["db"], agosto.id
    ) == Decimal("250.00")


# ---- Compra parcelada ------------------------------------------------------


def test_parcelamento_desliza_o_cronograma_inteiro(cena):
    """Se o emissor processou a compra no ciclo seguinte, processou a COMPRA —
    todas as parcelas deslizam, cada uma medida do ciclo natural dela."""
    _lancar(cena, shift=1, valor="300.00", parcelas=3)

    parcelas = cena["db"].exec(
        select(Transaction)
        .where(Transaction.installment_group_id.is_not(None))
        .order_by(Transaction.installment_no)
    ).all()
    assert len(parcelas) == 3
    assert [_mes_da_fatura(cena, p.statement_id) for p in parcelas] == [
        "2026-08", "2026-09", "2026-10",
    ]
    # A competência de cada parcela segue a data dela, intocada pelo
    # deslocamento — 1/3 é de julho, e não de agosto.
    assert [p.billing_month for p in parcelas] == ["2026-07", "2026-08", "2026-09"]
    # E toda parcela guarda o deslocamento, para uma edição de data futura
    # reaplicá-lo em vez de desfazê-lo em silêncio.
    assert all(p.statement_shift == 1 for p in parcelas)


# ---- Mover depois de lançada ----------------------------------------------


def test_mover_lancamento_existente_de_fatura(cena):
    """O caso que motivou tudo: a fatura real chegou e a compra estava na outra."""
    tx = _lancar(cena).json()
    assert _mes_da_fatura(cena, tx["statement_id"]) == "2026-07"

    r = client.put(
        f"/api/v1/workspaces/{cena['ws_id']}/transactions/{tx['id']}",
        headers=cena["headers"], json={"statement_shift": 1},
    )
    assert r.status_code == 200
    movida = r.json()
    assert _mes_da_fatura(cena, movida["statement_id"]) == "2026-08"
    assert movida["billing_month"] == "2026-07", "a competência não se move"


def test_mover_de_volta_desfaz(cena):
    tx = _lancar(cena, shift=1).json()
    r = client.put(
        f"/api/v1/workspaces/{cena['ws_id']}/transactions/{tx['id']}",
        headers=cena["headers"], json={"statement_shift": 0},
    )
    assert r.status_code == 200
    assert _mes_da_fatura(cena, r.json()["statement_id"]) == "2026-07"


def test_edicao_que_nao_fala_de_fatura_preserva_o_deslocamento(cena):
    """Um PUT de título não pode rerrotear a fatura.

    `statement_shift` é `Optional` na edição justamente para "não mexe" ser
    distinguível de "zera" — o mesmo cuidado que `settled` já tinha.
    """
    tx = _lancar(cena, shift=1).json()
    r = client.put(
        f"/api/v1/workspaces/{cena['ws_id']}/transactions/{tx['id']}",
        headers=cena["headers"], json={"title": "Restaurante (corrigido)"},
    )
    assert r.status_code == 200
    assert r.json()["statement_shift"] == 1
    assert _mes_da_fatura(cena, r.json()["statement_id"]) == "2026-08"


def test_deslocamento_sobrevive_a_edicao_de_data(cena):
    """A razão de a coluna ser RELATIVA e não um mês absoluto.

    Movida a compra de 27/07 para 27/06, o alvo natural passa a ser junho e o
    "+1" se reaplica sobre ele: julho. Um mês absoluto gravado ("agosto") teria
    de ser invalidado aqui, e a correção sumiria sem aviso.
    """
    tx = _lancar(cena, shift=1).json()
    r = client.put(
        f"/api/v1/workspaces/{cena['ws_id']}/transactions/{tx['id']}",
        headers=cena["headers"],
        json={"transaction_date": civil_instant(date(2026, 6, 27)).isoformat()},
    )
    assert r.status_code == 200
    assert _mes_da_fatura(cena, r.json()["statement_id"]) == "2026-07"
    assert r.json()["billing_month"] == "2026-06"


def test_sair_do_cartao_zera_o_deslocamento(cena):
    """Sem cartão não há fatura para deslocar.

    Deixar o valor antigo na linha o faria ACORDAR se o lançamento voltasse para
    um cartão depois, mandando a compra para uma fatura que ninguém pediu
    naquele momento.
    """
    tx = _lancar(cena, shift=1).json()
    r = client.put(
        f"/api/v1/workspaces/{cena['ws_id']}/transactions/{tx['id']}",
        headers=cena["headers"],
        json={"credit_card_id": None, "payment_method": "pix"},
    )
    assert r.status_code == 200
    assert r.json()["statement_shift"] == 0
    assert r.json()["statement_id"] is None


def test_mover_para_fatura_fechada_responde_409(cena):
    tx = _lancar(cena).json()
    _fechar(cena, "2026-08")
    r = client.put(
        f"/api/v1/workspaces/{cena['ws_id']}/transactions/{tx['id']}",
        headers=cena["headers"], json={"statement_shift": 1},
    )
    assert r.status_code == 409


# ---- Recorrência -----------------------------------------------------------


def _template(cena, shift):
    tpl = RecurringExpense(
        title="Assinatura", base_amount=Decimal("40.00"), currency="BRL",
        frequency=RecurrenceFrequency.monthly, day_of_month=27,
        start_date=date(2026, 7, 1), workspace_id=cena["ws_id"],
        created_by_user_id=cena["user_id"], payer_user_id=cena["user_id"],
        payment_method="credit_card", credit_card_id=cena["card_id"],
        statement_shift=shift,
    )
    cena["db"].add(tpl)
    cena["db"].commit()
    return tpl


def test_ocorrencia_herda_o_deslocamento_do_template(cena):
    """Uma assinatura cobrada perto do fechamento cai na fatura seguinte TODO
    mês: é característica do cobrador, declarada uma vez."""
    _template(cena, shift=1)
    RecurringService.generate_due_instances(cena["db"], cena["ws_id"], date(2026, 7, 28))
    cena["db"].commit()

    tx = cena["db"].exec(
        select(Transaction).where(Transaction.recurring_expense_id.is_not(None))
    ).first()
    assert tx is not None
    assert tx.statement_shift == 1
    assert _mes_da_fatura(cena, tx.statement_id) == "2026-08"
    assert tx.billing_month == "2026-07"


def test_materializacao_preguicosa_nao_quebra_com_alvo_fechado(cena):
    """A materialização roda dentro de rotas de LEITURA.

    Um deslocamento inalcançável ali não pode virar 409 num GET de extrato: a
    ocorrência cai no alvo natural, que é o mesmo tratamento que o cartão apagado
    já recebia. Sem `strict_shift=False` isto derruba a listagem inteira.
    """
    _template(cena, shift=1)
    _fechar(cena, "2026-08")

    RecurringService.generate_due_instances(cena["db"], cena["ws_id"], date(2026, 7, 28))
    cena["db"].commit()

    r = client.get(
        f"/api/v1/workspaces/{cena['ws_id']}/transactions/",
        headers=cena["headers"],
    )
    assert r.status_code == 200


def test_recorrencia_sem_cartao_recusa_deslocamento(cena):
    r = client.post(
        f"/api/v1/workspaces/{cena['ws_id']}/recurring",
        headers=cena["headers"],
        json={
            "title": "Aluguel", "base_amount": "1000.00", "day_of_month": 5,
            "payment_method": "pix", "statement_shift": 1,
        },
    )
    assert r.status_code == 400


# ---- O preview que sustenta a tela ----------------------------------------


def test_preview_lista_as_faturas_alcancaveis_com_o_shift_de_cada(cena):
    """A tela escolhe um MÊS e devolve o `shift` que veio na opção — a
    aritmética de ciclo continua inteira no servidor (ADR 0002)."""
    r = client.get(
        f"/api/v1/me/credit-cards/{cena['card_id']}/statement-for",
        headers=cena["headers"], params={"on": VESPERA.isoformat()},
    )
    assert r.status_code == 200
    corpo = r.json()
    assert corpo["month"] == "2026-07"
    assert [(o["shift"], o["month"]) for o in corpo["options"]] == [
        (-1, "2026-06"), (0, "2026-07"), (1, "2026-08"), (2, "2026-09"),
    ]
    assert all(o["available"] for o in corpo["options"])


def test_preview_marca_indisponivel_a_fatura_fechada_sem_esconde_la(cena):
    """Escondê-la deixaria a tela sem explicação para a opção que o usuário
    procura e não encontra."""
    _fechar(cena, "2026-06")
    r = client.get(
        f"/api/v1/me/credit-cards/{cena['card_id']}/statement-for",
        headers=cena["headers"], params={"on": VESPERA.isoformat()},
    )
    junho = next(o for o in r.json()["options"] if o["shift"] == -1)
    assert junho["available"] is False
    assert junho["status"] == "closed"


@pytest.mark.parametrize(
    "dia,esperado",
    [
        (date(2026, 7, 27), 1),   # véspera do fechamento: a janela do aviso
        (date(2026, 7, 25), 3),   # limite da janela de 3 dias
        (date(2026, 7, 24), 4),   # fora
        (date(2026, 7, 1), 27),   # começo do ciclo
        # Depois do fechamento a compra JÁ é do ciclo seguinte, que fecha em
        # 28/08: 30 dias. Longe da janela do aviso, e é o número certo — não há
        # nada de anômalo numa compra do começo do ciclo.
        (date(2026, 7, 29), 30),
    ],
)
def test_preview_conta_os_dias_ate_o_fechamento(cena, dia, esperado):
    r = client.get(
        f"/api/v1/me/credit-cards/{cena['card_id']}/statement-for",
        headers=cena["headers"], params={"on": dia.isoformat()},
    )
    assert r.json()["days_to_closing"] == esperado


def test_dias_ate_o_fechamento_e_nulo_quando_a_pergunta_nao_faz_sentido(cena):
    """Num destino deslocado ou rolado o número compararia a data da compra com o
    fechamento de um ciclo a que ela não pertence: um valor com aparência de
    resposta e sem significado. `None` é o que impede a tela de avisar "faltam 2
    dias para o fechamento" sobre uma compra que o próprio usuário já moveu."""
    rolada = client.get(
        f"/api/v1/me/credit-cards/{cena['card_id']}/statement-for",
        headers=cena["headers"], params={"on": VESPERA.isoformat()},
    )
    assert rolada.json()["days_to_closing"] == 1  # antes de fechar julho
    _fechar(cena, "2026-07")
    rolada = client.get(
        f"/api/v1/me/credit-cards/{cena['card_id']}/statement-for",
        headers=cena["headers"], params={"on": VESPERA.isoformat()},
    )
    assert rolada.json()["days_to_closing"] is None

    deslocado = client.get(
        f"/api/v1/me/credit-cards/{cena['card_id']}/statement-for",
        headers=cena["headers"], params={"on": VESPERA.isoformat(), "shift": 1},
    )
    assert deslocado.json()["days_to_closing"] is None


def test_preview_com_shift_nao_marca_rolagem(cena):
    """`rolled_forward` mede só a rolagem por fatura fechada.

    Medi-la contra o alvo natural cru marcaria todo `shift != 0` como "rolou", e
    a tela avisaria "a fatura do mês já está fechada" sobre uma compra que o
    próprio usuário mandou para frente.
    """
    r = client.get(
        f"/api/v1/me/credit-cards/{cena['card_id']}/statement-for",
        headers=cena["headers"], params={"on": VESPERA.isoformat(), "shift": 1},
    )
    corpo = r.json()
    assert corpo["month"] == "2026-08"
    assert corpo["rolled_forward"] is False
    assert corpo["shift"] == 1
