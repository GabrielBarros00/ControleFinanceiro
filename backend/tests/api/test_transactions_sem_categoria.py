"""Filtrar o que ainda NÃO foi categorizado.

## De onde veio a necessidade

Os Relatórios do espaço têm um quadro "Maior categoria". Numa conta de uso real
ele diz **"Sem categoria"** — e para na constatação. É o pior tipo de métrica:
identifica um problema, ocupa um quarto da faixa de destaque e não oferece
nenhuma saída. Quem lê fica sabendo que os relatórios não servem para nada
*e não sabe o que fazer a respeito*.

O convite óbvio é "categorizar essas despesas". Só que não havia como chegar
nelas: `category_id` filtra por UMA categoria, e a ausência de categoria não é
uma categoria — `?category_id=0` cai no `if category_id:` e é ignorado em
silêncio, devolvendo a lista inteira.

## Por que um parâmetro separado, e não `category_id=0`

Porque `0` significaria "sem categoria" só por convenção, e uma convenção que só
existe no código é a que some na próxima refatoração. `uncategorized=true` diz o
que faz, aparece no OpenAPI e não colide com id nenhum.

## O que é "sem categoria"

A categoria mora no ITEM, não na despesa. Uma despesa está sem categoria quando
**nenhum** item dela tem `category_id` — inclusive quando ela não tem item nenhum,
que é o caso da esmagadora maioria (lançamento simples não cria item). As duas
situações são a mesma coisa para quem olha o relatório, e o filtro tem de tratá-las
igual.
"""
import datetime

from fastapi.testclient import TestClient
from sqlmodel import Session

from app.main import app
from app.models.category import Category
from app.models.transaction import Transaction, TransactionItem

client = TestClient(app)


def _despesa(db_session, ws_id, user_id, titulo, *, categoria_id=None, com_item=True):
    tx = Transaction(
        title=titulo,
        total_amount=15,
        transaction_date=datetime.datetime.now(),
        workspace_id=ws_id,
        created_by_user_id=user_id,
    )
    db_session.add(tx)
    db_session.commit()
    db_session.refresh(tx)
    if com_item:
        db_session.add(TransactionItem(
            title=f"item de {titulo}", amount=15,
            category_id=categoria_id, transaction_id=tx.id,
        ))
        db_session.commit()
    return tx


def _listar(setup_data, ws_id, query):
    r = client.get(
        f"/api/v1/workspaces/{ws_id}/transactions/?{query}",
        headers=setup_data["headers1"],
    )
    assert r.status_code == 200, r.text
    return [t["title"] for t in r.json()["items"]]


def test_traz_so_o_que_nao_tem_categoria(db_session: Session, setup_data, override_get_session):
    ws1, u1 = setup_data["ws1"], setup_data["u1"]
    cat = Category(workspace_id=ws1.id, name="Comida")
    db_session.add(cat)
    db_session.commit()
    db_session.refresh(cat)

    _despesa(db_session, ws1.id, u1.id, "Pizza", categoria_id=cat.id)
    _despesa(db_session, ws1.id, u1.id, "Item sem categoria", categoria_id=None)
    _despesa(db_session, ws1.id, u1.id, "Sem item nenhum", com_item=False)

    titulos = _listar(setup_data, ws1.id, "uncategorized=true")

    assert sorted(titulos) == ["Item sem categoria", "Sem item nenhum"], (
        "o filtro precisa juntar os dois jeitos de estar sem categoria: item com "
        f"`category_id` nulo e despesa sem item nenhum. Veio {sorted(titulos)}"
    )


def test_uma_despesa_com_dois_itens_sem_categoria_aparece_uma_vez(
    db_session: Session, setup_data, override_get_session,
):
    """O `join` já duplicou lista neste arquivo antes (ver `category_id`)."""
    ws1, u1 = setup_data["ws1"], setup_data["u1"]
    tx = _despesa(db_session, ws1.id, u1.id, "Feira", categoria_id=None)
    db_session.add(TransactionItem(
        title="segundo item", amount=15, category_id=None, transaction_id=tx.id,
    ))
    db_session.commit()

    assert _listar(setup_data, ws1.id, "uncategorized=true") == ["Feira"]


def test_despesa_parcialmente_categorizada_nao_conta_como_sem_categoria(
    db_session: Session, setup_data, override_get_session,
):
    """Um item categorizado já é um começo — ela não entra na lista de trabalho."""
    ws1, u1 = setup_data["ws1"], setup_data["u1"]
    cat = Category(workspace_id=ws1.id, name="Casa")
    db_session.add(cat)
    db_session.commit()
    db_session.refresh(cat)

    tx = _despesa(db_session, ws1.id, u1.id, "Mercado", categoria_id=cat.id)
    db_session.add(TransactionItem(
        title="item solto", amount=15, category_id=None, transaction_id=tx.id,
    ))
    db_session.commit()

    assert _listar(setup_data, ws1.id, "uncategorized=true") == []


# --------------------------------------------------------------------------- #
# CONTROLE POSITIVO — sem isto, "não devolver nada" passaria em tudo acima.
# --------------------------------------------------------------------------- #

def test_controle_sem_o_filtro_a_lista_continua_inteira(
    db_session: Session, setup_data, override_get_session,
):
    ws1, u1 = setup_data["ws1"], setup_data["u1"]
    cat = Category(workspace_id=ws1.id, name="Comida")
    db_session.add(cat)
    db_session.commit()
    db_session.refresh(cat)

    _despesa(db_session, ws1.id, u1.id, "Pizza", categoria_id=cat.id)
    _despesa(db_session, ws1.id, u1.id, "Avulsa", categoria_id=None)

    assert sorted(_listar(setup_data, ws1.id, "limit=100")) == ["Avulsa", "Pizza"]


def test_controle_o_filtro_por_categoria_continua_funcionando(
    db_session: Session, setup_data, override_get_session,
):
    ws1, u1 = setup_data["ws1"], setup_data["u1"]
    cat = Category(workspace_id=ws1.id, name="Comida")
    db_session.add(cat)
    db_session.commit()
    db_session.refresh(cat)

    _despesa(db_session, ws1.id, u1.id, "Pizza", categoria_id=cat.id)
    _despesa(db_session, ws1.id, u1.id, "Avulsa", categoria_id=None)

    assert _listar(setup_data, ws1.id, f"category_id={cat.id}") == ["Pizza"]
