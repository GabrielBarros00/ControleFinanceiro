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


# --------------------------------------------------------------------------
# Pausado é pausado: não nascem contas
# --------------------------------------------------------------------------
#
# `/auth/*` é liberado no middleware para o administrador CONSEGUIR ENTRAR e
# desligar o modo. Isso deixava passar de carona o CADASTRO: com
# `registration_mode=open`, o site pausado continuava fazendo nascer usuário,
# workspace e categorias semeadas — e a pessoa entrava para receber 503 em tudo
# que importa. Quem decide agora é `assert_pode_cadastrar`, que é o ponto por
# onde os dois caminhos (formulário e Google) já passavam.

def _cadastra(email="novo@example.com"):
    return client.post(
        "/api/v1/auth/register",
        json={"name": "Novo", "email": email, "password": "senha123"},
    )


def test_cadastro_pelo_formulario_nao_passa_na_manutencao(elenco, db_session):
    # Com a manutenção desligada o mesmo cadastro entra: o que barra é o modo,
    # não outra coisa do ambiente.
    _liga(db_session, False)
    assert _cadastra("antes@example.com").status_code == 200

    _liga(db_session)
    resp = _cadastra("durante@example.com")
    assert resp.status_code == 503
    assert "manutenção" in resp.json()["error"]["message"]


def test_cadastro_pelo_google_nao_passa_na_manutencao(elenco, db_session, monkeypatch):
    """A outra porta. Ela é a razão de a checagem morar no serviço, e não numa
    dependência de `/auth/register`: o callback do OAuth não passa por lá."""
    from datetime import timedelta

    from app.api.routes import auth as auth_module
    from app.core.config import settings
    from app.core.jwt import create_purpose_token

    monkeypatch.setattr(settings, "GOOGLE_CLIENT_ID", "cid")
    monkeypatch.setattr(settings, "GOOGLE_CLIENT_SECRET", "csecret")
    monkeypatch.setattr(settings, "GOOGLE_REDIRECT_URI", "http://x/callback")
    monkeypatch.setattr(
        auth_module, "_fetch_google_user",
        lambda code: {"email": "google@example.com", "name": "G", "email_verified": True},
    )
    nonce = "n" * 24
    state = create_purpose_token(
        {"nonce": nonce, "invite": None}, purpose="oauth_state",
        expires_delta=timedelta(minutes=10),
    )

    _liga(db_session)
    client.cookies.set("oauth_state", nonce)
    resp = client.get(
        f"/api/v1/auth/google/callback?code=x&state={state}", follow_redirects=False
    )
    client.cookies.clear()

    assert "error=cadastro_por_convite" in resp.headers["location"]
    from sqlmodel import select
    assert db_session.exec(
        select(User).where(User.email == "google@example.com")
    ).first() is None


def test_o_primeiro_acesso_atravessa_a_manutencao(elenco, db_session, monkeypatch):
    """A isenção que impede o impasse.

    Um deploy que subisse com a manutenção ligada — e ela é uma linha no banco,
    que sobrevive a `docker compose down` — não pode trancar o próprio dono do
    lado de fora: sem conta, ninguém entra na área administrativa; sem entrar,
    ninguém desliga a manutenção.
    """
    from app.core.config import settings

    monkeypatch.setattr(settings, "SUPERADMIN_EMAIL", "dono@example.com")
    _liga(db_session)

    assert _cadastra("qualquer-um@example.com").status_code == 503
    resp = _cadastra("dono@example.com")
    assert resp.status_code == 200
    assert resp.json()["platform_role"] == "superadmin"
