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
        received_at=QUANDO, billing_month=MES, user_id=dono.id,
    )
    renda_restrito = Income(
        title="Salário do restrito", amount=Decimal("3000.00"), currency="BRL",
        received_at=QUANDO, billing_month=MES, user_id=restrito.id,
    )
    # Cartão do dono (o restrito não tem compra nele)
    cartao = CreditCard(
        name="Cartão do dono", limit=Decimal("10000.00"), closing_day=1, due_day=10,
        currency="BRL", owner_user_id=dono.id,
    )
    # Financiamento do dono
    fin = Financing(
        title="Carro do dono", total_amount=Decimal("50000.00"),
        interest_rate=Decimal("0.01"), installments_count=48,
        start_date=datetime.date(2026, 1, 1), currency="BRL",
        owner_user_id=dono.id,
    )
    # Duas contas pessoais: a do dono e a do restrito. "Conta da casa"
    # (`owner_user_id=None`) deixou de existir no ADR 0021 — conta bancária é de
    # uma pessoa, e o `None` fazia o extrato de alguém virar recurso coletivo.
    conta_dono = PaymentAccount(
        name="Conta do dono", currency="BRL", owner_user_id=dono.id
    )
    conta_restrito = PaymentAccount(
        name="Conta do restrito", currency="BRL", owner_user_id=restrito.id
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
        day_of_month=5, user_id=dono.id, is_active=False,
    )
    # Acerto entre dono e admin: não envolve o restrito
    acerto = Settlement(
        workspace_id=ws.id, from_user_id=usuarios["admin"].id, to_user_id=dono.id,
        amount=Decimal("50.00"), billing_month=MES, created_by_user_id=dono.id,
    )
    db_session.add_all([
        renda_dono, renda_restrito, cartao, fin, conta_dono, conta_restrito,
        rec_dono, rec_casa, rec_renda_dono, acerto,
    ])
    db_session.commit()

    # Cronograma do financiamento: sem parcela em aberto ele não é compromisso
    # nenhum, e `/me/commitments` (com razão) o ignoraria.
    from app.services.financing_service import FinancingService

    for parcela in FinancingService.calculate_amortization_schedule(
        total_amount=fin.total_amount,
        interest_rate=fin.interest_rate,
        installments_count=fin.installments_count,
        start_date=fin.start_date,
        method=fin.method,
    ):
        parcela.financing_id = fin.id
        db_session.add(parcela)
    db_session.commit()
    for obj in (solo, compartilhada, renda_dono, renda_restrito, cartao, fin,
                conta_dono, conta_restrito, rec_dono, rec_casa, acerto):
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
        "conta_restrito": conta_restrito,
        "rec_dono": rec_dono,
        "rec_casa": rec_casa,
        "acerto": acerto,
    }


def _get(casa, perfil: str, caminho: str):
    return client.get(
        f"/api/v1/workspaces/{casa['ws'].id}{caminho}", headers=_h(casa["u"][perfil])
    )


def _get_me(casa, perfil: str, caminho: str):
    """GET numa rota PESSOAL — sem workspace no caminho (ADR 0021)."""
    return client.get(f"/api/v1/me{caminho}", headers=_h(casa["u"][perfil]))


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
# Recurso PESSOAL: só o dono, em papel nenhum (ADR 0021)
#
# Esta seção mudou de forma na Onda 5, e a mudança é a correção do P0 da
# auditoria. Antes, renda/cartão/conta/financiamento moravam no workspace e a
# visibilidade deles seguia `financial_access`: quem tinha `full_workspace` via
# o salário, o limite e a fatura de todo mundo — e o cartão "compartilhado" com
# nível `use` entregava a fatura inteira, com as compras privadas de outro
# workspace dentro, porque o predicado que implementava o nível `full`
# (`card_full_access_here`) não era chamado por rota nenhuma.
#
# Agora o eixo `financial_access` **não alcança recurso pessoal**. Por isso os
# testes abaixo são parametrizados por TODOS os perfis, e não só pelos restritos:
# o ponto é justamente que `dono`, `admin` e `member_completo` também não veem.
# ---------------------------------------------------------------------------

TODOS_MENOS_DONO = ["admin", "member_completo", "member_restrito", "viewer_restrito"]


@pytest.mark.parametrize("perfil", TODOS_MENOS_DONO)
def test_renda_alheia_e_invisivel_em_qualquer_papel(casa, perfil):
    ids = [i["id"] for i in _get_me(casa, perfil, "/income").json()]
    assert casa["renda_dono"].id not in ids, (
        f"{perfil} não pode ver o salário do dono — nem com full_workspace"
    )


def test_cada_um_ve_a_propria_renda(casa):
    meus = [i["id"] for i in _get_me(casa, "member_restrito", "/income").json()]
    assert casa["renda_restrito"].id in meus
    assert casa["renda_dono"].id not in meus

    do_dono = [i["id"] for i in _get_me(casa, "dono", "/income").json()]
    assert casa["renda_dono"].id in do_dono
    assert casa["renda_restrito"].id not in do_dono


def test_renda_recorrente_alheia_nao_aparece(casa):
    assert _get_me(casa, "member_restrito", "/recurring-income").json() == []
    assert len(_get_me(casa, "dono", "/recurring-income").json()) == 1


@pytest.mark.parametrize("perfil", TODOS_MENOS_DONO)
def test_cartao_alheio_e_invisivel_em_qualquer_papel(casa, perfil):
    """O P0: limite, comprometido e fatura do dono não vazam para ninguém."""
    ids = [c["id"] for c in _get_me(casa, perfil, "/credit-cards/").json()]
    assert casa["cartao"].id not in ids
    assert _get_me(casa, perfil, f"/credit-cards/{casa['cartao'].id}/statements").status_code == 404


@pytest.mark.parametrize("perfil", TODOS_MENOS_DONO)
def test_ter_compra_no_cartao_alheio_nao_abre_a_fatura(casa, perfil, db_session):
    """O ramo que o modelo antigo considerava legítimo ("preciso achar em que
    fatura caiu minha despesa") entregava junto o limite e as demais compras do
    dono. Ver o LANÇAMENTO no workspace continua valendo; ver o CARTÃO, não."""
    casa["compartilhada"].credit_card_id = casa["cartao"].id
    db_session.add(casa["compartilhada"])
    db_session.commit()

    ids = [c["id"] for c in _get_me(casa, perfil, "/credit-cards/").json()]
    assert casa["cartao"].id not in ids


@pytest.mark.parametrize("perfil", TODOS_MENOS_DONO)
def test_ciclo_da_fatura_alheia_responde_404(casa, perfil, db_session):
    """Fechar/pagar/reabrir não tinham guarda de dono: pediam só
    `require_role(member)` no workspace, então quem enxergasse o cartão
    controlava o ciclo da fatura de outra pessoa."""
    from app.models.credit_card import CardStatement

    fatura = CardStatement(
        card_id=casa["cartao"].id, month=MES,
        closing_date=QUANDO, due_date=QUANDO,
    )
    db_session.add(fatura)
    db_session.commit()
    db_session.refresh(fatura)

    base = f"/api/v1/me/credit-cards/{casa['cartao'].id}/statements/{fatura.id}"
    for acao, corpo in (("close", None), ("pay", {}), ("reopen", None)):
        res = client.post(
            f"{base}/{acao}", json=corpo, headers=_h(casa["u"][perfil])
        )
        assert res.status_code == 404, f"{perfil} não pode {acao} fatura alheia"


@pytest.mark.parametrize("perfil", TODOS_MENOS_DONO)
def test_financiamento_alheio_invisivel(casa, perfil):
    assert _get_me(casa, perfil, "/financing").json() == []
    assert _get_me(casa, perfil, f"/financing/{casa['fin'].id}").status_code == 404
    assert _get_me(casa, perfil, f"/financing/{casa['fin'].id}/schedule").status_code == 404


@pytest.mark.parametrize("perfil", TODOS_MENOS_DONO)
def test_conta_alheia_invisivel(casa, perfil):
    ids = [c["id"] for c in _get_me(casa, perfil, "/payment-accounts").json()]
    assert casa["conta_dono"].id not in ids


def test_cada_um_ve_a_propria_conta(casa):
    minhas = [c["id"] for c in _get_me(casa, "member_restrito", "/payment-accounts").json()]
    assert casa["conta_restrito"].id in minhas
    assert casa["conta_dono"].id not in minhas


@pytest.mark.parametrize("perfil", RESTRITOS)
def test_recorrencia_da_casa_sim_pessoal_alheia_nao(casa, perfil):
    """Recorrência de DESPESA continua no workspace, com dono opcional: o aluguel
    que todos rateiam é da casa e o `None` ali é modelagem, não dado faltando."""
    ids = [r["id"] for r in _get(casa, perfil, "/recurring").json()]
    assert casa["rec_casa"].id in ids
    assert casa["rec_dono"].id not in ids
    assert _get(casa, perfil, f"/recurring/{casa['rec_dono'].id}").status_code == 404
    assert _get(casa, perfil, f"/recurring/{casa['rec_casa'].id}").status_code == 200


@pytest.mark.parametrize("perfil", TODOS_MENOS_DONO)
def test_ninguem_altera_cartao_de_outro(casa, perfil):
    """404, não 403: 403 confirmaria que o cartão existe, e a existência já vaza."""
    res = client.put(
        f"/api/v1/me/credit-cards/{casa['cartao'].id}",
        json={"limit": "1.00"},
        headers=_h(casa["u"][perfil]),
    )
    assert res.status_code == 404


def test_lancar_com_cartao_alheio_e_recusado(casa):
    """A outra metade do P0: o cartão compartilhado aparecia na listagem do
    workspace de destino e o lançamento nele respondia 400 — vazava e não servia.
    Agora o cartão nem aparece, e usá-lo continua recusado."""
    res = client.post(
        f"/api/v1/workspaces/{casa['ws'].id}/transactions/",
        json={
            "title": "Compra no cartão do outro",
            "total_amount": "100.00",
            "transaction_date": QUANDO.isoformat(),
            "payment_method": "credit_card",
            "credit_card_id": casa["cartao"].id,
            "payers": [{
                "user_id": casa["u"]["member_restrito"].id,
                "amount": "100.00",
                "payment_method": "credit_card",
            }],
            "splits": [{
                "user_id": casa["u"]["member_restrito"].id,
                "split_method": "fixed",
                "input_value": "100.00",
            }],
        },
        headers=_h(casa["u"]["member_restrito"]),
    )
    assert res.status_code == 400
    assert "Cartão" in res.json()["error"]["message"]


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
    assert corpo["categories"] is None
    # O recorte pessoal NUNCA é suprimido — é dado do próprio usuário
    assert corpo["my_expenses"] is not None
    assert corpo["paid_by_me"] is not None


def test_resumo_do_workspace_nao_fala_de_renda(casa):
    """`my_income`/`my_net` saíram do resumo (ADR 0021).

    `my_net` era renda GLOBAL menos despesa DESTE workspace: quem participa de
    dois workspaces via o mesmo salário combinado com um subconjunto diferente
    das despesas em cada um, e as duas "sobras" eram maiores que a real. O número
    certo existe num lugar só — `/me/overview`.
    """
    corpo = _get(casa, "dono", f"/analytics/summary?month={MES}").json()
    for campo in ("my_income", "my_net", "total_income", "net_savings"):
        assert campo not in corpo, f"{campo} mistura escopo pessoal com o do workspace"


def test_minha_parte_do_restrito_conta_so_o_split_dele(casa):
    corpo = _get(casa, "member_restrito", f"/analytics/summary?month={MES}").json()
    assert Decimal(str(corpo["my_expenses"])) == Decimal("100.00")
    # Ele consumiu 100 e não pagou nada → deve 100 (saldo negativo)
    assert Decimal(str(corpo["paid_by_me"])) == Decimal("0.00")
    assert Decimal(str(corpo["my_balance"])) == Decimal("-100.00")


def test_quem_pagou_tudo_tem_saldo_a_receber(casa):
    """O par que faltava no Painel: consumo × caixa — e o acerto já recebido.

    O dono pagou as duas despesas (600) e consumiu 400, então adiantou 200. Mas o
    admin já lhe acertou 50 neste mês (fixture `casa`), e o que resta a receber é
    150.

    Este teste afirmava 200 e, ao afirmar, congelava o defeito que a auditoria
    externa encontrou: `my_balance` era `paid_by_me − my_expenses` e ignorava
    `Settlement`, então o Painel e os Relatórios seguiam cobrando um valor já
    pago — enquanto `/me/overview`, que usa o ledger do `DebtService`, mostrava o
    saldo certo. Os números brutos continuam sendo 600 e 400: o acerto não desfaz
    o que foi pago nem o que foi consumido, só quita a diferença.
    """
    corpo = _get(casa, "dono", f"/analytics/summary?month={MES}").json()
    assert Decimal(str(corpo["paid_by_me"])) == Decimal("600.00")
    assert Decimal(str(corpo["my_expenses"])) == Decimal("400.00")
    assert Decimal(str(corpo["my_balance"])) == Decimal("150.00")


@pytest.mark.parametrize("perfil", COMPLETOS)
def test_acesso_completo_recebe_os_totais_da_casa(casa, perfil):
    corpo = _get(casa, perfil, f"/analytics/summary?month={MES}").json()
    assert Decimal(str(corpo["total_expenses"])) == Decimal("600.00")
    assert corpo["categories"] is not None


@pytest.mark.parametrize("perfil", RESTRITOS)
def test_historico_de_6_meses_tambem_suprime_a_casa(casa, perfil):
    """Suprimir o resumo e deixar o histórico passar seria pior que não suprimir:
    daria o total da casa mês a mês na MESMA resposta."""
    corpo = _get(casa, perfil, f"/analytics/reports?month={MES}").json()
    assert corpo["current_summary"]["total_expenses"] is None
    for barra in corpo["monthly_history"]:
        assert barra["expenses"] is None
        assert barra["my_expenses"] is not None


@pytest.mark.parametrize("perfil", RESTRITOS)
def test_previsao_deixa_so_a_meta_pessoal(casa, perfil):
    corpo = _get(casa, perfil, f"/analytics/forecast?month={MES}").json()
    for campo in ("actual_spent", "projected_eom", "total_budget", "fixed_costs_pending"):
        assert corpo[campo] is None, f"{campo} é projeção de gasto da CASA"
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


@pytest.mark.parametrize("perfil", TODOS_MENOS_DONO)
def test_compromissos_nao_expoem_dividas_alheias(casa, perfil):
    """O painel de endividamento do workspace deixou de existir (ADR 0021): a
    dívida com banco e cartão é de quem assinou, e agora vive em
    `/me/commitments`, que só enxerga os compromissos de quem pergunta."""
    corpo = _get_me(casa, perfil, "/commitments").json()
    assert corpo["financings"] == []
    assert corpo["cards"] == []
    assert Decimal(str(corpo["outstanding_total"])) == Decimal("0.00")


def test_compromissos_do_dono_mostram_o_que_e_dele(casa):
    corpo = _get_me(casa, "dono", "/commitments").json()
    assert [f["financing_id"] for f in corpo["financings"]] == [casa["fin"].id]
    # Saldo devedor é o PRINCIPAL em aberto — juros são custo futuro, não dívida
    assert Decimal(str(corpo["outstanding_total"])) > Decimal("0.00")
    # E os prazos vêm separados, em vez de somados num "Total a pagar" só
    for campo in ("overdue", "due_this_month", "monthly_commitment", "next_installments"):
        assert campo in corpo


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
    do_workspace = {
        "/settlements": casa["acerto"].id,
        "/recurring": casa["rec_dono"].id,
    }
    for caminho, id_proibido in do_workspace.items():
        ids = [item["id"] for item in _get(casa, "member_restrito", caminho).json()]
        assert id_proibido not in ids, f"{caminho} vazou o registro do dono"

    # Recurso pessoal: a varredura roda para TODO perfil, inclusive os de acesso
    # completo — é o que distingue os dois eixos depois do ADR 0021.
    pessoais = {
        "/income": casa["renda_dono"].id,
        "/financing": casa["fin"].id,
        "/credit-cards/": casa["cartao"].id,
        "/payment-accounts": casa["conta_dono"].id,
    }
    for perfil in TODOS_MENOS_DONO:
        for caminho, id_proibido in pessoais.items():
            ids = [item["id"] for item in _get_me(casa, perfil, caminho).json()]
            assert id_proibido not in ids, (
                f"{caminho} vazou o recurso pessoal do dono para {perfil}"
            )
