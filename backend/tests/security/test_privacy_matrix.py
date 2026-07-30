"""Matriz de privacidade DENTRO do workspace: papel × acesso × envolvimento (ADR 0018).

`test_idor_scan.py` cobre isolamento ENTRE workspaces — atacante de fora não
alcança dado de dentro. Este arquivo cobre o que faltava, que é o furo real que a
auditoria encontrou: **membro legítimo do MESMO workspace lendo o que não é dele**.

Antes desta onda, `get_workspace_membership` (satisfeito por qualquer papel,
inclusive `viewer`) era o gate de praticamente todo GET, e cada listagem filtrava
`workspace_id + deleted_at` e mais nada. Um convidado lia o salário dos outros, os
lançamentos individuais de quem não o envolveu, os ANEXOS desses lançamentos, os
cartões e os totais da casa.

Os dois eixos são testados de propósito juntos, porque o valor da mudança está em
serem independentes:

- **`member_restrito`** (`member` + `involved_only`) → vê só o que o envolve.
- **`member_completo`** (`member` + `full_workspace`) → mesmo papel, vê a casa.
  É este que prova que a permissão é do ACESSO e não do cargo.
- **`viewer_restrito`** → papel mais baixo, também restrito.
- **`admin`** → acesso completo pelo CARGO, mesmo com `involved_only` gravado.
"""
import datetime
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from app.core.jwt import create_access_token
from app.main import app
from app.models.credit_card import CreditCard
from app.models.financing import Financing
from app.models.income import Income
from app.models.payment_account import PaymentAccount
from app.models.recurring import RecurringExpense, RecurringIncome
from app.models.settlement import Settlement
from app.models.transaction import Transaction, TransactionPayer, TransactionSplit
from app.models.user import User
from app.models.workspace import (
    FinancialAccess,
    Workspace,
    WorkspaceMembership,
    WorkspaceRole,
)

client = TestClient(app)

MES = "2026-07"
QUANDO = datetime.datetime(2026, 7, 15, 12, 0, tzinfo=datetime.UTC)

# Quem é restrito e quem vê a casa — usado nos testes parametrizados
RESTRITOS = ["member_restrito", "viewer_restrito"]
COMPLETOS = ["dono", "admin", "member_completo"]


def _h(user: User) -> dict:
    return {"Cookie": f"access_token={create_access_token({'sub': str(user.id)})}"}


@pytest.fixture(name="casa")
def casa_fixture(db_session: Session, override_get_session):
    """Workspace com os cinco perfis e um dado de cada tipo pertencente ao dono."""
    perfis = {
        "dono": (WorkspaceRole.owner, FinancialAccess.full_workspace),
        "admin": (WorkspaceRole.admin, FinancialAccess.involved_only),
        "member_completo": (WorkspaceRole.member, FinancialAccess.full_workspace),
        "member_restrito": (WorkspaceRole.member, FinancialAccess.involved_only),
        "viewer_restrito": (WorkspaceRole.viewer, FinancialAccess.involved_only),
    }

    usuarios = {}
    for nome in perfis:
        u = User(name=nome, email=f"{nome}@priv.com", password_hash="h")
        db_session.add(u)
        usuarios[nome] = u
    ws = Workspace(name="Casa", base_currency="BRL")
    db_session.add(ws)
    db_session.commit()

    for nome, (papel, acesso) in perfis.items():
        db_session.add(WorkspaceMembership(
            workspace_id=ws.id,
            user_id=usuarios[nome].id,
            role=papel,
            financial_access=acesso,
        ))

    dono = usuarios["dono"]
    restrito = usuarios["member_restrito"]
    viewer = usuarios["viewer_restrito"]

    # (1) Despesa SÓ do dono: ninguém mais é pagador nem tem split.
    solo = Transaction(
        title="Terapia do dono", total_amount=Decimal("300.00"), currency="BRL",
        transaction_date=QUANDO, billing_month=MES, status="confirmed",
        workspace_id=ws.id, created_by_user_id=dono.id,
    )
    # (2) Despesa COMPARTILHADA em três: dono, member_restrito e viewer_restrito
    # têm split → os dois restritos são ENVOLVIDOS e precisam vê-la. Um viewer
    # participa de despesa normalmente; o que ele não pode é criar/editar.
    compartilhada = Transaction(
        title="Mercado da casa", total_amount=Decimal("300.00"), currency="BRL",
        transaction_date=QUANDO, billing_month=MES, status="confirmed",
        workspace_id=ws.id, created_by_user_id=dono.id,
    )
    db_session.add_all([solo, compartilhada])
    db_session.commit()

    db_session.add_all([
        TransactionPayer(transaction_id=solo.id, user_id=dono.id, amount=Decimal("300.00")),
        TransactionSplit(
            transaction_id=solo.id, user_id=dono.id,
            input_value=Decimal("300.00"), computed_amount=Decimal("300.00"),
        ),
        TransactionPayer(
            transaction_id=compartilhada.id, user_id=dono.id, amount=Decimal("300.00")
        ),
        TransactionSplit(
            transaction_id=compartilhada.id, user_id=dono.id,
            input_value=Decimal("100.00"), computed_amount=Decimal("100.00"),
        ),
        TransactionSplit(
            transaction_id=compartilhada.id, user_id=restrito.id,
            input_value=Decimal("100.00"), computed_amount=Decimal("100.00"),
        ),
        TransactionSplit(
            transaction_id=compartilhada.id, user_id=viewer.id,
            input_value=Decimal("100.00"), computed_amount=Decimal("100.00"),
        ),
    ])

    # Renda: uma de cada, para provar que some a do outro e fica a própria
    renda_dono = Income(
        title="Salário do dono", amount=Decimal("9000.00"), currency="BRL",
        received_at=QUANDO, billing_month=MES, workspace_id=ws.id, user_id=dono.id,
    )
    renda_restrito = Income(
        title="Salário do restrito", amount=Decimal("3000.00"), currency="BRL",
        received_at=QUANDO, billing_month=MES, workspace_id=ws.id, user_id=restrito.id,
    )
    # Cartão do dono (o restrito não tem compra nele)
    cartao = CreditCard(
        name="Cartão do dono", limit=Decimal("10000.00"), closing_day=1, due_day=10,
        currency="BRL", workspace_id=ws.id, owner_user_id=dono.id,
    )
    # Financiamento do dono
    fin = Financing(
        title="Carro do dono", total_amount=Decimal("50000.00"),
        interest_rate=Decimal("0.01"), installments_count=48,
        start_date=datetime.date(2026, 1, 1), currency="BRL",
        workspace_id=ws.id, created_by_user_id=dono.id,
    )
    # Conta pessoal do dono × conta da CASA (dono NULL = compartilhada)
    conta_dono = PaymentAccount(
        name="Conta do dono", currency="BRL", workspace_id=ws.id, owner_user_id=dono.id
    )
    conta_casa = PaymentAccount(
        name="Conta da casa", currency="BRL", workspace_id=ws.id, owner_user_id=None
    )
    # Recorrência do dono × da casa (sem criador)
    # `is_active=False` nas recorrências: a materialização preguiçosa roda em
    # ROTAS DE LEITURA, então template ativo criaria despesa a cada GET e os totais
    # da casa deixariam de ser os 500 que o fixture monta. Pior, `viewer` NÃO
    # materializa (recurring_service), então o viewer veria números diferentes dos
    # outros perfis — o teste mediria a materialização, não a privacidade.
    rec_dono = RecurringExpense(
        title="Academia do dono", base_amount=Decimal("150.00"), day_of_month=5,
        workspace_id=ws.id, created_by_user_id=dono.id, is_active=False,
    )
    rec_casa = RecurringExpense(
        title="Aluguel da casa", base_amount=Decimal("2000.00"), day_of_month=10,
        workspace_id=ws.id, created_by_user_id=None, is_active=False,
    )
    rec_renda_dono = RecurringIncome(
        title="Salário recorrente do dono", base_amount=Decimal("9000.00"),
        day_of_month=5, workspace_id=ws.id, user_id=dono.id, is_active=False,
    )
    # Acerto entre dono e admin: não envolve o restrito
    acerto = Settlement(
        workspace_id=ws.id, from_user_id=usuarios["admin"].id, to_user_id=dono.id,
        amount=Decimal("50.00"), billing_month=MES, created_by_user_id=dono.id,
    )
    db_session.add_all([
        renda_dono, renda_restrito, cartao, fin, conta_dono, conta_casa,
        rec_dono, rec_casa, rec_renda_dono, acerto,
    ])
    db_session.commit()
    for obj in (solo, compartilhada, renda_dono, renda_restrito, cartao, fin,
                conta_dono, conta_casa, rec_dono, rec_casa, acerto):
        db_session.refresh(obj)

    return {
        "ws": ws,
        "u": usuarios,
        "solo": solo,
        "compartilhada": compartilhada,
        "renda_dono": renda_dono,
        "renda_restrito": renda_restrito,
        "cartao": cartao,
        "fin": fin,
        "conta_dono": conta_dono,
        "conta_casa": conta_casa,
        "rec_dono": rec_dono,
        "rec_casa": rec_casa,
        "acerto": acerto,
    }


def _get(casa, perfil: str, caminho: str):
    return client.get(
        f"/api/v1/workspaces/{casa['ws'].id}{caminho}", headers=_h(casa["u"][perfil])
    )


# ---------------------------------------------------------------------------
# Lançamentos
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("perfil", RESTRITOS)
def test_restrito_nao_ve_lancamento_que_nao_o_envolve(casa, perfil):
    corpo = _get(casa, perfil, "/transactions/").json()
    ids = [t["id"] for t in corpo["items"]]
    assert casa["solo"].id not in ids
    assert casa["compartilhada"].id in ids, "a despesa em que ele tem split precisa aparecer"
    # A CONTAGEM e a SOMA derivam da mesma statement, então acompanham o recorte —
    # senão a tela diria "2 lançamentos" mostrando 1, e somaria os 300 escondidos
    assert corpo["total"] == 1
    assert Decimal(str(corpo["total_amount"])) == Decimal("300.00")


@pytest.mark.parametrize("perfil", COMPLETOS)
def test_acesso_completo_ve_os_dois_lancamentos(casa, perfil):
    corpo = _get(casa, perfil, "/transactions/").json()
    ids = [t["id"] for t in corpo["items"]]
    assert casa["solo"].id in ids
    assert casa["compartilhada"].id in ids
    assert corpo["total"] == 2
    assert Decimal(str(corpo["total_amount"])) == Decimal("600.00")


@pytest.mark.parametrize("perfil", RESTRITOS)
def test_detalhe_de_lancamento_alheio_responde_404(casa, perfil):
    """404 e não 403: 403 confirmaria a existência, e a existência já é informação."""
    assert _get(casa, perfil, f"/transactions/{casa['solo'].id}").status_code == 404
    assert _get(casa, perfil, f"/transactions/{casa['compartilhada'].id}").status_code == 200


def test_member_restrito_nao_escreve_em_lancamento_invisivel(casa):
    """Escrita segue a leitura: o que não se vê não se edita nem se apaga → 404."""
    ws = casa["ws"].id
    h = _h(casa["u"]["member_restrito"])
    assert client.put(
        f"/api/v1/workspaces/{ws}/transactions/{casa['solo'].id}",
        json={"title": "invadido"}, headers=h,
    ).status_code == 404
    assert client.delete(
        f"/api/v1/workspaces/{ws}/transactions/{casa['solo'].id}", headers=h
    ).status_code == 404


def test_viewer_leva_403_do_papel_antes_da_visibilidade(casa):
    """403, não 404 — e está certo.

    `require_role(member)` roda como dependency, ANTES do corpo da rota. Para o
    viewer a resposta honesta é "você não escreve nada aqui", que não diz nada
    sobre aquele registro específico. O 404 por invisibilidade só importa para
    quem PODERIA escrever — daí o teste do member restrito ser separado.
    """
    ws = casa["ws"].id
    h = _h(casa["u"]["viewer_restrito"])
    # Vale tanto para o lançamento invisível quanto para o que ele VÊ
    for tx in (casa["solo"], casa["compartilhada"]):
        assert client.put(
            f"/api/v1/workspaces/{ws}/transactions/{tx.id}",
            json={"title": "invadido"}, headers=h,
        ).status_code == 403


# ---------------------------------------------------------------------------
# Anexos — o vazamento de pior consequência (servia o ARQUIVO)
# ---------------------------------------------------------------------------

PNG = (
    b"\x89PNG\r\n\x1a\n" + b"\x00" * 8 + b"IHDR" + b"\x00" * 40
)


def _sobe_anexo(casa, transaction_id: int) -> int:
    res = client.post(
        f"/api/v1/workspaces/{casa['ws'].id}/transactions/{transaction_id}/attachments",
        files={"file": ("recibo.png", PNG, "image/png")},
        headers=_h(casa["u"]["dono"]),
    )
    assert res.status_code == 200, res.text
    return res.json()["id"]


@pytest.mark.parametrize("perfil", RESTRITOS)
def test_anexo_herda_a_visibilidade_do_lancamento(casa, perfil):
    anexo_id = _sobe_anexo(casa, casa["solo"].id)

    # Listagem do lançamento invisível: 404 antes de chegar aos anexos
    assert _get(
        casa, perfil, f"/transactions/{casa['solo'].id}/attachments"
    ).status_code == 404
    # E o DOWNLOAD do arquivo, que é o que realmente vazava
    assert _get(casa, perfil, f"/attachments/{anexo_id}").status_code == 404


@pytest.mark.parametrize("perfil", RESTRITOS)
def test_anexo_de_lancamento_compartilhado_continua_acessivel(casa, perfil):
    anexo_id = _sobe_anexo(casa, casa["compartilhada"].id)
    assert _get(
        casa, perfil, f"/transactions/{casa['compartilhada'].id}/attachments"
    ).status_code == 200
    assert _get(casa, perfil, f"/attachments/{anexo_id}").status_code == 200


def test_acesso_completo_baixa_qualquer_anexo(casa):
    anexo_id = _sobe_anexo(casa, casa["solo"].id)
    assert _get(casa, "member_completo", f"/attachments/{anexo_id}").status_code == 200


# ---------------------------------------------------------------------------
# Renda — o dado mais sensível
# ---------------------------------------------------------------------------

def test_restrito_ve_a_propria_renda_e_nao_a_alheia(casa):
    corpo = _get(casa, "member_restrito", "/income/").json()
    ids = [i["id"] for i in corpo]
    assert casa["renda_dono"].id not in ids
    assert casa["renda_restrito"].id in ids


def test_viewer_restrito_nao_ve_renda_de_ninguem(casa):
    """O viewer restrito não tem renda própria neste workspace: lista vazia."""
    assert _get(casa, "viewer_restrito", "/income/").json() == []


@pytest.mark.parametrize("perfil", COMPLETOS)
def test_acesso_completo_ve_todas_as_rendas(casa, perfil):
    ids = [i["id"] for i in _get(casa, perfil, "/income/").json()]
    assert casa["renda_dono"].id in ids
    assert casa["renda_restrito"].id in ids


def test_renda_recorrente_alheia_nao_aparece(casa):
    assert _get(casa, "member_restrito", "/recurring-income").json() == []
    assert len(_get(casa, "dono", "/recurring-income").json()) == 1


# ---------------------------------------------------------------------------
# Cartões, financiamentos, contas, recorrências
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("perfil", RESTRITOS)
def test_cartao_de_outro_sem_compra_minha_nao_aparece(casa, perfil):
    ids = [c["id"] for c in _get(casa, perfil, "/credit-cards/").json()]
    assert casa["cartao"].id not in ids
    assert _get(casa, perfil, f"/credit-cards/{casa['cartao'].id}/statements").status_code == 404


def test_cartao_aparece_para_quem_tem_compra_nele(casa, db_session):
    """Ramo legítimo do `card_scope`: preciso achar em que fatura caiu MINHA despesa."""
    casa["compartilhada"].credit_card_id = casa["cartao"].id
    db_session.add(casa["compartilhada"])
    db_session.commit()

    ids = [c["id"] for c in _get(casa, "member_restrito", "/credit-cards/").json()]
    assert casa["cartao"].id in ids


@pytest.mark.parametrize("perfil", RESTRITOS)
def test_financiamento_alheio_invisivel(casa, perfil):
    assert _get(casa, perfil, "/financing").json() == []
    assert _get(casa, perfil, f"/financing/{casa['fin'].id}").status_code == 404
    assert _get(casa, perfil, f"/financing/{casa['fin'].id}/schedule").status_code == 404


@pytest.mark.parametrize("perfil", RESTRITOS)
def test_conta_da_casa_sim_conta_pessoal_alheia_nao(casa, perfil):
    """Dono NULL significa "da casa" e continua visível; com dono, é privada."""
    ids = [c["id"] for c in _get(casa, perfil, "/payment-accounts").json()]
    assert casa["conta_casa"].id in ids
    assert casa["conta_dono"].id not in ids


@pytest.mark.parametrize("perfil", RESTRITOS)
def test_recorrencia_da_casa_sim_pessoal_alheia_nao(casa, perfil):
    ids = [r["id"] for r in _get(casa, perfil, "/recurring").json()]
    assert casa["rec_casa"].id in ids
    assert casa["rec_dono"].id not in ids
    assert _get(casa, perfil, f"/recurring/{casa['rec_dono'].id}").status_code == 404
    assert _get(casa, perfil, f"/recurring/{casa['rec_casa'].id}").status_code == 200


def test_member_nao_altera_cartao_de_outro(casa):
    """Cartão não tinha trava de autoria NENHUMA: qualquer member mudava o limite
    do cartão alheio. Com dono, some da vista → 404."""
    res = client.put(
        f"/api/v1/workspaces/{casa['ws'].id}/credit-cards/{casa['cartao'].id}",
        json={"limit": "1.00"},
        headers=_h(casa["u"]["member_restrito"]),
    )
    assert res.status_code == 404


def test_member_completo_ve_o_cartao_mas_nao_o_altera(casa):
    """Aqui os dois eixos se separam: com `full_workspace` ele VÊ o cartão, e
    ainda assim não pode ESCREVER nele, porque o dono é outro (403, não 404)."""
    ids = [c["id"] for c in _get(casa, "member_completo", "/credit-cards/").json()]
    assert casa["cartao"].id in ids

    res = client.put(
        f"/api/v1/workspaces/{casa['ws'].id}/credit-cards/{casa['cartao'].id}",
        json={"limit": "1.00"},
        headers=_h(casa["u"]["member_completo"]),
    )
    assert res.status_code == 403


# ---------------------------------------------------------------------------
# Acertos
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("perfil", RESTRITOS)
def test_acerto_entre_terceiros_invisivel(casa, perfil):
    assert _get(casa, perfil, "/settlements").json() == []


def test_acerto_visivel_para_as_duas_pontas(casa):
    for perfil in ("dono", "admin"):
        ids = [s["id"] for s in _get(casa, perfil, "/settlements").json()]
        assert casa["acerto"].id in ids, f"{perfil} é uma das pontas do acerto"


# ---------------------------------------------------------------------------
# Agregações: o número da casa não sai, e não vira zero
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("perfil", RESTRITOS)
def test_resumo_suprime_a_casa_e_mantem_a_minha_parte(casa, perfil):
    corpo = _get(casa, perfil, f"/analytics/summary?month={MES}").json()
    # None, não 0: zero seria mentira aritmética somável
    assert corpo["total_expenses"] is None
    assert corpo["total_income"] is None
    assert corpo["net_savings"] is None
    assert corpo["categories"] is None
    # O recorte pessoal NUNCA é suprimido — é dado do próprio usuário
    assert corpo["my_expenses"] is not None
    assert corpo["my_income"] is not None


def test_minha_parte_do_restrito_conta_so_o_split_dele(casa):
    corpo = _get(casa, "member_restrito", f"/analytics/summary?month={MES}").json()
    assert Decimal(str(corpo["my_expenses"])) == Decimal("100.00")
    assert Decimal(str(corpo["my_income"])) == Decimal("3000.00")


@pytest.mark.parametrize("perfil", COMPLETOS)
def test_acesso_completo_recebe_os_totais_da_casa(casa, perfil):
    corpo = _get(casa, perfil, f"/analytics/summary?month={MES}").json()
    assert Decimal(str(corpo["total_expenses"])) == Decimal("600.00")
    assert Decimal(str(corpo["total_income"])) == Decimal("12000.00")
    assert corpo["categories"] is not None


@pytest.mark.parametrize("perfil", RESTRITOS)
def test_historico_de_6_meses_tambem_suprime_a_casa(casa, perfil):
    """Suprimir o resumo e deixar o histórico passar seria pior que não suprimir:
    daria o total da casa mês a mês na MESMA resposta."""
    corpo = _get(casa, perfil, f"/analytics/reports?month={MES}").json()
    assert corpo["current_summary"]["total_expenses"] is None
    for barra in corpo["monthly_history"]:
        assert barra["expenses"] is None
        assert barra["income"] is None
        assert barra["my_expenses"] is not None


@pytest.mark.parametrize("perfil", RESTRITOS)
def test_previsao_deixa_so_a_meta_pessoal(casa, perfil):
    corpo = _get(casa, perfil, f"/analytics/forecast?month={MES}").json()
    for campo in (
        "actual_spent", "projected_eom", "total_budget", "income_actual",
        "projected_net", "card_statements_pending", "fixed_costs_pending",
    ):
        assert corpo[campo] is None, f"{campo} é projeção de caixa da CASA"
    assert corpo["my_budget"] is not None


# ---------------------------------------------------------------------------
# Dívidas e endividamento
# ---------------------------------------------------------------------------

def test_divida_recortada_nas_pontas_de_quem_pede(casa):
    """O ledger é calculado INTEIRO (o pareamento guloso precisa de todos os
    saldos) e recortado na saída."""
    for linha in _get(casa, "member_restrito", "/debts").json():
        assert casa["u"]["member_restrito"].id in (linha["debtor_id"], linha["creditor_id"])


def test_ledger_mensal_do_restrito_mostra_so_a_linha_dele(casa):
    corpo = _get(casa, "member_restrito", f"/debts/monthly?month={MES}").json()
    assert [m["user_id"] for m in corpo["members"]] == [casa["u"]["member_restrito"].id]
    # Só a despesa em que ele entra — e `totals` acompanha o que está listado
    assert [e["id"] for e in corpo["expenses"]] == [casa["compartilhada"].id]
    assert Decimal(str(corpo["totals"]["total"])) == Decimal("300.00")
    # O acerto entre dono e admin não é dele
    assert corpo["settlements"] == []
    assert Decimal(str(corpo["settled_total"])) == Decimal("0.00")


def test_ledger_mensal_completo_mostra_a_casa(casa):
    corpo = _get(casa, "member_completo", f"/debts/monthly?month={MES}").json()
    assert len(corpo["expenses"]) == 2
    assert Decimal(str(corpo["totals"]["total"])) == Decimal("600.00")
    assert len(corpo["settlements"]) == 1


@pytest.mark.parametrize("perfil", RESTRITOS)
def test_endividamento_nao_expoe_compromisso_alheio(casa, perfil):
    corpo = _get(casa, perfil, f"/liabilities/overview?month={MES}").json()
    assert corpo["financings"] == []
    assert Decimal(str(corpo["totals"]["financing_outstanding"])) == Decimal("0.00")
    assert [c["id"] for c in corpo["cards"]] == []
    for pessoa in corpo["by_person"]:
        assert pessoa["user_id"] == casa["u"][perfil].id


def test_endividamento_completo_ve_tudo(casa):
    corpo = _get(casa, "member_completo", f"/liabilities/overview?month={MES}").json()
    assert [f["id"] for f in corpo["financings"]] == [casa["fin"].id]
    assert casa["cartao"].id in [c["id"] for c in corpo["cards"]]


# ---------------------------------------------------------------------------
# Auditoria e o eixo papel × acesso
# ---------------------------------------------------------------------------

def test_auditoria_continua_exigindo_admin(casa):
    """Único GET que já tinha gate de papel antes desta onda."""
    assert _get(casa, "member_completo", "/audit").status_code == 403
    assert _get(casa, "admin", "/audit").status_code == 200


def test_admin_tem_acesso_completo_pelo_cargo(casa):
    """O admin do fixture tem `involved_only` GRAVADO na coluna. Quem administra
    membros, cadastros e auditoria precisa dos números da casa — então o cargo
    sobrepõe a coluna (`effective_access`). Sem isto, um admin ficaria sem a visão
    do workspace que ele administra."""
    corpo = _get(casa, "admin", f"/analytics/summary?month={MES}").json()
    assert corpo["total_expenses"] is not None
    ids = [t["id"] for t in _get(casa, "admin", "/transactions/").json()["items"]]
    assert casa["solo"].id in ids


def test_papel_e_acesso_sao_eixos_independentes(casa):
    """O núcleo do ADR 0018 num teste só.

    `member_restrito` e `member_completo` têm o MESMO papel e veem coisas
    diferentes; `viewer_restrito` tem papel menor e vê o mesmo que o
    `member_restrito`. Logo a visibilidade não se deriva do papel.
    """
    def ve_a_casa(perfil: str) -> bool:
        corpo = _get(casa, perfil, f"/analytics/summary?month={MES}").json()
        return corpo["total_expenses"] is not None

    assert ve_a_casa("member_completo") is True
    assert ve_a_casa("member_restrito") is False
    assert ve_a_casa("viewer_restrito") is False


def test_member_report_da_matriz_de_leitura(casa):
    """Varredura: para cada listagem, o restrito nunca recebe o registro do dono.

    Existe como rede de segurança contra endpoint novo que esqueça a política —
    a lista de caminhos aqui é o inventário do que precisa estar escopado.
    """
    proibidos = {
        "/income/": casa["renda_dono"].id,
        "/financing": casa["fin"].id,
        "/credit-cards/": casa["cartao"].id,
        "/settlements": casa["acerto"].id,
        "/payment-accounts": casa["conta_dono"].id,
        "/recurring": casa["rec_dono"].id,
    }
    for caminho, id_proibido in proibidos.items():
        corpo = _get(casa, "member_restrito", caminho).json()
        ids = [item["id"] for item in corpo]
        assert id_proibido not in ids, f"{caminho} vazou o registro do dono"
