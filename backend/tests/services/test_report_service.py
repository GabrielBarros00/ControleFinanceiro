from sqlmodel import Session
from datetime import date, datetime
from decimal import Decimal
from app.models.transaction import (
    Transaction,
    TransactionItem,
    TransactionPayer,
    TransactionSplit,
    SplitMethod,
)
from app.models.category import Category
from app.models.user import User
from app.services.report_service import ReportService

def test_get_summary_with_data(db_session: Session, seed_ws):
    workspace_id = seed_ws["ws"].id
    user = seed_ws["user"]
    target_month = date(2026, 5, 1)

    # Setup: Categorias do workspace
    cat_a = Category(workspace_id=workspace_id, name="Mercado")
    cat_b = Category(workspace_id=workspace_id, name="Transporte")
    db_session.add_all([cat_a, cat_b])
    db_session.commit()
    db_session.refresh(cat_a)
    db_session.refresh(cat_b)

    # Setup: Expenses
    t1 = Transaction(title="T1", total_amount=Decimal("100.00"), transaction_date=datetime(2026, 5, 1), workspace_id=workspace_id, created_by_user_id=user.id)
    db_session.add(t1)
    db_session.flush()

    item1 = TransactionItem(transaction_id=t1.id, category_id=cat_a.id, amount=Decimal("60.00"), description="Item 1", title="Item 1")
    item2 = TransactionItem(transaction_id=t1.id, category_id=cat_b.id, amount=Decimal("40.00"), description="Item 2", title="Item 2")
    db_session.add_all([item1, item2])
    
    db_session.commit()

    # Act
    summary = ReportService.get_summary(db_session, workspace_id, target_month)

    # Assert — só gasto: renda saiu do resumo do workspace (ADR 0021)
    assert summary["total_expenses"] == 100.0
    assert len(summary["categories"]) == 2
    # Nomes de categoria resolvidos a partir da tabela Category
    cats = sorted(summary["categories"], key=lambda x: x["name"])
    assert cats[0]["name"] == "Mercado"
    assert cats[0]["value"] == 60.0
    assert cats[1]["name"] == "Transporte"
    assert cats[1]["value"] == 40.0

def test_get_summary_empty(db_session: Session):
    workspace_id = 1
    target_month = date(2026, 5, 1)
    
    summary = ReportService.get_summary(db_session, workspace_id, target_month)

    assert summary["total_expenses"] == 0.0
    assert summary["categories"] == []

def test_get_summary_excludes_and_counts_foreign_currency(db_session: Session, seed_ws):
    """E5/F-04: lançamento em moeda != base fica FORA dos totais, mas é contado."""
    workspace_id = seed_ws["ws"].id
    user = seed_ws["user"]
    target_month = date(2026, 5, 1)

    brl = Transaction(
        title="BRL", total_amount=Decimal("100.00"), transaction_date=datetime(2026, 5, 2),
        workspace_id=workspace_id, created_by_user_id=user.id, currency="BRL",
    )
    usd = Transaction(
        title="USD", total_amount=Decimal("50.00"), transaction_date=datetime(2026, 5, 3),
        workspace_id=workspace_id, created_by_user_id=user.id, currency="USD",
    )
    db_session.add_all([brl, usd])
    db_session.commit()

    summary = ReportService.get_summary(db_session, workspace_id, target_month)
    assert summary["total_expenses"] == Decimal("100.00")   # USD não somado
    assert summary["base_currency"] == "BRL"
    assert summary["excluded_foreign_count"] == 1


def test_get_last_6_months(db_session: Session):
    workspace_id = 1
    # Just verify it doesn't crash and returns 6 items
    results = ReportService.get_last_6_months(db_session, workspace_id)
    assert len(results) == 6
    for item in results:
        assert "name" in item
        assert "expenses" in item
        assert "my_expenses" in item
        # A barra de RECEITA saiu do histórico do workspace junto com a renda:
        # ela era a versão gráfica do mesmo erro do `my_net` (ADR 0021).
        assert "income" not in item


def test_get_last_6_months_ancorado_no_mes_pedido(db_session: Session, seed_ws):
    """A série termina no mês pedido — sem isso os Relatórios ficavam presos no
    mês corrente e não dava para olhar o passado."""
    workspace_id = seed_ws["ws"].id
    user = seed_ws["user"]
    db_session.add(Transaction(
        title="Antiga", total_amount=Decimal("80.00"),
        transaction_date=datetime(2026, 3, 10),
        workspace_id=workspace_id, created_by_user_id=user.id,
    ))
    db_session.commit()

    results = ReportService.get_last_6_months(db_session, workspace_id, ref_month=date(2026, 5, 1))

    assert len(results) == 6
    # `month` é o rótulo autoritativo (o frontend formata em PT-BR a partir dele);
    # `name` vem de strftime e depende do locale do processo — não serve de âncora.
    assert [r["month"] for r in results] == [
        "2025-12", "2026-01", "2026-02", "2026-03", "2026-04", "2026-05",
    ]
    assert results[3]["expenses"] == Decimal("80.00")  # março
    assert results[-1]["expenses"] == Decimal("0.00")  # maio


def test_historico_e_resumo_concordam_no_gasto(db_session: Session, seed_ws):
    """Resumo e histórico alimentam a MESMA tela e têm de contar a mesma coisa.

    A versão anterior comparava a RENDA nos dois: `get_summary` filtrava a moeda,
    `get_last_6_months` não, e o card "Receita" divergia da barra do mesmo mês.
    Renda saiu dos dois (ADR 0021); a invariante de concordância continua valendo
    para o gasto, que é o que o workspace mede.
    """
    workspace_id = seed_ws["ws"].id
    user = seed_ws["user"]
    db_session.add_all([
        Transaction(
            title="BRL", total_amount=Decimal("100.00"), currency="BRL",
            transaction_date=datetime(2026, 5, 5), billing_month="2026-05",
            workspace_id=workspace_id, created_by_user_id=user.id,
        ),
        Transaction(
            title="USD", total_amount=Decimal("900.00"), currency="USD",
            transaction_date=datetime(2026, 5, 6), billing_month="2026-05",
            workspace_id=workspace_id, created_by_user_id=user.id,
        ),
    ])
    db_session.commit()

    resumo = ReportService.get_summary(db_session, workspace_id, date(2026, 5, 1))
    historico = ReportService.get_last_6_months(db_session, workspace_id, ref_month=date(2026, 5, 1))
    maio = next(r for r in historico if r["month"] == "2026-05")

    assert resumo["total_expenses"] == Decimal("100.00")
    assert maio["expenses"] == resumo["total_expenses"]


def test_summary_leva_o_id_da_categoria(db_session: Session, seed_ws):
    """O orçamento casa meta × gasto por id: renomear a categoria não pode zerar
    o consumo (BUD-001)."""
    workspace_id = seed_ws["ws"].id
    user = seed_ws["user"]
    cat = Category(workspace_id=workspace_id, name="Mercado")
    db_session.add(cat)
    db_session.commit()
    db_session.refresh(cat)

    tx = Transaction(
        title="Compra", total_amount=Decimal("100.00"),
        transaction_date=datetime(2026, 5, 4),
        workspace_id=workspace_id, created_by_user_id=user.id,
    )
    db_session.add(tx)
    db_session.flush()
    db_session.add(TransactionItem(
        transaction_id=tx.id, category_id=cat.id, amount=Decimal("70.00"),
        title="Item", description="Item",
    ))
    db_session.commit()

    cats = ReportService.get_summary(db_session, workspace_id, date(2026, 5, 1))["categories"]
    por_nome = {c["name"]: c for c in cats}
    assert por_nome["Mercado"]["category_id"] == cat.id
    # O resto (100 − 70) vira "Sem categoria", que por definição não tem id
    assert por_nome["Sem categoria"]["category_id"] is None


def test_get_summary_my_share(db_session: Session, seed_ws):
    """A 'minha parte' vem dos splits do usuário, não do valor cheio (issue 2)."""
    workspace_id = seed_ws["ws"].id
    user = seed_ws["user"]
    u2 = User(name="Outro", email="outro-share@test.com", password_hash="h")
    db_session.add(u2)
    db_session.commit()
    db_session.refresh(u2)
    target_month = date(2026, 5, 1)

    # Despesa de 300 dividida 50/50; user pagou tudo
    tx = Transaction(
        title="Geladeira", total_amount=Decimal("300.00"),
        transaction_date=datetime(2026, 5, 10), workspace_id=workspace_id,
        created_by_user_id=user.id,
    )
    db_session.add(tx)
    db_session.flush()
    db_session.add(TransactionPayer(transaction_id=tx.id, user_id=user.id, amount=Decimal("300.00")))
    db_session.add(TransactionSplit(
        transaction_id=tx.id, user_id=user.id, split_method=SplitMethod.fixed,
        input_value=Decimal("150.00"), computed_amount=Decimal("150.00"),
    ))
    db_session.add(TransactionSplit(
        transaction_id=tx.id, user_id=u2.id, split_method=SplitMethod.fixed,
        input_value=Decimal("150.00"), computed_amount=Decimal("150.00"),
    ))
    db_session.commit()

    s_user = ReportService.get_summary(db_session, workspace_id, target_month, user_id=user.id)
    assert s_user["total_expenses"] == Decimal("300.00")   # visão da casa
    assert s_user["my_expenses"] == Decimal("150.00")      # só a minha parte
    # Pagou os 300 e consumiu 150 → tem 150 a receber. É o par que faltava.
    assert s_user["paid_by_me"] == Decimal("300.00")
    assert s_user["my_balance"] == Decimal("150.00")

    s_u2 = ReportService.get_summary(db_session, workspace_id, target_month, user_id=u2.id)
    assert s_u2["my_expenses"] == Decimal("150.00")
    assert s_u2["paid_by_me"] == Decimal("0.00")
    assert s_u2["my_balance"] == Decimal("-150.00")

    # Sem user_id: campos do recorte zerados (visão só da casa)
    s_none = ReportService.get_summary(db_session, workspace_id, target_month)
    assert s_none["my_expenses"] == Decimal("0.00")
    assert s_none["paid_by_me"] == Decimal("0.00")
