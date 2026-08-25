"""Área administrativa: guardas de papel e as travas que impedem trancar o site.

O que está sendo provado aqui não é "a rota responde 200" — é que ninguém sem
papel chega perto dela, e que nenhuma sequência de PATCHes plausível deixa o
sistema sem quem o administre.
"""
import smtplib

import pytest
from fastapi.testclient import TestClient
from structlog.testing import capture_logs

from app.core.jwt import create_access_token
from app.main import app
from app.models.user import PlatformRole, User
from app.services import app_settings, smtp_transport

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


def test_sobrescrito_segue_o_valor_que_esta_valendo(elenco, db_session, monkeypatch):
    """"Existe linha no banco" e "o banco é quem manda" não são a mesma pergunta.

    `get` descarta a linha que não passa na validação e recua para o ambiente —
    é o que acontece ao baixar `IMPORT_MAX_ROWS` abaixo de um número gravado
    antes. Enquanto `sobrescrito` respondia só "existe linha", a tela mostrava o
    valor do `.env` com a marca de "gravado aqui", e o operador ia procurar a
    causa no lugar errado.
    """
    from app.core.config import settings as cfg

    def _chaves():
        corpo = client.get("/api/v1/admin/settings", headers=_headers(elenco["admin"])).json()
        return corpo, {c["nome"]: c for c in corpo["chaves"]}

    client.put(
        "/api/v1/admin/settings",
        json={"valores": {"import_max_rows": 4000}},
        headers=_headers(elenco["admin"]),
    )
    corpo, por_nome = _chaves()
    assert corpo["valores"]["import_max_rows"] == 4000
    assert por_nome["import_max_rows"]["sobrescrito"] is True

    # O operador aperta o teto do PROCESSO abaixo do que estava gravado.
    monkeypatch.setattr(cfg, "IMPORT_MAX_ROWS", 1000)
    app_settings.invalidate_cache()

    corpo, por_nome = _chaves()
    assert corpo["valores"]["import_max_rows"] == 1000, "a linha inválida continuou valendo"
    assert por_nome["import_max_rows"]["sobrescrito"] is False, (
        "a tela creditou ao banco um valor que veio do ambiente"
    )


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


# --------------------------------------------------------------------------
# Teste de e-mail: o botão existe para DIZER o que está errado
# --------------------------------------------------------------------------

def test_teste_de_email_diz_por_qual_porta_o_envio_saiu(elenco, monkeypatch):
    """A resposta carrega a rota descoberta, não só "enviado".

    Sem isso, o operador que configurou a porta 587 e recebeu o e-mail por 2587
    continuaria sem saber que a porta do `.env` está bloqueada na saída — a
    informação existe no servidor e não chegava a quem opera.
    """
    monkeypatch.setattr("app.core.config.settings.SMTP_HOST", "smtp.exemplo.com")
    monkeypatch.setattr("app.core.config.settings.SMTP_PORT", 587)
    monkeypatch.setattr(
        "app.services.email_service.EmailService.send",
        lambda *a, **kw: smtp_transport.Endpoint("smtp.exemplo.com", 2587),
    )

    resp = client.post(
        "/api/v1/admin/settings/test-email",
        json={"para": "eu@example.com"},
        headers=_headers(elenco["admin"]),
    )
    assert resp.status_code == 200
    corpo = resp.json()
    assert corpo["enviado"] is True
    assert "2587" in corpo["rota"]


def _dispara_o_teste_de_email(elenco):
    return client.post(
        "/api/v1/admin/settings/test-email",
        json={"para": "eu@example.com"},
        headers=_headers(elenco["admin"]),
    )


def test_teste_de_email_manda_o_diagnostico_para_o_log_e_nao_para_a_tela(elenco, monkeypatch):
    """O "2587" tem de existir — no LOG. Na resposta HTTP, não.

    As duas metades são o teste: sem a primeira, "não expor" vira "não
    diagnosticar" e o botão deixa de servir para o que foi feito; sem a segunda,
    o texto volta à tela na primeira refatoração distraída.
    """
    monkeypatch.setattr("app.core.config.settings.SMTP_HOST", "smtp.exemplo.com")
    monkeypatch.setattr("app.services.smtp_transport._resolve", lambda host: True)
    monkeypatch.setattr(
        "app.services.smtp_transport._alcancavel", lambda host, porta, timeout: False
    )
    smtp_transport.esquece_rota()

    with capture_logs() as registros:
        resp = _dispara_o_teste_de_email(elenco)
    smtp_transport.esquece_rota()

    corpo = resp.json()
    assert corpo["enviado"] is False and corpo["configurado"] is True

    falhou = [r for r in registros if r["event"] == "teste_de_email_falhou"]
    assert falhou, f"a falha não foi logada; eventos: {[r['event'] for r in registros]}"
    assert "2587" in falhou[0]["erro"], falhou[0]

    assert "2587" not in corpo["detalhe"], corpo["detalhe"]
    assert "teste_de_email_falhou" in corpo["detalhe"], (
        "a tela não diz ONDE procurar — mandar ao log sem a chave do evento é "
        "mandar procurar agulha no palheiro"
    )


def test_teste_de_email_nao_devolve_a_recusa_literal_do_servidor(elenco, monkeypatch):
    """Nem o "535" do servidor sai na resposta, por mais útil que ele seja.

    Este é o caso que mais dói na decisão de não expor — é a falha nº 1 em
    produção e a resposta do servidor diz exatamente o que corrigir. Ainda
    assim: o texto vem do servidor remoto, que é justamente o que está sendo
    diagnosticado, e quem escolhe o que há nele não somos nós.
    """
    monkeypatch.setattr("app.core.config.settings.SMTP_HOST", "smtp.exemplo.com")

    def recusa(*a, **kw):
        raise smtp_transport.RecusadoPeloServidor(
            "o servidor de e-mail recusou: (535, b'5.7.8 Username and Password not accepted')"
        )

    monkeypatch.setattr("app.services.email_service.EmailService.send", recusa)

    with capture_logs() as registros:
        resp = _dispara_o_teste_de_email(elenco)

    corpo = resp.json()
    assert corpo["enviado"] is False and corpo["configurado"] is True
    assert "535" not in corpo["detalhe"], corpo["detalhe"]
    assert "Password not accepted" not in corpo["detalhe"], corpo["detalhe"]

    # E, no log, inteiro — incluindo o "535", que é o que resolve o problema.
    falhou = [r for r in registros if r["event"] == "teste_de_email_falhou"]
    assert falhou and "535" in falhou[0]["erro"], registros

    # A tela não mostra o motivo, mas AFIRMA uma categoria — e afirmar errado é
    # pior que não afirmar: mandaria caçar bug quem só precisa trocar a senha.
    #
    # A garantia é de dois elos, e nenhum deles sozinho: aqui, que um
    # `ErroDeEnvio` nunca é reportado como defeito interno; e em
    # `test_credencial_recusada_nao_e_repetida_em_outras_portas`, que `entrega()`
    # de fato entrega a recusa do servidor como `ErroDeEnvio` (é lá que o
    # `SMTPAuthenticationError` real aparece — este teste injeta a exceção já
    # envelopada, e não provaria o envelope).
    assert "erro interno" not in corpo["detalhe"], corpo["detalhe"]
    assert "SMTP" in corpo["detalhe"] or "e-mail de teste" in corpo["detalhe"], corpo


def test_teste_de_email_nao_ecoa_defeito_interno_na_tela(elenco, monkeypatch):
    """Defeito NOSSO não vira texto na tela — vira uma linha no log.

    O preço de mostrar `str(exc)` era ecoar também o `str()` de qualquer exceção
    que passasse por ali: caminho de arquivo do container, nome de interno,
    valor de configuração na mensagem. O alerta `py/stack-trace-exposure` do
    CodeQL é exatamente este caminho.
    """
    monkeypatch.setattr("app.core.config.settings.SMTP_HOST", "smtp.exemplo.com")

    def quebra(*a, **kw):
        raise RuntimeError("/srv/app/app/services/segredo.py: SMTP_PASSWORD=hunter2")

    monkeypatch.setattr("app.services.email_service.EmailService.send", quebra)

    resp = _dispara_o_teste_de_email(elenco)

    assert resp.status_code == 200, "o botão responde, não estoura um 500"
    corpo = resp.json()
    assert corpo["enviado"] is False
    detalhe = corpo["detalhe"]
    assert "hunter2" not in detalhe and "/srv/app" not in detalhe, detalhe
    # Nem o nome da classe: `RuntimeError` já é informação sobre o interno, e a
    # regra aqui é "o `detalhe` é uma constante do arquivo", sem exceções.
    assert "RuntimeError" not in detalhe, detalhe
    # Mas a CATEGORIA fica: sem ela o operador vai mexer em host, porta e senha
    # atrás de um defeito que não está no SMTP.
    assert "erro interno" in detalhe, detalhe


def test_nenhuma_falha_do_teste_de_email_devolve_texto_de_excecao(elenco, monkeypatch):
    """Varredura: o `detalhe` é sempre uma das constantes, para QUALQUER exceção.

    Os testes acima cobrem um caminho cada. Este cobre o denominador — inclusive
    as exceções que ninguém pensou em listar —, porque a regressão que interessa
    não é "o caso X voltou a vazar", é "alguém acrescentou um `except` novo".
    """
    monkeypatch.setattr("app.core.config.settings.SMTP_HOST", "smtp.exemplo.com")

    marca = "CANARIO-a1b2c3-nao-pode-sair-na-resposta"
    excecoes = [
        smtp_transport.SemRota(marca),
        smtp_transport.EntregaIncerta(marca),
        smtp_transport.RecusadoPeloServidor(marca),
        smtp_transport.ErroDeEnvio(marca),
        RuntimeError(marca),
        ValueError(marca),
        OSError(marca),
        smtplib.SMTPAuthenticationError(535, marca.encode()),
        KeyError(marca),
        TypeError(marca),
    ]

    for exc in excecoes:
        def estoura(*a, __exc=exc, **kw):
            raise __exc

        monkeypatch.setattr("app.services.email_service.EmailService.send", estoura)
        corpo = _dispara_o_teste_de_email(elenco).json()

        assert corpo["enviado"] is False, exc
        assert marca not in corpo["detalhe"], (
            f"{type(exc).__name__} vazou o texto da exceção na resposta: {corpo['detalhe']}"
        )
        assert type(exc).__name__ not in corpo["detalhe"], (
            f"{type(exc).__name__} vazou o nome da classe na resposta: {corpo['detalhe']}"
        )
