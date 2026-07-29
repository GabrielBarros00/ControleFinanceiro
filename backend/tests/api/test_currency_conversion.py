"""Conversão de moeda estrangeira → BRL na entrada (PTAX do dia + IOF no cartão).
PTAX é mockado para não bater na rede."""
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.main import app
from app.models.credit_card import CreditCard
from app.models.transaction import Transaction
from app.models.workspace import WorkspaceMembership, WorkspaceRole
from app.services.currency_service import CurrencyService

client = TestClient(app)


@pytest.fixture(name="ws_with_card")
def ws_with_card_fixture(db_session: Session, setup_data):
    db_session.add(WorkspaceMembership(
        workspace_id=setup_data["ws1"].id, user_id=setup_data["u2"].id, role=WorkspaceRole.member,
    ))
    card = CreditCard(
        workspace_id=setup_data["ws1"].id, name="Nubank",
        limit=Decimal("50000.00"), closing_day=25, due_day=5,
    )
    db_session.add(card)
    db_session.commit()
    db_session.refresh(card)
    setup_data["card"] = card
    return setup_data


@pytest.fixture(autouse=True)
def _mock_ptax(monkeypatch):
    # PTAX fixa em 5,00 (fonte 'ptax') — sem rede
    monkeypatch.setattr(CurrencyService, "get_rate_sync", lambda *a, **k: (Decimal("5.00"), "ptax"))


def _usd_payload(u1_id, **over):
    p = {
        "title": "Amazon US",
        "total_amount": 50.0,
        "currency": "USD",
        "transaction_date": "2026-03-10T12:00:00",
        "payment_method": "credit_card",
        "payers": [{"user_id": u1_id, "amount": 50.0}],
        "splits": [{"user_id": u1_id, "split_method": "equal", "input_value": 0}],
    }
    p.update(over)
    return p


@pytest.mark.parametrize(
    "moeda",
    [
        "../../../etc/passwd",   # o código desce até o PATH da URL da fonte de mercado
        "usd/../../outro",
        "NOTACURRENCY",          # aceito e persistido: sumia de TODA agregação
        "US",
        "US1",
        "ÁÁÁ",                   # isalpha() sozinho aceitava letras não-ASCII
    ],
)
def test_moeda_invalida_e_recusada_sem_ir_a_rede(
    ws_with_card, override_get_session, monkeypatch, moeda
):
    """Código de moeda é validado como ISO-3 ANTES de qualquer I/O.

    Dois problemas de uma vez: (1) o código entra na URL da fonte de mercado
    (`.../v1/currencies/{codigo}.json`), então um parâmetro de query escolhia o
    caminho de uma requisição que o SERVIDOR faz para fora; (2) um código
    inventado era gravado no lançamento e, como toda agregação filtra
    `currency == base_currency`, a linha sumia de dívidas, relatórios, fatura e
    previsão sem nenhum aviso.
    """
    ws, u1, headers = ws_with_card["ws1"], ws_with_card["u1"], ws_with_card["headers1"]

    def _explode(*a, **k):  # nenhuma busca externa pode acontecer
        raise AssertionError("foi à fonte de câmbio com uma moeda inválida")

    monkeypatch.setattr(CurrencyService, "get_rate_sync", _explode)

    # 1) Consulta de câmbio: 400 explícito
    resp = client.get(
        f"/api/v1/workspaces/{ws.id}/analytics/exchange-rate",
        params={"from_currency": moeda},
        headers=headers,
    )
    assert resp.status_code == 400
    assert "Moeda inválida" in resp.json()["error"]["message"]

    # 2) Criação de lançamento: 422 na borda (nunca persiste a moeda inventada)
    resp = client.post(
        f"/api/v1/workspaces/{ws.id}/transactions/",
        json=_usd_payload(u1.id, currency=moeda),
        headers=headers,
    )
    assert resp.status_code == 422


def test_usd_card_converts_with_iof(db_session, ws_with_card, override_get_session):
    ws, u1, card, headers = ws_with_card["ws1"], ws_with_card["u1"], ws_with_card["card"], ws_with_card["headers1"]
    resp = client.post(
        f"/api/v1/workspaces/{ws.id}/transactions/",
        json=_usd_payload(u1.id, credit_card_id=card.id),
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    tx = resp.json()
    # 50 × 5,00 × (1 + 0,035) = 258,75
    assert tx["total_amount"] == "258.75"
    assert tx["currency"] == "BRL"
    assert tx["original_currency"] == "USD"
    assert Decimal(tx["original_amount"]) == Decimal("50.00")
    assert Decimal(tx["exchange_rate"]) == Decimal("5.00")
    assert Decimal(tx["iof_rate"]) == Decimal("0.035")
    assert tx["payers"][0]["amount"] == "258.75"
    assert tx["splits"][0]["computed_amount"] == "258.75"


def test_usd_pix_sem_iof(db_session, ws_with_card, override_get_session):
    ws, u1, headers = ws_with_card["ws1"], ws_with_card["u1"], ws_with_card["headers1"]
    resp = client.post(
        f"/api/v1/workspaces/{ws.id}/transactions/",
        json=_usd_payload(u1.id, payment_method="pix"),
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    tx = resp.json()
    assert tx["total_amount"] == "250.00"  # 50 × 5,00, sem IOF fora do cartão
    assert Decimal(tx["iof_rate"]) == Decimal("0")


def test_moeda_de_mercado_carimba_fonte(db_session, ws_with_card, override_get_session, monkeypatch):
    """Moeda fora do PTAX (ex.: ARS) usa fonte de mercado — carimba rate_source."""
    monkeypatch.setattr(CurrencyService, "get_rate_sync", lambda *a, **k: (Decimal("0.005"), "market"))
    ws, u1, headers = ws_with_card["ws1"], ws_with_card["u1"], ws_with_card["headers1"]
    resp = client.post(
        f"/api/v1/workspaces/{ws.id}/transactions/",
        json=_usd_payload(u1.id, currency="ARS", payment_method="pix", total_amount=10000.0,
                          payers=[{"user_id": u1.id, "amount": 10000.0}]),
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    tx = resp.json()
    assert tx["total_amount"] == "50.00"  # 10000 × 0,005
    assert tx["original_currency"] == "ARS"
    assert tx["rate_source"] == "market"


def test_brl_nao_converte(db_session, ws_with_card, override_get_session):
    ws, u1, headers = ws_with_card["ws1"], ws_with_card["u1"], ws_with_card["headers1"]
    resp = client.post(
        f"/api/v1/workspaces/{ws.id}/transactions/",
        json=_usd_payload(u1.id, currency="BRL", payment_method="pix"),
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    tx = resp.json()
    assert tx["total_amount"] == "50.00"
    assert tx["original_currency"] is None
    assert tx["exchange_rate"] is None


def test_estrangeiro_divisao_fixa_converte(db_session, ws_with_card, override_get_session):
    """Valor fixo em moeda estrangeira agora CONVERTE (rateio proporcional em BRL)."""
    ws, u1, u2, headers = ws_with_card["ws1"], ws_with_card["u1"], ws_with_card["u2"], ws_with_card["headers1"]
    resp = client.post(
        f"/api/v1/workspaces/{ws.id}/transactions/",
        json=_usd_payload(
            u1.id, payment_method="pix",
            payers=[{"user_id": u1.id, "amount": 50.0}],
            splits=[
                {"user_id": u1.id, "split_method": "fixed", "input_value": 30.0},
                {"user_id": u2.id, "split_method": "fixed", "input_value": 20.0},
            ],
        ),
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    tx = resp.json()
    assert tx["total_amount"] == "250.00"  # 50 × 5,00
    splits = {s["user_id"]: s["computed_amount"] for s in tx["splits"]}
    assert splits == {u1.id: "150.00", u2.id: "100.00"}  # 30→150, 20→100
    assert sum(Decimal(v) for v in splits.values()) == Decimal("250.00")


def test_estrangeiro_multi_pagador(db_session, ws_with_card, override_get_session):
    ws, u1, u2, headers = ws_with_card["ws1"], ws_with_card["u1"], ws_with_card["u2"], ws_with_card["headers1"]
    resp = client.post(
        f"/api/v1/workspaces/{ws.id}/transactions/",
        json=_usd_payload(
            u1.id, payment_method="pix", total_amount=100.0,
            payers=[{"user_id": u1.id, "amount": 60.0}, {"user_id": u2.id, "amount": 40.0}],
            splits=[
                {"user_id": u1.id, "split_method": "equal", "input_value": 0},
                {"user_id": u2.id, "split_method": "equal", "input_value": 0},
            ],
        ),
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    tx = resp.json()
    assert tx["total_amount"] == "500.00"  # 100 × 5
    payers = {p["user_id"]: p["amount"] for p in tx["payers"]}
    assert payers == {u1.id: "300.00", u2.id: "200.00"}  # 60→300, 40→200


def test_estrangeiro_por_item(db_session, ws_with_card, override_get_session):
    ws, u1, u2, headers = ws_with_card["ws1"], ws_with_card["u1"], ws_with_card["u2"], ws_with_card["headers1"]
    resp = client.post(
        f"/api/v1/workspaces/{ws.id}/transactions/",
        json=_usd_payload(
            u1.id, payment_method="pix", total_amount=90.0, split_mode="item",
            payers=[{"user_id": u1.id, "amount": 90.0}], splits=[],
            items=[
                {"title": "Carne", "amount": 60.0, "shares": [
                    {"user_id": u1.id, "split_method": "equal", "input_value": 0},
                    {"user_id": u2.id, "split_method": "equal", "input_value": 0}]},
                {"title": "Cerveja", "amount": 30.0, "shares": [
                    {"user_id": u1.id, "split_method": "equal", "input_value": 0},
                    {"user_id": u2.id, "split_method": "equal", "input_value": 0}]},
            ],
        ),
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    tx = resp.json()
    assert tx["total_amount"] == "450.00"  # 90 × 5
    items = {it["title"]: it["amount"] for it in tx["items"]}
    assert items == {"Carne": "300.00", "Cerveja": "150.00"}  # 60→300, 30→150
    assert sum(Decimal(s["computed_amount"]) for s in tx["splits"]) == Decimal("450.00")


def test_usd_parcelado_converte_e_fatia(db_session, ws_with_card, override_get_session):
    ws, u1, card, headers = ws_with_card["ws1"], ws_with_card["u1"], ws_with_card["card"], ws_with_card["headers1"]
    resp = client.post(
        f"/api/v1/workspaces/{ws.id}/transactions/",
        json=_usd_payload(
            u1.id, credit_card_id=card.id, installments_count=2, total_amount=100.0,
            payers=[{"user_id": u1.id, "amount": 100.0}],
        ),
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    group_id = resp.json()["installment_group_id"]
    sibs = db_session.exec(
        select(Transaction).where(
            Transaction.installment_group_id == group_id
        ).order_by(Transaction.installment_no)
    ).all()
    # 100 USD × 5 × 1,035 = 517,50 BRL → 258,75 por parcela; original fatiado 50/50
    assert [s.total_amount for s in sibs] == [Decimal("258.75"), Decimal("258.75")]
    assert all(s.currency == "BRL" for s in sibs)
    assert all(s.original_currency == "USD" for s in sibs)
    assert [s.original_amount for s in sibs] == [Decimal("50.00"), Decimal("50.00")]


def test_group_whole_estrangeiro_por_item_volta_na_moeda_original(db_session, ws_with_card, override_get_session):
    """Grupo parcelado ESTRANGEIRO dividido por item: o `whole` (para o form de
    edição) volta na MOEDA ORIGINAL, com itens e shares fixas que fecham o total
    original — antes a reconstrução por item devolvia valores em BRL contra o
    total em USD, e o form não fechava."""
    ws, u1, u2, card, headers = (
        ws_with_card["ws1"], ws_with_card["u1"], ws_with_card["u2"],
        ws_with_card["card"], ws_with_card["headers1"],
    )
    resp = client.post(
        f"/api/v1/workspaces/{ws.id}/transactions/",
        json=_usd_payload(
            u1.id, credit_card_id=card.id, installments_count=2, total_amount=100.0,
            split_mode="item", payers=[{"user_id": u1.id, "amount": 100.0}], splits=[],
            items=[
                {"title": "Hotel", "amount": 60.0, "shares": [
                    {"user_id": u1.id, "split_method": "fixed", "input_value": 40.0},
                    {"user_id": u2.id, "split_method": "fixed", "input_value": 20.0}]},
                {"title": "Passeio", "amount": 40.0, "shares": [
                    {"user_id": u1.id, "split_method": "fixed", "input_value": 20.0},
                    {"user_id": u2.id, "split_method": "fixed", "input_value": 20.0}]},
            ],
        ),
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    anchor_id = resp.json()["id"]

    resp = client.get(
        f"/api/v1/workspaces/{ws.id}/transactions/{anchor_id}/installment-group",
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    whole = resp.json()["whole"]
    assert whole["currency"] == "USD"
    assert Decimal(whole["total_amount"]) == Decimal("100.00")
    items = sorted(whole["items"], key=lambda it: it["position"])
    # Itens fecham o total ORIGINAL (USD), não o BRL convertido (que somaria 517,50)
    assert [Decimal(it["amount"]) for it in items] == [Decimal("60.00"), Decimal("40.00")]
    assert sum(Decimal(it["amount"]) for it in items) == Decimal("100.00")
    # Cada item: shares fixas fecham o valor do item, na moeda original
    for it in items:
        assert sum(Decimal(s["input_value"]) for s in it["shares"]) == Decimal(it["amount"])
    hotel = {s["user_id"]: Decimal(s["input_value"]) for s in items[0]["shares"]}
    assert hotel == {u1.id: Decimal("40.00"), u2.id: Decimal("20.00")}


def test_partial_total_edit_limpa_original_estrangeiro(db_session, ws_with_card, override_get_session):
    """Caminho parcial legado: mudar só o total (semântica BRL) de uma transação
    que era estrangeira limpa os original_* obsoletos — senão o registro afirmaria
    um câmbio que já não bate. Edição de moeda usa a edição completa (re-converte)."""
    ws, u1, headers = ws_with_card["ws1"], ws_with_card["u1"], ws_with_card["headers1"]
    resp = client.post(
        f"/api/v1/workspaces/{ws.id}/transactions/",
        json=_usd_payload(u1.id, payment_method="pix"),  # 50 USD × 5 = 250 BRL, sem IOF
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    tx = resp.json()
    assert tx["original_currency"] == "USD"
    tx_id = tx["id"]

    # PUT parcial só com total_amount (sem currency, sem payers) → semântica BRL
    resp = client.put(
        f"/api/v1/workspaces/{ws.id}/transactions/{tx_id}",
        json={"total_amount": 300.0},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    upd = resp.json()
    assert upd["total_amount"] == "300.00"
    assert upd["currency"] == "BRL"
    assert upd["original_currency"] is None
    assert upd["original_amount"] is None
    assert upd["exchange_rate"] is None


def test_estrangeiro_por_item_com_ajuste(db_session, ws_with_card, override_get_session):
    """Item mode + ajuste (frete) em moeda estrangeira: itens e ajuste convertidos,
    fechando o total em BRL."""
    ws, u1, headers = ws_with_card["ws1"], ws_with_card["u1"], ws_with_card["headers1"]
    resp = client.post(
        f"/api/v1/workspaces/{ws.id}/transactions/",
        json=_usd_payload(
            u1.id, payment_method="pix", total_amount=100.0, split_mode="item",
            payers=[{"user_id": u1.id, "amount": 100.0}], splits=[],
            items=[
                {"title": "Item A", "amount": 60.0, "shares": [
                    {"user_id": u1.id, "split_method": "equal", "input_value": 0}]},
                {"title": "Item B", "amount": 30.0, "shares": [
                    {"user_id": u1.id, "split_method": "equal", "input_value": 0}]},
            ],
            adjustments=[{"type": "shipping", "amount": 10.0}],
        ),
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    tx = resp.json()
    assert tx["total_amount"] == "500.00"  # 100 × 5
    items = {it["title"]: it["amount"] for it in tx["items"]}
    assert items == {"Item A": "300.00", "Item B": "150.00"}  # 60→300, 30→150
    assert tx["adjustments"][0]["amount"] == "50.00"  # frete 10 → 50
    # itens (450) + ajuste (50) = 500; split derivado fecha o total
    assert sum(Decimal(s["computed_amount"]) for s in tx["splits"]) == Decimal("500.00")


def test_editar_estrangeiro_reconverte(db_session, ws_with_card, override_get_session):
    """Editar um lançamento estrangeiro (form manda o original) re-converte."""
    ws, u1, headers = ws_with_card["ws1"], ws_with_card["u1"], ws_with_card["headers1"]
    created = client.post(
        f"/api/v1/workspaces/{ws.id}/transactions/",
        json=_usd_payload(u1.id, payment_method="pix"),
        headers=headers,
    ).json()
    tx_id = created["id"]

    # Full edit mandando USD 80 (o form manda o original + payers)
    resp = client.put(
        f"/api/v1/workspaces/{ws.id}/transactions/{tx_id}",
        json={
            "total_amount": 80.0, "currency": "USD", "payment_method": "pix",
            "split_mode": "transaction",
            "payers": [{"user_id": u1.id, "amount": 80.0}],
            "splits": [{"user_id": u1.id, "split_method": "equal", "input_value": 0}],
        },
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    tx = resp.json()
    assert tx["total_amount"] == "400.00"  # 80 × 5,00
    assert tx["currency"] == "BRL"
    assert Decimal(tx["original_amount"]) == Decimal("80.00")
    assert tx["original_currency"] == "USD"
