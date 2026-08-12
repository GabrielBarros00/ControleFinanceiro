"""Sonda ATIVA: um membro restrito varre TODA rota GET atrás do segredo alheio.

`test_privacy_matrix.py` prova endpoint por endpoint, escolhidos à mão; este
percorre o router de verdade e chama **tudo** que responde a GET, procurando na
resposta inteira os marcadores que só existem no lançamento — e nos recursos
pessoais — de outra pessoa. É o mesmo mecanismo do
`test_admin_sem_vazamento_financeiro.py`, virado para o vizinho de workspace em
vez do administrador: quem tem `involved_only` divide a casa com a vítima e
enxerga muito mais superfície que um admin de plataforma.

O valor de varrer em vez de listar: a rota que NASCER amanhã já entra aqui.
"""
from datetime import datetime, UTC
from decimal import Decimal

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from app.core.jwt import create_access_token
from app.main import app
from app.models.category import Category
from app.models.credit_card import CreditCard
from app.models.financing import AmortizationMethod, Financing
from app.models.income import Income
from app.models.transaction import Transaction, TransactionPayer, TransactionSplit
from app.models.user import User
from app.models.workspace import (
    FinancialAccess, Workspace, WorkspaceMembership, WorkspaceRole,
)

cliente = TestClient(app, raise_server_exceptions=False)

# Marcadores improváveis: nenhum aparece por acaso num id, contagem ou data.
VALOR_LANCAMENTO = "9182.73"
TITULO_LANCAMENTO = "consulta-reservada-xyz"
VALOR_RENDA = "31337.11"
TITULO_RENDA = "bonus-confidencial-abc"
NOME_CARTAO = "cartao-secreto-qwe"
TITULO_FINANCIAMENTO = "financiamento-sigiloso-rst"
VALOR_FINANCIAMENTO = "77321.19"

MARCADORES = [
    VALOR_LANCAMENTO, TITULO_LANCAMENTO, VALOR_RENDA, TITULO_RENDA,
    NOME_CARTAO, TITULO_FINANCIAMENTO, VALOR_FINANCIAMENTO,
]


@pytest.fixture(name="casa")
def casa_fixture(db_session, override_get_session):
    """Vítima (owner) e bisbilhoteiro (member, `involved_only`) na mesma casa."""
    vitima = User(name="Vitima", email="v@ex.com", password_hash="h")
    bisbilhoteiro = User(name="Bisb", email="b@ex.com", password_hash="h")
    db_session.add_all([vitima, bisbilhoteiro])
    db_session.commit()
    db_session.refresh(vitima)
    db_session.refresh(bisbilhoteiro)

    ws = Workspace(name="Casa", created_by_user_id=vitima.id)
    db_session.add(ws)
    db_session.commit()
    db_session.refresh(ws)

    db_session.add_all([
        WorkspaceMembership(
            workspace_id=ws.id, user_id=vitima.id, role=WorkspaceRole.owner,
            financial_access=FinancialAccess.full_workspace,
        ),
        # O papel é de escrita; o ACESSO é o restrito (ADR 0018)
        WorkspaceMembership(
            workspace_id=ws.id, user_id=bisbilhoteiro.id, role=WorkspaceRole.member,
            financial_access=FinancialAccess.involved_only,
        ),
    ])
    categoria = Category(name="Saude", workspace_id=ws.id)
    db_session.add(categoria)
    db_session.commit()
    db_session.refresh(categoria)

    # 1) Lançamento SÓ da vítima (o bisbilhoteiro não é pagador nem participante)
    tx = Transaction(
        workspace_id=ws.id, title=TITULO_LANCAMENTO,
        total_amount=Decimal(VALOR_LANCAMENTO), currency="BRL",
        transaction_date=datetime(2026, 8, 10, 12, 0, tzinfo=UTC),
        status="paid", created_by_user_id=vitima.id, category_id=categoria.id,
    )
    db_session.add(tx)
    db_session.commit()
    db_session.refresh(tx)
    db_session.add_all([
        TransactionPayer(transaction_id=tx.id, user_id=vitima.id,
                         amount=Decimal(VALOR_LANCAMENTO)),
        TransactionSplit(transaction_id=tx.id, user_id=vitima.id,
                         input_value=Decimal(VALOR_LANCAMENTO),
                         computed_amount=Decimal(VALOR_LANCAMENTO)),
    ])
    # 2) Recursos PESSOAIS da vítima (ADR 0021): renda, cartão, financiamento
    db_session.add_all([
        Income(title=TITULO_RENDA, amount=Decimal(VALOR_RENDA),
               received_at=datetime(2026, 8, 5, 12, 0, tzinfo=UTC), user_id=vitima.id),
        CreditCard(name=NOME_CARTAO, limit=Decimal("5000.00"), closing_day=10,
                   due_day=20, currency="BRL", owner_user_id=vitima.id),
        Financing(title=TITULO_FINANCIAMENTO, total_amount=Decimal(VALOR_FINANCIAMENTO),
                  interest_rate=Decimal("0.01"), installments_count=12,
                  start_date=datetime(2026, 1, 15).date(),
                  method=AmortizationMethod.SAC, currency="BRL",
                  owner_user_id=vitima.id),
    ])
    db_session.commit()

    return {
        "ws": ws, "tx": tx,
        "cookies": {"access_token": create_access_token(data={"sub": str(bisbilhoteiro.id)})},
        "cookies_vitima": {"access_token": create_access_token(data={"sub": str(vitima.id)})},
    }


def _varre(cookies, ws_id, tx_id):
    """Chama toda rota GET preenchível e devolve (chamadas, achados por URL)."""
    substituicoes = {
        "workspace_id": str(ws_id), "transaction_id": str(tx_id),
        "card_id": "1", "financing_id": "1", "account_id": "1", "income_id": "1",
        "statement_id": "1", "installment_number": "1", "category_id": "1",
        "tag_id": "1", "user_id": "1", "settlement_id": "1", "batch_id": "1",
        "attachment_id": "1", "notification_id": "1", "estimate_id": "1",
        "recurring_id": "1", "token": "x", "key": "registration_mode",
        "invite_id": "1", "member_id": "1", "group_id": "1",
    }
    achados, chamadas = [], 0
    for caminho in sorted(set(_rotas_get())):
        url = caminho
        for nome, valor in substituicoes.items():
            url = url.replace("{" + nome + "}", valor)
        if "{" in url:
            continue
        resp = cliente.get(url, cookies=cookies)
        chamadas += 1
        if resp.status_code >= 400:
            continue
        encontrados = [m for m in MARCADORES if m in resp.text]
        if encontrados:
            achados.append(f"{url} (HTTP {resp.status_code}) -> {encontrados}")
    return chamadas, achados


def _rotas_get():
    """Toda rota GET do app, com os parâmetros de caminho preenchíveis."""
    for r in app.routes:
        if isinstance(r, APIRoute) and "GET" in r.methods:
            yield r.path


def test_a_varredura_enxerga_os_marcadores_quando_a_dona_olha(casa):
    """CONTROLE do teste abaixo — sem isto, ele passaria mesmo vazio.

    Se a MESMA varredura, com o cookie da vítima, não achasse marcador nenhum,
    seria porque as rotas não carregam esses dados (ou porque a varredura não
    alcança nada) — e o teste de vazamento não estaria provando coisa alguma.
    """
    chamadas, achados = _varre(casa["cookies_vitima"], casa["ws"].id, casa["tx"].id)
    assert chamadas > 25, f"a varredura chamou só {chamadas} rotas"
    assert achados, (
        "a dona dos dados não encontrou nenhum marcador nas próprias rotas — "
        "a varredura não está medindo nada"
    )


def test_nenhuma_rota_get_vaza_dado_de_quem_nao_me_envolve(casa):
    chamadas, vazou = _varre(casa["cookies"], casa["ws"].id, casa["tx"].id)
    assert chamadas > 25, f"a varredura chamou só {chamadas} rotas — não está medindo"
    assert not vazou, "rotas vazando dado de quem não me envolve: " + "; ".join(vazou)
