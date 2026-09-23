"""Tools de escrita de lançamentos: criar, editar, excluir, restaurar e massa.

O que se prova aqui é o CONTRATO do MCP (nomes → ids, espaço implícito,
idempotência, confirmação, escopo, erros). As regras financeiras em si (centavos,
fatura, parcelas) são as do app e têm a suíte REST como rede; aqui elas aparecem
só para mostrar que a tool chegou ao MESMO comando.
"""
from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import pytest
from sqlmodel import select

from app.models.attachment import Attachment
from app.models.mcp import McpConfirmation, McpOperation
from app.models.transaction import Transaction, TransactionStatus
from app.models.workspace import WorkspaceRole
from app.services.oauth import scopes as escopos
from tests.mcp.conftest import call_tool, err, issue_token, make_space, make_user, ok
from tests.mcp.scenario import categoria, cria_despesa, monta


@pytest.fixture
def c(db_session, mcp_client):
    return monta(db_session, mcp_client)


def chave() -> str:
    return str(uuid4())


def vivos(db) -> list[Transaction]:
    db.expire_all()
    return list(db.exec(select(Transaction).where(Transaction.deleted_at.is_(None))).all())


# --- transactions_create --------------------------------------------------------

def test_cria_despesa_simples_no_espaco_pessoal(mcp_client, db_session, c):
    saida = ok(call_tool(mcp_client, c.token, "transactions_create", {
        "idempotency_key": chave(), "title": "Padaria", "amount": "12.50",
    }))
    tx = saida["transaction"]
    assert tx["space"]["name"] == "Meu espaço"  # ninguém citado → o espaço pessoal
    assert tx["amount"] == "12.50" and tx["my_share"] == "12.50"
    assert tx["date"] == c.hoje.isoformat()
    assert saida["replayed"] is False
    assert len(vivos(db_session)) == 1


def test_cartao_categoria_e_fatura_derivada(mcp_client, db_session, c):
    tx = ok(call_tool(mcp_client, c.token, "transactions_create", {
        "idempotency_key": chave(), "title": "Gasolina", "amount": "89.90",
        "card": "nubank", "category": "transporte",
    }))["transaction"]
    assert tx["card"]["name"] == "Nubank" and tx["payment_method"] == "credit_card"
    assert tx["statement"]["month"]  # fatura derivada no servidor
    assert tx["category"]["name"] == "Transporte"


def test_parcelado_em_10x_soma_o_total(mcp_client, db_session, c):
    saida = ok(call_tool(mcp_client, c.token, "transactions_create", {
        "idempotency_key": chave(), "title": "TV", "amount": "3000.00", "card": "Nubank", "installments": 10,
    }))
    parcelas = saida["installments"]
    assert [p["installment"] for p in parcelas] == [f"{i}/10" for i in range(1, 11)]
    assert sum(Decimal(p["amount"]) for p in parcelas) == Decimal("3000.00")
    assert len(vivos(db_session)) == 10


def test_parcelado_sem_cartao_e_recusado(mcp_client, c):
    erro = err(call_tool(mcp_client, c.token, "transactions_create", {
        "idempotency_key": chave(), "title": "TV", "amount": "3000", "installments": 10,
    }))
    assert erro["code"] == "VALIDATION_ERROR"


def test_metade_do_joao_escolhe_o_espaco_em_comum(mcp_client, c):
    tx = ok(call_tool(mcp_client, c.token, "transactions_create", {
        "idempotency_key": chave(), "title": "Jantar", "amount": "120.01", "split_with": ["João"],
    }))["transaction"]
    assert tx["space"]["name"] == "Casa"
    partes = {p["person"]["name"]: p["amount"] for p in tx["split"]}
    assert partes == {"Alice Souza": "60.01", "João Pereira": "60.00"}  # centavo ao primeiro (ADR 0001)
    assert tx["my_share"] == "60.01"


def test_divisao_desigual_por_valor(mcp_client, c):
    tx = ok(call_tool(mcp_client, c.token, "transactions_create", {
        "idempotency_key": chave(), "title": "Mercado", "amount": "100.00", "space": "Casa",
        "split": [{"person": "eu", "amount": "70.00"}, {"person": "joão", "amount": "30.00"}],
    }))["transaction"]
    assert {p["person"]["name"]: p["amount"] for p in tx["split"]} == {"Alice Souza": "70.00", "João Pereira": "30.00"}


def test_divisao_que_nao_fecha_e_regra_de_negocio(mcp_client, db_session, c):
    erro = err(call_tool(mcp_client, c.token, "transactions_create", {
        "idempotency_key": chave(), "title": "Mercado", "amount": "100.00", "space": "Casa",
        "split": [{"person": "eu", "amount": "70.00"}, {"person": "joão", "amount": "20.00"}],
    }))
    assert erro["code"] == "BUSINESS_RULE_VIOLATION"
    assert vivos(db_session) == []


def test_outra_pessoa_pagou_sem_divisao_pede_divisao(mcp_client, c):
    erro = err(call_tool(mcp_client, c.token, "transactions_create", {
        "idempotency_key": chave(), "title": "Uber", "amount": "30", "paid_by": "João",
    }))
    assert erro["code"] == "VALIDATION_ERROR" and "split_with" in erro["message"]


def test_joao_pagou_e_eu_devo_metade(mcp_client, c):
    tx = ok(call_tool(mcp_client, c.token, "transactions_create", {
        "idempotency_key": chave(), "title": "Uber", "amount": "30.00", "paid_by": "João", "split_with": ["João"],
    }))["transaction"]
    assert tx["payers"][0]["person"]["name"] == "João Pereira"
    assert tx["my_share"] == "15.00"


def test_nome_de_pessoa_desconhecido(mcp_client, c):
    erro = err(call_tool(mcp_client, c.token, "transactions_create", {
        "idempotency_key": chave(), "title": "Cinema", "amount": "40", "split_with": ["Maria"],
    }))
    assert erro["code"] == "NOT_FOUND"


def test_cartao_ambiguo_devolve_candidatos_e_nada_e_criado(mcp_client, db_session, c):
    from app.models.credit_card import CreditCard

    db_session.add(CreditCard(name="Nubank Ultravioleta", limit="1000.00", closing_day=5, due_day=12,
                              owner_user_id=c.alice.id, currency="BRL"))
    db_session.add(CreditCard(name="Nubank PJ", limit="1000.00", closing_day=5, due_day=12,
                              owner_user_id=c.alice.id, currency="BRL"))
    db_session.commit()
    erro = err(call_tool(mcp_client, c.token, "transactions_create", {
        "idempotency_key": chave(), "title": "Café", "amount": "8", "card": "nub",
    }))
    assert erro["code"] == "AMBIGUOUS"
    assert {x["name"] for x in erro["candidates"]} == {"Nubank", "Nubank Ultravioleta", "Nubank PJ"}
    assert vivos(db_session) == []


def test_valor_com_mais_de_duas_casas_nao_e_arredondado(mcp_client, c):
    erro = err(call_tool(mcp_client, c.token, "transactions_create", {
        "idempotency_key": chave(), "title": "X", "amount": "10.999",
    }))
    assert erro["code"] == "VALIDATION_ERROR"


def test_nao_aceita_user_id(mcp_client, c):
    erro = err(call_tool(mcp_client, c.token, "transactions_create", {
        "idempotency_key": chave(), "title": "X", "amount": "10", "user_id": c.bob.id,
    }))
    assert erro["code"] == "VALIDATION_ERROR"


# --- Idempotência -------------------------------------------------------------------

def test_mesma_chave_mesmo_pedido_nao_duplica(mcp_client, db_session, c):
    args = {"idempotency_key": chave(), "title": "Farmácia", "amount": "45.00"}
    primeiro = ok(call_tool(mcp_client, c.token, "transactions_create", args))
    segundo = call_tool(mcp_client, c.token, "transactions_create", args)
    assert ok(segundo)["replayed"] is True
    assert segundo["_meta"]["controle-financeiro/replayed"] is True
    assert ok(segundo)["transaction"]["id"] == primeiro["transaction"]["id"]
    assert len(vivos(db_session)) == 1


def test_mesma_chave_outro_pedido_e_conflito(mcp_client, db_session, c):
    k = chave()
    ok(call_tool(mcp_client, c.token, "transactions_create", {"idempotency_key": k, "title": "A", "amount": "1.00"}))
    erro = err(call_tool(mcp_client, c.token, "transactions_create", {"idempotency_key": k, "title": "A", "amount": "2.00"}))
    assert erro["code"] == "CONFLICT"
    assert len(vivos(db_session)) == 1


def test_duas_compras_iguais_com_chaves_diferentes_sao_duas(mcp_client, db_session, c):
    for _ in range(2):
        ok(call_tool(mcp_client, c.token, "transactions_create", {"idempotency_key": chave(), "title": "Café", "amount": "8.00"}))
    assert len(vivos(db_session)) == 2


def test_falha_libera_a_chave(mcp_client, db_session, c):
    k = chave()
    ruim = {"idempotency_key": k, "title": "Mercado", "amount": "100.00", "space": "Casa",
            "split": [{"person": "eu", "amount": "10.00"}]}
    assert err(call_tool(mcp_client, c.token, "transactions_create", ruim))["code"] == "BUSINESS_RULE_VIOLATION"
    db_session.expire_all()
    assert db_session.exec(select(McpOperation)).all() == []
    bom = {**ruim, "split": [{"person": "eu", "amount": "100.00"}]}
    assert ok(call_tool(mcp_client, c.token, "transactions_create", bom))["replayed"] is False


def test_rollback_total_quando_algo_falha_depois_do_comando(mcp_client, db_session, c, monkeypatch):
    """Falha DEPOIS de o comando gravar (na montagem da saída): nada persiste."""
    from app.mcp.tools import transactions_write

    def explode(*a, **k):
        raise RuntimeError("falha injetada")

    monkeypatch.setattr(transactions_write, "_saida", explode)
    erro = err(call_tool(mcp_client, c.token, "transactions_create", {
        "idempotency_key": chave(), "title": "TV", "amount": "3000", "card": "Nubank", "installments": 10,
    }))
    assert erro["code"] == "INTERNAL_ERROR" and erro["details"]["correlation_id"]
    assert "falha injetada" not in str(erro)
    assert vivos(db_session) == []
    assert db_session.exec(select(McpOperation)).all() == []


# --- Escopo e papel -------------------------------------------------------------------

def test_sem_escopo_de_escrita(mcp_client, db_session, c):
    so_leitura = issue_token(db_session, c.alice, [escopos.FINANCE_READ])
    resultado = call_tool(mcp_client, so_leitura, "transactions_create", {
        "idempotency_key": chave(), "title": "X", "amount": "1",
    })
    erro = err(resultado)
    assert erro["code"] == "PERMISSION_DENIED" and erro["required_scopes"] == ["transactions.write"]
    desafio = resultado["_meta"]["mcp/www_authenticate"][0]
    assert 'error="insufficient_scope"' in desafio and 'scope="transactions.write"' in desafio
    assert vivos(db_session) == []


def test_viewer_nao_escreve(mcp_client, db_session, c):
    visitante = make_user(db_session, "Vera Visitante", "vera@example.com")
    ws = make_space(db_session, c.alice, "Viagem", members=[(visitante, WorkspaceRole.viewer)])
    token = issue_token(db_session, visitante)
    erro = err(call_tool(mcp_client, token, "transactions_create", {
        "idempotency_key": chave(), "title": "Hotel", "amount": "500", "space_id": ws.id,
    }))
    assert erro["code"] == "PERMISSION_DENIED"


def test_espaco_alheio_e_nao_encontrado(mcp_client, db_session, c):
    erro = err(call_tool(mcp_client, c.token, "transactions_create", {
        "idempotency_key": chave(), "title": "X", "amount": "1", "space_id": c.ws_bob.id,
    }))
    assert erro["code"] == "NOT_FOUND"
    assert vivos(db_session) == []


# --- transactions_update -----------------------------------------------------------

def test_troca_categoria_e_devolve_o_anterior(mcp_client, db_session, c):
    criado = cria_despesa(mcp_client, c.alice, c.pessoal, title="iFood", amount="55.00", day=c.hoje,
                          category_id=categoria(db_session, c.pessoal, "Lazer"))
    saida = ok(call_tool(mcp_client, c.token, "transactions_update", {
        "transaction_id": criado["id"], "category": "Alimentação",
    }))
    assert saida["previous"]["category"]["name"] == "Lazer"
    assert saida["transaction"]["category"]["name"] == "Alimentação"
    assert "category" in saida["changed"]


def test_metade_dessa_compra_e_do_joao(mcp_client, db_session, c):
    criado = cria_despesa(mcp_client, c.alice, c.casa, title="Mercado", amount="200.00", day=c.hoje,
                          category_id=categoria(db_session, c.casa, "Alimentação"))
    saida = ok(call_tool(mcp_client, c.token, "transactions_update", {
        "transaction_id": criado["id"], "split_with": ["João"],
    }))
    tx = saida["transaction"]
    assert tx["my_share"] == "100.00" and saida["previous"]["my_share"] == "200.00"
    assert tx["category"]["name"] == "Alimentação"  # a categoria sobrevive à edição da divisão
    assert "split" in saida["changed"]


def test_mudar_valor_de_despesa_dividida_mantem_a_divisao(mcp_client, c):
    criado = cria_despesa(mcp_client, c.alice, c.casa, title="Pizza", amount="80.00", day=c.hoje, split_with=[c.joao])
    tx = ok(call_tool(mcp_client, c.token, "transactions_update", {
        "transaction_id": criado["id"], "amount": "100.00",
    }))["transaction"]
    assert tx["amount"] == "100.00"
    assert {p["amount"] for p in tx["split"]} == {"50.00"}


def test_marcar_como_paga(mcp_client, c):
    criado = cria_despesa(mcp_client, c.alice, c.pessoal, title="Luz", amount="150.00", day=c.hoje)
    saida = ok(call_tool(mcp_client, c.token, "transactions_update", {"transaction_id": criado["id"], "settled": False}))
    assert saida["transaction"]["settled"] is False
    saida = ok(call_tool(mcp_client, c.token, "transactions_update", {"transaction_id": criado["id"], "settled": True}))
    assert saida["transaction"]["settled"] is True and "settled" in saida["changed"]


def test_update_sem_campos(mcp_client, c):
    criado = cria_despesa(mcp_client, c.alice, c.pessoal, title="X", amount="1.00", day=c.hoje)
    assert err(call_tool(mcp_client, c.token, "transactions_update", {"transaction_id": criado["id"]}))["code"] == "VALIDATION_ERROR"


def test_compra_inteira_muda_o_total_e_recalcula_parcelas(mcp_client, c):
    criado = cria_despesa(mcp_client, c.alice, c.pessoal, title="Geladeira", amount="3000.00", day=c.hoje,
                          card=c.nubank, installments=3)
    saida = ok(call_tool(mcp_client, c.token, "transactions_update", {
        "transaction_id": criado["id"], "scope": "purchase", "amount": "2400.00",
    }))
    assert [p["amount"] for p in saida["installments"]] == ["800.00", "800.00", "800.00"]


def test_cancelar_e_definitivo(mcp_client, c):
    criado = cria_despesa(mcp_client, c.alice, c.pessoal, title="Assinatura", amount="30.00", day=c.hoje)
    assert ok(call_tool(mcp_client, c.token, "transactions_update", {
        "transaction_id": criado["id"], "status": "cancelled",
    }))["transaction"]["status"] == "cancelled"
    erro = err(call_tool(mcp_client, c.token, "transactions_update", {"transaction_id": criado["id"], "title": "Y"}))
    assert erro["code"] == "CONFLICT"


def test_editar_lancamento_de_outro_membro_sem_ser_admin(mcp_client, db_session, c):
    doJoao = cria_despesa(mcp_client, c.joao, c.casa, title="Do João", amount="10.00", day=c.hoje, split_with=[c.alice])
    token_joao = issue_token(db_session, c.joao)
    meu = cria_despesa(mcp_client, c.alice, c.casa, title="Da Alice", amount="10.00", day=c.hoje, split_with=[c.joao])
    # João é `member`: não edita o da Alice.
    assert err(call_tool(mcp_client, token_joao, "transactions_update", {"transaction_id": meu["id"], "title": "Hack"}))["code"] == "PERMISSION_DENIED"
    # Alice é dona do espaço: edita o do João (admin+ edita qualquer um).
    assert ok(call_tool(mcp_client, c.token, "transactions_update", {"transaction_id": doJoao["id"], "title": "Corrigido"}))


# --- transactions_delete / restore -------------------------------------------------

def test_exclui_e_restaura(mcp_client, db_session, c):
    criado = cria_despesa(mcp_client, c.alice, c.pessoal, title="McDonald's", amount="42.90", day=c.hoje)
    saida = ok(call_tool(mcp_client, c.token, "transactions_delete", {"transaction_id": criado["id"]}))
    assert [d["id"] for d in saida["deleted"]] == [criado["id"]]
    assert vivos(db_session) == []
    assert ok(call_tool(mcp_client, c.token, "transactions_restore", {"transaction_id": criado["id"]}))["transaction"]["id"] == criado["id"]
    assert len(vivos(db_session)) == 1


def test_excluir_compra_inteira(mcp_client, db_session, c):
    criado = cria_despesa(mcp_client, c.alice, c.pessoal, title="Sofá", amount="900.00", day=c.hoje, card=c.nubank, installments=3)
    saida = ok(call_tool(mcp_client, c.token, "transactions_delete", {"transaction_id": criado["id"], "scope": "purchase"}))
    assert len(saida["deleted"]) == 3
    assert vivos(db_session) == []


def test_excluir_com_anexo_exige_previa(mcp_client, db_session, c):
    criado = cria_despesa(mcp_client, c.alice, c.pessoal, title="Consulta", amount="300.00", day=c.hoje)
    db_session.add(Attachment(transaction_id=criado["id"], workspace_id=c.pessoal.id, filename="recibo.pdf",
                              content_type="application/pdf", size_bytes=10, storage_key="k/recibo",
                              uploaded_by_user_id=c.alice.id))
    db_session.commit()
    erro = err(call_tool(mcp_client, c.token, "transactions_delete", {"transaction_id": criado["id"]}))
    assert erro["code"] == "BUSINESS_RULE_VIOLATION" and erro["details"]["attachments"] == 1
    assert len(vivos(db_session)) == 1


def test_excluir_despesa_paga_e_conflito(mcp_client, db_session, c):
    criado = cria_despesa(mcp_client, c.alice, c.pessoal, title="Aluguel", amount="1500.00", day=c.hoje)
    tx = db_session.get(Transaction, criado["id"])
    tx.status = TransactionStatus.paid
    db_session.add(tx)
    db_session.commit()
    assert err(call_tool(mcp_client, c.token, "transactions_delete", {"transaction_id": criado["id"]}))["code"] == "CONFLICT"


# --- Massa ---------------------------------------------------------------------------

def test_previa_e_exclusao_em_massa(mcp_client, db_session, c):
    for i in range(3):
        cria_despesa(mcp_client, c.alice, c.pessoal, title="McDonald's", amount="30.00", day=c.hoje)
    cria_despesa(mcp_client, c.alice, c.pessoal, title="Padaria", amount="5.00", day=c.hoje)
    previa = ok(call_tool(mcp_client, c.token, "transactions_bulk_preview", {
        "action": "delete", "filters": {"text": "mcdonald"},
    }))
    assert previa["count"] == 3 and previa["totals"] == [{"currency": "BRL", "amount": "90.00", "count": 3}]
    token = previa["confirmation_token"]
    assert token.startswith("cfm_cf_")
    # O token não fica em claro no banco.
    assert db_session.exec(select(McpConfirmation)).one().token_hash != token

    feito = ok(call_tool(mcp_client, c.token, "transactions_bulk_delete", {"confirmation_token": token}))
    assert feito["count"] == 3 and feito["replayed"] is False
    assert [t.title for t in vivos(db_session)] == ["Padaria"]
    # Retry com o mesmo token: devolve o mesmo resultado, não exclui de novo.
    de_novo = ok(call_tool(mcp_client, c.token, "transactions_bulk_delete", {"confirmation_token": token}))
    assert de_novo["replayed"] is True and de_novo["count"] == 3


def test_previa_nao_aceita_filtro_vazio(mcp_client, c):
    assert err(call_tool(mcp_client, c.token, "transactions_bulk_preview", {"action": "delete", "filters": {}}))["code"] == "VALIDATION_ERROR"


def test_conjunto_mudou_nada_e_excluido(mcp_client, db_session, c):
    a = cria_despesa(mcp_client, c.alice, c.pessoal, title="Lanche", amount="10.00", day=c.hoje)
    cria_despesa(mcp_client, c.alice, c.pessoal, title="Lanche", amount="12.00", day=c.hoje)
    token = ok(call_tool(mcp_client, c.token, "transactions_bulk_preview", {
        "action": "delete", "filters": {"text": "lanche"},
    }))["confirmation_token"]
    tx = db_session.get(Transaction, a["id"])
    tx.status = TransactionStatus.paid
    db_session.add(tx)
    db_session.commit()
    assert err(call_tool(mcp_client, c.token, "transactions_bulk_delete", {"confirmation_token": token}))["code"] == "CONFLICT"
    assert len(vivos(db_session)) == 2


def test_token_de_outra_pessoa_nao_serve(mcp_client, db_session, c):
    cria_despesa(mcp_client, c.alice, c.pessoal, title="Lanche", amount="10.00", day=c.hoje)
    token = ok(call_tool(mcp_client, c.token, "transactions_bulk_preview", {
        "action": "delete", "transaction_ids": [vivos(db_session)[0].id],
    }))["confirmation_token"]
    assert err(call_tool(mcp_client, c.token_bob, "transactions_bulk_delete", {"confirmation_token": token}))["code"] == "VALIDATION_ERROR"
    # Outra CONEXÃO da mesma pessoa também não (o token é amarrado à concessão).
    outra = issue_token(db_session, c.alice)
    assert err(call_tool(mcp_client, outra, "transactions_bulk_delete", {"confirmation_token": token}))["code"] == "VALIDATION_ERROR"
    assert len(vivos(db_session)) == 1


def test_token_de_exclusao_nao_categoriza(mcp_client, db_session, c):
    cria_despesa(mcp_client, c.alice, c.pessoal, title="Lanche", amount="10.00", day=c.hoje)
    token = ok(call_tool(mcp_client, c.token, "transactions_bulk_preview", {
        "action": "delete", "filters": {"text": "lanche"},
    }))["confirmation_token"]
    assert err(call_tool(mcp_client, c.token, "transactions_bulk_categorize", {"confirmation_token": token}))["code"] == "VALIDATION_ERROR"


def test_previa_com_ids_alheios_nao_os_alcanca(mcp_client, db_session, c):
    do_bob = cria_despesa(mcp_client, c.bob, c.ws_bob, title="Segredo do Bob", amount="99.00", day=c.hoje)
    previa = ok(call_tool(mcp_client, c.token, "transactions_bulk_preview", {
        "action": "delete", "transaction_ids": [do_bob["id"]],
    }))
    assert previa["count"] == 0 and previa["confirmation_token"] is None
    assert previa["not_found_ids"] == [do_bob["id"]]
    assert "Segredo" not in str(previa)


def test_categorizar_em_massa(mcp_client, db_session, c):
    for titulo in ("Mercado A", "Mercado B"):
        cria_despesa(mcp_client, c.alice, c.pessoal, title=titulo, amount="50.00", day=c.hoje)
    cria_despesa(mcp_client, c.alice, c.pessoal, title="Mercado C", amount="50.00", day=c.hoje,
                 category_id=categoria(db_session, c.pessoal, "Lazer"))
    previa = ok(call_tool(mcp_client, c.token, "transactions_bulk_preview", {
        "action": "categorize", "filters": {"text": "mercado", "space": "Meu espaço"}, "category": "Alimentação",
    }))
    assert previa["count"] == 2 and previa["ineligible_count"] == 1
    assert previa["category"]["name"] == "Alimentação"
    feito = ok(call_tool(mcp_client, c.token, "transactions_bulk_categorize", {"confirmation_token": previa["confirmation_token"]}))
    assert feito["count"] == 2
    busca = ok(call_tool(mcp_client, c.token, "transactions_search", {"category": "Alimentação"}))
    assert {i["title"] for i in busca["items"]} == {"Mercado A", "Mercado B"}


def test_previa_acima_do_teto(mcp_client, c, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "MCP_BULK_MAX_ITEMS", 2)
    for i in range(3):
        cria_despesa(mcp_client, c.alice, c.pessoal, title="Café", amount="5.00", day=c.hoje)
    erro = err(call_tool(mcp_client, c.token, "transactions_bulk_preview", {"action": "delete", "filters": {"text": "café"}}))
    assert erro["code"] == "VALIDATION_ERROR" and erro["details"]["max_items"] == 2


def test_alvo_excluido_depois_da_previa_e_conflito(mcp_client, db_session, c):
    a = cria_despesa(mcp_client, c.alice, c.pessoal, title="Lanche", amount="10.00", day=c.hoje)
    cria_despesa(mcp_client, c.alice, c.pessoal, title="Lanche", amount="12.00", day=c.hoje)
    token = ok(call_tool(mcp_client, c.token, "transactions_bulk_preview", {
        "action": "delete", "filters": {"text": "lanche"},
    }))["confirmation_token"]
    ok(call_tool(mcp_client, c.token, "transactions_delete", {"transaction_id": a["id"]}))
    erro = err(call_tool(mcp_client, c.token, "transactions_bulk_delete", {"confirmation_token": token}))
    assert erro["code"] == "CONFLICT" and "nova prévia" in erro["message"]
    assert [t.total_amount for t in vivos(db_session)] == [Decimal("12.00")]


def test_trocar_a_moeda_reconverte_o_valor(mcp_client, db_session, c, monkeypatch):
    """"Aquilo foi 50 dólares, não 50 reais": a moeda nova tem de CONVERTER o valor.

    O caminho parcial do comando grava `currency` sem conversão (o SPA sempre
    manda a edição completa quando mexe na moeda); a tool precisa ir pelo mesmo
    caminho completo, senão o lançamento ficaria "USD 50" com o valor de R$ 50.
    """
    from app.services.currency_service import CurrencyService

    monkeypatch.setattr(CurrencyService, "get_rate_sync", lambda *a, **k: (Decimal("5.00"), "ptax"))
    criado = cria_despesa(mcp_client, c.alice, c.pessoal, title="Loja online", amount="50.00", day=c.hoje)
    tx = ok(call_tool(mcp_client, c.token, "transactions_update", {
        "transaction_id": criado["id"], "currency": "USD",
    }))["transaction"]
    assert tx["currency"] == "BRL" and tx["amount"] == "250.00"
    assert tx["foreign"]["original_currency"] == "USD" and tx["foreign"]["original_amount"] == "50.00"
    assert tx["my_share"] == "250.00"


def test_trocar_a_moeda_no_cartao_aplica_o_iof(mcp_client, db_session, c, monkeypatch):
    """No cartão a conversão leva IOF, igual à edição feita pelo app."""
    from app.services.currency_service import CurrencyService

    monkeypatch.setattr(CurrencyService, "get_rate_sync", lambda *a, **k: (Decimal("5.00"), "ptax"))
    criado = cria_despesa(mcp_client, c.alice, c.pessoal, title="Assinatura", amount="50.00", day=c.hoje, card=c.nubank)
    tx = ok(call_tool(mcp_client, c.token, "transactions_update", {
        "transaction_id": criado["id"], "currency": "usd",
    }))["transaction"]
    assert tx["foreign"]["original_currency"] == "USD" and tx["foreign"]["iof_rate"] is not None
    iof = Decimal(tx["foreign"]["iof_rate"])
    assert iof > 0
    assert Decimal(tx["amount"]) == (Decimal("250.00") * (1 + iof)).quantize(Decimal("0.01"))
    assert tx["card"]["name"] == "Nubank"


def test_repetir_a_moeda_original_nao_muda_nada(mcp_client, db_session, c, monkeypatch):
    """Já convertido de USD: "currency": "USD" junto com outra mudança não é recusado nem reconverte."""
    from app.services.currency_service import CurrencyService

    monkeypatch.setattr(CurrencyService, "get_rate_sync", lambda *a, **k: (Decimal("5.00"), "ptax"))
    criado = cria_despesa(mcp_client, c.alice, c.pessoal, title="Loja online", amount="50.00", day=c.hoje)
    ok(call_tool(mcp_client, c.token, "transactions_update", {"transaction_id": criado["id"], "currency": "USD"}))
    tx = ok(call_tool(mcp_client, c.token, "transactions_update", {
        "transaction_id": criado["id"], "currency": "USD", "title": "Loja online (EUA)",
    }))["transaction"]
    assert tx["title"] == "Loja online (EUA)"
    assert tx["currency"] == "BRL" and tx["amount"] == "250.00"
    assert tx["foreign"]["original_amount"] == "50.00"


def test_trocar_a_moeda_da_compra_parcelada_reconverte_todas_as_parcelas(mcp_client, db_session, c, monkeypatch):
    """`scope=purchase` vai pela edição do grupo do app, que converte o total e reparte nas parcelas."""
    from app.services.currency_service import CurrencyService

    monkeypatch.setattr(CurrencyService, "get_rate_sync", lambda *a, **k: (Decimal("5.00"), "ptax"))
    criado = cria_despesa(mcp_client, c.alice, c.pessoal, title="Curso", amount="300.00", day=c.hoje,
                          card=c.nubank, installments=3)
    res = ok(call_tool(mcp_client, c.token, "transactions_update", {
        "transaction_id": criado["id"], "scope": "purchase", "currency": "USD",
    }))
    parcelas = res["installments"]
    assert len(parcelas) == 3
    iof = Decimal(res["transaction"]["foreign"]["iof_rate"])
    total = sum(Decimal(p["amount"]) for p in parcelas)
    assert total == (Decimal("1500.00") * (1 + iof)).quantize(Decimal("0.01"))
    assert {p["currency"] for p in parcelas} == {"BRL"}


# --- Compra já convertida: tudo que mexe na conversão reconverte ----------------
#
# O caminho parcial do comando não converte (o SPA sempre manda a edição completa
# numa compra estrangeira). Por ele, `amount: 60` numa compra de US$ 50 virava
# R$ 60 e apagava o original; a data nova mantinha a cotação velha; e o cartão
# novo não cobrava IOF.

def _compra_em_dolar(mcp_client, c, monkeypatch, taxa="5.00", **extra) -> int:
    from app.services.currency_service import CurrencyService

    monkeypatch.setattr(CurrencyService, "get_rate_sync", lambda *a, **k: (Decimal(taxa), "ptax"))
    tx = ok(call_tool(mcp_client, c.token, "transactions_create", {
        "idempotency_key": chave(), "title": "Loja", "amount": "50.00", "currency": "USD",
        "space": "Meu espaço", "payment_method": "pix", **extra,
    }))["transaction"]
    assert tx["amount"] == "250.00" and tx["foreign"]["original_amount"] == "50.00"
    return tx["id"]


def test_valor_novo_de_compra_convertida_e_na_moeda_original(mcp_client, db_session, c, monkeypatch):
    tid = _compra_em_dolar(mcp_client, c, monkeypatch)
    res = ok(call_tool(mcp_client, c.token, "transactions_update", {"transaction_id": tid, "amount": "60.00"}))
    tx = res["transaction"]
    assert tx["foreign"]["original_currency"] == "USD" and tx["foreign"]["original_amount"] == "60.00"
    assert tx["amount"] == "300.00" and tx["my_share"] == "300.00"
    assert res["previous"]["amount"] == "250.00"


def test_data_nova_de_compra_convertida_usa_a_cotacao_do_dia(mcp_client, db_session, c, monkeypatch):
    from app.services.currency_service import CurrencyService

    tid = _compra_em_dolar(mcp_client, c, monkeypatch)
    monkeypatch.setattr(CurrencyService, "get_rate_sync", lambda *a, **k: (Decimal("6.00"), "ptax"))
    tx = ok(call_tool(mcp_client, c.token, "transactions_update", {
        "transaction_id": tid, "date": c.hoje.replace(day=1).isoformat(),
    }))["transaction"]
    assert tx["amount"] == "300.00" and tx["foreign"]["exchange_rate"].startswith("6.00")
    assert tx["foreign"]["original_amount"] == "50.00"


def test_compra_convertida_que_vai_para_o_cartao_passa_a_ter_iof(mcp_client, db_session, c, monkeypatch):
    tid = _compra_em_dolar(mcp_client, c, monkeypatch)
    tx = ok(call_tool(mcp_client, c.token, "transactions_update", {"transaction_id": tid, "card": "Nubank"}))["transaction"]
    iof = Decimal(tx["foreign"]["iof_rate"])
    assert iof > 0 and tx["card"]["name"] == "Nubank" and tx["payment_method"] == "credit_card"
    assert Decimal(tx["amount"]) == (Decimal("250.00") * (1 + iof)).quantize(Decimal("0.01"))


def test_compra_convertida_volta_para_a_moeda_base_mantendo_o_numero(mcp_client, db_session, c, monkeypatch):
    tid = _compra_em_dolar(mcp_client, c, monkeypatch)
    tx = ok(call_tool(mcp_client, c.token, "transactions_update", {"transaction_id": tid, "currency": "BRL"}))["transaction"]
    assert tx["currency"] == "BRL" and tx["amount"] == "50.00" and tx["foreign"] is None


def test_so_o_titulo_de_compra_convertida_preserva_a_conversao(mcp_client, db_session, c, monkeypatch):
    from app.services.currency_service import CurrencyService

    tid = _compra_em_dolar(mcp_client, c, monkeypatch)
    monkeypatch.setattr(CurrencyService, "get_rate_sync", lambda *a, **k: (Decimal("9.99"), "ptax"))
    tx = ok(call_tool(mcp_client, c.token, "transactions_update", {"transaction_id": tid, "title": "Loja (EUA)"}))["transaction"]
    assert tx["amount"] == "250.00" and tx["foreign"]["exchange_rate"].startswith("5.00")


def test_compra_convertida_com_divisao_fixa_pede_a_divisao_nova(mcp_client, db_session, c, monkeypatch):
    """Os valores fixos gravados estão na moeda-base; refazer a conversão exige a divisão de novo."""
    from app.services.currency_service import CurrencyService

    monkeypatch.setattr(CurrencyService, "get_rate_sync", lambda *a, **k: (Decimal("5.00"), "ptax"))
    tx = ok(call_tool(mcp_client, c.token, "transactions_create", {
        "idempotency_key": chave(), "title": "Jantar", "amount": "50.00", "currency": "USD", "space": "Casa",
        "payment_method": "pix", "split": [{"person": "Alice", "amount": "30.00"}, {"person": "João", "amount": "20.00"}],
    }))["transaction"]
    erro = err(call_tool(mcp_client, c.token, "transactions_update", {"transaction_id": tx["id"], "date": c.hoje.isoformat()}))
    assert erro["code"] == "VALIDATION_ERROR" and "`split`" in erro["message"]
    refeito = ok(call_tool(mcp_client, c.token, "transactions_update", {
        "transaction_id": tx["id"], "date": c.hoje.isoformat(),
        "split": [{"person": "Alice", "amount": "25.00"}, {"person": "João", "amount": "25.00"}],
    }))["transaction"]
    assert refeito["amount"] == "250.00" and {p["amount"] for p in refeito["split"]} == {"125.00"}


def test_trocar_a_conta_mantem_a_divisao_fixa_quando_o_total_nao_muda(mcp_client, db_session, c):
    tx = ok(call_tool(mcp_client, c.token, "transactions_create", {
        "idempotency_key": chave(), "title": "Mercado", "amount": "100.00", "space": "Casa", "payment_method": "pix",
        "split": [{"person": "Alice", "amount": "70.00"}, {"person": "João", "amount": "30.00"}],
    }))["transaction"]
    novo = ok(call_tool(mcp_client, c.token, "transactions_update", {"transaction_id": tx["id"], "account": "Itaú"}))["transaction"]
    from app.models.transaction import TransactionPayer

    pagador = db_session.exec(select(TransactionPayer).where(TransactionPayer.transaction_id == tx["id"])).one()
    assert pagador.account_id == c.conta.id
    assert sorted(p["amount"] for p in novo["split"]) == ["30.00", "70.00"]


def test_sair_do_cartao_mudando_o_valor_de_despesa_dividida(mcp_client, db_session, c):
    """O pagador guardava `credit_card` e o lançamento ficava sem cartão: o app recusava (400)."""
    from tests.mcp.conftest import cookie_headers

    r = mcp_client.post(f"/api/v1/workspaces/{c.casa.id}/transactions/", headers=cookie_headers(c.alice), json={
        "title": "Pizza", "total_amount": "80.00", "transaction_date": f"{c.hoje.isoformat()}T15:00:00Z",
        "credit_card_id": c.nubank.id, "split_mode": "transaction",
        "payers": [{"user_id": c.alice.id, "amount": "80.00", "payment_method": "credit_card"}],
        "splits": [{"user_id": u.id, "split_method": "equal", "input_value": "0"} for u in (c.alice, c.joao)],
    })
    assert r.status_code == 200, r.text
    criado = r.json()
    tx = ok(call_tool(mcp_client, c.token, "transactions_update", {
        "transaction_id": criado["id"], "amount": "90.00", "payment_method": "pix",
    }))["transaction"]
    assert tx["card"] is None and tx["payment_method"] == "pix" and tx["amount"] == "90.00"
    assert {p["amount"] for p in tx["split"]} == {"45.00"}
