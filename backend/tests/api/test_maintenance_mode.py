"""Modo manutenção: o site pausa para todo mundo, menos para quem vai despausá-lo.

A propriedade que este arquivo protege é a de não se trancar do lado de fora. Um
modo manutenção que bloqueie `/auth/login` ou `/admin/settings` transforma um
botão de "pausar por 10 minutos" numa viagem ao `docker compose exec` — que é
precisamente a situação que a área administrativa existe para eliminar.
"""
import pytest
from fastapi.testclient import TestClient

from app.core.jwt import create_access_token
from app.main import app
from app.models.user import PlatformRole, User
from app.services import app_settings

client = TestClient(app)


def _cria(db, nome, email, papel=PlatformRole.user):
    user = User(name=nome, email=email, password_hash="hash", platform_role=papel)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _headers(user):
    return {"Cookie": f"access_token={create_access_token(data={'sub': str(user.id)})}"}


@pytest.fixture(name="elenco")
def elenco_fixture(db_session, override_get_session):
    elenco = {
        "comum": _cria(db_session, "Comum", "comum@example.com"),
        "admin": _cria(db_session, "Admin", "admin@example.com", PlatformRole.admin),
    }
    yield elenco
    app_settings.invalidate_cache()


def _liga(db, ligado=True):
    app_settings.set_value(db, "maintenance_mode", ligado)
    db.commit()


def test_desligado_todo_mundo_passa(elenco, db_session):
    _liga(db_session, False)
    assert client.get("/api/v1/notifications", headers=_headers(elenco["comum"])).status_code == 200


def test_ligado_usuario_comum_recebe_503(elenco, db_session):
    _liga(db_session)
    resp = client.get("/api/v1/notifications", headers=_headers(elenco["comum"]))
    assert resp.status_code == 503
    assert "manutenção" in resp.json()["error"]["message"]


def test_ligado_administrador_continua_usando(elenco, db_session):
    _liga(db_session)
    assert client.get("/api/v1/notifications", headers=_headers(elenco["admin"])).status_code == 200


def test_o_healthcheck_do_container_nao_pode_cair(elenco, db_session):
    """Sem esta liberação, ligar a manutenção faria o Docker considerar o backend
    doente e reiniciá-lo em laço — a pausa derrubaria o serviço."""
    _liga(db_session)
    assert client.get("/api/v1/health").status_code == 200


def test_o_admin_precisa_conseguir_entrar(elenco, db_session):
    """`/auth/*` fica no ar: é por onde o administrador faz login para desligar."""
    _liga(db_session)
    resp = client.get("/api/v1/auth/me", headers=_headers(elenco["admin"]))
    assert resp.status_code == 200


def test_a_area_administrativa_continua_no_ar(elenco, db_session):
    """É onde fica o botão de desligar."""
    _liga(db_session)
    assert client.get(
        "/api/v1/admin/settings", headers=_headers(elenco["admin"])
    ).status_code == 200


def test_o_administrador_consegue_desligar_de_dentro_da_manutencao(elenco, db_session):
    """O caminho completo de recuperação, que é a razão de tudo acima existir."""
    _liga(db_session)
    assert client.get("/api/v1/notifications", headers=_headers(elenco["comum"])).status_code == 503

    resp = client.put(
        "/api/v1/admin/settings",
        json={"valores": {"maintenance_mode": False}},
        headers=_headers(elenco["admin"]),
    )
    assert resp.status_code == 200
    assert client.get("/api/v1/notifications", headers=_headers(elenco["comum"])).status_code == 200


def test_sem_sessao_durante_a_manutencao_tambem_e_503(elenco, db_session):
    """"Não consegui provar que é admin" e "não é admin" levam ao mesmo lugar."""
    _liga(db_session)
    assert client.get("/api/v1/notifications").status_code == 503
