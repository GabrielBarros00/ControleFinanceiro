"""O administrador do site NÃO enxerga a vida financeira de ninguém.

Este arquivo é o que sustenta a decisão do ADR 0026. A área administrativa
nasceu com poder real — desativar conta, mudar papel, ler a trilha inteira — e a
tentação natural, na próxima funcionalidade, é "já que o admin vê tudo mesmo,
deixa ele abrir o workspace para dar suporte". A partir daí os ADRs 0018
(privacidade por membro) e 0021 (recurso pessoal sem workspace) viram letra
morta, e o programa de seis ondas que os construiu foi desfeito por conveniência.

A defesa é mecânica: varre a RESPOSTA INTEIRA de cada rota administrativa
procurando os valores que só existem no lançamento de outra pessoa. Um `SUM`
sobre coluna de dinheiro que apareça em `/admin/overview` reprova aqui, mesmo
que quem o escreveu ache que é só um total inofensivo.
"""
from datetime import datetime, UTC
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.core.jwt import create_access_token
from app.main import app
from app.models.category import Category
from app.models.transaction import Transaction
from app.models.user import PlatformRole, User
from app.models.workspace import Workspace, WorkspaceMembership, WorkspaceRole

client = TestClient(app)

# Valores propositalmente esquisitos: se qualquer um deles aparecer em qualquer
# canto de uma resposta administrativa, é vazamento — e nenhum deles apareceria
# por acaso numa contagem ou num tamanho em bytes.
VALOR_SECRETO = Decimal("13337.71")
TITULO_SECRETO = "psicoterapia-quinzenal"
CATEGORIA_SECRETA = "Saude-Mental-Confidencial"


@pytest.fixture(name="cenario")
def cenario_fixture(db_session, override_get_session):
    """Uma pessoa comum com um lançamento delicado, e um admin que não a conhece."""
    vitima = User(name="Vitima", email="vitima@example.com", password_hash="hash")
    admin = User(
        name="Admin", email="admin@example.com", password_hash="hash",
        platform_role=PlatformRole.superadmin,
    )
    db_session.add_all([vitima, admin])
    db_session.commit()
    db_session.refresh(vitima)
    db_session.refresh(admin)

    ws = Workspace(name="Casa da Vitima", created_by_user_id=vitima.id)
    db_session.add(ws)
    db_session.commit()
    db_session.refresh(ws)
    db_session.add(WorkspaceMembership(
        workspace_id=ws.id, user_id=vitima.id, role=WorkspaceRole.owner
    ))

    categoria = Category(workspace_id=ws.id, name=CATEGORIA_SECRETA)
    db_session.add(categoria)
    db_session.commit()
    db_session.refresh(categoria)

    db_session.add(Transaction(
        workspace_id=ws.id,
        title=TITULO_SECRETO,
        total_amount=VALOR_SECRETO,
        transaction_date=datetime.now(UTC),
        created_by_user_id=vitima.id,
        category_id=categoria.id,
        currency="BRL",
    ))
    db_session.commit()

    return {
        "vitima": vitima,
        "admin": admin,
        "ws": ws,
        "headers_admin": {
            "Cookie": f"access_token={create_access_token(data={'sub': str(admin.id)})}"
        },
    }


ROTAS_ADMINISTRATIVAS = [
    "/api/v1/admin/overview",
    "/api/v1/admin/users",
    "/api/v1/admin/health",
    "/api/v1/admin/audit",
    "/api/v1/admin/settings",
    "/api/v1/admin/registration-invites",
]


@pytest.mark.parametrize("rota", ROTAS_ADMINISTRATIVAS)
def test_nenhuma_rota_administrativa_devolve_dado_financeiro(cenario, rota):
    resp = client.get(rota, headers=cenario["headers_admin"])
    assert resp.status_code == 200
    corpo = resp.text

    assert TITULO_SECRETO not in corpo, f"{rota} vazou o TÍTULO de um lançamento"
    assert CATEGORIA_SECRETA not in corpo, f"{rota} vazou a CATEGORIA de um lançamento"
    # O valor em qualquer forma plausível de serialização.
    for forma in ("13337.71", "13337,71", "1333771"):
        assert forma not in corpo, f"{rota} vazou o VALOR de um lançamento ({forma})"


def test_admin_conta_lancamentos_mas_nao_os_soma(cenario):
    """A fronteira exata deste projeto: `COUNT(*)` é operação, `SUM(amount)` é
    intimidade. Um administrador precisa saber que existem 400 lançamentos para
    dimensionar o banco; nunca precisou saber que somam R$ 38.000."""
    corpo = client.get("/api/v1/admin/overview", headers=cenario["headers_admin"]).json()
    assert corpo["lancamentos"] == 1
    assert not any("total" in chave and "amount" in chave for chave in corpo)
    assert "valor" not in corpo
    assert "saldo" not in corpo


def test_superadmin_nao_entra_no_workspace_alheio(cenario):
    """`access_policy` não consulta `platform_role`, e é isso que mantém 0018 e
    0021 de pé. Ser dono do servidor não é ser membro da casa."""
    ws_id = cenario["ws"].id
    # A barra final de `transactions/` é a forma REGISTRADA da rota. Sem ela o
    # Starlette responde 307 e o TestClient segue o salto sem levar o cookie —
    # o 401 resultante daria este teste por verde sem a política ter sido
    # consultada uma única vez. (É a mesma armadilha que o `_colecao` fecha nos
    # roteadores de coleção.)
    for rota in (
        f"/api/v1/workspaces/{ws_id}/transactions/",
        f"/api/v1/workspaces/{ws_id}/categories",
        f"/api/v1/workspaces/{ws_id}/audit",
    ):
        resp = client.get(rota, headers=cenario["headers_admin"])
        assert resp.status_code in (403, 404), f"{rota} deixou o superadmin entrar"


def test_superadmin_nao_ve_renda_nem_cartao_alheios(cenario):
    """As rotas `/me/...` são pessoais por construção (ADR 0021): elas respondem
    sobre QUEM PERGUNTA. O risco não é o admin forçar a entrada — é a rota um dia
    aceitar um `?user_id=` "só para o admin"."""
    for rota in ("/api/v1/me/income", "/api/v1/me/credit-cards", "/api/v1/me/overview"):
        resp = client.get(
            rota, params={"user_id": cenario["vitima"].id}, headers=cenario["headers_admin"]
        )
        assert resp.status_code == 200
        assert TITULO_SECRETO not in resp.text
        assert "13337.71" not in resp.text


def test_lista_de_usuarios_expoe_uso_mas_nao_conteudo(cenario):
    """O uso de cada pessoa é metadado legítimo de operação; o que ela gastou não."""
    corpo = client.get("/api/v1/admin/users", headers=cenario["headers_admin"]).json()
    linha = next(u for u in corpo["items"] if u["email"] == "vitima@example.com")

    assert linha["lancamentos"] == 1          # quantos: sim
    assert linha["anexos_bytes"] == 0         # quanto ocupa: sim
    assert "total_gasto" not in linha         # quanto gastou: nunca
    assert "renda" not in linha
    assert "saldo" not in linha
