"""Liquidação: a conta só sai do caixa quando é paga (ADR 0029).

O defeito que estes testes fixam: `CashFlowService` lia `transaction_date` e
afirmava que TODO lançamento fora do cartão saía do bolso no instante em que era
registrado. `payment_method` — `pix`, `cash`, `boleto`, `bank_transfer` — não
entrava em consulta nenhuma, e o status `paid`, que deveria dizer "foi pago", não
era escrito por rota nem por tela alguma.

O eixo do arquivo é a separação: **competência não muda, caixa muda.** O boleto de
julho pago em agosto continua sendo gasto de julho (consumo, dívidas, relatórios) e
vira dinheiro que saiu em agosto.
"""
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.core.jwt import create_access_token
from app.main import app
from app.models.recurring import RecurrenceFrequency, RecurringExpense
from app.models.transaction import Transaction
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMembership, WorkspaceRole
from app.domain.dates import today_local

client = TestClient(app)


def _cena(db_session: Session, *, settlement_tracking: bool = True, sufixo: str = ""):
    user = User(name="Dona", email=f"liq{sufixo}@t.com", password_hash="h")
    db_session.add(user)
    ws = Workspace(
        name="Casa", base_currency="BRL", settlement_tracking=settlement_tracking
    )
    db_session.add(ws)
    db_session.flush()
    db_session.add(
        WorkspaceMembership(workspace_id=ws.id, user_id=user.id, role=WorkspaceRole.owner)
    )
    db_session.commit()
    token = create_access_token(data={"sub": str(user.id)})
    return {
        "ws_id": ws.id,
        "user_id": user.id,
        "headers": {"Cookie": f"access_token={token}"},
    }


@pytest.fixture(name="cena")
def cena_fixture(db_session: Session, override_get_session):
    return _cena(db_session)


def _lanca(cena, *, quando: datetime, valor="300.00", titulo="Luz", **extra):
    corpo = {
        "title": titulo,
        "total_amount": valor,
        "transaction_date": quando.isoformat(),
        "payment_method": "boleto",
        "payers": [{"user_id": cena["user_id"], "amount": valor}],
        "splits": [{"user_id": cena["user_id"], "split_method": "equal", "input_value": "0"}],
        **extra,
    }
    r = client.post(
        f"/api/v1/workspaces/{cena['ws_id']}/transactions/",
        json=corpo, headers=cena["headers"],
    )
    assert r.status_code == 200, r.text
    return r.json()


def _mes(quando: date) -> str:
    return f"{quando.year:04d}-{quando.month:02d}"


def _overview(cena, mes: str):
    r = client.get(f"/api/v1/me/overview?month={mes}", headers=cena["headers"])
    assert r.status_code == 200, r.text
    return r.json()


def _payables(cena, mes: str, **params):
    query = "&".join(f"{k}={v}" for k, v in params.items())
    r = client.get(
        f"/api/v1/me/payables?month={mes}" + (f"&{query}" if query else ""),
        headers=cena["headers"],
    )
    assert r.status_code == 200, r.text
    return r.json()


# --- 1. O padrão: passado nasce pago, futuro nasce a pagar ------------------


def test_despesa_de_hoje_nasce_liquidada(cena):
    """Quem registra o que já aconteceu não deveria ter uma etapa a mais.

    A pendência existe para a conta que ainda VAI ser paga; anotar o mercado de
    ontem é descrever um pagamento que já ocorreu.
    """
    hoje = today_local()
    tx = _lanca(cena, quando=datetime(hoje.year, hoje.month, hoje.day, 12, 0))

    assert tx["settled_at"] is not None
    assert _payables(cena, _mes(hoje))["entries"] == []
    assert Decimal(_overview(cena, _mes(hoje))["cash_out"]) == Decimal("300.00")


def test_despesa_com_data_futura_nasce_a_pagar(cena):
    """O boleto que vence dia 30 não pode debitar o caixa no dia 1º.

    Era exatamente isto que acontecia: o caixa somava pela data do lançamento,
    então cadastrar a conta com antecedência já a dava por paga.
    """
    hoje = today_local()
    daqui_a_pouco = hoje + timedelta(days=5)
    tx = _lanca(
        cena, quando=datetime(daqui_a_pouco.year, daqui_a_pouco.month, daqui_a_pouco.day, 12, 0)
    )

    assert tx["settled_at"] is None
    pendencias = _payables(cena, _mes(daqui_a_pouco))
    assert [e["transaction_id"] for e in pendencias["entries"]] == [tx["id"]]
    assert Decimal(pendencias["total"]) == Decimal("300.00")

    visao = _overview(cena, _mes(daqui_a_pouco))
    # Caixa: nada saiu. Competência: a despesa existe e é consumo do mês.
    assert Decimal(visao["cash_out_breakdown"]["transactions"]) == Decimal("0.00")
    assert Decimal(visao["consumption"]) == Decimal("300.00")
    assert Decimal(visao["payables_total"]) == Decimal("300.00")
    assert visao["payables_count"] == 1


def test_ja_foi_paga_vence_o_palpite_da_data(cena):
    """`settled: true` numa data futura — o adiantamento que a regra não adivinha."""
    hoje = today_local()
    frente = hoje + timedelta(days=5)
    tx = _lanca(
        cena,
        quando=datetime(frente.year, frente.month, frente.day, 12, 0),
        settled=True,
    )
    assert tx["settled_at"] is not None
    assert _payables(cena, _mes(frente))["entries"] == []


def test_nao_paguei_ainda_numa_despesa_de_ontem(cena):
    """E o inverso: cadastrar hoje o boleto que chegou ontem e ainda não foi pago."""
    ontem = today_local() - timedelta(days=1)
    tx = _lanca(
        cena,
        quando=datetime(ontem.year, ontem.month, ontem.day, 12, 0),
        settled=False,
    )
    assert tx["settled_at"] is None
    pendencias = _payables(cena, _mes(ontem))
    assert pendencias["entries"][0]["is_overdue"] is True
    assert Decimal(pendencias["overdue_total"]) == Decimal("300.00")


# --- 2. Marcar como paga move o caixa para o mês do PAGAMENTO ---------------


def test_conta_de_julho_paga_em_agosto_sai_no_caixa_de_agosto(db_session, override_get_session):
    """O caso que dá nome ao ADR 0029.

    Competência de julho, caixa de agosto. Antes o app não sabia dizer isso: a
    despesa saía do caixa em julho, no dia em que foi registrada, e agosto — o mês
    em que o dinheiro realmente saiu — não registrava nada.
    """
    cena = _cena(db_session, sufixo="-jul")
    tx = _lanca(cena, quando=datetime(2026, 7, 10, 12, 0), settled=False)

    julho = _overview(cena, "2026-07")
    assert Decimal(julho["consumption"]) == Decimal("300.00"), "a despesa é de julho"
    assert Decimal(julho["cash_out_breakdown"]["transactions"]) == Decimal("0.00")

    r = client.post(
        f"/api/v1/workspaces/{cena['ws_id']}/payables/settle",
        json={"transaction_ids": [tx["id"]], "settled": True, "settled_on": "2026-08-14"},
        headers=cena["headers"],
    )
    assert r.status_code == 200, r.text
    assert r.json() == {"status": "ok", "updated": 1, "skipped": 0}

    # Julho: a despesa continua sendo dele, e continua sem caixa.
    julho = _overview(cena, "2026-07")
    assert Decimal(julho["consumption"]) == Decimal("300.00")
    assert Decimal(julho["cash_out_breakdown"]["transactions"]) == Decimal("0.00")
    assert Decimal(julho["payables_total"]) == Decimal("0.00")

    # Agosto: o dinheiro saiu, no dia 14.
    agosto = _overview(cena, "2026-08")
    assert Decimal(agosto["cash_out_breakdown"]["transactions"]) == Decimal("300.00")
    assert Decimal(agosto["consumption"]) == Decimal("0.00"), (
        "liquidar não pode mover a competência — a despesa é de julho"
    )

    # E o extrato mostra a linha no dia do PAGAMENTO, não no do lançamento.
    r = client.get(
        "/api/v1/me/ledger?month=2026-08&source=transaction", headers=cena["headers"]
    )
    assert r.status_code == 200, r.text
    linhas = r.json()["entries"]
    assert [linha["occurred_on"] for linha in linhas] == ["2026-08-14"]


def test_desmarcar_devolve_a_conta_para_a_fila(db_session, override_get_session):
    """Errou o clique: desfazer tem de tirar o dinheiro do caixa de volta."""
    cena = _cena(db_session, sufixo="-undo")
    tx = _lanca(cena, quando=datetime(2026, 7, 10, 12, 0), settled=True)
    assert Decimal(_overview(cena, "2026-07")["cash_out"]) == Decimal("300.00")

    r = client.post(
        f"/api/v1/workspaces/{cena['ws_id']}/payables/settle",
        json={"transaction_ids": [tx["id"]], "settled": False},
        headers=cena["headers"],
    )
    assert r.status_code == 200 and r.json()["updated"] == 1

    assert Decimal(_overview(cena, "2026-07")["cash_out"]) == Decimal("0.00")
    assert [e["transaction_id"] for e in _payables(cena, "2026-07")["entries"]] == [tx["id"]]


def test_liquidar_nao_congela_a_despesa(db_session, override_get_session):
    """Marcar como paga é fato de CAIXA — não é o status `paid`, que trava a edição.

    A trava de imutabilidade existe para proteger o histórico de acertos. Se
    liquidar usasse aquele estado, confirmar o pagamento de um boleto impediria
    corrigir o valor dele — e corrigir valor de conta paga é rotina.
    """
    cena = _cena(db_session, sufixo="-edit")
    tx = _lanca(cena, quando=datetime(2026, 7, 10, 12, 0), settled=True)

    r = client.put(
        f"/api/v1/workspaces/{cena['ws_id']}/transactions/{tx['id']}",
        json={"title": "Luz (corrigida)"},
        headers=cena["headers"],
    )
    assert r.status_code == 200, r.text
    assert r.json()["title"] == "Luz (corrigida)"
    assert r.json()["settled_at"] is not None, "editar não pode desfazer o pagamento"
    assert r.json()["status"] == "confirmed"


def test_editar_nao_reescreve_a_data_do_pagamento(db_session, override_get_session):
    """PUT com o formulário inteiro (`settled: true` junto) não pode mover a saída.

    O formulário reenvia todos os campos. Sem a guarda de "só age quando MUDA o
    estado", corrigir o título de uma conta paga em 14/08 gravaria a data do
    lançamento por cima e a saída pularia para julho.
    """
    cena = _cena(db_session, sufixo="-nomove")
    tx = _lanca(cena, quando=datetime(2026, 7, 10, 12, 0), settled=False)
    client.post(
        f"/api/v1/workspaces/{cena['ws_id']}/payables/settle",
        json={"transaction_ids": [tx["id"]], "settled": True, "settled_on": "2026-08-14"},
        headers=cena["headers"],
    )

    client.put(
        f"/api/v1/workspaces/{cena['ws_id']}/transactions/{tx['id']}",
        json={"title": "Luz", "settled": True},
        headers=cena["headers"],
    )
    assert Decimal(_overview(cena, "2026-08")["cash_out"]) == Decimal("300.00")
    assert Decimal(_overview(cena, "2026-07")["cash_out"]) == Decimal("0.00")


# --- 3. O espaço decide ----------------------------------------------------


def test_espaco_sem_controle_mantem_o_comportamento_antigo(db_session, override_get_session):
    """Quem lança tudo depois de pagar não quer a etapa a mais.

    Com o controle desligado, a data do lançamento é a data do caixa — que é
    exatamente o que o app fazia antes do ADR 0029.
    """
    cena = _cena(db_session, settlement_tracking=False, sufixo="-off")
    frente = today_local() + timedelta(days=5)
    tx = _lanca(cena, quando=datetime(frente.year, frente.month, frente.day, 12, 0))

    assert tx["settled_at"] is not None
    assert _payables(cena, _mes(frente))["entries"] == []
    assert Decimal(_overview(cena, _mes(frente))["cash_out"]) == Decimal("300.00")


def test_espaco_nasce_com_o_controle_ligado(cena):
    r = client.post(
        "/api/v1/workspaces/", json={"name": "Nova"}, headers=cena["headers"]
    )
    assert r.status_code == 200, r.text
    assert r.json()["settlement_tracking"] is True


def test_criacao_respeita_o_controle_desligado(cena):
    """`False` explícito não pode ser confundido com "não opinou"."""
    r = client.post(
        "/api/v1/workspaces/",
        json={"name": "Sem controle", "settlement_tracking": False},
        headers=cena["headers"],
    )
    assert r.status_code == 200, r.text
    assert r.json()["settlement_tracking"] is False


# --- 4. Compra no cartão não é conta a pagar -------------------------------


def test_compra_no_cartao_fica_fora_da_fila(db_session, override_get_session):
    """Quem se paga é a FATURA. Contar a compra aqui pediria o mesmo dinheiro duas
    vezes — uma na conta a pagar, outra no pagamento da fatura."""
    from app.models.credit_card import CreditCard

    cena = _cena(db_session, sufixo="-card")
    card = CreditCard(
        name="Nubank", limit=Decimal("5000.00"), closing_day=25, due_day=5,
        currency="BRL", owner_user_id=cena["user_id"],
    )
    db_session.add(card)
    db_session.commit()
    db_session.refresh(card)

    tx = _lanca(
        cena, quando=datetime(2026, 7, 10, 12, 0), titulo="Tênis",
        payment_method="credit_card", credit_card_id=card.id,
    )
    assert tx["settled_at"] is None
    assert _payables(cena, "2026-07")["entries"] == []


def test_settle_recusa_compra_no_cartao(db_session, override_get_session):
    """Segunda linha de defesa: um id forjado no corpo não pode liquidar a compra
    de cartão pelas costas da fatura."""
    from app.models.credit_card import CreditCard

    cena = _cena(db_session, sufixo="-card2")
    card = CreditCard(
        name="Nubank", limit=Decimal("5000.00"), closing_day=25, due_day=5,
        currency="BRL", owner_user_id=cena["user_id"],
    )
    db_session.add(card)
    db_session.commit()
    db_session.refresh(card)
    tx = _lanca(
        cena, quando=datetime(2026, 7, 10, 12, 0), titulo="Tênis",
        payment_method="credit_card", credit_card_id=card.id,
    )

    r = client.post(
        f"/api/v1/workspaces/{cena['ws_id']}/payables/settle",
        json={"transaction_ids": [tx["id"]], "settled": True},
        headers=cena["headers"],
    )
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "updated": 0, "skipped": 1}
    assert Decimal(_overview(cena, "2026-07")["cash_out"]) == Decimal("0.00")


# --- 5. Recorrência: o caso que motivou tudo -------------------------------


def test_recorrencia_nasce_a_pagar(db_session, override_get_session):
    """A conta de luz materializada pela recorrência não foi paga por ninguém.

    Ninguém a digitou — a materialização preguiçosa a criou sozinha no dia 10 —,
    então ninguém afirmou que pagou. Antes ela debitava o caixa no mesmo instante.
    """
    cena = _cena(db_session, sufixo="-rec")
    hoje = today_local()
    db_session.add(RecurringExpense(
        title="Luz", base_amount=Decimal("250.00"), currency="BRL",
        frequency=RecurrenceFrequency.monthly, day_of_month=1,
        workspace_id=cena["ws_id"], created_by_user_id=cena["user_id"],
        payer_user_id=cena["user_id"],
    ))
    db_session.commit()

    # A materialização é preguiçosa: roda ao abrir Lançamentos.
    client.get(
        f"/api/v1/workspaces/{cena['ws_id']}/transactions/", headers=cena["headers"]
    )

    pendencias = _payables(cena, _mes(hoje))
    assert len(pendencias["entries"]) == 1
    assert pendencias["entries"][0]["recurring_expense_id"] is not None
    assert Decimal(_overview(cena, _mes(hoje))["cash_out_breakdown"]["transactions"]) == Decimal("0.00")


def test_recorrencia_com_debito_automatico_nasce_liquidada(db_session, override_get_session):
    """`auto_settle`: o banco debita sozinho, então pedir confirmação todo mês
    seria ruído — é a opção de "Pix automático" que os bancos oferecem."""
    cena = _cena(db_session, sufixo="-auto")
    hoje = today_local()
    db_session.add(RecurringExpense(
        title="Internet", base_amount=Decimal("120.00"), currency="BRL",
        frequency=RecurrenceFrequency.monthly, day_of_month=1,
        workspace_id=cena["ws_id"], created_by_user_id=cena["user_id"],
        payer_user_id=cena["user_id"], auto_settle=True,
    ))
    db_session.commit()

    client.get(
        f"/api/v1/workspaces/{cena['ws_id']}/transactions/", headers=cena["headers"]
    )

    assert _payables(cena, _mes(hoje))["entries"] == []
    assert Decimal(
        _overview(cena, _mes(hoje))["cash_out_breakdown"]["transactions"]
    ) == Decimal("120.00")


# --- 6. Import e parcelamento ----------------------------------------------


def test_lote_nasce_liquidado(cena):
    """Importação é FATO CONSUMADO: o extrato veio do banco, o dinheiro já saiu.

    Sem isto, subir um CSV de seis meses despejaria o histórico inteiro em Contas
    a pagar.
    """
    r = client.post(
        f"/api/v1/workspaces/{cena['ws_id']}/transactions/bulk",
        json=[
            {"title": "Mercado", "total_amount": "80.00",
             "transaction_date": "2026-07-03T12:00:00"},
        ],
        headers=cena["headers"],
    )
    assert r.status_code == 200, r.text
    assert r.json()["created"] == 1
    assert _payables(cena, "2026-07")["entries"] == []


def test_parcelas_futuras_do_carne_ficam_a_pagar(db_session, override_get_session):
    """Carnê sem cartão: a 1ª parcela já venceu, as outras ainda não.

    Cada parcela responde pela SUA data — dizer que todas saíram do caixa no dia
    da compra é o mesmo erro do boleto, multiplicado por N.
    """
    cena = _cena(db_session, sufixo="-parc")
    hoje = today_local()
    corpo = {
        "title": "Geladeira",
        "total_amount": "300.00",
        "transaction_date": datetime(hoje.year, hoje.month, hoje.day, 12, 0).isoformat(),
        "payment_method": "boleto",
        "installments_count": 3,
        "payers": [{"user_id": cena["user_id"], "amount": "300.00"}],
        "splits": [{"user_id": cena["user_id"], "split_method": "equal", "input_value": "0"}],
    }
    r = client.post(
        f"/api/v1/workspaces/{cena['ws_id']}/transactions/", json=corpo,
        headers=cena["headers"],
    )
    # Parcelamento sem cartão é recusado pelo schema (exige crédito); a checagem
    # aqui é a do contrato, e o caso do carnê fica documentado como não suportado.
    assert r.status_code == 422, r.text


# --- 7. Duas pessoas pagando a mesma conta ---------------------------------


def test_conta_com_dois_pagadores_e_uma_linha_so_no_espaco(db_session, override_get_session):
    """A consulta junta `TransactionPayer`: sem agrupar, a despesa aparece DUAS
    vezes na tela do espaço, com duas caixas de seleção para um único
    `settled_at` — e o total do topo a contaria uma vez enquanto a lista a
    mostrava duas."""
    from app.models.workspace import WorkspaceMembership, WorkspaceRole

    cena = _cena(db_session, sufixo="-dois")
    outro = User(name="Vizinho", email="liq-vizinho@t.com", password_hash="h")
    db_session.add(outro)
    db_session.flush()
    db_session.add(WorkspaceMembership(
        workspace_id=cena["ws_id"], user_id=outro.id, role=WorkspaceRole.member
    ))
    db_session.commit()

    corpo = {
        "title": "Mercado (rachado na hora)",
        "total_amount": "200.00",
        "transaction_date": datetime(2026, 7, 10, 12, 0).isoformat(),
        "payment_method": "pix",
        "settled": False,
        "payers": [
            {"user_id": cena["user_id"], "amount": "120.00"},
            {"user_id": outro.id, "amount": "80.00"},
        ],
        "splits": [
            {"user_id": cena["user_id"], "split_method": "equal", "input_value": "0"},
            {"user_id": outro.id, "split_method": "equal", "input_value": "0"},
        ],
    }
    r = client.post(
        f"/api/v1/workspaces/{cena['ws_id']}/transactions/", json=corpo,
        headers=cena["headers"],
    )
    assert r.status_code == 200, r.text

    espaco = client.get(
        f"/api/v1/workspaces/{cena['ws_id']}/payables?month=2026-07",
        headers=cena["headers"],
    )
    assert espaco.status_code == 200, espaco.text
    linhas = espaco.json()["entries"]
    assert len(linhas) == 1, "a despesa apareceu uma vez por pagador"
    # O que a tela do espaço pergunta é quanto a conta tira do caixa da CASA.
    assert Decimal(linhas[0]["amount"]) == Decimal("200.00")
    assert Decimal(espaco.json()["total"]) == Decimal("200.00")

    # Na camada pessoal continua sendo a MINHA parte — outro eixo, outro número.
    minhas = _payables(cena, "2026-07")
    assert len(minhas["entries"]) == 1
    assert Decimal(minhas["entries"][0]["amount"]) == Decimal("120.00")


# --- 8. Migração: o passado não muda ---------------------------------------


def test_backfill_deixa_o_historico_intacto(db_session, override_get_session):
    """A linha antiga nasceu sem `settled_at` e a migração a preenche.

    Este teste imita o estado PÓS-migração (que é o que o banco de produção terá)
    e prova o que ela promete: um lançamento antigo continua no caixa do mês dele.
    Sem o `UPDATE`, o caixa de todo mês fechado cairia a zero no primeiro GET
    depois do deploy.
    """
    cena = _cena(db_session, sufixo="-hist")
    antiga = Transaction(
        title="Aluguel (linha antiga)", total_amount=Decimal("1000.00"), currency="BRL",
        transaction_date=datetime(2026, 5, 5, 12, 0, tzinfo=UTC), billing_month="2026-05",
        workspace_id=cena["ws_id"], created_by_user_id=cena["user_id"],
    )
    db_session.add(antiga)
    db_session.flush()
    from app.models.transaction import TransactionPayer

    db_session.add(TransactionPayer(
        transaction_id=antiga.id, user_id=cena["user_id"], amount=Decimal("1000.00")
    ))
    db_session.commit()

    # Antes do backfill: fora do caixa (é o que a migração existe para evitar).
    assert Decimal(_overview(cena, "2026-05")["cash_out"]) == Decimal("0.00")

    # O UPDATE da migração, na forma exata em que ela o faz.
    for tx in db_session.exec(select(Transaction).where(Transaction.settled_at.is_(None))).all():
        tx.settled_at = tx.transaction_date
        db_session.add(tx)
    db_session.commit()

    assert Decimal(_overview(cena, "2026-05")["cash_out"]) == Decimal("1000.00")
    assert _payables(cena, "2026-05")["entries"] == []


# --- 9. O filtro no extrato ------------------------------------------------


def test_filtro_de_liquidacao_no_extrato(db_session, override_get_session):
    """"Só a pagar" dentro de Lançamentos, para quem já está olhando o mês.

    Compra no CARTÃO fica fora do recorte: ela nunca tem liquidação própria — quem
    se paga é a fatura — e sem a exclusão o filtro devolveria toda compra do mês
    como pendente, que é o oposto do que ele promete.
    """
    from app.models.credit_card import CreditCard

    cena = _cena(db_session, sufixo="-filtro")
    card = CreditCard(
        name="Nubank", limit=Decimal("5000.00"), closing_day=25, due_day=5,
        currency="BRL", owner_user_id=cena["user_id"],
    )
    db_session.add(card)
    db_session.commit()
    db_session.refresh(card)

    _lanca(cena, quando=datetime(2026, 7, 3, 12, 0), titulo="Mercado", settled=True)
    _lanca(cena, quando=datetime(2026, 7, 10, 12, 0), titulo="Luz", settled=False)
    _lanca(
        cena, quando=datetime(2026, 7, 12, 12, 0), titulo="Tênis",
        payment_method="credit_card", credit_card_id=card.id,
    )

    def titulos(**params):
        query = "&".join(f"{k}={v}" for k, v in params.items())
        r = client.get(
            f"/api/v1/workspaces/{cena['ws_id']}/transactions/?month=2026-07&{query}",
            headers=cena["headers"],
        )
        assert r.status_code == 200, r.text
        return sorted(t["title"] for t in r.json()["items"])

    assert titulos() == ["Luz", "Mercado", "Tênis"]
    assert titulos(settled="false") == ["Luz"]
    assert titulos(settled="true") == ["Mercado"]
