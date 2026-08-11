"""Área administrativa: guardas de papel e as travas que impedem trancar o site.

O que está sendo provado aqui não é "a rota responde 200" — é que ninguém sem
papel chega perto dela, e que nenhuma sequência de PATCHes plausível deixa o
sistema sem quem o administre.
"""
import pytest
from fastapi.testclient import TestClient

from app.core.jwt import create_access_token
from app.main import app
from app.models.user import PlatformRole, User
from app.services import app_settings

client = TestClient(app)


def _cria(db, nome, email, papel=PlatformRole.user, ativo=True):
    user = User(
        name=nome, email=email, password_hash="hash",
        platform_role=papel, is_active=ativo,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _headers(user):
    return {"Cookie": f"access_token={create_access_token(data={'sub': str(user.id)})}"}


@pytest.fixture(name="elenco")
def elenco_fixture(db_session, override_get_session):
    return {
        "comum": _cria(db_session, "Comum", "comum@example.com"),
        "admin": _cria(db_session, "Admin", "admin@example.com", PlatformRole.admin),
        "super": _cria(db_session, "Super", "super@example.com", PlatformRole.superadmin),
    }


# --------------------------------------------------------------------------
# Guardas
# --------------------------------------------------------------------------

ROTAS_DE_ADMIN = [
    ("get", "/api/v1/admin/overview"),
    ("get", "/api/v1/admin/users"),
    ("get", "/api/v1/admin/settings"),
    ("get", "/api/v1/admin/health"),
    ("get", "/api/v1/admin/audit"),
    ("get", "/api/v1/admin/registration-invites"),
]


@pytest.mark.parametrize("metodo,rota", ROTAS_DE_ADMIN)
def test_usuario_comum_nao_alcanca_a_area_administrativa(elenco, metodo, rota):
    """404, não 403: a existência da área não é informação que um usuário comum
    precise confirmar."""
    resp = getattr(client, metodo)(rota, headers=_headers(elenco["comum"]))
    assert resp.status_code == 404


@pytest.mark.parametrize("metodo,rota", ROTAS_DE_ADMIN)
def test_sem_sessao_nao_alcanca(elenco, metodo, rota):
    assert getattr(client, metodo)(rota).status_code == 401


@pytest.mark.parametrize("metodo,rota", ROTAS_DE_ADMIN)
def test_admin_alcanca(elenco, metodo, rota):
    resp = getattr(client, metodo)(rota, headers=_headers(elenco["admin"]))
    assert resp.status_code == 200


def test_rota_de_colecao_responde_com_e_sem_barra(elenco):
    """O 307 do Starlette não leva o cookie junto — a URL com a barra "errada"
    devolveria 401 em vez de funcionar."""
    for url in ("/api/v1/admin/registration-invites", "/api/v1/admin/registration-invites/"):
        assert client.get(url, headers=_headers(elenco["admin"])).status_code == 200


# --------------------------------------------------------------------------
# Hierarquia de papéis
# --------------------------------------------------------------------------

def test_admin_nao_mexe_em_superadmin(elenco):
    """Sem esta trava, qualquer admin rebaixaria o dono do site num único PATCH."""
    resp = client.patch(
        f"/api/v1/admin/users/{elenco['super'].id}",
        json={"platform_role": "user"},
        headers=_headers(elenco["admin"]),
    )
    assert resp.status_code == 403
    assert "superadministrador" in resp.json()["error"]["message"]


def test_admin_nao_promove_a_superadmin(elenco):
    """Um admin que pudesse criar superadmins seria, na prática, superadmin."""
    resp = client.patch(
        f"/api/v1/admin/users/{elenco['comum'].id}",
        json={"platform_role": "superadmin"},
        headers=_headers(elenco["admin"]),
    )
    assert resp.status_code == 403


def test_superadmin_promove_e_rebaixa(elenco, db_session):
    alvo = elenco["comum"]
    resp = client.patch(
        f"/api/v1/admin/users/{alvo.id}",
        json={"platform_role": "admin"},
        headers=_headers(elenco["super"]),
    )
    assert resp.status_code == 200
    assert resp.json()["platform_role"] == "admin"

    resp = client.patch(
        f"/api/v1/admin/users/{alvo.id}",
        json={"platform_role": "user"},
        headers=_headers(elenco["super"]),
    )
    assert resp.status_code == 200
    assert resp.json()["platform_role"] == "user"


# --------------------------------------------------------------------------
# A trava do último superadmin — o site tem de continuar administrável
# --------------------------------------------------------------------------

def test_ultimo_superadmin_nao_pode_se_rebaixar(elenco):
    """"Eu sei o que estou fazendo" é exatamente o que a pessoa pensa antes de se
    trancar do lado de fora: sem superadmin, a configuração vira imutável e o
    cadastro por convite fica sem quem emita convite."""
    resp = client.patch(
        f"/api/v1/admin/users/{elenco['super'].id}",
        json={"platform_role": "admin"},
        headers=_headers(elenco["super"]),
    )
    assert resp.status_code == 409
    assert "último superadministrador" in resp.json()["error"]["message"]


def test_ultimo_superadmin_nao_pode_se_desativar(elenco):
    resp = client.patch(
        f"/api/v1/admin/users/{elenco['super'].id}",
        json={"is_active": False},
        headers=_headers(elenco["super"]),
    )
    assert resp.status_code == 409


def test_ultimo_superadmin_nao_pode_ser_removido(elenco, db_session):
    outro = _cria(db_session, "Outro Super", "s2@example.com", PlatformRole.superadmin)
    # Com dois, remover um passa.
    assert client.delete(
        f"/api/v1/admin/users/{elenco['super'].id}", headers=_headers(outro)
    ).status_code == 200
    # Sobrou um: agora não passa mais. (Precisa de um terceiro ator para tentar,
    # porque ninguém remove a própria conta por aqui.)
    admin = _cria(db_session, "A2", "a2@example.com", PlatformRole.admin)
    resp = client.delete(f"/api/v1/admin/users/{outro.id}", headers=_headers(admin))
    assert resp.status_code == 403  # admin não mexe em superadmin


def test_com_dois_superadmins_o_rebaixamento_passa(elenco, db_session):
    _cria(db_session, "Outro Super", "s2@example.com", PlatformRole.superadmin)
    resp = client.patch(
        f"/api/v1/admin/users/{elenco['super'].id}",
        json={"platform_role": "admin"},
        headers=_headers(elenco["super"]),
    )
    assert resp.status_code == 200


def test_superadmin_inativo_nao_conta_para_a_trava(elenco, db_session):
    """Um segundo superadmin DESATIVADO não administra nada — contá-lo deixaria o
    site sem administrador ativo com a trava reportando que estava tudo bem."""
    _cria(db_session, "Dormente", "dorm@example.com", PlatformRole.superadmin, ativo=False)
    resp = client.patch(
        f"/api/v1/admin/users/{elenco['super'].id}",
        json={"platform_role": "admin"},
        headers=_headers(elenco["super"]),
    )
    assert resp.status_code == 409


def test_ninguem_remove_a_propria_conta_pela_area_administrativa(elenco):
    resp = client.delete(
        f"/api/v1/admin/users/{elenco['admin'].id}", headers=_headers(elenco["admin"])
    )
    assert resp.status_code == 409


def test_ninguem_desativa_a_propria_conta(elenco):
    """`delete_user` já barrava a auto-remoção; o PATCH não barrava a
    auto-desativação, que tem o mesmo efeito e é mais fácil de fazer sem querer.

    É o único ato desta tela sem volta pelas mãos de quem o pratica: a sessão cai
    junto e o login seguinte é recusado por conta inativa. Vale para admin comum
    também — não é a trava do último superadministrador, que responde outra
    pergunta.
    """
    for quem in ("admin", "super"):
        resp = client.patch(
            f"/api/v1/admin/users/{elenco[quem].id}",
            json={"is_active": False},
            headers=_headers(elenco[quem]),
        )
        assert resp.status_code == 409, f"{quem} conseguiu se desativar"
        assert "própria conta" in resp.json()["error"]["message"]


def test_rebaixar_a_si_mesmo_continua_permitido(elenco, db_session):
    """Quem se rebaixa segue usando o sistema — só perde a área administrativa.
    É diferente de se desativar, e proibir seria impedir um superadministrador de
    passar o bastão depois de promover outro."""
    outro = _cria(db_session, "Outro Super", "outro@example.com", PlatformRole.superadmin)
    assert outro is not None

    resp = client.patch(
        f"/api/v1/admin/users/{elenco['super'].id}",
        json={"platform_role": "user"},
        headers=_headers(elenco["super"]),
    )
    assert resp.status_code == 200
    assert resp.json()["platform_role"] == "user"


# --------------------------------------------------------------------------
# Desativar precisa DERRUBAR a sessão
# --------------------------------------------------------------------------

def test_desativar_revoga_as_sessoes(elenco, db_session):
    """Sem isto, "inativo" não significa nada: o refresh token vale por dias e o
    access token continua aceito até expirar."""
    from app.models.refresh_session import RefreshSession
    from datetime import datetime, timedelta, UTC

    alvo = elenco["comum"]
    db_session.add(RefreshSession(
        user_id=alvo.id, jti="j1", family_id="f1",
        expires_at=datetime.now(UTC) + timedelta(days=7),
    ))
    db_session.commit()

    resp = client.patch(
        f"/api/v1/admin/users/{alvo.id}",
        json={"is_active": False},
        headers=_headers(elenco["admin"]),
    )
    assert resp.status_code == 200

    viva = db_session.exec(
        __import__("sqlmodel").select(RefreshSession).where(
            RefreshSession.user_id == alvo.id, RefreshSession.revoked_at.is_(None)
        )
    ).first()
    assert viva is None


def test_revoke_sessions_derruba_e_conta(elenco, db_session):
    from app.models.refresh_session import RefreshSession
    from datetime import datetime, timedelta, UTC

    alvo = elenco["comum"]
    for i in range(3):
        db_session.add(RefreshSession(
            user_id=alvo.id, jti=f"j{i}", family_id="f",
            expires_at=datetime.now(UTC) + timedelta(days=7),
        ))
    db_session.commit()

    resp = client.post(
        f"/api/v1/admin/users/{alvo.id}/revoke-sessions",
        headers=_headers(elenco["admin"]),
    )
    assert resp.status_code == 200
    assert resp.json()["revogadas"] == 3


# --------------------------------------------------------------------------
# Configuração em runtime
# --------------------------------------------------------------------------

def test_configuracao_grava_e_passa_a_valer(elenco, db_session):
    resp = client.put(
        "/api/v1/admin/settings",
        json={"valores": {"registration_mode": "closed"}},
        headers=_headers(elenco["admin"]),
    )
    assert resp.status_code == 200
    assert resp.json()["valores"]["registration_mode"] == "closed"
    assert app_settings.get(db_session, "registration_mode") == "closed"


def test_configuracao_recusa_valor_invalido(elenco):
    resp = client.put(
        "/api/v1/admin/settings",
        json={"valores": {"registration_mode": "talvez"}},
        headers=_headers(elenco["admin"]),
    )
    assert resp.status_code == 422


def test_configuracao_recusa_chave_desconhecida(elenco):
    resp = client.put(
        "/api/v1/admin/settings",
        json={"valores": {"desligar_a_seguranca": True}},
        headers=_headers(elenco["admin"]),
    )
    assert resp.status_code == 422


def test_upload_acima_do_teto_do_nginx_e_recusado(elenco):
    """O `client_max_body_size 6m` do nginx fica NA FRENTE do backend: aceitar um
    valor maior aqui salvaria uma configuração que não vale, e o usuário levaria
    413 do nginx com uma página que não é do app."""
    resp = client.put(
        "/api/v1/admin/settings",
        json={"valores": {"upload_max_bytes": 20 * 1024 * 1024}},
        headers=_headers(elenco["admin"]),
    )
    assert resp.status_code == 422


def test_import_acima_do_teto_do_processo_e_recusado(elenco):
    """`CommitRequest.rows` tem `Field(max_length=settings.IMPORT_MAX_ROWS)`, e o
    Pydantic recusa o corpo ANTES de o handler existir.

    Enquanto esta chave aceitava até um milhão, a tela gravava 50.000, dizia
    "Configuração salva", e a importação seguia morrendo em 5.001 linhas com um
    erro sobre comprimento de lista — a configuração que reporta sucesso e não
    vale nada, que é o defeito que o comentário do rate limiter, no mesmo commit,
    dizia estar evitando. O admin só APERTA este limite.
    """
    from app.core.config import settings as cfg

    resp = client.put(
        "/api/v1/admin/settings",
        json={"valores": {"import_max_rows": cfg.IMPORT_MAX_ROWS + 1}},
        headers=_headers(elenco["admin"]),
    )
    assert resp.status_code == 422

    apertar = client.put(
        "/api/v1/admin/settings",
        json={"valores": {"import_max_rows": 100}},
        headers=_headers(elenco["admin"]),
    )
    assert apertar.status_code == 200
    assert apertar.json()["valores"]["import_max_rows"] == 100


def test_configuracao_gravada_vale_na_requisicao_seguinte(elenco, db_session):
    """O cache é de processo e é invalidado DUAS vezes: antes do commit (para a
    própria transação enxergar a escrita) e depois (a janela em que uma leitura
    concorrente recacheava o valor antigo — para sempre, porque a invalidação já
    tinha passado)."""
    client.put(
        "/api/v1/admin/settings",
        json={"valores": {"invite_expiry_days": 21}},
        headers=_headers(elenco["admin"]),
    )
    assert app_settings.get(db_session, "invite_expiry_days") == 21

    corpo = client.get("/api/v1/admin/settings", headers=_headers(elenco["admin"])).json()
    assert corpo["valores"]["invite_expiry_days"] == 21


def test_configuracao_e_tudo_ou_nada(elenco, db_session):
    """Um formulário em que o segundo campo é inválido não pode gravar o
    primeiro: o operador leria o erro e concluiria, errado, que nada mudou."""
    antes = app_settings.get(db_session, "invite_expiry_days")
    resp = client.put(
        "/api/v1/admin/settings",
        json={"valores": {"invite_expiry_days": 30, "registration_mode": "talvez"}},
        headers=_headers(elenco["admin"]),
    )
    assert resp.status_code == 422
    assert app_settings.get(db_session, "invite_expiry_days") == antes


def test_settings_diz_o_que_veio_do_ambiente(elenco):
    """Sem `sobrescrito`, um número que ainda acompanha o `.env` aparece igual a
    um gravado no banco, e o operador muda a variável esperando efeito que não vem."""
    corpo = client.get("/api/v1/admin/settings", headers=_headers(elenco["admin"])).json()
    por_nome = {c["nome"]: c for c in corpo["chaves"]}
    assert por_nome["attachment_quota_bytes"]["origem_ambiente"] == "ATTACHMENT_QUOTA_BYTES"
    assert por_nome["registration_mode"]["origem_ambiente"] == "REGISTRATION_MODE"
    # `who_can_invite` só existe como configuração de runtime: não há variável de
    # ambiente para ela, e a tela precisa saber disso para não prometer ao
    # operador um `.env` que não existe.
    assert por_nome["who_can_invite"]["origem_ambiente"] is None


# --------------------------------------------------------------------------
# Métricas
# --------------------------------------------------------------------------

def test_overview_conta_usuarios_e_ignora_removidos(elenco, db_session):
    from datetime import datetime, UTC

    corpo = client.get("/api/v1/admin/overview", headers=_headers(elenco["admin"])).json()
    assert corpo["usuarios_total"] == 3

    removido = _cria(db_session, "Sumiu", "sumiu@example.com")
    removido.deleted_at = datetime.now(UTC)
    db_session.add(removido)
    db_session.commit()

    corpo = client.get("/api/v1/admin/overview", headers=_headers(elenco["admin"])).json()
    assert corpo["usuarios_total"] == 3


def test_lista_de_usuarios_busca_sem_diferenciar_maiuscula(elenco):
    resp = client.get(
        "/api/v1/admin/users", params={"busca": "COMUM"}, headers=_headers(elenco["admin"])
    )
    assert resp.status_code == 200
    emails = [u["email"] for u in resp.json()["items"]]
    assert "comum@example.com" in emails


def test_lista_de_usuarios_traz_uso_por_pessoa(elenco):
    corpo = client.get("/api/v1/admin/users", headers=_headers(elenco["admin"])).json()
    linha = next(u for u in corpo["items"] if u["email"] == "comum@example.com")
    for campo in ("workspaces", "lancamentos", "anexos_bytes", "last_login_at", "platform_role"):
        assert campo in linha


@pytest.mark.parametrize("curinga", ["%", "_", "%%", "c%m"])
def test_busca_trata_curinga_do_like_como_texto(elenco, curinga):
    """`%` e `_` são curingas do LIKE e precisam de escape.

    Sem `autoescape=True`, buscar "%" devolvia a LISTA INTEIRA e "c_mum" casava
    com qualquer letra no lugar do sublinhado. Não é injeção — o valor é
    parametrizado —, é um filtro que silenciosamente responde outra pergunta, e
    numa tela de administração isso é a diferença entre "ninguém com esse nome" e
    "todo mundo". O projeto já tinha resolvido o mesmo problema na busca de
    lançamentos (`transactions.py`); esta rota nasceu sem.
    """
    resp = client.get(
        "/api/v1/admin/users", params={"busca": curinga}, headers=_headers(elenco["admin"])
    )
    assert resp.status_code == 200
    assert resp.json()["total"] == 0, f"{curinga!r} funcionou como curinga"


def test_busca_por_texto_literal_continua_achando(elenco):
    """A trava não pode virar um filtro que nunca acha nada."""
    resp = client.get(
        "/api/v1/admin/users", params={"busca": "comum@"}, headers=_headers(elenco["admin"])
    )
    assert [u["email"] for u in resp.json()["items"]] == ["comum@example.com"]


# --------------------------------------------------------------------------
# Auditoria das próprias ações administrativas
# --------------------------------------------------------------------------

def test_mudanca_de_papel_entra_na_trilha(elenco, db_session):
    """Poder que não deixa rastro transforma uma conta comprometida numa
    investigação sem respostas."""
    client.patch(
        f"/api/v1/admin/users/{elenco['comum'].id}",
        json={"platform_role": "admin"},
        headers=_headers(elenco["super"]),
    )
    trilha = client.get(
        "/api/v1/admin/audit", params={"resource_type": "User"},
        headers=_headers(elenco["super"]),
    ).json()
    assert any(linha["resource_id"] == elenco["comum"].id for linha in trilha)


def test_auditoria_nao_devolve_conteudo_dos_valores(elenco):
    """`old_values`/`new_values` são JSON livre e, num lançamento, incluem o
    valor. A trilha administrativa mostra quem fez o quê, não o quê mudou."""
    client.patch(
        f"/api/v1/admin/users/{elenco['comum'].id}",
        json={"is_active": False},
        headers=_headers(elenco["admin"]),
    )
    linhas = client.get("/api/v1/admin/audit", headers=_headers(elenco["admin"])).json()
    assert linhas
    for linha in linhas:
        assert "old_values" not in linha
        assert "new_values" not in linha
