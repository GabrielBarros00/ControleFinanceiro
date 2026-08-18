"""Transferência de propriedade do espaço e a trava do administrador (ADR 0028).

A propriedade era um estado TERMINAL: a API recusa promover a owner, recusa
alterar o papel de quem já é, recusa removê-lo e recusa que ele saia. Somado a um
`admin.py` que nem importava `Workspace`, desativar o dono produzia um espaço
**permanentemente indelével** — a única conta que poderia apagá-lo deixava de
autenticar e ninguém podia herdar o papel.

O que está sendo provado aqui é o par: existe saída (a transferência), e não
existe caminho que crie o beco (a trava nas DUAS rotas do admin).
"""
import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.core.jwt import create_access_token
from app.main import app
from app.models.audit import AuditLog
from app.models.user import PlatformRole, User
from app.models.workspace import (
    FinancialAccess,
    Workspace,
    WorkspaceMembership,
    WorkspaceRole,
)

client = TestClient(app)


def _headers(user):
    return {"Cookie": f"access_token={create_access_token(data={'sub': str(user.id)})}"}


def _cria_usuario(db, nome, email, papel=PlatformRole.user, ativo=True):
    user = User(
        name=nome, email=email, password_hash="hash",
        platform_role=papel, is_active=ativo,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture(name="casa")
def casa_fixture(db_session: Session, override_get_session):
    """Um espaço com dono (Ana), um admin (Bruno) e um member (Célia)."""
    ana = _cria_usuario(db_session, "Ana", "ana@example.com")
    bruno = _cria_usuario(db_session, "Bruno", "bruno@example.com")
    celia = _cria_usuario(db_session, "Célia", "celia@example.com")

    ws = Workspace(name="Casa da Praia", created_by_user_id=ana.id)
    db_session.add(ws)
    db_session.commit()
    db_session.refresh(ws)
    db_session.add_all([
        WorkspaceMembership(
            workspace_id=ws.id, user_id=ana.id, role=WorkspaceRole.owner,
            financial_access=FinancialAccess.full_workspace,
        ),
        WorkspaceMembership(workspace_id=ws.id, user_id=bruno.id, role=WorkspaceRole.admin),
        WorkspaceMembership(workspace_id=ws.id, user_id=celia.id, role=WorkspaceRole.member),
    ])
    db_session.commit()
    return {"ws": ws, "ana": ana, "bruno": bruno, "celia": celia}


def _rota(casa, alvo):
    return f"/api/v1/workspaces/{casa['ws'].id}/members/{casa[alvo].id}/transfer-ownership"


# --- O caminho feliz -------------------------------------------------------

def test_transferencia_troca_os_dois_papeis(db_session: Session, casa):
    """O alvo vira owner com acesso completo; o antigo dono vira admin.

    Ele não é expulso — perde o poder terminal sobre o espaço, não o espaço.
    """
    resp = client.post(_rota(casa, "celia"), headers=_headers(casa["ana"]))
    assert resp.status_code == 200, resp.text
    assert resp.json()["role"] == "owner"

    papeis = {
        m.user_id: (m.role, m.financial_access)
        for m in db_session.exec(
            select(WorkspaceMembership).where(
                WorkspaceMembership.workspace_id == casa["ws"].id
            )
        ).all()
    }
    assert papeis[casa["celia"].id] == (WorkspaceRole.owner, FinancialAccess.full_workspace)
    assert papeis[casa["ana"].id][0] == WorkspaceRole.admin
    # Um dono, nunca dois
    assert [p[0] for p in papeis.values()].count(WorkspaceRole.owner) == 1


def test_transferencia_nao_reescreve_quem_criou(db_session: Session, casa):
    """`created_by_user_id` é registro histórico: quem criou continua tendo criado."""
    client.post(_rota(casa, "celia"), headers=_headers(casa["ana"]))
    db_session.refresh(casa["ws"])
    assert casa["ws"].created_by_user_id == casa["ana"].id


def test_transferencia_muda_quem_a_api_exibe_como_dono(casa):
    """O rótulo da tela segue a membership — é o ponto do ADR 0028."""
    antes = client.get(f"/api/v1/workspaces/{casa['ws'].id}", headers=_headers(casa["ana"])).json()
    assert (antes["owner_user_id"], antes["owner_name"]) == (casa["ana"].id, "Ana")

    client.post(_rota(casa, "celia"), headers=_headers(casa["ana"]))

    depois = client.get(f"/api/v1/workspaces/{casa['ws'].id}", headers=_headers(casa["ana"])).json()
    assert (depois["owner_user_id"], depois["owner_name"]) == (casa["celia"].id, "Célia")


def test_transferencia_move_o_direito_de_excluir(casa):
    """A prova de que o poder foi junto, e não só o rótulo."""
    client.post(_rota(casa, "celia"), headers=_headers(casa["ana"]))

    # O antigo dono agora é admin — e admin não exclui espaço
    assert client.delete(
        f"/api/v1/workspaces/{casa['ws'].id}", headers=_headers(casa["ana"])
    ).status_code == 403
    assert client.delete(
        f"/api/v1/workspaces/{casa['ws'].id}", headers=_headers(casa["celia"])
    ).status_code == 200


def test_transferencia_deixa_trilha_explicita(db_session: Session, casa):
    """Duas linhas soltas de membership não dizem "houve transferência"."""
    client.post(_rota(casa, "celia"), headers=_headers(casa["ana"]))

    linha = db_session.exec(
        select(AuditLog).where(AuditLog.resource_type == "WorkspaceOwnership")
    ).first()
    assert linha is not None
    assert linha.resource_id == casa["ws"].id
    assert linha.user_id == casa["ana"].id
    assert linha.old_values["dono"] == casa["ana"].id
    assert linha.new_values["dono"] == casa["celia"].id


def test_antigo_dono_pode_sair_depois_de_transferir(casa):
    """A saída que não existia: o dono não podia sair nem transferir."""
    assert client.post(
        f"/api/v1/workspaces/{casa['ws'].id}/leave", headers=_headers(casa["ana"])
    ).status_code == 400

    client.post(_rota(casa, "celia"), headers=_headers(casa["ana"]))

    assert client.post(
        f"/api/v1/workspaces/{casa['ws'].id}/leave", headers=_headers(casa["ana"])
    ).status_code == 200


# --- As recusas ------------------------------------------------------------

def test_so_o_dono_transfere(casa):
    """Admin é o papel mais alto abaixo do dono — e nem ele passa."""
    resp = client.post(_rota(casa, "celia"), headers=_headers(casa["bruno"]))
    assert resp.status_code == 403


def test_recusa_transferir_para_conta_inativa(db_session: Session, casa):
    """Transferir para quem não consegue entrar recria o problema que a rota resolve."""
    casa["celia"].is_active = False
    db_session.add(casa["celia"])
    db_session.commit()

    resp = client.post(_rota(casa, "celia"), headers=_headers(casa["ana"]))
    assert resp.status_code == 400
    assert "ativa" in resp.json()["error"]["message"]


def test_recusa_transferir_para_quem_nao_e_membro(db_session: Session, casa):
    forasteiro = _cria_usuario(db_session, "Fora", "fora@example.com")
    resp = client.post(
        f"/api/v1/workspaces/{casa['ws'].id}/members/{forasteiro.id}/transfer-ownership",
        headers=_headers(casa["ana"]),
    )
    assert resp.status_code == 404


def test_recusa_transferir_para_si_mesmo(casa):
    resp = client.post(_rota(casa, "ana"), headers=_headers(casa["ana"]))
    assert resp.status_code == 400


# --- A trava do administrador de plataforma --------------------------------

@pytest.fixture(name="operador")
def operador_fixture(db_session: Session, override_get_session):
    return _cria_usuario(db_session, "Super", "super@example.com", PlatformRole.superadmin)


def test_admin_nao_desativa_dono_de_espaco(casa, operador):
    """Sem esta trava, o espaço ficava indelével: a única conta que pode apagá-lo
    deixa de autenticar e ninguém pode herdar o papel."""
    resp = client.patch(
        f"/api/v1/admin/users/{casa['ana'].id}",
        json={"is_active": False},
        headers=_headers(operador),
    )
    assert resp.status_code == 409
    assert "Casa da Praia" in resp.json()["error"]["message"]


def test_admin_nao_exclui_dono_de_espaco(casa, operador):
    """A MESMA trava na outra porta: um portão com um só ponto de chamada
    guardado é um portão aberto."""
    resp = client.delete(
        f"/api/v1/admin/users/{casa['ana'].id}", headers=_headers(operador)
    )
    assert resp.status_code == 409


def test_admin_desativa_depois_da_transferencia(casa, operador):
    """A trava aponta o caminho, e o caminho funciona."""
    client.post(_rota(casa, "celia"), headers=_headers(casa["ana"]))

    resp = client.patch(
        f"/api/v1/admin/users/{casa['ana'].id}",
        json={"is_active": False},
        headers=_headers(operador),
    )
    assert resp.status_code == 200, resp.text


def test_trava_ignora_espaco_ja_excluido(db_session: Session, casa, operador):
    """Espaço soft-deletado não tem o que administrar — não pode prender a conta
    do dono para sempre."""
    from datetime import datetime, UTC
    casa["ws"].deleted_at = datetime.now(UTC)
    db_session.add(casa["ws"])
    db_session.commit()

    resp = client.patch(
        f"/api/v1/admin/users/{casa['ana'].id}",
        json={"is_active": False},
        headers=_headers(operador),
    )
    assert resp.status_code == 200, resp.text


def test_admin_desativa_quem_nao_e_dono(casa, operador):
    """A trava é sobre PROPRIEDADE, não sobre participar de um espaço."""
    resp = client.patch(
        f"/api/v1/admin/users/{casa['bruno'].id}",
        json={"is_active": False},
        headers=_headers(operador),
    )
    assert resp.status_code == 200, resp.text
