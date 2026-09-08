"""Desfazer a exclusão de um lançamento — e dizer o que não volta.

## Por que dá para desfazer

A exclusão de despesa sempre foi **soft** (`deleted_at`): o dado continua no
banco e some das listas. Só não havia caminho de volta. Excluir a linha errada
— que é o erro mais fácil de cometer numa lista de trinta linhas parecidas —
significava relançar tudo à mão: título, valor, data, pagadores, divisão.

## O que NÃO volta, e por que o teste insiste nisso

Excluir apaga os **anexos** de verdade (`_purge_attachments`): o recibo não tem
soft delete, e mantê-lo ocuparia cota para sempre num lançamento que a interface
não alcança. Ou seja: restaurar devolve a despesa **sem os recibos**.

Um "desfazer" que devolve 90% do que se perdeu e finge ter devolvido 100% é pior
do que não ter desfazer nenhum — a pessoa confia, não confere, e descobre a
falta quando precisa do comprovante. Por isso a exclusão passa a **contar** os
anexos removidos e a devolver esse número: é com ele que a tela avisa.
"""
import datetime
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.core.jwt import create_access_token
from app.main import app
from app.models.attachment import Attachment
from app.models.transaction import Transaction
from app.models.user import User
from app.models.workspace import (
    FinancialAccess,
    Workspace,
    WorkspaceMembership,
    WorkspaceRole,
)

client = TestClient(app)

QUANDO = datetime.datetime(2026, 9, 10, 12, 0, tzinfo=datetime.UTC)


@pytest.fixture(name="cena")
def cena_fixture(db_session: Session, override_get_session):
    dono = User(name="Dono", email="dono@desfazer.com", password_hash="h")
    outro = User(name="Outro", email="outro@desfazer.com", password_hash="h")
    ws = Workspace(name="Casa", base_currency="BRL")
    db_session.add_all([dono, outro, ws])
    db_session.commit()
    db_session.add_all([
        WorkspaceMembership(workspace_id=ws.id, user_id=dono.id, role=WorkspaceRole.owner),
        # Acesso COMPLETO de propósito: assim ele enxerga a despesa, e o que o
        # barra é a permissão de escrita — que é o assunto do teste. Com acesso
        # restrito viria 404 (anti-enumeração, correto) e o teste estaria
        # medindo visibilidade em vez de permissão.
        WorkspaceMembership(
            workspace_id=ws.id, user_id=outro.id, role=WorkspaceRole.member,
            financial_access=FinancialAccess.full_workspace,
        ),
    ])
    tx = Transaction(
        title="Mercado", total_amount=Decimal("120.00"), currency="BRL",
        transaction_date=QUANDO, billing_month="2026-09", status="confirmed",
        workspace_id=ws.id, created_by_user_id=dono.id,
    )
    db_session.add(tx)
    db_session.commit()
    db_session.refresh(tx)
    return {
        "db": db_session, "ws": ws, "tx": tx, "dono_id": dono.id,
        "dono": {"Cookie": f"access_token={create_access_token({'sub': str(dono.id)})}"},
        "outro": {"Cookie": f"access_token={create_access_token({'sub': str(outro.id)})}"},
    }


def _excluir(cena, quem="dono"):
    return client.delete(
        f"/api/v1/workspaces/{cena['ws'].id}/transactions/{cena['tx'].id}",
        headers=cena[quem],
    )


def _restaurar(cena, quem="dono"):
    return client.post(
        f"/api/v1/workspaces/{cena['ws'].id}/transactions/{cena['tx'].id}/restore",
        headers=cena[quem],
    )


def _lista(cena, quem="dono"):
    r = client.get(
        f"/api/v1/workspaces/{cena['ws'].id}/transactions/?month=2026-09",
        headers=cena[quem],
    )
    assert r.status_code == 200, r.text
    return [t["title"] for t in r.json()["items"]]


def test_a_linha_volta_para_a_lista(cena):
    assert _excluir(cena).status_code == 200
    assert _lista(cena) == []

    r = _restaurar(cena)

    assert r.status_code == 200, r.text
    assert _lista(cena) == ["Mercado"], (
        "restaurar não devolveu a despesa à lista — o desfazer não desfaz"
    )


def test_diz_quantos_anexos_a_exclusao_levou(cena):
    """O número que a tela usa para avisar que o recibo não volta."""
    db = cena["db"]
    db.add(Attachment(
        workspace_id=cena["ws"].id, transaction_id=cena["tx"].id,
        filename="nota.pdf", content_type="application/pdf",
        # Usuário REAL, e não `1`: no SQLite a chave estrangeira não é cobrada e
        # o teste passava; no Postgres ela é, e o insert estourava. É a mesma
        # divergência de schema que este projeto já registrou — só o Postgres
        # reprova o dado inventado.
        size_bytes=1024, storage_key="k/nota.pdf", uploaded_by_user_id=cena["dono_id"],
    ))
    db.commit()

    corpo = _excluir(cena).json()

    assert corpo.get("attachments_removed") == 1, (
        "a exclusão não informa quantos anexos levou junto — sem isso a tela "
        "oferece um 'desfazer' que devolve menos do que promete"
    )


def test_sem_anexo_nao_inventa_aviso(cena):
    """Contrapeso: o aviso é exceção, não decoração de toda exclusão."""
    assert _excluir(cena).json().get("attachments_removed") == 0


def test_restaurar_e_idempotente(cena):
    """Dois cliques no mesmo 'desfazer' não podem virar erro na cara da pessoa."""
    _excluir(cena)
    assert _restaurar(cena).status_code == 200
    assert _restaurar(cena).status_code == 200
    assert _lista(cena) == ["Mercado"]


def test_quem_nao_pode_excluir_tambem_nao_restaura(cena):
    """O restore anda com a mesma permissão do delete — senão ele é a porta dos
    fundos para reviver o lançamento de outra pessoa."""
    _excluir(cena)

    r = _restaurar(cena, quem="outro")

    assert r.status_code == 403, (
        f"membro comum restaurou lançamento alheio (status {r.status_code})"
    )


def test_lancamento_de_outro_espaco_nao_e_alcancavel(cena, db_session: Session):
    outra = Workspace(name="Vizinha", base_currency="BRL")
    db_session.add(outra)
    db_session.commit()

    _excluir(cena)
    r = client.post(
        f"/api/v1/workspaces/{outra.id}/transactions/{cena['tx'].id}/restore",
        headers=cena["dono"],
    )
    assert r.status_code in (403, 404)


def test_o_anexo_nao_volta_com_a_despesa(cena):
    """O que o aviso da tela precisa estar dizendo — verificado, não suposto."""
    db = cena["db"]
    db.add(Attachment(
        workspace_id=cena["ws"].id, transaction_id=cena["tx"].id,
        filename="nota.pdf", content_type="application/pdf",
        # Usuário REAL, e não `1`: no SQLite a chave estrangeira não é cobrada e
        # o teste passava; no Postgres ela é, e o insert estourava. É a mesma
        # divergência de schema que este projeto já registrou — só o Postgres
        # reprova o dado inventado.
        size_bytes=1024, storage_key="k/nota.pdf", uploaded_by_user_id=cena["dono_id"],
    ))
    db.commit()

    _excluir(cena)
    _restaurar(cena)

    sobrando = db.exec(
        select(Attachment).where(Attachment.transaction_id == cena["tx"].id)
    ).all()
    assert sobrando == [], (
        "o anexo voltou — então o aviso da tela está mentindo, e é o aviso que "
        "precisa mudar, não este teste"
    )
