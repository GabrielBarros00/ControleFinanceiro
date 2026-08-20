from decimal import Decimal
from datetime import datetime
from sqlmodel import Session
from app.models.transaction import (
    Transaction,
    TransactionPayer,
    TransactionSplit,
    SplitMethod,
    TransactionStatus,
)
from app.models.workspace import Workspace
from app.models.user import User
from app.models.settlement import Settlement
from app.services.debt_service import DebtService

def test_calculate_net_debts_simple(db_session: Session):
    # Setup: Gabriel e João num Workspace
    u1 = User(name="Gabriel", email="g@test.com", password_hash="h")
    u2 = User(name="Joao", email="j@test.com", password_hash="h")
    ws = Workspace(name="WS")
    db_session.add_all([u1, u2, ws])
    db_session.flush()

    # Transação: Gabriel pagou R$ 100,00. Split 50/50.
    # Resultado esperado: João deve R$ 50,00 para Gabriel.
    tx = Transaction(title="Jantar", total_amount=Decimal("100.00"), workspace_id=ws.id)
    db_session.add(tx)
    db_session.flush()

    p1 = TransactionPayer(transaction_id=tx.id, user_id=u1.id, amount=Decimal("100.00"))
    s1 = TransactionSplit(transaction_id=tx.id, user_id=u1.id, split_method=SplitMethod.fixed, input_value=Decimal("50.00"), computed_amount=Decimal("50.00"))
    s2 = TransactionSplit(transaction_id=tx.id, user_id=u2.id, split_method=SplitMethod.fixed, input_value=Decimal("50.00"), computed_amount=Decimal("50.00"))
    
    db_session.add_all([p1, s1, s2])
    db_session.commit()

    # Act
    debts = DebtService.get_workspace_debts(db_session, ws.id)

    # Assert
    # O formato esperado é uma lista de devedores e quanto devem para quem
    # Joao -> Gabriel: 50.00
    assert len(debts) == 1
    debt = debts[0]
    assert debt["debtor_id"] == u2.id
    assert debt["creditor_id"] == u1.id
    assert debt["amount"] == Decimal("50.00")

def test_calculate_net_debts_complex(db_session: Session):
    # Cenário: Gabriel paga R$ 100 (50/50). João paga R$ 40 (50/50).
    # Gabriel deve 20 p/ João. João deve 50 p/ Gabriel.
    # Resultado Líquido: João deve 30 p/ Gabriel.
    u1 = User(name="Gabriel", email="g2@test.com", password_hash="h")
    u2 = User(name="Joao", email="j2@test.com", password_hash="h")
    ws = Workspace(name="WS2")
    db_session.add_all([u1, u2, ws])
    db_session.flush()

    # TX 1 (Gabriel pagou 100)
    tx1 = Transaction(title="TX1", total_amount=Decimal("100.00"), workspace_id=ws.id)
    db_session.add(tx1)
    db_session.flush()
    db_session.add(TransactionPayer(transaction_id=tx1.id, user_id=u1.id, amount=Decimal("100.00")))
    db_session.add(TransactionSplit(transaction_id=tx1.id, user_id=u1.id, computed_amount=Decimal("50.00"), input_value=Decimal("50"), split_method="fixed"))
    db_session.add(TransactionSplit(transaction_id=tx1.id, user_id=u2.id, computed_amount=Decimal("50.00"), input_value=Decimal("50"), split_method="fixed"))

    # TX 2 (João pagou 40)
    tx2 = Transaction(title="TX2", total_amount=Decimal("40.00"), workspace_id=ws.id)
    db_session.add(tx2)
    db_session.flush()
    db_session.add(TransactionPayer(transaction_id=tx2.id, user_id=u2.id, amount=Decimal("40.00")))
    db_session.add(TransactionSplit(transaction_id=tx2.id, user_id=u1.id, computed_amount=Decimal("20.00"), input_value=Decimal("20"), split_method="fixed"))
    db_session.add(TransactionSplit(transaction_id=tx2.id, user_id=u2.id, computed_amount=Decimal("20.00"), input_value=Decimal("20"), split_method="fixed"))
    
    db_session.commit()

    debts = DebtService.get_workspace_debts(db_session, ws.id)

    # João deve 30 para Gabriel
    assert len(debts) == 1
    assert debts[0]["debtor_id"] == u2.id
    assert debts[0]["creditor_id"] == u1.id
    assert debts[0]["amount"] == Decimal("30.00")


def _make_installment(db_session, ws_id, u1, u2, i, billing_month, status=TransactionStatus.confirmed):
    """Uma parcela i/3 de R$100 dividida 50/50, u1 paga tudo, no seu billing_month."""
    tx = Transaction(
        title=f"Geladeira ({i}/3)", total_amount=Decimal("100.00"),
        workspace_id=ws_id, billing_month=billing_month, status=status,
        installment_no=i, installments_of=3,
        transaction_date=datetime(2026, i, 10),
    )
    db_session.add(tx)
    db_session.flush()
    db_session.add(TransactionPayer(transaction_id=tx.id, user_id=u1.id, amount=Decimal("100.00")))
    db_session.add(TransactionSplit(transaction_id=tx.id, user_id=u1.id, split_method=SplitMethod.fixed, input_value=Decimal("50.00"), computed_amount=Decimal("50.00")))
    db_session.add(TransactionSplit(transaction_id=tx.id, user_id=u2.id, split_method=SplitMethod.fixed, input_value=Decimal("50.00"), computed_amount=Decimal("50.00")))
    return tx


def test_monthly_ledger_installments_per_month(db_session: Session):
    """Parcela 3x aparece SÓ no mês dela — é a 'dívida por mês' (issue 1)."""
    u1 = User(name="Gabriel", email="g3@test.com", password_hash="h")
    u2 = User(name="Joao", email="j3@test.com", password_hash="h")
    ws = Workspace(name="WS3")
    db_session.add_all([u1, u2, ws])
    db_session.flush()

    for i, bm in enumerate(["2026-01", "2026-02", "2026-03"], start=1):
        _make_installment(db_session, ws.id, u1, u2, i, bm)
    db_session.commit()

    jan = DebtService.get_monthly_ledger(db_session, ws.id, "2026-01")
    assert len(jan["expenses"]) == 1
    exp = jan["expenses"][0]
    assert exp["installment_no"] == 1
    assert exp["installments_of"] == 3
    assert exp["is_paid"] is False
    assert jan["totals"]["total"] == Decimal("100.00")
    assert jan["totals"]["open"] == Decimal("100.00")

    # No mês, u2 deve 50 a u1 (não os 150 do total)
    assert len(jan["net_debts"]) == 1
    assert jan["net_debts"][0]["debtor_id"] == u2.id
    assert jan["net_debts"][0]["creditor_id"] == u1.id
    assert jan["net_debts"][0]["amount"] == Decimal("50.00")

    members = {m["user_id"]: m for m in jan["members"]}
    assert members[u1.id]["paid"] == Decimal("100.00")
    assert members[u1.id]["owed"] == Decimal("50.00")
    assert members[u1.id]["balance"] == Decimal("50.00")
    assert members[u2.id]["balance"] == Decimal("-50.00")

    feb = DebtService.get_monthly_ledger(db_session, ws.id, "2026-02")
    assert len(feb["expenses"]) == 1
    assert feb["expenses"][0]["installment_no"] == 2

    # Mês sem despesa: retrato vazio
    empty = DebtService.get_monthly_ledger(db_session, ws.id, "2026-09")
    assert empty["expenses"] == []
    assert empty["net_debts"] == []
    assert empty["totals"]["total"] == Decimal("0.00")


def test_monthly_ledger_paid_status(db_session: Session):
    """Status 'paid' vira 'Paga' e entra no total pago do mês."""
    u1 = User(name="A", email="a4@test.com", password_hash="h")
    u2 = User(name="B", email="b4@test.com", password_hash="h")
    ws = Workspace(name="WS4")
    db_session.add_all([u1, u2, ws])
    db_session.flush()

    _make_installment(db_session, ws.id, u1, u2, 1, "2026-05", status=TransactionStatus.paid)
    db_session.commit()

    may = DebtService.get_monthly_ledger(db_session, ws.id, "2026-05")
    assert may["expenses"][0]["is_paid"] is True
    assert may["totals"]["paid"] == Decimal("100.00")
    assert may["totals"]["open"] == Decimal("0.00")


def test_monthly_ledger_settlement_zeroes_month(db_session: Session):
    """Acerto vinculado ao mês (billing_month) quita a dívida daquele mês."""
    u1 = User(name="A", email="a5@test.com", password_hash="h")
    u2 = User(name="B", email="b5@test.com", password_hash="h")
    ws = Workspace(name="WS5")
    db_session.add_all([u1, u2, ws])
    db_session.flush()

    _make_installment(db_session, ws.id, u1, u2, 1, "2026-06")
    db_session.commit()

    before = DebtService.get_monthly_ledger(db_session, ws.id, "2026-06")
    assert len(before["net_debts"]) == 1
    assert before["net_debts"][0]["amount"] == Decimal("50.00")
    assert before["settled_total"] == Decimal("0.00")

    # u2 paga os 50 a u1, marcado para 2026-06 → mês quita
    db_session.add(Settlement(
        workspace_id=ws.id, from_user_id=u2.id, to_user_id=u1.id,
        amount=Decimal("50.00"), billing_month="2026-06",
    ))
    db_session.commit()

    after = DebtService.get_monthly_ledger(db_session, ws.id, "2026-06")
    assert after["net_debts"] == []
    assert after["settled_total"] == Decimal("50.00")
    assert len(after["settlements"]) == 1
    assert after["settlements"][0]["from_user_id"] == u2.id
    assert after["settlements"][0]["to_user_id"] == u1.id


def test_monthly_ledger_ignores_settlement_of_other_scope(db_session: Session):
    """Acerto global (billing_month=None) ou de outro mês não mexe no mês visto."""
    u1 = User(name="A", email="a6@test.com", password_hash="h")
    u2 = User(name="B", email="b6@test.com", password_hash="h")
    ws = Workspace(name="WS6")
    db_session.add_all([u1, u2, ws])
    db_session.flush()

    _make_installment(db_session, ws.id, u1, u2, 1, "2026-06")
    db_session.add(Settlement(workspace_id=ws.id, from_user_id=u2.id, to_user_id=u1.id, amount=Decimal("50.00"), billing_month=None))
    db_session.add(Settlement(workspace_id=ws.id, from_user_id=u2.id, to_user_id=u1.id, amount=Decimal("50.00"), billing_month="2026-07"))
    db_session.commit()

    jun = DebtService.get_monthly_ledger(db_session, ws.id, "2026-06")
    assert jun["settled_total"] == Decimal("0.00")
    assert len(jun["net_debts"]) == 1
    assert jun["net_debts"][0]["amount"] == Decimal("50.00")


# --- A origem do saldo: de quais meses vem o acumulado -----------------------
#
# O que estes testes travam é UMA propriedade, e ela é a razão de a tela existir:
# a soma das linhas exibidas tem de dar o total exibido. Um "de onde vem esse
# saldo" que não fecha é pior do que não ter — a pessoa deixa de confiar nos dois
# números em vez de só continuar sem o segundo.


def _despesa(db, ws_id, mes, pagadores, rateio, dia=10):
    """Uma despesa no mês `mes`. `pagadores`/`rateio` são `{user_id: valor}`."""
    total = sum(pagadores.values())
    ano, num = (int(p) for p in mes.split("-"))
    tx = Transaction(
        title=f"Despesa {mes}", total_amount=total, workspace_id=ws_id,
        billing_month=mes, status=TransactionStatus.confirmed,
        transaction_date=datetime(ano, num, dia),
    )
    db.add(tx)
    db.flush()
    for uid, valor in pagadores.items():
        db.add(TransactionPayer(transaction_id=tx.id, user_id=uid, amount=valor))
    for uid, valor in rateio.items():
        db.add(TransactionSplit(
            transaction_id=tx.id, user_id=uid, split_method=SplitMethod.fixed,
            input_value=valor, computed_amount=valor,
        ))
    return tx


def _saldo_segundo_debts(db, ws_id, user_id) -> Decimal:
    """O saldo que `GET /debts` implica para `user_id`, a partir das linhas dele.

    A segunda testemunha da identidade: não basta a quebra fechar consigo mesma
    (isso ela faz por construção, já que sai da mesma soma) — ela tem de bater
    com o número que a OUTRA rota mostra na mesma tela.
    """
    linhas = DebtService.get_workspace_debts(db, ws_id)
    recebe = sum(
        (linha["amount"] for linha in linhas if linha["creditor_id"] == user_id),
        Decimal("0.00"),
    )
    paga = sum(
        (linha["amount"] for linha in linhas if linha["debtor_id"] == user_id),
        Decimal("0.00"),
    )
    return recebe - paga


def _trio(db, sufixo):
    u1 = User(name="Eu", email=f"eu{sufixo}@test.com", password_hash="h")
    u2 = User(name="Ana", email=f"ana{sufixo}@test.com", password_hash="h")
    u3 = User(name="Bruno", email=f"bruno{sufixo}@test.com", password_hash="h")
    ws = Workspace(name=f"Casa {sufixo}")
    db.add_all([u1, u2, u3, ws])
    db.flush()
    return u1, u2, u3, ws


def test_origem_do_saldo_fecha_a_conta(db_session: Session):
    """`balance == Σ meses + older + unassigned`, e bate com `/debts`.

    Cenário deliberadamente sujo: três pessoas, meses com sinais opostos, acerto
    COM mês e acerto SEM mês. É o caso em que a versão ingênua (somar só os meses)
    erra, porque o acerto global não pertence a mês nenhum.
    """
    u1, u2, u3, ws = _trio(db_session, "fecha")

    # jan: eu pago 300, rateio igual → sobro 200
    _despesa(db_session, ws.id, "2026-01",
             {u1.id: Decimal("300.00")},
             {u1.id: Decimal("100.00"), u2.id: Decimal("100.00"), u3.id: Decimal("100.00")})
    # fev: Ana paga 600, rateio igual → devo 200
    _despesa(db_session, ws.id, "2026-02",
             {u2.id: Decimal("600.00")},
             {u1.id: Decimal("200.00"), u2.id: Decimal("200.00"), u3.id: Decimal("200.00")})
    # mar: Bruno paga 90, rateio igual → devo 30
    _despesa(db_session, ws.id, "2026-03",
             {u3.id: Decimal("90.00")},
             {u1.id: Decimal("30.00"), u2.id: Decimal("30.00"), u3.id: Decimal("30.00")})
    # Acerto COM mês: eu pago 50 à Ana, quitando parte de fevereiro
    db_session.add(Settlement(
        workspace_id=ws.id, from_user_id=u1.id, to_user_id=u2.id,
        amount=Decimal("50.00"), billing_month="2026-02",
    ))
    # Acerto SEM mês: Bruno me paga 40 "por fora"
    db_session.add(Settlement(
        workspace_id=ws.id, from_user_id=u3.id, to_user_id=u1.id,
        amount=Decimal("40.00"), billing_month=None,
    ))
    db_session.commit()

    origem = DebtService.get_balance_by_month(db_session, ws.id, u1.id)

    por_mes = {m["month"]: m["balance"] for m in origem["months"]}
    assert por_mes == {
        "2026-01": Decimal("200.00"),
        "2026-02": Decimal("-150.00"),   # -200 devidos + 50 já acertados
        "2026-03": Decimal("-30.00"),
    }
    # Do meu ponto de vista, receber um acerto DERRUBA meu saldo.
    assert origem["unassigned"] == Decimal("-40.00")
    assert origem["older"] == {"count": 0, "balance": Decimal("0.00")}

    # A identidade, escrita como a tela a exibe
    soma = sum(por_mes.values(), Decimal("0.00")) + origem["older"]["balance"] + origem["unassigned"]
    assert soma == origem["balance"] == Decimal("-20.00")
    # ... e a segunda testemunha: é o mesmo número que `/debts` mostra
    assert origem["balance"] == _saldo_segundo_debts(db_session, ws.id, u1.id)

    # A linha do mês diz a quem, e quanto daquele mês já foi acertado
    fev = next(m for m in origem["months"] if m["month"] == "2026-02")
    assert fev["settled"] == Decimal("50.00")
    assert {(d["debtor_id"], d["creditor_id"]) for d in fev["net_debts"]} == {(u1.id, u2.id), (u3.id, u2.id)}
    assert origem["months"][0]["month"] == "2026-03"  # mais recente primeiro


def test_origem_ignora_mes_quitado_sem_desequilibrar_a_conta(db_session: Session):
    """Mês fechado sai da lista — e some contribuindo exatamente zero."""
    u1, u2, _u3, ws = _trio(db_session, "quitado")

    _despesa(db_session, ws.id, "2026-04",
             {u2.id: Decimal("100.00")},
             {u1.id: Decimal("50.00"), u2.id: Decimal("50.00")})
    _despesa(db_session, ws.id, "2026-05",
             {u2.id: Decimal("80.00")},
             {u1.id: Decimal("40.00"), u2.id: Decimal("40.00")})
    db_session.commit()

    antes = DebtService.get_balance_by_month(db_session, ws.id, u1.id)
    assert [m["month"] for m in antes["months"]] == ["2026-05", "2026-04"]
    assert antes["balance"] == Decimal("-90.00")

    # Quito abril inteiro
    db_session.add(Settlement(
        workspace_id=ws.id, from_user_id=u1.id, to_user_id=u2.id,
        amount=Decimal("50.00"), billing_month="2026-04",
    ))
    db_session.commit()

    depois = DebtService.get_balance_by_month(db_session, ws.id, u1.id)
    assert [m["month"] for m in depois["months"]] == ["2026-05"]
    assert depois["balance"] == Decimal("-40.00")
    assert depois["balance"] == _saldo_segundo_debts(db_session, ws.id, u1.id)
    soma = sum((m["balance"] for m in depois["months"]), Decimal("0.00")) + depois["unassigned"]
    assert soma == depois["balance"]


def test_origem_mostra_os_meses_mesmo_com_saldo_total_zero(db_session: Session):
    """Saldo global zero NÃO quer dizer mês nenhum em aberto.

    Devo 50 de janeiro e tenho 50 a receber de fevereiro: `/debts` não me lista
    (líquido zero), mas os dois meses seguem abertos e cada um se acerta sozinho.
    É o caso que prova por que a quebra é por SALDO da pessoa e não pela soma dos
    pares que o pareamento guloso devolve — os pares do mês não somam os globais.
    """
    u1, u2, _u3, ws = _trio(db_session, "zero")

    _despesa(db_session, ws.id, "2026-01",
             {u2.id: Decimal("100.00")},
             {u1.id: Decimal("50.00"), u2.id: Decimal("50.00")})
    _despesa(db_session, ws.id, "2026-02",
             {u1.id: Decimal("100.00")},
             {u1.id: Decimal("50.00"), u2.id: Decimal("50.00")})
    db_session.commit()

    assert DebtService.get_workspace_debts(db_session, ws.id) == []

    origem = DebtService.get_balance_by_month(db_session, ws.id, u1.id)
    assert origem["balance"] == Decimal("0.00")
    assert {m["month"]: m["balance"] for m in origem["months"]} == {
        "2026-01": Decimal("-50.00"),
        "2026-02": Decimal("50.00"),
    }
    soma = sum((m["balance"] for m in origem["months"]), Decimal("0.00")) + origem["unassigned"]
    assert soma == origem["balance"]


def test_origem_agrupa_os_meses_antigos_em_vez_de_truncar(db_session: Session):
    """Além do teto, os meses viram `older` — a lista encolhe, a conta não."""
    u1, u2, _u3, ws = _trio(db_session, "antigos")

    for mes in ["2026-01", "2026-02", "2026-03", "2026-04"]:
        _despesa(db_session, ws.id, mes,
                 {u2.id: Decimal("100.00")},
                 {u1.id: Decimal("50.00"), u2.id: Decimal("50.00")})
    db_session.commit()

    origem = DebtService.get_balance_by_month(db_session, ws.id, u1.id, limite=2)
    assert [m["month"] for m in origem["months"]] == ["2026-04", "2026-03"]
    assert origem["older"] == {"count": 2, "balance": Decimal("-100.00")}
    soma = (
        sum((m["balance"] for m in origem["months"]), Decimal("0.00"))
        + origem["older"]["balance"]
        + origem["unassigned"]
    )
    assert soma == origem["balance"] == Decimal("-200.00")
    assert origem["balance"] == _saldo_segundo_debts(db_session, ws.id, u1.id)


def test_origem_recorta_as_linhas_de_quem_nao_tem_acesso_completo(db_session: Session):
    """ADR 0018: sem acesso completo, só as linhas em que eu sou uma das pontas.

    O SALDO continua sendo o meu inteiro — recortar a origem dele daria um total
    diferente do que `/debts` mostra para a mesma pessoa.
    """
    u1, u2, u3, ws = _trio(db_session, "recorte")

    _despesa(db_session, ws.id, "2026-07",
             {u2.id: Decimal("300.00")},
             {u1.id: Decimal("100.00"), u2.id: Decimal("100.00"), u3.id: Decimal("100.00")})
    db_session.commit()

    completo = DebtService.get_balance_by_month(db_session, ws.id, u1.id)
    assert len(completo["months"][0]["net_debts"]) == 2  # eu→Ana e Bruno→Ana

    recortado = DebtService.get_balance_by_month(
        db_session, ws.id, u1.id, viewer_user_id=u1.id
    )
    assert [(d["debtor_id"], d["creditor_id"]) for d in recortado["months"][0]["net_debts"]] == [
        (u1.id, u2.id)
    ]
    assert recortado["balance"] == completo["balance"] == Decimal("-100.00")


def test_origem_e_retrato_do_mes_dao_o_mesmo_numero(db_session: Session):
    """A linha "ago/2026 · você deve R$ 200" tem de bater com o que abre ao clicar.

    São dois caminhos de cálculo diferentes para o mesmo número: a origem agrupa
    o histórico inteiro em SQL, o retrato carrega um mês e pareia em Python. Nada
    obriga os dois a concordarem — e discordar seria invisível, porque cada tela
    mostra um só. Foi assim que o app já teve dois "Acertos" que não mostravam a
    mesma coisa.
    """
    u1, u2, u3, ws = _trio(db_session, "concorda")

    _despesa(db_session, ws.id, "2026-01",
             {u1.id: Decimal("300.00")},
             {u1.id: Decimal("100.00"), u2.id: Decimal("100.00"), u3.id: Decimal("100.00")})
    _despesa(db_session, ws.id, "2026-02",
             {u2.id: Decimal("600.00")},
             {u1.id: Decimal("200.00"), u2.id: Decimal("200.00"), u3.id: Decimal("200.00")})
    _despesa(db_session, ws.id, "2026-03",
             {u3.id: Decimal("120.00")},
             {u1.id: Decimal("40.00"), u2.id: Decimal("40.00"), u3.id: Decimal("40.00")})
    db_session.add(Settlement(
        workspace_id=ws.id, from_user_id=u1.id, to_user_id=u2.id,
        amount=Decimal("50.00"), billing_month="2026-02",
    ))
    db_session.commit()

    origem = DebtService.get_balance_by_month(db_session, ws.id, u1.id)
    assert origem["months"], "o cenário precisa ter mês em aberto"

    for linha in origem["months"]:
        ledger = DebtService.get_monthly_ledger(db_session, ws.id, linha["month"])
        # O saldo que o retrato do mês implica para mim, pelas linhas dele
        recebe = sum(
            (d["amount"] for d in ledger["net_debts"] if d["creditor_id"] == u1.id),
            Decimal("0.00"),
        )
        paga = sum(
            (d["amount"] for d in ledger["net_debts"] if d["debtor_id"] == u1.id),
            Decimal("0.00"),
        )
        assert linha["balance"] == recebe - paga, (
            f"{linha['month']}: origem diz {linha['balance']}, o mês diz {recebe - paga}"
        )
        # E o "já acertados" da linha bate com o do retrato
        assert linha["settled"] == ledger["settled_total"]


def test_origem_ignora_moeda_estrangeira_como_o_saldo_ignora(db_session: Session):
    """Mesmos filtros de `get_workspace_debts` — senão os dois números divergem.

    Despesa fora da moeda-base não entra no saldo (ADR 0006). Se entrasse só aqui,
    a quebra passaria a somar mais do que o total, e o defeito seria invisível:
    os dois números continuariam plausíveis.
    """
    u1, u2, _u3, ws = _trio(db_session, "moeda")

    _despesa(db_session, ws.id, "2026-08",
             {u2.id: Decimal("100.00")},
             {u1.id: Decimal("50.00"), u2.id: Decimal("50.00")})
    estrangeira = _despesa(db_session, ws.id, "2026-08",
                           {u2.id: Decimal("200.00")},
                           {u1.id: Decimal("100.00"), u2.id: Decimal("100.00")}, dia=11)
    estrangeira.currency = "USD"
    db_session.add(estrangeira)

    cancelada = _despesa(db_session, ws.id, "2026-08",
                         {u2.id: Decimal("400.00")},
                         {u1.id: Decimal("200.00"), u2.id: Decimal("200.00")}, dia=12)
    cancelada.status = TransactionStatus.cancelled
    db_session.add(cancelada)
    db_session.commit()

    origem = DebtService.get_balance_by_month(db_session, ws.id, u1.id)
    assert origem["balance"] == Decimal("-50.00")
    assert origem["balance"] == _saldo_segundo_debts(db_session, ws.id, u1.id)
    assert [m["balance"] for m in origem["months"]] == [Decimal("-50.00")]
