"""Acertos na camada global — `/me/debts`, `/me/debts/monthly`, `/me/settlements`.

O que estes testes protegem, em uma frase cada:

- o recorte é a PESSOA, mesmo para quem é dono da casa (acerto de terceiros não
  vaza para a visão global);
- casa de que não sou membro não entra;
- duas casas com saldos opostos continuam sendo DOIS grupos — compensar seria
  dizer "você está quitado" a quem deve para uma pessoa e tem a receber de outra;
- casa cuja moeda-base não converte aparece na moeda dela, fora do total, e
  nomeada — não como um zero silencioso.
"""
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.core.jwt import create_access_token
from app.main import app
from app.models.settlement import Settlement
from app.models.transaction import (
    SplitMethod,
    Transaction,
    TransactionPayer,
    TransactionSplit,
)
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMembership, WorkspaceRole

client = TestClient(app)

MES = "2026-08"


def _usuario(db: Session, nome: str, email: str) -> User:
    u = User(name=nome, email=email, password_hash="hash")
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


def _workspace(db: Session, nome: str, dono: User, moeda: str = "BRL") -> Workspace:
    ws = Workspace(name=nome, created_by_user_id=dono.id, base_currency=moeda)
    db.add(ws)
    db.commit()
    db.refresh(ws)
    return ws


def _entra(db: Session, ws: Workspace, user: User, papel=WorkspaceRole.member) -> None:
    db.add(WorkspaceMembership(workspace_id=ws.id, user_id=user.id, role=papel))
    db.commit()


def _despesa(
    db: Session,
    ws: Workspace,
    *,
    pagador: User,
    valor: str,
    divisao: list,
    mes: str = MES,
    moeda: str = "BRL",
) -> Transaction:
    """Uma despesa realizada: `pagador` adianta tudo, `divisao` reparte o consumo.

    `divisao` é uma LISTA de `(user, valor)`: `User` é SQLModel e não é hashable,
    então não serve de chave de dicionário.
    """
    tx = Transaction(
        title=f"Despesa {ws.name}",
        total_amount=Decimal(valor),
        transaction_date=datetime(2026, 8, 10, 12, tzinfo=UTC),
        workspace_id=ws.id,
        created_by_user_id=pagador.id,
        currency=moeda,
        status="confirmed",
        billing_month=mes,
    )
    db.add(tx)
    db.commit()
    db.refresh(tx)
    db.add(TransactionPayer(transaction_id=tx.id, user_id=pagador.id, amount=Decimal(valor)))
    for user, parte in divisao:
        db.add(TransactionSplit(
            transaction_id=tx.id,
            user_id=user.id,
            split_method=SplitMethod.fixed,
            input_value=Decimal(parte),
            computed_amount=Decimal(parte),
        ))
    db.commit()
    return tx


@pytest.fixture
def cenario(db_session: Session):
    """Eu em duas casas, com saldos OPOSTOS — e uma terceira casa que não é minha.

    - Casa: a Ana adiantou 200 e eu consumi 100 → **eu devo 100**.
    - Viagem: eu adiantei 300 e o Bruno consumiu 120 → **tenho 120 a receber**.
    - Alheia: Ana e Bruno se acertam entre si; eu não participo.
    """
    eu = _usuario(db_session, "Eu", "eu@example.com")
    ana = _usuario(db_session, "Ana", "ana@example.com")
    bruno = _usuario(db_session, "Bruno", "bruno@example.com")

    casa = _workspace(db_session, "Casa", ana)
    _entra(db_session, casa, ana, WorkspaceRole.owner)
    _entra(db_session, casa, eu)
    _despesa(db_session, casa, pagador=ana, valor="200.00", divisao=[(ana, "100.00"), (eu, "100.00")])

    # Sou OWNER na Viagem: é o caso que prova que o recorte pessoal não afrouxa
    # com o cargo — mesmo com acesso completo, a visão global só mostra o que me
    # envolve.
    viagem = _workspace(db_session, "Viagem", eu)
    _entra(db_session, viagem, eu, WorkspaceRole.owner)
    _entra(db_session, viagem, bruno)
    _despesa(db_session, viagem, pagador=eu, valor="300.00", divisao=[(eu, "180.00"), (bruno, "120.00")])

    alheia = _workspace(db_session, "Alheia", ana)
    _entra(db_session, alheia, ana, WorkspaceRole.owner)
    _entra(db_session, alheia, bruno)
    _despesa(db_session, alheia, pagador=ana, valor="80.00", divisao=[(ana, "40.00"), (bruno, "40.00")])

    token = create_access_token(data={"sub": str(eu.id)})
    return {
        "eu": eu, "ana": ana, "bruno": bruno,
        "casa": casa, "viagem": viagem, "alheia": alheia,
        "headers": {"Cookie": f"access_token={token}"},
    }


# --- /me/debts ---------------------------------------------------------------

def test_saldos_ficam_agrupados_e_nao_se_compensam(cenario, override_get_session):
    """Devo 100 numa casa e tenho 120 a receber noutra: dois grupos, zero netting.

    Se algum dia isto virar um único "saldo líquido de 20 a receber", o app estará
    dizendo que a dívida com a Ana foi paga pelo que o Bruno me deve.
    """
    resp = client.get("/api/v1/me/debts", headers=cenario["headers"])
    assert resp.status_code == 200
    data = resp.json()

    assert Decimal(data["to_pay"]) == Decimal("100.00")
    assert Decimal(data["to_receive"]) == Decimal("120.00")
    assert "net" not in data  # compensar entre casas é proibido (ADR 0020)

    grupos = {g["workspace_name"]: g for g in data["by_workspace"]}
    assert set(grupos) == {"Casa", "Viagem"}

    assert Decimal(grupos["Casa"]["to_pay"]) == Decimal("100.00")
    assert Decimal(grupos["Casa"]["to_receive"]) == Decimal("0.00")
    assert Decimal(grupos["Viagem"]["to_receive"]) == Decimal("120.00")
    assert Decimal(grupos["Viagem"]["to_pay"]) == Decimal("0.00")


def test_casa_alheia_nao_aparece(cenario, override_get_session):
    resp = client.get("/api/v1/me/debts", headers=cenario["headers"])
    nomes = {g["workspace_name"] for g in resp.json()["by_workspace"]}
    assert "Alheia" not in nomes


def test_divida_entre_terceiros_nao_vaza_para_a_visao_global(cenario, db_session, override_get_session):
    """Sou OWNER da Viagem — acesso completo — e mesmo assim a linha Ana↔Bruno
    não aparece aqui. `/me/*` é a visão da pessoa; terceiros são assunto da tela
    da casa."""
    ana, bruno, eu = cenario["ana"], cenario["bruno"], cenario["eu"]
    _entra(db_session, cenario["viagem"], ana)
    _despesa(
        db_session, cenario["viagem"],
        pagador=ana, valor="60.00", divisao=[(ana, "0.00"), (bruno, "60.00")],
    )

    resp = client.get("/api/v1/me/debts", headers=cenario["headers"])
    grupos = {g["workspace_name"]: g for g in resp.json()["by_workspace"]}
    partes = {
        (linha["debtor_id"], linha["creditor_id"])
        for linha in grupos["Viagem"]["net_debts"]
    }
    assert all(eu.id in par for par in partes)
    assert (bruno.id, ana.id) not in partes

    # A mesma dívida CONTINUA visível na tela da casa, para quem tem acesso
    # completo — é o que justifica as duas telas conviverem.
    da_casa = client.get(
        f"/api/v1/workspaces/{cenario['viagem'].id}/debts", headers=cenario["headers"]
    ).json()
    assert any(
        d["debtor_id"] == bruno.id and d["creditor_id"] == ana.id for d in da_casa
    )


def test_linhas_trazem_o_nome_de_quem_deve_e_de_quem_recebe(cenario, override_get_session):
    """A tela global não tem uma casa só de onde buscar `/{ws}/members`."""
    data = client.get("/api/v1/me/debts", headers=cenario["headers"]).json()
    casa = next(g for g in data["by_workspace"] if g["workspace_name"] == "Casa")
    linha = casa["net_debts"][0]
    assert linha["debtor_name"] == "Eu"
    assert linha["creditor_name"] == "Ana"


def test_papel_da_casa_decide_se_pode_registrar(cenario, override_get_session):
    """`can_write` é o mesmo gate de `require_role(member)` do POST de acerto —
    um botão que sempre falha com 403 é pior que um botão ausente."""
    data = client.get("/api/v1/me/debts", headers=cenario["headers"]).json()
    grupos = {g["workspace_name"]: g for g in data["by_workspace"]}
    assert grupos["Casa"]["role"] == "member"
    assert grupos["Casa"]["can_write"] is True
    assert grupos["Viagem"]["role"] == "owner"
    assert grupos["Viagem"]["can_write"] is True


def test_viewer_nao_pode_registrar(cenario, db_session, override_get_session):
    membro = db_session.exec(
        select(WorkspaceMembership)
        .where(WorkspaceMembership.workspace_id == cenario["casa"].id)
        .where(WorkspaceMembership.user_id == cenario["eu"].id)
    ).one()
    membro.role = WorkspaceRole.viewer
    db_session.add(membro)
    db_session.commit()

    data = client.get("/api/v1/me/debts", headers=cenario["headers"]).json()
    casa = next(g for g in data["by_workspace"] if g["workspace_name"] == "Casa")
    assert casa["can_write"] is False


def test_casa_sem_cotacao_fica_fora_do_total_mas_aparece_na_moeda_dela(
    cenario, db_session, override_get_session
):
    """A regra do ADR 0006 com o acréscimo desta onda: omitir do TOTAL, sim;
    sumir da tela, não. Dizer "você deve R$ 0,00" a quem deve USD 90 é pior que
    não somar."""
    eu, bruno = cenario["eu"], cenario["bruno"]
    fora = _workspace(db_session, "Exterior", bruno, moeda="USD")
    _entra(db_session, fora, bruno, WorkspaceRole.owner)
    _entra(db_session, fora, eu)
    _despesa(
        db_session, fora,
        pagador=bruno, valor="180.00", divisao=[(bruno, "90.00"), (eu, "90.00")],
        moeda="USD",
    )

    data = client.get("/api/v1/me/debts", headers=cenario["headers"]).json()

    # Total NÃO absorveu os 90 estrangeiros
    assert Decimal(data["to_pay"]) == Decimal("100.00")

    grupo = next(g for g in data["by_workspace"] if g["workspace_name"] == "Exterior")
    assert grupo["converted"] is False
    assert grupo["base_currency"] == "USD"
    assert Decimal(grupo["to_pay"]) == Decimal("90.00")

    excluidas = {e["workspace_name"]: e for e in data["excluded_workspaces"]}
    assert "Exterior" in excluidas
    assert excluidas["Exterior"]["base_currency"] == "USD"
    assert Decimal(excluidas["Exterior"]["to_pay"]) == Decimal("90.00")


def test_sem_workspace_nenhum_responde_vazio(db_session, override_get_session):
    solitario = _usuario(db_session, "Só", "so@example.com")
    token = create_access_token(data={"sub": str(solitario.id)})
    resp = client.get("/api/v1/me/debts", headers={"Cookie": f"access_token={token}"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["by_workspace"] == []
    assert Decimal(data["to_pay"]) == Decimal("0.00")


def test_barra_final_nao_redireciona(cenario, override_get_session):
    """307 do Starlette perde o cookie e a resposta vira 401 sem explicação."""
    resp = client.get("/api/v1/me/debts/", headers=cenario["headers"], follow_redirects=False)
    assert resp.status_code == 200
    resp2 = client.get(
        "/api/v1/me/settlements/", headers=cenario["headers"], follow_redirects=False
    )
    assert resp2.status_code == 200


def test_exige_autenticacao(override_get_session):
    assert client.get("/api/v1/me/debts").status_code == 401
    assert client.get("/api/v1/me/settlements").status_code == 401
    assert client.get("/api/v1/me/debts/monthly").status_code == 401


# --- /me/debts/monthly -------------------------------------------------------

def test_mes_traz_uma_secao_por_casa_com_os_nomes(cenario, override_get_session):
    resp = client.get(f"/api/v1/me/debts/monthly?month={MES}", headers=cenario["headers"])
    assert resp.status_code == 200
    data = resp.json()
    assert data["month"] == MES

    grupos = {g["workspace_name"]: g for g in data["by_workspace"]}
    assert set(grupos) == {"Casa", "Viagem"}

    casa = grupos["Casa"]
    assert len(casa["expenses"]) == 1
    assert Decimal(casa["totals"]["total"]) == Decimal("200.00")
    # `people` substitui o /{ws}/members que a tela da casa consulta
    nomes = {p["user_name"] for p in casa["people"]}
    assert {"Eu", "Ana"} <= nomes


def test_acerto_do_mes_aparece_no_retrato_com_os_nomes(cenario, db_session, override_get_session):
    """Acerto amarrado a um `billing_month` entra no ledger daquele mês.

    A linha "Fulano pagou X a Beltrano" precisa dos DOIS nomes, e nenhum deles
    vem do ledger — vêm de `people`, que é montado a partir de tudo que o ledger
    cita. Se a coleta de ids esquecer os acertos, a tela imprime "Membro #3".
    """
    eu, ana = cenario["eu"], cenario["ana"]
    db_session.add(Settlement(
        workspace_id=cenario["casa"].id, from_user_id=eu.id, to_user_id=ana.id,
        amount=Decimal("30.00"), billing_month=MES, created_by_user_id=eu.id,
    ))
    db_session.commit()

    data = client.get(
        f"/api/v1/me/debts/monthly?month={MES}", headers=cenario["headers"]
    ).json()
    casa = next(g for g in data["by_workspace"] if g["workspace_name"] == "Casa")

    assert len(casa["settlements"]) == 1
    assert Decimal(casa["settled_total"]) == Decimal("30.00")
    nomes = {p["user_id"]: p["user_name"] for p in casa["people"]}
    assert nomes[eu.id] == "Eu"
    assert nomes[ana.id] == "Ana"
    # E o acerto abate a dívida do mês: de 100 sobram 70.
    assert Decimal(casa["net_debts"][0]["amount"]) == Decimal("70.00")


def test_mes_sem_movimento_nao_vira_secao(cenario, override_get_session):
    data = client.get(
        "/api/v1/me/debts/monthly?month=2026-01", headers=cenario["headers"]
    ).json()
    assert data["by_workspace"] == []


def test_mes_invalido_e_400(cenario, override_get_session):
    resp = client.get("/api/v1/me/debts/monthly?month=xx", headers=cenario["headers"])
    assert resp.status_code == 400


def test_moeda_invalida_e_400(cenario, override_get_session):
    assert client.get(
        "/api/v1/me/debts?currency=NOTACURRENCY", headers=cenario["headers"]
    ).status_code == 400


# --- /me/settlements ---------------------------------------------------------

def test_historico_soma_as_casas_e_diz_de_qual_veio(cenario, db_session, override_get_session):
    eu, ana, bruno = cenario["eu"], cenario["ana"], cenario["bruno"]
    db_session.add(Settlement(
        workspace_id=cenario["casa"].id, from_user_id=eu.id, to_user_id=ana.id,
        amount=Decimal("40.00"), created_by_user_id=eu.id,
    ))
    db_session.add(Settlement(
        workspace_id=cenario["viagem"].id, from_user_id=bruno.id, to_user_id=eu.id,
        amount=Decimal("20.00"), created_by_user_id=eu.id,
    ))
    db_session.commit()

    data = client.get("/api/v1/me/settlements", headers=cenario["headers"]).json()
    por_casa = {i["workspace_name"]: i for i in data["items"]}
    assert set(por_casa) == {"Casa", "Viagem"}

    assert por_casa["Casa"]["direction"] == "sent"
    assert por_casa["Casa"]["counterparty_name"] == "Ana"
    assert por_casa["Casa"]["currency"] == "BRL"

    assert por_casa["Viagem"]["direction"] == "received"
    assert por_casa["Viagem"]["counterparty_name"] == "Bruno"


def test_historico_ignora_acerto_entre_terceiros(cenario, db_session, override_get_session):
    """Mesmo sendo owner da Viagem: o histórico global é o MEU histórico."""
    ana, bruno = cenario["ana"], cenario["bruno"]
    _entra(db_session, cenario["viagem"], ana)
    db_session.add(Settlement(
        workspace_id=cenario["viagem"].id, from_user_id=bruno.id, to_user_id=ana.id,
        amount=Decimal("15.00"), created_by_user_id=ana.id,
    ))
    db_session.commit()

    data = client.get("/api/v1/me/settlements", headers=cenario["headers"]).json()
    assert data["items"] == []


def test_historico_nomeia_a_casa_de_que_eu_ja_sai(cenario, db_session, override_get_session):
    """Sair de um workspace é permitido depois de quitar o saldo. A casa continua
    existindo, e o histórico tem de continuar dizendo o nome dela.

    A primeira versão montava os nomes a partir das casas de que sou membro HOJE,
    então todo o histórico daquela virava "Casa removida" — um rótulo falso sobre
    um workspace vivo, e um link quebrado para a tela dele.
    """
    eu, ana = cenario["eu"], cenario["ana"]
    db_session.add(Settlement(
        workspace_id=cenario["casa"].id, from_user_id=eu.id, to_user_id=ana.id,
        amount=Decimal("40.00"), created_by_user_id=eu.id,
    ))
    db_session.commit()

    membro = db_session.exec(
        select(WorkspaceMembership)
        .where(WorkspaceMembership.workspace_id == cenario["casa"].id)
        .where(WorkspaceMembership.user_id == eu.id)
    ).one()
    db_session.delete(membro)
    db_session.commit()

    data = client.get("/api/v1/me/settlements", headers=cenario["headers"]).json()
    assert [i["workspace_name"] for i in data["items"]] == ["Casa"]


def test_historico_diz_quantos_acertos_existem_alem_da_pagina(
    cenario, db_session, override_get_session
):
    """Truncar histórico financeiro em silêncio é o mesmo defeito do `or ZERO`:
    a tela mostraria as primeiras linhas como se fossem todas."""
    eu, ana = cenario["eu"], cenario["ana"]
    for _ in range(3):
        db_session.add(Settlement(
            workspace_id=cenario["casa"].id, from_user_id=eu.id, to_user_id=ana.id,
            amount=Decimal("10.00"), created_by_user_id=eu.id,
        ))
    db_session.commit()

    data = client.get("/api/v1/me/settlements?limit=2", headers=cenario["headers"]).json()
    assert len(data["items"]) == 2
    assert data["total"] == 3


def test_mensal_nao_promete_moeda_que_nao_converte(cenario, override_get_session):
    """Cada seção é uma casa, na moeda dela. Um `currency` no topo diria que os
    números estão numa moeda em que eles não estão."""
    data = client.get(
        f"/api/v1/me/debts/monthly?month={MES}", headers=cenario["headers"]
    ).json()
    assert "currency" not in data
    assert {g["base_currency"] for g in data["by_workspace"]} == {"BRL"}


def test_mes_aparece_mesmo_com_tudo_quitado(cenario, db_session, override_get_session):
    """Quitar o mês não pode fazer o retrato dele sumir.

    `/me/debts` (saldo consolidado) e `/me/debts/monthly` (retrato do mês) são
    consultas independentes: uma casa sem saldo pendente ainda tem despesas no
    mês, e "tudo acertado ✅" é informação, não motivo para esconder a seção.
    """
    resp = client.post(
        f"/api/v1/workspaces/{cenario['casa'].id}/settlements",
        headers=cenario["headers"],
        json={
            "from_user_id": cenario["eu"].id,
            "to_user_id": cenario["ana"].id,
            "amount": "100.00",
        },
    )
    assert resp.status_code == 200, resp.text

    consolidado = client.get("/api/v1/me/debts", headers=cenario["headers"]).json()
    assert not any(g["workspace_name"] == "Casa" for g in consolidado["by_workspace"])

    mensal = client.get(
        f"/api/v1/me/debts/monthly?month={MES}", headers=cenario["headers"]
    ).json()
    casa = next(g for g in mensal["by_workspace"] if g["workspace_name"] == "Casa")
    assert len(casa["expenses"]) == 1


def test_historico_ignora_acerto_desfeito(cenario, db_session, override_get_session):
    eu, ana = cenario["eu"], cenario["ana"]
    db_session.add(Settlement(
        workspace_id=cenario["casa"].id, from_user_id=eu.id, to_user_id=ana.id,
        amount=Decimal("40.00"), created_by_user_id=eu.id,
        deleted_at=datetime.now(UTC),
    ))
    db_session.commit()
    data = client.get("/api/v1/me/settlements", headers=cenario["headers"]).json()
    assert data["items"] == []


def test_acerto_registrado_pela_casa_abate_o_saldo_global(cenario, db_session, override_get_session):
    """A ponta que amarra as duas telas: a escrita continua sendo do workspace, e
    o efeito dela tem de aparecer aqui."""
    antes = client.get("/api/v1/me/debts", headers=cenario["headers"]).json()
    assert Decimal(antes["to_pay"]) == Decimal("100.00")

    resp = client.post(
        f"/api/v1/workspaces/{cenario['casa'].id}/settlements",
        headers=cenario["headers"],
        json={
            "from_user_id": cenario["eu"].id,
            "to_user_id": cenario["ana"].id,
            "amount": "40.00",
        },
    )
    assert resp.status_code == 200, resp.text

    depois = client.get("/api/v1/me/debts", headers=cenario["headers"]).json()
    assert Decimal(depois["to_pay"]) == Decimal("60.00")

    historico = client.get("/api/v1/me/settlements", headers=cenario["headers"]).json()
    assert len(historico["items"]) == 1
    assert historico["items"][0]["workspace_name"] == "Casa"
