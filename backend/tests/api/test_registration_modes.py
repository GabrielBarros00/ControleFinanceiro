"""O portão de cadastro: aberto, por convite, fechado — e o impasse do banco vazio.

Este é o único arquivo da suíte que exercita o padrão de PRODUÇÃO
(`invite_only`). Todos os outros usam a fixture `cadastro_aberto_por_padrao` do
conftest, que abre a porta explicitamente porque usam `/auth/register` como
atalho para fabricar usuários. Aqui cada teste grava o próprio modo.
"""
from datetime import datetime, timedelta, UTC

import pytest
from fastapi.testclient import TestClient
from sqlmodel import select

from app.core.config import settings
from app.main import app
from app.models.registration_invite import RegistrationInvite
from app.models.user import PlatformRole, User
from app.models.workspace import (
    FinancialAccess, InviteStatus, Workspace, WorkspaceInvite, WorkspaceRole,
)
from app.services import app_settings

client = TestClient(app)


def _modo(db, valor):
    app_settings.set_value(db, "registration_mode", valor)
    db.commit()


def _cadastra(email="novo@example.com", token=None, nome="Novo"):
    corpo = {"name": nome, "email": email, "password": "senha123"}
    if token:
        corpo["invite_token"] = token
    return client.post("/api/v1/auth/register", json=corpo)


@pytest.fixture(name="ambiente")
def ambiente_fixture(db_session, override_get_session):
    return db_session


# --------------------------------------------------------------------------
# Os três modos
# --------------------------------------------------------------------------

def test_modo_aberto_deixa_qualquer_um_entrar(ambiente):
    _modo(ambiente, app_settings.RegistrationMode.open)
    assert _cadastra().status_code == 200


def test_modo_por_convite_recusa_sem_token(ambiente):
    _modo(ambiente, app_settings.RegistrationMode.invite_only)
    resp = _cadastra()
    assert resp.status_code == 403
    assert "convite" in resp.json()["error"]["message"].lower()


def test_modo_fechado_recusa_ate_com_convite_valido(ambiente):
    convite = RegistrationInvite(expires_at=datetime.now(UTC) + timedelta(days=7))
    ambiente.add(convite)
    ambiente.commit()
    ambiente.refresh(convite)

    _modo(ambiente, app_settings.RegistrationMode.closed)
    resp = _cadastra(token=convite.token)
    assert resp.status_code == 403
    assert "fechado" in resp.json()["error"]["message"].lower()


# --------------------------------------------------------------------------
# Convite de cadastro
# --------------------------------------------------------------------------

def _convite(db, **kwargs):
    kwargs.setdefault("expires_at", datetime.now(UTC) + timedelta(days=7))
    convite = RegistrationInvite(**kwargs)
    db.add(convite)
    db.commit()
    db.refresh(convite)
    return convite


def test_convite_valido_deixa_entrar_e_marca_o_uso(ambiente):
    convite = _convite(ambiente)
    _modo(ambiente, app_settings.RegistrationMode.invite_only)

    assert _cadastra(token=convite.token).status_code == 200
    ambiente.refresh(convite)
    assert convite.uses == 1
    assert convite.status == InviteStatus.accepted


def test_convite_de_uso_unico_nao_serve_duas_vezes(ambiente):
    convite = _convite(ambiente)
    _modo(ambiente, app_settings.RegistrationMode.invite_only)

    assert _cadastra("um@example.com", convite.token).status_code == 200
    assert _cadastra("dois@example.com", convite.token).status_code == 403


def test_convite_de_link_respeita_o_teto_de_usos(ambiente):
    convite = _convite(ambiente, max_uses=2)
    _modo(ambiente, app_settings.RegistrationMode.invite_only)

    assert _cadastra("um@example.com", convite.token).status_code == 200
    assert _cadastra("dois@example.com", convite.token).status_code == 200
    assert _cadastra("tres@example.com", convite.token).status_code == 403


def test_convite_expirado_nao_serve(ambiente):
    convite = _convite(ambiente, expires_at=datetime.now(UTC) - timedelta(hours=1))
    _modo(ambiente, app_settings.RegistrationMode.invite_only)
    assert _cadastra(token=convite.token).status_code == 403


def test_convite_revogado_nao_serve(ambiente):
    convite = _convite(ambiente, status=InviteStatus.revoked)
    _modo(ambiente, app_settings.RegistrationMode.invite_only)
    assert _cadastra(token=convite.token).status_code == 403


def test_convite_nominal_so_vale_para_o_endereco_convidado(ambiente):
    """O link vazado num grupo de mensagens não pode virar cadastro aberto para
    quem o encontrar."""
    convite = _convite(ambiente, email="convidada@example.com")
    _modo(ambiente, app_settings.RegistrationMode.invite_only)

    assert _cadastra("outra@example.com", convite.token).status_code == 403
    assert _cadastra("convidada@example.com", convite.token).status_code == 200


def test_token_inventado_nao_serve(ambiente):
    _modo(ambiente, app_settings.RegistrationMode.invite_only)
    assert _cadastra(token="nao-existe-este-token").status_code == 403


# --------------------------------------------------------------------------
# O convite de WORKSPACE também autoriza a criar conta
# --------------------------------------------------------------------------

def test_convite_de_workspace_serve_de_permissao_para_cadastrar(ambiente):
    """Quem foi chamado para dentro de uma casa obviamente pode existir no site;
    exigir um segundo convite, de outra espécie, para a mesma pessoa só produz
    gente travada na tela de cadastro."""
    dono = User(name="Dono", email="dono@example.com", password_hash="hash")
    ws = Workspace(name="Casa")
    ambiente.add_all([dono, ws])
    ambiente.commit()
    ambiente.refresh(dono)
    ambiente.refresh(ws)

    convite = WorkspaceInvite(
        workspace_id=ws.id,
        email="convidada@example.com",
        role=WorkspaceRole.member,
        financial_access=FinancialAccess.involved_only,
        invited_by_user_id=dono.id,
        expires_at=datetime.now(UTC) + timedelta(days=7),
    )
    ambiente.add(convite)
    ambiente.commit()
    ambiente.refresh(convite)

    _modo(ambiente, app_settings.RegistrationMode.invite_only)
    assert _cadastra("convidada@example.com", convite.token).status_code == 200


# --------------------------------------------------------------------------
# Bootstrap: o impasse do banco vazio
# --------------------------------------------------------------------------

def test_superadmin_entra_sem_convite_no_banco_vazio(ambiente, monkeypatch):
    """Sem esta janela, um deploy novo é um impasse: o cadastro é por convite,
    não há quem convide, e a única saída seria SQL na mão dentro do container."""
    monkeypatch.setattr(settings, "SUPERADMIN_EMAIL", "dono@example.com")
    _modo(ambiente, app_settings.RegistrationMode.invite_only)

    resp = _cadastra("dono@example.com")
    assert resp.status_code == 200
    assert resp.json()["platform_role"] == "superadmin"


def test_a_janela_de_bootstrap_fecha_depois_do_primeiro(ambiente, monkeypatch):
    """Ela fecha sozinha: vale só enquanto NÃO existir superadmin nenhum."""
    monkeypatch.setattr(settings, "SUPERADMIN_EMAIL", "dono@example.com")
    _modo(ambiente, app_settings.RegistrationMode.invite_only)
    assert _cadastra("dono@example.com").status_code == 200

    # Mesmo e-mail, segunda tentativa: agora existe superadmin, a janela fechou.
    # 403 e não 400 ("já cadastrado") de propósito: o portão roda ANTES da
    # checagem de duplicidade, então um endereço existente e um inexistente
    # respondem igual. Sem essa ordem, quem não tem convite ainda conseguiria
    # descobrir quem tem conta no site comparando as mensagens de erro.
    assert _cadastra("dono@example.com").status_code == 403

    # E ninguém mais entra sem convite.
    assert _cadastra("penetra@example.com").status_code == 403


def test_o_portao_nao_deixa_enumerar_contas(ambiente):
    """E-mail cadastrado e e-mail inexistente respondem exatamente igual."""
    _modo(ambiente, app_settings.RegistrationMode.open)
    assert _cadastra("existe@example.com").status_code == 200

    _modo(ambiente, app_settings.RegistrationMode.invite_only)
    existente = _cadastra("existe@example.com")
    inexistente = _cadastra("nao-existe@example.com")
    assert existente.status_code == inexistente.status_code == 403
    assert existente.json() == inexistente.json()


def test_bootstrap_nao_vale_para_outro_email(ambiente, monkeypatch):
    monkeypatch.setattr(settings, "SUPERADMIN_EMAIL", "dono@example.com")
    _modo(ambiente, app_settings.RegistrationMode.invite_only)
    assert _cadastra("impostor@example.com").status_code == 403


def test_sem_superadmin_configurado_nao_ha_janela(ambiente, monkeypatch):
    monkeypatch.setattr(settings, "SUPERADMIN_EMAIL", None)
    _modo(ambiente, app_settings.RegistrationMode.invite_only)
    assert _cadastra("qualquer@example.com").status_code == 403


def test_cadastro_comum_nasce_sem_poder_de_plataforma(ambiente):
    _modo(ambiente, app_settings.RegistrationMode.open)
    resp = _cadastra()
    assert resp.status_code == 200
    assert resp.json()["platform_role"] == "user"


# --------------------------------------------------------------------------
# A política que a TELA consulta
# --------------------------------------------------------------------------

def _politica():
    return client.get("/api/v1/auth/registration-policy").json()


def test_politica_de_cadastro_e_publica(ambiente):
    _modo(ambiente, app_settings.RegistrationMode.invite_only)
    p = _politica()
    assert p["mode"] == "invite_only"
    assert p["aceita_cadastro"] is True
    assert p["exige_convite"] is True


def test_politica_anuncia_o_primeiro_acesso_enquanto_nao_ha_dono(ambiente, monkeypatch):
    """O campo que torna um deploy novo utilizável PELO NAVEGADOR.

    Sem ele a tela escondia o formulário sempre que o modo exigia convite — e num
    site recém-instalado ninguém tem convite nem existe quem o emita. O primeiro
    acesso descrito no SETUP.md era impossível pela interface, e o único contorno
    era descobrir que `/register?invite=qualquer-coisa` passava.
    """
    monkeypatch.setattr(settings, "SUPERADMIN_EMAIL", "dono@example.com")
    _modo(ambiente, app_settings.RegistrationMode.invite_only)
    assert _politica()["primeiro_acesso"] is True

    # Criada a conta, a janela fecha — e a tela volta a exigir convite.
    assert _cadastra("dono@example.com").status_code == 200
    assert _politica()["primeiro_acesso"] is False


def test_politica_nao_anuncia_primeiro_acesso_sem_superadmin_configurado(
    ambiente, monkeypatch
):
    """Sem `SUPERADMIN_EMAIL` não há janela nenhuma — anunciá-la seria oferecer
    um formulário que o servidor recusa para todo mundo."""
    monkeypatch.setattr(settings, "SUPERADMIN_EMAIL", None)
    _modo(ambiente, app_settings.RegistrationMode.invite_only)
    assert _politica()["primeiro_acesso"] is False


def test_politica_nao_revela_o_email_do_administrador(ambiente, monkeypatch):
    """`primeiro_acesso` responde "este site já tem dono?", não "quem é ele"."""
    monkeypatch.setattr(settings, "SUPERADMIN_EMAIL", "dono-secreto@example.com")
    _modo(ambiente, app_settings.RegistrationMode.invite_only)
    corpo = client.get("/api/v1/auth/registration-policy").text
    assert "dono-secreto" not in corpo


# --------------------------------------------------------------------------
# O MESMO portão vale para o Google (ADR 0026)
# --------------------------------------------------------------------------
#
# Este bloco existe porque o portão nasceu com uma porta dos fundos: o callback
# do OAuth criava usuário sem consultar `assert_pode_cadastrar`. Um site em
# `invite_only` — ou até em `closed` — continuava aceitando qualquer pessoa que
# tivesse uma conta Google e alcançasse a URL, que é exatamente o defeito que o
# portão existe para fechar. Autenticar prova QUEM é a pessoa; não responde se
# ela pode existir neste site.

@pytest.fixture(name="google")
def google_fixture(monkeypatch):
    from app.api.routes import auth as auth_module
    from app.core.jwt import create_purpose_token

    monkeypatch.setattr(settings, "GOOGLE_CLIENT_ID", "cid")
    monkeypatch.setattr(settings, "GOOGLE_CLIENT_SECRET", "csecret")
    monkeypatch.setattr(settings, "GOOGLE_REDIRECT_URI", "http://x/callback")

    def entrar(email="google@example.com", invite=None, nome="Pessoa Google"):
        monkeypatch.setattr(
            auth_module, "_fetch_google_user",
            lambda code: {"email": email, "name": nome, "email_verified": True},
        )
        nonce = "n" * 24
        state = create_purpose_token(
            {"nonce": nonce, "invite": invite}, purpose="oauth_state",
            expires_delta=timedelta(minutes=10),
        )
        client.cookies.set("oauth_state", nonce)
        resp = client.get(
            f"/api/v1/auth/google/callback?code=x&state={state}", follow_redirects=False
        )
        client.cookies.clear()
        return resp

    return entrar


def _criou(db, email) -> bool:
    return db.exec(select(User).where(User.email == email)).first() is not None


def test_google_nao_cria_conta_com_cadastro_por_convite(ambiente, google):
    _modo(ambiente, app_settings.RegistrationMode.invite_only)
    resp = google("penetra@example.com")
    assert "error=cadastro_por_convite" in resp.headers["location"]
    assert not _criou(ambiente, "penetra@example.com")


def test_google_nao_cria_conta_com_cadastro_fechado(ambiente, google):
    _modo(ambiente, app_settings.RegistrationMode.closed)
    resp = google("penetra@example.com")
    assert "error=cadastro_por_convite" in resp.headers["location"]
    assert not _criou(ambiente, "penetra@example.com")


def test_google_cria_conta_com_cadastro_aberto(ambiente, google):
    _modo(ambiente, app_settings.RegistrationMode.open)
    resp = google("livre@example.com")
    assert resp.headers["location"] == settings.FRONTEND_URL
    assert _criou(ambiente, "livre@example.com")


def test_google_aceita_convite_carregado_no_state(ambiente, google):
    """O token viaja assinado dentro do `state` — o Google não devolve query
    string nossa, e sem carregá-lo o convite se perderia no salto."""
    convite = RegistrationInvite(
        email="convidada@example.com", expires_at=datetime.now(UTC) + timedelta(days=7)
    )
    ambiente.add(convite)
    ambiente.commit()
    ambiente.refresh(convite)
    token = convite.token

    _modo(ambiente, app_settings.RegistrationMode.invite_only)
    resp = google("convidada@example.com", invite=token)
    assert resp.headers["location"] == settings.FRONTEND_URL
    assert _criou(ambiente, "convidada@example.com")

    ambiente.expire_all()
    usado = ambiente.exec(
        select(RegistrationInvite).where(RegistrationInvite.token == token)
    ).one()
    assert usado.uses == 1
    assert usado.status == InviteStatus.accepted


def test_google_recusa_convite_de_outro_endereco(ambiente, google):
    """Convite nominal continua nominal: o e-mail que o Google confirmou tem de
    ser o convidado, senão o link vazado num grupo vira cadastro aberto."""
    convite = RegistrationInvite(
        email="convidada@example.com", expires_at=datetime.now(UTC) + timedelta(days=7)
    )
    ambiente.add(convite)
    ambiente.commit()
    ambiente.refresh(convite)

    _modo(ambiente, app_settings.RegistrationMode.invite_only)
    resp = google("outra@example.com", invite=convite.token)
    assert "error=cadastro_por_convite" in resp.headers["location"]
    assert not _criou(ambiente, "outra@example.com")


def test_google_honra_a_janela_de_bootstrap(ambiente, google, monkeypatch):
    """O `SUPERADMIN_EMAIL` pode ser um endereço do Google — obrigá-lo a criar
    senha local só para nascer superadmin seria exigência sem motivo."""
    monkeypatch.setattr(settings, "SUPERADMIN_EMAIL", "dono@gmail.com")
    _modo(ambiente, app_settings.RegistrationMode.invite_only)

    resp = google("dono@gmail.com")
    assert resp.headers["location"] == settings.FRONTEND_URL
    dono = ambiente.exec(select(User).where(User.email == "dono@gmail.com")).one()
    assert dono.platform_role == PlatformRole.superadmin

    # E fecha: o segundo endereço do Google não entra.
    assert "error=cadastro_por_convite" in google("outro@gmail.com").headers["location"]


def test_google_de_quem_ja_tem_conta_entra_com_o_cadastro_fechado(ambiente, google):
    """O portão é de CADASTRO, não de login: quem já existe continua entrando
    mesmo depois de o administrador fechar a porta da frente."""
    _modo(ambiente, app_settings.RegistrationMode.open)
    assert google("antiga@example.com").headers["location"] == settings.FRONTEND_URL

    _modo(ambiente, app_settings.RegistrationMode.closed)
    assert google("antiga@example.com").headers["location"] == settings.FRONTEND_URL


def test_google_entra_por_convite_de_workspace_e_vira_membro(ambiente, google):
    """Mesmo consentimento do cadastro local: o token veio do link do convite,
    que o navegador levou até `/auth/google/login?invite=<token>`. Sem isto, quem
    clicasse no convite e usasse o botão do Google cairia num espaço vazio."""
    dona = User(name="Dona", email="dona@example.com", password_hash="x")
    ws = Workspace(name="Casa")
    ambiente.add_all([dona, ws])
    ambiente.commit()
    ambiente.refresh(dona)
    ambiente.refresh(ws)
    convite = WorkspaceInvite(
        workspace_id=ws.id, email="vizinha@example.com", role=WorkspaceRole.member,
        financial_access=FinancialAccess.involved_only, invited_by_user_id=dona.id,
        expires_at=datetime.now(UTC) + timedelta(days=7),
    )
    ambiente.add(convite)
    ambiente.commit()
    ambiente.refresh(convite)

    _modo(ambiente, app_settings.RegistrationMode.invite_only)
    resp = google("vizinha@example.com", invite=convite.token)
    assert resp.headers["location"] == settings.FRONTEND_URL

    from app.models.workspace import WorkspaceMembership
    nova = ambiente.exec(select(User).where(User.email == "vizinha@example.com")).one()
    membro = ambiente.exec(
        select(WorkspaceMembership).where(
            WorkspaceMembership.workspace_id == ws.id,
            WorkspaceMembership.user_id == nova.id,
        )
    ).first()
    assert membro is not None, "o convite de workspace não virou membership"


# --------------------------------------------------------------------------
# Quem pode convidar, e quantos
# --------------------------------------------------------------------------

def _login(db, email, papel=PlatformRole.user):
    from app.core.jwt import create_access_token
    user = User(name="Alguem", email=email, password_hash="hash", platform_role=papel)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user, {"Cookie": f"access_token={create_access_token(data={'sub': str(user.id)})}"}


def test_usuario_comum_convida_quando_permitido(ambiente):
    _, headers = _login(ambiente, "membro@example.com")
    app_settings.set_value(ambiente, "who_can_invite", app_settings.WhoCanInvite.all_users)
    ambiente.commit()

    resp = client.post("/api/v1/me/registration-invites", json={}, headers=headers)
    assert resp.status_code == 201
    assert resp.json()["link"].endswith(resp.json()["token"])


def test_usuario_comum_nao_convida_quando_so_admin_pode(ambiente):
    _, headers = _login(ambiente, "membro@example.com")
    app_settings.set_value(ambiente, "who_can_invite", app_settings.WhoCanInvite.admins_only)
    ambiente.commit()

    resp = client.post("/api/v1/me/registration-invites", json={}, headers=headers)
    assert resp.status_code == 403


def test_admin_convida_mesmo_com_a_trava_de_usuario_comum(ambiente):
    _, headers = _login(ambiente, "admin@example.com", PlatformRole.admin)
    app_settings.set_value(ambiente, "who_can_invite", app_settings.WhoCanInvite.admins_only)
    ambiente.commit()

    assert client.post(
        "/api/v1/me/registration-invites", json={}, headers=headers
    ).status_code == 201


def test_cota_mensal_do_usuario_comum(ambiente):
    """Sem a cota, "cadastro por convite" é cadastro aberto com um passo a mais
    para quem quiser abusar."""
    _, headers = _login(ambiente, "membro@example.com")
    app_settings.set_value(ambiente, "user_invite_quota_per_month", 2)
    ambiente.commit()

    assert client.post("/api/v1/me/registration-invites", json={}, headers=headers).status_code == 201
    assert client.post("/api/v1/me/registration-invites", json={}, headers=headers).status_code == 201
    resp = client.post("/api/v1/me/registration-invites", json={}, headers=headers)
    assert resp.status_code == 429


def test_admin_nao_tem_cota(ambiente):
    _, headers = _login(ambiente, "admin@example.com", PlatformRole.admin)
    app_settings.set_value(ambiente, "user_invite_quota_per_month", 1)
    ambiente.commit()

    for _ in range(3):
        assert client.post(
            "/api/v1/me/registration-invites", json={}, headers=headers
        ).status_code == 201


def test_convite_emitido_pelo_admin_faz_o_cadastro_passar(ambiente):
    """O caminho ponta a ponta: o admin gera, a pessoa entra."""
    _, headers = _login(ambiente, "admin@example.com", PlatformRole.admin)
    criado = client.post(
        "/api/v1/admin/registration-invites",
        json={"email": "convidada@example.com"},
        headers=headers,
    )
    assert criado.status_code == 201

    _modo(ambiente, app_settings.RegistrationMode.invite_only)
    assert _cadastra("convidada@example.com", criado.json()["token"]).status_code == 200


def test_convite_revogado_pelo_admin_deixa_de_servir(ambiente):
    _, headers = _login(ambiente, "admin@example.com", PlatformRole.admin)
    criado = client.post("/api/v1/admin/registration-invites", json={}, headers=headers).json()

    assert client.delete(
        f"/api/v1/admin/registration-invites/{criado['id']}", headers=headers
    ).status_code == 200

    _modo(ambiente, app_settings.RegistrationMode.invite_only)
    assert _cadastra(token=criado["token"]).status_code == 403
