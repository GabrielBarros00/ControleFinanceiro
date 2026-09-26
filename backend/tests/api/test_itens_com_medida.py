"""Itens da nota com medida (ADR 0040), pela rota de lançamento.

Os casos são os da auditoria de 2026-09-26 (C10): a nota de balança que trunca,
a leitura errada, o litro de combustível com 3 casas, e os caminhos internos que
apagavam a medida — parcelamento, edição parcial e compra em moeda estrangeira.
"""
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.main import app
from app.models.credit_card import CreditCard
from app.models.transaction import Transaction, TransactionItem
from app.services.currency_service import CurrencyService

client = TestClient(app)


@pytest.fixture(name="cena")
def cena_fixture(db_session: Session, setup_data, override_get_session):
    card = CreditCard(name="Nubank", limit=Decimal("50000.00"), closing_day=25, due_day=5,
                      owner_user_id=setup_data["u1"].id)
    db_session.add(card)
    db_session.commit()
    db_session.refresh(card)
    return {"db": db_session, "ws": setup_data["ws1"].id, "u": setup_data["u1"].id,
            "h": setup_data["headers1"], "card": card.id}


def _nota(cena, itens, **extra):
    total = sum(Decimal(i["amount"]) for i in itens)
    corpo = {
        "title": "Mercado", "total_amount": str(total), "transaction_date": "2026-09-20T15:00:00Z",
        "payment_method": "pix", "payers": [{"user_id": cena["u"], "amount": str(total)}],
        "splits": [{"user_id": cena["u"], "split_method": "equal", "input_value": "0"}],
        "items": itens,
    }
    corpo.update(extra)
    return client.post(f"/api/v1/workspaces/{cena['ws']}/transactions/", json=corpo, headers=cena["h"])


def _itens(cena, tx_id):
    db = cena["db"]
    db.expire_all()
    return db.exec(
        select(TransactionItem).where(TransactionItem.transaction_id == tx_id).order_by(TransactionItem.position)
    ).all()


def test_nota_de_balanca_que_trunca_e_aceita_e_guarda_a_medida(cena):
    r = _nota(cena, [
        {"title": "Carne", "quantity": "1.235", "unit": "kg", "unit_amount": "39.90", "amount": "49.27", "position": 0},
        {"title": "Refrigerante", "quantity": "2", "unit": "un", "unit_amount": "8.50", "amount": "17.00", "position": 1},
    ])
    assert r.status_code == 200, r.text
    assert [(i.title, i.quantity, i.unit, i.unit_amount, i.amount) for i in _itens(cena, r.json()["id"])] == [
        ("Carne", Decimal("1.235"), "kg", Decimal("39.90"), Decimal("49.27")),
        ("Refrigerante", Decimal("2"), "un", Decimal("8.50"), Decimal("17.00")),
    ]


def test_o_que_a_tela_mandava_e_nao_conseguia_salvar_agora_passa(cena):
    """2,050 × R$ 19,90: a tela calculava R$ 40,79 (ponto flutuante) e o
    servidor exigia R$ 40,80 exatos. As duas leituras são honestas."""
    for impresso in ("40.79", "40.80"):
        r = _nota(cena, [{"title": "Queijo", "quantity": "2.050", "unit": "kg", "unit_amount": "19.90",
                          "amount": impresso, "position": 0}])
        assert r.status_code == 200, r.text


def test_leitura_errada_e_recusada_dizendo_o_que_conferir(cena):
    r = _nota(cena, [{"title": "Carne", "quantity": "1.235", "unit": "kg", "unit_amount": "39.90",
                      "amount": "49.40", "position": 0}])
    assert r.status_code == 422, r.text
    assert any("Confira a nota" in m for m in r.json()["error"]["details"].values())


def test_combustivel_guarda_o_preco_do_litro_com_tres_casas(cena):
    r = _nota(cena, [{"title": "Gasolina", "quantity": "40.123", "unit": "l", "unit_amount": "5.899",
                      "amount": "236.69", "position": 0}])
    assert r.status_code == 200, r.text
    [item] = _itens(cena, r.json()["id"])
    assert (item.unit_amount, item.unit) == (Decimal("5.899"), "l")
    assert r.json()["items"][0]["unit_amount"] in ("5.899", "5.8990")


def test_unidade_fora_do_vocabulario_e_recusada(cena):
    r = _nota(cena, [{"title": "Arroz", "quantity": "1", "unit": "saco", "unit_amount": "30.00",
                      "amount": "30.00", "position": 0}])
    assert r.status_code == 422, r.text


def test_item_sombra_da_categoria_segue_sem_medida(cena):
    """O lançamento simples com categoria não pede nada novo (decisão do dono)."""
    r = _nota(cena, [{"title": "Mercado", "amount": "150.00", "position": 0}])
    assert r.status_code == 200, r.text
    [item] = _itens(cena, r.json()["id"])
    assert (item.quantity, item.unit, item.unit_amount) == (Decimal("1"), None, None)


def test_parcelado_leva_a_medida_para_as_parcelas_e_a_compra_a_devolve(cena):
    r = _nota(cena, [{"title": "Carne", "quantity": "1.235", "unit": "kg", "unit_amount": "39.90",
                      "amount": "49.28", "position": 0}],
              payment_method="credit_card", credit_card_id=cena["card"], installments_count=2,
              payers=[{"user_id": cena["u"], "amount": "49.28", "payment_method": "credit_card"}])
    assert r.status_code == 200, r.text
    db = cena["db"]
    grupo = db.get(Transaction, r.json()["id"]).installment_group_id
    parcelas = db.exec(select(Transaction).where(Transaction.installment_group_id == grupo)).all()
    fatias = [i for p in parcelas for i in _itens(cena, p.id)]
    # A medida é da compra; o unitário não vai para a fatia (a tela recalcularia
    # o total da parcela a partir dele).
    assert {(i.quantity, i.unit, i.unit_amount) for i in fatias} == {(Decimal("1.235"), "kg", None)}
    assert sum(i.amount for i in fatias) == Decimal("49.28")

    compra = client.get(f"/api/v1/workspaces/{cena['ws']}/transactions/{r.json()['id']}/installment-group",
                        headers=cena["h"]).json()
    [item] = compra["whole"]["items"]
    assert (Decimal(item["quantity"]), item["unit"], Decimal(item["amount"])) == (Decimal("1.235"), "kg", Decimal("49.28"))


def test_edicao_parcial_do_total_mantem_a_medida(cena):
    r = _nota(cena, [{"title": "Carne", "quantity": "2", "unit": "kg", "unit_amount": "40.00",
                      "amount": "80.00", "position": 0}])
    assert r.status_code == 200, r.text
    r = client.put(f"/api/v1/workspaces/{cena['ws']}/transactions/{r.json()['id']}",
                   json={"total_amount": "70.00"}, headers=cena["h"])
    assert r.status_code == 200, r.text
    [item] = _itens(cena, r.json()["id"])
    assert (item.quantity, item.unit, item.unit_amount, item.amount) == (
        Decimal("2"), "kg", Decimal("35"), Decimal("70.00"),
    )


def test_compra_em_moeda_estrangeira_mantem_a_medida(cena, monkeypatch):
    monkeypatch.setattr(CurrencyService, "get_rate_sync", lambda *a, **k: (Decimal("5.00"), "ptax"))
    r = _nota(cena, [{"title": "Café", "quantity": "3", "unit": "un", "unit_amount": "4.00",
                      "amount": "12.00", "position": 0}], currency="USD")
    assert r.status_code == 200, r.text
    [item] = _itens(cena, r.json()["id"])
    # US$ 12 × 5 = R$ 60: a quantidade fica e o unitário acompanha (R$ 20).
    assert (item.quantity, item.unit, item.unit_amount, item.amount) == (
        Decimal("3"), "un", Decimal("20"), Decimal("60.00"),
    )
