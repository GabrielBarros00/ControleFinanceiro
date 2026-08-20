"""Foto de perfil.

O que precisa ser verdade, e por quê:

- Os BYTES ficam no volume e a linha guarda só a chave — mesma decisão dos
  anexos (ADR 0007/0016): o dump do Postgres não cresce com imagem.
- O tipo DECLARADO não decide nada: o conteúdo é conferido por assinatura. Um
  arquivo que não é imagem não pode entrar e voltar a ser servido.
- **Quem pode ver a foto de quem** é a parte que mais importa. A rota de leitura
  responde 404 — e nunca 403 — para quem não tem relação com a pessoa, porque um
  403 confirmaria que a conta existe e transformaria a rota num oráculo de
  enumeração.
- O armazenamento dedupica por conteúdo: duas pessoas com a mesma imagem
  compartilham um arquivo, e remover a de uma não pode levar a da outra.
"""
import hashlib
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from app.core.config import settings
from app.core.jwt import create_access_token
from app.main import app
from app.models.user import PlatformRole, User
from app.models.workspace import WorkspaceMembership, WorkspaceRole

client = TestClient(app)

PNG = b"\x89PNG\r\n\x1a\n" + b"foto-de-perfil" * 8
OUTRO_PNG = b"\x89PNG\r\n\x1a\n" + b"outra-foto" * 8
JPEG = b"\xff\xd8\xff" + b"foto-jpeg" * 8
WEBP = b"RIFF" + b"\x00\x00\x00\x00" + b"WEBP" + b"conteudo" * 8
# Passa pela allowlist do `Content-Type` e NÃO é imagem: é o caso que os magic
# bytes existem para barrar.
HTML_DISFARCADO = b"<html><script>alert(1)</script></html>"


@pytest.fixture(autouse=True)
def _usa_o_banco_do_teste(override_get_session):
    """Sem isto, as rotas falam com o banco de DESENVOLVIMENTO.

    Não é detalhe de encanamento: a primeira execução destes testes estourou com
    `no such column: user.avatar_key` — o `create_all` da suíte já tinha a coluna
    nova, e o `dev.db` (que ainda não recebeu a migração) não. O erro apontava
    para o schema; a causa era o banco errado do outro lado.
    """
    yield


def _subir(headers, conteudo=PNG, tipo="image/png", nome="foto.png"):
    return client.put(
        "/api/v1/auth/me/avatar",
        files={"file": (nome, conteudo, tipo)},
        headers=headers,
    )


def test_upload_grava_no_volume_e_nao_no_banco(db_session: Session, setup_data):
    u1, headers = setup_data["u1"], setup_data["headers1"]

    resp = _subir(headers)
    assert resp.status_code == 200, resp.text
    corpo = resp.json()
    assert corpo["avatar_version"], "a resposta não trouxe o token de cache"

    db_session.expire_all()
    linha = db_session.get(User, u1.id)
    sha = hashlib.sha256(PNG).hexdigest()
    assert linha.avatar_key == f"avatars/{sha[:2]}/{sha}"
    assert linha.avatar_content_type == "image/png"
    # O token exposto é o começo do hash — é o que faz a URL mudar junto com a
    # foto e permite cachear `immutable`.
    assert corpo["avatar_version"] == sha[:8]

    caminho = Path(settings.ATTACHMENT_STORAGE_DIR) / linha.avatar_key
    assert caminho.is_file()
    assert caminho.read_bytes() == PNG


def test_me_devolve_a_versao_e_ela_muda_com_a_foto(setup_data):
    headers = setup_data["headers1"]
    assert client.get("/api/v1/auth/me", headers=headers).json()["avatar_version"] is None

    _subir(headers, PNG)
    primeira = client.get("/api/v1/auth/me", headers=headers).json()["avatar_version"]
    _subir(headers, OUTRO_PNG)
    segunda = client.get("/api/v1/auth/me", headers=headers).json()["avatar_version"]

    assert primeira and segunda and primeira != segunda, (
        "o token de cache não acompanhou a troca da foto — a URL não mudaria e o "
        "navegador continuaria mostrando a imagem antiga"
    )


@pytest.mark.parametrize(
    "conteudo,tipo,nome",
    [
        (b"%PDF-boletim", "application/pdf", "doc.pdf"),   # PDF é anexo, não rosto
        (b"MZ\x90\x00", "application/octet-stream", "x.exe"),
    ],
)
def test_tipo_fora_da_allowlist_e_recusado(setup_data, conteudo, tipo, nome):
    resp = _subir(setup_data["headers1"], conteudo, tipo, nome)
    assert resp.status_code == 400, resp.text
    assert "JPEG, PNG ou WebP" in resp.json()["error"]["message"]


def test_conteudo_que_nao_bate_com_o_tipo_e_recusado(setup_data):
    """Declarar `image/png` e enviar HTML: sem os magic bytes, o arquivo entra e
    a rota de leitura o serve de volta."""
    resp = _subir(setup_data["headers1"], HTML_DISFARCADO, "image/png", "x.png")
    assert resp.status_code == 400, resp.text
    assert "não corresponde" in resp.json()["error"]["message"]


def test_arquivo_grande_demais_e_recusado(setup_data):
    grande = b"\x89PNG\r\n\x1a\n" + b"x" * (1024 * 1024 + 1)
    resp = _subir(setup_data["headers1"], grande)
    assert resp.status_code == 400, resp.text
    assert "limite" in resp.json()["error"]["message"]


@pytest.mark.parametrize(
    "conteudo,tipo",
    [(PNG, "image/png"), (JPEG, "image/jpeg"), (WEBP, "image/webp")],
)
def test_os_tres_formatos_aceitos_entram(setup_data, conteudo, tipo):
    assert _subir(setup_data["headers1"], conteudo, tipo).status_code == 200


def test_leitura_devolve_os_bytes_com_o_tipo_certo(setup_data):
    u1, headers = setup_data["u1"], setup_data["headers1"]
    _subir(headers, JPEG, "image/jpeg", "foto.jpg")

    resp = client.get(f"/api/v1/auth/users/{u1.id}/avatar", headers=headers)
    assert resp.status_code == 200
    assert resp.content == JPEG
    assert resp.headers["content-type"] == "image/jpeg"
    # Sem `nosniff`, um conteúdo que enganasse a validação poderia ser
    # interpretado como outra coisa pelo navegador.
    assert resp.headers["x-content-type-options"] == "nosniff"
    assert "immutable" in resp.headers["cache-control"]
    # `private`: a resposta depende de quem pediu, então um cache compartilhado
    # não pode reusá-la para outra pessoa.
    assert "private" in resp.headers["cache-control"]


def test_estranho_leva_404_e_nao_403(setup_data):
    """u1 e u2 não dividem espaço nenhum.

    O código importa tanto quanto a recusa: 403 diria "esta conta existe e tem
    foto", e quem varresse os ids montaria a lista de usuários do site.
    """
    u1, headers2 = setup_data["u1"], setup_data["headers2"]
    _subir(setup_data["headers1"])

    resp = client.get(f"/api/v1/auth/users/{u1.id}/avatar", headers=headers2)
    assert resp.status_code == 404, resp.text


def test_quem_divide_o_espaco_ve_a_foto(db_session: Session, setup_data):
    u1, u2, ws1 = setup_data["u1"], setup_data["u2"], setup_data["ws1"]
    _subir(setup_data["headers1"])

    db_session.add(
        WorkspaceMembership(workspace_id=ws1.id, user_id=u2.id, role=WorkspaceRole.member)
    )
    db_session.commit()

    resp = client.get(f"/api/v1/auth/users/{u1.id}/avatar", headers=setup_data["headers2"])
    assert resp.status_code == 200
    assert resp.content == PNG


def test_admin_de_plataforma_ve_a_foto_de_qualquer_um(db_session: Session, setup_data):
    """A tela de Pessoas já lista todas as contas — esconder o rosto ali seria
    uma proteção que não protege nada."""
    _subir(setup_data["headers1"])

    admin = User(
        name="Admin", email="admin@example.com", password_hash="hash",
        platform_role=PlatformRole.admin,
    )
    db_session.add(admin)
    db_session.commit()
    db_session.refresh(admin)
    headers = {"Cookie": f"access_token={create_access_token(data={'sub': str(admin.id)})}"}

    resp = client.get(f"/api/v1/auth/users/{setup_data['u1'].id}/avatar", headers=headers)
    assert resp.status_code == 200


def test_conta_sem_foto_responde_404(setup_data):
    u1 = setup_data["u1"]
    resp = client.get(f"/api/v1/auth/users/{u1.id}/avatar", headers=setup_data["headers1"])
    assert resp.status_code == 404


def test_remover_apaga_o_arquivo(db_session: Session, setup_data):
    u1, headers = setup_data["u1"], setup_data["headers1"]
    _subir(headers)
    db_session.expire_all()
    caminho = Path(settings.ATTACHMENT_STORAGE_DIR) / db_session.get(User, u1.id).avatar_key
    assert caminho.is_file()

    resp = client.delete("/api/v1/auth/me/avatar", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["avatar_version"] is None
    assert not caminho.exists(), "o arquivo ficou órfão no volume"


def test_trocar_de_foto_libera_a_anterior(db_session: Session, setup_data):
    u1, headers = setup_data["u1"], setup_data["headers1"]
    _subir(headers, PNG)
    db_session.expire_all()
    antiga = Path(settings.ATTACHMENT_STORAGE_DIR) / db_session.get(User, u1.id).avatar_key

    _subir(headers, OUTRO_PNG)
    db_session.expire_all()
    nova = Path(settings.ATTACHMENT_STORAGE_DIR) / db_session.get(User, u1.id).avatar_key

    assert nova.is_file()
    assert not antiga.exists(), "a foto anterior continuou ocupando o volume"


def test_dedup_nao_leva_a_foto_de_quem_ainda_usa(db_session: Session, setup_data):
    """Duas contas com a MESMA imagem compartilham um arquivo. Trocar a de uma
    não pode deixar a outra sem conteúdo."""
    u2, headers1, headers2 = setup_data["u2"], setup_data["headers1"], setup_data["headers2"]
    _subir(headers1, PNG)
    _subir(headers2, PNG)

    db_session.expire_all()
    compartilhado = Path(settings.ATTACHMENT_STORAGE_DIR) / db_session.get(User, u2.id).avatar_key

    client.delete("/api/v1/auth/me/avatar", headers=headers1)
    assert compartilhado.is_file(), "a foto da outra conta foi levada junto"

    resp = client.get(f"/api/v1/auth/users/{u2.id}/avatar", headers=headers2)
    assert resp.status_code == 200
    assert resp.content == PNG

    # E quando a última referência sai, aí sim o objeto some.
    client.delete("/api/v1/auth/me/avatar", headers=headers2)
    assert not compartilhado.exists()


def test_lista_de_membros_traz_a_versao(db_session: Session, setup_data):
    """Sem isto a foto só apareceria para o próprio dono — a lista de membros e
    os avatares da divisão de despesa leem daqui."""
    u1, u2, ws1 = setup_data["u1"], setup_data["u2"], setup_data["ws1"]
    _subir(setup_data["headers1"])
    db_session.add(
        WorkspaceMembership(workspace_id=ws1.id, user_id=u2.id, role=WorkspaceRole.member)
    )
    db_session.commit()

    resp = client.get(f"/api/v1/workspaces/{ws1.id}/members", headers=setup_data["headers2"])
    assert resp.status_code == 200, resp.text
    por_id = {m["user_id"]: m for m in resp.json()}
    assert por_id[u1.id]["avatar_version"] == hashlib.sha256(PNG).hexdigest()[:8]
    assert por_id[u2.id]["avatar_version"] is None


def test_upload_exige_sessao():
    assert _subir({}).status_code == 401
