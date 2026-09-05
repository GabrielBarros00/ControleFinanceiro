"""Categorizar várias despesas de uma vez.

## De onde vem a necessidade

O quadro "Maior categoria" dos Relatórios responde **"Sem categoria"** numa conta
de uso real, e agora leva à lista do que falta categorizar (`uncategorized`).
Chegar na lista é metade do caminho: categorizar trinta despesas uma a uma
significa trinta vezes abrir o detalhe, entrar na edição, escolher a categoria e
salvar. Ninguém faz isso, e é por isso que a categoria fica vazia — não por falta
de vontade, por custo.

## A decisão que o teste tranca

Categoria mora no ITEM, não na despesa. Uma despesa sem item nenhum (o caso
comum) precisa **ganhar um item** para ter categoria — e esse item tem de valer
o total, senão a soma da despesa deixa de fechar. Uma despesa que já tem itens
categorizados não é tocada: quem separou "mercado" de "farmácia" na mesma compra
fez isso de propósito, e um lote não pode desfazer esse trabalho.
"""
import datetime
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.core.jwt import create_access_token
from app.main import app
from app.models.category import Category
from app.models.transaction import Transaction, TransactionItem
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMembership, WorkspaceRole

client = TestClient(app)

QUANDO = datetime.datetime(2026, 9, 10, 12, 0, tzinfo=datetime.UTC)


@pytest.fixture(name="cena")
def cena_fixture(db_session: Session, override_get_session):
    dono = User(name="Dono", email="dono@lote.com", password_hash="h")
    ws = Workspace(name="Casa", base_currency="BRL")
    db_session.add_all([dono, ws])
    db_session.commit()
    db_session.add(WorkspaceMembership(
        workspace_id=ws.id, user_id=dono.id, role=WorkspaceRole.owner,
    ))
    cat = Category(workspace_id=ws.id, name="Mercado")
    outra = Category(workspace_id=ws.id, name="Farmácia")
    db_session.add_all([cat, outra])
    db_session.commit()
    db_session.refresh(cat)
    db_session.refresh(outra)

    def despesa(titulo, valor="100.00"):
        tx = Transaction(
            title=titulo, total_amount=Decimal(valor), currency="BRL",
            transaction_date=QUANDO, billing_month="2026-09", status="confirmed",
            workspace_id=ws.id, created_by_user_id=dono.id,
        )
        db_session.add(tx)
        db_session.commit()
        db_session.refresh(tx)
        return tx

    return {
        "db": db_session, "ws": ws, "cat": cat, "outra": outra, "despesa": despesa,
        "h": {"Cookie": f"access_token={create_access_token({'sub': str(dono.id)})}"},
    }


def _categorizar(cena, ids, category_id):
    return client.post(
        f"/api/v1/workspaces/{cena['ws'].id}/transactions/bulk-categorize",
        json={"transaction_ids": ids, "category_id": category_id},
        headers=cena["h"],
    )


def _categorias_de(cena, tx_id):
    return [
        i.category_id
        for i in cena["db"].exec(
            select(TransactionItem).where(TransactionItem.transaction_id == tx_id)
        ).all()
    ]


def test_categoriza_varias_de_uma_vez(cena):
    a = cena["despesa"]("Padaria")
    b = cena["despesa"]("Feira")

    r = _categorizar(cena, [a.id, b.id], cena["cat"].id)

    assert r.status_code == 200, r.text
    assert r.json()["updated"] == 2
    assert _categorias_de(cena, a.id) == [cena["cat"].id]
    assert _categorias_de(cena, b.id) == [cena["cat"].id]


def test_o_item_criado_vale_o_total_da_despesa(cena):
    """Senão a soma da despesa deixa de fechar e a divisão por item quebra."""
    a = cena["despesa"]("Padaria", "137.45")

    _categorizar(cena, [a.id], cena["cat"].id)

    item = cena["db"].exec(
        select(TransactionItem).where(TransactionItem.transaction_id == a.id)
    ).one()
    assert item.amount == Decimal("137.45"), (
        f"o item nasceu com {item.amount} numa despesa de 137.45 — a soma dos "
        "itens tem de fechar com o total"
    )


def test_nao_desfaz_categorizacao_existente(cena):
    """Quem separou mercado de farmácia na mesma compra fez de propósito."""
    a = cena["despesa"]("Mercado grande", "200.00")
    db = cena["db"]
    db.add_all([
        TransactionItem(transaction_id=a.id, title="comida", amount=Decimal("120.00"),
                        category_id=cena["cat"].id),
        TransactionItem(transaction_id=a.id, title="remédio", amount=Decimal("80.00"),
                        category_id=cena["outra"].id),
    ])
    db.commit()

    r = _categorizar(cena, [a.id], cena["cat"].id)

    assert r.status_code == 200, r.text
    assert r.json()["skipped"] == 1, (
        "a despesa já categorizada foi reescrita pelo lote"
    )
    assert sorted(_categorias_de(cena, a.id)) == sorted([cena["cat"].id, cena["outra"].id])


def test_despesa_de_outro_espaco_nao_entra_no_lote(cena, db_session: Session):
    """Passar um id alheio na lista não pode categorizar o que não é daqui."""
    outro_dono = User(name="Alheio", email="alheio@lote.com", password_hash="h")
    outra_casa = Workspace(name="Vizinha", base_currency="BRL")
    db_session.add_all([outro_dono, outra_casa])
    db_session.commit()
    alheia = Transaction(
        title="Despesa alheia", total_amount=Decimal("50.00"), currency="BRL",
        transaction_date=QUANDO, billing_month="2026-09", status="confirmed",
        workspace_id=outra_casa.id, created_by_user_id=outro_dono.id,
    )
    db_session.add(alheia)
    db_session.commit()
    db_session.refresh(alheia)

    minha = cena["despesa"]("Minha")
    r = _categorizar(cena, [minha.id, alheia.id], cena["cat"].id)

    assert r.status_code == 200, r.text
    assert r.json()["updated"] == 1, "o lote alcançou despesa de outro espaço"
    assert _categorias_de(cena, alheia.id) == []


def test_categoria_de_outro_espaco_e_recusada(cena, db_session: Session):
    outra_casa = Workspace(name="Vizinha", base_currency="BRL")
    db_session.add(outra_casa)
    db_session.commit()
    cat_alheia = Category(workspace_id=outra_casa.id, name="Alheia")
    db_session.add(cat_alheia)
    db_session.commit()
    db_session.refresh(cat_alheia)

    a = cena["despesa"]("Padaria")
    r = _categorizar(cena, [a.id], cat_alheia.id)

    assert r.status_code in (400, 404), (
        f"categoria de outro espaço foi aceita (status {r.status_code})"
    )
    assert _categorias_de(cena, a.id) == []


def test_lista_vazia_nao_e_erro(cena):
    """A tela pode chamar com seleção vazia num duplo clique; não é falha."""
    r = _categorizar(cena, [], cena["cat"].id)
    assert r.status_code == 200
    assert r.json()["updated"] == 0
