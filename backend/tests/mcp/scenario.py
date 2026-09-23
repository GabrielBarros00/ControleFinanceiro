"""Cenário realista para os testes das tools, criado pela API REST do próprio app.

Criar pelo REST (e não por ORM) garante que os dados têm a forma que o app de
verdade grava — fatura derivada, `billing_month`, divisão em centavos,
`settled_at` — e é exatamente com esses dados que as tools precisam conversar.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Optional

from app.domain.dates import today_local
from app.models.credit_card import CreditCard
from app.models.payment_account import PaymentAccount
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceRole
from tests.mcp.conftest import cookie_headers, issue_token, make_space, make_user


@dataclass
class Cenario:
    alice: User
    joao: User
    bob: User
    pessoal: Workspace
    casa: Workspace
    ws_bob: Workspace
    nubank: CreditCard
    conta: PaymentAccount
    token: str
    token_bob: str
    hoje: date


def cria_despesa(client, user: User, ws: Workspace, *, title: str, amount: str, day: date,
                 card: Optional[CreditCard] = None, split_with: Optional[list[User]] = None,
                 category_id: Optional[int] = None, installments: Optional[int] = None) -> dict:
    participantes = [user] + list(split_with or [])
    corpo = {
        "title": title,
        "total_amount": amount,
        "transaction_date": f"{day.isoformat()}T15:00:00Z",
        "payers": [{"user_id": user.id, "amount": amount}],
        "splits": [{"user_id": p.id, "split_method": "equal", "input_value": "0"} for p in participantes],
        "split_mode": "transaction",
    }
    if card is not None:
        corpo["credit_card_id"] = card.id
    if category_id is not None:
        corpo["items"] = [{"title": title, "amount": amount, "quantity": "1", "position": 0, "category_id": category_id}]
    if installments:
        corpo["installments_count"] = installments
    r = client.post(f"/api/v1/workspaces/{ws.id}/transactions/", json=corpo, headers=cookie_headers(user))
    assert r.status_code == 200, r.text
    return r.json()


def monta(db, client) -> Cenario:
    alice = make_user(db, "Alice Souza", "alice@example.com")
    joao = make_user(db, "João Pereira", "joao@example.com")
    bob = make_user(db, "Bob Lima", "bob@example.com")
    pessoal = make_space(db, alice, "Meu espaço")
    casa = make_space(db, alice, "Casa", members=[(joao, WorkspaceRole.member)])
    ws_bob = make_space(db, bob, "Espaço do Bob")
    nubank = CreditCard(name="Nubank", limit="5000.00", closing_day=3, due_day=10, owner_user_id=alice.id, currency="BRL")
    conta = PaymentAccount(name="Itaú", owner_user_id=alice.id, currency="BRL")
    db.add_all([nubank, conta])
    db.commit()
    db.refresh(nubank)
    db.refresh(conta)
    hoje = today_local()
    return Cenario(
        alice=alice, joao=joao, bob=bob, pessoal=pessoal, casa=casa, ws_bob=ws_bob,
        nubank=nubank, conta=conta,
        token=issue_token(db, alice), token_bob=issue_token(db, bob), hoje=hoje,
    )


def categoria(db, ws: Workspace, nome: str) -> int:
    from sqlmodel import select
    from app.models.category import Category

    return db.exec(select(Category).where(Category.workspace_id == ws.id, Category.name == nome)).one().id


def ontem(c: Cenario) -> date:
    return c.hoje - timedelta(days=1)
