"""Estabelecimento (ADR 0038): onde a despesa foi feita, como vocabulário do espaço."""
from fastapi.testclient import TestClient
from sqlmodel import select

from app.domain.dates import civil_instant, today_local
from app.main import app
from app.models.transaction import Transaction, TransactionItem

client = TestClient(app)
HOJE = civil_instant(today_local()).isoformat()


def _api(ws):
    return f"/api/v1/workspaces/{ws}"


def _estabelecimento(ws, h, **corpo):
    r = client.post(f"{_api(ws)}/merchants", json=corpo, headers=h)
    assert r.status_code == 200, r.text
    return r.json()


def _despesa(ws, uid, h, titulo="Compra", valor="50.00", **extra):
    corpo = {
        "title": titulo, "total_amount": valor, "transaction_date": HOJE,
        "payers": [{"user_id": uid, "amount": valor}],
        "splits": [{"user_id": uid, "split_method": "equal", "input_value": "100"}],
        **extra,
    }
    r = client.post(f"{_api(ws)}/transactions/", json=corpo, headers=h)
    assert r.status_code == 200, r.text
    return r.json()


def _categoria(ws, h, nome):
    r = client.post(f"{_api(ws)}/categories", json={"name": nome}, headers=h)
    assert r.status_code == 200, r.text
    return r.json()["id"]


def test_apelidos_normalizados_e_nome_unico(db_session, setup_data, override_get_session):
    ws, h = setup_data["ws1"].id, setup_data["headers1"]
    m = _estabelecimento(ws, h, name="McDonald's", aliases=["IFD*MC DONALDS 0231", "MC DONALDS"])
    # Sem acento, sem caixa, sem dígito, sem pontuação; repetido some.
    assert m["aliases"] == ["ifd mc donalds", "mc donalds"]
    assert client.post(f"{_api(ws)}/merchants", json={"name": "McDonald's"}, headers=h).status_code == 400
    # O apelido já é de outro estabelecimento: 409 com o nome dele.
    r = client.post(f"{_api(ws)}/merchants", json={"name": "Méqui", "aliases": ["mc donalds"]}, headers=h)
    assert r.status_code == 409 and "McDonald's" in r.json()["error"]["message"]


def test_lancamento_pelo_nome_acha_ou_cria(db_session, setup_data, override_get_session):
    ws, uid, h = setup_data["ws1"].id, setup_data["u1"].id, setup_data["headers1"]
    a = _despesa(ws, uid, h, merchant_name="Padaria Pão Quente")
    b = _despesa(ws, uid, h, merchant_name="PADARIA PAO QUENTE")
    assert a["merchant"]["name"] == "Padaria Pão Quente"
    assert b["merchant"]["id"] == a["merchant"]["id"]
    assert len(client.get(f"{_api(ws)}/merchants", headers=h).json()) == 1


def test_titulo_com_apelido_exato_vincula_sozinho_e_parecido_nao(db_session, setup_data, override_get_session):
    ws, uid, h = setup_data["ws1"].id, setup_data["u1"].id, setup_data["headers1"]
    m = _estabelecimento(ws, h, name="McDonald's", aliases=["IFD*MC DONALDS"])
    assert _despesa(ws, uid, h, titulo="IFD*MC DONALDS 0231")["merchant"]["id"] == m["id"]
    assert _despesa(ws, uid, h, titulo="MC DONALDS SHOPPING")["merchant"] is None


def test_categoria_padrao_so_quando_a_pessoa_nao_escolheu(db_session, setup_data, override_get_session):
    ws, uid, h = setup_data["ws1"].id, setup_data["u1"].id, setup_data["headers1"]
    lanche = _categoria(ws, h, "Lanche")
    outra = _categoria(ws, h, "Trabalho")
    _estabelecimento(ws, h, name="Starbucks", default_category_id=lanche)
    sem = _despesa(ws, uid, h, titulo="Starbucks")
    com = _despesa(ws, uid, h, titulo="Starbucks", items=[{"title": "Starbucks", "amount": "50.00", "category_id": outra}])
    categorias = lambda tx: {i.category_id for i in db_session.exec(select(TransactionItem).where(TransactionItem.transaction_id == tx["id"])).all()}  # noqa: E731
    assert categorias(sem) == {lanche}
    assert categorias(com) == {outra}


def test_editar_vincula_troca_e_desvincula(db_session, setup_data, override_get_session):
    ws, uid, h = setup_data["ws1"].id, setup_data["u1"].id, setup_data["headers1"]
    tx = _despesa(ws, uid, h, titulo="Almoço")
    url = f"{_api(ws)}/transactions/{tx['id']}"
    assert client.put(url, json={"merchant_name": "Restaurante Sabor"}, headers=h).json()["merchant"]["name"] == "Restaurante Sabor"
    assert client.put(url, json={"merchant_id": None}, headers=h).json()["merchant"] is None
    # Editar o título não mexe no estabelecimento.
    outro = _estabelecimento(ws, h, name="Almoço")
    assert client.put(url, json={"title": "Almoço"}, headers=h).json()["merchant"] is None
    assert client.put(url, json={"merchant_id": outro["id"]}, headers=h).json()["merchant"]["id"] == outro["id"]


def test_mesclar_leva_lancamentos_e_apelidos(db_session, setup_data, override_get_session):
    ws, uid, h = setup_data["ws1"].id, setup_data["u1"].id, setup_data["headers1"]
    fica = _estabelecimento(ws, h, name="McDonald's")
    sai = _estabelecimento(ws, h, name="MC DONALDS", aliases=["IFD MC"])
    tx = _despesa(ws, uid, h, merchant_id=sai["id"])
    r = client.post(f"{_api(ws)}/merchants/{sai['id']}/merge", json={"into_id": fica["id"]}, headers=h)
    assert r.status_code == 200, r.text
    assert set(r.json()["aliases"]) == {"mc donalds", "ifd mc"}
    db_session.expire_all()
    assert db_session.get(Transaction, tx["id"]).merchant_id == fica["id"]
    assert [m["name"] for m in client.get(f"{_api(ws)}/merchants", headers=h).json()] == ["McDonald's"]
    # O título com o apelido herdado passa a vincular ao que ficou.
    assert _despesa(ws, uid, h, titulo="IFD MC")["merchant"]["id"] == fica["id"]


def test_excluir_desvincula_os_lancamentos(db_session, setup_data, override_get_session):
    ws, uid, h = setup_data["ws1"].id, setup_data["u1"].id, setup_data["headers1"]
    m = _estabelecimento(ws, h, name="Loja X")
    tx = _despesa(ws, uid, h, merchant_id=m["id"])
    assert client.delete(f"{_api(ws)}/merchants/{m['id']}", headers=h).status_code == 200
    db_session.expire_all()
    assert db_session.get(Transaction, tx["id"]).merchant_id is None


def test_filtro_da_lista_por_estabelecimento(db_session, setup_data, override_get_session):
    ws, uid, h = setup_data["ws1"].id, setup_data["u1"].id, setup_data["headers1"]
    m = _estabelecimento(ws, h, name="Farmácia")
    _despesa(ws, uid, h, titulo="Remédio", merchant_id=m["id"])
    _despesa(ws, uid, h, titulo="Mercado")
    lista = client.get(f"{_api(ws)}/transactions/?merchant_id={m['id']}", headers=h).json()
    assert [i["title"] for i in lista["items"]] == ["Remédio"]


def test_estabelecimento_de_outro_espaco_nao_serve(db_session, setup_data, override_get_session):
    ws1, ws2 = setup_data["ws1"].id, setup_data["ws2"].id
    h1, h2, uid = setup_data["headers1"], setup_data["headers2"], setup_data["u1"].id
    alheio = _estabelecimento(ws2, h2, name="Do vizinho")
    corpo = {"title": "X", "total_amount": "5.00", "transaction_date": HOJE, "merchant_id": alheio["id"],
             "payers": [{"user_id": uid, "amount": "5.00"}], "splits": [{"user_id": uid, "split_method": "equal", "input_value": "100"}]}
    assert client.post(f"{_api(ws1)}/transactions/", json=corpo, headers=h1).status_code == 404
    assert client.put(f"{_api(ws1)}/merchants/{alheio['id']}", json={"name": "Meu"}, headers=h1).status_code == 404


def test_importacao_vincula_pelo_apelido(db_session, setup_data, override_get_session):
    ws, h = setup_data["ws1"].id, setup_data["headers1"]
    m = _estabelecimento(ws, h, name="Uber", aliases=["UBER *TRIP"])
    r = client.post(f"{_api(ws)}/imports/commit", headers=h, json={"rows": [
        {"title": "UBER *TRIP", "total_amount": 23.0, "transaction_date": "2026-03-01T00:00:00"},
        {"title": "TAXI", "total_amount": 30.0, "transaction_date": "2026-03-01T00:00:00"},
    ]})
    assert r.status_code == 200, r.text
    vinculos = {t.title: t.merchant_id for t in db_session.exec(select(Transaction).where(Transaction.workspace_id == ws)).all()}
    assert vinculos == {"UBER *TRIP": m["id"], "TAXI": None}


def test_a_ocorrencia_da_recorrencia_nasce_com_o_estabelecimento(db_session, setup_data, override_get_session):
    ws, h = setup_data["ws1"].id, setup_data["headers1"]
    m = _estabelecimento(ws, h, name="Netflix")
    hoje = today_local()
    r = client.post(f"{_api(ws)}/recurring?materialize=current", json={
        "title": "Assinatura", "base_amount": "55.90", "day_of_month": hoje.day, "start_date": hoje.isoformat(),
        "merchant_id": m["id"],
    }, headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["merchant_id"] == m["id"]
    ocorrencias = db_session.exec(select(Transaction).where(Transaction.recurring_expense_id == r.json()["id"])).all()
    assert ocorrencias and all(t.merchant_id == m["id"] for t in ocorrencias)


def _cartao(db_session, uid):
    from decimal import Decimal

    from app.models.credit_card import CreditCard

    card = CreditCard(name="Card", limit=Decimal("50000.00"), closing_day=25, due_day=5, owner_user_id=uid)
    db_session.add(card)
    db_session.commit()
    return card.id


def _parcelada(ws, uid, h, card_id, **extra):
    return _despesa(ws, uid, h, titulo="Geladeira", valor="300.00", installments_count=3,
                    credit_card_id=card_id, payment_method="credit_card", **extra)


def test_a_parcelada_nasce_com_o_estabelecimento_em_todas_as_parcelas(db_session, setup_data, override_get_session):
    ws, uid, h = setup_data["ws1"].id, setup_data["u1"].id, setup_data["headers1"]
    m = _estabelecimento(ws, h, name="Magazine")
    _parcelada(ws, uid, h, _cartao(db_session, uid), merchant_id=m["id"])
    parcelas = db_session.exec(select(Transaction).where(Transaction.installment_group_id.is_not(None))).all()
    assert len(parcelas) == 3 and {t.merchant_id for t in parcelas} == {m["id"]}


def test_editar_a_compra_inteira_mantem_troca_e_recusa_alheio(db_session, setup_data, override_get_session):
    ws, uid, h = setup_data["ws1"].id, setup_data["u1"].id, setup_data["headers1"]
    card = _cartao(db_session, uid)
    m = _estabelecimento(ws, h, name="Magazine")
    outro = _estabelecimento(ws, h, name="Casas Bahia")
    ancora = _parcelada(ws, uid, h, card, merchant_id=m["id"])
    url = f"{_api(ws)}/transactions/{ancora['id']}/installment-group"
    inteira = client.get(url, headers=h).json()["whole"]
    assert inteira["merchant"]["id"] == m["id"]
    corpo = {
        "title": "Geladeira", "total_amount": "360.00", "transaction_date": HOJE, "installments_count": 3,
        "credit_card_id": card, "payment_method": "credit_card",
        "payers": [{"user_id": uid, "amount": "360.00"}],
        "splits": [{"user_id": uid, "split_method": "equal", "input_value": "100"}],
    }

    def vinculos():
        db_session.expire_all()
        vivas = db_session.exec(select(Transaction).where(
            Transaction.installment_group_id.is_not(None), Transaction.deleted_at.is_(None))).all()
        return {t.merchant_id for t in vivas}

    # Quem não manda o campo (cliente antigo) não apaga o vínculo.
    r = client.put(url, json=corpo, headers=h)
    assert r.status_code == 200, r.text
    assert vinculos() == {m["id"]}
    url = f"{_api(ws)}/transactions/{r.json()['id']}/installment-group"
    r = client.put(url, json={**corpo, "merchant_id": outro["id"]}, headers=h)
    assert r.status_code == 200, r.text
    assert vinculos() == {outro["id"]}
    alheio = _estabelecimento(setup_data["ws2"].id, setup_data["headers2"], name="Do vizinho")
    url = f"{_api(ws)}/transactions/{r.json()['id']}/installment-group"
    assert client.put(url, json={**corpo, "merchant_id": alheio["id"]}, headers=h).status_code == 404
    db_session.rollback()
    assert client.put(url, json={**corpo, "merchant_id": None}, headers=h).status_code == 200
    assert vinculos() == {None}


def test_editar_a_compra_com_parcela_paga_leva_o_estabelecimento_as_abertas(db_session, setup_data, override_get_session):
    ws, uid, h = setup_data["ws1"].id, setup_data["u1"].id, setup_data["headers1"]
    card = _cartao(db_session, uid)
    m = _estabelecimento(ws, h, name="Magazine")
    ancora = _parcelada(ws, uid, h, card)
    assert client.put(f"{_api(ws)}/transactions/{ancora['id']}", json={"status": "paid"}, headers=h).status_code == 200
    corpo = {
        "title": "Geladeira", "total_amount": "300.00", "transaction_date": HOJE, "installments_count": 3,
        "credit_card_id": card, "payment_method": "credit_card", "merchant_id": m["id"],
        "payers": [{"user_id": uid, "amount": "300.00"}],
        "splits": [{"user_id": uid, "split_method": "equal", "input_value": "100"}],
    }
    r = client.put(f"{_api(ws)}/transactions/{ancora['id']}/installment-group", json=corpo, headers=h)
    assert r.status_code == 200, r.text
    db_session.expire_all()
    parcelas = db_session.exec(select(Transaction).where(Transaction.installment_group_id.is_not(None))).all()
    # A paga congela (como o resto dela); as em aberto passam a ter o estabelecimento.
    assert {t.installment_no: t.merchant_id for t in parcelas} == {1: None, 2: m["id"], 3: m["id"]}


def test_gasto_por_estabelecimento_no_mes(db_session, setup_data, override_get_session):
    ws, uid, h = setup_data["ws1"].id, setup_data["u1"].id, setup_data["headers1"]
    m = _estabelecimento(ws, h, name="Mercado")
    _despesa(ws, uid, h, titulo="Compra 1", valor="100.00", merchant_id=m["id"])
    _despesa(ws, uid, h, titulo="Compra 2", valor="50.00", merchant_id=m["id"])
    _despesa(ws, uid, h, titulo="Avulsa", valor="30.00")
    linhas = client.get(f"{_api(ws)}/merchants/spending", headers=h).json()
    assert [(i["name"], i["total"], i["my_share"], i["count"]) for i in linhas] == [
        ("Mercado", "150.00", "150.00", 2), ("Sem estabelecimento", "30.00", "30.00", 1),
    ]
    assert client.get(f"{_api(ws)}/merchants", headers=h).json()[0]["transaction_count"] == 2
    assert client.get(f"{_api(ws)}/merchants/spending?month=2026-13", headers=h).status_code == 422


def test_quem_so_ve_o_seu_nao_soma_nem_conta_o_dos_outros(db_session, setup_data, override_get_session):
    from app.models.workspace import FinancialAccess, WorkspaceMembership, WorkspaceRole

    ws, uid, h = setup_data["ws1"].id, setup_data["u1"].id, setup_data["headers1"]
    db_session.add(WorkspaceMembership(
        workspace_id=ws, user_id=setup_data["u2"].id, role=WorkspaceRole.member,
        financial_access=FinancialAccess.involved_only,
    ))
    db_session.commit()
    m = _estabelecimento(ws, h, name="Mercado")
    _despesa(ws, uid, h, titulo="Só minha", valor="100.00", merchant_id=m["id"])
    h2 = setup_data["headers2"]
    assert client.get(f"{_api(ws)}/merchants", headers=h2).json()[0]["transaction_count"] == 0
    assert client.get(f"{_api(ws)}/merchants/spending", headers=h2).json() == []


def test_nome_sem_chave_de_apelido_e_achado_pelo_nome(db_session, setup_data, override_get_session):
    """"7-11" normaliza para vazio (sem letras de duas ou mais): é achado pelo nome, e não recriado."""
    ws, uid, h = setup_data["ws1"].id, setup_data["u1"].id, setup_data["headers1"]
    m = _estabelecimento(ws, h, name="7-11")
    assert _despesa(ws, uid, h, merchant_name="7-11")["merchant"]["id"] == m["id"]
    # E o título "7-11" não vincula sozinho: sem chave, não há apelido exato.
    assert _despesa(ws, uid, h, titulo="7-11")["merchant"] is None


def test_lote_de_lancamentos_vincula_pelo_apelido(db_session, setup_data, override_get_session):
    ws, h = setup_data["ws1"].id, setup_data["headers1"]
    m = _estabelecimento(ws, h, name="Uber", aliases=["UBER *TRIP"])
    r = client.post(f"{_api(ws)}/transactions/bulk", headers=h, json=[
        {"title": "UBER *TRIP", "total_amount": 23.0, "transaction_date": "2026-03-01T12:00:00"},
        {"title": "TAXI", "total_amount": 30.0, "transaction_date": "2026-03-01T12:00:00"},
    ])
    assert r.status_code == 200, r.text
    db_session.expire_all()
    vinculos = {t.title: t.merchant_id for t in db_session.exec(select(Transaction).where(Transaction.workspace_id == ws)).all()}
    assert vinculos == {"UBER *TRIP": m["id"], "TAXI": None}


def test_sem_estabelecimento_vem_por_ultimo_mesmo_sendo_o_maior(db_session, setup_data, override_get_session):
    ws, uid, h = setup_data["ws1"].id, setup_data["u1"].id, setup_data["headers1"]
    m = _estabelecimento(ws, h, name="Padaria")
    _despesa(ws, uid, h, titulo="Pão", valor="10.00", merchant_id=m["id"])
    _despesa(ws, uid, h, titulo="Aluguel", valor="2000.00")
    assert [i["name"] for i in client.get(f"{_api(ws)}/merchants/spending", headers=h).json()] == ["Padaria", "Sem estabelecimento"]


def test_edicao_completa_da_tela_com_categoria_e_estabelecimento(db_session, setup_data, override_get_session):
    """A tela edita pelo caminho COMPLETO (pagadores, divisão e itens no corpo).
    O `merchant_name` só era resolvido no caminho parcial, e aqui chegava ao
    `setattr` do lançamento: erro 500 em produção ao pôr estabelecimento e
    categoria num lançamento que já existia."""
    ws, uid, h = setup_data["ws1"].id, setup_data["u1"].id, setup_data["headers1"]
    tx = _despesa(ws, uid, h, titulo="Mercado", valor="80.00")
    categoria = _categoria(ws, h, "Feira")
    corpo = {
        "title": "Mercado", "total_amount": "80.00", "transaction_date": HOJE, "currency": "BRL",
        "split_mode": "transaction", "payment_method": "pix", "tag_ids": [], "settled": True,
        "payers": [{"user_id": uid, "amount": "80.00", "payment_method": None, "account_id": None}],
        "splits": [{"user_id": uid, "split_method": "equal", "input_value": "0"}],
        "items": [{"title": "Mercado", "amount": "80.00", "quantity": "1", "position": 0, "category_id": categoria}],
        "merchant_name": "Hortifruti Central",
    }
    url = f"{_api(ws)}/transactions/{tx['id']}"
    r = client.put(url, json=corpo, headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["merchant"]["name"] == "Hortifruti Central"
    assert [i["category_id"] for i in r.json()["items"]] == [categoria]
    # E a mesma edição completa desvincula com `merchant_id` nulo.
    sem_nome = {k: v for k, v in corpo.items() if k != "merchant_name"}
    r = client.put(url, json={**sem_nome, "merchant_id": None}, headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["merchant"] is None
