"""Editar recorrência é planejar, revisar e aplicar (ADR 0030).

O que estes testes fixam é a queixa de uso: **mudar o dia da recorrência não movia
nada**. `sync_unpaid_instances` reaplicava título, valor, moeda, divisão e
categoria, e nunca a data — "todo dia 5" virava "todo dia 20" e os lançamentos já
criados ficavam no dia 5 para sempre. Excluir ou desativar o template também não
tocava em lançamento nenhum, e a confirmação dizia isso numa linha em cinza.

Somado a um `<select>` de escopo no rodapé de um modal longo, sem contagem e sem
lista, o resultado era a leitura correta de que "alterar a recorrência não muda
nada no Geral".

O eixo do arquivo: **o que o preview promete é o que o apply faz**, e nada é
tocado sem estar na lista de escolhidos.
"""
from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.core.jwt import create_access_token
from app.domain.dates import today_local
from app.main import app
from app.models.recurring import RecurrenceFrequency, RecurringExpense
from app.models.transaction import Transaction, TransactionStatus
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMembership, WorkspaceRole

client = TestClient(app)


@pytest.fixture(name="cena")
def cena_fixture(db_session: Session, override_get_session):
    user = User(name="Dona", email="revisao@t.com", password_hash="h")
    db_session.add(user)
    ws = Workspace(name="Casa", base_currency="BRL")
    db_session.add(ws)
    db_session.flush()
    db_session.add(
        WorkspaceMembership(workspace_id=ws.id, user_id=user.id, role=WorkspaceRole.owner)
    )
    # Dia 1, e não dia 5: a ocorrência precisa estar SEMPRE no passado. Com o dia
    # 5, este arquivo inteiro ficava vermelho nos quatro primeiros dias de cada mês
    # — a ocorrência nascia `pending` (ainda não venceu) e o consumo, que só conta
    # o realizado, dava zero. O teste falhava por causa do calendário, não do
    # código, e num dia em que ninguém estava olhando.
    template = RecurringExpense(
        title="Aluguel", base_amount=Decimal("1000.00"), currency="BRL",
        frequency=RecurrenceFrequency.monthly, day_of_month=1,
        workspace_id=ws.id, created_by_user_id=user.id, payer_user_id=user.id,
    )
    db_session.add(template)
    db_session.commit()
    db_session.refresh(template)

    token = create_access_token(data={"sub": str(user.id)})
    return {
        "ws_id": ws.id,
        "user_id": user.id,
        "template_id": template.id,
        "headers": {"Cookie": f"access_token={token}"},
        "db": db_session,
    }


def _materializa(cena):
    """A materialização é preguiçosa: roda ao abrir Lançamentos."""
    r = client.get(
        f"/api/v1/workspaces/{cena['ws_id']}/transactions/", headers=cena["headers"]
    )
    assert r.status_code == 200, r.text


def _preview(cena, **body):
    r = client.post(
        f"/api/v1/workspaces/{cena['ws_id']}/recurring/{cena['template_id']}/preview",
        json={"action": "update", **body},
        headers=cena["headers"],
    )
    assert r.status_code == 200, r.text
    return r.json()["items"]


def _instancias(cena):
    return cena["db"].exec(
        select(Transaction)
        .where(Transaction.recurring_expense_id == cena["template_id"])
        .order_by(Transaction.occurrence_date)
    ).all()


def _mes_atual() -> str:
    hoje = today_local()
    return f"{hoje.year:04d}-{hoje.month:02d}"


# --- 1. O preview diz o que vai acontecer ----------------------------------


def test_mudar_o_dia_planeja_um_MOVE(cena):
    """O achado: a data ficava congelada. Agora ela aparece no plano."""
    _materializa(cena)
    hoje = today_local()

    itens = _preview(cena, changes={"day_of_month": 20})
    do_mes = [i for i in itens if i["billing_month"] == _mes_atual()]
    assert len(do_mes) == 1
    assert do_mes[0]["action"] == "move"
    assert do_mes[0]["occurrence_date"] == f"{hoje.year:04d}-{hoje.month:02d}-01"
    assert do_mes[0]["new_occurrence_date"] == f"{hoje.year:04d}-{hoje.month:02d}-20"
    assert do_mes[0]["changes"]["date"]["to"] == f"{hoje.year:04d}-{hoje.month:02d}-20"


def test_mudar_o_valor_planeja_um_UPDATE_com_o_diff(cena):
    _materializa(cena)
    itens = _preview(cena, changes={"base_amount": "1200.00"})
    do_mes = [i for i in itens if i["billing_month"] == _mes_atual()]
    assert do_mes[0]["action"] == "update"
    # O diff é o que a pessoa reconhece na linha: de quanto para quanto.
    assert Decimal(do_mes[0]["changes"]["amount"]["from"]) == Decimal("1000.00")
    assert Decimal(do_mes[0]["changes"]["amount"]["to"]) == Decimal("1200.00")


def test_lancamento_pago_aparece_congelado_com_o_motivo(cena):
    """Ele não some da lista: a contagem da tela tem de bater com o extrato."""
    _materializa(cena)
    tx = _instancias(cena)[0]
    tx.status = TransactionStatus.paid
    cena["db"].add(tx)
    cena["db"].commit()

    itens = _preview(cena, changes={"day_of_month": 20})
    congelado = next(i for i in itens if i["transaction_id"] == tx.id)
    assert congelado["action"] == "none"
    assert congelado["frozen_reason"] == "já paga — não será alterada"


def test_desativar_planeja_CANCEL_das_ocorrencias(cena):
    """Desativar parava a geração e deixava o mês corrente intacto.

    Era metade da queixa de "excluí e nada mudou": a conta do mês continuava lá,
    confirmada e contando no Geral.
    """
    _materializa(cena)
    itens = _preview(cena, action="deactivate")
    do_mes = [i for i in itens if i["billing_month"] == _mes_atual()]
    assert do_mes[0]["action"] == "cancel"


def test_desde_recorta_o_plano(cena):
    """"Aplicar a partir de" — o filtro que a revisão oferece."""
    _materializa(cena)
    hoje = today_local()
    futuro = date(hoje.year + 1, 1, 1)
    itens = _preview(cena, changes={"day_of_month": 20}, since=futuro.isoformat())
    assert all(i["billing_month"] >= f"{futuro.year:04d}-01" for i in itens)


def test_preview_nao_escreve_nada(cena):
    """É o contrato do nome. Um `preview` que persiste é o pior tipo de defeito:
    a pessoa desiste no diálogo e a mudança já aconteceu."""
    _materializa(cena)
    antes = [(t.id, t.occurrence_date, t.total_amount) for t in _instancias(cena)]

    _preview(cena, changes={"day_of_month": 20, "base_amount": "9999.00"})
    cena["db"].expire_all()

    assert [(t.id, t.occurrence_date, t.total_amount) for t in _instancias(cena)] == antes
    template = cena["db"].get(RecurringExpense, cena["template_id"])
    assert template.day_of_month == 1, "o preview alterou o próprio template"


# --- 2. O apply faz só o que foi escolhido ---------------------------------


def _salva(cena, changes, **params):
    query = "&".join(
        f"{k}={v}" for k, vs in params.items() for v in (vs if isinstance(vs, list) else [vs])
    )
    r = client.put(
        f"/api/v1/workspaces/{cena['ws_id']}/recurring/{cena['template_id']}"
        + (f"?{query}" if query else ""),
        json=changes,
        headers=cena["headers"],
    )
    assert r.status_code == 200, r.text
    return r.json()


def test_aplicar_move_de_verdade(cena):
    _materializa(cena)
    hoje = today_local()
    tx = _instancias(cena)[0]

    _salva(cena, {"day_of_month": 20}, apply_to=tx.id)
    cena["db"].expire_all()

    movida = cena["db"].get(Transaction, tx.id)
    assert movida.occurrence_date == date(hoje.year, hoje.month, 20)
    # `billing_month` NÃO muda: a nova data é do mesmo mês, por construção.
    assert movida.billing_month == _mes_atual()
    # E o instante acompanha a data civil (ADR 0025) — meia-noite jogaria a
    # despesa para o dia 19 em fuso negativo.
    assert movida.transaction_date.date() in (
        date(hoje.year, hoje.month, 20), date(hoje.year, hoje.month, 21)
    )


def test_nao_escolhido_nao_e_tocado(cena):
    """A revisão é opt-in por linha: o que não foi marcado fica como está."""
    _materializa(cena)
    tx = _instancias(cena)[0]
    data_original = tx.occurrence_date

    # `apply_to` presente porém VAZIO seria indistinguível de ausente na query
    # string; o caminho testado aqui é o de escolher OUTRO id.
    _salva(cena, {"day_of_month": 20}, apply_to=999999)
    cena["db"].expire_all()

    assert cena["db"].get(Transaction, tx.id).occurrence_date == data_original


def test_pago_nao_e_movido_nem_quando_escolhido(cena):
    """Segunda linha de defesa: a trava roda de novo no apply, contra o banco.

    A lista da tela pode ter sido aberta há dez minutos; se alguém pagou a conta
    nesse meio-tempo, o id ainda está marcado e o servidor precisa recusar.
    """
    _materializa(cena)
    tx = _instancias(cena)[0]
    data_original = tx.occurrence_date
    tx.status = TransactionStatus.paid
    cena["db"].add(tx)
    cena["db"].commit()

    _salva(cena, {"day_of_month": 20}, apply_to=tx.id)
    cena["db"].expire_all()

    assert cena["db"].get(Transaction, tx.id).occurrence_date == data_original


def test_desativar_com_escolha_cancela_o_lancamento(cena):
    """A resposta para "desativei e o mês continuou contando"."""
    _materializa(cena)
    tx = _instancias(cena)[0]

    _salva(cena, {"is_active": False}, apply_to=tx.id)
    cena["db"].expire_all()

    assert cena["db"].get(Transaction, tx.id).status == TransactionStatus.cancelled


def test_excluir_pode_cancelar_os_lancamentos_escolhidos(cena):
    """Excluir a recorrência nunca apagou lançamento nenhum — agora oferece."""
    _materializa(cena)
    tx = _instancias(cena)[0]

    r = client.delete(
        f"/api/v1/workspaces/{cena['ws_id']}/recurring/{cena['template_id']}"
        f"?cancel_instance={tx.id}",
        headers=cena["headers"],
    )
    assert r.status_code == 200, r.text
    cena["db"].expire_all()

    cancelada = cena["db"].get(Transaction, tx.id)
    assert cancelada.status == TransactionStatus.cancelled
    # E continua desvinculada, como sempre foi (a FK não aceita o template morto).
    assert cancelada.recurring_expense_id is None


def test_excluir_sem_escolha_nao_toca_em_nada(cena):
    """O comportamento de sempre continua sendo o padrão."""
    _materializa(cena)
    tx = _instancias(cena)[0]

    r = client.delete(
        f"/api/v1/workspaces/{cena['ws_id']}/recurring/{cena['template_id']}",
        headers=cena["headers"],
    )
    assert r.status_code == 200, r.text
    cena["db"].expire_all()
    assert cena["db"].get(Transaction, tx.id).status == TransactionStatus.confirmed


def test_sem_apply_to_o_escopo_legado_continua_valendo(cena):
    """Quem chama a API antiga (sem revisão) não pode ver o comportamento mudar.

    Valor acompanha, data não — exatamente como antes do ADR 0030.
    """
    _materializa(cena)
    tx = _instancias(cena)[0]
    data_original = tx.occurrence_date

    _salva(cena, {"base_amount": "1500.00", "day_of_month": 20}, scope="future")
    cena["db"].expire_all()

    depois = cena["db"].get(Transaction, tx.id)
    assert depois.total_amount == Decimal("1500.00")
    assert depois.occurrence_date == data_original


# --- 3. O Seu mês enxerga a recorrência sozinho ----------------------------


def test_seu_mes_materializa_a_recorrencia(cena):
    """Sem abrir Lançamentos primeiro.

    A materialização preguiçosa não rodava em nenhuma rota de `/me`, então
    cadastrar uma recorrência e abrir o Seu mês mostrava o mês SEM ela — e a
    conclusão de que "a recorrência não alterou nada" era correta pelo que a
    tela mostrava.
    """
    assert _instancias(cena) == []

    r = client.get(f"/api/v1/me/overview?month={_mes_atual()}", headers=cena["headers"])
    assert r.status_code == 200, r.text

    cena["db"].expire_all()
    # Do MÊS pedido: o horizonte também materializa o mês seguinte (ADR 0034), e
    # o que este teste afirma é que abrir o Seu mês faz a recorrência aparecer.
    do_mes = [t for t in _instancias(cena) if t.billing_month == _mes_atual()]
    assert len(do_mes) == 1
    assert Decimal(r.json()["consumption"]) == Decimal("1000.00")
